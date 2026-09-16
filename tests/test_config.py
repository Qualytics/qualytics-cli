"""Tests for configuration management."""

import json
from unittest.mock import patch

import pytest
import yaml

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
        config_path = tmp_path / "config.yaml"
        with patch("qualytics.config.CONFIG_PATH", str(config_path)):
            save_config({"url": "https://example.com/api", "token": "test-token"})
        assert config_path.exists()
        data = yaml.safe_load(config_path.read_text())
        assert data["url"] == "https://example.com/api"
        assert data["token"] == "test-token"

    def test_save_config_creates_directory(self, tmp_path):
        config_path = tmp_path / "subdir" / "config.yaml"
        with patch("qualytics.config.CONFIG_PATH", str(config_path)):
            save_config({"url": "https://example.com/api", "token": "t"})
        assert config_path.exists()

    def test_save_config_overwrites_existing(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.safe_dump({"url": "old"}))
        with patch("qualytics.config.CONFIG_PATH", str(config_path)):
            save_config({"url": "new"})
        data = yaml.safe_load(config_path.read_text())
        assert data["url"] == "new"


class TestLoadConfig:
    """Tests for load_config."""

    def test_load_config_returns_data(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text(yaml.safe_dump({"url": "https://example.com/api"}))
        with patch("qualytics.config.CONFIG_PATH", str(config_path)):
            result = load_config()
        assert result == {"url": "https://example.com/api"}

    def test_load_config_returns_none_when_missing(self, tmp_path):
        config_path = tmp_path / "nonexistent.yaml"
        legacy_path = tmp_path / "nonexistent.json"
        with (
            patch("qualytics.config.CONFIG_PATH", str(config_path)),
            patch("qualytics.config.CONFIG_PATH_LEGACY", str(legacy_path)),
        ):
            result = load_config()
        assert result is None

    def test_load_config_migrates_legacy_json(self, tmp_path):
        """Legacy config.json should be auto-migrated to config.yaml."""
        yaml_path = tmp_path / "config.yaml"
        json_path = tmp_path / "config.json"
        json_path.write_text(
            json.dumps({"url": "https://example.com/api", "token": "t"})
        )
        with (
            patch("qualytics.config.CONFIG_PATH", str(yaml_path)),
            patch("qualytics.config.CONFIG_PATH_LEGACY", str(json_path)),
        ):
            result = load_config()
        assert result == {"url": "https://example.com/api", "token": "t"}
        assert yaml_path.exists()
        migrated = yaml.safe_load(yaml_path.read_text())
        assert migrated["url"] == "https://example.com/api"

    def test_load_config_prefers_yaml_over_json(self, tmp_path):
        """When both config.yaml and config.json exist, YAML wins."""
        yaml_path = tmp_path / "config.yaml"
        json_path = tmp_path / "config.json"
        yaml_path.write_text(yaml.safe_dump({"url": "from-yaml"}))
        json_path.write_text(json.dumps({"url": "from-json"}))
        with (
            patch("qualytics.config.CONFIG_PATH", str(yaml_path)),
            patch("qualytics.config.CONFIG_PATH_LEGACY", str(json_path)),
        ):
            result = load_config()
        assert result["url"] == "from-yaml"


class TestIsTokenValid:
    """Tests for JWT token validation."""

    def test_invalid_token_returns_none(self):
        result = is_token_valid("not-a-jwt-token")
        assert result is None

    def test_token_without_exp_is_valid(self):
        """A JWT with no expiration claim should still be considered valid."""
        import jwt

        token = jwt.encode(
            {"sub": "user123"},
            key="test-secret-key-with-at-least-32-bytes",
            algorithm="HS256",
        )
        result = is_token_valid(token)
        assert result == token


class TestConfigHomeOverride:
    """Tests for the QUALYTICS_CONFIG_HOME directory override."""

    def test_config_home_env_redirects_all_paths(self, monkeypatch, tmp_path):
        import importlib

        import qualytics.config as config_module

        monkeypatch.setenv("QUALYTICS_CONFIG_HOME", str(tmp_path))
        importlib.reload(config_module)
        try:
            assert config_module.BASE_PATH == str(tmp_path)
            assert config_module.CONFIG_PATH == str(tmp_path / "config.yaml")

            config_module.save_config({"url": "https://alt.example.com", "token": "t"})
            assert (tmp_path / "config.yaml").exists()
            assert config_module.load_config()["url"] == "https://alt.example.com"
        finally:
            monkeypatch.delenv("QUALYTICS_CONFIG_HOME", raising=False)
            importlib.reload(config_module)

    def test_default_base_path_is_home_dot_qualytics(self):
        from pathlib import Path

        from qualytics.config import BASE_PATH

        assert BASE_PATH == f"{Path.home()}/.qualytics"


class TestLoadConfigEnvOverride:
    """Tests for the QUALYTICS_URL / QUALYTICS_TOKEN environment override."""

    def test_env_pair_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("QUALYTICS_URL", "https://uat.example.com")
        monkeypatch.setenv("QUALYTICS_TOKEN", "env-token")
        config = load_config()
        assert config == {"url": "https://uat.example.com", "token": "env-token"}

    def test_url_without_token_exits(self, monkeypatch):
        monkeypatch.setenv("QUALYTICS_URL", "https://uat.example.com")
        with pytest.raises(SystemExit):
            load_config()

    def test_token_without_url_exits(self, monkeypatch):
        monkeypatch.setenv("QUALYTICS_TOKEN", "env-token")
        with pytest.raises(SystemExit):
            load_config()

    def test_env_ssl_verify_flag(self, monkeypatch):
        monkeypatch.setenv("QUALYTICS_URL", "https://uat.example.com")
        monkeypatch.setenv("QUALYTICS_TOKEN", "env-token")
        monkeypatch.setenv("QUALYTICS_SSL_VERIFY", "0")
        assert load_config()["ssl_verify"] is False
        monkeypatch.setenv("QUALYTICS_SSL_VERIFY", "true")
        assert load_config()["ssl_verify"] is True

    def test_no_env_falls_back_to_file(self, monkeypatch, tmp_path):
        yaml_path = tmp_path / "config.yaml"
        yaml_path.write_text(yaml.safe_dump({"url": "from-file", "token": "t"}))
        with patch("qualytics.config.CONFIG_PATH", str(yaml_path)):
            assert load_config()["url"] == "from-file"
