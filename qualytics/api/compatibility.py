"""Runtime compatibility checks for controlplane API operations used by the CLI."""

import re
from typing import Any


HTTP_METHODS = frozenset({"DELETE", "GET", "PATCH", "POST", "PUT"})

# Keep this list aligned with every HTTP operation emitted by the CLI. Browser
# authentication is intentionally excluded because those routes are not in OpenAPI.
KNOWN_API_OPERATIONS = frozenset(
    {
        ("GET", "/api/status"),
        ("GET", "/api/anomalies"),
        ("PATCH", "/api/anomalies"),
        ("DELETE", "/api/anomalies"),
        ("GET", "/api/anomalies/{anomaly_id}"),
        ("PUT", "/api/anomalies/{anomaly_id}"),
        ("DELETE", "/api/anomalies/{anomaly_id}"),
        ("POST", "/api/computed-fields"),
        ("PUT", "/api/computed-fields/{field_id}"),
        ("DELETE", "/api/computed-fields/{field_id}"),
        ("GET", "/api/connections"),
        ("POST", "/api/connections"),
        ("GET", "/api/connections/{connection_id}"),
        ("PUT", "/api/connections/{connection_id}"),
        ("DELETE", "/api/connections/{connection_id}"),
        ("POST", "/api/connections/{connection_id}/test"),
        ("GET", "/api/containers"),
        ("POST", "/api/containers"),
        ("PATCH", "/api/containers"),
        ("GET", "/api/containers/listing"),
        ("POST", "/api/containers/validate"),
        ("GET", "/api/containers/{container_id}"),
        ("PUT", "/api/containers/{container_id}"),
        ("DELETE", "/api/containers/{container_id}"),
        ("GET", "/api/containers/{container_id}/field-profiles"),
        ("GET", "/api/datastores"),
        ("POST", "/api/datastores"),
        ("POST", "/api/datastores/connection"),
        ("GET", "/api/datastores/{datastore_id}"),
        ("PUT", "/api/datastores/{datastore_id}"),
        ("DELETE", "/api/datastores/{datastore_id}"),
        ("POST", "/api/datastores/{datastore_id}/connection"),
        ("DELETE", "/api/datastores/{datastore_id}/enrichment"),
        (
            "PATCH",
            "/api/datastores/{datastore_id}/enrichment/{enrichment_id}",
        ),
        ("POST", "/api/export/anomalies"),
        ("POST", "/api/export/checks"),
        ("POST", "/api/export/check-templates"),
        ("POST", "/api/export/field-profiles"),
        ("GET", "/api/global-tags"),
        ("POST", "/api/global-tags"),
        ("GET", "/api/global-tags/{tag_name}"),
        ("DELETE", "/api/global-tags/{tag_name}"),
        ("GET", "/api/operations"),
        ("POST", "/api/operations/run"),
        ("GET", "/api/operations/{operation_id}"),
        ("PUT", "/api/operations/abort/{operation_id}"),
        ("GET", "/api/quality-checks"),
        ("POST", "/api/quality-checks"),
        ("DELETE", "/api/quality-checks"),
        ("GET", "/api/quality-checks/{check_id}"),
        ("PUT", "/api/quality-checks/{check_id}"),
        ("DELETE", "/api/quality-checks/{check_id}"),
        ("POST", "/api/quality-check-templates"),
        ("GET", "/api/teams"),
        ("GET", "/api/teams/{team_id}"),
        ("GET", "/api/users"),
        ("GET", "/api/users/{user_id}"),
        ("POST", "/api/agent/chat"),
        ("GET", "/api/agent/llm-config/status"),
    }
)

# These operations are unused wrappers, optional diagnostics, or best-effort driver
# helpers. Their absence should not make a compatible deployment look unhealthy.
OPTIONAL_API_OPERATIONS = frozenset(
    {
        ("GET", "/api/status"),
        ("DELETE", "/api/computed-fields/{field_id}"),
        ("POST", "/api/datastores/connection"),
        ("POST", "/api/agent/chat"),
        ("GET", "/api/agent/llm-config/status"),
    }
)

REQUIRED_API_OPERATIONS = KNOWN_API_OPERATIONS - OPTIONAL_API_OPERATIONS

_PATH_PARAMETER = re.compile(r"\{[^}/]+\}")


def normalize_api_path(path: str) -> str:
    """Normalize path-parameter names while preserving the API route shape."""
    path = "/" + path.split("?", 1)[0].strip("/")
    if path == "/api":
        path = "/"
    elif path.startswith("/api/"):
        path = path[4:]
    return _PATH_PARAMETER.sub("{}", path)


def find_incompatible_operations(openapi_schema: Any) -> list[str]:
    """Return required CLI operations missing from an OpenAPI document."""
    if not isinstance(openapi_schema, dict):
        raise ValueError("response does not contain OpenAPI paths")

    paths = openapi_schema.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise ValueError("response does not contain OpenAPI paths")

    available: dict[str, set[str]] = {}
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            raise ValueError("response contains invalid OpenAPI paths")
        normalized_path = normalize_api_path(path)
        supported_methods = available.setdefault(normalized_path, set())
        for method, operation in path_item.items():
            if isinstance(method, str) and method.upper() in HTTP_METHODS:
                if not isinstance(operation, dict):
                    raise ValueError("response contains invalid OpenAPI operations")
                supported_methods.add(method.upper())

    issues = []
    for method, path in sorted(REQUIRED_API_OPERATIONS):
        normalized_path = normalize_api_path(path)
        supported_methods = available.get(normalized_path)
        if supported_methods is None:
            issues.append(f"{method} {path} — path is missing")
        elif method not in supported_methods:
            methods = ", ".join(sorted(supported_methods)) or "none"
            issues.append(
                f"{method} {path} — method is missing (server exposes: {methods})"
            )

    return issues
