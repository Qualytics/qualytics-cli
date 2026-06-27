"""Tests for qualytics.cli.generate_driver — YAML generation and helpers."""

import pytest
import yaml

from qualytics.cli.generate_driver import (
    VALID_DATE_ARITHMETIC_STYLE,
    VALID_DATE_LITERAL_STYLE,
    VALID_ROW_COUNT,
    VALID_ROW_LIMIT_STYLE,
    VALID_SCHEMA_ONLY,
    VALID_SQL_CLAUSES,
    VALID_SQL_FUNCTIONS,
    VALID_TABLE_NAME_CASING,
    VALID_TIMESTAMP_LITERAL_STYLE,
    VALID_TRANSACTION_ISOLATION,
    _apply_llm_suggestions,
    _build_yaml,
    _collect_todo_fields,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_MINIMAL_PROBES = {
    "className": "com.example.Driver",
    "dbProductName": "TestDB",
    "transactionIsolation": "READ_UNCOMMITTED",
    "identifierQuoteChar": '"',
    "tableNameCasing": "AS_IS",
    "rowLimitStyle": "LIMIT",
    "subqueryAlias": True,
    "timestampLiteralStyle": "PLAIN",
    "dateLiteralStyle": "PLAIN",
    "schemaOnly": "CTE",
    "connectionTest": "SELECT 1",
    "viewSampleFallback": "RAND",
    "rowCount": "COUNT_STAR",
    "dateArithmeticStyle": "STANDARD",
    "getTablesUsesNullCatalog": False,
}

_JDBC_URL = "jdbc:testdb://localhost:5432/mydb"


# ---------------------------------------------------------------------------
# _build_yaml — structure tests
# ---------------------------------------------------------------------------


class TestBuildYamlStructure:
    """Verify the v2 three-section YAML layout."""

    def _parse(self, probes=None, url=None, **kwargs):
        content, detected, todos = _build_yaml(
            "testdb",
            probes or _MINIMAL_PROBES,
            url or _JDBC_URL,
            **kwargs,
        )
        parsed = yaml.safe_load(content)
        return content, parsed, detected, todos

    def test_top_level_keys(self):
        """prefix, className, dialectClass stay at top level; config and sql are sections."""
        _, parsed, _, _ = self._parse()
        assert "prefix" in parsed
        assert "className" in parsed
        assert "dialectClass" in parsed
        assert "config" in parsed
        assert isinstance(parsed["config"], dict)
        assert "sql" in parsed
        assert isinstance(parsed["sql"], dict)

    def test_dialect_class_at_top_level(self):
        _, parsed, _, _ = self._parse(dialect_class="com.example.Dialect$")
        assert parsed["dialectClass"] == "com.example.Dialect$"

    def test_config_contains_display_name(self):
        _, parsed, _, _ = self._parse()
        assert "displayName" in parsed["config"]
        assert parsed["config"]["displayName"] == "TestDB"

    def test_config_contains_default_port(self):
        _, parsed, _, _ = self._parse()
        assert "defaultPort" in parsed["config"]
        assert parsed["config"]["defaultPort"] == 5432

    def test_config_contains_url_sub_object(self):
        _, parsed, _, _ = self._parse()
        config = parsed["config"]
        assert "url" in config
        url = config["url"]
        assert "template" in url
        assert "staticParams" in url
        assert "conditionalParams" in url
        assert "authVariants" in url
        assert "paramSeparator" in url

    def test_config_contains_connection_spec(self):
        _, parsed, _, _ = self._parse()
        assert "connectionSpec" in parsed["config"]
        cs = parsed["config"]["connectionSpec"]
        assert cs["supportsEnrichment"] is False
        assert isinstance(cs["fields"], list)
        assert any(f["name"] == "host" for f in cs["fields"])

    def test_config_contains_connectivity_fields(self):
        _, parsed, _, _ = self._parse()
        config = parsed["config"]
        assert "connectionProperties" in config
        assert "sessionInitStatements" in config

    def test_config_contains_network_capable(self):
        _, parsed, _, _ = self._parse()
        assert parsed["config"]["networkCapable"] is True

    def test_config_contains_read_only(self):
        _, parsed, _, _ = self._parse()
        assert parsed["config"]["readOnly"] is False

    def test_config_contains_supports_long_limit(self):
        _, parsed, _, _ = self._parse()
        assert parsed["config"]["supportsLongLimit"] is False

    def test_config_contains_default_insert_batch_size(self):
        _, parsed, _, _ = self._parse()
        assert "defaultInsertBatchSize" in parsed["config"]
        assert parsed["config"]["defaultInsertBatchSize"] is None

    def test_config_contains_connection_property_mappings(self):
        _, parsed, _, _ = self._parse()
        assert "connectionPropertyMappings" in parsed["config"]
        assert parsed["config"]["connectionPropertyMappings"] == {}

    def test_connection_spec_fields_have_aliases(self):
        """Each connection spec field should have an aliases key."""
        _, parsed, _, _ = self._parse()
        fields = parsed["config"]["connectionSpec"]["fields"]
        for f in fields:
            assert "aliases" in f, f"field '{f['name']}' missing aliases key"
            assert isinstance(f["aliases"], list)

    def test_connection_spec_comment_mentions_depends_on_values(self):
        """The connectionSpec comment should reference dependsOnValues (plural)."""
        content, _, _, _ = self._parse()
        assert "dependsOnValues" in content

    def test_config_contains_schema_filtering_fields(self):
        _, parsed, _, _ = self._parse()
        config = parsed["config"]
        assert "systemSchemaExclusions" in config
        assert "systemSchemaExclusionPrefixes" in config
        assert "systemCatalogExclusions" in config

    def test_sql_section_structure(self):
        """SQL section should have functions, clauses, queries sub-keys."""
        _, parsed, _, _ = self._parse()
        sql = parsed["sql"]
        assert "queries" in sql
        assert "functions" in sql
        assert isinstance(sql["functions"], list)  # empty list when all defaults
        assert "clauses" in sql
        assert isinstance(sql["clauses"], list)  # empty list when all defaults

    def test_sql_capabilities_under_sql_queries(self):
        """SQL query-style fields should use QuerySlot keys under sql.queries."""
        probes = {**_MINIMAL_PROBES, "schemaOnly": "PG_CTE"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["sql"]["queries"]["schemaOnly"] == "PG_CTE"
        assert "schemaOnlyQueryStyle" not in parsed
        assert "schemaOnlyQueryStyle" not in parsed.get("config", {})
        assert "schemaOnlyQueryStyle" not in parsed["sql"]["queries"]

    def test_sql_capabilities_with_detected_values(self):
        probes = {
            **_MINIMAL_PROBES,
            "schemaOnly": "SQLSERVER_TOP0",
            "dateArithmeticStyle": "DATEADD_DATEDIFF",
            "approxCountDistinctFunction": "APPROX_COUNT_DISTINCT",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        queries = parsed["sql"]["queries"]
        functions = parsed["sql"]["functions"]
        assert queries["schemaOnly"] == "SQLSERVER_TOP0"
        assert queries["freshness"]["style"] == "DATEADD_DATEDIFF"
        # schemaExistenceQueryStyle is not part of v2 schema — should NOT appear
        assert "schemaExistenceQueryStyle" not in queries
        assert "APPROX_COUNT_DISTINCT" in functions

    def test_sql_functions_with_detected_values(self):
        probes = {**_MINIMAL_PROBES, "viewSampleFallback": "RANDOM"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "RANDOM" in parsed["sql"]["functions"]

    def test_sql_clauses_with_detected_values(self):
        probes = {
            **_MINIMAL_PROBES,
            "tableSampleTemplate": "TABLESAMPLE SYSTEM ({pct})",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        assert isinstance(parsed["sql"]["clauses"], list)
        assert "TABLESAMPLE_SYSTEM" in parsed["sql"]["clauses"]

    def test_sql_clauses_maps_sample_percent(self):
        probes = {**_MINIMAL_PROBES, "tableSampleTemplate": "SAMPLE ({pct})"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "SAMPLE_PERCENT" in parsed["sql"]["clauses"]

    def test_sql_clauses_maps_bernoulli(self):
        probes = {
            **_MINIMAL_PROBES,
            "tableSampleTemplate": "TABLESAMPLE BERNOULLI ({pct})",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        assert "TABLESAMPLE_BERNOULLI" in parsed["sql"]["clauses"]

    def test_sql_clauses_empty_when_no_sample(self):
        _, parsed, _, _ = self._parse()
        assert parsed["sql"]["clauses"] == []

    def test_date_templates_under_freshness_query_slot(self):
        """Date templates should nest under sql.queries.freshness QuerySlot."""
        probes = {
            **_MINIMAL_PROBES,
            "intervalCalcDatetimeTimestampTemplate": "DATEADD(second, ...)",
            "upperBoundDatetimeDateTemplate": "DATEADD(day, ...)",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        freshness = parsed["sql"]["queries"]["freshness"]
        assert freshness["intervalCalcDatetimeTimestampTemplate"] == "DATEADD(second, ...)"
        assert freshness["upperBoundDatetimeDateTemplate"] == "DATEADD(day, ...)"
        assert "intervalCalcDatetimeTimestampTemplate" not in parsed
        assert "intervalCalcDatetimeTimestampTemplate" not in parsed.get("config", {})
        # Templates should NOT be at the queries level
        assert "intervalCalcDatetimeTimestampTemplate" not in parsed["sql"]["queries"]

    def test_freshness_with_style_and_templates(self):
        """freshness QuerySlot should contain both style and templates when both present."""
        probes = {
            **_MINIMAL_PROBES,
            "dateArithmeticStyle": "DATEADD_DATEDIFF",
            "intervalCalcDatetimeTimestampTemplate": "DATEADD(second, ...)",
            "intervalCalcDatetimeDateTemplate": "DATEADD(day, ...)",
            "upperBoundDatetimeTimestampTemplate": "DATEADD(second, ...)",
            "upperBoundDatetimeDateTemplate": "DATEADD(day, ...)",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        freshness = parsed["sql"]["queries"]["freshness"]
        assert freshness["style"] == "DATEADD_DATEDIFF"
        assert freshness["intervalCalcDatetimeTimestampTemplate"] == "DATEADD(second, ...)"
        assert freshness["intervalCalcDatetimeDateTemplate"] == "DATEADD(day, ...)"
        assert freshness["upperBoundDatetimeTimestampTemplate"] == "DATEADD(second, ...)"
        assert freshness["upperBoundDatetimeDateTemplate"] == "DATEADD(day, ...)"

    def test_freshness_omitted_when_all_defaults(self):
        """When dateArithmeticStyle is STANDARD and no templates, freshness key absent."""
        _, parsed, _, _ = self._parse()
        assert "freshness" not in parsed["sql"]["queries"]

    def test_row_count_uses_query_slot_key(self):
        """rowCountQueryStyle probe → rowCount QuerySlot key."""
        probes = {**_MINIMAL_PROBES, "rowCount": "BQ_TABLES"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["sql"]["queries"]["rowCount"] == "BQ_TABLES"
        assert "rowCountQueryStyle" not in parsed["sql"]["queries"]

    def test_config_fields_not_at_top_level(self):
        """Config fields should NOT appear at the top level."""
        _, parsed, _, _ = self._parse()
        for key in [
            "displayName",
            "defaultPort",
            "connectionProperties",
            "url",
            "connectionSpec",
        ]:
            assert key not in parsed, f"{key} should be in config, not top-level"

    def test_non_default_transaction_isolation_in_config(self):
        probes = {**_MINIMAL_PROBES, "transactionIsolation": "SERIALIZABLE"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["config"]["transactionIsolation"] == "SERIALIZABLE"

    def test_non_default_table_name_casing_in_config(self):
        probes = {**_MINIMAL_PROBES, "tableNameCasing": "LOWER"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["config"]["tableNameCasing"] == "LOWER"

    def test_connection_spec_field_schema(self):
        """Every connectionSpec field must have name, label, fieldType, required keys."""
        _, parsed, _, _ = self._parse()
        fields = parsed["config"]["connectionSpec"]["fields"]
        required_keys = {"name", "label", "fieldType", "required"}
        for f in fields:
            missing = required_keys - set(f.keys())
            assert not missing, f"field '{f.get('name', '?')}' missing keys: {missing}"

    def test_connection_spec_fields_match_url_components(self):
        """host/port/database fields appear only when the probe URL contains them."""
        _, parsed, _, _ = self._parse()
        names = [f["name"] for f in parsed["config"]["connectionSpec"]["fields"]]
        # Standard URL jdbc:testdb://localhost:5432/mydb has host, port, database
        assert "host" in names
        assert "port" in names
        assert "database" in names
        # username and password always present
        assert "username" in names
        assert "password" in names

    def test_connection_spec_omits_missing_url_components(self):
        """If the URL has no host/port, those fields are omitted from connectionSpec."""
        # jdbc:sqlite:/path/to/db has no host or port (but file path → database)
        _, parsed, _, _ = self._parse(url="jdbc:sqlite:/path/to/test.db")
        names = [f["name"] for f in parsed["config"]["connectionSpec"]["fields"]]
        assert "host" not in names
        assert "port" not in names
        assert "database" in names  # file path is treated as database
        # username and password always present
        assert "username" in names
        assert "password" in names

    def test_connection_spec_port_default_value(self):
        """Port field should include defaultValue when detected from URL."""
        _, parsed, _, _ = self._parse()
        fields = parsed["config"]["connectionSpec"]["fields"]
        port_field = next(f for f in fields if f["name"] == "port")
        assert port_field["defaultValue"] == "5432"

    def test_connection_spec_not_at_top_level(self):
        """connectionSpec must be nested under config, never at top level."""
        _, parsed, _, _ = self._parse()
        assert "connectionSpec" not in parsed, "connectionSpec should be in config"
        assert "connectionSpec" in parsed["config"]

    def test_non_default_row_limit_in_config(self):
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": "TOP"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["config"]["rowLimitStyle"] == "TOP"

    def test_fetch_first_not_in_row_limit_style(self):
        """FETCH_FIRST should NOT appear as rowLimitStyle — it's a sql.clause."""
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": "FETCH_FIRST"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "rowLimitStyle" not in parsed.get("config", {})

    def test_fetch_first_maps_to_offset_fetch_clause(self):
        """FETCH_FIRST rowLimit → OFFSET_FETCH in sql.clauses."""
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": "FETCH_FIRST"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "OFFSET_FETCH" in parsed["sql"]["clauses"]

    def test_fetch_first_with_tablesample_both_in_clauses(self):
        """FETCH_FIRST + tableSampleTemplate should both appear in sql.clauses."""
        probes = {
            **_MINIMAL_PROBES,
            "rowLimitStyle": "FETCH_FIRST",
            "tableSampleTemplate": "TABLESAMPLE SYSTEM ({pct})",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        clauses = parsed["sql"]["clauses"]
        assert "OFFSET_FETCH" in clauses
        assert "TABLESAMPLE_SYSTEM" in clauses

    def test_validation_query_in_config(self):
        probes = {**_MINIMAL_PROBES, "connectionTest": "SELECT 1 FROM DUAL"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["config"]["connectionTest"] == "SELECT 1 FROM DUAL"

    def test_yaml_parses_as_valid_yaml(self):
        content, _, _, _ = self._parse()
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)

    def test_removed_fields_not_in_output(self):
        """maxPartitionParallelism, dataSizeLimit, schemaExistenceQueryStyle must not appear."""
        _, parsed, _, _ = self._parse()
        config = parsed["config"]
        queries = parsed["sql"]["queries"]
        assert "maxPartitionParallelism" not in config
        assert "dataSizeLimit" not in config
        assert "schemaExistenceQueryStyle" not in queries

    def test_no_remaining_flat_fields(self):
        """Exhaustive check: every probe field routes to config or sql, never top level."""
        # Use non-default values for every probe field to force all emission paths
        probes = {
            "className": "com.example.FullDriver",
            "dbProductName": "FullDB",
            "dbProductVersion": "9.0.1",
            "identifierQuoteChar": "`",
            "transactionIsolation": "SERIALIZABLE",
            "tableNameCasing": "UPPER",
            "connectionTest": "SELECT 1 FROM DUAL",
            "getTablesUsesNullCatalog": True,
            "subqueryAlias": False,
            "approxCountDistinctFunction": "APPROX_COUNT_DISTINCT",
            "dateArithmeticStyle": "DATEADD_DATEDIFF",
            "rowLimitStyle": "TOP",
            "tableSampleTemplate": "TABLESAMPLE BERNOULLI ({pct})",
            "intervalCalcDatetimeTimestampTemplate": "DATEADD(second, ...)",
            "intervalCalcDatetimeDateTemplate": "DATEADD(day, ...)",
            "upperBoundDatetimeTimestampTemplate": "DATEADD(second, ...)",
            "upperBoundDatetimeDateTemplate": "DATEADD(day, ...)",
            "viewSampleFallback": "RANDOM",
            "timestampLiteralStyle": "CAST_DATETIME2",
            "dateLiteralStyle": "TO_DATE",
            "schemaOnly": "SQLSERVER_TOP0",
            "rowCount": "ALL_TABLES",
        }
        _, parsed, _, _ = self._parse(
            probes=probes, dialect_class="com.example.Dialect$"
        )
        # Only these keys are allowed at the top level
        allowed_top_keys = {"prefix", "className", "dialectClass", "config", "sql"}
        extra = set(parsed.keys()) - allowed_top_keys
        assert not extra, f"Unexpected top-level keys (should be in config or sql): {extra}"

        # v1-style flat field names must not appear anywhere in the parsed output
        v1_flat_names = {
            "jdbcUrlTemplate", "jdbcUrlStaticParams", "jdbcUrlConditionalParams",
            "jdbcUrlAuthVariants", "rowLimitSyntax", "subqueryRequiresAlias",
            "validationQuery", "rowCountQueryStyle", "schemaOnlyQueryStyle",
            "schemaExistenceQueryStyle", "maxPartitionParallelism", "dataSizeLimit",
            "approxCountDistinctFunction", "viewSampleFallback",
            "tableSampleTemplate", "dateArithmeticStyle",
            "intervalCalcDatetimeTimestampTemplate", "intervalCalcDatetimeDateTemplate",
            "upperBoundDatetimeTimestampTemplate", "upperBoundDatetimeDateTemplate",
        }
        for name in v1_flat_names:
            assert name not in parsed, f"v1 flat field '{name}' leaked to top level"
            assert name not in parsed.get("config", {}), (
                f"v1 flat field '{name}' in config (should be restructured)"
            )

        # Verify all config fields are under config:
        config = parsed["config"]
        assert config["identifierQuoteChar"] == "`"
        assert config["transactionIsolation"] == "SERIALIZABLE"
        assert config["tableNameCasing"] == "UPPER"
        assert config["connectionTest"] == "SELECT 1 FROM DUAL"
        assert config["getTablesUsesNullCatalog"] is True
        assert config["subqueryAlias"] is False
        assert config["rowLimitStyle"] == "TOP"
        assert config["timestampLiteralStyle"] == "CAST_DATETIME2"
        assert config["dateLiteralStyle"] == "TO_DATE"

        # Verify all SQL capabilities are under sql:
        sql = parsed["sql"]
        assert "APPROX_COUNT_DISTINCT" in sql["functions"]
        assert "RANDOM" in sql["functions"]
        assert "TABLESAMPLE_BERNOULLI" in sql["clauses"]
        assert sql["queries"]["schemaOnly"] == "SQLSERVER_TOP0"
        assert sql["queries"]["rowCount"] == "ALL_TABLES"
        freshness = sql["queries"]["freshness"]
        assert freshness["style"] == "DATEADD_DATEDIFF"
        assert "intervalCalcDatetimeTimestampTemplate" in freshness


# ---------------------------------------------------------------------------
# _collect_todo_fields — indentation handling
# ---------------------------------------------------------------------------


class TestCollectTodoFields:
    def test_collects_top_level_todos(self):
        yaml_content = "dialectClass: null  # TODO: Spark dialect\n"
        todos = _collect_todo_fields(yaml_content)
        assert len(todos) == 1
        assert todos[0][0] == "dialectClass"

    def test_collects_indented_todos(self):
        yaml_content = "  connectionTest: SELECT 1  # TODO: verify connection query\n"
        todos = _collect_todo_fields(yaml_content)
        assert len(todos) == 1
        assert todos[0][0] == "connectionTest"
        assert todos[0][1] == "SELECT 1"

    def test_collects_both_levels(self):
        yaml_content = (
            "dialectClass: null  # TODO: Spark dialect\n"
            "config:\n"
            "  connectionTest: SELECT 1  # TODO: verify connection\n"
            "  displayName: TestDB  # auto-detected\n"
        )
        todos = _collect_todo_fields(yaml_content)
        assert len(todos) == 2
        names = [t[0] for t in todos]
        assert "dialectClass" in names
        assert "connectionTest" in names

    def test_ignores_non_todo_comments(self):
        yaml_content = "  displayName: TestDB  # auto-detected\n"
        todos = _collect_todo_fields(yaml_content)
        assert len(todos) == 0


# ---------------------------------------------------------------------------
# _apply_llm_suggestions — indentation preservation
# ---------------------------------------------------------------------------


class TestApplyLlmSuggestions:
    def test_preserves_indentation_for_config_fields(self):
        yaml_content = (
            "config:\n"
            "  connectionTest: SELECT 1  # TODO: verify connection\n"
            "  displayName: TestDB  # auto-detected\n"
        )
        suggestions = {
            "connectionTest": {"value": "SELECT 1 FROM DUAL", "rationale": "Oracle convention"},
        }
        updated, count = _apply_llm_suggestions(yaml_content, suggestions)
        assert count == 1
        assert "  connectionTest: SELECT 1 FROM DUAL  # LLM-suggested:" in updated

    def test_handles_top_level_fields(self):
        yaml_content = "dialectClass: null  # TODO: Spark dialect\n"
        suggestions = {
            "dialectClass": {"value": "com.example.Dialect$", "rationale": "Found"},
        }
        updated, count = _apply_llm_suggestions(yaml_content, suggestions)
        assert count == 1
        assert updated.startswith("dialectClass: com.example.Dialect$")
        assert "  dialectClass:" not in updated  # no extra indentation

    def test_skips_none_values(self):
        yaml_content = "dialectClass: null  # TODO: Spark dialect\n"
        suggestions = {"dialectClass": {"value": None, "rationale": "Unknown"}}
        updated, count = _apply_llm_suggestions(yaml_content, suggestions)
        assert count == 0
        assert "# TODO:" in updated


# ---------------------------------------------------------------------------
# Enum value validation — ensure all generated values match dataplane vocab
# ---------------------------------------------------------------------------


class TestEnumValuesMatchDataplane:
    """Verify every enum value emitted by _build_yaml uses exact dataplane values."""

    def _parse(self, probes=None, url=None, **kwargs):
        content, detected, todos = _build_yaml(
            "testdb",
            probes or _MINIMAL_PROBES,
            url or _JDBC_URL,
            **kwargs,
        )
        parsed = yaml.safe_load(content)
        return parsed

    # -- transactionIsolation --

    @pytest.mark.parametrize(
        "value",
        ["NONE", "READ_UNCOMMITTED", "READ_COMMITTED", "REPEATABLE_READ", "SERIALIZABLE"],
    )
    def test_transaction_isolation_valid(self, value):
        probes = {**_MINIMAL_PROBES, "transactionIsolation": value}
        parsed = self._parse(probes=probes)
        emitted = parsed["config"].get("transactionIsolation", "READ_UNCOMMITTED")
        assert emitted in VALID_TRANSACTION_ISOLATION

    # -- tableNameCasing --

    @pytest.mark.parametrize("value", ["UPPER", "LOWER", "AS_IS"])
    def test_table_name_casing_valid(self, value):
        probes = {**_MINIMAL_PROBES, "tableNameCasing": value}
        parsed = self._parse(probes=probes)
        emitted = parsed["config"].get("tableNameCasing", "AS_IS")
        assert emitted in VALID_TABLE_NAME_CASING

    # -- rowLimitStyle --

    @pytest.mark.parametrize("value", ["LIMIT", "TOP", "ROWNUM"])
    def test_row_limit_style_valid(self, value):
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": value}
        parsed = self._parse(probes=probes)
        emitted = parsed["config"].get("rowLimitStyle", "LIMIT")
        assert emitted in VALID_ROW_LIMIT_STYLE

    def test_fetch_first_not_emitted_as_row_limit_style(self):
        """FETCH_FIRST is NOT a valid rowLimitStyle — must map to OFFSET_FETCH clause."""
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": "FETCH_FIRST"}
        parsed = self._parse(probes=probes)
        assert "rowLimitStyle" not in parsed.get("config", {})
        assert "OFFSET_FETCH" in parsed["sql"]["clauses"]
        assert "OFFSET_FETCH" in VALID_SQL_CLAUSES

    # -- timestampLiteralStyle --

    @pytest.mark.parametrize(
        "value",
        ["PLAIN", "TIMESTAMP_PREFIX", "CAST_DATETIME2", "TO_TIMESTAMP"],
    )
    def test_timestamp_literal_style_valid(self, value):
        probes = {**_MINIMAL_PROBES, "timestampLiteralStyle": value}
        parsed = self._parse(probes=probes)
        emitted = parsed["config"].get("timestampLiteralStyle", "PLAIN")
        assert emitted in VALID_TIMESTAMP_LITERAL_STYLE

    # -- dateLiteralStyle --

    @pytest.mark.parametrize("value", ["PLAIN", "TO_DATE"])
    def test_date_literal_style_valid(self, value):
        probes = {**_MINIMAL_PROBES, "dateLiteralStyle": value}
        parsed = self._parse(probes=probes)
        emitted = parsed["config"].get("dateLiteralStyle", "PLAIN")
        assert emitted in VALID_DATE_LITERAL_STYLE

    # -- sql.functions --

    @pytest.mark.parametrize("value", ["APPROX_COUNT_DISTINCT", "APPROX_DISTINCT"])
    def test_approx_function_valid(self, value):
        probes = {**_MINIMAL_PROBES, "approxCountDistinctFunction": value}
        parsed = self._parse(probes=probes)
        for fn in parsed["sql"]["functions"]:
            assert fn in VALID_SQL_FUNCTIONS, f"{fn} not in valid sql.functions vocab"

    @pytest.mark.parametrize("value", ["RAND", "RANDOM", "NEWID"])
    def test_view_sample_fallback_valid(self, value):
        probes = {**_MINIMAL_PROBES, "viewSampleFallback": value}
        parsed = self._parse(probes=probes)
        for fn in parsed["sql"]["functions"]:
            assert fn in VALID_SQL_FUNCTIONS, f"{fn} not in valid sql.functions vocab"

    # -- sql.clauses --

    @pytest.mark.parametrize(
        "template,expected_token",
        [
            ("TABLESAMPLE SYSTEM ({pct})", "TABLESAMPLE_SYSTEM"),
            ("TABLESAMPLE BERNOULLI ({pct})", "TABLESAMPLE_BERNOULLI"),
            ("TABLESAMPLE SYSTEM ({pct} PERCENT)", "TABLESAMPLE_SYSTEM_PERCENT"),
            ("TABLESAMPLE ({pct})", "TABLESAMPLE_PERCENT"),
            ("SAMPLE ({pct})", "SAMPLE_PERCENT"),
            ("SAMPLE ({pct} PERCENT)", "SAMPLE_PERCENT"),
        ],
    )
    def test_table_sample_clause_valid(self, template, expected_token):
        probes = {**_MINIMAL_PROBES, "tableSampleTemplate": template}
        parsed = self._parse(probes=probes)
        assert expected_token in parsed["sql"]["clauses"]
        assert expected_token in VALID_SQL_CLAUSES

    # -- sql.queries.schemaOnly --

    @pytest.mark.parametrize("value", ["CTE", "SQLSERVER_TOP0", "ORACLE_WHERE_FALSE"])
    def test_schema_only_valid(self, value):
        probes = {**_MINIMAL_PROBES, "schemaOnly": value}
        parsed = self._parse(probes=probes)
        assert parsed["sql"]["queries"]["schemaOnly"] in VALID_SCHEMA_ONLY

    # -- sql.queries.rowCount --

    @pytest.mark.parametrize(
        "value",
        [
            "COUNT_STAR",
            "BQ_TABLES",
            "INFORMATION_SCHEMA_ROW_COUNT",
            "INFORMATION_SCHEMA_TABLES_WITH_SIZE",
            "ALL_TABLES",
        ],
    )
    def test_row_count_valid(self, value):
        probes = {**_MINIMAL_PROBES, "rowCount": value}
        parsed = self._parse(probes=probes)
        assert parsed["sql"]["queries"]["rowCount"] in VALID_ROW_COUNT

    # -- sql.queries.freshness.style --

    @pytest.mark.parametrize(
        "value",
        ["STANDARD", "DATEADD_DATEDIFF", "NUMTODSINTERVAL", "TIMESTAMP_ADD", "TIMESTAMPDIFF_DB2"],
    )
    def test_date_arithmetic_style_valid(self, value):
        probes = {**_MINIMAL_PROBES, "dateArithmeticStyle": value}
        parsed = self._parse(probes=probes)
        if "freshness" in parsed["sql"]["queries"]:
            assert parsed["sql"]["queries"]["freshness"]["style"] in VALID_DATE_ARITHMETIC_STYLE

    # -- exhaustive: every probe output → valid enum --

    def test_all_non_default_enums_valid(self):
        """With every enum set to a non-default value, all emitted values are valid."""
        probes = {
            **_MINIMAL_PROBES,
            "transactionIsolation": "SERIALIZABLE",
            "tableNameCasing": "UPPER",
            "rowLimitStyle": "TOP",
            "timestampLiteralStyle": "CAST_DATETIME2",
            "dateLiteralStyle": "TO_DATE",
            "approxCountDistinctFunction": "APPROX_COUNT_DISTINCT",
            "viewSampleFallback": "RANDOM",
            "tableSampleTemplate": "TABLESAMPLE BERNOULLI ({pct})",
            "schemaOnly": "SQLSERVER_TOP0",
            "rowCount": "ALL_TABLES",
            "dateArithmeticStyle": "DATEADD_DATEDIFF",
        }
        parsed = self._parse(probes=probes)
        config = parsed["config"]
        sql = parsed["sql"]

        assert config["transactionIsolation"] in VALID_TRANSACTION_ISOLATION
        assert config["tableNameCasing"] in VALID_TABLE_NAME_CASING
        assert config["rowLimitStyle"] in VALID_ROW_LIMIT_STYLE
        assert config["timestampLiteralStyle"] in VALID_TIMESTAMP_LITERAL_STYLE
        assert config["dateLiteralStyle"] in VALID_DATE_LITERAL_STYLE

        for fn in sql["functions"]:
            assert fn in VALID_SQL_FUNCTIONS, f"sql.functions: {fn} not valid"
        for cl in sql["clauses"]:
            assert cl in VALID_SQL_CLAUSES, f"sql.clauses: {cl} not valid"

        assert sql["queries"]["schemaOnly"] in VALID_SCHEMA_ONLY
        assert sql["queries"]["rowCount"] in VALID_ROW_COUNT
        assert sql["queries"]["freshness"]["style"] in VALID_DATE_ARITHMETIC_STYLE
