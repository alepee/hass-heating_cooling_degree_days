"""Pure domain logic for Heating and Cooling Degree Days calculations.

This module contains only pure functions with no external dependencies.
All functions are synchronous and can be tested without any mocking.

Degree Days are a measure of how cold or warm a location is over a period of time.
- HDD (Heating Degree Days): Measures heating demand when temperature is below base
- CDD (Cooling Degree Days): Measures cooling demand when temperature is above base

The calculations use numerical integration (trapezoidal rule) for accurate results.
"""

from datetime import datetime
from typing import Sequence

# Type alias for temperature readings
TemperatureReading = tuple[datetime, float]

# Minimum interval duration in days (~1 minute) to avoid numerical issues
MIN_INTERVAL_DAYS = 0.0007


def calculate_hdd_from_readings(
    readings: Sequence[TemperatureReading],
    base_temp: float,
) -> float:
    """Calculate Heating Degree Days using numerical integration.

    Uses the trapezoidal rule to integrate temperature deficit over time.
    Only periods where temperature is below the base temperature contribute
    to the HDD total.

    Args:
        readings: Sequence of (timestamp, temperature) tuples.
                  Timestamps should be datetime objects.
                  Temperatures should be in consistent units (°C or °F).
        base_temp: Base/reference temperature in same units as readings.
                   Common values: 18°C (65°F) for heating.

    Returns:
        Calculated HDD value rounded to 1 decimal place.
        Returns 0.0 if fewer than 2 readings provided.

    Example:
        >>> from datetime import datetime, timedelta
        >>> base = datetime(2024, 1, 1)
        >>> readings = [(base + timedelta(hours=h), 10.0) for h in range(25)]
        >>> calculate_hdd_from_readings(readings, base_temp=18.0)
        8.0  # 1 day at 10°C with 18°C base = 8 HDD

    """
    if len(readings) < 2:
        return 0.0

    sorted_readings = sorted(readings, key=lambda x: x[0])
    total_hdd = 0.0

    for i in range(len(sorted_readings) - 1):
        current_time, current_temp = sorted_readings[i]
        next_time, next_temp = sorted_readings[i + 1]

        # Calculate interval duration in days
        interval_seconds = (next_time - current_time).total_seconds()
        interval_days = interval_seconds / (24 * 3600)

        # Skip very short intervals to avoid numerical issues
        if interval_days < MIN_INTERVAL_DAYS:
            continue

        # Trapezoidal rule: average of deficit at start and end of interval
        current_deficit = max(0.0, base_temp - current_temp)
        next_deficit = max(0.0, base_temp - next_temp)
        avg_deficit = (current_deficit + next_deficit) / 2

        total_hdd += avg_deficit * interval_days

    return round(total_hdd, 1)


def calculate_cdd_from_readings(
    readings: Sequence[TemperatureReading],
    base_temp: float,
) -> float:
    """Calculate Cooling Degree Days using numerical integration.

    Uses the trapezoidal rule to integrate temperature excess over time.
    Only periods where temperature is above the base temperature contribute
    to the CDD total.

    Args:
        readings: Sequence of (timestamp, temperature) tuples.
                  Timestamps should be datetime objects.
                  Temperatures should be in consistent units (°C or °F).
        base_temp: Base/reference temperature in same units as readings.
                   Common values: 18°C (65°F) for cooling.

    Returns:
        Calculated CDD value rounded to 1 decimal place.
        Returns 0.0 if fewer than 2 readings provided.

    Example:
        >>> from datetime import datetime, timedelta
        >>> base = datetime(2024, 7, 1)
        >>> readings = [(base + timedelta(hours=h), 28.0) for h in range(25)]
        >>> calculate_cdd_from_readings(readings, base_temp=18.0)
        10.0  # 1 day at 28°C with 18°C base = 10 CDD

    """
    if len(readings) < 2:
        return 0.0

    sorted_readings = sorted(readings, key=lambda x: x[0])
    total_cdd = 0.0

    for i in range(len(sorted_readings) - 1):
        current_time, current_temp = sorted_readings[i]
        next_time, next_temp = sorted_readings[i + 1]

        # Calculate interval duration in days
        interval_seconds = (next_time - current_time).total_seconds()
        interval_days = interval_seconds / (24 * 3600)

        # Skip very short intervals to avoid numerical issues
        if interval_days < MIN_INTERVAL_DAYS:
            continue

        # Trapezoidal rule: average of excess at start and end of interval
        current_excess = max(0.0, current_temp - base_temp)
        next_excess = max(0.0, next_temp - base_temp)
        avg_excess = (current_excess + next_excess) / 2

        total_cdd += avg_excess * interval_days

    return round(total_cdd, 1)
