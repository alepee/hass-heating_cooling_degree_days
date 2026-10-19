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


@pytest.mark.parametrize(
    "seconds", [0.1, 1, 2.8, 3, 14 * 60, 15 * 60, 900.001, 16 * 60, 30 * 60]
)
@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf")])
def test_confirmed_short_gaps_hold_previous_temperature(seconds, invalid):
    """Only closed spans of at most fifteen minutes contribute held temperature."""
    gap = START + timedelta(hours=12)
    result = integrate_degree_days(
        [
            TemperatureSample(START, 10),
            TemperatureSample(gap, invalid),
            TemperatureSample(gap + timedelta(seconds=seconds), 10),
        ],
        START,
        END,
        18,
    )
    expected = 86400 if seconds <= 900 else 86400 - seconds
    assert result.coverage_seconds == pytest.approx(expected)
    assert result.hdd == pytest.approx(8 * expected / 86400)
    assert result.mean_temp == pytest.approx(10)


@pytest.mark.parametrize(
    ("before", "after", "known"),
    [(300, 300, True), (899, 1, True), (899, 2, True), (300, 300, False)],
)
def test_gap_crossing_start_uses_full_duration_and_known_previous_value(
    before, after, known
):
    """A short clipped fragment of a long/unknown leading gap is not sufficient."""
    samples = [
        TemperatureSample(START - timedelta(seconds=before), None),
        TemperatureSample(START + timedelta(seconds=after), 10),
    ]
    if known:
        samples.insert(0, TemperatureSample(START - timedelta(hours=1), 10))
    result = integrate_degree_days(samples, START, END, 18)
    expected = 86400 if known and before + after <= 900 else 86400 - after
    assert result.coverage_seconds == expected
    assert result.hdd == pytest.approx(8 * expected / 86400)


@pytest.mark.parametrize("recovery_after_end", [60, 840, 841, None])
def test_gap_crossing_end_requires_bounded_observed_recovery(recovery_after_end):
    """Look-ahead can prove a short gap, but never contributes beyond the window."""
    samples = [
        TemperatureSample(START, 10),
        TemperatureSample(END - timedelta(seconds=60), None),
    ]
    if recovery_after_end is not None:
        samples.append(
            TemperatureSample(END + timedelta(seconds=recovery_after_end), 30)
        )
    result = integrate_degree_days(samples, START, END, 18)
    expected = 86400 if recovery_after_end in (60, 840) else 86340
    assert result.coverage_seconds == expected
    assert result.hdd == pytest.approx(8 * expected / 86400)
    assert result.cdd == 0
    assert result.mean_temp == 10


def test_multiple_gaps_and_consecutive_invalid_states():
    """Hold the preceding value, not the recovery value; measure entire invalid runs."""
    result = integrate_degree_days(
        [
            TemperatureSample(START, 10),
            TemperatureSample(START + timedelta(hours=1), None),
            TemperatureSample(START + timedelta(hours=1, minutes=5), float("nan")),
            TemperatureSample(START + timedelta(hours=1, minutes=10), 26),
            TemperatureSample(START + timedelta(hours=2), None),
            TemperatureSample(START + timedelta(hours=2, minutes=10), None),
            TemperatureSample(START + timedelta(hours=2, minutes=20), 26),
            TemperatureSample(START + timedelta(hours=3), None),
            TemperatureSample(START + timedelta(hours=3, seconds=3), 26),
        ],
        START,
        END,
        18,
    )
    assert result.coverage_seconds == 86400 - 1200
    assert result.hdd == pytest.approx(8 * 4200 / 86400)
    assert result.cdd == pytest.approx(8 * (86400 - 1200 - 4200) / 86400)
    assert result.mean_temp == pytest.approx((10 * 4200 + 26 * 81000) / 85200)


def test_duplicate_state_cannot_supply_a_spurious_held_temperature():
    """A valid state overwritten at the same instant cannot seed a gap."""
    gap = START + timedelta(hours=1)
    result = integrate_degree_days(
        [
            TemperatureSample(START, 10),
            TemperatureSample(gap, 100),
            TemperatureSample(gap, None),
            TemperatureSample(gap + timedelta(seconds=3), 10),
        ],
        START,
        END,
        18,
    )
    assert result.hdd == 8
    assert result.cdd == 0
    assert result.coverage_seconds == 86400


def test_gap_duration_across_repeated_hour_uses_absolute_instants():
    """A backwards clock jump can bound a short gap; equal wall times can be an hour apart."""
    paris = ZoneInfo("Europe/Paris")
    start = datetime(2026, 10, 25, tzinfo=paris)
    end = start + timedelta(days=1)
    short = integrate_degree_days(
        [
            TemperatureSample(start, 10),
            TemperatureSample(
                datetime(2026, 10, 25, 2, 59, tzinfo=paris, fold=0), None
            ),
            TemperatureSample(datetime(2026, 10, 25, 2, 1, tzinfo=paris, fold=1), 10),
        ],
        start,
        end,
        18,
    )
    assert short.coverage_seconds == 25 * 3600
    long = integrate_degree_days(
        [
            TemperatureSample(start, 10),
            TemperatureSample(datetime(2026, 10, 25, 2, 1, tzinfo=paris, fold=0), None),
            TemperatureSample(datetime(2026, 10, 25, 2, 1, tzinfo=paris, fold=1), 10),
        ],
        start,
        end,
        18,
    )
    assert long.coverage_seconds == 24 * 3600
