"""Tests for the centralized API client."""

import pytest
import requests
from unittest.mock import patch, MagicMock

from qualytics.api.client import (
    QualyticsClient,
    QualyticsAPIError,
    AuthenticationError,
    NotFoundError,
    ConflictError,
    ServerError,
    get_client,
)
from qualytics.utils.validation import validate_and_format_url


class TestQualyticsClient:
    """Tests for the QualyticsClient class."""

    def test_init_sets_base_url_with_trailing_slash(self):
        client = QualyticsClient("https://example.com/api", "token123")
        assert client.base_url == "https://example.com/api/"

    def test_init_normalizes_trailing_slash(self):
        client = QualyticsClient("https://example.com/api/", "token123")
        assert client.base_url == "https://example.com/api/"

    def test_init_sets_auth_header(self):
        client = QualyticsClient("https://example.com/api", "mytoken")
        assert client._session.headers["Authorization"] == "Bearer mytoken"

    def test_init_sets_content_type(self):
        client = QualyticsClient("https://example.com/api", "token")
        assert client._session.headers["Content-Type"] == "application/json"

    def test_init_ssl_verify_default_true(self):
        client = QualyticsClient("https://example.com/api", "token")
        assert client.ssl_verify is True
        assert client._session.verify is True

    def test_init_ssl_verify_disabled(self):
        client = QualyticsClient("https://example.com/api", "token", ssl_verify=False)
        assert client.ssl_verify is False
        assert client._session.verify is False

    def test_init_custom_timeout(self):
        client = QualyticsClient("https://example.com/api", "token", timeout=60)
        assert client.timeout == 60

    def test_build_url(self):
        client = QualyticsClient("https://example.com/api", "token")
        assert (
            client._build_url("quality-checks")
            == "https://example.com/api/quality-checks"
        )

    def test_build_url_strips_leading_slash(self):
        client = QualyticsClient("https://example.com/api", "token")
        assert (
            client._build_url("/quality-checks")
            == "https://example.com/api/quality-checks"
        )


class TestRaiseForStatus:
    """Tests for the _raise_for_status method."""

    def _make_response(self, status_code, text="error body"):
        resp = MagicMock()
        resp.ok = 200 <= status_code < 300
        resp.status_code = status_code
        resp.text = text
        resp.url = "https://example.com/api/test"
        return resp

    def test_ok_response_does_not_raise(self):
        resp = self._make_response(200)
        QualyticsClient._raise_for_status(resp)  # Should not raise

    def test_204_response_does_not_raise(self):
        resp = self._make_response(204)
        QualyticsClient._raise_for_status(resp)  # Should not raise

    def test_401_raises_auth_error(self):
        resp = self._make_response(401)
        with pytest.raises(AuthenticationError) as exc_info:
            QualyticsClient._raise_for_status(resp)
        assert exc_info.value.status_code == 401

    def test_403_raises_auth_error(self):
        resp = self._make_response(403)
        with pytest.raises(AuthenticationError):
            QualyticsClient._raise_for_status(resp)

    def test_404_raises_not_found(self):
        resp = self._make_response(404)
        with pytest.raises(NotFoundError) as exc_info:
            QualyticsClient._raise_for_status(resp)
        assert exc_info.value.status_code == 404

    def test_409_raises_conflict(self):
        resp = self._make_response(409, "Conflict: id: 42")
        with pytest.raises(ConflictError) as exc_info:
            QualyticsClient._raise_for_status(resp)
        assert exc_info.value.status_code == 409
        assert "42" in exc_info.value.message

    def test_500_raises_server_error(self):
        resp = self._make_response(500)
        with pytest.raises(ServerError):
            QualyticsClient._raise_for_status(resp)

    def test_502_raises_server_error(self):
        resp = self._make_response(502)
        with pytest.raises(ServerError):
            QualyticsClient._raise_for_status(resp)

    def test_422_raises_generic_api_error(self):
        resp = self._make_response(422)
        with pytest.raises(QualyticsAPIError) as exc_info:
            QualyticsClient._raise_for_status(resp)
        assert exc_info.value.status_code == 422


class TestQualyticsAPIError:
    """Tests for the exception hierarchy."""

    def test_error_has_status_code(self):
        err = QualyticsAPIError(400, "Bad Request")
        assert err.status_code == 400

    def test_error_has_message(self):
        err = QualyticsAPIError(400, "Bad Request")
        assert err.message == "Bad Request"

    def test_error_str(self):
        err = QualyticsAPIError(400, "Bad Request")
        assert "HTTP 400" in str(err)

    def test_auth_error_is_api_error(self):
        assert issubclass(AuthenticationError, QualyticsAPIError)

    def test_not_found_is_api_error(self):
        assert issubclass(NotFoundError, QualyticsAPIError)

    def test_conflict_is_api_error(self):
        assert issubclass(ConflictError, QualyticsAPIError)

    def test_server_error_is_api_error(self):
        assert issubclass(ServerError, QualyticsAPIError)


class TestConnectionErrors:
    """Tests for connection error handling."""

    def test_ssl_error_gives_helpful_message(self):
        client = QualyticsClient("https://localhost:8000/api/", "token")
        with patch.object(
            client._session,
            "request",
            side_effect=requests.exceptions.SSLError("SSL handshake failed"),
        ):
            with pytest.raises(ConnectionError, match="SSL handshake failed"):
                client.get("test")

    def test_ssl_error_suggests_http(self):
        client = QualyticsClient("https://localhost:8000/api/", "token")
        with patch.object(
            client._session,
            "request",
            side_effect=requests.exceptions.SSLError("SSL error"),
        ):
            with pytest.raises(ConnectionError, match="http://"):
                client.get("test")

    def test_connection_error_gives_helpful_message(self):
        client = QualyticsClient("https://localhost:9999/api/", "token")
        with patch.object(
            client._session,
            "request",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        ):
            with pytest.raises(ConnectionError, match="Could not connect"):
                client.get("test")


class TestValidateAndFormatUrl:
    """Tests for URL validation and formatting."""

    def test_https_url_preserved(self):
        assert (
            validate_and_format_url("https://example.com") == "https://example.com/api/"
        )

    def test_http_url_preserved(self):
        assert (
            validate_and_format_url("http://localhost:8000")
            == "http://localhost:8000/api/"
        )

    def test_no_scheme_defaults_to_https(self):
        assert validate_and_format_url("example.com") == "https://example.com/api/"

    def test_trailing_slash_stripped(self):
        assert (
            validate_and_format_url("https://example.com/")
            == "https://example.com/api/"
        )

    def test_trailing_api_stripped(self):
        assert (
            validate_and_format_url("https://example.com/api")
            == "https://example.com/api/"
        )

    def test_trailing_api_slash_stripped(self):
        assert (
            validate_and_format_url("https://example.com/api/")
            == "https://example.com/api/"
        )

    def test_http_localhost_with_port(self):
        assert (
            validate_and_format_url("http://localhost:8000/api/")
            == "http://localhost:8000/api/"
        )


class TestGetClient:
    """Tests for the get_client factory function."""

    def test_get_client_no_config_exits(self):
        with patch("qualytics.config.load_config", return_value=None):
            with pytest.raises(SystemExit):
                get_client()

    def test_get_client_invalid_token_exits(self):
        config = {"url": "https://example.com/api", "token": "bad"}
        with (
            patch("qualytics.config.load_config", return_value=config),
            patch("qualytics.config.is_token_valid", return_value=None),
        ):
            with pytest.raises(SystemExit):
                get_client()

    def test_get_client_returns_client(self):
        import jwt

        token = jwt.encode({"sub": "user"}, key="", algorithm="HS256")
        config = {"url": "https://example.com/api", "token": token}
        client = get_client(config)
        assert isinstance(client, QualyticsClient)
        assert client.ssl_verify is True

    def test_get_client_respects_ssl_verify(self):
        import jwt

        token = jwt.encode({"sub": "user"}, key="", algorithm="HS256")
        config = {
            "url": "https://example.com/api",
            "token": token,
            "ssl_verify": False,
        }
        client = get_client(config)
        assert client.ssl_verify is False
