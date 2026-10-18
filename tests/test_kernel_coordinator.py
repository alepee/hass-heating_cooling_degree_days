"""Daily kernel results reach the coordinator and sensor without losing validity."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import DOMAIN
from custom_components.heating_cooling_degree_days.coordinator import (
    HDDDataUpdateCoordinator,
)
from custom_components.heating_cooling_degree_days.degree_days import TemperatureSample
from custom_components.heating_cooling_degree_days.history import TemperatureHistory
from custom_components.heating_cooling_degree_days.sensor import DegreeDegreeSensor
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

START = datetime(2026, 1, 2, tzinfo=UTC)


def _coordinator(hass):
    """Create a coordinator with both daily calculations enabled."""
    dt_util.set_default_time_zone(UTC)
    return HDDDataUpdateCoordinator(
        hass,
        "sensor.outdoor",
        18.0,
        "°C",
        "test-entry",
        include_cooling=True,
        include_weekly=False,
        include_monthly=False,
    )


@pytest.mark.freeze_time("2026-01-03 12:00:00+00:00")
async def test_partial_result_precision_and_sensor_mean(
    recorder_mock, enable_custom_integrations, hass
):
    """Store unrounded integrals and display coverage with a time-weighted mean."""
    history = TemperatureHistory(
        samples=(
            TemperatureSample(START, 10),
            TemperatureSample(START + timedelta(hours=1), None),
            TemperatureSample(START + timedelta(hours=22), 22),
        ),
        assumed_unit=None,
        assumed_unit_count=0,
    )
    coordinator = _coordinator(hass)
    with patch(
        "custom_components.heating_cooling_degree_days.coordinator.get_temperature_history",
        return_value=history,
    ):
        await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert coordinator.data["hdd_daily"] == pytest.approx(8 / 24)
    assert coordinator.daily_hdd_values[START.date()] == pytest.approx(8 / 24)
    assert coordinator.day_result.coverage_seconds == 10800
    entry = MockConfigEntry(domain=DOMAIN, title="HDD")
    sensor = DegreeDegreeSensor(coordinator, entry, "hdd_daily")
    assert sensor.native_value == 0.3
    assert sensor.extra_state_attributes["mean_temperature"] == 18
    assert sensor.extra_state_attributes["coverage"] == 0.125
    assert sensor.extra_state_attributes["partial"] is True


@pytest.mark.freeze_time("2026-01-03 12:00:00+00:00")
async def test_missing_day_does_not_publish_or_persist_zero(
    recorder_mock, enable_custom_integrations, hass
):
    """A query without samples yields an unknown daily value with zero coverage."""
    coordinator = _coordinator(hass)
    with patch(
        "custom_components.heating_cooling_degree_days.coordinator.get_temperature_history",
        return_value=TemperatureHistory((), None, 0),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["hdd_daily"] is None
    assert coordinator.data["cdd_daily"] is None
    assert START.date() not in coordinator.daily_hdd_values
    assert coordinator.day_result.mean_temp is None
    sensor = DegreeDegreeSensor(
        coordinator, MockConfigEntry(domain=DOMAIN), "hdd_daily"
    )
    assert sensor.native_value is None
    assert sensor.extra_state_attributes["coverage"] == 0


async def test_recorder_failure_marks_coordinator_failed(
    recorder_mock, enable_custom_integrations, hass
):
    """A fetch failure cannot masquerade as a successful cached update."""
    coordinator = _coordinator(hass)
    coordinator.async_set_updated_data({"hdd_daily": 8})
    with patch(
        "custom_components.heating_cooling_degree_days.coordinator.get_temperature_history",
        side_effect=UpdateFailed("recorder failed"),
    ):
        await coordinator.async_refresh()
    assert not coordinator.last_update_success
    assert coordinator.data["hdd_daily"] == 8
    sensor = DegreeDegreeSensor(
        coordinator, MockConfigEntry(domain=DOMAIN), "hdd_daily"
    )
    assert not sensor.available
