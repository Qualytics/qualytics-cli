"""Quality checks service functions — export/import, UID, field stripping."""

import re
from pathlib import Path

import yaml

from ..api.client import QualyticsClient
from ..api.quality_checks import (
    list_all_quality_checks,
    create_quality_check,
    update_quality_check,
)
from ..services.containers import get_table_ids
from ..utils.serialization import _SafeStringLoader

# ── Stable UID ────────────────────────────────────────────────────────────

_UID_KEY = "_qualytics_check_uid"

# Cross-reference rule types that use ref_container_id / ref_datastore_id
_CROSS_REF_RULES = frozenset({"existsIn", "notExistsIn", "isReplicaOf", "dataDiff"})


def _slugify(text: str) -> str:
    """Lowercase, replace non-alnum with underscores, collapse multiples."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def generate_check_uid(container_name: str, rule_type: str, fields: list[str]) -> str:
    """Build a stable UID: container__rule_type__field1_field2."""
    parts = [_slugify(container_name), _slugify(rule_type)]
    if fields:
        parts.append("_".join(_slugify(f) for f in sorted(fields)))
    return "__".join(parts)


def check_filename(rule_type: str, fields: list[str]) -> str:
    """Build a git-friendly filename: rule_type__field(s).yaml."""
    parts = [_slugify(rule_type)]
    if fields:
        parts.append("_".join(_slugify(f) for f in sorted(fields)))
    return "__".join(parts) + ".yaml"


# ── Field stripping for portable export ───────────────────────────────────

# Fields to keep in the portable YAML (order matters for readability)
_PORTABLE_FIELD_ORDER = [
    "rule_type",
    "description",
    "container",
    "fields",
    "coverage",
    "filter",
    "properties",
    "tags",
    "status",
    "additional_metadata",
]


def strip_for_export(check: dict) -> dict:
    """Convert an API response check into a portable, git-friendly dict."""
    container_name = ""
    if check.get("container"):
        container_name = check["container"].get("name", "")

    field_names = []
    if check.get("fields"):
        field_names = [f["name"] for f in check["fields"]]

    tag_names = []
    if check.get("global_tags"):
        tag_names = [t["name"] for t in check["global_tags"]]

    # Copy properties and resolve cross-references to names
    properties = check.get("properties") or {}

    portable: dict = {
        "rule_type": check.get("rule_type"),
        "description": check.get("description", ""),
        "container": container_name,
        "fields": field_names,
        "coverage": check.get("coverage"),
        "filter": check.get("filter"),
        "properties": properties,
        "tags": tag_names,
        "status": check.get("status", "Active"),
        "additional_metadata": {},
    }

    # Inject stable UID into additional_metadata
    uid = generate_check_uid(container_name, check.get("rule_type", ""), field_names)
    portable["additional_metadata"][_UID_KEY] = uid

    # Preserve user-defined additional_metadata (minus internal tracking keys)
    if check.get("additional_metadata"):
        for k, v in check["additional_metadata"].items():
            if k not in ("from quality check id", "main datastore id"):
                portable["additional_metadata"][k] = v

    return portable


# ── Directory-based export ────────────────────────────────────────────────


def export_checks_to_directory(checks: list[dict], output_dir: str) -> dict[str, int]:
    """Write one YAML file per check, organized by container.

    Returns {"exported": N, "containers": M}.
    """
    base = Path(output_dir)
    containers_seen: set[str] = set()
    # Track filenames per container to handle duplicates
    used_filenames: dict[str, set[str]] = {}
    exported = 0

    for check in checks:
        portable = strip_for_export(check)
        container = portable["container"] or "_no_container"
        container_slug = (
            _slugify(container) if container != "_no_container" else container
        )
        containers_seen.add(container_slug)

        container_dir = base / container_slug
        container_dir.mkdir(parents=True, exist_ok=True)

        fname = check_filename(
            portable["rule_type"] or "unknown",
            portable["fields"],
        )

        # Deduplicate filenames within a container
        if container_slug not in used_filenames:
            used_filenames[container_slug] = set()
        if fname in used_filenames[container_slug]:
            stem = fname.rsplit(".yaml", 1)[0]
            counter = 2
            while f"{stem}_{counter}.yaml" in used_filenames[container_slug]:
                counter += 1
            fname = f"{stem}_{counter}.yaml"
        used_filenames[container_slug].add(fname)

        file_path = container_dir / fname
        with open(file_path, "w") as f:
            yaml.safe_dump(
                portable,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
        exported += 1

    return {"exported": exported, "containers": len(containers_seen)}


# ── Directory-based import ────────────────────────────────────────────────


def load_checks_from_directory(input_dir: str) -> list[dict]:
    """Read all YAML check files from a directory tree."""
    base = Path(input_dir)
    checks: list[dict] = []
    for yaml_file in sorted(base.rglob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.load(f, Loader=_SafeStringLoader)
        if isinstance(data, dict) and "rule_type" in data:
            data["_source_file"] = str(yaml_file.relative_to(base))
            checks.append(data)
    return checks


def _build_uid_lookup(client: QualyticsClient, datastore_id: int) -> dict[str, int]:
    """Build a mapping of _qualytics_check_uid → check_id for a datastore."""
    existing = list_all_quality_checks(client, datastore_id)
    lookup: dict[str, int] = {}
    for check in existing:
        meta = check.get("additional_metadata") or {}
        uid = meta.get(_UID_KEY)
        if uid:
            lookup[uid] = check["id"]
    return lookup


def _build_create_payload(check: dict, container_id: int) -> dict:
    """Convert a portable check dict into a POST /quality-checks payload."""
    return {
        "container_id": container_id,
        "rule": check["rule_type"],
        "description": check.get("description", ""),
        "fields": check.get("fields") or [],
        "coverage": check.get("coverage"),
        "filter": check.get("filter"),
        "properties": check.get("properties") or {},
        "tags": check.get("tags") or [],
        "additional_metadata": check.get("additional_metadata") or {},
        "status": check.get("status", "Active"),
    }


def _build_update_payload(check: dict) -> dict:
    """Convert a portable check dict into a PUT /quality-checks/{id} payload."""
    return {
        "description": check.get("description", ""),
        "fields": check.get("fields") or [],
        "coverage": check.get("coverage"),
        "filter": check.get("filter"),
        "properties": check.get("properties") or {},
        "tags": check.get("tags") or [],
        "additional_metadata": check.get("additional_metadata") or {},
        "status": check.get("status", "Active"),
    }


def import_checks_to_datastore(
    client: QualyticsClient,
    datastore_id: int,
    checks: list[dict],
    *,
    dry_run: bool = False,
) -> dict[str, int | list]:
    """Import checks to a single datastore with upsert logic.

    Returns {created: N, updated: N, failed: N, errors: [...]}.
    """
    # Resolve container names → IDs
    table_ids = get_table_ids(client=client, datastore_id=datastore_id)
    if table_ids is None:
        return {
            "created": 0,
            "updated": 0,
            "failed": len(checks),
            "errors": [f"Could not resolve containers for datastore {datastore_id}"],
        }

    # Build UID lookup for upsert matching
    uid_lookup = _build_uid_lookup(client, datastore_id)

    created = 0
    updated = 0
    failed = 0
    errors: list[str] = []

    for check in checks:
        container_name = check.get("container", "")
        source = check.get("_source_file", "unknown")

        container_id = table_ids.get(container_name)
        if container_id is None:
            errors.append(
                f"Container '{container_name}' not found in datastore {datastore_id} ({source})"
            )
            failed += 1
            continue

        uid = (check.get("additional_metadata") or {}).get(_UID_KEY)

        if dry_run:
            if uid and uid in uid_lookup:
                updated += 1
            else:
                created += 1
            continue

        try:
            if uid and uid in uid_lookup:
                # Update existing check
                existing_id = uid_lookup[uid]
                payload = _build_update_payload(check)
                update_quality_check(client, existing_id, payload)
                updated += 1
            else:
                # Create new check
                payload = _build_create_payload(check, container_id)
                result = create_quality_check(client, payload)
                created += 1
                # Register UID for subsequent duplicate detection within this run
                if uid:
                    uid_lookup[uid] = result["id"]
        except Exception as e:
            errors.append(f"Failed on '{source}': {e}")
            failed += 1

    return {"created": created, "updated": updated, "failed": failed, "errors": errors}
