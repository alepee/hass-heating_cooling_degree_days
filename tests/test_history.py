"""Recorder boundary and failure contracts for temperature history."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.heating_cooling_degree_days.degree_days import (
    integrate_degree_days,
)
from custom_components.heating_cooling_degree_days.history import (
    get_temperature_history,
)
from homeassistant.helpers.update_coordinator import UpdateFailed

START = datetime(2026, 1, 2, tzinfo=UTC)
END = START + timedelta(days=1)
ENTITY = "sensor.outdoor"


@pytest.mark.freeze_time("2026-01-01 22:00:00+00:00")
async def test_recorder_start_state_and_end_exclusion(recorder_mock, hass, freezer):
    """An actual recorder start-state covers the whole day, excluding end changes."""
    freezer.move_to(START - timedelta(hours=1))
    hass.states.async_set(ENTITY, "10", {"unit_of_measurement": "°C"})
    await async_wait_recording_done(hass)

    freezer.move_to(END)
    hass.states.async_set(ENTITY, "30", {"unit_of_measurement": "°C"})
    await async_wait_recording_done(hass)

    history = await get_temperature_history(hass, START, END, ENTITY, "°C")
    assert (
        len(history.samples) == 2
    )  # Includes look-ahead, but the integral excludes it.
    assert history.samples[0].timestamp == START - timedelta(minutes=15)
    result = integrate_degree_days(history.samples, START, END, 18)
    assert result.hdd == 8
    assert result.coverage_seconds == 86400


@pytest.mark.freeze_time("2026-01-01 22:00:00+00:00")
async def test_recorder_keeps_attribute_only_unit_changes(recorder_mock, hass, freezer):
    """A unit-only change with unchanged numeric state still splits the interval."""
    for when, unit in [
        (START - timedelta(hours=1), "°C"),
        (START + timedelta(hours=12), "°F"),
    ]:
        freezer.move_to(when)
        hass.states.async_set(ENTITY, "50", {"unit_of_measurement": unit})
        await async_wait_recording_done(hass)
    freezer.move_to(END)

    history = await get_temperature_history(hass, START, END, ENTITY, "°C")
    assert [s.temperature for s in history.samples] == [50, 10]
    result = integrate_degree_days(history.samples, START, END, 18)
    assert result.hdd == 4
    assert result.cdd == 16
    assert result.mean_temp == 30


async def test_recorder_failure_is_not_empty_history(recorder_mock, hass):
    """Database errors reach the coordinator as failed updates."""
    with (
        patch(
            "custom_components.heating_cooling_degree_days.history.get_significant_states",
            side_effect=RuntimeError("recorder failed"),
        ),
        pytest.raises(UpdateFailed, match="Could not read") as exc,
    ):
        await get_temperature_history(hass, START, END, ENTITY, "°C")
    assert isinstance(exc.value.__cause__, RuntimeError)


@pytest.mark.freeze_time("2026-01-01 22:00:00+00:00")
@pytest.mark.parametrize("invalid", ["unknown", "unavailable", "not numeric", "nan"])
async def test_recorder_context_bridges_midnight_gaps(
    recorder_mock, hass, freezer, invalid
):
    """Real recorder look-behind/look-ahead allow short spans across both day edges."""
    for when, value in [
        (START - timedelta(hours=1), "10"),
        (START - timedelta(seconds=1), invalid),
        (START + timedelta(seconds=1.8), "10"),
        (END - timedelta(seconds=1), invalid),
        (END + timedelta(seconds=1.8), "30"),
    ]:
        freezer.move_to(when)
        hass.states.async_set(ENTITY, value, {"unit_of_measurement": "°C"})
        # Drain the recorder worker too: an empty queue may hide an in-flight write.
        await async_wait_recording_done(hass)
    history = await get_temperature_history(hass, START, END, ENTITY, "°C")
    result = integrate_degree_days(history.samples, START, END, 18)
    assert result.coverage_seconds == 86400
    assert result.hdd == 8
    assert result.cdd == 0


@pytest.mark.freeze_time("2026-01-01 22:00:00+00:00")
async def test_recorder_open_end_gap_stays_partial_until_recovery(
    recorder_mock, hass, freezer
):
    """Future query bounds must not invent a recovery that has not been recorded."""
    for when, value in [
        (START - timedelta(hours=1), "10"),
        (END - timedelta(seconds=3), "unknown"),
    ]:
        freezer.move_to(when)
        hass.states.async_set(ENTITY, value, {"unit_of_measurement": "°C"})
        await async_wait_recording_done(hass)
    freezer.move_to(END)
    history = await get_temperature_history(hass, START, END, ENTITY, "°C")
    result = integrate_degree_days(history.samples, START, END, 18)
    assert result.coverage_seconds == 86400 - 3


async def test_query_context_uses_elapsed_utc_time_at_dst_transition(
    recorder_mock, hass
):
    """Context stays fifteen actual minutes even when local wall times do not exist."""
    zone = ZoneInfo("Europe/Paris")
    start = datetime(2026, 3, 29, 3, tzinfo=zone)
    end = start + timedelta(hours=1)
    with patch(
        "custom_components.heating_cooling_degree_days.history.get_significant_states",
        return_value={},
    ) as query:
        await get_temperature_history(hass, start, end, ENTITY, "°C")
    assert query.call_args.args[1] == datetime(2026, 3, 29, 0, 45, tzinfo=UTC)
    assert query.call_args.args[2] == datetime(2026, 3, 29, 2, 15, tzinfo=UTC)
