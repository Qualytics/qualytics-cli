"""Validation utilities for Qualytics CLI."""


def validate_and_format_url(url: str) -> str:
    """Validates and formats the URL to the desired structure.

    Preserves ``http://`` when explicitly provided (e.g. for local
    development).  Defaults to ``https://`` when no scheme is given.
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

    # Append '/api/' to the URL
    url = url.rstrip("/") + "/api/"

    return url
