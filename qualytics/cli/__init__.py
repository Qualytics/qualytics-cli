"""CLI command modules for Qualytics CLI."""

import difflib
import os

import click
import typer
import typer.core
from rich import print

from ..config import __version__

# Qualytics brand color
BRAND = "#FF9933"


class SuggestGroup(typer.core.TyperGroup):
    """Typer group that suggests similar commands on typos."""

    def resolve_command(self, ctx: click.Context, args: list[str]):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            cmd_name = args[0] if args else None
            if cmd_name:
                valid = self.list_commands(ctx)
                matches = difflib.get_close_matches(cmd_name, valid, n=3, cutoff=0.6)
                if matches:
                    hint = ", ".join(f"'{m}'" for m in matches)
                    raise click.UsageError(
                        f"No such command '{cmd_name}'. Did you mean: {hint}?"
                    )
                raise click.UsageError(
                    f"No such command '{cmd_name}'. "
                    f"Run 'qualytics --help' to see available commands."
                )
            raise


# fmt: off
# Wordmark traced from official SVG (qualytics-word-mark.svg).
# Each letter rendered independently to guarantee vertical alignment.
LOGO = [
    "   ▄▄███▀ ▄▄▄▄",
    "  ██▀       ▀██▄                      ██            ███   ▀█",
    " ██           ██ ██     ██  ▄█▀▀▀▀███ ██ ▀█▄   ▄██▀▀███▀▀ ██  ██▀▀▀██▄ ▄██▀▀██▄",
    " ██▄         ▄██ ██     ██ ██      ██ ██  ██▄  ██   ███   ██ ██     ▀▀  ▀██▄▄▄▄",
    "  ▀██▄▄▄▄▄▄▄██▀  ▀█▄▄  ▄██ ▀█▄▄  ▄▄██ ██   ██▄██    ███   ██ ▀█▄▄  ▄██ ██▄  ▄██",
    "     ▀▀▀▀▀▀▀▀▀▀▀  ▀▀▀▀▀▀▀▀   ▀▀▀▀▀▀▀▀ ▀▀    ▀██▀    ▀▀▀   ▀▀   ▀▀▀▀▀▀   ▀▀▀▀▀▀",
    "                                            ▄█▀",
]
# fmt: on


def print_banner(subtitle: str | None = None) -> None:
    """Print the Qualytics logo banner.

    Suppressed when ``QUALYTICS_NO_BANNER`` or ``CI`` env vars are set.
    *subtitle* replaces the default auth-status line (e.g. ``"Doctor"``).
    """
    if os.environ.get("QUALYTICS_NO_BANNER") or os.environ.get("CI"):
        return

    if subtitle is None:
        from ..config import CONFIG_PATH, load_config

        if not os.path.exists(CONFIG_PATH):
            subtitle = (
                f"[yellow]○[/yellow] [dim]Not configured — run[/dim] "
                "[bold]qualytics auth init[/bold]"
            )
        else:
            config = load_config()
            if not config or not config.get("token"):
                subtitle = (
                    f"[yellow]○[/yellow] [dim]Not configured — run[/dim] "
                    "[bold]qualytics auth init[/bold]"
                )
            else:
                url = config.get("url", "")
                display_url = url.rstrip("/") if url else ""
                subtitle = f"[{BRAND}]✓[/{BRAND}] [dim]Connected to[/dim] {display_url}"

    print()
    for line in LOGO:
        print(f"[bold {BRAND}]{line}[/bold {BRAND}]")
    print()
    print(f"  [bold]v{__version__}[/bold]  [dim]·[/dim]  {subtitle}")
    print()


def add_suggestion_callback(app: typer.Typer, group_name: str) -> None:
    """Add a callback that shows available commands when no subcommand is given.

    Replaces the unhelpful "Missing command." error with a list of
    available subcommands and a pointer to ``--help``.
    Also enables fuzzy "did you mean?" suggestions for invalid subcommands.

    Must be called **before** the app is registered via ``add_typer``.
    """
    app.info.cls = SuggestGroup

    @app.callback(invoke_without_command=True)
    def _show_commands(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is not None:
            return

        click_group = ctx.command
        commands = click_group.list_commands(ctx)

        # Filter out hidden commands
        visible = []
        for name in commands:
            cmd = click_group.get_command(ctx, name)
            if cmd and not cmd.hidden:
                help_text = cmd.get_short_help_str(limit=60) if cmd.help else ""
                visible.append((name, help_text))

        if visible:
            print(f"\n[bold]Available commands:[/bold]\n")
            max_name = max(len(name) for name, _ in visible)
            for name, help_text in visible:
                print(f"  [{BRAND}]{name:<{max_name}}[/{BRAND}]  {help_text}")

        print(f"\nRun [bold]'qualytics {group_name} --help'[/bold] for more details.\n")
        raise typer.Exit()
