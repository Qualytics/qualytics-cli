"""Tests for the `qualytics migrate plan` command."""

import re

import yaml

from qualytics.qualytics import app

GOOD_SHEET = (
    "check_id,kind,rule_type,container,fields,value,expression,comparison,"
    "ref_expression,ref_container,ref_field,query,sources,tags\n"
    "550,,freshness,orders,,36h,,,,,,,,\n"
    "326,,existsIn,orders,customer_id,,,,,customers,id,,,finance\n"
    '770,computed_table,,recon_unpivot,,,,,,,,"SELECT metric, delta FROM x",,\n'
    "771,,equalTo,recon_unpivot,delta,0,,,,,,,,\n"
)

BAD_SHEET = (
    "check_id,rule_type,container,fields\n"
    "100,freshness,orders,\n"  # missing value
    "100,notNull,orders,order_id\n"  # duplicate check_id
)


def _write(tmp_path, content, name="sheet.csv"):
    path = tmp_path / name
    path.write_text(content)
    return str(path)


class TestMigratePlan:
    def test_plan_is_offline(self, cli_runner, tmp_path, monkeypatch):
        """plan must never construct an API client."""
        import qualytics.api.client as client_module

        def _boom(*args, **kwargs):  # pragma: no cover - guard
            raise AssertionError("plan must not build a client")

        monkeypatch.setattr(client_module, "get_client", _boom)
        result = cli_runner.invoke(
            app, ["migrate", "plan", "--sheet", _write(tmp_path, GOOD_SHEET)]
        )
        assert result.exit_code == 0
        assert "3 checks" in result.output
        assert "1 computed containers" in result.output
        assert "Total" in result.output

    def test_plan_reports_issues_but_exits_zero(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app, ["migrate", "plan", "--sheet", _write(tmp_path, BAD_SHEET)]
        )
        assert result.exit_code == 0
        assert "freshness requires column(s): value" in result.output
        assert "duplicate check_id" in result.output

    def test_plan_strict_exits_nonzero_on_errors(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app,
            ["migrate", "plan", "--sheet", _write(tmp_path, BAD_SHEET), "--strict"],
        )
        assert result.exit_code == 1

    def test_plan_strict_passes_clean_sheet(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app,
            ["migrate", "plan", "--sheet", _write(tmp_path, GOOD_SHEET), "--strict"],
        )
        assert result.exit_code == 0

    def test_show_checks_lists_rows(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "plan",
                "--sheet",
                _write(tmp_path, GOOD_SHEET),
                "--show-checks",
            ],
        )
        assert result.exit_code == 0
        assert "550" in result.output
        assert "existsIn" in result.output

    def test_emit_yaml_writes_checks_and_container_specs(self, cli_runner, tmp_path):
        out_dir = tmp_path / "out"
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "plan",
                "--sheet",
                _write(tmp_path, GOOD_SHEET),
                "--emit-yaml",
                str(out_dir),
                "--tag",
                "UAT testing",
            ],
        )
        assert result.exit_code == 0

        check_file = out_dir / "orders" / "sheet__550.yaml"
        assert check_file.exists()
        check = yaml.safe_load(check_file.read_text())
        assert check["rule_type"] == "freshness"
        assert check["properties"] == {"value": 129_600_000}
        assert check["tags"] == ["UAT testing"]
        assert check["additional_metadata"] == {"legacy_check_id": "550"}

        specs = yaml.safe_load((out_dir / "_computed_containers.yaml").read_text())
        assert specs[0]["name"] == "recon_unpivot"
        assert specs[0]["container_type"] == "computed_table"

    def test_missing_sheet_exits_nonzero(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app, ["migrate", "plan", "--sheet", str(tmp_path / "absent.csv")]
        )
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_empty_sheet_exits_zero(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app,
            ["migrate", "plan", "--sheet", _write(tmp_path, "check_id,rule_type\n")],
        )
        assert result.exit_code == 0
        assert "no data rows" in result.output

    def test_invalid_status_flag(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "plan",
                "--sheet",
                _write(tmp_path, GOOD_SHEET),
                "--status",
                "Retired",
            ],
        )
        assert result.exit_code == 1
        assert "must be Active or Draft" in result.output


# ── apply ─────────────────────────────────────────────────────────────────

ROUTED_SHEET = (
    "check_id,kind,rule_type,container,fields,value,datastore,query\n"
    "550,,freshness,orders,,36h,,\n"
    "551,,freshness,invoices,,1d,5,\n"
    "770,computed_table,,recon,,,,SELECT 1\n"
)


class _ApplyHarness:
    """Patches every seam migrate apply touches; records what flowed through."""

    def __init__(self, monkeypatch, tmp_path):
        from unittest.mock import MagicMock

        import qualytics.api.client as client_module
        import qualytics.cli.import_flow as import_flow
        import qualytics.services.containers as containers_service
        import qualytics.services.migrate as migrate_service

        # Default-named side-effect files (results CSV) land in cwd; keep them
        # inside the test sandbox.
        monkeypatch.chdir(tmp_path)

        self.ensure_calls = []
        self.import_calls = []

        monkeypatch.setattr(
            client_module,
            "get_client",
            lambda: MagicMock(base_url="https://x.example.com/api/"),
        )
        monkeypatch.setattr(
            containers_service,
            "get_table_ids",
            lambda client, datastore_id: {"orders": 1, "invoices": 2, "recon": 3},
        )

        def _ensure(client, specs, ds_id, **kw):
            self.ensure_calls.append(
                {"datastore": ds_id, "names": [s.name for s in specs], **kw}
            )
            return {
                "created": len(specs),
                "updated": 0,
                "skipped": 0,
                "failed": self.fail_containers_for == ds_id and 1 or 0,
                "errors": ["boom"] if self.fail_containers_for == ds_id else [],
                "name_to_id": {},
            }

        self.fail_containers_for = None
        monkeypatch.setattr(migrate_service, "ensure_containers", _ensure)

        self.fail_check_sources = []

        def _import(client, checks_by_datastore, **kw):
            self.import_calls.append({"checks": checks_by_datastore, **kw})
            results = {}
            for ds, checks in checks_by_datastore.items():
                results[ds] = {
                    "failures": [
                        {"source": source, "reason": "boom: field not found"}
                        for source in self.fail_check_sources
                        if any(c.get("_source_file") == source for c in checks)
                    ],
                    "outcomes": [
                        {
                            "source": check.get("_source_file", ""),
                            "action": "created",
                            "id": 9000 + index,
                            "container_id": 77,
                            "check": check,
                        }
                        for index, check in enumerate(checks)
                    ],
                }
            return {"total_failed": 0, "results": results}

        monkeypatch.setattr(import_flow, "run_check_import", _import)


class TestMigrateApply:
    def test_routes_rows_by_datastore_override(self, cli_runner, tmp_path, monkeypatch):
        harness = _ApplyHarness(monkeypatch, tmp_path)
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
            ],
        )
        assert result.exit_code == 0, result.output

        assert harness.ensure_calls[0]["datastore"] == 7
        assert harness.ensure_calls[0]["names"] == ["recon"]

        (import_call,) = harness.import_calls
        checks = import_call["checks"]
        assert set(checks) == {7, 5}
        assert [c["additional_metadata"]["legacy_check_id"] for c in checks[7]] == [
            "550"
        ]
        assert [c["additional_metadata"]["legacy_check_id"] for c in checks[5]] == [
            "551"
        ]
        assert checks[7][0]["_source_file"] == "row 2 (550)"
        assert checks[7][0]["status"] == "Draft"
        # The check phase knows which containers this run creates, so a dry
        # run counts their dependent checks as creates rather than failures.
        assert import_call["pending_containers_by_datastore"] == {7: {"recon"}}

    def test_dry_run_flows_through(self, cli_runner, tmp_path, monkeypatch):
        harness = _ApplyHarness(monkeypatch, tmp_path)
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert harness.ensure_calls[0]["dry_run"] is True
        assert harness.import_calls[0]["dry_run"] is True
        assert "DRY RUN" in result.output

    def test_preserve_status_drops_status_key(self, cli_runner, tmp_path, monkeypatch):
        harness = _ApplyHarness(monkeypatch, tmp_path)
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
                "--preserve-status",
            ],
        )
        assert result.exit_code == 0, result.output
        checks = harness.import_calls[0]["checks"]
        assert all("status" not in c for group in checks.values() for c in group)

    def test_container_failure_blocks_check_phase(
        self, cli_runner, tmp_path, monkeypatch
    ):
        harness = _ApplyHarness(monkeypatch, tmp_path)
        harness.fail_containers_for = 7
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "skipping the check phase for datastore 7" in result.output
        checks = harness.import_calls[0]["checks"]
        assert set(checks) == {5}

    def test_skip_containers_flag(self, cli_runner, tmp_path, monkeypatch):
        harness = _ApplyHarness(monkeypatch, tmp_path)
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
                "--skip-containers",
            ],
        )
        assert result.exit_code == 0, result.output
        assert not harness.ensure_calls
        assert harness.import_calls

    def test_requires_datastore_when_rows_lack_override(
        self, cli_runner, tmp_path, monkeypatch
    ):
        _ApplyHarness(monkeypatch, tmp_path)
        result = cli_runner.invoke(
            app, ["migrate", "apply", "--sheet", _write(tmp_path, ROUTED_SHEET)]
        )
        assert result.exit_code == 1
        assert "--datastore-id is required" in result.output

    def test_strict_fails_on_sheet_errors(self, cli_runner, tmp_path, monkeypatch):
        _ApplyHarness(monkeypatch, tmp_path)
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, BAD_SHEET),
                "--datastore-id",
                "7",
                "--strict",
            ],
        )
        assert result.exit_code == 1

    def test_invalid_on_existing(self, cli_runner, tmp_path, monkeypatch):
        _ApplyHarness(monkeypatch, tmp_path)
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
                "--on-existing",
                "replace",
            ],
        )
        assert result.exit_code == 1
        assert "--on-existing must be skip or update" in result.output

    def test_container_name_case_repair(self, cli_runner, tmp_path, monkeypatch):
        harness = _ApplyHarness(monkeypatch, tmp_path)
        sheet = "check_id,rule_type,container,fields\n100,notNull,ORDERS,order_id\n"
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, sheet),
                "--datastore-id",
                "7",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Corrected 1 container name(s)" in result.output
        checks = harness.import_calls[0]["checks"]
        assert checks[7][0]["container"] == "orders"

    def test_results_csv_receipt(self, cli_runner, tmp_path, monkeypatch):
        import csv

        _ApplyHarness(monkeypatch, tmp_path)
        out = tmp_path / "results.csv"
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
                "--results-csv",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "Per-check results written" in result.output

        with open(out, newline="") as f:
            rows = {row["check_id"]: row for row in csv.DictReader(f)}
        assert set(rows) == {"550", "551"}
        row = rows["550"]
        assert row["action"] == "created"
        assert row["qualytics_check_id"] == "9000"
        assert row["datastore_id"] == "7"
        assert row["rule_type"] == "freshness"
        # UI link: API base without the api/ suffix, container from the outcome.
        assert row["url"] == (
            "https://x.example.com/datastores/7/containers/77/checks/9000/overview"
        )

    def test_dry_run_writes_no_results_csv(self, cli_runner, tmp_path, monkeypatch):
        _ApplyHarness(monkeypatch, tmp_path)
        out = tmp_path / "results.csv"
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
                "--dry-run",
                "--results-csv",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert not out.exists()

    def test_force_drop_fields_flag_reaches_container_phase(
        self, cli_runner, tmp_path, monkeypatch
    ):
        harness = _ApplyHarness(monkeypatch, tmp_path)
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
                "--on-existing",
                "update",
                "--force-drop-fields",
            ],
        )
        assert result.exit_code == 0, result.output
        assert harness.ensure_calls[0]["force_drop_fields"] is True
        assert harness.ensure_calls[0]["on_existing"] == "update"

    def test_run_dir_artifacts(self, cli_runner, tmp_path, monkeypatch):
        import csv

        harness = _ApplyHarness(monkeypatch, tmp_path)
        harness.fail_check_sources = ["row 2 (550)"]
        run_dir = tmp_path / "run"
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
                "--run-dir",
                str(run_dir),
            ],
        )
        assert result.exit_code == 0, result.output

        log_text = (run_dir / "run.log").read_text()
        assert "qualytics migrate apply" in log_text
        assert "Ensuring 1 computed container(s)" in log_text  # transcript
        assert re.search(r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", log_text)

        with open(run_dir / "results.csv", newline="") as f:
            rows = list(csv.DictReader(f))
        failed = [r for r in rows if r["action"] == "failed"]
        assert failed and failed[0]["reason"] == "boom: field not found"
        assert failed[0]["check_id"] == "550"

        assert (run_dir / "yaml" / "orders" / "sheet__550.yaml").exists()
        assert "Run artifacts in" in result.output

    def test_dry_run_creates_no_run_dir(self, cli_runner, tmp_path, monkeypatch):
        _ApplyHarness(monkeypatch, tmp_path)
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "apply",
                "--sheet",
                _write(tmp_path, ROUTED_SHEET),
                "--datastore-id",
                "7",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert not (tmp_path / "migrate-runs").exists()


class TestMigrateValidate:
    def _online_patches(self, monkeypatch):
        from unittest.mock import MagicMock

        import qualytics.api.client as client_module
        import qualytics.api.fields as fields_api
        import qualytics.cli.import_flow as import_flow
        import qualytics.services.containers as containers_service
        import qualytics.services.datastores as datastores_service

        monkeypatch.setattr(client_module, "get_client", lambda: MagicMock())
        monkeypatch.setattr(
            containers_service,
            "get_table_ids",
            lambda client, datastore_id: {"orders": 1, "invoices": 2, "REGION": 3},
        )
        monkeypatch.setattr(
            import_flow,
            "field_catalogue",
            lambda client, ds, containers: {"orders": ["order_id", "customer_id"]},
        )
        monkeypatch.setattr(
            fields_api,
            "container_field_names",
            lambda client, cid: ["R_REGIONKEY", "R_NAME"],
        )
        monkeypatch.setattr(
            datastores_service,
            "get_datastore_by_name",
            lambda client, name: {"id": 9} if name == "warehouse" else None,
        )

    def test_validate_passes_and_resolves_refs(self, cli_runner, tmp_path, monkeypatch):
        self._online_patches(monkeypatch)
        sheet = (
            "check_id,rule_type,container,fields,value,ref_container,ref_field,"
            "ref_datastore\n"
            "550,freshness,orders,,36h,,,\n"
            "326,existsIn,orders,customer_id,,REGION,R_REGIONKEY,warehouse\n"
        )
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--sheet",
                _write(tmp_path, sheet),
                "--datastore-id",
                "7",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "all references resolve" in result.output
        assert "Validation passed" in result.output

    def test_validate_fails_on_unknown_container_and_ref_field(
        self, cli_runner, tmp_path, monkeypatch
    ):
        self._online_patches(monkeypatch)
        sheet = (
            "check_id,rule_type,container,fields,value,ref_container,ref_field,"
            "ref_datastore\n"
            "1,freshness,ghost_table,,1d,,,\n"
            "2,existsIn,orders,customer_id,,REGION,R_GHOST,warehouse\n"
            "3,notNull,orders,not_a_field,,,,\n"
        )
        result = cli_runner.invoke(
            app,
            [
                "migrate",
                "validate",
                "--sheet",
                _write(tmp_path, sheet),
                "--datastore-id",
                "7",
            ],
        )
        assert result.exit_code == 1
        assert "'ghost_table' not found" in result.output
        assert "ref_field 'R_GHOST' not found" in result.output
        assert "not_a_field" in result.output
        assert "Validation failed" in result.output

    def test_validate_offline_only_without_datastore(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app, ["migrate", "validate", "--sheet", _write(tmp_path, BAD_SHEET)]
        )
        assert result.exit_code == 1
        assert "Validation failed" in result.output

    def test_validate_offline_clean_sheet_passes(self, cli_runner, tmp_path):
        result = cli_runner.invoke(
            app, ["migrate", "validate", "--sheet", _write(tmp_path, GOOD_SHEET)]
        )
        assert result.exit_code == 0
        assert "Validation passed" in result.output
