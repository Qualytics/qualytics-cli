"""Check sheet → Qualytics quality check + computed container conversion.

The check sheet is a normalized tabular template (XLSX or CSV, header-name
based) with one row per quality check or per computed container, designed to be
filled by hand from a client's own check catalog. ``convert_sheet`` turns it
into portable check dicts in the same shape as ``strip_for_export`` — ready for
``import_checks_to_datastore`` — plus computed-container specs for the
container phase of ``migrate apply``.

Conversion and reporting are pure logic — no API client, no auth, no network.
The container phase at the bottom of the module (``ensure_containers``,
``wait_for_container_profile``) is the client-bound half used by
``migrate apply``.

Design invariants (shared with ``services.dbt``):

* **Every UID is distinct.** The UID derives from the sheet's ``check_id``
  column, which the sheet author owns; a duplicate ``check_id`` is a plan
  error, never a silent upsert collision.
* **The client key survives.** ``check_id`` is also stamped verbatim as
  ``additional_metadata.legacy_check_id``, so every created check can be traced
  back to the source catalog row.
* **Row problems are reported, not raised.** A malformed row becomes a
  ``RowIssue`` and the rest of the sheet still converts; ``migrate apply``
  refuses to touch rows with error-level issues.
"""

import csv
import json
import re
from typing import Any

from .rules import contract_for, CROSS_REF_RULES, one_sided_between

UID_PREFIX = "sheet__"

KIND_CHECK = "check"
KIND_COMPUTED_TABLE = "computed_table"
KIND_COMPUTED_JOIN = "computed_join"
CONTAINER_KINDS = (KIND_COMPUTED_TABLE, KIND_COMPUTED_JOIN)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

_VALID_STATUSES = ("Active", "Draft")

# Column-header prefix for custom additional_metadata: a `metadata:<key>`
# column stamps <key> (verbatim) onto every row with a non-empty cell, so one
# sheet can carry different metadata keys for different subsets of rows.
METADATA_PREFIX = "metadata:"

# Keys the converter owns; a metadata: column may not override them.
_RESERVED_METADATA_KEYS = frozenset({"legacy_check_id", "_qualytics_check_uid"})

# Columns consumed by the converter. Anything else is preserved on the check
# as additional_metadata so sheet-only context (owner, source system, notes)
# survives the migration instead of being silently dropped.
_KNOWN_COLUMNS = frozenset(
    {
        "kind",
        "check_id",
        "datastore",
        "container",
        "rule_type",
        "description",
        "fields",
        "filter",
        "coverage",
        "tags",
        "status",
        "value",
        "min",
        "max",
        "inclusive",
        "inclusive_min",
        "inclusive_max",
        "pattern",
        "expression",
        "comparison",
        "ref_expression",
        "ref_datastore",
        "ref_container",
        "ref_field",
        "ref_filter",
        "anomaly_message_field",
        "properties_json",
        "query",
        "sources",
    }
)

# Sheet columns each rule cannot do without. Checked offline at plan time so
# a half-filled row fails in front of the author, not one POST at a time
# against the target instance.
RULE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "freshness": ("value",),
    "existsIn": ("fields", "ref_container", "ref_field"),
    "notExistsIn": ("fields", "ref_container", "ref_field"),
    "aggregationComparison": (
        "expression",
        "comparison",
        "ref_container",
        "ref_expression",
    ),
    "equalTo": ("fields", "value"),
    "greaterThan": ("fields", "value"),
    "lessThan": ("fields", "value"),
    "between": ("fields",),
    "matchesPattern": ("fields", "pattern"),
    "satisfiesExpression": ("expression",),
    "notNull": ("fields",),
    "unique": ("fields",),
}

# ── Row containers ────────────────────────────────────────────────────────


class RowIssue:
    """A problem found in one sheet row, graded by severity.

    ``error`` rows never apply; ``warning`` rows apply but deserve a look
    (e.g. date-now SQL without an explicit timezone conversion).
    """

    __slots__ = ("row", "check_id", "severity", "message")

    def __init__(self, row: int, check_id: str, severity: str, message: str):
        self.row = row
        self.check_id = check_id
        self.severity = severity
        self.message = message

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"RowIssue(row={self.row}, {self.severity}: {self.message})"


class SheetCheck:
    """A converted check plus the provenance needed to report on it."""

    __slots__ = ("check", "row", "check_id", "datastore", "container")

    def __init__(self, check: dict, row: int, check_id: str, datastore, container):
        self.check = check
        self.row = row
        self.check_id = check_id
        self.datastore = datastore  # per-row target override (name/id), or None
        self.container = container


class ContainerSpec:
    """A computed container to ensure before the check phase."""

    __slots__ = ("kind", "name", "row", "check_id", "datastore", "spec")

    def __init__(self, kind: str, name: str, row: int, check_id: str, datastore, spec):
        self.kind = kind
        self.name = name
        self.row = row
        self.check_id = check_id
        self.datastore = datastore
        self.spec = spec  # API payload fragment (no datastore_id/ids yet)


class SheetPlan:
    """Everything ``convert_sheet`` learned from one sheet."""

    __slots__ = ("checks", "containers", "issues")

    def __init__(
        self,
        checks: list[SheetCheck],
        containers: list[ContainerSpec],
        issues: list[RowIssue],
    ):
        self.checks = checks
        self.containers = containers
        self.issues = issues

    @property
    def errors(self) -> list[RowIssue]:
        return [i for i in self.issues if i.severity == SEVERITY_ERROR]

    @property
    def warnings(self) -> list[RowIssue]:
        return [i for i in self.issues if i.severity == SEVERITY_WARNING]


# ── Sheet loading ─────────────────────────────────────────────────────────


def _normalize_header(header) -> str:
    raw = str(header or "").strip()
    # `metadata:<key>` columns keep the key verbatim — the whole point is
    # stamping the client's exact metadata key, so normalization must not
    # touch its casing or punctuation.
    if raw.lower().startswith(METADATA_PREFIX):
        key = raw[len(METADATA_PREFIX) :].strip()
        return f"{METADATA_PREFIX}{key}" if key else ""
    text = re.sub(r"[^a-z0-9]+", "_", raw.lower())
    return text.strip("_")


def _clean(value):
    """Trim strings; collapse empties to None; leave real numbers alone."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def load_sheet(path: str) -> list[dict]:
    """Read a check sheet into row dicts keyed by normalized header name.

    Supports ``.xlsx``/``.xls`` (first worksheet) and ``.csv``. Each row dict
    carries ``_row``: its 1-based position in the file (header included), so
    issues can point at the exact spreadsheet line.
    """
    lower = path.lower()
    if lower.endswith((".xlsx", ".xls")):
        rows = _load_xlsx(path)
    elif lower.endswith(".csv"):
        rows = _load_csv(path)
    else:
        raise ValueError(
            f"Unsupported sheet format: {path} (expected .xlsx, .xls or .csv)"
        )
    # Drop rows with no values at all (spreadsheets love trailing blanks).
    return [r for r in rows if any(v is not None for k, v in r.items() if k != "_row")]


def _load_csv(path: str) -> list[dict]:
    out: list[dict] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers: list[str] | None = None
        for line_num, raw in enumerate(reader, start=1):
            if headers is None:
                headers = [_normalize_header(h) for h in raw]
                continue
            row = {h: _clean(v) for h, v in zip(headers, raw) if h}
            row["_row"] = line_num
            out.append(row)
    return out


def _load_xlsx(path: str) -> list[dict]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        out: list[dict] = []
        headers: list[str] | None = None
        for line_num, raw in enumerate(sheet.iter_rows(values_only=True), start=1):
            if headers is None:
                headers = [_normalize_header(h) for h in raw]
                continue
            row = {h: _clean(v) for h, v in zip(headers, raw) if h}
            row["_row"] = line_num
            out.append(row)
        return out
    finally:
        workbook.close()


# ── Value parsing ─────────────────────────────────────────────────────────

_DURATION_MS = {
    "ms": 1,
    "s": 1_000,
    "m": 60_000,
    "h": 3_600_000,
    "d": 86_400_000,
    "w": 604_800_000,
}


def parse_duration_ms(value) -> int | None:
    """A freshness max-age: raw milliseconds, or shorthand like ``36h``/``7d``.

    Returns None when the value cannot be read as a duration.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    text = str(value or "").strip().lower()
    if not text:
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h|d|w)?", text)
    if not match:
        return None
    amount = float(match.group(1))
    unit = _DURATION_MS[match.group(2) or "ms"]
    result = int(amount * unit)
    return result if result > 0 else None


def _parse_list(value) -> list[str]:
    """A comma/semicolon-separated cell → list of names."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    parts = re.split(r"[;,]", str(value))
    return [p.strip() for p in parts if p.strip()]


def _parse_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "n"}


def _coerce_number(value):
    """Best-effort numeric coercion; returns None when not a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return None


def parse_sources(value) -> list[dict] | None:
    """Computed-join sources: ``orders=o; customers=c`` pairs or a JSON list.

    Aliases default to the container name. Returns None on unparseable input.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return None
        out = []
        for item in loaded:
            if isinstance(item, str):
                out.append({"container": item.strip(), "alias": item.strip()})
            elif isinstance(item, dict) and item.get("container"):
                entry = {
                    "container": str(item["container"]).strip(),
                    "alias": str(item.get("alias") or item["container"]).strip(),
                }
                if item.get("where_clause"):
                    entry["where_clause"] = str(item["where_clause"])
                out.append(entry)
            else:
                return None
        return out or None
    out = []
    for part in _parse_list(value):
        name, _, alias = part.partition("=")
        name = name.strip()
        if not name:
            return None
        out.append({"container": name, "alias": alias.strip() or name})
    return out or None


# Accepted spellings for aggregationComparison/distinctCount comparisons. The
# API takes the ComparisonType names (lt/lte/eq/gte/gt) and the metric-style
# display values; common operators and long forms normalize to the names.
_COMPARISON_ALIASES = {
    "lt": "lt",
    "<": "lt",
    "less than": "lt",
    "lte": "lte",
    "<=": "lte",
    "less than or equal to": "lte",
    "eq": "eq",
    "=": "eq",
    "==": "eq",
    "equal to": "eq",
    "gte": "gte",
    ">=": "gte",
    "greater than or equal to": "gte",
    "gt": "gt",
    ">": "gt",
    "greater than": "gt",
}
_METRIC_COMPARISONS = {"absolute value", "absolute change", "percentage change"}


def normalize_comparison(value) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    alias = _COMPARISON_ALIASES.get(text.lower())
    if alias:
        return alias
    if text.lower() in _METRIC_COMPARISONS:
        return text.title()
    return None


# ── Timezone lint ─────────────────────────────────────────────────────────
# Date logic that anchors to "now" evaluates in the engine's timezone, which
# is rarely the business one. SQL that uses a now-function without an explicit
# conversion gets a warning so the author standardizes deliberately.

_NOW_FUNCTIONS = re.compile(
    r"\b(current_date|current_timestamp|sysdate)\b|\b(now|getdate)\s*\(",
    re.IGNORECASE,
)
_TZ_MARKERS = re.compile(
    r"from_utc_timestamp|to_utc_timestamp|convert_timezone|at\s+time\s+zone",
    re.IGNORECASE,
)


def timezone_suspect(text) -> bool:
    """True when SQL anchors to now() with no visible timezone conversion."""
    if not text:
        return False
    text = str(text)
    return bool(_NOW_FUNCTIONS.search(text)) and not _TZ_MARKERS.search(text)


# ── Conversion ────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def sheet_check_uid(check_id) -> str:
    """Slug form of the sheet's check_id: duplicate detection and filenames.

    The upsert identity itself is the raw ``legacy_check_id`` value (migrate
    apply imports with that as the uid_key), so this slug never lands in
    check metadata — it guards against two check_ids that differ only in
    case/punctuation, and names emitted YAML files.
    """
    return UID_PREFIX + _slugify(check_id)


def _row_metadata(row: dict, fail) -> dict | None:
    """Collect this row's ``metadata:<key>`` cells, keys verbatim.

    An empty cell simply means the key does not apply to this row, so one
    sheet can carry `metadata:X` for some rows and `metadata:Y` for others.
    Returns None (after recording an error) when a column tries to override a
    key the converter owns.
    """
    out: dict[str, Any] = {}
    for column, value in row.items():
        if not column.startswith(METADATA_PREFIX) or value is None:
            continue
        key = column[len(METADATA_PREFIX) :]
        if key in _RESERVED_METADATA_KEYS:
            fail(f"metadata:{key} is reserved — the converter sets it from check_id")
            return None
        out[key] = value if isinstance(value, (int, float)) else str(value)
    return out


def _build_properties(rule_type: str, row: dict, fail) -> dict | None:
    """Assemble rule properties from the flat columns + properties_json.

    ``fail(message)`` records an error-level issue; returning None means the
    row must not produce a check.
    """
    props: dict[str, Any] = {}
    ok = True

    def error(message: str):
        nonlocal ok
        fail(message)
        ok = False

    value = row.get("value")
    if value is not None:
        if rule_type == "freshness":
            parsed = parse_duration_ms(value)
            if parsed is None:
                error(
                    f"value '{value}' is not a duration "
                    "(use milliseconds or shorthand like 36h, 7d)"
                )
            else:
                props["value"] = parsed
        elif rule_type in ("equalTo", "greaterThan", "lessThan"):
            number = _coerce_number(value)
            if number is None:
                error(f"value '{value}' is not numeric")
            else:
                props["value"] = number
                props["inclusive"] = _parse_bool(row.get("inclusive"), True)
        else:
            props["value"] = (
                _coerce_number(value) if _coerce_number(value) is not None else value
            )

    for bound, inclusive_key in (("min", "inclusive_min"), ("max", "inclusive_max")):
        raw = row.get(bound)
        if raw is None:
            continue
        number = _coerce_number(raw)
        if number is None:
            error(f"{bound} '{raw}' is not numeric")
            continue
        props[bound] = number
        props[inclusive_key] = _parse_bool(row.get(inclusive_key), True)

    if row.get("pattern") is not None:
        props["pattern"] = str(row["pattern"])
    if row.get("expression") is not None:
        props["expression"] = str(row["expression"])
    if row.get("ref_expression") is not None:
        props["ref_expression"] = str(row["ref_expression"])
    if row.get("ref_filter") is not None:
        props["ref_filter"] = str(row["ref_filter"])

    if row.get("comparison") is not None:
        comparison = normalize_comparison(row["comparison"])
        if comparison is None:
            error(
                f"comparison '{row['comparison']}' not recognized "
                "(use lt, lte, eq, gte or gt)"
            )
        else:
            props["comparison"] = comparison

    if row.get("ref_container") is not None:
        props["ref_container_name"] = str(row["ref_container"])
    if row.get("ref_datastore") is not None:
        ref_datastore = row["ref_datastore"]
        if isinstance(ref_datastore, int) or str(ref_datastore).strip().isdigit():
            props["ref_datastore_id"] = int(ref_datastore)
        else:
            props["ref_datastore_name"] = str(ref_datastore)
    if row.get("ref_field") is not None:
        props["field_name"] = str(row["ref_field"])

    extra = row.get("properties_json")
    if extra is not None:
        try:
            loaded = json.loads(extra) if isinstance(extra, str) else extra
        except json.JSONDecodeError as e:
            error(f"properties_json is not valid JSON: {e}")
            loaded = None
        if loaded is not None:
            if not isinstance(loaded, dict):
                error("properties_json must be a JSON object")
            else:
                for key, val in loaded.items():
                    if key in props and props[key] != val:
                        error(
                            f"properties_json key '{key}' conflicts with the "
                            f"'{key}' column ({val!r} vs {props[key]!r})"
                        )
                    else:
                        props[key] = val

    return props if ok else None


def _missing_requirements(rule_type: str, row: dict) -> list[str]:
    missing = [
        col for col in RULE_REQUIREMENTS.get(rule_type, ()) if row.get(col) is None
    ]
    if rule_type == "between" and row.get("min") is None and row.get("max") is None:
        missing.append("min or max")
    return missing


def _convert_check_row(
    row: dict,
    row_num: int,
    check_id: str,
    *,
    default_status: str,
    extra_tags: list[str],
    add_issue,
) -> SheetCheck | None:
    def fail(message: str):
        add_issue(RowIssue(row_num, check_id, SEVERITY_ERROR, message))

    def warn(message: str):
        add_issue(RowIssue(row_num, check_id, SEVERITY_WARNING, message))

    rule_type = str(row.get("rule_type") or "").strip()
    if not rule_type:
        fail("rule_type is required for check rows")
        return None
    container = str(row.get("container") or "").strip()
    if not container:
        fail("container is required for check rows")
        return None

    if rule_type not in RULE_REQUIREMENTS and rule_type not in CROSS_REF_RULES:
        warn(
            f"rule_type '{rule_type}' is not in the sheet crosswalk — "
            "properties pass through unvalidated"
        )

    missing = _missing_requirements(rule_type, row)
    if missing:
        fail(f"{rule_type} requires column(s): {', '.join(missing)}")
        return None

    properties = _build_properties(rule_type, row, fail)
    if properties is None:
        return None

    if rule_type == "between":
        rule_type, properties = one_sided_between(properties)

    contract = contract_for(rule_type)
    fields = _parse_list(row.get("fields"))
    if contract.fields == "single" and len(fields) > 1:
        fail(f"{rule_type} takes a single field, got {len(fields)}: {fields}")
        return None

    coverage = 1.0
    if row.get("coverage") is not None:
        number = _coerce_number(row["coverage"])
        if number is None or not 0 <= float(number) <= 1:
            fail(f"coverage '{row['coverage']}' must be a number between 0 and 1")
            return None
        coverage = float(number)

    status = default_status
    if row.get("status") is not None:
        wanted = str(row["status"]).strip()
        match = next((s for s in _VALID_STATUSES if s.lower() == wanted.lower()), None)
        if match is None:
            fail(f"status '{wanted}' must be Active or Draft")
            return None
        status = match

    for column in ("expression", "ref_expression", "filter"):
        if timezone_suspect(row.get(column)):
            warn(
                f"{column} uses a date-now function with no timezone conversion — "
                "standardize (e.g. from_utc_timestamp(..., 'America/New_York'))"
            )

    tags = _parse_list(row.get("tags"))
    for tag in extra_tags:
        if tag not in tags:
            tags.append(tag)

    extra_metadata = _row_metadata(row, fail)
    if extra_metadata is None:
        return None
    # legacy_check_id is both the client's trace key AND the upsert identity —
    # migrate apply imports with uid_key="legacy_check_id", so no internal
    # _qualytics_check_uid needs to appear in the check's visible metadata.
    metadata: dict[str, Any] = {"legacy_check_id": str(check_id)}
    metadata.update(extra_metadata)

    description = str(row.get("description") or "").strip()
    if not description:
        description = f"[sheet {check_id}] {rule_type} on {container}"

    check: dict[str, Any] = {
        "rule_type": rule_type,
        "description": description,
        "container": container,
        "fields": [] if contract.fields == "none" else fields,
        "coverage": coverage if contract.coverage else None,
        "filter": (
            str(row["filter"])
            if contract.filterable and row.get("filter") is not None
            else None
        ),
        "properties": properties,
        "tags": tags,
        "status": status,
        "additional_metadata": metadata,
    }
    if row.get("filter") is not None and not contract.filterable:
        warn(f"{rule_type} does not accept a filter — column ignored")
    if row.get("anomaly_message_field") is not None:
        check["anomaly_message_field"] = str(row["anomaly_message_field"])

    return SheetCheck(check, row_num, str(check_id), row.get("datastore"), container)


def _convert_container_row(
    row: dict,
    row_num: int,
    check_id: str,
    kind: str,
    declared: dict[str, int],
    add_issue,
) -> ContainerSpec | None:
    def fail(message: str):
        add_issue(RowIssue(row_num, check_id, SEVERITY_ERROR, message))

    def warn(message: str):
        add_issue(RowIssue(row_num, check_id, SEVERITY_WARNING, message))

    name = str(row.get("container") or "").strip()
    if not name:
        fail(f"container is required for {kind} rows (the new container's name)")
        return None
    if re.search(r"\s", name):
        warn(
            f"container name '{name}' contains whitespace — "
            "the platform normalizes it to underscores"
        )

    query = str(row.get("query") or "").strip()
    if not query:
        fail(f"query is required for {kind} rows")
        return None

    if timezone_suspect(query):
        warn(
            "query uses a date-now function with no timezone conversion — "
            "standardize (e.g. from_utc_timestamp(..., 'America/New_York'))"
        )

    spec: dict[str, Any] = {"container_type": kind, "name": name, "query": query}
    description = str(row.get("description") or "").strip()
    if description:
        spec["description"] = description

    if kind == KIND_COMPUTED_JOIN:
        sources = parse_sources(row.get("sources"))
        if not sources or len(sources) < 2:
            fail(
                "computed_join requires a sources column naming at least two "
                "containers (e.g. 'orders=o; customers=c')"
            )
            return None
        # A join can read an in-file computed table, but only one declared on
        # an earlier row: apply creates containers in declaration order.
        for source in sources:
            declared_row = declared.get(source["container"])
            if declared_row is not None and declared_row > row_num:
                fail(
                    f"computed_join source '{source['container']}' is declared "
                    f"later in the sheet (row {declared_row}) — move it above "
                    "this row"
                )
                return None
        spec["sources"] = sources
        if re.search(r"\bselect\s+distinct\b", query, re.IGNORECASE):
            warn("computed_join queries with SELECT DISTINCT may be rejected")

    extra_metadata = _row_metadata(row, fail)
    if extra_metadata is None:
        return None
    spec["additional_metadata"] = {
        "legacy_check_id": str(check_id),
        **extra_metadata,
    }

    return ContainerSpec(kind, name, row_num, str(check_id), row.get("datastore"), spec)


def convert_sheet(
    rows: list[dict],
    *,
    default_status: str = "Draft",
    extra_tags: list[str] | None = None,
) -> SheetPlan:
    """Convert loaded sheet rows into checks, container specs and issues."""
    extra_tags = list(extra_tags or [])
    checks: list[SheetCheck] = []
    containers: list[ContainerSpec] = []
    issues: list[RowIssue] = []

    # Columns the converter neither consumes nor stamps are ignored — say so
    # once, because a silently dropped column usually means a typo'd header or
    # a missing metadata: prefix.
    unknown_columns = sorted(
        {
            key
            for row in rows
            for key, value in row.items()
            if value is not None
            and not key.startswith("_")
            and not key.startswith(METADATA_PREFIX)
            and key not in _KNOWN_COLUMNS
        }
    )
    if unknown_columns:
        issues.append(
            RowIssue(
                1,
                "",
                SEVERITY_WARNING,
                f"column(s) not recognized and ignored: "
                f"{', '.join(unknown_columns)} — prefix a column with "
                f"'{METADATA_PREFIX}' to stamp it into additional_metadata",
            )
        )
    seen_ids: dict[str, int] = {}

    # First pass: where each computed container is declared, for join ordering
    # and duplicate-name detection.
    declared: dict[str, int] = {}
    for row in rows:
        kind = _normalize_kind(row.get("kind"))
        name = str(row.get("container") or "").strip()
        if kind in CONTAINER_KINDS and name:
            if name in declared:
                issues.append(
                    RowIssue(
                        row["_row"],
                        str(row.get("check_id") or ""),
                        SEVERITY_ERROR,
                        f"computed container '{name}' is declared more than once "
                        f"(first at row {declared[name]})",
                    )
                )
            else:
                declared[name] = row["_row"]

    for row in rows:
        row_num = row["_row"]
        check_id = row.get("check_id")
        kind = _normalize_kind(row.get("kind"))

        if kind is None:
            issues.append(
                RowIssue(
                    row_num,
                    str(check_id or ""),
                    SEVERITY_ERROR,
                    f"kind '{row.get('kind')}' not recognized "
                    f"(use check, computed_table or computed_join)",
                )
            )
            continue

        if check_id is None:
            issues.append(RowIssue(row_num, "", SEVERITY_ERROR, "check_id is required"))
            continue

        uid_key = sheet_check_uid(check_id)
        if uid_key in seen_ids:
            issues.append(
                RowIssue(
                    row_num,
                    str(check_id),
                    SEVERITY_ERROR,
                    f"duplicate check_id '{check_id}' (first used at row "
                    f"{seen_ids[uid_key]}) — every row needs its own",
                )
            )
            continue
        seen_ids[uid_key] = row_num

        if kind in CONTAINER_KINDS:
            spec = _convert_container_row(
                row, row_num, str(check_id), kind, declared, issues.append
            )
            if spec is not None:
                containers.append(spec)
        else:
            converted = _convert_check_row(
                row,
                row_num,
                str(check_id),
                default_status=default_status,
                extra_tags=extra_tags,
                add_issue=issues.append,
            )
            if converted is not None:
                checks.append(converted)

    return SheetPlan(checks, containers, issues)


def _normalize_kind(value) -> str | None:
    text = re.sub(r"[^a-z]+", "_", str(value or "").strip().lower()).strip("_")
    if text in ("", KIND_CHECK):
        return KIND_CHECK
    if text in CONTAINER_KINDS:
        return text
    return None


# ── Reporting ─────────────────────────────────────────────────────────────


def summarize_sheet(plan: SheetPlan) -> dict:
    """Counts for ``migrate plan``'s summary output."""
    by_rule: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for item in plan.checks:
        rule = item.check["rule_type"]
        by_rule[rule] = by_rule.get(rule, 0) + 1
        status = item.check.get("status") or "Draft"
        by_status[status] = by_status.get(status, 0) + 1

    datastores = sorted(
        {
            str(item.datastore)
            for item in [*plan.checks, *plan.containers]
            if item.datastore is not None
        }
    )
    return {
        "checks": len(plan.checks),
        "containers": len(plan.containers),
        "computed_tables": sum(
            1 for c in plan.containers if c.kind == KIND_COMPUTED_TABLE
        ),
        "computed_joins": sum(
            1 for c in plan.containers if c.kind == KIND_COMPUTED_JOIN
        ),
        "by_rule": dict(sorted(by_rule.items())),
        "by_status": dict(sorted(by_status.items())),
        "errors": len(plan.errors),
        "warnings": len(plan.warnings),
        "datastore_overrides": datastores,
        "target_containers": sorted({c.container for c in plan.checks}),
    }


def to_checks(plan: SheetPlan) -> list[dict]:
    """Strip provenance wrappers, yielding dicts for import_checks_to_datastore."""
    return [item.check for item in plan.checks]


# ── Container-name repair (pure) ──────────────────────────────────────────


def repair_container_names(
    checks: list[dict], catalogued_names: list[str]
) -> list[str]:
    """Fix check container-name casing against the catalogued names, in place.

    The importer matches containers by exact name; a sheet that says ``orders``
    against a warehouse that catalogued ``ORDERS`` would fail every row. As
    with field names, the catalogue is ground truth, so casing is corrected
    rather than flagged. A name with no case-insensitive match (or an
    ambiguous one) is left for the importer to report.

    Returns human-readable corrections.
    """
    by_lower: dict[str, str | None] = {}
    for name in catalogued_names:
        key = name.lower()
        # Two catalogued names differing only by case: ambiguous, don't touch.
        by_lower[key] = None if key in by_lower else name

    corrections: list[str] = []
    for check in checks:
        container = check.get("container") or ""
        if not container or container in catalogued_names:
            continue
        actual = by_lower.get(container.lower())
        if actual and actual != container:
            corrections.append(f"{container} → {actual}")
            check["container"] = actual
    return corrections


# ── Container phase (client-bound) ────────────────────────────────────────
# Everything above is pure conversion; from here down talks to the target
# instance. `migrate apply` ensures the sheet's computed containers exist and
# are profiled before any check that targets them is imported.


def _container_payload(
    spec: ContainerSpec, datastore_id: int, name_to_id: dict[str, int]
) -> tuple[dict | None, str | None]:
    """API payload for one spec, with join sources resolved to container IDs."""
    payload = {key: value for key, value in spec.spec.items() if key != "sources"}
    payload["datastore_id"] = datastore_id
    if spec.kind == KIND_COMPUTED_JOIN:
        sources = []
        for source in spec.spec.get("sources") or []:
            container_id = name_to_id.get(source["container"])
            if container_id is None:
                return None, (
                    f"source container '{source['container']}' not found in "
                    f"datastore {datastore_id}"
                )
            entry = {"container_id": container_id, "alias": source["alias"]}
            if source.get("where_clause"):
                entry["where_clause"] = source["where_clause"]
            sources.append(entry)
        payload["sources"] = sources
    return payload, None


def _definition_changed(spec: ContainerSpec, payload: dict, existing: dict) -> bool:
    """Whether the sheet's definition differs from the live container's.

    Only the definition counts (query, join sources) — labels and metadata are
    handled separately because the platform re-validates and re-profiles on a
    definition change, and resending an identical join `sources` list forces
    that expensive path for nothing.
    """

    def _sql(value) -> str:
        return str(value or "").strip()

    if _sql(payload.get("query")) != _sql(existing.get("query")):
        return True
    if spec.kind != KIND_COMPUTED_JOIN:
        return False

    def _norm(sources) -> list[tuple]:
        return [
            (
                source.get("container_id"),
                source.get("alias"),
                source.get("where_clause") or None,
            )
            for source in sources or []
        ]

    return _norm(payload.get("sources")) != _norm(existing.get("sources"))


def _labels_changed(payload: dict, existing: dict) -> bool:
    """Whether the sheet carries label/metadata values the live container lacks."""
    if "description" in payload and payload["description"] != (
        existing.get("description") or None
    ):
        return True
    if "additional_metadata" in payload and payload["additional_metadata"] != (
        existing.get("additional_metadata") or None
    ):
        return True
    return False


def _latest_profile_operation_id(
    client, container_id: int, datastore_id: int
) -> int | None:
    """The newest profile operation id for a container, or None."""
    from ..api.operations import list_operations

    listing = list_operations(
        client,
        datastore=[datastore_id],
        container=[container_id],
        operation_type="profile",
        sort_created="desc",
        size=1,
    )
    items = listing.get("items") or []
    return items[0]["id"] if items else None


def wait_for_container_profile(
    client,
    container_id: int,
    datastore_id: int,
    *,
    timeout: int = 900,
    poll_interval: int = 10,
    sleep=None,
    after_operation_id: int | None = None,
) -> tuple[bool, str]:
    """Wait for THIS container's auto-triggered profile to finish.

    Creating a computed container kicks off an async profile; checks that name
    the container's fields only work once it completes. The operation is found
    by filtering on the container id — never "the newest profile in the
    datastore", which races against concurrent operations.

    ``after_operation_id`` anchors an UPDATE's wait: the async re-profile can
    register after we first look, and without the anchor the newest completed
    op is the container's previous profile — an instant false success against
    stale fields. Pass the id captured before the write; only younger
    operations count.
    """
    import time as _time

    from ..api.containers import get_field_profiles
    from ..api.operations import get_operation, list_operations

    sleep = sleep or _time.sleep
    deadline = _time.monotonic() + timeout
    operation_id: int | None = None

    while _time.monotonic() < deadline:
        if operation_id is None:
            listing = list_operations(
                client,
                datastore=[datastore_id],
                container=[container_id],
                operation_type="profile",
                sort_created="desc",
                size=1,
            )
            items = listing.get("items") or []
            if items and (
                after_operation_id is None or items[0]["id"] > after_operation_id
            ):
                operation_id = items[0]["id"]
            else:
                sleep(poll_interval)
                continue

        operation = get_operation(client, operation_id)
        if operation.get("end_time"):
            result = str(operation.get("result") or "").lower()
            if result != "success":
                return False, (
                    f"profile operation {operation_id} finished with "
                    f"result '{operation.get('result')}'"
                )
            try:
                profiles = get_field_profiles(client, container_id)
            except Exception as e:  # noqa: BLE001 - verification, not control flow
                return True, f"profiled (field-profile readback failed: {e})"
            items = (
                profiles.get("items") if isinstance(profiles, dict) else profiles
            ) or []
            if not items:
                return False, (
                    f"profile operation {operation_id} succeeded but the "
                    "container has no field profiles"
                )
            return True, f"profiled by operation {operation_id}"
        sleep(poll_interval)

    return False, f"timed out after {timeout}s waiting for the profile"


def ensure_containers(
    client,
    specs: list[ContainerSpec],
    datastore_id: int,
    *,
    on_existing: str = "skip",
    force_drop_fields: bool = False,
    wait_profile: bool = True,
    profile_timeout: int = 900,
    poll_interval: int = 10,
    dry_run: bool = False,
    report=None,
) -> dict:
    """Ensure the sheet's computed containers exist in a datastore.

    Validates every spec first (``POST containers/validate``) and aborts the
    phase on any failure — half a dependency graph is worse than none. Then
    creates in declaration order, waiting for each container's own profile
    operation before moving on, so dependent joins and checks always see a
    profiled container.

    ``on_existing='skip'`` leaves an existing same-name container untouched
    (reporting query drift when visible); ``'update'`` diffs the sheet against
    the live definition and PUTs only real changes — an identical definition is
    reported unchanged (label/metadata differences go through the platform's
    cheap label-only path, which never re-profiles).

    Returns {created, updated, unchanged, skipped, failed, errors, name_to_id}.
    """
    from ..api.containers import (
        create_container,
        get_container,
        list_containers_listing,
        update_container,
        validate_container,
    )

    report = report or (lambda message: None)
    result = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "skipped": 0,
        "failed": 0,
        "errors": [],
        "name_to_id": {},
    }

    listing = list_containers_listing(client, datastore_id)
    name_to_id: dict[str, int] = {item["name"]: item["id"] for item in listing}
    existing_types = {item["name"]: item.get("container_type") for item in listing}
    result["name_to_id"] = name_to_id

    def fail(spec: ContainerSpec, reason: str) -> None:
        result["failed"] += 1
        result["errors"].append(f"{spec.kind} '{spec.name}': {reason}")

    # First pass: decide what each spec needs. A join may read a container this
    # run creates on an earlier row (guaranteed earlier by convert_sheet), so
    # its payload build and validation are deferred to its turn in the create
    # loop; a source that is neither catalogued nor in-file is an error now.
    in_file = {spec.name for spec in specs}
    todo: list[tuple[ContainerSpec, dict | None, bool]] = []
    for spec in specs:
        existing_id = name_to_id.get(spec.name)
        if existing_id is not None and on_existing == "skip":
            todo.append((spec, None, False))  # decided later, needs no payload
            continue
        if spec.kind == KIND_COMPUTED_JOIN:
            sources = [s["container"] for s in spec.spec.get("sources") or []]
            unknown = [s for s in sources if s not in name_to_id and s not in in_file]
            if unknown:
                fail(
                    spec,
                    f"source container(s) not found in datastore "
                    f"{datastore_id}: {', '.join(unknown)}",
                )
                continue
            if any(s not in name_to_id for s in sources):
                todo.append((spec, None, True))  # build + validate just-in-time
                continue
        payload, error = _container_payload(spec, datastore_id, name_to_id)
        if error:
            fail(spec, error)
            continue
        todo.append((spec, payload, False))
    if result["failed"]:
        return result

    if dry_run:
        for spec, _payload, _deferred in todo:
            if spec.name not in name_to_id:
                report(f"[dry-run] would create {spec.kind} '{spec.name}'")
                result["created"] += 1
            elif on_existing == "skip":
                report(f"[dry-run] would skip existing '{spec.name}'")
                result["skipped"] += 1
            else:
                report(f"[dry-run] would update '{spec.name}'")
                result["updated"] += 1
        return result

    # Validate everything buildable before creating anything — half a
    # dependency graph is worse than none. Deferred joins validate at their
    # turn instead.
    for spec, payload, deferred in todo:
        if payload is None or deferred:
            continue
        try:
            validate_container(client, payload)
        except Exception as e:  # noqa: BLE001 - collected, phase aborts below
            fail(spec, f"validation failed: {e}")
    if result["failed"]:
        return result

    for spec, _payload, deferred in todo:
        existing_id = name_to_id.get(spec.name)

        if existing_id is not None and on_existing == "skip":
            drift = ""
            try:
                existing = get_container(client, existing_id)
                if (
                    existing.get("query")
                    and spec.spec.get("query")
                    and existing["query"].strip() != spec.spec["query"].strip()
                ):
                    drift = " (query differs from the sheet — --on-existing update)"
            except Exception:  # noqa: BLE001 - drift detection is best-effort
                pass
            report(f"skipped existing '{spec.name}'{drift}")
            result["skipped"] += 1
            continue

        # Sources may have been created earlier in this loop; resolve again.
        payload, error = _container_payload(spec, datastore_id, name_to_id)
        if error:
            fail(spec, error)
            break

        baseline_operation_id: int | None = None
        try:
            if existing_id is not None:
                if existing_types.get(spec.name) != spec.kind:
                    fail(
                        spec,
                        f"existing container is a "
                        f"{existing_types.get(spec.name)}, not a {spec.kind}",
                    )
                    break

                existing = get_container(client, existing_id)
                if not _definition_changed(spec, payload, existing):
                    # The definition matches the platform: a full PUT would be
                    # a no-op at best, and resending a join's sources forces a
                    # pointless re-validate + re-profile. Push label/metadata
                    # differences through the platform's cheap label-only path
                    # (no definition fields for a join; a computed table's
                    # update schema requires query, so send the live one).
                    if _labels_changed(payload, existing):
                        label_payload = {
                            "container_type": spec.kind,
                            "name": spec.name,
                        }
                        if spec.kind == KIND_COMPUTED_TABLE:
                            label_payload["query"] = existing.get("query")
                        for key in ("description", "additional_metadata"):
                            if key in payload:
                                label_payload[key] = payload[key]
                        update_container(client, existing_id, label_payload)
                        result["updated"] += 1
                        report(
                            f"updated metadata for '{spec.name}' "
                            f"(id {existing_id}, definition unchanged)"
                        )
                    else:
                        result["unchanged"] += 1
                        report(f"'{spec.name}' unchanged (id {existing_id})")
                    # No definition change ⇒ the platform will not re-profile;
                    # the existing profile stands.
                    continue

                # Anchor the profile wait to the newest pre-update operation so
                # a stale completed profile can't satisfy it (the update's
                # async re-profile may register after our first look).
                if wait_profile:
                    baseline_operation_id = _latest_profile_operation_id(
                        client, existing_id, datastore_id
                    )
                update_container(
                    client,
                    existing_id,
                    payload,
                    force_drop_fields=force_drop_fields,
                )
                container_id = existing_id
                result["updated"] += 1
                report(f"updated {spec.kind} '{spec.name}' (id {container_id})")
            else:
                if deferred:
                    validate_container(client, payload)
                created = create_container(client, payload)
                container_id = created["id"]
                name_to_id[spec.name] = container_id
                result["created"] += 1
                report(f"created {spec.kind} '{spec.name}' (id {container_id})")
        except Exception as e:  # noqa: BLE001 - reported, phase aborts
            message = str(e)
            if "force_drop_fields" in message and not force_drop_fields:
                message += (
                    "\n    The platform is protecting quality checks attached to "
                    "fields this change would drop. Re-run with "
                    "--force-drop-fields to proceed — affected checks are "
                    "preserved and reactivate if the fields reappear — and "
                    "update the sheet's dependent check rows to the new field "
                    "names."
                )
            fail(spec, message)
            break

        if wait_profile:
            ok, detail = wait_for_container_profile(
                client,
                container_id,
                datastore_id,
                timeout=profile_timeout,
                poll_interval=poll_interval,
                after_operation_id=baseline_operation_id,
            )
            report(f"'{spec.name}': {detail}")
            if not ok:
                fail(spec, detail)
                break

    return result
