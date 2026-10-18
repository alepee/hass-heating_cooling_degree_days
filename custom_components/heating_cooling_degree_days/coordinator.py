"""Fetch bounded recorder history and publish consistent calendar snapshots."""

from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.core import HomeAssistant
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
from .degree_days import DayResult, integrate_degree_days
from .history import TemperatureHistory, get_temperature_history
from .periods import (
    DailyRecord,
    aggregate_period,
    calendar_periods,
    day_seconds,
    day_window,
)

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
        include_cooling: bool = False,
        include_weekly: bool = True,
        include_monthly: bool = True,
    ):
        """Initialize per-entry storage and calculation settings."""
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.temp_entity = temp_entity
        self.base_temp = base_temp
        self.temperature_unit = temperature_unit
        self.entry_id = entry_id
        self.include_cooling = include_cooling
        self.include_weekly = include_weekly
        self.include_monthly = include_monthly
        self.ledger: dict[date, DailyRecord] = {}
        self.period_attributes: dict[str, dict] = {}
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
        return {
            CONF_TEMPERATURE_SENSOR: self.temp_entity,
            CONF_BASE_TEMPERATURE: self.base_temp,
            CONF_TEMPERATURE_UNIT: self.temperature_unit,
        }

    async def async_load_stored_data(self) -> None:
        """Load or invalidate the ledger; storage failures must not erase history."""
        stored = await self._store.async_load()
        if not stored:
            return
        if stored.get("config") not in (None, self._config_fingerprint()):
            _LOGGER.info("Calculation settings changed: rebuilding the daily ledger")
            self.ledger = {}
            await self._save_ledger(self.ledger)
            return
        self.ledger = {
            date.fromisoformat(day): DailyRecord(**record)
            for day, record in stored.get("days", {}).items()
        }
        if stored.get("config") is None:
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
            _, end = day_window(day, now.tzinfo)
            if recorder.auto_purge and end.timestamp() <= cutoff:
                continue
            if (
                record
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

    async def async_midnight_refresh(self, _now: datetime) -> None:
        """Roll calendar periods over shortly after local midnight."""
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict[str, float | None]:
        """Backfill bounded history, then atomically publish values and their labels."""
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
        for day in self._backfill_dates(needed, now):
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
            # A purge or rewritten history must not reduce an accumulating total.
            # Keep the entire previous observation (including coverage/mean),
            # rather than combining incompatible values from two recorder reads.
            if old and (
                (old.coverage_seconds or 0) >= result.coverage_seconds
                or (old.hdd or 0) > result.hdd
                or (old.cdd or 0) > result.cdd
            ):
                record = replace(old, last_attempt=now.timestamp())
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
