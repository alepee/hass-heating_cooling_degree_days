"""Calendar-day degree-day estimates for today and tomorrow from hourly forecasts.

The weather adapter only uses the public ``weather.get_forecasts`` service. The
estimate coordinator is independent of the historical one: a forecast or
recorder failure lowers coverage and sets a reason on the estimates, it never
makes historical sensors unavailable or enters the completed-day ledger.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from math import isfinite
from typing import Any

from homeassistant.const import ATTR_SUPPORTED_FEATURES
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import DOMAIN, SCAN_INTERVAL
from .degree_days import (
    DayResult,
    TemperatureSample,
    combine_results,
    forecast_samples,
    integrate_degree_days,
)
from .history import get_temperature_history
from .periods import day_window

_LOGGER = logging.getLogger(__name__)

WEATHER_DOMAIN = "weather"
SERVICE_GET_FORECASTS = "get_forecasts"
ATTR_WEATHER_TEMPERATURE_UNIT = "temperature_unit"
# weather.WeatherEntityFeature.FORECAST_HOURLY, without importing the component.
FEATURE_FORECAST_HOURLY = 2

# Retrieval policy: refetch hourly, use a payload for at most two hours, accept
# forecast points up to three hours apart. A final or isolated point holds for
# one nominal hourly step. Failed or requested fetches are spaced by 5 minutes.
FORECAST_FETCH_INTERVAL = timedelta(hours=1)
FORECAST_CACHE_LIFETIME = timedelta(hours=2)
FORECAST_STEP = timedelta(hours=1)
FORECAST_MAX_INTERVAL = timedelta(hours=3)
FORECAST_MIN_FETCH_SPACING = timedelta(minutes=5)
FORECAST_TIMEOUT = 30

# Reasons published in the estimates' ``reason`` attribute.
REASON_WEATHER_MISSING = "weather_missing"
REASON_FORECAST_UNSUPPORTED = "forecast_unsupported"
REASON_FORECAST_FAILED = "forecast_failed"
REASON_FORECAST_INVALID = "forecast_invalid"
REASON_FORECAST_EXPIRED = "forecast_expired"
REASON_RECORDER_FAILED = "recorder_failed"
REASON_SOURCE_MISSING = "source_missing"
REASON_NO_COVERAGE = "no_coverage"


class ForecastError(Exception):
    """A forecast retrieval failure; persistent ones are surfaced in Repairs."""

    def __init__(self, reason: str, *, persistent: bool = False) -> None:
        """Store the published reason."""
        super().__init__(reason)
        self.reason = reason
        self.persistent = persistent


@dataclass(frozen=True, slots=True)
class ForecastPayload:
    """Normalized hourly forecast held samples from one retrieval."""

    entity_id: str
    retrieved_at: datetime
    samples: tuple[TemperatureSample, ...]
    point_count: int


@dataclass(frozen=True, slots=True)
class Estimate:
    """One calendar day's estimate; value and labels come from this result."""

    day: date
    start: datetime
    end: datetime
    result: DayResult | None
    reasons: tuple[str, ...]

    def value(self, metric: str) -> float | None:
        """Return the unrounded covered contribution, or None without coverage."""
        if self.result is None or not self.result.coverage_seconds:
            return None
        return getattr(self.result, metric)

    @property
    def coverage(self) -> float:
        """Covered fraction of the full calendar day."""
        if self.result is None:
            return 0.0
        return min(self.result.coverage_seconds / self.result.window_seconds, 1.0)


@dataclass(frozen=True, slots=True)
class EstimateSnapshot:
    """Today's and tomorrow's estimates from one calculation instant."""

    as_of: datetime
    retrieved_at: datetime | None
    today: Estimate
    tomorrow: Estimate


def parse_forecast_response(
    response: Any, entity_id: str, calculation_unit: str, source_unit: str | None
) -> list[tuple[datetime, float | None]]:
    """Validate a get_forecasts response and convert temperatures per entity unit.

    Items with an unparseable or naive timestamp are dropped. Items with a
    missing, non-numeric or non-finite temperature become gaps.
    """
    if not isinstance(response, Mapping):
        raise ForecastError(REASON_FORECAST_INVALID)
    entity_response = response.get(entity_id)
    if not isinstance(entity_response, Mapping):
        raise ForecastError(REASON_FORECAST_INVALID)
    forecast = entity_response.get("forecast")
    if not isinstance(forecast, list):
        raise ForecastError(REASON_FORECAST_INVALID)
    if source_unit not in TemperatureConverter.VALID_UNITS:
        raise ForecastError(REASON_FORECAST_INVALID)

    points = []
    for item in forecast:
        if not isinstance(item, Mapping):
            continue
        raw_time = item.get("datetime")
        when = dt_util.parse_datetime(raw_time) if isinstance(raw_time, str) else None
        if when is None or when.utcoffset() is None:
            continue
        temperature = None
        raw_temperature = item.get("temperature")
        if isinstance(raw_temperature, int | float) and not isinstance(
            raw_temperature, bool
        ):
            converted = TemperatureConverter.convert(
                float(raw_temperature), source_unit, calculation_unit
            )
            if isfinite(converted):
                temperature = converted
        points.append((when, temperature))
    return points


async def async_fetch_forecast(
    hass: HomeAssistant, entity_id: str, calculation_unit: str
) -> ForecastPayload:
    """Fetch hourly forecasts through the public weather service."""
    state = hass.states.get(entity_id)
    if state is None:
        # Weather integrations can load after us; only a running HA confirms it.
        raise ForecastError(
            REASON_WEATHER_MISSING, persistent=hass.state is CoreState.running
        )
    features = state.attributes.get(ATTR_SUPPORTED_FEATURES) or 0
    if not features & FEATURE_FORECAST_HOURLY:
        raise ForecastError(REASON_FORECAST_UNSUPPORTED, persistent=True)
    try:
        async with asyncio.timeout(FORECAST_TIMEOUT):
            response = await hass.services.async_call(
                WEATHER_DOMAIN,
                SERVICE_GET_FORECASTS,
                {"entity_id": entity_id, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
    except (HomeAssistantError, TimeoutError) as err:
        _LOGGER.debug("Hourly forecast retrieval failed for %s: %s", entity_id, err)
        raise ForecastError(REASON_FORECAST_FAILED) from err

    points = parse_forecast_response(
        response,
        entity_id,
        calculation_unit,
        state.attributes.get(ATTR_WEATHER_TEMPERATURE_UNIT),
    )
    return ForecastPayload(
        entity_id=entity_id,
        retrieved_at=dt_util.utcnow(),
        samples=forecast_samples(
            points,
            FORECAST_STEP.total_seconds(),
            FORECAST_MAX_INTERVAL.total_seconds(),
        ),
        point_count=len(points),
    )


def estimate_day(
    day: date,
    zone,
    *,
    base_temp: float,
    as_of: datetime,
    observed: tuple[TemperatureSample, ...] | None,
    forecast: tuple[TemperatureSample, ...] | None,
    reasons: tuple[str, ...] = (),
) -> Estimate:
    """Combine observations before as_of and forecasts after it over one local day.

    ``None`` sources contribute no coverage. Windows are disjoint, so their
    unrounded contributions and covered seconds add up; nothing is scaled up.
    """
    start, end = day_window(day, zone)
    window_seconds = end.timestamp() - start.timestamp()
    cutover = min(max(as_of, start), end)
    parts = []
    if observed is not None and cutover > start:
        parts.append(integrate_degree_days(observed, start, cutover, base_temp))
    if forecast is not None and cutover < end:
        parts.append(integrate_degree_days(forecast, cutover, end, base_temp))
    result = combine_results(parts, window_seconds)
    if not result.coverage_seconds and not reasons:
        reasons = (REASON_NO_COVERAGE,)
    return Estimate(day, start, end, result, reasons)


@callback
def async_clear_forecast_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Remove only this entry's forecast-source repair."""
    ir.async_delete_issue(hass, DOMAIN, f"forecast_source_{entry_id}")


class ForecastCoordinator(DataUpdateCoordinator[EstimateSnapshot]):
    """Own forecast retrieval, caching and today/tomorrow recomputation."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry,
        weather_entity: str,
        temp_entity: str,
        base_temp: float,
        temperature_unit: str,
        source_missing: Callable[[], bool] = lambda: False,
    ) -> None:
        """Initialize an entry's estimate state."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} forecast",
            update_interval=SCAN_INTERVAL,
        )
        self.entry = entry
        self.weather_entity = weather_entity
        self.temp_entity = temp_entity
        self.base_temp = base_temp
        self.temperature_unit = temperature_unit
        self._source_missing = source_missing
        self.payload: ForecastPayload | None = None
        self.forecast_reason: str | None = None
        self._last_attempt: datetime | None = None
        self._fetch_requested = False

    @callback
    def async_request_forecast(self) -> None:
        """Refetch at the next refresh; weather state changes are only hints."""
        self._fetch_requested = True
        self.entry.async_create_background_task(
            self.hass, self.async_request_refresh(), "forecast weather update"
        )

    def _fetch_due(self, now: datetime) -> bool:
        if (
            self._last_attempt is not None
            and now - self._last_attempt < FORECAST_MIN_FETCH_SPACING
        ):
            return False
        return (
            self._fetch_requested
            or self.payload is None
            or now - self.payload.retrieved_at >= FORECAST_FETCH_INTERVAL
        )

    async def _async_refresh_payload(self, now: datetime) -> None:
        if not self._fetch_due(now):
            return
        self._last_attempt = now
        self._fetch_requested = False
        try:
            self.payload = await async_fetch_forecast(
                self.hass, self.weather_entity, self.temperature_unit
            )
        except ForecastError as err:
            self.forecast_reason = err.reason
            if err.reason in (REASON_WEATHER_MISSING, REASON_FORECAST_UNSUPPORTED):
                # No service call was made: retry as soon as the weather entity
                # appears or changes (e.g. it loads after this integration).
                self._last_attempt = None
            if err.persistent:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"forecast_source_{self.entry.entry_id}",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=err.reason,
                    translation_placeholders={
                        "name": self.entry.title,
                        "entity_id": self.weather_entity,
                        "url": f"/config/integrations/integration/{DOMAIN}",
                    },
                )
        else:
            self.forecast_reason = None
            async_clear_forecast_issue(self.hass, self.entry.entry_id)

    async def _async_update_data(self) -> EstimateSnapshot:
        """Recompute from the cached payload; failures lower coverage only."""
        now_utc = dt_util.utcnow()
        await self._async_refresh_payload(now_utc)
        payload = self.payload
        forecast_reasons: tuple[str, ...] = ()
        if payload and now_utc - payload.retrieved_at >= FORECAST_CACHE_LIFETIME:
            payload = None
            forecast_reasons = (self.forecast_reason or REASON_FORECAST_EXPIRED,)
        elif payload is None:
            forecast_reasons = (self.forecast_reason or REASON_FORECAST_FAILED,)
        forecast = payload.samples if payload else None

        now = dt_util.as_local(now_utc)
        zone = now.tzinfo
        today = now.date()
        start, _ = day_window(today, zone)
        observed = None
        observed_reasons: tuple[str, ...] = ()
        if self._source_missing():
            # Do not extrapolate a removed source's last recorder state.
            observed_reasons = (REASON_SOURCE_MISSING,)
        else:
            try:
                history = await get_temperature_history(
                    self.hass, start, now, self.temp_entity, self.temperature_unit
                )
            except UpdateFailed as err:
                _LOGGER.debug("Today's observations are unavailable: %s", err)
                observed_reasons = (REASON_RECORDER_FAILED,)
            else:
                observed = history.samples

        return EstimateSnapshot(
            as_of=now_utc,
            retrieved_at=payload.retrieved_at if payload else None,
            today=estimate_day(
                today,
                zone,
                base_temp=self.base_temp,
                as_of=now_utc,
                observed=observed,
                forecast=forecast,
                reasons=observed_reasons + forecast_reasons,
            ),
            tomorrow=estimate_day(
                today + timedelta(days=1),
                zone,
                base_temp=self.base_temp,
                as_of=now_utc,
                observed=None,
                forecast=forecast,
                reasons=forecast_reasons,
            ),
        )

    async def async_midnight_refresh(self, _now: datetime) -> None:
        """Move today/tomorrow to the new calendar dates."""
        await self.async_request_refresh()

    @callback
    def async_track(self) -> None:
        """Attach entry-owned midnight and weather-state listeners."""

        @callback
        def weather_changed(_event) -> None:
            self.async_request_forecast()

        self.entry.async_on_unload(
            async_track_time_change(
                self.hass, self.async_midnight_refresh, hour=0, minute=0, second=5
            )
        )
        self.entry.async_on_unload(
            async_track_state_change_event(
                self.hass, self.weather_entity, weather_changed
            )
        )
