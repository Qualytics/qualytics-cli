"""Configuration management for Qualytics CLI."""

import json
import os
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path

import jwt
import yaml
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

CONFIG_PATH = os.path.expanduser(f"{BASE_PATH}/config.yaml")
CONFIG_PATH_LEGACY = os.path.expanduser(f"{BASE_PATH}/config.json")
CRONTAB_ERROR_PATH = os.path.expanduser(f"{BASE_PATH}/schedule-operation-errors.txt")
CRONTAB_COMMANDS_PATH = os.path.expanduser(f"{BASE_PATH}/schedule-operation.txt")
OPERATION_ERROR_PATH = os.path.expanduser(f"{BASE_PATH}/operation-error.txt")
DOTENV_PATH = os.path.expanduser(f"{BASE_PATH}/.env")
PROJECT_CONFIG_PATH = os.path.expanduser(f"{BASE_PATH}/config/config.yml")


# Custom classes
class ConfigError(ValueError):
    pass


def save_config(data):
    """Save configuration data to the config file (YAML format)."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(
            data, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )


def load_config():
    """Load configuration data from the config file.

    Checks for ``config.yaml`` first, then falls back to the legacy
    ``config.json``.  When the legacy file is found it is automatically
    migrated to YAML.
    """
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)

    # Fall back to legacy JSON config and auto-migrate
    if os.path.exists(CONFIG_PATH_LEGACY):
        with open(CONFIG_PATH_LEGACY) as f:
            data = json.load(f)
        save_config(data)
        print(
            f"[bold yellow] Migrated config from {CONFIG_PATH_LEGACY} to {CONFIG_PATH}. "
            f"You can safely remove the old config.json file. [/bold yellow]"
        )
        return data

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
                    '[bold red] WARNING: Your token is expired, please setup with a new token by running: qualytics auth init --url "your-qualytics.io" --token "my-token" [/bold red]'
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
