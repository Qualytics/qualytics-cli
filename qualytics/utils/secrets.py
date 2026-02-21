"""Utilities for handling sensitive data — env var resolution and redaction."""

import copy
import os
import re


# Fields that should be masked in CLI output
_SENSITIVE_FIELDS = frozenset(
    {
        "password",
        "passphrase",
        "token",
        "api_key",
        "secret",
        "secret_key",
        "private_key",
        "private_key_der_b64",
        "private_key_path",
        "access_key",
        "credentials",
        "credentials_payload",
        "auth_token",
    }
)

_REDACTED = "*** redacted ***"


def resolve_env_vars(value: str | None) -> str | None:
    """Resolve ``${VAR}`` placeholders from environment variables.

    Returns *None* unchanged.  Raises ``ValueError`` if any ``${VAR}``
    placeholder cannot be resolved (i.e. the env var is not set).
    """
    if value is None:
        return None

    resolved = os.path.expandvars(value)

    # Check for unresolved placeholders
    unresolved = re.findall(r"\$\{(\w+)}", resolved)
    if unresolved:
        raise ValueError(
            f"Unresolved environment variable(s): {', '.join(unresolved)}. "
            "Set them in your environment or .env file."
        )

    return resolved


def _redact_dict(d: dict) -> None:
    """Recursively redact sensitive fields in-place."""
    for key in list(d.keys()):
        if key in _SENSITIVE_FIELDS:
            d[key] = _REDACTED
        elif isinstance(d[key], dict):
            _redact_dict(d[key])


def redact_payload(payload: dict) -> dict:
    """Return a deep copy of *payload* with sensitive fields masked.

    Works on any dict structure — connections, datastores, or nested
    payloads.  Sensitive fields are replaced with ``*** redacted ***``.
    """
    redacted = copy.deepcopy(payload)
    _redact_dict(redacted)
    return redacted
