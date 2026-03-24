"""User API operations using the centralized client."""

from ..api.client import QualyticsClient


def get_user(client: QualyticsClient, user_id: int) -> dict:
    """Get a single user by ID."""
    response = client.get(f"users/{user_id}")
    return response.json()


def list_users(
    client: QualyticsClient,
    *,
    page: int = 1,
    size: int = 100,
) -> dict:
    """List users with pagination.

    Returns the raw paginated response: {items, total, page, size}.
    """
    params: dict = {"page": page, "size": size}
    response = client.get("users", params=params)
    return response.json()


def list_all_users(client: QualyticsClient) -> list[dict]:
    """Fetch ALL users across all pages."""
    page = 1
    size = 100
    all_users: list[dict] = []

    while True:
        data = list_users(client, page=page, size=size)
        items = data.get("items", [])
        all_users.extend(items)
        total = data.get("total", 0)
        if page * size >= total:
            break
        page += 1

    return all_users
