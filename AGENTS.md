# AGENTS.md - Qualytics CLI Project Guide

## Project Overview

**Qualytics CLI** is a command-line interface for the Qualytics data quality platform. It wraps the Qualytics controlplane REST API, enabling users to manage quality checks, datastores, containers, and operations (catalog, profile, scan) programmatically.

**License:** MIT
**Language:** Python 3.10+
**Build Backend:** hatchling
**Package Manager:** uv

---

## Repository Structure

```
qualytics-cli/
├── .github/workflows/
│   ├── ci.yml               # PR validation: lint, test, pre-commit
│   ├── publish.yml           # Tag-triggered: build + publish to PyPI + GitHub Release
│   └── release.yml           # Manual dispatch: version bump → commit → tag → push
├── qualytics/
│   ├── __init__.py
│   ├── qualytics.py          # Entry point — registers all Typer sub-apps
│   ├── config.py             # Configuration management (load/save/validate)
│   ├── api/
│   │   ├── client.py         # Centralized API client (QualyticsClient)
│   │   ├── anomalies.py      # Anomaly API operations (CRUD + bulk)
│   │   ├── containers.py     # Container API operations (CRUD + validate + field profiles)
│   │   ├── connections.py    # Connection API operations (CRUD + test)
│   │   ├── datastores.py     # Datastore API operations (CRUD + verify + enrichment)
│   │   ├── operations.py     # Operation API operations (run, get, list, abort)
│   │   └── quality_checks.py # Quality checks API operations (CRUD + bulk)
│   ├── cli/
│   │   ├── main.py           # Deprecated wrappers (init → auth init, show-config → auth status)
│   │   ├── anomalies.py      # anomalies get/list/update/archive/delete commands
│   │   ├── checks.py         # checks CRUD + git-friendly export/import
│   │   ├── auth.py           # auth login/status/init commands
│   │   ├── connections.py    # connections create/update/get/list/delete/test commands
│   │   ├── containers.py     # containers create/update/get/list/delete/validate/import/preview commands
│   │   ├── datastores.py     # datastores create/update/get/list/delete/verify/enrichment commands
│   │   ├── export_import.py  # config export/import (config-as-code)
│   │   ├── operations.py     # operations catalog/profile/scan/materialize/export/get/list/abort commands
│   │   ├── mcp_cmd.py        # mcp serve CLI command
│   │   ├── computed_tables.py # Internal helpers for computed table import and preview (used by containers.py)
│   │   └── schedule.py       # schedule export-metadata command
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── server.py          # FastMCP server — all MCP tools (wraps api/ and services/ layer)
│   ├── services/
│   │   ├── quality_checks.py # Quality check business logic
│   │   ├── connections.py    # Connection lookup, payload building, name resolution
│   │   ├── containers.py     # Container business logic (name resolution, payload building)
│   │   ├── datastores.py     # Datastore lookup, payload building, name resolution
│   │   ├── export_import.py  # Config-as-code export/import orchestration
│   │   └── operations.py     # Operation execution and polling
│   └── utils/
│       ├── validation.py     # URL normalization
│       ├── file_ops.py       # Error logging, file deduplication
│       ├── secrets.py        # Env var resolution and sensitive field redaction
│       └── serialization.py  # YAML/JSON load, dump, display, format detection
├── tests/
│   ├── conftest.py           # Shared fixtures (cli_runner)
│   ├── test_anomalies.py     # Anomaly API + CLI tests
│   ├── test_cli.py           # CLI smoke tests (command registration)
│   ├── test_connections.py   # Connection API + service + secrets + CLI tests
│   ├── test_containers.py    # Container API + service + CLI tests
│   ├── test_datastores.py    # Datastore API + service + CLI tests
│   ├── test_export_import.py # Config export/import service + CLI tests
│   ├── test_operations.py    # Operation API + service + CLI tests
│   ├── test_client.py        # API client unit tests
│   ├── test_config.py        # Configuration and token validation tests
│   ├── test_quality_checks.py # Quality checks API + CLI + service tests
│   └── test_serialization.py # Serialization utilities tests
├── pyproject.toml            # Project config (hatchling, dependencies, tools)
├── uv.lock                   # Locked dependency versions (committed)
├── .pre-commit-config.yaml   # Pre-commit hooks
├── docs/
│   └── examples/
│       └── github-actions-promotion.md  # CI/CD promotion workflow guide
├── AGENTS.md                 # This file
└── README.md                 # User-facing documentation
```

---

## Architecture

### Layered Design

```
CLI layer (cli/)          ← Typer commands, user interaction, argument parsing
    ↓
Service layer (services/) ← Business logic, orchestration, pagination
    ↓
API layer (api/)          ← Centralized HTTP client, thin wrappers
    ↓
Config (config.py)        ← Load/save/validate configuration
```

**Key rule:** Only `api/client.py` imports `requests`. All other modules use `QualyticsClient`.

### API Client (`api/client.py`)

All HTTP communication goes through the centralized `QualyticsClient` class:

```python
from qualytics.api.client import get_client

client = get_client()           # Loads config, validates token, returns client
response = client.get("quality-checks", params={"datastore": 1})
response = client.post("operations/run", json={"type": "catalog", ...})
```

The client provides:
- `requests.Session`-based connection pooling with persistent Bearer auth
- Configurable SSL verification (from config)
- Configurable request timeout (default 30s)
- Automatic URL construction from path fragments

### Exception Hierarchy

Non-2xx responses raise typed exceptions:

```
QualyticsAPIError (base)
├── AuthenticationError  ← 401, 403
├── NotFoundError        ← 404
├── ConflictError        ← 409
└── ServerError          ← 5xx
```

CLI commands catch specific exceptions for business logic (e.g., `ConflictError` for upsert patterns in `checks import`) and let unexpected errors propagate.

### SSL Verification

SSL verification is **secure by default** (`True`) and configurable per installation:

- `qualytics auth init --no-verify-ssl` saves `ssl_verify: false` to `~/.qualytics/config.yaml`
- `QualyticsClient` reads `ssl_verify` from config
- `InsecureRequestWarning` is suppressed only when SSL is explicitly disabled
- `qualytics auth status` displays the current SSL status

### Operations (`api/operations.py`, `services/operations.py`, `cli/operations.py`)

Full operation lifecycle management — trigger, monitor, list, and abort operations.

**Supported operation types:** `catalog`, `profile`, `scan`, `materialize`, `export`

**Architecture:**
- `api/operations.py` — 5 thin HTTP wrappers: `run_operation`, `get_operation`, `list_operations`, `list_all_operations`, `abort_operation`
- `services/operations.py` — business logic: `run_catalog`, `run_profile`, `run_scan`, `run_materialize`, `run_export`, `wait_for_operation`, `_handle_operation_result`
- `cli/operations.py` — 8 CLI commands under `qualytics operations`

**Polling behavior:**
| Setting | Default | CLI Flag |
|---------|---------|----------|
| Poll interval | 10 seconds | `--poll-interval` |
| Timeout | 1800 seconds (30 min) | `--timeout` |

- Shows progress counters (containers analyzed, records processed) every 60s for profile/scan
- Returns `None` on timeout, allowing callers to handle gracefully
- Background mode (`--background`) skips polling entirely

### Quality Checks (`services/quality_checks.py`)

Git-friendly export/import with upsert support for multi-environment promotion (Dev → Test → Prod).

**Export format:** One YAML file per check, organized by container subdirectory:
```
checks/
  orders/
    notnull__order_id.yaml
    between__total_amount.yaml
  customers/
    matchespattern__email.yaml
```

**Stable UID:** Each exported check contains `_qualytics_check_uid` in `additional_metadata`, computed as `{container}__{rule_type}__{sorted_fields}`. This enables upsert on import — matching UIDs update existing checks, new UIDs create new checks.

**Portable fields:** `rule_type`, `description`, `container` (by name), `fields` (by name), `coverage`, `filter`, `properties`, `tags` (by name), `status`, `additional_metadata`. Environment-specific fields (IDs, timestamps, anomaly counts) are stripped on export.

**Multi-datastore import:** `checks import --datastore-id 1 --datastore-id 2` processes each datastore independently, resolving container names to IDs within each target.

### Anomalies (`api/anomalies.py`, `cli/anomalies.py`)

Anomaly CRUD for CI/CD gating and status management. Anomalies are created by failed quality checks during scan operations — there is no "create" command.

**Status model:**
- **Open statuses** (via `update` command → PUT/PATCH): `Active`, `Acknowledged`
- **Archive statuses** (via `archive` command → DELETE with `archive=true`): `Resolved`, `Invalid`, `Duplicate`, `Discarded`
- **Hard delete** (via `delete` command → DELETE with `archive=false`): permanent removal

**API functions:**
- `list_anomalies()` — GET /anomalies with 14+ filter params (datastore, container, quality_check, status, anomaly_type, tag, rule_type, start_date, end_date, timeframe, archived, sort_created, sort_weight)
- `list_all_anomalies()` — auto-paginate across all pages
- `get_anomaly()` — GET /anomalies/{id}
- `update_anomaly()` — PUT /anomalies/{id} (single, open statuses only)
- `bulk_update_anomalies()` — PATCH /anomalies (bulk, open statuses only)
- `delete_anomaly()` — DELETE /anomalies/{id} (archive or hard-delete)
- `bulk_delete_anomalies()` — DELETE /anomalies (bulk archive or hard-delete)

**CLI commands:**
- `get` — single anomaly by `--id`
- `list` — filterable by `--datastore-id`, `--container`, `--check-id`, `--status`, `--type`, `--tag`, `--start-date`, `--end-date`
- `update` — single (`--id`) or bulk (`--ids`), validates open statuses only
- `archive` — single or bulk soft-delete with status (default: `Resolved`)
- `delete` — single or bulk hard-delete

**CI use case:**
```bash
# Gate CI pipeline on active anomalies
ANOMALIES=$(qualytics anomalies list --datastore-id $DS --status Active --format json)
COUNT=$(echo "$ANOMALIES" | python -c "import sys,json; print(len(json.load(sys.stdin)))")
if [ "$COUNT" -gt "0" ]; then echo "FAIL: $COUNT active anomalies"; exit 1; fi
```

### Connections (`api/connections.py`, `services/connections.py`, `cli/connections.py`)

Full connection lifecycle management — create, update, get, list, delete, and test connections. Connections are the most sensitive resource because they hold database credentials.

**Secrets strategy:**
- Sensitive CLI flags (`--host`, `--username`, `--password`, `--access-key`, `--secret-key`, `--uri`) support `${ENV_VAR}` syntax, resolved via `os.path.expandvars()` before being sent to the API
- Unresolved `${VAR}` placeholders raise an error and abort
- All CLI output is redacted via `redact_payload()` from `utils/secrets.py`
- Sensitive fields never touch disk in plaintext

**Architecture:**
- `api/connections.py` — 7 thin HTTP wrappers: `create_connection`, `update_connection`, `get_connection_api`, `list_connections`, `list_all_connections`, `delete_connection`, `test_connection`
- `services/connections.py` — business logic: `get_connection_by`, `get_connection_by_name`, `build_create_connection_payload`, `build_update_connection_payload`
- `cli/connections.py` — 6 CLI commands under `qualytics connections`

**`--parameters` JSON catch-all:** For type-specific fields that don't have dedicated flags (e.g., `--parameters '{"role": "ADMIN", "warehouse": "WH"}'`). Merged last, overrides dedicated flags.

**CLI commands:**
- `create` — inline flags with `${ENV_VAR}` support, `--dry-run` support
- `update` — partial update: only provided fields are sent
- `get` — by `--id` or `--name`, secrets redacted in output
- `list` — filterable by `--name`, `--type` (comma-separated), all connections redacted
- `delete` — by `--id`, handles 409 when datastores still reference it
- `test` — test existing or with override credentials (`--host`, `--username`, `--password`)

### Config Export/Import (`services/export_import.py`, `cli/export_import.py`)

Config-as-code: export and import Qualytics configuration as a hierarchical YAML folder structure for git-tracked, cross-environment deployment.

**Folder structure:**
```
qualytics-export/
  connections/
    prod_pg.yaml
  datastores/
    prod_warehouse/
      _datastore.yaml
      containers/
        filtered_orders/
          _container.yaml
          computed_fields/
            order_margin.yaml
      checks/
        orders/
          notnull__order_id.yaml
```

**Export behavior:**
- `export_config()` fetches connections, datastores, computed containers, computed fields, and quality checks for given datastore IDs
- Connections are deduplicated across datastores (exported once by name)
- Secret fields (password, secret_key, etc.) are replaced with `${ENV_VAR}` placeholders
- Only computed containers are exported (table/view/file are created by catalog operations)
- `_write_yaml()` only writes when content changes — re-export produces zero git diff
- ID references are replaced with name references for portability

**Import behavior (dependency order):**
1. **Connections** — upsert by `name`, resolve `${ENV_VAR}` from environment
2. **Datastores** — upsert by `name`, resolve `connection_name` → `connection_id`, link enrichment
3. **Containers** — upsert computed containers by `name` within datastore, resolve name references to IDs
4. **Computed fields** — upsert by `name` within container
5. **Quality checks** — reuses existing `import_checks_to_datastore()` with `_qualytics_check_uid` upsert

**Natural keys for upsert:**
- Connection: `name` (globally unique)
- Datastore: `name` (globally unique)
- Container: `name` within datastore
- Computed field: `name` within container
- Quality check: `_qualytics_check_uid` in `additional_metadata`

**CLI commands:**
- `config export --datastore-id <id> [--output <dir>] [--include <types>]`
- `config import --input <dir> [--dry-run] [--include <types>]`

**`--include` filter:** Comma-separated resource types to include: `connections,datastores,containers,computed_fields,checks`. Defaults to all.

### Datastores (`api/datastores.py`, `services/datastores.py`, `cli/datastores.py`)

Full datastore lifecycle management — create, update, get, list, delete, verify connections, and manage enrichment links.

**Architecture:**
- `api/datastores.py` — 10 thin HTTP wrappers: `create_datastore`, `update_datastore`, `get_datastore`, `list_datastores`, `list_all_datastores`, `delete_datastore`, `verify_connection`, `validate_connection`, `connect_enrichment`, `disconnect_enrichment`
- `services/datastores.py` — business logic: `get_datastore_by`, `get_datastore_by_name`, `build_create_datastore_payload`, `build_update_datastore_payload`
- `cli/datastores.py` — 7 CLI commands under `qualytics datastores`

**CLI commands:**
- `create` — create with `--connection-name` (YAML lookup + auto-create) or `--connection-id`, `--dry-run` support
- `update` — partial update: name, connection, database, schema, tags, teams, enrichment settings
- `get` — by `--id` or `--name` with `--format yaml|json`
- `list` — paginated with `--name`, `--type`, `--tag`, `--enrichment-only` filters
- `delete` — by `--id`
- `verify` — test connection for an existing datastore (CI health checks)
- `enrichment` — `--link <id>` to connect or `--unlink` to disconnect enrichment datastore

### Containers (`api/containers.py`, `services/containers.py`, `cli/containers.py`)

Full container lifecycle management — create computed containers, update, get, list, delete, and validate definitions.

**Container types:** 6 total (`table`, `view`, `file`, `computed_table`, `computed_file`, `computed_join`). Only the 3 computed types can be created/updated via CLI — non-computed types are created during catalog operations.

**Architecture:**
- `api/containers.py` — 9 thin HTTP wrappers: `create_container`, `update_container`, `get_container`, `list_containers`, `list_all_containers`, `delete_container`, `validate_container`, `get_field_profiles`, `list_containers_listing`
- `services/containers.py` — business logic: `get_table_ids`, `get_container_by_name`, `build_create_container_payload`, `build_update_container_payload`
- `cli/containers.py` — 8 CLI commands under `qualytics containers`

**Polymorphic create:** The `--type` flag discriminates between computed types, each requiring different fields:
- `computed_table`: `--datastore-id`, `--name`, `--query`
- `computed_file`: `--datastore-id`, `--name`, `--source-container-id`, `--select-clause`
- `computed_join`: `--name`, `--left-container-id`, `--right-container-id`, `--left-key-field`, `--right-key-field`, `--select-clause`

**Update pattern (GET-merge-PUT):** Updates fetch the existing container, overlay user changes via `build_update_container_payload()`, and PUT the merged payload. The `container_type` discriminator is always preserved.

**409 handling:** When updating a computed container would drop fields that have associated quality checks or anomalies, the API returns 409. The CLI prints what would be dropped and fails unless `--force-drop-fields` is passed.

**CLI commands:**
- `create` — polymorphic by `--type`, with `--dry-run` support
- `update` — GET-merge-PUT with `--force-drop-fields` for 409 conflicts
- `get` — by `--id`, optional `--profiles` to include field profiles
- `list` — requires `--datastore-id`, filterable by `--type`, `--name`, `--tag`, `--search`, `--archived`
- `delete` — by `--id` (cascades to fields, checks, anomalies)
- `validate` — dry-run validation of computed container definitions against the API
- `import` — bulk import computed tables from file (.xlsx, .csv, .txt) with auto-check creation
- `preview` — preview computed table definitions from file without importing

### Serialization (`utils/serialization.py`)

YAML is the default format for all CLI input/output. JSON is supported via `--format json`.

**Key conventions:**
- Default export/import files use `.yaml` extension
- `--format yaml|json` flag on export and display commands (checks export, datastore list/get/create)
- Import commands auto-detect format by file extension (`.json` → JSON, everything else → YAML)
- Smart inference: `--output file.json` with default `--format yaml` infers JSON
- `_SafeStringLoader` prevents YAML from parsing ISO date strings as `datetime` objects
- `yaml.safe_dump(sort_keys=False)` preserves key order for human-readable output

```python
from qualytics.utils import OutputFormat, load_data_file, dump_data_file, format_for_display

data = load_data_file("checks.yaml")          # Auto-detects format
dump_data_file(data, "out.yaml", OutputFormat.YAML)
print(format_for_display(data, OutputFormat.JSON))
```

### MCP Server (`mcp/server.py`)

Model Context Protocol server for LLM tool integrations (Claude Code, Cursor, Windsurf).

**Architecture:** MCP tools call the **same api/ and services/ functions** as the CLI, just without the Typer/Rich formatting layer. Returns raw dicts/lists for structured JSON responses.

```
CLI layer (typer/rich)  →  services/  →  api/  →  Qualytics API
                               ↑
MCP layer (fastmcp)  ─────────┘
```

**35 MCP tools** across 8 groups: auth, connections, datastores, containers, checks, anomalies, operations, config.

**Error handling:** `_client()` converts `SystemExit` → `ToolError`. `_api_call()` converts `QualyticsAPIError` → `ToolError`. LLMs see structured error messages.

**Setup for Claude Code** (`~/.claude.json`):
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

---

## Configuration

### User Data Directory: `~/.qualytics/`

| File | Purpose |
|------|---------|
| `config.yaml` | URL, token, ssl_verify (auto-migrated from legacy `config.json`) |
| `data_checks.yaml` | Default checks export location |
| `data_checks_template.yaml` | Default templates export location |
| `errors-{date}.log` | Import operation errors |
| `operation-error.txt` | Operation execution errors |
| `logs/` | Debug logs (containers import --debug) |

### Token Validation

JWT tokens are validated for expiration before each operation. Expired tokens produce a warning and exit.

---

## CLI Command Structure

| Command Group | Subcommands | Description |
|--------------|-------------|-------------|
| `auth` | `login`, `status`, `init` | Authentication: browser login, status display, manual token init |
| `anomalies` | `get`, `list`, `update`, `archive`, `delete` | Anomaly management (status updates, archiving, deletion) |
| `checks` | `create`, `get`, `list`, `update`, `delete`, `export`, `import`, `export-templates`, `import-templates` | Quality check CRUD + git-friendly export/import |
| `config` | `export`, `import` | Config-as-code: export/import connections, datastores, containers, and checks as hierarchical YAML |
| `connections` | `create`, `update`, `get`, `list`, `delete`, `test` | Connection CRUD with secrets management + connectivity testing |
| `containers` | `create`, `update`, `get`, `list`, `delete`, `validate`, `import`, `preview` | Container CRUD + validation + bulk import |
| `datastores` | `create`, `update`, `get`, `list`, `delete`, `verify`, `enrichment` | Datastore CRUD + connection verification + enrichment linking |
| `operations` | `catalog`, `profile`, `scan`, `materialize`, `export`, `get`, `list`, `abort` | Operation lifecycle (trigger, monitor, abort) |
| `mcp` | `serve` | MCP server for Claude Code, Cursor, and other LLM tools |
| `schedule` | `export-metadata` | Cron-based export scheduling |
| ~~`init`~~ | — | **Deprecated** → `auth init` |
| ~~`show-config`~~ | — | **Deprecated** → `auth status` |

---

## Build & Tooling

### Build System

- **Backend:** hatchling (PEP 517/621 compliant)
- **Package manager:** uv (dependency resolution, lockfile, building, publishing, versioning)
- **Entry point:** `qualytics` console script → `qualytics.qualytics:app`

### Dependencies (Runtime)

| Package | Purpose |
|---------|---------|
| typer | CLI framework |
| rich | Terminal output (tables, progress bars, colors) |
| requests | HTTP client (used only in `api/client.py`) |
| pyjwt | JWT token validation |
| croniter | Cron expression validation |
| pyyaml | YAML serialization (config, export/import, display) |
| openpyxl | Excel file reading |
| fastmcp | MCP (Model Context Protocol) server framework (v3) |
| urllib3 | SSL warning suppression |

### Dev Dependencies

| Package | Purpose |
|---------|---------|
| ruff | Linting and formatting |
| pre-commit | Git hook automation |
| pytest | Test framework |
| pytest-cov | Coverage reporting |

---

## CI/CD

Three GitHub Actions workflows work together:

### 1. `ci.yml` — PR Validation

Triggers on pull requests to `main`:
- Linting: `ruff check`
- Formatting: `ruff format --check`
- Tests: `pytest` across Python 3.10, 3.11, 3.12, 3.13, 3.14
- Pre-commit: all hooks

### 2. `release.yml` — Version Bump (Manual Dispatch)

Triggered manually from GitHub Actions UI:
1. Accepts `bump` input: `patch`, `minor`, or `major`
2. Runs `uv version --bump {input}`
3. Commits `pyproject.toml` + `uv.lock`
4. Creates git tag `v{version}`
5. Pushes to `main` with tags (triggers publish.yml)

### 3. `publish.yml` — Build & Publish (Tag-Triggered)

Triggers on `v*` tags:
1. Builds wheel + sdist with `uv build`
2. Publishes to PyPI via OIDC trusted publishing (no stored secrets)
3. Creates GitHub Release with the tag

```
Manual trigger → release.yml → tag push → publish.yml → PyPI + GitHub Release
```

---

## Testing

### Running Tests

```bash
uv run pytest                           # Run all tests
uv run pytest -v                        # Verbose output
uv run pytest --cov --cov-report=term-missing  # With coverage
```

### Test Organization

| File | Coverage |
|------|----------|
| `test_auth.py` | Auth commands: callback server, login flow, status display, init, deprecated wrappers |
| `test_cli.py` | Smoke tests: CLI loads, all command groups registered |
| `test_mcp.py` | MCP server: tool registration, auth status, helpers, all tool groups, CLI command |
| `test_client.py` | QualyticsClient: URL building, SSL config, exception hierarchy, get_client factory |
| `test_config.py` | Config loading, saving, token validation, legacy JSON migration |
| `test_anomalies.py` | API layer (list, get, update, bulk update, delete, bulk delete), CLI commands (get, list, update, archive, delete), status validation, bulk operations |
| `test_connections.py` | API layer (create, update, get, list, list_all, delete, test), service layer (get_connection_by, build payloads), secrets (env var resolution, redaction), CLI commands (create, update, get, list, delete, test), 409 handling |
| `test_export_import.py` | Helpers (slugify, write_yaml, env var names), strip functions (connections, datastores, containers), import functions (connections, datastores, containers with upsert), export orchestrator (full, filtered, deduplication), import orchestrator (full, filtered), CLI commands (export, import, dry-run, error display) |
| `test_containers.py` | API layer (create, update, get, list, list_all, delete, validate, field_profiles, listing), service layer (get_container_by_name, build payloads), CLI commands (create, update, get, list, delete, validate), polymorphic create, 409 handling |
| `test_datastores.py` | API layer (create, update, get, list, list_all, delete, verify, validate, enrichment connect/disconnect), service layer (get_datastore_by, build payloads), CLI commands (create, update, get, list, delete, verify, enrichment), validation |
| `test_operations.py` | API layer (run, get, list, list_all, abort), service layer (polling, multi-datastore, background mode, payload construction), CLI commands (catalog, profile, scan, materialize, export, get, list, abort), validation |
| `test_quality_checks.py` | API layer (endpoints, params, pagination), CLI commands (all 9), service import (upsert, dry-run, multi-datastore), promotion workflow, edge cases |
| `test_serialization.py` | Format detection, YAML/JSON load/dump, datetime preservation, display formatting |

### Conventions

- Fixtures in `conftest.py` (e.g., `cli_runner`)
- Use `unittest.mock.patch` for external dependencies
- Patch at the source module (e.g., `qualytics.config.load_config`, not `qualytics.api.client.load_config`)

---

## Code Quality

### Pre-commit Hooks (`.pre-commit-config.yaml`)

| Hook | Purpose |
|------|---------|
| pre-commit-hooks (v6.0.0) | Large files, JSON/TOML/YAML validation, trailing whitespace, private key detection |
| ruff-check + ruff-format (v0.15.1) | Linting and formatting |
| pyupgrade (v3.21.2) | Enforce Python 3.10+ idioms |

### Ruff Configuration

- Line length: 88
- Target: Python 3.10
- Lint rules: E4, E7, E9, F (pycodestyle + pyflakes)
- Quote style: double
- Import sorting: isort with `qualytics` as first-party

### Type Annotations

Use Python 3.10+ syntax everywhere. Do not use `from __future__ import annotations` or legacy `typing` imports:

| Use | Instead of |
|-----|------------|
| `str \| None` | `Optional[str]` |
| `list[str]` | `List[str]` |
| `dict[str, Any]` | `Dict[str, Any]` |
| `tuple[str, ...]` | `Tuple[str, ...]` |

Only import from `typing` when needed for constructs that have no builtin equivalent (e.g., `Annotated`, `Any`, `Callable`, `Literal`).

---

## Development Workflow

```bash
# Setup
uv sync                              # Install all dependencies
uv run pre-commit install            # Install git hooks

# Day-to-day
uv run qualytics --help              # Run CLI
uv run pytest                        # Run tests
uv run ruff check .                  # Lint
uv run ruff format .                 # Format
uv run pre-commit run --all-files    # All quality checks

# Build & version
uv build                             # Build wheel + sdist
uv version --short                   # Show current version
```

### Adding a New CLI Command

1. Create or edit a file in `cli/` with a Typer sub-app
2. Use `get_client()` from `api/client.py` for API calls — never import `requests` directly
3. Catch `QualyticsAPIError` subclasses for expected error conditions
4. Register the sub-app in `qualytics/qualytics.py`
5. Add smoke test in `tests/test_cli.py`
6. Run `uv run pre-commit run --all-files` before committing

### Adding a New Service Function

1. Add function to the appropriate `services/` module
2. Accept `client: QualyticsClient` as the first parameter
3. Use `client.get()`, `client.post()`, etc. — the client handles auth, SSL, and error raising
4. Let exceptions propagate to the CLI layer for user-facing error messages

---

## API Integration

### Endpoints Used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/anomalies` | List anomalies (paginated, with filters) |
| GET | `/anomalies/{id}` | Get a single anomaly |
| PUT | `/anomalies/{id}` | Update anomaly (status, description, tags) |
| PATCH | `/anomalies` | Bulk update anomalies |
| DELETE | `/anomalies/{id}` | Delete/archive a single anomaly |
| DELETE | `/anomalies` | Bulk delete/archive anomalies |
| GET | `/quality-checks` | Fetch quality checks (paginated) |
| POST | `/quality-checks` | Create quality checks |
| GET | `/quality-checks/{id}` | Get a single quality check |
| PUT | `/quality-checks/{id}` | Update quality checks |
| DELETE | `/quality-checks/{id}` | Delete a single quality check |
| DELETE | `/quality-checks` | Bulk delete quality checks |
| POST | `/containers` | Create computed containers |
| PUT | `/containers/{id}` | Update container (full PUT) |
| GET | `/containers/{id}` | Get container by ID |
| GET | `/containers` | List containers (paginated, with filters) |
| DELETE | `/containers/{id}` | Delete container (cascades) |
| POST | `/containers/validate` | Validate computed container definition |
| GET | `/containers/{id}/field-profiles` | Get field profiles |
| GET | `/containers/listing` | Lightweight container listing (non-paginated) |
| POST | `/operations/run` | Trigger operations (catalog, profile, scan, materialize, export) |
| GET | `/operations/{id}` | Get operation detail with progress counters |
| GET | `/operations` | List operations (paginated, with filters) |
| PUT | `/operations/abort/{id}` | Abort a running operation (best-effort) |
| POST | `/connections` | Create a connection |
| PUT | `/connections/{id}` | Update a connection (partial PUT) |
| GET | `/connections/{id}` | Get a single connection |
| GET | `/connections` | List connections (paginated, with filters) |
| DELETE | `/connections/{id}` | Delete a connection (409 if datastores reference it) |
| POST | `/connections/{id}/test` | Test connection (optionally with override credentials) |
| POST | `/datastores` | Create datastores |
| PUT | `/datastores/{id}` | Update datastores |
| GET | `/datastores/{id}` | Get datastore by ID |
| GET | `/datastores` | List datastores (paginated, with filters) |
| DELETE | `/datastores/{id}` | Delete datastores |
| POST | `/datastores/{id}/connection` | Verify datastore connection |
| POST | `/datastores/connection` | Validate connection pre-creation |
| PATCH | `/datastores/{id}/enrichment/{eid}` | Link enrichment datastore |
| DELETE | `/datastores/{id}/enrichment` | Unlink enrichment datastore |
| POST | `/export/check-templates` | Export templates to enrichment |

### Authentication

All requests use Bearer token authentication via the `QualyticsClient` session headers:
```
Authorization: Bearer {jwt_token}
Content-Type: application/json
```

---

## Troubleshooting

| Issue | Symptom | Solution |
|-------|---------|----------|
| Token expired | "Your token is expired" warning | Run `qualytics auth login` or `qualytics auth init` with a new token |
| SSL errors | Certificate verification failures | Use `qualytics auth init --no-verify-ssl` (not recommended for production) |
| Profile not found | "Profile `{name}` was not found" | Verify container exists in target datastore |
| Operation timeout | "timed out after Xs" | Increase `--timeout` value |
| Import conflicts | Quality check already exists | CLI automatically updates (upsert pattern) |
| Operation failures | Check `~/.qualytics/operation-error.txt` | Review error details in log file |
