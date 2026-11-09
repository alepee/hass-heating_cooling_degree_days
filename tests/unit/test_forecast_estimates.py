"""Numerical contracts for forecast intervals and calendar-day estimates."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.heating_cooling_degree_days.degree_days import (
    DayResult,
    TemperatureSample,
    combine_results,
    forecast_samples,
    integrate_degree_days,
)
from custom_components.heating_cooling_degree_days.forecast import (
    REASON_NO_COVERAGE,
    estimate_day,
)

HOUR = 3600
STEP = HOUR
MAX = 3 * HOUR
START = datetime(2026, 1, 2, tzinfo=UTC)
END = START + timedelta(days=1)
PARIS = ZoneInfo("Europe/Paris")


def _hourly(start, hours, temperature):
    # UTC arithmetic: aware local datetimes add wall-clock time across DST.
    start = start.astimezone(UTC)
    return [(start + timedelta(hours=h), temperature) for h in range(hours)]


def _integrate(points, start=START, end=END, base=18):
    return integrate_degree_days(forecast_samples(points, STEP, MAX), start, end, base)


def test_hourly_points_cover_their_hour_including_the_last():
    """24 hourly points cover the day; the final point holds the last spacing."""
    result = _integrate(_hourly(START, 24, 10))
    assert result.hdd == 8
    assert result.coverage_seconds == 86400


def test_permitted_wider_spacing_holds_until_next_point():
    """Three-hour spacing is elapsed duration, not one hour per record."""
    points = [(START + timedelta(hours=h), 6) for h in range(0, 24, 3)]
    result = _integrate(points)
    assert result.hdd == 12
    assert result.coverage_seconds == 86400


def test_excessive_gap_is_not_bridged():
    """Beyond the accepted interval a point holds one step, then coverage stops."""
    points = [(START, 6), (START + timedelta(hours=5), 6)]
    result = _integrate(points)
    # 00:00-01:00 and 05:00-06:00 (nominal steps); the rest is uncovered.
    assert result.coverage_seconds == 2 * HOUR
    assert result.hdd == pytest.approx(12 * 2 / 24)


def test_unordered_duplicates_use_last_supplied_point():
    """Sorting is by instant; a duplicated timestamp keeps the last value."""
    points = [
        (START + timedelta(hours=1), 18),
        (START, 0),
        (START, 6),
    ]
    result = _integrate(points, end=START + timedelta(hours=2))
    assert result.hdd == pytest.approx(12 / 24)
    assert result.coverage_seconds == 2 * HOUR


def test_single_point_holds_one_nominal_step():
    """Without a known spacing the final boundary is one nominal hour."""
    result = _integrate([(START, 6)])
    assert result.coverage_seconds == HOUR


def test_invalid_forecast_temperature_is_a_gap():
    """A non-finite or missing temperature uncovers its interval."""
    points = [(START, 6), (START + timedelta(hours=1), float("nan"))]
    points.append((START + timedelta(hours=2), 6))
    result = _integrate(points, end=START + timedelta(hours=3))
    assert result.coverage_seconds == 2 * HOUR


def test_no_invented_coverage_beyond_horizon():
    """A horizon ending mid-day leaves the remainder uncovered."""
    result = _integrate(_hourly(START, 10, 10))
    assert result.coverage_seconds == 10 * HOUR
    assert result.hdd == pytest.approx(8 * 10 / 24)


def test_step_must_fit_the_interval_limit():
    """The policy must be explicit and coherent."""
    with pytest.raises(ValueError):
        forecast_samples([], 2 * HOUR, HOUR)


def test_naive_forecast_timestamp_is_rejected():
    """Forecast instants must be absolute."""
    with pytest.raises(ValueError):
        forecast_samples([(datetime(2026, 1, 2), 5)], STEP, MAX)


def test_combine_sums_disjoint_parts_and_weights_mean():
    """Coverage comes from seconds, not from averaging percentages."""
    combined = combine_results(
        (
            DayResult(1, 0, 6 * HOUR, 6 * HOUR, 10),
            DayResult(2, 0, 3 * HOUR, 18 * HOUR, 4),
        ),
        86400,
    )
    assert combined.hdd == 3
    assert combined.coverage_seconds == 9 * HOUR
    assert combined.window_seconds == 86400
    assert combined.mean_temp == pytest.approx((10 * 6 + 4 * 3) / 9)


def test_mid_hour_cutover_has_no_overlap_and_no_lost_fraction():
    """Observed until 10:30, then the 10:00 forecast point covers 10:30-11:00."""
    day = date(2026, 1, 2)
    as_of = START + timedelta(hours=10, minutes=30)
    observed = (TemperatureSample(START - timedelta(hours=1), 10),)
    forecast = forecast_samples(_hourly(START, 24, 4), STEP, MAX)
    estimate = estimate_day(
        day, UTC, base_temp=18, as_of=as_of, observed=observed, forecast=forecast
    )
    assert estimate.result.coverage_seconds == 86400
    expected = (8 * 10.5 + 14 * 13.5) / 24
    assert estimate.value("hdd") == pytest.approx(expected)
    assert estimate.coverage == 1
    assert estimate.reasons == ()


def test_missing_observations_remain_partial_and_unscaled():
    """A partial estimate is only the covered contribution."""
    as_of = START + timedelta(hours=12)
    forecast = forecast_samples(_hourly(START, 24, 6), STEP, MAX)
    estimate = estimate_day(
        date(2026, 1, 2),
        UTC,
        base_temp=18,
        as_of=as_of,
        observed=None,
        forecast=forecast,
        reasons=("recorder_failed",),
    )
    assert estimate.value("hdd") == pytest.approx(6)
    assert estimate.coverage == 0.5
    assert estimate.reasons == ("recorder_failed",)


def test_no_coverage_is_not_a_zero():
    """Without any usable interval the value is unknown, with a reason."""
    estimate = estimate_day(
        date(2026, 1, 3), UTC, base_temp=18, as_of=START, observed=None, forecast=None
    )
    assert estimate.value("hdd") is None
    assert estimate.reasons == (REASON_NO_COVERAGE,)


def test_fully_covered_day_without_demand_is_a_genuine_zero():
    """Warm forecast days have a real zero HDD."""
    forecast = forecast_samples(_hourly(END, 24, 25), STEP, MAX)
    estimate = estimate_day(
        date(2026, 1, 3),
        UTC,
        base_temp=18,
        as_of=START,
        observed=None,
        forecast=forecast,
    )
    assert estimate.value("hdd") == 0
    assert estimate.value("cdd") == pytest.approx(7)


@pytest.mark.parametrize(
    ("day", "hours", "expected"),
    [
        (date(2026, 3, 29), 23, 11.5),
        (date(2026, 3, 30), 24, 12),
        (date(2026, 10, 25), 25, 12.5),
    ],
)
def test_dst_days_use_elapsed_duration(day, hours, expected):
    """A constant 12° deficit gives 11.5, 12 and 12.5 over 23/24/25 hour days."""
    start = datetime.combine(day, datetime.min.time(), PARIS)
    forecast = forecast_samples(_hourly(start, hours, 6), STEP, MAX)
    as_of = start - timedelta(days=1)
    estimate = estimate_day(
        day, PARIS, base_temp=18, as_of=as_of, observed=None, forecast=forecast
    )
    assert estimate.result.window_seconds == hours * HOUR
    assert estimate.value("hdd") == pytest.approx(expected)
    assert estimate.coverage == 1
    assert estimate.start.isoformat().startswith(day.isoformat())
