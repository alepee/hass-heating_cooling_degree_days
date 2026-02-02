"""Migrations for Heating & Cooling Degree Days integration."""

from .entity_unique_ids import (
    async_migrate_entity_unique_ids,
)

__all__ = ["async_migrate_entity_unique_ids"]
