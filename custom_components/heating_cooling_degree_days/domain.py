"""Pure domain logic for Heating and Cooling Degree Days calculations.

This module contains only pure functions with no Home Assistant dependencies.
All functions are synchronous and can be tested without any mocking.
"""

from datetime import datetime
import logging

_LOGGER = logging.getLogger(__name__)

# Minimum interval duration in days (~1 minute) to avoid numerical issues
MIN_INTERVAL_DAYS = 0.0007


def calculate_hdd_from_readings(
    readings: list[tuple[datetime, float]], base_temp: float
) -> float:
    """Calculate HDD using numerical integration of temperature data.

    The integration method consists of:
    1. Collecting detailed temperature readings throughout the day
    2. For each time interval, calculating the duration during which the temperature
       was below the base temperature
    3. Calculating the average temperature difference from the base temperature for that interval
    4. Multiplying the duration and temperature difference to get the degree-days for that interval
    5. Summing all interval degree-days to get the total for the day

    Args:
        readings: List of tuples containing (timestamp, temperature)
        base_temp: Base temperature for HDD calculation

    Returns:
        float: Calculated HDD value rounded to 1 decimal place

    """
    if len(readings) < 2:
        _LOGGER.debug("Insufficient temperature readings for HDD calculation")
        return 0.0

    # Sort readings by timestamp
    sorted_readings = sorted(readings, key=lambda x: x[0])

    start_time = sorted_readings[0][0]
    end_time = sorted_readings[-1][0]
    total_duration = (end_time - start_time).total_seconds() / 3600  # in hours

    _LOGGER.debug(
        "Calculating HDD from %d readings spanning %.1f hours (%.2f days)",
        len(sorted_readings),
        total_duration,
        total_duration / 24,
    )

    # Calculate HDD using numerical integration (trapezoidal rule)
    total_hdd = 0.0
    significant_intervals = 0

    for i in range(len(sorted_readings) - 1):
        current_time, current_temp = sorted_readings[i]
        next_time, next_temp = sorted_readings[i + 1]

        # Calculate the interval duration in days
        interval_days = (next_time - current_time).total_seconds() / (24 * 3600)

        # Skip extremely short intervals to avoid numerical issues
        if interval_days < MIN_INTERVAL_DAYS:
            continue

        # Calculate the average temperature deficit using trapezoidal rule
        current_deficit = max(0.0, base_temp - current_temp)
        next_deficit = max(0.0, base_temp - next_temp)
        avg_deficit = (current_deficit + next_deficit) / 2

        # Accumulate degree-days
        interval_hdd = avg_deficit * interval_days
        total_hdd += interval_hdd

        if avg_deficit > 0:
            significant_intervals += 1

    if len(sorted_readings) > 1:
        contribution_percentage = (significant_intervals / (len(sorted_readings) - 1)) * 100
        _LOGGER.debug(
            "HDD calculation: %.1f degree-days from %d/%d intervals (%.1f%% contributed)",
            total_hdd,
            significant_intervals,
            len(sorted_readings) - 1,
            contribution_percentage,
        )

    return round(total_hdd, 1)


def calculate_cdd_from_readings(
    readings: list[tuple[datetime, float]], base_temp: float
) -> float:
    """Calculate CDD using numerical integration of temperature data.

    The integration method consists of:
    1. Collecting detailed temperature readings throughout the day
    2. For each time interval, calculating the duration during which the temperature
       was above the base temperature
    3. Calculating the average temperature difference from the base temperature for that interval
    4. Multiplying the duration and temperature difference to get the degree-days for that interval
    5. Summing all interval degree-days to get the total for the day

    Args:
        readings: List of tuples containing (timestamp, temperature)
        base_temp: Base temperature for CDD calculation

    Returns:
        float: Calculated CDD value rounded to 1 decimal place

    """
    if len(readings) < 2:
        _LOGGER.debug("Insufficient temperature readings for CDD calculation")
        return 0.0

    # Sort readings by timestamp
    sorted_readings = sorted(readings, key=lambda x: x[0])

    start_time = sorted_readings[0][0]
    end_time = sorted_readings[-1][0]
    total_duration = (end_time - start_time).total_seconds() / 3600  # in hours

    _LOGGER.debug(
        "Calculating CDD from %d readings spanning %.1f hours (%.2f days)",
        len(sorted_readings),
        total_duration,
        total_duration / 24,
    )

    # Calculate CDD using numerical integration (trapezoidal rule)
    total_cdd = 0.0
    significant_intervals = 0

    for i in range(len(sorted_readings) - 1):
        current_time, current_temp = sorted_readings[i]
        next_time, next_temp = sorted_readings[i + 1]

        # Calculate the interval duration in days
        interval_days = (next_time - current_time).total_seconds() / (24 * 3600)

        # Skip extremely short intervals to avoid numerical issues
        if interval_days < MIN_INTERVAL_DAYS:
            continue

        # Calculate the average temperature excess using trapezoidal rule
        current_excess = max(0.0, current_temp - base_temp)
        next_excess = max(0.0, next_temp - base_temp)
        avg_excess = (current_excess + next_excess) / 2

        # Accumulate degree-days
        interval_cdd = avg_excess * interval_days
        total_cdd += interval_cdd

        if avg_excess > 0:
            significant_intervals += 1

    if len(sorted_readings) > 1:
        contribution_percentage = (significant_intervals / (len(sorted_readings) - 1)) * 100
        _LOGGER.debug(
            "CDD calculation: %.1f degree-days from %d/%d intervals (%.1f%% contributed)",
            total_cdd,
            significant_intervals,
            len(sorted_readings) - 1,
            contribution_percentage,
        )

    return round(total_cdd, 1)
