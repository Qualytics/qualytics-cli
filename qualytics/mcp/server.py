"""Qualytics MCP — local tools exposed alongside the remote proxy."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import jwt
from fastmcp.exceptions import ToolError

from ..config import load_config, CONFIG_PATH


def auth_status() -> dict:
    """Show current Qualytics CLI authentication status.

    Returns the configured URL, token validity, expiry, and SSL setting.
    Call this first to verify the CLI is configured.
    """
    config = load_config()
    if config is None:
        raise ToolError(
            "Not authenticated. Run 'qualytics auth login' or 'qualytics auth init'."
        )

    url = config.get("url", "")
    token = config.get("token", "")
    ssl_verify = config.get("ssl_verify", True)

    try:
        host = urlparse(url).hostname or url
    except Exception:
        host = url

    masked = token[:4] + "****" if len(token) > 4 else "****"

    result = {
        "host": host,
        "url": url,
        "token": masked,
        "ssl_verify": ssl_verify,
        "config_file": CONFIG_PATH,
        "authenticated": True,
    }

    try:
        decoded = jwt.decode(
            token, algorithms=["none"], options={"verify_signature": False}
        )
        exp = decoded.get("exp")
        if exp is not None:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = exp_dt - now
            result["token_expires"] = exp_dt.isoformat()
            result["token_expired"] = delta.total_seconds() <= 0
            if delta.total_seconds() > 0:
                result["expires_in_days"] = delta.days
            else:
                result["expired_days_ago"] = abs(delta.days)
                result["authenticated"] = False
    except Exception:
        result["token_decode_error"] = True

    return result
