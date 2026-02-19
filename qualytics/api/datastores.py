"""Datastore API operations using the centralized client."""

from ..api.client import QualyticsClient


def create_datastore(client: QualyticsClient, payload: dict) -> dict:
    response = client.post("datastores", json=payload)
    return response.json()


def list_datastores(client: QualyticsClient) -> dict:
    response = client.get("datastores/listing")
    return response.json()


def get_datastore_by_id(client: QualyticsClient, datastore_id: int) -> dict:
    response = client.get(f"datastores/{datastore_id}")
    return response.json()


def remove_datastore(client: QualyticsClient, datastore_id: int) -> dict:
    response = client.delete(f"datastores/{datastore_id}")

    if not response.content or response.status_code == 204:
        return {"success": True, "message": "Datastore deleted successfully"}

    return response.json()
