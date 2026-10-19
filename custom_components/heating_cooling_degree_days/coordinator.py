"""Fetch bounded recorder history and publish consistent calendar snapshots."""

from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BASE_TEMPERATURE,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    DOMAIN,
    SCAN_INTERVAL,
)
from .degree_days import CALCULATION_REVISION, DayResult, integrate_degree_days
from .history import TemperatureHistory, get_temperature_history
from .periods import (
    DailyRecord,
    aggregate_period,
    calendar_periods,
    day_seconds,
    day_window,
)
from .source import CONF_SOURCE_REGISTRY_ID, SourceTracker

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 2
STORAGE_KEY = f"{DOMAIN}_data"
MAX_BACKFILL_DAYS = 7
PARTIAL_RETRY_INTERVAL = timedelta(hours=6)


class DailyLedgerStore(Store[dict]):
    """Migrate scalar histories without fabricating measured coverage."""

    async def _async_migrate_func(self, old_major_version, old_minor_version, old_data):
        """Retain v1 HDD/CDD values and mark their coverage as legacy/assumed."""
        if old_major_version != 1:
            raise NotImplementedError
        hdd = old_data.get("daily_hdd_values", old_data.get("daily_values", {}))
        cdd = old_data.get("daily_cdd_values", {})
        return {
            "config": old_data.get("config"),
            "days": {
                day: asdict(
                    DailyRecord(
                        hdd.get(day),
                        cdd.get(day),
                        None,
                        day_seconds(date.fromisoformat(day), dt_util.DEFAULT_TIME_ZONE),
                        None,
                        legacy=True,
                    )
                )
                for day in hdd.keys() | cdd.keys()
            },
        }


async def async_remove_stored_data(hass: HomeAssistant, entry_id: str) -> None:
    """Drop daily values when calculation settings change."""
    await Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}").async_remove()


class HDDDataUpdateCoordinator(DataUpdateCoordinator[dict[str, float | None]]):
    """Manage the entry's ledger and its published value/metadata snapshot."""

    def __init__(
        self,
        hass: HomeAssistant,
        temp_entity: str,
        base_temp: float,
        temperature_unit: str,
        entry_id: str,
        *,
        source: SourceTracker | None = None,
        include_cooling: bool = False,
        include_weekly: bool = True,
        include_monthly: bool = True,
    ):
        """Initialize per-entry storage and calculation settings."""
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.source = source
        self.source_missing = False
        self.temp_entity = temp_entity
        self.base_temp = base_temp
        self.temperature_unit = temperature_unit
        self.entry_id = entry_id
        self.include_cooling = include_cooling
        self.include_weekly = include_weekly
        self.include_monthly = include_monthly
        self.ledger: dict[date, DailyRecord] = {}
        self.period_attributes: dict[str, dict] = {}
        self.last_refresh_time: datetime | None = None
        self.day_result: DayResult | None = None
        self.temperature_history: TemperatureHistory | None = None
        self._store = DailyLedgerStore(
            hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}"
        )

    @property
    def daily_hdd_values(self) -> dict[date, float]:
        """Return measured HDD values, excluding days without observations."""
        return {
            day: record.hdd
            for day, record in self.ledger.items()
            if record.hdd is not None
        }

    @property
    def daily_cdd_values(self) -> dict[date, float]:
        """Return measured CDD values, excluding days without observations."""
        return {
            day: record.cdd
            for day, record in self.ledger.items()
            if record.cdd is not None
        }

    def _config_fingerprint(self) -> dict:
        """Identify the source/base/unit shared by every record in this ledger."""
        identity = (
            {CONF_SOURCE_REGISTRY_ID: self.source.registry_id}
            if self.source and self.source.registry_id
            else {CONF_TEMPERATURE_SENSOR: self.temp_entity}
        )
        return {
            **identity,
            CONF_BASE_TEMPERATURE: self.base_temp,
            CONF_TEMPERATURE_UNIT: self.temperature_unit,
        }

    async def async_load_stored_data(self) -> None:
        """Load or invalidate the ledger; storage failures must not erase history."""
        stored = await self._store.async_load()
        if not stored:
            return
        legacy_fingerprint = {
            CONF_TEMPERATURE_SENSOR: (
                self.source.previous_entity_id if self.source else self.temp_entity
            ),
            CONF_BASE_TEMPERATURE: self.base_temp,
            CONF_TEMPERATURE_UNIT: self.temperature_unit,
        }
        if stored.get("config") not in (
            None,
            self._config_fingerprint(),
            legacy_fingerprint,
        ):
            _LOGGER.info("Calculation settings changed: rebuilding the daily ledger")
            self.ledger = {}
            await self._save_ledger(self.ledger)
            return
        self.ledger = {
            date.fromisoformat(day): DailyRecord(**record)
            for day, record in stored.get("days", {}).items()
        }
        if stored.get("config") != self._config_fingerprint():
            await self._save_ledger(self.ledger)

    async def _save_ledger(self, ledger: dict[date, DailyRecord]) -> None:
        """Persist full precision and retry timestamps under one calculation fingerprint."""
        await self._store.async_save(
            {
                "config": self._config_fingerprint(),
                "days": {
                    day.isoformat(): asdict(record) for day, record in ledger.items()
                },
            }
        )

    def _backfill_dates(self, needed: set[date], now: datetime) -> list[date]:
        """Prioritize yesterday, then unqueried days; retry partials every six hours."""
        recorder = get_instance(self.hass)
        cutoff = now.timestamp() - timedelta(days=recorder.keep_days).total_seconds()
        candidates = []
        for day in needed:
            record = self.ledger.get(day)
            if record and record.complete:
                continue
            needs_revision = (
                record is not None
                and record.last_attempt_revision < CALCULATION_REVISION
            )
            _, end = day_window(day, now.tzinfo)
            if (
                recorder.auto_purge
                and end.timestamp() <= cutoff
                and not needs_revision
                and not (record and record.legacy and not record.last_attempt)
            ):
                # Probe legacy and outdated incomplete days once even outside
                # nominal retention: recorder may still hold recoverable history.
                continue
            if (
                record
                and not needs_revision
                and now.timestamp() - record.last_attempt
                < PARTIAL_RETRY_INTERVAL.total_seconds()
            ):
                continue
            candidates.append(day)
        yesterday = now.date() - timedelta(days=1)
        candidates.sort(
            key=lambda day: (
                day != yesterday,
                self.ledger[day].last_attempt if day in self.ledger else 0,
                -day.toordinal(),
            )
        )
        return candidates[:MAX_BACKFILL_DAYS]

    @callback
    def async_update_source_status(self) -> None:
        """Publish live source status without waiting for backfill or clearing errors."""
        missing = self.source is not None and not self.source.async_available()
        changed = self.source_missing != missing or any(
            attrs.get("source_missing") != missing
            for attrs in self.period_attributes.values()
        )
        self.source_missing = missing
        if changed:
            self.period_attributes = {
                key: {**attrs, "source_missing": missing}
                for key, attrs in self.period_attributes.items()
            }
            self.async_update_listeners()

    async def async_midnight_refresh(self, _now: datetime) -> None:
        """Roll calendar periods over shortly after local midnight."""
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, float | None]:
        """Backfill bounded history, then atomically publish values and their labels."""
        # Timestamp the attempt even if a recorder read or storage write fails.
        self.last_refresh_time = dt_util.utcnow()
        self.async_update_source_status()
        now = dt_util.now()
        periods = calendar_periods(now.date())
        if not self.include_weekly:
            del periods["weekly"]
        if not self.include_monthly:
            del periods["monthly"]
        needed = {day for period in periods.values() for day in period.completed_days}
        ledger = {
            day: record
            for day, record in self.ledger.items()
            if day >= now.date() - timedelta(days=60)
        }
        yesterday = now.date() - timedelta(days=1)
        yesterday_history = (
            self.temperature_history
            if self.period_attributes.get("hdd_daily", {}).get("period_start")
            == str(yesterday)
            else None
        )
        # A removed source can leave an old numeric recorder state behind. Do not
        # extrapolate it into newly completed days while the source is missing.
        dates = [] if self.source_missing else self._backfill_dates(needed, now)
        for day in dates:
            start, end = day_window(day, now.tzinfo)
            history = await get_temperature_history(
                self.hass,
                start,
                end,
                self.temp_entity,
                self.temperature_unit,
            )
            result = integrate_degree_days(history.samples, start, end, self.base_temp)
            record = DailyRecord.from_result(result, now)
            old = ledger.get(day)
            # Outside legacy correction, a purge or rewritten history must not
            # reduce an accumulating total.
            # Keep the entire previous observation (including coverage/mean),
            # rather than combining incompatible values from two recorder reads.
            if old and old.legacy:
                # Legacy scalar methods can be wrong in either direction. Replace
                # them once, only with a fully covered day, even if totals fall.
                if not record.complete:
                    record = replace(
                        old,
                        last_attempt=now.timestamp(),
                        last_attempt_revision=CALCULATION_REVISION,
                    )
                elif day == yesterday:
                    yesterday_history = history
            elif old and (
                (old.coverage_seconds or 0) >= result.coverage_seconds
                or (old.hdd or 0) > result.hdd
                or (old.cdd or 0) > result.cdd
            ):
                record = replace(
                    old,
                    last_attempt=now.timestamp(),
                    last_attempt_revision=CALCULATION_REVISION,
                )
            elif day == yesterday:
                yesterday_history = history
            ledger[day] = record

        if ledger != self.ledger:
            await self._save_ledger(ledger)
        values = {}
        attributes = {}
        for metric in ("hdd", "cdd") if self.include_cooling else ("hdd",):
            for name, period in periods.items():
                key = f"{metric}_{name}"
                values[key], attributes[key] = aggregate_period(
                    ledger, period, metric, now.tzinfo
                )
                attributes[key]["source_missing"] = self.source_missing
                if (
                    name == "daily"
                    and (record := ledger.get(yesterday))
                    and record.mean_temp is not None
                ):
                    attributes[key]["mean_temperature"] = round(record.mean_temp, 1)
        # Nothing observable changes until all recorder reads and the save succeed.
        self.ledger = ledger
        self.period_attributes = attributes
        self.temperature_history = yesterday_history
        record = ledger.get(yesterday)
        self.day_result = (
            DayResult(
                record.hdd or 0,
                record.cdd or 0,
                record.coverage_seconds or 0,
                record.window_seconds,
                record.mean_temp,
            )
            if record
            else None
        )
        return values
