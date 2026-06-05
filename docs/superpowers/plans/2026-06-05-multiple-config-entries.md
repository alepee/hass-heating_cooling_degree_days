# Multiple Config Entries Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to create several config entries of the integration (e.g. different base temperatures on the same outdoor sensor), with automatic migration of existing single-entry installs.

**Architecture:** Standard HA multi-entry pattern — per-entry unique_ids (`{entry_id}_{sensor_type}`), one service device per entry, no explicit `entity_id` assignment, entry title owned by the config flow (optional user-provided name, derived default). Config flow `VERSION = 2` with `async_migrate_entry` rewriting registry unique_ids for v1 entries.

**Tech Stack:** Home Assistant custom integration (Python 3.13), pytest + pytest-homeassistant-custom-component, uv for env management, ruff for lint.

**Spec:** `docs/superpowers/specs/2026-06-05-multiple-config-entries-design.md`

**Project conventions (from project CLAUDE.md):**
- Before modifying any function/class/method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` (MCP tool) and report the blast radius.
- Before each commit, run `gitnexus_detect_changes()` (MCP tool).
- If GitNexus warns the index is stale, run `npx gitnexus analyze` first.

**Known environment quirk:** the installed git pre-commit hook points at `/usr/local/bin/python3` which lacks the `pre_commit` module, so plain `git commit` fails. Task 1 fixes this by reinstalling the hook from the project venv. Until then, use `git commit --no-verify`.

---

### Task 1: Test harness setup

There is currently **no test infrastructure** (`tests/` contains only `__pycache__`). This task creates the pytest harness used by every later task.

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Modify: `setup.cfg` (add `[tool:pytest]` section)
- Modify: `requirements-dev.txt`
- Modify: `.gitignore` only if `.venv` is not already ignored (check first)

- [ ] **Step 1: Create the venv and install dependencies**

```bash
cd /Users/alepee/Documents/Perso/homeassistant/integrations/hass-heating_cooling_degree_days
uv venv .venv --python 3.13
uv pip install --python .venv/bin/python homeassistant colorlog pytest-homeassistant-custom-component pre-commit ruff
```

Expected: installs succeed. `pytest-homeassistant-custom-component` brings pytest, pytest-asyncio and the HA test helpers (`MockConfigEntry`, `hass`, `recorder_mock`, `enable_custom_integrations` fixtures).

- [ ] **Step 2: Fix the broken pre-commit hook**

```bash
.venv/bin/pre-commit install -f
.venv/bin/pre-commit run --all-files
```

Expected: hook reinstalled pointing at the venv python; run passes (or auto-fixes whitespace — re-stage if so).

- [ ] **Step 3: Create test package and conftest**

`tests/__init__.py`:

```python
"""Tests for the Heating & Cooling Degree Days integration."""
```

`tests/conftest.py`:

```python
"""Common fixtures for Heating & Cooling Degree Days tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    yield
```

- [ ] **Step 4: Add pytest configuration to `setup.cfg`**

Append to `setup.cfg`:

```ini
[tool:pytest]
testpaths = tests
asyncio_mode = auto
```

- [ ] **Step 5: Add test dependency to `requirements-dev.txt`**

Append this line to `requirements-dev.txt`:

```
pytest-homeassistant-custom-component
```

- [ ] **Step 6: Verify the harness collects (no tests yet, exit code 5 is expected)**

```bash
.venv/bin/pytest tests/ -v
```

Expected: `no tests ran` / exit code 5 (collection works, zero tests). Any import error means the harness is broken — fix before continuing.

- [ ] **Step 7: Commit**

```bash
git add tests/__init__.py tests/conftest.py setup.cfg requirements-dev.txt
git commit -m "test: add pytest harness with pytest-homeassistant-custom-component"
```

---

### Task 2: Config flow — optional name, duplicate guard, derived title, VERSION 2

**Files:**
- Test: `tests/test_config_flow.py` (create)
- Modify: `custom_components/heating_cooling_degree_days/config_flow.py`
- Modify: `custom_components/heating_cooling_degree_days/translations/en.json`
- Modify: `custom_components/heating_cooling_degree_days/translations/fr.json`

**Note on `CONF_NAME`:** use `homeassistant.const.CONF_NAME` (value `"name"`). The name is consumed as the entry **title** only — it is popped from `user_input` and NOT stored in `entry.data`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config_flow.py`:

```python
"""Tests for the config flow."""

from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    DOMAIN,
)

TEMP_SENSOR = "sensor.outdoor_temperature"

BASE_USER_INPUT = {
    CONF_TEMPERATURE_SENSOR: TEMP_SENSOR,
    CONF_BASE_TEMPERATURE: 18.0,
    CONF_INCLUDE_COOLING: False,
    CONF_INCLUDE_WEEKLY: True,
    CONF_INCLUDE_MONTHLY: True,
}


@pytest.fixture
def temperature_sensor(hass: HomeAssistant) -> None:
    """Register a valid outdoor temperature sensor."""
    hass.states.async_set(
        TEMP_SENSOR,
        "12.5",
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )


async def _start_user_flow(hass: HomeAssistant):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_derived_title(hass: HomeAssistant, temperature_sensor) -> None:
    """No name provided: title is derived from base temperature and unit."""
    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_user_flow(hass)
        assert result["type"] is FlowResultType.FORM

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(BASE_USER_INPUT)
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Heating Degree Days (18.0°C)"
    # The name must not leak into entry data
    assert CONF_NAME not in result["data"]
    assert result["data"][CONF_TEMPERATURE_UNIT] == "°C"


async def test_user_flow_custom_name(hass: HomeAssistant, temperature_sensor) -> None:
    """A provided name becomes the entry title."""
    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Salon", **BASE_USER_INPUT}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Salon"
    assert CONF_NAME not in result["data"]


async def test_user_flow_derived_title_with_cooling(
    hass: HomeAssistant, temperature_sensor
) -> None:
    """Derived title reflects the cooling option."""
    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_USER_INPUT, CONF_INCLUDE_COOLING: True}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Heating & Cooling Degree Days (18.0°C)"


async def test_duplicate_entry_aborts(hass: HomeAssistant, temperature_sensor) -> None:
    """Same sensor + same base temperature aborts with already_configured."""
    MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Existing",
        data={**BASE_USER_INPUT, CONF_TEMPERATURE_UNIT: "°C"},
    ).add_to_hass(hass)

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], dict(BASE_USER_INPUT)
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_second_entry_with_different_base_temperature(
    hass: HomeAssistant, temperature_sensor
) -> None:
    """Same sensor with a different base temperature is allowed."""
    MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Existing",
        data={**BASE_USER_INPUT, CONF_TEMPERATURE_UNIT: "°C"},
    ).add_to_hass(hass)

    with patch(
        "custom_components.heating_cooling_degree_days.async_setup_entry",
        return_value=True,
    ):
        result = await _start_user_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**BASE_USER_INPUT, CONF_BASE_TEMPERATURE: 16.0}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Heating Degree Days (16.0°C)"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_config_flow.py -v
```

Expected: `test_user_flow_derived_title`, `test_user_flow_custom_name`, `test_user_flow_derived_title_with_cooling` FAIL (title is the old fixed string, or `CONF_NAME` unknown in schema → `vol.Invalid`); `test_duplicate_entry_aborts` FAILS (entry created instead of abort). `test_second_entry_with_different_base_temperature` may already pass — fine.

- [ ] **Step 3: Run impact analysis (project convention)**

Run MCP tool `gitnexus_impact({target: "async_step_user", direction: "upstream"})` and `gitnexus_impact({target: "_get_default_name", direction: "upstream"})`. Report blast radius. (`_get_default_name` is only used inside the flow; expected LOW.)

- [ ] **Step 4: Implement the config flow changes**

In `custom_components/heating_cooling_degree_days/config_flow.py`:

Add import:

```python
from homeassistant.const import CONF_NAME
```

Replace the class header and `async_step_user` / `_get_default_name` with:

```python
class HDDConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Heating & Cooling Degree Days."""

    VERSION = 2

    def is_matching(self, other_flow: config_entries.ConfigFlow) -> bool:
        """Return True if other_flow matches this flow."""
        return self.context.get("unique_id") == other_flow.context.get("unique_id")

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Reject a strict duplicate: same source sensor + same base temperature
            self._async_abort_entries_match(
                {
                    CONF_TEMPERATURE_SENSOR: user_input[CONF_TEMPERATURE_SENSOR],
                    CONF_BASE_TEMPERATURE: user_input[CONF_BASE_TEMPERATURE],
                }
            )

            # Validate the temperature sensor
            if not self._validate_sensor(user_input[CONF_TEMPERATURE_SENSOR]):
                errors["base"] = "invalid_temperature_sensor"

            if not errors:
                # Set the temperature unit to the user's preferred unit
                user_input[CONF_TEMPERATURE_UNIT] = (
                    self.hass.config.units.temperature_unit
                )

                include_cooling = user_input.get(
                    CONF_INCLUDE_COOLING, DEFAULT_INCLUDE_COOLING
                )

                # The name is only used as the entry title, not stored in data
                name = user_input.pop(CONF_NAME, "").strip()
                title = name or self._derive_title(
                    include_cooling,
                    user_input[CONF_BASE_TEMPERATURE],
                    user_input[CONF_TEMPERATURE_UNIT],
                )

                _LOGGER.debug("Creating integration with title: %s", title)

                return self.async_create_entry(
                    title=title,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME): selector.TextSelector(),
                    vol.Required(CONF_TEMPERATURE_SENSOR): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["sensor"],
                            device_class=SensorDeviceClass.TEMPERATURE,
                        ),
                    ),
                    vol.Required(
                        CONF_BASE_TEMPERATURE,
                        default=self._get_default_base_temperature(),
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_INCLUDE_COOLING, default=DEFAULT_INCLUDE_COOLING
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_INCLUDE_WEEKLY, default=DEFAULT_INCLUDE_WEEKLY
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_INCLUDE_MONTHLY, default=DEFAULT_INCLUDE_MONTHLY
                    ): selector.BooleanSelector(),
                }
            ),
            errors=errors,
        )

    def _derive_title(
        self, include_cooling: bool, base_temp: float, unit: str
    ) -> str:
        """Derive an entry title from the configuration, e.g. 'Heating Degree Days (18.0°C)'."""
        base_name = (
            DEFAULT_NAME_WITH_HEATING_AND_COOLING
            if include_cooling
            else DEFAULT_NAME_WITH_HEATING
        )
        return f"{base_name} ({base_temp:.1f}{unit})"
```

Keep `_get_default_base_temperature` and `_validate_sensor` unchanged. Delete `_get_default_name` (replaced by `_derive_title`).

- [ ] **Step 5: Update translations**

`translations/en.json` — in `config.step.user.data` add as FIRST key:

```json
"name": "Name"
```

In `config.step.user.data_description` add:

```json
"name": "Optional. Used as the entry title and device name. If left empty, a name is derived from the base temperature, e.g. \"Heating Degree Days (18.0°C)\"."
```

After the `"error"` object, add an `"abort"` object inside `"config"`:

```json
"abort": {
  "already_configured": "An entry with this temperature sensor and base temperature already exists."
}
```

`translations/fr.json` — same structure:

```json
"name": "Nom"
```

```json
"name": "Optionnel. Utilisé comme titre de l'instance et nom de l'appareil. Si vide, un nom est dérivé de la température de base, par ex. « Heating Degree Days (18.0°C) »."
```

```json
"abort": {
  "already_configured": "Une instance avec ce capteur de température et cette température de base existe déjà."
}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_config_flow.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 7: Lint, detect changes, commit**

```bash
.venv/bin/ruff check custom_components tests --fix
```

Run MCP tool `gitnexus_detect_changes()` — expected affected symbols: `HDDConfigFlow`, `async_step_user`, `_derive_title` (added), `_get_default_name` (removed).

```bash
git add custom_components/heating_cooling_degree_days/config_flow.py \
        custom_components/heating_cooling_degree_days/translations/en.json \
        custom_components/heating_cooling_degree_days/translations/fr.json \
        tests/test_config_flow.py
git commit -m "feat: allow multiple config entries with optional name and duplicate guard"
```

---

### Task 3: Sensors — per-entry unique_ids, device per entry, no explicit entity_id

**Files:**
- Test: `tests/test_sensor.py` (create)
- Modify: `custom_components/heating_cooling_degree_days/sensor.py`

**Note:** full-setup tests need the `recorder_mock` fixture (the integration declares a `recorder` dependency and queries history). With empty recorder history the coordinator returns 0 values — fine for these tests. `recorder_mock` MUST be listed before `hass` in test signatures.

- [ ] **Step 1: Write the failing tests**

`tests/test_sensor.py`:

```python
"""Tests for the sensor platform with multiple config entries."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    DOMAIN,
)

TEMP_SENSOR = "sensor.outdoor_temperature"


def _make_entry(base_temp: float, title: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title=title,
        data={
            CONF_TEMPERATURE_SENSOR: TEMP_SENSOR,
            CONF_BASE_TEMPERATURE: base_temp,
            CONF_TEMPERATURE_UNIT: "°C",
            CONF_INCLUDE_COOLING: False,
            CONF_INCLUDE_WEEKLY: True,
            CONF_INCLUDE_MONTHLY: True,
        },
    )


async def _setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_unique_ids_are_prefixed_with_entry_id(
    recorder_mock, hass: HomeAssistant
) -> None:
    """Sensor unique_ids must include the config entry id."""
    entry = _make_entry(18.0, "Degree Days Test")
    await _setup_entry(hass, entry)

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert {e.unique_id for e in entries} == {
        f"{entry.entry_id}_hdd_daily",
        f"{entry.entry_id}_hdd_weekly",
        f"{entry.entry_id}_hdd_monthly",
    }


async def test_device_created_per_entry(recorder_mock, hass: HomeAssistant) -> None:
    """Each entry gets a service device named after the entry title."""
    entry = _make_entry(18.0, "Degree Days Test")
    await _setup_entry(hass, entry)

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )
    assert device is not None
    assert device.name == "Degree Days Test"
    assert device.entry_type is dr.DeviceEntryType.SERVICE


async def test_two_entries_coexist(recorder_mock, hass: HomeAssistant) -> None:
    """Two entries with different base temperatures set up without collision."""
    entry_18 = _make_entry(18.0, "Base 18")
    entry_16 = _make_entry(16.0, "Base 16")
    await _setup_entry(hass, entry_18)
    await _setup_entry(hass, entry_16)

    assert entry_18.state.value == "loaded"
    assert entry_16.state.value == "loaded"

    entity_registry = er.async_get(hass)
    assert len(er.async_entries_for_config_entry(entity_registry, entry_18.entry_id)) == 3
    assert len(er.async_entries_for_config_entry(entity_registry, entry_16.entry_id)) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_sensor.py -v
```

Expected: `test_unique_ids_are_prefixed_with_entry_id` FAILS (unique_ids are `heating_cooling_degree_days_*`), `test_device_created_per_entry` FAILS (no device), `test_two_entries_coexist` FAILS (registry collision: second entry's entities not created or `already used` errors).

- [ ] **Step 3: Run impact analysis (project convention)**

Run MCP tool `gitnexus_impact({target: "DegreeDegreeSensor", direction: "upstream"})` and report blast radius (expected: only `async_setup_entry` in sensor.py).

- [ ] **Step 4: Implement the sensor changes**

In `custom_components/heating_cooling_degree_days/sensor.py`:

Add import:

```python
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
```

In `async_setup_entry`, pass the entry to every sensor — replace each `DegreeDegreeSensor(coordinator, SENSOR_TYPE_X)` with `DegreeDegreeSensor(coordinator, entry, SENSOR_TYPE_X)` (6 call sites).

Replace `DegreeDegreeSensor.__init__` with:

```python
    def __init__(
        self,
        coordinator: HDDDataUpdateCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.sensor_type = sensor_type
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_translation_key = sensor_type

        # Group all sensors of this entry under one service device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
        )

        # Set the unit of measurement based on temperature unit
        self._attr_native_unit_of_measurement = f"{coordinator.temperature_unit}·d"

        _LOGGER.debug(
            "Initialized degree days sensor %s with unit %s",
            self._attr_unique_id,
            self._attr_native_unit_of_measurement,
        )
```

This removes: the explicit `self.entity_id = f"sensor.{sensor_type}"` assignments and the `sensor_type_desc` branching (HA now generates entity_ids from device name + translation key).

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_sensor.py tests/test_config_flow.py -v
```

Expected: all PASS.

- [ ] **Step 6: Lint, detect changes, commit**

```bash
.venv/bin/ruff check custom_components tests --fix
```

Run MCP tool `gitnexus_detect_changes()` — expected affected symbols: `DegreeDegreeSensor.__init__`, `async_setup_entry` (sensor.py).

```bash
git add custom_components/heating_cooling_degree_days/sensor.py tests/test_sensor.py
git commit -m "feat: per-entry unique_ids and service device for sensors"
```

---

### Task 4: Stop rewriting the entry title on setup

**Files:**
- Test: `tests/test_init.py` (create)
- Modify: `custom_components/heating_cooling_degree_days/__init__.py`

- [ ] **Step 1: Write the failing test**

`tests/test_init.py`:

```python
"""Tests for integration setup and migration."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.heating_cooling_degree_days.const import (
    CONF_BASE_TEMPERATURE,
    CONF_INCLUDE_COOLING,
    CONF_INCLUDE_MONTHLY,
    CONF_INCLUDE_WEEKLY,
    CONF_TEMPERATURE_SENSOR,
    CONF_TEMPERATURE_UNIT,
    DOMAIN,
)

TEMP_SENSOR = "sensor.outdoor_temperature"

ENTRY_DATA = {
    CONF_TEMPERATURE_SENSOR: TEMP_SENSOR,
    CONF_BASE_TEMPERATURE: 18.0,
    CONF_TEMPERATURE_UNIT: "°C",
    CONF_INCLUDE_COOLING: False,
    CONF_INCLUDE_WEEKLY: True,
    CONF_INCLUDE_MONTHLY: True,
}


async def test_title_is_not_overwritten_on_setup(
    recorder_mock, hass: HomeAssistant
) -> None:
    """A custom entry title must survive setup (no forced rewrite)."""
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, title="My Custom Name", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.title == "My Custom Name"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_init.py -v
```

Expected: FAIL — title rewritten to `Heating Degree Days` by `async_setup_entry`.

- [ ] **Step 3: Run impact analysis (project convention)**

Run MCP tool `gitnexus_impact({target: "async_setup_entry", direction: "upstream"})` (the `__init__.py` one) and report blast radius.

- [ ] **Step 4: Remove the title rewrite**

In `custom_components/heating_cooling_degree_days/__init__.py`, delete:

- The two constants:

```python
# Simple fixed titles in English
TITLE_STANDARD = "Heating Degree Days"
TITLE_WITH_COOLING = "Heating & Cooling Degree Days"
```

- This block inside `async_setup_entry`:

```python
    # Use simple fixed titles based on configuration
    title = TITLE_WITH_COOLING if include_cooling else TITLE_STANDARD

    # Update the entry title if needed
    if entry.title != title:
        _LOGGER.debug("Updating integration title to: %s", title)
        hass.config_entries.async_update_entry(entry, title=title)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 6: Lint, detect changes, commit**

```bash
.venv/bin/ruff check custom_components tests --fix
```

Run MCP tool `gitnexus_detect_changes()` — expected affected symbol: `async_setup_entry` (`__init__.py`).

```bash
git add custom_components/heating_cooling_degree_days/__init__.py tests/test_init.py
git commit -m "fix: stop overwriting the config entry title on every setup"
```

---

### Task 5: Migration of v1 entries (registry unique_ids)

**Files:**
- Test: `tests/test_init.py` (extend)
- Modify: `custom_components/heating_cooling_degree_days/__init__.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_init.py`:

```python
async def test_migrate_v1_entry_rewrites_unique_ids(
    recorder_mock, hass: HomeAssistant
) -> None:
    """V1 entries migrate registry unique_ids; entity_ids are preserved."""
    from homeassistant.helpers import entity_registry as er

    entry = MockConfigEntry(
        domain=DOMAIN, version=1, title="Heating Degree Days", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)

    # Simulate pre-existing v1 entities with old static unique_ids
    entity_registry = er.async_get(hass)
    old_entity = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DOMAIN}_hdd_daily",
        suggested_object_id="hdd_daily",
        config_entry=entry,
    )
    assert old_entity.entity_id == "sensor.hdd_daily"

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    migrated = entity_registry.async_get("sensor.hdd_daily")
    assert migrated is not None
    # entity_id preserved, unique_id rewritten
    assert migrated.unique_id == f"{entry.entry_id}_hdd_daily"


async def test_migrate_future_version_fails(
    recorder_mock, hass: HomeAssistant
) -> None:
    """Entries from a future major version must not be migrated."""
    entry = MockConfigEntry(domain=DOMAIN, version=3, title="X", data=ENTRY_DATA)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state.value == "migration_error"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_init.py -v
```

Expected: `test_migrate_v1_entry_rewrites_unique_ids` FAILS — without `async_migrate_entry`, HA refuses to set up an entry whose version (1) differs from the flow version (2). `test_migrate_future_version_fails` may already pass.

- [ ] **Step 3: Implement `async_migrate_entry`**

In `custom_components/heating_cooling_degree_days/__init__.py`, add imports:

```python
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
```

(`HomeAssistant` is already imported — merge into the existing import line.)

Add this function before `async_setup_entry`:

```python
async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries to the current version."""
    if entry.version > 2:
        # Downgrade from a future version: not supported
        return False

    if entry.version == 1:
        _LOGGER.info("Migrating config entry %s from version 1 to 2", entry.entry_id)

        old_prefix = f"{DOMAIN}_"

        @callback
        def _migrate_unique_id(entity_entry: er.RegistryEntry) -> dict | None:
            """Rewrite static v1 unique_ids to per-entry unique_ids."""
            if entity_entry.unique_id.startswith(old_prefix):
                sensor_type = entity_entry.unique_id.removeprefix(old_prefix)
                return {"new_unique_id": f"{entry.entry_id}_{sensor_type}"}
            # Already migrated or unknown format: leave untouched
            return None

        await er.async_migrate_entries(hass, entry.entry_id, _migrate_unique_id)
        hass.config_entries.async_update_entry(entry, version=2)

    return True
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/ -v
```

Expected: all PASS (full suite).

- [ ] **Step 5: Lint, detect changes, commit**

```bash
.venv/bin/ruff check custom_components tests --fix
```

Run MCP tool `gitnexus_detect_changes()` — expected affected symbols: `async_migrate_entry` (added).

```bash
git add custom_components/heating_cooling_degree_days/__init__.py tests/test_init.py
git commit -m "feat: migrate v1 entries to per-entry unique_ids"
```

---

### Task 6: Changelog, full verification

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add changelog entry**

In `CHANGELOG.md`, insert right after the intro paragraph (before `## [1.0.3]`):

```markdown
## [Unreleased]

### Added
- Support for multiple config entries: create several instances with different base temperatures or source sensors (#<issue/PR number if known, else omit>)
- Optional name field in the config flow, used as entry title and device name
- A device per entry grouping its sensors
- Strict duplicate guard: an entry with the same sensor and base temperature is rejected

### Changed
- Sensor unique_ids now include the config entry id (existing installs are migrated automatically; entity_ids and history are preserved)
- The entry title is no longer overwritten at startup; renaming an entry in the UI now sticks
```

(Drop the `(#...)` reference if there is no issue number.)

- [ ] **Step 2: Full verification**

```bash
.venv/bin/pytest tests/ -v
.venv/bin/ruff check custom_components tests
.venv/bin/pre-commit run --all-files
```

Expected: all tests PASS, ruff clean, pre-commit clean.

- [ ] **Step 3: Detect changes and commit**

Run MCP tool `gitnexus_detect_changes()` — expected: docs-only change for this commit.

```bash
git add CHANGELOG.md
git commit -m "docs: changelog entry for multiple config entries support"
```

- [ ] **Step 4: Wrap up**

Use the superpowers:finishing-a-development-branch skill to decide merge/PR. Note for the release: this is a feature release (1.1.0 candidate, not a patch bump — `make bump` does patch only, so bump minor manually or with `bump2version minor`).

---

## Self-review notes

- Spec coverage: §1 config flow → Task 2; §2 title → Task 4; §3 entities/device → Task 3; §4 migration → Task 5; §5 error handling → Task 5 (idempotence + future version); §6 testing → Tasks 2-5; harness prerequisite → Task 1; changelog → Task 6.
- Out of scope respected: no options flow, no calculation/storage changes.
- Type consistency: `DegreeDegreeSensor(coordinator, entry, sensor_type)` signature matches all 6 call sites; `_derive_title` defined and used only in Task 2; `ENTRY_DATA`/`TEMP_SENSOR` test constants defined in each test file that uses them.
