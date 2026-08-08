"""Tests for the `qualytics dbt` command group."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
import yaml

from qualytics.qualytics import app


# ── Fixtures ──────────────────────────────────────────────────────────────


def _manifest_dict():
    model = "model.jaffle.stg_orders"
    return {
        "nodes": {
            model: {
                "resource_type": "model",
                "name": "stg_orders",
                "alias": "stg_orders",
                "schema": "analytics",
            },
            "test.jaffle.not_null_stg_orders_order_id.abc": {
                "resource_type": "test",
                "name": "not_null_stg_orders_order_id",
                "column_name": "order_id",
                "attached_node": model,
                "depends_on": {"nodes": [model]},
                "test_metadata": {
                    "namespace": None,
                    "name": "not_null",
                    "kwargs": {"column_name": "order_id"},
                },
            },
            "test.jaffle.assert_totals.def": {
                "resource_type": "test",
                "name": "assert_totals",
                "attached_node": model,
                "depends_on": {"nodes": [model]},
                "compiled_code": "select 1",
            },
        }
    }


@pytest.fixture
def manifest_file(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest_dict()))
    return str(path)


# ══════════════════════════════════════════════════════════════════════════
# plan — offline, no auth
# ══════════════════════════════════════════════════════════════════════════


class TestDbtPlan:
    def test_reports_coverage(self, cli_runner, manifest_file):
        result = cli_runner.invoke(app, ["dbt", "plan", "--manifest", manifest_file])
        assert result.exit_code == 0
        assert "2" in result.output
        assert "direct" in result.output

    def test_does_not_require_auth(self, cli_runner, manifest_file):
        """plan must never construct a client."""
        with patch("qualytics.cli.dbt.get_client") as get_client:
            result = cli_runner.invoke(
                app, ["dbt", "plan", "--manifest", manifest_file]
            )
        assert result.exit_code == 0
        get_client.assert_not_called()

    def test_show_checks_lists_rules(self, cli_runner, manifest_file):
        result = cli_runner.invoke(
            app, ["dbt", "plan", "--manifest", manifest_file, "--show-checks"]
        )
        assert result.exit_code == 0
        assert "notNull" in result.output

    def test_missing_manifest_errors(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app, ["dbt", "plan", "--manifest", str(tmp_path / "nope.json")]
        )
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_invalid_json_errors(self, cli_runner, tmp_path):
        bad = tmp_path / "manifest.json"
        bad.write_text("{not json")
        result = cli_runner.invoke(app, ["dbt", "plan", "--manifest", str(bad)])
        assert result.exit_code == 1
        assert "json" in result.output.lower()

    def test_json_without_nodes_errors(self, cli_runner, tmp_path):
        bad = tmp_path / "manifest.json"
        bad.write_text('{"metadata": {}}')
        result = cli_runner.invoke(app, ["dbt", "plan", "--manifest", str(bad)])
        assert result.exit_code == 1
        assert "nodes" in result.output.lower()

    def test_manifest_with_no_tests_exits_cleanly(self, cli_runner, tmp_path):
        empty = tmp_path / "manifest.json"
        empty.write_text(json.dumps({"nodes": {}}))
        result = cli_runner.invoke(app, ["dbt", "plan", "--manifest", str(empty)])
        assert result.exit_code == 0
        assert "nothing to migrate" in result.output.lower()

    def test_bad_container_map_errors(self, cli_runner, manifest_file):
        result = cli_runner.invoke(
            app,
            ["dbt", "plan", "--manifest", manifest_file, "--container-map", "novalue"],
        )
        assert result.exit_code == 1
        assert "model=container" in result.output


# ══════════════════════════════════════════════════════════════════════════
# import — conversion + upsert
# ══════════════════════════════════════════════════════════════════════════


class TestDbtImport:
    def _run(self, cli_runner, manifest_file, extra=None, result_payload=None):
        payload = result_payload or {
            "created": 2,
            "updated": 0,
            "failed": 0,
            "errors": [],
        }
        with (
            patch("qualytics.cli.dbt.get_client", return_value=MagicMock()),
            patch(
                "qualytics.cli.dbt.import_checks_to_datastore", return_value=payload
            ) as importer,
        ):
            res = cli_runner.invoke(
                app,
                ["dbt", "import", "--manifest", manifest_file, "--datastore-id", "1"]
                + (extra or []),
            )
        return res, importer

    def test_converts_and_imports(self, cli_runner, manifest_file):
        res, importer = self._run(cli_runner, manifest_file)
        assert res.exit_code == 0
        importer.assert_called_once()
        checks = importer.call_args[0][2]
        assert len(checks) == 2
        assert {c["rule_type"] for c in checks} == {"notNull", "satisfiesExpression"}

    def test_passes_dry_run_through(self, cli_runner, manifest_file):
        res, importer = self._run(cli_runner, manifest_file, ["--dry-run"])
        assert res.exit_code == 0
        assert importer.call_args.kwargs["dry_run"] is True
        assert "DRY RUN" in res.output

    def test_uids_are_dbt_derived(self, cli_runner, manifest_file):
        _, importer = self._run(cli_runner, manifest_file)
        for check in importer.call_args[0][2]:
            assert check["additional_metadata"]["_qualytics_check_uid"].startswith(
                "dbt__"
            )

    def test_preserve_status_omits_status(self, cli_runner, manifest_file):
        _, importer = self._run(cli_runner, manifest_file, ["--preserve-status"])
        for check in importer.call_args[0][2]:
            assert "status" not in check

    def test_default_includes_status(self, cli_runner, manifest_file):
        _, importer = self._run(cli_runner, manifest_file)
        statuses = {c["status"] for c in importer.call_args[0][2]}
        assert statuses == {"Active", "Draft"}

    def test_container_map_applied(self, cli_runner, manifest_file):
        _, importer = self._run(
            cli_runner, manifest_file, ["--container-map", "stg_orders=ORDERS"]
        )
        assert {c["container"] for c in importer.call_args[0][2]} == {"ORDERS"}

    def test_multiple_datastores(self, cli_runner, manifest_file):
        with (
            patch("qualytics.cli.dbt.get_client", return_value=MagicMock()),
            patch(
                "qualytics.cli.dbt.import_checks_to_datastore",
                return_value={"created": 2, "updated": 0, "failed": 0, "errors": []},
            ) as importer,
        ):
            res = cli_runner.invoke(
                app,
                [
                    "dbt",
                    "import",
                    "--manifest",
                    manifest_file,
                    "--datastore-id",
                    "1",
                    "--datastore-id",
                    "2",
                ],
            )
        assert res.exit_code == 0
        assert importer.call_count == 2

    def test_failures_exit_nonzero_with_guidance(self, cli_runner, manifest_file):
        res, _ = self._run(
            cli_runner,
            manifest_file,
            result_payload={
                "created": 0,
                "updated": 0,
                "failed": 2,
                "errors": ["Container 'stg_orders' not found in datastore 1"],
            },
        )
        assert res.exit_code == 1
        assert "catalogued" in res.output

    def test_emit_yaml_writes_files(self, cli_runner, manifest_file, tmp_path):
        out = tmp_path / "checks"
        res, _ = self._run(cli_runner, manifest_file, ["--emit-yaml", str(out)])
        assert res.exit_code == 0

        files = []
        for root, _dirs, names in os.walk(out):
            files += [os.path.join(root, n) for n in names]
        assert len(files) == 2

        for path in files:
            with open(path) as f:
                check = yaml.safe_load(f)
            assert check["additional_metadata"]["_qualytics_check_uid"].startswith(
                "dbt__"
            )

    def test_emit_yaml_filenames_are_unique_per_test(
        self, cli_runner, manifest_file, tmp_path
    ):
        """Two checks on one container must not overwrite each other's file."""
        out = tmp_path / "checks"
        self._run(cli_runner, manifest_file, ["--emit-yaml", str(out)])
        names = [n for _r, _d, ns in os.walk(out) for n in ns]
        assert len(names) == len(set(names)) == 2
