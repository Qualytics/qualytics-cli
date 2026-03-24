"""Team API operations using the centralized client."""

from ..api.client import QualyticsClient


def get_team(client: QualyticsClient, team_id: int) -> dict:
    """Get a single team by ID."""
    response = client.get(f"teams/{team_id}")
    return response.json()


def list_teams(
    client: QualyticsClient,
    *,
    page: int = 1,
    size: int = 100,
) -> dict:
    """List teams with pagination.

    Returns the raw paginated response: {items, total, page, size}.
    """
    params: dict = {"page": page, "size": size}
    response = client.get("teams", params=params)
    return response.json()


def list_all_teams(client: QualyticsClient) -> list[dict]:
    """Fetch ALL teams across all pages."""
    page = 1
    size = 100
    all_teams: list[dict] = []

    while True:
        data = list_teams(client, page=page, size=size)
        items = data.get("items", [])
        all_teams.extend(items)
        total = data.get("total", 0)
        if page * size >= total:
            break
        page += 1

    return all_teams
