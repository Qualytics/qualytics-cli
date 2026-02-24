# Export and Import (Config-as-Code)

The `config` command group enables config-as-code workflows. Export your Qualytics configuration to a hierarchical YAML folder structure, track it in git, and import it into any environment.

## Commands

| Command | Description |
|---------|-------------|
| `config export` | Export configuration as hierarchical YAML |
| `config import` | Import configuration with dependency-ordered upsert |

## Export

```bash
# Export one or more datastores
qualytics config export --datastore-id 42 --output ./qualytics-config

# Export multiple datastores
qualytics config export --datastore-id 42 --datastore-id 43 --output ./qualytics-config

# Export only specific resource types
qualytics config export --datastore-id 42 --include connections,datastores
```

### Folder structure

```
qualytics-config/
  connections/
    prod_pg.yaml                        # ${ENV_VAR} placeholders for secrets
  datastores/
    order_analytics/
      _datastore.yaml                   # References connection by name
      containers/
        filtered_orders/
          _container.yaml               # Computed container definition
          computed_fields/
            order_margin.yaml           # Computed field definition
      checks/
        orders/
          notnull__order_id.yaml        # One file per quality check
          between__total_amount.yaml
```

### Key behaviors

- **Secrets** are replaced with `${ENV_VAR}` placeholders (never exported in plaintext)
- **Connections** are deduplicated across datastores (exported once by name)
- **Computed containers** are exported with their SQL definitions (tables/views/files are created by catalog)
- **Computed fields** are exported per container under `computed_fields/`
- **ID references** are replaced with name references for cross-environment portability
- **Re-export** produces zero git diff when nothing has changed

### Resource types

The `--include` flag accepts a comma-separated list: `connections`, `datastores`, `containers`, `computed_fields`, `checks`.

```bash
# Export only computed fields and checks
qualytics config export --datastore-id 1 --include computed_fields,checks
```

## Import

```bash
# Import everything
qualytics config import --input ./qualytics-config

# Preview what would change
qualytics config import --input ./qualytics-config --dry-run

# Import only specific resource types
qualytics config import --input ./qualytics-config --include connections,datastores
```

### Import order (dependency-safe)

1. **Connections** -- matched by `name` (create or update)
2. **Datastores** -- matched by `name`, resolves `connection_name` to ID
3. **Containers** -- matched by `name` within datastore, resolves references
4. **Computed fields** -- matched by `name` within container
5. **Quality checks** -- matched by `_qualytics_check_uid` (upsert)

### Secrets on import

Secrets in connection files use `${ENV_VAR}` placeholders. Set the environment variables before importing:

```bash
export PROD_PG_HOST=db-prod.example.com
export PROD_PG_USERNAME=analyst
export PROD_PG_PASSWORD=s3cret
qualytics config import --input ./qualytics-config
```

## Full Workflow: Dev to Prod

```bash
# 1. Export from Dev
qualytics config export --datastore-id $DEV_DS --output ./qualytics-config

# 2. Commit to git (secrets are safe -- only placeholders)
git add ./qualytics-config && git commit -m "Export from dev"

# 3. Preview what an import would change in Prod
qualytics config import --input ./qualytics-config --dry-run

# 4. Import to Prod
export PROD_PG_HOST=db-prod.example.com
export PROD_PG_USERNAME=analyst
export PROD_PG_PASSWORD=s3cret
qualytics config import --input ./qualytics-config
```

## Exported YAML Examples

### Connection

```yaml
# connections/prod_pg.yaml
name: prod_pg
type: postgresql
host: ${PROD_PG_HOST}
username: ${PROD_PG_USERNAME}
password: ${PROD_PG_PASSWORD}
port: 5432
```

### Datastore

```yaml
# datastores/order_analytics/_datastore.yaml
connection_name: prod-pg
name: Order Analytics
store_type: JDBC
type: postgresql
database: analytics
schema: public
```

### Computed container

```yaml
# datastores/order_analytics/containers/filtered_orders/_container.yaml
container_type: computed_table
name: filtered_orders
query: SELECT * FROM orders WHERE status = 'active'
datastore_name: Order Analytics
```

### Computed field

```yaml
# datastores/order_analytics/containers/accounts/computed_fields/cleaned_name.yaml
name: cleaned_name
transformation: cleanedEntityName
source_fields:
  - company_name
properties:
  drop_from_suffix: true
  terms_to_drop:
    - Inc.
    - Corp.
```

### Quality check

```yaml
# datastores/order_analytics/checks/orders/notnull__order_id.yaml
rule_type: notNull
description: Order ID must not be null
container: orders
fields:
  - order_id
coverage: 1.0
status: Active
additional_metadata:
  _qualytics_check_uid: orders__notnull__order_id
```

## CI/CD Promotion

For a complete GitHub Actions workflow that promotes configuration across environments, see [GitHub Actions Promotion](examples/github-actions-promotion.md).
