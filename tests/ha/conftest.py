"""Fixtures for the Home Assistant integration tests."""

from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")



@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/ in every test."""
    yield
