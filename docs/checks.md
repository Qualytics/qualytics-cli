# Quality Checks

Quality checks define data validation rules that run against containers during scan operations. Checks can be created individually or in bulk from YAML files.

## Commands

| Command | Description |
|---------|-------------|
| `checks create` | Create checks from a YAML/JSON file (single or bulk) |
| `checks update` | Update a check from a YAML/JSON file |
| `checks get` | Get a single check by `--check-id` |
| `checks list` | List checks for a `--datastore-id`, filterable by container, tag, status |
| `checks delete` | Delete check(s) by `--check-id` or `--ids` (bulk) |
| `checks export` | Export checks to a directory (one YAML file per check, by container) |
| `checks import` | Import checks with upsert to one or more `--datastore-id` targets |
| `checks export-templates` | Export check templates to an enrichment datastore |
| `checks import-templates` | Import check templates from a file |

## Creating a Single Check

Define a check in a YAML file:

```yaml
# check_order_id.yaml
rule_type: notNull
description: Order ID must not be null
container: orders
fields:
  - order_id
coverage: 1.0
tags:
  - data-quality
status: Active
```

```bash
qualytics checks create --datastore-id 1 --file check_order_id.yaml
```

## Bulk Create from YAML

Define multiple checks in a single file as a YAML list:

```yaml
# checks.yaml
- rule_type: notNull
  description: Order ID must not be null
  container: orders
  fields:
    - order_id
  coverage: 1.0
  status: Active

- rule_type: between
  description: Total amount must be between 0 and 100000
  container: orders
  fields:
    - total_amount
  coverage: 1.0
  properties:
    min_value: 0
    max_value: 100000
  status: Draft
```

```bash
qualytics checks create --datastore-id 1 --file checks.yaml
```

## Check YAML Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `rule_type` | string | Yes | Check type (`notNull`, `between`, `unique`, `matchesPattern`, etc.) |
| `description` | string | No | Human-readable description |
| `container` | string | Yes | Container name (resolved to ID on import) |
| `fields` | list[string] | No | Field names the check targets |
| `coverage` | float | No | Fraction of records to check (0.0-1.0) |
| `filter` | string | No | SQL WHERE clause to filter records |
| `properties` | dict | No | Rule-specific configuration (varies by rule_type) |
| `tags` | list[string] | No | Tags for filtering |
| `status` | string | No | `Active` or `Draft` (default: Active) |

## Export and Import

### Export checks

```bash
# Export all checks for a datastore, organized by container
qualytics checks export --datastore-id 1 --output ./checks/
```

This creates one YAML file per check:

```
checks/
  orders/
    notnull__order_id.yaml
    between__total_amount.yaml
  customers/
    unique__customer_id.yaml
```

### Import checks (upsert)

```bash
# Import to one or more datastores
qualytics checks import --datastore-id 1 --input ./checks/

# Preview what would change
qualytics checks import --datastore-id 1 --input ./checks/ --dry-run
```

Import uses **upsert** logic:
- Each check has a stable `_qualytics_check_uid` in `additional_metadata`
- **Match found** -- update the existing check
- **No match** -- create a new check
- Container names are resolved to IDs within each target datastore

For full config-as-code workflows including connections, datastores, and computed fields, see [Export/Import](export-import.md).

For CI/CD promotion workflows, see [GitHub Actions Promotion](examples/github-actions-promotion.md).
