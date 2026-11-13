"""Output streams for commands that emit ``--format`` data.

The structured payload goes to stdout through ``typer.echo`` so it pipes
cleanly into ``jq`` or ``yaml``; status lines, warnings and errors around it
go to stderr through ``err_console`` so they never corrupt that payload.
"""

from rich.console import Console

err_console = Console(stderr=True)
