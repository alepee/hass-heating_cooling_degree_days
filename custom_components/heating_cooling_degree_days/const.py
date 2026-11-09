"""Constants for the Heating & Cooling Degree Days integration."""

from datetime import timedelta

from homeassistant.const import UnitOfTemperature

DOMAIN = "heating_cooling_degree_days"

CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_BASE_TEMPERATURE = "base_temperature"
CONF_TEMPERATURE_UNIT = "temperature_unit"
CONF_INCLUDE_COOLING = "include_cooling"
CONF_INCLUDE_WEEKLY = "include_weekly"
CONF_INCLUDE_MONTHLY = "include_monthly"
CONF_WEATHER_ENTITY = "weather_entity"

DEFAULT_BASE_TEMPERATURE_CELSIUS = 18.0
DEFAULT_BASE_TEMPERATURE_FAHRENHEIT = 65.0
MAP_DEFAULT_BASE_TEMPERATURE = {
    UnitOfTemperature.CELSIUS: DEFAULT_BASE_TEMPERATURE_CELSIUS,
    UnitOfTemperature.FAHRENHEIT: DEFAULT_BASE_TEMPERATURE_FAHRENHEIT,
}

DEFAULT_NAME_WITH_HEATING = "Heating Degree Days"
DEFAULT_NAME_WITH_HEATING_AND_COOLING = "Heating & Cooling Degree Days"

DEFAULT_INCLUDE_COOLING = False
DEFAULT_INCLUDE_WEEKLY = True
DEFAULT_INCLUDE_MONTHLY = True
SCAN_INTERVAL = timedelta(minutes=5)

# HDD Sensor types
SENSOR_TYPE_HDD_DAILY = "hdd_daily"
SENSOR_TYPE_HDD_WEEKLY = "hdd_weekly"
SENSOR_TYPE_HDD_MONTHLY = "hdd_monthly"

# For backward compatibility
SENSOR_TYPE_DAILY = SENSOR_TYPE_HDD_DAILY
SENSOR_TYPE_WEEKLY = SENSOR_TYPE_HDD_WEEKLY
SENSOR_TYPE_MONTHLY = SENSOR_TYPE_HDD_MONTHLY

# CDD Sensor types
SENSOR_TYPE_CDD_DAILY = "cdd_daily"
SENSOR_TYPE_CDD_WEEKLY = "cdd_weekly"
SENSOR_TYPE_CDD_MONTHLY = "cdd_monthly"

# Forecast estimate sensor types (only when a weather entity is configured)
SENSOR_TYPE_HDD_ESTIMATED_TODAY = "hdd_estimated_today"
SENSOR_TYPE_HDD_ESTIMATED_TOMORROW = "hdd_estimated_tomorrow"
SENSOR_TYPE_CDD_ESTIMATED_TODAY = "cdd_estimated_today"
SENSOR_TYPE_CDD_ESTIMATED_TOMORROW = "cdd_estimated_tomorrow"
FORECAST_SENSOR_TYPES = frozenset(
    {
        SENSOR_TYPE_HDD_ESTIMATED_TODAY,
        SENSOR_TYPE_HDD_ESTIMATED_TOMORROW,
        SENSOR_TYPE_CDD_ESTIMATED_TODAY,
        SENSOR_TYPE_CDD_ESTIMATED_TOMORROW,
    }
)

# Attributes
ATTR_BASE_TEMPERATURE = "base_temperature"
ATTR_DATE_RANGE = "date_range"
ATTR_MEAN_TEMPERATURE = "mean_temperature"


def get_enabled_sensor_types(
    include_cooling: bool,
    include_weekly: bool,
    include_monthly: bool,
    include_forecast: bool = False,
) -> tuple[str, ...]:
    """Return the sensor types enabled for an entry, in display order."""
    types = [SENSOR_TYPE_HDD_DAILY]
    if include_weekly:
        types.append(SENSOR_TYPE_HDD_WEEKLY)
    if include_monthly:
        types.append(SENSOR_TYPE_HDD_MONTHLY)
    if include_cooling:
        types.append(SENSOR_TYPE_CDD_DAILY)
        if include_weekly:
            types.append(SENSOR_TYPE_CDD_WEEKLY)
        if include_monthly:
            types.append(SENSOR_TYPE_CDD_MONTHLY)
    if include_forecast:
        types += [SENSOR_TYPE_HDD_ESTIMATED_TODAY, SENSOR_TYPE_HDD_ESTIMATED_TOMORROW]
        if include_cooling:
            types += [
                SENSOR_TYPE_CDD_ESTIMATED_TODAY,
                SENSOR_TYPE_CDD_ESTIMATED_TOMORROW,
            ]
    return tuple(types)


HISTORICAL_SENSOR_TYPES = frozenset(get_enabled_sensor_types(True, True, True))
MANAGED_SENSOR_TYPES = HISTORICAL_SENSOR_TYPES | FORECAST_SENSOR_TYPES
