"""Strict AnalyzerState update helpers."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


def apply_state_update(state: Any, path: tuple[str, ...], value: Any) -> None:
    """Apply a processor-requested update to AnalyzerState."""
    if not path:
        msg = "State update path must not be empty"
        raise ValueError(msg)
    if len(path) < 2:
        msg = "State update path must include a root and destination key"
        raise ValueError(msg)

    root = path[0]
    if root not in getattr(type(state), "__dataclass_fields__", {}):
        msg = f"State update path has unknown root: {root}"
        raise ValueError(msg)

    target = getattr(state, root)
    if not isinstance(target, MutableMapping):
        msg = f"State update root is not a mapping: {root}"
        raise TypeError(msg)

    target_segment = root
    for segment in path[1:-1]:
        if not isinstance(target, MutableMapping):
            msg = f"State update target is not a mapping at: {target_segment}"
            raise TypeError(msg)
        if segment not in target:
            msg = f"State update cannot create intermediate key: {segment}"
            raise ValueError(msg)
        target = target[segment]
        target_segment = segment

    if not isinstance(target, MutableMapping):
        msg = f"State update target is not a mapping at: {target_segment}"
        raise TypeError(msg)
    final_segment = path[-1]
    target[final_segment] = value


class StateReducer:
    """Apply validated state update paths."""

    def apply_update(self, state: Any, path: tuple[str, ...], value: Any) -> None:
        """Apply one validated state update path."""
        apply_state_update(state, path, value)
