"""Main CLI commands for Qualytics CLI."""

import typer
from typing import Annotated
from rich import print

from ..config import __version__
from . import BRAND, print_banner


app = typer.Typer()


@app.callback(invoke_without_command=True)
def version_callback(
    ctx: typer.Context,
    version: Annotated[bool | None, typer.Option("--version", is_eager=True)] = None,
):
    """Display version information."""
    if version:
        print(f"Qualytics CLI Version: {__version__}")
        raise typer.Exit()

    if ctx.invoked_subcommand is not None:
        return

    print_banner()

    # Show available command groups when invoked without a subcommand
    click_group = ctx.command
    commands = click_group.list_commands(ctx)

    visible = []
    for name in commands:
        cmd = click_group.get_command(ctx, name)
        if cmd and not cmd.hidden:
            help_text = cmd.get_short_help_str(limit=60) if cmd.help else ""
            visible.append((name, help_text))

    if visible:
        print(f"[bold]Available commands:[/bold]\n")
        max_name = max(len(name) for name, _ in visible)
        for name, help_text in visible:
            print(f"  [{BRAND}]{name:<{max_name}}[/{BRAND}]  {help_text}")

    print("\nRun [bold]'qualytics --help'[/bold] for more details.\n")
    raise typer.Exit()


@app.command(hidden=True, deprecated=True)
def show_config():
    """[Deprecated] Use 'qualytics auth status' instead."""
    print(
        "[bold yellow]Warning: 'qualytics show-config' is deprecated. "
        "Use 'qualytics auth status' instead.[/bold yellow]\n"
    )
    from .auth import auth_status

    auth_status()


@app.command(hidden=True, deprecated=True)
def init(
    url: str = typer.Option(
        ..., help="The URL to be set. Example: https://your-qualytics.qualytics.io/"
    ),
    token: str = typer.Option(..., help="The token to be set."),
    no_verify_ssl: bool = typer.Option(
        False,
        "--no-verify-ssl",
        help="Disable SSL certificate verification for API requests.",
    ),
):
    """[Deprecated] Use 'qualytics auth init' instead."""
    print(
        "[bold yellow]Warning: 'qualytics init' is deprecated. "
        "Use 'qualytics auth init' instead.[/bold yellow]\n"
    )
    from .auth import auth_init

    auth_init(url=url, token=token, no_verify_ssl=no_verify_ssl)
