"""Forecast estimates through the public weather service and the entry lifecycle."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import DOMAIN
from custom_components.heating_cooling_degree_days.degree_days import (
    TemperatureSample,
)
from custom_components.heating_cooling_degree_days.forecast import (
    ForecastError,
    parse_forecast_response,
)
from custom_components.heating_cooling_degree_days.history import TemperatureHistory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util

pytestmark = [pytest.mark.usefixtures("recorder_mock", "enable_custom_integrations")]

PKG = "custom_components.heating_cooling_degree_days"
FORECAST_HISTORY = f"{PKG}.forecast.get_temperature_history"
LEDGER_HISTORY = f"{PKG}.coordinator.get_temperature_history"
WEATHER = "weather.home"
SOURCE = "sensor.outdoor_temperature"
NOW = "2026-01-02 12:00:00+00:00"
DAY = datetime(2026, 1, 2, tzinfo=UTC)
ENTRY_DATA = {
    "temperature_sensor": SOURCE,
    "base_temperature": 18.0,
    "temperature_unit": "°C",
    "include_cooling": True,
    "include_weekly": True,
    "include_monthly": True,
    "weather_entity": WEATHER,
}


def _observed(temperature=10.0):
    return TemperatureHistory(
        (TemperatureSample(DAY - timedelta(hours=1), temperature),), None, 0
    )


def _forecast_items(start=DAY, hours=48, temperature=6.0):
    return [
        {
            "datetime": (start + timedelta(hours=h)).isoformat(),
            "temperature": temperature,
        }
        for h in range(hours)
    ]


class FakeWeather:
    """Register a public weather.get_forecasts service with controllable output."""

    def __init__(self, hass: HomeAssistant, unit="°C", features=2) -> None:
        """Expose a weather state and its response-only forecast service."""
        self.hass = hass
        self.items = _forecast_items()
        self.error: Exception | None = None
        self.calls: list[dict] = []
        self.set_state(unit=unit, features=features)
        hass.services.async_register(
            "weather",
            "get_forecasts",
            self._handle,
            supports_response=SupportsResponse.ONLY,
        )

    def set_state(self, state="cloudy", unit="°C", features=2) -> None:
        """Change the weather state; this is not a forecast-update guarantee."""
        self.unit = unit
        self.hass.states.async_set(
            WEATHER, state, {"supported_features": features, "temperature_unit": unit}
        )

    async def _handle(self, call: ServiceCall):
        self.calls.append(dict(call.data))
        if self.error:
            raise self.error
        return {WEATHER: {"forecast": self.items}}


@pytest.fixture(autouse=True)
def _utc(hass):
    dt_util.set_default_time_zone(UTC)


@pytest.fixture
def weather(hass):
    """Provide a default hourly weather source."""
    return FakeWeather(hass)


def _add_entry(hass, **overrides) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Heating & Cooling Degree Days (18.0°C)",
        data={**ENTRY_DATA, **overrides},
    )
    entry.add_to_hass(hass)
    hass.states.async_set(
        SOURCE, "10", {"device_class": "temperature", "unit_of_measurement": "°C"}
    )
    return entry


async def _setup(hass, entry, observed=None):
    with (
        patch(FORECAST_HISTORY, return_value=observed or _observed()),
        patch(LEDGER_HISTORY, return_value=TemperatureHistory((), None, 0)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _state(hass, entry, sensor_type):
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{sensor_type}"
    )
    return hass.states.get(entity_id) if entity_id else None


@pytest.mark.freeze_time(NOW)
async def test_estimates_combine_observed_and_forecast(hass, weather):
    """Today = observed 10° until noon then forecast 6°; tomorrow = forecast only."""
    entry = _add_entry(hass)
    await _setup(hass, entry)

    today = _state(hass, entry, "hdd_estimated_today")
    assert float(today.state) == 10.0  # (8 * 12 + 12 * 12) / 24
    assert today.attributes["coverage"] == 1
    assert today.attributes["partial"] is False
    assert today.attributes["date"] == "2026-01-02"
    assert today.attributes["period_start"] == "2026-01-02T00:00:00+00:00"
    assert today.attributes["as_of"] == "2026-01-02T12:00:00+00:00"
    assert today.attributes["forecast_source"] == WEATHER
    assert today.attributes["forecast_retrieved_at"] == today.attributes["as_of"]
    assert today.attributes["reason"] is None
    assert today.attributes["unit_of_measurement"] == "°C·d"
    assert "state_class" not in today.attributes
    tomorrow = _state(hass, entry, "hdd_estimated_tomorrow")
    assert float(tomorrow.state) == 12.0
    assert tomorrow.attributes["date"] == "2026-01-03"
    assert float(_state(hass, entry, "cdd_estimated_tomorrow").state) == 0
    assert weather.calls == [{"entity_id": WEATHER, "type": "hourly"}]
    # Historical sensors are unaffected and estimates never enter the ledger.
    ledger = entry.runtime_data.coordinator.ledger
    assert all(record.hdd is None for record in ledger.values())
    assert _state(hass, entry, "hdd_daily") is not None


@pytest.mark.freeze_time(NOW)
async def test_weather_unit_override_is_converted(hass):
    """A °F weather entity gives the same estimates for a °C entry."""
    weather = FakeWeather(hass, unit="°F")
    weather.items = [
        {**item, "temperature": 6.0 * 9 / 5 + 32} for item in _forecast_items()
    ]
    entry = _add_entry(hass)
    await _setup(hass, entry)
    assert float(_state(hass, entry, "hdd_estimated_tomorrow").state) == 12.0


@pytest.mark.freeze_time(NOW)
async def test_fahrenheit_entry_with_celsius_weather(hass, weather):
    """Temperatures are normalized to the entry's calculation unit."""
    entry = _add_entry(hass, temperature_unit="°F", base_temperature=64.4)
    await _setup(hass, entry)
    tomorrow = _state(hass, entry, "hdd_estimated_tomorrow")
    assert float(tomorrow.state) == pytest.approx(21.6)
    assert tomorrow.attributes["unit_of_measurement"] == "°F·d"


@pytest.mark.freeze_time(NOW)
async def test_recorder_failure_keeps_tomorrow_and_flags_today(hass, weather):
    """Missing observations make today partial, never a complete zero-demand day."""
    entry = _add_entry(hass)
    with (
        patch(FORECAST_HISTORY, side_effect=UpdateFailed("db")),
        patch(LEDGER_HISTORY, return_value=TemperatureHistory((), None, 0)),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    today = _state(hass, entry, "hdd_estimated_today")
    assert float(today.state) == 6.0
    assert today.attributes["coverage"] == 0.5
    assert today.attributes["partial"] is True
    assert today.attributes["reason"] == "recorder_failed"
    assert float(_state(hass, entry, "hdd_estimated_tomorrow").state) == 12.0


@pytest.mark.freeze_time(NOW)
async def test_service_failure_recovers_and_cache_expires(hass, weather, freezer):
    """Transient failures keep a valid cache, then expire to unknown, then recover."""
    entry = _add_entry(hass)
    await _setup(hass, entry)
    forecast = entry.runtime_data.forecast
    weather.error = HomeAssistantError("provider down")

    with patch(FORECAST_HISTORY, return_value=_observed()):
        freezer.move_to("2026-01-02 13:05:00+00:00")
        await forecast.async_refresh()
        tomorrow = _state(hass, entry, "hdd_estimated_tomorrow")
        assert float(tomorrow.state) == 12.0
        assert tomorrow.attributes["forecast_retrieved_at"].startswith(
            "2026-01-02T12:00"
        )

        freezer.move_to("2026-01-02 14:00:00+00:00")
        await forecast.async_refresh()
        tomorrow = _state(hass, entry, "hdd_estimated_tomorrow")
        assert tomorrow.state == "unknown"
        assert tomorrow.attributes["reason"] == "forecast_failed"
        assert tomorrow.attributes["coverage"] == 0
        assert tomorrow.attributes["date"] == "2026-01-03"
        today = _state(hass, entry, "hdd_estimated_today")
        assert today.attributes["coverage"] == pytest.approx(14 / 24)
        assert not ir.async_get(hass).async_get_issue(
            DOMAIN, f"forecast_source_{entry.entry_id}"
        )
        # Historical entities do not depend on forecast availability.
        assert entry.runtime_data.coordinator.last_update_success

        weather.error = None
        freezer.move_to("2026-01-02 14:06:00+00:00")
        await forecast.async_refresh()
        assert float(_state(hass, entry, "hdd_estimated_tomorrow").state) == 12.0


@pytest.mark.freeze_time("2026-01-02 23:59:00+00:00")
async def test_midnight_rollover_relabels_from_the_same_result(hass, weather, freezer):
    """After midnight, yesterday's tomorrow becomes today; labels follow values."""
    entry = _add_entry(hass)
    await _setup(hass, entry)
    assert _state(hass, entry, "hdd_estimated_tomorrow").attributes["date"] == (
        "2026-01-03"
    )
    freezer.move_to("2026-01-03 00:00:05+00:00")
    with patch(FORECAST_HISTORY, return_value=_observed()):
        await entry.runtime_data.forecast.async_refresh()
    today = _state(hass, entry, "hdd_estimated_today")
    assert today.attributes["date"] == "2026-01-03"
    tomorrow = _state(hass, entry, "hdd_estimated_tomorrow")
    assert tomorrow.attributes["date"] == "2026-01-04"
    # The 48-hour fixture ends at 2026-01-04 00:00: tomorrow is not covered.
    assert tomorrow.state == "unknown"
    assert tomorrow.attributes["reason"] == "no_coverage"


@pytest.mark.freeze_time(NOW)
async def test_weather_state_change_requests_a_spaced_refetch(hass, weather, freezer):
    """State changes are hints: they refetch, at most every five minutes."""
    entry = _add_entry(hass)
    await _setup(hass, entry)
    assert len(weather.calls) == 1
    with patch(FORECAST_HISTORY, return_value=_observed()):
        freezer.move_to("2026-01-02 12:06:00+00:00")
        weather.items = _forecast_items(temperature=0.0)
        weather.set_state("rainy")
        await hass.async_block_till_done()
        await entry.runtime_data.forecast.async_refresh()
        assert len(weather.calls) == 2
        assert float(_state(hass, entry, "hdd_estimated_tomorrow").state) == 18.0
        weather.set_state("sunny")
        await entry.runtime_data.forecast.async_refresh()
        assert len(weather.calls) == 2


@pytest.mark.freeze_time(NOW)
async def test_unsupported_hourly_creates_repair_resolved_by_reconfigure(
    hass, hass_storage
):
    """Persistent capability problems use Repairs; removing the source clears it."""
    FakeWeather(hass, features=1)
    entry = _add_entry(hass)
    await _setup(hass, entry)
    issue_id = f"forecast_source_{entry.entry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue.translation_key == "forecast_unsupported"
    today = _state(hass, entry, "hdd_estimated_today")
    assert today.attributes["reason"] == "forecast_unsupported"
    assert today.attributes["coverage"] == 0.5

    registry = er.async_get(hass)
    historical = _state(hass, entry, "hdd_daily").entity_id
    result = await entry.start_reconfigure_flow(hass)
    with (
        patch(FORECAST_HISTORY, return_value=_observed()),
        patch(LEDGER_HISTORY, return_value=TemperatureHistory((), None, 0)),
        patch(f"{PKG}.config_flow.async_remove_stored_data") as remove,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": entry.title,
                "temperature_sensor": SOURCE,
                "base_temperature": 18.0,
                "include_cooling": True,
                "include_weekly": True,
                "include_monthly": True,
            },
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    remove.assert_not_called()
    assert "weather_entity" not in entry.data
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert _state(hass, entry, "hdd_estimated_today") is None
    assert _state(hass, entry, "cdd_estimated_tomorrow") is None
    assert registry.async_get(historical) is not None


async def test_missing_weather_after_start_creates_repair(hass):
    """A weather entity absent once HA runs is a persistent source issue."""
    FakeWeather(hass)
    hass.states.async_remove(WEATHER)
    entry = _add_entry(hass)
    await _setup(hass, entry)
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, f"forecast_source_{entry.entry_id}"
    )
    assert issue.translation_key == "weather_missing"
    assert entry.state is ConfigEntryState.LOADED


@pytest.mark.freeze_time(NOW)
async def test_entries_are_isolated_and_unload_releases_listeners(hass, weather):
    """Two entries keep separate state; reloads leave no callbacks behind."""
    first = _add_entry(hass)
    second = _add_entry(hass, base_temperature=15.0, include_cooling=False)
    await _setup(hass, first)  # Setting up the domain loads both entries.
    assert second.state is ConfigEntryState.LOADED
    # Baseline after one full cycle: component-level listeners stay loaded.
    for entry in (first, second):
        assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    baseline = hass.bus.async_listeners()
    for entry in (first, second):
        await _setup(hass, entry)
    assert first.runtime_data.forecast is not second.runtime_data.forecast
    assert float(_state(hass, second, "hdd_estimated_tomorrow").state) == 9.0
    assert _state(hass, second, "cdd_estimated_today") is None
    for _ in range(2):
        with (
            patch(FORECAST_HISTORY, return_value=_observed()),
            patch(LEDGER_HISTORY, return_value=TemperatureHistory((), None, 0)),
        ):
            assert await hass.config_entries.async_reload(first.entry_id)
            await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(first.entry_id)
    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    assert hass.bus.async_listeners() == baseline


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {WEATHER: None},
        {WEATHER: {"forecast": "x"}},
        {"weather.other": {"forecast": []}},
    ],
)
def test_malformed_response_is_rejected(response):
    """Unexpected structures are explicit errors, not empty forecasts."""
    with pytest.raises(ForecastError):
        parse_forecast_response(response, WEATHER, "°C", "°C")


def test_invalid_items_are_dropped_or_gaps():
    """Naive or unparseable times are dropped; invalid temperatures are gaps."""
    points = parse_forecast_response(
        {
            WEATHER: {
                "forecast": [
                    {"datetime": "2026-01-02T00:00:00", "temperature": 5},
                    {"datetime": "garbage", "temperature": 5},
                    {"datetime": "2026-01-02T01:00:00+00:00", "temperature": None},
                    {"datetime": "2026-01-02T02:00:00+00:00", "temperature": True},
                    {"datetime": "2026-01-02T03:00:00+00:00", "temperature": 41},
                    "not a mapping",
                ]
            }
        },
        WEATHER,
        "°C",
        "°F",
    )
    assert [t for _, t in points] == [None, None, pytest.approx(5)]
    assert points[0][0] == datetime(2026, 1, 2, 1, tzinfo=UTC)
    assert date(2026, 1, 2) == points[0][0].date()


def test_unknown_weather_unit_is_rejected():
    """Temperatures without a known unit cannot be normalized."""
    with pytest.raises(ForecastError):
        parse_forecast_response({WEATHER: {"forecast": []}}, WEATHER, "°C", None)


@pytest.mark.parametrize(
    ("entity_id", "features", "error"),
    [
        (WEATHER, 2, None),
        (WEATHER, 3, None),
        (WEATHER, 1, "invalid_weather_entity"),
        ("weather.unknown", 2, "invalid_weather_entity"),
    ],
)
async def test_user_flow_validates_hourly_weather(hass, entity_id, features, error):
    """The optional weather entity must exist and provide hourly forecasts."""
    FakeWeather(hass, features=features)
    hass.states.async_set(
        SOURCE, "10", {"device_class": "temperature", "unit_of_measurement": "°C"}
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    with (
        patch(FORECAST_HISTORY, return_value=_observed()),
        patch(LEDGER_HISTORY, return_value=TemperatureHistory((), None, 0)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "temperature_sensor": SOURCE,
                "weather_entity": entity_id,
                "base_temperature": 18.0,
                "include_cooling": False,
                "include_weekly": True,
                "include_monthly": True,
            },
        )
        await hass.async_block_till_done()
    if error:
        assert result["errors"] == {"weather_entity": error}
    else:
        assert result["data"]["weather_entity"] == WEATHER


@pytest.mark.freeze_time(NOW)
async def test_weather_loading_after_us_is_fetched_immediately(hass):
    """A weather entity created after setup is fetched without waiting 5 minutes."""
    weather = FakeWeather(hass)
    hass.states.async_remove(WEATHER)
    entry = _add_entry(hass)
    await _setup(hass, entry)
    assert weather.calls == []
    with patch(FORECAST_HISTORY, return_value=_observed()):
        weather.set_state()
        await hass.async_block_till_done()
        await entry.runtime_data.forecast.async_refresh()
    assert len(weather.calls) == 1
    assert float(_state(hass, entry, "hdd_estimated_tomorrow").state) == 12.0
    assert (
        ir.async_get(hass).async_get_issue(DOMAIN, f"forecast_source_{entry.entry_id}")
        is None
    )
