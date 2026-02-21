"""Operation API functions using the centralized client."""

from ..api.client import QualyticsClient


def run_operation(client: QualyticsClient, payload: dict) -> dict:
    """Trigger an operation (catalog, profile, scan, materialize, export).

    Payload must include ``type`` and ``datastore_id`` plus type-specific params.
    Returns the created operation object.
    """
    response = client.post("operations/run", json=payload)
    return response.json()


def get_operation(client: QualyticsClient, operation_id: int) -> dict:
    """Get full detail for a single operation including progress counters."""
    response = client.get(f"operations/{operation_id}")
    return response.json()


def list_operations(
    client: QualyticsClient,
    *,
    datastore: list[int] | None = None,
    operation_type: str | None = None,
    result: list[str] | None = None,
    finished: bool | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    sort_created: str | None = None,
    page: int = 1,
    size: int = 100,
) -> dict:
    """List operations with pagination and filters.

    Returns the raw paginated response: {items, total, page, size}.
    """
    params: dict = {"page": page, "size": size}
    if datastore is not None:
        params["datastore"] = datastore
    if operation_type:
        params["operation_type"] = operation_type
    if result is not None:
        params["result"] = result
    if finished is not None:
        params["finished"] = finished
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if sort_created:
        params["sort_created"] = sort_created
    response = client.get("operations", params=params)
    return response.json()


def list_all_operations(client: QualyticsClient, **filters) -> list[dict]:
    """Fetch ALL operations across all pages."""
    page = 1
    size = 100
    all_operations: list[dict] = []

    while True:
        data = list_operations(client, page=page, size=size, **filters)
        items = data.get("items", [])
        all_operations.extend(items)
        total = data.get("total", 0)
        if page * size >= total:
            break
        page += 1

    return all_operations


def abort_operation(client: QualyticsClient, operation_id: int) -> dict:
    """Abort a running operation. Best-effort — no-op if already finished."""
    response = client.put(f"operations/abort/{operation_id}")
    return response.json()
