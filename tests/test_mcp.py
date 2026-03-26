"""Tests for the Qualytics MCP server."""

import time
from unittest.mock import patch, MagicMock

import jwt
import pytest
from fastmcp.exceptions import ToolError

from qualytics.mcp.server import auth_status


# ── server module tests ──────────────────────────────────────────────────


class TestMCPServer:
    """Tests for the MCP server module."""

    def test_auth_status_is_callable(self):
        """Test that auth_status is exported as a callable."""
        assert callable(auth_status)


# ── auth tool tests ──────────────────────────────────────────────────────


class TestAuthStatusTool:
    """Tests for the auth_status MCP tool."""

    def test_no_config_raises_error(self):
        """Test that auth_status raises ToolError when not configured."""
        with patch("qualytics.mcp.server.load_config", return_value=None):
            with pytest.raises(ToolError, match="Not authenticated"):
                auth_status()

    def test_valid_config_returns_status(self):
        """Test that auth_status returns structured status."""
        token = jwt.encode(
            {"sub": "user", "exp": int(time.time()) + 86400},
            key="",
            algorithm="HS256",
        )
        config = {
            "url": "https://test.qualytics.io/api/",
            "token": token,
            "ssl_verify": True,
        }
        with patch("qualytics.mcp.server.load_config", return_value=config):
            result = auth_status()
            assert result["host"] == "test.qualytics.io"
            assert result["authenticated"] is True
            assert result["ssl_verify"] is True
            assert "****" in result["token"]
            assert result.get("token_expired") is False

    def test_expired_token_detected(self):
        """Test that auth_status detects expired tokens."""
        token = jwt.encode(
            {"sub": "user", "exp": int(time.time()) - 86400},
            key="",
            algorithm="HS256",
        )
        config = {
            "url": "https://test.qualytics.io/api/",
            "token": token,
            "ssl_verify": True,
        }
        with patch("qualytics.mcp.server.load_config", return_value=config):
            result = auth_status()
            assert result["authenticated"] is False
            assert result["token_expired"] is True


# ── CLI command tests ─────────────────────────────────────────────────────


class TestMCPCommand:
    """Tests for the qualytics mcp serve CLI command."""

    def test_mcp_command_registered(self, cli_runner):
        """Test that the 'mcp' command group is registered."""
        from qualytics.qualytics import app

        result = cli_runner.invoke(app, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "serve" in result.output.lower()

    def test_mcp_serve_help(self, cli_runner):
        """Test that mcp serve shows help with setup instructions."""
        from qualytics.qualytics import app

        result = cli_runner.invoke(app, ["mcp", "serve", "--help"])
        assert result.exit_code == 0
        assert "stdio" in result.output.lower()
        assert "claude" in result.output.lower()

    def test_mcp_serve_exits_when_not_authenticated(self, cli_runner):
        """Test that mcp serve fails gracefully when no config exists."""
        from qualytics.qualytics import app

        with patch("qualytics.cli.mcp_cmd.load_config", return_value=None):
            result = cli_runner.invoke(app, ["mcp", "serve"])
            assert result.exit_code != 0

    def test_mcp_serve_builds_proxy_with_correct_url(self, cli_runner):
        """Test that mcp serve constructs the proxy URL from config."""
        import jwt as _jwt

        token = _jwt.encode({"sub": "u"}, key="", algorithm="HS256")
        config = {
            "url": "https://demo.qualytics.io/api",
            "token": token,
            "ssl_verify": True,
        }

        with patch("qualytics.cli.mcp_cmd.load_config", return_value=config):
            with patch("qualytics.cli.mcp_cmd.create_proxy") as mock_proxy:
                with patch("qualytics.cli.mcp_cmd.Client"):
                    with patch(
                        "qualytics.cli.mcp_cmd.StreamableHttpTransport"
                    ) as mock_transport:
                        mock_server = MagicMock()
                        mock_proxy.return_value = mock_server

                        cli_runner.invoke(
                            __import__("qualytics.qualytics", fromlist=["app"]).app,
                            ["mcp", "serve"],
                        )

                        mock_transport.assert_called_once()
                        call_kwargs = mock_transport.call_args
                        assert (
                            call_kwargs.kwargs["url"]
                            == "https://demo.qualytics.io/api/mcp"
                        )  # config url already includes /api
                        assert call_kwargs.kwargs["auth"] == token
