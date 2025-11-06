# Heating & Cooling Degree Days Integration for Home Assistant

This custom integration calculates Heating Degree Days (HDD) and Cooling Degree Days (CDD) based on outdoor temperature measurements. Degree days are measurements designed to quantify the demand for energy needed to heat or cool a building.

## What are Degree Days?

### Heating Degree Days (HDD)

Heating degree days are a measure of how much (in degrees) and for how long (in days) the outside air temperature was below a certain base temperature. They are commonly used in calculations relating to the energy consumption required to heat buildings.

For example, if you set a base temperature of 19°C (66.2°F):
- If the average temperature for a day is 14°C, that day has 5 heating degree days
- If the average temperature is above the base temperature, that day has 0 heating degree days

### Cooling Degree Days (CDD)

Cooling degree days are the opposite of heating degree days - they measure how much and for how long the outside air temperature was above a certain base temperature. They are used to estimate energy consumption for cooling buildings.

For example, if you set a base temperature of 21°C (69.8°F):
- If the average temperature for a day is 26°C, that day has 5 cooling degree days
- If the average temperature is below the base temperature, that day has 0 cooling degree days

## Calculation Method

This integration uses a numerical integration method for calculating degree days:

1. Detailed temperature readings are collected throughout the day
2. For each time interval, the duration and temperature difference from the base temperature are calculated
3. The temperature difference is weighted by the duration
4. All intervals are summed to get the total degree days

This method provides more accurate results than simple daily averages, especially when temperature fluctuates significantly throughout the day.

**Note**: All degree days values are rounded to 1 decimal place (e.g., `12.3°C·d`) for optimal readability and practical use.

## Installation

### Using HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alepee&repository=hass-heating_cooling_degree_days)

1. Open HACS
2. Click on "Custom Repositories"
3. Add this repository URL
4. Select "Integration" as the category
5. Click "Install"

### Manual Installation

1. Download the latest release from the [releases page](https://github.com/alepee/hass-heating_cooling_degree_days/releases)
2. Extract the `heating_cooling_degree_days` folder from the `custom_components` directory in the downloaded archive
3. Copy the `heating_cooling_degree_days` folder to your Home Assistant's `custom_components` directory
   - If the `custom_components` directory doesn't exist, create it in your Home Assistant config directory
4. Restart Home Assistant

## Configuration

1. Go to Settings -> Devices & Services
2. Click the "+ ADD INTEGRATION" button
3. Search for "Heating & Cooling Degree Days"
4. Configure:
   - Select your outdoor temperature sensor
   - Set the base temperature (defaults are 18°C or 65°F)
   - Enable/disable Cooling Degree Days calculation
   - Choose whether to include weekly and monthly sensors

## Features

- Calculates daily, weekly, and monthly heating degree days (HDD)
- Optional calculation of cooling degree days (CDD)
- Configurable base temperature
- Support for both Celsius and Fahrenheit with appropriate units (°C·d or °F·d)
- Uses full temperature history with numerical integration for accurate calculations
- Values displayed with 1 decimal place precision for optimal readability
- Flexibility to enable only the sensors you need (daily, weekly, monthly)
- Provides additional attributes:
  - Base temperature
  - Date range for the calculation
  - Mean temperature for the period (for daily sensors)

## Sensors Created

The integration creates the following sensors depending on your configuration:

### Heating Degree Days sensors (always included):
- `sensor.hdd_daily`: HDD for the previous day
- `sensor.hdd_weekly`: HDD for the current week (optional)
- `sensor.hdd_monthly`: HDD for the current month (optional)

### Cooling Degree Days sensors (when cooling is enabled):
- `sensor.cdd_daily`: CDD for the previous day
- `sensor.cdd_weekly`: CDD for the current week (optional)
- `sensor.cdd_monthly`: CDD for the current month (optional)

## Time Periods

- **Daily**: Represents the previous completed day
- **Weekly**: Represents the current week from Monday to Sunday
- **Monthly**: Represents the current month from 1st to last day

## Example Usage

Degree days can be used to:
- Monitor heating and cooling energy requirements
- Compare energy usage between different periods
- Normalize energy consumption data
- Predict energy costs
- Calculate climate statistics
- Evaluate building energy efficiency

## Requirements

- Home Assistant Core: 2024.1.0 or later
- HACS: 1.32.0 or later (if using HACS installation)

## Contributing

Feel free to submit issues and pull requests for improvements.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a detailed list of changes and version history.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
