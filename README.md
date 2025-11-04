# Qualytics CLI

This is a CLI tool for working with the Qualytics API. With this tool, you can manage your configurations, export checks, import checks, and more. It's built on top of the Typer CLI framework and uses the Rich library for enhanced terminal outputs.

## Requirements

- Python 3.9 or higher

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

You can set up your Qualytics URL and token using the `init` command. This will create configuration in your **home directory** and project structure in your **current working directory**:

**Configuration (in home directory):**
```
~/.qualytics/
  └── .env
```

**Project structure (in current working directory):**
```
./
  ├── assets/
  │   ├── anomalies/
  │   ├── check_templates/
  │   └── checks/
  └── config/
      ├── connections_example.yml
      └── instance.yml
```

You will be prompted to input your URL and token (note that your token won't appear when you type it):

```
Enter your Qualytics URL (e.g., https://your-qualytics.qualytics.io): <your_url>
Enter your Qualytics API token: <your_token>
```

Your credentials are stored in `~/.qualytics/.env` in your home directory, while project files (assets, config) are created in your current working directory.

**Migration Note**: If you were previously using the old `~/.qualytics/config.json` file, simply run the `init` command again. It will automatically:
- Migrate your configuration to the new `.env` format in `~/.qualytics/.env`
- Remove the old JSON config file
- Set up the project structure in your current directory

```bash
qualytics init
```

### Qualytics init help

```bash
qualytics init --help
```

### Display Configuration

To view the currently saved configuration:

```bash
qualytics show-config
```

### Export Checks

You can export checks to a file using the `checks export` command:

```bash
qualytics checks export --datastore DATASTORE_ID [--containers CONTAINER_IDS] [--tags TAG_NAMES] [--output LOCATION_TO_BE_EXPORTED]
```

By default, it saves the exported checks to `./qualytics/data_checks.json`. However, you can specify a different output path with the `--output` option.

| Option         | Type            | Description                                             | Default                            | Required |
|----------------|-----------------|---------------------------------------------------------|------------------------------------|----------|
| `--datastore`  | INTEGER         | Datastore ID                                            | None                               | Yes      |
| `--containers` | List of INTEGER | Containers IDs                                          | None                               | No       |
| `--tags`       | List of TEXT    | Tag names                                               | None                               | No       |
| `--status`      | List of TEXT   | Status `Active`, `Draft` or `Archived`                  | None                               | No       |
| `--output`     | TEXT            | Output file path   | ./qualytics/data_checks.json       | No                                 | No       |

### Export Check Templates

You can export check templates to the `_export_check_templates` table to an enrichment datastore.

```bash
qualytics checks export-templates --enrichment_datastore_id ENRICHMENT_DATASTORE_ID [--check_templates CHECK_TEMPLATE_IDS]
```

| Option                   | Type     | Description                                                                | Required |
|--------------------------|----------|----------------------------------------------------------------------------|----------|
| `--enrichment_datastore_id` | INTEGER  | The ID of the enrichment datastore where check templates will be exported. | Yes      |
| `--check_templates`       | TEXT     | Comma-separated list of check template IDs or array-like format. Example: "1, 2, 3" or "[1,2,3]".| No       |

### Import Checks

To import checks from a file:

```bash
qualytics checks import --datastore DATASTORE_ID_LIST [--input LOCATION_FROM_THE_EXPORT]
```

By default, it reads the checks from `./qualytics/data_checks.json`. You can specify a different input file with the `--input` option.

**Note**: Any errors encountered during the importing of checks will be logged in `./qualytics/errors.log`.

| Option       | Type | Description                                                                  | Default                       | Required |
|--------------|------|------------------------------------------------------------------------------|-------------------------------|----------|
| `--datastore`| TEXT | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]" | None | Yes      |
| `--input`    | TEXT | Input file path                                                              | HOME/.qualytics/data_checks.json | No       |



### Import Check Templates

You can import check templates from a file using the `checks import-templates` command:

```bash
qualytics checks import-templates [--input LOCATION_OF_CHECK_TEMPLATES]
```

By default, it reads the check templates from `./qualytics/data_checks_template.json`. You can specify a different input file with the `--input` option.

| Option    | Type | Description                  | Default                               | Required |
|-----------|------|------------------------------|---------------------------------------|----------|
| `--input` | TEXT | Input file path               | ./qualytics/data_checks_template.json | No       |

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

### Run a Catalog Operation on a Datastore

Allows you to trigger a catalog operation on any current datastore (requires admin permissions on the datastore).

```bash
qualytics run catalog --datastore "DATASTORE_ID_LIST" --include "INCLUDE_LIST" --prune --recreate --background
```

| Option         | Type | Description                                                                                         | Required |
|----------------|------|-----------------------------------------------------------------------------------------------------|----------|
| `--datastore`  | TEXT | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]"     | Yes      |
| `--include`    | TEXT | Comma-separated list of include types or array-like format. Example: "table,view" or "[table,view]" | No       |
| `--prune`      | BOOL | Prune the operation. Do not include if you want prune == false                                      | No       |
| `--recreate`   | BOOL | Recreate the operation. Do not include if you want recreate == false                                | No       |
| `--background` | BOOL | Starts the catalog but does not wait for the operation to finish                                    | No       |

### Run a Profile Operation on a Datastore

Allows you to trigger a profile operation on any current datastore (requires admin permissions on the datastore).

```bash
qualytics run profile --datastore "DATASTORE_ID_LIST" --container_names "CONTAINER_NAMES_LIST" --container_tags "CONTAINER_TAGS_LIST"
--inference_threshold "INFERENCE_THRESHOLD" --infer_as_draft --max_records_analyzed_per_partition "MAX_RECORDS_ANALYZED_PER_PARTITION"
--max_count_testing_sample "MAX_COUNT_TESTING_SAMPLE" --percent_testing_threshold "PERCENT_TESTING_THRESHOLD" --high_correlation_threshold
"HIGH_CORRELATION_THRESHOLD" --greater_than_time "GREATER_THAN_TIME" --greater_than_batch "GREATER_THAN_BATCH" --histogram_max_distinct_values
"HISTOGRAM_MAX_DISTINCT_VALUES" --background
```

| Option                                 | Type     | Description                                                                                                                                      | Required |
|----------------------------------------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------|----------|
| `--datastore`                          | TEXT     | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]"                                                  | Yes      |
| `--container_names`                    | TEXT     | Comma-separated list of container names or array-like format. Example: "container1,container2" or "[container1,container2]"                      | No       |
| `--container_tags`                     | TEXT     | Comma-separated list of container tags or array-like format. Example: "tag1,tag2" or "[tag1,tag2]"                                               | No       |
| `--inference_threshold`                | INT      | Inference quality checks threshold in profile from 0 to 5. Do not include if inference_threshold == 0                                             | No       |
| `--infer_as_draft`                     | BOOL     | Infer all quality checks in profile as DRAFT. Do not include if you want infer_as_draft == False                                                 | No       |
| `--max_records_analyzed_per_partition` | INT      | Number of max records analyzed per partition                                                                                                     | No       |
| `--max_count_testing_sample`           | INT      | The number of records accumulated during profiling for validation of inferred checks. Capped at 100,000                                           | No       |
| `--percent_testing_threshold`          | FLOAT    | Percent of testing threshold                                                                                                                     | No       |
| `--high_correlation_threshold`         | FLOAT    | Number of correlation threshold                                                                                                                  | No       |
| `--greater_than_time`                  | DATETIME | Only include rows where the incremental field's value is greater than this time. Use one of these formats %Y-%m-%dT%H:%M:%S or %Y-%m-%d %H:%M:%S | No       |
| `--greater_than_batch`                 | FLOAT    | Only include rows where the incremental field's value is greater than this number                                                                | No       |
| `--histogram_max_distinct_values`      | INT      | Number of max distinct values in the histogram                                                                                                   | No       |
| `--background`                         | BOOL     | Starts the profile operation but does not wait for the operation to finish                                                                       | No       |


### Run a Scan Operation on a Datastore

Allows you to trigger a scan operation on a datastore (requires admin permissions on the datastore).

```bash
qualytics run scan --datastore "DATASTORE_ID_LIST" --container_names "CONTAINER_NAMES_LIST" --container_tags "CONTAINER_TAGS_LIST"
--incremental --remediation --max_records_analyzed_per_partition "MAX_RECORDS_ANALYZED_PER_PARTITION" --enrichment_source_record_limit
--greater_than_time "GREATER_THAN_TIME" --greater_than_batch "GREATER_THAN_BATCH" --background
```

| Option                                 | Type     | Description                                                                                                                                      | Required |
|----------------------------------------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------|----------|
| `--datastore`                          | TEXT     | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]"                                                  | Yes      |
| `--container_names`                    | TEXT     | Comma-separated list of container names or array-like format. Example: "container1,container2" or "[container1,container2]"                      | No       |
| `--container_tags`                     | TEXT     | Comma-separated list of container tags or array-like format. Example: "tag1,tag2" or "[tag1,tag2]"                                                | No       |
| `--incremental`                        | BOOL     | Process only new or updated records since the last incremental scan                                                                              | No       |
| `--remediation`                        | TEXT     | Replication strategy for source tables in the enrichment datastore. Either 'append', 'overwrite', or 'none'                                      | No       |
| `--max_records_analyzed_per_partition` | INT      | Number of max records analyzed per partition. Value must be greater than or equal to 0                                                           | No       |
| `--enrichment_source_record_limit`     | INT      | Limit of enrichment source records per run. Value must be greater than or equal to -1                                                            | No       |
| `--greater_than_time`                  | DATETIME | Only include rows where the incremental field's value is greater than this time. Use one of these formats %Y-%m-%dT%H:%M:%S or %Y-%m-%d %H:%M:%S | No       |
| `--greater_than_batch`                 | FLOAT    | Only include rows where the incremental field's value is greater than this number                                                                | No       |
| `--background`                         | BOOL     | Starts the scan operation but does not wait for the operation to finish                                                                          | No       |

### Check Operation Status

Allows a user to check an operation's status. Useful if a user triggered an operation but had it running in the background.

```bash
qualytics operation check_status --ids "OPERATION_IDS"
```

| Option  | Type     | Description                                                                                                               | Required |
|---------|----------|---------------------------------------------------------------------------------------------------------------------------|----------|
| `--ids` | TEXT     | Comma-separated list of Operation IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]"                           | Yes      |

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

### Add a New Datastore

Create a new datastore in Qualytics. You can either reference an existing connection by ID or specify a connection name from your `connections.yml` file.

#### Example: Adding a Regular Datastore

```bash
qualytics datastore new \
  --name "Production Analytics" \
  --connection-name "prod_snowflake_connection" \
  --database "ANALYTICS_DB" \
  --schema "PUBLIC" \
  --tags "production,analytics" \
  --teams "data-team,engineering" \
  --trigger-catalog
```

#### Example: Adding an Enrichment Datastore

```bash
qualytics datastore new \
  --name "Data Quality Enrichment" \
  --connection-name "enrichment_db_connection" \
  --database "DQ_ENRICHMENT" \
  --schema "QUALITY" \
  --enrichment-only \
  --enrichment-prefix "dq_" \
  --enrichment-source-record-limit 1000 \
  --enrichment-remediation-strategy "append" \
  --trigger-catalog
```

| Option                                 | Type    | Description                                                                                      | Required |
|----------------------------------------|---------|--------------------------------------------------------------------------------------------------|----------|
| `--name`                               | TEXT    | Name for the datastore                                                                           | Yes      |
| `--connection-name`                    | TEXT    | Connection name from the 'name' field in connections.yml (mutually exclusive with connection-id)| No       |
| `--connection-id`                      | INTEGER | Existing connection ID to reference (mutually exclusive with connection-name)                    | No       |
| `--database`                           | TEXT    | The database name from the connection being used                                                 | Yes      |
| `--schema`                             | TEXT    | The schema name from the connection being used                                                   | Yes      |
| `--tags`                               | TEXT    | Comma-separated list of tags                                                                     | No       |
| `--teams`                              | TEXT    | Comma-separated list of team names                                                               | No       |
| `--enrichment-only`                    | BOOL    | Set if datastore will be an enrichment one (use flag to enable)                                  | No       |
| `--enrichment-prefix`                  | TEXT    | Prefix for enrichment artifacts                                                                  | No       |
| `--enrichment-source-record-limit`     | INTEGER | Limit of enrichment source records (min: 1)                                                      | No       |
| `--enrichment-remediation-strategy`    | TEXT    | Strategy for enrichment: 'append', 'overwrite', or 'none' (default: 'none')                     | No       |
| `--high-count-rollup-threshold`        | INTEGER | High count rollup threshold (min: 1)                                                             | No       |
| `--trigger-catalog`/`--no-trigger-catalog` | BOOL | Whether to trigger catalog after creation (default: True)                                     | No       |
| `--dry-run`                            | BOOL    | Print payload only without making HTTP request                                                   | No       |

**Note**: You must provide either `--connection-name` or `--connection-id`, but not both. Use `--connection-name` to create a new connection from your YAML config, or `--connection-id` to reference an existing connection.

### List All Datastores

```bash
qualytics datastore list
```

### Get a Datastore

Retrieve a datastore by either its ID or name.

**By ID:**
```bash
qualytics datastore get --id DATASTORE_ID
```

**By Name:**
```bash
qualytics datastore get --name "My Datastore Name"
```

| Option   | Type    | Description                                      | Required |
|----------|---------|--------------------------------------------------|----------|
| `--id`   | INTEGER | Datastore ID (mutually exclusive with --name)    | No*      |
| `--name` | TEXT    | Datastore name (mutually exclusive with --id)    | No*      |

**Note**: You must provide either `--id` or `--name`, but not both.

### Remove a Datastore

```bash
qualytics datastore remove --id DATASTORE_ID
```

**Warning**: Use with caution as this will permanently delete the datastore.

---

## Development

This project uses modern Python tooling with [uv](https://docs.astral.sh/uv/) for dependency management and [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

### Requirements

- Python 3.9 or higher
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

# Run all pre-commit hooks (includes linting, formatting, and Python 3.9+ upgrades)
uv run pre-commit run --all-files

# Build the package
uv build

# Run tests (if available)
uv run pytest

# Bump version (patch/minor/major)
bump2version patch   # 0.1.19 -> 0.1.20
bump2version minor   # 0.1.19 -> 0.2.0
bump2version major   # 0.1.19 -> 1.0.0
```

### Code Quality Standards

This project enforces:
- **Python 3.9+** minimum version
- **Ruff** for linting and formatting (88 character line length)
- **pyupgrade** for automatic Python syntax modernization
- **Pre-commit hooks** for automated quality checks

### Project Structure

```
qualytics-cli/
├── qualytics/           # Main package
│   ├── __init__.py
│   └── qualytics.py     # CLI implementation
├── pyproject.toml       # Project configuration & dependencies
└── .pre-commit-config.yaml  # Pre-commit hooks configuration
```

### Contributing

1. Create a new branch for your feature/fix
2. Make your changes
3. Run `uv run ruff check qualytics/` and `uv run ruff format qualytics/`
4. Run `uv run pre-commit run --all-files` to ensure all checks pass
5. Commit your changes (pre-commit hooks will run automatically if installed)
6. Submit a pull request

---

## License

MIT License - see [LICENSE](LICENSE) file for details.
