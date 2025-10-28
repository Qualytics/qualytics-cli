"""Validation utilities for Qualytics CLI."""


def validate_and_format_url(url: str) -> str:
    """Validates and formats the URL to the desired structure."""

    # Ensure the URL starts with 'https://'
    if not url.startswith("https://"):
        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)
        else:
            url = "https://" + url

    # Remove any trailing slashes or '/api' or '/api/'
    url = url.rstrip("/").rstrip("/api").rstrip("/")

    # Append '/api/' to the URL
    url += "/api/"

    return url
