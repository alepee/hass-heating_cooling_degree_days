"""Recorder access and per-state temperature normalization."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
import logging
from math import isfinite

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .degree_days import TemperatureSample

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TemperatureHistory:
    """Normalized samples and the fallback used for states without a unit."""

    samples: tuple[TemperatureSample, ...]
    assumed_unit: str | None
    assumed_unit_count: int


def normalize_temperature_states(
    states: Iterable[State], calculation_unit: str, source_unit: str | None = None
) -> TemperatureHistory:
    """Convert each state in its own unit, preserving invalid states as gaps."""
    if calculation_unit not in TemperatureConverter.VALID_UNITS:
        raise ValueError(f"Unsupported calculation unit: {calculation_unit}")

    fallback_unit = source_unit or calculation_unit
    samples = []
    assumed_unit_count = 0
    for state in states:
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if not unit:
            unit = fallback_unit
            assumed_unit_count += 1

        temperature = None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            pass
        else:
            if isfinite(value) and unit in TemperatureConverter.VALID_UNITS:
                converted = TemperatureConverter.convert(value, unit, calculation_unit)
                if isfinite(converted):
                    temperature = converted
        samples.append(TemperatureSample(state.last_updated, temperature))

    return TemperatureHistory(
        samples=tuple(samples),
        assumed_unit=fallback_unit if assumed_unit_count else None,
        assumed_unit_count=assumed_unit_count,
    )


async def get_temperature_history(
    hass: HomeAssistant,
    start_time: datetime,
    end_time: datetime,
    entity_id: str,
    calculation_unit: str,
) -> TemperatureHistory:
    """Fetch the start-state and all changes before end, including unit changes.

    Empty history is a successful query with zero coverage. Recorder failures
    propagate as UpdateFailed so a cached measurement cannot look fresh.
    """
    current_state = hass.states.get(entity_id)
    source_unit = (
        current_state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if current_state
        else None
    )
    try:
        history = await get_instance(hass).async_add_executor_job(
            partial(
                get_significant_states,
                hass,
                dt_util.as_utc(start_time),
                dt_util.as_utc(end_time),
                [entity_id],
                include_start_time_state=True,
                significant_changes_only=False,
                minimal_response=False,
                no_attributes=False,
            )
        )
    except Exception as err:
        raise UpdateFailed(
            f"Could not read temperature history for {entity_id}"
        ) from err

    result = normalize_temperature_states(
        history.get(entity_id, ()), calculation_unit, source_unit
    )
    if result.assumed_unit_count:
        _LOGGER.debug(
            "Assumed %s for %d historical states without a unit on %s",
            result.assumed_unit,
            result.assumed_unit_count,
            entity_id,
        )
    return result
