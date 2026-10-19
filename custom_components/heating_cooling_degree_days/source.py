"""Track a source's stable identity and report missing temperature sensors."""

from homeassistant.components.recorder import get_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_TEMPERATURE_SENSOR, DOMAIN

CONF_SOURCE_REGISTRY_ID = "temperature_sensor_registry_id"


@callback
def async_clear_source_issue(hass: HomeAssistant, entry_id: str) -> None:
    """Remove only this entry's missing-source repair."""
    ir.async_delete_issue(hass, DOMAIN, f"missing_source_{entry_id}")


class SourceTracker:
    """Resolve registry renames without treating them as a different sensor."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Resolve saved identities, including renames while the entry was unloaded."""
        self.hass = hass
        self.entry = entry
        self.previous_entity_id = entry.data[CONF_TEMPERATURE_SENSOR]
        registry = er.async_get(hass)
        self.registry_id = entry.data.get(CONF_SOURCE_REGISTRY_ID)
        registered = registry.async_get(self.registry_id or self.previous_entity_id)
        if registered:
            self.registry_id = registered.id
        self.entity_id = registered.entity_id if registered else self.previous_entity_id

    @callback
    def async_available(self) -> bool:
        """Publish a repair for missing entities, leaving unavailable states to history."""
        registered = er.async_get(self.hass).async_get(self.entity_id)
        available = self.hass.states.get(self.entity_id) is not None and (
            self.registry_id is None
            or (registered is not None and registered.id == self.registry_id)
        )
        if available:
            async_clear_source_issue(self.hass, self.entry.entry_id)
        else:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"missing_source_{self.entry.entry_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="missing_source",
                translation_placeholders={
                    "name": self.entry.title,
                    "entity_id": self.entity_id,
                    "url": f"/config/integrations/integration/{DOMAIN}",
                },
            )
        return available

    @callback
    def async_update_entry(self) -> None:
        """Save the resolved entity ID and stable identity with a single update."""
        data = {**self.entry.data, CONF_TEMPERATURE_SENSOR: self.entity_id}
        if self.registry_id:
            data[CONF_SOURCE_REGISTRY_ID] = self.registry_id
        self.hass.config_entries.async_update_entry(self.entry, data=data)

    @callback
    def async_track(self, coordinator) -> None:
        """Attach entry-owned listeners; the entry update listener owns any reload."""

        async def handle_registry_update(event) -> None:
            if (
                event.data["action"] == "update"
                and event.data.get("old_entity_id") == self.entity_id
            ):
                registered = er.async_get(self.hass).async_get(event.data["entity_id"])
                if registered and (
                    self.registry_id is None or registered.id == self.registry_id
                ):
                    if self.registry_id is None:
                        self.registry_id = registered.id
                        # A source may acquire a registry entry after setup. Upgrade
                        # its fingerprint before changing the saved entity ID.
                        await coordinator._save_ledger(coordinator.ledger)
                    self.entity_id = registered.entity_id
                    # Recorder queues states_meta/statistics renames from this event.
                    # Finish that commit before reloading and querying the new ID.
                    await get_instance(self.hass).async_block_till_done()
                    self.async_update_entry()
            elif event.data["entity_id"] == self.entity_id:
                if event.data["action"] == "create" and self.registry_id is None:
                    if registered := er.async_get(self.hass).async_get(self.entity_id):
                        self.registry_id = registered.id
                        await coordinator._save_ledger(coordinator.ledger)
                        self.async_update_entry()
                self.async_available()

        @callback
        def registry_updated(event) -> None:
            if (
                event.data["entity_id"] == self.entity_id
                or event.data.get("old_entity_id") == self.entity_id
            ):
                self.entry.async_create_background_task(
                    self.hass, handle_registry_update(event), "source registry update"
                )

        @callback
        def state_changed(_event) -> None:
            was_missing = coordinator.source_missing
            coordinator.source_missing = not self.async_available()
            if was_missing and not coordinator.source_missing:
                self.entry.async_create_background_task(
                    self.hass, coordinator.async_request_refresh(), "source restored"
                )

        self.entry.async_on_unload(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, registry_updated
            )
        )
        self.entry.async_on_unload(
            async_track_state_change_event(self.hass, self.entity_id, state_changed)
        )
        coordinator.source_missing = not self.async_available()
