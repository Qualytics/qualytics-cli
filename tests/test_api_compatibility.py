import ast
from pathlib import Path

import pytest

from qualytics.api.compatibility import (
    HTTP_METHODS,
    KNOWN_API_OPERATIONS,
    REQUIRED_API_OPERATIONS,
    find_incompatible_operations,
    normalize_api_path,
)


ROOT = Path(__file__).resolve().parents[1]


def _compatible_schema() -> dict:
    paths: dict[str, dict] = {}
    for method, path in REQUIRED_API_OPERATIONS:
        paths.setdefault(path, {})[method.lower()] = {}
    return {"openapi": "3.1.0", "paths": paths}


def test_all_required_operations_are_supported():
    assert find_incompatible_operations(_compatible_schema()) == []


def test_path_parameter_names_do_not_cause_false_incompatibility():
    schema = _compatible_schema()
    operations = schema["paths"].pop("/api/connections/{connection_id}")
    schema["paths"]["/api/connections/{id}"] = operations

    assert find_incompatible_operations(schema) == []


def test_api_prefix_is_optional_in_openapi_paths():
    schema = _compatible_schema()
    schema["paths"] = {
        path.removeprefix("/api"): operations
        for path, operations in schema["paths"].items()
    }

    assert find_incompatible_operations(schema) == []
    assert normalize_api_path("/apiary/status") == "/apiary/status"


def test_methods_are_combined_when_prefixed_and_unprefixed_paths_coexist():
    schema = _compatible_schema()
    schema["paths"].pop("/api/connections")
    schema["paths"]["/api/connections"] = {"get": {}}
    schema["paths"]["/connections"] = {"post": {}}

    assert find_incompatible_operations(schema) == []


def test_missing_path_and_method_are_reported():
    schema = _compatible_schema()
    schema["paths"].pop("/api/operations/run")
    schema["paths"]["/api/containers/validate"] = {"get": {}}

    issues = find_incompatible_operations(schema)

    assert "POST /api/operations/run — path is missing" in issues
    assert any(
        issue.startswith("POST /api/containers/validate — method is missing")
        for issue in issues
    )


@pytest.mark.parametrize(
    "schema",
    [
        None,
        {},
        {"paths": []},
        {"paths": {}},
        {"paths": {"/api/status": []}},
        {"paths": {"/api/operations/run": {"post": None}}},
    ],
)
def test_invalid_openapi_schema_is_rejected(schema):
    with pytest.raises(ValueError, match="OpenAPI"):
        find_incompatible_operations(schema)


def _render_path(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("{}")
            else:
                return None
        return "".join(parts)
    return None


class _ClientCallVisitor(ast.NodeVisitor):
    def __init__(self, source: Path):
        self.source = source
        self.function = "<module>"
        self.operations: set[tuple[str, str]] = set()
        self.dynamic_calls: set[tuple[str, str, str]] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        previous = self.function
        self.function = node.name
        self.generic_visit(node)
        self.function = previous

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        previous = self.function
        self.function = node.name
        self.generic_visit(node)
        self.function = previous

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "client"
            and function.attr.upper() in HTTP_METHODS
            and node.args
        ):
            method = function.attr.upper()
            path = _render_path(node.args[0])
            if path is None:
                self.dynamic_calls.add(
                    (self.source.relative_to(ROOT).as_posix(), self.function, method)
                )
            else:
                self.operations.add(
                    (method, normalize_api_path(f"/api/{path.lstrip('/')}"))
                )
        self.generic_visit(node)


def test_every_client_operation_is_in_the_compatibility_manifest():
    discovered: set[tuple[str, str]] = set()
    dynamic_calls: set[tuple[str, str, str]] = set()

    for source in (ROOT / "qualytics").rglob("*.py"):
        visitor = _ClientCallVisitor(source)
        visitor.visit(ast.parse(source.read_text()))
        discovered.update(visitor.operations)
        dynamic_calls.update(visitor.dynamic_calls)

    expected_dynamic_calls = {
        ("qualytics/cli/checks.py", "check_templates_export", "POST")
    }
    manual_operations = {
        ("GET", normalize_api_path("/api/status")),
        ("POST", normalize_api_path("/api/export/anomalies")),
        ("POST", normalize_api_path("/api/export/checks")),
        ("POST", normalize_api_path("/api/export/check-templates")),
        ("POST", normalize_api_path("/api/export/field-profiles")),
    }
    known = {
        (method, normalize_api_path(path)) for method, path in KNOWN_API_OPERATIONS
    }

    assert dynamic_calls == expected_dynamic_calls
    assert discovered | manual_operations == known
