# Datastores

Datastores represent a database, schema, or file source within a connection. They scope containers, quality checks, and operations.

## Commands

| Command | Description |
|---------|-------------|
| `datastores create` | Create a datastore with `--connection-name` or `--connection-id` |
| `datastores update` | Update datastore fields (partial update) |
| `datastores get` | Get a datastore by `--id` or `--name` |
| `datastores list` | List datastores, filterable by `--type`, `--tag`, `--name` |
| `datastores delete` | Delete a datastore by `--id` |
| `datastores verify` | Test the connection for an existing datastore |
| `datastores enrichment` | Link (`--link`) or unlink (`--unlink`) an enrichment datastore |

## Creating a Datastore

```bash
# Reference connection by name
qualytics datastores create \
  --name "Order Analytics" \
  --connection-name prod-pg \
  --database analytics \
  --schema public \
  --tags "production,orders"

# Or reference by connection ID
qualytics datastores create \
  --name "Order Analytics" \
  --connection-id 1 \
  --database analytics \
  --schema public

# Preview the payload without creating anything
qualytics datastores create \
  --name "Order Analytics" \
  --connection-name prod-pg \
  --database analytics \
  --schema public \
  --dry-run
```

## Listing and Retrieving

```bash
# List all datastores
qualytics datastores list

# Filter by type and tag
qualytics datastores list --type JDBC --tag production

# Get by name
qualytics datastores get --name "Order Analytics"
```

## Enrichment Datastores

Link an enrichment datastore for anomaly enrichment:

```bash
# Link enrichment
qualytics datastores enrichment --id 1 --link 2

# Unlink enrichment
qualytics datastores enrichment --id 1 --unlink
```

## In Config Export/Import

Exported datastore YAML references the connection by name (not ID) for portability:

```yaml
# datastores/order_analytics/_datastore.yaml
connection_name: prod-pg
name: Order Analytics
store_type: JDBC
type: postgresql
database: analytics
schema: public
tags:
  - production
  - orders
```

See [Export/Import](export-import.md) for the full workflow.
