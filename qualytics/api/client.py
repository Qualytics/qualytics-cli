"""Centralized API client for the Qualytics controlplane."""

import requests
import urllib3
from rich import print


class QualyticsAPIError(Exception):
    """Base exception for API errors."""

    def __init__(self, status_code: int, message: str, url: str = ""):
        self.status_code = status_code
        self.message = message
        self.url = url
        super().__init__(f"HTTP {status_code}: {message}")


class AuthenticationError(QualyticsAPIError):
    """Raised on 401/403 responses."""

    pass


class NotFoundError(QualyticsAPIError):
    """Raised on 404 responses."""

    pass


class ConflictError(QualyticsAPIError):
    """Raised on 409 responses."""

    pass


class ServerError(QualyticsAPIError):
    """Raised on 5xx responses."""

    pass


class QualyticsClient:
    """HTTP client for the Qualytics API.

    Centralizes authentication, SSL verification, timeouts, and error
    handling so that every caller gets consistent behaviour.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        ssl_verify: bool = True,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/"):
            self.base_url += "/"
        self.token = token
        self.ssl_verify = ssl_verify
        self.timeout = timeout

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
        )
        self._session.verify = ssl_verify

        # Suppress InsecureRequestWarning only when SSL verification is off
        if not ssl_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # -- public HTTP helpers --------------------------------------------------

    def get(self, path: str, params: dict | None = None, **kwargs) -> requests.Response:
        return self._request("GET", path, params=params, **kwargs)

    def post(
        self, path: str, json: dict | None = None, params: dict | None = None, **kwargs
    ) -> requests.Response:
        return self._request("POST", path, json=json, params=params, **kwargs)

    def put(self, path: str, json: dict | None = None, **kwargs) -> requests.Response:
        return self._request("PUT", path, json=json, **kwargs)

    def patch(self, path: str, json: dict | None = None, **kwargs) -> requests.Response:
        return self._request("PATCH", path, json=json, **kwargs)

    def delete(self, path: str, **kwargs) -> requests.Response:
        return self._request("DELETE", path, **kwargs)

    # -- internals ------------------------------------------------------------

    def _build_url(self, path: str) -> str:
        return f"{self.base_url}{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self._build_url(path)
        kwargs.setdefault("timeout", self.timeout)

        response = self._session.request(method, url, **kwargs)
        self._raise_for_status(response)
        return response

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        """Translate HTTP error codes into typed exceptions."""
        if response.ok:
            return

        status = response.status_code
        try:
            body = response.text
        except Exception:
            body = "(unable to read response body)"

        url = str(response.url)

        if status in (401, 403):
            raise AuthenticationError(
                status,
                "Authentication failed. Your token may be expired or invalid. "
                'Run: qualytics init --url "..." --token "..." to reconfigure.',
                url,
            )
        if status == 404:
            raise NotFoundError(status, f"Resource not found: {body}", url)
        if status == 409:
            raise ConflictError(status, f"Conflict: {body}", url)
        if status >= 500:
            raise ServerError(status, f"Server error: {body}", url)

        raise QualyticsAPIError(status, body, url)


def get_client(config: dict | None = None) -> QualyticsClient:
    """Create a QualyticsClient from the stored configuration.

    If *config* is ``None`` the configuration is loaded from disk.
    """
    from ..config import load_config, is_token_valid
    from ..utils import validate_and_format_url

    if config is None:
        config = load_config()

    if config is None:
        print(
            "[bold red]Configuration not found. Run 'qualytics init' first.[/bold red]"
        )
        raise SystemExit(1)

    token = is_token_valid(config["token"])
    if token is None:
        raise SystemExit(1)

    base_url = validate_and_format_url(config["url"])
    ssl_verify = config.get("ssl_verify", True)

    return QualyticsClient(
        base_url=base_url,
        token=token,
        ssl_verify=ssl_verify,
    )
