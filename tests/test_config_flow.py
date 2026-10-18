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
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM

TEMP_SENSOR = "sensor.outdoor_temperature"

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

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


@pytest.mark.parametrize("source", ["user", "reconfigure"])
@pytest.mark.parametrize("base_temp", [float("nan"), float("inf"), float("-inf")])
async def test_nonfinite_base_is_rejected(
    hass: HomeAssistant, _temperature_sensor, source, base_temp
) -> None:
    """Neither configuration path accepts NaN or infinite base temperatures."""
    entry = _add_entry(hass) if source == "reconfigure" else None
    result = (
        await _start_reconfigure_flow(hass, entry)
        if entry
        else await _start_user_flow(hass)
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**BASE_USER_INPUT, CONF_BASE_TEMPERATURE: base_temp}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_BASE_TEMPERATURE: "invalid_base_temperature"}
    if entry:
        assert entry.data[CONF_BASE_TEMPERATURE] == 18.0


@pytest.mark.parametrize("source", ["user", "reconfigure"])
@pytest.mark.parametrize(
    ("entity_id", "attributes"),
    [
        ("sensor.missing", None),
        ("sensor.humidity", {"device_class": "humidity", "unit_of_measurement": "%"}),
        ("sensor.numeric", {}),
        ("weather.outdoor", {"temperature": 12.5, "temperature_unit": "°C"}),
    ],
)
async def test_invalid_source_is_rejected(
    hass: HomeAssistant, _temperature_sensor, source, entity_id, attributes
) -> None:
    """Backend checks reject missing/non-temperature entities in either flow."""
    if attributes is not None:
        hass.states.async_set(entity_id, "12.5", attributes)
    entry = _add_entry(hass) if source == "reconfigure" else None
    result = (
        await _start_reconfigure_flow(hass, entry)
        if entry
        else await _start_user_flow(hass)
    )
    if entity_id.startswith("weather."):
        with pytest.raises(InvalidData):
            await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {**BASE_USER_INPUT, CONF_TEMPERATURE_SENSOR: entity_id},
            )
        return
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**BASE_USER_INPUT, CONF_TEMPERATURE_SENSOR: entity_id}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_temperature_sensor"}
    if entry:
        assert entry.data[CONF_TEMPERATURE_SENSOR] == TEMP_SENSOR


@pytest.mark.parametrize("source", ["user", "reconfigure"])
@pytest.mark.parametrize(
    "attributes",
    [
        {"device_class": "temperature"},
        {"unit_of_measurement": "°C"},
        {"unit_of_measurement": "°F"},
        {"unit_of_measurement": "K"},
    ],
)
async def test_temperature_class_or_unit_is_accepted(
    hass: HomeAssistant, source, attributes
) -> None:
    """Unit-only sensors and currently unavailable temperature sensors are valid."""
    hass.states.async_set(TEMP_SENSOR, "unavailable", attributes)
    entry = _add_entry(hass) if source == "reconfigure" else None
    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = (
            await _start_reconfigure_flow(hass, entry)
            if entry
            else await _start_user_flow(hass)
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(BASE_USER_INPUT)
        )
        await hass.async_block_till_done()

    if entry:
        assert result["reason"] == "reconfigure_successful"
    else:
        assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("entry_unit", "base_temp", "new_system"),
    [("°C", 18.0, US_CUSTOMARY_SYSTEM), ("°F", 65.0, METRIC_SYSTEM)],
)
async def test_reconfigure_preserves_stored_unit_after_system_change(
    recorder_mock,
    hass: HomeAssistant,
    _temperature_sensor,
    *,
    entry_unit,
    base_temp,
    new_system,
) -> None:
    """The displayed base retains its physical meaning on a genuinely loaded entry."""
    entry = _add_entry(hass, temperature_unit=entry_unit, base_temperature=base_temp)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.config.units = new_system

    with patch(
        "custom_components.heating_cooling_degree_days.config_flow.async_remove_stored_data",
        new=AsyncMock(),
    ) as remove_stored:
        result = await _start_reconfigure_flow(hass, entry)
        assert result["description_placeholders"]["temperature_unit"] == entry_unit
        defaults = {
            key.schema: key.default()
            for key in result["data_schema"].schema
            if callable(getattr(key, "default", None))
        }
        assert defaults[CONF_BASE_TEMPERATURE] == base_temp
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**BASE_USER_INPUT, **defaults, CONF_INCLUDE_WEEKLY: False},
        )
        await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_BASE_TEMPERATURE] == base_temp
    assert entry.data[CONF_TEMPERATURE_UNIT] == entry_unit
    assert entry.runtime_data.temperature_unit == entry_unit
    remove_stored.assert_not_awaited()


@pytest.mark.parametrize("custom_name", ["Office", "Heating Degree Days (17.0°C)"])
async def test_reconfigure_preserves_existing_custom_title(
    recorder_mock, hass: HomeAssistant, _temperature_sensor, custom_name
) -> None:
    """Only titles matching the old generated title are automatically rederived."""
    entry = _add_entry(hass)
    hass.config_entries.async_update_entry(entry, title=custom_name)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await _start_reconfigure_flow(hass, entry)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**BASE_USER_INPUT, CONF_NAME: custom_name, CONF_BASE_TEMPERATURE: 15.0},
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.title == custom_name


async def test_same_number_with_different_units_is_not_a_duplicate(
    hass: HomeAssistant, _temperature_sensor
) -> None:
    """18°C and 18°F are distinct base temperatures despite the same number."""
    _add_entry(hass, temperature_unit="°F")
    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(BASE_USER_INPUT)
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
