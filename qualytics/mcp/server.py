"""Qualytics MCP server — exposes CLI operations as structured tools for LLMs."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import jwt
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from ..api.client import get_client, QualyticsAPIError
from ..config import load_config, CONFIG_PATH

mcp = FastMCP(
    name="Qualytics",
    instructions=(
        "Qualytics is a data quality platform. Use these tools to manage "
        "connections, datastores, containers, quality checks, anomalies, "
        "and operations. Always call auth_status first to verify "
        "the CLI is configured before calling other tools."
    ),
)


# ── helpers ──────────────────────────────────────────────────────────────


def _client():
    """Get an authenticated QualyticsClient, raising ToolError on failure."""
    try:
        return get_client()
    except SystemExit:
        raise ToolError(
            "Not authenticated. Run 'qualytics auth login --url <your-url>' "
            "or 'qualytics auth init --url <url> --token <token>' first."
        )


def _api_call(fn, *args, **kwargs):
    """Call an API function, converting QualyticsAPIError to ToolError."""
    try:
        return fn(*args, **kwargs)
    except QualyticsAPIError as e:
        raise ToolError(f"API error {e.status_code}: {e.message}")


# ── auth ─────────────────────────────────────────────────────────────────


@mcp.tool
def auth_status() -> dict:
    """Show current Qualytics CLI authentication status.

    Returns the configured URL, token validity, expiry, and SSL setting.
    Call this first to verify the CLI is configured.
    """
    config = load_config()
    if config is None:
        raise ToolError(
            "Not authenticated. Run 'qualytics auth login' or 'qualytics auth init'."
        )

    url = config.get("url", "")
    token = config.get("token", "")
    ssl_verify = config.get("ssl_verify", True)

    try:
        host = urlparse(url).hostname or url
    except Exception:
        host = url

    masked = token[:4] + "****" if len(token) > 4 else "****"

    result = {
        "host": host,
        "url": url,
        "token": masked,
        "ssl_verify": ssl_verify,
        "config_file": CONFIG_PATH,
        "authenticated": True,
    }

    try:
        decoded = jwt.decode(
            token, algorithms=["none"], options={"verify_signature": False}
        )
        exp = decoded.get("exp")
        if exp is not None:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = exp_dt - now
            result["token_expires"] = exp_dt.isoformat()
            result["token_expired"] = delta.total_seconds() <= 0
            if delta.total_seconds() > 0:
                result["expires_in_days"] = delta.days
            else:
                result["expired_days_ago"] = abs(delta.days)
                result["authenticated"] = False
    except Exception:
        result["token_decode_error"] = True

    return result


# ── connections ──────────────────────────────────────────────────────────


@mcp.tool
def list_connections(
    name: str | None = None,
    type: str | None = None,
) -> list[dict]:
    """List all connections, optionally filtered by name or type."""
    from ..api.connections import list_all_connections

    client = _client()
    type_list = [t.strip() for t in type.split(",")] if type else None
    return _api_call(list_all_connections, client, name=name, connection_type=type_list)


@mcp.tool
def get_connection(
    id: int | None = None,
    name: str | None = None,
) -> dict:
    """Get a connection by ID or name. Provide exactly one."""
    from ..services.connections import get_connection_by

    if id is None and name is None:
        raise ToolError("Provide either 'id' or 'name'.")
    client = _client()
    result = _api_call(
        get_connection_by, client, connection_id=id, connection_name=name
    )
    if result is None:
        raise ToolError(f"Connection not found: id={id}, name={name}")
    return result


@mcp.tool
def create_connection(
    type: str,
    name: str,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    uri: str | None = None,
    database: str | None = None,
    parameters: dict | None = None,
) -> dict:
    """Create a new connection. Type examples: postgresql, snowflake, bigquery, mysql, etc."""
    from ..api.connections import create_connection as api_create
    from ..services.connections import build_create_connection_payload

    payload = build_create_connection_payload(
        type,
        name=name,
        host=host,
        port=port,
        username=username,
        password=password,
        uri=uri,
        parameters=parameters,
    )
    client = _client()
    return _api_call(api_create, client, payload)


@mcp.tool
def delete_connection(id: int) -> dict:
    """Delete a connection by ID."""
    from ..api.connections import delete_connection as api_delete

    client = _client()
    return _api_call(api_delete, client, id)


@mcp.tool
def test_connection(id: int) -> dict:
    """Test connectivity for an existing connection."""
    from ..api.connections import test_connection as api_test

    client = _client()
    return _api_call(api_test, client, id)


# ── datastores ───────────────────────────────────────────────────────────


@mcp.tool
def list_datastores(
    name: str | None = None,
    type: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    """List all datastores, optionally filtered by name, type, or tag."""
    from ..api.datastores import list_all_datastores

    client = _client()
    type_list = [t.strip() for t in type.split(",")] if type else None
    return _api_call(
        list_all_datastores,
        client,
        name=name,
        datastore_type=type_list,
        tag=tag,
    )


@mcp.tool
def get_datastore(
    id: int | None = None,
    name: str | None = None,
) -> dict:
    """Get a datastore by ID or name. Provide exactly one."""
    from ..services.datastores import get_datastore_by

    if id is None and name is None:
        raise ToolError("Provide either 'id' or 'name'.")
    client = _client()
    result = _api_call(get_datastore_by, client, datastore_id=id, datastore_name=name)
    if result is None:
        raise ToolError(f"Datastore not found: id={id}, name={name}")
    return result


@mcp.tool
def create_datastore(
    name: str,
    connection_id: int,
    database: str,
    schema: str,
    tags: list[str] | None = None,
    teams: list[str] | None = None,
    trigger_catalog: bool = True,
) -> dict:
    """Create a new datastore linked to an existing connection."""
    from ..api.datastores import create_datastore as api_create
    from ..services.datastores import build_create_datastore_payload

    payload = build_create_datastore_payload(
        name=name,
        connection_id=connection_id,
        database=database,
        schema=schema,
        tags=tags,
        teams=teams,
        trigger_catalog=trigger_catalog,
    )
    client = _client()
    return _api_call(api_create, client, payload)


@mcp.tool
def delete_datastore(id: int) -> dict:
    """Delete a datastore by ID."""
    from ..api.datastores import delete_datastore as api_delete

    client = _client()
    return _api_call(api_delete, client, id)


@mcp.tool
def verify_datastore_connection(datastore_id: int) -> dict:
    """Verify the database connection for a datastore. Returns {connected, message}."""
    from ..api.datastores import verify_connection

    client = _client()
    return _api_call(verify_connection, client, datastore_id)


@mcp.tool
def link_enrichment(datastore_id: int, enrichment_id: int) -> dict:
    """Link an enrichment datastore to a source datastore."""
    from ..api.datastores import connect_enrichment

    client = _client()
    return _api_call(connect_enrichment, client, datastore_id, enrichment_id)


@mcp.tool
def unlink_enrichment(datastore_id: int) -> dict:
    """Unlink the enrichment datastore from a source datastore."""
    from ..api.datastores import disconnect_enrichment

    client = _client()
    return _api_call(disconnect_enrichment, client, datastore_id)


# ── containers ───────────────────────────────────────────────────────────


@mcp.tool
def list_containers(
    datastore_id: int,
    type: str | None = None,
    name: str | None = None,
    tag: str | None = None,
    search: str | None = None,
) -> list[dict]:
    """List containers for a datastore. Filter by type (table, view, computed_table, etc.), name, tag, or search string."""
    from ..api.containers import list_all_containers

    client = _client()
    type_list = [t.strip() for t in type.split(",")] if type else None
    tag_list = [tag] if tag else None
    return _api_call(
        list_all_containers,
        client,
        datastore=[datastore_id],
        container_type=type_list,
        name=name,
        tag=tag_list,
        search=search,
    )


@mcp.tool
def get_container(id: int) -> dict:
    """Get a container by ID."""
    from ..api.containers import get_container as api_get

    client = _client()
    return _api_call(api_get, client, id)


@mcp.tool
def get_field_profiles(container_id: int) -> dict:
    """Get field profiles (column metadata) for a container."""
    from ..api.containers import get_field_profiles as api_get_profiles

    client = _client()
    return _api_call(api_get_profiles, client, container_id)


@mcp.tool
def create_container(
    container_type: str,
    name: str,
    datastore_id: int | None = None,
    query: str | None = None,
    source_container_id: int | None = None,
    select_clause: str | None = None,
    where_clause: str | None = None,
    group_by_clause: str | None = None,
    left_container_id: int | None = None,
    right_container_id: int | None = None,
    left_key_field: str | None = None,
    right_key_field: str | None = None,
    join_type: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Create a computed container.

    container_type must be one of: computed_table, computed_file, computed_join.
    - computed_table: requires datastore_id, name, query
    - computed_file: requires datastore_id, name, source_container_id, select_clause
    - computed_join: requires name, left_container_id, right_container_id, left_key_field, right_key_field, select_clause
    """
    from ..api.containers import create_container as api_create
    from ..services.containers import build_create_container_payload

    try:
        payload = build_create_container_payload(
            container_type,
            datastore_id=datastore_id,
            name=name,
            query=query,
            source_container_id=source_container_id,
            select_clause=select_clause,
            where_clause=where_clause,
            group_by_clause=group_by_clause,
            left_container_id=left_container_id,
            right_container_id=right_container_id,
            left_key_field=left_key_field,
            right_key_field=right_key_field,
            join_type=join_type,
            description=description,
            tags=tags,
        )
    except ValueError as e:
        raise ToolError(str(e))

    client = _client()
    return _api_call(api_create, client, payload)


@mcp.tool
def delete_container(id: int) -> dict:
    """Delete a container by ID. Cascades to fields, checks, and anomalies."""
    from ..api.containers import delete_container as api_delete

    client = _client()
    return _api_call(api_delete, client, id)


@mcp.tool
def validate_container(
    container_type: str,
    name: str = "validation_test",
    datastore_id: int | None = None,
    query: str | None = None,
    source_container_id: int | None = None,
    select_clause: str | None = None,
    left_container_id: int | None = None,
    right_container_id: int | None = None,
    left_key_field: str | None = None,
    right_key_field: str | None = None,
    join_type: str | None = None,
) -> dict:
    """Validate a computed container definition without creating it (dry-run)."""
    from ..api.containers import validate_container as api_validate
    from ..services.containers import build_create_container_payload

    try:
        payload = build_create_container_payload(
            container_type,
            datastore_id=datastore_id,
            name=name,
            query=query,
            source_container_id=source_container_id,
            select_clause=select_clause,
            left_container_id=left_container_id,
            right_container_id=right_container_id,
            left_key_field=left_key_field,
            right_key_field=right_key_field,
            join_type=join_type,
        )
    except ValueError as e:
        raise ToolError(str(e))

    client = _client()
    return _api_call(api_validate, client, payload)


# ── quality checks ───────────────────────────────────────────────────────


@mcp.tool
def list_checks(
    datastore_id: int,
    container_id: int | None = None,
    tag: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """List quality checks for a datastore. Filter by container, tag, or status."""
    from ..api.quality_checks import list_all_quality_checks

    client = _client()
    containers = [container_id] if container_id else None
    tags = [tag] if tag else None
    return _api_call(
        list_all_quality_checks,
        client,
        datastore_id,
        containers=containers,
        tags=tags,
        status=status,
    )


@mcp.tool
def get_check(check_id: int) -> dict:
    """Get a quality check by ID."""
    from ..api.quality_checks import get_quality_check

    client = _client()
    return _api_call(get_quality_check, client, check_id)


@mcp.tool
def create_check(payload: dict) -> dict:
    """Create a quality check from a payload dict.

    Required fields: container_id, rule (rule type), fields (list of field names).
    Optional: description, coverage, filter, properties, tags, status.
    """
    from ..api.quality_checks import create_quality_check

    client = _client()
    return _api_call(create_quality_check, client, payload)


@mcp.tool
def update_check(check_id: int, payload: dict) -> dict:
    """Update a quality check. Provide the full updated check payload."""
    from ..api.quality_checks import update_quality_check

    client = _client()
    return _api_call(update_quality_check, client, check_id, payload)


@mcp.tool
def delete_check(check_id: int) -> None:
    """Delete (archive) a quality check by ID."""
    from ..api.quality_checks import delete_quality_check

    client = _client()
    _api_call(delete_quality_check, client, check_id)


@mcp.tool
def export_checks(datastore_id: int, output_dir: str) -> dict:
    """Export quality checks to a directory (one YAML per check, organized by container).

    Returns {exported: count, containers: count}.
    """
    from ..api.quality_checks import list_all_quality_checks
    from ..services.quality_checks import export_checks_to_directory

    client = _client()
    checks = _api_call(list_all_quality_checks, client, datastore_id)
    return export_checks_to_directory(checks, output_dir)


@mcp.tool
def import_checks(
    datastore_id: int,
    input_dir: str,
    dry_run: bool = False,
) -> dict:
    """Import quality checks from a directory with upsert (create or update).

    Returns {created, updated, failed, errors}.
    """
    from ..services.quality_checks import (
        import_checks_to_datastore,
        load_checks_from_directory,
    )

    client = _client()
    checks = load_checks_from_directory(input_dir)
    return _api_call(
        import_checks_to_datastore, client, datastore_id, checks, dry_run=dry_run
    )


# ── anomalies ────────────────────────────────────────────────────────────


@mcp.tool
def list_anomalies(
    datastore_id: int | None = None,
    container_id: int | None = None,
    check_id: int | None = None,
    status: str | None = None,
    type: str | None = None,
    tag: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """List anomalies with optional filters.

    Status: Active, Acknowledged, Resolved, Invalid, Duplicate, Discarded.
    Type: shape, record (anomaly_type).
    """
    from ..api.anomalies import list_all_anomalies

    client = _client()
    tag_list = [tag] if tag else None
    return _api_call(
        list_all_anomalies,
        client,
        datastore=datastore_id,
        container=container_id,
        quality_check=check_id,
        status=status,
        anomaly_type=type,
        tag=tag_list,
        start_date=start_date,
        end_date=end_date,
    )


@mcp.tool
def get_anomaly(id: int) -> dict:
    """Get a single anomaly by ID."""
    from ..api.anomalies import get_anomaly as api_get

    client = _client()
    return _api_call(api_get, client, id)


@mcp.tool
def update_anomaly(
    id: int,
    status: str,
) -> dict:
    """Update anomaly status. Status must be Active or Acknowledged."""
    from ..api.anomalies import update_anomaly as api_update

    if status not in ("Active", "Acknowledged"):
        raise ToolError(
            f"Status must be 'Active' or 'Acknowledged', got '{status}'. "
            "Use archive_anomaly for Resolved/Invalid/Duplicate/Discarded."
        )
    client = _client()
    return _api_call(api_update, client, id, {"status": status})


@mcp.tool
def archive_anomaly(
    id: int,
    status: str = "Resolved",
) -> None:
    """Archive (soft-delete) an anomaly. Status: Resolved, Invalid, Duplicate, Discarded."""
    from ..api.anomalies import delete_anomaly as api_delete

    valid = {"Resolved", "Invalid", "Duplicate", "Discarded"}
    if status not in valid:
        raise ToolError(f"Status must be one of {valid}, got '{status}'.")
    client = _client()
    _api_call(api_delete, client, id, archive=True, status=status)


@mcp.tool
def delete_anomaly(id: int) -> None:
    """Permanently delete an anomaly (hard delete, cannot be undone)."""
    from ..api.anomalies import delete_anomaly as api_delete

    client = _client()
    _api_call(api_delete, client, id, archive=False)


# ── operations ───────────────────────────────────────────────────────────


@mcp.tool
def run_catalog(
    datastore_ids: list[int],
    prune: bool = False,
    recreate: bool = False,
) -> dict:
    """Trigger a catalog operation to discover containers in datastores.

    Returns the operation details. Use get_operation to check progress.
    """
    from ..api.operations import run_operation

    client = _client()
    payload = {
        "type": "catalog",
        "datastore_ids": datastore_ids,
        "prune": prune,
        "recreate": recreate,
    }
    return _api_call(run_operation, client, payload)


@mcp.tool
def run_profile(
    datastore_ids: list[int],
    container_names: list[str] | None = None,
    container_tags: list[str] | None = None,
    max_records_analyzed_per_partition: int | None = None,
) -> dict:
    """Trigger a profile operation to infer quality checks.

    Returns the operation details. Use get_operation to check progress.
    """
    from ..api.operations import run_operation

    client = _client()
    payload: dict = {
        "type": "profile",
        "datastore_ids": datastore_ids,
    }
    if container_names:
        payload["container_names"] = container_names
    if container_tags:
        payload["container_tags"] = container_tags
    if max_records_analyzed_per_partition is not None:
        payload["max_records_analyzed_per_partition"] = (
            max_records_analyzed_per_partition
        )
    return _api_call(run_operation, client, payload)


@mcp.tool
def run_scan(
    datastore_ids: list[int],
    container_names: list[str] | None = None,
    container_tags: list[str] | None = None,
    incremental: bool | None = None,
    max_records_analyzed_per_partition: int | None = None,
) -> dict:
    """Trigger a scan operation to detect anomalies.

    Returns the operation details. Use get_operation to check progress.
    """
    from ..api.operations import run_operation

    client = _client()
    payload: dict = {
        "type": "scan",
        "datastore_ids": datastore_ids,
    }
    if container_names:
        payload["container_names"] = container_names
    if container_tags:
        payload["container_tags"] = container_tags
    if incremental is not None:
        payload["incremental"] = incremental
    if max_records_analyzed_per_partition is not None:
        payload["max_records_analyzed_per_partition"] = (
            max_records_analyzed_per_partition
        )
    return _api_call(run_operation, client, payload)


@mcp.tool
def run_materialize(
    datastore_ids: list[int],
    container_names: list[str] | None = None,
    container_tags: list[str] | None = None,
) -> dict:
    """Trigger a materialize operation for computed containers.

    Returns the operation details. Use get_operation to check progress.
    """
    from ..api.operations import run_operation

    client = _client()
    payload: dict = {
        "type": "materialize",
        "datastore_ids": datastore_ids,
    }
    if container_names:
        payload["container_names"] = container_names
    if container_tags:
        payload["container_tags"] = container_tags
    return _api_call(run_operation, client, payload)


@mcp.tool
def get_operation(operation_id: int) -> dict:
    """Get operation details including progress counters."""
    from ..api.operations import get_operation as api_get

    client = _client()
    return _api_call(api_get, client, operation_id)


@mcp.tool
def list_operations(
    datastore_id: int | None = None,
    type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """List operations, optionally filtered by datastore, type, or result status."""
    from ..api.operations import list_all_operations

    client = _client()
    ds_list = [datastore_id] if datastore_id else None
    result_list = [status] if status else None
    return _api_call(
        list_all_operations,
        client,
        datastore=ds_list,
        operation_type=type,
        result=result_list,
    )


@mcp.tool
def abort_operation(operation_id: int) -> dict:
    """Abort a running operation (best-effort)."""
    from ..api.operations import abort_operation as api_abort

    client = _client()
    return _api_call(api_abort, client, operation_id)


# ── config export/import ─────────────────────────────────────────────────


@mcp.tool
def export_config(
    datastore_ids: list[int],
    output_dir: str = "qualytics-export",
    include: list[str] | None = None,
) -> dict:
    """Export Qualytics configuration as hierarchical YAML for git tracking.

    Exports connections, datastores, containers, and checks.
    Use 'include' to limit: ["connections", "datastores", "containers", "checks"].
    """
    from ..services.export_import import export_config as svc_export

    client = _client()
    include_set = set(include) if include else None
    return _api_call(svc_export, client, datastore_ids, output_dir, include=include_set)


@mcp.tool
def import_config(
    input_dir: str,
    dry_run: bool = False,
    include: list[str] | None = None,
) -> dict:
    """Import Qualytics configuration from a YAML directory with upsert.

    Follows dependency order: connections → datastores → containers → checks.
    Use dry_run=True to preview without making changes.
    """
    from ..services.export_import import import_config as svc_import

    client = _client()
    include_set = set(include) if include else None
    return _api_call(
        svc_import, client, input_dir, dry_run=dry_run, include=include_set
    )
