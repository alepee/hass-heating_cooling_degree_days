"""Tests for integration setup and migration."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    DOMAIN,
)
from homeassistant.core import HomeAssistant

TEMP_SENSOR = "sensor.outdoor_temperature"

ENTRY_DATA = {
    CONF_TEMPERATURE_SENSOR: TEMP_SENSOR,
    CONF_BASE_TEMPERATURE: 18.0,
    CONF_TEMPERATURE_UNIT: "°C",
    CONF_INCLUDE_COOLING: False,
    CONF_INCLUDE_WEEKLY: True,
    CONF_INCLUDE_MONTHLY: True,
}


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations():
    """Override the conftest autouse fixture for this module.

    The conftest version depends on ``enable_custom_integrations`` → ``hass``,
    which would initialize ``hass`` before ``recorder_db_url`` and break
    ``recorder_mock`` ordering. Tests here request ``recorder_mock`` and
    ``enable_custom_integrations`` explicitly, in that order, instead.
    """


async def test_title_is_not_overwritten_on_setup(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """A custom entry title must survive setup (no forced rewrite)."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, title="My Custom Name", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.title == "My Custom Name"
