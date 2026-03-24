"""CLI commands for team management."""

import typer
from rich import print

from ..api.client import get_client
from ..api.teams import get_team, list_all_teams
from ..utils.serialization import OutputFormat, format_for_display

from . import add_suggestion_callback
from .progress import status

teams_app = typer.Typer(
    name="teams",
    help="List and view teams",
)
add_suggestion_callback(teams_app, "teams")


@teams_app.command("list")
def teams_list(
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """List all teams."""
    client = get_client()

    with status("[bold cyan]Fetching teams...[/bold cyan]"):
        all_teams = list_all_teams(client)

    if not all_teams:
        print("[yellow]No teams found.[/yellow]")
        raise typer.Exit()

    print(f"[bold]Found {len(all_teams)} team(s).[/bold]\n")
    print(format_for_display(all_teams, fmt))


@teams_app.command("get")
def teams_get(
    team_id: int = typer.Option(..., "--id", help="Team ID"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Get a single team by ID."""
    client = get_client()

    with status("[bold cyan]Fetching team...[/bold cyan]"):
        result = get_team(client, team_id)

    print(format_for_display(result, fmt))
