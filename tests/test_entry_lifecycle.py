"""Regression tests for loaded entries, setup rollback, and persistent storage."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

ENTRY_DATA = {
    "temperature_sensor": "sensor.outdoor_temperature",
    "base_temperature": 18.0,
    "temperature_unit": "°C",
    "include_cooling": False,
    "include_weekly": True,
    "include_monthly": True,
}


@pytest.fixture(autouse=True)
def _calculated_data():
    """Isolate lifecycle tests from recorder history and calculation semantics."""
    with patch(
        "custom_components.heating_cooling_degree_days.coordinator."
        "HDDDataUpdateCoordinator._async_update_data",
        return_value={
            "hdd_daily": 1.0,
            "hdd_weekly": 2.0,
            "hdd_monthly": 3.0,
            "cdd_daily": 0.0,
            "cdd_weekly": 0.0,
            "cdd_monthly": 0.0,
        },
    ):
        yield


def _add_entry(hass: HomeAssistant, **overrides) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Heating Degree Days (18.0°C)",
        data={**ENTRY_DATA, **overrides},
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        ENTRY_DATA["temperature_sensor"],
        "12.5",
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )
    return entry


async def test_loaded_reconfigure_reloads_once(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """Reconfiguration of a loaded entry performs one real unload/setup cycle."""
    entry = _add_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    old_coordinator = entry.runtime_data
    registry = er.async_get(hass)
    entity_ids = {
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }

    with patch.object(
        hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload
    ) as reload_entry:
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": entry.title,
                **{k: v for k, v in ENTRY_DATA.items() if k != "temperature_unit"},
                "base_temperature": 15.0,
            },
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    reload_entry.assert_awaited_once_with(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old_coordinator
    assert entry.runtime_data.base_temp == 15.0
    assert entry.title == "Heating Degree Days (15.0°C)"
    assert len(entry.update_listeners) == 1
    assert DOMAIN not in hass.data
    assert entity_ids == {
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert all(hass.states.get(entity_id) is not None for entity_id in entity_ids)


async def test_unchanged_loaded_reconfigure_does_not_reload(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """Submitting unchanged settings leaves the active coordinator alone."""
    entry = _add_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    with patch.object(hass.config_entries, "async_reload", new=AsyncMock()) as reload:
        result = await entry.start_reconfigure_flow(hass)
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {k: v for k, v in ENTRY_DATA.items() if k != "temperature_unit"},
        )
        await hass.async_block_till_done()

    reload.assert_not_awaited()
    assert entry.runtime_data is coordinator


@pytest.mark.parametrize(
    ("error", "expected_state"),
    [
        (
            ConfigEntryNotReady("History temporarily unavailable"),
            ConfigEntryState.SETUP_RETRY,
        ),
        (ConfigEntryAuthFailed("Authentication failed"), ConfigEntryState.SETUP_ERROR),
        (RuntimeError("Unexpected setup error"), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_first_refresh_failure_reaches_home_assistant(
    recorder_mock,
    enable_custom_integrations,
    hass: HomeAssistant,
    error,
    expected_state,
) -> None:
    """HA handles retry/auth errors and no runtime data or listener is retained."""
    entry = _add_entry(hass)
    with patch(
        "custom_components.heating_cooling_degree_days.coordinator."
        "HDDDataUpdateCoordinator.async_config_entry_first_refresh",
        side_effect=error,
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is expected_state
    assert not hasattr(entry, "runtime_data")
    assert not entry.update_listeners
    assert DOMAIN not in hass.data


async def test_forwarding_failure_rolls_back_entities_and_runtime_data(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """An error after the sensor platform loads leaves no active entities behind."""
    entry = _add_entry(hass)
    forward = hass.config_entries.async_forward_entry_setups
    coordinators = []

    async def fail_after_forward(config_entry, platforms):
        await forward(config_entry, platforms)
        coordinators.append(config_entry.runtime_data)
        raise ConfigEntryNotReady("Retry after partial setup")

    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        side_effect=fail_after_forward,
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hasattr(entry, "runtime_data")
    assert not entry.update_listeners
    assert not coordinators[0]._listeners
    assert coordinators[0]._unsub_refresh is None
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        assert hass.data["sensor"].get_entity(entity.entity_id) is None

    # The same entry can be retried without duplicate entities or listeners.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(entry.update_listeners) == 1
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 3


async def test_unload_failure_preserves_loaded_runtime(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """Runtime data and listeners survive when the platform cannot unload."""
    entry = _add_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data

    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ):
        assert not await hass.config_entries.async_unload(entry.entry_id)

    assert entry.runtime_data is coordinator
    assert len(entry.update_listeners) == 1


async def test_unload_preserves_storage_remove_deletes_only_own_storage(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant, hass_storage
) -> None:
    """Reload persistence and removal are isolated between config entries."""
    entries = []
    for base_temp in (18.0, 16.0):
        entry = _add_entry(hass, base_temperature=base_temp)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entry.runtime_data.daily_hdd_values[date(2026, 10, 1)] = 2.0
        await entry.runtime_data.async_save_data()
        entries.append(entry)

    removed, kept = entries
    removed_key = f"{DOMAIN}_data_{removed.entry_id}"
    kept_key = f"{DOMAIN}_data_{kept.entry_id}"
    assert removed_key in hass_storage
    assert kept_key in hass_storage

    assert await hass.config_entries.async_unload(removed.entry_id)
    assert not hasattr(removed, "runtime_data")
    assert not removed.update_listeners
    assert removed_key in hass_storage

    await hass.config_entries.async_remove(removed.entry_id)
    await hass.async_block_till_done()
    assert removed_key not in hass_storage
    assert kept_key in hass_storage
    assert kept.state is ConfigEntryState.LOADED
    assert kept.runtime_data.daily_hdd_values[date(2026, 10, 1)] == 2.0


async def test_cleanup_preserves_unmanaged_and_other_entry_entities(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """Disabling historical sensors does not delete future forecast/foreign keys."""
    entry = _add_entry(hass, include_monthly=False)
    other = _add_entry(hass, base_temperature=16.0)
    registry = er.async_get(hass)
    preserved = [
        registry.async_get_or_create(
            "sensor", DOMAIN, f"{entry.entry_id}_hdd_forecast", config_entry=entry
        ),
        registry.async_get_or_create(
            "sensor", DOMAIN, "legacy_unknown_key", config_entry=entry
        ),
        registry.async_get_or_create(
            "binary_sensor", DOMAIN, f"{entry.entry_id}_hdd_monthly", config_entry=entry
        ),
        registry.async_get_or_create(
            "sensor",
            "other_platform",
            f"{entry.entry_id}_hdd_monthly",
            config_entry=entry,
        ),
        registry.async_get_or_create(
            "sensor", DOMAIN, f"{other.entry_id}_hdd_monthly", config_entry=other
        ),
    ]
    disabled = registry.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_hdd_monthly", config_entry=entry
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(disabled.entity_id) is None
    assert all(registry.async_get(entity.entity_id) is not None for entity in preserved)


async def test_reconfigure_recovers_entry_waiting_for_retry(
    recorder_mock, enable_custom_integrations, hass: HomeAssistant
) -> None:
    """Entries without an active listener still reload after reconfiguration."""
    entry = _add_entry(hass)
    with patch(
        "custom_components.heating_cooling_degree_days.coordinator."
        "HDDDataUpdateCoordinator.async_config_entry_first_refresh",
        side_effect=ConfigEntryNotReady("History unavailable"),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY

    with patch.object(
        hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload
    ) as reload:
        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {k: v for k, v in ENTRY_DATA.items() if k != "temperature_unit"},
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    reload.assert_awaited_once_with(entry.entry_id)
    assert entry.state is ConfigEntryState.LOADED
    assert len(entry.update_listeners) == 1


@pytest.mark.parametrize(
    ("cooling", "weekly", "monthly", "expected_types"),
    [
        (False, False, False, {"hdd_daily"}),
        (True, False, False, {"hdd_daily", "cdd_daily"}),
        (True, True, False, {"hdd_daily", "hdd_weekly", "cdd_daily", "cdd_weekly"}),
    ],
)
async def test_reconfigure_sensor_options_match_registry_and_active_entities(
    recorder_mock,
    enable_custom_integrations,
    hass: HomeAssistant,
    *,
    cooling,
    weekly,
    monthly,
    expected_types,
) -> None:
    """Creation and cleanup agree when options remove previously loaded sensors."""
    entry = _add_entry(hass, include_cooling=True)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **{k: v for k, v in ENTRY_DATA.items() if k != "temperature_unit"},
            "include_cooling": cooling,
            "include_weekly": weekly,
            "include_monthly": monthly,
        },
    )
    await hass.async_block_till_done()

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert {entity.unique_id for entity in entities} == {
        f"{entry.entry_id}_{sensor_type}" for sensor_type in expected_types
    }
    assert all(hass.data["sensor"].get_entity(entity.entity_id) for entity in entities)
