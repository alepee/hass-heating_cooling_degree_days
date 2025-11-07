"""Sensor platform for heating_cooling_degree_days."""

import calendar
from datetime import timedelta
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BASE_TEMPERATURE,
    ATTR_DATE_RANGE,
    ATTR_MEAN_TEMPERATURE,
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
from .coordinator import HDDDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the HDD and CDD sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    _LOGGER.info(
        "Setting up degree days sensors with temperature sensor %s and base temperature %.1f°%s",
        coordinator.temp_entity,
        coordinator.base_temp,
        coordinator.temperature_unit,
    )

    # Start with the daily HDD sensor which is always included
    sensors = [DegreeDegreeSensor(coordinator, SENSOR_TYPE_HDD_DAILY)]
    _LOGGER.debug("Created HDD daily sensor")

    # Add weekly and monthly HDD sensors if enabled
    if coordinator.include_weekly:
        sensors.append(DegreeDegreeSensor(coordinator, SENSOR_TYPE_HDD_WEEKLY))
        _LOGGER.debug("Created HDD weekly sensor")

    if coordinator.include_monthly:
        sensors.append(DegreeDegreeSensor(coordinator, SENSOR_TYPE_HDD_MONTHLY))
        _LOGGER.debug("Created HDD monthly sensor")

    # Add CDD sensors if enabled
    if coordinator.include_cooling:
        # Daily CDD sensor is always included if cooling is enabled
        sensors.append(DegreeDegreeSensor(coordinator, SENSOR_TYPE_CDD_DAILY))
        _LOGGER.debug("Created CDD daily sensor")

        # Add weekly and monthly CDD sensors if both cooling and respective period are enabled
        if coordinator.include_weekly:
            sensors.append(DegreeDegreeSensor(coordinator, SENSOR_TYPE_CDD_WEEKLY))
            _LOGGER.debug("Created CDD weekly sensor")

        if coordinator.include_monthly:
            sensors.append(DegreeDegreeSensor(coordinator, SENSOR_TYPE_CDD_MONTHLY))
            _LOGGER.debug("Created CDD monthly sensor")
    else:
        _LOGGER.debug("CDD sensors not enabled in configuration")

    # Add forecast sensors if weather entity is configured
    if coordinator.weather_entity:
        sensors.append(DegreeDegreeSensor(coordinator, SENSOR_TYPE_HDD_ESTIMATED_TODAY))
        _LOGGER.debug("Created HDD estimated today sensor")

        sensors.append(
            DegreeDegreeSensor(coordinator, SENSOR_TYPE_HDD_ESTIMATED_TOMORROW)
        )
        _LOGGER.debug("Created HDD estimated tomorrow sensor")

        if coordinator.include_cooling:
            sensors.append(
                DegreeDegreeSensor(coordinator, SENSOR_TYPE_CDD_ESTIMATED_TODAY)
            )
            _LOGGER.debug("Created CDD estimated today sensor")

            sensors.append(
                DegreeDegreeSensor(coordinator, SENSOR_TYPE_CDD_ESTIMATED_TOMORROW)
            )
            _LOGGER.debug("Created CDD estimated tomorrow sensor")
    else:
        _LOGGER.debug("Forecast sensors not enabled (no weather entity configured)")

    async_add_entities(sensors)
    _LOGGER.info("Added %d degree days sensors", len(sensors))


class DegreeDegreeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a degree days sensor (HDD or CDD)."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HDDDataUpdateCoordinator,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.sensor_type = sensor_type
        # Include entry_id in unique_id to avoid conflicts with multiple instances
        self._attr_unique_id = f"{DOMAIN}_{coordinator.entry_id}_{sensor_type}"
        self._attr_translation_key = sensor_type

        # Set entity_id based on type (HDD or CDD)
        if sensor_type.startswith("cdd_"):
            # CDD sensor
            self.entity_id = f"sensor.{sensor_type}"
            sensor_type_desc = "Cooling"
        else:
            # HDD sensor
            self.entity_id = f"sensor.{sensor_type}"
            sensor_type_desc = "Heating"

        # Set the unit of measurement based on temperature unit
        self._attr_native_unit_of_measurement = f"{coordinator.temperature_unit}·d"

        _LOGGER.debug(
            "Initialized %s Degree Days sensor: %s with unit %s",
            sensor_type_desc,
            self.entity_id,
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

        # Handle None values (e.g., when forecast data is unavailable)
        if value is None:
            _LOGGER.debug(
                "No data available for %s (forecast may be unavailable)",
                self.entity_id,
            )
            return None

        # Ensure value is rounded to 1 decimal place
        if isinstance(value, (int, float)):
            value = round(float(value), 1)

        _LOGGER.debug(
            "Returning value for %s: %.1f %s",
            self.entity_id,
            value,
            self._attr_native_unit_of_measurement,
        )
        return value

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        attrs = {
            ATTR_BASE_TEMPERATURE: self.coordinator.base_temp,
            ATTR_DATE_RANGE: self._get_date_range(),
        }

        # Only add mean temperature for daily sensors
        mean_temp = self._get_mean_temperature()
        if mean_temp is not None:
            attrs[ATTR_MEAN_TEMPERATURE] = mean_temp

        return attrs

    def _get_date_range(self):
        """Get the date range for the current value."""
        now = dt_util.now()
        today = now.date()

        if self.sensor_type in [SENSOR_TYPE_HDD_DAILY, SENSOR_TYPE_CDD_DAILY]:
            # The daily value represents yesterday
            yesterday = today - timedelta(days=1)
            return f"{yesterday}"

        elif self.sensor_type in [SENSOR_TYPE_HDD_WEEKLY, SENSOR_TYPE_CDD_WEEKLY]:
            # From Monday to Sunday
            weekday = today.weekday()
            week_start = today - timedelta(days=weekday)  # Monday
            week_end = week_start + timedelta(days=6)  # Sunday
            return f"{week_start} to {week_end}"

        elif self.sensor_type in [SENSOR_TYPE_HDD_MONTHLY, SENSOR_TYPE_CDD_MONTHLY]:
            # From 1st to last day of the month
            month_start = today.replace(day=1)
            _, last_day = calendar.monthrange(today.year, today.month)
            month_end = today.replace(day=last_day)
            return f"{month_start} to {month_end}"

        elif self.sensor_type in [
            SENSOR_TYPE_HDD_ESTIMATED_TODAY,
            SENSOR_TYPE_CDD_ESTIMATED_TODAY,
        ]:
            # Estimated for today (combines actual + forecast)
            return f"{today} (estimated)"

        elif self.sensor_type in [
            SENSOR_TYPE_HDD_ESTIMATED_TOMORROW,
            SENSOR_TYPE_CDD_ESTIMATED_TOMORROW,
        ]:
            # Estimated for tomorrow (forecast only)
            tomorrow = today + timedelta(days=1)
            return f"{tomorrow} (estimated)"

        return "Unknown period"

    def _get_mean_temperature(self):
        """Get the mean temperature for the period."""
        if (
            self.sensor_type in [SENSOR_TYPE_HDD_DAILY, SENSOR_TYPE_CDD_DAILY]
            and self.coordinator.temperature_history
        ):
            temps = [temp for _, temp in self.coordinator.temperature_history]
            if not temps:
                _LOGGER.debug("No temperature data available for mean calculation")
                return None

            mean_temp = sum(temps) / len(temps)
            _LOGGER.debug(
                "Calculated mean temperature: %.1f°%s from %d readings",
                mean_temp,
                self.coordinator.temperature_unit,
                len(temps),
            )
            return round(mean_temp, 1)

        # For weekly and monthly, we don't have an average temperature
        # because these values are accumulations
        return None
