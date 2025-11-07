"""The Heating & Cooling Degree Days integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change

from .const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    CONF_WEATHER_ENTITY,
    DEFAULT_INCLUDE_COOLING,
    DEFAULT_INCLUDE_MONTHLY,
    DEFAULT_INCLUDE_WEEKLY,
    DOMAIN,
)
from .coordinator import HDDDataUpdateCoordinator
from .migrations import async_migrate_entity_unique_ids

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]

# Simple fixed titles in English
TITLE_STANDARD = "Heating Degree Days"
TITLE_WITH_COOLING = "Heating & Cooling Degree Days"


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

    # Use simple fixed titles based on configuration
    title = TITLE_WITH_COOLING if include_cooling else TITLE_STANDARD

    # Update the entry title if needed
    if entry.title != title:
        _LOGGER.debug("Updating integration title to: %s", title)
        hass.config_entries.async_update_entry(entry, title=title)

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
            weather_entity=entry.data.get(CONF_WEATHER_ENTITY),
        )

        # Load stored data before first refresh
        _LOGGER.debug("Loading stored data for coordinator")
        await coordinator.async_load_stored_data()

        # Do the initial data refresh
        _LOGGER.debug("Performing initial data refresh for coordinator")
        await coordinator.async_config_entry_first_refresh()

        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = coordinator

        # Migrate old entities with old unique_id format to new format
        # This must be done BEFORE setting up platforms to avoid conflicts
        await async_migrate_entity_unique_ids(hass, entry)

        # Set up listener for weather entity changes if configured
        weather_entity = entry.data.get(CONF_WEATHER_ENTITY)
        if weather_entity:

            @callback
            def async_weather_state_changed(entity_id, old_state, new_state):
                """Handle weather entity state changes."""
                if new_state is None:
                    return
                # Trigger coordinator refresh when weather forecast updates
                _LOGGER.debug(
                    "Weather entity %s state changed, triggering coordinator refresh",
                    entity_id,
                )
                hass.async_create_task(coordinator.async_request_refresh())

            # Listen for changes to the weather entity
            async_track_state_change(hass, weather_entity, async_weather_state_changed)
            _LOGGER.debug(
                "Registered state change listener for weather entity %s", weather_entity
            )

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
