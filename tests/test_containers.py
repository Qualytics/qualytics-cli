"""Tests for containers — API, service, and CLI."""

import pytest
from unittest.mock import MagicMock, patch

from qualytics.api.containers import (
    create_container,
    update_container,
    get_container,
    list_containers,
    list_all_containers,
    delete_container,
    validate_container,
    get_field_profiles,
    list_containers_listing,
)
from qualytics.services.containers import (
    get_container_by_name,
    build_create_container_payload,
    build_update_container_payload,
)
from qualytics.qualytics import app


# ── Shared fixtures ──────────────────────────────────────────────────────


def _mock_client():
    return MagicMock()


# ══════════════════════════════════════════════════════════════════════════
# 1. API LAYER
# ══════════════════════════════════════════════════════════════════════════


class TestCreateContainer:
    def test_posts_payload(self):
        client = _mock_client()
        client.post.return_value.json.return_value = {
            "id": 1,
            "name": "ct_test",
            "container_type": "computed_table",
        }
        payload = {
            "container_type": "computed_table",
            "name": "ct_test",
            "query": "SELECT 1",
            "datastore_id": 10,
        }
        result = create_container(client, payload)
        client.post.assert_called_once_with("containers", json=payload)
        assert result["id"] == 1
        assert result["container_type"] == "computed_table"

    def test_returns_full_response(self):
        client = _mock_client()
        resp = {"id": 5, "name": "ct_join", "container_type": "computed_join"}
        client.post.return_value.json.return_value = resp
        result = create_container(client, {"container_type": "computed_join"})
        assert result == resp


class TestUpdateContainer:
    def test_puts_payload(self):
        client = _mock_client()
        client.put.return_value.json.return_value = {"id": 1, "name": "updated"}
        result = update_container(client, 1, {"name": "updated"})
        client.put.assert_called_once_with(
            "containers/1", json={"name": "updated"}, params=None
        )
        assert result["name"] == "updated"

    def test_force_drop_fields(self):
        client = _mock_client()
        client.put.return_value.json.return_value = {"id": 1}
        update_container(client, 1, {"name": "x"}, force_drop_fields=True)
        client.put.assert_called_once_with(
            "containers/1",
            json={"name": "x"},
            params={"force_drop_fields": True},
        )

    def test_no_force_drop_fields(self):
        client = _mock_client()
        client.put.return_value.json.return_value = {"id": 1}
        update_container(client, 1, {"name": "x"}, force_drop_fields=False)
        client.put.assert_called_once_with(
            "containers/1", json={"name": "x"}, params=None
        )


class TestGetContainer:
    def test_calls_correct_endpoint(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "id": 42,
            "name": "my_table",
            "container_type": "table",
        }
        result = get_container(client, 42)
        client.get.assert_called_once_with("containers/42")
        assert result["id"] == 42


class TestListContainers:
    def test_basic_call(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}],
            "total": 1,
        }
        result = list_containers(client)
        client.get.assert_called_once_with(
            "containers", params={"page": 1, "size": 100}
        )
        assert result["items"] == [{"id": 1}]

    def test_with_filters(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_containers(
            client,
            datastore=[10],
            container_type=["computed_table"],
            name="test",
            tag=["prod"],
            search="foo",
            archived="only",
        )
        params = client.get.call_args.kwargs["params"]
        assert params["datastore"] == [10]
        assert params["container_type"] == ["computed_table"]
        assert params["name"] == "test"
        assert params["tag"] == ["prod"]
        assert params["search"] == "foo"
        assert params["archived"] == "only"

    def test_none_filters_excluded(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_containers(client)
        params = client.get.call_args.kwargs["params"]
        assert "datastore" not in params
        assert "container_type" not in params
        assert "name" not in params
        assert "tag" not in params
        assert "search" not in params
        assert "archived" not in params


class TestListAllContainers:
    def test_single_page(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}, {"id": 2}],
            "total": 2,
        }
        result = list_all_containers(client)
        assert len(result) == 2
        assert client.get.call_count == 1

    def test_multi_page(self):
        client = _mock_client()
        page1 = {"items": [{"id": i} for i in range(100)], "total": 150}
        page2 = {"items": [{"id": i} for i in range(100, 150)], "total": 150}
        client.get.return_value.json.side_effect = [page1, page2]
        result = list_all_containers(client)
        assert len(result) == 150
        assert client.get.call_count == 2

    def test_empty(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        result = list_all_containers(client)
        assert result == []

    def test_passes_filters_through(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_all_containers(client, datastore=[5], container_type=["table"])
        params = client.get.call_args.kwargs["params"]
        assert params["datastore"] == [5]
        assert params["container_type"] == ["table"]


class TestDeleteContainer:
    def test_returns_success_on_204(self):
        client = _mock_client()
        client.delete.return_value.content = b""
        client.delete.return_value.status_code = 204
        result = delete_container(client, 42)
        client.delete.assert_called_once_with("containers/42")
        assert result["success"] is True

    def test_returns_json_when_body(self):
        client = _mock_client()
        client.delete.return_value.content = b'{"ok": true}'
        client.delete.return_value.status_code = 200
        client.delete.return_value.json.return_value = {"ok": True}
        result = delete_container(client, 42)
        assert result == {"ok": True}


class TestValidateContainer:
    def test_success_on_204(self):
        client = _mock_client()
        client.post.return_value.content = b""
        client.post.return_value.status_code = 204
        payload = {"container_type": "computed_table", "query": "SELECT 1"}
        result = validate_container(client, payload)
        client.post.assert_called_once_with(
            "containers/validate",
            json={"container": payload},
            params={"timeout_seconds": 60},
        )
        assert result["success"] is True

    def test_custom_timeout(self):
        client = _mock_client()
        client.post.return_value.content = b""
        client.post.return_value.status_code = 204
        validate_container(client, {"container_type": "computed_table"}, timeout=120)
        params = client.post.call_args.kwargs["params"]
        assert params["timeout_seconds"] == 120

    def test_returns_error_on_body(self):
        client = _mock_client()
        client.post.return_value.content = b'{"error": "bad query"}'
        client.post.return_value.status_code = 400
        client.post.return_value.json.return_value = {"error": "bad query"}
        result = validate_container(client, {"container_type": "computed_table"})
        assert result == {"error": "bad query"}


class TestGetFieldProfiles:
    def test_calls_correct_endpoint(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"name": "col1", "type": "string"}]
        }
        result = get_field_profiles(client, 99)
        client.get.assert_called_once_with("containers/99/field-profiles")
        assert result["items"][0]["name"] == "col1"


class TestListContainersListing:
    def test_basic_call(self):
        client = _mock_client()
        client.get.return_value.json.return_value = [
            {"id": 1, "name": "table_a"},
            {"id": 2, "name": "table_b"},
        ]
        result = list_containers_listing(client, 10)
        client.get.assert_called_once_with(
            "containers/listing", params={"datastore": 10}
        )
        assert len(result) == 2

    def test_with_container_type(self):
        client = _mock_client()
        client.get.return_value.json.return_value = []
        list_containers_listing(client, 10, container_type="computed_table")
        params = client.get.call_args.kwargs["params"]
        assert params["type"] == "computed_table"

    def test_without_container_type(self):
        client = _mock_client()
        client.get.return_value.json.return_value = []
        list_containers_listing(client, 10)
        params = client.get.call_args.kwargs["params"]
        assert "type" not in params


# ══════════════════════════════════════════════════════════════════════════
# 2. SERVICE LAYER
# ══════════════════════════════════════════════════════════════════════════


class TestGetContainerByName:
    @patch("qualytics.services.containers.list_containers_listing")
    def test_found(self, mock_listing):
        mock_listing.return_value = [
            {"id": 10, "name": "target"},
            {"id": 20, "name": "other"},
        ]
        client = _mock_client()
        result = get_container_by_name(client, 5, "target")
        mock_listing.assert_called_once_with(client, 5)
        assert result["id"] == 10

    @patch("qualytics.services.containers.list_containers_listing")
    def test_not_found(self, mock_listing):
        mock_listing.return_value = [{"id": 10, "name": "other"}]
        client = _mock_client()
        result = get_container_by_name(client, 5, "missing")
        assert result is None

    @patch("qualytics.services.containers.list_containers_listing")
    def test_empty_listing(self, mock_listing):
        mock_listing.return_value = []
        client = _mock_client()
        result = get_container_by_name(client, 5, "any")
        assert result is None


class TestBuildCreateContainerPayload:
    def test_computed_table(self):
        payload = build_create_container_payload(
            "computed_table",
            datastore_id=10,
            name="ct_test",
            query="SELECT * FROM t",
        )
        assert payload["container_type"] == "computed_table"
        assert payload["datastore_id"] == 10
        assert payload["name"] == "ct_test"
        assert payload["query"] == "SELECT * FROM t"

    def test_computed_table_requires_datastore_id(self):
        with pytest.raises(ValueError, match="--datastore-id"):
            build_create_container_payload(
                "computed_table", name="ct_test", query="SELECT 1"
            )

    def test_computed_table_requires_query(self):
        with pytest.raises(ValueError, match="--query"):
            build_create_container_payload(
                "computed_table", datastore_id=10, name="ct_test"
            )

    def test_computed_file(self):
        payload = build_create_container_payload(
            "computed_file",
            datastore_id=10,
            name="cf_test",
            source_container_id=20,
            select_clause="col1, col2",
        )
        assert payload["container_type"] == "computed_file"
        assert payload["datastore_id"] == 10
        assert payload["source_container_id"] == 20
        assert payload["select_clause"] == "col1, col2"

    def test_computed_file_requires_source(self):
        with pytest.raises(ValueError, match="--source-container-id"):
            build_create_container_payload(
                "computed_file",
                datastore_id=10,
                name="cf_test",
                select_clause="col1",
            )

    def test_computed_file_requires_select(self):
        with pytest.raises(ValueError, match="--select-clause"):
            build_create_container_payload(
                "computed_file",
                datastore_id=10,
                name="cf_test",
                source_container_id=20,
            )

    def test_computed_file_optional_clauses(self):
        payload = build_create_container_payload(
            "computed_file",
            datastore_id=10,
            name="cf_test",
            source_container_id=20,
            select_clause="col1",
            where_clause="col1 > 0",
            group_by_clause="col1",
        )
        assert payload["where_clause"] == "col1 > 0"
        assert payload["group_by_clause"] == "col1"

    def test_computed_join(self):
        payload = build_create_container_payload(
            "computed_join",
            name="cj_test",
            left_container_id=10,
            right_container_id=20,
            left_key_field="id",
            right_key_field="fk_id",
            select_clause="l.id, r.name",
        )
        assert payload["container_type"] == "computed_join"
        assert payload["left_container_id"] == 10
        assert payload["right_container_id"] == 20
        assert payload["left_join_field_name"] == "id"
        assert payload["right_join_field_name"] == "fk_id"
        assert payload["select_clause"] == "l.id, r.name"

    def test_computed_join_requires_left_container(self):
        with pytest.raises(ValueError, match="--left-container-id"):
            build_create_container_payload(
                "computed_join",
                name="cj_test",
                right_container_id=20,
                left_key_field="id",
                right_key_field="fk_id",
                select_clause="*",
            )

    def test_computed_join_requires_right_container(self):
        with pytest.raises(ValueError, match="--right-container-id"):
            build_create_container_payload(
                "computed_join",
                name="cj_test",
                left_container_id=10,
                left_key_field="id",
                right_key_field="fk_id",
                select_clause="*",
            )

    def test_computed_join_requires_key_fields(self):
        with pytest.raises(ValueError, match="--left-key-field"):
            build_create_container_payload(
                "computed_join",
                name="cj_test",
                left_container_id=10,
                right_container_id=20,
                right_key_field="fk_id",
                select_clause="*",
            )
        with pytest.raises(ValueError, match="--right-key-field"):
            build_create_container_payload(
                "computed_join",
                name="cj_test",
                left_container_id=10,
                right_container_id=20,
                left_key_field="id",
                select_clause="*",
            )

    def test_computed_join_requires_select(self):
        with pytest.raises(ValueError, match="--select-clause"):
            build_create_container_payload(
                "computed_join",
                name="cj_test",
                left_container_id=10,
                right_container_id=20,
                left_key_field="id",
                right_key_field="fk_id",
            )

    def test_computed_join_optional_fields(self):
        payload = build_create_container_payload(
            "computed_join",
            name="cj_test",
            left_container_id=10,
            right_container_id=20,
            left_key_field="id",
            right_key_field="fk_id",
            select_clause="*",
            join_type="left",
            left_prefix="l_",
            right_prefix="r_",
            where_clause="l_id > 0",
            group_by_clause="l_id",
        )
        assert payload["join_type"] == "left"
        assert payload["left_prefix"] == "l_"
        assert payload["right_prefix"] == "r_"
        assert payload["where_clause"] == "l_id > 0"
        assert payload["group_by_clause"] == "l_id"

    def test_rejects_non_computed_type(self):
        with pytest.raises(ValueError, match="Only computed types"):
            build_create_container_payload("table", name="t1")

    def test_additional_metadata(self):
        payload = build_create_container_payload(
            "computed_table",
            datastore_id=10,
            name="ct_test",
            query="SELECT 1",
            additional_metadata={"source": "cli"},
        )
        assert payload["additional_metadata"] == {"source": "cli"}

    def test_additional_metadata_omitted_when_none(self):
        payload = build_create_container_payload(
            "computed_table",
            datastore_id=10,
            name="ct_test",
            query="SELECT 1",
        )
        assert "additional_metadata" not in payload


class TestBuildUpdateContainerPayload:
    def test_preserves_container_type(self):
        existing = {"container_type": "computed_table", "name": "old", "query": "q"}
        payload = build_update_container_payload(existing, name="new")
        assert payload["container_type"] == "computed_table"

    def test_computed_table_includes_name_and_query(self):
        existing = {
            "container_type": "computed_table",
            "name": "old",
            "query": "SELECT 1",
        }
        payload = build_update_container_payload(existing, name="new")
        assert payload["name"] == "new"
        assert payload["query"] == "SELECT 1"

    def test_computed_table_overrides_query(self):
        existing = {
            "container_type": "computed_table",
            "name": "old",
            "query": "SELECT 1",
        }
        payload = build_update_container_payload(existing, query="SELECT 2")
        assert payload["query"] == "SELECT 2"
        assert payload["name"] == "old"

    def test_computed_file_includes_select_clause(self):
        existing = {
            "container_type": "computed_file",
            "name": "old",
            "select_clause": "col1",
        }
        payload = build_update_container_payload(existing)
        assert payload["select_clause"] == "col1"
        assert payload["name"] == "old"

    def test_non_computed_type_minimal(self):
        existing = {"container_type": "table", "name": "t1"}
        payload = build_update_container_payload(existing, description="desc")
        assert payload["container_type"] == "table"
        assert payload["description"] == "desc"
        assert "name" not in payload

    def test_none_values_excluded(self):
        existing = {"container_type": "table"}
        payload = build_update_container_payload(existing, tags=None)
        assert "tags" not in payload

    def test_overlays_extra_changes(self):
        existing = {"container_type": "computed_table", "name": "ct", "query": "q"}
        payload = build_update_container_payload(
            existing, description="updated", tags=["a", "b"]
        )
        assert payload["description"] == "updated"
        assert payload["tags"] == ["a", "b"]


# ══════════════════════════════════════════════════════════════════════════
# 3. CLI COMMAND TESTS
# ══════════════════════════════════════════════════════════════════════════


class TestContainersCreateCLI:
    @patch("qualytics.cli.containers.create_container")
    @patch("qualytics.cli.containers.get_client")
    def test_create_computed_table(self, mock_gc, mock_create, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_create.return_value = {
            "id": 1,
            "name": "ct_test",
            "container_type": "computed_table",
        }
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "create",
                "--type",
                "computed_table",
                "--name",
                "ct_test",
                "--datastore-id",
                "10",
                "--query",
                "SELECT * FROM t",
            ],
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output
        mock_create.assert_called_once()

    @patch("qualytics.cli.containers.create_container")
    @patch("qualytics.cli.containers.get_client")
    def test_create_computed_join(self, mock_gc, mock_create, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_create.return_value = {
            "id": 2,
            "name": "cj_test",
            "container_type": "computed_join",
        }
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "create",
                "--type",
                "computed_join",
                "--name",
                "cj_test",
                "--left-container-id",
                "10",
                "--right-container-id",
                "20",
                "--left-key-field",
                "id",
                "--right-key-field",
                "fk_id",
                "--select-clause",
                "l.id, r.name",
            ],
        )
        assert result.exit_code == 0
        assert "created successfully" in result.output

    @patch("qualytics.cli.containers.get_client")
    def test_create_dry_run(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "create",
                "--type",
                "computed_table",
                "--name",
                "ct_test",
                "--datastore-id",
                "10",
                "--query",
                "SELECT 1",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "Dry run" in result.output

    @patch("qualytics.cli.containers.get_client")
    def test_create_rejects_non_computed(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "create",
                "--type",
                "table",
                "--name",
                "t1",
            ],
        )
        assert result.exit_code == 1
        assert "must be one of" in result.output

    @patch("qualytics.cli.containers.get_client")
    def test_create_rejects_invalid_join_type(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "create",
                "--type",
                "computed_join",
                "--name",
                "cj",
                "--left-container-id",
                "10",
                "--right-container-id",
                "20",
                "--left-key-field",
                "id",
                "--right-key-field",
                "fk",
                "--select-clause",
                "*",
                "--join-type",
                "invalid",
            ],
        )
        assert result.exit_code == 1
        assert "must be one of" in result.output

    @patch("qualytics.cli.containers.get_client")
    def test_create_missing_required_field(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "create",
                "--type",
                "computed_table",
                "--name",
                "ct_test",
                "--datastore-id",
                "10",
                # Missing --query
            ],
        )
        assert result.exit_code == 1
        assert "--query" in result.output


class TestContainersUpdateCLI:
    @patch("qualytics.cli.containers.update_container")
    @patch("qualytics.cli.containers.get_container")
    @patch("qualytics.cli.containers.get_client")
    def test_update_basic(self, mock_gc, mock_get, mock_update, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {
            "id": 1,
            "container_type": "computed_table",
            "name": "old",
            "query": "SELECT 1",
        }
        mock_update.return_value = {"id": 1, "name": "new", "query": "SELECT 1"}
        result = cli_runner.invoke(
            app, ["containers", "update", "--id", "1", "--name", "new"]
        )
        assert result.exit_code == 0
        assert "updated successfully" in result.output
        mock_update.assert_called_once()

    @patch("qualytics.cli.containers.get_container")
    @patch("qualytics.cli.containers.get_client")
    def test_update_no_fields(self, mock_gc, mock_get, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {"id": 1, "container_type": "table"}
        result = cli_runner.invoke(app, ["containers", "update", "--id", "1"])
        assert result.exit_code == 1
        assert "No fields to update" in result.output

    @patch("qualytics.cli.containers.update_container")
    @patch("qualytics.cli.containers.get_container")
    @patch("qualytics.cli.containers.get_client")
    def test_update_with_force_drop(self, mock_gc, mock_get, mock_update, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {
            "id": 1,
            "container_type": "computed_table",
            "name": "ct",
            "query": "SELECT 1",
        }
        mock_update.return_value = {"id": 1, "name": "ct", "query": "SELECT 2"}
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "update",
                "--id",
                "1",
                "--query",
                "SELECT 2",
                "--force-drop-fields",
            ],
        )
        assert result.exit_code == 0
        _, kwargs = mock_update.call_args
        assert kwargs["force_drop_fields"] is True

    @patch("qualytics.cli.containers.update_container")
    @patch("qualytics.cli.containers.get_container")
    @patch("qualytics.cli.containers.get_client")
    def test_update_409_conflict(self, mock_gc, mock_get, mock_update, cli_runner):
        from qualytics.api.client import QualyticsAPIError

        mock_gc.return_value = _mock_client()
        mock_get.return_value = {
            "id": 1,
            "container_type": "computed_table",
            "name": "ct",
            "query": "SELECT 1",
        }
        mock_update.side_effect = QualyticsAPIError(409, "Field drop conflict")
        result = cli_runner.invoke(
            app, ["containers", "update", "--id", "1", "--query", "SELECT 2"]
        )
        assert result.exit_code == 1
        assert "409 Conflict" in result.output
        assert "force-drop-fields" in result.output


class TestContainersGetCLI:
    @patch("qualytics.cli.containers.get_container")
    @patch("qualytics.cli.containers.get_client")
    def test_get_basic(self, mock_gc, mock_get, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {
            "id": 42,
            "name": "my_table",
            "container_type": "table",
        }
        result = cli_runner.invoke(app, ["containers", "get", "--id", "42"])
        assert result.exit_code == 0
        assert "Container found" in result.output
        mock_get.assert_called_once_with(mock_gc.return_value, 42)

    @patch("qualytics.cli.containers.get_field_profiles")
    @patch("qualytics.cli.containers.get_container")
    @patch("qualytics.cli.containers.get_client")
    def test_get_with_profiles(self, mock_gc, mock_get, mock_profiles, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {"id": 42, "name": "t1"}
        mock_profiles.return_value = {"items": [{"name": "col1"}]}
        result = cli_runner.invoke(
            app, ["containers", "get", "--id", "42", "--profiles"]
        )
        assert result.exit_code == 0
        assert "Field Profiles" in result.output
        mock_profiles.assert_called_once_with(mock_gc.return_value, 42)


class TestContainersListCLI:
    @patch("qualytics.cli.containers.list_all_containers")
    @patch("qualytics.cli.containers.get_client")
    def test_list_basic(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = [{"id": 1}, {"id": 2}]
        result = cli_runner.invoke(app, ["containers", "list", "--datastore-id", "10"])
        assert result.exit_code == 0
        assert "Found 2 containers" in result.output

    @patch("qualytics.cli.containers.list_all_containers")
    @patch("qualytics.cli.containers.get_client")
    def test_list_with_filters(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = []
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "list",
                "--datastore-id",
                "10",
                "--type",
                "computed_table,computed_file",
                "--name",
                "test",
                "--tag",
                "prod",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        _, kwargs = mock_list.call_args
        assert kwargs["container_type"] == ["computed_table", "computed_file"]
        assert kwargs["name"] == "test"
        assert kwargs["tag"] == ["prod"]
        assert kwargs["datastore"] == [10]

    @patch("qualytics.cli.containers.get_client")
    def test_list_invalid_type(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            ["containers", "list", "--datastore-id", "10", "--type", "invalid_type"],
        )
        assert result.exit_code == 1
        assert "Invalid container type" in result.output


class TestContainersDeleteCLI:
    @patch("qualytics.cli.containers.delete_container")
    @patch("qualytics.cli.containers.get_client")
    def test_delete(self, mock_gc, mock_delete, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_delete.return_value = {
            "success": True,
            "message": "Container deleted successfully",
        }
        result = cli_runner.invoke(app, ["containers", "delete", "--id", "42"])
        assert result.exit_code == 0
        assert "deleted successfully" in result.output
        mock_delete.assert_called_once_with(mock_gc.return_value, 42)


class TestContainersValidateCLI:
    @patch("qualytics.cli.containers.validate_container")
    @patch("qualytics.cli.containers.get_client")
    def test_validate_success(self, mock_gc, mock_validate, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_validate.return_value = {"success": True, "message": "Validation passed"}
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "validate",
                "--type",
                "computed_table",
                "--datastore-id",
                "10",
                "--query",
                "SELECT 1",
            ],
        )
        assert result.exit_code == 0
        assert "Validation passed" in result.output

    @patch("qualytics.cli.containers.validate_container")
    @patch("qualytics.cli.containers.get_client")
    def test_validate_failure(self, mock_gc, mock_validate, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_validate.return_value = {"error": "Invalid SQL"}
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "validate",
                "--type",
                "computed_table",
                "--datastore-id",
                "10",
                "--query",
                "INVALID SQL",
            ],
        )
        assert result.exit_code == 0
        assert "Validation failed" in result.output

    @patch("qualytics.cli.containers.get_client")
    def test_validate_rejects_non_computed(self, mock_gc, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app, ["containers", "validate", "--type", "table", "--name", "t1"]
        )
        assert result.exit_code == 1
        assert "must be one of" in result.output

    @patch("qualytics.cli.containers.validate_container")
    @patch("qualytics.cli.containers.get_client")
    def test_validate_custom_timeout(self, mock_gc, mock_validate, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_validate.return_value = {"success": True}
        result = cli_runner.invoke(
            app,
            [
                "containers",
                "validate",
                "--type",
                "computed_table",
                "--datastore-id",
                "10",
                "--query",
                "SELECT 1",
                "--timeout",
                "120",
            ],
        )
        assert result.exit_code == 0
        _, kwargs = mock_validate.call_args
        assert kwargs["timeout"] == 120
