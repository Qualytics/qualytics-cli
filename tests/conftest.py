"""Shared test fixtures for qualytics-cli tests."""

import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli_runner():
    """Provide a Typer CLI test runner."""
    return CliRunner()
