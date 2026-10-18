"""The Heating & Cooling Degree Days integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_change

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
    HISTORICAL_SENSOR_TYPES,
    get_enabled_sensor_types,
)
from .coordinator import HDDDataUpdateCoordinator, async_remove_stored_data

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

type HDDConfigEntry = ConfigEntry[HDDDataUpdateCoordinator]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current version."""
    if entry.version > 2:
        # Unknown future version — cannot migrate
        return False

    if entry.version == 1:
        _LOGGER.info("Migrating config entry %s from version 1 to 2", entry.entry_id)

        old_prefix = f"{DOMAIN}_"

        @callback
        def _migrate_unique_id(entity_entry: er.RegistryEntry) -> dict | None:
            """Rewrite static v1 unique_ids to per-entry unique_ids."""
            if entity_entry.unique_id.startswith(old_prefix):
                sensor_type = entity_entry.unique_id.removeprefix(old_prefix)
                return {"new_unique_id": f"{entry.entry_id}_{sensor_type}"}
            # Already migrated or unknown format: leave untouched
            return None

        await er.async_migrate_entries(hass, entry.entry_id, _migrate_unique_id)
        hass.config_entries.async_update_entry(entry, version=2)
        _LOGGER.info("Migration of entry %s to version 2 complete", entry.entry_id)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: HDDConfigEntry) -> bool:
    """Set up Heating & Cooling Degree Days from a config entry."""
    _LOGGER.info(
        "Setting up Heating & Cooling Degree Days integration with ID: %s",
        entry.entry_id,
    )

    # Check if options are in the entry data, if not set defaults
    include_cooling = entry.data.get(CONF_INCLUDE_COOLING, DEFAULT_INCLUDE_COOLING)
    include_weekly = entry.data.get(CONF_INCLUDE_WEEKLY, DEFAULT_INCLUDE_WEEKLY)
    include_monthly = entry.data.get(CONF_INCLUDE_MONTHLY, DEFAULT_INCLUDE_MONTHLY)

    # Log the configuration
    _LOGGER.debug(
        "Configuration: temperature_sensor=%s, base_temperature=%.1f, temperature_unit=%s, "
        "include_cooling=%s, include_weekly=%s, include_monthly=%s",
        entry.data[CONF_TEMPERATURE_SENSOR],
        entry.data[CONF_BASE_TEMPERATURE],
        entry.data[CONF_TEMPERATURE_UNIT],
        "Yes" if include_cooling else "No",
        "Yes" if include_weekly else "No",
        "Yes" if include_monthly else "No",
    )

    coordinator = HDDDataUpdateCoordinator(
        hass=hass,
        temp_entity=entry.data[CONF_TEMPERATURE_SENSOR],
        base_temp=entry.data[CONF_BASE_TEMPERATURE],
        temperature_unit=entry.data[CONF_TEMPERATURE_UNIT],
        entry_id=entry.entry_id,
        include_cooling=include_cooling,
        include_weekly=include_weekly,
        include_monthly=include_monthly,
    )

    await coordinator.async_load_stored_data()
    # Let HA handle ConfigEntryNotReady and authentication/setup failures.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    setup_complete = False
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        # A reconfiguration may have disabled sensor types: drop their entities
        # instead of leaving them behind as unavailable
        _async_remove_disabled_entities(
            hass,
            entry,
            get_enabled_sensor_types(include_cooling, include_weekly, include_monthly),
        )

        # This listener owns reloads, including title changes and reconfiguration.
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))
        entry.async_on_unload(
            async_track_time_change(
                hass, coordinator.async_midnight_refresh, hour=0, minute=0, second=5
            )
        )
        setup_complete = True
    finally:
        if not setup_complete:
            # Forwarding may have added entities before raising or being cancelled.
            try:
                await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
            finally:
                del entry.runtime_data

    return True


@callback
def _async_remove_disabled_entities(
    hass: HomeAssistant, entry: HDDConfigEntry, enabled_types: tuple[str, ...]
) -> None:
    """Remove registry entries for sensor types the configuration no longer exposes."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"

    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity_entry.domain != Platform.SENSOR
            or entity_entry.platform != DOMAIN
            or not entity_entry.unique_id.startswith(prefix)
        ):
            continue
        sensor_type = entity_entry.unique_id.removeprefix(prefix)
        if sensor_type in HISTORICAL_SENSOR_TYPES and sensor_type not in enabled_types:
            _LOGGER.info(
                "Removing %s: sensor type %s is disabled in the configuration",
                entity_entry.entity_id,
                sensor_type,
            )
            registry.async_remove(entity_entry.entity_id)


async def _async_update_listener(hass: HomeAssistant, entry: HDDConfigEntry) -> None:
    """Reload the config entry when it is updated (e.g. renamed in the UI)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: HDDConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info(
        "Unloading Heating & Cooling Degree Days integration with ID: %s",
        entry.entry_id,
    )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        _LOGGER.debug("Successfully unloaded platforms")
        _LOGGER.info("Integration unloaded successfully")
    else:
        _LOGGER.warning("Failed to unload one or more platforms")

    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: HDDConfigEntry) -> None:
    """Remove only this entry's persistent history when the entry is deleted."""
    await async_remove_stored_data(hass, entry.entry_id)
