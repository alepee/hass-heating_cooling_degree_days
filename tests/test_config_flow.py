"""Tests for the config flow."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

TEMP_SENSOR = "sensor.outdoor_temperature"

BASE_USER_INPUT = {
    CONF_TEMPERATURE_SENSOR: TEMP_SENSOR,
    CONF_BASE_TEMPERATURE: 18.0,
    CONF_INCLUDE_COOLING: False,
    CONF_INCLUDE_WEEKLY: True,
    CONF_INCLUDE_MONTHLY: True,
}


@pytest.fixture(autouse=True)
def _mock_deps():
    """Bypass dependency resolution so recorder is not required."""
    with patch(
        "homeassistant.config_entries.async_process_deps_reqs",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.fixture
def _temperature_sensor(hass: HomeAssistant) -> None:
    """Register a valid outdoor temperature sensor."""
    hass.states.async_set(
        TEMP_SENSOR,
        "12.5",
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )


async def _start_user_flow(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    return result


async def test_user_flow_derived_title(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """No name provided: title is derived from base temperature and unit."""
    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(BASE_USER_INPUT)
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Heating Degree Days (18.0°C)"
    # The name must not leak into entry data
    assert CONF_NAME not in result["data"]
    assert result["data"][CONF_TEMPERATURE_UNIT] == "°C"


async def test_user_flow_custom_name(hass: HomeAssistant, _temperature_sensor) -> None:
    """A provided name becomes the entry title."""
    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Salon", **BASE_USER_INPUT}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Salon"
    assert CONF_NAME not in result["data"]


async def test_user_flow_derived_title_with_cooling(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """Derived title reflects the cooling option."""
    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_USER_INPUT, CONF_INCLUDE_COOLING: True}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Heating & Cooling Degree Days (18.0°C)"


async def test_duplicate_entry_aborts(hass: HomeAssistant, _temperature_sensor) -> None:
    """Same sensor + same base temperature aborts with already_configured."""
    MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Existing",
        data={**BASE_USER_INPUT, CONF_TEMPERATURE_UNIT: "°C"},
    ).add_to_hass(hass)

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(BASE_USER_INPUT)
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_second_entry_with_different_base_temperature(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """Same sensor with a different base temperature is allowed."""
    MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Existing",
        data={**BASE_USER_INPUT, CONF_TEMPERATURE_UNIT: "°C"},
    ).add_to_hass(hass)

    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_USER_INPUT, CONF_BASE_TEMPERATURE: 16.0}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Heating Degree Days (16.0°C)"
