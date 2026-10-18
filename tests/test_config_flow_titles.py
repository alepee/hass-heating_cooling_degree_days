"""Localized generated titles and compatibility with previously saved names."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_TEMPERATURE_UNIT,
    DOMAIN,
)
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .test_config_flow import BASE_USER_INPUT, TEMP_SENSOR

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture(autouse=True)
def _flow_dependencies(hass: HomeAssistant):
    """Exercise real translations while keeping integration setup out of flows."""
    hass.states.async_set(
        TEMP_SENSOR,
        "12.5",
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )
    with (
        patch("homeassistant.config_entries.async_process_deps_reqs", new=AsyncMock()),
        patch(
            "homeassistant.config_entries.ConfigEntries.async_setup",
            return_value=True,
        ),
    ):
        yield


@pytest.mark.parametrize(
    ("language", "heating", "cooling"),
    [
        ("en", "Heating Degree Days", "Heating & Cooling Degree Days"),
        (
            "fr",
            "Degrés-jours de chauffage",
            "Degrés-jours de chauffage et de refroidissement",
        ),
        ("de", "Heating Degree Days", "Heating & Cooling Degree Days"),
    ],
)
@pytest.mark.parametrize("include_cooling", [False, True])
async def test_new_entry_title_language(
    hass: HomeAssistant, language, heating, cooling, include_cooling
) -> None:
    """Use actual EN/FR resources and fall back to English for another language."""
    hass.config.language = language
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={**BASE_USER_INPUT, CONF_INCLUDE_COOLING: include_cooling},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"{cooling if include_cooling else heating} (18.0°C)"


async def test_close_bases_have_distinct_titles(hass: HomeAssistant) -> None:
    """Retain precision when different bases would round to the same title."""
    titles = []
    for base in (18.01, 18.04):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data={**BASE_USER_INPUT, CONF_BASE_TEMPERATURE: base},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        titles.append(result["title"])
    assert titles == [
        "Heating Degree Days (18.01°C)",
        "Heating Degree Days (18.04°C)",
    ]


@pytest.mark.parametrize(
    ("language", "old_title", "old_base", "expected"),
    [
        ("fr", "Heating Degree Days (18.0°C)", 18.0, "Degrés-jours de chauffage"),
        ("en", "Degrés-jours de chauffage (18.0°C)", 18.0, "Heating Degree Days"),
        ("fr", "Heating Degree Days (18.0°C)", 18.04, "Degrés-jours de chauffage"),
        ("en", "Degrés-jours de chauffage (18.04°C)", 18.04, "Heating Degree Days"),
    ],
)
async def test_reconfigure_previous_language_or_rounded_title(
    hass: HomeAssistant, language, old_title, old_base, expected
) -> None:
    """Regenerate old defaults only on submission, preserving entry identity."""
    hass.config.language = language
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id="stable-entry",
        title=old_title,
        data={
            **BASE_USER_INPUT,
            CONF_BASE_TEMPERATURE: old_base,
            CONF_TEMPERATURE_UNIT: "°C",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert entry.title == old_title
    with patch(
        "custom_components.heating_cooling_degree_days.config_flow.async_remove_stored_data",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**BASE_USER_INPUT, CONF_NAME: old_title, CONF_BASE_TEMPERATURE: 16.04},
        )
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == f"{expected} (16.04°C)"
    assert entry.unique_id == "stable-entry"
    assert entry.version == 2
    await hass.async_block_till_done()


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize(
    "name",
    ["Salon", "Heating Degree Days (17.0°C)", "Degrés-jours de chauffage (17.0°C)"],
)
async def test_custom_title_survives_language_and_settings_change(
    hass: HomeAssistant, language, name
) -> None:
    """A custom title, including a different generated-looking title, is retained."""
    hass.config.language = language
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={**BASE_USER_INPUT, CONF_NAME: name},
    )
    assert result["title"] == name
    entry = result["result"]
    await hass.async_block_till_done()
    hass.config.language = "en" if language == "fr" else "fr"
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    with patch(
        "custom_components.heating_cooling_degree_days.config_flow.async_remove_stored_data",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**BASE_USER_INPUT, CONF_NAME: name, CONF_BASE_TEMPERATURE: 16.0},
        )
    assert result["reason"] == "reconfigure_successful"
    assert entry.title == name
    await hass.async_block_till_done()


async def test_missing_translation_keys_fall_back_to_english(
    hass: HomeAssistant,
) -> None:
    """Missing resources still yield a usable English entry title."""
    hass.config.language = "fr"
    with patch(
        "custom_components.heating_cooling_degree_days.config_flow.async_get_translations",
        return_value={},
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=dict(BASE_USER_INPUT),
        )
    assert result["title"] == "Heating Degree Days (18.0°C)"
