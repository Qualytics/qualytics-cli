"""Shared per-rule knowledge for check producers and the import pipeline.

Single source of truth for facts that were previously duplicated between
``services.dbt`` and ``services.quality_checks``:

* which rules carry a cross-container reference (``CROSS_REF_RULES``),
* which top-level check fields each rule accepts (``Contract``), and
* field-name validation against the warehouse catalogue
  (``resolve_check_fields``).

Everything here is pure — no API client, no auth, no network.
"""

# Rules that carry a cross-container reference in their properties. The
# portable YAML uses ref_container_name / ref_datastore_name; the importer
# resolves them back to IDs on the destination instance.
CROSS_REF_RULES = frozenset(
    {"existsIn", "notExistsIn", "isReplicaOf", "dataDiff", "aggregationComparison"}
)


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
    "notExistsIn": Contract("single", True, True),
    "between": Contract("single", True, True),
    "greaterThan": Contract("single", True, True),
    "lessThan": Contract("single", True, True),
    "equalTo": Contract("multi", True, True),
    "satisfiesExpression": Contract("calculated", True, True),
    "aggregationComparison": Contract("calculated", True, False),
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


def one_sided_between(props: dict) -> tuple[str, dict]:
    """Narrow a one-sided range to the single-bound rule.

    The API's `between` contract requires both bounds (min, inclusive_min, max,
    inclusive_max), so a one-sided range becomes greaterThan/lessThan with the
    same inclusive semantics rather than fabricating the missing bound.
    """
    if "min" in props and "max" not in props:
        return "greaterThan", {
            "value": props["min"],
            "inclusive": props.get("inclusive_min", True),
        }
    if "max" in props and "min" not in props:
        return "lessThan", {
            "value": props["max"],
            "inclusive": props.get("inclusive_max", True),
        }
    return "between", props


def resolve_check_fields(
    checks: list[dict], fields_by_container: dict[str, list[str]]
) -> tuple[list[dict], list[dict], list[str]]:
    """Match each check's fields against the catalogued field names.

    ``import_checks_to_datastore`` resolves container names to IDs and errors on
    a miss, but passes ``fields`` through untouched — so a field name that does
    not exist in the warehouse creates a check that never evaluates, with no
    error anywhere. Checking against the catalogue closes that gap.

    Because the catalogue is ground truth, this also fixes casing rather than
    guessing at it: a producer writes ``order_id``, Snowflake catalogues
    ``ORDER_ID``, and the right answer is knowable instead of a flag the user
    has to set.

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
