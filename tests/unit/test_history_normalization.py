"""State normalization tests without a Home Assistant or recorder instance."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.heating_cooling_degree_days.degree_days import (
    integrate_degree_days,
)
from custom_components.heating_cooling_degree_days.history import (
    normalize_temperature_states,
)
from homeassistant.core import State

START = datetime(2026, 1, 2, tzinfo=UTC)
END = START + timedelta(days=1)


def _state(value, hour=0, unit="°C"):
    """Make a historical state, retaining each state's own unit."""
    return State(
        "sensor.outdoor",
        value,
        {} if unit is None else {"unit_of_measurement": unit},
        last_updated=START + timedelta(hours=hour),
    )


@pytest.mark.parametrize(
    ("target", "base", "hdd", "mean"), [("°C", 18, 8, 10), ("°F", 65, 15, 50)]
)
def test_mixed_units_are_normalized_before_integration(target, base, hdd, mean):
    """10 Celsius and 50 Fahrenheit represent the same physical temperature."""
    history = normalize_temperature_states(
        [_state("10"), _state("50", hour=12, unit="°F")], target
    )
    result = integrate_degree_days(history.samples, START, END, base)
    assert result.hdd == pytest.approx(hdd)
    assert result.mean_temp == pytest.approx(mean)
    assert result.coverage_seconds == 86400
    assert history.assumed_unit_count == 0


@pytest.mark.parametrize(
    "value", ["unknown", "unavailable", "invalid", "nan", "inf", "-inf"]
)
def test_invalid_states_preserve_gap_markers(value):
    """Invalid states terminate a held reading instead of being filtered out."""
    history = normalize_temperature_states(
        [_state("10"), _state(value, hour=1), _state("10", hour=23)], "°C"
    )
    assert history.samples[1].temperature is None
    result = integrate_degree_days(history.samples, START, END, 18)
    assert result.coverage_seconds == 7200
    assert result.hdd == pytest.approx(8 / 12)


@pytest.mark.parametrize(("source_unit", "value"), [("°F", "50"), (None, "10")])
def test_missing_unit_records_assumption(source_unit, value):
    """Use the current source unit, otherwise the entry unit, and record it."""
    history = normalize_temperature_states(
        [_state(value, unit=None)], "°C", source_unit
    )
    assert history.samples[0].temperature == pytest.approx(10)
    assert history.assumed_unit == (source_unit or "°C")
    assert history.assumed_unit_count == 1


def test_unsupported_source_unit_is_a_gap():
    """Do not interpret an explicitly invalid unit as the calculation unit."""
    history = normalize_temperature_states([_state("10", unit="kWh")], "°C")
    assert history.samples[0].temperature is None
    with pytest.raises(ValueError, match="Unsupported"):
        normalize_temperature_states([], "kWh")
