"""Numerical contracts for held-state degree-day integration."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.heating_cooling_degree_days.degree_days import (
    TemperatureSample,
    integrate_degree_days,
)

START = datetime(2026, 1, 2, tzinfo=UTC)
END = START + timedelta(days=1)


def test_single_start_state_covers_day():
    """An unchanged state before midnight holds through the next midnight."""
    result = integrate_degree_days(
        [TemperatureSample(START - timedelta(hours=2), 10)], START, END, 18
    )
    assert result.hdd == 8
    assert result.cdd == 0
    assert result.coverage_seconds == result.window_seconds == 86400
    assert result.mean_temp == 10


@pytest.mark.parametrize("seconds", [1, 30, 60])
def test_frequent_samples_keep_every_interval(seconds):
    """Even subminute intervals contribute; 1441 minute points give eight HDD."""
    samples = [
        TemperatureSample(START + timedelta(seconds=i), 10)
        for i in range(0, 86401, seconds)
    ]
    result = integrate_degree_days(samples, START, END, 18)
    assert result.hdd == pytest.approx(8)
    assert result.coverage_seconds == 86400


def test_base_crossing_uses_hold_not_interpolation():
    """An abrupt change at noon contributes twelve hours on each side of base."""
    result = integrate_degree_days(
        [
            TemperatureSample(START, 10),
            TemperatureSample(START + timedelta(hours=12), 26),
        ],
        START,
        END,
        18,
    )
    assert result.hdd == result.cdd == 4
    assert result.mean_temp == 18


def test_gap_and_weighted_mean():
    """Only covered intervals contribute, including the last held interval."""
    result = integrate_degree_days(
        [
            TemperatureSample(START + timedelta(hours=2), 10),
            TemperatureSample(START + timedelta(hours=4), None),
            TemperatureSample(START + timedelta(hours=20), 22),
        ],
        START,
        END,
        18,
    )
    assert result.coverage_seconds == 6 * 3600
    assert result.hdd == pytest.approx(8 * 2 / 24)
    assert result.cdd == pytest.approx(4 * 4 / 24)
    assert result.mean_temp == 18  # (10*2 + 22*4) / 6, not sample mean 16


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), -float("inf")])
def test_invalid_state_starts_gap(invalid):
    """A valid value must not bridge an unavailable/nonfinite span."""
    result = integrate_degree_days(
        [
            TemperatureSample(START, 10),
            TemperatureSample(START + timedelta(hours=1), invalid),
            TemperatureSample(END - timedelta(hours=1), 10),
        ],
        START,
        END,
        18,
    )
    assert result.coverage_seconds == 7200
    assert result.hdd == pytest.approx(8 / 12)
    assert result.mean_temp == 10


@pytest.mark.parametrize("samples", [[], [TemperatureSample(START, None)]])
def test_empty_coverage_is_distinct_from_valid_zero(samples):
    """The result reports missing coverage even though its raw integral is zero."""
    missing = integrate_degree_days(samples, START, END, 18)
    zero = integrate_degree_days([TemperatureSample(START, 18)], START, END, 18)
    assert missing.hdd == zero.hdd == 0
    assert missing.mean_temp is None
    assert missing.coverage_seconds == 0
    assert zero.coverage_seconds == 86400


def test_window_clipping_stable_sort_and_duplicate_states():
    """Last duplicate wins; an end-boundary sample cannot affect this day."""
    samples = [
        TemperatureSample(END, 100),
        TemperatureSample(START - timedelta(hours=2), 0),
        TemperatureSample(START, 12),
        TemperatureSample(START, 10),
        TemperatureSample(END + timedelta(hours=1), -100),
    ]
    original = samples.copy()
    result = integrate_degree_days(samples, START, END, 18)
    assert result.hdd == 8
    assert result.coverage_seconds == 86400
    assert samples == original


@pytest.mark.parametrize(
    ("day", "hours"), [(datetime(2026, 3, 29), 23), (datetime(2026, 10, 25), 25)]
)
def test_dst_uses_elapsed_seconds(day, hours):
    """Local calendar days have 23/25 hours, with a fixed 86400 divisor."""
    start = day.replace(tzinfo=ZoneInfo("Europe/Paris"))
    end = start + timedelta(days=1)
    result = integrate_degree_days([TemperatureSample(start, 10)], start, end, 18)
    assert result.window_seconds == result.coverage_seconds == hours * 3600
    assert result.hdd == pytest.approx(8 * hours / 24)
    assert result.mean_temp == 10


def test_repeated_local_hour_is_ordered_by_instant():
    """The two 02:30 occurrences in autumn are distinct absolute instants."""
    paris = ZoneInfo("Europe/Paris")
    start = datetime(2026, 10, 25, 2, 30, tzinfo=paris, fold=0)
    repeated = start.replace(fold=1)
    end = datetime(2026, 10, 25, 3, 30, tzinfo=paris)
    result = integrate_degree_days(
        [TemperatureSample(repeated, 26), TemperatureSample(start, 10)], start, end, 18
    )
    assert result.window_seconds == 7200
    assert result.hdd == result.cdd == pytest.approx(8 / 24)


def test_no_rounding_in_kernel():
    """Short intervals retain precision for aggregation."""
    result = integrate_degree_days(
        [TemperatureSample(START, 17)], START, START + timedelta(seconds=1), 18
    )
    assert result.hdd == 1 / 86400


@pytest.mark.parametrize("base", [float("nan"), float("inf")])
def test_nonfinite_base_is_rejected(base):
    """A configuration error cannot silently produce a plausible zero."""
    with pytest.raises(ValueError, match="finite"):
        integrate_degree_days([], START, END, base)


def test_invalid_windows_are_rejected():
    """Naive timestamps and empty/reversed intervals cannot define a day."""
    with pytest.raises(ValueError, match="timezone-aware"):
        integrate_degree_days([], START.replace(tzinfo=None), END, 18)
    with pytest.raises(ValueError, match="positive"):
        integrate_degree_days([], END, START, 18)
    with pytest.raises(ValueError, match="positive"):
        integrate_degree_days([], START, START, 18)
