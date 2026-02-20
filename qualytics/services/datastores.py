"""Datastore service functions."""

from ..api.client import QualyticsClient


def get_connection_by(
    client: QualyticsClient, connection_id: int = None, connection_name: str = None
):
    """
    Get connection from Qualytics API by ID or name.
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

    endpoint = "connections"

    # Pagination parameters
    page = 1
    size = 50

    while True:
        url = f"{endpoint}?page={page}&size={size}"
        response = client.get(url)

        data = response.json()

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


def get_datastore_by(
    client: QualyticsClient, datastore_id: int = None, datastore_name: str = None
):
    """
    Get datastore from Qualytics API by ID or name.
    Handles pagination to search through all datastores.

    Returns:
        dict: The datastore object if found
        None: If datastore not found
    """
    if datastore_id is None and datastore_name is None:
        raise ValueError("Either datastore_id or datastore_name must be provided")

    if datastore_id is not None and datastore_name is not None:
        raise ValueError(
            "Cannot specify both datastore_id and datastore_name. Please use only one."
        )

    endpoint = "datastores/listing"

    page = 1
    size = 50

    while True:
        url = f"{endpoint}?page={page}&size={size}"
        response = client.get(url)

        data = response.json()

        datastores = data if isinstance(data, list) else data.get("items", [])

        for datastore in datastores:
            if datastore_id is not None and datastore.get("id") == datastore_id:
                return datastore
            if datastore_name is not None and datastore.get("name") == datastore_name:
                return datastore

        if len(datastores) < size:
            break

        page += 1

    return None


def build_create_datastore_payload(
    *,
    cfg: dict | None,
    name: str,
    connection_id: int | None = None,
    tags: list[str] | None = None,
    teams: list[str] | None = None,
    enrichment_only: bool = False,
    enrichment_prefix: str | None = None,
    enrichment_source_record_limit: int | None = None,
    enrichment_remediation_strategy: str = "none",
    high_count_rollup_threshold: int | None = None,
    trigger_catalog: bool = True,
    database: str,
    schema: str,
) -> dict:
    """Build a payload for creating a datastore."""
    payload: dict = {
        "name": name,
        "enrichment_only": enrichment_only,
        "enrichment_remediation_strategy": enrichment_remediation_strategy,
        "trigger_catalog": trigger_catalog,
        "tags": tags,
        "teams": teams,
        "database": database,
        "schema": schema,
    }

    if connection_id is not None:
        payload["connection_id"] = int(connection_id)
    elif cfg is not None:
        params = cfg["parameters"]
        connection: dict = {
            "name": cfg["name"],
            "type": cfg["type"],
            "host": params["host"],
            "port": params["port"],
            "username": params["user"],
            "password": params["password"],
        }

        payload["connection"] = connection
    else:
        raise ValueError("Either cfg or connection_id must be provided")
    if enrichment_prefix is not None:
        payload["enrichment_prefix"] = enrichment_prefix
    if enrichment_source_record_limit is not None:
        payload["enrichment_source_record_limit"] = int(enrichment_source_record_limit)
    if high_count_rollup_threshold is not None:
        payload["high_count_rollup_threshold"] = int(high_count_rollup_threshold)

    return payload
