"""Keep numerical and normalization tests independent of HA/recorder fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations():
    """Override the integration fixture: these tests never create Home Assistant."""


@pytest.fixture(autouse=True)
def auto_setup_recorder():
    """Override the recorder fixture: these tests operate only on values."""
