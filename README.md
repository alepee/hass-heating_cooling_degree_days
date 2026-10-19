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

1. Recorder states are read for completed local calendar days, including the state at each day's start.
2. Each state's temperature is converted from its recorded unit to the configured calculation unit. If its unit is missing, the current source unit (or the calculation unit) is assumed and recorded internally.
3. A temperature holds until the next state or the end of the day. Unknown, unavailable, non-numeric, non-finite, or unsupported-unit states start gaps; gaps are never interpolated through.
4. Heating deficits and cooling excesses are multiplied by their elapsed seconds, summed, and divided by 86,400. No short intervals are dropped.

This method provides more accurate results than simple daily averages, especially when temperature fluctuates significantly throughout the day.

The divisor remains 86,400 on daylight-saving transitions: a constant 8-degree
heating deficit produces 8 × 23/24 degree days on a 23-hour day and 8 × 25/24
on a 25-hour day. The mean temperature is weighted by the duration of valid
states, excluding gaps.

Daily sensors represent yesterday. Weekly and monthly sensors sum only completed
days of the current calendar week (Monday start) or month. They reset to zero on
Monday or the 1st, respectively, and refresh at 00:00:05 local time as well as
every five minutes. Today is never included in a historical total.

All sensors expose `coverage` (covered seconds divided by the expected elapsed
seconds), `partial`, `missing_days`, `days_counted`, `period_start`, `period_end`
and `completed_through`. Period boundaries label the full calendar period;
coverage and totals stop at yesterday. An empty new period has zero value and
coverage 1. A nonempty period with no observed time is unknown. Partial values
include only covered time, without extrapolating across gaps. Recorder query
failures mark sensors unavailable and retain the previous snapshot.

Missing days are backfilled from recorder, at most seven dates per refresh,
prioritizing yesterday and recent unqueried days. Completed days with full
coverage are cached; partial/empty days are retried every six hours while within
recorder retention. Retries that reduce coverage or either cached integral keep
the previous observation to avoid artificial statistics resets. The ledger keeps
60 days. Coverage can remain partial if recorder has purged or never recorded
the source. Legacy daily totals are preserved with coverage assumed complete,
flagged by `legacy_days`; absent legacy cooling values remain unknown.

Renaming a registered temperature sensor automatically updates this integration
and preserves its calculated history. If the source disappears, a Repairs notice
links to the integration: use the entry’s three-dot menu > Reconfigure to select
a replacement. While the source is missing, `source_missing` is true, backfill
is paused, and existing ledger values remain available. Newly missing days have
unknown values and reduce coverage; they are not counted as zero. Restoring the
source clears the notice and resumes backfill. Selecting a different source
starts a new ledger.

Weekly/monthly sensors use `total_increasing`; daily sensors have no state class.
After upgrading, Home Assistant may request a one-time statistics correction in
Developer Tools > Statistics. Existing long-term statistics are not rewritten.

**Note**: Values are kept unrounded for calculations and storage, and displayed
with 1 decimal place (e.g., `12.3°C·d`). Previously stored daily totals are not
retroactively recomputed by this change.

## Installation

### Using HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=alepee&repository=hass-heating_cooling_degree_days)

1. Open HACS
2. Click on "Custom Repositories"
3. Add this repository URL
4. Select "Integration" as the category
5. Click "Install"

### Manual Installation

1. Download the attached `heating_cooling_degree_days.zip` asset from the [releases page](https://github.com/alepee/hass-heating_cooling_degree_days/releases)
2. Create `custom_components/heating_cooling_degree_days/` in your Home Assistant configuration directory if needed
3. Extract the ZIP contents into that directory. The archive is flat: `manifest.json` must end up at `custom_components/heating_cooling_degree_days/manifest.json`
4. Restart Home Assistant

If you download GitHub's source archive instead, copy its
`custom_components/heating_cooling_degree_days/` directory into your configuration.

## Configuration

1. Go to Settings -> Devices & Services
2. Click the "+ ADD INTEGRATION" button
3. Search for "Heating & Cooling Degree Days"
4. Configure:
   - Select your outdoor temperature sensor
   - Set the base temperature (defaults are 18°C or 65°F)
   - Enable/disable Cooling Degree Days calculation
   - Choose whether to include weekly and monthly sensors

### Changing the settings later

1. Go to Settings -> Devices & Services -> Heating & Cooling Degree Days
2. On the entry, open the three-dot menu (⋮) and choose "Reconfigure". There is no "Configure" button: all settings are edited through this menu entry
3. The form is prefilled with the current settings; change what you need

Entity IDs and history are preserved. Turning off the cooling, weekly or monthly
sensors removes the matching entities. Changing the temperature source, the base
temperature or the unit invalidates the stored daily values, so they are reset
instead of being mixed with values calculated under the previous settings, and
the weekly and monthly totals rebuild in bounded batches from history still
available in recorder. Home Assistant's existing long-term statistics are not
recalculated; changing calculation settings starts a new basis for future totals.

## Features

- Calculates daily, weekly, and monthly heating degree days (HDD)
- Optional calculation of cooling degree days (CDD)
- Configurable base temperature, editable after setup through the reconfigure flow
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

- Home Assistant Core: 2025.1 or later
- HACS: 1.32.0 or later (if using HACS installation)

## Contributing

Feel free to submit issues and pull requests for improvements.

Development uses local [uv](https://docs.astral.sh/uv/getting-started/installation/)
and Python 3.13 (see `.python-version`). From the repository root:

```bash
uv python install
make setup
make check && make test
make ha-run
```

Home Assistant uses `http://localhost:8123` by default. Its local configuration
is in `config/`. In VS Code, select `.venv/bin/python` as the interpreter.

`make ha-upgrade`, `make ha-dev-branch` and `make ha-version` first restore the
locked environment, then temporarily replace Home Assistant. `make ha-run`
preserves that override; run `make install` to return to the lockfile. For tests
after a deliberate dependency override, use `uv run --no-sync pytest` because
ordinary `uv run` restores locked dependencies.

CI tests HA 2025.1.0, the locked Python 3.13 environment, and the latest published
`pytest-homeassistant-custom-component` (phac) on Python 3.14. Each row verifies
the installed HA version against its harness; the floor and latest rows also
assert their requested versions. The canary fails if the latest harness needs
a newer Python instead of silently falling back to an older harness.

phac owns the pytest and pytest-asyncio versions. Dependabot updates independent
development tools, but excludes this tightly pinned family and Home Assistant:
forcing one newest harness version across the universal lock can exclude older
Python versions. To refresh the harness deliberately, run
`uv lock --upgrade-package pytest-homeassistant-custom-component`, review the
Python-specific resolutions, and run all CI rows. Keep the explicit HA floor pin
until the minimum supported version is deliberately changed.

Maintainers: follow the [manual release checklist and template](docs/development/release.md).

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a detailed list of changes and version history.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
