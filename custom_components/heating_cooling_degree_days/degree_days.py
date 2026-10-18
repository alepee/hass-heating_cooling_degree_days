"""Pure degree-day integration of held temperatures over an explicit window."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

SECONDS_PER_DAY = 86400


@dataclass(frozen=True, slots=True)
class TemperatureSample:
    """A normalized temperature, or a gap, effective from an aware timestamp."""

    timestamp: datetime
    temperature: float | None


@dataclass(frozen=True, slots=True)
class DayResult:
    """Unrounded integrals and coverage of a requested local-day window."""

    hdd: float
    cdd: float
    coverage_seconds: float
    window_seconds: float
    mean_temp: float | None


def _timestamp(value: datetime) -> float:
    """Require an absolute instant, including across repeated local hours."""
    if value.utcoffset() is None:
        raise ValueError("Temperature windows and samples must be timezone-aware")
    return value.timestamp()


def integrate_degree_days(
    samples: Iterable[TemperatureSample],
    start: datetime,
    end: datetime,
    base_temp: float,
) -> DayResult:
    """Integrate held values in [start, end), without bridging invalid states.

    The last state at or before start seeds the window. A valid value holds
    until the next sample or end; None and non-finite values start gaps.
    Equal timestamps use the last supplied state. Leading gaps stay uncovered.
    Elapsed degree-seconds are divided by 86400 even on 23/25-hour local days.
    """
    start_ts, end_ts = _timestamp(start), _timestamp(end)
    if end_ts <= start_ts:
        raise ValueError("The integration window must have positive duration")
    if not isfinite(base_temp):
        raise ValueError("Base temperature must be finite")

    ordered = sorted(samples, key=lambda sample: _timestamp(sample.timestamp))
    cursor = start_ts
    held: float | None = None
    hdd_seconds = cdd_seconds = temperature_seconds = coverage_seconds = 0.0

    # A gap at end closes the final held interval without inventing a reading.
    for sample in (*ordered, TemperatureSample(end, None)):
        timestamp = _timestamp(sample.timestamp)
        temperature = sample.temperature
        if temperature is not None and not isfinite(temperature):
            temperature = None
        if timestamp <= start_ts:
            held = temperature
            continue

        interval_end = min(timestamp, end_ts)
        seconds = interval_end - cursor
        if held is not None:
            coverage_seconds += seconds
            temperature_seconds += held * seconds
            hdd_seconds += max(0.0, base_temp - held) * seconds
            cdd_seconds += max(0.0, held - base_temp) * seconds
        cursor = interval_end
        if timestamp >= end_ts:
            break
        held = temperature

    return DayResult(
        hdd=hdd_seconds / SECONDS_PER_DAY,
        cdd=cdd_seconds / SECONDS_PER_DAY,
        coverage_seconds=coverage_seconds,
        window_seconds=end_ts - start_ts,
        mean_temp=(
            temperature_seconds / coverage_seconds if coverage_seconds else None
        ),
    )
