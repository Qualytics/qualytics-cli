"""Tests for dbt manifest → quality check conversion."""

import pytest

from qualytics.services.dbt import (
    DBT_RULE_MAP,
    TIER_DIRECT,
    TIER_MANUAL,
    TIER_NORMALIZE,
    container_name_for,
    convert_manifest,
    dbt_check_uid,
    dbt_metadata,
    index_models,
    summarize,
    row_filter,
    to_checks,
)
from qualytics.services.quality_checks import _UID_KEY, _build_create_payload


# ── Fixtures ──────────────────────────────────────────────────────────────

PKG = "jaffle_analytics"


def _model(name, *, alias=None, schema="analytics"):
    return {
        "resource_type": "model",
        "name": name,
        "alias": alias or name,
        "schema": schema,
        "database": "warehouse",
    }


def _generic_test(
    model_uid,
    model_name,
    test_name,
    *,
    namespace=None,
    column=None,
    kwargs=None,
    extra_deps=None,
):
    key = f"{namespace}.{test_name}" if namespace else test_name
    suffix = f"{column or 'tbl'}"
    unique_id = f"test.{PKG}.{key.replace('.', '_')}_{model_name}_{suffix}.a1b2c3"
    deps = [model_uid] + list(extra_deps or [])
    return unique_id, {
        "resource_type": "test",
        "name": f"{key}_{model_name}_{suffix}",
        "column_name": column,
        "attached_node": model_uid,
        "file_key_name": f"models.{model_name}",
        "depends_on": {"nodes": deps},
        "test_metadata": {
            "namespace": namespace,
            "name": test_name,
            "kwargs": {**({"column_name": column} if column else {}), **(kwargs or {})},
        },
    }


def _singular_test(model_uid, model_name, name, sql="select * from x where 1=0"):
    unique_id = f"test.{PKG}.{name}.deadbee"
    return unique_id, {
        "resource_type": "test",
        "name": name,
        "attached_node": model_uid,
        "file_key_name": f"models.{model_name}",
        "depends_on": {"nodes": [model_uid]},
        "compiled_code": sql,
    }


@pytest.fixture
def manifest():
    """A manifest shaped like real dbt output: models + tests, aliases, singulars."""
    orders = f"model.{PKG}.stg_orders"
    customers = f"model.{PKG}.stg_customers"
    revenue = f"model.{PKG}.fct_revenue"

    nodes = {
        orders: _model("stg_orders", alias="stg_orders_v2"),
        customers: _model("stg_customers"),
        revenue: _model("fct_revenue"),
    }

    for uid, node in [
        _generic_test(orders, "stg_orders", "not_null", column="order_id"),
        _generic_test(orders, "stg_orders", "unique", column="order_id"),
        _generic_test(
            orders,
            "stg_orders",
            "accepted_values",
            column="status",
            kwargs={"values": ["placed", "shipped"]},
        ),
        _generic_test(
            orders,
            "stg_orders",
            "relationships",
            column="customer_id",
            kwargs={"to": "ref('stg_customers')", "field": "customer_id"},
            extra_deps=[customers],
        ),
        _generic_test(
            orders,
            "stg_orders",
            "accepted_range",
            namespace="dbt_utils",
            column="amount",
            kwargs={"min_value": 0, "max_value": 5000},
        ),
        _generic_test(
            revenue,
            "fct_revenue",
            "expect_column_values_to_match_regex",
            namespace="dbt_expectations",
            column="currency",
            kwargs={"regex": "^[A-Z]{3}$"},
        ),
        _generic_test(
            revenue,
            "fct_revenue",
            "expect_table_row_count_to_be_between",
            namespace="dbt_expectations",
            kwargs={"min_value": 1000},
        ),
        _generic_test(
            revenue,
            "fct_revenue",
            "is_valid_iso_currency",
            namespace="mycompany",
            column="currency_code",
        ),
        # Splits into minLength + maxLength.
        _generic_test(
            revenue,
            "fct_revenue",
            "expect_column_value_lengths_to_be_between",
            namespace="dbt_expectations",
            column="sku",
            kwargs={"min_value": 8, "max_value": 12},
        ),
        # Two singular tests on the SAME model — the collision case.
        _singular_test(revenue, "fct_revenue", "assert_revenue_reconciles"),
        _singular_test(revenue, "fct_revenue", "assert_no_orphan_refunds"),
    ]:
        nodes[uid] = node

    return {"nodes": nodes}


def _by_dbt_test(converted, name):
    return next(c for c in converted if c.dbt_test == name)


# ══════════════════════════════════════════════════════════════════════════
# 1. UID — the invariant that prevents silent test loss
# ══════════════════════════════════════════════════════════════════════════


class TestCheckUID:
    def test_derived_from_unique_id(self):
        uid = dbt_check_uid("test.jaffle.not_null_orders_order_id.5fb5b8f")
        assert uid == "dbt__test_jaffle_not_null_orders_order_id_5fb5b8f"

    def test_every_check_has_a_distinct_uid(self, manifest):
        converted = convert_manifest(manifest)
        uids = [c.check["additional_metadata"][_UID_KEY] for c in converted]
        assert len(uids) == len(set(uids)), "UID collision would silently drop checks"

    def test_two_singular_tests_on_one_model_do_not_collide(self, manifest):
        """The case the CLI's own container__rule__fields scheme collapses."""
        converted = convert_manifest(manifest)
        singular = [c for c in converted if c.note == "singular SQL test"]
        assert len(singular) == 2
        uids = {c.check["additional_metadata"][_UID_KEY] for c in singular}
        assert len(uids) == 2

    def test_every_dbt_test_yields_at_least_one_check(self, manifest):
        """Split mappings emit two; nothing may emit zero."""
        test_nodes = [
            n for n in manifest["nodes"].values() if n.get("resource_type") == "test"
        ]
        converted = convert_manifest(manifest)
        sources = {c.check["additional_metadata"]["dbt_unique_id"] for c in converted}
        assert len(sources) == len(test_nodes)
        assert len(converted) >= len(test_nodes)

    def test_conversion_is_deterministic(self, manifest):
        assert to_checks(convert_manifest(manifest)) == to_checks(
            convert_manifest(manifest)
        )


# ══════════════════════════════════════════════════════════════════════════
# 2. Rule + property mapping
# ══════════════════════════════════════════════════════════════════════════


class TestRuleMapping:
    def test_not_null_is_direct(self, manifest):
        c = _by_dbt_test(convert_manifest(manifest), "not_null")
        assert c.check["rule_type"] == "notNull"
        assert c.tier == TIER_DIRECT
        assert c.check["fields"] == ["order_id"]

    def test_accepted_values_uses_list_property(self, manifest):
        """controlplane QualityCheckProperties calls it `list`, not `list_of_values`."""
        c = _by_dbt_test(convert_manifest(manifest), "accepted_values")
        assert c.check["rule_type"] == "expectedValues"
        assert c.check["properties"] == {"list": ["placed", "shipped"]}

    def test_accepted_range_maps_min_max_not_min_value(self, manifest):
        """dbt says min_value/max_value; Qualytics `between` says min/max."""
        c = _by_dbt_test(convert_manifest(manifest), "dbt_utils.accepted_range")
        assert c.check["rule_type"] == "between"
        assert c.check["properties"] == {"min": 0, "max": 5000}

    def test_regex_maps_to_pattern(self, manifest):
        c = _by_dbt_test(
            convert_manifest(manifest),
            "dbt_expectations.expect_column_values_to_match_regex",
        )
        assert c.check["rule_type"] == "matchesPattern"
        assert c.check["properties"] == {"pattern": "^[A-Z]{3}$"}

    def test_relationships_carries_ref_container_name(self, manifest):
        c = _by_dbt_test(convert_manifest(manifest), "relationships")
        assert c.check["rule_type"] == "existsIn"
        assert c.check["properties"]["ref_container_name"] == "stg_customers"

    def test_container_level_rule_has_no_fields(self, manifest):
        c = _by_dbt_test(
            convert_manifest(manifest),
            "dbt_expectations.expect_table_row_count_to_be_between",
        )
        assert c.check["rule_type"] == "volumetric"
        assert c.check["fields"] == []

    def test_every_mapping_targets_a_known_rule_type(self):
        # Mirrors controlplane app/types/rule_types.py RuleType.
        known = {
            "notNull",
            "unique",
            "expectedValues",
            "existsIn",
            "between",
            "satisfiesExpression",
            "distinctCount",
            "matchesPattern",
            "maxLength",
            "minLength",
            "isType",
            "maxValue",
            "minValue",
            "metric",
            "sum",
            "volumetric",
            "freshness",
            "fieldCount",
            "expectedSchema",
        }
        for key, mapping in DBT_RULE_MAP.items():
            assert mapping.rule_type in known, (
                f"{key} → unknown rule {mapping.rule_type}"
            )

    def test_every_mapping_has_a_valid_tier(self):
        for key, mapping in DBT_RULE_MAP.items():
            assert mapping.tier in (TIER_DIRECT, TIER_NORMALIZE, TIER_MANUAL), key


# ══════════════════════════════════════════════════════════════════════════
# 2b. Split mappings — one dbt test asserting two things
# ══════════════════════════════════════════════════════════════════════════


LENGTHS_BETWEEN = "dbt_expectations.expect_column_value_lengths_to_be_between"
LENGTHS_EQUAL = "dbt_expectations.expect_column_value_lengths_to_equal"


def _lengths_manifest(kwargs, test_name="expect_column_value_lengths_to_be_between"):
    model = f"model.{PKG}.dim_product"
    uid, node = _generic_test(
        model,
        "dim_product",
        test_name,
        namespace="dbt_expectations",
        column="sku",
        kwargs=kwargs,
    )
    return {"nodes": {model: _model("dim_product"), uid: node}}


class TestSplitMappings:
    def test_lengths_between_emits_min_and_max(self, manifest):
        checks = [
            c for c in convert_manifest(manifest) if c.dbt_test == LENGTHS_BETWEEN
        ]
        assert len(checks) == 2
        assert {c.check["rule_type"] for c in checks} == {"minLength", "maxLength"}

    def test_split_properties_carry_the_right_bound(self, manifest):
        checks = {
            c.check["rule_type"]: c.check["properties"]
            for c in convert_manifest(manifest)
            if c.dbt_test == LENGTHS_BETWEEN
        }
        assert checks["minLength"] == {"value": 8}
        assert checks["maxLength"] == {"value": 12}

    def test_split_uids_are_suffixed_and_distinct(self, manifest):
        checks = [
            c for c in convert_manifest(manifest) if c.dbt_test == LENGTHS_BETWEEN
        ]
        uids = [c.check["additional_metadata"][_UID_KEY] for c in checks]
        assert len(set(uids)) == 2
        assert any(u.endswith("__minlength") for u in uids)
        assert any(u.endswith("__maxlength") for u in uids)

    def test_split_halves_share_dbt_provenance(self, manifest):
        checks = [
            c for c in convert_manifest(manifest) if c.dbt_test == LENGTHS_BETWEEN
        ]
        sources = {c.check["additional_metadata"]["dbt_unique_id"] for c in checks}
        assert len(sources) == 1

    def test_split_is_direct_not_draft(self, manifest):
        for c in convert_manifest(manifest):
            if c.dbt_test == LENGTHS_BETWEEN:
                assert c.tier == TIER_DIRECT
                assert c.check["status"] == "Active"

    def test_min_only_emits_one_check(self):
        converted = convert_manifest(_lengths_manifest({"min_value": 8}))
        assert len(converted) == 1
        assert converted[0].check["rule_type"] == "minLength"
        assert converted[0].check["properties"] == {"value": 8}

    def test_max_only_emits_one_check(self):
        converted = convert_manifest(_lengths_manifest({"max_value": 12}))
        assert len(converted) == 1
        assert converted[0].check["rule_type"] == "maxLength"

    def test_no_bounds_falls_back_to_manual(self):
        """Never emit zero checks — downgrade to a Draft instead."""
        converted = convert_manifest(_lengths_manifest({}))
        assert len(converted) == 1
        assert converted[0].check["rule_type"] == "satisfiesExpression"
        assert converted[0].tier == TIER_MANUAL

    def test_lengths_to_equal_pins_both_ends(self):
        converted = convert_manifest(
            _lengths_manifest(
                {"value": 10}, test_name="expect_column_value_lengths_to_equal"
            )
        )
        assert len(converted) == 2
        props = {c.check["rule_type"]: c.check["properties"] for c in converted}
        assert props == {"minLength": {"value": 10}, "maxLength": {"value": 10}}


# ══════════════════════════════════════════════════════════════════════════
# 3. Nothing is dropped
# ══════════════════════════════════════════════════════════════════════════


class TestNothingDropped:
    def test_unrecognized_generic_test_still_converts(self, manifest):
        c = _by_dbt_test(convert_manifest(manifest), "mycompany.is_valid_iso_currency")
        assert c.check["rule_type"] == "satisfiesExpression"
        assert c.tier == TIER_MANUAL
        assert c.check["status"] == "Draft"

    def test_singular_test_carries_compiled_sql(self, manifest):
        converted = convert_manifest(manifest)
        c = _by_dbt_test(converted, "assert_revenue_reconciles")
        assert c.check["rule_type"] == "satisfiesExpression"
        assert c.check["additional_metadata"]["dbt_compiled_sql"]

    def test_provenance_is_recorded(self, manifest):
        for c in convert_manifest(manifest):
            meta = c.check["additional_metadata"]
            assert meta["dbt_unique_id"].startswith("test.")
            assert meta[_UID_KEY].startswith("dbt__")


# ══════════════════════════════════════════════════════════════════════════
# 3b. dbt `where` → Qualytics `filter`, and metadata capture
# ══════════════════════════════════════════════════════════════════════════


def _configured_manifest(config, *, kwargs=None, singular=False):
    model = f"model.{PKG}.stg_orders"
    if singular:
        uid, node = _singular_test(model, "stg_orders", "assert_thing")
    else:
        uid, node = _generic_test(
            model, "stg_orders", "not_null", column="order_id", kwargs=kwargs
        )
    node["config"] = config
    return {"nodes": {model: _model("stg_orders"), uid: node}}


class TestFilterMapping:
    def test_where_becomes_filter(self):
        """Dropping `where` would fire the check on rows dbt excluded."""
        converted = convert_manifest(
            _configured_manifest({"where": "status != 'deleted'"})
        )
        assert converted[0].check["filter"] == "status != 'deleted'"

    def test_filter_key_present_even_when_unset(self, manifest):
        """Matches the shape strip_for_export produces."""
        for c in convert_manifest(manifest):
            assert "filter" in c.check
            assert c.check["filter"] is None

    def test_where_applies_to_singular_tests(self):
        converted = convert_manifest(
            _configured_manifest({"where": "amount > 0"}, singular=True)
        )
        assert converted[0].check["filter"] == "amount > 0"

    def test_where_applies_to_split_checks(self):
        model = f"model.{PKG}.dim_product"
        uid, node = _generic_test(
            model,
            "dim_product",
            "expect_column_value_lengths_to_be_between",
            namespace="dbt_expectations",
            column="sku",
            kwargs={"min_value": 8, "max_value": 12},
        )
        node["config"] = {"where": "sku is not null"}
        converted = convert_manifest(
            {"nodes": {model: _model("dim_product"), uid: node}}
        )
        assert len(converted) == 2
        assert all(c.check["filter"] == "sku is not null" for c in converted)

    def test_empty_where_stays_none(self):
        converted = convert_manifest(_configured_manifest({"where": ""}))
        assert converted[0].check["filter"] is None

    def test_row_filter_helper(self):
        assert row_filter({"config": {"where": "x = 1"}}) == "x = 1"
        assert row_filter({"config": {}}) is None
        assert row_filter({}) is None


class TestMetadataCapture:
    def test_unconsumed_kwargs_are_recorded(self):
        """A reviewer must not have to reopen the dbt project for a threshold."""
        converted = convert_manifest(
            _configured_manifest({}, kwargs={"at_least": 0.95, "group_by": ["region"]})
        )
        kwargs = converted[0].check["additional_metadata"]["dbt_kwargs"]
        assert kwargs == {"at_least": 0.95, "group_by": ["region"]}

    def test_column_name_is_not_echoed_into_metadata(self):
        converted = convert_manifest(_configured_manifest({}))
        assert "dbt_kwargs" not in converted[0].check["additional_metadata"]

    def test_package_recorded(self, manifest):
        node = next(
            n for n in manifest["nodes"].values() if n.get("resource_type") == "test"
        )
        node["package_name"] = "acme_analytics"
        converted = convert_manifest(manifest)
        assert any(
            c.check["additional_metadata"].get("dbt_package") == "acme_analytics"
            for c in converted
        )

    def test_non_default_severity_recorded(self):
        converted = convert_manifest(_configured_manifest({"severity": "warn"}))
        assert converted[0].check["additional_metadata"]["dbt_severity"] == "warn"

    def test_default_severity_omitted(self):
        converted = convert_manifest(_configured_manifest({"severity": "error"}))
        assert "dbt_severity" not in converted[0].check["additional_metadata"]

    def test_tags_recorded(self):
        converted = convert_manifest(_configured_manifest({"tags": ["nightly", "pii"]}))
        assert converted[0].check["additional_metadata"]["dbt_tags"] == [
            "nightly",
            "pii",
        ]

    def test_extra_config_recorded(self):
        converted = convert_manifest(
            _configured_manifest({"limit": 500, "store_failures": True})
        )
        meta = converted[0].check["additional_metadata"]
        assert meta["dbt_limit"] == 500
        assert meta["dbt_store_failures"] is True

    def test_metadata_helper_on_bare_node(self):
        assert dbt_metadata({}, "not_null") == {"dbt_test": "not_null"}

    def test_uid_and_provenance_survive_metadata_merge(self, manifest):
        for c in convert_manifest(manifest):
            meta = c.check["additional_metadata"]
            assert meta[_UID_KEY].startswith("dbt__")
            assert meta["dbt_unique_id"].startswith("test.")
            assert meta["dbt_test"]


# ══════════════════════════════════════════════════════════════════════════
# 4. Container resolution
# ══════════════════════════════════════════════════════════════════════════


class TestContainerResolution:
    def test_alias_wins_over_name(self, manifest):
        c = _by_dbt_test(convert_manifest(manifest), "not_null")
        assert c.check["container"] == "stg_orders_v2"

    def test_container_map_override(self, manifest):
        converted = convert_manifest(
            manifest, container_map={"stg_orders": "ORDERS_RAW"}
        )
        assert _by_dbt_test(converted, "not_null").check["container"] == "ORDERS_RAW"

    def test_container_case_upper(self, manifest):
        converted = convert_manifest(manifest, container_case="upper")
        assert _by_dbt_test(converted, "not_null").check["container"] == "STG_ORDERS_V2"

    def test_relationships_attaches_to_the_right_model(self, manifest):
        """A relationships test depends on two models; it must attach to its own."""
        c = _by_dbt_test(convert_manifest(manifest), "relationships")
        assert c.check["container"] == "stg_orders_v2"
        assert c.check["properties"]["ref_container_name"] == "stg_customers"

    def test_index_models_ignores_tests(self, manifest):
        assert all("model." in uid for uid in index_models(manifest))

    def test_container_name_prefers_alias(self):
        assert container_name_for({"name": "a", "alias": "b"}) == "b"
        assert container_name_for({"name": "a"}) == "a"


# ══════════════════════════════════════════════════════════════════════════
# 5. Status / re-sync behavior
# ══════════════════════════════════════════════════════════════════════════


class TestStatus:
    def test_direct_lands_active(self, manifest):
        assert (
            _by_dbt_test(convert_manifest(manifest), "not_null").check["status"]
            == "Active"
        )

    def test_normalize_and_manual_land_draft(self, manifest):
        converted = convert_manifest(manifest)
        for c in converted:
            if c.tier in (TIER_NORMALIZE, TIER_MANUAL):
                assert c.check["status"] == "Draft", c.dbt_test

    def test_include_status_false_omits_the_key(self, manifest):
        """Re-sync must not reset a check a human activated in the product."""
        for c in convert_manifest(manifest, include_status=False):
            assert "status" not in c.check

    def test_status_override_forces_draft(self, manifest):
        for c in convert_manifest(manifest, status_override="Draft"):
            assert c.check["status"] == "Draft"

    def test_status_override_forces_active(self, manifest):
        """The tiers are a recommendation; the caller owns the migration."""
        for c in convert_manifest(manifest, status_override="Active"):
            assert c.check["status"] == "Active"

    def test_status_override_does_not_change_tiers(self, manifest):
        """Overriding status must not rewrite the reported crosswalk."""
        default = summarize(convert_manifest(manifest))
        forced = summarize(convert_manifest(manifest, status_override="Active"))
        assert default["direct"] == forced["direct"]
        assert default["manual"] == forced["manual"]

    def test_status_override_wins_over_include_status(self, manifest):
        converted = convert_manifest(
            manifest, include_status=False, status_override="Draft"
        )
        assert all(c.check["status"] == "Draft" for c in converted)


# ══════════════════════════════════════════════════════════════════════════
# 6. Interop with the existing import path
# ══════════════════════════════════════════════════════════════════════════


class TestImportInterop:
    def test_checks_build_a_valid_create_payload(self, manifest):
        for check in to_checks(convert_manifest(manifest)):
            payload = _build_create_payload(check, container_id=42)
            assert payload["container_id"] == 42
            assert payload["rule"] == check["rule_type"]
            assert payload["additional_metadata"][_UID_KEY].startswith("dbt__")

    def test_portable_shape_has_the_expected_keys(self, manifest):
        required = {
            "rule_type",
            "description",
            "container",
            "fields",
            "coverage",
            "properties",
            "tags",
            "additional_metadata",
            "status",
        }
        for check in to_checks(convert_manifest(manifest)):
            assert required <= set(check)


# ══════════════════════════════════════════════════════════════════════════
# 7. Reporting
# ══════════════════════════════════════════════════════════════════════════


class TestSummarize:
    def test_counts_add_up(self, manifest):
        s = summarize(convert_manifest(manifest))
        assert s["direct"] + s["normalize"] + s["manual"] == s["total"]
        assert s["automatic"] == s["direct"] + s["normalize"]

    def test_checks_and_dbt_tests_are_counted_separately(self, manifest):
        """11 test nodes, one of which splits into minLength + maxLength."""
        s = summarize(convert_manifest(manifest))
        assert s["dbt_tests"] == 11
        assert s["total"] == 12

    def test_percentage(self, manifest):
        s = summarize(convert_manifest(manifest))
        assert s["automatic_pct"] == round(s["automatic"] / s["total"] * 100)

    def test_containers_listed(self, manifest):
        s = summarize(convert_manifest(manifest))
        assert "stg_orders_v2" in s["containers"]
        assert s["unresolved_containers"] == 0

    def test_empty_manifest(self):
        s = summarize(convert_manifest({"nodes": {}}))
        assert s["total"] == 0
        assert s["automatic_pct"] == 0
