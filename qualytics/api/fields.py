"""Field API endpoints."""

from .client import QualyticsClient


def list_container_fields(
    client: QualyticsClient,
    container_id: int,
    *,
    status: list[str] | None = None,
    sort_natural_order: str | None = None,
) -> list[dict]:
    """Retrieve the fields catalogued for a container.

    Returns active and missing fields by default, matching the endpoint's
    behaviour when no status filter is supplied.
    """
    params: dict = {}
    if status:
        params["status"] = status
    if sort_natural_order:
        params["sort_natural_order"] = sort_natural_order
    response = client.get(f"containers/{container_id}/fields", params=params or None)
    return response.json()


def container_field_names(client: QualyticsClient, container_id: int) -> list[str]:
    """Just the field names for a container, in catalogue casing."""
    return [
        f["name"] for f in list_container_fields(client, container_id) if f.get("name")
    ]
