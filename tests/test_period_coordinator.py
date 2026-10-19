"""Persistent backfill, migration, atomic snapshots and calendar lifecycle."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    DOMAIN,
)
from custom_components.heating_cooling_degree_days.coordinator import (
    MAX_BACKFILL_DAYS,
    STORAGE_KEY,
    HDDDataUpdateCoordinator,
)
from custom_components.heating_cooling_degree_days.degree_days import TemperatureSample
from custom_components.heating_cooling_degree_days.history import TemperatureHistory
from custom_components.heating_cooling_degree_days.periods import DailyRecord
from custom_components.heating_cooling_degree_days.sensor import DegreeDegreeSensor
from homeassistant.components.recorder import get_instance
from homeassistant.components.sensor import SensorStateClass
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

pytestmark = [pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations")]
HISTORY = (
    "custom_components.heating_cooling_degree_days.coordinator.get_temperature_history"
)


def make_coordinator(hass, **kwargs):
    """Use UTC and an unpurged recorder unless a test specifies retention."""
    dt_util.set_default_time_zone(UTC)
    get_instance(hass).auto_purge = False
    return HDDDataUpdateCoordinator(
        hass, "sensor.outdoor", 18, "°C", "test-entry", **kwargs
    )


async def full_day(_hass, start, _end, _entity, _unit):
    """Provide a constant day whose integral is eight HDD."""
    return TemperatureHistory((TemperatureSample(start, 10),), None, 0)


@pytest.mark.freeze_time("2026-06-21 12:00:00+00:00")
async def test_bounded_midmonth_backfill_persists_and_resumes(hass):
    """A fresh midmonth install fills in batches; restart never re-queries full days."""
    coordinator = make_coordinator(hass, include_cooling=True)
    with patch(HISTORY, side_effect=full_day) as history:
        await coordinator.async_refresh()
        assert history.await_count == MAX_BACKFILL_DAYS
        assert history.await_args_list[0].args[1].date() == date(2026, 6, 20)
        assert coordinator.data["hdd_monthly"] == 56
        assert coordinator.period_attributes["hdd_monthly"]["missing_days"] == 13
        assert coordinator.period_attributes["hdd_monthly"]["coverage"] == 7 / 20
        resumed = make_coordinator(hass, include_cooling=True)
        await resumed.async_load_stored_data()
        await resumed.async_refresh()
        assert history.await_count == 14
        await resumed.async_refresh()
        assert history.await_count == 20
        assert resumed.data["hdd_monthly"] == 160
        assert resumed.data["hdd_weekly"] == 48
        assert resumed.data["cdd_monthly"] == 0
        assert resumed.period_attributes["hdd_monthly"]["coverage"] == 1
        await resumed.async_refresh()
        assert history.await_count == 20
        dates = [call.args[1].date() for call in history.await_args_list]
        assert len(set(dates)) == 20


@pytest.mark.freeze_time("2026-06-21 12:00:00+00:00")
async def test_retention_leaves_expired_days_explicitly_missing(hass):
    """Do not query dates wholly outside automatic recorder retention."""
    coordinator = make_coordinator(hass)
    recorder = get_instance(hass)
    recorder.auto_purge = True
    recorder.keep_days = 3
    with patch(HISTORY, side_effect=full_day) as history:
        await coordinator.async_refresh()
    assert {call.args[1].date() for call in history.await_args_list} == {
        date(2026, 6, 18),
        date(2026, 6, 19),
        date(2026, 6, 20),
    }
    attrs = coordinator.period_attributes["hdd_monthly"]
    assert attrs["missing_days"] == 17
    assert attrs["partial"] is True


@pytest.mark.freeze_time("2026-06-03 00:01:00+00:00")
async def test_partial_retry_survives_restart_and_never_loses_coverage(hass, freezer):
    """Retry after cooldown, preserve better observations after purge, then finalize."""
    coordinator = make_coordinator(hass, include_weekly=False, include_monthly=False)
    start = datetime(2026, 6, 2, tzinfo=UTC)
    partial = TemperatureHistory(
        (TemperatureSample(start + timedelta(hours=12), 10),), None, 0
    )
    with patch(HISTORY, return_value=partial) as history:
        await coordinator.async_refresh()
        assert coordinator.data["hdd_daily"] == 4
        await coordinator.async_refresh()
        assert history.await_count == 1
        coordinator = make_coordinator(
            hass, include_weekly=False, include_monthly=False
        )
        await coordinator.async_load_stored_data()
        await coordinator.async_refresh()
        assert history.await_count == 1
    freezer.move_to("2026-06-03 06:01:00+00:00")
    with patch(HISTORY, return_value=TemperatureHistory((), None, 0)):
        await coordinator.async_refresh()
    assert coordinator.data["hdd_daily"] == 4
    assert coordinator.period_attributes["hdd_daily"]["coverage"] == 0.5
    freezer.move_to("2026-06-03 12:01:00+00:00")
    with patch(HISTORY, side_effect=full_day) as history:
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert history.await_count == 1
    assert coordinator.data["hdd_daily"] == 8
    assert coordinator.period_attributes["hdd_daily"]["coverage"] == 1


@pytest.mark.freeze_time("2026-06-21 12:00:00+00:00")
async def test_failure_during_backfill_keeps_previous_values_and_labels(hass, freezer):
    """A failed later query cannot publish partially committed metadata or values."""
    coordinator = make_coordinator(hass)
    with patch(HISTORY, side_effect=full_day):
        await coordinator.async_refresh()
    before = (
        coordinator.data.copy(),
        coordinator.period_attributes.copy(),
        coordinator.ledger.copy(),
    )
    freezer.move_to("2026-06-22 00:00:05+00:00")
    with patch(
        HISTORY,
        side_effect=[
            await full_day(None, dt_util.now() - timedelta(days=1), None, None, None),
            UpdateFailed("recorder failed"),
        ],
    ):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert (
        coordinator.data,
        coordinator.period_attributes,
        coordinator.ledger,
    ) == before
    sensor = DegreeDegreeSensor(
        coordinator, MockConfigEntry(domain=DOMAIN), "hdd_weekly"
    )
    assert not sensor.available
    assert sensor.extra_state_attributes["period_start"] == "2026-06-15"


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
@pytest.mark.parametrize("legacy_key", ["daily_values", "daily_hdd_values"])
async def test_scalar_store_migration_preserves_values_and_flags_unknown_coverage(
    hass, hass_storage, legacy_key
):
    """Both v1 formats retain their legacy values when recorder has no coverage."""
    coordinator = make_coordinator(hass, include_cooling=True)
    key = f"{STORAGE_KEY}_test-entry"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {
            legacy_key: {"2026-06-01": 4.2345, "2026-06-02": 5},
            "daily_cdd_values": {"2026-06-02": 1},
        },
    }
    await coordinator.async_load_stored_data()
    with patch(HISTORY, return_value=TemperatureHistory((), None, 0)) as history:
        await coordinator.async_refresh()
    assert history.await_count == 2
    assert coordinator.data["hdd_monthly"] == 9.2345
    assert coordinator.period_attributes["hdd_monthly"]["coverage"] == 1
    assert coordinator.period_attributes["hdd_monthly"]["legacy_days"] == 2
    assert coordinator.period_attributes["cdd_monthly"]["coverage"] == 0.5
    assert hass_storage[key]["version"] == 2
    assert hass_storage[key]["data"]["days"]["2026-06-01"]["coverage_seconds"] is None


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
@pytest.mark.parametrize(
    ("field", "value"),
    [("base_temp", 16), ("temp_entity", "sensor.other"), ("temperature_unit", "°F")],
)
async def test_fingerprint_change_rebuilds_available_history(hass, field, value):
    """Changing any calculation input discards every old record before backfill."""
    coordinator = make_coordinator(hass)
    with patch(HISTORY, side_effect=full_day):
        await coordinator.async_refresh()
    reconfigured = make_coordinator(hass)
    setattr(reconfigured, field, value)
    await reconfigured.async_load_stored_data()
    assert reconfigured.ledger == {}
    with patch(HISTORY, side_effect=full_day) as history:
        await reconfigured.async_refresh()
    assert history.await_count == 2
    assert len(reconfigured.ledger) == 2


@pytest.mark.parametrize(
    ("sensor_type", "expected"),
    [
        ("hdd_daily", None),
        ("cdd_daily", None),
        ("hdd_weekly", SensorStateClass.TOTAL_INCREASING),
        ("hdd_monthly", SensorStateClass.TOTAL_INCREASING),
        ("cdd_weekly", SensorStateClass.TOTAL_INCREASING),
        ("cdd_monthly", SensorStateClass.TOTAL_INCREASING),
    ],
)
async def test_statistics_class_preserves_unique_ids(hass, sensor_type, expected):
    """Only accumulating calendar sensors have a statistics state class."""
    entry = MockConfigEntry(domain=DOMAIN)
    sensor = DegreeDegreeSensor(make_coordinator(hass), entry, sensor_type)
    assert sensor.state_class == expected
    assert sensor.unique_id == f"{entry.entry_id}_{sensor_type}"


async def test_midnight_listener_requests_refresh_and_is_cancelled_on_unload(hass):
    """Register local midnight once and release it through the config entry lifecycle."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Test",
        data={
            CONF_TEMPERATURE_SENSOR: "sensor.outdoor",
            CONF_BASE_TEMPERATURE: 18,
            CONF_TEMPERATURE_UNIT: "°C",
            CONF_INCLUDE_WEEKLY: True,
            CONF_INCLUDE_MONTHLY: True,
        },
    )
    entry.add_to_hass(hass)
    cancel = Mock()
    with patch(
        "custom_components.heating_cooling_degree_days.async_track_time_change",
        return_value=cancel,
    ) as track:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert track.call_args.kwargs == {"hour": 0, "minute": 0, "second": 5}
    coordinator = entry.runtime_data
    with patch.object(
        coordinator, "async_request_refresh", new_callable=AsyncMock
    ) as refresh:
        await track.call_args.args[1](dt_util.now())
        refresh.assert_awaited_once()
    assert await hass.config_entries.async_unload(entry.entry_id)
    cancel.assert_called_once_with()


@pytest.mark.freeze_time("2026-06-03 00:01:00+00:00")
async def test_retry_cannot_reduce_accumulating_total_even_with_more_coverage(
    hass, freezer
):
    """A shifted retained interval can cover more time yet lose previously counted HDD."""
    coordinator = make_coordinator(hass, include_cooling=True)
    start = datetime(2026, 6, 2, tzinfo=UTC)
    first = TemperatureHistory(
        (
            TemperatureSample(start, 10),
            TemperatureSample(start + timedelta(hours=12), None),
        ),
        None,
        0,
    )
    with patch(HISTORY, return_value=first):
        await coordinator.async_refresh()
    before = coordinator.data.copy(), coordinator.period_attributes.copy()
    freezer.move_to("2026-06-03 06:01:00+00:00")
    shifted = TemperatureHistory(
        (TemperatureSample(start + timedelta(hours=6), 17),), None, 0
    )
    with patch(HISTORY, return_value=shifted):
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert (coordinator.data, coordinator.period_attributes) == before
    assert coordinator.data["hdd_daily"] == 4
    assert coordinator.period_attributes["hdd_daily"]["coverage"] == 0.5


@pytest.mark.freeze_time("2026-06-05 12:00:00+00:00")
async def test_downtime_backfills_missed_days_and_snapshot_stays_coherent(
    hass, freezer
):
    """A restart after three offline days catches up without re-reading cached dates."""
    coordinator = make_coordinator(hass)
    with patch(HISTORY, side_effect=full_day) as history:
        await coordinator.async_refresh()
    assert history.await_count == 4
    freezer.move_to("2026-06-08 00:00:05+00:00")
    sensor = DegreeDegreeSensor(
        coordinator, MockConfigEntry(domain=DOMAIN), "hdd_weekly"
    )
    assert sensor.extra_state_attributes["period_start"] == "2026-06-01"
    assert sensor.native_value == 32
    resumed = make_coordinator(hass)
    await resumed.async_load_stored_data()
    with patch(HISTORY, side_effect=full_day) as history:
        await resumed.async_refresh()
    assert {call.args[1].date() for call in history.await_args_list} == {
        date(2026, 6, n) for n in (5, 6, 7)
    }
    assert resumed.data["hdd_daily"] == 8
    assert resumed.data["hdd_weekly"] == 0
    assert resumed.data["hdd_monthly"] == 56
    assert resumed.period_attributes["hdd_weekly"]["period_start"] == "2026-06-08"
    assert resumed.period_attributes["hdd_weekly"]["coverage"] == 1


@pytest.mark.freeze_time("2026-06-03 12:00:00+00:00")
async def test_failed_save_does_not_publish_unsaved_totals(hass):
    """Storage errors retain the last successful value/coverage snapshot."""
    coordinator = make_coordinator(hass)
    with (
        patch(HISTORY, side_effect=full_day),
        patch.object(
            coordinator._store, "async_save", side_effect=OSError("disk full")
        ),
    ):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.ledger == {}
    assert coordinator.period_attributes == {}
    assert coordinator.data is None


@pytest.mark.freeze_time("2026-06-21 12:00:00+00:00")
async def test_legacy_full_days_correct_once_in_bounded_batches_and_survive_restart(
    hass,
):
    """Full recorder days replace inflated legacy totals once, across restarts."""
    coordinator = make_coordinator(hass, include_cooling=True)
    coordinator.ledger = {
        date(2026, 6, day): DailyRecord(12, 3, None, 86400, None, legacy=True)
        for day in range(1, 21)
    }
    await coordinator._save_ledger(coordinator.ledger)
    with patch(HISTORY, side_effect=full_day) as history:
        await coordinator.async_refresh()
        assert history.await_count == MAX_BACKFILL_DAYS
        assert coordinator.data["hdd_monthly"] == 13 * 12 + 7 * 8
        assert coordinator.data["cdd_monthly"] == 13 * 3
        assert coordinator.period_attributes["hdd_monthly"]["legacy_days"] == 13
        assert coordinator.ledger[date(2026, 6, 20)].mean_temp == 10
        resumed = make_coordinator(hass, include_cooling=True)
        await resumed.async_load_stored_data()
        await resumed.async_refresh()
        assert history.await_count == 14
        await resumed.async_refresh()
        assert history.await_count == 20
        assert resumed.data["hdd_monthly"] == 160
        assert resumed.data["cdd_monthly"] == 0
        assert resumed.period_attributes["hdd_monthly"]["legacy_days"] == 0
        assert all(
            record.complete and not record.legacy for record in resumed.ledger.values()
        )
        await resumed.async_refresh()
        assert history.await_count == 20
        assert len({call.args[1].date() for call in history.await_args_list}) == 20


@pytest.mark.freeze_time("2026-06-03 00:01:00+00:00")
@pytest.mark.parametrize(
    "samples", [(), (TemperatureSample(datetime(2026, 6, 2, 12, tzinfo=UTC), 10),)]
)
async def test_legacy_partial_or_empty_history_retains_value_until_full_day(
    hass, freezer, samples
):
    """Incomplete history never replaces legacy totals; full history can correct downward."""
    coordinator = make_coordinator(
        hass, include_cooling=True, include_weekly=False, include_monthly=False
    )
    day = date(2026, 6, 2)
    coordinator.ledger[day] = DailyRecord(12, 3, None, 86400, None, legacy=True)
    with patch(HISTORY, return_value=TemperatureHistory(samples, None, 0)) as history:
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        assert history.await_count == 1
        assert coordinator.ledger[day].legacy
        assert coordinator.data["hdd_daily"] == 12
        assert coordinator.data["cdd_daily"] == 3
        assert coordinator.ledger[day].coverage_seconds is None
    freezer.move_to("2026-06-03 06:01:00+00:00")
    with patch(HISTORY, side_effect=full_day) as history:
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        assert history.await_count == 1
    assert coordinator.data["hdd_daily"] == 8
    assert coordinator.data["cdd_daily"] == 0
    assert coordinator.ledger[day].coverage_seconds == 86400
    assert not coordinator.ledger[day].legacy


@pytest.mark.freeze_time("2026-06-04 12:00:00+00:00")
async def test_legacy_probes_actual_history_once_outside_retention(hass, freezer):
    """Nominal retention does not discard recoverable legacy days or retry purged ones."""
    coordinator = make_coordinator(hass)
    recorder = get_instance(hass)
    recorder.auto_purge = True
    recorder.keep_days = 1
    coordinator.ledger = {
        date(2026, 6, day): DailyRecord(12, None, None, 86400, None, legacy=True)
        for day in (1, 2, 3)
    }

    async def retained(_hass, start, end, entity, unit):
        if start.day == 1:
            return TemperatureHistory((), None, 0)
        return await full_day(_hass, start, end, entity, unit)

    with patch(HISTORY, side_effect=retained) as history:
        await coordinator.async_refresh()
        assert history.await_count == 3
        assert coordinator.data["hdd_monthly"] == 28
        assert coordinator.ledger[date(2026, 6, 1)].legacy
        assert not coordinator.ledger[date(2026, 6, 2)].legacy
        freezer.move_to("2026-06-05 12:00:00+00:00")
        resumed = make_coordinator(hass)
        recorder.auto_purge = True
        recorder.keep_days = 1
        await resumed.async_load_stored_data()
        await resumed.async_refresh()
        assert history.await_count == 4  # Only the newly completed June 4 is queried.
