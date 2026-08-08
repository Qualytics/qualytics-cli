"""dbt manifest → Qualytics quality check conversion.

Pure logic: no API client, no auth, no network. Takes a parsed ``manifest.json``
and returns portable check dicts in the same shape as ``strip_for_export``, ready
for ``import_checks_to_datastore``.

Design invariants:

* **Every UID is distinct.** The UID is derived from the dbt node's
  ``unique_id``, which dbt guarantees unique, plus a rule-type suffix for the few
  tests that split into two checks (a length range is a minLength *and* a
  maxLength). Never use ``generate_check_uid`` here: its
  ``container__rule__fields`` scheme collides for the cases dbt produces
  constantly (several singular tests on one model, two ``expression_is_true`` on
  one column), and the importer silently *updates* on a UID collision rather than
  erroring — so a collision loses a check with no output.
* **Nothing is dropped.** A dbt test that cannot be mapped deterministically still
  emits a check, as ``satisfiesExpression`` in ``Draft`` with the dbt source in the
  description. Migration tiers grade effort, not feasibility.
"""

import re
from collections.abc import Callable
from typing import Any

# ── Tiers ─────────────────────────────────────────────────────────────────
# 1 = direct/deterministic, 2 = needs normalization, 3 = manual authoring.
# Tier drives `status`: tier 1 lands Active, tiers 2 and 3 land Draft so a human
# reviews before anything fires.

TIER_DIRECT = 1
TIER_NORMALIZE = 2
TIER_MANUAL = 3

_STATUS_BY_TIER = {
    TIER_DIRECT: "Active",
    TIER_NORMALIZE: "Draft",
    TIER_MANUAL: "Draft",
}

UID_PREFIX = "dbt__"


# ── Property builders ─────────────────────────────────────────────────────
# Property names come from controlplane `QualityCheckProperties`
# (app/schemas/model_schemas.py). Note `between` uses min/max — NOT
# min_value/max_value, which is what dbt calls them — and `expectedValues` uses
# `list`. Getting these wrong produces checks the API accepts but that test
# nothing, so they are centralized here rather than inlined per rule.


def _p_expected_values(kw: dict) -> dict:
    values = kw.get("values") or kw.get("value_set") or []
    return {"list": list(values)}


def _p_pattern(kw: dict) -> dict:
    return {"pattern": kw.get("regex") or kw.get("pattern") or ""}


def _p_between(kw: dict) -> dict:
    """dbt min_value/max_value → Qualytics min/max.

    `between` wants min/inclusive_min/max/inclusive_max, so each bound's
    inclusivity is stated rather than left to a server default — dbt ranges are
    inclusive. A one-sided dbt range yields a one-sided check rather than a
    fabricated opposite bound.
    """
    props: dict[str, Any] = {}
    if kw.get("min_value") is not None:
        props["min"] = kw["min_value"]
        props["inclusive_min"] = True
    if kw.get("max_value") is not None:
        props["max"] = kw["max_value"]
        props["inclusive_max"] = True
    return props


def _p_value_from_min(kw: dict) -> dict:
    return {"value": kw.get("min_value"), "inclusive": True}


def _p_value_from_max(kw: dict) -> dict:
    return {"value": kw.get("max_value"), "inclusive": True}


def _p_sum(kw: dict) -> dict | None:
    """`sum` asserts equality, not a range.

    dataplane evaluates it as ``hasSum(field, _ == value)``. Emitting a dbt
    range's lower bound would assert ``sum == min`` and report valid data as
    anomalous, so only a degenerate range (min == max) converts. Anything wider
    returns None and falls through to manual authoring with the bounds preserved
    in metadata.
    """
    low, high = kw.get("min_value"), kw.get("max_value")
    if low is not None and low == high:
        return {"value": low}
    return None


# ComparisonType, from controlplane app/types/comparison_types.py.
_LT = "less than"
_EQ = "equal to"
_GT = "greater than"

# Metric/Volumetric comparison, from their respective enums.
_ABSOLUTE_VALUE = "Absolute Value"


def _p_distinct_count(comparison: str):
    """distinctCount requires both `comparison` and `value`."""

    def build(kw: dict) -> dict:
        value = kw.get("value")
        if value is None:
            value = kw.get("max_value")
        return {"comparison": comparison, "value": value}

    return build


def _p_not_constant(kw: dict) -> dict:
    """`not_constant` asserts more than one distinct value."""
    return {"comparison": _GT, "value": 1}


def _p_exists_in(kw: dict) -> dict:
    """existsIn needs the referenced field; the container is resolved later."""
    field = kw.get("field")
    return {"field_name": field} if field else {}


def _p_expected_schema(kw: dict) -> dict:
    """`expect_column_to_exist` asserts one column is present, others allowed."""
    column = kw.get("column_name")
    return {
        "list": [column] if column else [],
        "allow_other_fields": True,
    }


# dbt datepart → milliseconds, for freshness. controlplane documents freshness
# `value` as the maximum allowed age in MILLISECONDS.
_DATEPART_MS = {
    "second": 1_000,
    "minute": 60_000,
    "hour": 3_600_000,
    "day": 86_400_000,
    "week": 604_800_000,
    "month": 2_592_000_000,  # 30 days
    "year": 31_536_000_000,  # 365 days
}


def _p_freshness(kw: dict) -> dict:
    """dbt datepart+interval → freshness max age in milliseconds."""
    datepart = str(kw.get("datepart") or "day").strip().lower().rstrip("s")
    interval = kw.get("interval")
    unit = _DATEPART_MS.get(datepart)
    if unit is None or interval is None:
        return {}
    return {"value": int(interval) * unit}


def _p_volumetric(kw: dict) -> dict:
    """dbt's absolute row-count range → volumetric with an absolute comparison.

    volumetric is drift-oriented and requires a `window_size` for its moving
    average; dbt has no equivalent concept, so an absolute-value comparison over
    a single-day window is the closest faithful reading. It stays Draft so the
    window is confirmed rather than assumed.
    """
    return {
        "comparison": _ABSOLUTE_VALUE,
        "window_size": 1,
        "min": kw.get("min_value"),
        "max": kw.get("max_value"),
    }


def _p_metric(kw: dict) -> dict:
    """metric requires `comparison`; dbt supplies the absolute bounds."""
    return {
        "comparison": _ABSOLUTE_VALUE,
        "min": kw.get("min_value"),
        "max": kw.get("max_value"),
    }


# Length builders return None when their bound is absent, so a one-sided dbt
# test emits only the half it actually specifies.


def _p_min_length(kw: dict) -> dict | None:
    value = kw.get("min_value")
    return {"value": value} if value is not None else None


def _p_max_length(kw: dict) -> dict | None:
    value = kw.get("max_value")
    return {"value": value} if value is not None else None


def _p_exact_length(kw: dict) -> dict | None:
    """`lengths_to_equal` pins both ends to the same value."""
    value = kw.get("value")
    return {"value": value} if value is not None else None


def _p_expression(kw: dict) -> dict:
    return {"expression": kw.get("expression") or ""}


_DBT_TYPE_TO_FIELD_TYPE = {
    "int": "Integral",
    "integer": "Integral",
    "bigint": "Integral",
    "smallint": "Integral",
    "float": "Fractional",
    "double": "Fractional",
    "decimal": "Fractional",
    "numeric": "Fractional",
    "number": "Fractional",
    "bool": "Boolean",
    "boolean": "Boolean",
    "string": "String",
    "varchar": "String",
    "text": "String",
    "char": "String",
    "date": "Date",
    "timestamp": "Timestamp",
    "datetime": "Timestamp",
    "array": "Array",
    "struct": "Struct",
    "map": "MapType",
}


def _p_is_type(kw: dict) -> dict:
    raw = kw.get("column_type") or kw.get("type") or ""
    key = str(raw).strip().lower()
    # strip parameterization, e.g. varchar(64) → varchar
    key = re.sub(r"\(.*\)$", "", key).strip()
    return {"field_type": _DBT_TYPE_TO_FIELD_TYPE.get(key, "Unknown")}


class Split:
    """One of several checks produced from a single dbt test.

    ``props`` returns None when this half of the test is not specified, so the
    split is skipped rather than emitting a check with a null bound.
    """

    __slots__ = ("rule_type", "props")

    def __init__(self, rule_type: str, props: Callable[[dict], dict | None]):
        self.rule_type = rule_type
        self.props = props


class Mapping:
    """A dbt test → Qualytics rule mapping.

    ``splits`` covers dbt tests that assert two things at once (a length range is
    a minLength *and* a maxLength). Each split becomes its own check with a
    UID suffixed by its rule type, keeping every UID distinct.
    """

    __slots__ = ("rule_type", "tier", "props", "note", "splits")

    def __init__(
        self,
        rule_type: str,
        tier: int,
        props: Callable[[dict], dict] | None = None,
        note: str | None = None,
        splits: list[Split] | None = None,
    ):
        self.rule_type = rule_type
        self.tier = tier
        self.props = props
        self.note = note
        self.splits = splits


# ── The crosswalk ─────────────────────────────────────────────────────────
# Keyed by "<namespace>.<name>" for packaged tests, bare name for native dbt
# tests. Mirrors dbt-crosswalk's ruleMap.ts; rule_type values are from
# controlplane's RuleType enum (app/types/rule_types.py).

DBT_RULE_MAP: dict[str, Mapping] = {
    # ---- native dbt ----
    "not_null": Mapping("notNull", TIER_DIRECT),
    "unique": Mapping("unique", TIER_DIRECT),
    "accepted_values": Mapping("expectedValues", TIER_DIRECT, _p_expected_values),
    "relationships": Mapping(
        "existsIn", TIER_DIRECT, _p_exists_in, note="reference resolved from dbt ref()"
    ),
    # ---- dbt_utils ----
    "dbt_utils.unique_combination_of_columns": Mapping("unique", TIER_DIRECT),
    "dbt_utils.accepted_range": Mapping("between", TIER_DIRECT, _p_between),
    "dbt_utils.not_null_proportion": Mapping(
        "notNull", TIER_NORMALIZE, note="dbt threshold % — set coverage to match"
    ),
    "dbt_utils.expression_is_true": Mapping(
        "satisfiesExpression",
        TIER_NORMALIZE,
        _p_expression,
        note="verify expression is valid Spark SQL",
    ),
    "dbt_utils.not_constant": Mapping("distinctCount", TIER_DIRECT, _p_not_constant),
    "dbt_utils.cardinality_equality": Mapping(
        "distinctCount",
        TIER_NORMALIZE,
        note="dbt compares two columns' cardinality — set the expected count",
    ),
    # ---- dbt_expectations ----
    "dbt_expectations.expect_column_values_to_not_be_null": Mapping(
        "notNull", TIER_DIRECT
    ),
    "dbt_expectations.expect_column_values_to_be_unique": Mapping(
        "unique", TIER_DIRECT
    ),
    "dbt_expectations.expect_column_values_to_be_in_set": Mapping(
        "expectedValues", TIER_DIRECT, _p_expected_values
    ),
    "dbt_expectations.expect_column_values_to_match_regex": Mapping(
        "matchesPattern", TIER_DIRECT, _p_pattern
    ),
    "dbt_expectations.expect_column_values_to_match_like_pattern": Mapping(
        "matchesPattern",
        TIER_NORMALIZE,
        _p_pattern,
        note="SQL LIKE pattern — convert to regex",
    ),
    "dbt_expectations.expect_column_values_to_be_between": Mapping(
        "between", TIER_DIRECT, _p_between
    ),
    "dbt_expectations.expect_column_value_lengths_to_be_between": Mapping(
        "minLength",
        TIER_DIRECT,
        splits=[Split("minLength", _p_min_length), Split("maxLength", _p_max_length)],
    ),
    "dbt_expectations.expect_column_value_lengths_to_equal": Mapping(
        "minLength",
        TIER_DIRECT,
        splits=[
            Split("minLength", _p_exact_length),
            Split("maxLength", _p_exact_length),
        ],
    ),
    "dbt_expectations.expect_column_values_to_be_of_type": Mapping(
        "isType", TIER_NORMALIZE, _p_is_type, note="verify the mapped field type"
    ),
    "dbt_expectations.expect_column_values_to_be_in_type_list": Mapping(
        "isType", TIER_NORMALIZE, _p_is_type, note="dbt allows several types — pick one"
    ),
    "dbt_expectations.expect_column_max_to_be_between": Mapping(
        "maxValue", TIER_NORMALIZE, _p_value_from_max
    ),
    "dbt_expectations.expect_column_min_to_be_between": Mapping(
        "minValue", TIER_NORMALIZE, _p_value_from_min
    ),
    "dbt_expectations.expect_column_mean_to_be_between": Mapping(
        "metric",
        TIER_NORMALIZE,
        _p_metric,
        note="metric records the field value — confirm it aggregates as a mean",
    ),
    "dbt_expectations.expect_column_sum_to_be_between": Mapping(
        "sum", TIER_NORMALIZE, _p_sum, note="sum asserts equality, not a range"
    ),
    "dbt_expectations.expect_column_distinct_count_to_be_less_than": Mapping(
        "distinctCount", TIER_DIRECT, _p_distinct_count(_LT)
    ),
    "dbt_expectations.expect_column_distinct_count_to_equal": Mapping(
        "distinctCount", TIER_DIRECT, _p_distinct_count(_EQ)
    ),
    "dbt_expectations.expect_table_row_count_to_be_between": Mapping(
        "volumetric",
        TIER_NORMALIZE,
        _p_volumetric,
        note="confirm the moving-average window; dbt has no equivalent",
    ),
    "dbt_expectations.expect_row_values_to_have_recent_data": Mapping(
        "freshness", TIER_DIRECT, _p_freshness
    ),
    "dbt_expectations.expect_table_column_count_to_equal": Mapping(
        "fieldCount", TIER_DIRECT, lambda kw: {"value": kw.get("value")}
    ),
    "dbt_expectations.expect_column_to_exist": Mapping(
        "expectedSchema", TIER_DIRECT, _p_expected_schema
    ),
}

# Rules that carry a cross-container reference. The portable YAML uses
# ref_container_name / ref_datastore_name; the importer resolves them to IDs.
_CROSS_REF_RULES = frozenset({"existsIn", "notExistsIn", "isReplicaOf", "dataDiff"})


class Contract:
    """Per-rule capabilities, from controlplane's quality_check_specs().

    Not every rule accepts every top-level field: `volumetric` and `freshness`
    are container-level and reject a filter, and several rules do not support
    coverage. Emitting those anyway produces a payload the API has no meaning
    for, so the contract is encoded rather than assumed uniform.
    """

    __slots__ = ("fields", "filterable", "coverage")

    def __init__(self, fields: str, filterable: bool, coverage: bool):
        self.fields = fields  # multi | single | calculated | none
        self.filterable = filterable
        self.coverage = coverage


RULE_CONTRACT: dict[str, Contract] = {
    "notNull": Contract("multi", True, True),
    "unique": Contract("multi", True, True),
    "expectedValues": Contract("single", True, True),
    "existsIn": Contract("single", True, True),
    "between": Contract("single", True, True),
    "greaterThan": Contract("single", True, True),
    "lessThan": Contract("single", True, True),
    "satisfiesExpression": Contract("calculated", True, True),
    "distinctCount": Contract("single", True, False),
    "matchesPattern": Contract("single", True, True),
    "maxLength": Contract("single", True, True),
    "minLength": Contract("single", True, True),
    "isType": Contract("single", True, True),
    "maxValue": Contract("single", True, True),
    "minValue": Contract("single", True, True),
    "metric": Contract("single", True, False),
    "sum": Contract("single", True, True),
    "volumetric": Contract("none", False, False),
    "freshness": Contract("none", False, False),
    "fieldCount": Contract("none", False, False),
    "expectedSchema": Contract("none", False, False),
}

_DEFAULT_CONTRACT = Contract("single", True, True)


def contract_for(rule_type: str) -> Contract:
    return RULE_CONTRACT.get(rule_type, _DEFAULT_CONTRACT)


# ── Helpers ───────────────────────────────────────────────────────────────


def _slugify(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def dbt_check_uid(unique_id: str, suffix: str | None = None) -> str:
    """Stable UID from a dbt node's unique_id.

    dbt guarantees ``unique_id`` is unique per node. ``suffix`` distinguishes the
    checks of a split mapping (one dbt test asserting two things), keeping every
    emitted UID distinct.
    """
    uid = UID_PREFIX + _slugify(unique_id)
    if suffix:
        uid += "__" + _slugify(suffix)
    return uid


def _ref_model_name(to_expr: str) -> str | None:
    """Extract the model name from a dbt ``ref('x')`` / ``ref('pkg','x')``."""
    if not to_expr:
        return None
    names = re.findall(r"""['"]([^'"]+)['"]""", str(to_expr))
    return names[-1] if names else None


def index_models(manifest: dict) -> dict[str, dict]:
    """Map model unique_id → node, for every model-like node in the manifest."""
    out = {}
    for uid, node in (manifest.get("nodes") or {}).items():
        if node.get("resource_type") in ("model", "seed", "snapshot"):
            out[uid] = node
    for uid, node in (manifest.get("sources") or {}).items():
        out[uid] = node
    return out


def container_name_for(node: dict, *, case: str | None = None) -> str:
    """Resolve the warehouse table name a dbt node lands in.

    Prefers ``alias`` over ``name`` because dbt models can be aliased, and the
    Qualytics container is catalogued from the warehouse — not from dbt.
    """
    name = node.get("alias") or node.get("identifier") or node.get("name") or ""
    if case == "upper":
        return name.upper()
    if case == "lower":
        return name.lower()
    return name


def _attached_model(test_node: dict, models: dict[str, dict]) -> dict | None:
    """Find the model a test is attached to.

    A ``relationships`` test depends on two models; ``attached_node`` (dbt 1.6+)
    disambiguates. Falls back to ``file_key_name``, then to the sole dependency.
    """
    attached = test_node.get("attached_node")
    if attached and attached in models:
        return models[attached]

    deps = [
        d for d in (test_node.get("depends_on") or {}).get("nodes") or [] if d in models
    ]

    file_key = test_node.get("file_key_name") or ""
    if "." in file_key:
        wanted = file_key.split(".")[-1]
        for dep in deps:
            if models[dep].get("name") == wanted:
                return models[dep]

    return models[deps[0]] if deps else None


def _referenced_model(
    test_node: dict, models: dict[str, dict], kwargs: dict
) -> dict | None:
    """For relationships tests, the model named by the ``to`` kwarg."""
    wanted = _ref_model_name(kwargs.get("to", ""))
    if not wanted:
        return None
    for dep in (test_node.get("depends_on") or {}).get("nodes") or []:
        node = models.get(dep)
        if node and node.get("name") == wanted:
            return node
    return None


# ── Conversion ────────────────────────────────────────────────────────────


class ConvertedCheck:
    """A converted check plus the provenance needed to report on it."""

    __slots__ = ("check", "tier", "dbt_test", "container", "note")

    def __init__(self, check: dict, tier: int, dbt_test: str, container: str, note):
        self.check = check
        self.tier = tier
        self.dbt_test = dbt_test
        self.container = container
        self.note = note


# kwargs already expressed elsewhere in the check, so recording them again in
# metadata would be noise rather than information.
_REDUNDANT_KWARGS = frozenset({"column_name"})


def row_filter(node: dict) -> str | None:
    """dbt's ``where`` config → Qualytics ``filter``.

    Both are a SQL predicate scoping which rows the assertion applies to.
    Dropping it would run the check against precisely the rows dbt was told to
    exclude, so this is a correctness mapping, not an enhancement.
    """
    where = (node.get("config") or {}).get("where")
    return str(where) if where else None


def dbt_metadata(node: dict, key: str, kwargs: dict | None = None) -> dict:
    """dbt facts with no direct Qualytics field, recorded rather than dropped.

    A reviewer completing a Draft check should not have to go back to the dbt
    project to find the threshold or interval the test was written with, so
    everything unconsumed lands here. ``additional_metadata`` is typed
    ``dict[str, Any]`` server-side, so structured values need no encoding.
    """
    meta: dict[str, Any] = {"dbt_test": key}

    package = node.get("package_name")
    if package:
        meta["dbt_package"] = package

    config = node.get("config") or {}

    # Only record severity when it departs from dbt's default.
    severity = config.get("severity")
    if severity and str(severity).lower() != "error":
        meta["dbt_severity"] = str(severity)

    for cfg in ("limit", "store_failures", "error_if", "warn_if"):
        if config.get(cfg) is not None:
            meta[f"dbt_{cfg}"] = config[cfg]

    tags = config.get("tags") or node.get("tags")
    if tags:
        meta["dbt_tags"] = (
            list(tags) if isinstance(tags, (list, tuple)) else [str(tags)]
        )

    # Every kwarg the mapping did not turn into a property or field. Keeps the
    # thresholds of a partially-mapped rule visible on the check itself.
    leftover = {k: v for k, v in (kwargs or {}).items() if k not in _REDUNDANT_KWARGS}
    if leftover:
        meta["dbt_kwargs"] = leftover

    return meta


def _build_check(
    *,
    rule_type: str,
    container: str,
    fields: list[str],
    description: str,
    unique_id: str,
    tier: int,
    properties: dict | None = None,
    coverage: float = 1.0,
    tags: list[str] | None = None,
    extra_metadata: dict | None = None,
    include_status: bool = True,
    uid_suffix: str | None = None,
    check_filter: str | None = None,
) -> dict:
    # The rule's contract decides which top-level fields are meaningful. A
    # container-level rule takes no fields and rejects a filter; several rules
    # do not support coverage. Emitting them regardless would be noise the API
    # has to ignore, or reject.
    contract = contract_for(rule_type)

    check: dict[str, Any] = {
        "rule_type": rule_type,
        "description": description,
        "container": container,
        "fields": [] if contract.fields == "none" else fields,
        "coverage": coverage if contract.coverage else None,
        "filter": check_filter if contract.filterable else None,
        "properties": properties or {},
        "tags": tags if tags is not None else ["dbt"],
        "additional_metadata": {
            "_qualytics_check_uid": dbt_check_uid(unique_id, uid_suffix),
            "dbt_unique_id": unique_id,
            **(extra_metadata or {}),
        },
    }
    # Omitting `status` on re-sync lets the importer's merge keep whatever a human
    # set in the product; including it would reset an activated check to Draft.
    if include_status:
        check["status"] = _STATUS_BY_TIER[tier]
    return check


def convert_manifest(
    manifest: dict,
    *,
    container_map: dict[str, str] | None = None,
    container_case: str | None = None,
    include_status: bool = True,
    status_override: str | None = None,
    default_coverage: float = 1.0,
    tags: list[str] | None = None,
) -> list[ConvertedCheck]:
    """Convert every test node in a dbt manifest into a portable check.

    ``container_map`` overrides the resolved container name per dbt model name,
    for the cases where the warehouse table does not match dbt's alias.

    ``status_override`` forces every check to one status, replacing the
    tier-derived default. The migration is the caller's to manage: the tiers are
    a recommendation, not a policy this function enforces.
    """
    container_map = container_map or {}
    models = index_models(manifest)
    out: list[ConvertedCheck] = []

    def resolve_container(model: dict | None) -> str:
        """Single resolution path for every container name a check refers to.

        A cross-reference target (``existsIn``) has to resolve identically to the
        check's own container; resolving them separately let --container-map and
        --container-case apply to one and not the other.
        """
        name = (model or {}).get("name") or ""
        return container_map.get(name) or container_name_for(
            model or {}, case=container_case
        )

    for unique_id, node in sorted((manifest.get("nodes") or {}).items()):
        if node.get("resource_type") != "test":
            continue

        model = _attached_model(node, models)
        container = resolve_container(model)

        meta = node.get("test_metadata")
        if meta:
            converted = _convert_generic(
                node,
                unique_id,
                meta,
                models,
                container,
                default_coverage,
                tags,
                include_status,
                resolve_container,
            )
        else:
            converted = _convert_singular(
                node, unique_id, container, default_coverage, tags, include_status
            )

        out.extend(converted)

    if status_override:
        for c in out:
            c.check["status"] = status_override

    return out


def _convert_generic(
    node,
    unique_id,
    meta,
    models,
    container,
    coverage,
    tags,
    include_status,
    resolve_container,
) -> list[ConvertedCheck]:
    namespace = meta.get("namespace")
    name = meta.get("name") or ""
    key = f"{namespace}.{name}" if namespace else name
    kwargs = meta.get("kwargs") or {}

    mapping = DBT_RULE_MAP.get(key) or DBT_RULE_MAP.get(name)

    column = node.get("column_name") or kwargs.get("column_name")
    fields = [column] if column else []

    def _unmapped(reason: str) -> list[ConvertedCheck]:
        """Fallback so a test is never dropped, only downgraded to manual."""
        return [
            ConvertedCheck(
                _build_check(
                    rule_type="satisfiesExpression",
                    container=container,
                    fields=fields,
                    description=f"[dbt] {key} — {reason}, author the expression by hand",
                    unique_id=unique_id,
                    tier=TIER_MANUAL,
                    properties={"expression": ""},
                    coverage=coverage,
                    tags=tags,
                    extra_metadata=dbt_metadata(node, key, kwargs),
                    include_status=include_status,
                    check_filter=row_filter(node),
                ),
                TIER_MANUAL,
                key,
                container,
                reason,
            )
        ]

    if mapping is None:
        # Unrecognized generic test — still migrates, as a Draft for a human.
        return _unmapped("unrecognized dbt test")

    # A dbt test that asserts two things becomes two checks, each with its own
    # UID suffix. A half whose bound is absent is skipped, not emitted null.
    if mapping.splits:
        out = []
        for split in mapping.splits:
            props = split.props(kwargs)
            if props is None:
                continue
            out.append(
                ConvertedCheck(
                    _build_check(
                        rule_type=split.rule_type,
                        container=container,
                        fields=fields,
                        description=f"[dbt] {key} → {split.rule_type}",
                        unique_id=unique_id,
                        tier=mapping.tier,
                        properties=props,
                        coverage=coverage,
                        tags=tags,
                        extra_metadata=dbt_metadata(node, key, kwargs),
                        include_status=include_status,
                        uid_suffix=split.rule_type,
                        check_filter=row_filter(node),
                    ),
                    mapping.tier,
                    key,
                    container,
                    mapping.note,
                )
            )
        return out or _unmapped("no bounds specified")

    properties = mapping.props(kwargs) if mapping.props else {}

    # A builder returns None when the rule cannot express what the dbt test
    # asserts. Converting anyway would change the assertion's meaning, so the
    # test degrades to manual authoring instead — with its kwargs preserved.
    if properties is None:
        return _unmapped(f"{mapping.rule_type} cannot express this dbt assertion")

    # Composite unique: dbt passes the column set in kwargs, not column_name.
    if key == "dbt_utils.unique_combination_of_columns":
        combo = kwargs.get("combination_of_columns") or []
        fields = list(combo) or fields

    if mapping.rule_type in _CROSS_REF_RULES:
        ref = _referenced_model(node, models, kwargs)
        if ref is not None:
            properties = dict(properties)
            # The referenced container must go through the same resolution as the
            # primary one, or --container-map/--container-case would resolve the
            # source and leave the target as a name the importer cannot find.
            properties["ref_container_name"] = resolve_container(ref)

    # Container-level rules take no fields; _build_check enforces that from the
    # rule contract rather than a second list kept in sync here.

    description = f"[dbt] {key}"
    if mapping.note:
        description += f" — {mapping.note}"

    return [
        ConvertedCheck(
            _build_check(
                rule_type=mapping.rule_type,
                container=container,
                fields=fields,
                description=description,
                unique_id=unique_id,
                tier=mapping.tier,
                properties=properties,
                coverage=coverage,
                tags=tags,
                extra_metadata=dbt_metadata(node, key, kwargs),
                include_status=include_status,
                check_filter=row_filter(node),
            ),
            mapping.tier,
            key,
            container,
            mapping.note,
        )
    ]


def _convert_singular(
    node, unique_id, container, coverage, tags, include_status
) -> list[ConvertedCheck]:
    """Singular (bespoke SQL) test → satisfiesExpression in Draft.

    dbt compiles these to SQL that selects failing rows, which is not a row
    predicate. The SQL is carried across so a reviewer adapts it rather than
    going back to the dbt project to find it.
    """
    name = node.get("name") or unique_id.split(".")[-1]
    sql = node.get("compiled_code") or node.get("raw_code") or ""

    description = (
        f"[dbt] singular test '{name}' — port the SQL to a row predicate. "
        "dbt's version selects failing rows; Qualytics expects an expression "
        "that is true for valid rows."
    )

    metadata = dbt_metadata(node, name)
    if sql:
        metadata["dbt_compiled_sql"] = sql

    return [
        ConvertedCheck(
            _build_check(
                rule_type="satisfiesExpression",
                container=container,
                fields=[],
                description=description,
                unique_id=unique_id,
                tier=TIER_MANUAL,
                properties={"expression": ""},
                coverage=coverage,
                tags=tags,
                extra_metadata=metadata,
                include_status=include_status,
                check_filter=row_filter(node),
            ),
            TIER_MANUAL,
            name,
            container,
            "singular SQL test",
        )
    ]


# ── Reporting ─────────────────────────────────────────────────────────────


def summarize(converted: list[ConvertedCheck]) -> dict:
    """Coverage breakdown for `dbt plan`.

    ``total`` counts emitted checks and ``dbt_tests`` counts source test nodes.
    They differ when a split mapping turns one dbt test into two checks, so the
    two are reported separately rather than conflated.
    """
    total = len(converted)
    by_tier = {t: 0 for t in (TIER_DIRECT, TIER_NORMALIZE, TIER_MANUAL)}
    for c in converted:
        by_tier[c.tier] += 1

    automatic = by_tier[TIER_DIRECT] + by_tier[TIER_NORMALIZE]
    containers = sorted({c.container for c in converted if c.container})
    missing_container = [c for c in converted if not c.container]
    dbt_tests = {c.check["additional_metadata"]["dbt_unique_id"] for c in converted}

    return {
        "total": total,
        "dbt_tests": len(dbt_tests),
        "direct": by_tier[TIER_DIRECT],
        "normalize": by_tier[TIER_NORMALIZE],
        "manual": by_tier[TIER_MANUAL],
        "automatic": automatic,
        "automatic_pct": round(automatic / total * 100) if total else 0,
        "containers": containers,
        "unresolved_containers": len(missing_container),
    }


def to_checks(converted: list[ConvertedCheck]) -> list[dict]:
    """Strip provenance wrappers, yielding dicts for import_checks_to_datastore."""
    return [c.check for c in converted]


# ── Field validation ──────────────────────────────────────────────────────


def resolve_check_fields(
    checks: list[dict], fields_by_container: dict[str, list[str]]
) -> tuple[list[dict], list[dict], list[str]]:
    """Match each check's fields against the catalogued field names.

    ``import_checks_to_datastore`` resolves container names to IDs and errors on
    a miss, but passes ``fields`` through untouched — so a field name that does
    not exist in the warehouse creates a check that never evaluates, with no
    error anywhere. Checking against the catalogue closes that gap.

    Because the catalogue is ground truth, this also fixes casing rather than
    guessing at it: dbt writes ``order_id``, Snowflake catalogues ``ORDER_ID``,
    and the right answer is knowable instead of a flag the user has to set.

    A container absent from ``fields_by_container`` passes through untouched —
    the importer reports unknown containers itself, and this must not
    second-guess it.

    Returns ``(importable, rejected, corrections)``.
    """
    importable: list[dict] = []
    rejected: list[dict] = []
    corrections: list[str] = []

    for check in checks:
        container = check.get("container") or ""
        known = fields_by_container.get(container)
        if known is None:
            importable.append(check)
            continue

        exact = set(known)
        by_lower = {name.lower(): name for name in known}

        resolved: list[str] = []
        missing: list[str] = []
        for field in check.get("fields") or []:
            if field in exact:
                resolved.append(field)
            elif field.lower() in by_lower:
                actual = by_lower[field.lower()]
                resolved.append(actual)
                corrections.append(f"{container}.{field} → {actual}")
            else:
                missing.append(field)

        if missing:
            rejected.append(
                {
                    "check": check,
                    "reason": (
                        f"Field(s) not found in container '{container}': "
                        f"{', '.join(missing)}"
                    ),
                }
            )
            continue

        importable.append({**check, "fields": resolved})

    return importable, rejected, corrections
