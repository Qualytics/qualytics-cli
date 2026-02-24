"""
Qualytics CLI - Main Entry Point (Refactored)

This is the new streamlined entry point that wires together all CLI modules.
"""

from dotenv import load_dotenv

# Import main app and commands from cli modules
from .cli.main import app
from .cli.checks import checks_app
from .cli.schedule import schedule_app
from .cli.operations import operations_app
from .cli.datastores import datastores_app
from .cli.connections import connections_app
from .cli.containers import containers_app
from .cli.anomalies import anomalies_app
from .cli.auth import auth_app
from .cli.export_import import export_import_app
from .cli.mcp_cmd import mcp_app
from .cli.doctor import doctor

# Import config for environment setup
from .config import DOTENV_PATH


# Load environment variables
load_dotenv(DOTENV_PATH)


# Add all sub-apps to the main app
app.add_typer(checks_app, name="checks")
app.add_typer(schedule_app, name="schedule")
app.add_typer(operations_app, name="operations")
app.add_typer(datastores_app, name="datastores")
app.add_typer(connections_app, name="connections")
app.add_typer(containers_app, name="containers")
app.add_typer(anomalies_app, name="anomalies")
app.add_typer(auth_app, name="auth")
app.add_typer(export_import_app, name="config")
app.add_typer(mcp_app, name="mcp")
app.command("doctor", help="Check CLI health and connectivity")(doctor)


if __name__ == "__main__":
    app()
