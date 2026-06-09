"""Common fixtures for Heating & Cooling Degree Days tests."""

import pytest
from pytest_homeassistant_custom_component.typing import RecorderInstanceContextManager


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture
async def mock_recorder_before_hass(
    async_test_recorder: RecorderInstanceContextManager,
) -> None:
    """Force recorder_db_url to resolve before the hass fixture.

    Required because the integration declares recorder as a dependency.
    """


@pytest.fixture(autouse=True)
async def auto_setup_recorder(recorder_mock):
    """Set up an in-memory recorder for all tests."""
    return
