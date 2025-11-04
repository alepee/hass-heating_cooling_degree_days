"""DataUpdateCoordinator for heating_cooling_degree_days."""

import calendar
from collections import defaultdict
from datetime import date, timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .calculations import (
    calculate_cdd_from_readings,
    calculate_hdd_from_readings,
    get_temperature_readings,
)
from .const import (
    DOMAIN,
    SCAN_INTERVAL,
    SENSOR_TYPE_CDD_DAILY,
    SENSOR_TYPE_CDD_MONTHLY,
    SENSOR_TYPE_CDD_WEEKLY,
    SENSOR_TYPE_HDD_DAILY,
    SENSOR_TYPE_HDD_MONTHLY,
    SENSOR_TYPE_HDD_WEEKLY,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_data"


class HDDDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching HDD and CDD data."""

    def __init__(
        self,
        hass: HomeAssistant,
        temp_entity: str,
        base_temp: float,
        temperature_unit: str,
        entry_id: str,
        include_cooling: bool = False,
        include_weekly: bool = True,
        include_monthly: bool = True,
    ):
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.temp_entity = temp_entity
        self.base_temp = base_temp
        self.temperature_unit = temperature_unit
        self.entry_id = entry_id
        self.include_cooling = include_cooling
        self.include_weekly = include_weekly
        self.include_monthly = include_monthly
        self.temperature_history = []
        self.daily_hdd_values = defaultdict(
            float
        )  # Storage for daily HDD values by date
        self.daily_cdd_values = defaultdict(
            float
        )  # Storage for daily CDD values by date

        # Initialize storage for persistent data
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}_{entry_id}",
        )

        _LOGGER.info(
            "Initialized HDDDataUpdateCoordinator with sensor %s, base temp %.1f°%s, "
            "cooling: %s, weekly: %s, monthly: %s",
            temp_entity,
            base_temp,
            temperature_unit,
            "enabled" if include_cooling else "disabled",
            "enabled" if include_weekly else "disabled",
            "enabled" if include_monthly else "disabled",
        )

    async def async_load_stored_data(self):
        """Load stored daily values from persistent storage."""
        try:
            stored_data = await self._store.async_load()
            if stored_data:
                # Convert date strings back to date objects
                # Support both old "daily_values" key and new "daily_hdd_values" key for backward compatibility
                hdd_key = (
                    "daily_hdd_values"
                    if "daily_hdd_values" in stored_data
                    else "daily_values"
                )
                if hdd_key in stored_data:
                    loaded_values = {
                        date.fromisoformat(date_str): value
                        for date_str, value in stored_data[hdd_key].items()
                    }
                    # Convert back to defaultdict for consistency
                    self.daily_hdd_values = defaultdict(float, loaded_values)
                    _LOGGER.info(
                        "Loaded %d HDD daily values from storage",
                        len(self.daily_hdd_values),
                    )

                if "daily_cdd_values" in stored_data:
                    loaded_cdd_values = {
                        date.fromisoformat(date_str): value
                        for date_str, value in stored_data["daily_cdd_values"].items()
                    }
                    # Convert back to defaultdict for consistency
                    self.daily_cdd_values = defaultdict(float, loaded_cdd_values)
                    _LOGGER.info(
                        "Loaded %d CDD daily values from storage",
                        len(self.daily_cdd_values),
                    )
            else:
                _LOGGER.debug("No stored data found, starting with empty history")
        except Exception as ex:
            _LOGGER.warning(
                "Error loading stored data: %s. Starting with empty history.", str(ex)
            )
            # Reset to empty dictionaries on error
            self.daily_hdd_values = defaultdict(float)
            self.daily_cdd_values = defaultdict(float)

    async def async_save_data(self):
        """Save daily values to persistent storage."""
        try:
            # Convert date objects to ISO format strings for JSON serialization
            data_to_save = {
                "daily_hdd_values": {
                    date_obj.isoformat(): value
                    for date_obj, value in self.daily_hdd_values.items()
                },
                "daily_cdd_values": {
                    date_obj.isoformat(): value
                    for date_obj, value in self.daily_cdd_values.items()
                },
            }
            await self._store.async_save(data_to_save)
            _LOGGER.debug(
                "Saved %d HDD and %d CDD daily values to storage",
                len(self.daily_hdd_values),
                len(self.daily_cdd_values),
            )
        except Exception as ex:
            _LOGGER.error("Error saving data to storage: %s", str(ex))

    async def _async_update_data(self):
        """Update data via library."""
        now = dt_util.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        yesterday_date = yesterday_start.date()

        _LOGGER.debug(
            "Starting data update for period %s to %s",
            yesterday_start.isoformat(),
            today_start.isoformat(),
        )

        # Get temperature readings for yesterday (full day)
        daily_readings = await get_temperature_readings(
            self.hass,
            yesterday_start,
            today_start,
            self.temp_entity,
        )

        if not daily_readings:
            _LOGGER.warning(
                "No temperature readings found for %s between %s and %s",
                self.temp_entity,
                yesterday_start.isoformat(),
                today_start.isoformat(),
            )
            # Prepare empty result based on enabled types
            result = {
                SENSOR_TYPE_HDD_DAILY: 0,
            }

            if self.include_weekly:
                result[SENSOR_TYPE_HDD_WEEKLY] = 0

            if self.include_monthly:
                result[SENSOR_TYPE_HDD_MONTHLY] = 0

            if self.include_cooling:
                result[SENSOR_TYPE_CDD_DAILY] = 0

                if self.include_weekly:
                    result[SENSOR_TYPE_CDD_WEEKLY] = 0

                if self.include_monthly:
                    result[SENSOR_TYPE_CDD_MONTHLY] = 0

            return self.data if self.data else result

        _LOGGER.debug("Retrieved %d temperature readings", len(daily_readings))

        # Store the most recent readings for attributes
        self.temperature_history = daily_readings

        # Calculate daily HDD using integration method
        # (Integration method as requested by the user)
        daily_hdd = calculate_hdd_from_readings(daily_readings, self.base_temp)
        daily_cdd = 0

        # Store in daily values history - use yesterday as it's a complete day
        data_changed = False
        if daily_readings:
            self.daily_hdd_values[yesterday_date] = daily_hdd
            data_changed = True
            _LOGGER.debug(
                "Calculated daily HDD for %s: %.2f (from %d readings)",
                yesterday_date,
                daily_hdd,
                len(daily_readings),
            )

            # Calculate and store CDD if enabled
            if self.include_cooling:
                daily_cdd = calculate_cdd_from_readings(daily_readings, self.base_temp)
                self.daily_cdd_values[yesterday_date] = daily_cdd
                data_changed = True
                _LOGGER.debug(
                    "Calculated daily CDD for %s: %.2f (from %d readings)",
                    yesterday_date,
                    daily_cdd,
                    len(daily_readings),
                )

        # Clean up old data (keep 60 days maximum)
        old_hdd_count, old_cdd_count = self._cleanup_old_data(60)
        if old_hdd_count or old_cdd_count:
            data_changed = True
            _LOGGER.debug(
                "Cleaned up %d old HDD values and %d old CDD values",
                old_hdd_count,
                old_cdd_count,
            )

        # Save data to persistent storage if it changed
        if data_changed:
            await self.async_save_data()

        # Prepare result dict - daily values are always included
        result = {
            SENSOR_TYPE_HDD_DAILY: daily_hdd,
        }

        # Add weekly and monthly HDD if enabled
        if self.include_weekly:
            weekly_hdd = self._calculate_current_week_hdd(yesterday_date)
            result[SENSOR_TYPE_HDD_WEEKLY] = weekly_hdd
            _LOGGER.debug("Calculated weekly HDD: %.2f", weekly_hdd)

        if self.include_monthly:
            monthly_hdd = self._calculate_current_month_hdd(yesterday_date)
            result[SENSOR_TYPE_HDD_MONTHLY] = monthly_hdd
            _LOGGER.debug("Calculated monthly HDD: %.2f", monthly_hdd)

        # Add CDD data if enabled
        if self.include_cooling:
            result[SENSOR_TYPE_CDD_DAILY] = daily_cdd

            if self.include_weekly:
                weekly_cdd = self._calculate_current_week_cdd(yesterday_date)
                result[SENSOR_TYPE_CDD_WEEKLY] = weekly_cdd
                _LOGGER.debug("Calculated weekly CDD: %.2f", weekly_cdd)

            if self.include_monthly:
                monthly_cdd = self._calculate_current_month_cdd(yesterday_date)
                result[SENSOR_TYPE_CDD_MONTHLY] = monthly_cdd
                _LOGGER.debug("Calculated monthly CDD: %.2f", monthly_cdd)

        return result

    def _cleanup_old_data(self, days_to_keep):
        """Remove old data from daily values history."""
        cutoff_date = dt_util.now().date() - timedelta(days=days_to_keep)

        # Count items to be removed for logging
        hdd_before_count = len(self.daily_hdd_values)
        cdd_before_count = len(self.daily_cdd_values)

        # Create new dictionaries with only recent values
        filtered_hdd = {
            date: value
            for date, value in self.daily_hdd_values.items()
            if date >= cutoff_date
        }
        self.daily_hdd_values = defaultdict(float, filtered_hdd)

        filtered_cdd = {
            date: value
            for date, value in self.daily_cdd_values.items()
            if date >= cutoff_date
        }
        self.daily_cdd_values = defaultdict(float, filtered_cdd)

        # Return count of removed items
        return (
            hdd_before_count - len(self.daily_hdd_values),
            cdd_before_count - len(self.daily_cdd_values),
        )

    def _calculate_current_week_hdd(self, reference_date):
        """Calculate weekly HDD by summing daily values.

        Week is defined as Monday to Sunday.
        """
        # Determine the start of the week (Monday)
        weekday = reference_date.weekday()
        week_start = reference_date - timedelta(days=weekday)
        week_end = week_start + timedelta(days=6)

        _LOGGER.debug(
            "Calculating weekly HDD from %s to %s",
            week_start.isoformat(),
            week_end.isoformat(),
        )

        # Check for missing data in the week
        missing_dates = []
        for i in range(7):
            current_date = week_start + timedelta(days=i)
            if (
                current_date <= dt_util.now().date()
                and current_date not in self.daily_hdd_values
            ):
                missing_dates.append(current_date)

        if missing_dates:
            _LOGGER.debug(
                "Missing HDD data for dates in current week: %s",
                ", ".join(date.isoformat() for date in missing_dates),
            )

        # Sum all daily values that fall within this week
        weekly_hdd = 0
        for i in range(7):  # Monday to Sunday
            current_date = week_start + timedelta(days=i)
            daily_value = self.daily_hdd_values.get(current_date, 0)
            weekly_hdd += daily_value

        return weekly_hdd

    def _calculate_current_month_hdd(self, reference_date):
        """Calculate monthly HDD by summing daily values.

        Month is defined as 1st to last day of the month.
        """
        # First day of current month
        month_start = reference_date.replace(day=1)

        # Last day of current month
        _, last_day = calendar.monthrange(reference_date.year, reference_date.month)
        month_end = reference_date.replace(day=last_day)

        _LOGGER.debug(
            "Calculating monthly HDD from %s to %s",
            month_start.isoformat(),
            month_end.isoformat(),
        )

        # Check for missing data in the month
        missing_dates = []
        current_date = month_start
        while current_date <= min(dt_util.now().date(), month_end):
            if current_date not in self.daily_hdd_values:
                missing_dates.append(current_date)
            current_date += timedelta(days=1)

        if missing_dates:
            _LOGGER.debug(
                "Missing HDD data for dates in current month: %s",
                ", ".join(date.isoformat() for date in missing_dates[:5])
                + (
                    f" and {len(missing_dates) - 5} more"
                    if len(missing_dates) > 5
                    else ""
                ),
            )

        # Sum all daily values that fall within this month
        monthly_hdd = 0
        current_date = month_start

        while current_date <= month_end:
            monthly_hdd += self.daily_hdd_values.get(current_date, 0)
            current_date += timedelta(days=1)

        return monthly_hdd

    def _calculate_current_week_cdd(self, reference_date):
        """Calculate weekly CDD by summing daily values.

        Week is defined as Monday to Sunday.
        """
        # Determine the start of the week (Monday)
        weekday = reference_date.weekday()
        week_start = reference_date - timedelta(days=weekday)
        week_end = week_start + timedelta(days=6)

        _LOGGER.debug(
            "Calculating weekly CDD from %s to %s",
            week_start.isoformat(),
            week_end.isoformat(),
        )

        # Check for missing data in the week
        missing_dates = []
        for i in range(7):
            current_date = week_start + timedelta(days=i)
            if (
                current_date <= dt_util.now().date()
                and current_date not in self.daily_cdd_values
            ):
                missing_dates.append(current_date)

        if missing_dates:
            _LOGGER.debug(
                "Missing CDD data for dates in current week: %s",
                ", ".join(date.isoformat() for date in missing_dates),
            )

        # Sum all daily values that fall within this week
        weekly_cdd = 0
        for i in range(7):  # Monday to Sunday
            current_date = week_start + timedelta(days=i)
            weekly_cdd += self.daily_cdd_values.get(current_date, 0)

        return weekly_cdd

    def _calculate_current_month_cdd(self, reference_date):
        """Calculate monthly CDD by summing daily values.

        Month is defined as 1st to last day of the month.
        """
        # First day of current month
        month_start = reference_date.replace(day=1)

        # Last day of current month
        _, last_day = calendar.monthrange(reference_date.year, reference_date.month)
        month_end = reference_date.replace(day=last_day)

        _LOGGER.debug(
            "Calculating monthly CDD from %s to %s",
            month_start.isoformat(),
            month_end.isoformat(),
        )

        # Check for missing data in the month
        missing_dates = []
        current_date = month_start
        while current_date <= min(dt_util.now().date(), month_end):
            if current_date not in self.daily_cdd_values:
                missing_dates.append(current_date)
            current_date += timedelta(days=1)

        if missing_dates:
            _LOGGER.debug(
                "Missing CDD data for dates in current month: %s",
                ", ".join(date.isoformat() for date in missing_dates[:5])
                + (
                    f" and {len(missing_dates) - 5} more"
                    if len(missing_dates) > 5
                    else ""
                ),
            )

        # Sum all daily values that fall within this month
        monthly_cdd = 0
        current_date = month_start

        while current_date <= month_end:
            monthly_cdd += self.daily_cdd_values.get(current_date, 0)
            current_date += timedelta(days=1)

        return monthly_cdd
