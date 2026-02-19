"""Configuration management for Qualytics CLI."""

from __future__ import annotations

import json
import os
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

import jwt
from datetime import datetime, timezone
from rich import print

try:
    __version__ = version("qualytics-cli")
except PackageNotFoundError:
    __version__ = "0.4.0"

# Get the home directory
home = Path.home()

# Define the new directory
folder_name = ".qualytics"
BASE_PATH = f"{home}/{folder_name}"

CONFIG_PATH = os.path.expanduser(f"{BASE_PATH}/config.json")
CRONTAB_ERROR_PATH = os.path.expanduser(f"{BASE_PATH}/schedule-operation-errors.txt")
CRONTAB_COMMANDS_PATH = os.path.expanduser(f"{BASE_PATH}/schedule-operation.txt")
OPERATION_ERROR_PATH = os.path.expanduser(f"{BASE_PATH}/operation-error.txt")
DOTENV_PATH = os.path.expanduser(f"{BASE_PATH}/.env")
CONNECTIONS_PATH = os.path.expanduser(f"{BASE_PATH}/config/connections.yml")
PROJECT_CONFIG_PATH = os.path.expanduser(f"{BASE_PATH}/config/config.yml")


# Custom classes
class ConfigError(ValueError):
    pass


def save_config(data):
    """Save configuration data to the config file."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=4)


def load_config():
    """Load configuration data from the config file."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return None


def is_token_valid(token: str):
    """Validate JWT token expiration."""
    try:
        decoded_token = jwt.decode(
            token, algorithms=["none"], options={"verify_signature": False}
        )
        expiration_time = decoded_token.get("exp")

        if expiration_time is not None:
            current_time = datetime.now(timezone.utc).timestamp()
            if not expiration_time >= current_time:
                print(
                    '[bold red] WARNING: Your token is expired, please setup with a new token by running: qualytics init --url "your-qualytics.io/api" --token "my-token" [/bold red]'
                )
                return None
            else:
                return token
        else:
            # Token has no expiration claim - still valid
            return token
    except Exception as e:
        print("[bold red] WARNING: Your token is not valid [/bold red]")
        print(f"[bold red] {e} [/bold red]")
        return None
