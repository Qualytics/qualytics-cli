"""Computed field API operations using the centralized client."""

from ..api.client import QualyticsClient


def create_computed_field(client: QualyticsClient, payload: dict) -> dict:
    """Create a computed field on a container.

    Required payload keys: ``name``, ``container_id``, ``transformation``,
    ``source_fields`` (list or null), ``properties``.
    """
    response = client.post("computed-fields", json=payload)
    return response.json()


def update_computed_field(
    client: QualyticsClient, field_id: int, payload: dict
) -> dict:
    """Update an existing computed field (full PUT).

    Same as create minus ``container_id`` (cannot move between containers).
    """
    response = client.put(f"computed-fields/{field_id}", json=payload)
    return response.json()


def delete_computed_field(client: QualyticsClient, field_id: int) -> dict:
    """Delete a computed field by ID."""
    response = client.delete(f"computed-fields/{field_id}")
    if not response.content or response.status_code == 204:
        return {"success": True, "message": "Computed field deleted"}
    return response.json()
