"""CLI commands for anomalies."""

import typer
from rich import print

from ..api.client import get_client
from ..api.anomalies import (
    get_anomaly,
    list_all_anomalies,
    update_anomaly,
    bulk_update_anomalies,
    delete_anomaly,
    bulk_delete_anomalies,
)
from ..utils import OutputFormat, format_for_display

anomalies_app = typer.Typer(name="anomalies", help="Commands for handling anomalies")

# Valid statuses for update (open) and archive
_OPEN_STATUSES = {"Active", "Acknowledged"}
_ARCHIVE_STATUSES = {"Resolved", "Invalid", "Duplicate", "Discarded"}


# ── Helpers ───────────────────────────────────────────────────────────────


def _parse_comma_list(value: str) -> list[str]:
    """Parse '1,2,3' or '[1,2,3]' into a list of stripped strings."""
    return [x.strip() for x in value.strip("[]").split(",") if x.strip()]


# ── get ──────────────────────────────────────────────────────────────────


@anomalies_app.command("get")
def anomalies_get(
    anomaly_id: int = typer.Option(..., "--id", help="Anomaly ID"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", help="Output format: yaml or json"
    ),
):
    """Get a single anomaly by ID."""
    client = get_client()
    result = get_anomaly(client, anomaly_id)
    print(format_for_display(result, fmt))


# ── list ─────────────────────────────────────────────────────────────────


@anomalies_app.command("list")
def anomalies_list(
    datastore_id: int = typer.Option(
        ..., "--datastore-id", help="Datastore ID to list anomalies from"
    ),
    container: int | None = typer.Option(
        None, "--container", help="Container ID to filter by"
    ),
    check_id: int | None = typer.Option(
        None, "--check-id", help="Quality check ID to filter by"
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Comma-separated statuses: Active, Acknowledged, Resolved, etc.",
    ),
    anomaly_type: str | None = typer.Option(
        None, "--type", help="Anomaly type: shape or record"
    ),
    tag: str | None = typer.Option(None, "--tag", help="Tag name to filter by"),
    start_date: str | None = typer.Option(
        None, "--start-date", help="Start date (YYYY-MM-DD)"
    ),
    end_date: str | None = typer.Option(
        None, "--end-date", help="End date (YYYY-MM-DD)"
    ),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", help="Output format: yaml or json"
    ),
):
    """List anomalies for a datastore."""
    client = get_client()

    # Handle archived as a special status
    archived = None
    api_status = None
    if status:
        statuses = _parse_comma_list(status)
        # If any archived status is requested, use archived filter
        archive_vals = [s for s in statuses if s in _ARCHIVE_STATUSES]
        open_vals = [s for s in statuses if s in _OPEN_STATUSES]
        if archive_vals and not open_vals:
            archived = "only"
            api_status = ",".join(archive_vals)
        elif archive_vals:
            # Mixed — pass as-is, let API handle
            api_status = ",".join(statuses)
        else:
            api_status = ",".join(statuses)

    tag_list = [tag] if tag else None

    all_anomalies = list_all_anomalies(
        client,
        datastore=datastore_id,
        container=container,
        quality_check=check_id,
        status=api_status,
        anomaly_type=anomaly_type,
        tag=tag_list,
        start_date=start_date,
        end_date=end_date,
        archived=archived,
    )

    print(f"[green]Found {len(all_anomalies)} anomalies.[/green]")
    print(format_for_display(all_anomalies, fmt))


# ── update ───────────────────────────────────────────────────────────────


@anomalies_app.command("update")
def anomalies_update(
    anomaly_id: int | None = typer.Option(
        None, "--id", help="Single anomaly ID to update"
    ),
    ids: str | None = typer.Option(
        None,
        "--ids",
        help='Comma-separated anomaly IDs for bulk update. Example: "1,2,3"',
    ),
    status: str = typer.Option(
        ..., "--status", help="New status: Active or Acknowledged"
    ),
    description: str | None = typer.Option(
        None, "--description", help="Update description"
    ),
    tags: str | None = typer.Option(None, "--tags", help="Comma-separated tag names"),
):
    """Update anomaly status (Active or Acknowledged)."""
    if not anomaly_id and not ids:
        print("[red]Must specify --id or --ids.[/red]")
        raise typer.Exit(code=1)

    if status not in _OPEN_STATUSES:
        print(
            f"[red]Invalid status '{status}'. "
            f"Use 'Active' or 'Acknowledged'. "
            f"For archived statuses, use 'anomalies archive'.[/red]"
        )
        raise typer.Exit(code=1)

    client = get_client()

    if anomaly_id and not ids:
        # Single update via PUT
        payload: dict = {"status": status}
        if description is not None:
            payload["description"] = description
        if tags:
            payload["tags"] = _parse_comma_list(tags)
        result = update_anomaly(client, anomaly_id, payload)
        print(f"[green]Anomaly {result['id']} updated to '{status}'.[/green]")
    else:
        # Bulk update via PATCH
        id_list: list[int] = []
        if anomaly_id:
            id_list.append(anomaly_id)
        if ids:
            id_list.extend(int(x) for x in _parse_comma_list(ids))

        items = [{"id": aid, "status": status} for aid in id_list]
        bulk_update_anomalies(client, items)
        print(f"[green]Updated {len(id_list)} anomalies to '{status}'.[/green]")


# ── archive ──────────────────────────────────────────────────────────────


@anomalies_app.command("archive")
def anomalies_archive(
    anomaly_id: int | None = typer.Option(
        None, "--id", help="Single anomaly ID to archive"
    ),
    ids: str | None = typer.Option(
        None,
        "--ids",
        help='Comma-separated anomaly IDs for bulk archive. Example: "1,2,3"',
    ),
    status: str = typer.Option(
        "Resolved",
        "--status",
        help="Archive status: Resolved, Invalid, Duplicate, or Discarded",
    ),
):
    """Archive anomalies (soft-delete with status)."""
    if not anomaly_id and not ids:
        print("[red]Must specify --id or --ids.[/red]")
        raise typer.Exit(code=1)

    if status not in _ARCHIVE_STATUSES:
        print(
            f"[red]Invalid archive status '{status}'. "
            f"Must be one of: {', '.join(sorted(_ARCHIVE_STATUSES))}.[/red]"
        )
        raise typer.Exit(code=1)

    client = get_client()

    if anomaly_id and not ids:
        delete_anomaly(client, anomaly_id, archive=True, status=status)
        print(f"[green]Anomaly {anomaly_id} archived as '{status}'.[/green]")
    else:
        id_list: list[int] = []
        if anomaly_id:
            id_list.append(anomaly_id)
        if ids:
            id_list.extend(int(x) for x in _parse_comma_list(ids))

        items = [{"id": aid, "archive": True, "status": status} for aid in id_list]
        bulk_delete_anomalies(client, items)
        print(f"[green]Archived {len(id_list)} anomalies as '{status}'.[/green]")


# ── delete ───────────────────────────────────────────────────────────────


@anomalies_app.command("delete")
def anomalies_delete(
    anomaly_id: int | None = typer.Option(
        None, "--id", help="Single anomaly ID to delete"
    ),
    ids: str | None = typer.Option(
        None,
        "--ids",
        help='Comma-separated anomaly IDs for bulk delete. Example: "1,2,3"',
    ),
):
    """Permanently delete anomalies (hard-delete)."""
    if not anomaly_id and not ids:
        print("[red]Must specify --id or --ids.[/red]")
        raise typer.Exit(code=1)

    client = get_client()

    if anomaly_id and not ids:
        delete_anomaly(client, anomaly_id, archive=False)
        print(f"[green]Deleted anomaly {anomaly_id}.[/green]")
    else:
        id_list: list[int] = []
        if anomaly_id:
            id_list.append(anomaly_id)
        if ids:
            id_list.extend(int(x) for x in _parse_comma_list(ids))

        items = [{"id": aid, "archive": False} for aid in id_list]
        bulk_delete_anomalies(client, items)
        print(f"[green]Deleted {len(id_list)} anomalies.[/green]")
