"""CLI commands for user management."""

import typer

from ..api.client import get_client
from ..api.users import get_user, list_all_users
from ..utils.serialization import OutputFormat, format_for_display

from . import add_suggestion_callback
from .output import err_console
from .progress import status

users_app = typer.Typer(
    name="users",
    help="List and view users",
)
add_suggestion_callback(users_app, "users")


@users_app.command("list")
def users_list(
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """List all users."""
    client = get_client()

    with status("[bold cyan]Fetching users...[/bold cyan]"):
        all_users = list_all_users(client)

    # An empty result still prints [] so stdout stays parseable.
    if not all_users:
        err_console.print("[yellow]No users found.[/yellow]")
    else:
        err_console.print(f"[bold]Found {len(all_users)} user(s).[/bold]\n")
    typer.echo(format_for_display(all_users, fmt))


@users_app.command("get")
def users_get(
    user_id: int = typer.Option(..., "--id", help="User ID"),
    fmt: OutputFormat = typer.Option(
        OutputFormat.YAML, "--format", "-f", help="Output format: yaml or json"
    ),
):
    """Get a single user by ID."""
    client = get_client()

    with status("[bold cyan]Fetching user...[/bold cyan]"):
        result = get_user(client, user_id)

    typer.echo(format_for_display(result, fmt))
