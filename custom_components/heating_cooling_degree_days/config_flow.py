"""Config flow for Heating & Cooling Degree Days integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers import selector

from .const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    DEFAULT_BASE_TEMPERATURE_CELSIUS,
    DEFAULT_INCLUDE_COOLING,
    DEFAULT_INCLUDE_MONTHLY,
    DEFAULT_INCLUDE_WEEKLY,
    DEFAULT_NAME_WITH_HEATING,
    DEFAULT_NAME_WITH_HEATING_AND_COOLING,
    DOMAIN,
    MAP_DEFAULT_BASE_TEMPERATURE,
)

_LOGGER = logging.getLogger(__name__)


class HDDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Heating & Cooling Degree Days."""

    VERSION = 1

    def is_matching(self, other_flow: config_entries.ConfigFlow) -> bool:
        """Return True if other_flow matches this flow."""
        return self.context.get("unique_id") == other_flow.context.get("unique_id")

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate the temperature sensor
            if not self._validate_sensor(user_input[CONF_TEMPERATURE_SENSOR]):
                errors["base"] = "invalid_temperature_sensor"

            if not errors:
                # Set the temperature unit to the user's preferred unit
                user_input[CONF_TEMPERATURE_UNIT] = (
                    self.hass.config.units.temperature_unit
                )

                include_cooling = user_input.get(
                    CONF_INCLUDE_COOLING, DEFAULT_INCLUDE_COOLING
                )

                # Use simple fixed titles
                title = self._get_default_name(include_cooling)

                _LOGGER.debug("Creating integration with title: %s", title)

                return self.async_create_entry(
                    title=title,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TEMPERATURE_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["sensor"],
                            device_class=SensorDeviceClass.TEMPERATURE,
                        ),
                    ),
                    vol.Required(
                        CONF_BASE_TEMPERATURE,
                        default=self._get_default_base_temperature(),
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_INCLUDE_COOLING, default=DEFAULT_INCLUDE_COOLING
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_INCLUDE_WEEKLY, default=DEFAULT_INCLUDE_WEEKLY
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_INCLUDE_MONTHLY, default=DEFAULT_INCLUDE_MONTHLY
                    ): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )

    def _get_default_base_temperature(self) -> float:
        """Get the default base temperature based on user preferred unit system."""
        return MAP_DEFAULT_BASE_TEMPERATURE.get(
            self.hass.config.units.temperature_unit, DEFAULT_BASE_TEMPERATURE_CELSIUS
        )

    def _get_default_name(self, include_cooling: bool) -> str:
        """Get the default name based on heating and cooling degree days configuration."""
        return (
            DEFAULT_NAME_WITH_HEATING_AND_COOLING
            if include_cooling
            else DEFAULT_NAME_WITH_HEATING
        )

    def _validate_sensor(self, entity_id):
        """Validate the temperature sensor entity exists."""
        state = self.hass.states.get(entity_id)
        if not state:
            return False

        # Check that it is a temperature sensor
        if state.attributes.get(
            "device_class"
        ) != SensorDeviceClass.TEMPERATURE and not entity_id.startswith("weather."):
            _LOGGER.warning(
                "Entity %s does not appear to be a temperature sensor (device_class=%s)",
                entity_id,
                state.attributes.get("device_class"),
            )

        return True
