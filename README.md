# Qualytics CLI

This is a CLI tool for working with the Qualytics API. With this tool, you can manage your configurations, export checks, import checks, and more. It's built on top of the Typer CLI framework and uses the Rich library for enhanced terminal outputs.

## Requirements

- Python 3.10 or higher

## Installation

### From PyPI (recommended)

```bash
pip install qualytics-cli
```

### Using uv (faster)

```bash
uv pip install qualytics-cli
```

### From source

```bash
git clone https://github.com/Qualytics/qualytics-cli.git
cd qualytics-cli
uv sync
uv pip install -e .
```

## Usage

### Help

```bash
qualytics --help
```

### Initializing the Configuration

You can set up your Qualytics URL and token using the `init` command:

```bash
qualytics init --url "https://your-qualytics.qualytics.io/" --token "YOUR_TOKEN_HERE"
```

To disable SSL certificate verification (e.g., for self-signed certificates in development):

```bash
qualytics init --url "https://your-qualytics.qualytics.io/" --token "YOUR_TOKEN_HERE" --no-verify-ssl
```

| Option  | Type | Description                                           | Default | Required |
|---------|------|-------------------------------------------------------|---------|----------|
| `--url` | TEXT | The URL to be set. Example: https://your-qualytics.qualytics.io/ | None    | Yes      |
| `--token` | TEXT | The token to be set.                                 | None    | Yes      |
| `--no-verify-ssl` | FLAG | Disable SSL certificate verification for API requests. | False | No |

### Qualytics init help

```bash
qualytics init --help
```

### Display Configuration

To view the currently saved configuration:

```bash
qualytics show-config
```

### Quality Checks

The `checks` command group provides full CRUD operations and git-friendly export/import for quality checks.

#### Create Checks

Create quality checks from a YAML or JSON file:

```bash
# Create from a single-check file
qualytics checks create --datastore-id 42 --file check.yaml

# Create from a file containing a list of checks (bulk)
qualytics checks create --datastore-id 42 --file checks.yaml
```

| Option           | Type    | Description                              | Required |
|------------------|---------|------------------------------------------|----------|
| `--datastore-id` | INTEGER | Target datastore ID                      | Yes      |
| `--file`         | TEXT    | Path to YAML/JSON file with check definitions | Yes  |

#### Get a Check

```bash
qualytics checks get --check-id 123
qualytics checks get --check-id 123 --format json
```

| Option       | Type    | Description                               | Required |
|--------------|---------|-------------------------------------------|----------|
| `--check-id` | INTEGER | Quality check ID                          | Yes      |
| `--format`   | TEXT    | Output format: `yaml` or `json` (default: `yaml`) | No |

#### List Checks

```bash
qualytics checks list --datastore-id 42
qualytics checks list --datastore-id 42 --containers "1,2,3" --tags "production" --status Active
```

| Option           | Type    | Description                                      | Required |
|------------------|---------|--------------------------------------------------|----------|
| `--datastore-id` | INTEGER | Datastore ID                                     | Yes      |
| `--containers`   | TEXT    | Comma-separated container IDs                    | No       |
| `--tags`         | TEXT    | Comma-separated tag names                        | No       |
| `--status`       | TEXT    | Filter by status: `Active`, `Draft`, `Archived`  | No       |
| `--format`       | TEXT    | Output format: `yaml` or `json` (default: `yaml`)| No      |

#### Update a Check

```bash
qualytics checks update --check-id 123 --file updated_check.yaml
```

| Option       | Type    | Description                              | Required |
|--------------|---------|------------------------------------------|----------|
| `--check-id` | INTEGER | Quality check ID to update               | Yes      |
| `--file`     | TEXT    | Path to YAML/JSON file with updated fields | Yes    |

#### Delete Checks

```bash
# Delete a single check
qualytics checks delete --check-id 123

# Bulk delete
qualytics checks delete --ids "1,2,3,4,5"

# Hard delete (permanent, no archival)
qualytics checks delete --check-id 123 --no-archive
```

| Option       | Type    | Description                                          | Required |
|--------------|---------|------------------------------------------------------|----------|
| `--check-id` | INTEGER | Single check ID to delete                            | No*      |
| `--ids`      | TEXT    | Comma-separated list of check IDs for bulk delete    | No*      |
| `--archive`/`--no-archive` | FLAG | Archive on delete (default: `--archive`) | No       |

**Note**: You must provide either `--check-id` or `--ids`, but not both.

#### Export Checks (Git-Friendly)

Export checks to a directory structure with one YAML file per check, organized by container:

```bash
qualytics checks export --datastore-id 42 --output ./checks/
```

This creates:
```
checks/
  orders/
    notnull__order_id.yaml
    between__total_amount.yaml
  customers/
    matchespattern__email.yaml
    isunique__customer_id.yaml
```

Each file is a portable check definition that references containers and fields by name (not ID), so the same files can be imported to any datastore that has matching containers.

| Option           | Type    | Description                                      | Required |
|------------------|---------|--------------------------------------------------|----------|
| `--datastore-id` | INTEGER | Datastore ID to export from                      | Yes      |
| `--output`       | TEXT    | Output directory path (default: `./checks`)      | No       |
| `--containers`   | TEXT    | Comma-separated container IDs to filter          | No       |
| `--tags`         | TEXT    | Comma-separated tag names to filter              | No       |
| `--status`       | TEXT    | Filter by status: `Active`, `Draft`, `Archived`  | No       |

#### Import Checks (Multi-Datastore + Upsert)

Import checks from a directory to one or more datastores. Uses upsert logic — existing checks are updated, new ones are created.

```bash
# Import to a single datastore
qualytics checks import --datastore-id 42 --input ./checks/

# Import to multiple datastores (Dev → Test → Prod promotion)
qualytics checks import --datastore-id 42 --datastore-id 43 --datastore-id 44 --input ./checks/

# Preview what would change without making changes
qualytics checks import --datastore-id 42 --input ./checks/ --dry-run
```

| Option           | Type         | Description                                      | Required |
|------------------|--------------|--------------------------------------------------|----------|
| `--datastore-id` | INTEGER (repeatable) | Target datastore ID(s)                   | Yes      |
| `--input`        | TEXT         | Input directory path (default: `./checks`)       | No       |
| `--dry-run`      | FLAG         | Preview changes without executing                | No       |

**Upsert behavior:** Each check has a stable `_qualytics_check_uid` in its `additional_metadata`. On import, UIDs are matched against existing checks in the target datastore — matches update, new UIDs create. This makes repeated imports safe and idempotent.

For a complete CI/CD promotion workflow with GitHub Actions, see [docs/examples/github-actions-promotion.md](docs/examples/github-actions-promotion.md).

#### Export Check Templates

Export check templates to the `_export_check_templates` table in an enrichment datastore.

```bash
qualytics checks export-templates --enrichment_datastore_id ENRICHMENT_DATASTORE_ID [--check_templates CHECK_TEMPLATE_IDS]
```

| Option                      | Type    | Description                                                                | Required |
|-----------------------------|---------|----------------------------------------------------------------------------|----------|
| `--enrichment_datastore_id` | INTEGER | The ID of the enrichment datastore where templates will be exported        | Yes      |
| `--check_templates`         | TEXT    | Comma-separated list of template IDs. Example: "1, 2, 3" or "[1,2,3]"     | No       |

#### Import Check Templates

Import check templates from a file:

```bash
qualytics checks import-templates [--input LOCATION_OF_CHECK_TEMPLATES]
```

| Option    | Type | Description                                         | Default                                | Required |
|-----------|------|-----------------------------------------------------|----------------------------------------|----------|
| `--input` | TEXT | Input file path (format auto-detected by extension) | ~/.qualytics/data_checks_template.yaml | No       |

### Anomalies

The `anomalies` command group provides tools for managing anomalies created by failed quality checks during scan operations. This is especially useful for CI/CD pipelines that gate deployments on data quality.

#### Get an Anomaly

```bash
qualytics anomalies get --id 42
qualytics anomalies get --id 42 --format json
```

| Option     | Type    | Description                                      | Required |
|------------|---------|--------------------------------------------------|----------|
| `--id`     | INTEGER | Anomaly ID                                       | Yes      |
| `--format` | TEXT    | Output format: `yaml` or `json` (default: `yaml`) | No     |

#### List Anomalies

```bash
# List all anomalies for a datastore
qualytics anomalies list --datastore-id 42

# Filter by status, type, date range
qualytics anomalies list --datastore-id 42 --status Active --type record --start-date 2024-01-01

# JSON output for CI scripting
qualytics anomalies list --datastore-id 42 --status Active --format json
```

| Option           | Type    | Description                                          | Required |
|------------------|---------|------------------------------------------------------|----------|
| `--datastore-id` | INTEGER | Datastore ID to list anomalies from                  | Yes      |
| `--container`    | INTEGER | Container ID to filter by                            | No       |
| `--check-id`     | INTEGER | Quality check ID to filter by                        | No       |
| `--status`       | TEXT    | Comma-separated statuses: Active, Acknowledged, Resolved, etc. | No |
| `--type`         | TEXT    | Anomaly type: `shape` or `record`                    | No       |
| `--tag`          | TEXT    | Tag name to filter by                                | No       |
| `--start-date`   | TEXT    | Start date (YYYY-MM-DD)                              | No       |
| `--end-date`     | TEXT    | End date (YYYY-MM-DD)                                | No       |
| `--format`       | TEXT    | Output format: `yaml` or `json` (default: `yaml`)   | No       |

#### Update Anomaly Status

Update anomalies to open statuses (`Active` or `Acknowledged`):

```bash
# Single update
qualytics anomalies update --id 42 --status Acknowledged

# With description and tags
qualytics anomalies update --id 42 --status Acknowledged --description "Known issue" --tags "reviewed,ci"

# Bulk update
qualytics anomalies update --ids "1,2,3" --status Acknowledged
```

| Option          | Type    | Description                                          | Required |
|-----------------|---------|------------------------------------------------------|----------|
| `--id`          | INTEGER | Single anomaly ID to update                          | No*      |
| `--ids`         | TEXT    | Comma-separated anomaly IDs for bulk update          | No*      |
| `--status`      | TEXT    | New status: `Active` or `Acknowledged`               | Yes      |
| `--description` | TEXT    | Update description                                   | No       |
| `--tags`        | TEXT    | Comma-separated tag names                            | No       |

**Note**: You must provide either `--id` or `--ids`. For archived statuses (`Resolved`, `Invalid`, etc.), use `anomalies archive`.

#### Archive Anomalies

Soft-delete anomalies with an archived status:

```bash
# Archive with default status (Resolved)
qualytics anomalies archive --id 42

# Archive with specific status
qualytics anomalies archive --id 42 --status Invalid

# Bulk archive
qualytics anomalies archive --ids "1,2,3" --status Duplicate
```

| Option     | Type    | Description                                              | Required |
|------------|---------|----------------------------------------------------------|----------|
| `--id`     | INTEGER | Single anomaly ID to archive                             | No*      |
| `--ids`    | TEXT    | Comma-separated anomaly IDs for bulk archive             | No*      |
| `--status` | TEXT    | Archive status: `Resolved`, `Invalid`, `Duplicate`, or `Discarded` (default: `Resolved`) | No |

**Note**: You must provide either `--id` or `--ids`.

#### Delete Anomalies

Permanently delete anomalies (hard-delete):

```bash
# Single delete
qualytics anomalies delete --id 42

# Bulk delete
qualytics anomalies delete --ids "1,2,3"
```

| Option | Type    | Description                                          | Required |
|--------|---------|------------------------------------------------------|----------|
| `--id` | INTEGER | Single anomaly ID to delete                          | No*      |
| `--ids`| TEXT    | Comma-separated anomaly IDs for bulk delete          | No*      |

**Warning**: Hard-delete is permanent. Use `anomalies archive` for soft-delete.

#### CI/CD Anomaly Gating

Use anomalies to gate CI/CD pipelines based on data quality:

```bash
# Check for active anomalies and fail the pipeline if any exist
ANOMALY_COUNT=$(qualytics anomalies list --datastore-id $DS_ID --status Active --format json | python -c "import sys,json; print(len(json.load(sys.stdin)))")

if [ "$ANOMALY_COUNT" -gt "0" ]; then
  echo "FAIL: $ANOMALY_COUNT active anomalies found"
  exit 1
fi

# Acknowledge known anomalies in CI
qualytics anomalies update --ids "1,2,3" --status Acknowledged --description "Acknowledged by CI pipeline"
```

### Schedule Metadata Export

Allows you to schedule exports of metadata from your datastores using a specified crontab expression.

```bash
qualytics schedule export-metadata --crontab "CRONTAB_EXPRESSION" --datastore "DATASTORE_ID" [--containers "CONTAINER_IDS"] --options "EXPORT_OPTIONS"
```

| Option       | Type | Description                                                          | Required |
|--------------|------|----------------------------------------------------------------------|----------|
| `--crontab`  | TEXT | Crontab expression inside quotes, specifying when the task should run. Example: "0 * * * *" | Yes      |
| `--datastore`| TEXT | The datastore ID                                                     | Yes      |
| `--containers`| TEXT | Comma-separated list of container IDs or array-like format. Example: "1, 2, 3" or "[1,2,3]" | No       |
| `--options`  | TEXT | Comma-separated list of options to export or "all". Example: "anomalies, checks, field-profiles" | Yes      |

### Operations

The `operations` command group provides full lifecycle management for datastore operations: trigger, monitor, list, and abort.

#### Run a Catalog Operation

```bash
qualytics operations catalog --datastore-id 42
qualytics operations catalog --datastore-id "1,2,3" --include "table,view" --prune --recreate --background
```

| Option             | Type    | Description                                      | Required |
|--------------------|---------|--------------------------------------------------|----------|
| `--datastore-id`   | TEXT    | Comma-separated Datastore IDs                    | Yes      |
| `--include`        | TEXT    | Include types: "table,view"                      | No       |
| `--prune`          | FLAG    | Remove containers not found in catalog           | No       |
| `--recreate`       | FLAG    | Drop and recreate all containers                 | No       |
| `--background`     | FLAG    | Start without waiting for completion             | No       |
| `--poll-interval`  | INT     | Seconds between status checks (default: 10)      | No       |
| `--timeout`        | INT     | Max seconds to wait (default: 1800 = 30 min)     | No       |

#### Run a Profile Operation

```bash
qualytics operations profile --datastore-id 42
qualytics operations profile --datastore-id 42 --container-names "orders,customers" --inference-threshold 3 --infer-as-draft
```

| Option                                  | Type     | Description                                          | Required |
|-----------------------------------------|----------|------------------------------------------------------|----------|
| `--datastore-id`                        | TEXT     | Comma-separated Datastore IDs                        | Yes      |
| `--container-names`                     | TEXT     | Comma-separated container names                      | No       |
| `--container-tags`                      | TEXT     | Comma-separated container tags                       | No       |
| `--inference-threshold`                 | INT      | Check inference threshold (0 to 5)                   | No       |
| `--infer-as-draft`                      | FLAG     | Infer checks as Draft                                | No       |
| `--max-records-analyzed-per-partition`  | INT      | Max records per partition (-1 for unlimited)         | No       |
| `--max-count-testing-sample`            | INT      | Records for validation (max 100000)                  | No       |
| `--percent-testing-threshold`           | FLOAT    | Testing threshold percentage                         | No       |
| `--high-correlation-threshold`          | FLOAT    | Correlation threshold                                | No       |
| `--greater-than-time`                   | DATETIME | Incremental start time (YYYY-MM-DDTHH:MM:SS)        | No       |
| `--greater-than-batch`                  | FLOAT    | Incremental batch number threshold                   | No       |
| `--histogram-max-distinct-values`       | INT      | Max distinct values for histogram                    | No       |
| `--background`                          | FLAG     | Start without waiting for completion                 | No       |
| `--poll-interval`                       | INT      | Seconds between status checks (default: 10)          | No       |
| `--timeout`                             | INT      | Max seconds to wait (default: 1800 = 30 min)         | No       |

#### Run a Scan Operation

```bash
qualytics operations scan --datastore-id 42
qualytics operations scan --datastore-id 42 --container-names "orders" --incremental --remediation append
```

| Option                                  | Type     | Description                                          | Required |
|-----------------------------------------|----------|------------------------------------------------------|----------|
| `--datastore-id`                        | TEXT     | Comma-separated Datastore IDs                        | Yes      |
| `--container-names`                     | TEXT     | Comma-separated container names                      | No       |
| `--container-tags`                      | TEXT     | Comma-separated container tags                       | No       |
| `--incremental`                         | FLAG     | Process only new/updated records since last scan     | No       |
| `--remediation`                         | TEXT     | Replication strategy: append, overwrite, or none     | No       |
| `--max-records-analyzed-per-partition`  | INT      | Max records per partition (-1 for unlimited)         | No       |
| `--enrichment-source-record-limit`      | INT      | Enrichment source records limit (>= 1)               | No       |
| `--greater-than-time`                   | DATETIME | Incremental start time (YYYY-MM-DDTHH:MM:SS)        | No       |
| `--greater-than-batch`                  | FLOAT    | Incremental batch number threshold                   | No       |
| `--background`                          | FLAG     | Start without waiting for completion                 | No       |
| `--poll-interval`                       | INT      | Seconds between status checks (default: 10)          | No       |
| `--timeout`                             | INT      | Max seconds to wait (default: 1800 = 30 min)         | No       |

#### Run a Materialize Operation

```bash
qualytics operations materialize --datastore-id 42
qualytics operations materialize --datastore-id 42 --container-names "ct_orders" --max-records-per-partition 5000
```

| Option                        | Type | Description                                      | Required |
|-------------------------------|------|--------------------------------------------------|----------|
| `--datastore-id`              | TEXT | Comma-separated Datastore IDs                    | Yes      |
| `--container-names`           | TEXT | Comma-separated container names                  | No       |
| `--container-tags`            | TEXT | Comma-separated container tags                   | No       |
| `--max-records-per-partition` | INT  | Max records per partition (-1 for unlimited)     | No       |
| `--background`                | FLAG | Start without waiting for completion             | No       |
| `--poll-interval`             | INT  | Seconds between status checks (default: 10)      | No       |
| `--timeout`                   | INT  | Max seconds to wait (default: 1800 = 30 min)     | No       |

#### Run an Export Operation

```bash
qualytics operations export --datastore-id 42 --asset-type anomalies
qualytics operations export --datastore-id 42 --asset-type checks --container-ids "1,2,3" --include-deleted
```

| Option             | Type | Description                                      | Required |
|--------------------|------|--------------------------------------------------|----------|
| `--datastore-id`   | TEXT | Comma-separated Datastore IDs                    | Yes      |
| `--asset-type`     | TEXT | Asset type: anomalies, checks, or profiles       | Yes      |
| `--container-ids`  | TEXT | Comma-separated container IDs                    | No       |
| `--container-tags` | TEXT | Comma-separated container tags                   | No       |
| `--include-deleted`| FLAG | Include deleted items in export                  | No       |
| `--background`     | FLAG | Start without waiting for completion             | No       |
| `--poll-interval`  | INT  | Seconds between status checks (default: 10)      | No       |
| `--timeout`        | INT  | Max seconds to wait (default: 1800 = 30 min)     | No       |

#### Get Operation Details

```bash
qualytics operations get --id 123
qualytics operations get --id 123 --format json
```

| Option     | Type    | Description                                      | Required |
|------------|---------|--------------------------------------------------|----------|
| `--id`     | INTEGER | Operation ID                                     | Yes      |
| `--format` | TEXT    | Output format: `yaml` or `json` (default: `yaml`) | No     |

#### List Operations

```bash
qualytics operations list
qualytics operations list --datastore-id 42 --type scan --status "running,success" --format json
```

| Option           | Type | Description                                              | Required |
|------------------|------|----------------------------------------------------------|----------|
| `--datastore-id` | TEXT | Comma-separated Datastore IDs to filter by               | No       |
| `--type`         | TEXT | Operation type: catalog, profile, scan, materialize, export | No    |
| `--status`       | TEXT | Comma-separated result statuses: running, success, failure, aborted | No |
| `--start-date`   | TEXT | Start date filter (YYYY-MM-DD)                           | No       |
| `--end-date`     | TEXT | End date filter (YYYY-MM-DD)                             | No       |
| `--format`       | TEXT | Output format: `yaml` or `json` (default: `yaml`)       | No       |

#### Abort a Running Operation

```bash
qualytics operations abort --id 123
```

| Option | Type    | Description                  | Required |
|--------|---------|------------------------------|----------|
| `--id` | INTEGER | Operation ID to abort        | Yes      |

**Note**: Abort is best-effort. If the operation has already finished, it's a no-op.

## Configuring Connections

Before creating datastores, you need to define your database connections in a YAML configuration file. This allows you to:
- Reuse connection configurations across multiple datastores
- Manage connection credentials in a centralized location
- Automatically create new connections or reference existing ones in Qualytics

### Setting Up connections.yml

Create a file at `~/.qualytics/config/connections.yml` with your connection configurations.

**Important**: All connection values must be directly written in the `connections.yml` file. The CLI does not use `.env` files for connection configuration.

#### Configuration Structure

```yaml
connections:
  <connection_key>:                  # Identifier for this connection block
    type: <connection_type>          # Required: Database type (postgresql, snowflake, mysql, etc.)
    name: <connection_name>           # Required: Unique name to identify this connection
    parameters:                       # Required: Connection-specific parameters
      host: <hostname>
      port: <port_number>
      user: <username>
      password: <password>
      # Additional parameters vary by connection type
```

#### Supported Connection Types

- `postgresql` - PostgreSQL databases
- `snowflake` - Snowflake data warehouse
- `mysql` - MySQL databases
- `bigquery` - Google BigQuery
- `redshift` - Amazon Redshift
- `abfs` - Azure Blob File System
- `sqlserver` - Microsoft SQL Server
- And more...

### Connection Examples

#### PostgreSQL Connection

```yaml
connections:
  my_postgres:
    type: postgresql
    name: production_postgres_db
    parameters:
      host: postgres.example.com
      port: 5432
      user: postgres_user
      password: your_secure_password
```

#### Snowflake Connection (Username/Password)

```yaml
connections:
  my_snowflake:
    type: snowflake
    name: prod_snowflake_connection
    parameters:
      host: account.snowflakecomputing.com
      role: DATA_ANALYST
      warehouse: COMPUTE_WH
      user: snowflake_user
      password: your_snowflake_password
```

#### Snowflake Connection (Key-Pair Authentication)

```yaml
connections:
  my_snowflake_keypair:
    type: snowflake
    name: prod_snowflake_keypair
    parameters:
      host: account.snowflakecomputing.com
      role: DATA_ANALYST
      warehouse: COMPUTE_WH
      database: ANALYTICS_DB
      schema: PUBLIC
      authentication:
        method: keypair
        user: snowflake_user
        private_key_path: /path/to/private_key.pem
```

#### MySQL Connection

```yaml
connections:
  my_mysql:
    type: mysql
    name: prod_mysql_db
    parameters:
      host: mysql.example.com
      port: 3306
      user: mysql_user
      password: mysql_password
```

#### BigQuery Connection

```yaml
connections:
  my_bigquery:
    type: bigquery
    name: prod_bigquery
    parameters:
      project_id: my-gcp-project-id
      credentials_path: /path/to/service-account-key.json
```

#### Azure Blob File System (ABFS)

```yaml
connections:
  my_abfs:
    type: abfs
    name: azure_data_lake
    parameters:
      storage_account: mystorageaccount
      container: mycontainer
      access_key: your_access_key
```

### Complete Example connections.yml

```yaml
connections:
  # PostgreSQL for production analytics
  prod_postgres:
    type: postgresql
    name: production_analytics
    parameters:
      host: analytics.postgres.example.com
      port: 5432
      user: analyst
      password: secure_pass_123

  # Snowflake data warehouse
  snowflake_dw:
    type: snowflake
    name: data_warehouse
    parameters:
      host: mycompany.snowflakecomputing.com
      role: ANALYST_ROLE
      warehouse: ANALYTICS_WH
      user: dw_user
      password: snowflake_password

  # Development MySQL database
  dev_mysql:
    type: mysql
    name: dev_database
    parameters:
      host: localhost
      port: 3306
      user: dev_user
      password: dev_password
```

### Security Notes

- **File Permissions**: Ensure your `connections.yml` file has restricted permissions:
  ```bash
  chmod 600 ~/.qualytics/config/connections.yml
  ```
- **Sensitive Data**: Passwords, tokens, and keys are automatically redacted in CLI output
- **Version Control**: Never commit `connections.yml` to version control. Add it to `.gitignore`

### How Connections Work with Datastores

When creating a datastore with `--connection-name`:

1. **Check Existing**: The CLI checks if a connection with that name already exists in your Qualytics instance
2. **Reuse Existing**: If found, the CLI uses the existing connection ID automatically
3. **Create New**: If not found, the CLI creates a new connection using the configuration from `connections.yml`

This means you can define your connection once and reuse it across multiple datastores!

### Datastores

The `datastores` command group provides full CRUD operations plus connection verification and enrichment management.

#### Create a Datastore

```bash
# With connection name from connections.yml
qualytics datastores create \
  --name "Production Analytics" \
  --connection-name "prod_snowflake_connection" \
  --database "ANALYTICS_DB" \
  --schema "PUBLIC" \
  --tags "production,analytics" \
  --teams "data-team,engineering" \
  --trigger-catalog

# With existing connection ID
qualytics datastores create \
  --name "Dev Analytics" \
  --connection-id 5 \
  --database "DEV_DB" \
  --schema "PUBLIC"

# Preview payload without creating
qualytics datastores create --name "test" --connection-id 5 --database "db" --schema "sc" --dry-run
```

| Option                                 | Type    | Description                                                                 | Required |
|----------------------------------------|---------|-----------------------------------------------------------------------------|----------|
| `--name`                               | TEXT    | Datastore name                                                              | Yes      |
| `--connection-name`                    | TEXT    | Connection name from connections.yml (mutually exclusive with --connection-id) | No*    |
| `--connection-id`                      | INTEGER | Existing connection ID (mutually exclusive with --connection-name)           | No*      |
| `--database`                           | TEXT    | Database name                                                               | Yes      |
| `--schema`                             | TEXT    | Schema name                                                                 | Yes      |
| `--tags`                               | TEXT    | Comma-separated tags                                                        | No       |
| `--teams`                              | TEXT    | Comma-separated team names                                                  | No       |
| `--enrichment-only/--no-enrichment-only` | FLAG | Set datastore as enrichment-only                                            | No       |
| `--enrichment-prefix`                  | TEXT    | Prefix for enrichment artifacts                                             | No       |
| `--enrichment-source-record-limit`     | INTEGER | Enrichment source records limit (min: 1)                                    | No       |
| `--enrichment-remediation-strategy`    | TEXT    | Strategy: none, append, or overwrite (default: none)                        | No       |
| `--high-count-rollup-threshold`        | INTEGER | High count rollup threshold (min: 1)                                        | No       |
| `--trigger-catalog/--no-trigger-catalog` | FLAG | Trigger catalog after creation (default: True)                              | No       |
| `--dry-run`                            | FLAG    | Print payload without making HTTP request                                   | No       |
| `--format`                             | TEXT    | Output format: `yaml` or `json` (default: `yaml`)                          | No       |

**Note**: You must provide either `--connection-name` or `--connection-id`, but not both.

#### Update a Datastore

```bash
# Rename
qualytics datastores update --id 42 --name "New Name"

# Update multiple fields
qualytics datastores update --id 42 --database "new_db" --schema "new_schema" --tags "updated,v2"

# Change enrichment settings
qualytics datastores update --id 42 --enrichment-remediation-strategy append --enrichment-source-record-limit 500
```

| Option                                 | Type    | Description                                      | Required |
|----------------------------------------|---------|--------------------------------------------------|----------|
| `--id`                                 | INTEGER | Datastore ID to update                           | Yes      |
| `--name`                               | TEXT    | New datastore name                               | No       |
| `--connection-id`                      | INTEGER | New connection ID                                | No       |
| `--database`                           | TEXT    | New database                                     | No       |
| `--schema`                             | TEXT    | New schema                                       | No       |
| `--tags`                               | TEXT    | Comma-separated tags                             | No       |
| `--teams`                              | TEXT    | Comma-separated team names                       | No       |
| `--enrichment-only/--no-enrichment-only` | FLAG | Enrichment-only flag                             | No       |
| `--enrichment-prefix`                  | TEXT    | Prefix for enrichment artifacts                  | No       |
| `--enrichment-source-record-limit`     | INTEGER | Enrichment source records limit                  | No       |
| `--enrichment-remediation-strategy`    | TEXT    | Strategy: none, append, or overwrite             | No       |
| `--high-count-rollup-threshold`        | INTEGER | High count rollup threshold                      | No       |
| `--format`                             | TEXT    | Output format: `yaml` or `json` (default: `yaml`) | No     |

#### Get a Datastore

```bash
qualytics datastores get --id 42
qualytics datastores get --name "Production Analytics" --format json
```

| Option     | Type    | Description                                      | Required |
|------------|---------|--------------------------------------------------|----------|
| `--id`     | INTEGER | Datastore ID (mutually exclusive with --name)    | No*      |
| `--name`   | TEXT    | Datastore name (mutually exclusive with --id)    | No*      |
| `--format` | TEXT    | Output format: `yaml` or `json` (default: `yaml`) | No     |

**Note**: You must provide either `--id` or `--name`, but not both.

#### List Datastores

```bash
qualytics datastores list
qualytics datastores list --name "prod" --type "postgresql,snowflake" --tag "production"
qualytics datastores list --enrichment-only --format json
```

| Option                                 | Type | Description                                              | Required |
|----------------------------------------|------|----------------------------------------------------------|----------|
| `--name`                               | TEXT | Filter by name (search)                                  | No       |
| `--type`                               | TEXT | Comma-separated connection types (e.g. postgresql,snowflake) | No   |
| `--tag`                                | TEXT | Tag name to filter by                                    | No       |
| `--enrichment-only/--no-enrichment-only` | FLAG | Filter enrichment-only datastores                      | No       |
| `--format`                             | TEXT | Output format: `yaml` or `json` (default: `yaml`)       | No       |

#### Delete a Datastore

```bash
qualytics datastores delete --id 42
```

| Option | Type    | Description           | Required |
|--------|---------|-----------------------|----------|
| `--id` | INTEGER | Datastore ID to delete | Yes      |

**Warning**: Use with caution — this permanently deletes the datastore.

#### Verify Connection

Test the connection for an existing datastore. Useful for CI health checks.

```bash
qualytics datastores verify --id 42
qualytics datastores verify --id 42 --format json
```

| Option     | Type    | Description                                      | Required |
|------------|---------|--------------------------------------------------|----------|
| `--id`     | INTEGER | Datastore ID to verify                           | Yes      |
| `--format` | TEXT    | Output format: `yaml` or `json` (default: `yaml`) | No     |

#### Manage Enrichment Links

Link or unlink an enrichment datastore to/from a source datastore.

```bash
# Link enrichment datastore 5 to source datastore 1
qualytics datastores enrichment --id 1 --link 5

# Unlink enrichment from datastore 1
qualytics datastores enrichment --id 1 --unlink
```

| Option     | Type    | Description                                          | Required |
|------------|---------|------------------------------------------------------|----------|
| `--id`     | INTEGER | Source datastore ID                                  | Yes      |
| `--link`   | INTEGER | Enrichment datastore ID to link                      | No*      |
| `--unlink` | FLAG    | Unlink enrichment datastore                          | No*      |

**Note**: You must provide either `--link` or `--unlink`, but not both.

---

## Computed Tables

The `computed-tables` command group allows you to import computed tables from files and automatically create quality checks for error detection queries.

### Import Computed Tables

Import computed tables from a file (Excel, CSV, or TXT) and optionally create satisfiesExpression checks.

```bash
qualytics computed-tables import --datastore DATASTORE_ID --input FILE_PATH [OPTIONS]
```

#### Input File Structure

The input file must have **3 columns in positional order** (the first row is treated as a header and skipped):

| Column | Name        | Required | Description                                           |
|--------|-------------|----------|-------------------------------------------------------|
| 1      | name        | **Yes**  | Unique identifier for the computed table              |
| 2      | description | No       | Description stored in metadata and check              |
| 3      | query       | **Yes**  | SQL query for the computed table                      |

**Important**: Column names in the header row don't matter - only the position matters. You can name them anything (e.g., `check_id`, `check_description`, `check_query`).

#### Excel File Example (.xlsx)

| check_id    | check_description                     | check_query                                                        |
|-------------|---------------------------------------|--------------------------------------------------------------------|
| CHK001      | Detect orders with negative totals    | SELECT * FROM sales_orders WHERE total_amount < 0                  |
| CHK002      | Find customers without email          | SELECT * FROM customer_master WHERE email IS NULL OR email = ''    |
| CHK003      | Identify duplicate invoices           | SELECT invoice_no, COUNT(*) FROM invoices GROUP BY invoice_no HAVING COUNT(*) > 1 |

#### CSV File Example (.csv)

```csv
check_id,check_description,check_query
CHK001,Detect orders with negative totals,"SELECT * FROM sales_orders WHERE total_amount < 0"
CHK002,Find customers without email,"SELECT * FROM customer_master WHERE email IS NULL OR email = ''"
CHK003,Identify duplicate invoices,"SELECT invoice_no, COUNT(*) FROM invoices GROUP BY invoice_no HAVING COUNT(*) > 1"
```

**Note**: For multiline SQL queries in CSV, wrap the entire query in double quotes:

```csv
check_id,check_description,check_query
CHK004,Complex order validation,"SELECT o.*
FROM sales_orders o
JOIN customer_master c ON o.customer_id = c.id
WHERE o.status = 'SHIPPED'
  AND c.country IS NULL"
```

#### Validation Rules

The import process validates each row before processing:

| Validation          | Behavior                                           |
|---------------------|----------------------------------------------------|
| Empty name          | Row is **skipped** with warning                    |
| Empty query         | Row is **skipped** with warning                    |
| Empty description   | Row is **processed** (description defaults to "")  |
| Duplicate name      | Second occurrence is **skipped** with warning      |
| Blank row           | Row is **skipped** silently                        |

**Example validation output:**
```
Found 5 records in the file.
Warnings during validation:
  - Row 3: Empty name, skipping.
  - Row 4: 'CHK001' has empty query, skipping.
  - Row 7: Duplicate name 'CHK002' (first seen at row 2), skipping.
3 valid records to import.
```

#### Options

| Option                | Type    | Description                                                      | Default               |
|-----------------------|---------|------------------------------------------------------------------|-----------------------|
| `--datastore`         | INTEGER | Datastore ID to create computed tables in                        | Required              |
| `--input`             | TEXT    | Input file path (.xlsx, .csv, or .txt)                           | Required              |
| `--prefix`            | TEXT    | Prefix for computed table names                                  | `ct_`                 |
| `--delimiter`         | TEXT    | Delimiter for CSV/TXT files                                      | `,` for CSV, `\t` for TXT |
| `--as-draft`          | FLAG    | Create checks in Draft status (default)                          | True                  |
| `--as-active`         | FLAG    | Create checks in Active status                                   | False                 |
| `--skip-checks`       | FLAG    | Skip creating quality checks (only create computed tables)       | False                 |
| `--skip-profile-wait` | FLAG    | Skip waiting for profile operation (**Warning**: checks may fail) | False                 |
| `--tags`              | TEXT    | Tags for checks (comma-separated)                                | None                  |
| `--dry-run`           | FLAG    | Preview what would be created without making changes             | False                 |
| `--debug`             | FLAG    | Enable debug mode with API logging                               | False                 |

#### Check Status: Draft vs Active

The `--as-draft` and `--as-active` flags control the status of created quality checks:

| Status   | Flag          | Behavior                                                    |
|----------|---------------|-------------------------------------------------------------|
| Draft    | `--as-draft`  | Check exists but won't run during scans. Review before activating. |
| Active   | `--as-active` | Check runs immediately during scan operations.              |

**Default**: Checks are created as **Draft** for safety.

#### Use Cases

Below are common use cases showing what happens with different option combinations:

---

**1. Basic Import (Default)**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx
```
| What happens |
|--------------|
| Creates computed tables with `ct_` prefix |
| Waits for profile operation to complete |
| Creates quality checks in **Draft** status |
| Skips existing computed tables |
| Skips check creation if check already exists |

---

**2. Import with Active Checks**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --as-active
```
| What happens |
|--------------|
| Same as basic import |
| Checks are created in **Active** status |
| Checks will run during the next scan operation |

**Use when**: Rules are tested and ready for production.

---

**3. Import Only Computed Tables (No Checks)**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --skip-checks
```
| What happens |
|--------------|
| Creates computed tables only |
| **No quality checks are created** |
| Still waits for profile operations |

**Use when**: You want to configure checks manually in the UI.

---

**4. Skip Profile Wait**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --skip-profile-wait
```
| What happens |
|--------------|
| Creates computed tables without waiting for profile |
| **⚠️ Checks will likely FAIL** - container has no fields until profile completes |
| Faster for bulk imports |

**Warning**: If profiling hasn't completed, check creation will fail with: `Container X has no fields. Cannot create check.`

**Use when**: Only use with `--skip-checks` for bulk computed table creation. Add checks manually later after profiling completes.

---

**5. Import with Custom Prefix**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --prefix "dq_"
```
| What happens |
|--------------|
| Computed tables use `dq_` prefix instead of `ct_` |
| Example: `CHK001` → `dq_CHK001` |

**Use when**: Organizing different types of rules with different prefixes.

---

**6. Import with Tags**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --tags "production,finance"
```
| What happens |
|--------------|
| Checks are created with specified tags |
| Multiple tags separated by commas |

**Use when**: Organizing checks for filtering in the UI.

---

**7. Dry Run (Preview Only)**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --dry-run
```
| What happens |
|--------------|
| **No changes are made** |
| Shows preview table of what would be created |
| Shows which tables would be skipped (already exist) |

**Use when**: Validating input file before actual import.

---

**8. Debug Mode**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx --debug
```
| What happens |
|--------------|
| Shows API requests/responses in console |
| Writes detailed logs to `~/.qualytics/logs/` |

**Use when**: Troubleshooting import failures.

---

**9. CSV with Custom Delimiter**
```bash
qualytics computed-tables import --datastore 123 --input checks.txt --delimiter ";"
```
| What happens |
|--------------|
| Reads file using semicolon as delimiter |

**Use when**: Files exported from systems with non-standard delimiters.

---

**10. Production-Ready Import**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx \
  --prefix "prod_" \
  --tags "production,automated" \
  --as-active \
  --debug
```
| What happens |
|--------------|
| Computed tables with `prod_` prefix |
| Checks in **Active** status |
| Tags: `production`, `automated` |
| Full API logging for audit trail |

---

**11. Fast Bulk Import (Minimal)**
```bash
qualytics computed-tables import --datastore 123 --input checks.xlsx \
  --skip-checks \
  --skip-profile-wait
```
| What happens |
|--------------|
| Fastest possible import |
| No profile waiting, no checks created |
| Computed tables only |

**Use when**: Bulk setup of computed tables only. You must add checks manually after profiling completes.

**Note**: This is the recommended way to use `--skip-profile-wait` - always combine it with `--skip-checks`.

#### Computed Table Naming

The final computed table name follows the pattern: `<prefix><name>`

For example, with default prefix `ct_`:
- Input name: `CHK001` → Computed table: `ct_CHK001`
- Input name: `order_validation` → Computed table: `ct_order_validation`

Common suffixes like `_SF`, `_DB`, `_BQ`, `_SNOWFLAKE` are automatically stripped from the `rule_id` stored in metadata:
- Input name: `CHK001_SF` → `rule_id` in metadata: `CHK001`

#### Check Behavior

When checks are created (default behavior), a `satisfiesExpression` check is automatically generated where:

- **Empty result set (no rows)** = PASS (all data is valid)
- **Any rows returned** = FAIL (each row is flagged as an anomaly)

This is ideal for error detection queries where returned results indicate data quality issues.

The check expression wraps all field names with backticks for compatibility with special characters and functions:
```sql
`order_id` IS NULL AND `customer_name` IS NULL AND `coalesce(trim(status))` IS NULL
```

#### Metadata Storage

Both the computed table and quality check store metadata for traceability:

**Computed Table `additional_metadata`:**
```json
{
  "description": "Detect orders with negative totals",
  "rule_id": "CHK001",
  "imported_from": "qualytics-cli",
  "import_timestamp": "2026-01-28T12:00:00"
}
```

**Quality Check `additional_metadata`:**
```json
{
  "rule_id": "CHK001",
  "computed_table_name": "ct_CHK001",
  "original_description": "Detect orders with negative totals",
  "imported_from": "qualytics-cli",
  "import_timestamp": "2026-01-28T12:00:00"
}
```

#### SQL Query Handling

**Cross-catalog/schema references** are preserved as-is:

```sql
SELECT * FROM analytics_prod.sales_schema.orders o
JOIN finance_db.accounting.invoices i ON o.invoice_id = i.id
WHERE o.status = 'PENDING'
```

**Automatic alias addition**: Columns without aliases get unique aliases added automatically (`expr_1`, `expr_2`, etc.):

```sql
-- Original query (columns without aliases)
SELECT coalesce(trim(name), 'Blank'), upper(status), id as order_id FROM orders

-- After processing (aliases added)
SELECT coalesce(trim(name), 'Blank') as expr_1, upper(status) as expr_2, id as order_id FROM orders
```

This ensures all fields have proper names for the quality check expression.

If you need to test with all tables in the same catalog/schema, pre-process your input file to remove the prefixes before importing.

### List Computed Tables

List all computed tables in a datastore.

```bash
qualytics computed-tables list --datastore DATASTORE_ID
```

| Option        | Type    | Description                              | Required |
|---------------|---------|------------------------------------------|----------|
| `--datastore` | INTEGER | Datastore ID to list computed tables from | Yes      |

**Example output:**
```
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ ID   ┃ Name               ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ 101  │ ct_CHK001          │
│ 102  │ ct_CHK002          │
│ 103  │ ct_CHK003          │
└──────┴────────────────────┘

Total: 3 computed tables
```

### Preview File

Preview computed table definitions from a file without importing. Useful for validating your input file before import.

```bash
qualytics computed-tables preview --input FILE_PATH [OPTIONS]
```

| Option        | Type    | Description                                      | Default |
|---------------|---------|--------------------------------------------------|---------|
| `--input`     | TEXT    | Input file path (.xlsx, .csv, or .txt)           | Required |
| `--delimiter` | TEXT    | Delimiter for CSV/TXT files                      | `,` for CSV, `\t` for TXT |
| `--limit`     | INTEGER | Number of records to preview                     | 5       |
| `--prefix`    | TEXT    | Prefix to show for computed table names          | `ct_`   |

**Example:**
```bash
qualytics computed-tables preview --input checks.xlsx --limit 3
```

**Example output:**
```
Reading definitions from: checks.xlsx
Found 5 records in the file.

Preview of first 3 records:

Record 1:
  Computed Table Name: ct_CHK001
  Description: Detect orders with negative totals
  Query: SELECT * FROM sales_orders WHERE total_amount < 0

Record 2:
  Computed Table Name: ct_CHK002
  Description: Find customers without email
  Query: SELECT * FROM customer_master WHERE email IS NULL...

Record 3:
  Computed Table Name: ct_CHK003
  Description: Identify duplicate invoices
  Query: SELECT invoice_no, COUNT(*) FROM invoices GROUP B...

... and 2 more records
```

---

## Development

This project uses modern Python tooling with [uv](https://docs.astral.sh/uv/) for dependency management and [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

### Requirements

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Setting Up Development Environment

1. **Install uv** (if not already installed):
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone the repository**:
   ```bash
   git clone https://github.com/Qualytics/qualytics-cli.git
   cd qualytics-cli
   ```

3. **Install dependencies**:
   ```bash
   uv sync
   ```

4. **Install pre-commit hooks** (optional but recommended):
   ```bash
   uv run pre-commit install
   ```

### Development Commands

```bash
# Install/update dependencies
uv sync

# Run the CLI in development mode
uv run qualytics --help

# Run linting checks
uv run ruff check qualytics/

# Auto-fix linting issues
uv run ruff check qualytics/ --fix

# Format code
uv run ruff format qualytics/

# Run all pre-commit hooks (includes linting, formatting, and Python 3.10+ upgrades)
uv run pre-commit run --all-files

# Build the package
uv build

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov --cov-report=term-missing
```

### Versioning & Releases

Version bumping is managed via `uv version` and automated through GitHub Actions:

```bash
# Check current version
uv version

# Bump version locally (patch/minor/major)
uv version patch   # 0.4.0 -> 0.4.1
uv version minor   # 0.4.0 -> 0.5.0
uv version major   # 0.4.0 -> 1.0.0
```

Releases are triggered by the **Release** workflow in GitHub Actions (manual dispatch), which bumps the version, creates a git tag, and triggers the **Publish** workflow to build and publish to PyPI via trusted publishing (OIDC).

### Code Quality Standards

This project enforces:
- **Python 3.10+** minimum version
- **Ruff** for linting and formatting (88 character line length)
- **pyupgrade** for automatic Python syntax modernization
- **Pre-commit hooks** for automated quality checks

### Project Structure

```
qualytics-cli/
├── qualytics/               # Main package
│   ├── qualytics.py         # Entry point — registers all Typer sub-apps
│   ├── config.py            # Configuration management
│   ├── cli/                 # CLI commands layer (Typer sub-applications)
│   ├── services/            # Business logic & orchestration
│   ├── api/                 # Thin HTTP wrappers over the Qualytics API
│   └── utils/               # Validation, file ops, YAML loading
├── tests/                   # Test suite (pytest)
├── pyproject.toml           # Project configuration & dependencies
├── .pre-commit-config.yaml  # Pre-commit hooks configuration
└── .github/workflows/       # CI/CD (lint, test, publish, release)
```

### Contributing

1. Create a new branch for your feature/fix
2. Make your changes
3. Run `uv run pytest` to ensure tests pass
4. Run `uv run pre-commit run --all-files` to ensure all quality checks pass
5. Commit your changes (pre-commit hooks will run automatically if installed)
6. Submit a pull request — CI will run lint, tests, and pre-commit checks automatically

---

## License

MIT License - see [LICENSE](LICENSE) file for details.
