"""Tests for integration setup and migration."""

from datetime import date

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


async def test_migrate_v1_entry_rewrites_unique_ids(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """V1 entries migrate registry unique_ids; entity_ids are preserved."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=1, title="Heating Degree Days", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)

    # Simulate pre-existing v1 entities with old static unique_ids
    entity_registry = er.async_get(hass)
    old_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_hdd_daily",
        suggested_object_id="hdd_daily",
        config_entry=entry,
    )
    assert old_entity.entity_id == "sensor.hdd_daily"

    old_weekly = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_hdd_weekly",
        suggested_object_id="hdd_weekly",
        config_entry=entry,
    )
    assert old_weekly.entity_id == "sensor.hdd_weekly"

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    migrated = entity_registry.async_get("sensor.hdd_daily")
    assert migrated is not None
    # entity_id preserved, unique_id rewritten
    assert migrated.unique_id == f"{entry.entry_id}_hdd_daily"

    # All entities of the entry are migrated, not just the first
    migrated_weekly = entity_registry.async_get("sensor.hdd_weekly")
    assert migrated_weekly is not None
    assert migrated_weekly.unique_id == f"{entry.entry_id}_hdd_weekly"


async def test_migrate_future_version_fails(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """Entries from a future major version must not be migrated."""
    entry = MockConfigEntry(domain=DOMAIN, version=3, title="X", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


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


async def test_entry_rename_propagates_to_device_name(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """Renaming the entry in the UI reloads it so the device name tracks the title."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, title="Salon", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    assert device.name == "Salon"

    # Simulate a UI rename of the config entry (title-only update).
    hass.config_entries.async_update_entry(entry, title="Garage")
    await hass.async_block_till_done()

    device = device_registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device.name == "Garage"


async def test_disabled_sensor_types_are_removed_from_registry(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """Entities of sensor types turned off in the configuration are dropped."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Heating Degree Days",
        data={**ENTRY_DATA, CONF_INCLUDE_MONTHLY: False},
    )
    entry.add_to_hass(hass)

    entity_registry = er.async_get(hass)
    stale = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{entry.entry_id}_hdd_monthly",
        suggested_object_id="hdd_monthly",
        config_entry=entry,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(stale.entity_id) is None
    remaining = {
        e.unique_id
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }
    assert f"{entry.entry_id}_hdd_daily" in remaining
    assert f"{entry.entry_id}_hdd_monthly" not in remaining


def _storage_payload(data: dict, values: dict) -> dict:
    return {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}_data",
        "data": {
            "config": {
                CONF_TEMPERATURE_SENSOR: data[CONF_TEMPERATURE_SENSOR],
                CONF_BASE_TEMPERATURE: data[CONF_BASE_TEMPERATURE],
                CONF_TEMPERATURE_UNIT: data[CONF_TEMPERATURE_UNIT],
            },
            "daily_hdd_values": values,
            "daily_cdd_values": {},
        },
    }


async def test_stored_values_kept_when_settings_match(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant, hass_storage
) -> None:
    """Stored daily values written with the current settings are loaded."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, title="HDD", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}_data_{entry.entry_id}"] = _storage_payload(
        ENTRY_DATA, {"2026-09-20": 4.2}
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.daily_hdd_values[date(2026, 9, 20)] == 4.2


async def test_stored_values_discarded_when_base_temperature_changed(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant, hass_storage
) -> None:
    """Values calculated with another base temperature are not mixed in."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, title="HDD", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    hass_storage[f"{DOMAIN}_data_{entry.entry_id}"] = _storage_payload(
        {**ENTRY_DATA, CONF_BASE_TEMPERATURE: 15.0}, {"2026-09-20": 4.2}
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert date(2026, 9, 20) not in coordinator.daily_hdd_values
