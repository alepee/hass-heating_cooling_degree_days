# Source sensor identity and history

Registered temperature sensors are tracked by their entity registry entry ID.
The config entry retains the current entity ID for recorder queries. A rename
updates that field and invokes the existing entry update listener once. The
ledger fingerprint uses the registry ID, base temperature and calculation unit;
raw entity-ID fingerprints are migrated before the config entry is updated.
Config entry version 2, output entity unique IDs and per-entry storage keys stay
unchanged. Unregistered sensors retain entity-ID fingerprints until registered.

A saved registry ID also resolves renames made while this integration is unloaded.
If another sensor takes a removed sensor's entity ID, it is not accepted as the
same source: explicit Reconfigure is required and resets the ledger.

## Recorder behavior

Home Assistant's recorder listens for entity registry rename events. It queues
statistics metadata updates and a `states_meta.entity_id` update. Historical
state rows keep their `metadata_id`, so queries using the new entity ID retrieve
the old samples. The integration waits asynchronously for that recorder commit
before the rename-triggered reload starts backfill. It never rewrites the database.

Recorder refuses the metadata rename if the target entity ID already exists in
`states_meta` (for example, a previously used entity ID). It does not merge those
histories. Existing calculated ledger days survive, but uncached old-ID history
may then be inaccessible through the new ID. Prefer a previously unused entity ID.
This behavior exists in both HA 2025.1 and the locked HA 2026.2.3 environment.

Source references: [recorder registry listener](https://github.com/home-assistant/core/blob/2025.1.0/homeassistant/components/recorder/entity_registry.py)
and [states metadata manager](https://github.com/home-assistant/core/blob/2025.1.0/homeassistant/components/recorder/table_managers/states_meta.py).
`tests/test_source.py` exercises an actual recorder database to verify history
lookup after a rename and the coverage gap left by a removed/restored state.

## Missing sources

A missing state or missing/mismatched saved registry entry creates one warning
repair per config entry. The English/French notice links to the integration and
instructs the user to open Reconfigure. It clears on restoration, successful
reconfiguration or entry removal. Listeners are owned by the config entry.
An existing `unknown`/`unavailable` state is handled as an observed gap by the
history kernel, rather than as a deleted source.

While a source is absent, backfill is deliberately suspended: a stale numeric
start-state must not be extrapolated across newly completed days. Cached records
remain usable, calendar aggregation continues, and missing dates reduce coverage.
This also delays backfill of legitimate older observations until restoration.
Normal backfill bounds, recorder retention and partial retry rules still apply.
