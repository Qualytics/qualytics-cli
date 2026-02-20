"""Datastore API operations using the centralized client."""

from ..api.client import QualyticsClient


def create_datastore(client: QualyticsClient, payload: dict) -> dict:
    """Create a new datastore."""
    response = client.post("datastores", json=payload)
    return response.json()


def update_datastore(client: QualyticsClient, datastore_id: int, payload: dict) -> dict:
    """Update an existing datastore."""
    response = client.put(f"datastores/{datastore_id}", json=payload)
    return response.json()


def get_datastore(client: QualyticsClient, datastore_id: int) -> dict:
    """Get a single datastore by ID."""
    response = client.get(f"datastores/{datastore_id}")
    return response.json()


def list_datastores(
    client: QualyticsClient,
    *,
    name: str | None = None,
    datastore_type: list[str] | None = None,
    enrichment_only: bool | None = None,
    tag: str | None = None,
    search: str | None = None,
    sort: str | None = None,
    page: int = 1,
    size: int = 100,
) -> dict:
    """List datastores with pagination and filters.

    Returns the raw paginated response: {items, total, page, size}.
    """
    params: dict = {"page": page, "size": size}
    if name is not None:
        params["name"] = name
    if datastore_type is not None:
        params["datastore_type"] = datastore_type
    if enrichment_only is not None:
        params["enrichment_only"] = enrichment_only
    if tag is not None:
        params["tag"] = tag
    if search is not None:
        params["search"] = search
    if sort is not None:
        params["sort"] = sort
    response = client.get("datastores", params=params)
    return response.json()


def list_all_datastores(client: QualyticsClient, **filters) -> list[dict]:
    """Fetch ALL datastores across all pages."""
    page = 1
    size = 100
    all_datastores: list[dict] = []

    while True:
        data = list_datastores(client, page=page, size=size, **filters)
        items = data.get("items", [])
        all_datastores.extend(items)
        total = data.get("total", 0)
        if page * size >= total:
            break
        page += 1

    return all_datastores


def delete_datastore(client: QualyticsClient, datastore_id: int) -> dict:
    """Delete a datastore by ID."""
    response = client.delete(f"datastores/{datastore_id}")

    if not response.content or response.status_code == 204:
        return {"success": True, "message": "Datastore deleted successfully"}

    return response.json()


def verify_connection(client: QualyticsClient, datastore_id: int) -> dict:
    """Verify the connection for an existing datastore.

    Returns {connected: bool, message?: str}.
    """
    response = client.post(f"datastores/{datastore_id}/connection")
    return response.json()


def validate_connection(client: QualyticsClient, payload: dict) -> dict:
    """Validate connection parameters before creating a datastore (dry-run).

    The payload is the same format as create_datastore.
    """
    response = client.post("datastores/connection", json=payload)
    return response.json()


def connect_enrichment(
    client: QualyticsClient, datastore_id: int, enrichment_id: int
) -> dict:
    """Link an enrichment datastore to a source datastore."""
    response = client.patch(f"datastores/{datastore_id}/enrichment/{enrichment_id}")
    return response.json()


def disconnect_enrichment(client: QualyticsClient, datastore_id: int) -> dict:
    """Unlink the enrichment datastore from a source datastore."""
    response = client.delete(f"datastores/{datastore_id}/enrichment")

    if not response.content or response.status_code == 204:
        return {"success": True, "message": "Enrichment disconnected successfully"}

    return response.json()
