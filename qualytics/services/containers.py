"""Container service functions."""

import time

import typer

from ..api.client import QualyticsClient, QualyticsAPIError
from ..api.containers import list_containers_listing


def get_table_ids(
    client: QualyticsClient, datastore_id: int, max_retries=5, retry_delay=5
):
    """Get table/container IDs for a datastore with retry logic."""
    for attempt in range(max_retries):
        try:
            items_array = list_containers_listing(client, datastore_id)
            table_ids = {}
            for item in items_array:
                table_ids[item["name"]] = item["id"]
            return table_ids
        except QualyticsAPIError as e:
            typer.secho(
                f"Attempt {attempt + 1} failed with status code {e.status_code}. Retrying...",
                fg=typer.colors.RED,
            )
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
        except Exception as e:
            typer.secho(
                f"Request error during attempt {attempt + 1}: {e}. Retrying...",
                fg=typer.colors.RED,
            )
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    typer.secho(
        f"Failed getting the table ids after {max_retries} attempts.",
        fg=typer.colors.RED,
    )
    return None


def get_container_by_name(
    client: QualyticsClient, datastore_id: int, name: str
) -> dict | None:
    """Find a container by name within a datastore via listing.

    Returns:
        dict: The container stub if found
        None: If container not found
    """
    items = list_containers_listing(client, datastore_id)
    for item in items:
        if item.get("name") == name:
            return item
    return None


_COMPUTED_TYPES = {"computed_table", "computed_file", "computed_join"}
_ALL_CONTAINER_TYPES = {
    "table",
    "view",
    "file",
    "computed_table",
    "computed_file",
    "computed_join",
}
_VALID_JOIN_TYPES = {"inner", "left", "right", "full"}


def build_create_container_payload(
    container_type: str,
    *,
    datastore_id: int | None = None,
    name: str,
    query: str | None = None,
    source_container_id: int | None = None,
    select_clause: str | None = None,
    where_clause: str | None = None,
    group_by_clause: str | None = None,
    left_container_id: int | None = None,
    right_container_id: int | None = None,
    left_key_field: str | None = None,
    right_key_field: str | None = None,
    left_prefix: str | None = None,
    right_prefix: str | None = None,
    join_type: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    additional_metadata: dict | None = None,
) -> dict:
    """Build a polymorphic create payload for a computed container."""
    if container_type not in _COMPUTED_TYPES:
        raise ValueError(
            f"Only computed types can be created: {', '.join(sorted(_COMPUTED_TYPES))}"
        )

    payload: dict = {"container_type": container_type, "name": name}

    if additional_metadata is not None:
        payload["additional_metadata"] = additional_metadata

    if container_type == "computed_table":
        if datastore_id is None:
            raise ValueError("--datastore-id is required for computed_table")
        if query is None:
            raise ValueError("--query is required for computed_table")
        payload["datastore_id"] = datastore_id
        payload["query"] = query

    elif container_type == "computed_file":
        if datastore_id is None:
            raise ValueError("--datastore-id is required for computed_file")
        if source_container_id is None:
            raise ValueError("--source-container-id is required for computed_file")
        if select_clause is None:
            raise ValueError("--select-clause is required for computed_file")
        payload["datastore_id"] = datastore_id
        payload["source_container_id"] = source_container_id
        payload["select_clause"] = select_clause
        if where_clause is not None:
            payload["where_clause"] = where_clause
        if group_by_clause is not None:
            payload["group_by_clause"] = group_by_clause

    elif container_type == "computed_join":
        if left_container_id is None:
            raise ValueError("--left-container-id is required for computed_join")
        if right_container_id is None:
            raise ValueError("--right-container-id is required for computed_join")
        if left_key_field is None:
            raise ValueError("--left-key-field is required for computed_join")
        if right_key_field is None:
            raise ValueError("--right-key-field is required for computed_join")
        if select_clause is None:
            raise ValueError("--select-clause is required for computed_join")
        payload["left_container_id"] = left_container_id
        payload["right_container_id"] = right_container_id
        payload["left_join_field_name"] = left_key_field
        payload["right_join_field_name"] = right_key_field
        payload["select_clause"] = select_clause
        if join_type is not None:
            payload["join_type"] = join_type
        if left_prefix is not None:
            payload["left_prefix"] = left_prefix
        if right_prefix is not None:
            payload["right_prefix"] = right_prefix
        if where_clause is not None:
            payload["where_clause"] = where_clause
        if group_by_clause is not None:
            payload["group_by_clause"] = group_by_clause

    return payload


def build_update_container_payload(existing: dict, **changes) -> dict:
    """Merge user changes into an existing container for a full PUT.

    The returned payload always includes ``container_type`` (required
    discriminator) and any user-supplied fields overlaid on top of the
    current values.
    """
    payload: dict = {"container_type": existing["container_type"]}

    ct = existing["container_type"]

    # For computed types, name is required in the PUT body
    if ct in _COMPUTED_TYPES:
        payload["name"] = changes.pop("name", existing.get("name"))

    # Computed-table specifics
    if ct == "computed_table":
        payload["query"] = changes.pop("query", existing.get("query"))

    # Computed-file specifics
    if ct == "computed_file":
        payload["select_clause"] = changes.pop(
            "select_clause", existing.get("select_clause")
        )

    # Overlay remaining changes
    for key, value in changes.items():
        if value is not None:
            payload[key] = value

    return payload
