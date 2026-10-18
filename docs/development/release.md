# Manual releases

Releases are prepared and published by a maintainer. There is no automatic release
drafter or generated-notes configuration. The manifest is the runtime version's
source of truth; `make bump` updates it and `pyproject.toml`, then refreshes
`uv.lock`. Changelog headings and release notes are reviewed manually.

The next stable release is planned as **v1.2.0**. Publish it only after the planned
calculation, calendar-period and missing-data fixes are merged and validated.
This checklist does not bump or publish anything by itself.

## Prepare the release

1. Start a release preparation branch from fresh `origin/main`. Inspect the diff
   since the previous release and confirm the intended scope. Check that all
   required fixes and upgrade tests have passed.
2. Choose the version: patch for fixes, minor for new compatible features, major
   for incompatible changes. Run `make bump PART=patch|minor|major` with the
   selected part, not the literal alternatives. Do not bump twice by accident.
3. Move `[Unreleased]` entries in `CHANGELOG.md` under a dated
   `## [X.Y.Z] - YYYY-MM-DD` heading. Leave an empty `[Unreleased]` heading above it.
   Review the manifest, project version, lockfile and changelog together. Do not
   retag a published release to correct old metadata.
4. Run the checks below and require green Tests, Lint and Validate workflows on
   the final release preparation commit. Review the actual Python/HA versions
   printed by the matrix, including the declared HA floor in `hacs.json`.
5. Smoke-test installation and upgrade from the previous stable release. Check
   multiple entries, preserved IDs/history, reconfiguration, restart persistence,
   disabled sensors, daily values, period boundaries and incomplete recorder data.
   Record any reset, migration or statistics changes in the release notes.
6. Commit the four version/changelog files as `release: X.Y.Z`, open the release
   preparation PR and merge after review. The lockfile may normalize beta version
   spelling to PEP 440; do not edit that normalized value by hand.

```bash
uv sync --locked --group dev
uv run --locked ruff check custom_components tests
uv run --locked ruff format --check custom_components tests
uv run --locked python scripts/check_translations.py
uv run --locked pytest -q
```

Run floor/latest tests in their separate CI environments. After an explicit
harness override, use `uv run --no-sync pytest` so the lockfile does not undo it.

## Beta releases

To start the next minor as a beta, run `make bump PART=minor`, then
`make bump PART=beta`: for example, `1.1.0` becomes `1.2.0-beta.1`.
`PART=beta` alone increments the suffix of the current base version; it does not
select the next minor. Further beta bumps increment `beta.N`.

Use the full beta version in the dated changelog heading, tag and release title.
Publish with `--prerelease --latest=false`; keep the previous stable release as
Latest. Testers opt in through HACS's beta-version selector. To promote a tested
beta to stable, `make bump PART=patch` removes the beta suffix without increasing
the patch number. Summarize the full change since the previous stable release in
the stable release notes, not just the last beta's diff.

## Publish and verify

1. Prepare English release notes using the template below. Use the title `vX.Y.Z`
   and link the compare view against the previous appropriate tag. Explain user
   behavior and upgrade requirements; omit empty or irrelevant sections.
2. Check for an existing tag or draft. The old `v1.1.1` draft titled
   `Example title` must be reviewed and replaced/retargeted manually before the
   next release. Removing the drafter does not remove existing GitHub drafts.
3. Verify the merged release commit SHA, then publish against that exact SHA:

   ```bash
   gh release create vX.Y.Z --target <verified-commit-sha> --title "vX.Y.Z" --notes-file <notes.md>
   ```

   For a beta, add `--prerelease --latest=false`. This command creates a new
   release; do not use it blindly if a release with that tag already exists.
4. Watch the Release workflow. It checks out the release tag, requires equality
   between tag (without `v`), manifest and project versions, and uploads
   `heating_cooling_degree_days.zip`. It has explicit write permission and refuses
   to overwrite an existing asset.
5. Download and inspect the attached ZIP: `manifest.json` must be at the archive
   root and contain the released version. The ZIP is **flat**. For manual
   installation, extract into `custom_components/heating_cooling_degree_days/`,
   never directly into `custom_components/`. GitHub's source archive has a
   different layout and is not the attached HACS asset.
6. Confirm HACS can download the asset, upgrade a test installation, restart Home
   Assistant and check its loaded version and logs.

The asset workflow starts **after** publication, so the release is briefly
visible without its ZIP. If upload fails with no asset present, resolve the
failure and rerun the job. If an asset already exists, verify it instead of
overwriting it. If the published tag contains incorrect code or versions, ship a
new corrected version; do not move the tag or silently replace its archive.

## Release notes template

```markdown
# Heating & Cooling Degree Days vX.Y.Z: <short theme>

<One or two sentences describing the user-visible result. Link relevant issues.>

## Highlights

- <Feature or fix and its observable effect.>

## Upgrade notes

<Minimum supported Home Assistant version. Explain any required user action,
stored-value reset, entity change or statistics change. Remove this section
only when there is nothing relevant to communicate.>

## Installation

1. Update to vX.Y.Z through HACS.
2. Restart Home Assistant.

For manual installation, extract the attached heating_cooling_degree_days.zip
into custom_components/heating_cooling_degree_days/.

<For a beta, explain how to opt in and which behavior needs testing.>

## Bug reports

Include the integration and Home Assistant versions, temperature sensor and
units, affected dates, and relevant logs.

**Full changelog:** [vPREV...vX.Y.Z](https://github.com/alepee/hass-heating_cooling_degree_days/compare/vPREV...vX.Y.Z)
```
