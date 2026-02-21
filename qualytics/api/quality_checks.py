"""Quality checks API operations using the centralized client."""

from ..api.client import QualyticsClient


def list_quality_checks(
    client: QualyticsClient,
    datastore_id: int,
    *,
    containers: list[int] | None = None,
    tags: list[str] | None = None,
    status: str | None = None,
    archived: str | None = None,
    page: int = 1,
    size: int = 100,
) -> dict:
    """List quality checks with pagination and filters.

    Returns the raw paginated response: {items, total, page, size}.
    """
    params: dict = {"datastore": datastore_id, "page": page, "size": size}
    if status:
        params["status"] = status
    if archived:
        params["archived"] = archived
    if tags:
        params["tag"] = tags
    if containers:
        params["container"] = containers
    response = client.get("quality-checks", params=params)
    return response.json()


def get_quality_check(client: QualyticsClient, check_id: int) -> dict:
    """Get a single quality check by ID."""
    response = client.get(f"quality-checks/{check_id}")
    return response.json()


def create_quality_check(client: QualyticsClient, payload: dict) -> dict:
    """Create a quality check. Returns the created check."""
    response = client.post("quality-checks", json=payload)
    return response.json()


def update_quality_check(client: QualyticsClient, check_id: int, payload: dict) -> dict:
    """Full update of a quality check. Returns the updated check."""
    response = client.put(f"quality-checks/{check_id}", json=payload)
    return response.json()


def delete_quality_check(
    client: QualyticsClient,
    check_id: int,
    *,
    archive: bool = True,
    status: str = "Discarded",
    delete_anomalies: bool = True,
) -> None:
    """Delete (archive) a single quality check."""
    client.delete(
        f"quality-checks/{check_id}",
        params={
            "archive": str(archive).lower(),
            "status": status,
            "delete_anomalies": str(delete_anomalies).lower(),
        },
    )


def bulk_delete_quality_checks(client: QualyticsClient, items: list[dict]) -> None:
    """Bulk delete quality checks.

    Each item: {id, archive?, status?, delete_anomalies?}
    """
    client.delete("quality-checks", json=items)


def list_all_quality_checks(
    client: QualyticsClient,
    datastore_id: int,
    *,
    containers: list[int] | None = None,
    tags: list[str] | None = None,
    status: str | None = None,
    archived: str | None = None,
) -> list[dict]:
    """Fetch ALL quality checks across all pages for a datastore."""
    page = 1
    size = 100
    all_checks: list[dict] = []

    while True:
        data = list_quality_checks(
            client,
            datastore_id,
            containers=containers,
            tags=tags,
            status=status,
            archived=archived,
            page=page,
            size=size,
        )
        items = data.get("items", [])
        all_checks.extend(items)
        total = data.get("total", 0)
        if page * size >= total:
            break
        page += 1

    return all_checks
