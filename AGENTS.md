# AGENTS.md - Qualytics CLI Project Guide

## Project Overview

**Qualytics CLI** is a command-line interface for the Qualytics data quality platform. It wraps the Qualytics controlplane REST API, enabling users to manage quality checks, datastores, computed tables, and operations (catalog, profile, scan) programmatically.

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
│   │   ├── datastores.py     # Datastore API operations (CRUD + verify + enrichment)
│   │   ├── operations.py     # Operation API operations (run, get, list, abort)
│   │   └── quality_checks.py # Quality checks API operations (CRUD + bulk)
│   ├── cli/
│   │   ├── main.py           # init, show-config commands
│   │   ├── anomalies.py      # anomalies get/list/update/archive/delete commands
│   │   ├── checks.py         # checks CRUD + git-friendly export/import
│   │   ├── datastores.py     # datastores create/update/get/list/delete/verify/enrichment commands
│   │   ├── operations.py     # operations catalog/profile/scan/materialize/export/get/list/abort commands
│   │   ├── computed_tables.py # computed-tables import/list/preview commands
│   │   └── schedule.py       # schedule export-metadata command
│   ├── services/
│   │   ├── quality_checks.py # Quality check business logic
│   │   ├── containers.py     # Container/table ID resolution
│   │   ├── datastores.py     # Datastore lookup, payload building, name resolution
│   │   └── operations.py     # Operation execution and polling
│   └── utils/
│       ├── validation.py     # URL normalization
│       ├── file_ops.py       # Error logging, file deduplication
│       ├── yaml_loader.py    # Connection YAML parsing
│       └── serialization.py  # YAML/JSON load, dump, display, format detection
├── tests/
│   ├── conftest.py           # Shared fixtures (cli_runner)
│   ├── test_anomalies.py     # Anomaly API + CLI tests
│   ├── test_cli.py           # CLI smoke tests (command registration)
│   ├── test_datastores.py    # Datastore API + service + CLI tests
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

- `qualytics init --no-verify-ssl` saves `ssl_verify: false` to `~/.qualytics/config.yaml`
- `QualyticsClient` reads `ssl_verify` from config
- `InsecureRequestWarning` is suppressed only when SSL is explicitly disabled
- `qualytics show-config` displays the current SSL status

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

### Datastores (`api/datastores.py`, `services/datastores.py`, `cli/datastores.py`)

Full datastore lifecycle management — create, update, get, list, delete, verify connections, and manage enrichment links.

**Architecture:**
- `api/datastores.py` — 10 thin HTTP wrappers: `create_datastore`, `update_datastore`, `get_datastore`, `list_datastores`, `list_all_datastores`, `delete_datastore`, `verify_connection`, `validate_connection`, `connect_enrichment`, `disconnect_enrichment`
- `services/datastores.py` — business logic: `get_connection_by`, `get_datastore_by`, `get_datastore_by_name`, `build_create_datastore_payload`, `build_update_datastore_payload`
- `cli/datastores.py` — 7 CLI commands under `qualytics datastores`

**CLI commands:**
- `create` — create with `--connection-name` (YAML lookup + auto-create) or `--connection-id`, `--dry-run` support
- `update` — partial update: name, connection, database, schema, tags, teams, enrichment settings
- `get` — by `--id` or `--name` with `--format yaml|json`
- `list` — paginated with `--name`, `--type`, `--tag`, `--enrichment-only` filters
- `delete` — by `--id`
- `verify` — test connection for an existing datastore (CI health checks)
- `enrichment` — `--link <id>` to connect or `--unlink` to disconnect enrichment datastore

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

---

## Configuration

### User Data Directory: `~/.qualytics/`

| File | Purpose |
|------|---------|
| `config.yaml` | URL, token, ssl_verify (auto-migrated from legacy `config.json`) |
| `config/connections.yml` | Database connection definitions |
| `data_checks.yaml` | Default checks export location |
| `data_checks_template.yaml` | Default templates export location |
| `errors-{date}.log` | Import operation errors |
| `operation-error.txt` | Operation execution errors |
| `logs/` | Debug logs (computed-tables --debug) |

### Token Validation

JWT tokens are validated for expiration before each operation. Expired tokens produce a warning and exit.

---

## CLI Command Structure

| Command Group | Subcommands | Description |
|--------------|-------------|-------------|
| `init` | — | Configure URL, token, SSL |
| `show-config` | — | Display current configuration |
| `anomalies` | `get`, `list`, `update`, `archive`, `delete` | Anomaly management (status updates, archiving, deletion) |
| `checks` | `create`, `get`, `list`, `update`, `delete`, `export`, `import`, `export-templates`, `import-templates` | Quality check CRUD + git-friendly export/import |
| `datastores` | `create`, `update`, `get`, `list`, `delete`, `verify`, `enrichment` | Datastore CRUD + connection verification + enrichment linking |
| `operations` | `catalog`, `profile`, `scan`, `materialize`, `export`, `get`, `list`, `abort` | Operation lifecycle (trigger, monitor, abort) |
| `computed-tables` | `import`, `list`, `preview` | Computed table management |
| `schedule` | `export-metadata` | Cron-based export scheduling |

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
| `test_cli.py` | Smoke tests: CLI loads, all command groups registered |
| `test_client.py` | QualyticsClient: URL building, SSL config, exception hierarchy, get_client factory |
| `test_config.py` | Config loading, saving, token validation, legacy JSON migration |
| `test_anomalies.py` | API layer (list, get, update, bulk update, delete, bulk delete), CLI commands (get, list, update, archive, delete), status validation, bulk operations |
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
| GET | `/containers/listing` | Get container/table IDs |
| POST | `/containers` | Create computed tables |
| GET | `/containers/{id}/field-profiles` | Get field profiles |
| POST | `/operations/run` | Trigger operations (catalog, profile, scan, materialize, export) |
| GET | `/operations/{id}` | Get operation detail with progress counters |
| GET | `/operations` | List operations (paginated, with filters) |
| PUT | `/operations/abort/{id}` | Abort a running operation (best-effort) |
| GET | `/connections` | List connections (paginated) |
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
| Token expired | "Your token is expired" warning | Run `qualytics init` with a new token |
| SSL errors | Certificate verification failures | Use `qualytics init --no-verify-ssl` (not recommended for production) |
| Profile not found | "Profile `{name}` was not found" | Verify container exists in target datastore |
| Operation timeout | "timed out after Xs" | Increase `--timeout` value |
| Import conflicts | Quality check already exists | CLI automatically updates (upsert pattern) |
| Operation failures | Check `~/.qualytics/operation-error.txt` | Review error details in log file |
