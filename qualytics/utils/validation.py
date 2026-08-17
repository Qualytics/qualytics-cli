"""Validation utilities for Qualytics CLI."""

import os


def _api_path() -> str:
    """The path prefix the API is served under, without surrounding slashes.

    Deployments serve the API under ``/api``; a bare local controlplane serves
    it at the root. ``QUALYTICS_API_PATH`` overrides the default — set it to an
    empty string for a root-served API (e.g. ``http://localhost:8000``).
    """
    path = os.environ.get("QUALYTICS_API_PATH")
    return "api" if path is None else path.strip("/")


def validate_and_format_url(url: str) -> str:
    """Validates and formats the URL to the desired structure.

    Preserves ``http://`` when explicitly provided (e.g. for local
    development).  Defaults to ``https://`` when no scheme is given.

    Any trailing ``/api`` is normalized away before the configured API path is
    appended, so stored (already formatted) URLs can be re-formatted safely.
    """

    if url.startswith("http://"):
        # Preserve explicit http:// (local development)
        pass
    elif url.startswith("https://"):
        pass
    else:
        url = "https://" + url

    # Normalize an existing API path without stripping valid hostname characters.
    url = url.rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]

    api_path = _api_path()
    url = url.rstrip("/") + "/"
    return url + api_path + "/" if api_path else url
