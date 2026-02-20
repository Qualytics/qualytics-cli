"""Tests for connections — API, service, secrets utilities, and CLI."""

import pytest
from unittest.mock import MagicMock, patch

from qualytics.api.connections import (
    create_connection,
    update_connection,
    get_connection_api,
    list_connections,
    list_all_connections,
    delete_connection,
    test_connection as api_test_connection,
)
from qualytics.services.connections import (
    get_connection_by,
    get_connection_by_name,
    build_create_connection_payload,
    build_update_connection_payload,
)
from qualytics.utils.secrets import resolve_env_vars, redact_payload
from qualytics.qualytics import app


# ── Shared fixtures ──────────────────────────────────────────────────────


def _mock_client():
    return MagicMock()


# ══════════════════════════════════════════════════════════════════════════
# 1. API LAYER
# ══════════════════════════════════════════════════════════════════════════


class TestCreateConnection:
    def test_posts_payload(self):
        client = _mock_client()
        client.post.return_value.json.return_value = {
            "id": 1,
            "name": "pg-prod",
            "type": "postgresql",
        }
        payload = {"type": "postgresql", "name": "pg-prod", "host": "db.example.com"}
        result = create_connection(client, payload)
        client.post.assert_called_once_with("connections", json=payload)
        assert result["id"] == 1
        assert result["type"] == "postgresql"

    def test_returns_full_response(self):
        client = _mock_client()
        resp = {"id": 5, "name": "sf-dev", "type": "snowflake"}
        client.post.return_value.json.return_value = resp
        result = create_connection(client, {"type": "snowflake"})
        assert result == resp


class TestUpdateConnection:
    def test_puts_payload(self):
        client = _mock_client()
        client.put.return_value.json.return_value = {"id": 1, "name": "updated"}
        result = update_connection(client, 1, {"name": "updated"})
        client.put.assert_called_once_with("connections/1", json={"name": "updated"})
        assert result["name"] == "updated"

    def test_partial_update(self):
        client = _mock_client()
        client.put.return_value.json.return_value = {"id": 3, "host": "new-host.com"}
        result = update_connection(client, 3, {"host": "new-host.com"})
        assert result["host"] == "new-host.com"


class TestGetConnectionAPI:
    def test_calls_correct_endpoint(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "id": 42,
            "name": "my-conn",
            "type": "postgresql",
        }
        result = get_connection_api(client, 42)
        client.get.assert_called_once_with("connections/42")
        assert result["id"] == 42


class TestListConnections:
    def test_basic_call(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}],
            "total": 1,
        }
        result = list_connections(client)
        client.get.assert_called_once_with(
            "connections", params={"page": 1, "size": 100}
        )
        assert result["items"] == [{"id": 1}]

    def test_with_name_filter(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_connections(client, name="prod")
        params = client.get.call_args.kwargs["params"]
        assert params["name"] == "prod"

    def test_with_type_filter(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_connections(client, connection_type=["postgresql", "mysql"])
        params = client.get.call_args.kwargs["params"]
        assert params["type"] == ["postgresql", "mysql"]

    def test_none_filters_excluded(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_connections(client)
        params = client.get.call_args.kwargs["params"]
        assert "name" not in params
        assert "type" not in params


class TestListAllConnections:
    def test_single_page(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}, {"id": 2}],
            "total": 2,
        }
        result = list_all_connections(client)
        assert len(result) == 2
        assert client.get.call_count == 1

    def test_multi_page(self):
        client = _mock_client()
        page1 = {"items": [{"id": i} for i in range(100)], "total": 150}
        page2 = {"items": [{"id": i} for i in range(100, 150)], "total": 150}
        client.get.return_value.json.side_effect = [page1, page2]
        result = list_all_connections(client)
        assert len(result) == 150
        assert client.get.call_count == 2

    def test_empty(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        result = list_all_connections(client)
        assert result == []

    def test_passes_filters_through(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_all_connections(client, name="test", connection_type=["postgresql"])
        params = client.get.call_args.kwargs["params"]
        assert params["name"] == "test"
        assert params["type"] == ["postgresql"]


class TestDeleteConnection:
    def test_returns_success_on_204(self):
        client = _mock_client()
        client.delete.return_value.content = b""
        client.delete.return_value.status_code = 204
        result = delete_connection(client, 42)
        client.delete.assert_called_once_with("connections/42")
        assert result["success"] is True

    def test_returns_json_when_body(self):
        client = _mock_client()
        client.delete.return_value.content = b'{"ok": true}'
        client.delete.return_value.status_code = 200
        client.delete.return_value.json.return_value = {"ok": True}
        result = delete_connection(client, 42)
        assert result == {"ok": True}


class TestTestConnection:
    def test_without_payload(self):
        client = _mock_client()
        client.post.return_value.json.return_value = {"connected": True}
        result = api_test_connection(client, 10)
        client.post.assert_called_once_with("connections/10/test")
        assert result["connected"] is True

    def test_with_payload(self):
        client = _mock_client()
        client.post.return_value.json.return_value = {"connected": True}
        override = {"host": "new-host", "password": "secret"}
        result = api_test_connection(client, 10, payload=override)
        client.post.assert_called_once_with("connections/10/test", json=override)
        assert result["connected"] is True


# ══════════════════════════════════════════════════════════════════════════
# 2. SERVICE LAYER
# ══════════════════════════════════════════════════════════════════════════


class TestGetConnectionBy:
    @patch("qualytics.services.connections.list_connections")
    def test_find_by_id(self, mock_list):
        mock_list.return_value = {
            "items": [
                {"id": 10, "name": "a"},
                {"id": 20, "name": "b"},
            ]
        }
        client = _mock_client()
        result = get_connection_by(client, connection_id=10)
        assert result["id"] == 10

    @patch("qualytics.services.connections.list_connections")
    def test_find_by_name(self, mock_list):
        mock_list.return_value = {
            "items": [
                {"id": 10, "name": "prod-pg"},
                {"id": 20, "name": "dev-pg"},
            ]
        }
        client = _mock_client()
        result = get_connection_by(client, connection_name="prod-pg")
        assert result["name"] == "prod-pg"

    @patch("qualytics.services.connections.list_connections")
    def test_not_found(self, mock_list):
        mock_list.return_value = {"items": [{"id": 10, "name": "other"}]}
        client = _mock_client()
        result = get_connection_by(client, connection_name="missing")
        assert result is None

    def test_neither_id_nor_name_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="Either"):
            get_connection_by(client)

    def test_both_id_and_name_raises(self):
        client = _mock_client()
        with pytest.raises(ValueError, match="Cannot specify both"):
            get_connection_by(client, connection_id=1, connection_name="x")

    @patch("qualytics.services.connections.list_connections")
    def test_paginates_to_find(self, mock_list):
        """Search spans multiple pages to find a connection."""
        page1 = {"items": [{"id": i, "name": f"conn-{i}"} for i in range(50)]}
        page2 = {"items": [{"id": 99, "name": "target"}]}
        mock_list.side_effect = [page1, page2]
        client = _mock_client()
        result = get_connection_by(client, connection_name="target")
        assert result["id"] == 99
        assert mock_list.call_count == 2


class TestGetConnectionByName:
    @patch("qualytics.services.connections.list_connections")
    def test_delegates_to_get_connection_by(self, mock_list):
        mock_list.return_value = {"items": [{"id": 5, "name": "target"}]}
        client = _mock_client()
        result = get_connection_by_name(client, "target")
        assert result["id"] == 5


class TestBuildCreateConnectionPayload:
    def test_jdbc_connection(self):
        payload = build_create_connection_payload(
            "postgresql",
            name="pg-prod",
            host="db.example.com",
            port=5432,
            username="admin",
            password="secret",
        )
        assert payload["type"] == "postgresql"
        assert payload["name"] == "pg-prod"
        assert payload["host"] == "db.example.com"
        assert payload["port"] == 5432
        assert payload["username"] == "admin"
        assert payload["password"] == "secret"

    def test_dfs_connection(self):
        payload = build_create_connection_payload(
            "s3",
            name="s3-bucket",
            uri="s3://my-bucket",
            access_key="AKIA...",
            secret_key="secret123",
        )
        assert payload["type"] == "s3"
        assert payload["uri"] == "s3://my-bucket"
        assert payload["access_key"] == "AKIA..."
        assert payload["secret_key"] == "secret123"

    def test_native_with_catalog(self):
        payload = build_create_connection_payload(
            "databricks",
            name="db-conn",
            host="host.databricks.com",
            catalog="main",
        )
        assert payload["catalog"] == "main"

    def test_parameters_catch_all(self):
        payload = build_create_connection_payload(
            "snowflake",
            name="sf-conn",
            parameters={"role": "ADMIN", "warehouse": "WH"},
        )
        assert payload["role"] == "ADMIN"
        assert payload["warehouse"] == "WH"

    def test_parameters_overrides_dedicated_flags(self):
        payload = build_create_connection_payload(
            "postgresql",
            host="original-host",
            parameters={"host": "override-host"},
        )
        assert payload["host"] == "override-host"

    def test_tuning_params(self):
        payload = build_create_connection_payload(
            "postgresql",
            jdbc_fetch_size=5000,
            max_parallelization=4,
        )
        assert payload["jdbc_fetch_size"] == 5000
        assert payload["max_parallelization"] == 4

    def test_none_values_excluded(self):
        payload = build_create_connection_payload("postgresql")
        assert "name" not in payload
        assert "host" not in payload
        assert "port" not in payload
        assert "username" not in payload
        assert "password" not in payload
        assert payload == {"type": "postgresql"}


class TestBuildUpdateConnectionPayload:
    def test_includes_non_none_values(self):
        payload = build_update_connection_payload(name="new-name", host="new-host")
        assert payload == {"name": "new-name", "host": "new-host"}

    def test_excludes_none_values(self):
        payload = build_update_connection_payload(name="new-name", host=None, port=None)
        assert payload == {"name": "new-name"}

    def test_empty_when_all_none(self):
        payload = build_update_connection_payload(name=None, host=None)
        assert payload == {}


# ══════════════════════════════════════════════════════════════════════════
# 3. SECRETS UTILITIES
# ══════════════════════════════════════════════════════════════════════════


class TestResolveEnvVars:
    def test_resolves_existing_var(self, monkeypatch):
        monkeypatch.setenv("TEST_DB_USER", "admin")
        result = resolve_env_vars("${TEST_DB_USER}")
        assert result == "admin"

    def test_resolves_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("TEST_HOST", "db.example.com")
        monkeypatch.setenv("TEST_PORT", "5432")
        result = resolve_env_vars("${TEST_HOST}:${TEST_PORT}")
        assert result == "db.example.com:5432"

    def test_raises_on_unresolved(self, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        with pytest.raises(ValueError, match="Unresolved environment variable"):
            resolve_env_vars("${NONEXISTENT_VAR}")

    def test_none_passthrough(self):
        assert resolve_env_vars(None) is None

    def test_plain_string_unchanged(self):
        result = resolve_env_vars("plain-value")
        assert result == "plain-value"

    def test_mixed_resolved_and_literal(self, monkeypatch):
        monkeypatch.setenv("TEST_USER", "admin")
        result = resolve_env_vars("user=${TEST_USER}")
        assert result == "user=admin"


class TestRedactPayload:
    def test_redacts_sensitive_fields(self):
        payload = {
            "name": "pg-prod",
            "password": "secret123",
            "host": "db.example.com",
        }
        result = redact_payload(payload)
        assert result["name"] == "pg-prod"
        assert result["password"] == "*** redacted ***"
        assert result["host"] == "db.example.com"

    def test_redacts_nested_sensitive_fields(self):
        payload = {
            "connection": {
                "name": "conn",
                "password": "secret",
                "credentials": {"token": "abc"},
            }
        }
        result = redact_payload(payload)
        assert result["connection"]["password"] == "*** redacted ***"
        assert result["connection"]["credentials"] == "*** redacted ***"

    def test_does_not_modify_original(self):
        payload = {"password": "secret"}
        result = redact_payload(payload)
        assert payload["password"] == "secret"
        assert result["password"] == "*** redacted ***"

    def test_redacts_all_known_fields(self):
        payload = {
            "password": "a",
            "passphrase": "b",
            "token": "c",
            "api_key": "d",
            "secret": "e",
            "secret_key": "f",
            "private_key": "g",
            "access_key": "h",
            "credentials": "i",
            "credentials_payload": "j",
            "auth_token": "k",
        }
        result = redact_payload(payload)
        for key in payload:
            assert result[key] == "*** redacted ***"

    def test_preserves_non_sensitive_fields(self):
        payload = {"name": "conn", "type": "postgresql", "host": "localhost"}
        result = redact_payload(payload)
        assert result == payload


# ══════════════════════════════════════════════════════════════════════════
# 4. CLI COMMAND TESTS
# ══════════════════════════════════════════════════════════════════════════


class TestConnectionsCreateCLI:
    @patch("qualytics.cli.connections.create_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_create_inline(self, mock_gc, mock_create, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_create.return_value = {
            "id": 1,
            "name": "pg-prod",
            "type": "postgresql",
        }
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "create",
                "--type",
                "postgresql",
                "--name",
                "pg-prod",
                "--host",
                "db.example.com",
                "--port",
                "5432",
                "--username",
                "admin",
                "--password",
                "secret",
            ],
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output
        mock_create.assert_called_once()
        # Verify sensitive data is redacted in output
        assert "secret" not in result.output or "redacted" in result.output

    @patch("qualytics.cli.connections.get_client")
    def test_create_dry_run(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "create",
                "--type",
                "postgresql",
                "--name",
                "pg-test",
                "--host",
                "localhost",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output

    def test_create_requires_type(self, cli_runner):
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "create",
                "--name",
                "pg-prod",
                "--host",
                "localhost",
            ],
        )
        assert result.exit_code == 1
        assert "--type" in result.output

    @patch("qualytics.cli.connections.create_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_create_with_parameters_json(self, mock_gc, mock_create, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_create.return_value = {
            "id": 2,
            "name": "sf-conn",
            "type": "snowflake",
        }
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "create",
                "--type",
                "snowflake",
                "--name",
                "sf-conn",
                "--parameters",
                '{"role": "ADMIN", "warehouse": "WH"}',
            ],
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output

    @patch("qualytics.cli.connections.get_client")
    def test_create_invalid_parameters_json(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "create",
                "--type",
                "postgresql",
                "--parameters",
                "not-valid-json",
            ],
        )
        assert result.exit_code == 1
        assert "Invalid JSON" in result.output

    @patch("qualytics.cli.connections.create_connection")
    @patch("qualytics.cli.connections.get_yaml_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_create_from_yaml(self, mock_gc, mock_yaml, mock_create, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_yaml.return_value = {
            "type": "postgresql",
            "name": "pg-prod",
            "parameters": {
                "host": "db.example.com",
                "port": 5432,
                "user": "admin",
                "password": "secret",
            },
        }
        mock_create.return_value = {
            "id": 3,
            "name": "pg-prod",
            "type": "postgresql",
        }
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "create",
                "--from-yaml",
                "/tmp/connections.yml",
                "--connection-key",
                "pg_prod",
            ],
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output
        mock_yaml.assert_called_once_with("/tmp/connections.yml", "pg_prod")

    def test_create_from_yaml_requires_connection_key(self, cli_runner):
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "create",
                "--from-yaml",
                "/tmp/connections.yml",
            ],
        )
        assert result.exit_code == 1
        assert "--connection-key" in result.output

    @patch("qualytics.cli.connections.create_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_create_env_var_resolution(
        self, mock_gc, mock_create, cli_runner, monkeypatch
    ):
        monkeypatch.setenv("TEST_DB_HOST", "resolved-host.com")
        monkeypatch.setenv("TEST_DB_PASS", "resolved-secret")
        mock_gc.return_value = _mock_client()
        mock_create.return_value = {"id": 4, "name": "env-conn", "type": "postgresql"}
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "create",
                "--type",
                "postgresql",
                "--name",
                "env-conn",
                "--host",
                "${TEST_DB_HOST}",
                "--password",
                "${TEST_DB_PASS}",
            ],
        )
        assert result.exit_code == 0
        # Verify the payload sent to the API used resolved values
        call_payload = mock_create.call_args[0][1]
        assert call_payload["host"] == "resolved-host.com"
        assert call_payload["password"] == "resolved-secret"

    @patch("qualytics.cli.connections.get_client")
    def test_create_unresolved_env_var_fails(self, mock_gc, cli_runner, monkeypatch):
        monkeypatch.delenv("NONEXISTENT_VAR_XYZ", raising=False)
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "create",
                "--type",
                "postgresql",
                "--password",
                "${NONEXISTENT_VAR_XYZ}",
            ],
        )
        assert result.exit_code == 1
        assert "Unresolved environment variable" in result.output


class TestConnectionsUpdateCLI:
    @patch("qualytics.cli.connections.update_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_update_basic(self, mock_gc, mock_update, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_update.return_value = {"id": 1, "name": "updated-name"}
        result = cli_runner.invoke(
            app, ["connections", "update", "--id", "1", "--name", "updated-name"]
        )
        assert result.exit_code == 0
        assert "updated successfully" in result.output
        mock_update.assert_called_once()

    @patch("qualytics.cli.connections.update_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_update_partial(self, mock_gc, mock_update, cli_runner):
        """Only changed fields are sent."""
        mock_gc.return_value = _mock_client()
        mock_update.return_value = {"id": 1, "host": "new-host"}
        result = cli_runner.invoke(
            app, ["connections", "update", "--id", "1", "--host", "new-host"]
        )
        assert result.exit_code == 0
        # Verify only the changed field was sent
        call_args = mock_update.call_args
        payload = call_args[0][2]  # third positional arg
        assert payload.get("host") == "new-host"
        assert "name" not in payload

    @patch("qualytics.cli.connections.get_client")
    def test_update_no_fields_fails(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(app, ["connections", "update", "--id", "1"])
        assert result.exit_code == 1
        assert "No fields to update" in result.output

    @patch("qualytics.cli.connections.update_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_update_redacts_output(self, mock_gc, mock_update, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_update.return_value = {
            "id": 1,
            "name": "conn",
            "password": "new-secret",
        }
        result = cli_runner.invoke(
            app, ["connections", "update", "--id", "1", "--name", "conn"]
        )
        assert result.exit_code == 0
        assert "redacted" in result.output
        assert "new-secret" not in result.output

    @patch("qualytics.cli.connections.update_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_update_with_parameters_json(self, mock_gc, mock_update, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_update.return_value = {"id": 1, "role": "READER"}
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "update",
                "--id",
                "1",
                "--parameters",
                '{"role": "READER"}',
            ],
        )
        assert result.exit_code == 0
        call_args = mock_update.call_args
        payload = call_args[0][2]
        assert payload["role"] == "READER"


class TestConnectionsGetCLI:
    @patch("qualytics.cli.connections.get_connection_api")
    @patch("qualytics.cli.connections.get_client")
    def test_get_by_id(self, mock_gc, mock_get, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {
            "id": 42,
            "name": "my-conn",
            "type": "postgresql",
            "password": "secret",
        }
        result = cli_runner.invoke(app, ["connections", "get", "--id", "42"])
        assert result.exit_code == 0
        assert "Connection found" in result.output
        # Verify secrets are redacted
        assert "secret" not in result.output or "redacted" in result.output

    @patch("qualytics.cli.connections.get_connection_by_name")
    @patch("qualytics.cli.connections.get_client")
    def test_get_by_name(self, mock_gc, mock_get_name, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get_name.return_value = {"id": 42, "name": "pg-prod", "type": "postgresql"}
        result = cli_runner.invoke(app, ["connections", "get", "--name", "pg-prod"])
        assert result.exit_code == 0
        assert "Connection found" in result.output

    @patch("qualytics.cli.connections.get_connection_by_name")
    @patch("qualytics.cli.connections.get_client")
    def test_get_not_found(self, mock_gc, mock_get_name, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get_name.return_value = None
        result = cli_runner.invoke(app, ["connections", "get", "--name", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_get_requires_id_or_name(self, cli_runner):
        result = cli_runner.invoke(app, ["connections", "get"])
        assert result.exit_code == 1
        assert "Must specify either --id or --name" in result.output

    def test_get_rejects_both_id_and_name(self, cli_runner):
        result = cli_runner.invoke(
            app, ["connections", "get", "--id", "1", "--name", "x"]
        )
        assert result.exit_code == 1
        assert "Cannot specify both" in result.output


class TestConnectionsListCLI:
    @patch("qualytics.cli.connections.list_all_connections")
    @patch("qualytics.cli.connections.get_client")
    def test_list_basic(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = [
            {"id": 1, "name": "conn-a", "type": "postgresql"},
            {"id": 2, "name": "conn-b", "type": "mysql"},
        ]
        result = cli_runner.invoke(app, ["connections", "list"])
        assert result.exit_code == 0
        assert "Found 2 connections" in result.output

    @patch("qualytics.cli.connections.list_all_connections")
    @patch("qualytics.cli.connections.get_client")
    def test_list_with_filters(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = []
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "list",
                "--name",
                "prod",
                "--type",
                "postgresql,snowflake",
            ],
        )
        assert result.exit_code == 0
        _, kwargs = mock_list.call_args
        assert kwargs["name"] == "prod"
        assert kwargs["connection_type"] == ["postgresql", "snowflake"]

    @patch("qualytics.cli.connections.list_all_connections")
    @patch("qualytics.cli.connections.get_client")
    def test_list_redacts_each_connection(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = [
            {"id": 1, "name": "conn", "password": "secret123"},
        ]
        result = cli_runner.invoke(app, ["connections", "list"])
        assert result.exit_code == 0
        assert "secret123" not in result.output
        assert "redacted" in result.output

    @patch("qualytics.cli.connections.list_all_connections")
    @patch("qualytics.cli.connections.get_client")
    def test_list_json_format(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = [{"id": 1, "name": "conn"}]
        result = cli_runner.invoke(app, ["connections", "list", "--format", "json"])
        assert result.exit_code == 0


class TestConnectionsDeleteCLI:
    @patch("qualytics.cli.connections.delete_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_delete(self, mock_gc, mock_delete, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_delete.return_value = {
            "success": True,
            "message": "Connection deleted successfully",
        }
        result = cli_runner.invoke(app, ["connections", "delete", "--id", "42"])
        assert result.exit_code == 0
        assert "deleted successfully" in result.output
        mock_delete.assert_called_once_with(mock_gc.return_value, 42)

    @patch("qualytics.cli.connections.delete_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_delete_409_conflict(self, mock_gc, mock_delete, cli_runner):
        from qualytics.api.client import QualyticsAPIError

        mock_gc.return_value = _mock_client()
        mock_delete.side_effect = QualyticsAPIError(409, "Conflict")
        result = cli_runner.invoke(app, ["connections", "delete", "--id", "42"])
        assert result.exit_code == 1
        assert "datastores still reference" in result.output


class TestConnectionsTestCLI:
    @patch("qualytics.cli.connections.test_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_without_overrides(self, mock_gc, mock_test, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_test.return_value = {"connected": True}
        result = cli_runner.invoke(app, ["connections", "test", "--id", "10"])
        assert result.exit_code == 0
        assert "test passed" in result.output
        mock_test.assert_called_once_with(mock_gc.return_value, 10, payload=None)

    @patch("qualytics.cli.connections.test_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_with_override_credentials(self, mock_gc, mock_test, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_test.return_value = {"connected": True}
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "test",
                "--id",
                "10",
                "--host",
                "new-host",
                "--password",
                "new-pass",
            ],
        )
        assert result.exit_code == 0
        call_kwargs = mock_test.call_args.kwargs
        assert call_kwargs["payload"]["host"] == "new-host"
        assert call_kwargs["payload"]["password"] == "new-pass"

    @patch("qualytics.cli.connections.test_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_failure_result(self, mock_gc, mock_test, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_test.return_value = {
            "connected": False,
            "message": "Connection refused",
        }
        result = cli_runner.invoke(app, ["connections", "test", "--id", "10"])
        assert result.exit_code == 0
        assert "test failed" in result.output
        assert "Connection refused" in result.output

    @patch("qualytics.cli.connections.test_connection")
    @patch("qualytics.cli.connections.get_client")
    def test_with_env_var_overrides(self, mock_gc, mock_test, cli_runner, monkeypatch):
        monkeypatch.setenv("TEST_OVERRIDE_PASS", "env-resolved-pass")
        mock_gc.return_value = _mock_client()
        mock_test.return_value = {"connected": True}
        result = cli_runner.invoke(
            app,
            [
                "connections",
                "test",
                "--id",
                "10",
                "--password",
                "${TEST_OVERRIDE_PASS}",
            ],
        )
        assert result.exit_code == 0
        call_kwargs = mock_test.call_args.kwargs
        assert call_kwargs["payload"]["password"] == "env-resolved-pass"
