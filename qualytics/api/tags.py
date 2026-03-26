"""Tag API operations using the centralized client."""

from ..api.client import QualyticsClient


def get_tag(client: QualyticsClient, tag_name: str) -> dict:
    """Get a single tag by name."""
    response = client.get(f"global-tags/{tag_name}")
    return response.json()


def list_tags(
    client: QualyticsClient,
    *,
    page: int = 1,
    size: int = 100,
) -> dict:
    """List tags with pagination.

    Returns the raw paginated response: {items, total, page, size}.
    """
    params: dict = {"page": page, "size": size}
    response = client.get("global-tags", params=params)
    return response.json()


def list_all_tags(client: QualyticsClient) -> list[dict]:
    """Fetch ALL tags across all pages."""
    page = 1
    size = 100
    all_tags: list[dict] = []

    while True:
        data = list_tags(client, page=page, size=size)
        items = data.get("items", [])
        all_tags.extend(items)
        total = data.get("total", 0)
        if page * size >= total:
            break
        page += 1

    return all_tags


def create_tag(client: QualyticsClient, payload: dict) -> dict:
    """Create a new tag. Returns the created tag."""
    response = client.post("global-tags", json=payload)
    return response.json()


def delete_tag(client: QualyticsClient, tag_name: str) -> dict:
    """Delete a tag by name."""
    response = client.delete(f"global-tags/{tag_name}")
    if not response.content or response.status_code == 204:
        return {"success": True, "message": "Tag deleted successfully"}
    return response.json()
