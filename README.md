# Qualytics CLI

Command-line interface for the [Qualytics](https://www.qualytics.ai/) data quality platform.

[![PyPI](https://img.shields.io/pypi/v/qualytics-cli)](https://pypi.org/project/qualytics-cli/)
[![Python](https://img.shields.io/pypi/pyversions/qualytics-cli)](https://pypi.org/project/qualytics-cli/)
[![Tests](https://github.com/Qualytics/qualytics-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/Qualytics/qualytics-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Manage connections, datastores, containers, quality checks, anomalies, and operations as code. Export your entire Qualytics configuration to git-tracked YAML files and deploy across environments through CI/CD pipelines.

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

# 2. Check connectivity
qualytics doctor

# 3. Export your datastore configuration to YAML
qualytics config export --datastore-id 1 --output ./qualytics-config

# 4. Preview what an import would do (without making changes)
qualytics config import --input ./qualytics-config --dry-run
```

## Commands

| Group | Description |
|-------|-------------|
| `auth` | Authenticate and manage credentials |
| `connections` | Create and manage database connections |
| `datastores` | Create and manage datastores |
| `containers` | Create and manage computed containers |
| `checks` | Create and manage quality checks |
| `anomalies` | View and manage detected anomalies |
| `operations` | Trigger sync, profile, and scan operations |
| `config` | Export and import configuration as code |
| `users` | List and view users |
| `teams` | List and view teams |
| `tags` | Manage tags (list, create, delete) |
| `schedule` | Schedule recurring operations |
| `mcp` | Start the MCP server for LLM integration |
| `doctor` | Check CLI health and connectivity |

Run `qualytics <command> --help` for full details on any command.

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Authentication, configuration, environment variables |
| [Connections](docs/connections.md) | Creating and managing database connections |
| [Datastores](docs/datastores.md) | Creating and managing datastores |
| [Quality Checks](docs/checks.md) | Creating checks from YAML (single and bulk) |
| [Operations](docs/operations.md) | Sync, profile, scan workflows |
| [Export/Import](docs/export-import.md) | Config-as-code: export, import, CI/CD promotion |
| [Anomalies](docs/anomalies.md) | Viewing and managing anomalies |
| [Computed Fields](docs/computed-fields.md) | User-defined computed fields in export/import |
| [Computed Tables](docs/computed-tables.md) | Bulk import of computed tables from Excel/CSV |
| [MCP Server](docs/mcp-server.md) | LLM integration with Claude Code, Cursor, etc. |
| [CI/CD Promotion](docs/examples/github-actions-promotion.md) | GitHub Actions workflow for environment promotion |

## Development

```bash
git clone https://github.com/Qualytics/qualytics-cli.git
cd qualytics-cli
uv sync                              # Install dependencies
uv run pytest                        # Run tests
uv run pre-commit run --all-files    # Lint, format, type checks
```

For architecture details and contribution guidelines, see [AGENTS.md](AGENTS.md).

## Releasing

Releases are automated via GitHub Actions. The version lives in `pyproject.toml` and is managed by `uv version`.

### Steps to release a new version

1. **Ensure `main` is green** -- CI (lint + tests across Python 3.10-3.14 + pre-commit) must pass.

2. **Trigger the Release workflow** -- Go to [Actions > Release](../../actions/workflows/release.yml) and click **Run workflow**. Select the bump type:
   - `patch` -- bug fixes (1.0.0 → 1.0.1)
   - `minor` -- new features (1.0.0 → 1.1.0)
   - `major` -- breaking changes (1.0.0 → 2.0.0)

3. **The workflow automatically:**
   - Bumps the version in `pyproject.toml` via `uv version --bump <type>`
   - Commits the change and creates a `v{version}` git tag
   - Pushes the commit and tag to `main`

4. **The tag push triggers the Publish workflow**, which:
   - Builds the package (`uv build`)
   - Publishes to [PyPI](https://pypi.org/project/qualytics-cli/) via OIDC trusted publishing (no API tokens needed)
   - Creates a GitHub Release with auto-generated release notes and attached artifacts

### Manual version check

```bash
# Current version in pyproject.toml
uv version --short

# Installed version
qualytics --version
```

## License

MIT License -- see [LICENSE](LICENSE) for details.
