"""Tests for datastores — API, service, and CLI."""

from unittest.mock import MagicMock, patch

from qualytics.api.datastores import (
    create_datastore,
    update_datastore,
    get_datastore,
    list_datastores,
    list_all_datastores,
    delete_datastore,
    verify_connection,
    validate_connection,
    connect_enrichment,
    disconnect_enrichment,
)
from qualytics.services.datastores import (
    get_datastore_by,
    get_datastore_by_name,
    build_create_datastore_payload,
    build_update_datastore_payload,
)
from qualytics.qualytics import app


# ── Shared fixtures ──────────────────────────────────────────────────────


def _mock_client():
    return MagicMock()


# ══════════════════════════════════════════════════════════════════════════
# 1. API LAYER
# ══════════════════════════════════════════════════════════════════════════


class TestCreateDatastore:
    def test_posts_payload(self):
        client = _mock_client()
        client.post.return_value.json.return_value = {"id": 1, "name": "ds1"}
        payload = {"name": "ds1", "database": "db", "schema": "sc"}
        result = create_datastore(client, payload)
        client.post.assert_called_once_with("datastores", json=payload)
        assert result["id"] == 1

    def test_returns_full_response(self):
        client = _mock_client()
        resp = {"id": 5, "name": "ds5", "connection": {"id": 10}}
        client.post.return_value.json.return_value = resp
        result = create_datastore(client, {"name": "ds5"})
        assert result == resp


class TestUpdateDatastore:
    def test_puts_payload(self):
        client = _mock_client()
        client.put.return_value.json.return_value = {"id": 1, "name": "new_name"}
        result = update_datastore(client, 1, {"name": "new_name"})
        client.put.assert_called_once_with("datastores/1", json={"name": "new_name"})
        assert result["name"] == "new_name"


class TestGetDatastore:
    def test_calls_correct_endpoint(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"id": 42, "name": "myds"}
        result = get_datastore(client, 42)
        client.get.assert_called_once_with("datastores/42")
        assert result["id"] == 42


class TestListDatastores:
    def test_basic_call(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}],
            "total": 1,
        }
        result = list_datastores(client)
        client.get.assert_called_once_with(
            "datastores", params={"page": 1, "size": 100}
        )
        assert result["items"] == [{"id": 1}]

    def test_with_filters(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_datastores(
            client,
            name="test",
            datastore_type=["postgresql"],
            enrichment_only=True,
            tag="prod",
        )
        params = client.get.call_args.kwargs["params"]
        assert params["name"] == "test"
        assert params["datastore_type"] == ["postgresql"]
        assert params["enrichment_only"] is True
        assert params["tag"] == "prod"

    def test_none_filters_excluded(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_datastores(client)
        params = client.get.call_args.kwargs["params"]
        assert "name" not in params
        assert "datastore_type" not in params
        assert "enrichment_only" not in params
        assert "tag" not in params


class TestListAllDatastores:
    def test_single_page(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}, {"id": 2}],
            "total": 2,
        }
        result = list_all_datastores(client)
        assert len(result) == 2
        assert client.get.call_count == 1

    def test_multi_page(self):
        client = _mock_client()
        page1 = {"items": [{"id": i} for i in range(100)], "total": 150}
        page2 = {"items": [{"id": i} for i in range(100, 150)], "total": 150}
        client.get.return_value.json.side_effect = [page1, page2]
        result = list_all_datastores(client)
        assert len(result) == 150
        assert client.get.call_count == 2

    def test_empty(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        result = list_all_datastores(client)
        assert result == []


class TestDeleteDatastore:
    def test_returns_success_on_204(self):
        client = _mock_client()
        client.delete.return_value.content = b""
        client.delete.return_value.status_code = 204
        result = delete_datastore(client, 42)
        client.delete.assert_called_once_with("datastores/42")
        assert result["success"] is True

    def test_returns_json_when_body(self):
        client = _mock_client()
        client.delete.return_value.content = b'{"ok": true}'
        client.delete.return_value.status_code = 200
        client.delete.return_value.json.return_value = {"ok": True}
        result = delete_datastore(client, 42)
        assert result == {"ok": True}


class TestVerifyConnection:
    def test_posts_to_connection_endpoint(self):
        client = _mock_client()
        client.post.return_value.json.return_value = {"connected": True}
        result = verify_connection(client, 10)
        client.post.assert_called_once_with("datastores/10/connection")
        assert result["connected"] is True

    def test_disconnected(self):
        client = _mock_client()
        client.post.return_value.json.return_value = {
            "connected": False,
            "message": "timeout",
        }
        result = verify_connection(client, 10)
        assert result["connected"] is False
        assert result["message"] == "timeout"


class TestValidateConnection:
    def test_posts_payload(self):
        client = _mock_client()
        client.post.return_value.json.return_value = {"valid": True}
        payload = {"name": "test", "connection": {"host": "localhost"}}
        result = validate_connection(client, payload)
        client.post.assert_called_once_with("datastores/connection", json=payload)
        assert result["valid"] is True


class TestConnectEnrichment:
    def test_patches_enrichment_link(self):
        client = _mock_client()
        client.patch.return_value.json.return_value = {"id": 1, "enrichment": {"id": 5}}
        result = connect_enrichment(client, 1, 5)
        client.patch.assert_called_once_with("datastores/1/enrichment/5")
        assert result["enrichment"]["id"] == 5


class TestDisconnectEnrichment:
    def test_returns_success_on_204(self):
        client = _mock_client()
        client.delete.return_value.content = b""
        client.delete.return_value.status_code = 204
        result = disconnect_enrichment(client, 1)
        client.delete.assert_called_once_with("datastores/1/enrichment")
        assert result["success"] is True

    def test_returns_json_when_body(self):
        client = _mock_client()
        client.delete.return_value.content = b'{"ok": true}'
        client.delete.return_value.status_code = 200
        client.delete.return_value.json.return_value = {"ok": True}
        result = disconnect_enrichment(client, 1)
        assert result == {"ok": True}


# ══════════════════════════════════════════════════════════════════════════
# 2. SERVICE LAYER
# ══════════════════════════════════════════════════════════════════════════


class TestGetDatastoreBy:
    @patch("qualytics.services.datastores.get_datastore")
    def test_by_id(self, mock_get):
        mock_get.return_value = {"id": 42, "name": "myds"}
        client = _mock_client()
        result = get_datastore_by(client, datastore_id=42)
        mock_get.assert_called_once_with(client, 42)
        assert result["id"] == 42

    @patch("qualytics.services.datastores.get_datastore_by_name")
    def test_by_name(self, mock_get_name):
        mock_get_name.return_value = {"id": 10, "name": "test"}
        client = _mock_client()
        result = get_datastore_by(client, datastore_name="test")
        mock_get_name.assert_called_once_with(client, "test")
        assert result["name"] == "test"

    def test_raises_when_both(self):
        import pytest

        with pytest.raises(ValueError, match="Cannot specify both"):
            get_datastore_by(_mock_client(), datastore_id=1, datastore_name="x")

    def test_raises_when_neither(self):
        import pytest

        with pytest.raises(ValueError, match="Either"):
            get_datastore_by(_mock_client())


class TestGetDatastoreByName:
    @patch("qualytics.services.datastores.list_datastores")
    def test_found(self, mock_list):
        mock_list.return_value = {
            "items": [{"id": 10, "name": "target"}],
            "total": 1,
        }
        client = _mock_client()
        result = get_datastore_by_name(client, "target")
        assert result["id"] == 10

    @patch("qualytics.services.datastores.list_datastores")
    def test_not_found(self, mock_list):
        mock_list.return_value = {"items": [], "total": 0}
        client = _mock_client()
        result = get_datastore_by_name(client, "missing")
        assert result is None


class TestBuildCreateDatastorePayload:
    def test_with_connection_id(self):
        payload = build_create_datastore_payload(
            name="ds1",
            connection_id=5,
            database="mydb",
            schema="public",
        )
        assert payload["name"] == "ds1"
        assert payload["connection_id"] == 5
        assert payload["database"] == "mydb"
        assert payload["schema"] == "public"


class TestBuildUpdateDatastorePayload:
    def test_partial_fields(self):
        payload = build_update_datastore_payload(name="new_name", database="new_db")
        assert payload == {"name": "new_name", "database": "new_db"}
        assert "schema" not in payload
        assert "tags" not in payload

    def test_empty_when_nothing(self):
        payload = build_update_datastore_payload()
        assert payload == {}

    def test_all_fields(self):
        payload = build_update_datastore_payload(
            name="n",
            connection_id=1,
            database="d",
            schema="s",
            tags=["a"],
            teams=["t"],
            enrichment_only=True,
            enrichment_prefix="p",
            enrichment_source_record_limit=100,
            enrichment_remediation_strategy="append",
            high_count_rollup_threshold=500,
        )
        assert payload["name"] == "n"
        assert payload["connection_id"] == 1
        assert payload["enrichment_only"] is True
        assert payload["enrichment_source_record_limit"] == 100


# ══════════════════════════════════════════════════════════════════════════
# 3. CLI COMMAND TESTS
# ══════════════════════════════════════════════════════════════════════════


class TestDatastoresCreateCLI:
    @patch("qualytics.cli.datastores.create_datastore")
    @patch("qualytics.cli.datastores.get_connection_by")
    @patch("qualytics.cli.datastores.get_client")
    def test_create_with_connection_id(
        self, mock_gc, mock_conn, mock_create, cli_runner
    ):
        mock_gc.return_value = _mock_client()
        mock_create.return_value = {"id": 1, "name": "ds1", "connection": {"id": 5}}
        result = cli_runner.invoke(
            app,
            [
                "datastores",
                "create",
                "--name",
                "ds1",
                "--connection-id",
                "5",
                "--database",
                "mydb",
                "--schema",
                "public",
            ],
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output
        mock_create.assert_called_once()

    @patch("qualytics.cli.datastores.create_datastore")
    @patch("qualytics.cli.datastores.get_connection_by")
    @patch("qualytics.cli.datastores.get_client")
    def test_create_dry_run(self, mock_gc, mock_conn, mock_create, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "datastores",
                "create",
                "--name",
                "ds1",
                "--connection-id",
                "5",
                "--database",
                "mydb",
                "--schema",
                "public",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        mock_create.assert_not_called()

    @patch("qualytics.cli.datastores.get_client")
    def test_create_rejects_both_connection_params(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "datastores",
                "create",
                "--name",
                "ds1",
                "--connection-name",
                "pg",
                "--connection-id",
                "5",
                "--database",
                "db",
                "--schema",
                "sc",
            ],
        )
        assert result.exit_code == 1
        assert "Cannot specify both" in result.output


class TestDatastoresUpdateCLI:
    @patch("qualytics.cli.datastores.update_datastore")
    @patch("qualytics.cli.datastores.get_client")
    def test_update_basic(self, mock_gc, mock_update, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_update.return_value = {"id": 1, "name": "new_name"}
        result = cli_runner.invoke(
            app, ["datastores", "update", "--id", "1", "--name", "new_name"]
        )
        assert result.exit_code == 0
        assert "updated successfully" in result.output
        mock_update.assert_called_once()

    @patch("qualytics.cli.datastores.update_datastore")
    @patch("qualytics.cli.datastores.get_client")
    def test_update_all_flags(self, mock_gc, mock_update, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_update.return_value = {"id": 1, "name": "n"}
        result = cli_runner.invoke(
            app,
            [
                "datastores",
                "update",
                "--id",
                "1",
                "--name",
                "n",
                "--database",
                "db",
                "--schema",
                "sc",
                "--tags",
                "a,b",
                "--teams",
                "t1,t2",
                "--enrichment-remediation-strategy",
                "append",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        _, kwargs = mock_update.call_args
        payload = (
            kwargs["payload"] if "payload" in kwargs else mock_update.call_args.args[2]
        )
        assert payload["name"] == "n"
        assert payload["database"] == "db"
        assert payload["tags"] == ["a", "b"]
        assert payload["teams"] == ["t1", "t2"]

    @patch("qualytics.cli.datastores.get_client")
    def test_update_invalid_remediation(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "datastores",
                "update",
                "--id",
                "1",
                "--enrichment-remediation-strategy",
                "invalid",
            ],
        )
        assert result.exit_code == 1
        assert "must be one of" in result.output

    @patch("qualytics.cli.datastores.get_client")
    def test_update_no_fields(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(app, ["datastores", "update", "--id", "1"])
        assert result.exit_code == 1
        assert "No fields to update" in result.output


class TestDatastoresGetCLI:
    @patch("qualytics.cli.datastores.get_datastore")
    @patch("qualytics.cli.datastores.get_client")
    def test_get_by_id(self, mock_gc, mock_get, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {"id": 42, "name": "myds"}
        result = cli_runner.invoke(app, ["datastores", "get", "--id", "42"])
        assert result.exit_code == 0
        assert "Datastore found" in result.output
        mock_get.assert_called_once_with(mock_gc.return_value, 42)

    @patch("qualytics.cli.datastores.get_datastore_by")
    @patch("qualytics.cli.datastores.get_client")
    def test_get_by_name(self, mock_gc, mock_get_by, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get_by.return_value = {"id": 10, "name": "target"}
        result = cli_runner.invoke(
            app, ["datastores", "get", "--name", "target", "--format", "json"]
        )
        assert result.exit_code == 0
        mock_get_by.assert_called_once_with(
            mock_gc.return_value, datastore_name="target"
        )

    @patch("qualytics.cli.datastores.get_client")
    def test_get_rejects_both(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app, ["datastores", "get", "--id", "1", "--name", "x"]
        )
        assert result.exit_code == 1
        assert "Cannot specify both" in result.output

    @patch("qualytics.cli.datastores.get_client")
    def test_get_requires_one(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(app, ["datastores", "get"])
        assert result.exit_code == 1
        assert "Must specify either" in result.output


class TestDatastoresListCLI:
    @patch("qualytics.cli.datastores.list_all_datastores")
    @patch("qualytics.cli.datastores.get_client")
    def test_list_basic(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = [{"id": 1}, {"id": 2}]
        result = cli_runner.invoke(app, ["datastores", "list"])
        assert result.exit_code == 0
        assert "Found 2 datastores" in result.output

    @patch("qualytics.cli.datastores.list_all_datastores")
    @patch("qualytics.cli.datastores.get_client")
    def test_list_with_filters(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = []
        result = cli_runner.invoke(
            app,
            [
                "datastores",
                "list",
                "--name",
                "test",
                "--type",
                "postgresql,snowflake",
                "--tag",
                "prod",
                "--enrichment-only",
            ],
        )
        assert result.exit_code == 0
        _, kwargs = mock_list.call_args
        assert kwargs["name"] == "test"
        assert kwargs["datastore_type"] == ["postgresql", "snowflake"]
        assert kwargs["tag"] == "prod"
        assert kwargs["enrichment_only"] is True


class TestDatastoresDeleteCLI:
    @patch("qualytics.cli.datastores.delete_datastore")
    @patch("qualytics.cli.datastores.get_client")
    def test_delete(self, mock_gc, mock_delete, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_delete.return_value = {
            "success": True,
            "message": "Datastore deleted successfully",
        }
        result = cli_runner.invoke(app, ["datastores", "delete", "--id", "42"])
        assert result.exit_code == 0
        assert "deleted successfully" in result.output
        mock_delete.assert_called_once_with(mock_gc.return_value, 42)


class TestDatastoresVerifyCLI:
    @patch("qualytics.cli.datastores.verify_connection")
    @patch("qualytics.cli.datastores.get_client")
    def test_verify_connected(self, mock_gc, mock_verify, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_verify.return_value = {"connected": True}
        result = cli_runner.invoke(app, ["datastores", "verify", "--id", "10"])
        assert result.exit_code == 0
        assert "verified successfully" in result.output

    @patch("qualytics.cli.datastores.verify_connection")
    @patch("qualytics.cli.datastores.get_client")
    def test_verify_failed(self, mock_gc, mock_verify, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_verify.return_value = {"connected": False, "message": "timeout"}
        result = cli_runner.invoke(
            app, ["datastores", "verify", "--id", "10", "--format", "json"]
        )
        assert result.exit_code == 0
        assert "connection failed" in result.output
        assert "timeout" in result.output


class TestDatastoresEnrichmentCLI:
    @patch("qualytics.cli.datastores.connect_enrichment")
    @patch("qualytics.cli.datastores.get_client")
    def test_link(self, mock_gc, mock_connect, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_connect.return_value = {"id": 1, "enrichment": {"id": 5}}
        result = cli_runner.invoke(
            app, ["datastores", "enrichment", "--id", "1", "--link", "5"]
        )
        assert result.exit_code == 0
        assert "linked" in result.output
        mock_connect.assert_called_once_with(mock_gc.return_value, 1, 5)

    @patch("qualytics.cli.datastores.disconnect_enrichment")
    @patch("qualytics.cli.datastores.get_client")
    def test_unlink(self, mock_gc, mock_disconnect, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_disconnect.return_value = {
            "success": True,
            "message": "Enrichment disconnected successfully",
        }
        result = cli_runner.invoke(
            app, ["datastores", "enrichment", "--id", "1", "--unlink"]
        )
        assert result.exit_code == 0
        assert "unlinked" in result.output.lower() or "Unlinked" in result.output

    @patch("qualytics.cli.datastores.get_client")
    def test_rejects_both(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app, ["datastores", "enrichment", "--id", "1", "--link", "5", "--unlink"]
        )
        assert result.exit_code == 1
        assert "Cannot specify both" in result.output

    @patch("qualytics.cli.datastores.get_client")
    def test_requires_one(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(app, ["datastores", "enrichment", "--id", "1"])
        assert result.exit_code == 1
        assert "Must specify either" in result.output
