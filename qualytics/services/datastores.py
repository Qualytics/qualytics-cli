"""Datastore service functions."""

from ..api.client import QualyticsClient
from ..api.datastores import get_datastore, list_datastores


def get_datastore_by_name(client: QualyticsClient, name: str) -> dict | None:
    """Find a datastore by name via paginated list search.

    Returns:
        dict: The datastore object if found
        None: If datastore not found
    """
    page = 1
    size = 50

    while True:
        data = list_datastores(client, name=name, page=page, size=size)
        items = data.get("items", [])

        for ds in items:
            if ds.get("name") == name:
                return ds

        if len(items) < size:
            break

        page += 1

    return None


def get_datastore_by(
    client: QualyticsClient,
    datastore_id: int | None = None,
    datastore_name: str | None = None,
) -> dict | None:
    """Get datastore by ID or name.

    Returns:
        dict: The datastore object if found
        None: If datastore not found
    """
    if datastore_id is None and datastore_name is None:
        raise ValueError("Either datastore_id or datastore_name must be provided")

    if datastore_id is not None and datastore_name is not None:
        raise ValueError(
            "Cannot specify both datastore_id and datastore_name. Please use only one."
        )

    if datastore_id is not None:
        return get_datastore(client, datastore_id)

    return get_datastore_by_name(client, datastore_name)


def build_create_datastore_payload(
    *,
    name: str,
    connection_id: int,
    tags: list[str] | None = None,
    teams: list[str] | None = None,
    enrichment_only: bool = False,
    enrichment_prefix: str | None = None,
    enrichment_source_record_limit: int | None = None,
    enrichment_remediation_strategy: str = "none",
    high_count_rollup_threshold: int | None = None,
    trigger_catalog: bool = True,
    database: str,
    schema: str,
) -> dict:
    """Build a payload for creating a datastore."""
    payload: dict = {
        "name": name,
        "connection_id": int(connection_id),
        "enrichment_only": enrichment_only,
        "enrichment_remediation_strategy": enrichment_remediation_strategy,
        "trigger_catalog": trigger_catalog,
        "tags": tags,
        "teams": teams,
        "database": database,
        "schema": schema,
    }

    if enrichment_prefix is not None:
        payload["enrichment_prefix"] = enrichment_prefix
    if enrichment_source_record_limit is not None:
        payload["enrichment_source_record_limit"] = int(enrichment_source_record_limit)
    if high_count_rollup_threshold is not None:
        payload["high_count_rollup_threshold"] = int(high_count_rollup_threshold)

    return payload


def flatten_datastore_for_put(datastore: dict) -> dict:
    """Flatten a GET /datastores/{id} response into a shape the PUT endpoint accepts.

    The GET response returns nested objects for teams, tags, and connection,
    but PUT expects simple scalars/strings.
    """
    flat = dict(datastore)

    # teams: [{id, name, ...}] → ["name1", "name2"]
    if "teams" in flat and flat["teams"]:
        flat["teams"] = [t["name"] if isinstance(t, dict) else t for t in flat["teams"]]

    # tags: [{id, name, ...}] or [{"name": ...}] → ["name1", "name2"]
    if "tags" in flat and flat["tags"]:
        flat["tags"] = [t["name"] if isinstance(t, dict) else t for t in flat["tags"]]

    # connection: {id, ...} → connection_id (flat key the PUT expects)
    if "connection" in flat and isinstance(flat["connection"], dict):
        flat.setdefault("connection_id", flat["connection"]["id"])
        del flat["connection"]

    return flat


def build_update_datastore_payload(
    *,
    name: str | None = None,
    connection_id: int | None = None,
    database: str | None = None,
    schema: str | None = None,
    tags: list[str] | None = None,
    teams: list[str] | None = None,
    enrichment_only: bool | None = None,
    enrichment_prefix: str | None = None,
    enrichment_source_record_limit: int | None = None,
    enrichment_remediation_strategy: str | None = None,
    high_count_rollup_threshold: int | None = None,
) -> dict:
    """Build a payload for updating a datastore (partial update)."""
    payload: dict = {}

    if name is not None:
        payload["name"] = name
    if connection_id is not None:
        payload["connection_id"] = int(connection_id)
    if database is not None:
        payload["database"] = database
    if schema is not None:
        payload["schema"] = schema
    if tags is not None:
        payload["tags"] = tags
    if teams is not None:
        payload["teams"] = teams
    if enrichment_only is not None:
        payload["enrichment_only"] = enrichment_only
    if enrichment_prefix is not None:
        payload["enrichment_prefix"] = enrichment_prefix
    if enrichment_source_record_limit is not None:
        payload["enrichment_source_record_limit"] = int(enrichment_source_record_limit)
    if enrichment_remediation_strategy is not None:
        payload["enrichment_remediation_strategy"] = enrichment_remediation_strategy
    if high_count_rollup_threshold is not None:
        payload["high_count_rollup_threshold"] = int(high_count_rollup_threshold)

    return payload
