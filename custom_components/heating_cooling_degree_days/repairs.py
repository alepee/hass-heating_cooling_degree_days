"""Repairs platform for Heating & Cooling Degree Days integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.components.weather import WeatherEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir, selector

from .const import CONF_WEATHER_ENTITY, DOMAIN

_LOGGER = logging.getLogger(__name__)

ISSUE_WEATHER_NO_HOURLY_FORECAST = "weather_no_hourly_forecast"


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create flow."""
    if issue_id == ISSUE_WEATHER_NO_HOURLY_FORECAST:
        return WeatherEntityRepairFlow(hass, data)

    return ConfirmRepairFlow()


class WeatherEntityRepairFlow(RepairsFlow):
    """Handler for weather entity repair flow."""

    def __init__(
        self, hass: HomeAssistant, data: dict[str, str | int | float | None] | None
    ) -> None:
        """Initialize the repair flow."""
        super().__init__()
        self.hass = hass
        self.entry_id = data.get("entry_id") if data else None
        self.current_entity = data.get("entity_id") if data else None

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of a fix flow."""
        if not self.entry_id:
            return self.async_abort(reason="no_entry_id")

        # Get the config entry
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if not entry:
            return self.async_abort(reason="entry_not_found")

        if user_input is not None:
            action = user_input.get("action")
            if action == "select_new":
                return await self.async_step_select_weather()
            elif action == "remove":
                return await self.async_step_confirm_remove()

        # Show form to choose action
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="select_new"): vol.In(
                        {
                            "select_new": "Select a new weather entity",
                            "remove": "Remove weather entity (disable forecast sensors)",
                        }
                    ),
                }
            ),
            description_placeholders={
                "current_entity": self.current_entity or "unknown",
            },
        )

    async def async_step_select_weather(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the weather entity selection step."""
        if user_input is not None:
            new_weather_entity = user_input.get(CONF_WEATHER_ENTITY)

            # Validate the new weather entity
            if new_weather_entity and await self._validate_weather_entity(
                new_weather_entity
            ):
                # Update the config entry
                entry = self.hass.config_entries.async_get_entry(self.entry_id)
                if entry:
                    new_data = {**entry.data, CONF_WEATHER_ENTITY: new_weather_entity}
                    self.hass.config_entries.async_update_entry(entry, data=new_data)

                    # Delete the issue
                    ir.async_delete_issue(
                        self.hass, DOMAIN, ISSUE_WEATHER_NO_HOURLY_FORECAST
                    )

                    # Reload the integration to apply changes
                    await self.hass.config_entries.async_reload(self.entry_id)

                    _LOGGER.info(
                        "Updated weather entity to %s for entry %s",
                        new_weather_entity,
                        self.entry_id,
                    )

                    return self.async_create_entry(title="", data={})
                else:
                    return self.async_abort(reason="entry_not_found")
            else:
                return self.async_show_form(
                    step_id="select_weather",
                    data_schema=vol.Schema(
                        {
                            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                                selector.EntitySelectorConfig(domain=["weather"]),
                            ),
                        }
                    ),
                    errors={"base": "invalid_weather_entity"},
                )

        # Show form to select new weather entity
        return self.async_show_form(
            step_id="select_weather",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=["weather"]),
                    ),
                }
            ),
            description_placeholders={
                "current_entity": self.current_entity or "unknown",
            },
        )

    async def _validate_weather_entity(self, entity_id: str) -> bool:
        """Validate the weather entity exists and supports hourly forecasts."""
        state = self.hass.states.get(entity_id)
        if not state:
            return False

        # Check that it is a weather entity
        if not entity_id.startswith("weather."):
            _LOGGER.warning(
                "Entity %s does not appear to be a weather entity", entity_id
            )
            return False

        # Verify hourly forecast support by checking the entity's supported features
        features = state.attributes.get("supported_features", 0)
        if not (features & WeatherEntityFeature.FORECAST_HOURLY):
            _LOGGER.warning(
                "Weather entity %s does not support hourly forecasts (features: %s)",
                entity_id,
                features,
            )
            return False

        _LOGGER.debug(
            "Weather entity %s supports hourly forecasts (features: %s)",
            entity_id,
            features,
        )
        return True

    async def async_step_confirm_remove(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirmation step for removing weather entity."""
        if user_input is not None:
            # Update the config entry to remove weather entity
            entry = self.hass.config_entries.async_get_entry(self.entry_id)
            if entry:
                new_data = {**entry.data}
                new_data.pop(CONF_WEATHER_ENTITY, None)
                self.hass.config_entries.async_update_entry(entry, data=new_data)

                # Delete the issue
                ir.async_delete_issue(
                    self.hass, DOMAIN, ISSUE_WEATHER_NO_HOURLY_FORECAST
                )

                # Reload the integration to apply changes
                await self.hass.config_entries.async_reload(self.entry_id)

                _LOGGER.info("Removed weather entity for entry %s", self.entry_id)

                return self.async_create_entry(title="", data={})
            else:
                return self.async_abort(reason="entry_not_found")

        # Show confirmation form
        return self.async_show_form(
            step_id="confirm_remove",
            data_schema=vol.Schema({}),
            description_placeholders={
                "current_entity": self.current_entity or "unknown",
            },
        )
