"""Connection API operations using the centralized client."""

from ..api.client import QualyticsClient


def create_connection(client: QualyticsClient, payload: dict) -> dict:
    """Create a new connection. Returns the created connection with ID."""
    response = client.post("connections", json=payload)
    return response.json()


def update_connection(
    client: QualyticsClient, connection_id: int, payload: dict
) -> dict:
    """Update an existing connection (partial PUT). Returns updated connection."""
    response = client.put(f"connections/{connection_id}", json=payload)
    return response.json()


def get_connection_api(client: QualyticsClient, connection_id: int) -> dict:
    """Get a single connection by ID. Secrets are masked in the response."""
    response = client.get(f"connections/{connection_id}")
    return response.json()


def list_connections(
    client: QualyticsClient,
    *,
    name: str | None = None,
    connection_type: list[str] | None = None,
    page: int = 1,
    size: int = 100,
) -> dict:
    """List connections with pagination and optional filters.

    Returns the raw paginated response: {items, total, page, size}.
    """
    params: dict = {"page": page, "size": size}
    if name is not None:
        params["name"] = name
    if connection_type is not None:
        params["type"] = connection_type
    response = client.get("connections", params=params)
    return response.json()


def list_all_connections(client: QualyticsClient, **filters) -> list[dict]:
    """Fetch ALL connections across all pages."""
    page = 1
    size = 100
    all_connections: list[dict] = []

    while True:
        data = list_connections(client, page=page, size=size, **filters)
        items = data.get("items", [])
        all_connections.extend(items)
        total = data.get("total", 0)
        if page * size >= total:
            break
        page += 1

    return all_connections


def delete_connection(client: QualyticsClient, connection_id: int) -> dict:
    """Delete a connection. Returns 409 if datastores still reference it."""
    response = client.delete(f"connections/{connection_id}")
    if not response.content or response.status_code == 204:
        return {"success": True, "message": "Connection deleted successfully"}
    return response.json()


def test_connection(
    client: QualyticsClient,
    connection_id: int,
    payload: dict | None = None,
) -> dict:
    """Test an existing connection, optionally with new credentials.

    If *payload* is provided, it is sent as the request body so the API
    tests with the new values without persisting them.
    """
    kwargs: dict = {}
    if payload is not None:
        kwargs["json"] = payload
    response = client.post(f"connections/{connection_id}/test", **kwargs)
    return response.json()
