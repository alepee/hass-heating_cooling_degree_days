"""Heating and Cooling Degree Days calculation functions.

This module provides the interface between Home Assistant and the pure domain logic.
- Pure calculation functions are imported from domain.py
- HA-specific functions (async, using recorder) are defined here
"""

from datetime import datetime
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.core import HomeAssistant

# Import pure domain functions (no HA dependencies)
from .domain import (
    calculate_cdd_from_readings,
    calculate_hdd_from_readings,
)

__all__ = [
    "calculate_hdd_from_readings",
    "calculate_cdd_from_readings",
    "get_temperature_readings",
    "async_calculate_hdd",
    "async_calculate_cdd",
]

_LOGGER = logging.getLogger(__name__)


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
        List of (timestamp, temperature) tuples

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
            if state.state in ("unknown", "unavailable"):
                invalid_states += 1
                continue

            try:
                temp_value = float(state.state)
                readings.append((state.last_updated, temp_value))
            except (ValueError, TypeError):
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
