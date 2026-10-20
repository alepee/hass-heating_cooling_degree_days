# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-10-20

### Added
- Reconfigure flow: change the temperature source, base temperature and cooling/weekly/monthly options of an existing entry from the integration page, prefilled with the current settings (#126, fixes #125)
- Renaming the temperature sensor is followed: the entry tracks the sensor's registry identity, keeps its stored daily values and entities, and waits for the recorder history migration (#146)
- A per-entry Repairs notice when the source sensor is missing, cleared once it is back or reconfigured; missing days lower coverage instead of counting as zero (#146)
- Diagnostics download with calculation settings, source availability, per-day coverage for the last 35 days and current period snapshots; identifying details are redacted (#143)
- Integration icon and logo, shipped with the integration (`brand/`) and shown by Home Assistant 2026.3 or later (#141)
- Contributor guide (`AGENTS.md`) and quality-scale checklist (#144)

### Fixed
- Weekly and monthly sensors sum completed days of the current calendar period, resetting on Monday and on the 1st. Values and period labels share one snapshot, refreshed shortly after local midnight (#138)
- Missing completed days are backfilled from retained recorder history (up to seven dates per refresh). Coverage, missing-day counts and partial status expose remaining gaps (#138)
- Integrate every recorder interval using the last known temperature, including the start-state and the final interval to midnight. Minute and subminute samples are no longer discarded (#135)
- Convert each recorded temperature from its own unit and preserve invalid/unavailable states as gaps. Recorder failures no longer appear as successful measurements (#135)
- Bridge confirmed invalid temperature spans of up to 15 minutes by holding the preceding valid temperature, including interruptions that cross midnight. Longer or unresolved interruptions stay uncovered (#152)
- Legacy daily values are recalculated once when Recorder provides a complete day; older partial/legacy records are retried once after a calculation revision (#150, #152)
- The missing-source Repairs notice waits for Home Assistant startup and does not treat a registered sensor without a state yet as removed (#149)
- Generated entry titles follow Home Assistant's language (English, French); nearby base temperatures produce distinct titles (#142)
- Daily sensors use the `measurement` state class; weekly/monthly keep `total_increasing` (#154)

### Changed
- Storage migrates to version 2 through a forward-only migration. Create a full Home Assistant backup before upgrading. Returning to an older integration version requires restoring the pre-upgrade stored data as well as the integration; downgrading the code alone is not supported
- Daily storage retains raw integrals, coverage and mean temperature. Legacy scalar values are preserved with assumed complete coverage (`legacy_days`). Source/base/unit changes invalidate this ledger and rebuild only history still available in recorder, without rewriting Home Assistant long-term statistics
- Correcting legacy values can lower a weekly or monthly total once during the current period; Home Assistant's `total_increasing` statistics may interpret that as a reset. Review affected statistics in Developer Tools > Statistics
- Minimum Home Assistant version raised to 2025.1
- Sensor types turned off in the configuration have their entities removed instead of being left behind as unavailable
- Local uv development replaces the obsolete devcontainer (#127); CI verifies actual Python/HA versions; Dependabot uses native uv support (#111, #113, #118, #128, #129, #134); releases use a checked manual process (#136)

## [1.1.0] - 2026-06-09

### Added
- Support for multiple config entries: create several instances with different base temperatures or source sensors
- Optional name field in the config flow, used as entry title and device name
- A device per entry grouping its sensors
- Strict duplicate guard: an entry with the same sensor and base temperature is rejected

### Changed
- Sensor unique_ids now include the config entry id (existing installs are migrated automatically; entity_ids and history are preserved)
- The entry title is no longer overwritten at startup; renaming an entry in the UI now sticks and propagates to the device and sensor names (the entry reloads automatically on rename)
- Existing sensors now group under a device; their friendly names gain the device prefix (e.g. "HDD Daily" → "Heating Degree Days HDD Daily"). Entity IDs and history are unchanged

## [1.0.3] - 2026-02-02

### Fixed
- Fixed issue #76: Negative temperatures (e.g. below 0°C) are now correctly accepted in sensor validation; validation uses float conversion instead of isdigit() so winter temperatures no longer cause failed or skipped updates

## [1.0.2] - 2025-11-05

### Added
- Persistent storage for historical HDD and CDD data (prevents data loss on restarts)
- Field descriptions in configuration UI

### Changed
- Default base temperature: 18°C for Celsius (was 65°C), 65°F for Fahrenheit (unchanged)
- Temperature unit now automatically detected from Home Assistant preferences
- Removed temperature unit field from configuration flow

### Fixed
- Fixed issue #57: Monthly and weekly degree days values no longer reset after Home Assistant restart

## [1.0.1] - 2025-01-27

### Fixed
- Fixed excessive precision in degree days values by rounding to 1 decimal place
- Resolves GitHub issue #13: "round value - 15 numbers after the decimal is useless"

## [1.0.0] - 2025-03-25

### Added
- Added Cooling Degree Days (CDD) calculation
- Added option to enable/disable weekly and monthly sensors
- Added improved debugging logs throughout the integration
- Added validation to ensure only temperature sensors can be selected

### Changed
- Renamed integration from "Heating Degree Days" to "Heating & Cooling Degree Days"
- Improved calculation method for daily values using numerical integration
- Updated title display based on configured options
- Fixed sensor entity_id generation

## [1.0.0-alpha.2] - 2025-02-14

### Changed
- Changed sensor unit to display proper temperature unit per day (°C·d or °F·d)
- Fixed HACS validation issues

## [1.0.0-alpha.1] - 2025-02-14

### Added
- Initial release
- Heating Degree Days (HDD) calculation
- Support for daily, weekly and monthly periods
