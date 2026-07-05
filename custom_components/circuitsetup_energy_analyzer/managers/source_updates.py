from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from typing import Any


class SourceUpdateManager:
    """Manage source entity listener lifecycle and debounced updates."""

    def __init__(
        self,
        coordinator: Any,
        *,
        track_state_change_event: Callable[..., Any] | None,
        debounce_seconds: float,
    ) -> None:
        self._coordinator = coordinator
        self._track_state_change_event = track_state_change_event
        self._debounce_seconds = debounce_seconds
        self.source_entities: tuple[str, ...] = ()
        self.pending_source_update_entities: tuple[str, ...] = ()
        self.last_source_update_entities: tuple[str, ...] = ()
        self._pending_source_update_entities: set[str] = set()
        self._source_update_task: asyncio.Task[Any] | None = None
        self._unsub_state_change: Any = None

    @property
    def source_update_task(self) -> asyncio.Task[Any] | None:
        return self._source_update_task

    async def async_start(self, source_entities: Iterable[str]) -> None:
        """Start listening to configured source entity state changes."""
        if self._unsub_state_change is not None:
            self._unsub_state_change()
            self._unsub_state_change = None
        self.cancel_pending_source_update()

        self.source_entities = tuple(source_entities)
        self._coordinator.started = True

        if self._track_state_change_event is None or not self.source_entities:
            return

        try:
            self._unsub_state_change = self._track_state_change_event(
                self._coordinator.hass,
                list(self.source_entities),
                self.async_handle_source_state_change,
            )
        except AttributeError:
            self._unsub_state_change = None

    async def async_stop(self) -> None:
        """Stop listening to source entity state changes."""
        if self._unsub_state_change is not None:
            self._unsub_state_change()
            self._unsub_state_change = None
        self.cancel_pending_source_update()
        self._coordinator.started = False

    async def async_handle_source_state_change(self, event: Any) -> None:
        """Handle Home Assistant source state changes."""
        entity_id = _event_entity_id(event)
        if entity_id:
            self._pending_source_update_entities.add(entity_id)
        self.pending_source_update_entities = tuple(
            sorted(self._pending_source_update_entities)
        )
        if (
            self._source_update_task is not None
            and not self._source_update_task.done()
        ):
            return
        self._source_update_task = asyncio.create_task(
            self.async_process_debounced_source_update()
        )

    async def async_process_debounced_source_update(self) -> None:
        """Process one analyzer update for a burst of source state changes."""
        try:
            await asyncio.sleep(self._debounce_seconds)
            changed_entities = tuple(sorted(self._pending_source_update_entities))
            self._pending_source_update_entities.clear()
            self.pending_source_update_entities = ()
            self.last_source_update_entities = changed_entities
            if not self._coordinator.started:
                return
            await self._coordinator.async_process_update(
                changed_entities=changed_entities
            )
        except asyncio.CancelledError:
            self._pending_source_update_entities.clear()
            self.pending_source_update_entities = ()
            self._source_update_task = None
            raise
        finally:
            if self._source_update_task is asyncio.current_task():
                self._source_update_task = None
                if self._coordinator.started and self._pending_source_update_entities:
                    self.pending_source_update_entities = tuple(
                        sorted(self._pending_source_update_entities)
                    )
                    self._source_update_task = asyncio.create_task(
                        self.async_process_debounced_source_update()
                    )

    def cancel_pending_source_update(self) -> None:
        """Cancel queued source-state processing during restart/unload."""
        if self._source_update_task is not None and not self._source_update_task.done():
            self._source_update_task.cancel()
        self._source_update_task = None
        self._pending_source_update_entities.clear()
        self.pending_source_update_entities = ()


def _event_entity_id(event: Any) -> str:
    data = getattr(event, "data", {})
    if not isinstance(data, Mapping):
        return ""
    return str(data.get("entity_id") or "").strip()
