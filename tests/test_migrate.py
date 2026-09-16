"""Tests for the check-sheet conversion service (pure logic, no API)."""

import pytest

from qualytics.services.migrate import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    convert_sheet,
    load_sheet,
    normalize_comparison,
    parse_duration_ms,
    parse_sources,
    sheet_check_uid,
    summarize_sheet,
    timezone_suspect,
    to_checks,
)


def _row(num: int = 2, **cells) -> dict:
    row = {"_row": num}
    row.update(cells)
    return row


def _errors(plan):
    return [i.message for i in plan.errors]


def _warnings(plan):
    return [i.message for i in plan.warnings]


# ── Loading ───────────────────────────────────────────────────────────────


class TestLoadSheet:
    def test_csv_headers_normalized_and_rows_numbered(self, tmp_path):
        path = tmp_path / "sheet.csv"
        path.write_text(
            "Check ID,Rule Type,Container,Fields\n"
            "100,notNull,orders,order_id\n"
            "\n"
            "101,unique,orders,order_id\n"
        )
        rows = load_sheet(str(path))
        assert [r["_row"] for r in rows] == [2, 4]
        assert rows[0]["check_id"] == "100"
        assert rows[0]["rule_type"] == "notNull"
        assert rows[0]["fields"] == "order_id"

    def test_xlsx_round_trip(self, tmp_path):
        from openpyxl import Workbook

        path = tmp_path / "sheet.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["check_id", "rule_type", "container", "value"])
        sheet.append([100, "freshness", "orders", 3600000])
        sheet.append([None, None, None, None])
        workbook.save(path)

        rows = load_sheet(str(path))
        assert len(rows) == 1
        assert rows[0]["check_id"] == 100
        assert rows[0]["value"] == 3600000

    def test_metadata_headers_keep_key_verbatim(self, tmp_path):
        path = tmp_path / "sheet.csv"
        path.write_text(
            "check_id,rule_type,container,fields,Metadata: Domain Owner\n"
            "100,notNull,orders,order_id,Treasury Ops\n"
        )
        rows = load_sheet(str(path))
        assert rows[0]["metadata:Domain Owner"] == "Treasury Ops"

    def test_unsupported_extension(self, tmp_path):
        path = tmp_path / "sheet.parquet"
        path.write_text("nope")
        with pytest.raises(ValueError, match="Unsupported sheet format"):
            load_sheet(str(path))


# ── Value parsing ─────────────────────────────────────────────────────────


class TestParsers:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (3_600_000, 3_600_000),
            ("1500", 1500),
            ("36h", 129_600_000),
            ("7d", 604_800_000),
            ("90m", 5_400_000),
            ("45 s", 45_000),
            ("1.5h", 5_400_000),
            ("", None),
            ("soon", None),
            (0, None),
            (True, None),
        ],
    )
    def test_parse_duration_ms(self, value, expected):
        assert parse_duration_ms(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("eq", "eq"),
            ("=", "eq"),
            (">=", "gte"),
            ("Less Than", "lt"),
            ("absolute value", "Absolute Value"),
            ("sideways", None),
            (None, None),
        ],
    )
    def test_normalize_comparison(self, value, expected):
        assert normalize_comparison(value) == expected

    def test_parse_sources_pairs(self):
        assert parse_sources("orders=o; customers") == [
            {"container": "orders", "alias": "o"},
            {"container": "customers", "alias": "customers"},
        ]

    def test_parse_sources_json(self):
        value = '[{"container": "orders", "alias": "o", "where_clause": "x > 1"}]'
        assert parse_sources(value) == [
            {"container": "orders", "alias": "o", "where_clause": "x > 1"}
        ]

    def test_parse_sources_invalid(self):
        assert parse_sources("[not json") is None

    def test_timezone_suspect(self):
        assert timezone_suspect("WHERE d >= CURRENT_DATE")
        assert timezone_suspect("select NOW() as t")
        assert not timezone_suspect(
            "WHERE d >= from_utc_timestamp(current_timestamp, 'America/New_York')"
        )
        assert not timezone_suspect("WHERE d >= '2026-01-01'")
        assert not timezone_suspect(None)


# ── Check rows ────────────────────────────────────────────────────────────


class TestConvertChecks:
    def test_minimal_not_null(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="100",
                    rule_type="notNull",
                    container="orders",
                    fields="order_id",
                )
            ]
        )
        assert not plan.issues
        (item,) = plan.checks
        check = item.check
        assert check["rule_type"] == "notNull"
        assert check["container"] == "orders"
        assert check["fields"] == ["order_id"]
        assert check["status"] == "Draft"
        assert check["coverage"] == 1.0
        meta = check["additional_metadata"]
        # The client key IS the upsert identity — no internal UID in metadata.
        assert "_qualytics_check_uid" not in meta
        assert meta["legacy_check_id"] == "100"

    def test_freshness_contract_and_duration(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="550",
                    rule_type="freshness",
                    container="orders",
                    value="36h",
                    filter="d > 1",
                    coverage="0.5",
                    fields="ignored_anyway",
                )
            ]
        )
        (item,) = plan.checks
        check = item.check
        assert check["properties"] == {"value": 129_600_000}
        assert check["fields"] == []
        assert check["filter"] is None
        assert check["coverage"] is None
        assert any("does not accept a filter" in m for m in _warnings(plan))

    def test_exists_in_reference_columns(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="326",
                    rule_type="existsIn",
                    container="child",
                    fields="fk_id",
                    ref_container="parent",
                    ref_field="id",
                    ref_datastore="warehouse",
                    ref_filter="active = true",
                )
            ]
        )
        assert not plan.errors
        (item,) = plan.checks
        assert item.check["properties"] == {
            "ref_container_name": "parent",
            "field_name": "id",
            "ref_datastore_name": "warehouse",
            "ref_filter": "active = true",
        }

    def test_ref_datastore_numeric_becomes_id(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="1",
                    rule_type="existsIn",
                    container="child",
                    fields="fk",
                    ref_container="parent",
                    ref_field="id",
                    ref_datastore="42",
                )
            ]
        )
        assert plan.checks[0].check["properties"]["ref_datastore_id"] == 42

    def test_aggregation_comparison(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="211",
                    rule_type="aggregationComparison",
                    container="efront_positions",
                    expression="count(*)",
                    comparison=">=",
                    ref_expression="count(*)",
                    ref_container="secmaster_map",
                    coverage="0.9",
                )
            ]
        )
        assert not plan.errors
        (item,) = plan.checks
        check = item.check
        assert check["properties"] == {
            "expression": "count(*)",
            "comparison": "gte",
            "ref_expression": "count(*)",
            "ref_container_name": "secmaster_map",
        }
        # aggregationComparison does not support coverage
        assert check["coverage"] is None

    def test_missing_requirements_reported_per_rule(self):
        plan = convert_sheet(
            [
                _row(2, check_id="a", rule_type="freshness", container="t"),
                _row(
                    3,
                    check_id="b",
                    rule_type="aggregationComparison",
                    container="t",
                    expression="count(*)",
                ),
                _row(4, check_id="c", rule_type="existsIn", container="t", fields="x"),
            ]
        )
        assert not plan.checks
        messages = _errors(plan)
        assert any("freshness requires column(s): value" in m for m in messages)
        assert any(
            "aggregationComparison requires column(s): comparison, ref_container, "
            "ref_expression" in m
            for m in messages
        )
        assert any(
            "existsIn requires column(s): ref_container, ref_field" in m
            for m in messages
        )

    def test_between_narrows_one_sided(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="x",
                    rule_type="between",
                    container="t",
                    fields="amount",
                    min="10",
                )
            ]
        )
        (item,) = plan.checks
        assert item.check["rule_type"] == "greaterThan"
        assert item.check["properties"] == {"value": 10, "inclusive": True}

    def test_between_both_bounds(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="x",
                    rule_type="between",
                    container="t",
                    fields="amount",
                    min="0",
                    max="1.5",
                    inclusive_max="false",
                )
            ]
        )
        (item,) = plan.checks
        assert item.check["properties"] == {
            "min": 0,
            "inclusive_min": True,
            "max": 1.5,
            "inclusive_max": False,
        }

    def test_between_requires_a_bound(self):
        plan = convert_sheet(
            [_row(check_id="x", rule_type="between", container="t", fields="amount")]
        )
        assert any("min or max" in m for m in _errors(plan))

    def test_equal_to_numeric_value(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="770",
                    rule_type="equalTo",
                    container="recon",
                    fields="delta",
                    value="0",
                )
            ]
        )
        (item,) = plan.checks
        assert item.check["properties"] == {"value": 0, "inclusive": True}

    def test_equal_to_rejects_non_numeric(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="770",
                    rule_type="equalTo",
                    container="recon",
                    fields="delta",
                    value="zero",
                )
            ]
        )
        assert any("not numeric" in m for m in _errors(plan))

    def test_single_field_contract_enforced(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="p",
                    rule_type="matchesPattern",
                    container="t",
                    fields="a, b",
                    pattern="^x$",
                )
            ]
        )
        assert any("takes a single field" in m for m in _errors(plan))

    def test_duplicate_check_id(self):
        rows = [
            _row(2, check_id="100", rule_type="notNull", container="t", fields="a"),
            _row(3, check_id="100", rule_type="unique", container="t", fields="a"),
        ]
        plan = convert_sheet(rows)
        assert len(plan.checks) == 1
        assert any("duplicate check_id '100'" in m for m in _errors(plan))

    def test_properties_json_merge_and_conflict(self):
        ok = convert_sheet(
            [
                _row(
                    check_id="1",
                    rule_type="equalTo",
                    container="t",
                    fields="a",
                    value="5",
                    properties_json='{"numeric_comparator": {"epsilon": 0.01}}',
                )
            ]
        )
        assert ok.checks[0].check["properties"]["numeric_comparator"] == {
            "epsilon": 0.01
        }

        conflict = convert_sheet(
            [
                _row(
                    check_id="1",
                    rule_type="equalTo",
                    container="t",
                    fields="a",
                    value="5",
                    properties_json='{"value": 6}',
                )
            ]
        )
        assert any("conflicts with" in m for m in _errors(conflict))

        invalid = convert_sheet(
            [
                _row(
                    check_id="1",
                    rule_type="notNull",
                    container="t",
                    fields="a",
                    properties_json="{nope",
                )
            ]
        )
        assert any("not valid JSON" in m for m in _errors(invalid))

    def test_status_override_and_validation(self):
        plan = convert_sheet(
            [
                _row(
                    2,
                    check_id="a",
                    rule_type="notNull",
                    container="t",
                    fields="x",
                    status="active",
                ),
                _row(
                    3,
                    check_id="b",
                    rule_type="notNull",
                    container="t",
                    fields="x",
                    status="Retired",
                ),
            ]
        )
        assert plan.checks[0].check["status"] == "Active"
        assert any("must be Active or Draft" in m for m in _errors(plan))

    def test_extra_tags_appended_once(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="a",
                    rule_type="notNull",
                    container="t",
                    fields="x",
                    tags="UAT testing, finance",
                )
            ],
            extra_tags=["UAT testing", "wafra-week1"],
        )
        assert plan.checks[0].check["tags"] == [
            "UAT testing",
            "finance",
            "wafra-week1",
        ]

    def test_unknown_rule_passes_with_warning(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="a",
                    rule_type="volumetricShift",
                    container="t",
                    properties_json='{"window_size": 7}',
                )
            ]
        )
        assert len(plan.checks) == 1
        assert any("not in the sheet crosswalk" in m for m in _warnings(plan))

    def test_timezone_lint_on_expression(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="a",
                    rule_type="satisfiesExpression",
                    container="t",
                    expression="d >= CURRENT_DATE - 1",
                )
            ]
        )
        assert any("timezone" in m for m in _warnings(plan))

    def test_metadata_columns_stamped_verbatim_and_sparse(self):
        rows = [
            _row(
                2,
                check_id="a",
                rule_type="notNull",
                container="t",
                fields="x",
                **{"metadata:Business Domain": "Treasury", "metadata:tier": 1},
            ),
            _row(
                3,
                check_id="b",
                rule_type="unique",
                container="t",
                fields="x",
                **{"metadata:Business Domain": None, "metadata:tier": 2},
            ),
        ]
        plan = convert_sheet(rows)
        assert not plan.issues
        first, second = (item.check["additional_metadata"] for item in plan.checks)
        assert first["Business Domain"] == "Treasury"
        assert first["tier"] == 1
        # Empty cell: the key does not apply to that row.
        assert "Business Domain" not in second
        assert second["tier"] == 2

    def test_reserved_metadata_key_rejected(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="a",
                    rule_type="notNull",
                    container="t",
                    fields="x",
                    **{"metadata:legacy_check_id": "override"},
                )
            ]
        )
        assert not plan.checks
        assert any("is reserved" in m for m in _errors(plan))

    def test_unknown_columns_warn_once_and_are_ignored(self):
        rows = [
            _row(
                2,
                check_id="a",
                rule_type="notNull",
                container="t",
                fields="x",
                severity="High",
                approach="Direct notNull check",
            ),
            _row(
                3,
                check_id="b",
                rule_type="unique",
                container="t",
                fields="x",
                severity="Low",
            ),
        ]
        plan = convert_sheet(rows)
        warnings = [i for i in plan.warnings if "not recognized" in i.message]
        assert len(warnings) == 1
        assert "approach, severity" in warnings[0].message
        assert "metadata:" in warnings[0].message
        for item in plan.checks:
            meta = item.check["additional_metadata"]
            assert "severity" not in meta and "sheet_severity" not in meta

    def test_container_rows_carry_metadata(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="ct1",
                    kind="computed_table",
                    container="calc",
                    query="SELECT 1",
                    **{"metadata:Source System": "eFront"},
                )
            ]
        )
        (spec,) = plan.containers
        assert spec.spec["additional_metadata"] == {
            "legacy_check_id": "ct1",
            "Source System": "eFront",
        }

    def test_missing_check_id_or_container(self):
        plan = convert_sheet(
            [
                _row(2, rule_type="notNull", container="t", fields="x"),
                _row(3, check_id="b", rule_type="notNull", fields="x"),
            ]
        )
        messages = _errors(plan)
        assert any("check_id is required" in m for m in messages)
        assert any("container is required" in m for m in messages)


# ── Container rows ────────────────────────────────────────────────────────


class TestConvertContainers:
    def test_computed_table_row(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="ct1",
                    kind="computed_table",
                    container="recon_unpivot",
                    description="Reconciliation metrics",
                    query="SELECT metric, delta FROM x",
                )
            ]
        )
        assert not plan.errors
        (spec,) = plan.containers
        assert spec.kind == "computed_table"
        assert spec.name == "recon_unpivot"
        assert spec.spec == {
            "container_type": "computed_table",
            "name": "recon_unpivot",
            "query": "SELECT metric, delta FROM x",
            "description": "Reconciliation metrics",
            "additional_metadata": {"legacy_check_id": "ct1"},
        }

    def test_computed_join_row(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="cj1",
                    kind="computed join",
                    container="orders_customers",
                    query="SELECT o.id FROM o JOIN c ON o.cid = c.id",
                    sources="orders=o; customers=c",
                )
            ]
        )
        assert not plan.errors
        (spec,) = plan.containers
        assert spec.spec["sources"] == [
            {"container": "orders", "alias": "o"},
            {"container": "customers", "alias": "c"},
        ]

    def test_join_needs_two_sources(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="cj1",
                    kind="computed_join",
                    container="j",
                    query="SELECT 1",
                    sources="orders",
                )
            ]
        )
        assert any("at least two" in m for m in _errors(plan))

    def test_join_cannot_reference_later_table(self):
        plan = convert_sheet(
            [
                _row(
                    2,
                    check_id="cj1",
                    kind="computed_join",
                    container="j",
                    query="SELECT 1",
                    sources="base_table=b; other=o",
                ),
                _row(
                    3,
                    check_id="ct1",
                    kind="computed_table",
                    container="base_table",
                    query="SELECT 1",
                ),
            ]
        )
        assert any("declared later in the sheet" in m for m in _errors(plan))

    def test_duplicate_container_names(self):
        plan = convert_sheet(
            [
                _row(2, check_id="a", kind="computed_table", container="x", query="q"),
                _row(3, check_id="b", kind="computed_table", container="x", query="q"),
            ]
        )
        assert any("declared more than once" in m for m in _errors(plan))

    def test_missing_query(self):
        plan = convert_sheet([_row(check_id="a", kind="computed_table", container="x")])
        assert any("query is required" in m for m in _errors(plan))

    def test_unknown_kind(self):
        plan = convert_sheet([_row(check_id="a", kind="materialized_view")])
        assert any("not recognized" in m for m in _errors(plan))

    def test_timezone_lint_on_query(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="a",
                    kind="computed_table",
                    container="x",
                    query="SELECT * FROM t WHERE d = CURRENT_DATE",
                )
            ]
        )
        assert any("timezone" in m for m in _warnings(plan))


# ── Reporting ─────────────────────────────────────────────────────────────


class TestSummary:
    def test_summarize_and_to_checks(self):
        plan = convert_sheet(
            [
                _row(
                    2,
                    check_id="a",
                    rule_type="notNull",
                    container="t",
                    fields="x",
                    datastore="dwh",
                ),
                _row(3, check_id="b", rule_type="freshness", container="t", value="1d"),
                _row(
                    4,
                    check_id="ct",
                    kind="computed_table",
                    container="calc",
                    query="SELECT CURRENT_DATE",
                ),
                _row(5, check_id="bad", rule_type="freshness", container="t"),
            ]
        )
        stats = summarize_sheet(plan)
        assert stats["checks"] == 2
        assert stats["containers"] == 1
        assert stats["computed_tables"] == 1
        assert stats["by_rule"] == {"freshness": 1, "notNull": 1}
        assert stats["by_status"] == {"Draft": 2}
        assert stats["errors"] == 1
        assert stats["warnings"] == 1
        assert stats["datastore_overrides"] == ["dwh"]
        assert stats["target_containers"] == ["t"]
        assert [c["rule_type"] for c in to_checks(plan)] == ["notNull", "freshness"]

    def test_uid_helper(self):
        assert sheet_check_uid("RE Fund #770") == "sheet__re_fund_770"

    def test_severity_constants(self):
        assert SEVERITY_ERROR == "error"
        assert SEVERITY_WARNING == "warning"


# ── Container phase (client-bound, mocked API) ────────────────────────────


class TestRepairContainerNames:
    def test_fixes_casing_in_place(self):
        from qualytics.services.migrate import repair_container_names

        checks = [{"container": "orders"}, {"container": "CUSTOMERS"}]
        corrections = repair_container_names(checks, ["ORDERS", "customers"])
        assert checks[0]["container"] == "ORDERS"
        assert checks[1]["container"] == "customers"
        assert corrections == ["orders → ORDERS", "CUSTOMERS → customers"]

    def test_exact_and_unknown_names_untouched(self):
        from qualytics.services.migrate import repair_container_names

        checks = [{"container": "orders"}, {"container": "mystery"}]
        corrections = repair_container_names(checks, ["orders"])
        assert not corrections
        assert checks[1]["container"] == "mystery"

    def test_ambiguous_casing_left_alone(self):
        from qualytics.services.migrate import repair_container_names

        checks = [{"container": "orders"}]
        corrections = repair_container_names(checks, ["ORDERS", "Orders"])
        assert not corrections
        assert checks[0]["container"] == "orders"


def _spec(kind="computed_table", name="calc", check_id="ct1", row=2, **extra):
    from qualytics.services.migrate import ContainerSpec

    spec = {"container_type": kind, "name": name, "query": "SELECT 1"}
    spec.update(extra)
    return ContainerSpec(kind, name, row, check_id, None, spec)


class TestEnsureContainers:
    def _patches(self, monkeypatch, listing=None):
        import qualytics.api.containers as api
        import qualytics.api.operations as operations_api

        # Baseline profile-op lookup before an update; no prior operations.
        monkeypatch.setattr(
            operations_api, "list_operations", lambda client, **kw: {"items": []}
        )

        calls = {"validate": [], "create": [], "update": [], "get": []}
        monkeypatch.setattr(
            api, "list_containers_listing", lambda client, ds: listing or []
        )
        monkeypatch.setattr(
            api,
            "validate_container",
            lambda client, payload, **kw: calls["validate"].append(payload),
        )

        def _create(client, payload):
            calls["create"].append(payload)
            return {"id": 100 + len(calls["create"]), "name": payload["name"]}

        monkeypatch.setattr(api, "create_container", _create)
        monkeypatch.setattr(
            api,
            "update_container",
            lambda client, cid, payload, **kw: calls["update"].append((cid, payload)),
        )
        monkeypatch.setattr(
            api,
            "get_container",
            lambda client, cid: {"id": cid, "query": "SELECT existing"},
        )
        return calls

    def _no_wait(self, monkeypatch):
        import qualytics.services.migrate as migrate

        waited = []

        def _wait(client, container_id, datastore_id, **kw):
            waited.append(container_id)
            return True, "profiled"

        monkeypatch.setattr(migrate, "wait_for_container_profile", _wait)
        return waited

    def test_validate_all_then_create_in_order(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers

        calls = self._patches(monkeypatch)
        waited = self._no_wait(monkeypatch)
        specs = [
            _spec(name="base"),
            _spec(
                kind="computed_join",
                name="joined",
                check_id="cj1",
                row=3,
                sources=[
                    {"container": "base", "alias": "b"},
                    {"container": "other", "alias": "o"},
                ],
            ),
        ]
        # "other" pre-exists; "base" is created by this run.
        calls_listing = [{"id": 7, "name": "other", "container_type": "table"}]
        import qualytics.api.containers as api

        monkeypatch.setattr(
            api, "list_containers_listing", lambda client, ds: calls_listing
        )

        result = ensure_containers(object(), specs, 42)

        assert result["created"] == 2
        assert result["failed"] == 0
        assert [p["name"] for p in calls["create"]] == ["base", "joined"]
        join_payload = calls["create"][1]
        assert join_payload["sources"] == [
            {"container_id": 101, "alias": "b"},
            {"container_id": 7, "alias": "o"},
        ]
        assert join_payload["datastore_id"] == 42
        assert waited == [101, 102]

    def test_validation_failure_aborts_before_create(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers

        calls = self._patches(monkeypatch)
        self._no_wait(monkeypatch)
        import qualytics.api.containers as api

        def _boom(client, payload, **kw):
            raise RuntimeError("bad SQL")

        monkeypatch.setattr(api, "validate_container", _boom)

        result = ensure_containers(object(), [_spec()], 42)
        assert result["failed"] == 1
        assert "validation failed" in result["errors"][0]
        assert not calls["create"]

    def test_existing_skip_reports_drift(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers

        calls = self._patches(
            monkeypatch,
            listing=[{"id": 9, "name": "calc", "container_type": "computed_table"}],
        )
        self._no_wait(monkeypatch)
        messages = []

        result = ensure_containers(object(), [_spec()], 42, report=messages.append)
        assert result["skipped"] == 1
        assert not calls["create"] and not calls["update"]
        assert any("query differs" in m for m in messages)

    def test_existing_update_puts_new_definition(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers

        calls = self._patches(
            monkeypatch,
            listing=[{"id": 9, "name": "calc", "container_type": "computed_table"}],
        )
        waited = self._no_wait(monkeypatch)

        # get_container mock returns "SELECT existing"; the spec says SELECT 1,
        # so the definition genuinely changed.
        result = ensure_containers(object(), [_spec()], 42, on_existing="update")
        assert result["updated"] == 1
        assert calls["update"][0][0] == 9
        assert calls["update"][0][1]["query"] == "SELECT 1"
        assert waited == [9]

    def test_existing_update_unchanged_definition_never_puts(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers

        calls = self._patches(
            monkeypatch,
            listing=[{"id": 9, "name": "calc", "container_type": "computed_table"}],
        )
        waited = self._no_wait(monkeypatch)
        messages = []

        spec = _spec(query="SELECT existing")
        result = ensure_containers(
            object(), [spec], 42, on_existing="update", report=messages.append
        )
        assert result["unchanged"] == 1
        assert result["updated"] == 0
        assert not calls["update"]
        assert waited == []  # existing profile stands
        assert any("unchanged" in m for m in messages)

    def test_force_drop_fields_passes_through(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers
        import qualytics.api.containers as api

        calls = self._patches(
            monkeypatch,
            listing=[{"id": 9, "name": "calc", "container_type": "computed_table"}],
        )
        self._no_wait(monkeypatch)
        forced = []
        monkeypatch.setattr(
            api,
            "update_container",
            lambda client, cid, payload, **kw: forced.append(
                kw.get("force_drop_fields")
            ),
        )

        ensure_containers(
            object(), [_spec()], 42, on_existing="update", force_drop_fields=True
        )
        assert forced == [True]
        assert not calls["update"]  # bypassed the default recorder above

    def test_conflict_error_gets_force_hint(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers
        import qualytics.api.containers as api

        self._patches(
            monkeypatch,
            listing=[{"id": 9, "name": "calc", "container_type": "computed_table"}],
        )
        self._no_wait(monkeypatch)

        def _conflict(client, cid, payload, **kw):
            raise RuntimeError(
                'HTTP 409: Conflict: {"detail": {"message": "Set '
                'force_drop_fields=true to proceed."}}'
            )

        monkeypatch.setattr(api, "update_container", _conflict)
        result = ensure_containers(object(), [_spec()], 42, on_existing="update")
        assert result["failed"] == 1
        assert "--force-drop-fields" in result["errors"][0]
        assert "update the sheet's dependent check rows" in result["errors"][0]

    def test_existing_update_metadata_only_uses_label_path(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers

        calls = self._patches(
            monkeypatch,
            listing=[{"id": 9, "name": "calc", "container_type": "computed_table"}],
        )
        waited = self._no_wait(monkeypatch)

        spec = _spec(
            query="SELECT existing",
            additional_metadata={"legacy_check_id": "ct1", "Source System": "eFront"},
        )
        result = ensure_containers(object(), [spec], 42, on_existing="update")
        assert result["updated"] == 1
        (update_call,) = calls["update"]
        assert update_call[0] == 9
        # Label-only PUT: live query resent (schema requires it), no re-profile wait.
        assert update_call[1]["query"] == "SELECT existing"
        assert update_call[1]["additional_metadata"]["Source System"] == "eFront"
        assert waited == []

    def test_existing_join_update_unchanged_sources_never_puts(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers
        import qualytics.api.containers as api

        calls = self._patches(
            monkeypatch,
            listing=[
                {"id": 9, "name": "j", "container_type": "computed_join"},
                {"id": 1, "name": "orders", "container_type": "table"},
                {"id": 2, "name": "customers", "container_type": "table"},
            ],
        )
        self._no_wait(monkeypatch)
        monkeypatch.setattr(
            api,
            "get_container",
            lambda client, cid: {
                "id": cid,
                "query": "SELECT 1",
                "sources": [
                    {"container_id": 1, "alias": "o", "ordinal": 0},
                    {"container_id": 2, "alias": "c", "ordinal": 1},
                ],
            },
        )

        spec = _spec(
            kind="computed_join",
            name="j",
            sources=[
                {"container": "orders", "alias": "o"},
                {"container": "customers", "alias": "c"},
            ],
        )
        result = ensure_containers(object(), [spec], 42, on_existing="update")
        assert result["unchanged"] == 1
        assert not calls["update"]

    def test_existing_type_mismatch_fails(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers

        self._patches(
            monkeypatch, listing=[{"id": 9, "name": "calc", "container_type": "view"}]
        )
        self._no_wait(monkeypatch)
        result = ensure_containers(object(), [_spec()], 42, on_existing="update")
        assert result["failed"] == 1
        assert "not a computed_table" in result["errors"][0]

    def test_dry_run_makes_no_writes(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers

        calls = self._patches(
            monkeypatch,
            listing=[{"id": 9, "name": "calc", "container_type": "computed_table"}],
        )
        result = ensure_containers(
            object(), [_spec(), _spec(name="fresh", check_id="ct2")], 42, dry_run=True
        )
        assert result["skipped"] == 1
        assert result["created"] == 1
        assert not calls["validate"] and not calls["create"] and not calls["update"]

    def test_unknown_join_source_fails(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers

        calls = self._patches(monkeypatch)
        self._no_wait(monkeypatch)
        specs = [
            _spec(
                kind="computed_join",
                name="j",
                sources=[
                    {"container": "ghost", "alias": "g"},
                    {"container": "phantom", "alias": "p"},
                ],
            )
        ]
        result = ensure_containers(object(), specs, 42)
        assert result["failed"] == 1
        assert "not found in datastore 42: ghost, phantom" in result["errors"][0]
        assert not calls["create"]

    def test_profile_failure_stops_the_phase(self, monkeypatch):
        from qualytics.services.migrate import ensure_containers
        import qualytics.services.migrate as migrate

        calls = self._patches(monkeypatch)
        monkeypatch.setattr(
            migrate,
            "wait_for_container_profile",
            lambda *a, **kw: (False, "timed out after 1s"),
        )
        specs = [_spec(name="one"), _spec(name="two", check_id="ct2", row=3)]
        result = ensure_containers(object(), specs, 42)
        assert result["failed"] == 1
        assert len(calls["create"]) == 1  # second create never attempted


class TestWaitForContainerProfile:
    def _api(self, monkeypatch, operations, operation, profiles):
        import qualytics.api.containers as containers_api
        import qualytics.api.operations as operations_api

        monkeypatch.setattr(
            operations_api, "list_operations", lambda client, **kw: operations
        )
        monkeypatch.setattr(
            operations_api, "get_operation", lambda client, oid: operation
        )
        monkeypatch.setattr(
            containers_api, "get_field_profiles", lambda client, cid: profiles
        )

    def test_success(self, monkeypatch):
        from qualytics.services.migrate import wait_for_container_profile

        self._api(
            monkeypatch,
            {"items": [{"id": 55}]},
            {"id": 55, "end_time": "t", "result": "success"},
            {"items": [{"field": "a"}]},
        )
        ok, detail = wait_for_container_profile(
            object(), 9, 42, timeout=5, sleep=lambda s: None
        )
        assert ok
        assert "operation 55" in detail

    def test_failed_operation(self, monkeypatch):
        from qualytics.services.migrate import wait_for_container_profile

        self._api(
            monkeypatch,
            {"items": [{"id": 55}]},
            {"id": 55, "end_time": "t", "result": "failure"},
            {"items": []},
        )
        ok, detail = wait_for_container_profile(
            object(), 9, 42, timeout=5, sleep=lambda s: None
        )
        assert not ok
        assert "result 'failure'" in detail

    def test_success_without_field_profiles(self, monkeypatch):
        from qualytics.services.migrate import wait_for_container_profile

        self._api(
            monkeypatch,
            {"items": [{"id": 55}]},
            {"id": 55, "end_time": "t", "result": "success"},
            {"items": []},
        )
        ok, detail = wait_for_container_profile(
            object(), 9, 42, timeout=5, sleep=lambda s: None
        )
        assert not ok
        assert "no field profiles" in detail

    def test_timeout_when_no_operation_appears(self, monkeypatch):
        from qualytics.services.migrate import wait_for_container_profile

        self._api(monkeypatch, {"items": []}, {}, {})
        ok, detail = wait_for_container_profile(
            object(), 9, 42, timeout=0, sleep=lambda s: None
        )
        assert not ok
        assert "timed out" in detail


class TestWaitForContainerProfileAnchor:
    def test_stale_completed_profile_never_satisfies_anchored_wait(self, monkeypatch):
        """The container's previous profile op must not read as instant success."""
        import qualytics.api.operations as operations_api
        from qualytics.services.migrate import wait_for_container_profile

        monkeypatch.setattr(
            operations_api,
            "list_operations",
            lambda client, **kw: {"items": [{"id": 55}]},
        )
        ok, detail = wait_for_container_profile(
            object(), 9, 42, timeout=0, sleep=lambda s: None, after_operation_id=55
        )
        assert not ok
        assert "timed out" in detail

    def test_younger_operation_satisfies_anchored_wait(self, monkeypatch):
        import qualytics.api.containers as containers_api
        import qualytics.api.operations as operations_api
        from qualytics.services.migrate import wait_for_container_profile

        monkeypatch.setattr(
            operations_api,
            "list_operations",
            lambda client, **kw: {"items": [{"id": 56}]},
        )
        monkeypatch.setattr(
            operations_api,
            "get_operation",
            lambda client, oid: {"id": 56, "end_time": "t", "result": "success"},
        )
        monkeypatch.setattr(
            containers_api,
            "get_field_profiles",
            lambda client, cid: {"items": [{"field": "a"}]},
        )
        ok, detail = wait_for_container_profile(
            object(), 9, 42, timeout=5, sleep=lambda s: None, after_operation_id=55
        )
        assert ok
        assert "operation 56" in detail
