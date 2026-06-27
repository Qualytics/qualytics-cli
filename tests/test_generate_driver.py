"""Tests for qualytics.cli.generate_driver — YAML generation and helpers."""

import yaml

from qualytics.cli.generate_driver import (
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
    "tableNameCasing": "asis",
    "rowLimitSyntax": "LIMIT",
    "subqueryRequiresAlias": True,
    "timestampLiteralStyle": "PLAIN",
    "dateLiteralStyle": "PLAIN",
    "schemaOnlyQueryStyle": "CTE",
    "validationQuery": "SELECT 1",
    "viewSampleFallback": "RAND",
    "rowCountQueryStyle": "COUNT_STAR",
    "schemaExistenceQueryStyle": "NONE",
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

    def test_config_contains_url_fields(self):
        _, parsed, _, _ = self._parse()
        config = parsed["config"]
        assert "jdbcUrlTemplate" in config
        assert "jdbcUrlStaticParams" in config
        assert "jdbcUrlConditionalParams" in config
        assert "jdbcUrlAuthVariants" in config

    def test_config_contains_connection_spec(self):
        _, parsed, _, _ = self._parse()
        assert "connectionSpec" in parsed["config"]
        cs = parsed["config"]["connectionSpec"]
        assert cs["supportsEnrichment"] is False
        assert isinstance(cs["fields"], list)
        assert any(f["name"] == "host" for f in cs["fields"])

    def test_config_contains_performance_fields(self):
        _, parsed, _, _ = self._parse()
        config = parsed["config"]
        assert "maxPartitionParallelism" in config
        assert "dataSizeLimit" in config

    def test_config_contains_connectivity_fields(self):
        _, parsed, _, _ = self._parse()
        config = parsed["config"]
        assert "connectionProperties" in config
        assert "sessionInitStatements" in config

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
        # functions and clauses may be None when all values are defaults

    def test_sql_capabilities_under_sql_queries(self):
        """SQL query-style fields should be under sql.queries, not top-level or config."""
        probes = {**_MINIMAL_PROBES, "schemaOnlyQueryStyle": "PG_CTE"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["sql"]["queries"]["schemaOnlyQueryStyle"] == "PG_CTE"
        assert "schemaOnlyQueryStyle" not in parsed
        assert "schemaOnlyQueryStyle" not in parsed.get("config", {})

    def test_sql_capabilities_with_detected_values(self):
        probes = {
            **_MINIMAL_PROBES,
            "schemaOnlyQueryStyle": "SQLSERVER_TOP0",
            "dateArithmeticStyle": "DATEADD_DATEDIFF",
            "schemaExistenceQueryStyle": "INFORMATION_SCHEMA",
            "approxCountDistinctFunction": "APPROX_COUNT_DISTINCT",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        queries = parsed["sql"]["queries"]
        functions = parsed["sql"]["functions"]
        assert queries["schemaOnlyQueryStyle"] == "SQLSERVER_TOP0"
        assert queries["dateArithmeticStyle"] == "DATEADD_DATEDIFF"
        assert queries["schemaExistenceQueryStyle"] == "INFORMATION_SCHEMA"
        assert functions["approxCountDistinctFunction"] == "APPROX_COUNT_DISTINCT"

    def test_sql_functions_with_detected_values(self):
        probes = {**_MINIMAL_PROBES, "viewSampleFallback": "RANDOM"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["sql"]["functions"]["viewSampleFallback"] == "RANDOM"

    def test_sql_clauses_with_detected_values(self):
        probes = {
            **_MINIMAL_PROBES,
            "tableSampleTemplate": "TABLESAMPLE SYSTEM ({pct})",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        assert (
            parsed["sql"]["clauses"]["tableSampleTemplate"]
            == "TABLESAMPLE SYSTEM ({pct})"
        )

    def test_date_templates_under_sql_queries(self):
        probes = {
            **_MINIMAL_PROBES,
            "intervalCalcDatetimeTimestampTemplate": "DATEADD(second, ...)",
            "upperBoundDatetimeDateTemplate": "DATEADD(day, ...)",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        queries = parsed["sql"]["queries"]
        assert queries["intervalCalcDatetimeTimestampTemplate"] == "DATEADD(second, ...)"
        assert queries["upperBoundDatetimeDateTemplate"] == "DATEADD(day, ...)"
        assert "intervalCalcDatetimeTimestampTemplate" not in parsed
        assert "intervalCalcDatetimeTimestampTemplate" not in parsed.get("config", {})

    def test_config_fields_not_at_top_level(self):
        """Config fields should NOT appear at the top level."""
        _, parsed, _, _ = self._parse()
        for key in [
            "displayName",
            "defaultPort",
            "maxPartitionParallelism",
            "connectionProperties",
            "jdbcUrlTemplate",
            "connectionSpec",
        ]:
            assert key not in parsed, f"{key} should be in config, not top-level"

    def test_non_default_transaction_isolation_in_config(self):
        probes = {**_MINIMAL_PROBES, "transactionIsolation": "SERIALIZABLE"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["config"]["transactionIsolation"] == "SERIALIZABLE"

    def test_non_default_table_name_casing_in_config(self):
        probes = {**_MINIMAL_PROBES, "tableNameCasing": "lower"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["config"]["tableNameCasing"] == "LOWER"

    def test_non_default_row_limit_in_config(self):
        probes = {**_MINIMAL_PROBES, "rowLimitSyntax": "TOP"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["config"]["rowLimitStyle"] == "TOP"

    def test_validation_query_in_config(self):
        probes = {**_MINIMAL_PROBES, "validationQuery": "SELECT 1 FROM DUAL"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["config"]["connectionTest"] == "SELECT 1 FROM DUAL"

    def test_yaml_parses_as_valid_yaml(self):
        content, _, _, _ = self._parse()
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)

    def test_int_max_data_size_for_redshift(self):
        content, _, _ = _build_yaml(
            "redshift",
            _MINIMAL_PROBES,
            "jdbc:redshift://host:5439/db",
        )
        parsed = yaml.safe_load(content)
        assert parsed["config"]["dataSizeLimit"] == "INT_MAX"


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
        yaml_content = "  maxPartitionParallelism: 10  # TODO: max partitions\n"
        todos = _collect_todo_fields(yaml_content)
        assert len(todos) == 1
        assert todos[0][0] == "maxPartitionParallelism"
        assert todos[0][1] == "10"

    def test_collects_both_levels(self):
        yaml_content = (
            "dialectClass: null  # TODO: Spark dialect\n"
            "config:\n"
            "  dataSizeLimit: LONG_MAX  # TODO: data size\n"
            "  displayName: TestDB  # auto-detected\n"
        )
        todos = _collect_todo_fields(yaml_content)
        assert len(todos) == 2
        names = [t[0] for t in todos]
        assert "dialectClass" in names
        assert "dataSizeLimit" in names

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
            "  maxPartitionParallelism: 10  # TODO: max partitions\n"
            "  displayName: TestDB  # auto-detected\n"
        )
        suggestions = {
            "maxPartitionParallelism": {"value": 4, "rationale": "Low concurrency"},
        }
        updated, count = _apply_llm_suggestions(yaml_content, suggestions)
        assert count == 1
        assert "  maxPartitionParallelism: 4  # LLM-suggested:" in updated

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
