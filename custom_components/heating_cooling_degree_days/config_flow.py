"""Config flow for Heating & Cooling Degree Days integration."""

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_NAME
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
from .coordinator import async_remove_stored_data

_LOGGER = logging.getLogger(__name__)


class HDDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Heating & Cooling Degree Days."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate the temperature sensor
            if not self._validate_sensor(user_input[CONF_TEMPERATURE_SENSOR]):
                errors["base"] = "invalid_temperature_sensor"

            if not errors:
                # Reject a strict duplicate: same source sensor + same base temperature
                self._async_abort_entries_match(
                    {
                        CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                        CONF_BASE_TEMPERATURE: user_input[CONF_BASE_TEMPERATURE],
                    }
                )

                data = self._build_entry_data(user_input)

                # The name is only used as the entry title, not stored in data
                name = user_input.get(CONF_NAME, "").strip()
                title = name or self._derive_title(data)

                _LOGGER.debug("Creating integration with title: %s", title)

                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_schema(),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            if not self._validate_sensor(user_input[CONF_TEMPERATURE_SENSOR]):
                errors["base"] = "invalid_temperature_sensor"

            if not errors and self._is_duplicate(entry, user_input):
                return self.async_abort(reason="already_configured")

            if not errors:
                data = self._build_entry_data(user_input)

                # An empty name falls back to a title derived from the new settings
                name = user_input.get(CONF_NAME, "").strip()
                title = name or self._derive_title(data)

                _LOGGER.debug(
                    "Reconfiguring entry %s with title: %s", entry.entry_id, title
                )

                # Values calculated with another source sensor, base temperature
                # or unit cannot be mixed with the new ones
                if self._calculation_changed(entry, data):
                    await async_remove_stored_data(self.hass, entry.entry_id)

                return self.async_update_reload_and_abort(
                    entry,
                    title=title,
                    data=data,
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._build_schema(entry),
            errors=errors,
        )

    def _build_schema(self, entry: ConfigEntry | None = None) -> vol.Schema:
        """Build the settings schema, prefilled with an entry's current values."""
        current = dict(entry.data) if entry else {}
        name_default = entry.title if entry else ""

        return vol.Schema(
            {
                vol.Optional(CONF_NAME, default=name_default): selector.TextSelector(),
                vol.Required(
                    CONF_TEMPERATURE_SENSOR,
                    description={
                        "suggested_value": current.get(CONF_TEMPERATURE_SENSOR)
                    },
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor"],
                        device_class=SensorDeviceClass.TEMPERATURE,
                    ),
                ),
                vol.Required(
                    CONF_BASE_TEMPERATURE,
                    default=current.get(
                        CONF_BASE_TEMPERATURE, self._get_default_base_temperature()
                    ),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_INCLUDE_COOLING,
                    default=current.get(CONF_INCLUDE_COOLING, DEFAULT_INCLUDE_COOLING),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_INCLUDE_WEEKLY,
                    default=current.get(CONF_INCLUDE_WEEKLY, DEFAULT_INCLUDE_WEEKLY),
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_INCLUDE_MONTHLY,
                    default=current.get(CONF_INCLUDE_MONTHLY, DEFAULT_INCLUDE_MONTHLY),
                ): selector.BooleanSelector(),
            }
        )

    def _build_entry_data(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Turn the submitted form into entry data (the name is not part of it)."""
        data = {k: v for k, v in user_input.items() if k != CONF_NAME}
        # The base temperature is entered in the unit currently displayed by HA
        data[CONF_TEMPERATURE_UNIT] = self.hass.config.units.temperature_unit
        return data

    def _is_duplicate(self, entry: ConfigEntry, user_input: dict[str, Any]) -> bool:
        """Check whether another entry already uses this sensor and base temperature."""
        return any(
            other.entry_id != entry.entry_id
            and other.data.get(CONF_TEMPERATURE_SENSOR)
            == user_input[CONF_TEMPERATURE_SENSOR]
            and other.data.get(CONF_BASE_TEMPERATURE)
            == user_input[CONF_BASE_TEMPERATURE]
            for other in self.hass.config_entries.async_entries(DOMAIN)
        )

    @staticmethod
    def _calculation_changed(entry: ConfigEntry, data: dict[str, Any]) -> bool:
        """Check whether the new settings invalidate the stored daily values."""
        return any(
            entry.data.get(key) != data.get(key)
            for key in (
                CONF_TEMPERATURE_SENSOR,
                CONF_BASE_TEMPERATURE,
                CONF_TEMPERATURE_UNIT,
            )
        )

    def _derive_title(self, data: dict[str, Any]) -> str:
        """Derive an entry title from the configuration, e.g. 'Heating Degree Days (18.0°C)'."""
        base_name = (
            DEFAULT_NAME_WITH_HEATING_AND_COOLING
            if data.get(CONF_INCLUDE_COOLING, DEFAULT_INCLUDE_COOLING)
            else DEFAULT_NAME_WITH_HEATING
        )
        return (
            f"{base_name} "
            f"({data[CONF_BASE_TEMPERATURE]:.1f}{data[CONF_TEMPERATURE_UNIT]})"
        )

    def _get_default_base_temperature(self) -> float:
        """Get the default base temperature based on user preferred unit system."""
        return MAP_DEFAULT_BASE_TEMPERATURE.get(
            self.hass.config.units.temperature_unit, DEFAULT_BASE_TEMPERATURE_CELSIUS
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
