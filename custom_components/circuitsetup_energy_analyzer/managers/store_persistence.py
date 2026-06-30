from __future__ import annotations

from datetime import datetime
from typing import Any


class StorePersistenceManager:
    """Manage store dirty tracking and save gating for the coordinator."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator
        self.dirty = False

    def mark_dirty(self) -> None:
        self.dirty = True

    async def async_save_if_dirty(self, now: datetime) -> None:
        store = getattr(self._coordinator, "_store", None)
        if store is None or not self.dirty:
            return
        self._coordinator._apply_retention(now)
        store.data = self._coordinator.store_data
        await store.async_save()
        self.dirty = False
