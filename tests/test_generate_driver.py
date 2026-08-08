"""Tests for qualytics.cli.generate_driver — YAML generation and helpers."""

import re

import pytest
import yaml

from qualytics.cli.generate_driver import (
    _SPARK_BUILTIN_DIALECTS,
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
        """Only config, sql and dialectClass are accepted at the top level — the parser's
        TopLevelKnownKeys. prefix/className are config fields, not top-level keys."""
        _, parsed, _, _ = self._parse()
        assert set(parsed.keys()) <= {"config", "sql", "dialectClass"}
        assert "config" in parsed
        assert isinstance(parsed["config"], dict)
        assert "sql" in parsed
        assert isinstance(parsed["sql"], dict)

    def test_identity_fields_live_under_config(self):
        _, parsed, _, _ = self._parse()
        assert parsed["config"]["prefix"] == "testdb"
        assert parsed["config"]["className"] == "com.example.Driver"
        assert "prefix" not in parsed
        assert "className" not in parsed

    def test_required_config_keys_always_emitted(self):
        """These are `required(...)` in parseConfig — they must be emitted even when the
        probed value equals the DriverConfig default, or the file fails to parse."""
        _, parsed, _, _ = self._parse()
        config = parsed["config"]
        for key in (
            "prefix",
            "className",
            "displayName",
            "tableNameCasing",
            "transactionIsolation",
            "url",
            "connectionSpec",
        ):
            assert key in config, f"required config key '{key}' was omitted"
        # AS_IS / READ_UNCOMMITTED are the DriverConfig defaults but still required keys.
        assert config["tableNameCasing"] == "AS_IS"
        assert config["transactionIsolation"] == "READ_UNCOMMITTED"

    def test_no_explicit_nulls_anywhere(self):
        """`optional` rejects an explicit null ("omit the key to use the default"), and
        `required` rejects a null value — so no emitted key may carry one."""

        def walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    assert v is not None, f"explicit null at {path}{k}"
                    walk(v, f"{path}{k}.")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    assert v is not None, f"explicit null at {path}[{i}]"
                    walk(v, f"{path}[{i}].")

        # Minimal probes exercise every "undetected" branch, where nulls used to leak.
        for probes in (_MINIMAL_PROBES, {"className": "com.example.D"}):
            _, parsed, _, _ = self._parse(probes=probes)
            walk(parsed)

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
        # paramSeparator only accepts ';' or ','; the default query style (?/&) is not
        # declarable, so the key must not be emitted for it.
        assert "paramSeparator" not in url

    def test_param_separator_never_emitted_as_ampersand(self):
        raw, parsed, _, _ = self._parse()
        assert "paramSeparator: '&'" not in raw
        assert parsed["config"]["url"].get("paramSeparator") is None

    def test_url_template_always_present_and_non_null(self):
        """config.url.template is required. A probe URL the deriver can't match (Oracle's
        `@host:port/service` form) must still yield a usable template, not null."""
        _, parsed, _, _ = self._parse(url="jdbc:oracleish:thin:@host:1521/svc")
        template = parsed["config"]["url"]["template"]
        assert template
        # Every placeholder must be backed by a connectionSpec field name.
        field_names = {f["name"] for f in parsed["config"]["connectionSpec"]["fields"]}
        placeholders = set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template))
        assert placeholders <= field_names, (
            f"template placeholders {placeholders - field_names} have no connectionSpec field"
        )

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

    def test_default_insert_batch_size_commented_not_null(self):
        """`defaultInsertBatchSize: null` is a parse error — the unset case must be a
        commented-out stub, not an emitted key."""
        raw, parsed, _, _ = self._parse()
        assert "defaultInsertBatchSize" not in parsed["config"]
        assert "# defaultInsertBatchSize:" in raw

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

    def test_query_slots_are_never_emitted_as_strategy_tokens(self):
        """Every sql.queries value is a full SQL statement, never a strategy token. A token
        like `schemaOnly: PG_CTE` PARSES (it is a non-empty, placeholder-free, keyword-free
        string) and is then sent to the database verbatim at query time — so the generator
        must leave the slots empty and carry the probed style as a comment only."""
        probes = {
            **_MINIMAL_PROBES,
            "schemaOnly": "PG_CTE",
            "rowCount": "BQ_TABLES",
        }
        raw, parsed, _, _ = self._parse(probes=probes)
        assert parsed["sql"]["queries"] == {}
        # The probe result is preserved for the operator, but only inside a comment.
        assert "# rowCount=BQ_TABLES" in raw
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert not stripped.startswith("schemaOnly:"), line
            assert not stripped.startswith("rowCount:"), line

    def test_sql_capabilities_with_detected_values(self):
        probes = {
            **_MINIMAL_PROBES,
            "schemaOnly": "SQLSERVER_TOP0",
            "approxCountDistinctFunction": "APPROX_COUNT_DISTINCT",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        functions = parsed["sql"]["functions"]
        # schemaExistenceQueryStyle is not part of the schema — should NOT appear
        assert "schemaExistenceQueryStyle" not in parsed["sql"]["queries"]
        assert "APPROX_COUNT_DISTINCT" in functions

    def test_sql_functions_with_detected_values(self):
        probes = {**_MINIMAL_PROBES, "viewSampleFallback": "RANDOM"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "RANDOM" in parsed["sql"]["functions"]

    def test_rand_view_sample_fallback_is_emitted(self):
        """RAND is a real detected function (MySQL), not an omittable default — it must appear."""
        probes = {**_MINIMAL_PROBES, "viewSampleFallback": "RAND"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "RAND" in parsed["sql"]["functions"]

    def test_dbms_random_value_view_sample_fallback_is_emitted(self):
        """Oracle's DBMS_RANDOM_VALUE round-trips into sql.functions."""
        probes = {**_MINIMAL_PROBES, "viewSampleFallback": "DBMS_RANDOM_VALUE"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "DBMS_RANDOM_VALUE" in parsed["sql"]["functions"]

    def test_view_sample_fallback_null_emits_no_function(self):
        """When the probe detects no random function, no entry is emitted."""
        probes = {**_MINIMAL_PROBES, "viewSampleFallback": "null"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["sql"]["functions"] == []

    def test_view_sample_fallback_missing_emits_no_function(self):
        """Absent viewSampleFallback probe key → no function (no RAND sentinel guess)."""
        probes = {k: v for k, v in _MINIMAL_PROBES.items() if k != "viewSampleFallback"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["sql"]["functions"] == []

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

    def test_sql_clauses_declares_limit_row_idiom(self):
        """The LIMIT row-limit idiom is declared in sql.clauses (no sample tokens here)."""
        _, parsed, _, _ = self._parse()
        assert parsed["sql"]["clauses"] == ["LIMIT"]

    def test_limit_row_idiom_in_clauses(self):
        """rowLimitStyle LIMIT → LIMIT token in sql.clauses (paired with a random function)."""
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": "LIMIT"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "LIMIT" in parsed["sql"]["clauses"]

    def test_top_row_idiom_maps_to_offset_fetch_clause(self):
        """rowLimitStyle TOP → OFFSET_FETCH token in sql.clauses (SQL Server sampling idiom)."""
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": "TOP"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "OFFSET_FETCH" in parsed["sql"]["clauses"]
        # TOP still appears as the rowLimitStyle config field
        assert parsed["config"]["rowLimitStyle"] == "TOP"

    def test_rownum_row_idiom_maps_to_rownum_clause(self):
        """rowLimitStyle ROWNUM → ROWNUM token in sql.clauses (Oracle sampling idiom)."""
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": "ROWNUM"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert "ROWNUM" in parsed["sql"]["clauses"]

    def test_row_idiom_clause_with_random_function_form_sampling_pair(self):
        """Redshift shape: RANDOM function + LIMIT clause — the view-sampling pair the renderer needs."""
        probes = {
            **_MINIMAL_PROBES,
            "rowLimitStyle": "LIMIT",
            "viewSampleFallback": "RANDOM",
        }
        _, parsed, _, _ = self._parse(probes=probes)
        assert "RANDOM" in parsed["sql"]["functions"]
        assert "LIMIT" in parsed["sql"]["clauses"]

    def test_retired_date_arithmetic_probes_are_never_emitted(self):
        """dateArithmeticStyle and the range-split templates were retired with the
        distribution probe (dataplane QUA-2282). Even when a stale probe payload still
        carries them, nothing may reach the YAML — `config.dateArithmeticStyle` is now an
        unknown-key parse error in the dataplane."""
        probes = {
            **_MINIMAL_PROBES,
            "dateArithmeticStyle": "DATEADD_DATEDIFF",
            "intervalCalcDatetimeTimestampTemplate": "DATEADD(second, ...)",
            "intervalCalcDatetimeDateTemplate": "DATEADD(day, ...)",
            "upperBoundDatetimeTimestampTemplate": "DATEADD(second, ...)",
            "upperBoundDatetimeDateTemplate": "DATEADD(day, ...)",
        }
        raw, parsed, _, _ = self._parse(probes=probes)
        retired = {
            "dateArithmeticStyle",
            "intervalCalcDatetimeTimestampTemplate",
            "intervalCalcDatetimeDateTemplate",
            "upperBoundDatetimeTimestampTemplate",
            "upperBoundDatetimeDateTemplate",
        }
        for name in retired:
            assert name not in raw, f"retired field '{name}' leaked into the YAML"
        assert "freshness" not in parsed["sql"]["queries"]

    def test_null_check_query_slot_is_never_emitted(self):
        """nullCheck was removed from the dataplane QuerySlot vocabulary; declaring it is
        now an `unknown query slot` parse error."""
        raw, parsed, _, _ = self._parse()
        assert "nullCheck" not in raw
        assert "nullCheck" not in parsed["sql"]["queries"]

    def test_query_slot_documentation_lists_the_current_vocabulary(self):
        """The emitted slot guidance must match the dataplane QuerySlot set — nullCheck was
        removed, and the remaining six each have a documented placeholder allow-set."""
        raw, _, _, _ = self._parse()
        assert "nullCheck" not in raw
        for slot in (
            "schemaOnly",
            "rowCount",
            "volume",
            "freshness",
            "partitionColumn",
            "lineage",
        ):
            assert slot in raw, f"slot '{slot}' missing from the generated guidance"

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

    def test_schema_field_emitted_when_supported(self):
        """When the probe reports the DB has schemas, an optional schema field is emitted."""
        probes = {**_MINIMAL_PROBES, "supportsSchemas": True}
        _, parsed, _, _ = self._parse(probes=probes)
        fields = parsed["config"]["connectionSpec"]["fields"]
        schema_field = next((f for f in fields if f["name"] == "schema"), None)
        assert schema_field is not None, "schema field should be present"
        assert schema_field["required"] is False
        assert schema_field["fieldType"] == "string"
        # Ordered between database and username
        names = [f["name"] for f in fields]
        assert names.index("schema") > names.index("database")
        assert names.index("schema") < names.index("username")

    def test_schema_field_absent_when_unsupported(self):
        """No schema field when the DB does not organise tables into schemas (e.g. MySQL)."""
        probes = {**_MINIMAL_PROBES, "supportsSchemas": False}
        _, parsed, _, _ = self._parse(probes=probes)
        names = [f["name"] for f in parsed["config"]["connectionSpec"]["fields"]]
        assert "schema" not in names

    def test_schema_field_absent_when_probe_key_missing(self):
        """Backward-compatible: absent supportsSchemas probe key → no schema field."""
        _, parsed, _, _ = self._parse()  # _MINIMAL_PROBES has no supportsSchemas key
        names = [f["name"] for f in parsed["config"]["connectionSpec"]["fields"]]
        assert "schema" not in names

    def test_schema_field_string_probe_value_truthy(self):
        """A string 'true' from the JSON probe is parsed as a boolean."""
        probes = {**_MINIMAL_PROBES, "supportsSchemas": "true"}
        _, parsed, _, _ = self._parse(probes=probes)
        names = [f["name"] for f in parsed["config"]["connectionSpec"]["fields"]]
        assert "schema" in names

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

    def test_fetch_first_is_a_row_limit_style(self):
        """FETCH_FIRST is a rowLimitStyle arm of its own (Db2), not clause-only."""
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": "FETCH_FIRST"}
        _, parsed, _, _ = self._parse(probes=probes)
        assert parsed["config"]["rowLimitStyle"] == "FETCH_FIRST"

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
            "rowLimitStyle": "TOP",
            "tableSampleTemplate": "TABLESAMPLE BERNOULLI ({pct})",
            "viewSampleFallback": "RANDOM",
            "timestampLiteralStyle": "CAST_DATETIME2",
            "dateLiteralStyle": "TO_DATE",
            "schemaOnly": "SQLSERVER_TOP0",
            "rowCount": "ALL_TABLES",
        }
        _, parsed, _, _ = self._parse(
            probes=probes, dialect_class="com.example.Dialect$"
        )
        # Only these keys are allowed at the top level (parser TopLevelKnownKeys)
        allowed_top_keys = {"dialectClass", "config", "sql"}
        extra = set(parsed.keys()) - allowed_top_keys
        assert not extra, (
            f"Unexpected top-level keys (should be in config or sql): {extra}"
        )

        # v1-style flat field names must not appear anywhere in the parsed output
        v1_flat_names = {
            "jdbcUrlTemplate",
            "jdbcUrlStaticParams",
            "jdbcUrlConditionalParams",
            "jdbcUrlAuthVariants",
            "rowLimitSyntax",
            "subqueryRequiresAlias",
            "validationQuery",
            "rowCountQueryStyle",
            "schemaOnlyQueryStyle",
            "schemaExistenceQueryStyle",
            "maxPartitionParallelism",
            "dataSizeLimit",
            "approxCountDistinctFunction",
            "viewSampleFallback",
            "tableSampleTemplate",
            "dateArithmeticStyle",
            "intervalCalcDatetimeTimestampTemplate",
            "intervalCalcDatetimeDateTemplate",
            "upperBoundDatetimeTimestampTemplate",
            "upperBoundDatetimeDateTemplate",
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
        # Query slots stay empty — probed styles are hints, not SQL (see
        # test_query_slots_are_never_emitted_as_strategy_tokens).
        assert sql["queries"] == {}


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
            "connectionTest": {
                "value": "SELECT 1 FROM DUAL",
                "rationale": "Oracle convention",
            },
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
        [
            "NONE",
            "READ_UNCOMMITTED",
            "READ_COMMITTED",
            "REPEATABLE_READ",
            "SERIALIZABLE",
        ],
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

    @pytest.mark.parametrize("value", ["LIMIT", "TOP", "ROWNUM", "FETCH_FIRST"])
    def test_row_limit_style_valid(self, value):
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": value}
        parsed = self._parse(probes=probes)
        emitted = parsed["config"].get("rowLimitStyle", "LIMIT")
        assert emitted in VALID_ROW_LIMIT_STYLE

    def test_fetch_first_also_declares_offset_fetch_clause(self):
        """FETCH_FIRST is a rowLimitStyle AND pairs with the OFFSET_FETCH clause token."""
        probes = {**_MINIMAL_PROBES, "rowLimitStyle": "FETCH_FIRST"}
        parsed = self._parse(probes=probes)
        assert parsed["config"]["rowLimitStyle"] == "FETCH_FIRST"
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

    # -- sql.queries: probe styles are hints, never emitted values --

    @pytest.mark.parametrize(
        "key,value",
        [
            ("schemaOnly", "CTE"),
            ("schemaOnly", "SQLSERVER_TOP0"),
            ("schemaOnly", "ORACLE_WHERE_FALSE"),
            ("rowCount", "COUNT_STAR"),
            ("rowCount", "BQ_TABLES"),
            ("rowCount", "INFORMATION_SCHEMA_ROW_COUNT"),
            ("rowCount", "INFORMATION_SCHEMA_TABLES_WITH_SIZE"),
            ("rowCount", "ALL_TABLES"),
        ],
    )
    def test_query_style_probes_never_reach_sql_queries(self, key, value):
        """These closed vocabularies describe what the probe observed. They are NOT SQL, and
        sql.queries only accepts SQL — so no probed style may be emitted as a slot value."""
        probes = {**_MINIMAL_PROBES, key: value}
        parsed = self._parse(probes=probes)
        assert parsed["sql"]["queries"] == {}

    def test_spark_builtin_dialects_have_no_object_suffix(self):
        """Spark's built-in dialects are case CLASSES. `PostgresDialect$` resolves to the
        companion object (a scala.runtime.AbstractFunction0), which does not extend
        JdbcDialect — CatalogValidation.dialectClassErrors then rejects the whole catalog
        with "class does not extend org.apache.spark.sql.jdbc.JdbcDialect". Qualytics' own
        dialects are Scala objects and DO need the '$'; the conventions are not the same."""
        for prefix, fqcn in _SPARK_BUILTIN_DIALECTS.items():
            assert fqcn.startswith("org.apache.spark.sql.jdbc."), (prefix, fqcn)
            assert not fqcn.endswith("$"), (
                f"{prefix} -> {fqcn}: Spark built-in dialects are classes, drop the '$'"
            )

    def test_schema_only_and_row_count_vocabularies_still_documented(self):
        """The vocabularies remain the probe's contract even though they are no longer
        emitted, so keep them pinned against the probe's own outputs."""
        assert "CTE" in VALID_SCHEMA_ONLY
        assert "COUNT_STAR" in VALID_ROW_COUNT

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

        assert sql["queries"] == {}
