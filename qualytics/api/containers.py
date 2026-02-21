"""Container API operations using the centralized client."""

from ..api.client import QualyticsClient


def create_container(client: QualyticsClient, payload: dict) -> dict:
    """Create a computed container (computed_table, computed_file, or computed_join)."""
    response = client.post("containers", json=payload)
    return response.json()


def update_container(
    client: QualyticsClient,
    container_id: int,
    payload: dict,
    *,
    force_drop_fields: bool = False,
) -> dict:
    """Update a container (full PUT).

    If *force_drop_fields* is True, allows dropping fields that have
    associated quality checks or anomalies.  Without the flag the API
    returns 409 when fields would be lost.
    """
    params: dict = {}
    if force_drop_fields:
        params["force_drop_fields"] = True
    response = client.put(
        f"containers/{container_id}", json=payload, params=params or None
    )
    return response.json()


def get_container(client: QualyticsClient, container_id: int) -> dict:
    """Get full detail for a single container."""
    response = client.get(f"containers/{container_id}")
    return response.json()


def list_containers(
    client: QualyticsClient,
    *,
    datastore: list[int] | None = None,
    container_type: list[str] | None = None,
    name: str | None = None,
    tag: list[str] | None = None,
    search: str | None = None,
    archived: str | None = None,
    page: int = 1,
    size: int = 100,
) -> dict:
    """List containers with pagination and filters.

    Returns the raw paginated response: {items, total, page, size}.
    """
    params: dict = {"page": page, "size": size}
    if datastore is not None:
        params["datastore"] = datastore
    if container_type is not None:
        params["container_type"] = container_type
    if name is not None:
        params["name"] = name
    if tag is not None:
        params["tag"] = tag
    if search is not None:
        params["search"] = search
    if archived is not None:
        params["archived"] = archived
    response = client.get("containers", params=params)
    return response.json()


def list_all_containers(client: QualyticsClient, **filters) -> list[dict]:
    """Fetch ALL containers across all pages."""
    page = 1
    size = 100
    all_containers: list[dict] = []

    while True:
        data = list_containers(client, page=page, size=size, **filters)
        items = data.get("items", [])
        all_containers.extend(items)
        total = data.get("total", 0)
        if page * size >= total:
            break
        page += 1

    return all_containers


def delete_container(client: QualyticsClient, container_id: int) -> dict:
    """Delete a container by ID."""
    response = client.delete(f"containers/{container_id}")

    if not response.content or response.status_code == 204:
        return {"success": True, "message": "Container deleted successfully"}

    return response.json()


def validate_container(
    client: QualyticsClient, payload: dict, *, timeout: int = 60
) -> dict:
    """Validate a computed container definition (dry-run).

    Returns 204-equivalent on success, error otherwise.
    """
    response = client.post(
        "containers/validate",
        json={"container": payload},
        params={"timeout_seconds": timeout},
    )

    if not response.content or response.status_code == 204:
        return {"success": True, "message": "Validation passed"}

    return response.json()


def get_field_profiles(client: QualyticsClient, container_id: int) -> dict:
    """Get field profiles for a container."""
    response = client.get(f"containers/{container_id}/field-profiles")
    return response.json()


def list_containers_listing(
    client: QualyticsClient,
    datastore_id: int,
    container_type: str | None = None,
) -> list[dict]:
    """Lightweight non-paginated container listing for name→ID resolution."""
    params: dict = {"datastore": datastore_id}
    if container_type is not None:
        params["type"] = container_type
    response = client.get("containers/listing", params=params)
    return response.json()
