# Check Sheet Migration

`qualytics migrate` creates quality checks — and the computed tables/joins they
depend on — from a **check sheet**: a normalized tabular template (XLSX or CSV)
with one row per check or computed container. It is built for bulk migrations
from an external check catalog (a legacy DQ system, a client spreadsheet, an
audit workbook) where the checks do not yet exist in any Qualytics instance, so
there is nothing to export.

```bash
# Offline: validate the sheet, see what it would produce (no auth needed)
qualytics migrate plan --sheet wafra-week1.xlsx --show-checks

# Create everything on the target (checks land as Draft by default)
qualytics migrate apply --sheet wafra-week1.xlsx --datastore-id 12 --tag "UAT testing"

# Re-apply after sheet edits — upserts in place, keeps hand-activated checks Active
qualytics migrate apply --sheet wafra-week1.xlsx --datastore-id 12 --preserve-status
```

The pipeline is: **sheet → portable check YAML → API**. `--emit-yaml` writes the
intermediate YAML (same format as `checks export`/`checks import`), so the
converted checks can be reviewed, diffed, and version-controlled before or
instead of applying.

## The sheet

Column headers are matched case-insensitively with spaces/punctuation
normalized (`Check ID`, `check_id` and `CHECK-ID` are the same column).
Unrecognized columns are ignored with a single plan-time warning naming them —
to stamp a column into `additional_metadata`, prefix its header with
`metadata:` (see below).

### Custom metadata columns

A column headed `metadata:<key>` writes `<key>` into every produced check's
(and computed container's) `additional_metadata` — the key is taken **verbatim**
after the prefix, casing and punctuation preserved. An empty cell means the key
does not apply to that row, so one sheet can carry `metadata:X` for one subset
of rows and `metadata:Y` for another:

```csv
check_id,rule_type,container,fields,metadata:Business Domain,metadata:SLA Tier
100,notNull,orders,order_id,Treasury,
200,unique,invoices,invoice_id,,gold
```

`legacy_check_id` and `_qualytics_check_uid` are reserved (the converter sets
them from `check_id`); a `metadata:` column naming them is a plan error.

### Identity columns (every row)

| Column | Meaning |
|---|---|
| `check_id` | **Required.** Your catalog's key for the row. Duplicates are plan errors. Becomes the upsert UID (`sheet__<check_id>`) and is stamped verbatim as `additional_metadata.legacy_check_id`, so every created check traces back to its source row. |
| `kind` | Blank or `check` (default) for a quality check; `computed_table` or `computed_join` for a computed container the checks depend on. |
| `datastore` | Optional per-row target (name or numeric id). Rows without it go to every `--datastore-id` passed to `apply`; rows with it go only there. |
| `container` | For checks: the target table/view name (matched by name on the target, casing auto-corrected against the catalogue). For computed rows: the new container's name. |

### Check columns

| Column | Meaning |
|---|---|
| `rule_type` | Qualytics rule, e.g. `notNull`, `unique`, `freshness`, `existsIn`, `aggregationComparison`, `equalTo`, `between`, `matchesPattern`, `satisfiesExpression`. Rules outside the crosswalk pass through with a warning — supply their properties via `properties_json`. |
| `fields` | Comma/semicolon-separated field names. Casing is auto-corrected against the target's catalogue. |
| `description` | Check description (generated from `check_id` + rule when blank). |
| `filter` | Row-scope SparkSQL predicate (dropped with a warning on rules that reject filters, e.g. `freshness`). |
| `coverage` | 0–1 (omitted on rules without coverage support). |
| `tags` | Comma/semicolon-separated tag names; `apply --tag X` appends `X` to every row. Tags auto-create on the target. |
| `status` | `Active` or `Draft` per row; default is **Draft** so everything is reviewed before it fires. |
| `anomaly_message_field` | Field whose value becomes the anomaly message. |

### Rule properties (flat columns)

| Column | Used by | Notes |
|---|---|---|
| `value` | `freshness` (max age: raw milliseconds or shorthand `45s`, `90m`, `36h`, `7d`, `2w`), `equalTo`/`greaterThan`/`lessThan` (numeric, with `inclusive`) | |
| `min`, `max`, `inclusive_min`, `inclusive_max` | `between` (one-sided ranges narrow to `greaterThan`/`lessThan` automatically) | inclusivity defaults to true |
| `inclusive` | `equalTo`, `greaterThan`, `lessThan` | defaults to true |
| `pattern` | `matchesPattern` | regex |
| `expression` | `satisfiesExpression`, `aggregationComparison` (left-side aggregate) | SparkSQL |
| `comparison` | `aggregationComparison` | `lt`, `lte`, `eq`, `gte`, `gt` — also accepts `<`, `<=`, `=`, `>=`, `>` and long forms |
| `ref_expression` | `aggregationComparison` (right-side aggregate, evaluated on the referenced container) | |
| `ref_container` | `existsIn`, `notExistsIn`, `aggregationComparison` | referenced container **name**, resolved to an id on the target at apply time |
| `ref_field` | `existsIn`, `notExistsIn` | the referenced field's name |
| `ref_datastore` | cross-datastore references | name or numeric id; omit when the referenced container lives in the same datastore |
| `ref_filter` | `existsIn`, `aggregationComparison` | SparkSQL filter on the referenced container |
| `properties_json` | any rule | JSON object merged over the flat columns — the escape hatch for anything not listed above (e.g. `{"numeric_comparator": {"epsilon": 0.01}}`). A key set by both a flat column and the JSON with different values is a plan error. |

Required columns are validated offline per rule at `plan` time — e.g.
`freshness` requires `value`; `existsIn` requires `fields` + `ref_container` +
`ref_field`; `aggregationComparison` requires `expression` + `comparison` +
`ref_container` + `ref_expression`.

### Computed container columns

| Column | Meaning |
|---|---|
| `query` | The container's SQL. For `computed_table` this runs on the source datastore. For `computed_join` it is the join query written against the source aliases. |
| `sources` | `computed_join` only: the joined containers as `orders=o; customers=c` pairs (alias defaults to the name), or a JSON list `[{"container": "orders", "alias": "o", "where_clause": "..."}]`. Names resolve to container ids on the target at apply time. |
| `description` | Container description. |

A check row that targets a computed container declared in the same sheet just
names it in `container` — `apply` orders the phases. A `computed_join` may read
a computed table from the same sheet **if that table's row comes first**
(containers are created in declaration order).

## What apply does

1. **Container phase** (skip with `--skip-containers`): every spec is validated
   via the API's dry-run endpoint before anything is created — a validation
   failure aborts the phase. Containers are then created in declaration order,
   and after each creation the CLI waits for **that container's own profile
   operation** to finish (`--profile-timeout`, default 900s) so dependent joins
   and checks always see profiled fields. Existing same-name containers are
   skipped by default (query drift is reported); `--on-existing update` PUTs
   the sheet's definition instead. If the phase fails for a datastore, its
   check phase is skipped rather than failing one check at a time.
2. **Check phase**: container and field names are case-corrected against the
   target's catalogue, cross-references (`ref_container`, `ref_datastore`)
   resolve to ids, and checks upsert on the `sheet__<check_id>` UID — re-running
   after sheet edits updates in place instead of duplicating. Failures are
   printed, written to `--failures-log`, and do not stop the run (add
   `--strict` to exit non-zero for CI).
3. **Receipt**: the per-check mapping (sheet `check_id` → created/updated
   Qualytics check id, container, rule, status, UI link) is written to
   `--results-csv` (default `migrate-apply-results.csv`; empty string to
   skip). The terminal stays a summary — the CSV is the record to hand back
   to whoever owns the source catalog. Dry runs write nothing.

### Draft-first, activate by hand

Checks land as **Draft** by default: Draft creation skips the synchronous
dataplane validation (fast bulk loads) and gives reviewers a look before
anything fires. Activate in the product after review — and use
`--preserve-status` on re-applies so those activations are kept rather than
reset to the sheet's status.

## Timezone convention

Date logic that anchors to "now" (`CURRENT_DATE`, `NOW()`,
`current_timestamp`, `GETDATE()`, `SYSDATE`) evaluates in the engine's
timezone, which is rarely the business one. Standardize explicitly in the
sheet's SQL, e.g. Eastern Time:

```sql
WHERE file_date >= from_utc_timestamp(current_timestamp(), 'America/New_York') - INTERVAL 1 DAY
```

`migrate plan` warns on any `query`, `expression`, `ref_expression` or `filter`
that uses a now-function without a visible conversion
(`from_utc_timestamp`, `to_utc_timestamp`, `convert_timezone`, `AT TIME ZONE`).

## Example

[docs/examples/check-sheet-example.csv](examples/check-sheet-example.csv):

```csv
check_id,kind,rule_type,container,fields,value,min,max,expression,comparison,ref_expression,ref_container,ref_field,ref_datastore,query,sources,tags,description,metadata:Source System
550,,freshness,STG_FUND_POSITIONS,,36h,,,,,,,,,,,UAT testing,STG_FUND_POSITIONS loaded within 36 hours,eFront
326,,existsIn,STG_INVESTOR_POSITIONS,PORTFOLIO_ID,,,,,,,efront_portfolio_status,PORTFOLIO_ID,,,,UAT testing,Child portfolio ids exist in portfolio status,eFront
211,,aggregationComparison,efront_entities,,,,,count(distinct FUND_FAMILY_ID),eq,count(distinct FUND_FAMILY_ID),secmaster_mappings,,warehouse,,,UAT testing,Fund family count matches SecMaster mappings,SecMaster
770,computed_table,,re_fund_recon,,,,,,,,,,,"SELECT metric, delta FROM (SELECT count(*) AS row_count_delta FROM a) UNPIVOT (delta FOR metric IN (row_count_delta))",,,RE fund reconciliation metrics (one row per metric),
771,,equalTo,re_fund_recon,delta,0,,,,,,,,,,,UAT testing,Reconciliation delta must be exactly zero,Synapse
```

Workflow:

```bash
qualytics migrate plan  --sheet sheet.xlsx --show-checks   # review offline
qualytics migrate apply --sheet sheet.xlsx --datastore-id 12 --dry-run
qualytics migrate apply --sheet sheet.xlsx --datastore-id 12
# review Drafts in the product, activate, then on later edits:
qualytics migrate apply --sheet sheet.xlsx --datastore-id 12 --preserve-status
```

## migrate vs the other bulk paths

| Path | Use when |
|---|---|
| `migrate apply` | Checks live in an external catalog/spreadsheet; computed containers and cross-references involved; you want offline validation and Draft-first review. |
| `checks export` / `checks import` | The checks already exist in another Qualytics instance. |
| `dbt import` | The checks are dbt tests. |
| `containers import` | Legacy bulk computed-table load with the fixed 3-column layout and auto-generated `satisfiesExpression` checks. Prefer a check sheet: it also handles joins, updates, and arbitrary dependent checks. |
| `config export` / `config import` | Whole-datastore config-as-code trees. Note `config import` syncs every datastore it touches. |
