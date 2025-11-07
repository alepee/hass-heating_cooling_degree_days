"""Migrations for Heating & Cooling Degree Days integration."""

from ._20251107_1_0_3_update_entities_ids import (
    async_migrate_entity_unique_ids,
)

__all__ = ["async_migrate_entity_unique_ids"]
