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
    __version__ = "1.0.0"

# Get the home directory
home = Path.home()

# Define the new directory
folder_name = ".qualytics"
# QUALYTICS_CONFIG_HOME points the CLI at an alternate config directory,
# allowing side-by-side instance profiles (e.g. one directory per deployment).
BASE_PATH = os.environ.get("QUALYTICS_CONFIG_HOME") or f"{home}/{folder_name}"

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


def _config_from_env():
    """Build a configuration dict from environment variables, if present.

    ``QUALYTICS_URL`` and ``QUALYTICS_TOKEN`` must be set together; setting
    only one is treated as a misconfiguration rather than silently falling
    back to the on-disk config. ``QUALYTICS_SSL_VERIFY=0|false|no`` disables
    certificate verification for the env-configured instance.
    """
    url = os.environ.get("QUALYTICS_URL")
    token = os.environ.get("QUALYTICS_TOKEN")
    if not url and not token:
        return None
    if not (url and token):
        missing = "QUALYTICS_TOKEN" if url else "QUALYTICS_URL"
        print(
            f"[bold red]QUALYTICS_URL and QUALYTICS_TOKEN must be set together; "
            f"{missing} is missing.[/bold red]"
        )
        raise SystemExit(1)
    config = {"url": url, "token": token}
    ssl_verify = os.environ.get("QUALYTICS_SSL_VERIFY")
    if ssl_verify is not None:
        config["ssl_verify"] = ssl_verify.strip().lower() not in {"0", "false", "no"}
    return config


def load_config():
    """Resolve the effective configuration.

    The ``QUALYTICS_URL``/``QUALYTICS_TOKEN`` environment pair takes
    precedence over the on-disk configuration. Otherwise checks for
    ``config.yaml`` first, then falls back to the legacy ``config.json``.
    When the legacy file is found it is automatically migrated to YAML.
    """
    env_config = _config_from_env()
    if env_config is not None:
        return env_config

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
