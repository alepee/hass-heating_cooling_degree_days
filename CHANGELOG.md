# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
