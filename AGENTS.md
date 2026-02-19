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
│   │   └── datastores.py     # Datastore API operations
│   ├── cli/
│   │   ├── main.py           # init, show-config commands
│   │   ├── checks.py         # checks export/import commands
│   │   ├── datastores.py     # datastore new/list/get/remove commands
│   │   ├── operations.py     # run catalog/profile/scan commands
│   │   ├── computed_tables.py # computed-tables import/list/preview commands
│   │   └── schedule.py       # schedule export-metadata command
│   ├── services/
│   │   ├── quality_checks.py # Quality check business logic
│   │   ├── containers.py     # Container/table ID resolution
│   │   ├── datastores.py     # Datastore lookup and payload building
│   │   └── operations.py     # Operation execution and polling
│   └── utils/
│       ├── validation.py     # URL normalization
│       ├── file_ops.py       # Error logging, file deduplication
│       └── yaml_loader.py    # Connection YAML parsing
├── tests/
│   ├── conftest.py           # Shared fixtures (cli_runner)
│   ├── test_cli.py           # CLI smoke tests (command registration)
│   ├── test_client.py        # API client unit tests
│   └── test_config.py        # Configuration and token validation tests
├── pyproject.toml            # Project config (hatchling, dependencies, tools)
├── uv.lock                   # Locked dependency versions (committed)
├── .pre-commit-config.yaml   # Pre-commit hooks
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

- `qualytics init --no-verify-ssl` saves `ssl_verify: false` to `~/.qualytics/config.json`
- `QualyticsClient` reads `ssl_verify` from config
- `InsecureRequestWarning` is suppressed only when SSL is explicitly disabled
- `qualytics show-config` displays the current SSL status

### Operation Polling

Operations (catalog, profile, scan) use time-based polling instead of fixed retry counts:

| Setting | Default | CLI Flag |
|---------|---------|----------|
| Poll interval | 10 seconds | `--poll-interval` |
| Timeout | 1800 seconds (30 min) | `--timeout` |

- Periodic status updates print every 60 seconds during long waits
- Returns `None` on timeout, allowing callers to handle gracefully
- Background mode (`--background`) skips polling entirely

---

## Configuration

### User Data Directory: `~/.qualytics/`

| File | Purpose |
|------|---------|
| `config.json` | URL, token, ssl_verify |
| `config/connections.yml` | Database connection definitions |
| `data_checks.json` | Default checks export location |
| `data_checks_template.json` | Default templates export location |
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
| `checks` | `export`, `import`, `export-templates`, `import-templates` | Quality check management |
| `datastore` | `new`, `list`, `get`, `remove` | Datastore CRUD |
| `run` | `catalog`, `profile`, `scan` | Trigger datastore operations |
| `operation` | `check_status` | Check operation status |
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
| pyyaml | Connection YAML parsing |
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
| `test_config.py` | Config loading, saving, token validation |

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
| GET | `/quality-checks` | Fetch quality checks (paginated) |
| POST | `/quality-checks` | Create quality checks |
| PUT | `/quality-checks/{id}` | Update quality checks |
| GET | `/containers/listing` | Get container/table IDs |
| POST | `/containers` | Create computed tables |
| GET | `/containers/{id}/field-profiles` | Get field profiles |
| POST | `/operations/run` | Trigger operations |
| GET | `/operations/{id}` | Check operation status |
| GET | `/operations` | List operations (with filters) |
| GET | `/connections` | List connections (paginated) |
| POST | `/datastores` | Create datastores |
| GET | `/datastores/listing` | List datastores |
| DELETE | `/datastores/{id}` | Delete datastores |
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
