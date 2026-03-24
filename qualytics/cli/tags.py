"""CLI commands for tag management."""

import typer
from rich import print

from ..api.client import get_client, QualyticsAPIError
from ..api.tags import create_tag, delete_tag, get_tag, list_all_tags
from ..utils.serialization import OutputFormat, format_for_display

from . import add_suggestion_callback
from .progress import status

tags_app = typer.Typer(
    name="tags",
    help="Manage tags",
)
add_suggestion_callback(tags_app, "tags")


@tags_app.command("list")
def tags_list(
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """List all tags."""
    client = get_client()

    with status("[bold cyan]Fetching tags...[/bold cyan]"):
        all_tags = list_all_tags(client)

    if not all_tags:
        print("[yellow]No tags found.[/yellow]")
        raise typer.Exit()

    print(f"[bold]Found {len(all_tags)} tag(s).[/bold]\n")
    print(format_for_display(all_tags, fmt))


@tags_app.command("get")
def tags_get(
    tag_id: int = typer.Option(..., "--id", help="Tag ID"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Get a single tag by ID."""
    client = get_client()

    with status("[bold cyan]Fetching tag...[/bold cyan]"):
        result = get_tag(client, tag_id)

    print(format_for_display(result, fmt))


@tags_app.command("create")
def tags_create(
    name: str = typer.Option(..., "--name", "-n", help="Tag name"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Create a new tag."""
    client = get_client()
    payload = {"name": name}

    result = create_tag(client, payload)
    print(f"[green]Tag created successfully![/green]")
    print(f"[green]Tag ID: {result.get('id')}[/green]\n")
    print(format_for_display(result, fmt))


@tags_app.command("delete")
def tags_delete(
    tag_id: int = typer.Option(..., "--id", help="Tag ID to delete"),
):
    """Delete a tag by ID."""
    client = get_client()

    try:
        delete_tag(client, tag_id)
        print(f"[green]Tag {tag_id} deleted successfully.[/green]")
    except QualyticsAPIError as e:
        print(f"[red]Failed to delete tag {tag_id}: {e.message}[/red]")
        raise typer.Exit(code=1)
