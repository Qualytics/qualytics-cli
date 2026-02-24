"""CLI commands for quality checks."""

import os
import typer
from datetime import datetime
from rich import print
from rich.progress import track
from rich.table import Table
from rich.console import Console

from ..api.client import get_client, QualyticsAPIError
from ..api.quality_checks import (
    get_quality_check,
    list_all_quality_checks,
    create_quality_check,
    update_quality_check,
    delete_quality_check,
    bulk_delete_quality_checks,
)
from ..config import BASE_PATH
from ..utils import (
    distinct_file_content,
    log_error,
    OutputFormat,
    load_data_file,
    dump_data_file,
    format_for_display,
)
from ..services.quality_checks import (
    export_checks_to_directory,
    load_checks_from_directory,
    import_checks_to_datastore,
    _build_create_payload,
)
from ..services.containers import get_table_ids

from . import add_suggestion_callback

# Create Typer instance for checks
checks_app = typer.Typer(name="checks", help="Manage quality checks")
add_suggestion_callback(checks_app, "checks")

console = Console()

# ── Helpers ───────────────────────────────────────────────────────────────


def _parse_comma_list(value: str) -> list[str]:
    """Parse '1,2,3' or '[1,2,3]' into a list of stripped strings."""
    return [x.strip() for x in value.strip("[]").split(",") if x.strip()]


# ── CRUD: create ──────────────────────────────────────────────────────────


@checks_app.command("create")
def checks_create(
    datastore_id: int = typer.Option(..., "--datastore-id", help="Target datastore ID"),
    file: str = typer.Option(
        ..., "--file", "-f", help="YAML/JSON file with check definition(s)"
    ),
):
    """Create quality checks from a file (single or bulk)."""
    client = get_client()
    data = load_data_file(file)

    # Accept a single dict or a list of dicts
    items = data if isinstance(data, list) else [data]

    # Resolve container names → IDs
    table_ids = get_table_ids(client=client, datastore_id=datastore_id)
    if table_ids is None:
        print(f"[red]Could not resolve containers for datastore {datastore_id}.[/red]")
        raise typer.Exit(code=1)

    created = 0
    failed = 0
    total = len(items)

    for i, check in enumerate(items, 1):
        container_name = check.get("container", "")
        container_id = table_ids.get(container_name)
        if container_id is None:
            print(
                f"[red]({i}/{total}) Container '{container_name}' not found "
                f"in datastore {datastore_id}. Skipping.[/red]"
            )
            failed += 1
            continue
        try:
            payload = _build_create_payload(check, container_id)
            result = create_quality_check(client, payload)
            print(
                f"[green]({i}/{total}) Created check {result['id']}: "
                f"{check.get('description', '')}[/green]"
            )
            created += 1
        except QualyticsAPIError as e:
            print(f"[red]({i}/{total}) Failed: {e.message}[/red]")
            failed += 1

    print(f"\n[bold]Created {created}, failed {failed} of {total} checks.[/bold]")


# ── CRUD: get ─────────────────────────────────────────────────────────────


@checks_app.command("get")
def checks_get(
    check_id: int = typer.Option(..., "--id", help="Quality check ID"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", help="Output format: yaml or json"
    ),
):
    """Get a single quality check by ID."""
    client = get_client()
    result = get_quality_check(client, check_id)
    print(format_for_display(result, fmt))


# ── CRUD: list ────────────────────────────────────────────────────────────


@checks_app.command("list")
def checks_list(
    datastore_id: int = typer.Option(
        ..., "--datastore-id", help="Datastore ID to list checks from"
    ),
    containers: str | None = typer.Option(
        None,
        "--containers",
        help='Comma-separated container IDs. Example: "1,2,3"',
    ),
    tags: str | None = typer.Option(
        None,
        "--tags",
        help='Comma-separated tag names. Example: "tag1,tag2"',
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter by status: Active, Draft, Archived",
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", help="Output format: yaml or json"
    ),
):
    """List quality checks for a datastore."""
    client = get_client()

    container_ids = None
    if containers:
        container_ids = [int(x) for x in _parse_comma_list(containers)]
    tag_list = _parse_comma_list(tags) if tags else None

    # Handle archived as a special status
    archived = None
    api_status = None
    if status:
        if status.lower() == "archived":
            archived = "only"
        else:
            api_status = status.capitalize()

    all_checks = list_all_quality_checks(
        client,
        datastore_id,
        containers=container_ids,
        tags=tag_list,
        status=api_status,
        archived=archived,
    )

    print(f"[green]Found {len(all_checks)} quality checks.[/green]")
    print(format_for_display(all_checks, fmt))


# ── CRUD: update ──────────────────────────────────────────────────────────


@checks_app.command("update")
def checks_update(
    check_id: int = typer.Option(..., "--id", help="Quality check ID to update"),
    file: str = typer.Option(
        ..., "--file", "-f", help="YAML/JSON file with updated check definition"
    ),
):
    """Update a quality check from a file."""
    client = get_client()
    data = load_data_file(file)

    payload = {
        "description": data.get("description", ""),
        "fields": data.get("fields") or [],
        "coverage": data.get("coverage"),
        "filter": data.get("filter"),
        "properties": data.get("properties") or {},
        "tags": data.get("tags") or [],
        "additional_metadata": data.get("additional_metadata") or {},
        "status": data.get("status", "Active"),
    }

    result = update_quality_check(client, check_id, payload)
    print(f"[green]Quality check {result['id']} updated successfully.[/green]")


# ── CRUD: delete ──────────────────────────────────────────────────────────


@checks_app.command("delete")
def checks_delete(
    check_id: int | None = typer.Option(
        None, "--id", help="Single quality check ID to delete"
    ),
    ids: str | None = typer.Option(
        None, "--ids", help='Comma-separated check IDs. Example: "1,2,3"'
    ),
    archive: bool = typer.Option(
        True,
        "--archive/--no-archive",
        help="Soft-delete (archive) or hard-delete",
    ),
):
    """Delete quality check(s)."""
    if not check_id and not ids:
        print("[red]Must specify --id or --ids.[/red]")
        raise typer.Exit(code=1)

    client = get_client()

    if check_id and not ids:
        delete_quality_check(client, check_id, archive=archive)
        action = "Archived" if archive else "Deleted"
        print(f"[green]{action} quality check {check_id}.[/green]")
    else:
        id_list = []
        if check_id:
            id_list.append(check_id)
        if ids:
            id_list.extend(int(x) for x in _parse_comma_list(ids))

        items = [{"id": cid, "archive": archive} for cid in id_list]
        bulk_delete_quality_checks(client, items)
        action = "Archived" if archive else "Deleted"
        print(f"[green]{action} {len(id_list)} quality checks.[/green]")


# ── Export (git-friendly, directory-based) ────────────────────────────────


@checks_app.command("export")
def checks_export(
    datastore_id: int = typer.Option(
        ..., "--datastore-id", help="Datastore ID to export from"
    ),
    output: str = typer.Option(
        "./checks", "--output", "-o", help="Output directory for check files"
    ),
    containers: str | None = typer.Option(
        None,
        "--containers",
        help='Comma-separated container IDs. Example: "1,2,3"',
    ),
    tags: str | None = typer.Option(
        None, "--tags", help='Comma-separated tag names. Example: "tag1,tag2"'
    ),
    status: str | None = typer.Option(
        None, "--status", help="Filter by status: Active, Draft, Archived"
    ),
):
    """Export quality checks to a directory (one file per check, organized by container)."""
    client = get_client()

    container_ids = None
    if containers:
        container_ids = [int(x) for x in _parse_comma_list(containers)]
    tag_list = _parse_comma_list(tags) if tags else None

    archived = None
    api_status = None
    if status:
        if status.lower() == "archived":
            archived = "only"
        else:
            api_status = status.capitalize()

    print(f"[cyan]Fetching quality checks from datastore {datastore_id}...[/cyan]")
    all_checks = list_all_quality_checks(
        client,
        datastore_id,
        containers=container_ids,
        tags=tag_list,
        status=api_status,
        archived=archived,
    )

    if not all_checks:
        print("[yellow]No quality checks found matching the filters.[/yellow]")
        raise typer.Exit(code=0)

    print(f"[cyan]Exporting {len(all_checks)} checks to {output}/...[/cyan]")
    result = export_checks_to_directory(all_checks, output)

    print(
        f"[bold green]Exported {result['exported']} checks "
        f"across {result['containers']} containers to {output}/[/bold green]"
    )


# ── Import (git-friendly, directory-based, multi-datastore) ───────────────


@checks_app.command("import")
def checks_import(
    datastore_id: list[int] = typer.Option(
        ..., "--datastore-id", help="Target datastore ID (repeat for multiple)"
    ),
    input_dir: str = typer.Option(
        "./checks", "--input", "-i", help="Input directory with check files"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview what would be created/updated"
    ),
):
    """Import quality checks from a directory to one or more datastores (upsert)."""
    client = get_client()

    if not os.path.isdir(input_dir):
        print(f"[red]Input directory not found: {input_dir}[/red]")
        raise typer.Exit(code=1)

    checks = load_checks_from_directory(input_dir)
    if not checks:
        print(f"[yellow]No check YAML files found in {input_dir}/[/yellow]")
        raise typer.Exit(code=0)

    print(f"[cyan]Loaded {len(checks)} check definitions from {input_dir}/[/cyan]")

    if dry_run:
        print("[bold yellow]DRY RUN — no changes will be made.[/bold yellow]")

    # Summary table
    summary_table = Table(title="Import Summary")
    summary_table.add_column("Datastore ID", style="cyan")
    summary_table.add_column("Created", style="green")
    summary_table.add_column("Updated", style="yellow")
    summary_table.add_column("Failed", style="red")

    for ds_id in datastore_id:
        print(
            f"\n[cyan]{'[DRY RUN] ' if dry_run else ''}Importing to datastore {ds_id}...[/cyan]"
        )
        result = import_checks_to_datastore(client, ds_id, checks, dry_run=dry_run)

        summary_table.add_row(
            str(ds_id),
            str(result["created"]),
            str(result["updated"]),
            str(result["failed"]),
        )

        for err in result["errors"]:
            print(f"  [red]{err}[/red]")

    console.print(summary_table)


# ── Templates (kept from existing implementation) ─────────────────────────


@checks_app.command("export-templates")
def check_templates_export(
    enrich_datastore_id: int | None = typer.Option(
        None, "--enrichment_datastore_id", help="Enrichment Datastore ID"
    ),
    check_templates: str | None = typer.Option(
        None,
        "--check_templates",
        help='Comma-separated check template IDs. Example: "1,2,3"',
    ),
    status: bool | None = typer.Option(
        None,
        "--status",
        help="Template locked status: true for locked, false for unlocked.",
    ),
    rules: str | None = typer.Option(
        None,
        "--rules",
        help='Comma-separated rule types. Example: "afterDateTime,aggregationComparison"',
    ),
    tags: str | None = typer.Option(
        None,
        "--tags",
        help='Comma-separated tag names. Example: "tag1,tag2"',
    ),
    output: str = typer.Option(
        BASE_PATH + "/data_checks_template.yaml",
        "--output",
        help="Output file path",
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", help="Output format: yaml or json"
    ),
):
    """Export check templates to an enrichment datastore or file."""
    client = get_client()

    if check_templates:
        check_templates = [
            int(x.strip()) for x in check_templates.strip("[]").split(",")
        ]

    if enrich_datastore_id:
        endpoint = f"export/check-templates?enrich_datastore_id={enrich_datastore_id}"
        if check_templates:
            endpoint += "".join(f"&template_ids={tid}" for tid in check_templates)
        response = client.post(endpoint)
        if response.status_code != 204:
            print(
                f"[red]Failed to export check templates. "
                f"Server responded with: {response.status_code} - {response.text}.[/red]"
            )
            raise typer.Exit(code=1)
        print(
            f"[bold green]Check templates exported to "
            f"`_export_check_templates` in enrichment id: {enrich_datastore_id}.[/bold green]"
        )
    else:
        if rules:
            rules = [str(x.strip()) for x in rules.strip("[]").split(",")]
        if tags:
            tags = [str(x.strip()) for x in tags.strip("[]").split(",")]

        # Fetch templates via paginated listing
        params: dict = {"template_only": "true", "size": 100, "page": 1}
        if status is not None:
            params["template_locked"] = str(status).lower()
        if rules:
            params["rule_type"] = rules
        if tags:
            params["tag"] = tags

        page = 1
        all_templates: list[dict] = []
        while True:
            params["page"] = page
            resp = client.get("quality-checks", params=params)
            data = resp.json()
            all_templates.extend(data.get("items", []))
            total = data.get("total", 0)
            if page * 100 >= total:
                break
            page += 1

        if check_templates:
            all_templates = [t for t in all_templates if t["id"] in check_templates]

        if not all_templates:
            print("[red]No check templates found.[/red]")
        else:
            print(
                f"[green]Total check templates exported: {len(all_templates)}[/green]"
            )
            effective_fmt = fmt
            if output.endswith(".json") and fmt == OutputFormat.YAML:
                effective_fmt = OutputFormat.JSON
            dump_data_file(all_templates, output, effective_fmt)
            print(f"[bold green]Data exported to {output}[/bold green]")


@checks_app.command("import-templates")
def check_templates_import(
    input_file: str = typer.Option(
        BASE_PATH + "/data_checks_template.yaml",
        "--input",
        help="Input file path",
    ),
):
    """Import check templates from a file. Only creates new templates, no updates."""
    client = get_client()
    error_log_path = f"/errors-{datetime.now().strftime('%Y-%m-%d')}.log"

    all_check_templates = load_data_file(input_file)
    total_created_templates = 0

    for check_template in track(
        all_check_templates, description="Processing templates..."
    ):
        try:
            additional_metadata = {
                "from quality check id": f"{check_template.get('id', None)}",
            }

            if check_template.get("additional_metadata", None) is None:
                check_template["additional_metadata"] = additional_metadata
            else:
                check_template["additional_metadata"].update(additional_metadata)

            payload = {
                "fields": [field["name"] for field in check_template["fields"]],
                "description": check_template["description"],
                "rule": check_template["rule_type"],
                "coverage": check_template["coverage"],
                "properties": check_template["properties"],
                "tags": [
                    global_tag["name"] for global_tag in check_template["global_tags"]
                ],
                "template_locked": check_template.get("template_locked", False),
                "template_only": True,
                "additional_metadata": check_template.get("additional_metadata", None),
            }

            response = client.post("quality-checks", json=payload)
            print(
                f"[bold green]Check template id: {response.json()['id']} "
                f"created successfully[/bold green]"
            )
            total_created_templates += 1
        except QualyticsAPIError:
            print("[bold red]Error creating check template[/bold red]")
            log_error(
                "Error creating check template.",
                BASE_PATH + error_log_path,
            )
        except Exception as e:
            print(
                f"[bold red]Error processing check template "
                f"{check_template['id']}: {e!s}[/bold red]"
            )
            log_error(
                f"Error processing check template {check_template['id']}. "
                f"Details: {e!s}",
                BASE_PATH + error_log_path,
            )

    print(f"Created a total of {total_created_templates} check templates.")
    distinct_file_content(BASE_PATH + error_log_path)
