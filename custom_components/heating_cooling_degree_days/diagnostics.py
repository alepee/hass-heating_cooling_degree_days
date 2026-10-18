"""Redacted calculation and coverage diagnostics, without raw source history."""

from copy import deepcopy
from datetime import timedelta
import math
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
    __version__ as HA_VERSION,
)
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from . import HDDConfigEntry
from .const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    DEFAULT_INCLUDE_COOLING,
    DEFAULT_INCLUDE_MONTHLY,
    DEFAULT_INCLUDE_WEEKLY,
    DOMAIN,
    get_enabled_sensor_types,
)
from .coordinator import STORAGE_VERSION
from .source import CONF_SOURCE_REGISTRY_ID

TO_REDACT = {
    CONF_TEMPERATURE_SENSOR,
    CONF_SOURCE_REGISTRY_ID,
    "entity_id",
    "unique_id",
    "name",
    "title",
}
LEDGER_DAYS = 35


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HDDConfigEntry
) -> dict[str, Any]:
    """Return bounded summaries, including when an entry has no running coordinator."""
    integration = await async_get_integration(hass, DOMAIN)
    source = hass.states.get(entry.data[CONF_TEMPERATURE_SENSOR])
    availability = "missing"
    source_unit = None
    if source is not None:
        source_unit = source.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if source.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            availability = source.state
        else:
            try:
                availability = (
                    "available" if math.isfinite(float(source.state)) else "invalid"
                )
            except ValueError:
                availability = "invalid"
    # Do not export arbitrary source attributes or free-form state strings.
    if source_unit not in set(UnitOfTemperature):
        source_unit = None
    coordinator = getattr(entry, "runtime_data", None)
    result = {
        "versions": {"home_assistant": HA_VERSION, "integration": integration.version},
        "entry": async_redact_data(
            {"title": entry.title, "data": entry.data, "options": entry.options},
            TO_REDACT,
        ),
        "calculation": {
            "unit": entry.data[CONF_TEMPERATURE_UNIT],
            "base_temperature": entry.data[CONF_BASE_TEMPERATURE],
            "enabled_sensor_types": list(
                get_enabled_sensor_types(
                    entry.data.get(CONF_INCLUDE_COOLING, DEFAULT_INCLUDE_COOLING),
                    entry.data.get(CONF_INCLUDE_WEEKLY, DEFAULT_INCLUDE_WEEKLY),
                    entry.data.get(CONF_INCLUDE_MONTHLY, DEFAULT_INCLUDE_MONTHLY),
                )
            ),
        },
        "source": {"unit": source_unit, "availability": availability},
        "refresh": {"last_update_success": None, "last_attempt": None},
        "ledger": None,
        "periods": {},
    }
    if coordinator is None:
        return result

    today = dt_util.now().date()
    cutoff = today - timedelta(days=LEDGER_DAYS)
    result["refresh"] = {
        "last_update_success": (
            coordinator.last_update_success if coordinator.last_refresh_time else None
        ),
        "last_attempt": (
            coordinator.last_refresh_time.isoformat()
            if coordinator.last_refresh_time
            else None
        ),
    }
    result["ledger"] = {
        "storage_version": STORAGE_VERSION,
        "days_count": len(coordinator.ledger),
        "window_start": cutoff.isoformat(),
        "window_end": (today - timedelta(days=1)).isoformat(),
        "days": {
            day.isoformat(): {
                "coverage_seconds": record.coverage_seconds,
                "window_seconds": record.window_seconds,
                "coverage": (
                    record.coverage_seconds / record.window_seconds
                    if record.coverage_seconds is not None and record.window_seconds
                    else None
                ),
                "legacy": record.legacy,
                "complete": record.complete,
                "last_attempt": (
                    dt_util.utc_from_timestamp(record.last_attempt).isoformat()
                    if record.last_attempt
                    else None
                ),
            }
            for day, record in sorted(coordinator.ledger.items())
            if cutoff <= day < today
        },
    }
    result["periods"] = deepcopy(
        {
            key: {
                "value": value,
                "attributes": coordinator.period_attributes.get(key, {}),
            }
            for key, value in (coordinator.data or {}).items()
        }
    )
    return result
