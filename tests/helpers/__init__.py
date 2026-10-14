"""Shared test helpers for CircuitSetup Energy Analyzer."""

from types import SimpleNamespace
from typing import Any


class FakeConfigEntry(SimpleNamespace):
    def async_on_unload(self, _callback: Any) -> None:
        """Unit tests stop their coordinators explicitly."""
