"""Source identity, repair lifecycle, and recorder rename regression tests."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import DOMAIN
from custom_components.heating_cooling_degree_days.degree_days import (
    TemperatureSample,
    integrate_degree_days,
)
from custom_components.heating_cooling_degree_days.history import (
    TemperatureHistory,
    get_temperature_history,
)
from custom_components.heating_cooling_degree_days.source import CONF_SOURCE_REGISTRY_ID
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

pytestmark = [pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations")]
HISTORY = (
    "custom_components.heating_cooling_degree_days.coordinator.get_temperature_history"
)
ATTRS = {"device_class": "temperature", "unit_of_measurement": "°C"}


@pytest.fixture(autouse=True)
def running_hass(hass):
    """Existing source lifecycle tests model reloads of an already running HA."""
    hass.state = CoreState.running


def add_source(hass, name="outside"):
    """Register a temperature source and its current state."""
    entity = er.async_get(hass).async_get_or_create("sensor", "test", name)
    hass.states.async_set(entity.entity_id, "10", ATTRS)
    return entity


def add_entry(hass, entity_id, **extra):
    """Configure a per-entry source, independent of the current system units."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Heating Degree Days (18.0°C)",
        data={
            "temperature_sensor": entity_id,
            "base_temperature": 18,
            "temperature_unit": "°C",
            "include_cooling": False,
            "include_weekly": True,
            "include_monthly": True,
            **extra,
        },
    )
    entry.add_to_hass(hass)
    return entry


def issue(hass, entry):
    """Find the repair belonging to exactly one entry."""
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"missing_source_{entry.entry_id}"
    )


async def full_day(_hass, start, _end, _entity, _unit):
    """Provide a recorded full day with eight HDD."""
    return TemperatureHistory((TemperatureSample(start, 10),), None, 0)


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_rename_keeps_ledger_and_entity_ids_with_one_reload(hass, hass_storage):
    """Renaming updates configuration, while storage and output identity survive."""
    dt_util.set_default_time_zone(UTC)
    source = add_source(hass)
    entry = add_entry(hass, source.entity_id)
    with patch(HISTORY, side_effect=full_day) as history:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        ledger = dict(entry.runtime_data.ledger)
        registry = er.async_get(hass)
        output_ids = {
            entity.entity_id
            for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        with patch.object(
            hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload
        ) as reload:
            registry.async_update_entity(
                source.entity_id, new_entity_id="sensor.renamed"
            )
            hass.states.async_remove(source.entity_id)
            hass.states.async_set("sensor.renamed", "10", ATTRS)
            await hass.async_block_till_done(wait_background_tasks=True)
        reload.assert_awaited_once_with(entry.entry_id)
        assert history.await_count == 2  # Completed dates are not queried again.
    assert entry.data["temperature_sensor"] == "sensor.renamed"
    assert entry.data[CONF_SOURCE_REGISTRY_ID] == source.id
    assert entry.runtime_data.ledger == ledger
    assert entry.runtime_data.temp_entity == "sensor.renamed"
    assert issue(hass, entry) is None
    assert output_ids == {
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    stored = hass_storage[f"{DOMAIN}_data_{entry.entry_id}"]["data"]
    assert stored["config"][CONF_SOURCE_REGISTRY_ID] == source.id
    assert "temperature_sensor" not in stored["config"]


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_missing_source_retains_values_and_restoration_clears_repair(
    hass, freezer
):
    """Missing sources cannot extrapolate stale data or affect another entry."""
    dt_util.set_default_time_zone(UTC)
    source, other_source = add_source(hass), add_source(hass, "other")
    entry, other = (
        add_entry(hass, source.entity_id),
        add_entry(hass, other_source.entity_id),
    )
    with patch(HISTORY, side_effect=full_day) as history:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        before = dict(entry.runtime_data.data)
        er.async_get(hass).async_remove(source.entity_id)
        hass.states.async_remove(source.entity_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, entry).translation_key == "missing_source"
        assert issue(hass, other) is None
        history.reset_mock()
        await entry.runtime_data.async_refresh()
        history.assert_not_awaited()
        assert entry.runtime_data.data == before
        assert entry.runtime_data.last_update_success
        freezer.move_to("2026-06-04 12:00:00+00:00")
        await entry.runtime_data.async_refresh()
        assert entry.runtime_data.data["hdd_daily"] is None
        assert entry.runtime_data.data["hdd_monthly"] == 16
        attrs = entry.runtime_data.period_attributes["hdd_monthly"]
        assert attrs["coverage"] == 2 / 3
        assert attrs["partial"] and attrs["source_missing"]
        assert attrs["missing_days"] == 1
        restored = add_source(hass)
        assert restored.id == source.id
        await hass.async_block_till_done(wait_background_tasks=True)
        await entry.runtime_data.async_refresh()
        assert issue(hass, entry) is None
        assert entry.runtime_data.data["hdd_daily"] == 8
        assert not entry.runtime_data.period_attributes["hdd_monthly"]["source_missing"]


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_missing_at_setup_reconfigure_and_remove_clear_issue(hass):
    """Setup succeeds without a source; repair, reconfigure, and removal are scoped."""
    entry = add_entry(hass, "sensor.missing")
    other = add_entry(hass, "sensor.also_missing")
    with patch(HISTORY, side_effect=full_day) as history:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        history.assert_not_awaited()
        assert issue(hass, entry) is not None
        assert issue(hass, other) is not None
        assert entry.runtime_data.data["hdd_daily"] is None
        assert entry.runtime_data.last_update_success
        source = add_source(hass)
        flow = await entry.start_reconfigure_flow(hass)
        await hass.config_entries.flow.async_configure(
            flow["flow_id"],
            {
                **{k: v for k, v in entry.data.items() if k != "temperature_unit"},
                "temperature_sensor": source.entity_id,
            },
        )
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, entry) is None
        assert issue(hass, other) is not None
        await hass.config_entries.async_remove(other.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, other) is None


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_unload_removes_listeners_and_reload_resolves_offline_rename(hass):
    """No unloaded-entry listener fires; stable identity resolves renames at setup."""
    source = add_source(hass)
    entry = add_entry(hass, source.entity_id)
    with patch(HISTORY, side_effect=full_day):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        ledger = dict(entry.runtime_data.ledger)
        assert await hass.config_entries.async_unload(entry.entry_id)
        with patch.object(hass.config_entries, "async_reload") as reload:
            er.async_get(hass).async_update_entity(
                source.entity_id, new_entity_id="sensor.new"
            )
            hass.states.async_remove(source.entity_id)
            hass.states.async_set("sensor.new", "10", ATTRS)
            await hass.async_block_till_done(wait_background_tasks=True)
            reload.assert_not_called()
        assert entry.data["temperature_sensor"] == source.entity_id
        assert issue(hass, entry) is None
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.data["temperature_sensor"] == "sensor.new"
        assert entry.runtime_data.ledger == ledger


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_legacy_fingerprint_is_migrated_before_rename(hass, hass_storage):
    """Existing raw entity-ID fingerprints retain days when identity is learned."""
    dt_util.set_default_time_zone(UTC)
    source = add_source(hass)
    entry = add_entry(hass, source.entity_id)
    key = f"{DOMAIN}_data_{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            "config": {
                k: entry.data[k]
                for k in ("temperature_sensor", "base_temperature", "temperature_unit")
            },
            "daily_hdd_values": {"2026-06-02": 12.5},
        },
    }
    with patch(HISTORY, return_value=TemperatureHistory((), None, 0)):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.runtime_data.ledger[date(2026, 6, 2)].hdd == 12.5
        er.async_get(hass).async_update_entity(
            source.entity_id, new_entity_id="sensor.new"
        )
        hass.states.async_set("sensor.new", "10", ATTRS)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.runtime_data.ledger[date(2026, 6, 2)].hdd == 12.5


@pytest.mark.freeze_time("2026-01-01 22:00:00+00:00")
async def test_recorder_rename_keeps_pre_rename_history(hass, recorder_mock, freezer):
    """Recorder renames states_meta so new-ID backfill includes old-ID samples."""
    source = add_source(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    await recorder_mock.async_block_till_done()
    start = datetime(2026, 1, 2, tzinfo=UTC)
    end = start + timedelta(days=1)
    freezer.move_to(end)
    er.async_get(hass).async_update_entity(
        source.entity_id, new_entity_id="sensor.renamed"
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    await recorder_mock.async_block_till_done()
    history = await get_temperature_history(hass, start, end, "sensor.renamed", "°C")
    result = integrate_degree_days(history.samples, start, end, 18)
    assert result.hdd == 8
    assert result.coverage_seconds == 86400
    old_history = await get_temperature_history(
        hass, start, end, source.entity_id, "°C"
    )
    assert not old_history.samples


@pytest.mark.freeze_time("2026-01-01 22:00:00+00:00")
async def test_recorder_restoration_preserves_removed_state_gap(
    hass, recorder_mock, freezer
):
    """Backfill after restoration must not bridge a recorded state removal."""
    source = add_source(hass)
    start = datetime(2026, 1, 2, tzinfo=UTC)
    end = start + timedelta(days=1)
    await hass.async_block_till_done(wait_background_tasks=True)
    await recorder_mock.async_block_till_done()
    freezer.move_to(start + timedelta(hours=12))
    hass.states.async_remove(source.entity_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    await recorder_mock.async_block_till_done()
    freezer.move_to(start + timedelta(hours=18))
    hass.states.async_set(source.entity_id, "10", ATTRS)
    await hass.async_block_till_done(wait_background_tasks=True)
    await recorder_mock.async_block_till_done()
    freezer.move_to(end)
    history = await get_temperature_history(hass, start, end, source.entity_id, "°C")
    result = integrate_degree_days(history.samples, start, end, 18)
    assert result.hdd == 6
    assert result.coverage_seconds == 18 * 3600


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_late_registry_identity_preserves_ledger_on_rename(hass):
    """A sensor registered after integration setup also retains its raw-ID ledger."""
    dt_util.set_default_time_zone(UTC)
    hass.states.async_set("sensor.late", "10", ATTRS)
    entry = add_entry(hass, "sensor.late")
    with patch(HISTORY, side_effect=full_day):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        ledger = dict(entry.runtime_data.ledger)
        registry = er.async_get(hass)
        hass.states.async_remove("sensor.late")
        source = registry.async_get_or_create(
            "sensor", "test", "late", suggested_object_id="late"
        )
        assert source.entity_id == "sensor.late"
        registry.async_update_entity(source.entity_id, new_entity_id="sensor.renamed")
        hass.states.async_remove(source.entity_id)
        hass.states.async_set("sensor.renamed", "10", ATTRS)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert entry.runtime_data.ledger == ledger
        assert entry.data[CONF_SOURCE_REGISTRY_ID] == source.id


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_different_registry_source_requires_reconfigure(hass):
    """Reusing a removed entity ID cannot silently attach a different physical source."""
    source = add_source(hass)
    entry = add_entry(hass, source.entity_id)
    with patch(HISTORY, side_effect=full_day):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        registry = er.async_get(hass)
        registry.async_remove(source.entity_id)
        hass.states.async_remove(source.entity_id)
        replacement = registry.async_get_or_create(
            "sensor",
            "replacement",
            "outside",
            suggested_object_id=source.entity_id.split(".", 1)[1],
        )
        hass.states.async_set(replacement.entity_id, "20", ATTRS)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert replacement.entity_id == source.entity_id
        assert issue(hass, entry) is not None
        with patch(
            "custom_components.heating_cooling_degree_days.config_flow.async_remove_stored_data"
        ) as remove:
            flow = await entry.start_reconfigure_flow(hass)
            await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {
                    key: value
                    for key, value in entry.data.items()
                    if key not in ("temperature_unit", CONF_SOURCE_REGISTRY_ID)
                },
            )
            await hass.async_block_till_done(wait_background_tasks=True)
            remove.assert_awaited_once_with(hass, entry.entry_id)
        assert entry.data[CONF_SOURCE_REGISTRY_ID] == replacement.id
        assert issue(hass, entry) is None


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_unload_cancels_pending_rename_commit(hass, recorder_mock):
    """Unloading cancels a rename waiting for recorder, before any late config write."""
    source = add_source(hass)
    entry = add_entry(hass, source.entity_id)
    with patch(HISTORY, side_effect=full_day):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def pending_commit():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with patch.object(
        recorder_mock, "async_block_till_done", side_effect=pending_commit
    ):
        er.async_get(hass).async_update_entity(
            source.entity_id, new_entity_id="sensor.new"
        )
        await started.wait()
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert cancelled.is_set()
    assert entry.data["temperature_sensor"] == source.entity_id


@pytest.mark.parametrize("registered", [True, False])
@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_startup_does_not_report_or_suspend_stateless_source(hass, registered):
    """Setup and refresh may use recorded days before the source platform loads."""
    hass.state = CoreState.starting
    dt_util.set_default_time_zone(UTC)
    entity_id = "sensor.late_source"
    if registered:
        source = er.async_get(hass).async_get_or_create("sensor", "test", "late_source")
        entity_id = source.entity_id
    entry = add_entry(hass, entity_id)
    with patch(HISTORY, side_effect=full_day) as history:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        coordinator = entry.runtime_data
        assert history.await_count == 2
        assert coordinator.data["hdd_monthly"] == 16
        assert coordinator.period_attributes["hdd_monthly"]["coverage"] == 1
        assert not coordinator.source_missing
        assert not coordinator.period_attributes["hdd_monthly"]["source_missing"]
        assert issue(hass, entry) is None
        await coordinator.async_refresh()
        assert issue(hass, entry) is None
        # A source appearing just before STARTED must not cause a transient repair.
        hass.states.async_set(entity_id, "10", ATTRS)
        hass.state = CoreState.running
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, entry) is None
        assert not coordinator.source_missing
        await coordinator.async_refresh()
        assert coordinator.data["hdd_monthly"] == 16
        assert coordinator.period_attributes["hdd_monthly"]["coverage"] == 1


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_missing_source_checked_at_start_and_cleared_on_return(hass):
    """An absent registry entry becomes actionable only after startup completes."""
    hass.state = CoreState.starting
    entry = add_entry(hass, "sensor.missing")
    with patch(HISTORY, side_effect=full_day):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, entry) is None
        hass.state = CoreState.running
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, entry) is not None
        assert entry.runtime_data.source_missing
        hass.states.async_set("sensor.missing", "10", ATTRS)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, entry) is None
        assert not entry.runtime_data.source_missing


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_registered_stateless_source_clears_stale_issue_without_new_repair(hass):
    """A registered source may load late without a repair or arbitrary grace timer."""
    hass.state = CoreState.starting
    source = er.async_get(hass).async_get_or_create("sensor", "test", "late_source")
    entry = add_entry(hass, source.entity_id)
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"missing_source_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="missing_source",
    )
    with patch(HISTORY, side_effect=full_day) as history:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        ledger = dict(entry.runtime_data.ledger)
        hass.state = CoreState.running
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, entry) is None
        assert entry.runtime_data.source_missing
        history.reset_mock()
        await entry.runtime_data.async_refresh()
        history.assert_not_awaited()
        assert entry.runtime_data.ledger == ledger
        assert issue(hass, entry) is None
        hass.states.async_set(source.entity_id, "10", ATTRS)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert issue(hass, entry) is None
        assert not entry.runtime_data.source_missing


async def test_unload_before_start_cancels_first_source_check(hass):
    """The STARTED callback must not create repairs after its entry is unloaded."""
    hass.state = CoreState.starting
    entry = add_entry(hass, "sensor.missing")
    with patch(HISTORY, side_effect=full_day):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.state = CoreState.running
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert issue(hass, entry) is None


async def test_already_running_stateless_registered_source_does_not_need_repair(hass):
    """An integration reload also distinguishes a known source from a deleted one."""
    source = er.async_get(hass).async_get_or_create("sensor", "test", "late_source")
    entry = add_entry(hass, source.entity_id)
    with patch(HISTORY, side_effect=full_day) as history:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        history.assert_not_awaited()
        assert entry.runtime_data.source_missing
        assert issue(hass, entry) is None


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
@pytest.mark.parametrize("previous_failure", [False, True])
async def test_source_status_is_published_immediately_without_waiting_for_backfill(
    hass,
    previous_failure,
):
    """Entity attributes follow a restored source even if refresh is debounced."""
    source = add_source(hass)
    entry = add_entry(hass, source.entity_id)
    with patch(HISTORY, side_effect=full_day):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    before = dict(coordinator.data)
    if previous_failure:
        coordinator.async_set_update_error(UpdateFailed("recorder unavailable"))
    with patch.object(coordinator, "async_request_refresh") as refresh:
        hass.states.async_remove(source.entity_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert coordinator.source_missing
        assert all(
            hass.data["sensor"]
            .get_entity(entity.entity_id)
            .extra_state_attributes["source_missing"]
            for entity in entities
        )
        hass.states.async_set(source.entity_id, "10", ATTRS)
        await hass.async_block_till_done(wait_background_tasks=True)
        refresh.assert_awaited_once()
        assert not coordinator.source_missing
        assert all(
            not attrs["source_missing"]
            for attrs in coordinator.period_attributes.values()
        )
        assert all(
            not hass.data["sensor"]
            .get_entity(entity.entity_id)
            .extra_state_attributes["source_missing"]
            for entity in entities
        )
        assert coordinator.data == before
        assert coordinator.last_update_success is not previous_failure
        for entity in entities:
            state = hass.states.get(entity.entity_id)
            if previous_failure:
                assert state.state == "unavailable"
            else:
                assert state.attributes["source_missing"] is False


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_refresh_repairs_stale_source_metadata_even_when_totals_unchanged(hass):
    """Every poll reconciles live availability, not only the state-change callback."""
    source = add_source(hass)
    entry = add_entry(hass, source.entity_id)
    with patch(HISTORY, side_effect=full_day):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    before = dict(coordinator.data)
    coordinator.source_missing = False
    coordinator.period_attributes = {
        key: {**attrs, "source_missing": True}
        for key, attrs in coordinator.period_attributes.items()
    }
    with patch(HISTORY) as history:
        await coordinator.async_refresh()
        history.assert_not_awaited()
    assert coordinator.last_update_success
    assert coordinator.data == before
    assert all(
        not attrs["source_missing"] for attrs in coordinator.period_attributes.values()
    )
    for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        assert not hass.states.get(entity.entity_id).attributes["source_missing"]
