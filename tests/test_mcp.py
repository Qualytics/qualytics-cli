"""Tests for the Qualytics MCP server."""

import asyncio
import time
from stat import S_IMODE
from unittest.mock import patch, MagicMock

import jwt
import pytest
from fastmcp.exceptions import ToolError
from mcp.shared.auth import OAuthToken

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
            key="test-secret-key-with-at-least-32-bytes",
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
            key="test-secret-key-with-at-least-32-bytes",
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

    def test_mcp_serve_exits_when_url_empty(self, cli_runner):
        """Test that mcp serve fails when config url is empty."""
        from qualytics.qualytics import app

        config = {"url": "", "token": "some-token", "ssl_verify": True}
        with patch("qualytics.cli.mcp_cmd.load_config", return_value=config):
            result = cli_runner.invoke(app, ["mcp", "serve"])
            assert result.exit_code != 0

    def test_mcp_serve_exits_when_token_empty(self, cli_runner):
        """Test that mcp serve fails when config token is empty."""
        from qualytics.qualytics import app

        config = {
            "url": "https://demo.qualytics.io/api",
            "token": "",
            "ssl_verify": True,
        }
        with patch("qualytics.cli.mcp_cmd.load_config", return_value=config):
            result = cli_runner.invoke(app, ["mcp", "serve"])
            assert result.exit_code != 0

    def test_mcp_serve_builds_proxy_with_correct_url(self, cli_runner, tmp_path):
        """Test that mcp serve constructs the proxy URL from config."""
        import jwt as _jwt

        token = _jwt.encode(
            {"sub": "u"},
            key="test-secret-key-with-at-least-32-bytes",
            algorithm="HS256",
        )
        config = {
            "url": "https://demo.qualytics.io/api",
            "token": token,
            "ssl_verify": True,
        }

        with (
            patch("qualytics.cli.mcp_cmd.load_config", return_value=config),
            patch("qualytics.cli.mcp_cmd.BASE_PATH", str(tmp_path)),
        ):
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
                        auth = call_kwargs.kwargs["auth"]
                        assert auth is not token
                        assert auth.__class__.__name__ == "OAuth"
                        assert auth._scopes == ["read", "write"]

    def test_mcp_serve_forwards_ssl_verify_false(self, cli_runner, tmp_path):
        """Test that ssl_verify=False is wired into the httpx client factory."""
        import jwt as _jwt

        token = _jwt.encode(
            {"sub": "u"},
            key="test-secret-key-with-at-least-32-bytes",
            algorithm="HS256",
        )
        config = {
            "url": "https://demo.qualytics.io/api",
            "token": token,
            "ssl_verify": False,
        }

        with (
            patch("qualytics.cli.mcp_cmd.load_config", return_value=config),
            patch("qualytics.cli.mcp_cmd.BASE_PATH", str(tmp_path)),
        ):
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
                        factory = mock_transport.call_args.kwargs[
                            "httpx_client_factory"
                        ]
                        with patch(
                            "qualytics.cli.mcp_cmd.httpx.AsyncClient"
                        ) as mock_async:
                            factory()
                            mock_async.assert_called_once_with(verify=False)


def test_mcp_grant_survives_restart_and_is_separate_per_url(tmp_path):
    """Persist a grant, reload it, and keep other MCP deployments isolated."""
    from qualytics.cli.mcp_cmd import mcp_serve

    config = {
        "url": "https://demo.qualytics.io/api",
        "token": "rest-pat",
        "ssl_verify": True,
    }
    transports = []

    def capture_transport(**kwargs):
        transports.append(kwargs)
        return MagicMock()

    with (
        patch("qualytics.cli.mcp_cmd.load_config", return_value=config),
        patch("qualytics.cli.mcp_cmd.BASE_PATH", str(tmp_path)),
        patch(
            "qualytics.cli.mcp_cmd.StreamableHttpTransport",
            side_effect=capture_transport,
        ),
        patch("qualytics.cli.mcp_cmd.Client"),
        patch("qualytics.cli.mcp_cmd.create_proxy"),
    ):
        mcp_serve(transport="stdio")
        first = transports[-1]["auth"]
        assert transports[-1]["auth"] != config["token"]
        grant = OAuthToken(
            access_token="mcp-access", token_type="Bearer", refresh_token="mcp-refresh"
        )
        asyncio.run(first.token_storage_adapter.set_tokens(grant))

        mcp_serve(transport="stdio")
        same_url = transports[-1]["auth"]
        restored = asyncio.run(same_url.token_storage_adapter.get_tokens())
        assert restored is not None
        assert restored.refresh_token == "mcp-refresh"

        config["url"] = "https://other.qualytics.io/api"
        mcp_serve(transport="stdio")
        other_url = transports[-1]["auth"]
        assert asyncio.run(other_url.token_storage_adapter.get_tokens()) is None

    assert S_IMODE((tmp_path / "mcp-oauth").stat().st_mode) == 0o700
