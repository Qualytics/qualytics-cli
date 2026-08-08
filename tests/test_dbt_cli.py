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

    def test_status_draft_forces_all_draft(self, cli_runner, manifest_file):
        res, importer = self._run(cli_runner, manifest_file, ["--status", "Draft"])
        assert res.exit_code == 0
        assert {c["status"] for c in importer.call_args[0][2]} == {"Draft"}

    def test_status_active_forces_all_active_and_warns(self, cli_runner, manifest_file):
        res, importer = self._run(cli_runner, manifest_file, ["--status", "Active"])
        assert res.exit_code == 0
        assert {c["status"] for c in importer.call_args[0][2]} == {"Active"}
        assert "incomplete properties" in res.output

    def test_status_is_case_insensitive(self, cli_runner, manifest_file):
        _, importer = self._run(cli_runner, manifest_file, ["--status", "draft"])
        assert {c["status"] for c in importer.call_args[0][2]} == {"Draft"}

    def test_invalid_status_errors(self, cli_runner, manifest_file):
        res, _ = self._run(cli_runner, manifest_file, ["--status", "Paused"])
        assert res.exit_code == 1
        assert "Active or Draft" in res.output

    def test_status_conflicts_with_preserve_status(self, cli_runner, manifest_file):
        res, _ = self._run(
            cli_runner, manifest_file, ["--status", "Draft", "--preserve-status"]
        )
        assert res.exit_code == 1
        assert "mutually exclusive" in res.output

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

    def test_failures_are_reported_without_failing(self, cli_runner, manifest_file):
        """Matches `checks import`: per-check errors are printed, exit stays 0."""
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
        assert res.exit_code == 0
        assert "not found in datastore 1" in res.output
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


# ══════════════════════════════════════════════════════════════════════════
# Field validation wiring
# ══════════════════════════════════════════════════════════════════════════


class TestFieldValidation:
    def _run(self, cli_runner, manifest_file, catalogue, extra=None):
        """Run import with a stubbed field catalogue for container stg_orders."""
        with (
            patch("qualytics.cli.dbt.get_client", return_value=MagicMock()),
            patch("qualytics.cli.dbt.get_table_ids", return_value={"stg_orders": 7}),
            patch("qualytics.cli.dbt.container_field_names", return_value=catalogue),
            patch(
                "qualytics.cli.dbt.import_checks_to_datastore",
                return_value={"created": 1, "updated": 0, "failed": 0, "errors": []},
            ) as importer,
        ):
            res = cli_runner.invoke(
                app,
                ["dbt", "import", "--manifest", manifest_file, "--datastore-id", "1"]
                + (extra or []),
            )
        return res, importer

    def test_casing_is_corrected_from_the_catalogue(self, cli_runner, manifest_file):
        res, importer = self._run(cli_runner, manifest_file, ["ORDER_ID"])
        assert res.exit_code == 0
        sent = importer.call_args[0][2]
        assert ["ORDER_ID"] in [c["fields"] for c in sent if c["fields"]]
        assert "order_id → ORDER_ID" in res.output

    def test_unknown_field_is_rejected_and_counted(self, cli_runner, manifest_file):
        res, importer = self._run(cli_runner, manifest_file, ["something_else"])
        assert res.exit_code == 0
        assert "not found in container 'stg_orders'" in res.output
        # the notNull check is withheld; the singular test has no fields
        sent = importer.call_args[0][2]
        assert all(not c["fields"] for c in sent)

    def test_rejected_checks_are_not_sent_to_the_importer(
        self, cli_runner, manifest_file
    ):
        _, importer = self._run(cli_runner, manifest_file, ["nope"])
        sent = importer.call_args[0][2]
        assert len(sent) == 1  # only the fieldless singular check survives

    def test_no_validate_fields_skips_lookup_entirely(self, cli_runner, manifest_file):
        with (
            patch("qualytics.cli.dbt.get_client", return_value=MagicMock()),
            patch("qualytics.cli.dbt.get_table_ids") as table_ids,
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
                    "--no-validate-fields",
                ],
            )
        assert res.exit_code == 0
        table_ids.assert_not_called()
        assert len(importer.call_args[0][2]) == 2

    def test_exact_match_sends_fields_unchanged(self, cli_runner, manifest_file):
        res, importer = self._run(cli_runner, manifest_file, ["order_id"])
        assert res.exit_code == 0
        assert "Corrected" not in res.output
        assert ["order_id"] in [
            c["fields"] for c in importer.call_args[0][2] if c["fields"]
        ]


# ══════════════════════════════════════════════════════════════════════════
# --emit-yaml must stay inside the directory the caller chose
# ══════════════════════════════════════════════════════════════════════════


class TestEmitYamlContainment:
    def _manifest_with_alias(self, tmp_path, alias):
        model = "model.jaffle.stg_orders"
        manifest = {
            "nodes": {
                model: {
                    "resource_type": "model",
                    "name": "stg_orders",
                    "alias": alias,
                },
                "test.jaffle.not_null_stg_orders_order_id.abc": {
                    "resource_type": "test",
                    "name": "nn",
                    "column_name": "order_id",
                    "attached_node": model,
                    "depends_on": {"nodes": [model]},
                    "test_metadata": {
                        "namespace": None,
                        "name": "not_null",
                        "kwargs": {"column_name": "order_id"},
                    },
                },
            }
        }
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(manifest))
        return str(path)

    def _emit(self, cli_runner, manifest_file, out_dir):
        with (
            patch("qualytics.cli.dbt.get_client", return_value=MagicMock()),
            patch(
                "qualytics.cli.dbt.import_checks_to_datastore",
                return_value={"created": 1, "updated": 0, "failed": 0, "errors": []},
            ),
        ):
            return cli_runner.invoke(
                app,
                [
                    "dbt",
                    "import",
                    "--manifest",
                    manifest_file,
                    "--datastore-id",
                    "1",
                    "--emit-yaml",
                    str(out_dir),
                    "--no-validate-fields",
                ],
            )

    def _written(self, out_dir):
        return [os.path.join(r, n) for r, _d, ns in os.walk(out_dir) for n in ns]

    def test_traversal_alias_stays_inside_output_dir(self, cli_runner, tmp_path):
        """A manifest is often someone else's file; its alias is untrusted."""
        outside = tmp_path / "outside"
        outside.mkdir()
        out_dir = tmp_path / "checks"
        mf = self._manifest_with_alias(tmp_path, "../outside/pwned")

        res = self._emit(cli_runner, mf, out_dir)
        assert res.exit_code == 0
        assert not self._written(outside), "wrote outside the chosen directory"
        assert len(self._written(out_dir)) == 1

    def test_absolute_alias_stays_inside_output_dir(self, cli_runner, tmp_path):
        outside = tmp_path / "abs"
        outside.mkdir()
        out_dir = tmp_path / "checks"
        mf = self._manifest_with_alias(tmp_path, f"{outside}/pwned")

        res = self._emit(cli_runner, mf, out_dir)
        assert res.exit_code == 0
        assert not self._written(outside)
        assert len(self._written(out_dir)) == 1

    def test_normal_alias_still_groups_by_container(self, cli_runner, tmp_path):
        out_dir = tmp_path / "checks"
        mf = self._manifest_with_alias(tmp_path, "stg_orders")
        res = self._emit(cli_runner, mf, out_dir)
        assert res.exit_code == 0
        written = self._written(out_dir)
        assert len(written) == 1
        assert os.path.basename(os.path.dirname(written[0])) == "stg_orders"
