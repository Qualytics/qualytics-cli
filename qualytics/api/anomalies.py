"""Anomaly API operations using the centralized client."""

from ..api.client import QualyticsClient


def list_anomalies(
    client: QualyticsClient,
    *,
    datastore: int | None = None,
    container: int | None = None,
    quality_check: int | None = None,
    status: str | None = None,
    anomaly_type: str | None = None,
    tag: list[str] | None = None,
    rule_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    timeframe: str | None = None,
    archived: str | None = None,
    sort_created: str | None = None,
    sort_weight: str | None = None,
    page: int = 1,
    size: int = 100,
) -> dict:
    """List anomalies with pagination and filters.

    Returns the raw paginated response: {items, total, page, size}.
    """
    params: dict = {"page": page, "size": size}
    if datastore is not None:
        params["datastore"] = datastore
    if container is not None:
        params["container"] = container
    if quality_check is not None:
        params["quality_check"] = quality_check
    if status:
        params["status"] = status
    if anomaly_type:
        params["anomaly_type"] = anomaly_type
    if tag:
        params["tag"] = tag
    if rule_type:
        params["rule_type"] = rule_type
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if timeframe:
        params["timeframe"] = timeframe
    if archived:
        params["archived"] = archived
    if sort_created:
        params["sort_created"] = sort_created
    if sort_weight:
        params["sort_weight"] = sort_weight
    response = client.get("anomalies", params=params)
    return response.json()


def list_all_anomalies(
    client: QualyticsClient,
    **filters,
) -> list[dict]:
    """Fetch ALL anomalies across all pages."""
    page = 1
    size = 100
    all_anomalies: list[dict] = []

    while True:
        data = list_anomalies(client, page=page, size=size, **filters)
        items = data.get("items", [])
        all_anomalies.extend(items)
        total = data.get("total", 0)
        if page * size >= total:
            break
        page += 1

    return all_anomalies


def get_anomaly(client: QualyticsClient, anomaly_id: int) -> dict:
    """Get a single anomaly by ID."""
    response = client.get(f"anomalies/{anomaly_id}")
    return response.json()


def update_anomaly(client: QualyticsClient, anomaly_id: int, payload: dict) -> dict:
    """Update a single anomaly (status, tags, description).

    Status only accepts open values: "Active" or "Acknowledged".
    """
    response = client.put(f"anomalies/{anomaly_id}", json=payload)
    return response.json()


def bulk_update_anomalies(client: QualyticsClient, items: list[dict]) -> None:
    """Bulk update anomalies.

    Each item: {id, status?, tags?, description?}
    """
    client.patch("anomalies", json=items)


def delete_anomaly(
    client: QualyticsClient,
    anomaly_id: int,
    *,
    archive: bool = True,
    status: str = "Resolved",
) -> None:
    """Delete (archive) a single anomaly."""
    client.delete(
        f"anomalies/{anomaly_id}",
        params={
            "archive": str(archive).lower(),
            "status": status,
        },
    )


def bulk_delete_anomalies(client: QualyticsClient, items: list[dict]) -> None:
    """Bulk delete anomalies.

    Each item: {id, archive?, status?}
    """
    client.delete("anomalies", json=items)
