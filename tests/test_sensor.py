"""Tests for the sensor platform with multiple config entries."""

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
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

TEMP_SENSOR = "sensor.outdoor_temperature"


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations():
    """Override the conftest autouse fixture for this module.

    The conftest version depends on ``enable_custom_integrations`` → ``hass``,
    which would initialize ``hass`` before ``recorder_db_url`` and break
    ``recorder_mock`` ordering. Tests here request ``recorder_mock`` and
    ``enable_custom_integrations`` explicitly, in that order, instead.
    """


def _make_entry(
    base_temp: float, title: str, include_cooling: bool = False
) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=title,
        data={
            CONF_TEMPERATURE_SENSOR: TEMP_SENSOR,
            CONF_BASE_TEMPERATURE: base_temp,
            CONF_TEMPERATURE_UNIT: "°C",
            CONF_INCLUDE_COOLING: include_cooling,
            CONF_INCLUDE_WEEKLY: True,
            CONF_INCLUDE_MONTHLY: True,
        },
    )


async def _setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_unique_ids_are_prefixed_with_entry_id(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations
) -> None:
    """Sensor unique_ids must include the config entry id."""
    entry = _make_entry(18.0, "Degree Days Test")
    await _setup_entry(hass, entry)

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert {e.unique_id for e in entries} == {
        f"{entry.entry_id}_hdd_daily",
        f"{entry.entry_id}_hdd_weekly",
        f"{entry.entry_id}_hdd_monthly",
    }


async def test_device_created_per_entry(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations
) -> None:
    """Each entry gets a service device named after the entry title."""
    entry = _make_entry(18.0, "Degree Days Test")
    await _setup_entry(hass, entry)

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.name == "Degree Days Test"
    assert device.entry_type is dr.DeviceEntryType.SERVICE


async def test_two_entries_coexist(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations
) -> None:
    """Two entries with different base temperatures set up without collision."""
    entry_18 = _make_entry(18.0, "Base 18")
    entry_16 = _make_entry(16.0, "Base 16")
    await _setup_entry(hass, entry_18)
    await _setup_entry(hass, entry_16)

    assert entry_18.state is ConfigEntryState.LOADED
    assert entry_16.state is ConfigEntryState.LOADED

    entity_registry = er.async_get(hass)
    assert (
        len(er.async_entries_for_config_entry(entity_registry, entry_18.entry_id)) == 3
    )
    assert (
        len(er.async_entries_for_config_entry(entity_registry, entry_16.entry_id)) == 3
    )


async def test_unique_ids_with_cooling_enabled(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations
) -> None:
    """With cooling enabled, all six HDD and CDD unique_ids are prefixed."""
    entry = _make_entry(18.0, "Degree Days Cooling", include_cooling=True)
    await _setup_entry(hass, entry)

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert {e.unique_id for e in entries} == {
        f"{entry.entry_id}_hdd_daily",
        f"{entry.entry_id}_hdd_weekly",
        f"{entry.entry_id}_hdd_monthly",
        f"{entry.entry_id}_cdd_daily",
        f"{entry.entry_id}_cdd_weekly",
        f"{entry.entry_id}_cdd_monthly",
    }
