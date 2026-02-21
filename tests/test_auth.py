"""Tests for auth commands (login, status, init)."""

import threading
import time
import urllib.error
import urllib.request
from unittest.mock import patch
import re

import jwt
from typer.testing import CliRunner

from qualytics.cli.auth import _create_callback_server
from qualytics.qualytics import app

runner = CliRunner()


# ── callback server unit tests ───────────────────────────────────────────


class TestCallbackServer:
    """Tests for the local callback HTTP server."""

    def test_valid_callback_extracts_token(self):
        state = "test-state-123"
        result: dict = {}
        server = _create_callback_server(state, result)
        _, port = server.server_address

        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        url = f"http://127.0.0.1:{port}/callback?token=my-jwt-token&state={state}"
        resp = urllib.request.urlopen(url)
        assert resp.status == 200
        thread.join(timeout=5)
        server.server_close()

        assert result["token"] == "my-jwt-token"
        assert "error" not in result

    def test_state_mismatch_returns_error(self):
        state = "correct-state"
        result: dict = {}
        server = _create_callback_server(state, result)
        _, port = server.server_address

        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        url = f"http://127.0.0.1:{port}/callback?token=tok&state=wrong-state"
        try:
            urllib.request.urlopen(url)
        except urllib.error.HTTPError as e:
            assert e.code == 400
        thread.join(timeout=5)
        server.server_close()

        assert "error" in result
        assert "state mismatch" in result["error"].lower()

    def test_missing_token_returns_error(self):
        state = "test-state"
        result: dict = {}
        server = _create_callback_server(state, result)
        _, port = server.server_address

        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        url = f"http://127.0.0.1:{port}/callback?state={state}"
        try:
            urllib.request.urlopen(url)
        except urllib.error.HTTPError as e:
            assert e.code == 400
        thread.join(timeout=5)
        server.server_close()

        assert result.get("error") == "No token in callback"

    def test_server_error_param_forwarded(self):
        state = "test-state"
        result: dict = {}
        server = _create_callback_server(state, result)
        _, port = server.server_address

        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()

        url = f"http://127.0.0.1:{port}/callback?state={state}&error=access_denied"
        try:
            urllib.request.urlopen(url)
        except urllib.error.HTTPError as e:
            assert e.code == 400
        thread.join(timeout=5)
        server.server_close()

        assert result["error"] == "access_denied"


# ── helpers ──────────────────────────────────────────────────────────────


def _simulate_callback(mock_browser):
    """Extract port and state from the captured browser URL, then hit the callback."""
    call_args = mock_browser.call_args[0][0]
    port = re.search(r":(\d+)/callback", call_args).group(1)
    state = re.search(r"state=([^&]+)", call_args).group(1)
    url = f"http://127.0.0.1:{port}/callback?token=test-jwt&state={state}"
    urllib.request.urlopen(url)


# ── CLI integration tests ────────────────────────────────────────────────


class TestAuthLoginCommand:
    """Tests for the auth login CLI command."""

    @patch("qualytics.cli.auth.webbrowser.open")
    @patch("qualytics.cli.auth.save_config")
    @patch("qualytics.cli.auth.is_token_valid", return_value="valid-token")
    def test_successful_login(self, mock_valid, mock_save, mock_browser):
        """Test a full successful auth login flow."""
        mock_browser.side_effect = lambda *a, **kw: _simulate_callback(mock_browser)

        result = runner.invoke(
            app,
            ["auth", "login", "--url", "https://test.qualytics.io", "--timeout", "10"],
        )

        assert result.exit_code == 0
        assert "successful" in result.output.lower()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved["token"] == "test-jwt"
        assert "test.qualytics.io" in saved["url"]
        assert saved["ssl_verify"] is True

    @patch("qualytics.cli.auth.webbrowser.open")
    @patch("qualytics.cli.auth.save_config")
    @patch("qualytics.cli.auth.is_token_valid", return_value="valid-token")
    def test_login_with_no_verify_ssl(self, mock_valid, mock_save, mock_browser):
        """Test that --no-verify-ssl is passed through to config."""
        mock_browser.side_effect = lambda *a, **kw: _simulate_callback(mock_browser)

        result = runner.invoke(
            app,
            [
                "auth",
                "login",
                "--url",
                "https://test.qualytics.io",
                "--no-verify-ssl",
                "--timeout",
                "10",
            ],
        )

        assert result.exit_code == 0
        saved = mock_save.call_args[0][0]
        assert saved["ssl_verify"] is False

    @patch("qualytics.cli.auth.webbrowser.open")
    def test_login_timeout(self, mock_browser):
        """Test that login exits with error on timeout."""
        result = runner.invoke(
            app,
            ["auth", "login", "--url", "https://test.qualytics.io", "--timeout", "1"],
        )

        assert result.exit_code == 1
        assert "timed out" in result.output.lower()

    @patch("qualytics.cli.auth.webbrowser.open")
    @patch("qualytics.cli.auth.is_token_valid", return_value=None)
    def test_login_invalid_token(self, mock_valid, mock_browser):
        """Test that login rejects an invalid/expired token."""

        def simulate_callback(*args, **kwargs):
            call_args = mock_browser.call_args[0][0]
            port = re.search(r":(\d+)/callback", call_args).group(1)
            state = re.search(r"state=([^&]+)", call_args).group(1)
            url = f"http://127.0.0.1:{port}/callback?token=expired-jwt&state={state}"
            urllib.request.urlopen(url)

        mock_browser.side_effect = simulate_callback

        result = runner.invoke(
            app,
            ["auth", "login", "--url", "https://test.qualytics.io", "--timeout", "10"],
        )

        assert result.exit_code == 1
        assert "invalid" in result.output.lower() or "expired" in result.output.lower()

    def test_login_requires_url(self):
        """Test that --url is required."""
        result = runner.invoke(app, ["auth", "login"])
        assert result.exit_code != 0

    @patch("qualytics.cli.auth.webbrowser.open")
    @patch("qualytics.cli.auth.save_config")
    @patch("qualytics.cli.auth.is_token_valid", return_value="valid-token")
    def test_authorize_url_construction(self, mock_valid, mock_save, mock_browser):
        """Test that the authorize URL is constructed correctly."""
        captured_url = {}

        def capture_url(url):
            captured_url["url"] = url
            port = re.search(r":(\d+)/callback", url).group(1)
            state = re.search(r"state=([^&]+)", url).group(1)
            callback = f"http://127.0.0.1:{port}/callback?token=tok&state={state}"
            urllib.request.urlopen(callback)

        mock_browser.side_effect = capture_url

        runner.invoke(
            app,
            [
                "auth",
                "login",
                "--url",
                "https://my-instance.qualytics.io",
                "--timeout",
                "10",
            ],
        )

        authorize_url = captured_url["url"]
        assert "my-instance.qualytics.io" in authorize_url
        assert "/api/cli/authorize" in authorize_url
        assert "state=" in authorize_url
        assert "redirect_uri=http://127.0.0.1:" in authorize_url
        assert "hostname=" in authorize_url

    @patch("qualytics.cli.auth.platform.node", return_value="Jose-MacPro.local")
    @patch("qualytics.cli.auth.webbrowser.open")
    @patch("qualytics.cli.auth.save_config")
    @patch("qualytics.cli.auth.is_token_valid", return_value="valid-token")
    def test_hostname_strips_local_suffix(
        self, mock_valid, mock_save, mock_browser, mock_node
    ):
        """Test that .local suffix is stripped from hostname."""
        captured_url = {}

        def capture_url(url):
            captured_url["url"] = url
            port = re.search(r":(\d+)/callback", url).group(1)
            state = re.search(r"state=([^&]+)", url).group(1)
            callback = f"http://127.0.0.1:{port}/callback?token=tok&state={state}"
            urllib.request.urlopen(callback)

        mock_browser.side_effect = capture_url

        runner.invoke(
            app,
            ["auth", "login", "--url", "https://test.qualytics.io", "--timeout", "10"],
        )

        assert "hostname=Jose-MacPro" in captured_url["url"]
        assert "hostname=Jose-MacPro.local" not in captured_url["url"]


# ── auth status tests ────────────────────────────────────────────────────


class TestAuthStatusCommand:
    """Tests for the auth status CLI command."""

    def test_status_no_config_exits(self):
        """Test that status exits with error when no config exists."""
        with patch("qualytics.cli.auth.load_config", return_value=None):
            result = runner.invoke(app, ["auth", "status"])
            assert result.exit_code == 1
            assert "not logged in" in result.output.lower()

    def test_status_shows_host(self):
        """Test that status displays the hostname from URL."""
        token = jwt.encode(
            {"sub": "user", "exp": int(time.time()) + 86400},
            key="",
            algorithm="HS256",
        )
        config = {
            "url": "https://my-instance.qualytics.io/api/",
            "token": token,
            "ssl_verify": True,
        }
        with patch("qualytics.cli.auth.load_config", return_value=config):
            result = runner.invoke(app, ["auth", "status"])
            assert result.exit_code == 0
            assert "my-instance.qualytics.io" in result.output

    def test_status_masks_token(self):
        """Test that status masks the token (shows first 4 chars + asterisks)."""
        token = jwt.encode(
            {"sub": "user", "exp": int(time.time()) + 86400},
            key="",
            algorithm="HS256",
        )
        config = {
            "url": "https://example.com/api/",
            "token": token,
            "ssl_verify": True,
        }
        with patch("qualytics.cli.auth.load_config", return_value=config):
            result = runner.invoke(app, ["auth", "status"])
            assert result.exit_code == 0
            # Token should be masked — first 4 chars visible, rest asterisks
            assert token[:4] in result.output
            assert token not in result.output

    def test_status_shows_expiry(self):
        """Test that status shows token expiry information."""
        token = jwt.encode(
            {"sub": "user", "exp": int(time.time()) + 86400 * 30},
            key="",
            algorithm="HS256",
        )
        config = {
            "url": "https://example.com/api/",
            "token": token,
            "ssl_verify": True,
        }
        with patch("qualytics.cli.auth.load_config", return_value=config):
            result = runner.invoke(app, ["auth", "status"])
            assert result.exit_code == 0
            assert "expires" in result.output.lower()

    def test_status_expired_token(self):
        """Test that status detects expired tokens."""
        token = jwt.encode(
            {"sub": "user", "exp": int(time.time()) - 86400},
            key="",
            algorithm="HS256",
        )
        config = {
            "url": "https://example.com/api/",
            "token": token,
            "ssl_verify": True,
        }
        with patch("qualytics.cli.auth.load_config", return_value=config):
            result = runner.invoke(app, ["auth", "status"])
            assert result.exit_code == 1
            assert "expired" in result.output.lower()

    def test_status_shows_ssl_status(self):
        """Test that status shows SSL verification status."""
        token = jwt.encode(
            {"sub": "user", "exp": int(time.time()) + 86400},
            key="",
            algorithm="HS256",
        )
        config = {
            "url": "https://example.com/api/",
            "token": token,
            "ssl_verify": False,
        }
        with patch("qualytics.cli.auth.load_config", return_value=config):
            result = runner.invoke(app, ["auth", "status"])
            assert result.exit_code == 0
            assert "disabled" in result.output.lower()


# ── auth init tests ──────────────────────────────────────────────────────


class TestAuthInitCommand:
    """Tests for the auth init CLI command."""

    @patch("qualytics.cli.auth.save_config")
    @patch("qualytics.cli.auth.is_token_valid", return_value="valid-token")
    def test_init_saves_config(self, mock_valid, mock_save):
        """Test that auth init saves configuration."""
        result = runner.invoke(
            app,
            [
                "auth",
                "init",
                "--url",
                "https://test.qualytics.io",
                "--token",
                "my-token",
            ],
        )
        assert result.exit_code == 0
        assert "saved" in result.output.lower()
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert "test.qualytics.io" in saved["url"]
        assert saved["token"] == "my-token"
        assert saved["ssl_verify"] is True

    @patch("qualytics.cli.auth.save_config")
    @patch("qualytics.cli.auth.is_token_valid", return_value="valid-token")
    def test_init_with_no_verify_ssl(self, mock_valid, mock_save):
        """Test that auth init respects --no-verify-ssl."""
        result = runner.invoke(
            app,
            [
                "auth",
                "init",
                "--url",
                "https://test.qualytics.io",
                "--token",
                "my-token",
                "--no-verify-ssl",
            ],
        )
        assert result.exit_code == 0
        saved = mock_save.call_args[0][0]
        assert saved["ssl_verify"] is False

    def test_init_requires_url_and_token(self):
        """Test that auth init requires --url and --token."""
        result = runner.invoke(app, ["auth", "init"])
        assert result.exit_code != 0

    @patch("qualytics.cli.auth.is_token_valid", return_value=None)
    def test_init_rejects_invalid_token(self, mock_valid):
        """Test that auth init rejects an invalid token."""
        result = runner.invoke(
            app,
            ["auth", "init", "--url", "https://test.qualytics.io", "--token", "bad"],
        )
        # Should not save config — is_token_valid returns None
        assert result.exit_code == 0  # no explicit exit, just doesn't save


# ── deprecated command tests ─────────────────────────────────────────────


class TestDeprecatedCommands:
    """Tests for deprecated command wrappers."""

    @patch("qualytics.cli.auth.save_config")
    @patch("qualytics.cli.auth.is_token_valid", return_value="valid-token")
    def test_deprecated_init_delegates(self, mock_valid, mock_save):
        """Test that deprecated 'init' delegates to 'auth init'."""
        result = runner.invoke(
            app,
            ["init", "--url", "https://test.qualytics.io", "--token", "my-token"],
        )
        assert result.exit_code == 0
        assert "deprecated" in result.output.lower()
        mock_save.assert_called_once()

    def test_deprecated_show_config_delegates(self):
        """Test that deprecated 'show-config' delegates to 'auth status'."""
        with patch("qualytics.cli.auth.load_config", return_value=None):
            result = runner.invoke(app, ["show-config"])
            assert "deprecated" in result.output.lower()
