# Operations

Operations are the data processing workflows in Qualytics. The standard lifecycle is: **catalog** (discover containers) then **profile** (infer checks) then **scan** (detect anomalies).

## Commands

| Command | Description |
|---------|-------------|
| `operations catalog` | Trigger a catalog operation (discover containers) |
| `operations profile` | Trigger a profile operation (infer quality checks) |
| `operations scan` | Trigger a scan operation (detect anomalies) |
| `operations materialize` | Trigger a materialize operation (computed containers) |
| `operations export` | Trigger an export operation (anomalies, checks, profiles) |
| `operations get` | Get operation details by `--id` |
| `operations list` | List operations, filterable by `--datastore-id`, `--type`, `--status` |
| `operations abort` | Abort a running operation by `--id` |

## Standard Lifecycle

### 1. Catalog (discover containers)

```bash
qualytics operations catalog --datastore-id 1
```

Discovers tables, views, and files in the datastore and creates container records.

### 2. Profile (infer checks)

```bash
qualytics operations profile --datastore-id 1

# With inference threshold (higher = more checks inferred)
qualytics operations profile --datastore-id 1 --inference-threshold 3
```

Profiles container data to infer quality checks based on statistical analysis.

### 3. Scan (detect anomalies)

```bash
qualytics operations scan --datastore-id 1

# Scan specific containers
qualytics operations scan --datastore-id 1 --container-names "orders,customers"

# Incremental scan (only new/updated records)
qualytics operations scan --datastore-id 1 --incremental
```

Runs quality checks against the data and detects anomalies.

## Running in Background

By default, operations wait for completion. Use `--background` to return immediately:

```bash
qualytics operations scan --datastore-id 1 --background
```

## Multiple Datastores

Run operations across multiple datastores at once:

```bash
qualytics operations catalog --datastore-id 1,2,3
```

## Monitoring Operations

```bash
# Check operation status
qualytics operations get --id 42

# List recent operations
qualytics operations list --datastore-id 1

# Filter by type and status
qualytics operations list --datastore-id 1 --type scan --status running

# Abort a running operation
qualytics operations abort --id 42
```

## Materialize

Materialize computed containers (execute their SQL and persist results):

```bash
qualytics operations materialize --datastore-id 1
```
