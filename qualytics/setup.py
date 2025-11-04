"""Configuration management for Qualytics CLI."""
from __future__ import annotations

import json
import os
from pathlib import Path

import jwt
from datetime import datetime, timezone
from rich import print


__version__ = "0.2.0"

# Get the home directory
home = Path.home()

# Define the new directory
folder_name = ".qualytics"
BASE_PATH = f"{home}/{folder_name}"

# Helper functions to get local project paths dynamically (at runtime)
def get_local_base_path():
    """Get the current working directory at runtime."""
    return os.getcwd()

def get_local_config_dir():
    """Get the config directory path in current working directory."""
    return os.path.join(get_local_base_path(), "config")

def get_local_assets_dir():
    """Get the assets directory path in current working directory."""
    return os.path.join(get_local_base_path(), "assets")


# Backwards compatibility - these will be deprecated
LOCAL_BASE_PATH = None  # Use get_local_base_path() instead
LOCAL_CONFIG_DIR = None  # Use get_local_config_dir() instead
LOCAL_ASSETS_DIR = None  # Use get_local_assets_dir() instead

CONFIG_PATH = os.path.expanduser(f"{BASE_PATH}/config.json")
DOTENV_PATH = os.path.expanduser(f"{BASE_PATH}/.env")
CRONTAB_ERROR_PATH = os.path.expanduser(f"{BASE_PATH}/schedule-operation-errors.txt")
CRONTAB_COMMANDS_PATH = os.path.expanduser(f"{BASE_PATH}/schedule-operation.txt")
OPERATION_ERROR_PATH = os.path.expanduser(f"{BASE_PATH}/operation-error.txt")
CONNECTIONS_PATH = os.path.expanduser(f"{BASE_PATH}/config/connections.yml")


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

def save_local_env_config(url: str, token: str):
    """Save configuration data to the .env file in the home directory's .qualytics folder."""
    # Ensure the .qualytics directory exists in home directory
    os.makedirs(os.path.dirname(DOTENV_PATH), exist_ok=True)

    # Create .env file with the configuration
    with open(DOTENV_PATH, "w") as f:
        f.write(f'QUALYTICS_URL="{url}"\n')
        f.write(f'QUALYTICS_API_TOKEN="{token}"\n')


def load_local_env_config():
    """Load configuration data from the .env file in the home directory's .qualytics folder."""
    if os.path.exists(DOTENV_PATH):
        config = {}
        with open(DOTENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    # Remove quotes from value if present
                    value = value.strip('"').strip("'")
                    if key == "QUALYTICS_URL":
                        config["url"] = value
                    elif key == "QUALYTICS_API_TOKEN":
                        config["token"] = value
        return config if config else None
    return None


def get_config():
    """
    Load configuration with backward compatibility.
    Checks .env file first, falls back to JSON config with migration reminder.
    """
    # Try loading from new .env file first
    config = load_local_env_config()

    if config:
        return config

    # Fall back to old JSON config
    config = load_config()

    if config:
        print("[bold yellow] You are using the old configuration format. [/bold yellow]")
        print("[bold yellow] Please run 'qualytics init' to migrate to the new .env format. [/bold yellow]")
        return config

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
    except Exception as e:
        print("[bold red] WARNING: Your token is not valid [/bold red]")
        print(f"[bold red] {e} [/bold red]")
