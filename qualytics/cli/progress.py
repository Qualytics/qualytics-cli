"""Reusable progress indicators for CLI commands."""

import os
import sys
from contextlib import contextmanager

from rich.console import Console

_console = Console()


def _quiet() -> bool:
    """Return True when progress indicators should be suppressed."""
    return (
        not sys.stdout.isatty()
        or bool(os.environ.get("QUALYTICS_NO_BANNER"))
        or bool(os.environ.get("CI"))
    )


@contextmanager
def status(message: str):
    """Show a Rich spinner with *message* while work is in progress.

    No-op when output is piped, or ``CI`` / ``QUALYTICS_NO_BANNER`` is set.
    """
    if _quiet():
        yield
    else:
        with _console.status(message, spinner="dots"):
            yield
