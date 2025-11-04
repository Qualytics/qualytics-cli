"""
Qualytics CLI - Main Entry Point (Refactored)

This is the new streamlined entry point that wires together all CLI modules.
"""
from __future__ import annotations

import urllib3
from dotenv import load_dotenv

# Import main app and commands from cli modules
from .cli.main import app
from .cli.checks import checks_app
from .cli.schedule import schedule_app
from .cli.operations import run_operation_app, check_operation_app
from .cli.datastores import datastore_app

# Import config for environment setup
from .setup import DOTENV_PATH


# Load environment variables
load_dotenv(DOTENV_PATH)

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Add all sub-apps to the main app
app.add_typer(checks_app, name="checks")
app.add_typer(schedule_app, name="schedule")
app.add_typer(run_operation_app, name="run")
app.add_typer(check_operation_app, name="operation")
app.add_typer(datastore_app, name="datastore")


if __name__ == "__main__":
    app()
