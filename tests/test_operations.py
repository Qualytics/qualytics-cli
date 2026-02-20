"""Tests for operations API layer, service layer, and CLI commands."""

from unittest.mock import MagicMock, patch

from qualytics.api.operations import (
    run_operation,
    get_operation,
    list_operations,
    list_all_operations,
    abort_operation,
)
from qualytics.qualytics import app


# ── helpers ──────────────────────────────────────────────────────────────


def _mock_client():
    client = MagicMock()
    return client


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    return resp


# ═══════════════════════════════════════════════════════════════════════
# API Layer Tests
# ═══════════════════════════════════════════════════════════════════════


class TestRunOperation:
    def test_posts_payload_to_operations_run(self):
        client = _mock_client()
        client.post.return_value = _mock_response(
            {"id": 1, "type": "catalog", "result": "running"}
        )
        payload = {"type": "catalog", "datastore_id": 42}
        result = run_operation(client, payload)
        client.post.assert_called_once_with("operations/run", json=payload)
        assert result["id"] == 1

    def test_returns_full_response(self):
        client = _mock_client()
        data = {"id": 5, "type": "scan", "result": "running", "end_time": None}
        client.post.return_value = _mock_response(data)
        result = run_operation(client, {"type": "scan", "datastore_id": 1})
        assert result == data


class TestGetOperation:
    def test_gets_operation_by_id(self):
        client = _mock_client()
        data = {
            "id": 10,
            "type": "profile",
            "result": "success",
            "end_time": "2025-01-01T00:00:00",
        }
        client.get.return_value = _mock_response(data)
        result = get_operation(client, 10)
        client.get.assert_called_once_with("operations/10")
        assert result["result"] == "success"


class TestListOperations:
    def test_basic_list(self):
        client = _mock_client()
        data = {"items": [{"id": 1}], "total": 1, "page": 1, "size": 100}
        client.get.return_value = _mock_response(data)
        result = list_operations(client)
        client.get.assert_called_once_with(
            "operations", params={"page": 1, "size": 100}
        )
        assert result["total"] == 1

    def test_with_filters(self):
        client = _mock_client()
        data = {"items": [], "total": 0, "page": 1, "size": 50}
        client.get.return_value = _mock_response(data)
        list_operations(
            client,
            datastore=[42],
            operation_type="scan",
            result=["success", "failure"],
            finished=True,
            start_date="2025-01-01",
            end_date="2025-12-31",
            sort_created="desc",
            page=1,
            size=50,
        )
        args = client.get.call_args
        params = args.kwargs["params"]
        assert params["datastore"] == [42]
        assert params["operation_type"] == "scan"
        assert params["result"] == ["success", "failure"]
        assert params["finished"] is True
        assert params["start_date"] == "2025-01-01"
        assert params["sort_created"] == "desc"

    def test_omits_none_filters(self):
        client = _mock_client()
        data = {"items": [], "total": 0, "page": 1, "size": 100}
        client.get.return_value = _mock_response(data)
        list_operations(client, datastore=None, operation_type=None)
        params = client.get.call_args.kwargs["params"]
        assert "datastore" not in params
        assert "operation_type" not in params


class TestListAllOperations:
    def test_single_page(self):
        client = _mock_client()
        data = {"items": [{"id": 1}, {"id": 2}], "total": 2, "page": 1, "size": 100}
        client.get.return_value = _mock_response(data)
        result = list_all_operations(client)
        assert len(result) == 2

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
        client.get.side_effect = [_mock_response(page1), _mock_response(page2)]
        result = list_all_operations(client)
        assert len(result) == 150

    def test_empty(self):
        client = _mock_client()
        data = {"items": [], "total": 0, "page": 1, "size": 100}
        client.get.return_value = _mock_response(data)
        result = list_all_operations(client)
        assert result == []


class TestAbortOperation:
    def test_puts_to_abort_endpoint(self):
        client = _mock_client()
        data = {"id": 7, "result": "aborted", "end_time": "2025-01-01T00:00:00"}
        client.put.return_value = _mock_response(data)
        result = abort_operation(client, 7)
        client.put.assert_called_once_with("operations/abort/7")
        assert result["result"] == "aborted"


# ═══════════════════════════════════════════════════════════════════════
# Service Layer Tests
# ═══════════════════════════════════════════════════════════════════════


class TestWaitForOperation:
    @patch("qualytics.services.operations.get_operation")
    @patch("qualytics.services.operations.time")
    def test_returns_when_end_time_set(self, mock_time, mock_get_op):
        mock_time.monotonic.return_value = 0
        mock_time.sleep = MagicMock()
        finished = {"id": 1, "end_time": "2025-01-01T00:00:00", "result": "success"}
        mock_get_op.return_value = finished

        from qualytics.services.operations import wait_for_operation

        client = _mock_client()
        result = wait_for_operation(client, 1, poll_interval=1, timeout=60)
        assert result["result"] == "success"

    @patch("qualytics.services.operations.get_operation")
    @patch("qualytics.services.operations.time")
    def test_returns_none_on_timeout(self, mock_time, mock_get_op):
        # monotonic() is called: start_time, then inside loop: elapsed check, then after get: status check, then sleep
        # We need enough calls: start=0, loop-elapsed=1801 (exceeds timeout)
        mock_time.monotonic.side_effect = [0, 1801]
        mock_time.sleep = MagicMock()
        mock_get_op.return_value = {"id": 1, "end_time": None, "result": "running"}

        from qualytics.services.operations import wait_for_operation

        client = _mock_client()
        result = wait_for_operation(client, 1, poll_interval=1, timeout=1800)
        assert result is None

    @patch("qualytics.services.operations.get_operation")
    @patch("qualytics.services.operations.time")
    def test_polls_until_complete(self, mock_time, mock_get_op):
        mock_time.monotonic.side_effect = [0, 0, 10, 10, 20, 20]
        mock_time.sleep = MagicMock()
        running = {"id": 1, "end_time": None, "result": "running"}
        finished = {
            "id": 1,
            "end_time": "2025-01-01",
            "result": "success",
            "status": {},
        }
        mock_get_op.side_effect = [running, finished]

        from qualytics.services.operations import wait_for_operation

        client = _mock_client()
        result = wait_for_operation(client, 1, poll_interval=5, timeout=60)
        assert result["result"] == "success"
        assert mock_get_op.call_count == 2


class TestRunForDatastores:
    @patch("qualytics.services.operations.run_operation")
    @patch("qualytics.services.operations.wait_for_operation")
    def test_catalog_foreground(self, mock_wait, mock_run):
        mock_run.return_value = {"id": 100}
        mock_wait.return_value = {"result": "success", "message": None}

        from qualytics.services.operations import run_catalog

        client = _mock_client()
        run_catalog(
            client, [42], ["table"], False, False, False, poll_interval=1, timeout=10
        )
        mock_run.assert_called_once()
        mock_wait.assert_called_once()

    @patch("qualytics.services.operations.run_operation")
    @patch("qualytics.services.operations.wait_for_operation")
    def test_catalog_background_skips_polling(self, mock_wait, mock_run):
        mock_run.return_value = {"id": 100}

        from qualytics.services.operations import run_catalog

        client = _mock_client()
        run_catalog(client, [42], None, False, False, True)
        mock_run.assert_called_once()
        mock_wait.assert_not_called()

    @patch("qualytics.services.operations.run_operation")
    @patch("qualytics.services.operations.wait_for_operation")
    def test_multiple_datastores(self, mock_wait, mock_run):
        mock_run.side_effect = [{"id": 1}, {"id": 2}]
        mock_wait.side_effect = [
            {"result": "success", "message": None},
            {"result": "success", "message": None},
        ]

        from qualytics.services.operations import run_catalog

        client = _mock_client()
        run_catalog(
            client, [10, 20], None, False, False, False, poll_interval=1, timeout=10
        )
        assert mock_run.call_count == 2
        assert mock_wait.call_count == 2

    @patch("qualytics.services.operations.run_operation")
    @patch("qualytics.services.operations.wait_for_operation")
    def test_profile_builds_correct_payload(self, mock_wait, mock_run):
        mock_run.return_value = {"id": 200}
        mock_wait.return_value = {"result": "success", "message": None}

        from qualytics.services.operations import run_profile

        client = _mock_client()
        run_profile(
            client,
            [42],
            ["orders"],
            None,
            3,
            True,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
            poll_interval=1,
            timeout=10,
        )
        payload = mock_run.call_args.args[1]
        assert payload["type"] == "profile"
        assert payload["datastore_id"] == 42
        assert payload["container_names"] == ["orders"]
        assert payload["inference_threshold"] == 3

    @patch("qualytics.services.operations.run_operation")
    @patch("qualytics.services.operations.wait_for_operation")
    def test_scan_builds_correct_payload(self, mock_wait, mock_run):
        mock_run.return_value = {"id": 300}
        mock_wait.return_value = {"result": "success", "message": None}

        from qualytics.services.operations import run_scan

        client = _mock_client()
        run_scan(
            client,
            [42],
            None,
            ["prod"],
            True,
            "append",
            None,
            100,
            None,
            None,
            False,
            poll_interval=1,
            timeout=10,
        )
        payload = mock_run.call_args.args[1]
        assert payload["type"] == "scan"
        assert payload["incremental"] is True
        assert payload["remediation"] == "append"
        assert payload["enrichment_source_record_limit"] == 100

    @patch("qualytics.services.operations.run_operation")
    @patch("qualytics.services.operations.wait_for_operation")
    def test_materialize_builds_correct_payload(self, mock_wait, mock_run):
        mock_run.return_value = {"id": 400}
        mock_wait.return_value = {"result": "success", "message": None}

        from qualytics.services.operations import run_materialize

        client = _mock_client()
        run_materialize(
            client, [42], ["ct_table"], None, 1000, False, poll_interval=1, timeout=10
        )
        payload = mock_run.call_args.args[1]
        assert payload["type"] == "materialize"
        assert payload["container_names"] == ["ct_table"]
        assert payload["max_records_per_partition"] == 1000

    @patch("qualytics.services.operations.run_operation")
    @patch("qualytics.services.operations.wait_for_operation")
    def test_export_builds_correct_payload(self, mock_wait, mock_run):
        mock_run.return_value = {"id": 500}
        mock_wait.return_value = {"result": "success", "message": None}

        from qualytics.services.operations import run_export

        client = _mock_client()
        run_export(
            client,
            [42],
            "anomalies",
            [1, 2],
            None,
            False,
            False,
            poll_interval=1,
            timeout=10,
        )
        payload = mock_run.call_args.args[1]
        assert payload["type"] == "export"
        assert payload["asset_type"] == "anomalies"
        assert payload["container_ids"] == [1, 2]
        assert payload["include_deleted"] is False


# ═══════════════════════════════════════════════════════════════════════
# CLI Command Tests
# ═══════════════════════════════════════════════════════════════════════


class TestOperationsCatalogCLI:
    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_catalog")
    def test_basic_catalog(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "catalog",
                "--datastore-id",
                "42",
            ],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args.args[1] == [42]  # datastore_ids
        assert args.args[4] is False  # recreate

    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_catalog")
    def test_catalog_with_all_flags(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "catalog",
                "--datastore-id",
                "1,2,3",
                "--include",
                "table,view",
                "--prune",
                "--recreate",
                "--background",
                "--poll-interval",
                "5",
                "--timeout",
                "600",
            ],
        )
        assert result.exit_code == 0
        args = mock_run.call_args
        assert args.args[1] == [1, 2, 3]
        assert args.args[2] == ["table", "view"]  # include
        assert args.args[3] is True  # prune
        assert args.args[4] is True  # recreate
        assert args.args[5] is True  # background


class TestOperationsProfileCLI:
    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_profile")
    def test_basic_profile(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "profile",
                "--datastore-id",
                "42",
            ],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_profile")
    def test_profile_with_kebab_case_flags(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "profile",
                "--datastore-id",
                "42",
                "--container-names",
                "orders,customers",
                "--container-tags",
                "production",
                "--inference-threshold",
                "3",
                "--infer-as-draft",
                "--max-records-analyzed-per-partition",
                "1000",
                "--max-count-testing-sample",
                "50000",
                "--background",
            ],
        )
        assert result.exit_code == 0
        kwargs = mock_run.call_args.kwargs
        assert kwargs["container_names"] == ["orders", "customers"]
        assert kwargs["container_tags"] == ["production"]
        assert kwargs["inference_threshold"] == 3
        assert kwargs["max_records_analyzed_per_partition"] == 1000

    @patch("qualytics.cli.operations.get_client")
    def test_rejects_invalid_max_records(self, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "profile",
                "--datastore-id",
                "42",
                "--max-records-analyzed-per-partition",
                "-5",
            ],
        )
        assert result.exit_code == 1


class TestOperationsScanCLI:
    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_scan")
    def test_basic_scan(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "scan",
                "--datastore-id",
                "42",
            ],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_scan")
    def test_scan_with_kebab_case_flags(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "scan",
                "--datastore-id",
                "42",
                "--container-names",
                "orders",
                "--incremental",
                "--remediation",
                "append",
                "--enrichment-source-record-limit",
                "500",
            ],
        )
        assert result.exit_code == 0
        kwargs = mock_run.call_args.kwargs
        assert kwargs["remediation"] == "append"
        assert kwargs["enrichment_source_record_limit"] == 500

    @patch("qualytics.cli.operations.get_client")
    def test_rejects_invalid_remediation(self, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "scan",
                "--datastore-id",
                "42",
                "--remediation",
                "invalid",
            ],
        )
        assert result.exit_code == 1

    @patch("qualytics.cli.operations.get_client")
    def test_rejects_invalid_enrichment_limit(self, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "scan",
                "--datastore-id",
                "42",
                "--enrichment-source-record-limit",
                "0",
            ],
        )
        assert result.exit_code == 1


class TestOperationsMaterializeCLI:
    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_materialize")
    def test_basic_materialize(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "materialize",
                "--datastore-id",
                "42",
            ],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_materialize")
    def test_materialize_with_flags(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "materialize",
                "--datastore-id",
                "42",
                "--container-names",
                "ct_orders",
                "--max-records-per-partition",
                "5000",
                "--background",
            ],
        )
        assert result.exit_code == 0


class TestOperationsExportCLI:
    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_export")
    def test_basic_export(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "export",
                "--datastore-id",
                "42",
                "--asset-type",
                "anomalies",
            ],
        )
        assert result.exit_code == 0
        mock_run.assert_called_once()

    @patch("qualytics.cli.operations.get_client")
    def test_rejects_invalid_asset_type(self, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "export",
                "--datastore-id",
                "42",
                "--asset-type",
                "invalid",
            ],
        )
        assert result.exit_code == 1

    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.run_export")
    def test_export_with_all_flags(self, mock_run, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "export",
                "--datastore-id",
                "42",
                "--asset-type",
                "checks",
                "--container-ids",
                "1,2,3",
                "--container-tags",
                "prod",
                "--include-deleted",
                "--background",
            ],
        )
        assert result.exit_code == 0


class TestOperationsGetCLI:
    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.get_operation")
    def test_get_yaml(self, mock_get_op, mock_get_client, cli_runner):
        mock_client = _mock_client()
        mock_get_client.return_value = mock_client
        mock_get_op.return_value = {"id": 10, "type": "scan", "result": "success"}
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "get",
                "--id",
                "10",
            ],
        )
        assert result.exit_code == 0
        mock_get_op.assert_called_once_with(mock_client, 10)

    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.get_operation")
    def test_get_json(self, mock_get_op, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        mock_get_op.return_value = {"id": 10, "type": "scan"}
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "get",
                "--id",
                "10",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0


class TestOperationsListCLI:
    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.list_all_operations")
    def test_list_all(self, mock_list, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        mock_list.return_value = [{"id": 1}, {"id": 2}]
        result = cli_runner.invoke(app, ["operations", "list"])
        assert result.exit_code == 0
        assert "2 operations" in result.output

    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.list_all_operations")
    def test_list_with_filters(self, mock_list, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        mock_list.return_value = []
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "list",
                "--datastore-id",
                "42",
                "--type",
                "scan",
                "--status",
                "running,success",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        kwargs = mock_list.call_args.kwargs
        assert kwargs["datastore"] == [42]
        assert kwargs["operation_type"] == "scan"
        assert kwargs["result"] == ["running", "success"]


class TestOperationsAbortCLI:
    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.abort_operation")
    def test_abort_running(self, mock_abort, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        mock_abort.return_value = {"id": 7, "result": "aborted"}
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "abort",
                "--id",
                "7",
            ],
        )
        assert result.exit_code == 0
        assert "aborted" in result.output.lower()

    @patch("qualytics.cli.operations.get_client")
    @patch("qualytics.cli.operations.abort_operation")
    def test_abort_already_finished(self, mock_abort, mock_get_client, cli_runner):
        mock_get_client.return_value = _mock_client()
        mock_abort.return_value = {"id": 7, "result": "success"}
        result = cli_runner.invoke(
            app,
            [
                "operations",
                "abort",
                "--id",
                "7",
            ],
        )
        assert result.exit_code == 0
        assert "already finished" in result.output.lower()
