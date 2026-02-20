"""Connection service functions."""

from ..api.client import QualyticsClient
from ..api.connections import list_connections


def get_connection_by(
    client: QualyticsClient,
    connection_id: int | None = None,
    connection_name: str | None = None,
) -> dict | None:
    """Get connection from Qualytics API by ID or name.

    Handles pagination to search through all connections.

    Returns:
        dict: The connection object if found
        None: If connection not found
    """
    if connection_id is None and connection_name is None:
        raise ValueError("Either connection_id or connection_name must be provided")

    if connection_id is not None and connection_name is not None:
        raise ValueError(
            "Cannot specify both connection_id and connection_name. Please use only one."
        )

    page = 1
    size = 50

    while True:
        data = list_connections(client, page=page, size=size)

        if "items" not in data:
            raise ValueError(
                f"Unexpected API response format. Expected 'items' field but got: {list(data.keys())}"
            )

        connections = data["items"]

        for connection in connections:
            if connection_id is not None and connection.get("id") == connection_id:
                return connection
            if (
                connection_name is not None
                and connection.get("name") == connection_name
            ):
                return connection

        if len(connections) < size:
            break

        page += 1

    return None


def get_connection_by_name(client: QualyticsClient, name: str) -> dict | None:
    """Find a connection by exact name via paginated search."""
    return get_connection_by(client, connection_name=name)


def build_create_connection_payload(
    connection_type: str,
    *,
    name: str | None = None,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    uri: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    catalog: str | None = None,
    jdbc_fetch_size: int | None = None,
    max_parallelization: int | None = None,
    parameters: dict | None = None,
) -> dict:
    """Build a payload for creating a connection.

    The *connection_type* determines which fields are relevant.
    A ``--parameters`` JSON catch-all is merged last so it can supply
    any type-specific fields not covered by dedicated flags.
    """
    payload: dict = {"type": connection_type}

    if name is not None:
        payload["name"] = name

    # JDBC-style connections
    if host is not None:
        payload["host"] = host
    if port is not None:
        payload["port"] = port
    if username is not None:
        payload["username"] = username
    if password is not None:
        payload["password"] = password

    # DFS-style connections
    if uri is not None:
        payload["uri"] = uri
    if access_key is not None:
        payload["access_key"] = access_key
    if secret_key is not None:
        payload["secret_key"] = secret_key

    # Native (Databricks, etc.)
    if catalog is not None:
        payload["catalog"] = catalog

    # Tuning
    if jdbc_fetch_size is not None:
        payload["jdbc_fetch_size"] = jdbc_fetch_size
    if max_parallelization is not None:
        payload["max_parallelization"] = max_parallelization

    # Merge the catch-all parameters dict last (overrides dedicated flags)
    if parameters is not None:
        payload.update(parameters)

    return payload


def build_update_connection_payload(**changes) -> dict:
    """Build a partial-update payload for a connection.

    Only non-None values are included.
    """
    payload: dict = {}

    for key, value in changes.items():
        if value is not None:
            payload[key] = value

    return payload
