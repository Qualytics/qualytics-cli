"""Datastore service functions."""
import requests
import typing as t


def get_default_headers(token):
    """Get default authorization headers."""
    return {"Authorization": f"Bearer {token}"}


def get_connection_by(
    base_url: str, token: str, connection_id: int = None, connection_name: str = None
):
    """
    Get connection from Qualytics API by ID or name.
    Handles pagination to search through all connections.

    Args:
        base_url: The Qualytics API base URL
        token: The authentication token
        connection_id: The ID of the connection to search for (optional)
        connection_name: The name of the connection to search for (optional)

    Returns:
        dict: The connection object if found
        None: If connection not found

    Raises:
        ValueError: If neither connection_id nor connection_name is provided
        requests.RequestException: If API call fails
    """
    if connection_id is None and connection_name is None:
        raise ValueError("Either connection_id or connection_name must be provided")

    if connection_id is not None and connection_name is not None:
        raise ValueError(
            "Cannot specify both connection_id and connection_name. Please use only one."
        )

    endpoint = "connections"
    headers = get_default_headers(token)

    # Pagination parameters
    page = 1
    size = 50  # Using 50 as the minimum size

    try:
        while True:
            # Build URL with pagination params
            url = f"{base_url}{endpoint}?page={page}&size={size}"
            response = requests.get(url, headers=headers, verify=False)
            response.raise_for_status()

            data = response.json()

            # Check if response has the expected structure
            if "items" not in data:
                raise ValueError(
                    f"Unexpected API response format. Expected 'items' field but got: {list(data.keys())}"
                )

            connections = data["items"]

            # Search for connection by ID or name in current page
            for connection in connections:
                if connection_id is not None and connection.get("id") == connection_id:
                    return connection
                if (
                    connection_name is not None
                    and connection.get("name") == connection_name
                ):
                    return connection

            # Check if there are more pages
            if len(connections) < size:
                # Last page reached, connection not found
                break

            page += 1

        # If not found after all pages, return None
        return None

    except requests.RequestException as e:
        raise requests.RequestException(f"Failed to fetch connections from API: {e}")


def get_datastore_by(
    base_url: str, token: str, datastore_id: int = None, datastore_name: str = None
):
    """
    Get datastore from Qualytics API by ID or name.
    Uses the listing endpoint for consistent response format.
    Handles pagination to search through all datastores.

    Args:
        base_url: The Qualytics API base URL
        token: The authentication token
        datastore_id: The ID of the datastore to search for (optional)
        datastore_name: The name of the datastore to search for (optional)

    Returns:
        dict: The datastore object if found
        None: If datastore not found

    Raises:
        ValueError: If neither datastore_id nor datastore_name is provided
        requests.RequestException: If API call fails
    """
    if datastore_id is None and datastore_name is None:
        raise ValueError("Either datastore_id or datastore_name must be provided")

    if datastore_id is not None and datastore_name is not None:
        raise ValueError(
            "Cannot specify both datastore_id and datastore_name. Please use only one."
        )

    # Use listing endpoint for both ID and name searches for consistent format
    endpoint = "datastores/listing"
    headers = get_default_headers(token)

    # Pagination parameters
    page = 1
    size = 50

    try:
        while True:
            # Build URL with pagination params
            url = f"{base_url}{endpoint}?page={page}&size={size}"
            response = requests.get(url, headers=headers, verify=False)
            response.raise_for_status()

            data = response.json()

            # The listing endpoint returns an array directly (not wrapped in items)
            datastores = data if isinstance(data, list) else data.get("items", [])

            # Search for datastore by ID or name in current page
            for datastore in datastores:
                if datastore_id is not None and datastore.get("id") == datastore_id:
                    return datastore
                if (
                    datastore_name is not None
                    and datastore.get("name") == datastore_name
                ):
                    return datastore

            # Check if there are more pages
            if len(datastores) < size:
                # Last page reached, datastore not found
                break

            page += 1

        # If not found after all pages, return None
        return None

    except requests.RequestException as e:
        raise requests.RequestException(f"Failed to fetch datastores from API: {e}")


def build_new_datastore_payload(
    *,
    cfg: t.Optional[dict],
    name: str,
    connection_id: t.Optional[int] = None,
    tags: t.Optional[t.List[str]] = None,
    teams: t.Optional[t.List[str]] = None,
    enrichment_only: bool = False,
    enrichment_prefix: t.Optional[str] = None,
    enrichment_source_record_limit: t.Optional[int] = None,
    enrichment_remediation_strategy: str = "none",
    high_count_rollup_threshold: t.Optional[int] = None,
    trigger_catalog: bool = True,
    database: str,
    schema: str,
) -> dict:
    """Build a payload for creating a new datastore."""
    # Base payload structure
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

    # If connection_id is provided, use it to reference existing connection
    if connection_id is not None:
        payload["connection_id"] = int(connection_id)
    # If cfg (connection config from YAML) is provided, build the connection object
    elif cfg is not None:
        params = cfg["parameters"]
        # Base connection block (aligned to your schema)
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
