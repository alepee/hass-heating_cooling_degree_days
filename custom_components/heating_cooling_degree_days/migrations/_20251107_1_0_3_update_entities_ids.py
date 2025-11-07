"""Migration: Update entity unique_ids to include entry_id.

Migration date: 2025-11-07
Version: 1.0.3

This migration updates entity unique_ids from the old format to the new format:
- Old format: {DOMAIN}_{sensor_type}
- New format: {DOMAIN}_{entry_id}_{sensor_type}

This change prevents conflicts when multiple instances of the integration are configured.
The migration preserves entity history by updating the unique_id instead of removing
and recreating entities.
"""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import (
    DOMAIN,
    SENSOR_TYPE_CDD_DAILY,
    SENSOR_TYPE_CDD_ESTIMATED_TODAY,
    SENSOR_TYPE_CDD_ESTIMATED_TOMORROW,
    SENSOR_TYPE_CDD_MONTHLY,
    SENSOR_TYPE_CDD_WEEKLY,
    SENSOR_TYPE_HDD_DAILY,
    SENSOR_TYPE_HDD_ESTIMATED_TODAY,
    SENSOR_TYPE_HDD_ESTIMATED_TOMORROW,
    SENSOR_TYPE_HDD_MONTHLY,
    SENSOR_TYPE_HDD_WEEKLY,
)

_LOGGER = logging.getLogger(__name__)


async def async_migrate_entity_unique_ids(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Migrate old entities with old unique_id format to new format.

    Old format: {DOMAIN}_{sensor_type}
    New format: {DOMAIN}_{entry_id}_{sensor_type}

    This function updates the unique_id of old entities that belong to this config entry
    to preserve their history. It only updates entities if:
    1. They have the old unique_id format
    2. They belong to this config entry (via config_entry_id)
    3. The new unique_id doesn't already exist
    """
    ent_reg = er.async_get(hass)

    # List of all possible sensor types (old format)
    old_sensor_types = [
        SENSOR_TYPE_HDD_DAILY,
        SENSOR_TYPE_HDD_WEEKLY,
        SENSOR_TYPE_HDD_MONTHLY,
        SENSOR_TYPE_CDD_DAILY,
        SENSOR_TYPE_CDD_WEEKLY,
        SENSOR_TYPE_CDD_MONTHLY,
        SENSOR_TYPE_HDD_ESTIMATED_TODAY,
        SENSOR_TYPE_HDD_ESTIMATED_TOMORROW,
        SENSOR_TYPE_CDD_ESTIMATED_TODAY,
        SENSOR_TYPE_CDD_ESTIMATED_TOMORROW,
    ]

    # Find and migrate old entities with old unique_id format that belong to this entry
    old_unique_ids = [f"{DOMAIN}_{sensor_type}" for sensor_type in old_sensor_types]

    migrated_count = 0
    for old_unique_id in old_unique_ids:
        # Find entity with old unique_id
        old_entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, old_unique_id)
        if old_entity_id:
            # Get the entity registry entry
            old_entity_entry = ent_reg.async_get(old_entity_id)
            if old_entity_entry:
                # Only migrate if it belongs to this config entry
                # We check config_entry_id to ensure we only migrate entities from this entry
                if old_entity_entry.config_entry_id == entry.entry_id:
                    # Extract sensor_type from old_unique_id (format: {DOMAIN}_{sensor_type})
                    sensor_type = old_unique_id.replace(f"{DOMAIN}_", "", 1)
                    new_unique_id = f"{DOMAIN}_{entry.entry_id}_{sensor_type}"

                    # Check if new entity with new format already exists
                    new_entity_id = ent_reg.async_get_entity_id(
                        "sensor", DOMAIN, new_unique_id
                    )
                    if new_entity_id:
                        # New entity already exists, remove old one to avoid duplicates
                        _LOGGER.info(
                            "Removing old entity %s with unique_id %s (new entity %s already exists)",
                            old_entity_id,
                            old_unique_id,
                            new_entity_id,
                        )
                        ent_reg.async_remove(old_entity_id)
                        migrated_count += 1
                    else:
                        # Update the unique_id to preserve history
                        try:
                            ent_reg.async_update_entity(
                                old_entity_id, new_unique_id=new_unique_id
                            )
                            _LOGGER.info(
                                "Migrated entity %s from unique_id %s to %s (preserving history)",
                                old_entity_id,
                                old_unique_id,
                                new_unique_id,
                            )
                            migrated_count += 1
                        except ValueError as ex:
                            # Unique ID already taken or other error
                            _LOGGER.warning(
                                "Could not migrate entity %s: %s. Removing old entity.",
                                old_entity_id,
                                ex,
                            )
                            ent_reg.async_remove(old_entity_id)
                            migrated_count += 1

    if migrated_count > 0:
        _LOGGER.info(
            "Migration completed: migrated %d entities to new unique_id format for entry %s",
            migrated_count,
            entry.entry_id,
        )

