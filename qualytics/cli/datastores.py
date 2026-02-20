"""CLI commands for datastore management."""

import typer
from rich import print

from ..api.client import get_client, QualyticsAPIError
from ..api.datastores import (
    connect_enrichment,
    create_datastore,
    delete_datastore,
    disconnect_enrichment,
    get_datastore,
    list_all_datastores,
    update_datastore,
    verify_connection,
)
from ..config import ConfigError, CONNECTIONS_PATH
from ..services.connections import get_connection_by
from ..services.datastores import (
    build_create_datastore_payload,
    build_update_datastore_payload,
    get_datastore_by,
)
from ..utils import get_connection, OutputFormat, format_for_display, redact_payload

datastores_app = typer.Typer(
    name="datastores", help="Create, get, update, delete, and manage datastores"
)

_VALID_REMEDIATION = {"none", "append", "overwrite"}


# ── helpers ──────────────────────────────────────────────────────────────


def _parse_comma_list(value: str) -> list[str]:
    """Parse '1,2,3' or '[1,2,3]' into a list of stripped strings."""
    return [x.strip() for x in value.strip("[]").split(",") if x.strip()]


# ── create ───────────────────────────────────────────────────────────────


@datastores_app.command("create")
def datastores_create(
    name: str = typer.Option(..., "--name", "-n", help="Datastore name"),
    connection_name: str | None = typer.Option(
        None,
        "--connection-name",
        "-cn",
        help="Connection name from connections.yml",
    ),
    connection_id: int | None = typer.Option(
        None, "--connection-id", help="Existing connection id to reference"
    ),
    database: str = typer.Option(
        ...,
        "--database",
        "-db",
        help="The database name from the connection being used",
    ),
    schema: str = typer.Option(
        ..., "--schema", "-sc", help="The schema name from the connection being used"
    ),
    tags: str | None = typer.Option(None, "--tags", help="Comma-separated tags"),
    teams: str | None = typer.Option(
        None, "--teams", help="Comma-separated team names"
    ),
    enrichment_only: bool = typer.Option(
        False,
        "--enrichment-only/--no-enrichment-only",
        help="Set if datastore will be an enrichment one",
    ),
    enrichment_prefix: str | None = typer.Option(
        None, "--enrichment-prefix", help="Prefix for enrichment artifacts"
    ),
    enrichment_source_record_limit: int | None = typer.Option(
        None, "--enrichment-source-record-limit", min=1
    ),
    enrichment_remediation_strategy: str = typer.Option(
        "none", "--enrichment-remediation-strategy"
    ),
    high_count_rollup_threshold: int | None = typer.Option(
        None, "--high-count-rollup-threshold", min=1
    ),
    trigger_catalog: bool = typer.Option(
        True,
        "--trigger-catalog/--no-trigger-catalog",
        help="Whether to trigger catalog. Default is TRUE",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print payload only; no HTTP"
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Create a new datastore."""
    client = get_client()

    try:
        if connection_name and connection_id:
            print(
                "[red]Error: Cannot specify both --connection-name and --connection-id. Please use only one.[/red]"
            )
            raise typer.Exit(code=1)

        if not connection_name and not connection_id:
            print(
                "[red]Error: Must specify either --connection-name or --connection-id.[/red]"
            )
            raise typer.Exit(code=1)

        connection_cfg = None

        if connection_name:
            print(
                f"[cyan]Checking if connection '{connection_name}' exists in Qualytics...[/cyan]"
            )
            existing_connection = get_connection_by(
                client, connection_name=connection_name
            )

            if existing_connection:
                connection_id = existing_connection["id"]
                print(
                    f"[green]Found existing connection with ID: {connection_id}[/green]"
                )
            else:
                print(
                    f"[yellow]Connection not found in Qualytics. Getting config from YAML to create new connection...[/yellow]"
                )
                connection_cfg = get_connection(CONNECTIONS_PATH, connection_name)
                connection_id = None

        payload = build_create_datastore_payload(
            cfg=connection_cfg,
            name=name,
            connection_id=connection_id,
            tags=[t.strip() for t in tags.split(",")] if tags else None,
            teams=[t.strip() for t in teams.split(",")] if teams else None,
            enrichment_only=enrichment_only,
            enrichment_prefix=enrichment_prefix,
            enrichment_source_record_limit=enrichment_source_record_limit,
            enrichment_remediation_strategy=enrichment_remediation_strategy,
            high_count_rollup_threshold=high_count_rollup_threshold,
            trigger_catalog=trigger_catalog,
            database=database,
            schema=schema,
        )

        print("[bold]Datastore Create Payload (preview with redacted secrets):[/bold]")
        print(format_for_display(redact_payload(payload), fmt))

        if dry_run:
            print("[green]Dry run successful. No HTTP request was made.[/green]")
            raise typer.Exit(code=0)

        print("[cyan]POSTing datastore to API...[/cyan]")
        result = create_datastore(client, payload)
        print("[green]Datastore created successfully![/green]")
        print(f"[green]Datastore ID: {result.get('id')}[/green]")
        print(f"[green]Datastore Name: {result.get('name')}[/green]")
        if result.get("connection"):
            print(
                f"[green]Connection ID: {result.get('connection', {}).get('id')}[/green]"
            )
    except ConfigError as e:
        print(f"[red]Config error:[/red] {e}")
        raise typer.Exit(code=2)
    except QualyticsAPIError as e:
        if e.status_code == 409 or "conflict" in e.message.lower():
            print(
                "[red]Error: A connection with these credentials already exists.[/red]"
            )
            print(
                "[yellow]Suggestion: Use the --connection-id flag to reference the existing connection instead.[/yellow]"
            )
            print(f"[yellow]Details: {e.message}[/yellow]")
        else:
            print(f"[red]{e}[/red]")
        raise typer.Exit(code=5)
    except typer.Exit:
        raise
    except Exception as e:
        print(f"[red]Unexpected error:[/red] {e}")
        raise typer.Exit(code=1)


# ── update ───────────────────────────────────────────────────────────────


@datastores_app.command("update")
def datastores_update(
    datastore_id: int = typer.Option(..., "--id", help="Datastore ID to update"),
    name: str | None = typer.Option(None, "--name", "-n", help="New datastore name"),
    connection_id: int | None = typer.Option(
        None, "--connection-id", help="New connection ID"
    ),
    database: str | None = typer.Option(None, "--database", "-db", help="New database"),
    schema: str | None = typer.Option(None, "--schema", "-sc", help="New schema"),
    tags: str | None = typer.Option(None, "--tags", help="Comma-separated tags"),
    teams: str | None = typer.Option(
        None, "--teams", help="Comma-separated team names"
    ),
    enrichment_only: bool | None = typer.Option(
        None, "--enrichment-only/--no-enrichment-only", help="Enrichment-only flag"
    ),
    enrichment_prefix: str | None = typer.Option(
        None, "--enrichment-prefix", help="Prefix for enrichment artifacts"
    ),
    enrichment_source_record_limit: int | None = typer.Option(
        None, "--enrichment-source-record-limit", min=1
    ),
    enrichment_remediation_strategy: str | None = typer.Option(
        None, "--enrichment-remediation-strategy"
    ),
    high_count_rollup_threshold: int | None = typer.Option(
        None, "--high-count-rollup-threshold", min=1
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Update an existing datastore (partial update)."""
    if (
        enrichment_remediation_strategy
        and enrichment_remediation_strategy not in _VALID_REMEDIATION
    ):
        print(
            f"[red]--enrichment-remediation-strategy must be one of: {', '.join(sorted(_VALID_REMEDIATION))}.[/red]"
        )
        raise typer.Exit(code=1)

    payload = build_update_datastore_payload(
        name=name,
        connection_id=connection_id,
        database=database,
        schema=schema,
        tags=[t.strip() for t in tags.split(",")] if tags else None,
        teams=[t.strip() for t in teams.split(",")] if teams else None,
        enrichment_only=enrichment_only,
        enrichment_prefix=enrichment_prefix,
        enrichment_source_record_limit=enrichment_source_record_limit,
        enrichment_remediation_strategy=enrichment_remediation_strategy,
        high_count_rollup_threshold=high_count_rollup_threshold,
    )

    if not payload:
        print("[yellow]No fields to update. Provide at least one option.[/yellow]")
        raise typer.Exit(code=1)

    client = get_client()
    result = update_datastore(client, datastore_id, payload)
    print(f"[green]Datastore {datastore_id} updated successfully.[/green]")
    print(format_for_display(result, fmt))


# ── get ──────────────────────────────────────────────────────────────────


@datastores_app.command("get")
def datastores_get(
    id: int | None = typer.Option(None, "--id", help="Datastore ID"),
    name: str | None = typer.Option(None, "--name", help="Datastore name"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Get a datastore by ID or name."""
    if id and name:
        print(
            "[red]Error: Cannot specify both --id and --name. Please use only one.[/red]"
        )
        raise typer.Exit(code=1)

    if not id and not name:
        print("[red]Error: Must specify either --id or --name.[/red]")
        raise typer.Exit(code=1)

    client = get_client()

    if id:
        result = get_datastore(client, id)
    else:
        result = get_datastore_by(client, datastore_name=name)

    if result is None:
        identifier = f"ID {id}" if id else f"name '{name}'"
        print(f"[red]Datastore with {identifier} not found.[/red]")
        raise typer.Exit(code=1)

    print("[green]Datastore found:[/green]")
    print(format_for_display(result, fmt))


# ── list ─────────────────────────────────────────────────────────────────


@datastores_app.command("list")
def datastores_list(
    name: str | None = typer.Option(
        None, "--name", help="Filter datastores by name (search)"
    ),
    datastore_type: str | None = typer.Option(
        None,
        "--type",
        help="Comma-separated connection types to filter by (e.g. postgresql,snowflake)",
    ),
    tag: str | None = typer.Option(None, "--tag", help="Tag name to filter by"),
    enrichment_only: bool | None = typer.Option(
        None,
        "--enrichment-only/--no-enrichment-only",
        help="Filter by enrichment-only datastores",
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """List datastores with optional filters."""
    client = get_client()

    type_list = (
        [t.strip() for t in datastore_type.split(",")] if datastore_type else None
    )

    all_ds = list_all_datastores(
        client,
        name=name,
        datastore_type=type_list,
        tag=tag,
        enrichment_only=enrichment_only,
    )

    print(f"[green]Found {len(all_ds)} datastores.[/green]")
    print(format_for_display(all_ds, fmt))


# ── delete ───────────────────────────────────────────────────────────────


@datastores_app.command("delete")
def datastores_delete(
    id: int = typer.Option(..., "--id", help="Datastore ID to delete"),
):
    """Delete a datastore. Use with caution!"""
    client = get_client()
    result = delete_datastore(client, id)
    print(f"[green]Datastore with ID {id} deleted successfully![/green]")
    if result.get("message"):
        print(f"[green]{result.get('message')}[/green]")


# ── verify ───────────────────────────────────────────────────────────────


@datastores_app.command("verify")
def datastores_verify(
    id: int = typer.Option(..., "--id", help="Datastore ID to verify connection for"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Verify the connection for an existing datastore."""
    client = get_client()
    result = verify_connection(client, id)

    connected = result.get("connected", False)
    if connected:
        print(f"[green]Datastore {id}: connection verified successfully.[/green]")
    else:
        msg = result.get("message", "Unknown error")
        print(f"[red]Datastore {id}: connection failed — {msg}[/red]")

    print(format_for_display(result, fmt))


# ── enrichment ───────────────────────────────────────────────────────────


@datastores_app.command("enrichment")
def datastores_enrichment(
    id: int = typer.Option(..., "--id", help="Source datastore ID"),
    link: int | None = typer.Option(
        None, "--link", help="Enrichment datastore ID to link"
    ),
    unlink: bool = typer.Option(False, "--unlink", help="Unlink enrichment datastore"),
):
    """Link or unlink an enrichment datastore."""
    if link and unlink:
        print("[red]Cannot specify both --link and --unlink.[/red]")
        raise typer.Exit(code=1)

    if not link and not unlink:
        print("[red]Must specify either --link <enrichment_id> or --unlink.[/red]")
        raise typer.Exit(code=1)

    client = get_client()

    if link:
        result = connect_enrichment(client, id, link)
        print(f"[green]Enrichment datastore {link} linked to datastore {id}.[/green]")
        print(f"[green]{result}[/green]")
    else:
        result = disconnect_enrichment(client, id)
        print(f"[green]Enrichment unlinked from datastore {id}.[/green]")
        if result.get("message"):
            print(f"[green]{result['message']}[/green]")
