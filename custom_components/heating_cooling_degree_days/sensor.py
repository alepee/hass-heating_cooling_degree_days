"""Sensor platform for heating_cooling_degree_days."""

import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HDDConfigEntry
from .const import (
    ATTR_BASE_TEMPERATURE,
    DOMAIN,
    SENSOR_TYPE_CDD_DAILY,
    SENSOR_TYPE_HDD_DAILY,
    get_enabled_sensor_types,
)
from .coordinator import HDDDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HDDConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HDD and CDD sensors."""
    coordinator = entry.runtime_data

    _LOGGER.info(
        "Setting up degree days sensors with temperature sensor %s and base temperature %.1f°%s",
        coordinator.temp_entity,
        coordinator.base_temp,
        coordinator.temperature_unit,
    )

    sensors = [
        DegreeDegreeSensor(coordinator, entry, sensor_type)
        for sensor_type in get_enabled_sensor_types(
            coordinator.include_cooling,
            coordinator.include_weekly,
            coordinator.include_monthly,
        )
    ]

    async_add_entities(sensors)
    _LOGGER.info("Added %d degree days sensors", len(sensors))


class DegreeDegreeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a degree days sensor (HDD or CDD)."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HDDDataUpdateCoordinator,
        entry: HDDConfigEntry,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        # Daily values change once per day, so measurement statistics keep
        # their long-term history; period totals accumulate within the period.
        self._attr_state_class = (
            SensorStateClass.MEASUREMENT
            if sensor_type in (SENSOR_TYPE_HDD_DAILY, SENSOR_TYPE_CDD_DAILY)
            else SensorStateClass.TOTAL_INCREASING
        )
        self.sensor_type = sensor_type
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_translation_key = sensor_type

        # Group all sensors of this entry under one service device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

        # Set the unit of measurement based on temperature unit
        self._attr_native_unit_of_measurement = f"{coordinator.temperature_unit}·d"

        _LOGGER.debug(
            "Initialized degree days sensor %s with unit %s",
            self._attr_unique_id,
            self._attr_native_unit_of_measurement,
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            _LOGGER.warning("No data available for %s", self.entity_id)
            return None

        if self.sensor_type not in self.coordinator.data:
            _LOGGER.warning(
                "Sensor type %s not found in coordinator data for %s",
                self.sensor_type,
                self.entity_id,
            )
            return None

        value = self.coordinator.data[self.sensor_type]
        # Keep integration and stored totals unrounded; round only for display.
        if value is None:
            return None

        _LOGGER.debug(
            "Returning value for %s: %.1f %s",
            self.entity_id,
            value,
            self._attr_native_unit_of_measurement,
        )
        return round(value, 1)

    @property
    def extra_state_attributes(self):
        """Return metadata from the same completed refresh as the sensor value."""
        return {
            ATTR_BASE_TEMPERATURE: self.coordinator.base_temp,
            **self.coordinator.period_attributes.get(self.sensor_type, {}),
        }
