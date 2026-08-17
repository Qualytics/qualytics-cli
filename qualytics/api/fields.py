"""Field API endpoints."""

from .client import QualyticsClient


def list_container_fields(client: QualyticsClient, container_id: int) -> list[dict]:
    """Retrieve the fields catalogued for a container.

    Returns active and missing fields by default, matching the endpoint's
    behaviour when no status filter is supplied.
    """
    response = client.get(f"containers/{container_id}/fields")
    return response.json()


def container_field_names(client: QualyticsClient, container_id: int) -> list[str]:
    """Just the field names for a container, in catalogue casing."""
    return [
        f["name"] for f in list_container_fields(client, container_id) if f.get("name")
    ]
