# Multiple Config Entries Support — Design

**Date:** 2026-06-05
**Status:** Approved
**Context:** A user on the HACF forum ([post #21](https://forum.hacf.fr/t/integration-degres-jours-de-chauffage-et-de-refroidissement/59384/21)) wants to create several instances of the integration with different base temperatures, to compare them over time. Home Assistant currently rejects the second entry with `ID heating_cooling_degree_days_hdd_daily is already used`.

## Problem

Three blockers prevent multiple config entries:

1. `sensor.py` — `_attr_unique_id = f"{DOMAIN}_{sensor_type}"` is static: the second entry collides on every sensor.
2. `sensor.py` — `self.entity_id` is explicitly forced to `sensor.{sensor_type}` (e.g. `sensor.hdd_daily`), colliding as well.
3. `__init__.py` — the entry title is forcibly rewritten to a fixed string on every setup, so multiple entries would be indistinguishable and any manual rename is reverted on restart.

Not a blocker: coordinator storage is already keyed by `entry_id` (`coordinator.py`), so per-entry data does not conflict.

## Decisions

- **Naming:** optional `name` field in the config flow, with an auto-derived default such as `Heating Degree Days (18.0°C)` (base temperature + unit). The entry title is set once at creation; users can rename later through the HA UI.
- **Grouping:** one device per config entry. With `_attr_has_entity_name = True` (already in place), sensors group under the device and get names like `<Entry name> HDD daily`.
- **Migration:** automatic. Config flow `VERSION = 2` plus `async_migrate_entry` rewriting registry unique_ids. Existing entity_ids and history are preserved.
- **Approach:** standard HA pattern — drop explicit `entity_id` assignment, let HA generate entity_ids from device name + `translation_key`.

## Design

### 1. Config flow (`config_flow.py`)

- Add an optional `CONF_NAME` field at the top of the user form. The field is left empty in the form (it cannot be pre-filled since it depends on the base temperature entered in the same screen); when left empty, the title is derived at submission from the entered values, e.g. `Heating Degree Days (18.0°C)` / `Heating & Cooling Degree Days (65.0°F)`.
- Call `self._async_abort_entries_match({CONF_TEMPERATURE_SENSOR: ..., CONF_BASE_TEMPERATURE: ...})` to reject a strict duplicate (same source sensor + same base temperature) with reason `already_configured`.
- Entry title = provided name, or the derived default when left empty.
- Bump `VERSION` to 2.
- Add EN/FR translations for the new field and the abort reason.

### 2. Entry title (`__init__.py`)

- Remove the forced title rewrite in `async_setup_entry` (current lines 44-50, `TITLE_STANDARD` / `TITLE_WITH_COOLING` constants included). The title is owned by the config flow at creation time and by the user afterwards.

### 3. Entities and device (`sensor.py`)

- `_attr_unique_id = f"{entry.entry_id}_{sensor_type}"`.
- Remove the explicit `self.entity_id` assignment; HA generates entity_ids from device + `translation_key`.
- Add `_attr_device_info` with:
  - `identifiers={(DOMAIN, entry.entry_id)}`
  - `name` = entry title
  - `entry_type=DeviceEntryType.SERVICE`
- All sensors of an entry (1 to 6 depending on options) group under this device.

### 4. Migration (`__init__.py`)

- `async_migrate_entry(hass, entry)`:
  - For version 1 entries: rewrite entity registry unique_ids via `er.async_migrate_entries`, mapping `heating_cooling_degree_days_{sensor_type}` → `{entry.entry_id}_{sensor_type}`, then bump entry version to 2.
  - Existing entity_ids (`sensor.hdd_daily`, …), customizations, and recorder history are preserved — only the registry unique_id changes.
- Coordinator storage requires no migration (already keyed by `entry_id`).

### 5. Error handling

- Migration is idempotent: unique_ids that do not match the old static format are left untouched.
- `async_migrate_entry` returns `False` only for unknown future versions (> 2).

### 6. Testing

- **Config flow:** creating two entries with different base temperatures succeeds; a strict duplicate (same sensor + same base temperature) aborts with `already_configured`; the custom name is used as entry title; the default title is derived when no name is given.
- **Sensor:** unique_ids are prefixed with `entry_id`; a device is created per entry; two entries set up side by side produce no registry collision.
- **Migration:** a v1 entry with entities registered under old static unique_ids migrates to `{entry_id}_{sensor_type}` with entity_ids unchanged; running migration twice is harmless.

## Out of scope

- Options flow (editing an existing entry's parameters).
- Recalculating past statistics for new base temperatures (impossible in HA, this is precisely why the user wants parallel instances).
- Any change to calculation logic or storage format.
