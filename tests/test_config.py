"""Tests for configuration management."""

import json
from unittest.mock import patch


from qualytics.config import (
    __version__,
    save_config,
    load_config,
    is_token_valid,
)


class TestVersion:
    """Tests for version management."""

    def test_version_is_string(self):
        assert isinstance(__version__, str)

    def test_version_is_semver(self):
        parts = __version__.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()


class TestSaveConfig:
    """Tests for save_config."""

    def test_save_config_creates_file(self, tmp_path):
        config_path = tmp_path / "config.json"
        with patch("qualytics.config.CONFIG_PATH", str(config_path)):
            save_config({"url": "https://example.com/api", "token": "test-token"})
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data["url"] == "https://example.com/api"
        assert data["token"] == "test-token"

    def test_save_config_creates_directory(self, tmp_path):
        config_path = tmp_path / "subdir" / "config.json"
        with patch("qualytics.config.CONFIG_PATH", str(config_path)):
            save_config({"url": "https://example.com/api", "token": "t"})
        assert config_path.exists()

    def test_save_config_overwrites_existing(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"url": "old"}))
        with patch("qualytics.config.CONFIG_PATH", str(config_path)):
            save_config({"url": "new"})
        data = json.loads(config_path.read_text())
        assert data["url"] == "new"


class TestLoadConfig:
    """Tests for load_config."""

    def test_load_config_returns_data(self, tmp_path):
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"url": "https://example.com/api"}))
        with patch("qualytics.config.CONFIG_PATH", str(config_path)):
            result = load_config()
        assert result == {"url": "https://example.com/api"}

    def test_load_config_returns_none_when_missing(self, tmp_path):
        config_path = tmp_path / "nonexistent.json"
        with patch("qualytics.config.CONFIG_PATH", str(config_path)):
            result = load_config()
        assert result is None


class TestIsTokenValid:
    """Tests for JWT token validation."""

    def test_invalid_token_returns_none(self):
        result = is_token_valid("not-a-jwt-token")
        assert result is None

    def test_token_without_exp_is_valid(self):
        """A JWT with no expiration claim should still be considered valid."""
        import jwt

        token = jwt.encode({"sub": "user123"}, key="", algorithm="HS256")
        result = is_token_valid(token)
        assert result == token
