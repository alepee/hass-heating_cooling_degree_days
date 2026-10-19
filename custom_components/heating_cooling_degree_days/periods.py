"""Daily ledger records and calendar aggregation, independent of Home Assistant."""

import calendar
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Self

from .degree_days import CALCULATION_REVISION, DayResult


@dataclass(frozen=True, slots=True)
class DailyRecord:
    """One completed local day, with unknown legacy coverage kept explicit."""

    hdd: float | None
    cdd: float | None
    coverage_seconds: float | None
    window_seconds: float
    mean_temp: float | None
    last_attempt: float = 0
    legacy: bool = False
    # Kernel revision of the last attempt, even if older values were retained.
    # Missing in beta.3 stores; complete non-legacy days remain finalized.
    last_attempt_revision: int = 0

    @classmethod
    def from_result(cls, result: DayResult, attempted: datetime) -> Self:
        """Preserve raw integrals; no observed interval means an unknown value."""
        return cls(
            result.hdd if result.coverage_seconds else None,
            result.cdd if result.coverage_seconds else None,
            result.coverage_seconds,
            result.window_seconds,
            result.mean_temp,
            attempted.timestamp(),
            last_attempt_revision=CALCULATION_REVISION,
        )

    @property
    def complete(self) -> bool:
        """Only fully covered days are final; legacy values can be corrected once."""
        return not self.legacy and self.coverage_seconds == self.window_seconds


def day_window(day: date, zone: tzinfo) -> tuple[datetime, datetime]:
    """Return local midnight boundaries, preserving 23/25-hour DST days."""
    return (
        datetime.combine(day, time.min, zone),
        datetime.combine(day + timedelta(days=1), time.min, zone),
    )


def day_seconds(day: date, zone: tzinfo) -> float:
    """Return the elapsed duration of a local date."""
    start, end = day_window(day, zone)
    return end.timestamp() - start.timestamp()


@dataclass(frozen=True, slots=True)
class Period:
    """Calendar label and exclusive completed-day cutoff from one reference date."""

    start: date
    end: date
    stop: date

    @property
    def completed_days(self) -> tuple[date, ...]:
        """Return completed dates only, excluding today and future dates."""
        return tuple(
            self.start + timedelta(days=offset)
            for offset in range((self.stop - self.start).days)
        )


def calendar_periods(today: date) -> dict[str, Period]:
    """Build yesterday and the current calendar week/month, including empty ones."""
    yesterday = today - timedelta(days=1)
    monday = today - timedelta(days=today.weekday())
    return {
        "daily": Period(yesterday, yesterday, today),
        "weekly": Period(monday, monday + timedelta(days=6), today),
        "monthly": Period(
            today.replace(day=1),
            today.replace(day=calendar.monthrange(today.year, today.month)[1]),
            today,
        ),
    }


def aggregate_period(
    ledger: Mapping[date, DailyRecord], period: Period, metric: str, zone: tzinfo
) -> tuple[float | None, dict]:
    """Sum observed integrals and duration-weighted coverage without inventing data."""
    dates = period.completed_days
    expected = sum(day_seconds(day, zone) for day in dates)
    covered = 0.0
    value = 0.0
    counted = legacy = missing = 0
    for day in dates:
        record = ledger.get(day)
        measured = getattr(record, metric) if record else None
        if measured is None:
            missing += 1
            continue
        counted += 1
        value += measured
        if record.legacy:
            legacy += 1
            covered += day_seconds(day, zone)
        else:
            covered += record.coverage_seconds or 0
    coverage = min(covered / expected, 1.0) if expected else 1.0
    attrs = {
        "date_range": (
            str(period.start)
            if period.start == period.end
            else f"{period.start} to {period.end}"
        ),
        "period_start": period.start.isoformat(),
        "period_end": period.end.isoformat(),
        "completed_through": dates[-1].isoformat() if dates else None,
        "days_counted": counted,
        "missing_days": missing,
        "coverage": coverage,
        "partial": coverage < 1,
        "legacy_days": legacy,
    }
    return (value if counted or not dates else None), attrs
