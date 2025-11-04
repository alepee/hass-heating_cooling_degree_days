"""Heating and Cooling Degree Days calculation functions."""

from datetime import datetime
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


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
        float: Calculated HDD value

    """
    if not readings:
        _LOGGER.debug("No temperature readings provided for HDD calculation")
        return 0

    # Sort readings by timestamp
    readings.sort(key=lambda x: x[0])

    start_time = readings[0][0]
    end_time = readings[-1][0]
    total_duration = (end_time - start_time).total_seconds() / 3600  # in hours

    _LOGGER.debug(
        "Calculating HDD from %d readings spanning %.1f hours (%.2f days)",
        len(readings),
        total_duration,
        total_duration / 24,
    )

    # Calculate HDD using numerical integration
    total_hdd = 0
    significant_intervals = 0  # Count intervals with temperature below base temp

    for i in range(len(readings) - 1):
        current_time, current_temp = readings[i]
        next_time, next_temp = readings[i + 1]

        # 2. Calculate the interval duration in days
        interval_days = (next_time - current_time).total_seconds() / (24 * 3600)

        # Skip extremely short intervals (less than 1 minute) to avoid numerical issues
        if interval_days < 0.0007:  # ~1 minute in days
            continue

        # 3. Calculate the average temperature difference over the interval
        # using trapezoidal rule for integration
        current_deficit = max(0, base_temp - current_temp)
        next_deficit = max(0, base_temp - next_temp)
        avg_deficit = (current_deficit + next_deficit) / 2

        # 4. Multiply duration and temperature difference
        interval_hdd = avg_deficit * interval_days

        # 5. Add to total
        total_hdd += interval_hdd

        # Track significant intervals for debugging
        if avg_deficit > 0:
            significant_intervals += 1

    # Log the percentage of intervals that contributed to the HDD
    if len(readings) > 1:
        contribution_percentage = (significant_intervals / (len(readings) - 1)) * 100
        _LOGGER.debug(
            "HDD calculation: %.1f degree-days from %d/%d intervals (%.1f%% contributed)",
            total_hdd,
            significant_intervals,
            len(readings) - 1,
            contribution_percentage,
        )

    # Round to 1 decimal place to avoid excessive precision
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
    if not readings:
        _LOGGER.debug("No temperature readings provided for CDD calculation")
        return 0

    # Sort readings by timestamp
    readings.sort(key=lambda x: x[0])

    start_time = readings[0][0]
    end_time = readings[-1][0]
    total_duration = (end_time - start_time).total_seconds() / 3600  # in hours

    _LOGGER.debug(
        "Calculating CDD from %d readings spanning %.1f hours (%.2f days)",
        len(readings),
        total_duration,
        total_duration / 24,
    )

    # Calculate CDD using numerical integration
    total_cdd = 0
    significant_intervals = 0  # Count intervals with temperature above base temp

    for i in range(len(readings) - 1):
        current_time, current_temp = readings[i]
        next_time, next_temp = readings[i + 1]

        # 2. Calculate the interval duration in days
        interval_days = (next_time - current_time).total_seconds() / (24 * 3600)

        # Skip extremely short intervals (less than 1 minute) to avoid numerical issues
        if interval_days < 0.0007:  # ~1 minute in days
            continue

        # 3. Calculate the average temperature difference over the interval
        # using trapezoidal rule for integration
        # For CDD, we measure how much the temperature exceeds the base temperature
        current_excess = max(0, current_temp - base_temp)
        next_excess = max(0, next_temp - base_temp)
        avg_excess = (current_excess + next_excess) / 2

        # 4. Multiply duration and temperature difference
        interval_cdd = avg_excess * interval_days

        # 5. Add to total
        total_cdd += interval_cdd

        # Track significant intervals for debugging
        if avg_excess > 0:
            significant_intervals += 1

    # Log the percentage of intervals that contributed to the CDD
    if len(readings) > 1:
        contribution_percentage = (significant_intervals / (len(readings) - 1)) * 100
        _LOGGER.debug(
            "CDD calculation: %.1f degree-days from %d/%d intervals (%.1f%% contributed)",
            total_cdd,
            significant_intervals,
            len(readings) - 1,
            contribution_percentage,
        )

    # Round to 1 decimal place to avoid excessive precision
    return round(total_cdd, 1)


async def get_temperature_readings(
    hass: HomeAssistant,
    start_time: datetime,
    end_time: datetime,
    entity_id: str,
) -> list[tuple[datetime, float]]:
    """Get temperature readings from Home Assistant history.

    Args:
        hass: Home Assistant instance
        start_time: Start time for data collection
        end_time: End time for data collection
        entity_id: Entity ID of the temperature sensor

    Returns:
        List[Tuple[datetime, float]]: List of (timestamp, temperature) tuples

    """
    _LOGGER.debug(
        "Fetching temperature history for %s from %s to %s",
        entity_id,
        start_time.isoformat(),
        end_time.isoformat(),
    )

    try:
        temp_history = await get_instance(hass).async_add_executor_job(
            get_significant_states, hass, start_time, end_time, [entity_id]
        )

        if not temp_history or entity_id not in temp_history:
            _LOGGER.warning(
                "No history found for entity %s in the specified time range", entity_id
            )
            return []

        # Filter and prepare valid temperature readings with timestamps
        readings = []
        invalid_states = 0

        for state in temp_history[entity_id]:
            if (
                state.state not in ("unknown", "unavailable")
                and state.state.replace(".", "", 1).isdigit()
            ):
                readings.append((state.last_updated, float(state.state)))
            else:
                invalid_states += 1

        if invalid_states:
            _LOGGER.debug(
                "Filtered out %d invalid states (unknown, unavailable, or non-numeric) from %s",
                invalid_states,
                entity_id,
            )

        if not readings:
            _LOGGER.warning(
                "No valid temperature readings found for %s after filtering", entity_id
            )
        else:
            _LOGGER.debug("Retrieved %d valid temperature readings", len(readings))

        return readings

    except Exception as ex:
        _LOGGER.error(
            "Error fetching temperature history for %s: %s", entity_id, str(ex)
        )
        return []


async def async_calculate_hdd(
    hass: HomeAssistant,
    start_time: datetime,
    end_time: datetime,
    entity_id: str,
    base_temp: float,
) -> float:
    """Calculate HDD for a given period.

    This function serves as a bridge between Home Assistant's infrastructure
    and the pure HDD calculation logic.
    """
    _LOGGER.debug(
        "Starting HDD calculation for %s from %s to %s with base temp %.1f",
        entity_id,
        start_time.isoformat(),
        end_time.isoformat(),
        base_temp,
    )

    readings = await get_temperature_readings(hass, start_time, end_time, entity_id)
    result = calculate_hdd_from_readings(readings, base_temp)

    _LOGGER.debug("HDD calculation result: %.2f degree-days", result)
    return result


async def async_calculate_cdd(
    hass: HomeAssistant,
    start_time: datetime,
    end_time: datetime,
    entity_id: str,
    base_temp: float,
) -> float:
    """Calculate CDD for a given period.

    This function serves as a bridge between Home Assistant's infrastructure
    and the pure CDD calculation logic.
    """
    _LOGGER.debug(
        "Starting CDD calculation for %s from %s to %s with base temp %.1f",
        entity_id,
        start_time.isoformat(),
        end_time.isoformat(),
        base_temp,
    )

    readings = await get_temperature_readings(hass, start_time, end_time, entity_id)
    result = calculate_cdd_from_readings(readings, base_temp)

    _LOGGER.debug("CDD calculation result: %.2f degree-days", result)
    return result
