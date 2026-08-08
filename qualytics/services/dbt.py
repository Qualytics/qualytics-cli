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
from typing import Any, Callable

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
    """dbt min_value/max_value → Qualytics min/max."""
    props: dict[str, Any] = {}
    if kw.get("min_value") is not None:
        props["min"] = kw["min_value"]
    if kw.get("max_value") is not None:
        props["max"] = kw["max_value"]
    return props


def _p_value_from_min(kw: dict) -> dict:
    return {"value": kw.get("min_value"), "inclusive": True}


def _p_value_from_max(kw: dict) -> dict:
    return {"value": kw.get("max_value"), "inclusive": True}


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
        "existsIn", TIER_DIRECT, note="reference resolved from dbt ref()"
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
    "dbt_utils.not_constant": Mapping(
        "distinctCount", TIER_NORMALIZE, note="expects distinct count > 1"
    ),
    "dbt_utils.cardinality_equality": Mapping("distinctCount", TIER_NORMALIZE),
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
        "metric", TIER_NORMALIZE, note="configure the metric aggregation"
    ),
    "dbt_expectations.expect_column_sum_to_be_between": Mapping(
        "sum", TIER_NORMALIZE, _p_value_from_min
    ),
    "dbt_expectations.expect_column_distinct_count_to_be_less_than": Mapping(
        "distinctCount", TIER_NORMALIZE
    ),
    "dbt_expectations.expect_column_distinct_count_to_equal": Mapping(
        "distinctCount", TIER_NORMALIZE
    ),
    "dbt_expectations.expect_table_row_count_to_be_between": Mapping(
        "volumetric", TIER_NORMALIZE, note="set the volumetric window"
    ),
    "dbt_expectations.expect_row_values_to_have_recent_data": Mapping(
        "freshness", TIER_NORMALIZE, note="set the freshness interval"
    ),
    "dbt_expectations.expect_table_column_count_to_equal": Mapping(
        "fieldCount", TIER_DIRECT, lambda kw: {"value": kw.get("value")}
    ),
    "dbt_expectations.expect_column_to_exist": Mapping("expectedSchema", TIER_DIRECT),
}

# Rules that carry a cross-container reference. The portable YAML uses
# ref_container_name / ref_datastore_name; the importer resolves them to IDs.
_CROSS_REF_RULES = frozenset({"existsIn", "notExistsIn", "isReplicaOf", "dataDiff"})

# Rules that operate on the container, not a field.
_CONTAINER_LEVEL_RULES = frozenset(
    {"volumetric", "fieldCount", "expectedSchema", "freshness"}
)


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
) -> dict:
    check: dict[str, Any] = {
        "rule_type": rule_type,
        "description": description,
        "container": container,
        "fields": fields,
        "coverage": coverage,
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

    for unique_id, node in sorted((manifest.get("nodes") or {}).items()):
        if node.get("resource_type") != "test":
            continue

        model = _attached_model(node, models)
        model_name = (model or {}).get("name") or ""
        container = container_map.get(model_name) or container_name_for(
            model or {}, case=container_case
        )

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
    node, unique_id, meta, models, container, coverage, tags, include_status
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
                    extra_metadata={"dbt_test": key},
                    include_status=include_status,
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
                        extra_metadata={"dbt_test": key},
                        include_status=include_status,
                        uid_suffix=split.rule_type,
                    ),
                    mapping.tier,
                    key,
                    container,
                    mapping.note,
                )
            )
        return out or _unmapped("no bounds specified")

    properties = mapping.props(kwargs) if mapping.props else {}

    # Composite unique: dbt passes the column set in kwargs, not column_name.
    if key == "dbt_utils.unique_combination_of_columns":
        combo = kwargs.get("combination_of_columns") or []
        fields = list(combo) or fields

    if mapping.rule_type in _CROSS_REF_RULES:
        ref = _referenced_model(node, models, kwargs)
        if ref is not None:
            properties = dict(properties)
            properties["ref_container_name"] = container_name_for(ref)

    if mapping.rule_type in _CONTAINER_LEVEL_RULES:
        fields = []

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
                extra_metadata={"dbt_test": key},
                include_status=include_status,
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
                extra_metadata={"dbt_test": name, "dbt_compiled_sql": sql}
                if sql
                else {"dbt_test": name},
                include_status=include_status,
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
