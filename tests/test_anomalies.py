"""Tests for anomalies — API and CLI."""

from unittest.mock import MagicMock, patch

from qualytics.api.anomalies import (
    list_anomalies,
    list_all_anomalies,
    get_anomaly,
    update_anomaly,
    bulk_update_anomalies,
    delete_anomaly,
    bulk_delete_anomalies,
)
from qualytics.qualytics import app


# ── Shared fixtures ──────────────────────────────────────────────────────


def _mock_client():
    return MagicMock()


# ══════════════════════════════════════════════════════════════════════════
# 1. API LAYER
# ══════════════════════════════════════════════════════════════════════════


class TestListAnomalies:
    def test_basic_call(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}],
            "total": 1,
            "page": 1,
            "size": 100,
        }
        result = list_anomalies(client, datastore=42)
        client.get.assert_called_once_with(
            "anomalies",
            params={"page": 1, "size": 100, "datastore": 42},
        )
        assert result["items"] == [{"id": 1}]

    def test_with_filters(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_anomalies(
            client,
            datastore=42,
            container=10,
            quality_check=5,
            status="Active",
            anomaly_type="record",
            tag=["prod"],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        params = client.get.call_args.kwargs["params"]
        assert params["datastore"] == 42
        assert params["container"] == 10
        assert params["quality_check"] == 5
        assert params["status"] == "Active"
        assert params["anomaly_type"] == "record"
        assert params["tag"] == ["prod"]
        assert params["start_date"] == "2024-01-01"
        assert params["end_date"] == "2024-12-31"

    def test_none_filters_excluded(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"items": [], "total": 0}
        list_anomalies(client)
        params = client.get.call_args.kwargs["params"]
        assert "datastore" not in params
        assert "container" not in params
        assert "status" not in params
        assert "tag" not in params


class TestListAllAnomalies:
    def test_single_page(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [{"id": 1}, {"id": 2}],
            "total": 2,
            "page": 1,
            "size": 100,
        }
        result = list_all_anomalies(client, datastore=42)
        assert len(result) == 2
        assert client.get.call_count == 1

    def test_multi_page(self):
        client = _mock_client()
        page1 = {
            "items": [{"id": i} for i in range(100)],
            "total": 150,
            "page": 1,
            "size": 100,
        }
        page2 = {
            "items": [{"id": i} for i in range(100, 150)],
            "total": 150,
            "page": 2,
            "size": 100,
        }
        client.get.return_value.json.side_effect = [page1, page2]
        result = list_all_anomalies(client, datastore=42)
        assert len(result) == 150
        assert client.get.call_count == 2

    def test_empty(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {
            "items": [],
            "total": 0,
            "page": 1,
            "size": 100,
        }
        result = list_all_anomalies(client, datastore=42)
        assert result == []


class TestGetAnomaly:
    def test_calls_correct_endpoint(self):
        client = _mock_client()
        client.get.return_value.json.return_value = {"id": 99, "status": "Active"}
        result = get_anomaly(client, 99)
        client.get.assert_called_once_with("anomalies/99")
        assert result["id"] == 99


class TestUpdateAnomaly:
    def test_puts_payload(self):
        client = _mock_client()
        client.put.return_value.json.return_value = {"id": 42, "status": "Acknowledged"}
        payload = {"status": "Acknowledged"}
        result = update_anomaly(client, 42, payload)
        client.put.assert_called_once_with("anomalies/42", json=payload)
        assert result["status"] == "Acknowledged"


class TestBulkUpdateAnomalies:
    def test_patches_items(self):
        client = _mock_client()
        items = [
            {"id": 1, "status": "Acknowledged"},
            {"id": 2, "status": "Acknowledged"},
        ]
        bulk_update_anomalies(client, items)
        client.patch.assert_called_once_with("anomalies", json=items)


class TestDeleteAnomaly:
    def test_archive_default(self):
        client = _mock_client()
        delete_anomaly(client, 42)
        client.delete.assert_called_once_with(
            "anomalies/42",
            params={"archive": "true", "status": "Resolved"},
        )

    def test_hard_delete(self):
        client = _mock_client()
        delete_anomaly(client, 42, archive=False)
        params = client.delete.call_args.kwargs["params"]
        assert params["archive"] == "false"

    def test_custom_archive_status(self):
        client = _mock_client()
        delete_anomaly(client, 42, status="Invalid")
        params = client.delete.call_args.kwargs["params"]
        assert params["status"] == "Invalid"


class TestBulkDeleteAnomalies:
    def test_sends_items(self):
        client = _mock_client()
        items = [{"id": 1, "archive": True}, {"id": 2, "archive": False}]
        bulk_delete_anomalies(client, items)
        client.delete.assert_called_once_with("anomalies", json=items)


# ══════════════════════════════════════════════════════════════════════════
# 2. CLI COMMAND TESTS
# ══════════════════════════════════════════════════════════════════════════


class TestAnomaliesGetCLI:
    @patch("qualytics.cli.anomalies.get_anomaly")
    @patch("qualytics.cli.anomalies.get_client")
    def test_get_outputs_anomaly(self, mock_gc, mock_get, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {"id": 42, "status": "Active"}
        result = cli_runner.invoke(app, ["anomalies", "get", "--id", "42"])
        assert result.exit_code == 0
        mock_get.assert_called_once()

    @patch("qualytics.cli.anomalies.get_anomaly")
    @patch("qualytics.cli.anomalies.get_client")
    def test_get_json_format(self, mock_gc, mock_get, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_get.return_value = {"id": 42, "status": "Active"}
        result = cli_runner.invoke(
            app, ["anomalies", "get", "--id", "42", "--format", "json"]
        )
        assert result.exit_code == 0


class TestAnomaliesListCLI:
    @patch("qualytics.cli.anomalies.list_all_anomalies")
    @patch("qualytics.cli.anomalies.get_client")
    def test_list_basic(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = [{"id": 1}, {"id": 2}]
        result = cli_runner.invoke(app, ["anomalies", "list", "--datastore-id", "42"])
        assert result.exit_code == 0
        assert "Found 2 anomalies" in result.output

    @patch("qualytics.cli.anomalies.list_all_anomalies")
    @patch("qualytics.cli.anomalies.get_client")
    def test_list_with_filters(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = []
        result = cli_runner.invoke(
            app,
            [
                "anomalies",
                "list",
                "--datastore-id",
                "42",
                "--container",
                "10",
                "--check-id",
                "5",
                "--status",
                "Active",
                "--type",
                "record",
            ],
        )
        assert result.exit_code == 0
        mock_list.assert_called_once()
        _, kwargs = mock_list.call_args
        assert kwargs["datastore"] == 42
        assert kwargs["container"] == 10
        assert kwargs["quality_check"] == 5
        assert kwargs["anomaly_type"] == "record"

    @patch("qualytics.cli.anomalies.list_all_anomalies")
    @patch("qualytics.cli.anomalies.get_client")
    def test_list_with_date_range(self, mock_gc, mock_list, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_list.return_value = []
        result = cli_runner.invoke(
            app,
            [
                "anomalies",
                "list",
                "--datastore-id",
                "42",
                "--start-date",
                "2024-01-01",
                "--end-date",
                "2024-12-31",
            ],
        )
        assert result.exit_code == 0
        _, kwargs = mock_list.call_args
        assert kwargs["start_date"] == "2024-01-01"
        assert kwargs["end_date"] == "2024-12-31"


class TestAnomaliesUpdateCLI:
    @patch("qualytics.cli.anomalies.update_anomaly")
    @patch("qualytics.cli.anomalies.get_client")
    def test_update_single(self, mock_gc, mock_update, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_update.return_value = {"id": 42, "status": "Acknowledged"}
        result = cli_runner.invoke(
            app, ["anomalies", "update", "--id", "42", "--status", "Acknowledged"]
        )
        assert result.exit_code == 0
        assert "Acknowledged" in result.output
        mock_update.assert_called_once()

    @patch("qualytics.cli.anomalies.bulk_update_anomalies")
    @patch("qualytics.cli.anomalies.get_client")
    def test_update_bulk(self, mock_gc, mock_bulk, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app, ["anomalies", "update", "--ids", "1,2,3", "--status", "Acknowledged"]
        )
        assert result.exit_code == 0
        assert "3 anomalies" in result.output
        mock_bulk.assert_called_once()
        items = mock_bulk.call_args.args[1]
        assert len(items) == 3
        assert all(item["status"] == "Acknowledged" for item in items)

    def test_update_rejects_archived_status(self, cli_runner):
        with patch("qualytics.cli.anomalies.get_client"):
            result = cli_runner.invoke(
                app, ["anomalies", "update", "--id", "42", "--status", "Resolved"]
            )
        assert result.exit_code == 1

    def test_update_no_id_or_ids(self, cli_runner):
        with patch("qualytics.cli.anomalies.get_client"):
            result = cli_runner.invoke(
                app, ["anomalies", "update", "--status", "Active"]
            )
        assert result.exit_code == 1

    @patch("qualytics.cli.anomalies.update_anomaly")
    @patch("qualytics.cli.anomalies.get_client")
    def test_update_with_description_and_tags(self, mock_gc, mock_update, cli_runner):
        mock_gc.return_value = _mock_client()
        mock_update.return_value = {"id": 42, "status": "Acknowledged"}
        result = cli_runner.invoke(
            app,
            [
                "anomalies",
                "update",
                "--id",
                "42",
                "--status",
                "Acknowledged",
                "--description",
                "Known issue",
                "--tags",
                "reviewed,ci",
            ],
        )
        assert result.exit_code == 0
        payload = mock_update.call_args.args[2]
        assert payload["description"] == "Known issue"
        assert payload["tags"] == ["reviewed", "ci"]


class TestAnomaliesArchiveCLI:
    @patch("qualytics.cli.anomalies.delete_anomaly")
    @patch("qualytics.cli.anomalies.get_client")
    def test_archive_single_default_status(self, mock_gc, mock_del, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(app, ["anomalies", "archive", "--id", "42"])
        assert result.exit_code == 0
        assert "Resolved" in result.output
        mock_del.assert_called_once_with(
            mock_gc.return_value, 42, archive=True, status="Resolved"
        )

    @patch("qualytics.cli.anomalies.delete_anomaly")
    @patch("qualytics.cli.anomalies.get_client")
    def test_archive_custom_status(self, mock_gc, mock_del, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app, ["anomalies", "archive", "--id", "42", "--status", "Invalid"]
        )
        assert result.exit_code == 0
        assert "Invalid" in result.output

    @patch("qualytics.cli.anomalies.bulk_delete_anomalies")
    @patch("qualytics.cli.anomalies.get_client")
    def test_archive_bulk(self, mock_gc, mock_bulk, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            ["anomalies", "archive", "--ids", "1,2,3", "--status", "Duplicate"],
        )
        assert result.exit_code == 0
        assert "3 anomalies" in result.output
        items = mock_bulk.call_args.args[1]
        assert all(item["archive"] is True for item in items)
        assert all(item["status"] == "Duplicate" for item in items)

    def test_archive_rejects_invalid_status(self, cli_runner):
        with patch("qualytics.cli.anomalies.get_client"):
            result = cli_runner.invoke(
                app, ["anomalies", "archive", "--id", "42", "--status", "Active"]
            )
        assert result.exit_code == 1

    def test_archive_no_id_or_ids(self, cli_runner):
        with patch("qualytics.cli.anomalies.get_client"):
            result = cli_runner.invoke(app, ["anomalies", "archive"])
        assert result.exit_code == 1


class TestAnomaliesDeleteCLI:
    @patch("qualytics.cli.anomalies.delete_anomaly")
    @patch("qualytics.cli.anomalies.get_client")
    def test_delete_single(self, mock_gc, mock_del, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(app, ["anomalies", "delete", "--id", "42"])
        assert result.exit_code == 0
        assert "Deleted" in result.output
        mock_del.assert_called_once_with(mock_gc.return_value, 42, archive=False)

    @patch("qualytics.cli.anomalies.bulk_delete_anomalies")
    @patch("qualytics.cli.anomalies.get_client")
    def test_delete_bulk(self, mock_gc, mock_bulk, cli_runner):
        mock_gc.return_value = _mock_client()
        result = cli_runner.invoke(app, ["anomalies", "delete", "--ids", "1,2,3"])
        assert result.exit_code == 0
        assert "3 anomalies" in result.output
        items = mock_bulk.call_args.args[1]
        assert all(item["archive"] is False for item in items)

    def test_delete_no_id_or_ids(self, cli_runner):
        with patch("qualytics.cli.anomalies.get_client"):
            result = cli_runner.invoke(app, ["anomalies", "delete"])
        assert result.exit_code == 1
