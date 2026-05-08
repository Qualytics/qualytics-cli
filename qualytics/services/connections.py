"""Connection service functions."""

from ..api.client import QualyticsClient
from ..api.connections import list_connections


def get_connection_by(
    client: QualyticsClient,
    connection_id: int | None = None,
    connection_name: str | None = None,
) -> dict | None:
    """Get connection from Qualytics API by ID or name.

    Handles pagination to search through all connections.

    Returns:
        dict: The connection object if found
        None: If connection not found
    """
    if connection_id is None and connection_name is None:
        raise ValueError("Either connection_id or connection_name must be provided")

    if connection_id is not None and connection_name is not None:
        raise ValueError(
            "Cannot specify both connection_id and connection_name. Please use only one."
        )

    page = 1
    size = 50

    while True:
        data = list_connections(client, page=page, size=size)

        if "items" not in data:
            raise ValueError(
                f"Unexpected API response format. Expected 'items' field but got: {list(data.keys())}"
            )

        connections = data["items"]

        for connection in connections:
            if connection_id is not None and connection.get("id") == connection_id:
                return connection
            if (
                connection_name is not None
                and connection.get("name") == connection_name
            ):
                return connection

        if len(connections) < size:
            break

        page += 1

    return None


def get_connection_by_name(client: QualyticsClient, name: str) -> dict | None:
    """Find a connection by exact name via paginated search."""
    return get_connection_by(client, connection_name=name)


def build_create_connection_payload(
    connection_type: str,
    *,
    name: str | None = None,
    host: str | None = None,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    uri: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    catalog: str | None = None,
    jdbc_fetch_size: int | None = None,
    max_parallelization: int | None = None,
    authentication_type: str | None = None,
    role_arn: str | None = None,
    external_id: str | None = None,
    parameters: dict | None = None,
) -> dict:
    """Build a payload for creating a connection.

    The *connection_type* determines which fields are relevant.
    A ``--parameters`` JSON catch-all is merged last so it can supply
    any type-specific fields not covered by dedicated flags.
    """
    payload: dict = {"type": connection_type}

    if name is not None:
        payload["name"] = name

    # JDBC-style connections
    if host is not None:
        payload["host"] = host
    if port is not None:
        payload["port"] = port
    if username is not None:
        payload["username"] = username
    if password is not None:
        payload["password"] = password

    # DFS-style connections
    if uri is not None:
        payload["uri"] = uri
    if access_key is not None:
        payload["access_key"] = access_key
    if secret_key is not None:
        payload["secret_key"] = secret_key

    # Native (Databricks, etc.)
    if catalog is not None:
        payload["catalog"] = catalog

    # Tuning
    if jdbc_fetch_size is not None:
        payload["jdbc_fetch_size"] = jdbc_fetch_size
    if max_parallelization is not None:
        payload["max_parallelization"] = max_parallelization

    # IAM Role auth (S3, Athena, Redshift) — these go *inside* the
    # ``parameters`` dict on the wire (controlplane spec uses
    # ``map_to="parameters"`` for them), not at the top level.
    _require_role_arn_for_iam_role(authentication_type, role_arn)
    iam_params = _iam_role_params(authentication_type, role_arn, external_id)
    if iam_params:
        payload["parameters"] = {**(payload.get("parameters") or {}), **iam_params}

    # Merge the catch-all parameters dict last (overrides dedicated flags).
    # Top-level merge is preserved for legacy callers that used --parameters
    # to set fields like Snowflake's role/warehouse.
    if parameters is not None:
        payload.update(parameters)

    return payload


def build_update_connection_payload(**changes) -> dict:
    """Build a partial-update payload for a connection.

    Only non-None values are included. IAM Role fields (``authentication_type``,
    ``role_arn``, ``external_id``) are nested under ``parameters``.
    """
    iam_keys = {"authentication_type", "role_arn", "external_id"}
    iam_changes = {k: changes.pop(k) for k in list(changes) if k in iam_keys}

    _require_role_arn_for_iam_role(
        iam_changes.get("authentication_type"), iam_changes.get("role_arn")
    )

    payload: dict = {}
    for key, value in changes.items():
        if value is not None:
            payload[key] = value

    iam_params = _iam_role_params(
        iam_changes.get("authentication_type"),
        iam_changes.get("role_arn"),
        iam_changes.get("external_id"),
    )
    if iam_params:
        payload["parameters"] = iam_params

    return payload


def _iam_role_params(
    authentication_type: str | None,
    role_arn: str | None,
    external_id: str | None,
) -> dict:
    """Collect non-None IAM Role fields into a ``parameters`` sub-dict."""
    out: dict = {}
    if authentication_type is not None:
        out["authentication_type"] = authentication_type
    if role_arn is not None:
        out["role_arn"] = role_arn
    if external_id is not None:
        out["external_id"] = external_id
    return out


def _require_role_arn_for_iam_role(
    authentication_type: str | None, role_arn: str | None
) -> None:
    """Fail fast if IAM_ROLE is selected without a role ARN."""
    if authentication_type == "IAM_ROLE" and not role_arn:
        raise ValueError(
            "--role-arn is required when --authentication-type is IAM_ROLE."
        )
