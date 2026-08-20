from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from typing import Any


class SourceUpdateManager:
    """Manage source entity listener lifecycle and debounced updates."""

    def __init__(
        self,
        coordinator: Any,
        *,
        track_state_change_event: Callable[..., Any] | None,
        debounce_seconds: float,
        max_batch_seconds: float | None = None,
        analysis_interval_seconds: float = 0.0,
    ) -> None:
        self._coordinator = coordinator
        self._track_state_change_event = track_state_change_event
        self._debounce_seconds = debounce_seconds
        self._max_batch_seconds = max(
            debounce_seconds if max_batch_seconds is None else max_batch_seconds,
            debounce_seconds,
        )
        self._analysis_interval_seconds = max(float(analysis_interval_seconds), 0.0)
        self.source_entities: tuple[str, ...] = ()
        self.pending_source_update_entities: tuple[str, ...] = ()
        self.last_source_update_entities: tuple[str, ...] = ()
        self._pending_source_update_entities: set[str] = set()
        self._source_update_task: asyncio.Task[Any] | None = None
        self._analysis_update_task: asyncio.Task[Any] | None = None
        self._pending_analysis_entities: set[str] = set()
        self._batch_started_at: float | None = None
        self._latest_source_update_at: float | None = None
        self._unsub_state_change: Any = None

    @property
    def source_update_task(self) -> asyncio.Task[Any] | None:
        return self._source_update_task

    @property
    def analysis_update_task(self) -> asyncio.Task[Any] | None:
        return self._analysis_update_task

    @property
    def pending_analysis_entities(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending_analysis_entities))

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
        self._coordinator.started = False
        for pending_task in (self._source_update_task, self._analysis_update_task):
            if (
                pending_task is not None
                and pending_task is not asyncio.current_task()
                and not pending_task.done()
            ):
                pending_task.cancel()
                with suppress(asyncio.CancelledError):
                    await pending_task
        self.cancel_pending_source_update()

    async def async_handle_source_state_change(self, event: Any) -> None:
        """Handle Home Assistant source state changes."""
        entity_id = _event_entity_id(event)
        now = asyncio.get_running_loop().time()
        if not self._pending_source_update_entities:
            self._batch_started_at = now
        self._latest_source_update_at = now
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
            await self._async_wait_for_source_update_batch()
            changed_entities = tuple(sorted(self._pending_source_update_entities))
            self._pending_source_update_entities.clear()
            self.pending_source_update_entities = ()
            self._batch_started_at = None
            self.last_source_update_entities = changed_entities
            if not self._coordinator.started:
                return
            ingest = getattr(self._coordinator, "async_ingest_source_update", None)
            if ingest is not None:
                loop = asyncio.get_running_loop()
                started_at = loop.time()
                try:
                    await ingest(changed_entities=changed_entities)
                finally:
                    self._coordinator._record_runtime_performance(
                        "source_ingest",
                        loop.time() - started_at,
                    )
            self._pending_analysis_entities.update(changed_entities)
            if self._analysis_interval_seconds <= 0.0:
                await self.async_process_pending_analysis()
            elif (
                self._analysis_update_task is None
                or self._analysis_update_task.done()
            ):
                self._analysis_update_task = asyncio.create_task(
                    self.async_process_pending_analysis()
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

    async def async_process_pending_analysis(self) -> None:
        """Run one latest-state analysis pass without building an event backlog."""
        current_task = asyncio.current_task()
        try:
            if self._analysis_interval_seconds > 0.0:
                await asyncio.sleep(self._analysis_interval_seconds)
            changed_entities = tuple(sorted(self._pending_analysis_entities))
            self._pending_analysis_entities.clear()
            if not self._coordinator.started or not changed_entities:
                return
            loop = asyncio.get_running_loop()
            started_at = loop.time()
            try:
                await self._coordinator.async_process_update(
                    changed_entities=changed_entities
                )
            finally:
                self._coordinator._record_runtime_performance(
                    "source_update",
                    loop.time() - started_at,
                )
        except asyncio.CancelledError:
            raise
        finally:
            if self._analysis_update_task is current_task:
                self._analysis_update_task = None
            if self._coordinator.started and self._pending_analysis_entities:
                self._analysis_update_task = asyncio.create_task(
                    self.async_process_pending_analysis()
                )

    async def _async_wait_for_source_update_batch(self) -> None:
        while True:
            now = asyncio.get_running_loop().time()
            started_at = self._batch_started_at
            if started_at is None:
                started_at = now
            latest_at = self._latest_source_update_at
            if latest_at is None:
                latest_at = started_at
            quiet_remaining = self._debounce_seconds - (now - latest_at)
            max_remaining = self._max_batch_seconds - (now - started_at)
            if quiet_remaining <= 0 or max_remaining <= 0:
                return
            await asyncio.sleep(min(quiet_remaining, max_remaining))

    def cancel_pending_source_update(self) -> None:
        """Cancel queued source-state processing during restart/unload."""
        if self._source_update_task is not None and not self._source_update_task.done():
            self._source_update_task.cancel()
        if (
            self._analysis_update_task is not None
            and not self._analysis_update_task.done()
        ):
            self._analysis_update_task.cancel()
        self._source_update_task = None
        self._analysis_update_task = None
        self._pending_source_update_entities.clear()
        self._pending_analysis_entities.clear()
        self.pending_source_update_entities = ()
        self._batch_started_at = None
        self._latest_source_update_at = None


def _event_entity_id(event: Any) -> str:
    data = getattr(event, "data", {})
    if not isinstance(data, Mapping):
        return ""
    return str(data.get("entity_id") or "").strip()
