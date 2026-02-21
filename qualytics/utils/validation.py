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

    # Remove any trailing slashes or '/api' or '/api/'
    url = url.rstrip("/").rstrip("/api").rstrip("/")

    # Append '/api/' to the URL
    url += "/api/"

    return url
