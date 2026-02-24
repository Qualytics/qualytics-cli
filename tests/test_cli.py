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


def test_datastores_command_registered(cli_runner):
    """Test that the 'datastores' command group is registered."""
    result = cli_runner.invoke(app, ["datastores", "--help"])
    assert result.exit_code == 0
    assert "create" in result.output.lower()
    assert "update" in result.output.lower()
    assert "get" in result.output.lower()
    assert "list" in result.output.lower()
    assert "delete" in result.output.lower()
    assert "verify" in result.output.lower()
    assert "enrichment" in result.output.lower()


def test_operations_command_registered(cli_runner):
    """Test that the 'operations' command group is registered."""
    result = cli_runner.invoke(app, ["operations", "--help"])
    assert result.exit_code == 0
    assert "catalog" in result.output.lower()
    assert "profile" in result.output.lower()
    assert "scan" in result.output.lower()
    assert "materialize" in result.output.lower()
    assert "get" in result.output.lower()
    assert "list" in result.output.lower()
    assert "abort" in result.output.lower()


def test_schedule_command_registered(cli_runner):
    """Test that the 'schedule' command group is registered."""
    result = cli_runner.invoke(app, ["schedule", "--help"])
    assert result.exit_code == 0
    assert "schedule" in result.output.lower() or "export" in result.output.lower()


def test_containers_command_registered(cli_runner):
    """Test that the 'containers' command group is registered."""
    result = cli_runner.invoke(app, ["containers", "--help"])
    assert result.exit_code == 0
    assert "create" in result.output.lower()
    assert "update" in result.output.lower()
    assert "get" in result.output.lower()
    assert "list" in result.output.lower()
    assert "delete" in result.output.lower()
    assert "validate" in result.output.lower()
    assert "import" in result.output.lower()
    assert "preview" in result.output.lower()


def test_connections_command_registered(cli_runner):
    """Test that the 'connections' command group is registered."""
    result = cli_runner.invoke(app, ["connections", "--help"])
    assert result.exit_code == 0
    assert "create" in result.output.lower()
    assert "update" in result.output.lower()
    assert "get" in result.output.lower()
    assert "list" in result.output.lower()
    assert "delete" in result.output.lower()
    assert "test" in result.output.lower()


def test_anomalies_command_registered(cli_runner):
    """Test that the 'anomalies' command group is registered."""
    result = cli_runner.invoke(app, ["anomalies", "--help"])
    assert result.exit_code == 0
    assert "get" in result.output.lower()
    assert "list" in result.output.lower()
    assert "update" in result.output.lower()
    assert "archive" in result.output.lower()
    assert "delete" in result.output.lower()


def test_auth_command_registered(cli_runner):
    """Test that the 'auth' command group is registered with all subcommands."""
    result = cli_runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    assert "login" in result.output.lower()
    assert "status" in result.output.lower()
    assert "init" in result.output.lower()


def test_config_command_registered(cli_runner):
    """Test that the 'config' command group is registered."""
    result = cli_runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "export" in result.output.lower()
    assert "import" in result.output.lower()


def test_mcp_command_registered(cli_runner):
    """Test that the 'mcp' command group is registered."""
    result = cli_runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "serve" in result.output.lower()


def test_version_is_semver():
    """Test that the version follows semver format."""
    parts = __version__.split(".")
    assert len(parts) == 3, (
        f"Version {__version__} does not follow semver (expected X.Y.Z)"
    )
    for part in parts:
        assert part.isdigit(), f"Version part '{part}' is not numeric in {__version__}"


# ── Command suggestion tests ────────────────────────────────────────────


import re


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestCommandSuggestions:
    """Tests for friendly 'available commands' output when no subcommand is given."""

    def test_top_level_shows_available_commands(self, cli_runner):
        """qualytics (no subcommand) lists available command groups."""
        result = cli_runner.invoke(app, [])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "auth" in output
        assert "checks" in output
        assert "datastores" in output
        assert "qualytics --help" in output

    def test_top_level_hides_deprecated_commands(self, cli_runner):
        """Top-level suggestions should not show hidden/deprecated commands."""
        result = cli_runner.invoke(app, [])
        output = _strip_ansi(result.output)
        # show-config and init are hidden/deprecated
        assert "show-config" not in output
        # 'init' appears in 'qualytics --help' hint, check it's not listed as a command
        lines = [
            line.strip()
            for line in output.split("\n")
            if line.strip() and not line.strip().startswith("Run")
        ]
        command_lines = [
            line for line in lines if line and not line.startswith("Available")
        ]
        # None of the command lines should be just 'init' (it may appear as part of help text)
        command_names = [line.split()[0] for line in command_lines if line.split()]
        assert "init" not in command_names
        assert "show-config" not in command_names

    def test_auth_shows_available_commands(self, cli_runner):
        """qualytics auth (no subcommand) lists subcommands."""
        result = cli_runner.invoke(app, ["auth"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "login" in output
        assert "status" in output
        assert "init" in output
        assert "qualytics auth --help" in output

    def test_checks_shows_available_commands(self, cli_runner):
        """qualytics checks (no subcommand) lists subcommands."""
        result = cli_runner.invoke(app, ["checks"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "create" in output
        assert "export" in output

    def test_datastores_shows_available_commands(self, cli_runner):
        """qualytics datastores (no subcommand) lists subcommands."""
        result = cli_runner.invoke(app, ["datastores"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "create" in output
        assert "verify" in output

    def test_connections_shows_available_commands(self, cli_runner):
        """qualytics connections (no subcommand) lists subcommands."""
        result = cli_runner.invoke(app, ["connections"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "test" in output

    def test_containers_shows_available_commands(self, cli_runner):
        """qualytics containers (no subcommand) lists subcommands."""
        result = cli_runner.invoke(app, ["containers"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "validate" in output

    def test_anomalies_shows_available_commands(self, cli_runner):
        """qualytics anomalies (no subcommand) lists subcommands."""
        result = cli_runner.invoke(app, ["anomalies"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "archive" in output

    def test_operations_shows_available_commands(self, cli_runner):
        """qualytics operations (no subcommand) lists subcommands."""
        result = cli_runner.invoke(app, ["operations"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "catalog" in output
        assert "scan" in output

    def test_config_shows_available_commands(self, cli_runner):
        """qualytics config (no subcommand) lists subcommands."""
        result = cli_runner.invoke(app, ["config"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "export" in output
        assert "import" in output

    def test_mcp_shows_available_commands(self, cli_runner):
        """qualytics mcp (no subcommand) lists subcommands."""
        result = cli_runner.invoke(app, ["mcp"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "Available commands" in output
        assert "serve" in output

    def test_banner_shows_logo_and_version(self, cli_runner, monkeypatch):
        """qualytics (no subcommand) displays the ASCII wordmark and version."""
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("QUALYTICS_NO_BANNER", raising=False)
        result = cli_runner.invoke(app, [])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        # SVG-traced wordmark: Q logomark + lowercase ualytics
        assert "▄▄███▀" in output  # Q top
        assert "▀██▄▄▄▄▄▄▄██▀" in output  # Q bottom
        assert "▀▀▀▀▀▀▀▀" in output  # baseline
        # Version below wordmark
        assert f"v{__version__}" in output

    def test_banner_hidden_with_env_var(self, cli_runner, monkeypatch):
        """QUALYTICS_NO_BANNER suppresses the banner but still shows commands."""
        monkeypatch.setenv("QUALYTICS_NO_BANNER", "1")
        result = cli_runner.invoke(app, [])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "▄▄███▀" not in output
        assert "Available commands" in output

    def test_banner_hidden_in_ci(self, cli_runner, monkeypatch):
        """CI environment suppresses the banner."""
        monkeypatch.setenv("CI", "true")
        result = cli_runner.invoke(app, [])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "▄▄███▀" not in output
        assert "Available commands" in output

    def test_banner_not_shown_with_subcommand(self, cli_runner):
        """Banner should not appear when a subcommand is given."""
        result = cli_runner.invoke(app, ["auth", "--help"])
        assert result.exit_code == 0
        output = _strip_ansi(result.output)
        assert "▄▄███▀" not in output

    def test_typo_suggestion_still_works(self, cli_runner):
        """Typer's built-in fuzzy matching for typos still works."""
        result = cli_runner.invoke(app, ["auth", "lgin"])
        assert result.exit_code != 0
        output = _strip_ansi(result.output)
        assert "login" in output.lower()

    def test_version_flag_still_works(self, cli_runner):
        """--version should still work after callback changes."""
        result = cli_runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_help_flag_still_works_with_subgroup(self, cli_runner):
        """--help should still work for subgroups."""
        result = cli_runner.invoke(app, ["auth", "--help"])
        assert result.exit_code == 0
        assert "login" in result.output.lower()

    def test_main_typo_suggests_similar(self, cli_runner):
        """Typo at top level should suggest similar commands."""
        result = cli_runner.invoke(app, ["datastore"])
        assert result.exit_code != 0
        output = _strip_ansi(result.output)
        assert "datastores" in output
        assert "Did you mean" in output

    def test_main_unknown_shows_help_hint(self, cli_runner):
        """Completely unknown command shows --help hint."""
        result = cli_runner.invoke(app, ["foobar"])
        assert result.exit_code != 0
        output = _strip_ansi(result.output)
        assert "qualytics --help" in output

    def test_doctor_visible_in_top_level(self, cli_runner):
        """doctor command should appear in top-level command list."""
        result = cli_runner.invoke(app, [])
        output = _strip_ansi(result.output)
        assert "doctor" in output


# ── Doctor command tests ───────────────────────────────────────────────

from unittest.mock import patch, MagicMock
import time


class TestDoctorCommand:
    """Tests for the qualytics doctor diagnostic command."""

    def test_doctor_help(self, cli_runner):
        """qualytics doctor --help shows usage information."""
        result = cli_runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        assert (
            "diagnostic" in result.output.lower() or "doctor" in result.output.lower()
        )

    def test_doctor_no_config(self, cli_runner, tmp_path, monkeypatch):
        """doctor fails gracefully when no config file exists."""
        monkeypatch.setattr(
            "qualytics.cli.doctor.CONFIG_PATH",
            str(tmp_path / "nonexistent.yaml"),
        )
        result = cli_runner.invoke(app, ["doctor"])
        output = _strip_ansi(result.output)
        assert result.exit_code == 1
        assert "No config file" in output
        assert "CLI version" in output
        assert "Python version" in output

    def test_doctor_all_pass(self, cli_runner, tmp_path, monkeypatch):
        """doctor passes all checks with valid config and reachable API."""
        import jwt as pyjwt

        # Create a token that expires in 30 days
        future_exp = int(time.time()) + 30 * 86400
        token = pyjwt.encode({"exp": future_exp}, "", algorithm="HS256")

        config_file = tmp_path / "config.yaml"
        config_data = {
            "url": "https://test.qualytics.io/api/",
            "token": token,
            "ssl_verify": True,
        }

        import yaml

        config_file.write_text(yaml.safe_dump(config_data))

        monkeypatch.setattr("qualytics.cli.doctor.CONFIG_PATH", str(config_file))
        monkeypatch.setattr("qualytics.cli.doctor.load_config", lambda: config_data)

        # Mock the requests.get call for API connectivity + SSL check
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200

        with patch("qualytics.cli.doctor.requests.get", return_value=mock_resp):
            result = cli_runner.invoke(app, ["doctor"])

        output = _strip_ansi(result.output)
        assert result.exit_code == 0
        assert "All checks passed" in output

    def test_doctor_expired_token(self, cli_runner, tmp_path, monkeypatch):
        """doctor detects an expired token."""
        import jwt as pyjwt

        # Create a token that expired 5 days ago
        past_exp = int(time.time()) - 5 * 86400
        token = pyjwt.encode({"exp": past_exp}, "", algorithm="HS256")

        config_data = {
            "url": "https://test.qualytics.io/api/",
            "token": token,
            "ssl_verify": True,
        }

        config_file = tmp_path / "config.yaml"
        import yaml

        config_file.write_text(yaml.safe_dump(config_data))

        monkeypatch.setattr("qualytics.cli.doctor.CONFIG_PATH", str(config_file))
        monkeypatch.setattr("qualytics.cli.doctor.load_config", lambda: config_data)

        # Mock requests to avoid real API calls
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200

        with patch("qualytics.cli.doctor.requests.get", return_value=mock_resp):
            result = cli_runner.invoke(app, ["doctor"])

        output = _strip_ansi(result.output)
        assert result.exit_code == 1
        assert "Expired" in output

    def test_doctor_api_unreachable(self, cli_runner, tmp_path, monkeypatch):
        """doctor detects unreachable API."""
        import jwt as pyjwt
        import requests

        future_exp = int(time.time()) + 30 * 86400
        token = pyjwt.encode({"exp": future_exp}, "", algorithm="HS256")

        config_data = {
            "url": "https://test.qualytics.io/api/",
            "token": token,
            "ssl_verify": True,
        }

        config_file = tmp_path / "config.yaml"
        import yaml

        config_file.write_text(yaml.safe_dump(config_data))

        monkeypatch.setattr("qualytics.cli.doctor.CONFIG_PATH", str(config_file))
        monkeypatch.setattr("qualytics.cli.doctor.load_config", lambda: config_data)

        with patch(
            "qualytics.cli.doctor.requests.get",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            result = cli_runner.invoke(app, ["doctor"])

        output = _strip_ansi(result.output)
        assert result.exit_code == 1
        assert "Cannot reach" in output

    def test_doctor_token_expiring_soon(self, cli_runner, tmp_path, monkeypatch):
        """doctor warns when token expires within 7 days."""
        import jwt as pyjwt

        # Token expires in 3 days
        soon_exp = int(time.time()) + 3 * 86400
        token = pyjwt.encode({"exp": soon_exp}, "", algorithm="HS256")

        config_data = {
            "url": "https://test.qualytics.io/api/",
            "token": token,
            "ssl_verify": True,
        }

        config_file = tmp_path / "config.yaml"
        import yaml

        config_file.write_text(yaml.safe_dump(config_data))

        monkeypatch.setattr("qualytics.cli.doctor.CONFIG_PATH", str(config_file))
        monkeypatch.setattr("qualytics.cli.doctor.load_config", lambda: config_data)

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200

        with patch("qualytics.cli.doctor.requests.get", return_value=mock_resp):
            result = cli_runner.invoke(app, ["doctor"])

        output = _strip_ansi(result.output)
        # Should warn but not fail
        assert "Expires" in output
        assert "warning" in output.lower()

    def test_doctor_shows_banner_with_doctor_label(
        self, cli_runner, tmp_path, monkeypatch
    ):
        """doctor command shows banner with 'Doctor' subtitle."""
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("QUALYTICS_NO_BANNER", raising=False)
        monkeypatch.setattr(
            "qualytics.cli.doctor.CONFIG_PATH",
            str(tmp_path / "nonexistent.yaml"),
        )
        result = cli_runner.invoke(app, ["doctor"])
        output = _strip_ansi(result.output)
        assert "Doctor" in output
        assert "▄▄███▀" in output  # Wordmark present
