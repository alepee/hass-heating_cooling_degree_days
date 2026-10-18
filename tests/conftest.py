"""Common fixtures for Heating & Cooling Degree Days tests."""

import pytest


@pytest.fixture
async def mock_recorder_before_hass(async_test_recorder) -> None:
    """Force recorder_db_url to resolve before the hass fixture.

    Required because the integration declares recorder as a dependency.
    Leave the fixture untyped: older test harnesses do not export
    RecorderInstanceContextManager. Tests request recorder_mock explicitly,
    so pure calculation tests do not initialize Home Assistant or its recorder.
    """
