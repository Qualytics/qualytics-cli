# dbt Migration

Convert an existing dbt test suite into Qualytics quality checks. Point the CLI at a compiled `manifest.json`; conversion happens in memory and the checks upsert into a datastore.

## Commands

| Command | Description |
|---------|-------------|
| `dbt plan` | Preview what a manifest would migrate to (offline, no auth) |
| `dbt import` | Convert a manifest and import the checks (upsert) |

## Prerequisites

1. A compiled dbt manifest — `dbt compile` writes `target/manifest.json`.
2. **The target datastore must already be catalogued.** Checks reference containers and fields by name, resolved to IDs at import. Run `qualytics operations catalog --datastore-id N` first.

Only `manifest.json` is needed. It carries no database credentials (those live in `profiles.yml`, which dbt never compiles into the manifest), but it does include compiled SQL and full schema lineage — treat it like source code.

## Plan

```bash
qualytics dbt plan --manifest target/manifest.json
qualytics dbt plan --manifest target/manifest.json --show-checks
```

```
    dbt → Qualytics coverage
┏━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━┓
┃ Tier      ┃ Tests ┃ Lands as ┃
┡━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━┩
│ direct    │    19 │ Active   │
│ normalize │     6 │ Draft    │
│ manual    │     3 │ Draft    │
│ total     │    28 │          │
└───────────┴───────┴──────────┘
```

`plan` never constructs an API client, so it works offline and in CI without credentials.

## Import

```bash
# Preview
qualytics dbt import --manifest target/manifest.json --datastore-id 42 --dry-run

# Apply
qualytics dbt import --manifest target/manifest.json --datastore-id 42

# Also write the converted YAML for git / review
qualytics dbt import --manifest target/manifest.json --datastore-id 42 \
  --emit-yaml ./qualytics-config/checks/
```

| Option | Description |
|--------|-------------|
| `--datastore-id` | Target datastore (repeat for multiple) |
| `--manifest`, `-m` | Path to `manifest.json` (default `target/manifest.json`) |
| `--dry-run` | Preview creates/updates without writing |
| `--container-map` | Override a container name: `model=container` (repeatable) |
| `--container-case` | Force container name case: `upper` or `lower` |
| `--preserve-status` | Omit `status` so re-imports keep what was set in the product |
| `--status` | Force every check to `Active` or `Draft`, overriding the tier default |
| `--emit-yaml` | Also write the converted checks to a directory |

`--status` and `--preserve-status` are mutually exclusive.

## Migration tiers

Every dbt test converts. Tiers grade **effort**, not feasibility.

| Tier | Meaning | Lands as |
|------|---------|----------|
| `direct` | Deterministic 1:1 mapping | `Active` |
| `normalize` | Mapped, but a parameter needs a human eye | `Draft` |
| `manual` | Custom SQL — the expression must be authored | `Draft` |

Nothing is skipped. An unrecognized generic test or a singular SQL test still produces a check, as a `satisfiesExpression` in `Draft` with the dbt source recorded in `additional_metadata`, so a reviewer adapts it rather than going back to the dbt project to find it.

### Status is yours to set

The tier → status mapping above is the **default, not a policy**. `--status` overrides it wholesale:

```bash
# review everything before anything fires
qualytics dbt import -m target/manifest.json --datastore-id 42 --status Draft

# activate everything, including checks that need editing
qualytics dbt import -m target/manifest.json --datastore-id 42 --status Active
```

The default exists because `manual` checks carry an empty `expression`, and several `normalize` rules (`volumetric`, `freshness`, `distinctCount`, `metric`) are created with empty properties — dbt's kwargs don't carry a window, interval, or bound. Those checks are unlikely to evaluate meaningfully until edited. `--status Active` prints how many fall into that group and then does what you asked.

### Tests that become two checks

A few dbt tests assert two things at once, and split:

| dbt test | Becomes |
|----------|---------|
| `expect_column_value_lengths_to_be_between` | `minLength` + `maxLength` |
| `expect_column_value_lengths_to_equal` | `minLength` + `maxLength` (same value) |

Each half gets its own check with the UID suffixed by its rule type (`…__minlength`, `…__maxlength`), so both upsert independently. A one-sided dbt test emits only the half it specifies — `min_value` alone produces just a `minLength`. Because of this, `plan` reports check count and dbt test count separately when they differ.

## Idempotency

Each check's `_qualytics_check_uid` is derived from the dbt node's `unique_id`:

```yaml
additional_metadata:
  _qualytics_check_uid: dbt__test_jaffle_not_null_stg_orders_order_id_a1b2c3
  dbt_unique_id: test.jaffle.not_null_stg_orders_order_id.a1b2c3
  dbt_test: not_null
```

Re-running after the dbt suite changes updates checks in place rather than duplicating them. This deliberately does **not** use the `container__rule__fields` scheme that `checks export` uses: several dbt tests routinely share a container/rule/field triple (multiple singular tests on one model, two `expression_is_true` on one column), and the importer upserts on UID collision — so a shared UID would silently discard a test.

### Status on re-import

By default `import` sets `status` from the tier, which means a re-import resets a check someone activated in the product back to `Draft`. Two ways to handle it:

- **Config-as-code** — treat the YAML as the source of truth. Activate by editing `status` in the emitted file, not in the UI.
- **`--preserve-status`** — omit `status` entirely so the importer keeps whatever the check currently has.

## Container name resolution

Container names come from the dbt model's `alias` (falling back to `name`), because Qualytics catalogues containers from the warehouse rather than from dbt. When those differ:

```bash
# Snowflake uppercases identifiers
qualytics dbt import -m target/manifest.json --datastore-id 42 --container-case upper

# Explicit override
qualytics dbt import -m target/manifest.json --datastore-id 42 \
  --container-map stg_orders=ORDERS_RAW --container-map fct_sales=SALES_FACT
```

A `Container 'x' not found` error usually means the datastore has not been catalogued, or the warehouse table name differs from dbt's alias.

## Supported dbt tests

Native dbt, `dbt_utils`, and `dbt_expectations` generic tests are mapped in `qualytics/services/dbt.py` (`DBT_RULE_MAP`). Highlights:

| dbt test | Qualytics rule | Tier |
|----------|----------------|------|
| `not_null` | `notNull` | direct |
| `unique` | `unique` | direct |
| `accepted_values` | `expectedValues` | direct |
| `relationships` | `existsIn` | direct |
| `dbt_utils.accepted_range` | `between` | direct |
| `dbt_utils.expression_is_true` | `satisfiesExpression` | normalize |
| `dbt_expectations.expect_column_values_to_match_regex` | `matchesPattern` | direct |
| `dbt_expectations.expect_table_row_count_to_be_between` | `volumetric` | normalize |
| `dbt_expectations.expect_row_values_to_have_recent_data` | `freshness` | normalize |
| `dbt_expectations.expect_column_value_lengths_to_be_between` | `minLength` + `maxLength` | direct |
| singular (bespoke SQL) tests | `satisfiesExpression` | manual |
| anything unrecognized | `satisfiesExpression` | manual |

## CI

```yaml
- run: dbt compile
- run: qualytics dbt plan --manifest target/manifest.json
- run: qualytics dbt import --manifest target/manifest.json --datastore-id ${{ vars.DS_ID }} --dry-run
```

`import` exits non-zero when any check fails to import, so a broken container mapping fails the build.
