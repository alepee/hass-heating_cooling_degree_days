# uv Dev-Stack Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge `hass-heating_cooling_degree_days` onto the reference Home Assistant custom-integration dev stack (uv + single `pyproject.toml` + ruff + pre-commit + phac + matrix CI), using `hass-hitachi_yutaki` as the template.

**Architecture:** Replace the pip/`requirements*.txt` + `setup.cfg` + `.ruff.toml` + `.pylintrc` + flake8-CI base with a uv-managed project whose single source of config is `pyproject.toml`. The integration code is **not** touched except for one test-infra correctness fix (the `recorder` fixture, which the manifest already declares as a dependency). Each phase ends green on `make check && make test`.

**Tech Stack:** uv, ruff (lint+format), pre-commit, pytest + pytest-homeassistant-custom-component (phac), GitHub Actions, HACS + hassfest.

**Frozen decisions (revisable, surface to maintainer if contested):**
- **Python floor: 3.13.** HA 2025.x already requires Python 3.13, and `hacs.json` declares `homeassistant: 2025.1.0`. Aligns with the hitachi template. `ruff target-version` moves `py312 → py313`.
- **CI test matrix:** oldest supported `HA 2025.1.0` (phac `0.13.201`, py3.13) + `latest` (py3.13) + `latest` (py3.14), `fail-fast: false`.
- **`scripts/setup` drops the system-library install** (`libpcap-dev`, `libturbojpeg0`, `ffmpeg`): this integration is `iot_class: calculated`, pure Python, no native deps. Those libs were copied from hitachi (which talks Modbus/needs them) and are dead weight here.
- **Devcontainer fate is out of scope** for this plan — file a separate cleanup issue like hitachi #342. This plan *does* clean the dead `.gitignore` "Links" section + stray `todo` and tracks `.python-version`, because those are part of stack convergence.
- **Runtime deps stay empty** (`manifest.json requirements: []` → `[project].dependencies = []`). `colorlog` is dev-only (HA debug logging) and goes in the dev group.

---

## File Structure

| Path | Action | Responsibility |
|------|--------|----------------|
| `pyproject.toml` | Create | Single config source: project meta, dev deps, ruff, pytest |
| `.python-version` | Create | Pin Python 3.13 (uv) |
| `uv.lock` | Regenerate | Real lockfile (currently a stub) |
| `.ruff.toml` | Delete | Folded into `[tool.ruff]` |
| `setup.cfg` | Delete | bumpversion/flake8/isort/pytest config obsoleted |
| `.pylintrc` | Delete | pylint dropped (ruff covers it) |
| `requirements.txt`, `requirements-dev.txt`, `requirements-devcontainer.txt` | Delete | Replaced by uv groups |
| `Makefile` | Replace | Self-documented uv façade |
| `scripts/setup`, `scripts/develop`, `scripts/lint`, `scripts/dev-branch`, `scripts/specific-version`, `scripts/upgrade` | Modify | Switch to `uv run` / `uv sync`; drop system libs |
| `scripts/bump_version.py` | Create | SemVer + beta channel; syncs manifest + pyproject |
| `scripts/check_translations.py` | Create | All locales match `en.json`; wired into CI |
| `.pre-commit-config.yaml` | Modify | Bump ruff rev to match pinned ruff |
| `tests/conftest.py` | Modify | Add `recorder_mock` + `mock_recorder_before_hass` |
| `tests/test_calculations.py` | Create | Fast pure-function tests for HDD/CDD integration math |
| `.github/workflows/lint.yml` | Replace | flake8 → uv + ruff + check_translations |
| `.github/workflows/tests.yml` | Create | Matrix pytest (HA × Python) |
| `.github/workflows/validate.yml` | Keep | HACS + hassfest (already correct) |
| `.github/workflows/release.yml`, `release-drafter.yml` | Keep | Already correct |
| `.gitignore` | Modify | Remove dead "Links" section + `todo`; stop ignoring `.python-version` |
| `src/degree_days/` | Delete | Dead directory (only stale `.pyc`) |
| `links.sh` | Delete | Vestige (symlinks superseded by `PYTHONPATH` in `scripts/develop`) |

---

## Task 1: pyproject.toml + uv lockfile (the keystone)

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Delete: `.ruff.toml`, `setup.cfg`, `.pylintrc`, `requirements.txt`, `requirements-dev.txt`, `requirements-devcontainer.txt`
- Regenerate: `uv.lock`

- [ ] **Step 1: Create `.python-version`**

```
3.13
```

- [ ] **Step 2: Create `pyproject.toml`**

The `[tool.ruff.lint]` `select` and `ignore` arrays are **identical** to the current `.ruff.toml` (reproduce them verbatim — they are not changing). The only ruff deltas are: `target-version` `py312 → py313`, the section-header prefixing (`lint.* → [tool.ruff.lint.*]`), and a new `per-file-ignores` for `scripts/*`. Pytest config is migrated from `setup.cfg`'s `[tool:pytest]` plus `pythonpath`.

```toml
[project]
name = "hass-heating-cooling-degree-days"
version = "1.1.0"
requires-python = ">=3.13"
description = "Home Assistant custom integration computing heating and cooling degree days"
license = "MIT"
dependencies = []

[dependency-groups]
dev = [
    "pytest-homeassistant-custom-component",
    "pytest",
    "pytest-asyncio",
    "ruff==0.15.14",
    "pre-commit>=4.6.0",
    "colorlog>=6.9.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
python_files = "test_*.py"
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
norecursedirs = ["scripts", ".git", ".venv", "venv", "build", "dist"]

# The contents of [tool.ruff] is based on https://github.com/home-assistant/core/blob/dev/pyproject.toml

[tool.ruff]
target-version = "py313"

[tool.ruff.lint]
select = [
    # === COPY VERBATIM from the current .ruff.toml `lint.select` array ===
    # (B002, B005, ... W) — unchanged, every entry preserved
]
ignore = [
    # === COPY VERBATIM from the current .ruff.toml `lint.ignore` array ===
    # (D202, D203, ... ISC001, PLE0605, PT007..PT019) — unchanged, every entry preserved
]

[tool.ruff.lint.flake8-import-conventions.extend-aliases]
voluptuous = "vol"
"homeassistant.helpers.area_registry" = "ar"
"homeassistant.helpers.category_registry" = "cr"
"homeassistant.helpers.config_validation" = "cv"
"homeassistant.helpers.device_registry" = "dr"
"homeassistant.helpers.entity_registry" = "er"
"homeassistant.helpers.floor_registry" = "fr"
"homeassistant.helpers.issue_registry" = "ir"
"homeassistant.helpers.label_registry" = "lr"
"homeassistant.util.dt" = "dt_util"

[tool.ruff.lint.isort]
force-sort-within-sections = true
known-first-party = ["homeassistant"]
combine-as-imports = true

[tool.ruff.lint.flake8-pytest-style]
fixture-parentheses = false

[tool.ruff.lint.mccabe]
max-complexity = 25

# Allow print and missing main docstring in CLI dev scripts
[tool.ruff.lint.per-file-ignores]
"scripts/*" = ["D103", "T201"]
```

> **Implementation note for the worker:** open `.ruff.toml`, copy the full `lint.select = [...]` and `lint.ignore = [...]` blocks, and paste their contents (the array entries, including comments) into the two placeholders above. Do not edit any entry. Then verify with the ruff run in Step 5 — if a rule code was dropped, ruff's behavior changes and the diff in Step 6 will reveal it.

- [ ] **Step 3: Delete the obsolete config + requirements files**

```bash
git rm .ruff.toml setup.cfg .pylintrc requirements.txt requirements-dev.txt requirements-devcontainer.txt
```

- [ ] **Step 4: Generate the real lockfile and sync**

Run:
```bash
uv lock
uv sync --group dev
```
Expected: `uv.lock` grows from the 4-line stub to a full resolution including `homeassistant`, `pytest-homeassistant-custom-component`, `ruff`, etc. `uv sync` reports the venv populated.

- [ ] **Step 5: Verify ruff reads the new config**

Run:
```bash
uv run ruff check custom_components tests
```
Expected: ruff runs and reports findings (or clean) **using `[tool.ruff]`** — no "no configuration found" message, no reference to `.ruff.toml`.

- [ ] **Step 6: Verify no lint behavior drift**

Run:
```bash
uv run ruff format --check custom_components tests
uv run ruff check custom_components tests --statistics
```
Expected: the statistics list only rule codes that exist in the migrated `select`. If a previously-ignored rule now fires, a `select`/`ignore` entry was lost in Step 2 — fix it before committing.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .python-version uv.lock
git commit -m "build: migrate to uv + single pyproject.toml config"
```

---

## Task 2: Makefile (self-documented uv façade)

**Files:**
- Replace: `Makefile`

- [ ] **Step 1: Overwrite `Makefile`**

```makefile
.DEFAULT_GOAL := help

MANIFEST := custom_components/heating_cooling_degree_days/manifest.json
VERSION  := $(shell python3 -c "import json;print(json.load(open('$(MANIFEST)'))['version'])")

# —— Setup ——————————————————————————————————————————————

.PHONY: install
install: ## Install all dependencies (dev included)
	uv sync --group dev

.PHONY: setup
setup: ## Full project setup (deps + pre-commit hooks)
	./scripts/setup

.PHONY: upgrade-deps
upgrade-deps: ## Upgrade all deps (HA version follows pytest-homeassistant-custom-component)
	uv lock --upgrade
	uv sync --group dev

# —— Quality ————————————————————————————————————————————

.PHONY: lint
lint: ## Run ruff linter with auto-fix
	uv run ruff check custom_components tests --fix

.PHONY: format
format: ## Run ruff formatter
	uv run ruff format custom_components tests

.PHONY: check
check: lint format ## Run all code quality checks (lint + format)

.PHONY: pre-commit
pre-commit: ## Run all pre-commit hooks on the entire codebase
	uv run pre-commit run --all-files

# —— Testing ————————————————————————————————————————————

.PHONY: test
test: ## Run all tests
	uv run pytest

.PHONY: test-fast
test-fast: ## Run pure calculation tests only (no hass fixture)
	uv run pytest tests/test_calculations.py

.PHONY: test-verbose
test-verbose: ## Run all tests with verbose output
	uv run pytest -v

.PHONY: test-coverage
test-coverage: ## Run tests with coverage report
	uv run pytest --cov=custom_components/heating_cooling_degree_days --cov-report=term-missing

# —— Home Assistant ————————————————————————————————————

.PHONY: ha-run
ha-run: ## Start a local HA dev instance with debug config
	./scripts/develop

.PHONY: ha-upgrade
ha-upgrade: ## Temporary HA upgrade (reset by make install)
	./scripts/upgrade

.PHONY: ha-dev-branch
ha-dev-branch: ## Temporary HA dev branch (reset by make install)
	./scripts/dev-branch

.PHONY: ha-version
ha-version: ## Temporary HA specific version (reset by make install)
	./scripts/specific-version

# —— Release ———————————————————————————————————————————

.PHONY: bump
bump: ## Bump version — usage: make bump [PART=patch|minor|major|beta] (default: patch)
	@python3 scripts/bump_version.py $(PART)

.PHONY: version
version: ## Show current version
	@echo $(VERSION)

# —— Help ——————————————————————————————————————————————

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'
```

- [ ] **Step 2: Verify help + version**

Run:
```bash
make help
make version
```
Expected: `make help` prints the colorized target list; `make version` prints `1.1.0`.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "build: self-documented uv Makefile façade"
```

---

## Task 3: scripts/ — switch wrappers to uv, drop dead system libs

**Files:**
- Modify: `scripts/setup`, `scripts/develop`, `scripts/lint`, `scripts/upgrade`, `scripts/dev-branch`, `scripts/specific-version`

- [ ] **Step 1: Overwrite `scripts/setup`** (drop libpcap/ffmpeg, use uv)

```bash
#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

uv sync --group dev
uv run pre-commit install
```

- [ ] **Step 2: Overwrite `scripts/develop`** (run hass via uv; logger block already targets the right domain)

```bash
#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

# Create config dir if not present
if [[ ! -d "${PWD}/config" ]]; then
    mkdir -p "${PWD}/config"
    uv run hass --config "${PWD}/config" --script ensure_config
fi
if ! grep -R "^logger:" config/configuration.yaml >> /dev/null;then
echo -n "
logger:
  default: info
  logs:
    custom_components.heating_cooling_degree_days: debug
" >> config/configuration.yaml
fi
if ! grep -R "debugpy:" config/configuration.yaml >> /dev/null;then
echo "
# Uncomment the line below if you want to use debugger
# debugpy:
" >> config/configuration.yaml
fi

# Set the path to custom_components without resorting to symlinks.
export PYTHONPATH="${PYTHONPATH}:${PWD}/custom_components"

# Start Home Assistant
uv run hass --config "${PWD}/config" --debug
```

- [ ] **Step 3: Overwrite `scripts/lint`**

```bash
#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

uv run ruff check . --fix
```

- [ ] **Step 4: Overwrite `scripts/upgrade`**

```bash
#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

echo "⚠ Temporary override — 'make install' will restore the lockfile version."
uv pip install --upgrade --pre homeassistant
```

- [ ] **Step 5: Overwrite `scripts/dev-branch`**

```bash
#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

echo "⚠ Temporary override — 'make install' will restore the lockfile version."
uv pip install --upgrade git+https://github.com/home-assistant/home-assistant.git@dev
```

- [ ] **Step 6: Overwrite `scripts/specific-version`**

```bash
#!/usr/bin/env bash

set -e

cd "$(dirname "$0")/.."

echo "⚠ Temporary override — 'make install' will restore the lockfile version."
read -p 'Set Home Assistant version: ' -r version
uv pip install --upgrade homeassistant=="$version"
```

- [ ] **Step 7: Verify executable bits and a dry sync**

Run:
```bash
chmod +x scripts/setup scripts/develop scripts/lint scripts/upgrade scripts/dev-branch scripts/specific-version
./scripts/setup
```
Expected: `uv sync` completes, `pre-commit install` writes `.git/hooks/pre-commit`.

- [ ] **Step 8: Commit**

```bash
git add scripts/setup scripts/develop scripts/lint scripts/upgrade scripts/dev-branch scripts/specific-version
git commit -m "build: switch dev scripts to uv, drop unused system libs"
```

---

## Task 4: scripts/bump_version.py (replace bump2version)

**Files:**
- Create: `scripts/bump_version.py`

- [ ] **Step 1: Create `scripts/bump_version.py`**

```python
#!/usr/bin/env python3
"""Bump the integration version in manifest.json and pyproject.toml.

Usage: python scripts/bump_version.py [patch|minor|major|beta]

- patch (default): 1.1.0 → 1.1.1, or 1.1.0-beta.4 → 1.1.0 (promotes to release)
- minor: 1.1.0 → 1.2.0
- major: 1.1.0 → 2.0.0
- beta: 1.1.0 → 1.1.0-beta.1, or 1.1.0-beta.4 → 1.1.0-beta.5
"""

import json
import re
import sys

MANIFEST = "custom_components/heating_cooling_degree_days/manifest.json"
PYPROJECT = "pyproject.toml"

part = sys.argv[1] if len(sys.argv) > 1 else "patch"
if part not in ("patch", "minor", "major", "beta"):
    print(f'Error: invalid part "{part}" — use patch, minor, major, or beta')
    sys.exit(1)

with open(MANIFEST) as f:
    manifest = json.load(f)

old = manifest["version"]
match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$", old)
if not match:
    print(f'Error: cannot parse version "{old}"')
    sys.exit(1)

major, minor, patch_v = int(match[1]), int(match[2]), int(match[3])
beta = int(match[4]) if match[4] else None

if part == "beta":
    beta = (beta or 0) + 1
    new = f"{major}.{minor}.{patch_v}-beta.{beta}"
elif part == "major":
    new = f"{major + 1}.0.0"
elif part == "minor":
    new = f"{major}.{minor + 1}.0"
# patch: promote beta to release, or increment patch
elif beta is not None:
    new = f"{major}.{minor}.{patch_v}"
else:
    new = f"{major}.{minor}.{patch_v + 1}"

# Update manifest.json
manifest["version"] = new
with open(MANIFEST, "w") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
    f.write("\n")

# Update pyproject.toml
with open(PYPROJECT) as f:
    content = f.read()
content = content.replace(f'version = "{old}"', f'version = "{new}"', 1)
with open(PYPROJECT, "w") as f:
    f.write(content)

print(f"Bumped {old} → {new} ({part})")
```

- [ ] **Step 2: Verify a dry beta bump round-trips**

Run:
```bash
chmod +x scripts/bump_version.py
python3 scripts/bump_version.py beta
make version
```
Expected: prints `Bumped 1.1.0 → 1.1.0-beta.1 (beta)`; `make version` prints `1.1.0-beta.1`; both `manifest.json` and `pyproject.toml` show the new version.

- [ ] **Step 3: Revert the dry bump**

Run:
```bash
python3 scripts/bump_version.py patch
make version
```
Expected: prints `Bumped 1.1.0-beta.1 → 1.1.0 (patch)`; `make version` prints `1.1.0`. `git diff` on manifest/pyproject is now empty.

- [ ] **Step 4: Commit**

```bash
git add scripts/bump_version.py
git commit -m "build: add bump_version.py (manifest + pyproject sync, beta channel)"
```

---

## Task 5: scripts/check_translations.py + pre-commit bump

**Files:**
- Create: `scripts/check_translations.py`
- Modify: `.pre-commit-config.yaml`

- [ ] **Step 1: Create `scripts/check_translations.py`**

```python
#!/usr/bin/env python3
"""Check that all translation files have the same keys as en.json."""

import json
from pathlib import Path
import sys


def flatten_keys(obj: dict, prefix: str = "") -> set[str]:
    """Recursively flatten a nested dict into dot-separated key paths."""
    keys = set()
    for k, v in obj.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.update(flatten_keys(v, full))
        else:
            keys.add(full)
    return keys


def main() -> int:
    translations_dir = (
        Path(__file__).resolve().parent.parent
        / "custom_components"
        / "heating_cooling_degree_days"
        / "translations"
    )
    reference_file = translations_dir / "en.json"

    if not reference_file.exists():
        print(f"ERROR: Reference file not found: {reference_file}")
        return 1

    with open(reference_file) as f:
        reference_keys = flatten_keys(json.load(f))

    errors = 0
    translation_files = sorted(
        p for p in translations_dir.glob("*.json") if p.name != "en.json"
    )

    if not translation_files:
        print("No translation files found besides en.json")
        return 0

    for path in translation_files:
        with open(path) as f:
            file_keys = flatten_keys(json.load(f))

        missing = reference_keys - file_keys
        extra = file_keys - reference_keys
        name = path.name

        if missing or extra:
            errors += 1
            print(f"\n{name}:")
            if missing:
                print(f"  Missing keys ({len(missing)}):")
                for key in sorted(missing):
                    print(f"    - {key}")
            if extra:
                print(f"  Extra keys ({len(extra)}):")
                for key in sorted(extra):
                    print(f"    + {key}")
        else:
            print(f"{name}: OK ({len(file_keys)} keys)")

    if errors:
        print(f"\n{errors} file(s) with mismatched keys")
        return 1

    print(
        f"\nAll {len(translation_files)} translation files match en.json "
        f"({len(reference_keys)} keys)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it against the existing `en.json` / `fr.json`**

Run:
```bash
chmod +x scripts/check_translations.py
uv run python scripts/check_translations.py
```
Expected: either `fr.json: OK (N keys)` then the all-match summary, or a precise missing/extra key report. If it reports a mismatch, that is a **pre-existing** `fr.json` drift — fix `fr.json` to match `en.json` keys in the same commit.

- [ ] **Step 3: Bump the ruff pre-commit rev to match the pinned ruff**

In `.pre-commit-config.yaml`, change the ruff-pre-commit `rev` from `v0.7.0` to `v0.15.14` (matching `ruff==0.15.14` in `pyproject.toml`):

```yaml
repos:
    - repo: https://github.com/astral-sh/ruff-pre-commit
      rev: v0.15.14
      hooks:
          - id: ruff
            args:
                - --fix
```

(Leave the rest of `.pre-commit-config.yaml` unchanged — the `pretty-format-json` and hygiene hooks already match the reference stack.)

- [ ] **Step 4: Verify pre-commit runs clean**

Run:
```bash
uv run pre-commit run --all-files
```
Expected: all hooks pass (ruff may auto-fix formatting on first run; re-run until clean).

- [ ] **Step 5: Commit**

```bash
git add scripts/check_translations.py .pre-commit-config.yaml
git commit -m "build: add translation-key check, bump ruff pre-commit rev"
```

---

## Task 6: Fix tests/conftest.py (recorder dependency) — TDD

The manifest declares `"dependencies": ["recorder"]`. The reference stack requires the recorder test fixtures; without them, any test that exercises history/recorder access is unreliable. This task adds them and proves the wiring with a setup test.

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/test_init.py` (existing setup test is the verifier)

- [ ] **Step 1: Run the existing suite to capture the current baseline**

Run:
```bash
uv run pytest -q
```
Expected: record the current pass/fail counts. (Some recorder-touching tests may currently pass by accident or be skipped — this is the baseline to compare against.)

- [ ] **Step 2: Overwrite `tests/conftest.py`**

```python
"""Common fixtures for Heating & Cooling Degree Days tests."""

import pytest
from pytest_homeassistant_custom_component.typing import RecorderInstanceContextManager


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return


@pytest.fixture
async def mock_recorder_before_hass(
    async_test_recorder: RecorderInstanceContextManager,
) -> None:
    """Force recorder_db_url to resolve before the hass fixture.

    Required because the integration declares recorder as a dependency.
    """


@pytest.fixture(autouse=True)
async def auto_setup_recorder(recorder_mock):
    """Set up an in-memory recorder for all tests."""
    return
```

- [ ] **Step 3: Run the full suite and confirm no regression**

Run:
```bash
uv run pytest -q
```
Expected: pass count ≥ the Step 1 baseline; no new failures introduced by the recorder fixtures. If a test now fails because it asserted against a *missing* recorder, that test was relying on broken behavior — fix the test assertion in this commit.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "test: wire recorder fixtures (manifest declares recorder dependency)"
```

---

## Task 7: tests/test_calculations.py (fast pure-function coverage) — TDD

`calculate_hdd_from_readings` / `calculate_cdd_from_readings` are deterministic numerical-integration functions. They need no `hass` fixture, so they back the `make test-fast` target. (Note: `calculations.py` imports `homeassistant.components.recorder` at module top, so the import still loads HA — a future refactor could extract a HA-free module, but that is out of scope here.)

**Files:**
- Create: `tests/test_calculations.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Pure-function tests for HDD/CDD numerical integration (no hass fixture)."""

from datetime import datetime, timedelta

from custom_components.heating_cooling_degree_days.calculations import (
    calculate_cdd_from_readings,
    calculate_hdd_from_readings,
)

BASE = datetime(2026, 1, 1, 0, 0, 0)


def _series(temps: list[float], step_hours: float = 1.0):
    """Build (timestamp, temp) readings spaced step_hours apart."""
    return [(BASE + timedelta(hours=i * step_hours), t) for i, t in enumerate(temps)]


def test_hdd_empty_readings_returns_zero():
    assert calculate_hdd_from_readings([], base_temp=18.0) == 0


def test_cdd_empty_readings_returns_zero():
    assert calculate_cdd_from_readings([], base_temp=18.0) == 0


def test_hdd_constant_below_base_full_day():
    # 25 hourly readings = 24h span at a constant 8°C deficit below base 18°C.
    readings = _series([10.0] * 25)
    # 24h = 1.0 day at 8 deg deficit → 8.0 degree-days.
    assert calculate_hdd_from_readings(readings, base_temp=18.0) == 8.0


def test_hdd_constant_above_base_is_zero():
    readings = _series([22.0] * 25)
    assert calculate_hdd_from_readings(readings, base_temp=18.0) == 0.0


def test_cdd_constant_above_base_full_day():
    # 24h at constant 6°C excess above base 18°C → 6.0 degree-days.
    readings = _series([24.0] * 25)
    assert calculate_cdd_from_readings(readings, base_temp=18.0) == 6.0


def test_cdd_constant_below_base_is_zero():
    readings = _series([10.0] * 25)
    assert calculate_cdd_from_readings(readings, base_temp=18.0) == 0.0


def test_hdd_trapezoidal_crossing_base():
    # Two points 24h apart: 18°C (zero deficit) → 6°C (12°C deficit).
    # Trapezoid avg deficit = (0 + 12) / 2 = 6 over 1.0 day → 6.0.
    readings = [(BASE, 18.0), (BASE + timedelta(hours=24), 6.0)]
    assert calculate_hdd_from_readings(readings, base_temp=18.0) == 6.0


def test_readings_are_sorted_before_integration():
    # Same data, reversed input order, must give the identical result.
    forward = _series([10.0] * 25)
    reversed_input = list(reversed(forward))
    assert calculate_hdd_from_readings(
        reversed_input, base_temp=18.0
    ) == calculate_hdd_from_readings(forward, base_temp=18.0)
```

- [ ] **Step 2: Run the tests**

Run:
```bash
uv run pytest tests/test_calculations.py -v
```
Expected: all tests PASS (these exercise existing, already-correct functions; they lock current behavior). If `test_hdd_constant_below_base_full_day` fails on a rounding boundary, inspect the actual value — the function rounds to 1 decimal, so an exact `8.0` is expected for the constant case.

- [ ] **Step 3: Verify the fast target works**

Run:
```bash
make test-fast
```
Expected: runs only `tests/test_calculations.py`, green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_calculations.py
git commit -m "test: add pure HDD/CDD integration tests (test-fast target)"
```

---

## Task 8: CI — replace flake8 lint, add test matrix

**Files:**
- Replace: `.github/workflows/lint.yml`
- Create: `.github/workflows/tests.yml`
- Keep (verify only): `.github/workflows/validate.yml`, `release.yml`, `release-drafter.yml`

- [ ] **Step 1: Overwrite `.github/workflows/lint.yml`**

```yaml
name: Lint

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python 3.13
        run: uv python install 3.13

      - name: Install dependencies
        run: uv sync --group dev

      - name: Lint with ruff
        run: uv run ruff check custom_components tests

      - name: Check translation keys
        run: uv run python scripts/check_translations.py
```

- [ ] **Step 2: Create `.github/workflows/tests.yml`**

```yaml
name: Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    # pytest-homeassistant-custom-component (phac) pins a specific HA version.
    # To test against a given HA release, install the matching phac version.
    #
    # HA version  | phac version
    # ------------|-------------
    # 2025.1.0    | 0.13.201
    # 2026.2.0    | 0.13.313
    strategy:
      fail-fast: false
      matrix:
        include:
          # Oldest supported HA version
          - ha-version: "2025.1.0"
            phac-version: "0.13.201"
            python-version: "3.13"
          # Latest HA (resolved dynamically via latest phac)
          - ha-version: "latest"
            phac-version: ""
            python-version: "3.13"
          - ha-version: "latest"
            phac-version: ""
            python-version: "3.14"

    name: "Tests (HA ${{ matrix.ha-version }} / Python ${{ matrix.python-version }})"

    steps:
      - uses: actions/checkout@v5

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python ${{ matrix.python-version }}
        run: uv python install ${{ matrix.python-version }}

      - name: Install dependencies
        run: uv sync --group dev

      - name: Pin HA ${{ matrix.ha-version }}
        if: matrix.phac-version != ''
        run: uv pip install --prerelease=allow pytest-homeassistant-custom-component==${{ matrix.phac-version }}

      - name: Show resolved HA version
        run: uv run python -c "from homeassistant.const import __version__; print('HA version:', __version__)"

      - name: Run tests with pytest
        run: uv run pytest
```

- [ ] **Step 3: Validate workflow YAML locally**

Run:
```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/lint.yml')); yaml.safe_load(open('.github/workflows/tests.yml')); print('workflows OK')"
```
Expected: prints `workflows OK` (no YAML parse error).

- [ ] **Step 4: Confirm validate.yml/release.yml are unchanged and correct**

Run:
```bash
git status .github/workflows/
```
Expected: only `lint.yml` modified and `tests.yml` added; `validate.yml`, `release.yml`, `release-drafter.yml` untouched.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/lint.yml .github/workflows/tests.yml
git commit -m "ci: ruff + translation lint, matrix pytest (HA x Python)"
```

---

## Task 9: Cleanup — dead files + .gitignore

**Files:**
- Delete: `src/degree_days/`, `links.sh`
- Modify: `.gitignore`

- [ ] **Step 1: Remove the dead directory and vestige script**

```bash
git rm -r src/degree_days
git rm links.sh
```
(If `src/` becomes empty, remove it too: `rmdir src 2>/dev/null || true`.)

- [ ] **Step 2: Edit `.gitignore`**

Remove the dead "Links for local development" block (the `#Links for local development` comment plus the 12 `/<module>.py` and `/translations` entries) and the stray `todo` line. Then **remove the `.python-version` line** (line ~102, under the pyenv comment) so the pinned version is tracked.

- [ ] **Step 3: Track `.python-version`**

Run:
```bash
git add .python-version
git status --short .python-version
```
Expected: `.python-version` shows as a new tracked file (`A  .python-version`), no longer ignored.

- [ ] **Step 4: Verify the working tree is clean of dead refs**

Run:
```bash
grep -rn "links.sh" . --exclude-dir=.git || echo "no references to links.sh"
test -d src/degree_days && echo "STILL PRESENT" || echo "src/degree_days removed"
```
Expected: `no references to links.sh` and `src/degree_days removed`.

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: remove dead src/degree_days, links.sh, and stale .gitignore entries"
```

---

## Task 10: Final full verification

- [ ] **Step 1: Full quality + test pass**

Run:
```bash
make check && make test
```
Expected: ruff lint + format clean; full pytest suite green.

- [ ] **Step 2: Confirm the old world is gone**

Run:
```bash
ls requirements*.txt setup.cfg .pylintrc .ruff.toml 2>/dev/null || echo "old config removed"
test -s uv.lock && echo "uv.lock populated"
```
Expected: `old config removed`; `uv.lock populated`.

- [ ] **Step 3: Confirm pre-commit is wired**

Run:
```bash
uv run pre-commit run --all-files
```
Expected: all hooks pass.

---

## Self-Review

**Spec coverage** — every pillar of `topic-ha-custom-integration-stack` is addressed:
- uv → Task 1 (pyproject + lockfile + `.python-version`).
- single pyproject config → Task 1 (ruff + pytest folded in; `.ruff.toml`/`setup.cfg`/`.pylintrc` deleted).
- Makefile façade → Task 2.
- scripts/ (wrappers + python tooling) → Tasks 3, 4, 5.
- ruff + pre-commit → Tasks 1, 5.
- pytest + phac, hexagonal split, mock the boundary → Tasks 6 (recorder fixtures), 7 (pure fast tests).
- CI matrix → Task 8.
- HACS + hassfest → kept (Task 8 Step 4 verifies untouched).
- migration signals cleaned (flake8-CI, bump2version, requirements*, uv.lock stub, missing recorder fixture, dead .gitignore) → Tasks 1, 4, 6, 8, 9.

**Open decisions surfaced** (in the header): Python floor 3.13 vs 3.12; devcontainer fate deferred to a separate issue.

**Type/name consistency:** `make test-fast` (Task 2) matches the file it runs (`tests/test_calculations.py`, Task 7). `bump_version.py` MANIFEST path matches the real domain dir. `check_translations.py` translations dir matches `custom_components/heating_cooling_degree_days/translations/` (en.json + fr.json confirmed present). Pinned `ruff==0.15.14` (Task 1) matches pre-commit `rev: v0.15.14` (Task 5).
