"""YAML configuration loader utilities."""
import os
import yaml
from dotenv import load_dotenv


def load_connections(yaml_path: str, env_path: str = ".env"):
    """Load .env variables, then YAML, expanding env vars."""
    load_dotenv(env_path)  # loads variables from .env into os.environ

    with open(yaml_path) as f:
        raw = os.path.expandvars(f.read())  # substitutes ${VAR} from .env
        config = yaml.safe_load(raw)
    return config.get("connections", {})


def get_connection(yaml_path: str, name: str, env_path: str = ".env"):
    """
    Get a connection by its name field (not the type key).
    Searches through all connections and finds the one matching the name field.
    """
    connections = load_connections(yaml_path, env_path)

    # Search for connection by name field
    for conn_key, conn_data in connections.items():
        if conn_data.get("name") == name:
            return conn_data

    # If not found, raise error
    raise ValueError(
        f"Connection with name '{name}' not found in YAML. "
        f"Available connections: {[c.get('name') for c in connections.values()]}"
    )
