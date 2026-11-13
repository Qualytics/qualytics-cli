"""--format json/yaml output must be machine-readable.

Rich's ``print`` wraps lines at console width (80 columns when piped) and
parses ``[...]`` and ``:emoji:`` codes as markup, so a long description or
a bracketed name used to come out as invalid JSON with exit code 0. Status
lines such as "Found N datastores." printed to stdout too, so piping into
``jq`` failed even when the payload itself was intact.
"""

import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
import yaml

from qualytics.api.client import QualyticsAPIError
from qualytics.qualytics import app

LONG = "a value long enough to run past the console width " * 3
PAYLOAD = {
    "id": 1,
    "name": "orders[x]",
    "description": LONG,
    "note": ":warning: keep [bold]literal[/bold] text",
}

# (argv, function to patch, return value, status text expected on stderr)
CASES = [
    (["anomalies", "get", "--id", "1"], "anomalies.get_anomaly", PAYLOAD, ""),
    (["operations", "get", "--id", "1"], "operations.get_operation", PAYLOAD, ""),
    (["checks", "get", "--id", "1"], "checks.get_quality_check", PAYLOAD, ""),
    (["users", "get", "--id", "1"], "users.get_user", PAYLOAD, ""),
    (["teams", "get", "--id", "1"], "teams.get_team", PAYLOAD, ""),
    (["tags", "get", "--name", "x"], "tags.get_tag", PAYLOAD, ""),
    (
        ["containers", "get", "--id", "1"],
        "containers.get_container",
        PAYLOAD,
        "Container found:",
    ),
    (
        ["datastores", "get", "--id", "1"],
        "datastores.get_datastore",
        PAYLOAD,
        "Datastore found:",
    ),
    (
        ["connections", "get", "--id", "1"],
        "connections.get_connection_api",
        PAYLOAD,
        "Connection found:",
    ),
    (
        ["datastores", "list"],
        "datastores.list_all_datastores",
        [PAYLOAD],
        "Found 1 datastores.",
    ),
    (["users", "list"], "users.list_all_users", [PAYLOAD], "Found 1 user(s)."),
    (["users", "list"], "users.list_all_users", [], "No users found."),
    (["teams", "list"], "teams.list_all_teams", [], "No teams found."),
    (["tags", "list"], "tags.list_all_tags", [], "No tags found."),
    (
        ["tags", "create", "--name", "x"],
        "tags.create_tag",
        PAYLOAD,
        "Tag created successfully!",
    ),
    (
        ["datastores", "verify", "--id", "1"],
        "datastores.verify_connection",
        {**PAYLOAD, "connected": True},
        "connection verified successfully",
    ),
    (
        ["connections", "test", "--id", "1"],
        "connections.test_connection",
        {**PAYLOAD, "connected": False, "message": "refused"},
        "test failed — refused",
    ),
]

PARSERS = {"json": json.loads, "yaml": yaml.safe_load}


def _case_id(case):
    argv, _, returned, _ = case
    return " ".join(argv[:2]) + (" empty" if returned == [] else "")


@pytest.mark.parametrize("fmt", sorted(PARSERS))
@pytest.mark.parametrize(
    "argv,target,returned,status_text", CASES, ids=[_case_id(c) for c in CASES]
)
def test_stdout_is_exactly_the_structured_payload(
    argv, target, returned, status_text, fmt, cli_runner
):
    module = "qualytics.cli." + target.split(".")[0]
    with (
        patch(f"{module}.get_client", return_value=MagicMock()),
        patch(f"qualytics.cli.{target}", return_value=returned),
    ):
        result = cli_runner.invoke(app, [*argv, "--format", fmt])

    assert result.exit_code == 0, result.output
    assert PARSERS[fmt](result.stdout) == returned
    assert status_text in result.stderr


@pytest.mark.parametrize("fmt", sorted(PARSERS))
def test_container_with_profiles_is_one_document(fmt, cli_runner):
    profiles = {"items": [{"name": "col[1]", "notes": LONG}]}
    with (
        patch("qualytics.cli.containers.get_client", return_value=MagicMock()),
        patch("qualytics.cli.containers.get_container", return_value=PAYLOAD),
        patch("qualytics.cli.containers.get_field_profiles", return_value=profiles),
    ):
        result = cli_runner.invoke(
            app, ["containers", "get", "--id", "1", "--profiles", "--format", fmt]
        )

    assert result.exit_code == 0, result.output
    assert PARSERS[fmt](result.stdout) == {**PAYLOAD, "field_profiles": profiles}


@pytest.mark.parametrize("fmt", sorted(PARSERS))
def test_create_dry_run_prints_only_the_payload(fmt, cli_runner):
    result = cli_runner.invoke(
        app,
        [
            "containers",
            "create",
            "--type",
            "computed_table",
            "--name",
            "orders[x]",
            "--datastore-id",
            "1",
            "--query",
            f"select '{LONG}' as c",
            "--dry-run",
            "--format",
            fmt,
        ],
    )

    assert result.exit_code == 0, result.output
    payload = PARSERS[fmt](result.stdout)
    assert payload["name"] == "orders[x]"
    assert LONG in payload["query"]
    assert "Dry run successful" in result.stderr


CREATE_CASES = [
    (
        [
            "connections",
            "create",
            "--type",
            "postgresql",
            "--name",
            "orders[x]",
            "--host",
            "db.example.com",
            "--port",
            "5432",
            "--username",
            "admin",
            "--password",
            "secret",
        ],
        ["connections.create_connection"],
        "Connection ID: 1",
    ),
    (
        [
            "datastores",
            "create",
            "--name",
            "orders[x]",
            "--connection-id",
            "5",
            "--database",
            "mydb",
            "--schema",
            "public",
        ],
        ["datastores.create_datastore", "datastores.get_connection_by"],
        "Datastore ID: 1",
    ),
    (
        [
            "containers",
            "create",
            "--type",
            "computed_table",
            "--name",
            "orders[x]",
            "--datastore-id",
            "1",
            "--query",
            f"select '{LONG}' as c",
        ],
        ["containers.create_container"],
        "Container ID: 1",
    ),
]


@pytest.mark.parametrize("fmt", sorted(PARSERS))
@pytest.mark.parametrize(
    "argv,targets,id_line", CREATE_CASES, ids=[c[0][0] for c in CREATE_CASES]
)
def test_create_keeps_status_lines_off_stdout(argv, targets, id_line, fmt, cli_runner):
    module = "qualytics.cli." + argv[0]
    created = {"id": 1, "name": "orders[x]", "type": "x", "container_type": "x"}
    with ExitStack() as stack:
        stack.enter_context(patch(f"{module}.get_client", return_value=MagicMock()))
        stack.enter_context(patch(f"qualytics.cli.{targets[0]}", return_value=created))
        for extra in targets[1:]:
            stack.enter_context(patch(f"qualytics.cli.{extra}"))
        result = cli_runner.invoke(app, [*argv, "--format", fmt])

    assert result.exit_code == 0, result.output
    assert PARSERS[fmt](result.stdout)["name"] == "orders[x]"
    assert "created successfully" in result.stderr
    assert id_line in result.stderr


def test_update_prints_only_the_result(cli_runner):
    with (
        patch("qualytics.cli.datastores.get_client", return_value=MagicMock()),
        patch("qualytics.cli.datastores.get_datastore", return_value={"id": 1}),
        patch("qualytics.cli.datastores.flatten_datastore_for_put", return_value={}),
        patch("qualytics.cli.datastores.update_datastore", return_value=PAYLOAD),
    ):
        result = cli_runner.invoke(
            app,
            ["datastores", "update", "--id", "1", "--name", "n", "--format", "json"],
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == PAYLOAD
    assert "Datastore 1 updated successfully." in result.stderr


def test_container_lookup_retry_notice_stays_off_stdout(cli_runner):
    listing = [
        QualyticsAPIError(503, "busy"),
        [{"name": "orders", "id": 7}],
    ]
    with (
        patch("qualytics.cli.checks.get_client", return_value=MagicMock()),
        patch(
            "qualytics.services.containers.list_containers_listing",
            side_effect=listing,
        ),
        patch("qualytics.services.containers.time.sleep"),
        patch(
            "qualytics.cli.checks.list_all_quality_checks", return_value=[PAYLOAD]
        ) as list_checks,
    ):
        result = cli_runner.invoke(
            app,
            [
                "checks",
                "list",
                "--datastore-id",
                "1",
                "--containers",
                "orders",
                "--format",
                "json",
            ],
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [PAYLOAD]
    assert "Attempt 1 failed with status code 503" in result.stderr
    assert list_checks.call_args.kwargs["containers"] == [7]


def test_lookup_error_goes_to_stderr(cli_runner):
    with (
        patch("qualytics.cli.datastores.get_client", return_value=MagicMock()),
        patch("qualytics.cli.datastores.get_datastore", return_value=None),
    ):
        result = cli_runner.invoke(
            app, ["datastores", "get", "--id", "9", "--format", "json"]
        )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Datastore with ID 9 not found." in result.stderr


def test_missing_config_error_goes_to_stderr(cli_runner):
    with patch("qualytics.config.load_config", return_value=None):
        result = cli_runner.invoke(app, ["users", "list", "--format", "json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Configuration not found" in result.stderr


def test_expired_token_warning_goes_to_stderr(cli_runner):
    expired = "eyJhbGciOiJub25lIn0.eyJleHAiOjF9."  # {"exp": 1}
    with patch(
        "qualytics.config.load_config",
        return_value={"url": "https://x.example", "token": expired},
    ):
        result = cli_runner.invoke(app, ["users", "list", "--format", "json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Your token is expired" in result.stderr
