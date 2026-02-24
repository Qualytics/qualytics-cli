"""CLI commands for config-as-code export/import."""

import os

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from ..api.client import get_client
from ..services.export_import import export_config, import_config

from . import add_suggestion_callback
from .progress import status

export_import_app = typer.Typer(
    name="config",
    help="Export and import configuration",
)
add_suggestion_callback(export_import_app, "config")

console = Console()

_VALID_RESOURCES = {"connections", "datastores", "containers", "checks"}


def _parse_include(value: str | None) -> set[str] | None:
    """Parse ``--include connections,datastores`` into a set.

    Returns None (meaning all) when *value* is None.
    """
    if value is None:
        return None
    items = {x.strip().lower() for x in value.split(",") if x.strip()}
    invalid = items - _VALID_RESOURCES
    if invalid:
        print(
            f"[red]Invalid --include value(s): {', '.join(sorted(invalid))}. "
            f"Valid: {', '.join(sorted(_VALID_RESOURCES))}[/red]"
        )
        raise typer.Exit(code=1)
    return items


# ── export ───────────────────────────────────────────────────────────────


@export_import_app.command("export")
def config_export(
    datastore_id: list[int] = typer.Option(
        ...,
        "--datastore-id",
        help="Datastore ID to export (repeat for multiple)",
    ),
    output: str = typer.Option(
        "./qualytics-export",
        "--output",
        "-o",
        help="Root output directory",
    ),
    include: str | None = typer.Option(
        None,
        "--include",
        help="Comma-separated resource types to include: connections,datastores,containers,checks (default: all)",
    ),
):
    """Export Qualytics configuration to a hierarchical YAML folder structure.

    Exports connections, datastores, computed containers, and quality checks
    for the given datastore IDs.  The output is git-diff-friendly and designed
    for config-as-code workflows.

    \b
    Folder structure:
        <output>/
            connections/<name>.yaml
            datastores/<name>/_datastore.yaml
            datastores/<name>/containers/<name>/_container.yaml
            datastores/<name>/checks/<container>/<rule>.yaml

    Secrets are replaced with ${ENV_VAR} placeholders.  Re-running export
    on the same directory produces zero git diff when nothing has changed.

    Examples:

        qualytics config export --datastore-id 1 --datastore-id 2

        qualytics config export --datastore-id 1 --output ./my-config

        qualytics config export --datastore-id 1 --include connections,datastores
    """
    include_set = _parse_include(include)

    client = get_client()

    ds_label = ", ".join(str(d) for d in datastore_id)
    print(
        f"[cyan]Exporting configuration for datastore(s) "
        f"{ds_label} to {output}/...[/cyan]"
    )

    with status("[bold cyan]Exporting configuration...[/bold cyan]"):
        result = export_config(
            client,
            datastore_id,
            output,
            include=include_set,
        )

    # Summary table
    table = Table(title="Export Summary")
    table.add_column("Resource", style="cyan")
    table.add_column("Exported", style="green")

    for resource, count in result.items():
        if include_set is None or resource in include_set:
            table.add_row(resource.capitalize(), str(count))

    console.print(table)
    print(f"[bold green]Export complete: {output}/[/bold green]")


# ── import ───────────────────────────────────────────────────────────────


@export_import_app.command("import")
def config_import(
    input_dir: str = typer.Option(
        "./qualytics-export",
        "--input",
        "-i",
        help="Root input directory with exported YAML files",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview what would be created/updated without making changes",
    ),
    include: str | None = typer.Option(
        None,
        "--include",
        help="Comma-separated resource types to include: connections,datastores,containers,checks (default: all)",
    ),
):
    """Import Qualytics configuration from a hierarchical YAML folder structure.

    Reads connections, datastores, containers, and quality checks from the
    export directory and upserts them into the target Qualytics instance.

    \b
    Import order (dependency-safe):
        1. Connections (matched by name)
        2. Datastores (matched by name, connection resolved by name)
        3. Computed containers (matched by name within datastore)
        4. Quality checks (matched by _qualytics_check_uid)

    Secrets in connection files use ${ENV_VAR} placeholders that are
    resolved from environment variables (or .env file) at import time.

    Examples:

        qualytics config import --input ./qualytics-export

        qualytics config import --input ./qualytics-export --dry-run

        qualytics config import --input ./qualytics-export --include connections,datastores
    """
    include_set = _parse_include(include)

    if not os.path.isdir(input_dir):
        print(f"[red]Input directory not found: {input_dir}[/red]")
        raise typer.Exit(code=1)

    client = get_client()

    if dry_run:
        print("[bold yellow]DRY RUN — no changes will be made.[/bold yellow]")

    print(f"[cyan]Importing configuration from {input_dir}/...[/cyan]")

    with status("[bold cyan]Importing configuration...[/bold cyan]"):
        result = import_config(
            client,
            input_dir,
            dry_run=dry_run,
            include=include_set,
        )

    # Summary table
    table = Table(title="Import Summary")
    table.add_column("Resource", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Updated", style="yellow")
    table.add_column("Failed", style="red")

    for resource in ("connections", "datastores", "containers", "checks"):
        if include_set is None or resource in include_set:
            r = result[resource]
            table.add_row(
                resource.capitalize(),
                str(r["created"]),
                str(r["updated"]),
                str(r["failed"]),
            )

    console.print(table)

    # Print errors
    total_errors = 0
    for resource, r in result.items():
        for err in r.get("errors", []):
            print(f"  [red]{resource}: {err}[/red]")
            total_errors += 1

    if total_errors:
        print(f"\n[red]{total_errors} error(s) encountered during import.[/red]")
    else:
        print("[bold green]Import complete![/bold green]")
