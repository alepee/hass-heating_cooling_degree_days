"""The Heating & Cooling Degree Days integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

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
)
from .coordinator import HDDDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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

    try:
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

        # Load stored data before first refresh
        _LOGGER.debug("Loading stored data for coordinator")
        await coordinator.async_load_stored_data()

        # Do the initial data refresh
        _LOGGER.debug("Performing initial data refresh for coordinator")
        await coordinator.async_config_entry_first_refresh()

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = coordinator

        # Reload the entry when it is updated (e.g. renamed in the UI) so the
        # service device name and the sensor friendly-names track the title.
        entry.async_on_unload(entry.add_update_listener(_async_update_listener))

        # Set up all the platforms
        _LOGGER.debug("Setting up platforms: %s", PLATFORMS)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        _LOGGER.info(
            "Heating & Cooling Degree Days integration setup completed successfully"
        )
        return True

    except Exception as ex:
        _LOGGER.exception(
            "Error setting up Heating & Cooling Degree Days integration: %s",
            str(ex),
        )
        return False


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when it is updated (e.g. renamed in the UI)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info(
        "Unloading Heating & Cooling Degree Days integration with ID: %s",
        entry.entry_id,
    )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        _LOGGER.debug("Successfully unloaded platforms")
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.info("Integration unloaded successfully")
    else:
        _LOGGER.warning("Failed to unload one or more platforms")

    return unload_ok
