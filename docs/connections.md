# Connections

Connections define how Qualytics connects to your databases and data sources. Each connection stores host, credentials, and driver-specific parameters.

## Commands

| Command | Description |
|---------|-------------|
| `connections create` | Create a connection with inline flags and `${ENV_VAR}` support |
| `connections update` | Update connection fields (partial update) |
| `connections get` | Get a connection by `--id` or `--name` |
| `connections list` | List connections, filterable by `--type` and `--name` |
| `connections delete` | Delete a connection by `--id` |
| `connections test` | Test connectivity, optionally with override credentials |

## Creating a Connection

```bash
# Set credentials as environment variables (or use a .env file)
export PG_USER=analyst
export PG_PASS=s3cret

# Create a PostgreSQL connection
qualytics connections create \
  --type postgresql \
  --name prod-pg \
  --host db.example.com \
  --port 5432 \
  --username '${PG_USER}' \
  --password '${PG_PASS}'

# Verify it works
qualytics connections test --id 1
```

### Snowflake with extra parameters

```bash
qualytics connections create \
  --type snowflake \
  --name snow-wh \
  --host account.snowflakecomputing.com \
  --username '${SNOW_USER}' \
  --password '${SNOW_PASS}' \
  --parameters '{"role": "ANALYST", "warehouse": "COMPUTE_WH"}'
```

## Listing and Retrieving

```bash
# List all connections
qualytics connections list

# Filter by type
qualytics connections list --type postgresql

# Get by name
qualytics connections get --name prod-pg

# Get by ID
qualytics connections get --id 1
```

## Updating

```bash
# Update specific fields (partial update)
qualytics connections update --id 1 --host new-host.example.com --port 5433
```

## Deleting

```bash
qualytics connections delete --id 1
```

## In Config Export/Import

When you export configuration with `qualytics config export`, connections are written to `connections/<name>.yaml` with secrets replaced by `${ENV_VAR}` placeholders:

```yaml
# connections/prod_pg.yaml
name: prod_pg
type: postgresql
host: ${PROD_PG_HOST}
username: ${PROD_PG_USERNAME}
password: ${PROD_PG_PASSWORD}
port: 5432
```

On import, set the environment variables before running `qualytics config import`. See [Export/Import](export-import.md) for the full workflow.
