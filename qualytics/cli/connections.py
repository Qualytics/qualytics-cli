"""CLI commands for connection management."""

import json

import typer
from rich import print

from ..api.client import get_client, QualyticsAPIError
from ..api.connections import (
    create_connection,
    delete_connection,
    get_connection_api,
    list_all_connections,
    test_connection,
    update_connection,
)
from ..services.connections import (
    build_create_connection_payload,
    build_update_connection_payload,
    get_connection_by_name,
)
from ..utils import (
    OutputFormat,
    format_for_display,
    get_connection as get_yaml_connection,
    redact_payload,
    resolve_env_vars,
)
from ..config import CONNECTIONS_PATH

connections_app = typer.Typer(
    name="connections",
    help="Create, get, update, delete, test, and manage connections",
)


# ── helpers ──────────────────────────────────────────────────────────────


def _parse_comma_list(value: str) -> list[str]:
    """Parse '1,2,3' or '[1,2,3]' into a list of stripped strings."""
    return [x.strip() for x in value.strip("[]").split(",") if x.strip()]


def _resolve_sensitive_flags(
    *,
    host: str | None = None,
    username: str | None = None,
    password: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    uri: str | None = None,
) -> dict:
    """Resolve ``${VAR}`` in sensitive flag values.

    Returns a dict of the resolved values (only non-None entries).
    Raises ``typer.Exit`` on unresolved env vars.
    """
    mapping = {
        "host": host,
        "username": username,
        "password": password,
        "access_key": access_key,
        "secret_key": secret_key,
        "uri": uri,
    }

    resolved: dict = {}
    for key, value in mapping.items():
        if value is None:
            continue
        try:
            resolved[key] = resolve_env_vars(value)
        except ValueError as e:
            print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)
    return resolved


# ── create ───────────────────────────────────────────────────────────────


@connections_app.command("create")
def connections_create(
    connection_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Connection type: postgresql, snowflake, mysql, bigquery, etc.",
    ),
    name: str | None = typer.Option(None, "--name", "-n", help="Connection name"),
    host: str | None = typer.Option(
        None, "--host", help="Host (supports ${ENV_VAR} syntax)"
    ),
    port: int | None = typer.Option(None, "--port", help="Port number"),
    username: str | None = typer.Option(
        None, "--username", help="Username (supports ${ENV_VAR} syntax)"
    ),
    password: str | None = typer.Option(
        None, "--password", help="Password (supports ${ENV_VAR} syntax)"
    ),
    uri: str | None = typer.Option(
        None, "--uri", help="URI for DFS connections (supports ${ENV_VAR} syntax)"
    ),
    access_key: str | None = typer.Option(
        None,
        "--access-key",
        help="Access key for DFS connections (supports ${ENV_VAR} syntax)",
    ),
    secret_key: str | None = typer.Option(
        None,
        "--secret-key",
        help="Secret key for DFS connections (supports ${ENV_VAR} syntax)",
    ),
    catalog: str | None = typer.Option(
        None, "--catalog", help="Catalog for native connections"
    ),
    jdbc_fetch_size: int | None = typer.Option(
        None, "--jdbc-fetch-size", help="JDBC fetch size"
    ),
    max_parallelization: int | None = typer.Option(
        None, "--max-parallelization", help="Max parallelization level"
    ),
    parameters: str | None = typer.Option(
        None,
        "--parameters",
        help='JSON string for type-specific params (e.g. \'{"role": "ADMIN", "warehouse": "WH"}\')',
    ),
    from_yaml: str | None = typer.Option(
        None,
        "--from-yaml",
        help="Path to connections YAML file (default: ~/.qualytics/config/connections.yml)",
    ),
    connection_key: str | None = typer.Option(
        None,
        "--connection-key",
        help="Connection key/name in the YAML file (required with --from-yaml)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print payload only; no HTTP"
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Create a new connection.

    Two modes:
      1. Inline flags: --type, --host, --port, --username, --password, etc.
      2. From YAML: --from-yaml <path> --connection-key <key>

    Sensitive flags support ${ENV_VAR} syntax — values are resolved from
    environment variables (or .env file) before being sent to the API.
    Use single quotes in your shell to prevent premature expansion:

        qualytics connections create --type postgresql --name prod-pg \\
          --host db.example.com --port 5432 \\
          --username '${DB_USER}' --password '${DB_PASSWORD}'
    """
    # Mode 2: from YAML
    if from_yaml is not None or connection_key is not None:
        if from_yaml is None:
            from_yaml = CONNECTIONS_PATH
        if connection_key is None:
            print("[red]--connection-key is required when using --from-yaml.[/red]")
            raise typer.Exit(code=1)

        try:
            cfg = get_yaml_connection(from_yaml, connection_key)
        except (ValueError, FileNotFoundError) as e:
            print(f"[red]{e}[/red]")
            raise typer.Exit(code=1)

        payload = {
            "type": cfg["type"],
            "name": cfg.get("name", connection_key),
        }
        params = cfg.get("parameters", {})
        if "host" in params:
            payload["host"] = params["host"]
        if "port" in params:
            payload["port"] = params["port"]
        if "user" in params:
            payload["username"] = params["user"]
        if "username" in params:
            payload["username"] = params["username"]
        if "password" in params:
            payload["password"] = params["password"]

        # Merge any remaining params
        for k, v in params.items():
            if k not in ("host", "port", "user", "username", "password"):
                payload[k] = v
    else:
        # Mode 1: inline flags
        if connection_type is None:
            print("[red]--type is required (or use --from-yaml).[/red]")
            raise typer.Exit(code=1)

        # Resolve env vars in sensitive fields
        resolved = _resolve_sensitive_flags(
            host=host,
            username=username,
            password=password,
            access_key=access_key,
            secret_key=secret_key,
            uri=uri,
        )

        # Parse extra parameters JSON
        extra_params = None
        if parameters is not None:
            try:
                extra_params = json.loads(parameters)
            except json.JSONDecodeError as e:
                print(f"[red]Invalid JSON in --parameters: {e}[/red]")
                raise typer.Exit(code=1)

        payload = build_create_connection_payload(
            connection_type,
            name=name,
            host=resolved.get("host", host),
            port=port,
            username=resolved.get("username", username),
            password=resolved.get("password"),
            uri=resolved.get("uri"),
            access_key=resolved.get("access_key"),
            secret_key=resolved.get("secret_key"),
            catalog=catalog,
            jdbc_fetch_size=jdbc_fetch_size,
            max_parallelization=max_parallelization,
            parameters=extra_params,
        )

    print("[bold]Connection Create Payload (secrets redacted):[/bold]")
    print(format_for_display(redact_payload(payload), fmt))

    if dry_run:
        print("[green]Dry run successful. No HTTP request was made.[/green]")
        raise typer.Exit(code=0)

    client = get_client()
    result = create_connection(client, payload)
    print("[green]Connection created successfully![/green]")
    print(f"[green]Connection ID: {result.get('id')}[/green]")
    print(f"[green]Connection Name: {result.get('name')}[/green]")
    print(f"[green]Connection Type: {result.get('type')}[/green]")


# ── update ───────────────────────────────────────────────────────────────


@connections_app.command("update")
def connections_update(
    connection_id: int = typer.Option(..., "--id", help="Connection ID to update"),
    name: str | None = typer.Option(None, "--name", "-n", help="New connection name"),
    host: str | None = typer.Option(
        None, "--host", help="New host (supports ${ENV_VAR})"
    ),
    port: int | None = typer.Option(None, "--port", help="New port"),
    username: str | None = typer.Option(
        None, "--username", help="New username (supports ${ENV_VAR})"
    ),
    password: str | None = typer.Option(
        None, "--password", help="New password (supports ${ENV_VAR})"
    ),
    uri: str | None = typer.Option(None, "--uri", help="New URI (supports ${ENV_VAR})"),
    access_key: str | None = typer.Option(
        None, "--access-key", help="New access key (supports ${ENV_VAR})"
    ),
    secret_key: str | None = typer.Option(
        None, "--secret-key", help="New secret key (supports ${ENV_VAR})"
    ),
    parameters: str | None = typer.Option(
        None,
        "--parameters",
        help="JSON string for type-specific params to update",
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Update an existing connection (partial update).

    Only provided fields are sent. Sensitive flags support ${ENV_VAR} syntax.
    """
    # Resolve env vars in sensitive fields
    resolved = _resolve_sensitive_flags(
        host=host,
        username=username,
        password=password,
        access_key=access_key,
        secret_key=secret_key,
        uri=uri,
    )

    # Parse extra parameters JSON
    extra_params = None
    if parameters is not None:
        try:
            extra_params = json.loads(parameters)
        except json.JSONDecodeError as e:
            print(f"[red]Invalid JSON in --parameters: {e}[/red]")
            raise typer.Exit(code=1)

    changes = build_update_connection_payload(
        name=name,
        host=resolved.get("host"),
        port=port,
        username=resolved.get("username"),
        password=resolved.get("password"),
        uri=resolved.get("uri"),
        access_key=resolved.get("access_key"),
        secret_key=resolved.get("secret_key"),
    )

    # Merge extra parameters
    if extra_params:
        changes.update(extra_params)

    if not changes:
        print("[yellow]No fields to update. Provide at least one option.[/yellow]")
        raise typer.Exit(code=1)

    client = get_client()
    result = update_connection(client, connection_id, changes)
    print(f"[green]Connection {connection_id} updated successfully.[/green]")
    print(format_for_display(redact_payload(result), fmt))


# ── get ──────────────────────────────────────────────────────────────────


@connections_app.command("get")
def connections_get(
    connection_id: int | None = typer.Option(None, "--id", help="Connection ID"),
    name: str | None = typer.Option(None, "--name", help="Connection name"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Get a connection by ID or name. Secrets are masked in the response."""
    if connection_id and name:
        print(
            "[red]Error: Cannot specify both --id and --name. Please use only one.[/red]"
        )
        raise typer.Exit(code=1)

    if not connection_id and not name:
        print("[red]Error: Must specify either --id or --name.[/red]")
        raise typer.Exit(code=1)

    client = get_client()

    if connection_id:
        result = get_connection_api(client, connection_id)
    else:
        result = get_connection_by_name(client, name)

    if result is None:
        identifier = f"ID {connection_id}" if connection_id else f"name '{name}'"
        print(f"[red]Connection with {identifier} not found.[/red]")
        raise typer.Exit(code=1)

    print("[green]Connection found:[/green]")
    print(format_for_display(redact_payload(result), fmt))


# ── list ─────────────────────────────────────────────────────────────────


@connections_app.command("list")
def connections_list(
    name: str | None = typer.Option(
        None, "--name", help="Filter connections by name (search)"
    ),
    connection_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Comma-separated connection types to filter by (e.g. postgresql,snowflake)",
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """List connections with optional filters."""
    client = get_client()

    type_list = _parse_comma_list(connection_type) if connection_type else None

    all_conns = list_all_connections(
        client,
        name=name,
        connection_type=type_list,
    )

    # Redact each connection in the list
    redacted = [redact_payload(c) for c in all_conns]

    print(f"[green]Found {len(all_conns)} connections.[/green]")
    print(format_for_display(redacted, fmt))


# ── delete ───────────────────────────────────────────────────────────────


@connections_app.command("delete")
def connections_delete(
    connection_id: int = typer.Option(..., "--id", help="Connection ID to delete"),
):
    """Delete a connection by ID.

    Fails with 409 if datastores still reference this connection.
    """
    client = get_client()

    try:
        result = delete_connection(client, connection_id)
        print(f"[green]Connection {connection_id} deleted successfully.[/green]")
        if result.get("message"):
            print(f"[green]{result['message']}[/green]")
    except QualyticsAPIError as e:
        if e.status_code == 409:
            print(
                f"[red]Cannot delete connection {connection_id}: "
                "datastores still reference it.[/red]"
            )
            print("[yellow]Remove or reassign those datastores first.[/yellow]")
            raise typer.Exit(code=1)
        raise


# ── test ─────────────────────────────────────────────────────────────────


@connections_app.command("test")
def connections_test(
    connection_id: int = typer.Option(..., "--id", help="Connection ID to test"),
    host: str | None = typer.Option(
        None, "--host", help="Override host for testing (supports ${ENV_VAR})"
    ),
    username: str | None = typer.Option(
        None, "--username", help="Override username for testing (supports ${ENV_VAR})"
    ),
    password: str | None = typer.Option(
        None, "--password", help="Override password for testing (supports ${ENV_VAR})"
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Test a connection, optionally with new credentials.

    Without override flags, tests the existing saved connection.
    With override flags, tests with new values without persisting them.
    """
    # Resolve env vars if any overrides provided
    resolved = _resolve_sensitive_flags(host=host, username=username, password=password)

    payload = None
    if resolved:
        payload = resolved

    client = get_client()
    result = test_connection(client, connection_id, payload=payload)

    connected = result.get("connected", result.get("success", False))
    if connected:
        print(f"[green]Connection {connection_id}: test passed successfully.[/green]")
    else:
        msg = result.get("message", "Unknown error")
        print(f"[red]Connection {connection_id}: test failed — {msg}[/red]")

    print(format_for_display(redact_payload(result), fmt))
