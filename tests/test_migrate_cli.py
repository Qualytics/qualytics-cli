"""Tests for the `qualytics migrate plan` command."""

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
        assert check["additional_metadata"]["legacy_check_id"] == "550"

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
