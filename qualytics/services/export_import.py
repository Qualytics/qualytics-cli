"""Export/import service — hierarchical YAML config-as-code.

Folder structure produced by export::

    <output>/
        connections/
            <connection_name>.yaml
        datastores/
            <datastore_name>/
                _datastore.yaml
                containers/
                    <container_name>/
                        _container.yaml
                checks/
                    <container_slug>/
                        <rule_type>__<fields>.yaml

Import reads the same structure in dependency order:
connections → datastores → containers → quality checks.
"""

import re
from pathlib import Path

import yaml

from ..api.client import QualyticsClient
from ..api.connections import (
    create_connection,
    update_connection,
)
from ..api.containers import (
    create_container,
    list_all_containers,
    update_container,
)
from ..api.datastores import (
    connect_enrichment,
    create_datastore,
    get_datastore,
    update_datastore,
)
from ..api.quality_checks import list_all_quality_checks
from ..services.connections import get_connection_by_name
from ..services.containers import get_container_by_name
from ..services.datastores import get_datastore_by_name
from ..services.quality_checks import (
    export_checks_to_directory,
    import_checks_to_datastore,
    load_checks_from_directory,
)
from ..utils.secrets import resolve_env_vars
from ..utils.serialization import _SafeStringLoader

# ── Helpers ──────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    """Lowercase, replace non-alnum with underscores, collapse multiples."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _write_yaml(path: Path, data: dict) -> bool:
    """Write *data* as YAML to *path*.

    Returns True if the file was written (content changed or new),
    False if the file already had identical content.
    """
    content = yaml.safe_dump(
        data,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    if path.exists() and path.read_text() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def _generate_env_var_name(connection_name: str, field: str) -> str:
    """Generate an env var placeholder: ``${CONN_NAME_FIELD}``."""
    prefix = _slugify(connection_name).upper()
    return f"${{{prefix}_{field.upper()}}}"


# ── Secrets fields to strip / placeholder ────────────────────────────────

_CONNECTION_SECRET_FIELDS = frozenset({"password", "secret_key", "credentials_payload"})

# Fields the API never returns (already masked), but we still want
# placeholder env vars in the export for documentation.
_CONNECTION_SENSITIVE_FIELDS = frozenset(
    {"password", "secret_key", "credentials_payload", "access_key"}
)

# Internal-only connection fields to strip on export
_CONNECTION_INTERNAL_FIELDS = frozenset(
    {
        "id",
        "created",
        "connection_type",
        "datastores",
        "product_name",
        "product_version",
        "driver_name",
        "driver_version",
    }
)

# Internal-only datastore fields to strip on export
_DATASTORE_INTERNAL_FIELDS = frozenset(
    {
        "id",
        "created",
        "connected",
        "favorite",
        "latest_operation",
        "metrics",
        "anomaly_count",
        "check_count",
        "container_count",
        "field_count",
        "record_count",
        "score",
        "overall_score",
        "completeness_score",
        "conformity_score",
        "consistency_score",
        "precision_score",
        "timeliness_score",
        "volume_score",
        "accuracy_score",
        "uniqueness_score",
        "containers",
        "connection",
    }
)

# Container internal fields to strip
_CONTAINER_INTERNAL_FIELDS = frozenset(
    {
        "id",
        "created",
        "status",
        "metrics",
        "computed_fields",
        "field_count",
        "anomaly_count",
        "check_count",
        "record_count",
        "score",
        "cataloged",
        "datastore",
    }
)

# Computed container types
_COMPUTED_TYPES = frozenset({"computed_table", "computed_file", "computed_join"})

# ── Strip functions ──────────────────────────────────────────────────────


def strip_connection_for_export(conn: dict) -> dict:
    """Convert an API connection response into a portable YAML dict.

    Secret fields are replaced with ``${ENV_VAR}`` placeholders.
    """
    portable: dict = {}
    for key, value in conn.items():
        if key in _CONNECTION_INTERNAL_FIELDS:
            continue
        if key in _CONNECTION_SENSITIVE_FIELDS:
            # Replace with env-var placeholder
            conn_name = conn.get("name", "unknown")
            portable[key] = _generate_env_var_name(conn_name, key)
            continue
        portable[key] = value
    return portable


def strip_datastore_for_export(ds: dict) -> dict:
    """Convert an API datastore response into a portable YAML dict.

    Replaces ``connection`` object with ``connection_name`` string.
    Replaces ``enrichment_datastore`` object with ``enrichment_datastore_name``.
    """
    portable: dict = {}

    # Connection reference → name
    conn = ds.get("connection")
    if conn and isinstance(conn, dict):
        portable["connection_name"] = conn.get("name", "")

    # Enrichment reference → name
    enrichment = ds.get("enrichment_datastore")
    if enrichment and isinstance(enrichment, dict):
        portable["enrichment_datastore_name"] = enrichment.get("name", "")

    for key, value in ds.items():
        if key in _DATASTORE_INTERNAL_FIELDS:
            continue
        if key == "enrichment_datastore":
            continue
        portable[key] = value

    return portable


def strip_container_for_export(container: dict, ds_name: str) -> dict:
    """Convert an API container response into a portable YAML dict.

    Only computed containers are exported (table/view/file are cataloged).
    Replaces ID references with name references.
    """
    portable: dict = {}

    for key, value in container.items():
        if key in _CONTAINER_INTERNAL_FIELDS:
            continue
        # Replace source_container_id → source_container_name
        if key == "source_container" and isinstance(value, dict):
            portable["source_container_name"] = value.get("name", "")
            continue
        if key == "left_container" and isinstance(value, dict):
            portable["left_container_name"] = value.get("name", "")
            continue
        if key == "right_container" and isinstance(value, dict):
            portable["right_container_name"] = value.get("name", "")
            continue
        # Skip raw ID fields (we use names instead)
        if key in (
            "source_container_id",
            "left_container_id",
            "right_container_id",
            "datastore_id",
        ):
            continue
        portable[key] = value

    portable["datastore_name"] = ds_name
    return portable


# ── Export orchestrator ──────────────────────────────────────────────────


def export_config(
    client: QualyticsClient,
    datastore_ids: list[int],
    output_dir: str,
    *,
    include: set[str] | None = None,
) -> dict:
    """Export connections, datastores, containers, and checks to a folder tree.

    Args:
        client: Authenticated API client.
        datastore_ids: Datastore IDs to export.
        output_dir: Root output directory.
        include: Resource types to include. ``None`` = all.
            Valid values: ``{"connections", "datastores", "containers", "checks"}``.

    Returns a summary dict with counts per resource type.
    """
    if include is None:
        include = {"connections", "datastores", "containers", "checks"}

    base = Path(output_dir)
    summary: dict = {
        "connections": 0,
        "datastores": 0,
        "containers": 0,
        "checks": 0,
    }
    seen_connections: set[str] = set()

    for ds_id in datastore_ids:
        # Fetch datastore
        ds = get_datastore(client, ds_id)
        ds_name = ds.get("name", f"datastore_{ds_id}")
        ds_slug = _slugify(ds_name)

        # ── Connection ───────────────────────────────────────────────
        if "connections" in include:
            conn = ds.get("connection")
            if conn and isinstance(conn, dict):
                conn_name = conn.get("name", "")
                if conn_name and conn_name not in seen_connections:
                    seen_connections.add(conn_name)
                    portable_conn = strip_connection_for_export(conn)
                    conn_path = base / "connections" / f"{_slugify(conn_name)}.yaml"
                    _write_yaml(conn_path, portable_conn)
                    summary["connections"] += 1

            # Also export enrichment connection if present
            enrichment_ds = ds.get("enrichment_datastore")
            if enrichment_ds and isinstance(enrichment_ds, dict):
                enr_conn = enrichment_ds.get("connection")
                if enr_conn and isinstance(enr_conn, dict):
                    enr_conn_name = enr_conn.get("name", "")
                    if enr_conn_name and enr_conn_name not in seen_connections:
                        seen_connections.add(enr_conn_name)
                        portable_enr = strip_connection_for_export(enr_conn)
                        enr_path = (
                            base / "connections" / f"{_slugify(enr_conn_name)}.yaml"
                        )
                        _write_yaml(enr_path, portable_enr)
                        summary["connections"] += 1

        # ── Datastore ────────────────────────────────────────────────
        if "datastores" in include:
            portable_ds = strip_datastore_for_export(ds)
            ds_path = base / "datastores" / ds_slug / "_datastore.yaml"
            _write_yaml(ds_path, portable_ds)
            summary["datastores"] += 1

        # ── Containers (computed only) ───────────────────────────────
        if "containers" in include:
            all_containers = list_all_containers(client, datastore=[ds_id])
            for container in all_containers:
                ct = container.get("container_type", "")
                if ct not in _COMPUTED_TYPES:
                    continue
                c_name = container.get("name", "")
                c_slug = (
                    _slugify(c_name) if c_name else f"container_{container.get('id')}"
                )
                portable_c = strip_container_for_export(container, ds_name)
                c_path = (
                    base
                    / "datastores"
                    / ds_slug
                    / "containers"
                    / c_slug
                    / "_container.yaml"
                )
                _write_yaml(c_path, portable_c)
                summary["containers"] += 1

        # ── Quality checks ───────────────────────────────────────────
        if "checks" in include:
            all_checks = list_all_quality_checks(client, ds_id)
            if all_checks:
                checks_dir = base / "datastores" / ds_slug / "checks"
                result = export_checks_to_directory(all_checks, str(checks_dir))
                summary["checks"] += result["exported"]

    return summary


# ── Import orchestrator ──────────────────────────────────────────────────


def _resolve_connection_secrets(portable: dict) -> dict:
    """Resolve ``${ENV_VAR}`` placeholders in connection sensitive fields.

    Returns a copy with resolved values.  Raises ``ValueError`` on
    unresolved env vars.
    """
    resolved = dict(portable)
    for field in _CONNECTION_SENSITIVE_FIELDS:
        if field in resolved and isinstance(resolved[field], str):
            resolved[field] = resolve_env_vars(resolved[field])
    return resolved


def _import_connections(
    client: QualyticsClient,
    connections_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Import connections from ``connections/*.yaml``.

    Returns {created: N, updated: N, failed: N, errors: [...]}.
    """
    result: dict = {"created": 0, "updated": 0, "failed": 0, "errors": []}

    if not connections_dir.is_dir():
        return result

    for yaml_file in sorted(connections_dir.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.load(f, Loader=_SafeStringLoader)
            if not isinstance(data, dict) or "name" not in data:
                result["errors"].append(f"Skipped {yaml_file.name}: no 'name' field")
                result["failed"] += 1
                continue

            conn_name = data["name"]

            if dry_run:
                existing = get_connection_by_name(client, conn_name)
                if existing:
                    result["updated"] += 1
                else:
                    result["created"] += 1
                continue

            # Resolve env var placeholders in secret fields
            try:
                resolved = _resolve_connection_secrets(data)
            except ValueError as e:
                result["errors"].append(f"{yaml_file.name}: {e}")
                result["failed"] += 1
                continue

            # Upsert: find by name
            existing = get_connection_by_name(client, conn_name)
            if existing:
                update_connection(client, existing["id"], resolved)
                result["updated"] += 1
            else:
                create_connection(client, resolved)
                result["created"] += 1

        except Exception as e:
            result["errors"].append(f"{yaml_file.name}: {e}")
            result["failed"] += 1

    return result


def _import_datastore(
    client: QualyticsClient,
    ds_dir: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Import a single datastore from ``datastores/<name>/_datastore.yaml``.

    Returns {created: N, updated: N, failed: N, errors: [], datastore_id: int | None}.
    """
    result: dict = {
        "created": 0,
        "updated": 0,
        "failed": 0,
        "errors": [],
        "datastore_id": None,
    }

    ds_file = ds_dir / "_datastore.yaml"
    if not ds_file.exists():
        return result

    try:
        with open(ds_file) as f:
            data = yaml.load(f, Loader=_SafeStringLoader)
        if not isinstance(data, dict) or "name" not in data:
            result["errors"].append(f"Skipped {ds_file}: no 'name' field")
            result["failed"] += 1
            return result

        ds_name = data["name"]

        # Resolve connection_name → connection_id
        conn_name = data.pop("connection_name", None)
        enrichment_ds_name = data.pop("enrichment_datastore_name", None)

        if conn_name and "connection_id" not in data:
            conn = get_connection_by_name(client, conn_name)
            if conn:
                data["connection_id"] = conn["id"]
            else:
                result["errors"].append(
                    f"Connection '{conn_name}' not found for datastore '{ds_name}'"
                )
                result["failed"] += 1
                return result

        if dry_run:
            existing = get_datastore_by_name(client, ds_name)
            if existing:
                result["updated"] += 1
                result["datastore_id"] = existing["id"]
            else:
                result["created"] += 1
            return result

        # Upsert: find by name
        existing = get_datastore_by_name(client, ds_name)
        if existing:
            ds_id = existing["id"]
            # Don't send trigger_catalog on update
            data.pop("trigger_catalog", None)
            update_datastore(client, ds_id, data)
            result["updated"] += 1
            result["datastore_id"] = ds_id
        else:
            resp = create_datastore(client, data)
            ds_id = resp.get("id")
            result["created"] += 1
            result["datastore_id"] = ds_id

        # Link enrichment if specified
        if enrichment_ds_name and ds_id:
            enr_ds = get_datastore_by_name(client, enrichment_ds_name)
            if enr_ds:
                try:
                    connect_enrichment(client, ds_id, enr_ds["id"])
                except Exception as e:
                    result["errors"].append(
                        f"Failed to link enrichment '{enrichment_ds_name}': {e}"
                    )

    except Exception as e:
        result["errors"].append(f"{ds_dir.name}: {e}")
        result["failed"] += 1

    return result


def _import_containers(
    client: QualyticsClient,
    ds_dir: Path,
    datastore_id: int,
    *,
    dry_run: bool = False,
) -> dict:
    """Import computed containers from ``datastores/<name>/containers/``.

    Returns {created: N, updated: N, failed: N, errors: []}.
    """
    result: dict = {"created": 0, "updated": 0, "failed": 0, "errors": []}

    containers_dir = ds_dir / "containers"
    if not containers_dir.is_dir():
        return result

    for container_dir in sorted(containers_dir.iterdir()):
        if not container_dir.is_dir():
            continue
        yaml_file = container_dir / "_container.yaml"
        if not yaml_file.exists():
            continue

        try:
            with open(yaml_file) as f:
                data = yaml.load(f, Loader=_SafeStringLoader)
            if not isinstance(data, dict) or "name" not in data:
                result["errors"].append(f"Skipped {yaml_file}: no 'name' field")
                result["failed"] += 1
                continue

            c_name = data["name"]
            c_type = data.get("container_type", "")

            if c_type not in _COMPUTED_TYPES:
                continue

            # Strip non-API fields
            data.pop("datastore_name", None)

            # Resolve name references to IDs
            _resolve_container_refs(client, data, datastore_id)

            if dry_run:
                existing = get_container_by_name(client, datastore_id, c_name)
                if existing:
                    result["updated"] += 1
                else:
                    result["created"] += 1
                continue

            # Upsert
            existing = get_container_by_name(client, datastore_id, c_name)
            if existing:
                update_container(client, existing["id"], data)
                result["updated"] += 1
            else:
                data["datastore_id"] = datastore_id
                create_container(client, data)
                result["created"] += 1

        except Exception as e:
            result["errors"].append(f"{container_dir.name}: {e}")
            result["failed"] += 1

    return result


def _resolve_container_refs(
    client: QualyticsClient, data: dict, datastore_id: int
) -> None:
    """Resolve container name references to IDs in-place.

    Handles ``source_container_name``, ``left_container_name``,
    ``right_container_name``.
    """
    for name_key, id_key in [
        ("source_container_name", "source_container_id"),
        ("left_container_name", "left_container_id"),
        ("right_container_name", "right_container_id"),
    ]:
        ref_name = data.pop(name_key, None)
        if ref_name and id_key not in data:
            ref = get_container_by_name(client, datastore_id, ref_name)
            if ref:
                data[id_key] = ref["id"]
            else:
                raise ValueError(
                    f"Referenced container '{ref_name}' not found in datastore"
                )


def import_config(
    client: QualyticsClient,
    input_dir: str,
    *,
    dry_run: bool = False,
    include: set[str] | None = None,
) -> dict:
    """Import connections, datastores, containers, and checks from a folder tree.

    Import order: connections → datastores → containers → quality checks.

    Args:
        client: Authenticated API client.
        input_dir: Root input directory.
        dry_run: Preview only, no mutations.
        include: Resource types to include. ``None`` = all.

    Returns a summary dict with counts per resource type.
    """
    if include is None:
        include = {"connections", "datastores", "containers", "checks"}

    base = Path(input_dir)
    summary: dict = {
        "connections": {"created": 0, "updated": 0, "failed": 0, "errors": []},
        "datastores": {"created": 0, "updated": 0, "failed": 0, "errors": []},
        "containers": {"created": 0, "updated": 0, "failed": 0, "errors": []},
        "checks": {"created": 0, "updated": 0, "failed": 0, "errors": []},
    }

    # 1. Connections
    if "connections" in include:
        conn_result = _import_connections(client, base / "connections", dry_run=dry_run)
        summary["connections"] = conn_result

    # 2. Datastores + 3. Containers + 4. Checks (per datastore directory)
    datastores_dir = base / "datastores"
    if not datastores_dir.is_dir():
        return summary

    for ds_dir in sorted(datastores_dir.iterdir()):
        if not ds_dir.is_dir():
            continue

        # Import datastore
        ds_id = None
        if "datastores" in include:
            ds_result = _import_datastore(client, ds_dir, dry_run=dry_run)
            summary["datastores"]["created"] += ds_result["created"]
            summary["datastores"]["updated"] += ds_result["updated"]
            summary["datastores"]["failed"] += ds_result["failed"]
            summary["datastores"]["errors"].extend(ds_result["errors"])
            ds_id = ds_result.get("datastore_id")
        else:
            # Still need to resolve the datastore ID for containers/checks
            ds_file = ds_dir / "_datastore.yaml"
            if ds_file.exists():
                with open(ds_file) as f:
                    ds_data = yaml.load(f, Loader=_SafeStringLoader)
                if isinstance(ds_data, dict) and "name" in ds_data:
                    existing = get_datastore_by_name(client, ds_data["name"])
                    if existing:
                        ds_id = existing["id"]

        if ds_id is None and not dry_run:
            summary["datastores"]["errors"].append(
                f"Could not resolve datastore ID for {ds_dir.name}"
            )
            continue

        # Import containers
        if "containers" in include and ds_id is not None:
            c_result = _import_containers(client, ds_dir, ds_id, dry_run=dry_run)
            summary["containers"]["created"] += c_result["created"]
            summary["containers"]["updated"] += c_result["updated"]
            summary["containers"]["failed"] += c_result["failed"]
            summary["containers"]["errors"].extend(c_result["errors"])

        # Import checks
        if "checks" in include and ds_id is not None:
            checks_dir = ds_dir / "checks"
            if checks_dir.is_dir():
                checks = load_checks_from_directory(str(checks_dir))
                if checks:
                    ck_result = import_checks_to_datastore(
                        client, ds_id, checks, dry_run=dry_run
                    )
                    summary["checks"]["created"] += ck_result["created"]
                    summary["checks"]["updated"] += ck_result["updated"]
                    summary["checks"]["failed"] += ck_result["failed"]
                    summary["checks"]["errors"].extend(ck_result["errors"])

    return summary
