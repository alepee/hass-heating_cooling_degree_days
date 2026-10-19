"""Diagnostics redact identities and expose bounded, truthful calculation status."""

from datetime import UTC, date, datetime, timedelta
import json
from unittest.mock import patch

from aiohttp.resolver import ThreadedResolver
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import DOMAIN
from custom_components.heating_cooling_degree_days.coordinator import (
    HDDDataUpdateCoordinator,
)
from custom_components.heating_cooling_degree_days.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.heating_cooling_degree_days.history import TemperatureHistory
from custom_components.heating_cooling_degree_days.periods import DailyRecord
from homeassistant.components.diagnostics import REDACTED
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

pytestmark = [pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations")]
HISTORY = (
    "custom_components.heating_cooling_degree_days.coordinator.get_temperature_history"
)


@pytest.fixture
def diagnostic_entry(hass):
    """Create an entry with personally identifying source/title and nested options."""
    dt_util.set_default_time_zone(UTC)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Private garden at Alice's home",
        data={
            "temperature_sensor": "sensor.alice_private_garden",
            "temperature_sensor_registry_id": "private-registry-identity",
            "base_temperature": 18,
            "temperature_unit": "°C",
            "include_cooling": True,
            "include_weekly": False,
            "include_monthly": True,
        },
        options={"nested": [{"entity_id": "sensor.bobs_private_room", "name": "Bob"}]},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = HDDDataUpdateCoordinator(
        hass, entry.data["temperature_sensor"], 18, "°C", entry.entry_id
    )
    return entry


@pytest.mark.freeze_time("2026-06-21 12:00:00+00:00")
async def test_redacted_bounded_summary_does_not_read_history(hass, diagnostic_entry):
    """Retain coverage and snapshot data, excluding identities and raw observations."""
    entry = diagnostic_entry
    coordinator = entry.runtime_data
    coordinator.ledger = {
        date(2026, 6, 21) - timedelta(days=n): DailyRecord(
            123456.789, 0, 43200, 86400, 12345, legacy=n == 2
        )
        for n in range(1, 42)
    }
    coordinator.data = {"hdd_monthly": 12.3}
    coordinator.period_attributes = {"hdd_monthly": {"coverage": 0.5, "partial": True}}
    hass.states.async_set(
        entry.data["temperature_sensor"],
        "17.394586",
        {"unit_of_measurement": "°C", "friendly_name": "Secret address"},
    )
    with patch(HISTORY) as history:
        data = await async_get_config_entry_diagnostics(hass, entry)
    history.assert_not_called()
    serialized = json.dumps(data)
    for secret in (
        entry.title,
        entry.data["temperature_sensor"],
        entry.data["temperature_sensor_registry_id"],
        "sensor.bobs_private_room",
        "Bob",
        "Secret address",
        "17.394586",
        "123456.789",
        "12345",
    ):
        assert secret not in serialized
    assert data["entry"]["title"] == REDACTED
    assert data["entry"]["data"]["temperature_sensor"] == REDACTED
    assert data["entry"]["options"]["nested"][0]["entity_id"] == REDACTED
    assert entry.options["nested"][0]["name"] == "Bob"
    assert data["calculation"]["enabled_sensor_types"] == [
        "hdd_daily",
        "hdd_monthly",
        "cdd_daily",
        "cdd_monthly",
    ]
    assert data["source"] == {"unit": "°C", "availability": "available"}
    assert data["ledger"]["storage_version"] == 2
    assert data["ledger"]["days_count"] == 41
    assert len(data["ledger"]["days"]) == 35
    assert data["ledger"]["days"]["2026-06-19"]["legacy"] is True
    assert data["periods"]["hdd_monthly"] == {
        "value": 12.3,
        "attributes": {"coverage": 0.5, "partial": True},
    }
    data["periods"]["hdd_monthly"]["attributes"]["coverage"] = 0
    assert coordinator.period_attributes["hdd_monthly"]["coverage"] == 0.5
    assert data["versions"]["home_assistant"]
    assert data["versions"]["integration"]
    assert data["refresh"] == {"last_update_success": None, "last_attempt": None}


@pytest.mark.parametrize(
    ("state", "availability"),
    [
        (None, "missing"),
        ("unknown", "unknown"),
        ("unavailable", "unavailable"),
        ("nan", "invalid"),
        ("private text", "invalid"),
    ],
)
async def test_source_availability_without_raw_state(
    hass, diagnostic_entry, state, availability
):
    """Absent and invalid current readings remain distinguishable without disclosure."""
    if state is not None:
        hass.states.async_set(
            diagnostic_entry.data["temperature_sensor"],
            state,
            {"unit_of_measurement": "Private unit label"},
        )
    data = await async_get_config_entry_diagnostics(hass, diagnostic_entry)
    assert data["source"] == {"unit": None, "availability": availability}


@pytest.mark.freeze_time("2026-06-21 12:00:00+00:00")
async def test_refresh_attempt_time_and_failure_are_real(
    hass, diagnostic_entry, freezer
):
    """A failed refresh advances the attempt timestamp while retaining old snapshots."""
    coordinator = diagnostic_entry.runtime_data
    with patch(HISTORY, return_value=TemperatureHistory((), None, 0)):
        await coordinator.async_refresh()
    data = await async_get_config_entry_diagnostics(hass, diagnostic_entry)
    assert data["refresh"] == {
        "last_update_success": True,
        "last_attempt": "2026-06-21T12:00:00+00:00",
    }
    previous = data["periods"]
    freezer.move_to("2026-06-22 12:00:00+00:00")
    with patch(HISTORY, side_effect=UpdateFailed("sensitive source detail")):
        await coordinator.async_refresh()
    data = await async_get_config_entry_diagnostics(hass, diagnostic_entry)
    assert data["refresh"] == {
        "last_update_success": False,
        "last_attempt": "2026-06-22T12:00:00+00:00",
    }
    assert data["periods"] == previous
    assert "sensitive source detail" not in json.dumps(data)


async def test_unloaded_entry_has_configuration_but_no_fabricated_runtime(
    hass, diagnostic_entry
):
    """Diagnostics remain useful for an unloaded or failed setup entry."""
    del diagnostic_entry.runtime_data
    data = await async_get_config_entry_diagnostics(hass, diagnostic_entry)
    assert data["ledger"] is None
    assert data["periods"] == {}
    assert data["refresh"]["last_update_success"] is None
    assert data["entry"]["title"] == REDACTED


async def test_unknown_legacy_coverage_and_last_attempt(hass, diagnostic_entry):
    """Legacy unknown coverage is not relabeled as measured full coverage."""
    day = dt_util.now().date() - timedelta(days=1)
    attempted = datetime(2026, 1, 1, tzinfo=UTC)
    diagnostic_entry.runtime_data.ledger[day] = DailyRecord(
        4, None, None, 86400, None, attempted.timestamp(), legacy=True
    )
    data = await async_get_config_entry_diagnostics(hass, diagnostic_entry)
    record = data["ledger"]["days"][str(day)]
    assert record["coverage"] is None
    assert record["coverage_seconds"] is None
    assert record["legacy"] and not record["complete"]
    assert record["last_attempt"] == attempted.isoformat()


# The local HTTP test needs no DNS; avoid pycares global shutdown threads on HA 2025.1.
@patch("aiohttp.connector.DefaultResolver", ThreadedResolver)
async def test_diagnostics_download_via_home_assistant(
    hass, hass_client, diagnostic_entry
):
    """The actual diagnostics endpoint discovers the integration's implementation."""
    entry = diagnostic_entry
    with patch(HISTORY, return_value=TemperatureHistory((), None, 0)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert await async_setup_component(hass, "diagnostics", {})
    await hass.async_block_till_done()
    client = await hass_client()
    response = await client.get(f"/api/diagnostics/config_entry/{entry.entry_id}")
    assert response.status == 200
    data = (await response.json())["data"]
    assert data["entry"]["title"] == REDACTED
    assert data["refresh"]["last_update_success"] is True
    assert await hass.config_entries.async_unload(entry.entry_id)
