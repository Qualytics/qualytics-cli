"""Tests for the Qualytics MCP server tools."""

import time
from unittest.mock import patch, MagicMock

import jwt
import pytest
from fastmcp.exceptions import ToolError

from qualytics.mcp.server import (
    mcp,
    _client,
    _api_call,
    auth_status,
    list_connections,
    get_connection,
    list_datastores,
    get_datastore,
    list_containers,
    get_container,
    list_checks,
    get_check,
    list_anomalies,
    get_anomaly,
    update_anomaly,
    archive_anomaly,
    get_operation,
    list_operations,
)
from qualytics.api.client import QualyticsAPIError


# ── server instance tests ────────────────────────────────────────────────


class TestMCPServer:
    """Tests for the MCP server instance."""

    def test_server_exists(self):
        """Test that the MCP server is created."""
        assert mcp is not None
        assert mcp.name == "Qualytics"

    def test_server_has_tools(self):
        """Test that tools are registered on the server."""
        # The server should have tool functions registered
        assert mcp is not None
        # Verify at least one known tool function is importable
        assert callable(auth_status)
        assert callable(list_datastores)


# ── helper tests ─────────────────────────────────────────────────────────


class TestHelpers:
    """Tests for _client and _api_call helpers."""

    @patch("qualytics.mcp.server.get_client")
    def test_client_returns_client(self, mock_get):
        """Test that _client returns the client when configured."""
        mock_get.return_value = MagicMock()
        result = _client()
        assert result is not None

    @patch("qualytics.mcp.server.get_client", side_effect=SystemExit(1))
    def test_client_raises_tool_error_on_system_exit(self, mock_get):
        """Test that _client converts SystemExit to ToolError."""
        with pytest.raises(ToolError, match="Not authenticated"):
            _client()

    def test_api_call_success(self):
        """Test that _api_call passes through successful results."""
        result = _api_call(lambda: {"id": 1})
        assert result == {"id": 1}

    def test_api_call_converts_api_error(self):
        """Test that _api_call converts QualyticsAPIError to ToolError."""

        def failing_fn():
            raise QualyticsAPIError(404, "Not found", "http://example.com")

        with pytest.raises(ToolError, match="API error 404"):
            _api_call(failing_fn)


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


# ── connection tool tests ────────────────────────────────────────────────


class TestConnectionTools:
    """Tests for connection MCP tools."""

    @patch("qualytics.mcp.server.get_client")
    def test_list_connections(self, mock_get_client):
        """Test list_connections tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = [{"id": 1, "name": "pg"}]

        with patch(
            "qualytics.api.connections.list_all_connections", return_value=expected
        ):
            result = list_connections()
            assert result == expected

    @patch("qualytics.mcp.server.get_client")
    def test_get_connection_requires_id_or_name(self, mock_get_client):
        """Test that get_connection requires either id or name."""
        with pytest.raises(ToolError, match="Provide either"):
            get_connection()

    @patch("qualytics.mcp.server.get_client")
    def test_get_connection_not_found(self, mock_get_client):
        """Test that get_connection raises error when not found."""
        mock_get_client.return_value = MagicMock()
        with patch(
            "qualytics.services.connections.get_connection_by", return_value=None
        ):
            with pytest.raises(ToolError, match="Connection not found"):
                get_connection(name="nonexistent")


# ── datastore tool tests ────────────────────────────────────────────────


class TestDatastoreTools:
    """Tests for datastore MCP tools."""

    @patch("qualytics.mcp.server.get_client")
    def test_list_datastores(self, mock_get_client):
        """Test list_datastores tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = [{"id": 1, "name": "warehouse"}]

        with patch(
            "qualytics.api.datastores.list_all_datastores", return_value=expected
        ):
            result = list_datastores()
            assert result == expected

    @patch("qualytics.mcp.server.get_client")
    def test_get_datastore_requires_id_or_name(self, mock_get_client):
        """Test that get_datastore requires either id or name."""
        with pytest.raises(ToolError, match="Provide either"):
            get_datastore()


# ── container tool tests ─────────────────────────────────────────────────


class TestContainerTools:
    """Tests for container MCP tools."""

    @patch("qualytics.mcp.server.get_client")
    def test_list_containers(self, mock_get_client):
        """Test list_containers tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = [{"id": 1, "name": "orders", "container_type": "table"}]

        with patch(
            "qualytics.api.containers.list_all_containers", return_value=expected
        ):
            result = list_containers(datastore_id=1)
            assert result == expected

    @patch("qualytics.mcp.server.get_client")
    def test_get_container(self, mock_get_client):
        """Test get_container tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = {"id": 42, "name": "orders"}

        with patch("qualytics.api.containers.get_container", return_value=expected):
            result = get_container(id=42)
            assert result == expected


# ── quality check tool tests ─────────────────────────────────────────────


class TestCheckTools:
    """Tests for quality check MCP tools."""

    @patch("qualytics.mcp.server.get_client")
    def test_list_checks(self, mock_get_client):
        """Test list_checks tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = [{"id": 1, "rule": "notNull"}]

        with patch(
            "qualytics.api.quality_checks.list_all_quality_checks",
            return_value=expected,
        ):
            result = list_checks(datastore_id=1)
            assert result == expected

    @patch("qualytics.mcp.server.get_client")
    def test_get_check(self, mock_get_client):
        """Test get_check tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = {"id": 10, "rule": "between"}

        with patch(
            "qualytics.api.quality_checks.get_quality_check", return_value=expected
        ):
            result = get_check(check_id=10)
            assert result == expected


# ── anomaly tool tests ───────────────────────────────────────────────────


class TestAnomalyTools:
    """Tests for anomaly MCP tools."""

    @patch("qualytics.mcp.server.get_client")
    def test_list_anomalies(self, mock_get_client):
        """Test list_anomalies tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = [{"id": 1, "status": "Active"}]

        with patch("qualytics.api.anomalies.list_all_anomalies", return_value=expected):
            result = list_anomalies(datastore_id=1)
            assert result == expected

    @patch("qualytics.mcp.server.get_client")
    def test_get_anomaly(self, mock_get_client):
        """Test get_anomaly tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = {"id": 5, "status": "Active"}

        with patch("qualytics.api.anomalies.get_anomaly", return_value=expected):
            result = get_anomaly(id=5)
            assert result == expected

    def test_update_anomaly_rejects_archive_status(self):
        """Test that update_anomaly rejects archive statuses."""
        with pytest.raises(ToolError, match="Active.*Acknowledged"):
            update_anomaly(id=1, status="Resolved")

    def test_archive_anomaly_rejects_open_status(self):
        """Test that archive_anomaly rejects open statuses."""
        with pytest.raises(ToolError, match="must be one of"):
            archive_anomaly(id=1, status="Active")


# ── operation tool tests ─────────────────────────────────────────────────


class TestOperationTools:
    """Tests for operation MCP tools."""

    @patch("qualytics.mcp.server.get_client")
    def test_get_operation(self, mock_get_client):
        """Test get_operation tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = {"id": 99, "type": "scan", "result": "success"}

        with patch("qualytics.api.operations.get_operation", return_value=expected):
            result = get_operation(operation_id=99)
            assert result == expected

    @patch("qualytics.mcp.server.get_client")
    def test_list_operations(self, mock_get_client):
        """Test list_operations tool."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        expected = [{"id": 1, "type": "catalog"}]

        with patch(
            "qualytics.api.operations.list_all_operations", return_value=expected
        ):
            result = list_operations()
            assert result == expected


# ── CLI command test ─────────────────────────────────────────────────────


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
