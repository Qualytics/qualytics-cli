# AGENTS.md - Qualytics CLI Project Structure

## Project Overview

**Qualytics CLI** is a command-line interface tool for interacting with the Qualytics API. It enables users to manage data quality checks, export/import check templates, schedule operations, and trigger datastore operations (catalog, profile, scan) programmatically.

**Version:** 0.1.19
**License:** MIT
**Language:** Python 3.9+

---

## Repository Structure

```
qualytics-cli/
├── .github/
│   └── workflows/
│       └── publish-to-pypi.yml    # CI/CD pipeline for PyPI publishing (uses uv)
├── qualytics/
│   ├── __init__.py                # Package initialization (minimal)
│   └── qualytics.py               # Main CLI application logic
├── .bumpversion.cfg               # Version bumping configuration
├── .gitignore                     # Git ignore rules
├── .pre-commit-config.yaml        # Pre-commit hooks (ruff, pyupgrade)
├── LICENSE                        # MIT License
├── README.md                      # User-facing documentation
├── pyproject.toml                 # Modern Python packaging (PEP 621)
└── uv.lock                        # uv lock file for reproducible builds
```

---

## Core Components

### 1. Entry Point (`qualytics/qualytics.py`)

The main application file contains all CLI functionality. It's built using the **Typer** framework for creating CLI commands and **Rich** for enhanced terminal output.

**Key Components:**

- **Main App (`app`)**: Root Typer application instance
- **Sub-applications**:
  - `checks_app`: Commands for managing quality checks (`checks export`, `checks import`, `checks export-templates`, `checks import-templates`)
  - `schedule_app`: Commands for scheduling metadata exports (`schedule export-metadata`)
  - `run_operation_app`: Commands for triggering datastore operations (`run catalog`, `run profile`, `run scan`)
  - `check_operation_app`: Commands for checking operation status (`operation check_status`)

---

## CLI Command Structure

### Configuration Management

- **`qualytics init`**: Initialize configuration with Qualytics URL and authentication token
- **`qualytics show-config`**: Display current configuration and validate token expiration

### Quality Checks Management

#### Export Commands
- **`qualytics checks export`**: Export quality checks from a datastore to a JSON file
  - Supports filtering by containers, tags, and status (Active, Draft, Archived)
  - Default output: `~/.qualytics/data_checks.json`

- **`qualytics checks export-templates`**: Export check templates
  - Can export to enrichment datastore table or JSON file
  - Supports filtering by template IDs, status, rules, and tags

#### Import Commands
- **`qualytics checks import`**: Import quality checks from JSON file to one or more datastores
  - Handles conflicts (updates existing checks or creates new ones)
  - Supports check templates
  - Logs errors to `~/.qualytics/errors-{date}.log`

- **`qualytics checks import-templates`**: Import check templates from JSON file
  - Creates new templates only (no updates)

### Schedule Operations

- **`qualytics schedule export-metadata`**: Schedule periodic metadata exports using cron expressions
  - Supports anomalies, checks, and field-profiles
  - Platform-specific: generates PowerShell scripts for Windows, crontab entries for Linux

### Datastore Operations

#### Catalog Operation
- **`qualytics run catalog`**: Trigger catalog operation on datastores
  - Options: `--include`, `--prune`, `--recreate`, `--background`
  - Discovers and catalogs database objects (tables, views, etc.)

#### Profile Operation
- **`qualytics run profile`**: Trigger profiling operation on datastores
  - Analyzes data quality and infers quality checks
  - Supports filtering by container names/tags
  - Configurable parameters: inference threshold, sampling limits, correlation thresholds, etc.

#### Scan Operation
- **`qualytics run scan`**: Trigger data quality scan on datastores
  - Validates data against quality checks
  - Supports incremental scans and remediation strategies
  - Options for enrichment source record limits

#### Operation Status
- **`qualytics operation check_status`**: Check the status of running or completed operations
  - Useful for operations run in background mode

---

## Architecture & Design Patterns

### Configuration Storage

- **Location**: `~/.qualytics/config.json`
- **Contents**: Qualytics URL and authentication token
- **Token Validation**: JWT token expiration checking before operations

### Error Handling & Logging

- **Error Logs**: Stored in `~/.qualytics/` directory
- **Operation Errors**: `operation-error.txt`
- **Schedule Errors**: `schedule-operation-errors.txt`
- **Import Errors**: `errors-{date}.log` (deduplicated)

### API Communication

- **Base URL Formatting**: Automatically normalizes URLs to `https://{domain}/api/`
- **Authentication**: Bearer token in request headers
- **Retry Logic**: Implemented for table ID fetching (5 retries with 5-second delays)
- **SSL Verification**: Disabled (uses `verify=False` - note for production use)

### Pagination

- **Page Size**: 100 items per page
- **Progress Tracking**: Uses Rich progress bars for long-running operations
- **Sorting**: Ascending by creation date

### Operation Workflow

1. **Synchronous Mode** (default): Waits for operation to complete, displays status
2. **Background Mode** (`--background`): Starts operation and returns immediately
3. **Status Checking**: Poll operation endpoint every 5 seconds until completion
4. **Retry Logic**: Up to 10 retries with 50-second wait times for failed operations

---

## Data Flow

### Export Flow
```
User Command → Load Config → Validate Token → Fetch Data from API →
Paginate Results → Write to JSON File
```

### Import Flow
```
User Command → Load Config → Validate Token → Read JSON File →
For Each Datastore:
  → Get Container IDs →
  For Each Check:
    → Check for Existing (by metadata) →
    → Update or Create → Log Errors
```

### Operation Trigger Flow
```
User Command → Load Config → Validate Token →
POST to /operations/run →
If Not Background:
  → Poll /operations/{id} → Display Status → Handle Result
```

---

## Dependencies

### Core Libraries
- **typer**: CLI framework
- **rich**: Enhanced terminal output (tables, progress bars, colors)
- **requests**: HTTP client for API communication
- **pyjwt**: JWT token validation
- **croniter**: Cron expression validation
- **click**: Command line interface creation kit (typer dependency)
- **shellingham**: Shell detection for auto-completion
- **typing-extensions**: Backported type hints

### Development Tools
- **uv**: Fast Python package installer and resolver
- **ruff**: Extremely fast Python linter and formatter
- **pyupgrade**: Automatic Python syntax modernizer (enforces Python 3.9+)
- **bump2version**: Semantic versioning automation
- **pre-commit**: Git hooks for code quality

---

## Build & Deployment

### Version Management
- **Tool**: `bump2version`
- **Configuration**: `.bumpversion.cfg`
- **Files Updated**: `pyproject.toml`, `qualytics/qualytics.py`

### Package Management
- **Build System**: setuptools (>=77.0.0)
- **Build Backend**: setuptools.build_meta
- **Packaging**: Modern pyproject.toml (PEP 621)
- **Lock File**: uv.lock for reproducible builds
- **Minimum Python**: 3.9+ (no support for 3.7 or 3.8)

### CI/CD Pipeline
- **Platform**: GitHub Actions
- **Trigger**: Push to `main` branch
- **Steps**:
  1. Checkout repository (actions/checkout@v4)
  2. Set up Python 3.9 (actions/setup-python@v5)
  3. Install uv (astral-sh/setup-uv@v5)
  4. Build package with `uvx --from build pyproject-build --installer uv`
  5. Publish to PyPI using stored credentials

### Package Distribution
- **Registry**: PyPI (https://pypi.org/project/qualytics-cli/)
- **Installation**: `pip install qualytics-cli` or `uv pip install qualytics-cli`
- **Entry Point**: `qualytics` command

---

## Key Features

### Flexibility
- Supports multiple datastores in a single command
- Comma-separated or array-like input formats
- Configurable output paths

### Idempotency
- Import operations detect existing checks and update instead of duplicating
- Metadata-based conflict detection

### Platform Support
- Cross-platform: Windows (PowerShell scripts) and Linux (crontab)
- OS detection for scheduling commands

### User Experience
- Rich terminal output with colors and formatting
- Progress bars for long-running operations
- Detailed error messages with file paths
- Token expiration warnings

---

## Configuration Files

### `.bumpversion.cfg`
Manages semantic versioning across the project. Updates version in both `pyproject.toml` and `qualytics/qualytics.py`.

### `.pre-commit-config.yaml`
Enforces code quality standards before commits:
- **pre-commit-hooks v5.0.0**: File checks, YAML/JSON validation, trailing whitespace
- **ruff v0.12.2**: Fast linting and formatting
- **pyupgrade v3.20.0**: Enforces Python 3.9+ idioms

### `pyproject.toml`
Modern Python packaging configuration (PEP 621):
- **Package Name**: `qualytics-cli`
- **Entry Point**: `qualytics` console script
- **License**: MIT (SPDX format)
- **Python Requirement**: >=3.9
- **Classifiers**: Python 3.9-3.13, OS Independent
- **Project URLs**: Homepage, GitHub repository, User guide
- **Ruff Configuration**: Line length 88, target Python 3.9
- **Dependency Groups**: Separate dev dependencies for uv

---

## API Integration Points

### Endpoints Used
- `GET /quality-checks` - Fetch quality checks (with pagination)
- `POST /quality-checks` - Create quality checks
- `PUT /quality-checks/{id}` - Update quality checks
- `GET /containers/listing` - Get container IDs
- `POST /operations/run` - Trigger operations
- `GET /operations/{id}` - Check operation status
- `POST /export/check-templates` - Export templates to enrichment datastore
- `POST /export/{option}` - Export metadata (anomalies, checks, field-profiles)

### Authentication
- **Method**: JWT Bearer Token
- **Header**: `Authorization: Bearer {token}`
- **Validation**: Expiration check before each operation

---

## Storage Locations

### User Data Directory: `~/.qualytics/`
- `config.json` - User configuration
- `data_checks.json` - Default export location for checks
- `data_checks_template.json` - Default export location for templates
- `errors-{date}.log` - Import operation errors
- `operation-error.txt` - Operation execution errors
- `schedule-operation-errors.txt` - Crontab scheduling errors
- `schedule-operation.txt` - Generated crontab commands
- `schedule_{option}.txt` - Log files for scheduled exports
- `task_scheduler_script_{option}_{datastore}.ps1` - PowerShell scripts (Windows)

---

## Development Guidelines

### Setting Up Development Environment

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
git clone https://github.com/Qualytics/qualytics-cli.git
cd qualytics-cli

# Install dependencies with uv
uv sync

# Install pre-commit hooks
uv run pre-commit install

# Run the CLI in development
uv run qualytics --help

# Run linting
uv run ruff check qualytics/

# Run formatting
uv run ruff format qualytics/

# Run all pre-commit checks
uv run pre-commit run --all-files

# Build the package
uv build

# Bump version (patch, minor, or major)
bump2version patch
```

### Code Organization
- **Single-file architecture**: All CLI logic in `qualytics.py`
- **Function-based design**: Utility functions for reusable logic
- **Sub-application pattern**: Logical grouping of commands
- **Modern Python**: Uses Python 3.9+ features (native typing.Annotated)

### Error Handling
- Try-catch blocks around API calls
- Detailed error logging to files
- User-friendly error messages in terminal
- Status code validation (200-299 success range)

### Code Quality Standards
- **Linting**: ruff with strict error checking (E4, E7, E9, F rules)
- **Formatting**: ruff format (88 character line length, double quotes)
- **Python Version**: Python 3.9+ idioms enforced by pyupgrade
- **Pre-commit**: Automatic checks before each commit

### Best Practices Observed
- URL normalization for consistent API calls
- Token validation before operations
- Retry logic for transient failures
- Pagination for large datasets
- Progress indicators for user feedback
- Type hints using standard library (typing module)

---

## Future Considerations

### Potential Improvements
- Enable SSL verification for production security
- Add unit tests for core functionality (pytest)
- Implement configuration profiles for multiple environments
- Add support for macOS scheduling (launchd)
- Enhance error recovery mechanisms
- Add dry-run mode for import operations
- Implement parallel processing for multiple datastores
- Add type checking with mypy or pyright
- Consider migrating to hatchling or uv's native build backend

### Extensibility
- Modular command structure allows easy addition of new commands
- Utility functions can be extracted to a separate module
- API client could be abstracted into a separate class
- Modern packaging allows easy plugin system development

---

## Troubleshooting Guide

### Common Issues

1. **Token Expiration**
   - **Symptom**: "Your token is expired" warning
   - **Solution**: Run `qualytics init` with new token

2. **Profile Not Found**
   - **Symptom**: "Profile `{name}` was not found in datastore"
   - **Solution**: Verify container exists in target datastore

3. **Operation Failures**
   - **Symptom**: Operation fails during execution
   - **Solution**: Check `~/.qualytics/operation-error.txt`

4. **Import Conflicts**
   - **Symptom**: Quality check already exists
   - **Behavior**: CLI automatically updates existing check

---

## Summary

The **Qualytics CLI** is a well-structured command-line tool that provides comprehensive functionality for managing data quality operations through the Qualytics API. Its architecture emphasizes:

- **User-friendliness**: Rich terminal output, clear progress indicators
- **Robustness**: Error handling, retry logic, validation
- **Flexibility**: Multiple input formats, configurable options
- **Automation**: Scheduling capabilities, background operations
- **Maintainability**: Clear code structure, version management

The project follows Python best practices and leverages modern CLI frameworks to deliver a professional developer experience.
