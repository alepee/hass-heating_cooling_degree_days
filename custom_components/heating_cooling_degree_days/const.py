"""Constants for the Heating & Cooling Degree Days integration."""

from datetime import timedelta

DOMAIN = "heating_cooling_degree_days"

CONF_TEMPERATURE_SENSOR = "temperature_sensor"
CONF_BASE_TEMPERATURE = "base_temperature"
CONF_TEMPERATURE_UNIT = "temperature_unit"
CONF_INCLUDE_COOLING = "include_cooling"
CONF_INCLUDE_WEEKLY = "include_weekly"
CONF_INCLUDE_MONTHLY = "include_monthly"

DEFAULT_BASE_TEMPERATURE_CELSIUS = 18.0
DEFAULT_BASE_TEMPERATURE_FAHRENHEIT = 65.0
DEFAULT_BASE_TEMPERATURE = DEFAULT_BASE_TEMPERATURE_CELSIUS  # For backward compatibility
DEFAULT_NAME = "Heating & Cooling Degree Days"
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

# Attributes
ATTR_BASE_TEMPERATURE = "base_temperature"
ATTR_DATE_RANGE = "date_range"
ATTR_MEAN_TEMPERATURE = "mean_temperature"
