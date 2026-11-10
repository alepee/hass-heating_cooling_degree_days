"""Config flow for Heating & Cooling Degree Days integration."""

import logging
import math
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.translation import async_get_translations

from .const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    CONF_WEATHER_ENTITY,
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
from .forecast import (
    ATTR_SUPPORTED_FEATURES,
    FEATURE_FORECAST_HOURLY,
    async_clear_forecast_issue,
)
from .source import CONF_SOURCE_REGISTRY_ID, async_clear_source_issue

_LOGGER = logging.getLogger(__name__)

# Settings that only select which sensors exist; changing them keeps stored values.
SENSOR_OPTION_DEFAULTS = {
    CONF_INCLUDE_COOLING: DEFAULT_INCLUDE_COOLING,
    CONF_INCLUDE_WEEKLY: DEFAULT_INCLUDE_WEEKLY,
    CONF_INCLUDE_MONTHLY: DEFAULT_INCLUDE_MONTHLY,
}


def _weather_schema_field(current: dict[str, Any]) -> dict[Any, Any]:
    """Build the optional weather entity field, prefilled when already set."""
    return {
        vol.Optional(
            CONF_WEATHER_ENTITY,
            description={"suggested_value": current.get(CONF_WEATHER_ENTITY)},
        ): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["weather"]),
        ),
    }


def _sensor_option_fields(current: dict[str, Any]) -> dict[Any, Any]:
    """Build the sensor selection toggles, prefilled with current values."""
    return {
        vol.Required(key, default=current.get(key, default)): (
            selector.BooleanSelector()
        )
        for key, default in SENSOR_OPTION_DEFAULTS.items()
    }


def _is_valid_weather(hass: HomeAssistant, entity_id: str) -> bool:
    """Require an existing weather entity that provides hourly forecasts."""
    state = hass.states.get(entity_id)
    return (
        state is not None
        and state.domain == "weather"
        and bool(
            (state.attributes.get(ATTR_SUPPORTED_FEATURES) or 0)
            & FEATURE_FORECAST_HOURLY
        )
    )


async def _async_derive_title(
    hass: HomeAssistant, data: dict[str, Any], language: str | None = None
) -> str:
    """Derive a localized title without rounding distinct base temperatures."""
    cooling = data.get(CONF_INCLUDE_COOLING, DEFAULT_INCLUDE_COOLING)
    translations = await async_get_translations(
        hass, language or hass.config.language, "common", {DOMAIN}
    )
    key = "heating_and_cooling" if cooling else "heating"
    base_name = (
        DEFAULT_NAME_WITH_HEATING_AND_COOLING if cooling else DEFAULT_NAME_WITH_HEATING
    )
    base_name = translations.get(
        f"component.{DOMAIN}.common.default_title_{key}", base_name
    )
    return (
        f"{base_name} "
        f"({float(data[CONF_BASE_TEMPERATURE])}{data[CONF_TEMPERATURE_UNIT]})"
    )


async def _async_is_generated_title(
    hass: HomeAssistant, title: str, data: dict[str, Any]
) -> bool:
    """Recognize supported languages and legacy one-decimal generated titles."""
    rounded_data = {
        **data,
        CONF_BASE_TEMPERATURE: float(f"{data[CONF_BASE_TEMPERATURE]:.1f}"),
    }
    # An entry may have been created before the system language changed.
    for language in {"en", "fr", hass.config.language}:
        if title in {
            await _async_derive_title(hass, data, language),
            await _async_derive_title(hass, rounded_data, language),
        }:
            return True
    return False


class HDDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Heating & Cooling Degree Days."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Expose the forecast source and sensor selection behind the cog."""
        return HDDOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            errors = self._validate_input(user_input)

            if not errors:
                data = self._build_entry_data(user_input)
                # Reject a strict duplicate: same source sensor + same base temperature
                self._async_abort_entries_match(
                    {
                        CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                        CONF_BASE_TEMPERATURE: user_input[CONF_BASE_TEMPERATURE],
                        CONF_TEMPERATURE_UNIT: data[CONF_TEMPERATURE_UNIT],
                    }
                )

                # The name is only used as the entry title, not stored in data
                name = user_input.get(CONF_NAME, "").strip()
                title = name or await _async_derive_title(self.hass, data)

                _LOGGER.debug("Creating integration with title: %s", title)

                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=self._build_schema(),
            description_placeholders={
                "temperature_unit": self.hass.config.units.temperature_unit
            },
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        entry = self._get_reconfigure_entry()
        errors = {}

        if user_input is not None:
            errors = self._validate_input(user_input)
            data = self._build_entry_data(user_input, entry)

            if not errors and self._is_duplicate(entry, data):
                return self.async_abort(reason="already_configured")

            if not errors:
                # An empty name falls back to a title derived from the new settings
                name = user_input.get(CONF_NAME, "").strip()
                if name == entry.title and await _async_is_generated_title(
                    self.hass, name, entry.data
                ):
                    name = ""
                title = name or await _async_derive_title(self.hass, data)

                _LOGGER.debug(
                    "Reconfiguring entry %s with title: %s", entry.entry_id, title
                )

                # Values calculated with another source sensor, base temperature
                # or unit cannot be mixed with the new ones
                if self._calculation_changed(entry, data):
                    await async_remove_stored_data(self.hass, entry.entry_id)

                async_clear_source_issue(self.hass, entry.entry_id)
                async_clear_forecast_issue(self.hass, entry.entry_id)

                # The loaded entry's update listener owns the reload. Updating
                # directly also supports HA 2025.1 (no async_update_and_abort).
                self.hass.config_entries.async_update_entry(
                    entry,
                    title=title,
                    data=data,
                )
                if entry.state is not ConfigEntryState.LOADED:
                    # Failed/unloaded entries have no active update listener.
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._build_schema(entry),
            description_placeholders={
                "temperature_unit": entry.data[CONF_TEMPERATURE_UNIT]
            },
            errors=errors,
        )

    def _build_schema(self, entry: ConfigEntry | None = None) -> vol.Schema:
        """Build the settings schema, prefilled with an entry's current values."""
        current = dict(entry.data) if entry else {}
        name_default = entry.title if entry else ""

        schema: dict[Any, Any] = {
            vol.Optional(CONF_NAME, default=name_default): selector.TextSelector(),
            vol.Required(
                CONF_TEMPERATURE_SENSOR,
                description={"suggested_value": current.get(CONF_TEMPERATURE_SENSOR)},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor"],
                ),
            ),
            vol.Required(
                CONF_BASE_TEMPERATURE,
                default=current.get(
                    CONF_BASE_TEMPERATURE, self._get_default_base_temperature()
                ),
            ): vol.Coerce(float),
        }
        if entry is None:
            # Reconfiguration only changes the calculation; the forecast source
            # and the sensor selection are edited in the options flow.
            schema.update(_weather_schema_field(current))
            schema.update(_sensor_option_fields(current))
        return vol.Schema(schema)

    def _build_entry_data(
        self, user_input: dict[str, Any], entry: ConfigEntry | None = None
    ) -> dict[str, Any]:
        """Turn the submitted form into entry data (the name is not part of it)."""
        # Reconfiguration keeps the options it does not show; the source
        # registry identity is resolved again for the submitted sensor.
        data = (
            {k: v for k, v in entry.data.items() if k != CONF_SOURCE_REGISTRY_ID}
            if entry
            else {}
        )
        # An omitted or cleared weather entity removes the forecast estimates.
        data.update(
            {
                k: v
                for k, v in user_input.items()
                if k != CONF_NAME and not (k == CONF_WEATHER_ENTITY and not v)
            }
        )
        # Reconfiguration always displays and preserves the entry's stored unit.
        data[CONF_TEMPERATURE_UNIT] = (
            entry.data[CONF_TEMPERATURE_UNIT]
            if entry
            else self.hass.config.units.temperature_unit
        )
        if registered := er.async_get(self.hass).async_get(
            data[CONF_TEMPERATURE_SENSOR]
        ):
            data[CONF_SOURCE_REGISTRY_ID] = registered.id
        return data

    def _is_duplicate(self, entry: ConfigEntry, user_input: dict[str, Any]) -> bool:
        """Check whether another entry already uses this sensor and base temperature."""
        return any(
            other.entry_id != entry.entry_id
            and other.data.get(CONF_TEMPERATURE_SENSOR)
            == user_input[CONF_TEMPERATURE_SENSOR]
            and other.data.get(CONF_BASE_TEMPERATURE)
            == user_input[CONF_BASE_TEMPERATURE]
            and other.data.get(CONF_TEMPERATURE_UNIT)
            == user_input[CONF_TEMPERATURE_UNIT]
            for other in self.hass.config_entries.async_entries(DOMAIN)
        )

    @staticmethod
    def _calculation_changed(entry: ConfigEntry, data: dict[str, Any]) -> bool:
        """Check whether the new settings invalidate the stored daily values."""
        source_key = (
            CONF_SOURCE_REGISTRY_ID
            if entry.data.get(CONF_SOURCE_REGISTRY_ID)
            else CONF_TEMPERATURE_SENSOR
        )
        return any(
            entry.data.get(key) != data.get(key)
            for key in (source_key, CONF_BASE_TEMPERATURE, CONF_TEMPERATURE_UNIT)
        )

    def _get_default_base_temperature(self) -> float:
        """Get the default base temperature based on user preferred unit system."""
        return MAP_DEFAULT_BASE_TEMPERATURE.get(
            self.hass.config.units.temperature_unit, DEFAULT_BASE_TEMPERATURE_CELSIUS
        )

    def _validate_input(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate calculation settings independently of selector filtering."""
        errors = {}
        if not self._validate_sensor(user_input[CONF_TEMPERATURE_SENSOR]):
            errors["base"] = "invalid_temperature_sensor"
        if not math.isfinite(user_input[CONF_BASE_TEMPERATURE]):
            errors[CONF_BASE_TEMPERATURE] = "invalid_base_temperature"
        weather = user_input.get(CONF_WEATHER_ENTITY)
        if weather and not _is_valid_weather(self.hass, weather):
            errors[CONF_WEATHER_ENTITY] = "invalid_weather_entity"
        return errors

    def _validate_sensor(self, entity_id: str) -> bool:
        """Require an existing sensor with a temperature class or unit."""
        state = self.hass.states.get(entity_id)
        if not state or state.domain != "sensor":
            return False

        return state.attributes.get(
            "device_class"
        ) == SensorDeviceClass.TEMPERATURE or state.attributes.get(
            "unit_of_measurement"
        ) in set(UnitOfTemperature)


class HDDOptionsFlow(OptionsFlow):
    """Change the forecast source and the exposed sensors of an entry.

    These settings never affect stored daily values. They stay in entry data,
    shared with the reconfigure flow, so no storage migration is needed.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and apply the options form."""
        entry = self.config_entry
        errors: dict[str, str] = {}

        if user_input is not None:
            weather = user_input.get(CONF_WEATHER_ENTITY)
            if weather and not _is_valid_weather(self.hass, weather):
                errors[CONF_WEATHER_ENTITY] = "invalid_weather_entity"
            else:
                data = {k: v for k, v in entry.data.items() if k != CONF_WEATHER_ENTITY}
                data.update({key: user_input[key] for key in SENSOR_OPTION_DEFAULTS})
                # An omitted or cleared weather entity removes the estimates.
                if weather:
                    data[CONF_WEATHER_ENTITY] = weather

                # Keep a generated title in line with the cooling toggle.
                title = entry.title
                if await _async_is_generated_title(self.hass, title, entry.data):
                    title = await _async_derive_title(self.hass, data)

                async_clear_forecast_issue(self.hass, entry.entry_id)
                # The loaded entry's update listener owns the reload.
                if self.hass.config_entries.async_update_entry(
                    entry, title=title, data=data
                ) and (entry.state is not ConfigEntryState.LOADED):
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                return self.async_create_entry(data=dict(entry.options))

        current = dict(entry.data)
        if user_input is not None:
            current = {**current, **user_input}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {**_weather_schema_field(current), **_sensor_option_fields(current)}
            ),
            errors=errors,
        )
