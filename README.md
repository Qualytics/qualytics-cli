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
| `operations` | Trigger catalog, profile, and scan operations |
| `config` | Export and import configuration as code |
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
| [Operations](docs/operations.md) | Catalog, profile, scan workflows |
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

## License

MIT License -- see [LICENSE](LICENSE) for details.
