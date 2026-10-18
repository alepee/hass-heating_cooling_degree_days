"""Calendar boundaries, missing observations and elapsed-day coverage."""

from datetime import UTC, date
from zoneinfo import ZoneInfo

import pytest

from custom_components.heating_cooling_degree_days.periods import (
    DailyRecord,
    Period,
    aggregate_period,
    calendar_periods,
    day_seconds,
)


@pytest.mark.parametrize(
    ("today", "weekly_start", "monthly_start", "weekly_days", "monthly_days"),
    [
        (date(2026, 6, 1), date(2026, 6, 1), date(2026, 6, 1), 0, 0),
        (date(2026, 1, 1), date(2025, 12, 29), date(2026, 1, 1), 3, 0),
        (date(2026, 3, 1), date(2026, 2, 23), date(2026, 3, 1), 6, 0),
        (date(2026, 6, 15), date(2026, 6, 15), date(2026, 6, 1), 0, 14),
    ],
)
def test_current_period_boundaries(
    today, weekly_start, monthly_start, weekly_days, monthly_days
):
    """Monday, first of month and year rollover exclude all future dates."""
    periods = calendar_periods(today)
    assert periods["weekly"].start == weekly_start
    assert periods["monthly"].start == monthly_start
    assert len(periods["weekly"].completed_days) == weekly_days
    assert len(periods["monthly"].completed_days) == monthly_days
    for period in periods.values():
        assert all(day < today for day in period.completed_days)


@pytest.mark.parametrize("name", ["weekly", "monthly"])
def test_empty_period_is_complete_zero(name):
    """A new empty period is a real zero even with cached previous-period values."""
    ledger = {date(2026, 5, 31): DailyRecord(8, 0, 86400, 86400, 10)}
    value, attrs = aggregate_period(
        ledger, calendar_periods(date(2026, 6, 1))[name], "hdd", UTC
    )
    assert value == 0
    assert attrs["coverage"] == 1
    assert attrs["partial"] is False
    assert attrs["days_counted"] == attrs["missing_days"] == 0
    assert attrs["completed_through"] is None
    assert attrs["period_start"] == "2026-06-01"


@pytest.mark.parametrize(
    ("start", "end", "stop", "expected_hours"),
    [
        (date(2026, 3, 23), date(2026, 3, 29), date(2026, 3, 30), 167),
        (date(2026, 10, 19), date(2026, 10, 25), date(2026, 10, 26), 169),
    ],
)
def test_dst_week_coverage_uses_elapsed_seconds(start, end, stop, expected_hours):
    """Both DST transitions weight coverage by elapsed seconds, not day counts."""
    zone = ZoneInfo("Europe/Paris")
    period = Period(start, end, stop)
    ledger = {
        day: DailyRecord(
            day_seconds(day, zone) / 86400,
            0,
            day_seconds(day, zone),
            day_seconds(day, zone),
            17,
        )
        for day in period.completed_days
    }
    value, attrs = aggregate_period(ledger, period, "hdd", zone)
    assert value == pytest.approx(expected_hours / 24)
    assert attrs["coverage"] == 1
    del ledger[end]
    _, attrs = aggregate_period(ledger, period, "hdd", zone)
    assert attrs["coverage"] == pytest.approx(144 / expected_hours)
    assert attrs["missing_days"] == 1
    assert attrs["partial"] is True


def test_partial_unknown_and_legacy_values_are_distinct():
    """Observed zero counts; missing values do not; legacy coverage is flagged."""
    period = calendar_periods(date(2026, 6, 4))["monthly"]
    ledger = {
        date(2026, 6, 1): DailyRecord(0, 2, 43200, 86400, 20),
        date(2026, 6, 2): DailyRecord(4, None, None, 86400, None, legacy=True),
    }
    value, attrs = aggregate_period(ledger, period, "hdd", UTC)
    assert value == 4
    assert attrs["coverage"] == 0.5
    assert attrs["days_counted"] == 2
    assert attrs["legacy_days"] == 1
    assert attrs["missing_days"] == 1
    _, cooling = aggregate_period(ledger, period, "cdd", UTC)
    assert cooling["legacy_days"] == 0
    assert cooling["missing_days"] == 2
    assert cooling["coverage"] == pytest.approx(1 / 6)
    value, missing = aggregate_period({}, period, "hdd", UTC)
    assert value is None
    assert missing["coverage"] == 0
    assert missing["partial"] is True
