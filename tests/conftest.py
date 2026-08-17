"""Shared test fixtures for qualytics-cli tests."""

import pytest
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _clean_api_path(monkeypatch):
    """Keep the suite hermetic against the developer's own CLI config.

    The CLI loads ~/.qualytics/.env at import, so a locally configured
    QUALYTICS_API_PATH (e.g. for a root-served controlplane) would otherwise
    leak into every URL assertion. Tests that exercise the override set it
    explicitly via monkeypatch.
    """
    monkeypatch.delenv("QUALYTICS_API_PATH", raising=False)


@pytest.fixture
def cli_runner():
    """Provide a Typer CLI test runner."""
    return CliRunner()
