"""Smoke tests for the qualytics CLI."""

from qualytics.qualytics import app
from qualytics.config import __version__


def test_cli_help(cli_runner):
    """Test that the CLI entrypoint loads and shows help."""
    result = cli_runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_cli_version(cli_runner):
    """Test that --version returns the correct version string."""
    result = cli_runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_checks_command_registered(cli_runner):
    """Test that the 'checks' command group is registered."""
    result = cli_runner.invoke(app, ["checks", "--help"])
    assert result.exit_code == 0
    assert "checks" in result.output.lower() or "export" in result.output.lower()


def test_datastore_command_registered(cli_runner):
    """Test that the 'datastore' command group is registered."""
    result = cli_runner.invoke(app, ["datastore", "--help"])
    assert result.exit_code == 0
    assert "datastore" in result.output.lower() or "list" in result.output.lower()


def test_run_command_registered(cli_runner):
    """Test that the 'run' command group is registered."""
    result = cli_runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "catalog" in result.output.lower() or "profile" in result.output.lower()


def test_operation_command_registered(cli_runner):
    """Test that the 'operation' command group is registered."""
    result = cli_runner.invoke(app, ["operation", "--help"])
    assert result.exit_code == 0
    assert (
        "operation" in result.output.lower() or "check_status" in result.output.lower()
    )


def test_schedule_command_registered(cli_runner):
    """Test that the 'schedule' command group is registered."""
    result = cli_runner.invoke(app, ["schedule", "--help"])
    assert result.exit_code == 0
    assert "schedule" in result.output.lower() or "export" in result.output.lower()


def test_computed_tables_command_registered(cli_runner):
    """Test that the 'computed-tables' command group is registered."""
    result = cli_runner.invoke(app, ["computed-tables", "--help"])
    assert result.exit_code == 0
    assert "computed" in result.output.lower() or "import" in result.output.lower()


def test_anomalies_command_registered(cli_runner):
    """Test that the 'anomalies' command group is registered."""
    result = cli_runner.invoke(app, ["anomalies", "--help"])
    assert result.exit_code == 0
    assert "get" in result.output.lower()
    assert "list" in result.output.lower()
    assert "update" in result.output.lower()
    assert "archive" in result.output.lower()
    assert "delete" in result.output.lower()


def test_version_is_semver():
    """Test that the version follows semver format."""
    parts = __version__.split(".")
    assert len(parts) == 3, (
        f"Version {__version__} does not follow semver (expected X.Y.Z)"
    )
    for part in parts:
        assert part.isdigit(), f"Version part '{part}' is not numeric in {__version__}"
