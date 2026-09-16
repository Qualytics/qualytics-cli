"""Shared test fixtures for qualytics-cli tests."""

import pytest
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _clean_api_path(monkeypatch):
    """Keep the suite hermetic against the developer's own CLI config.

    The CLI loads ~/.qualytics/.env at import, so a locally configured
    QUALYTICS_API_PATH (e.g. for a root-served controlplane) or a
    QUALYTICS_URL/QUALYTICS_TOKEN instance override would otherwise leak
    into every URL assertion and client factory test. Tests that exercise
    the overrides set them explicitly via monkeypatch.
    """
    monkeypatch.delenv("QUALYTICS_API_PATH", raising=False)
    monkeypatch.delenv("QUALYTICS_URL", raising=False)
    monkeypatch.delenv("QUALYTICS_TOKEN", raising=False)
    monkeypatch.delenv("QUALYTICS_SSL_VERIFY", raising=False)


@pytest.fixture
def cli_runner():
    """Provide a Typer CLI test runner."""
    return CliRunner()
