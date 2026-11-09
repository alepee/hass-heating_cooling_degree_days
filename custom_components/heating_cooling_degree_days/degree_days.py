"""Pure degree-day integration of held temperatures over an explicit window."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite

SECONDS_PER_DAY = 86400
MAX_BRIDGED_GAP = 15 * 60
CALCULATION_REVISION = 1


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


def _bridge_short_gaps(
    samples: Iterable[TemperatureSample],
) -> Iterable[tuple[float, float | None]]:
    """Omit bounded invalid runs only when both surrounding valid states are known."""
    # Resolve duplicate timestamps before deciding which value can be held.
    by_timestamp = {
        _timestamp(sample.timestamp): (
            sample.temperature
            if sample.temperature is not None and isfinite(sample.temperature)
            else None
        )
        for sample in samples
    }
    gap_start: float | None = None
    last_valid: float | None = None
    for timestamp, temperature in sorted(by_timestamp.items()):
        if temperature is None:
            if gap_start is None:
                gap_start = timestamp
            continue
        if gap_start is not None:
            if last_valid is None or timestamp - gap_start > MAX_BRIDGED_GAP:
                yield gap_start, None
            gap_start = None
        yield timestamp, temperature
        last_valid = temperature
    if gap_start is not None:
        # An open-ended interruption cannot be assumed to be short.
        yield gap_start, None


def integrate_degree_days(
    samples: Iterable[TemperatureSample],
    start: datetime,
    end: datetime,
    base_temp: float,
) -> DayResult:
    """Integrate held values in [start, end), bridging confirmed short invalid spans.

    Invalid runs of at most MAX_BRIDGED_GAP seconds hold the preceding valid
    value, provided a valid recovery is observed. Longer/open-ended runs and
    gaps without a known preceding value remain uncovered. Samples outside the
    window provide boundary context only; integrals are clipped to the window.
    Equal timestamps use the last supplied state. Elapsed degree-seconds are
    divided by 86400 even on 23/25-hour local days.
    """
    start_ts, end_ts = _timestamp(start), _timestamp(end)
    if end_ts <= start_ts:
        raise ValueError("The integration window must have positive duration")
    if not isfinite(base_temp):
        raise ValueError("Base temperature must be finite")

    ordered = _bridge_short_gaps(samples)
    cursor = start_ts
    held: float | None = None
    hdd_seconds = cdd_seconds = temperature_seconds = coverage_seconds = 0.0

    # Apply the end sentinel after bridging so it cannot invent a recovery.
    for timestamp, temperature in (*ordered, (end_ts, None)):
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


def forecast_samples(
    points: Iterable[tuple[datetime, float | None]],
    step_seconds: float,
    max_interval_seconds: float,
) -> tuple[TemperatureSample, ...]:
    """Turn forecast points into held samples with explicit validity limits.

    Each point holds until the next timestamp when the spacing is at most
    max_interval_seconds. Otherwise, and for the final point, it holds for the
    preceding accepted spacing (one nominal step without one), followed by a
    gap: no coverage is invented beyond the accepted interval or the horizon.
    Equal timestamps use the last supplied point; invalid temperatures are gaps
    until the next point.
    """
    if not 0 < step_seconds <= max_interval_seconds:
        raise ValueError("The forecast step must be positive and within the limit")
    by_timestamp = {_timestamp(when): temperature for when, temperature in points}
    ordered = sorted(by_timestamp.items())
    samples = []
    spacing = step_seconds
    for index, (timestamp, temperature) in enumerate(ordered):
        if temperature is not None and not isfinite(temperature):
            temperature = None
        when = datetime.fromtimestamp(timestamp, UTC)
        samples.append(TemperatureSample(when, temperature))
        following = ordered[index + 1][0] if index + 1 < len(ordered) else None
        if following is not None and following - timestamp <= max_interval_seconds:
            spacing = following - timestamp
            continue
        expiry = datetime.fromtimestamp(timestamp + spacing, UTC)
        samples.append(TemperatureSample(expiry, None))
        spacing = step_seconds
    return tuple(samples)


def combine_results(parts: Iterable[DayResult], window_seconds: float) -> DayResult:
    """Sum disjoint window contributions; weight the mean by covered time."""
    hdd = cdd = covered = temperature_seconds = 0.0
    for part in parts:
        hdd += part.hdd
        cdd += part.cdd
        covered += part.coverage_seconds
        if part.mean_temp is not None:
            temperature_seconds += part.mean_temp * part.coverage_seconds
    return DayResult(
        hdd=hdd,
        cdd=cdd,
        coverage_seconds=covered,
        window_seconds=window_seconds,
        mean_temp=temperature_seconds / covered if covered else None,
    )
