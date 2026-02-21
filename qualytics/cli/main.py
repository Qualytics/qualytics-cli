"""Main CLI commands for Qualytics CLI."""

import typer
from typing import Annotated
from rich import print

from ..config import __version__


app = typer.Typer()


@app.callback(invoke_without_command=True)
def version_callback(
    version: Annotated[bool | None, typer.Option("--version", is_eager=True)] = None,
):
    """Display version information."""
    if version:
        print(f"Qualytics CLI Version: {__version__}")
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
