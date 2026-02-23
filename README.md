# Qualytics CLI

Command-line interface for the [Qualytics](https://www.qualytics.ai/) data quality platform.

[![PyPI](https://img.shields.io/pypi/v/qualytics-cli)](https://pypi.org/project/qualytics-cli/)
[![Python](https://img.shields.io/pypi/pyversions/qualytics-cli)](https://pypi.org/project/qualytics-cli/)
[![Tests](https://github.com/Qualytics/qualytics-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/Qualytics/qualytics-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Manage connections, datastores, containers, quality checks, anomalies, and operations as code. Export your entire Qualytics configuration to git-tracked YAML files and deploy across environments (Dev, Test, Prod) through CI/CD pipelines.

## Installation

```bash
pip install qualytics-cli
```

Or with [uv](https://docs.astral.sh/uv/) (faster):

```bash
uv pip install qualytics-cli
```

**Requirements:** Python 3.10 or higher.

## Quick Start

```bash
# 1. Authenticate via browser (recommended)
qualytics auth login --url "https://your-instance.qualytics.io/"

# Or configure with a token directly
qualytics auth init --url "https://your-instance.qualytics.io/" --token "YOUR_TOKEN"

# 2. Check your authentication status
qualytics auth status

# 3. Create a connection (credentials from environment variables)
qualytics connections create \
  --type postgresql --name prod-pg \
  --host db.example.com --port 5432 \
  --username '${PG_USER}' --password '${PG_PASS}'

# 4. Create a datastore referencing that connection
qualytics datastores create \
  --name "Order Analytics" \
  --connection-name prod-pg \
  --database analytics --schema public

# 5. Export your configuration to YAML
qualytics config export --datastore-id 1 --output ./qualytics-config

# 6. Preview what an import would do (without making changes)
qualytics config import --input ./qualytics-config --dry-run
```

## Configuration

### Authentication

```bash
# Browser-based login (opens your Qualytics instance login page)
qualytics auth login --url "https://your-instance.qualytics.io/"

# Manual token configuration
qualytics auth init --url "https://your-instance.qualytics.io/" --token "YOUR_TOKEN"

# For self-signed certificates
qualytics auth init --url "https://..." --token "..." --no-verify-ssl
```

Configuration is saved to `~/.qualytics/config.yaml`. View your auth status with:

```bash
qualytics auth status
```

### Environment Variables

The CLI loads environment variables from a `.env` file in your working directory (via `python-dotenv`). You can use `${ENV_VAR}` syntax in any CLI flag that accepts sensitive values:

```bash
export QUALYTICS_URL="https://your-instance.qualytics.io/"
export QUALYTICS_TOKEN="your-jwt-token"
qualytics auth init --url '${QUALYTICS_URL}' --token '${QUALYTICS_TOKEN}'
```

## Command Reference

Run `qualytics <command> --help` for full flag details on any command.

### Authentication

| Command | Description |
|---------|-------------|
| `auth login` | Authenticate via browser (opens login page, receives token callback) |
| `auth status` | Display authentication status (URL, masked token, expiry, SSL) |
| `auth init` | Configure URL, token, and SSL settings manually |

### Connections

| Command | Description |
|---------|-------------|
| `connections create` | Create a connection with inline flags and `${ENV_VAR}` support |
| `connections update` | Update connection fields (partial update) |
| `connections get` | Get a connection by `--id` or `--name` |
| `connections list` | List connections, filterable by `--type` and `--name` |
| `connections delete` | Delete a connection by `--id` |
| `connections test` | Test connectivity, optionally with override credentials |

### Datastores

| Command | Description |
|---------|-------------|
| `datastores create` | Create a datastore with `--connection-name` or `--connection-id` |
| `datastores update` | Update datastore fields (partial update) |
| `datastores get` | Get a datastore by `--id` or `--name` |
| `datastores list` | List datastores, filterable by `--type`, `--tag`, `--name` |
| `datastores delete` | Delete a datastore by `--id` |
| `datastores verify` | Test the connection for an existing datastore |
| `datastores enrichment` | Link (`--link`) or unlink (`--unlink`) an enrichment datastore |

### Containers

| Command | Description |
|---------|-------------|
| `containers create` | Create a computed container (`computed_table`, `computed_file`, `computed_join`) |
| `containers update` | Update a container (GET-merge-PUT pattern) |
| `containers get` | Get a container by `--id`, optionally with `--profiles` |
| `containers list` | List containers for a `--datastore-id`, filterable by `--type`, `--tag` |
| `containers delete` | Delete a container by `--id` (cascades to fields, checks, anomalies) |
| `containers validate` | Dry-run validation of a computed container definition |
| `containers import` | Bulk import computed tables from Excel, CSV, or TXT files |
| `containers preview` | Preview computed table definitions before importing |

### Quality Checks

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

### Anomalies

| Command | Description |
|---------|-------------|
| `anomalies get` | Get an anomaly by `--id` |
| `anomalies list` | List anomalies for a `--datastore-id`, filterable by status, type, date |
| `anomalies update` | Update status to `Active` or `Acknowledged` (single or bulk) |
| `anomalies archive` | Soft-delete with status: `Resolved`, `Invalid`, `Duplicate`, `Discarded` |
| `anomalies delete` | Hard-delete anomalies (single or bulk) |

### Operations

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

### Config (Export/Import)

| Command | Description |
|---------|-------------|
| `config export` | Export configuration as hierarchical YAML (connections, datastores, containers, checks) |
| `config import` | Import configuration with dependency-ordered upsert and `--dry-run` support |

### MCP (LLM Integration)

| Command | Description |
|---------|-------------|
| `mcp serve` | Start MCP server for Claude Code, Cursor, and other LLM tools |

### Schedule

| Command | Description |
|---------|-------------|
| `schedule export-metadata` | Schedule cron-based metadata exports |

## Secrets Management

The CLI never stores credentials in plaintext. Sensitive flags support `${ENV_VAR}` syntax, resolved from environment variables at runtime.

**Supported on these flags:** `--host`, `--username`, `--password`, `--access-key`, `--secret-key`, `--uri`, `--token`

```bash
# Set credentials as environment variables
export PG_USER=analyst
export PG_PASS=s3cret

# Reference them in CLI commands
qualytics connections create --type postgresql --name prod-pg \
  --host db.example.com --username '${PG_USER}' --password '${PG_PASS}'
```

**In CI/CD pipelines:**

```bash
# GitHub Actions — use repository secrets
qualytics connections create --type postgresql --name prod-pg \
  --host "${{ secrets.PG_HOST }}" --password "${{ secrets.PG_PASS }}"
```

**In exported YAML files:**

Secrets are replaced with `${ENV_VAR}` placeholders on export. On import, the CLI resolves them from the environment:

```yaml
# connections/prod_pg.yaml (exported)
name: prod_pg
type: postgresql
host: ${PROD_PG_HOST}
username: ${PROD_PG_USERNAME}
password: ${PROD_PG_PASSWORD}
```

```bash
# Set env vars before import
export PROD_PG_HOST=db.example.com
export PROD_PG_USERNAME=analyst
export PROD_PG_PASSWORD=s3cret
qualytics config import --input ./qualytics-config
```

All CLI output automatically redacts sensitive fields.

## Config Export/Import

The `config` command group enables config-as-code workflows. Export your Qualytics configuration to a hierarchical YAML folder structure, track it in git, and import it into any environment.

### Export

```bash
# Export one or more datastores
qualytics config export --datastore-id 42 --datastore-id 43 --output ./qualytics-config

# Export only specific resource types
qualytics config export --datastore-id 42 --include connections,datastores
```

This produces:

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
      checks/
        orders/
          notnull__order_id.yaml        # One file per quality check
          between__total_amount.yaml
```

Key behaviors:
- Secrets are replaced with `${ENV_VAR}` placeholders (never exported in plaintext)
- Connections are deduplicated across datastores (exported once by name)
- Only computed containers are exported (tables/views/files are created by catalog)
- Re-export produces zero git diff when nothing has changed
- ID references are replaced with name references for cross-environment portability

### Import

```bash
# Import everything
qualytics config import --input ./qualytics-config

# Preview what would change
qualytics config import --input ./qualytics-config --dry-run

# Import only specific resource types
qualytics config import --input ./qualytics-config --include connections,datastores
```

Import follows dependency order:
1. **Connections** -- matched by `name` (create or update)
2. **Datastores** -- matched by `name`, resolves `connection_name` to ID
3. **Containers** -- matched by `name` within datastore, resolves references
4. **Quality checks** -- matched by `_qualytics_check_uid` (upsert)

### CI/CD Promotion

```bash
# Export from Dev
qualytics config export --datastore-id $DEV_DS --output ./config

# Commit (secrets are placeholders)
git add ./config && git commit -m "Export from dev"

# Import to Prod (secrets from CI env vars)
qualytics config import --input ./config
```

For a complete GitHub Actions workflow, see [docs/examples/github-actions-promotion.md](docs/examples/github-actions-promotion.md).

## Computed Containers

Create SQL-based virtual containers and automatically generate quality checks for error detection.

```bash
# Create a single computed table
qualytics containers create --type computed_table --name ct_orders \
  --datastore-id 42 --query "SELECT * FROM orders WHERE total < 0"

# Bulk import from Excel/CSV
qualytics containers import --datastore 42 --input checks.xlsx --as-draft

# Preview before importing
qualytics containers preview --input checks.xlsx
```

For the full guide covering input file formats, validation rules, check behavior, and all use cases, see [docs/computed-tables.md](docs/computed-tables.md).

## LLM Integration (MCP Server)

The CLI includes a built-in [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server, enabling Claude Code, Cursor, Windsurf, and other AI tools to call Qualytics operations directly as structured tool calls.

### Setup for Claude Code

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "qualytics": {
      "command": "qualytics",
      "args": ["mcp", "serve"]
    }
  }
}
```

Then in Claude Code you can say things like:

> "List all datastores and show me which ones have failing quality checks"
> "Create a computed table that finds orders with negative totals"
> "Run a scan on datastore 42 and check for new anomalies"

Claude Code will call the appropriate tools directly and get structured JSON responses.

### Available Tools

35 tools across 8 groups: `auth_status`, `list_datastores`, `list_containers`, `list_checks`, `list_anomalies`, `run_scan`, `export_config`, and more. Run `qualytics mcp serve --help` for details.

### Running the Server

```bash
# STDIO transport (default — used by Claude Code and Cursor)
qualytics mcp serve

# Streamable-HTTP transport (network-accessible)
qualytics mcp serve --transport streamable-http --port 8000
```

## Development

```bash
git clone https://github.com/Qualytics/qualytics-cli.git
cd qualytics-cli
uv sync                              # Install dependencies
uv run pytest                        # Run tests (472 tests)
uv run pre-commit run --all-files    # Lint, format, type checks
```

For architecture details, code conventions, and contribution guidelines, see [AGENTS.md](AGENTS.md).

## License

MIT License -- see [LICENSE](LICENSE) for details.
