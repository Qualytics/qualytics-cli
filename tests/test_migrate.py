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
        assert meta["_qualytics_check_uid"] == "sheet__100"
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

    def test_unconsumed_columns_land_in_metadata(self):
        plan = convert_sheet(
            [
                _row(
                    check_id="a",
                    rule_type="notNull",
                    container="t",
                    fields="x",
                    severity="High",
                    approach="Direct notNull check",
                )
            ]
        )
        meta = plan.checks[0].check["additional_metadata"]
        assert meta["sheet_severity"] == "High"
        assert meta["sheet_approach"] == "Direct notNull check"

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
