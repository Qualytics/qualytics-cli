# Align CLI YAML Output to Dataplane v2 Schema

## Group 1: Restructure `_build_yaml()` to emit three top-level sections
- [x] Wrap all config fields under a `config:` key
- [x] Wrap all SQL capability fields under a `sql:` key with `functions`, `clauses`, `queries` sub-keys
- [x] Keep `dialectClass` at top level (already correct)

## Group 2: Rename config fields to match dataplane schema
- [x] `rowLimitSyntax` → `rowLimitStyle` (valid values: `LIMIT`, `TOP`, `ROWNUM`)
- [x] `subqueryRequiresAlias` → `subqueryAlias`
- [x] `validationQuery` → `connectionTest`
- [x] `tableNameCasing` values: `upper` → `UPPER`, `lower` → `LOWER`, `asis` → `AS_IS`

## Group 3: Restructure URL fields into `config.url` sub-object
- [x] `jdbcUrlTemplate` → `config.url.template`
- [x] `jdbcUrlStaticParams` → `config.url.staticParams`
- [x] `jdbcUrlConditionalParams` → `config.url.conditionalParams` (each item: `{key: ..., param: ...}`)
- [x] `jdbcUrlAuthVariants` → `config.url.authVariants` using full DriverAuthVariant structure (each value: object with optional keys `urlTemplate`, `staticParams`, `conditionalParams`, `connectionProperties`, `connectionPropertyMappings`)
- [x] Add support for `config.url.paramSeparator`

## Group 4: Restructure SQL capabilities into `sql` section
- [ ] Map `approxCountDistinctFunction` → entry in `sql.functions` list (closed vocab: `APPROX_COUNT_DISTINCT`, `APPROX_DISTINCT`, `RANDOM`, `RAND`, `NEWID`, `DBMS_RANDOM_VALUE`)
- [ ] Map `viewSampleFallback` → entry in `sql.functions`
- [ ] Map `tableSampleTemplate` → entry in `sql.clauses` (closed vocab: `TABLESAMPLE_SYSTEM`, `TABLESAMPLE_SYSTEM_PERCENT`, `TABLESAMPLE_BERNOULLI`, `TABLESAMPLE_PERCENT`, `TABLESAMPLE_ROWS`, `SAMPLE_PERCENT`, `SAMPLE_ROWS`, `LIMIT`, `OFFSET_FETCH`, `ROWNUM`)
- [ ] Map `FETCH_FIRST` rowLimit → `OFFSET_FETCH` in `sql.clauses` (NOT a rowLimitStyle)
- [ ] Map `rowCountQueryStyle`, `schemaOnlyQueryStyle`, date arithmetic templates → `sql.queries` using QuerySlot keys: `nullCheck`, `schemaOnly`, `rowCount`, `volume`, `freshness`, `partitionColumn`, `lineage`

## Group 5: Remove/remap fields not in dataplane schema
- [ ] Remove or remap: `maxPartitionParallelism`, `dataSizeLimit`, `schemaExistenceQueryStyle`
- [ ] Verify no other flat fields will be rejected by strict parser

## Group 6: Add missing optional fields with smart defaults
- [ ] `config.networkCapable` (default: `true`)
- [ ] `config.readOnly` (default: `false`)
- [ ] `config.defaultInsertBatchSize` (optional)
- [ ] `config.supportsLongLimit` (default: `false`)
- [ ] `config.connectionPropertyMappings` (optional)
- [ ] `config.connectionSpec.fields[].aliases` (optional)
- [ ] `config.connectionSpec.fields[].dependsOnValues` (plural, optional)

## Group 7: Update the Java probe and LLM resolver
- [ ] Update Java probe output parsing to feed into new v2 structure
- [ ] Update LLM prompt/resolver to produce field names matching v2 schema
- [ ] Update TODO comment generation to reference correct v2 field names

## Group 8: Update example YAML files
- [ ] Regenerate or manually update `dist/META-INF/jdbc-drivers/mongodb.yaml` to v2 format
- [ ] Regenerate or manually update `dist/META-INF/jdbc-drivers/redshift2.yaml` to v2 format

## Group 9: End-to-end validation
- [ ] Review entire `_build_yaml()` flow for any remaining flat fields
- [ ] Ensure all enum values use exact case-sensitive dataplane values
- [ ] Verify `connectionSpec` nesting is correct under `config`
