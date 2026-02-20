"""
Qualytics CLI - Main Entry Point (Refactored)

This is the new streamlined entry point that wires together all CLI modules.
"""

from dotenv import load_dotenv

# Import main app and commands from cli modules
from .cli.main import app
from .cli.checks import checks_app
from .cli.schedule import schedule_app
from .cli.operations import run_operation_app, check_operation_app
from .cli.datastores import datastore_app
from .cli.computed_tables import computed_tables_app
from .cli.anomalies import anomalies_app

# Import config for environment setup
from .config import DOTENV_PATH


# Load environment variables
load_dotenv(DOTENV_PATH)


# Add all sub-apps to the main app
app.add_typer(checks_app, name="checks")
app.add_typer(schedule_app, name="schedule")
app.add_typer(run_operation_app, name="run")
app.add_typer(check_operation_app, name="operation")
app.add_typer(datastore_app, name="datastore")
app.add_typer(computed_tables_app, name="computed-tables")
app.add_typer(anomalies_app, name="anomalies")


if __name__ == "__main__":
    app()
