"""CLI commands for container management."""

import typer
from rich import print

from ..api.client import get_client, QualyticsAPIError
from ..api.containers import (
    create_container,
    delete_container,
    get_container,
    get_field_profiles,
    list_all_containers,
    update_container,
    validate_container,
)
from ..services.containers import (
    _ALL_CONTAINER_TYPES,
    _COMPUTED_TYPES,
    _VALID_JOIN_TYPES,
    build_create_container_payload,
    build_update_container_payload,
)
from ..utils import OutputFormat, format_for_display

containers_app = typer.Typer(
    name="containers", help="Create, get, update, delete, and manage containers"
)


# ── helpers ──────────────────────────────────────────────────────────────


def _parse_comma_list(value: str) -> list[str]:
    """Parse '1,2,3' or '[1,2,3]' into a list of stripped strings."""
    return [x.strip() for x in value.strip("[]").split(",") if x.strip()]


# ── create ───────────────────────────────────────────────────────────────


@containers_app.command("create")
def containers_create(
    container_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help="Container type: computed_table, computed_file, or computed_join",
    ),
    name: str = typer.Option(..., "--name", "-n", help="Container name"),
    datastore_id: int | None = typer.Option(
        None,
        "--datastore-id",
        help="Datastore ID (required for computed_table and computed_file)",
    ),
    query: str | None = typer.Option(
        None, "--query", "-q", help="SQL query (required for computed_table)"
    ),
    source_container_id: int | None = typer.Option(
        None,
        "--source-container-id",
        help="Source container ID (required for computed_file)",
    ),
    select_clause: str | None = typer.Option(
        None,
        "--select-clause",
        help="Select clause (required for computed_file and computed_join)",
    ),
    where_clause: str | None = typer.Option(
        None, "--where-clause", help="Where clause (optional filter)"
    ),
    group_by_clause: str | None = typer.Option(
        None, "--group-by-clause", help="Group by clause"
    ),
    left_container_id: int | None = typer.Option(
        None,
        "--left-container-id",
        help="Left container ID (required for computed_join)",
    ),
    right_container_id: int | None = typer.Option(
        None,
        "--right-container-id",
        help="Right container ID (required for computed_join)",
    ),
    left_key_field: str | None = typer.Option(
        None,
        "--left-key-field",
        help="Left join key field (required for computed_join)",
    ),
    right_key_field: str | None = typer.Option(
        None,
        "--right-key-field",
        help="Right join key field (required for computed_join)",
    ),
    left_prefix: str | None = typer.Option(
        None, "--left-prefix", help="Left prefix for joined fields"
    ),
    right_prefix: str | None = typer.Option(
        None, "--right-prefix", help="Right prefix for joined fields"
    ),
    join_type: str | None = typer.Option(
        None, "--join-type", help="Join type: inner, left, right, or full"
    ),
    description: str | None = typer.Option(
        None, "--description", "-d", help="Container description"
    ),
    tags: str | None = typer.Option(None, "--tags", help="Comma-separated tags"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print payload only; no HTTP"
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Create a computed container (computed_table, computed_file, or computed_join)."""
    if container_type not in _COMPUTED_TYPES:
        print(
            f"[red]--type must be one of: {', '.join(sorted(_COMPUTED_TYPES))}.[/red]"
        )
        raise typer.Exit(code=1)

    if join_type is not None and join_type not in _VALID_JOIN_TYPES:
        print(
            f"[red]--join-type must be one of: {', '.join(sorted(_VALID_JOIN_TYPES))}.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        tag_list = _parse_comma_list(tags) if tags else None
        payload = build_create_container_payload(
            container_type,
            datastore_id=datastore_id,
            name=name,
            query=query,
            source_container_id=source_container_id,
            select_clause=select_clause,
            where_clause=where_clause,
            group_by_clause=group_by_clause,
            left_container_id=left_container_id,
            right_container_id=right_container_id,
            left_key_field=left_key_field,
            right_key_field=right_key_field,
            left_prefix=left_prefix,
            right_prefix=right_prefix,
            join_type=join_type,
            description=description,
            tags=tag_list,
        )
    except ValueError as e:
        print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    print("[bold]Container Create Payload:[/bold]")
    print(format_for_display(payload, fmt))

    if dry_run:
        print("[green]Dry run successful. No HTTP request was made.[/green]")
        raise typer.Exit(code=0)

    client = get_client()
    result = create_container(client, payload)
    print("[green]Container created successfully![/green]")
    print(f"[green]Container ID: {result.get('id')}[/green]")
    print(f"[green]Container Name: {result.get('name')}[/green]")
    print(f"[green]Container Type: {result.get('container_type')}[/green]")


# ── update ───────────────────────────────────────────────────────────────


@containers_app.command("update")
def containers_update(
    container_id: int = typer.Option(..., "--id", help="Container ID to update"),
    name: str | None = typer.Option(None, "--name", "-n", help="New container name"),
    query: str | None = typer.Option(
        None, "--query", "-q", help="New SQL query (computed_table)"
    ),
    select_clause: str | None = typer.Option(
        None, "--select-clause", help="New select clause"
    ),
    where_clause: str | None = typer.Option(
        None, "--where-clause", help="New where clause"
    ),
    group_by_clause: str | None = typer.Option(
        None, "--group-by-clause", help="New group by clause"
    ),
    description: str | None = typer.Option(
        None, "--description", "-d", help="New description"
    ),
    tags: str | None = typer.Option(None, "--tags", help="Comma-separated tags"),
    force_drop_fields: bool = typer.Option(
        False,
        "--force-drop-fields",
        help="Allow dropping fields that have associated checks or anomalies",
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Update an existing container (GET-merge-PUT)."""
    client = get_client()

    print(f"[cyan]Fetching container {container_id}...[/cyan]")
    existing = get_container(client, container_id)

    changes: dict = {}
    if name is not None:
        changes["name"] = name
    if query is not None:
        changes["query"] = query
    if select_clause is not None:
        changes["select_clause"] = select_clause
    if where_clause is not None:
        changes["where_clause"] = where_clause
    if group_by_clause is not None:
        changes["group_by_clause"] = group_by_clause
    if description is not None:
        changes["description"] = description
    if tags is not None:
        changes["tags"] = _parse_comma_list(tags)

    if not changes:
        print("[yellow]No fields to update. Provide at least one option.[/yellow]")
        raise typer.Exit(code=1)

    payload = build_update_container_payload(existing, **changes)

    try:
        result = update_container(
            client, container_id, payload, force_drop_fields=force_drop_fields
        )
        print(f"[green]Container {container_id} updated successfully.[/green]")
        print(format_for_display(result, fmt))
    except QualyticsAPIError as e:
        if e.status_code == 409:
            print(
                "[red]409 Conflict: Updating this container would drop fields "
                "that have associated quality checks or anomalies.[/red]"
            )
            print("[yellow]Re-run with --force-drop-fields to proceed.[/yellow]")
            try:
                detail = e.detail
                if detail:
                    print(f"[yellow]Details: {detail}[/yellow]")
            except Exception:
                pass
            raise typer.Exit(code=1)
        raise


# ── get ──────────────────────────────────────────────────────────────────


@containers_app.command("get")
def containers_get(
    container_id: int = typer.Option(..., "--id", help="Container ID"),
    include_profiles: bool = typer.Option(
        False, "--profiles", help="Also fetch field profiles"
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Get a container by ID."""
    client = get_client()
    result = get_container(client, container_id)

    print("[green]Container found:[/green]")
    print(format_for_display(result, fmt))

    if include_profiles:
        profiles = get_field_profiles(client, container_id)
        print("\n[bold]Field Profiles:[/bold]")
        print(format_for_display(profiles, fmt))


# ── list ─────────────────────────────────────────────────────────────────


@containers_app.command("list")
def containers_list(
    datastore_id: int = typer.Option(
        ..., "--datastore-id", help="Datastore ID to list containers from"
    ),
    container_type: str | None = typer.Option(
        None,
        "--type",
        "-t",
        help="Comma-separated container types: table, view, file, computed_table, computed_file, computed_join",
    ),
    name: str | None = typer.Option(None, "--name", help="Filter by name"),
    tag: str | None = typer.Option(None, "--tag", help="Tag name to filter by"),
    search: str | None = typer.Option(
        None, "--search", help="Search string across container fields"
    ),
    archived: str | None = typer.Option(
        None,
        "--archived",
        help="Archive filter: 'only' for archived, 'include' for all",
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """List containers for a datastore."""
    client = get_client()

    type_list = None
    if container_type:
        type_list = _parse_comma_list(container_type)
        invalid = [t for t in type_list if t not in _ALL_CONTAINER_TYPES]
        if invalid:
            print(
                f"[red]Invalid container type(s): {', '.join(invalid)}. "
                f"Valid: {', '.join(sorted(_ALL_CONTAINER_TYPES))}.[/red]"
            )
            raise typer.Exit(code=1)

    tag_list = [tag] if tag else None

    all_containers = list_all_containers(
        client,
        datastore=[datastore_id],
        container_type=type_list,
        name=name,
        tag=tag_list,
        search=search,
        archived=archived,
    )

    print(f"[green]Found {len(all_containers)} containers.[/green]")
    print(format_for_display(all_containers, fmt))


# ── delete ───────────────────────────────────────────────────────────────


@containers_app.command("delete")
def containers_delete(
    container_id: int = typer.Option(..., "--id", help="Container ID to delete"),
):
    """Delete a container by ID. Cascades to fields, checks, and anomalies."""
    client = get_client()
    result = delete_container(client, container_id)
    print(f"[green]Container {container_id} deleted successfully.[/green]")
    if result.get("message"):
        print(f"[green]{result['message']}[/green]")


# ── validate ─────────────────────────────────────────────────────────────


@containers_app.command("validate")
def containers_validate(
    container_type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help="Container type: computed_table, computed_file, or computed_join",
    ),
    name: str = typer.Option(
        "validation_test", "--name", "-n", help="Container name for validation"
    ),
    datastore_id: int | None = typer.Option(
        None,
        "--datastore-id",
        help="Datastore ID (required for computed_table and computed_file)",
    ),
    query: str | None = typer.Option(
        None, "--query", "-q", help="SQL query (required for computed_table)"
    ),
    source_container_id: int | None = typer.Option(
        None, "--source-container-id", help="Source container ID (for computed_file)"
    ),
    select_clause: str | None = typer.Option(
        None, "--select-clause", help="Select clause"
    ),
    where_clause: str | None = typer.Option(
        None, "--where-clause", help="Where clause"
    ),
    group_by_clause: str | None = typer.Option(
        None, "--group-by-clause", help="Group by clause"
    ),
    left_container_id: int | None = typer.Option(
        None, "--left-container-id", help="Left container ID (for computed_join)"
    ),
    right_container_id: int | None = typer.Option(
        None, "--right-container-id", help="Right container ID (for computed_join)"
    ),
    left_key_field: str | None = typer.Option(
        None, "--left-key-field", help="Left join key field"
    ),
    right_key_field: str | None = typer.Option(
        None, "--right-key-field", help="Right join key field"
    ),
    join_type: str | None = typer.Option(
        None, "--join-type", help="Join type: inner, left, right, or full"
    ),
    timeout: int = typer.Option(60, "--timeout", help="Validation timeout in seconds"),
):
    """Validate a computed container definition (dry-run against the API)."""
    if container_type not in _COMPUTED_TYPES:
        print(
            f"[red]--type must be one of: {', '.join(sorted(_COMPUTED_TYPES))}.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        payload = build_create_container_payload(
            container_type,
            datastore_id=datastore_id,
            name=name,
            query=query,
            source_container_id=source_container_id,
            select_clause=select_clause,
            where_clause=where_clause,
            group_by_clause=group_by_clause,
            left_container_id=left_container_id,
            right_container_id=right_container_id,
            left_key_field=left_key_field,
            right_key_field=right_key_field,
            join_type=join_type,
        )
    except ValueError as e:
        print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    client = get_client()
    result = validate_container(client, payload, timeout=timeout)

    if result.get("success"):
        print("[green]Validation passed! Container definition is valid.[/green]")
    else:
        print("[red]Validation failed:[/red]")
        print(result)
