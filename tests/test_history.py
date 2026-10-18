"""Recorder boundary and failure contracts for temperature history."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

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


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations():
    """Let recorder_mock establish fixture ordering before hass."""


@pytest.mark.freeze_time("2026-01-01 22:00:00+00:00")
async def test_recorder_start_state_and_end_exclusion(recorder_mock, hass, freezer):
    """An actual recorder start-state covers the whole day, excluding end changes."""
    freezer.move_to(START - timedelta(hours=1))
    hass.states.async_set(ENTITY, "10", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    await recorder_mock.async_block_till_done()

    freezer.move_to(END)
    hass.states.async_set(ENTITY, "30", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    await recorder_mock.async_block_till_done()

    history = await get_temperature_history(hass, START, END, ENTITY, "°C")
    assert len(history.samples) == 1
    assert history.samples[0].timestamp == START
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
        await hass.async_block_till_done()
        await recorder_mock.async_block_till_done()
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
