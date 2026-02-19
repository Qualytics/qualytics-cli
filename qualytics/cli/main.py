"""Main CLI commands for Qualytics CLI."""

import typer
from typing import Annotated
from rich import print

from ..config import (
    __version__,
    load_config,
    save_config,
    is_token_valid,
    CONFIG_PATH,
)
from ..utils import validate_and_format_url


app = typer.Typer()


@app.callback(invoke_without_command=True)
def version_callback(
    version: Annotated[bool | None, typer.Option("--version", is_eager=True)] = None,
):
    """Display version information."""
    if version:
        print(f"Qualytics CLI Version: {__version__}")
        raise typer.Exit()


@app.command()
def show_config():
    """Display the saved configuration."""
    config = load_config()
    if config:
        print(f"[bold yellow] Config file located in: {CONFIG_PATH} [/bold yellow]")
        print(f"[bold yellow] URL: {config['url']} [/bold yellow]")
        print(f"[bold yellow] Token: {config['token']} [/bold yellow]")

        # Verify token expiration using the separate function
        is_token_valid(config["token"])
    else:
        print("Configuration not found!")


@app.command()
def init(
    url: str = typer.Option(
        ..., help="The URL to be set. Example: https://your-qualytics.qualytics.io/"
    ),
    token: str = typer.Option(..., help="The token to be set."),
):
    """Initialize Qualytics CLI configuration."""
    url = validate_and_format_url(url)

    config = {"url": url, "token": token}

    # Verify token expiration using the separate function
    token_valid = is_token_valid(token)

    if token_valid:
        save_config(config)
        print("[bold green] Configuration saved! [/bold green]")
