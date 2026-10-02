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


async def _start_reconfigure_flow(hass: HomeAssistant, entry: MockConfigEntry):
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    return result


def _add_entry(hass: HomeAssistant, **overrides) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Heating Degree Days (18.0°C)",
        data={**BASE_USER_INPUT, CONF_TEMPERATURE_UNIT: "°C", **overrides},
    )
    entry.add_to_hass(hass)
    return entry


async def test_reconfigure_prefills_current_settings(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """The reconfigure form is prefilled with the entry's current settings."""
    entry = _add_entry(hass, base_temperature=16.0, include_weekly=False)

    result = await _start_reconfigure_flow(hass, entry)

    schema = result["data_schema"].schema
    defaults = {
        key.schema: key.default()
        for key in schema
        if callable(getattr(key, "default", None))
    }
    suggested = {
        key.schema: (key.description or {}).get("suggested_value") for key in schema
    }
    assert suggested[CONF_TEMPERATURE_SENSOR] == TEMP_SENSOR
    assert defaults[CONF_BASE_TEMPERATURE] == 16.0
    assert defaults[CONF_INCLUDE_WEEKLY] is False
    assert defaults[CONF_INCLUDE_MONTHLY] is True
    assert defaults[CONF_NAME] == entry.title


async def test_reconfigure_updates_entry(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """Submitting the reconfigure form updates data and re-derives the title."""
    entry = _add_entry(hass)

    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_reconfigure_flow(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_NAME: "",
                **BASE_USER_INPUT,
                CONF_BASE_TEMPERATURE: 15.0,
                CONF_INCLUDE_COOLING: True,
            },
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_BASE_TEMPERATURE] == 15.0
    assert entry.data[CONF_INCLUDE_COOLING] is True
    assert entry.data[CONF_TEMPERATURE_UNIT] == "°C"
    assert CONF_NAME not in entry.data
    assert entry.title == "Heating & Cooling Degree Days (15.0°C)"


async def test_reconfigure_keeps_custom_name(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """A name kept in the form stays the entry title."""
    entry = _add_entry(hass)

    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_reconfigure_flow(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_NAME: "Salon", **BASE_USER_INPUT, CONF_BASE_TEMPERATURE: 15.0},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert entry.title == "Salon"


async def test_reconfigure_invalid_sensor_shows_error(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """An unknown temperature sensor keeps the form open with an error."""
    entry = _add_entry(hass)

    result = await _start_reconfigure_flow(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**BASE_USER_INPUT, CONF_TEMPERATURE_SENSOR: "sensor.does_not_exist"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_temperature_sensor"}
    assert entry.data[CONF_TEMPERATURE_SENSOR] == TEMP_SENSOR


async def test_reconfigure_same_settings_is_not_a_duplicate(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """An entry does not collide with itself."""
    entry = _add_entry(hass)

    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_reconfigure_flow(hass, entry)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(BASE_USER_INPUT)
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_duplicate_of_other_entry_aborts(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """Reconfiguring onto another entry's sensor and base temperature aborts."""
    _add_entry(hass, base_temperature=16.0)
    entry = _add_entry(hass, base_temperature=18.0)

    result = await _start_reconfigure_flow(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**BASE_USER_INPUT, CONF_BASE_TEMPERATURE: 16.0}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_BASE_TEMPERATURE] == 18.0


async def test_reconfigure_clears_stored_data_on_calculation_change(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """Changing the base temperature drops the stored daily values."""
    entry = _add_entry(hass)

    with (
        patch(
            "custom_components.heating_cooling_degree_days.async_setup_entry",
            return_value=True,
        ),
        patch(
            "custom_components.heating_cooling_degree_days.config_flow.async_remove_stored_data",
            new=AsyncMock(),
        ) as remove_stored,
    ):
        result = await _start_reconfigure_flow(hass, entry)
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_USER_INPUT, CONF_BASE_TEMPERATURE: 15.0}
        )
        await hass.async_block_till_done()

    remove_stored.assert_awaited_once_with(hass, entry.entry_id)


async def test_reconfigure_keeps_stored_data_on_sensor_option_change(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """Toggling the weekly/monthly sensors leaves the stored daily values alone."""
    entry = _add_entry(hass)

    with (
        patch(
            "custom_components.heating_cooling_degree_days.async_setup_entry",
            return_value=True,
        ),
        patch(
            "custom_components.heating_cooling_degree_days.config_flow.async_remove_stored_data",
            new=AsyncMock(),
        ) as remove_stored,
    ):
        result = await _start_reconfigure_flow(hass, entry)
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_USER_INPUT, CONF_INCLUDE_MONTHLY: False}
        )
        await hass.async_block_till_done()

    remove_stored.assert_not_awaited()
