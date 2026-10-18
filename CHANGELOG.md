# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0-beta.1] - 2026-10-19

### Fixed
- Weekly and monthly sensors now sum completed days of the current calendar period, resetting on Monday and on the 1st. Values and period labels share one snapshot, refreshed shortly after local midnight.
- Missing completed days are backfilled from retained recorder history (up to seven dates per refresh). Coverage, missing-day counts and partial status expose remaining gaps; finalized days are cached, and partial days are retried every six hours while retained.
- Integrate every recorder interval using the last known temperature, including the start-state and the final interval to midnight. Minute and subminute samples are no longer discarded.
- Convert each recorded temperature from its own unit and preserve invalid/unavailable states as gaps. Recorder failures no longer appear as successful measurements.
- Calculate a time-weighted daily mean and expose daily coverage and partial status. Use elapsed seconds on daylight-saving days and round only when displaying sensor values.
- Reconfiguration preserves the entry's stored temperature unit and custom name, rejects invalid settings, and reloads the entry once. Deleting an entry removes only its own stored values; setup failures can be retried safely.

### Added
- Reconfigure flow: the temperature source, base temperature and cooling/weekly/monthly options of an existing entry can be changed from the integration page, prefilled with the current settings (#126, fixes #125)

### Changed
- Storage migrates to version 2 through a forward-only migration. Create a full Home Assistant backup before upgrading. Returning to an older integration version requires restoring the pre-upgrade stored data as well as the integration; downgrading the code alone is not supported.
- Weekly/monthly sensors use `total_increasing`; daily sensors no longer have a state class. Entity IDs are preserved. Home Assistant may ask you to fix statistics once after the state-class/unit change in Developer Tools > Statistics; existing statistics are not rewritten automatically.
- Daily storage now retains raw integrals, coverage and mean temperature. Legacy scalar values are preserved with assumed complete coverage, identified by `legacy_days`; absent legacy cooling values remain unknown. Source/base/unit changes invalidate this ledger and rebuild only the history still available in recorder, without recalculating existing Home Assistant long-term statistics.
- Minimum Home Assistant version raised to 2025.1, matching the tested support floor
- Sensor types turned off in the configuration now have their entities removed instead of being left behind as unavailable
- Stored daily values carry the settings they were calculated with, and are reset when the temperature source, the base temperature or the unit changes
- Local uv development replaces the obsolete devcontainer (#127); Home Assistant development overrides now survive `make ha-run`
- Ruff updated to 0.16.6 (#128), CI actions updated (#111, #113, #118), and Dependabot uses native uv support with grouped tooling updates (#129)
- CI verifies the actual Python and Home Assistant versions for the minimum, locked and latest-harness environments; pytest dependencies follow the harness, whose updates are managed separately from Dependabot
- Releases use a manual checklist and English notes; version bumps refresh the lockfile, and release assets require matching tag/manifest/project versions and cannot overwrite existing assets

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
