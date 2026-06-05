"""Common fixtures for Heating & Cooling Degree Days tests."""

import pytest


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
