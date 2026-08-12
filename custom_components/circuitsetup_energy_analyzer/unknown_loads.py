from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .nilm import (
    NilmEdge,
    NilmSignature,
    nilm_signature_fingerprint,
    nilm_signature_fingerprint_v1,
    nilm_signature_is_assignable,
    nilm_signature_is_off_direction,
)

MIN_OCCURRENCES = 3
MIN_CONFIDENCE = 0.5
UNKNOWN_LOAD_INVENTORY_SCHEMA_VERSION = 4
MIN_SIGNATURE_PAIR_SCORE = 0.50
SIGNATURE_PAIR_AMBIGUITY_MARGIN = 0.08
EDGE_COMPONENT_AMBIGUITY_MARGIN = 0.08
LEGACY_IDENTITY_UNRESOLVED_KEY = "legacy_identity_unresolved"
NILM_SESSION_HISTORY_COVERAGE_IDENTITY_MAX_ITEMS = 8_192
NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT = 2_000
NILM_SESSION_HISTORY_IDENTITY_MAX_COMPONENTS = (
    NILM_SESSION_HISTORY_COVERAGE_IDENTITY_MAX_ITEMS
)
NILM_SESSION_HISTORY_IDENTITY_MAX_ALIASES_PER_COMPONENT = 2
NILM_SESSION_HISTORY_IDENTITY_MAX_CHARS = 256
NILM_SESSION_HISTORY_IDENTITY_MAX_UTF8_BYTES = 256
NILM_SESSION_HISTORY_TIMESTAMP_MAX_CHARS = 64
NILM_SESSION_HISTORY_TIMESTAMP_MAX_UTF8_BYTES = 64
NILM_SESSION_HISTORY_SCALAR_ABS_MAX = 1_000_000_000
NILM_SESSION_HISTORY_COUNT_MAX = 1_000_000
_NILM_SESSION_HISTORY_TIMESTAMP_LATEST = (
    datetime.max - timedelta(days=30)
).replace(tzinfo=UTC)
_NILM_SESSION_HISTORY_MAX_ROW_FIELDS = 42
_NILM_SESSION_HISTORY_MAX_UNKNOWN_FIELDS = (
    NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT * 64
)
_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX = NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT
_NILM_SESSION_HISTORY_MISSING = object()
_NILM_SESSION_HISTORY_ROW_TEXT_FIELDS = (
    "session_id",
    "mains_circuit_id",
    "signature_fingerprint",
    "on_edge_id",
    "off_edge_id",
    "assignment_id",
    "energy_source",
)
_NILM_SESSION_HISTORY_ROW_TIMESTAMP_FIELDS = (
    "start",
    "end",
    "trace_started_at",
    "trace_ended_at",
)
_NILM_SESSION_HISTORY_ROW_NUMBER_FIELDS = (
    "duration_seconds",
    "median_power_w",
    "estimated_energy_kwh",
    "confidence",
    "known_load_confidence",
    "on_delta_w",
    "off_delta_w",
    "on_delta_var",
    "off_delta_var",
    "plateau_power_w",
    "measured_energy_kwh",
    "power_coverage",
    "partial_energy_kwh",
    "energy_estimate_confidence",
    "covered_duration_seconds",
    "longest_trace_gap_seconds",
    "known_source_coverage_min",
    "known_source_coverage_time_weighted",
)
_NILM_SESSION_HISTORY_ROW_COUNT_FIELDS = (
    "overlap_count",
    "alternate_match_count",
    "intermediate_transition_count",
    "stale_subtraction_prevented_count",
    "partial_residual_point_count",
    "negative_residual_point_count",
    "trace_point_cap_truncation_count",
)
_NILM_SESSION_HISTORY_ROW_BOOLEAN_FIELDS = (
    "ambiguous",
    "known_load_masked",
    "pre_context_coverage",
    "post_context_coverage",
    "trace_point_cap_truncated",
)
_NILM_SESSION_HISTORY_ENERGY_SOURCES = frozenset(
    {
        "residual_trace_measured",
        "residual_trace_partial",
        "transition_fallback",
        "unavailable",
    }
)
_NILM_SESSION_HISTORY_LEGACY_ENERGY_FIELD = "energy_kwh"
_NILM_SESSION_HISTORY_ROW_OUTPUT_FIELDS = (
    "session_id",
    "mains_circuit_id",
    "signature_fingerprint",
    "on_edge_id",
    "off_edge_id",
    "start",
    "end",
    "duration_seconds",
    "median_power_w",
    "estimated_energy_kwh",
    "confidence",
    "overlap_count",
    "ambiguous",
    "alternate_match_count",
    "known_load_masked",
    "known_load_confidence",
    "assignment_id",
    "on_delta_w",
    "off_delta_w",
    "on_delta_var",
    "off_delta_var",
    "plateau_power_w",
    "measured_energy_kwh",
    "power_coverage",
    "intermediate_transition_count",
    "partial_energy_kwh",
    "energy_source",
    "energy_estimate_confidence",
    "covered_duration_seconds",
    "longest_trace_gap_seconds",
    "pre_context_coverage",
    "post_context_coverage",
    "known_source_coverage_min",
    "known_source_coverage_time_weighted",
    "trace_point_cap_truncated",
    "trace_started_at",
    "trace_ended_at",
    "stale_subtraction_prevented_count",
    "partial_residual_point_count",
    "negative_residual_point_count",
    "trace_point_cap_truncation_count",
)
_NILM_SESSION_HISTORY_DURATION_CLOSE_FIELDS = (
    "session_id",
    "off_edge_id",
    "end",
    "duration_seconds",
    "estimated_energy_kwh",
    "confidence",
    "ambiguous",
    "alternate_match_count",
)


def _nilm_session_history_utf8_length(value: str) -> int | None:
    """Return a safe UTF-8 length without letting malformed text escape ingress."""

    try:
        return len(value.encode("utf-8"))
    except UnicodeError:
        return None


def _nilm_session_history_identity_alias(
    kind: Any, value: Any
) -> tuple[str, str] | None:
    """Return one strict stable alias without coercing untrusted values."""

    if not isinstance(kind, str) or kind not in {"session", "on_edge"}:
        return None
    if (
        not isinstance(value, str)
        or len(value) > NILM_SESSION_HISTORY_IDENTITY_MAX_CHARS
    ):
        return None
    if not (normalized := value.strip()):
        return None
    if len(normalized) > NILM_SESSION_HISTORY_IDENTITY_MAX_CHARS:
        return None
    utf8_length = _nilm_session_history_utf8_length(normalized)
    if (
        utf8_length is None
        or utf8_length > NILM_SESSION_HISTORY_IDENTITY_MAX_UTF8_BYTES
    ):
        return None
    return kind, normalized


def _nilm_session_history_text(value: Any) -> str | None:
    """Normalize one bounded non-empty session scalar without coercion."""

    if (
        not isinstance(value, str)
        or len(value) > NILM_SESSION_HISTORY_IDENTITY_MAX_CHARS
    ):
        return None
    if not (normalized := value.strip()):
        return None
    if len(normalized) > NILM_SESSION_HISTORY_IDENTITY_MAX_CHARS:
        return None
    utf8_length = _nilm_session_history_utf8_length(normalized)
    if (
        utf8_length is None
        or utf8_length > NILM_SESSION_HISTORY_IDENTITY_MAX_UTF8_BYTES
    ):
        return None
    return normalized


def _canonical_nilm_session_history_timestamp(value: Any) -> datetime | None:
    """Return one bounded UTC timestamp suitable for session history."""

    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and (
        len(value) <= NILM_SESSION_HISTORY_TIMESTAMP_MAX_CHARS
        and (
            utf8_length := _nilm_session_history_utf8_length(value)
        ) is not None
        and utf8_length <= NILM_SESSION_HISTORY_TIMESTAMP_MAX_UTF8_BYTES
    ):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    try:
        normalized = (
            parsed.replace(tzinfo=UTC)
            if parsed.tzinfo is None
            else parsed.astimezone(UTC)
        )
        return (
            normalized
            if normalized <= _NILM_SESSION_HISTORY_TIMESTAMP_LATEST
            else None
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _nilm_session_history_number(
    value: Any,
    *,
    unit_interval: bool = False,
) -> float | None:
    """Read one finite bounded session scalar without bool or coercion."""

    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not isfinite(normalized)
        or abs(normalized) > NILM_SESSION_HISTORY_SCALAR_ABS_MAX
    ):
        return None
    if unit_interval and not 0.0 <= normalized <= 1.0:
        return None
    return normalized


def _nilm_session_history_count(value: Any) -> int | None:
    """Read one fixed-range session count without numeric coercion."""

    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if not 0 <= value <= NILM_SESSION_HISTORY_COUNT_MAX:
        return None
    return value


def _nilm_session_history_mapping_value(
    raw: Mapping[str, Any],
    key: str,
) -> Any:
    """Read a fixed known mapping member without traversing unknown keys."""

    try:
        return raw.get(key, _NILM_SESSION_HISTORY_MISSING)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        return _NILM_SESSION_HISTORY_MISSING


def _saturated_nilm_session_history_count(
    current: int,
    increment: int,
    *,
    maximum: int,
) -> int:
    """Accumulate compact ingress diagnostics without unbounded counters."""

    return min(maximum, max(current, 0) + max(increment, 0))


@dataclass(frozen=True, slots=True)
class _NilmSessionHistoryIdentityComponent:
    """One canonical bounded transitive stable-identity component."""

    aliases: tuple[tuple[str, str], ...]


def _nilm_session_history_identity_component_closure(
    alias_groups: Iterable[Iterable[tuple[str, str]]],
) -> tuple[_NilmSessionHistoryIdentityComponent, ...]:
    """Close caller-bounded alias groups in O(A alpha(A) + A log A)."""

    parents: dict[tuple[str, str], tuple[str, str]] = {}
    ranks: dict[tuple[str, str], int] = {}

    def find(alias: tuple[str, str]) -> tuple[str, str]:
        root = alias
        while parents[root] != root:
            root = parents[root]
        while parents[alias] != alias:
            parent = parents[alias]
            parents[alias] = root
            alias = parent
        return root

    def union(first: tuple[str, str], second: tuple[str, str]) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root == second_root:
            return
        first_rank = ranks[first_root]
        second_rank = ranks[second_root]
        if first_rank < second_rank or (
            first_rank == second_rank and second_root < first_root
        ):
            first_root, second_root = second_root, first_root
            first_rank, second_rank = second_rank, first_rank
        parents[second_root] = first_root
        if first_rank == second_rank:
            ranks[first_root] += 1

    for raw_group in alias_groups:
        group = tuple(dict.fromkeys(raw_group))
        if not group:
            continue
        for alias in group:
            parents.setdefault(alias, alias)
            ranks.setdefault(alias, 0)
        for alias in group[1:]:
            union(group[0], alias)

    components_by_root: dict[
        tuple[str, str], list[tuple[str, str]]
    ] = {}
    for alias in parents:
        components_by_root.setdefault(find(alias), []).append(alias)
    return tuple(
        sorted(
            (
                _NilmSessionHistoryIdentityComponent(tuple(sorted(aliases)))
                for aliases in components_by_root.values()
            ),
            key=lambda component: component.aliases,
        )
    )


def _canonical_nilm_session_history_identity_components(
    raw_components: Any,
) -> tuple[tuple[_NilmSessionHistoryIdentityComponent, ...], bool]:
    """Normalize a bounded component ledger without fabricating grouping evidence."""

    if not isinstance(raw_components, (list, tuple)) or len(raw_components) > (
        NILM_SESSION_HISTORY_IDENTITY_MAX_COMPONENTS
    ):
        return (), False
    groups: list[tuple[tuple[str, str], ...]] = []
    valid = True
    for raw_component in raw_components:
        raw_aliases = (
            raw_component.aliases
            if isinstance(raw_component, _NilmSessionHistoryIdentityComponent)
            else raw_component
        )
        if (
            not isinstance(raw_aliases, (list, tuple))
            or not raw_aliases
            or len(raw_aliases)
            > NILM_SESSION_HISTORY_IDENTITY_MAX_ALIASES_PER_COMPONENT
        ):
            valid = False
            continue
        aliases: set[tuple[str, str]] = set()
        component_valid = True
        for raw_alias in raw_aliases:
            if not isinstance(raw_alias, (list, tuple)) or len(raw_alias) != 2:
                component_valid = False
                break
            alias = _nilm_session_history_identity_alias(
                raw_alias[0], raw_alias[1]
            )
            if alias is None:
                component_valid = False
                break
            aliases.add(alias)
        if not component_valid or not aliases:
            valid = False
            continue
        groups.append(tuple(aliases))
    closed_components = _nilm_session_history_identity_component_closure(
        groups
    )
    valid = valid and all(
        len(component.aliases)
        <= NILM_SESSION_HISTORY_IDENTITY_MAX_ALIASES_PER_COMPONENT
        for component in closed_components
    )
    components = tuple(
        component
        for component in closed_components
        if len(component.aliases)
        <= NILM_SESSION_HISTORY_IDENTITY_MAX_ALIASES_PER_COMPONENT
    )
    if len(components) > NILM_SESSION_HISTORY_IDENTITY_MAX_COMPONENTS:
        return (), False
    return components, valid


def _canonical_nilm_session_history_duration_close(
    raw_close: Any,
) -> tuple[dict[str, Any] | None, bool]:
    """Project an all-or-nothing scalar duration-close record."""

    if not isinstance(raw_close, Mapping):
        return None, False
    try:
        field_count = len(raw_close)
    except (TypeError, ValueError, OverflowError):
        return None, False
    if field_count != len(_NILM_SESSION_HISTORY_DURATION_CLOSE_FIELDS):
        return None, False
    values = {
        key: _nilm_session_history_mapping_value(raw_close, key)
        for key in _NILM_SESSION_HISTORY_DURATION_CLOSE_FIELDS
    }
    if any(
        value is _NILM_SESSION_HISTORY_MISSING for value in values.values()
    ):
        return None, False

    close: dict[str, Any] = {}
    for key in ("session_id", "off_edge_id"):
        value = values[key]
        if value is None and key == "off_edge_id":
            close[key] = None
            continue
        normalized = _nilm_session_history_text(value)
        if normalized is None:
            return None, False
        close[key] = normalized

    value = values["end"]
    parsed = _canonical_nilm_session_history_timestamp(value)
    if parsed is None:
        return None, False
    close["end"] = parsed.isoformat()

    for key in ("duration_seconds", "estimated_energy_kwh", "confidence"):
        value = values[key]
        if value is None:
            close[key] = None
            continue
        normalized = _nilm_session_history_number(
            value,
            unit_interval=key == "confidence",
        )
        if normalized is None:
            return None, False
        close[key] = normalized

    value = values["ambiguous"]
    if not isinstance(value, bool):
        return None, False
    close["ambiguous"] = value

    value = values["alternate_match_count"]
    normalized = _nilm_session_history_count(value)
    if normalized is None:
        return None, False
    close["alternate_match_count"] = normalized
    return close, True


def _canonical_nilm_session_history_row(
    raw_row: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, int | bool]]:
    """Project one row to the fixed scalar NILM session schema.

    The caller visits at most 2,000 rows. This function reads a fixed bounded
    scalar schema, never iterates unknown keys or nested values, and emits scalars or
    canonical <=64-byte timestamp text only.
    """

    facts: dict[str, int | bool] = {
        "identity_aliases_complete": True,
        "invalid_alias_count": 0,
        "unknown_field_count": 0,
        "invalid_scalar_count": 0,
        "invalid_timestamp_count": 0,
        "duration_bound_close_incomplete": False,
    }
    try:
        field_count = len(raw_row)
    except (TypeError, ValueError, OverflowError):
        facts["identity_aliases_complete"] = False
        facts["invalid_scalar_count"] = 1
        return {}, facts

    known_fields = (
        *_NILM_SESSION_HISTORY_ROW_TEXT_FIELDS,
        *_NILM_SESSION_HISTORY_ROW_TIMESTAMP_FIELDS,
        *_NILM_SESSION_HISTORY_ROW_NUMBER_FIELDS,
        *_NILM_SESSION_HISTORY_ROW_COUNT_FIELDS,
        *_NILM_SESSION_HISTORY_ROW_BOOLEAN_FIELDS,
        _NILM_SESSION_HISTORY_LEGACY_ENERGY_FIELD,
        "_duration_bound_close",
    )
    values = {
        key: _nilm_session_history_mapping_value(raw_row, key)
        for key in known_fields
    }
    known_count = sum(
        value is not _NILM_SESSION_HISTORY_MISSING for value in values.values()
    )
    if field_count != known_count:
        facts["unknown_field_count"] = min(
            _NILM_SESSION_HISTORY_MAX_UNKNOWN_FIELDS,
            max(field_count - known_count, 0),
        )
        facts["identity_aliases_complete"] = False

    row: dict[str, Any] = {}
    for key, identity_kind, allows_none in (
        ("session_id", "session", False),
        ("mains_circuit_id", None, False),
        ("signature_fingerprint", None, False),
        ("on_edge_id", "on_edge", False),
        ("off_edge_id", None, True),
        ("assignment_id", None, True),
        ("energy_source", None, False),
    ):
        value = values[key]
        if value is _NILM_SESSION_HISTORY_MISSING:
            continue
        if value is None and allows_none:
            row[key] = None
            continue
        normalized = (
            _nilm_session_history_identity_alias(identity_kind, value)
            if identity_kind is not None
            else _nilm_session_history_text(value)
        )
        if normalized is None:
            facts["identity_aliases_complete"] = False
            count_key = (
                "invalid_alias_count"
                if identity_kind is not None
                else "invalid_scalar_count"
            )
            facts[count_key] = _saturated_nilm_session_history_count(
                int(facts[count_key]),
                1,
                maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
            )
            continue
        if (
            key == "energy_source"
            and normalized not in _NILM_SESSION_HISTORY_ENERGY_SOURCES
        ):
            facts["identity_aliases_complete"] = False
            facts["invalid_scalar_count"] = _saturated_nilm_session_history_count(
                int(facts["invalid_scalar_count"]),
                1,
                maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
            )
            continue
        row[key] = normalized[1] if identity_kind is not None else normalized

    invalid_closed_interval = False
    for key in _NILM_SESSION_HISTORY_ROW_TIMESTAMP_FIELDS:
        allows_none = key != "start"
        value = values[key]
        if value is _NILM_SESSION_HISTORY_MISSING:
            continue
        if value is None and allows_none:
            row[key] = None
            continue
        parsed = _canonical_nilm_session_history_timestamp(value)
        if parsed is None:
            facts["identity_aliases_complete"] = False
            facts["invalid_timestamp_count"] = _saturated_nilm_session_history_count(
                int(facts["invalid_timestamp_count"]),
                1,
                maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
            )
            invalid_closed_interval = invalid_closed_interval or key == "end"
            continue
        row[key] = parsed.isoformat()
    if invalid_closed_interval:
        # An invalid persisted close must not silently become a valid open row.
        # Dropping its interval keeps the bounded identity available only as
        # conservative rejected evidence for its owning component.
        row.pop("start", None)

    nullable_number_fields = {
        "duration_seconds",
        "known_load_confidence",
        "on_delta_w",
        "off_delta_w",
        "on_delta_var",
        "off_delta_var",
        "plateau_power_w",
        "measured_energy_kwh",
        "power_coverage",
        "partial_energy_kwh",
        "energy_estimate_confidence",
        "covered_duration_seconds",
        "longest_trace_gap_seconds",
        "known_source_coverage_min",
        "known_source_coverage_time_weighted",
    }
    legacy_energy = values[_NILM_SESSION_HISTORY_LEGACY_ENERGY_FIELD]
    if legacy_energy is not _NILM_SESSION_HISTORY_MISSING:
        legacy_energy = _nilm_session_history_number(legacy_energy)
        if legacy_energy is None:
            facts["identity_aliases_complete"] = False
            facts["invalid_scalar_count"] = _saturated_nilm_session_history_count(
                int(facts["invalid_scalar_count"]),
                1,
                maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
            )
    for key in _NILM_SESSION_HISTORY_ROW_NUMBER_FIELDS:
        value = values[key]
        if (
            key == "estimated_energy_kwh"
            and value is _NILM_SESSION_HISTORY_MISSING
            and legacy_energy is not _NILM_SESSION_HISTORY_MISSING
        ):
            value = legacy_energy
        if value is _NILM_SESSION_HISTORY_MISSING:
            continue
        if value is None and key in nullable_number_fields:
            row[key] = None
            continue
        normalized = _nilm_session_history_number(
            value,
            unit_interval=key in {
                "confidence",
                "known_load_confidence",
                "power_coverage",
                "energy_estimate_confidence",
                "known_source_coverage_min",
                "known_source_coverage_time_weighted",
            },
        )
        if normalized is None:
            facts["identity_aliases_complete"] = False
            facts["invalid_scalar_count"] = _saturated_nilm_session_history_count(
                int(facts["invalid_scalar_count"]),
                1,
                maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
            )
            continue
        row[key] = normalized

    for key in _NILM_SESSION_HISTORY_ROW_COUNT_FIELDS:
        value = values[key]
        if value is _NILM_SESSION_HISTORY_MISSING:
            continue
        normalized = _nilm_session_history_count(value)
        if normalized is None:
            facts["identity_aliases_complete"] = False
            facts["invalid_scalar_count"] = _saturated_nilm_session_history_count(
                int(facts["invalid_scalar_count"]),
                1,
                maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
            )
            continue
        row[key] = normalized

    for key in _NILM_SESSION_HISTORY_ROW_BOOLEAN_FIELDS:
        value = values[key]
        if value is _NILM_SESSION_HISTORY_MISSING:
            continue
        if value is None and key in {"pre_context_coverage", "post_context_coverage"}:
            row[key] = None
            continue
        if not isinstance(value, bool):
            facts["identity_aliases_complete"] = False
            facts["invalid_scalar_count"] = _saturated_nilm_session_history_count(
                int(facts["invalid_scalar_count"]),
                1,
                maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
            )
            continue
        row[key] = value

    row = {
        key: row[key] for key in _NILM_SESSION_HISTORY_ROW_OUTPUT_FIELDS if key in row
    }
    close = values["_duration_bound_close"]
    if close is not _NILM_SESSION_HISTORY_MISSING:
        projected_close, close_complete = (
            _canonical_nilm_session_history_duration_close(close)
        )
        if not close_complete:
            facts["identity_aliases_complete"] = False
            facts["duration_bound_close_incomplete"] = True
        elif projected_close is not None:
            row["_duration_bound_close"] = projected_close
    return row, facts


def _sanitize_nilm_session_history_ingress(
    raw_rows: Any,
    *,
    max_source_rows: int,
) -> tuple[list[dict[str, Any]], dict[str, int | bool]]:
    """Project a fixed history prefix using bounded scalar-only CPU work.

    R is capped by ``max_source_rows`` (at most 2,000 in production). Each row
    reads a fixed scalar schema and bounded timestamp values. The
    helper is synchronous and pure: it performs no I/O, await, sleep, executor,
    replay, calibration, sorting, recursive traversal, or raw nested copying.
    """

    cap = (
        min(
            max(max_source_rows, 0),
            NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT,
        )
        if isinstance(max_source_rows, int) and not isinstance(max_source_rows, bool)
        else 0
    )
    if not isinstance(raw_rows, (list, tuple)):
        return [], {
            "source_count_before_ingress": 0,
            "retained_count": 0,
            "was_truncated": raw_rows is not None,
            "identity_aliases_complete": False,
            "invalid_alias_count": 0,
            "unknown_field_count": 0,
            "invalid_scalar_count": 0,
            "invalid_timestamp_count": 0,
            "duration_bound_close_incomplete": False,
        }
    raw_source_count = len(raw_rows)
    rows: list[dict[str, Any]] = []
    identity_aliases_complete = raw_source_count <= cap
    invalid_alias_count = 0
    unknown_field_count = 0
    invalid_scalar_count = 0
    invalid_timestamp_count = 0
    duration_bound_close_incomplete = False
    for raw_row in raw_rows[:cap]:
        if not isinstance(raw_row, Mapping):
            identity_aliases_complete = False
            invalid_scalar_count = _saturated_nilm_session_history_count(
                invalid_scalar_count,
                1,
                maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
            )
            continue
        row, facts = _canonical_nilm_session_history_row(raw_row)
        rows.append(row)
        identity_aliases_complete = (
            identity_aliases_complete
            and facts["identity_aliases_complete"] is True
        )
        invalid_alias_count = _saturated_nilm_session_history_count(
            invalid_alias_count,
            int(facts["invalid_alias_count"]),
            maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
        )
        unknown_field_count = _saturated_nilm_session_history_count(
            unknown_field_count,
            int(facts["unknown_field_count"]),
            maximum=_NILM_SESSION_HISTORY_MAX_UNKNOWN_FIELDS,
        )
        invalid_scalar_count = _saturated_nilm_session_history_count(
            invalid_scalar_count,
            int(facts["invalid_scalar_count"]),
            maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
        )
        invalid_timestamp_count = _saturated_nilm_session_history_count(
            invalid_timestamp_count,
            int(facts["invalid_timestamp_count"]),
            maximum=_NILM_SESSION_HISTORY_DIAGNOSTIC_MAX,
        )
        duration_bound_close_incomplete = (
            duration_bound_close_incomplete
            or facts["duration_bound_close_incomplete"] is True
        )
    was_truncated = raw_source_count > len(rows)
    return rows, {
        # A fixed-prefix ingress cannot establish whether its unvisited tail
        # repeats a retained identity. Only copied rows are an exact bounded
        # count; the identity-completeness fact preserves that uncertainty.
        "source_count_before_ingress": len(rows),
        "retained_count": len(rows),
        "was_truncated": was_truncated,
        "identity_aliases_complete": identity_aliases_complete,
        "invalid_alias_count": invalid_alias_count,
        "unknown_field_count": unknown_field_count,
        "invalid_scalar_count": invalid_scalar_count,
        "invalid_timestamp_count": invalid_timestamp_count,
        "duration_bound_close_incomplete": duration_bound_close_incomplete,
    }


@dataclass(frozen=True, slots=True)
class _UnknownLoadComponent:
    component_id: str
    component_fingerprint: str
    on_signature: NilmSignature
    off_signature: NilmSignature | None
    pair_status: str
    pair_score: float | None
    alternate_pair_count: int = 0


@dataclass(frozen=True, slots=True)
class _UnknownLoadAllocation:
    edges_by_component: Mapping[str, tuple[NilmEdge, ...]]
    matched_on_count_by_component: Mapping[str, int]
    matched_off_count_by_component: Mapping[str, int]
    ambiguous_edge_count_by_component: Mapping[str, int]
    ambiguous_component_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class _NormalizedUnknownLoadSession:
    """Storage-safe session evidence normalized to UTC before windowing."""

    session_id: str
    signature_fingerprint: str
    start: datetime
    end: datetime
    is_open: bool
    on_edge_id: str
    identities: frozenset[str]


@dataclass(frozen=True, slots=True)
class _OwnedUnknownLoadSession:
    session: _NormalizedUnknownLoadSession
    component_id: str


_ExcludedSessionReason = Literal[
    "ambiguous",
    "malformed",
    "known_load_masked",
    "deduplicated",
]


@dataclass(frozen=True, slots=True)
class _RejectedUnknownLoadSession:
    session_id: str
    on_edge_id: str
    identities: frozenset[str]
    start: datetime | None
    end: datetime | None
    has_trustworthy_interval: bool
    reason: _ExcludedSessionReason


@dataclass(frozen=True, slots=True)
class _ExcludedUnknownLoadSession:
    component_id: str
    session_id: str
    on_edge_id: str
    start: datetime | None
    end: datetime | None
    has_trustworthy_interval: bool
    reason: _ExcludedSessionReason


@dataclass(frozen=True, slots=True)
class _SessionInventoryEvidence:
    sessions_by_component: Mapping[str, tuple[_OwnedUnknownLoadSession, ...]]
    excluded_sessions_by_component: Mapping[
        str, tuple[_ExcludedUnknownLoadSession, ...]
    ]
    ambiguous_sessions_by_component: Mapping[
        str, tuple[_ExcludedUnknownLoadSession, ...]
    ]
    observation_started_at_by_component: Mapping[str, datetime | None]
    invalid_count: int
    unowned_count: int


@dataclass(frozen=True, slots=True)
class NilmSessionHistoryCoverage:
    """Retention facts captured before bounded session-history storage."""

    configured_max_items: int
    source_count_before_retention: int
    retained_count: int
    was_truncated: bool
    dropped_count: int
    oldest_retained_at: datetime | None
    newest_retained_at: datetime | None
    retention_identity_components: tuple[
        _NilmSessionHistoryIdentityComponent, ...
    ] = ()
    retention_identity_components_complete: bool = False
    ingress_history_incomplete: bool = False


def _coverage_for_supplied_sessions(
    sessions: Iterable[Mapping[str, Any]],
    *,
    configured_max_items: int | None,
) -> NilmSessionHistoryCoverage:
    """Describe directly supplied sessions when no retention facts are available."""

    session_list = tuple(sessions)
    timestamps: list[datetime] = []
    stable_identity_groups: list[set[tuple[str, str]]] = []
    anonymous_count = 0
    for session in session_list:
        if not isinstance(session, Mapping):
            anonymous_count += 1
            continue
        aliases = {
            alias
            for alias in (
                _nilm_session_history_identity_alias(
                    "session", session.get("session_id")
                ),
                _nilm_session_history_identity_alias(
                    "on_edge", session.get("on_edge_id")
                ),
            )
            if alias is not None
        }
        if aliases:
            matching_groups = [
                group for group in stable_identity_groups if group & aliases
            ]
            if matching_groups:
                merged = set(aliases)
                for group in matching_groups:
                    merged.update(group)
                    stable_identity_groups.remove(group)
                stable_identity_groups.append(merged)
            else:
                stable_identity_groups.append(set(aliases))
        else:
            anonymous_count += 1
        for key in ("start", "end"):
            value = session.get(key)
            if value is None:
                continue
            try:
                timestamps.append(_as_utc_datetime(value))
            except (TypeError, ValueError, OverflowError):
                continue
    try:
        configured = (
            int(configured_max_items) if configured_max_items is not None else 0
        )
    except (TypeError, ValueError, OverflowError):
        configured = 0
    retained_count = len(stable_identity_groups) + anonymous_count
    return NilmSessionHistoryCoverage(
        configured_max_items=max(configured, retained_count),
        source_count_before_retention=retained_count,
        retained_count=retained_count,
        was_truncated=False,
        dropped_count=0,
        oldest_retained_at=min(timestamps, default=None),
        newest_retained_at=max(timestamps, default=None),
        retention_identity_components_complete=True,
    )


def estimate_unknown_load(signature: NilmSignature) -> dict[str, Any]:
    """Return a conservative user-facing estimate for an unknown NILM signature."""

    typical_watts = _rounded_abs(signature.median_delta_w)
    typical_var = _rounded_abs(signature.median_delta_var)
    typical_va = _rounded_abs(signature.median_delta_va)
    typical_power_factor = _typical_power_factor(typical_watts, typical_va)
    voltage_class = _voltage_class(signature.split_phase_type)
    likely_type = _likely_type(
        signature,
        typical_watts=typical_watts,
        typical_var=typical_var,
        typical_va=typical_va,
        typical_power_factor=typical_power_factor,
        voltage_class=voltage_class,
    )

    return {
        "signature_id": signature.signature_id,
        "display_name": _display_name(likely_type, voltage_class),
        "likely_type": likely_type,
        "voltage_class": voltage_class,
        "split_phase_type": signature.split_phase_type,
        "dominant_leg": signature.dominant_leg,
        "typical_watts": typical_watts,
        "typical_var": typical_var,
        "typical_va": typical_va,
        "typical_power_factor": typical_power_factor,
        "confidence": signature.confidence,
        "occurrence_count": signature.occurrence_count,
        "evidence": _evidence(
            signature,
            likely_type=likely_type,
            voltage_class=voltage_class,
            typical_watts=typical_watts,
            typical_var=typical_var,
            typical_va=typical_va,
            typical_power_factor=typical_power_factor,
        ),
    }


def build_unknown_load_inventory(
    *,
    circuit_id: str,
    signatures: Iterable[NilmSignature],
    edges: Iterable[NilmEdge],
    sessions: Iterable[Mapping[str, Any]] = (),
    now: datetime,
    time_zone: str = "UTC",
    session_history_max_items: int | None = None,
    session_history_coverage: NilmSessionHistoryCoverage | None = None,
    existing_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a consolidated inventory of recurring unknown NILM loads."""

    signature_list = list(signatures)
    edge_list = sorted(
        (_edge_with_utc_timestamp(edge) for edge in edges),
        key=lambda edge: edge.timestamp,
    )
    components = _unknown_load_components(signature_list)
    allocation = _allocate_unknown_edges(components, edge_list)
    now_utc = _as_utc_datetime(now)
    session_list = tuple(sessions)
    if session_list and session_history_coverage is None:
        session_history_coverage = _coverage_for_supplied_sessions(
            session_list,
            configured_max_items=session_history_max_items,
        )
    session_evidence = _session_inventory_evidence(
        session_list,
        components=components,
        now=now_utc,
        existing_state=existing_state or {},
    )
    windows = _runtime_windows(now_utc, time_zone)
    loads = [
        (
            _unknown_component_session_payload(
                component,
                allocation,
                session_evidence,
                windows=windows,
                now=now_utc,
                existing_state=existing_state or {},
                session_history_coverage=session_history_coverage,
            )
            if session_list
            else _unknown_component_payload(
                component,
                allocation,
                now=now_utc,
                existing_state=existing_state or {},
            )
        )
        for component in components
    ]
    loads.sort(key=lambda load: str(load["component_id"]))
    active_count = sum(1 for load in loads if load["running_state"] == "probably_on")
    ambiguous_count = sum(
        1 for load in loads if load["separation_status"] == "ambiguous"
    )

    inventory = {
        "circuit_id": circuit_id,
        "schema_version": UNKNOWN_LOAD_INVENTORY_SCHEMA_VERSION,
        "unknown_load_count": len(loads),
        "active_unknown_load_count": active_count,
        "ambiguous_unknown_load_count": ambiguous_count,
        "simultaneous_unknown_event_count": _simultaneous_unknown_event_count(
            edge_list
        ),
        "unknown_estimated_energy_today_kwh": _sum_loads(
            loads,
            "estimated_energy_today_kwh",
        ),
        "unknown_estimated_energy_7_days_kwh": _sum_loads(
            loads,
            "estimated_energy_7_days_kwh",
        ),
        "unknown_estimated_energy_30_days_kwh": _sum_loads(
            loads,
            "estimated_energy_30_days_kwh",
        ),
        "largest_unknown_load": _largest_load(loads, "typical_watts"),
        "highest_unknown_energy_load": _largest_load(
            loads,
            "estimated_energy_today_kwh",
        ),
        "unknown_loads": loads,
    }
    if session_list:
        inventory.update(
            {
                "observation_started_at": _observation_started_at(
                    min(
                        (
                            value
                            for value in (
                                session_evidence.observation_started_at_by_component.values()
                            )
                            if value is not None
                        ),
                        default=None,
                    ),
                    existing_state or {},
                ),
                "runtime_window_definition": _runtime_window_definition(),
                "estimate_status": _worst_estimate_status(
                    load.get("estimate_status", "complete") for load in loads
                ),
                "session_history_diagnostics": {
                    "invalid_count": session_evidence.invalid_count,
                    "unowned_count": session_evidence.unowned_count,
                },
            }
        )
        if session_history_coverage is not None:
            inventory["session_history_coverage"] = _coverage_to_payload(
                session_history_coverage
            )
            inventory["estimate_provenance"] = "retained_session_history"
    else:
        observed = _edge_observation_started_at(loads)
        for load in loads:
            _add_edge_window_metadata(load, windows, observed, existing_state or {})
        inventory.update(
            {
                "observation_started_at": _observation_started_at(
                    observed, existing_state or {}
                ),
                "runtime_window_definition": _runtime_window_definition(),
                "estimate_status": _worst_estimate_status(
                    load.get("estimate_status", "partial_history") for load in loads
                ),
                "estimate_provenance": "edge_only",
            }
        )
    return inventory


def unknown_load_inventory_needs_rebuild(
    existing_state: Mapping[str, Any] | None,
) -> bool:
    """Return whether a persisted inventory predates component ownership."""

    if not isinstance(existing_state, Mapping):
        return True
    try:
        schema_version = int(existing_state.get("schema_version", 0))
    except (TypeError, ValueError):
        return True
    if schema_version < UNKNOWN_LOAD_INVENTORY_SCHEMA_VERSION:
        return True
    loads = existing_state.get("unknown_loads")
    if not isinstance(loads, list):
        return True
    if not isinstance(existing_state.get("runtime_window_definition"), Mapping):
        return True
    provenance = existing_state.get("estimate_provenance")
    if provenance not in {
        "retained_session_history",
        "edge_only",
        "legacy_unverified",
    }:
        return True
    if provenance == "retained_session_history":
        coverage_payload = existing_state.get("session_history_coverage")
        if not isinstance(coverage_payload, Mapping) or not isinstance(
            coverage_payload.get("_retention_identity_components_complete"), bool
        ):
            return True
    if str(existing_state.get("estimate_status") or "") not in {
        "complete",
        "partial_history",
        "legacy_unverified",
        "ambiguous",
    }:
        return True

    component_ids: set[str] = set()
    for load in loads:
        if not isinstance(load, Mapping):
            return True
        if str(load.get("estimate_status") or "") not in {
            "complete",
            "partial_history",
            "legacy_unverified",
            "ambiguous",
        }:
            return True
        windows = load.get("runtime_windows")
        if not isinstance(windows, Mapping) or not all(
            isinstance(windows.get(name), Mapping)
            and {
                "coverage_start",
                "coverage_end",
                "coverage_days",
                "estimate_status",
                "included_session_count",
                "excluded_session_count",
            }
            <= windows[name].keys()
            for name in ("today", "7_days", "30_days")
        ):
            return True
        if load.get(LEGACY_IDENTITY_UNRESOLVED_KEY) is True:
            continue
        if _stored_signature_direction(load) == "off":
            return True
        component_id = str(load.get("component_id") or "").strip()
        if not component_id or component_id in component_ids:
            return True
        component_ids.add(component_id)
        if not all(
            str(load.get(key) or "").strip()
            for key in (
                "component_fingerprint",
                "on_signature_id",
                "on_signature_fingerprint",
            )
        ):
            return True
    return False


def migrate_unknown_load_inventory(
    *,
    circuit_id: str,
    existing_state: Mapping[str, Any],
    signature_payloads: Iterable[Mapping[str, Any]],
    sessions: Iterable[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    time_zone: str = "UTC",
    session_history_max_items: int | None = None,
    session_history_coverage: NilmSessionHistoryCoverage | None = None,
) -> dict[str, Any]:
    """Upgrade a stale inventory without discarding rows that lack edge evidence."""

    signatures = [
        signature
        for payload in signature_payloads
        if (signature := _signature_from_payload(payload)) is not None
    ]
    components = _unknown_load_components(signatures)
    session_list = tuple(sessions) if sessions is not None else ()
    if session_list and now is not None:
        rebuilt = build_unknown_load_inventory(
            circuit_id=circuit_id,
            signatures=signatures,
            edges=(),
            sessions=session_list,
            now=now,
            time_zone=time_zone,
            session_history_max_items=session_history_max_items,
            session_history_coverage=session_history_coverage,
            existing_state=existing_state,
        )
        existing_loads = [
            dict(load)
            for load in existing_state.get("unknown_loads", ())
            if isinstance(load, Mapping)
        ]
        covered_indexes = {
            index
            for component in components
            for index, load in enumerate(existing_loads)
            if _load_identifies_component(load, component)
            or _legacy_load_matches_on_signature(load, component.on_signature)
            or (
                component.off_signature is not None
                and _load_is_off_duplicate(load, component.off_signature)
            )
        }
        retained = [
            _migrated_unclassified_row(load)
            for index, load in enumerate(existing_loads)
            if index not in covered_indexes
        ]
        if retained:
            legacy = _legacy_unverified_inventory(
                circuit_id, retained, existing_state
            )
            loads = [*rebuilt["unknown_loads"], *legacy["unknown_loads"]]
            loads.sort(
                key=lambda load: (
                    str(load.get("component_id") or load.get("signature_id") or ""),
                    str(load.get("signature_id") or ""),
                )
            )
            rebuilt.update(_inventory_aggregate(circuit_id, loads))
            rebuilt["estimate_status"] = _worst_estimate_status(
                str(load.get("estimate_status") or "legacy_unverified")
                for load in loads
            )
            legacy_observed = legacy.get("observation_started_at")
            if legacy_observed:
                rebuilt["observation_started_at"] = _observation_started_at(
                    _as_utc_datetime(legacy_observed), rebuilt
                )
        elif not rebuilt["unknown_loads"]:
            rebuilt["estimate_status"] = "partial_history"
        return rebuilt
    existing_loads = [
        dict(load)
        for load in existing_state.get("unknown_loads", ())
        if isinstance(load, Mapping)
    ]
    retained: list[dict[str, Any]] = []
    used_indexes: set[int] = set()

    for component in components:
        candidates = [
            index
            for index, load in enumerate(existing_loads)
            if _load_identifies_component(load, component)
        ]
        if not candidates:
            candidates = [
                index
                for index, load in enumerate(existing_loads)
                if _legacy_load_matches_on_signature(load, component.on_signature)
            ]
        if len(candidates) != 1:
            continue
        index = candidates[0]
        if index in used_indexes:
            continue
        used_indexes.add(index)
        retained.append(_migrated_component_row(existing_loads[index], component))

        if component.off_signature is not None:
            used_indexes.update(
                index
                for index, load in enumerate(existing_loads)
                if index not in used_indexes
                and _load_is_off_duplicate(load, component.off_signature)
            )

    retained_component_ids = {
        str(load.get("component_id") or "").strip() for load in retained
    }
    for index, load in enumerate(existing_loads):
        if index in used_indexes:
            continue
        component_id = str(load.get("component_id") or "").strip()
        if component_id and component_id in retained_component_ids:
            continue
        retained.append(_migrated_unclassified_row(load))
        if component_id:
            retained_component_ids.add(component_id)

    retained.sort(
        key=lambda load: (
            str(load.get("component_id") or load.get("signature_id") or ""),
            str(load.get("signature_id") or ""),
        )
    )
    return _legacy_unverified_inventory(circuit_id, retained, existing_state)


def _inventory_aggregate(
    circuit_id: str,
    loads: list[dict[str, Any]],
) -> dict[str, Any]:
    active_count = sum(
        1
        for load in loads
        if load.get("running_state") == "probably_on"
        and load.get("separation_status") != "ambiguous"
    )
    ambiguous_count = sum(
        1 for load in loads if load.get("separation_status") == "ambiguous"
    )
    return {
        "circuit_id": circuit_id,
        "schema_version": UNKNOWN_LOAD_INVENTORY_SCHEMA_VERSION,
        "unknown_load_count": len(loads),
        "active_unknown_load_count": active_count,
        "ambiguous_unknown_load_count": ambiguous_count,
        "simultaneous_unknown_event_count": 0,
        "unknown_estimated_energy_today_kwh": _sum_loads(
            loads, "estimated_energy_today_kwh"
        ),
        "unknown_estimated_energy_7_days_kwh": _sum_loads(
            loads, "estimated_energy_7_days_kwh"
        ),
        "unknown_estimated_energy_30_days_kwh": _sum_loads(
            loads, "estimated_energy_30_days_kwh"
        ),
        "largest_unknown_load": _largest_load(loads, "typical_watts"),
        "highest_unknown_energy_load": _largest_load(
            loads, "estimated_energy_today_kwh"
        ),
        "unknown_loads": loads,
    }


def _legacy_unverified_inventory(
    circuit_id: str,
    loads: list[dict[str, Any]],
    existing_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Preserve prior values when history was not retained for recomputation."""

    observation_started = _observation_started_at(
        _edge_observation_started_at(loads), existing_state
    )
    for load in loads:
        status = "legacy_unverified"
        load["estimate_status"] = status
        load["estimate_status_by_window"] = {
            name: status for name in ("today", "7_days", "30_days")
        }
        load["observation_started_at"] = observation_started
        load["runtime_window_definition"] = _runtime_window_definition()
        load["runtime_windows"] = {
            name: {
                "coverage_start": None,
                "coverage_end": None,
                "coverage_days": 0.0,
                "nominal_days": days,
                "estimate_status": status,
                "included_session_count": 0,
                "excluded_session_count": 0,
            }
            for name, days in (("today", 0.0), ("7_days", 7.0), ("30_days", 30.0))
        }
    inventory = _inventory_aggregate(circuit_id, loads)
    inventory.update(
        {
            "observation_started_at": observation_started,
            "runtime_window_definition": _runtime_window_definition(),
            "estimate_status": "legacy_unverified",
            "estimate_provenance": "legacy_unverified",
        }
    )
    return inventory


def _signature_from_payload(payload: Mapping[str, Any]) -> NilmSignature | None:
    signature_id = str(payload.get("signature_id") or "").strip()
    try:
        watts = float(payload.get("median_delta_w"))
    except (TypeError, ValueError):
        return None
    if not signature_id:
        return None
    return NilmSignature(
        signature_id=signature_id,
        median_delta_w=watts,
        median_delta_var=_optional_float(payload.get("median_delta_var")),
        median_delta_va=_optional_float(payload.get("median_delta_va")),
        median_delta_pf=_optional_float(payload.get("median_delta_pf")),
        occurrence_count=_nonnegative_int(payload.get("occurrence_count")),
        confidence=_finite_or_zero(payload.get("confidence")),
        dominant_leg=str(payload.get("dominant_leg") or "unknown"),
        split_phase_type=str(payload.get("split_phase_type") or "unknown"),
        median_leg_a_delta_w=_optional_float(payload.get("median_leg_a_delta_w")),
        median_leg_b_delta_w=_optional_float(payload.get("median_leg_b_delta_w")),
        leg_balance_ratio=_optional_float(payload.get("leg_balance_ratio")),
    )


def _load_identifies_component(
    load: Mapping[str, Any],
    component: _UnknownLoadComponent,
) -> bool:
    return any(
        str(load.get(key) or "").strip() == value
        for key, value in (
            ("component_id", component.component_id),
            ("signature_id", component.on_signature.signature_id),
            ("on_signature_id", component.on_signature.signature_id),
            ("component_fingerprint", component.component_fingerprint),
            ("on_signature_fingerprint", component.component_fingerprint),
            ("signature_fingerprint", component.component_fingerprint),
            ("fingerprint", component.component_fingerprint),
        )
    )


def _load_is_off_duplicate(
    load: Mapping[str, Any],
    off_signature: NilmSignature,
) -> bool:
    return str(load.get("signature_id") or "").strip() == off_signature.signature_id


def _migrated_component_row(
    load: Mapping[str, Any],
    component: _UnknownLoadComponent,
) -> dict[str, Any]:
    migrated = dict(load)
    migrated.pop(LEGACY_IDENTITY_UNRESOLVED_KEY, None)
    migrated.update(
        {
            "signature_id": component.on_signature.signature_id,
            "component_id": component.component_id,
            "component_fingerprint": component.component_fingerprint,
            "on_signature_id": component.on_signature.signature_id,
            "on_signature_fingerprint": nilm_signature_fingerprint(
                component.on_signature
            ),
            "off_signature_id": (
                component.off_signature.signature_id
                if component.off_signature is not None
                else None
            ),
            "off_signature_fingerprint": (
                nilm_signature_fingerprint(component.off_signature)
                if component.off_signature is not None
                else None
            ),
            "signature_pair_status": component.pair_status,
            "signature_pair_score": (
                round(component.pair_score, 3)
                if component.pair_score is not None
                else None
            ),
            "alternate_signature_pair_count": component.alternate_pair_count,
            "matched_on_edge_count": int(load.get("matched_on_edge_count") or 0),
            "matched_off_edge_count": int(load.get("matched_off_edge_count") or 0),
            "ambiguous_edge_count": int(load.get("ambiguous_edge_count") or 0),
        }
    )
    return migrated


def _migrated_unclassified_row(load: Mapping[str, Any]) -> dict[str, Any]:
    """Mark an opaque legacy row as retained so migration does not repeat."""

    migrated = dict(load)
    migrated[LEGACY_IDENTITY_UNRESOLVED_KEY] = True
    return migrated


def _stored_signature_direction(value: Mapping[str, Any]) -> str:
    signature_id = str(value.get("signature_id") or "").strip()
    try:
        watts = float(value.get("median_delta_w"))
    except (TypeError, ValueError):
        return "off" if nilm_signature_is_off_direction(signature_id) else "unknown"
    return _unknown_signature_direction(
        NilmSignature(signature_id=signature_id, median_delta_w=watts)
    )


def _optional_float(value: Any) -> float | None:
    try:
        number = None if value is None else float(value)
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _finite_or_zero(value: Any) -> float:
    number = _optional_float(value)
    return number if number is not None else 0.0


def _nonnegative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _unknown_signature_direction(signature: NilmSignature) -> str:
    """Classify a raw signature without trusting malformed identifier metadata."""

    watts = float(signature.median_delta_w)
    signature_id = signature.signature_id
    fingerprint = nilm_signature_fingerprint(signature)
    is_off_identifier = nilm_signature_is_off_direction(
        signature_id
    ) or nilm_signature_is_off_direction(fingerprint)
    if watts < 0.0:
        return "off"
    if watts > 0.0 and is_off_identifier:
        return "invalid"
    if watts > 0.0 and nilm_signature_is_assignable(signature_id):
        return "on"
    return "unknown"


def _unknown_load_components(
    signatures: Iterable[NilmSignature],
) -> tuple[_UnknownLoadComponent, ...]:
    on_signatures = sorted(
        (
            signature
            for signature in signatures
            if _unknown_signature_direction(signature) == "on"
        ),
        key=lambda signature: signature.signature_id,
    )
    off_signatures = sorted(
        (
            signature
            for signature in signatures
            if _unknown_signature_direction(signature) == "off"
        ),
        key=lambda signature: signature.signature_id,
    )
    candidates = [
        (on_signature, off_signature, score)
        for on_signature in on_signatures
        for off_signature in off_signatures
        if (score := _signature_pair_score(on_signature, off_signature))
        is not None
        and score >= MIN_SIGNATURE_PAIR_SCORE
    ]
    candidates.sort(
        key=lambda candidate: (
            -candidate[2],
            candidate[0].signature_id,
            candidate[1].signature_id,
        )
    )

    ambiguous_counts = _pair_ambiguity_counts(candidates)
    ambiguous_on_ids = set(ambiguous_counts)
    paired_by_on: dict[str, tuple[NilmSignature, float]] = {}
    used_off_ids: set[str] = set()
    for on_signature, off_signature, score in candidates:
        if (
            on_signature.signature_id in ambiguous_on_ids
            or on_signature.signature_id in paired_by_on
            or off_signature.signature_id in used_off_ids
        ):
            continue
        paired_by_on[on_signature.signature_id] = (off_signature, score)
        used_off_ids.add(off_signature.signature_id)

    return tuple(
        _UnknownLoadComponent(
            component_id=on_signature.signature_id,
            component_fingerprint=nilm_signature_fingerprint(on_signature),
            on_signature=on_signature,
            off_signature=(
                paired_by_on[on_signature.signature_id][0]
                if on_signature.signature_id in paired_by_on
                else None
            ),
            pair_status=(
                "ambiguous"
                if on_signature.signature_id in ambiguous_on_ids
                else "paired"
                if on_signature.signature_id in paired_by_on
                else "on_only"
            ),
            pair_score=(
                paired_by_on[on_signature.signature_id][1]
                if on_signature.signature_id in paired_by_on
                else None
            ),
            alternate_pair_count=ambiguous_counts.get(on_signature.signature_id, 0),
        )
        for on_signature in on_signatures
    )


def _pair_ambiguity_counts(
    candidates: list[tuple[NilmSignature, NilmSignature, float]],
) -> dict[str, int]:
    by_on: dict[str, list[tuple[NilmSignature, NilmSignature, float]]] = {}
    by_off: dict[str, list[tuple[NilmSignature, NilmSignature, float]]] = {}
    for candidate in candidates:
        by_on.setdefault(candidate[0].signature_id, []).append(candidate)
        by_off.setdefault(candidate[1].signature_id, []).append(candidate)

    counts: dict[str, int] = {}
    for group in (*by_on.values(), *by_off.values()):
        if len(group) < 2:
            continue
        best_score = max(candidate[2] for candidate in group)
        close = [
            candidate
            for candidate in group
            if best_score - candidate[2] <= SIGNATURE_PAIR_AMBIGUITY_MARGIN
        ]
        if len(close) < 2:
            continue
        for on_signature, _off_signature, _score in close:
            counts[on_signature.signature_id] = max(
                counts.get(on_signature.signature_id, 0),
                len(close) - 1,
            )
    return counts


def _signature_pair_score(
    on_signature: NilmSignature,
    off_signature: NilmSignature,
) -> float | None:
    if (
        _unknown_signature_direction(on_signature) != "on"
        or _unknown_signature_direction(off_signature) != "off"
    ):
        return None
    return _signature_electrical_score(on_signature, off_signature)


def _allocate_unknown_edges(
    components: Iterable[_UnknownLoadComponent],
    edges: Iterable[NilmEdge],
) -> _UnknownLoadAllocation:
    component_list = tuple(components)
    allocated: dict[str, list[NilmEdge]] = {
        component.component_id: [] for component in component_list
    }
    matched_on_counts = {component.component_id: 0 for component in component_list}
    matched_off_counts = {component.component_id: 0 for component in component_list}
    ambiguous_counts = {component.component_id: 0 for component in component_list}
    ambiguous_ids = {
        component.component_id
        for component in component_list
        if component.pair_status == "ambiguous"
    }
    edge_list = list(edges)
    simultaneous_timestamps = _simultaneous_timestamps(edge_list)

    for _index, edge in sorted(
        enumerate(edge_list),
        key=lambda item: (item[1].timestamp, item[0]),
    ):
        if edge.timestamp in simultaneous_timestamps:
            simultaneous_candidates = [
                component
                for component in component_list
                if component.component_id not in ambiguous_ids
                and _component_simultaneous_match(component, edge)
            ]
            for component in simultaneous_candidates:
                ambiguous_counts[component.component_id] += 1
                ambiguous_ids.add(component.component_id)
            continue
        candidates = [
            (component, score)
            for component in component_list
            if component.component_id not in ambiguous_ids
            and (score := _component_edge_score(component, edge)) is not None
        ]
        if not candidates:
            continue
        candidates.sort(
            key=lambda candidate: (-candidate[1], candidate[0].component_id)
        )

        winner, winner_score = candidates[0]
        close = [
            component
            for component, score in candidates
            if winner_score - score <= EDGE_COMPONENT_AMBIGUITY_MARGIN
        ]
        if len(close) > 1:
            for component in close:
                ambiguous_counts[component.component_id] += 1
                ambiguous_ids.add(component.component_id)
            continue

        allocated[winner.component_id].append(edge)
        if edge.direction == "on":
            matched_on_counts[winner.component_id] += 1
        else:
            matched_off_counts[winner.component_id] += 1

    return _UnknownLoadAllocation(
        edges_by_component={
            component_id: tuple(component_edges)
            for component_id, component_edges in allocated.items()
        },
        matched_on_count_by_component=matched_on_counts,
        matched_off_count_by_component=matched_off_counts,
        ambiguous_edge_count_by_component=ambiguous_counts,
        ambiguous_component_ids=frozenset(ambiguous_ids),
    )


def _component_edge_score(
    component: _UnknownLoadComponent,
    edge: NilmEdge,
) -> float | None:
    prototype = _component_edge_prototype(component, edge)
    return _signature_edge_score(prototype, edge) if prototype is not None else None


def _component_simultaneous_match(
    component: _UnknownLoadComponent,
    edge: NilmEdge,
) -> bool:
    prototype = _component_edge_prototype(component, edge)
    if prototype is None:
        return False
    topology_matches = (
        prototype.split_phase_type == "unknown"
        or edge.split_phase_type == "unknown"
        or prototype.split_phase_type == edge.split_phase_type
    )
    return topology_matches and _within_tolerance(
        abs(edge.delta_w),
        abs(float(prototype.median_delta_w)),
        0.2,
        50.0,
    )


def _component_edge_prototype(
    component: _UnknownLoadComponent,
    edge: NilmEdge,
) -> NilmSignature | None:
    direction = str(edge.direction or "").casefold()
    if direction == "on" and edge.delta_w > 0.0:
        return component.on_signature
    if direction != "off" or edge.delta_w >= 0.0:
        return None
    if component.off_signature is not None:
        return component.off_signature
    return component.on_signature if component.pair_status == "on_only" else None


def _signature_edge_score(signature: NilmSignature, edge: NilmEdge) -> float | None:
    reference = NilmSignature(
        signature_id=signature.signature_id,
        median_delta_w=edge.delta_w,
        median_delta_var=edge.delta_var,
        median_delta_va=edge.delta_va,
        median_delta_pf=edge.delta_pf,
        dominant_leg=edge.dominant_leg,
        split_phase_type=edge.split_phase_type,
    )
    return _signature_electrical_score(signature, reference)


def _signature_electrical_score(
    left: NilmSignature,
    right: NilmSignature,
) -> float | None:
    left_watts = abs(float(left.median_delta_w))
    right_watts = abs(float(right.median_delta_w))
    if not _within_tolerance(right_watts, left_watts, 0.2, 50.0):
        return None
    scores = [_tolerance_score(right_watts, left_watts, 0.2, 50.0)]
    for left_value, right_value, ratio, floor in (
        (left.median_delta_var, right.median_delta_var, 0.35, 75.0),
    ):
        if left_value is None or right_value is None:
            continue
        if not _within_tolerance(abs(right_value), abs(left_value), ratio, floor):
            return None
        scores.append(
            _tolerance_score(abs(right_value), abs(left_value), ratio, floor)
        )
    for left_value, right_value, ratio, floor in (
        (left.median_delta_va, right.median_delta_va, 0.35, 75.0),
        (left.median_delta_pf, right.median_delta_pf, 0.5, 0.10),
    ):
        if left_value is None or right_value is None:
            continue
        if _within_tolerance(abs(right_value), abs(left_value), ratio, floor):
            scores.append(
                _tolerance_score(abs(right_value), abs(left_value), ratio, floor)
            )
    for left_value, right_value in (
        (left.split_phase_type, right.split_phase_type),
        (left.dominant_leg, right.dominant_leg),
    ):
        if left_value == "unknown" or right_value == "unknown":
            continue
        if left_value != right_value:
            return None
        scores.append(1.0)
    return round(sum(scores) / len(scores), 6)


def _tolerance_score(
    value: float,
    reference: float,
    ratio: float,
    floor: float,
) -> float:
    tolerance = max(abs(reference) * ratio, floor)
    return max(0.0, 1.0 - (abs(value - reference) / tolerance))


def _as_utc_datetime(value: datetime | str | Any) -> datetime:
    """Parse storage timestamps, treating legacy naive values as UTC."""

    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("timestamp is not a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _edge_with_utc_timestamp(edge: NilmEdge) -> NilmEdge:
    """Apply the legacy UTC convention before edge timestamps reach runtime math."""

    timestamp = _as_utc_datetime(edge.timestamp)
    return replace(edge, timestamp=timestamp) if timestamp != edge.timestamp else edge


def _runtime_windows(
    now: datetime,
    time_zone: str,
) -> dict[str, tuple[datetime, datetime, float]]:
    """Build local-midnight and elapsed-time windows in UTC."""

    try:
        local_zone = ZoneInfo(time_zone)
    except (TypeError, ZoneInfoNotFoundError):
        local_zone = UTC
    local_now = now.astimezone(local_zone)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = local_midnight.astimezone(UTC)
    return {
        "today": (today_start, now, (now - today_start).total_seconds() / 86_400),
        "7_days": (now - timedelta(hours=168), now, 7.0),
        "30_days": (now - timedelta(hours=720), now, 30.0),
    }


def _runtime_window_definition() -> dict[str, str]:
    return {
        "today": "configured_local_midnight_to_now",
        "7_days": "trailing_168_elapsed_hours_to_now",
        "30_days": "trailing_720_elapsed_hours_to_now",
    }


def _session_identities(raw: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        str(raw.get(key) or "").strip()
        for key in (
            "component_id",
            "component_fingerprint",
            "signature_id",
            "signature_fingerprint",
            "on_signature_id",
            "on_signature_fingerprint",
        )
        if str(raw.get(key) or "").strip()
    )


def _session_evidence_interval(
    raw: Mapping[str, Any], now: datetime
) -> tuple[datetime | None, datetime | None, bool]:
    """Parse an interval without fabricating an end for rejected open evidence."""

    start: datetime | None = None
    end: datetime | None = None
    try:
        start = _as_utc_datetime(raw.get("start"))
    except (TypeError, ValueError, OverflowError):
        pass
    end_value = raw.get("end")
    if end_value is not None:
        try:
            end = _as_utc_datetime(end_value)
        except (TypeError, ValueError, OverflowError):
            pass
    trustworthy = (
        start is not None
        and start <= now
        and (end_value is None or (end is not None and end >= start))
    )
    return start, end, trustworthy


def _normalize_unknown_load_sessions(
    sessions: Iterable[Mapping[str, Any]], now: datetime
) -> tuple[
    tuple[_NormalizedUnknownLoadSession, ...],
    tuple[_RejectedUnknownLoadSession, ...],
]:
    """Validate persisted sessions without allowing malformed storage to raise."""

    normalized: list[_NormalizedUnknownLoadSession] = []
    rejected: list[_RejectedUnknownLoadSession] = []
    for raw in sessions:
        if not isinstance(raw, Mapping):
            rejected.append(
                _RejectedUnknownLoadSession(
                    session_id="",
                    on_edge_id="",
                    identities=frozenset(),
                    start=None,
                    end=None,
                    has_trustworthy_interval=False,
                    reason="malformed",
                )
            )
            continue
        session_alias = _nilm_session_history_identity_alias(
            "session", raw.get("session_id")
        )
        on_edge_alias = _nilm_session_history_identity_alias(
            "on_edge", raw.get("on_edge_id")
        )
        session_id = session_alias[1] if session_alias is not None else ""
        on_edge_id = on_edge_alias[1] if on_edge_alias is not None else ""
        identities = _session_identities(raw)
        start, evidence_end, has_trustworthy_interval = _session_evidence_interval(
            raw, now
        )
        reason: _ExcludedSessionReason | None = None
        if bool(raw.get("ambiguous")):
            reason = "ambiguous"
        elif bool(raw.get("known_load_masked")):
            reason = "known_load_masked"
        try:
            fingerprint = str(raw.get("signature_fingerprint") or "").strip()
            if reason is not None or not session_id or not fingerprint:
                raise ValueError("missing session identity")
            if not has_trustworthy_interval or start is None:
                raise ValueError("invalid session interval")
            end_value = raw.get("end")
            is_open = end_value is None
            end = now if is_open else evidence_end
            if end is None:
                raise ValueError("invalid session interval")
            normalized.append(
                _NormalizedUnknownLoadSession(
                    session_id=session_id,
                    signature_fingerprint=fingerprint,
                    start=start,
                    end=end,
                    is_open=is_open,
                    on_edge_id=on_edge_id,
                    identities=identities,
                )
            )
        except (TypeError, ValueError, OverflowError):
            rejected.append(
                _RejectedUnknownLoadSession(
                    session_id=session_id,
                    on_edge_id=on_edge_id,
                    identities=identities,
                    start=start,
                    end=evidence_end,
                    has_trustworthy_interval=has_trustworthy_interval,
                    reason=reason or "malformed",
                )
            )
    return tuple(normalized), tuple(rejected)


def _session_owner_candidates(
    session_identities: frozenset[str],
    components: Iterable[_UnknownLoadComponent],
    existing_state: Mapping[str, Any],
) -> tuple[str, ...]:
    """Resolve only explicit component/signature identities; never by watts."""

    candidates: list[str] = []
    for component in components:
        component_identities = {
            component.component_id,
            component.component_fingerprint,
            component.on_signature.signature_id,
            nilm_signature_fingerprint(component.on_signature),
            nilm_signature_fingerprint_v1(component.on_signature),
        }
        if session_identities & component_identities:
            candidates.append(component.component_id)
            continue
        loads = existing_state.get("unknown_loads")
        if not isinstance(loads, list):
            continue
        for load in loads:
            if not isinstance(load, Mapping) or not _load_identifies_component(
                load, component
            ):
                continue
            legacy_identities = {
                str(load.get(key) or "").strip()
                for key in (
                    "component_id",
                    "component_fingerprint",
                    "signature_id",
                    "on_signature_id",
                    "on_signature_fingerprint",
                    "signature_fingerprint",
                    "fingerprint",
                )
            }
            if session_identities & (legacy_identities - {""}):
                candidates.append(component.component_id)
                break
    return tuple(sorted(set(candidates)))


def _deduplicate_owned_sessions(
    sessions: Iterable[_OwnedUnknownLoadSession],
) -> tuple[
    tuple[_OwnedUnknownLoadSession, ...],
    tuple[_ExcludedUnknownLoadSession, ...],
]:
    """Resolve transitive stable-identity components before interval deduplication."""

    items = tuple(sessions)
    parents = list(range(len(items)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[max(left_root, right_root)] = min(left_root, right_root)

    alias_owner: dict[tuple[str, str], int] = {}
    for index, item in enumerate(items):
        aliases = [("session", item.session.session_id)]
        if item.session.on_edge_id:
            aliases.append(("on_edge", item.session.on_edge_id))
        for alias in aliases:
            owner = alias_owner.setdefault(alias, index)
            union(index, owner)

    identity_components: dict[int, list[_OwnedUnknownLoadSession]] = {}
    for index, item in enumerate(items):
        identity_components.setdefault(find(index), []).append(item)

    def sort_key(item: _OwnedUnknownLoadSession) -> tuple[Any, ...]:
        return (
            item.component_id,
            item.session.session_id,
            item.session.on_edge_id,
            item.session.start,
            item.session.end,
            item.session.is_open,
            item.session.signature_fingerprint,
        )

    retained: list[_OwnedUnknownLoadSession] = []
    excluded: list[_ExcludedUnknownLoadSession] = []
    groups = sorted(
        identity_components.values(),
        key=lambda group: min(sort_key(item) for item in group),
    )
    for group in groups:
        components = {item.component_id for item in group}
        intervals = {
            (
                item.session.start,
                None if item.session.is_open else item.session.end,
            )
            for item in group
        }
        if len(components) != 1 or len(intervals) != 1:
            trustworthy = len(intervals) == 1
            concrete_ends = [
                item.session.end for item in group if not item.session.is_open
            ]
            for component_id in sorted(components):
                excluded.append(
                    _ExcludedUnknownLoadSession(
                        component_id=component_id,
                        session_id=min(item.session.session_id for item in group),
                        on_edge_id=min(item.session.on_edge_id for item in group),
                        start=min(item.session.start for item in group),
                        end=(
                            next(iter(intervals))[1]
                            if trustworthy
                            else (max(concrete_ends) if concrete_ends else None)
                        ),
                        has_trustworthy_interval=trustworthy,
                        reason="deduplicated",
                    )
                )
            continue
        closed = sorted(
            (item for item in group if not item.session.is_open),
            key=sort_key,
        )
        retained.append(closed[0] if closed else min(group, key=sort_key))

    interval_groups: dict[
        tuple[str, datetime, datetime], list[_OwnedUnknownLoadSession]
    ] = {}
    for item in retained:
        interval_groups.setdefault(
            (item.component_id, item.session.start, item.session.end), []
        ).append(item)
    retained = []
    for key in sorted(interval_groups):
        group = interval_groups[key]
        closed = sorted(
            (item for item in group if not item.session.is_open),
            key=sort_key,
        )
        retained.append(closed[0] if closed else min(group, key=sort_key))
    return tuple(retained), tuple(excluded)


def _excluded_session(
    component_id: str,
    item: _RejectedUnknownLoadSession | _NormalizedUnknownLoadSession,
    *,
    reason: _ExcludedSessionReason,
) -> _ExcludedUnknownLoadSession:
    if isinstance(item, _NormalizedUnknownLoadSession):
        start = item.start
        end = None if item.is_open else item.end
        trustworthy = True
    else:
        start = item.start
        end = item.end
        trustworthy = item.has_trustworthy_interval
    return _ExcludedUnknownLoadSession(
        component_id=component_id,
        session_id=item.session_id,
        on_edge_id=item.on_edge_id,
        start=start,
        end=end,
        has_trustworthy_interval=trustworthy,
        reason=reason,
    )


def _excluded_session_identity(
    item: _ExcludedUnknownLoadSession,
) -> tuple[Any, ...]:
    if item.session_id:
        return ("session", item.component_id, item.session_id)
    if item.on_edge_id:
        return ("on_edge", item.component_id, item.on_edge_id)
    return (
        "interval",
        item.component_id,
        item.start,
        item.end,
        item.reason,
    )


def _rejected_session_identity(
    item: _RejectedUnknownLoadSession,
) -> tuple[Any, ...]:
    if item.session_id:
        return ("session", item.session_id)
    if item.on_edge_id:
        return ("on_edge", item.on_edge_id)
    return (
        "interval",
        tuple(sorted(item.identities)),
        item.start,
        item.end,
        item.reason,
    )


def _deduplicate_rejected_sessions(
    sessions: Iterable[_RejectedUnknownLoadSession],
) -> tuple[_RejectedUnknownLoadSession, ...]:
    """Deduplicate raw rejected diagnostics before ownership and counting."""

    grouped: dict[tuple[Any, ...], list[_RejectedUnknownLoadSession]] = {}
    for item in sessions:
        grouped.setdefault(_rejected_session_identity(item), []).append(item)
    deduplicated: list[_RejectedUnknownLoadSession] = []
    for key in sorted(grouped, key=repr):
        group = grouped[key]
        intervals = {
            (item.start, item.end, item.has_trustworthy_interval) for item in group
        }
        trustworthy = len(intervals) == 1 and group[0].has_trustworthy_interval
        starts = [item.start for item in group if item.start is not None]
        ends = [item.end for item in group if item.end is not None]
        deduplicated.append(
            _RejectedUnknownLoadSession(
                session_id=min(item.session_id for item in group),
                on_edge_id=min(item.on_edge_id for item in group),
                identities=frozenset().union(
                    *(item.identities for item in group)
                ),
                start=min(starts) if starts else None,
                end=(group[0].end if trustworthy else (max(ends) if ends else None)),
                has_trustworthy_interval=trustworthy,
                reason=min(item.reason for item in group),
            )
        )
    return tuple(deduplicated)


def _deduplicate_excluded_sessions(
    sessions: Iterable[_ExcludedUnknownLoadSession],
) -> tuple[_ExcludedUnknownLoadSession, ...]:
    """Collapse repeated rejected evidence into deterministic stable records."""

    grouped: dict[tuple[Any, ...], list[_ExcludedUnknownLoadSession]] = {}
    for item in sessions:
        grouped.setdefault(_excluded_session_identity(item), []).append(item)
    deduplicated: list[_ExcludedUnknownLoadSession] = []
    for key in sorted(grouped, key=repr):
        group = grouped[key]
        intervals = {
            (item.start, item.end, item.has_trustworthy_interval) for item in group
        }
        trustworthy = len(intervals) == 1 and group[0].has_trustworthy_interval
        starts = [item.start for item in group if item.start is not None]
        ends = [item.end for item in group if item.end is not None]
        deduplicated.append(
            _ExcludedUnknownLoadSession(
                component_id=group[0].component_id,
                session_id=min(item.session_id for item in group),
                on_edge_id=min(item.on_edge_id for item in group),
                start=min(starts) if starts else None,
                end=(
                    group[0].end
                    if trustworthy
                    else (max(ends) if ends else None)
                ),
                has_trustworthy_interval=trustworthy,
                reason=min(item.reason for item in group),
            )
        )
    return tuple(deduplicated)


def _session_inventory_evidence(
    sessions: Iterable[Mapping[str, Any]],
    *,
    components: Iterable[_UnknownLoadComponent],
    now: datetime,
    existing_state: Mapping[str, Any],
) -> _SessionInventoryEvidence:
    component_list = tuple(components)
    normalized, rejected = _normalize_unknown_load_sessions(sessions, now)
    rejected = _deduplicate_rejected_sessions(rejected)
    owned: list[_OwnedUnknownLoadSession] = []
    excluded: dict[str, list[_ExcludedUnknownLoadSession]] = {
        component.component_id: [] for component in component_list
    }
    ambiguous: dict[str, list[_ExcludedUnknownLoadSession]] = {
        component.component_id: [] for component in component_list
    }
    unowned_evidence: set[tuple[Any, ...]] = set()
    for item in rejected:
        candidates = _session_owner_candidates(
            item.identities, component_list, existing_state
        )
        if not candidates:
            unowned_evidence.add(("rejected", *_rejected_session_identity(item)))
            continue
        if len(candidates) == 1:
            component_id = candidates[0]
            excluded[component_id].append(
                _excluded_session(component_id, item, reason=item.reason)
            )
            continue
        for component_id in candidates:
            ambiguous[component_id].append(
                _excluded_session(component_id, item, reason="ambiguous")
            )
    for session in normalized:
        candidates = _session_owner_candidates(
            session.identities, component_list, existing_state
        )
        if len(candidates) != 1:
            if not candidates:
                unowned_evidence.add(("session", session.session_id))
            for component_id in candidates:
                ambiguous[component_id].append(
                    _excluded_session(component_id, session, reason="ambiguous")
                )
            continue
        owned.append(_OwnedUnknownLoadSession(session, candidates[0]))
    retained, dedup_excluded = _deduplicate_owned_sessions(owned)
    for item in dedup_excluded:
        ambiguous[item.component_id].append(item)
    return _SessionInventoryEvidence(
        sessions_by_component={
            component.component_id: tuple(
                item for item in retained if item.component_id == component.component_id
            )
            for component in component_list
        },
        excluded_sessions_by_component={
            component.component_id: _deduplicate_excluded_sessions(
                excluded[component.component_id]
            )
            for component in component_list
        },
        ambiguous_sessions_by_component={
            component.component_id: _deduplicate_excluded_sessions(
                ambiguous[component.component_id]
            )
            for component in component_list
        },
        observation_started_at_by_component={
            component.component_id: min(
                (
                    item.session.start
                    for item in retained
                    if item.component_id == component.component_id
                ),
                default=None,
            )
            for component in component_list
        },
        invalid_count=len(rejected),
        unowned_count=len(unowned_evidence),
    )


def _clip_session_seconds(
    session: _OwnedUnknownLoadSession, start: datetime, end: datetime
) -> float:
    clipped_start = max(session.session.start, start)
    clipped_end = min(session.session.end, end)
    return max(0.0, (clipped_end - clipped_start).total_seconds())


def _union_session_seconds(
    sessions: Iterable[_OwnedUnknownLoadSession],
    start: datetime,
    end: datetime,
) -> float:
    """Return clipped runtime without counting overlapping intervals twice."""

    intervals = sorted(
        (
            max(item.session.start, start),
            min(item.session.end, end),
        )
        for item in sessions
        if min(item.session.end, end) > max(item.session.start, start)
    )
    if not intervals:
        return 0.0
    total = 0.0
    current_start, current_end = intervals[0]
    for interval_start, interval_end in intervals[1:]:
        if interval_start <= current_end:
            current_end = max(current_end, interval_end)
            continue
        total += (current_end - current_start).total_seconds()
        current_start, current_end = interval_start, interval_end
    return total + (current_end - current_start).total_seconds()


def _estimate_status(
    *,
    intrinsic_ambiguous: bool,
    ambiguous_evidence: Iterable[_ExcludedUnknownLoadSession],
    excluded_evidence: Iterable[_ExcludedUnknownLoadSession],
    observation_started_at: datetime | None,
    window_start: datetime,
    window_end: datetime,
    session_history_coverage: NilmSessionHistoryCoverage | None,
) -> str:
    if intrinsic_ambiguous or any(
        _session_evidence_relevant(item, window_start, window_end)
        for item in ambiguous_evidence
    ):
        return "ambiguous"
    if (
        any(
            _session_evidence_relevant(item, window_start, window_end)
            for item in excluded_evidence
        )
        or observation_started_at is None
        or observation_started_at > window_start
        or _session_history_may_hide_open_session(session_history_coverage)
    ):
        return "partial_history"
    return "complete"


def _session_history_may_hide_open_session(
    coverage: NilmSessionHistoryCoverage | None,
) -> bool:
    """Return whether bounded history cannot rule out an omitted open session."""

    return coverage is not None and (
        coverage.was_truncated or coverage.ingress_history_incomplete
    )


def _session_evidence_relevant(
    item: _ExcludedUnknownLoadSession,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    if not item.has_trustworthy_interval or item.start is None:
        return True
    if item.end is None:
        return item.start < window_end
    return item.start < window_end and item.end > window_start


def _worst_estimate_status(statuses: Iterable[str]) -> str:
    severity = {
        "complete": 0,
        "partial_history": 1,
        "legacy_unverified": 2,
        "ambiguous": 3,
    }
    return max(statuses, key=lambda status: severity.get(status, 3), default="complete")


def _observation_started_at(
    observed: datetime | None, existing_state: Mapping[str, Any]
) -> str | None:
    values = [observed] if observed is not None else []
    try:
        existing = existing_state.get("observation_started_at")
        if existing:
            values.append(_as_utc_datetime(existing))
    except (TypeError, ValueError, OverflowError):
        pass
    return min(values).isoformat() if values else None


def _nilm_session_history_coverage_counts(
    configured_max_items: Any,
    source_count: Any,
    retained_count: Any,
    dropped_count: Any,
) -> tuple[int, int, int, int] | None:
    """Validate bounded numeric coverage facts without coercing payload scalars."""

    configured = _nilm_session_history_count(configured_max_items)
    source = _nilm_session_history_count(source_count)
    retained = _nilm_session_history_count(retained_count)
    dropped = _nilm_session_history_count(dropped_count)
    if (
        configured is None
        or source is None
        or retained is None
        or dropped is None
        or configured > NILM_SESSION_HISTORY_MAX_ITEMS_PER_CIRCUIT
        or retained > configured
        or source != retained + dropped
    ):
        return None
    return configured, source, retained, dropped


def _nilm_session_history_coverage_bounds(
    oldest_value: Any,
    newest_value: Any,
    *,
    retained_count: int,
) -> tuple[datetime | None, datetime | None, bool]:
    """Return ordered bounded coverage bounds or conservative unknown bounds."""

    if retained_count == 0:
        return None, None, oldest_value is None and newest_value is None
    if oldest_value is None or newest_value is None:
        return None, None, False
    oldest = _canonical_nilm_session_history_timestamp(oldest_value)
    newest = _canonical_nilm_session_history_timestamp(newest_value)
    if oldest is None or newest is None or oldest > newest:
        return None, None, False
    return oldest, newest, True


def _coverage_to_payload(coverage: NilmSessionHistoryCoverage) -> dict[str, Any]:
    counts = _nilm_session_history_coverage_counts(
        coverage.configured_max_items,
        coverage.source_count_before_retention,
        coverage.retained_count,
        coverage.dropped_count,
    )
    if counts is None:
        configured_max_items = source_count = retained_count = dropped_count = 0
        oldest = newest = None
        bounds_valid = False
        identity_components: tuple[_NilmSessionHistoryIdentityComponent, ...] = ()
        components_valid = False
    else:
        (
            configured_max_items,
            source_count,
            retained_count,
            dropped_count,
        ) = counts
        oldest, newest, bounds_valid = _nilm_session_history_coverage_bounds(
            coverage.oldest_retained_at,
            coverage.newest_retained_at,
            retained_count=retained_count,
        )
        identity_components, components_valid = (
            _canonical_nilm_session_history_identity_components(
                coverage.retention_identity_components
            )
        )
    payload: dict[str, Any] = {
        "configured_max_items": configured_max_items,
        "source_count_before_retention": source_count,
        "retained_count": retained_count,
        "was_truncated": dropped_count > 0,
        "dropped_count": dropped_count,
        "oldest_retained_at": oldest.isoformat() if oldest is not None else None,
        "newest_retained_at": newest.isoformat() if newest is not None else None,
        "_retention_identity_components_complete": (
            coverage.retention_identity_components_complete is True
            and components_valid
            and bounds_valid
            and dropped_count == len(identity_components)
        ),
    }
    if identity_components:
        payload["_retention_identity_components"] = [
            [[kind, value] for kind, value in component.aliases]
            for component in identity_components
        ]
    if coverage.ingress_history_incomplete is True:
        payload["_ingress_history_incomplete"] = True
    return payload


def nilm_session_history_coverage_from_payload(
    payload: Any,
) -> NilmSessionHistoryCoverage | None:
    """Read persisted coverage facts without treating malformed data as evidence."""

    if not isinstance(payload, Mapping):
        return None
    try:
        counts = _nilm_session_history_coverage_counts(
            payload["configured_max_items"],
            payload["source_count_before_retention"],
            payload["retained_count"],
            payload["dropped_count"],
        )
    except KeyError:
        return None
    if counts is None:
        return None
    configured_max_items, source_count, retained_count, dropped_count = counts
    oldest, newest, bounds_valid = _nilm_session_history_coverage_bounds(
        payload.get("oldest_retained_at"),
        payload.get("newest_retained_at"),
        retained_count=retained_count,
    )
    raw_components = payload.get("_retention_identity_components", ())
    components, components_valid = _canonical_nilm_session_history_identity_components(
        raw_components
    )
    raw_was_truncated = payload.get("was_truncated", _NILM_SESSION_HISTORY_MISSING)
    expected_was_truncated = dropped_count > 0
    truncation_valid = (
        isinstance(raw_was_truncated, bool)
        and raw_was_truncated is expected_was_truncated
    )
    raw_ingress_history_incomplete = payload.get(
        "_ingress_history_incomplete", False
    )
    ingress_history_incomplete = (
        raw_ingress_history_incomplete is True
        or (
            "_ingress_history_incomplete" in payload
            and not isinstance(raw_ingress_history_incomplete, bool)
        )
    )
    return NilmSessionHistoryCoverage(
        configured_max_items=configured_max_items,
        source_count_before_retention=source_count,
        retained_count=retained_count,
        was_truncated=expected_was_truncated,
        dropped_count=dropped_count,
        oldest_retained_at=oldest,
        newest_retained_at=newest,
        retention_identity_components=components,
        retention_identity_components_complete=(
            payload.get("_retention_identity_components_complete") is True
            and components_valid
            and truncation_valid
            and bounds_valid
            and dropped_count == len(components)
        ),
        ingress_history_incomplete=ingress_history_incomplete,
    )


def _edge_observation_started_at(loads: Iterable[Mapping[str, Any]]) -> datetime | None:
    observed: list[datetime] = []
    for load in loads:
        try:
            value = load.get("first_seen")
            if value:
                observed.append(_as_utc_datetime(value))
        except (TypeError, ValueError, OverflowError):
            continue
    return min(observed, default=None)


def _add_edge_window_metadata(
    load: dict[str, Any],
    windows: Mapping[str, tuple[datetime, datetime, float]],
    observed: datetime | None,
    existing_state: Mapping[str, Any],
) -> None:
    """Keep edge-only callers schema-compatible without claiming retained history."""

    ambiguous = load.get("separation_status") == "ambiguous"
    status = "ambiguous" if ambiguous else "partial_history"
    included = int(load.get("matched_on_edge_count") or 0)
    load["runtime_windows"] = {
        name: {
            "coverage_start": max(start, observed).isoformat()
            if observed is not None
            else start.isoformat(),
            "coverage_end": end.isoformat(),
            "coverage_days": round(
                max(0.0, (end - max(start, observed)).total_seconds() / 86_400)
                if observed is not None
                else 0.0,
                3,
            ),
            "nominal_days": round(nominal_days, 3),
            "estimate_status": status,
            "included_session_count": included,
            "excluded_session_count": 0,
        }
        for name, (start, end, nominal_days) in windows.items()
    }
    load["estimate_status_by_window"] = {
        name: status for name in windows
    }
    load["estimate_status"] = status
    load["observation_started_at"] = _observation_started_at(observed, existing_state)
    load["runtime_window_definition"] = _runtime_window_definition()


def _unknown_component_session_payload(
    component: _UnknownLoadComponent,
    allocation: _UnknownLoadAllocation,
    evidence: _SessionInventoryEvidence,
    *,
    windows: Mapping[str, tuple[datetime, datetime, float]],
    now: datetime,
    existing_state: Mapping[str, Any],
    session_history_coverage: NilmSessionHistoryCoverage | None,
) -> dict[str, Any]:
    """Assemble one component payload from reconstructed persisted runs."""

    payload = _unknown_component_payload(
        component, allocation, now=now, existing_state=existing_state
    )
    existing_load = _existing_component_state(existing_state, component)
    for key in ("user_label", "labels"):
        if key in existing_load:
            payload[key] = existing_load[key]
    sessions = evidence.sessions_by_component[component.component_id]
    ambiguous_sessions = evidence.ambiguous_sessions_by_component[
        component.component_id
    ]
    excluded_sessions = evidence.excluded_sessions_by_component[
        component.component_id
    ]
    intrinsic_ambiguous = (
        component.pair_status == "ambiguous"
        or (
            component.component_id in allocation.ambiguous_component_ids
            and not sessions
        )
    )
    open_sessions = [item for item in sessions if item.session.is_open]
    running_ambiguous = (
        intrinsic_ambiguous or bool(ambiguous_sessions) or len(open_sessions) > 1
    )
    if running_ambiguous or _session_history_may_hide_open_session(
        session_history_coverage
    ):
        payload["running_state"] = "unknown"
        payload["current_runtime_minutes"] = 0.0
    elif open_sessions:
        payload["running_state"] = "probably_on"
        payload["current_runtime_minutes"] = round(
            (now - open_sessions[0].session.start).total_seconds() / 60.0, 3
        )
        payload["last_start"] = open_sessions[0].session.start.isoformat()
        payload["last_stop"] = None
    else:
        payload["running_state"] = "probably_off"
        payload["current_runtime_minutes"] = 0.0

    estimate_statuses: dict[str, str] = {}
    runtime_windows: dict[str, dict[str, Any]] = {}
    for name, (start, end, nominal_days) in windows.items():
        relevant_ambiguous = tuple(
            item
            for item in ambiguous_sessions
            if _session_evidence_relevant(item, start, end)
        )
        relevant_excluded = tuple(
            item
            for item in excluded_sessions
            if _session_evidence_relevant(item, start, end)
        )
        window_ambiguous = (
            intrinsic_ambiguous or len(open_sessions) > 1 or bool(relevant_ambiguous)
        )
        seconds = (
            0.0 if window_ambiguous else _union_session_seconds(sessions, start, end)
        )
        runtime_minutes = round(seconds / 60.0, 3)
        status = _estimate_status(
            intrinsic_ambiguous=intrinsic_ambiguous or len(open_sessions) > 1,
            ambiguous_evidence=ambiguous_sessions,
            excluded_evidence=excluded_sessions,
            observation_started_at=evidence.observation_started_at_by_component[
                component.component_id
            ],
            window_start=start,
            window_end=end,
            session_history_coverage=session_history_coverage,
        )
        estimate_statuses[name] = status
        runtime_windows[name] = {
            "coverage_start": max(
                start,
                evidence.observation_started_at_by_component[component.component_id],
            )
            .isoformat()
            if evidence.observation_started_at_by_component[component.component_id]
            is not None
            else start.isoformat(),
            "coverage_end": end.isoformat(),
            "coverage_days": round(
                max(
                    0.0,
                    (
                        end
                        - max(
                            start,
                            evidence.observation_started_at_by_component[
                                component.component_id
                            ],
                        )
                    ).total_seconds()
                    / 86_400,
                )
                if evidence.observation_started_at_by_component[component.component_id]
                is not None
                else 0.0,
                3,
            ),
            "nominal_days": round(nominal_days, 3),
            "estimate_status": status,
            "included_session_count": sum(
                1 for item in sessions if _clip_session_seconds(item, start, end) > 0.0
            )
            if not window_ambiguous
            else 0,
            "excluded_session_count": len(relevant_excluded)
            + len(relevant_ambiguous),
        }
        suffix = {"today": "today", "7_days": "7_days", "30_days": "30_days"}[name]
        payload[f"runtime_{suffix}_minutes"] = runtime_minutes
        payload[f"estimated_energy_{suffix}_kwh"] = _estimated_kwh(
            float(payload["typical_watts"]), runtime_minutes
        )
    payload["runtime_windows"] = runtime_windows
    payload["estimate_status_by_window"] = estimate_statuses
    payload["estimate_status"] = _worst_estimate_status(estimate_statuses.values())
    payload["observation_started_at"] = _observation_started_at(
        evidence.observation_started_at_by_component[component.component_id],
        existing_load,
    )
    payload["runtime_window_definition"] = _runtime_window_definition()
    payload["separation_status"] = (
        "ambiguous" if running_ambiguous else "separable"
    )
    payload["energy_estimate_confidence"] = (
        0.0 if running_ambiguous else float(payload["confidence"])
    )
    return payload


def _unknown_component_payload(
    component: _UnknownLoadComponent,
    allocation: _UnknownLoadAllocation,
    *,
    now: datetime,
    existing_state: Mapping[str, Any],
) -> dict[str, Any]:
    estimate = estimate_unknown_load(component.on_signature)
    matching_edges = list(allocation.edges_by_component[component.component_id])
    first_seen = min((edge.timestamp for edge in matching_edges), default=None)
    last_seen = max((edge.timestamp for edge in matching_edges), default=None)
    runtime_minutes, running_state, last_start, last_stop = _runtime_state(
        matching_edges,
        now,
    )
    ambiguous = (
        component.pair_status == "ambiguous"
        or component.component_id in allocation.ambiguous_component_ids
    )
    if ambiguous:
        runtime_minutes = 0.0
        running_state = "unknown"

    energy_today = _estimated_kwh(estimate["typical_watts"], runtime_minutes)
    existing_load = _existing_component_state(existing_state, component)
    review_state = str(existing_load.get("review_state") or "new")
    if review_state == "merged":
        review_state = "merged"
    evidence = list(estimate["evidence"])
    evidence.append(_component_evidence(component, allocation))

    return {
        **estimate,
        "component_id": component.component_id,
        "component_fingerprint": component.component_fingerprint,
        "on_signature_id": component.on_signature.signature_id,
        "on_signature_fingerprint": nilm_signature_fingerprint(
            component.on_signature
        ),
        "off_signature_id": (
            component.off_signature.signature_id
            if component.off_signature is not None
            else None
        ),
        "off_signature_fingerprint": (
            nilm_signature_fingerprint(component.off_signature)
            if component.off_signature is not None
            else None
        ),
        "signature_pair_status": component.pair_status,
        "signature_pair_score": (
            round(component.pair_score, 3)
            if component.pair_score is not None
            else None
        ),
        "alternate_signature_pair_count": component.alternate_pair_count,
        "matched_on_edge_count": allocation.matched_on_count_by_component[
            component.component_id
        ],
        "matched_off_edge_count": allocation.matched_off_count_by_component[
            component.component_id
        ],
        "ambiguous_edge_count": allocation.ambiguous_edge_count_by_component[
            component.component_id
        ],
        "evidence": evidence,
        "first_seen": first_seen.isoformat() if first_seen else None,
        "last_seen": last_seen.isoformat() if last_seen else None,
        "review_state": review_state,
        "separation_status": "ambiguous" if ambiguous else "separable",
        "running_state": running_state,
        "last_start": last_start.isoformat() if last_start else None,
        "last_stop": last_stop.isoformat() if last_stop else None,
        "current_runtime_minutes": runtime_minutes
        if running_state == "probably_on"
        else 0.0,
        "runtime_today_minutes": runtime_minutes,
        "runtime_7_days_minutes": runtime_minutes,
        "runtime_30_days_minutes": runtime_minutes,
        "estimated_energy_today_kwh": energy_today,
        "estimated_energy_7_days_kwh": energy_today,
        "estimated_energy_30_days_kwh": energy_today,
        "energy_estimate_confidence": 0.0
        if ambiguous
        else float(estimate["confidence"]),
    }


def _component_evidence(
    component: _UnknownLoadComponent,
    allocation: _UnknownLoadAllocation,
) -> str:
    if component.pair_status == "paired" and component.off_signature is not None:
        return (
            "Paired "
            f"{allocation.matched_on_count_by_component[component.component_id]} ON "
            "events with "
            f"{allocation.matched_off_count_by_component[component.component_id]} OFF "
            f"events using {component.on_signature.signature_id} and "
            f"{component.off_signature.signature_id}."
        )
    if component.pair_status == "ambiguous":
        return (
            "Multiple component/signature matches were too close to separate "
            "conservatively."
        )
    return (
        "No separate recurring OFF signature is established; compatible negative "
        "edges use the ON-magnitude fallback."
    )


def _runtime_state(
    edges: list[NilmEdge],
    now: datetime,
) -> tuple[float, str, datetime | None, datetime | None]:
    running = False
    last_start: datetime | None = None
    last_stop: datetime | None = None
    runtime_minutes = 0.0

    for edge in edges:
        if edge.direction == "on" and not running:
            running = True
            last_start = edge.timestamp
            continue
        if edge.direction == "off" and running and last_start is not None:
            runtime_minutes += max(
                0.0,
                (edge.timestamp - last_start).total_seconds() / 60.0,
            )
            running = False
            last_stop = edge.timestamp

    if running and last_start is not None:
        runtime_minutes += max(0.0, (now - last_start).total_seconds() / 60.0)

    return (
        round(runtime_minutes, 3),
        "probably_on" if running else "probably_off",
        last_start,
        last_stop,
    )


def _ambiguous_signature_ids(
    signatures: list[NilmSignature],
    edges: list[NilmEdge],
) -> set[str]:
    simultaneous_timestamps = _simultaneous_timestamps(edges)
    if not simultaneous_timestamps:
        return set()

    ambiguous_ids: set[str] = set()
    for signature in signatures:
        if any(
            edge.timestamp in simultaneous_timestamps
            and _watts_topology_match(signature, edge)
            for edge in edges
        ):
            ambiguous_ids.add(signature.signature_id)
    return ambiguous_ids


def _watts_topology_match(signature: NilmSignature, edge: NilmEdge) -> bool:
    target_watts = abs(float(signature.median_delta_w))
    topology_match = (
        signature.split_phase_type == "unknown"
        or edge.split_phase_type == "unknown"
        or signature.split_phase_type == edge.split_phase_type
    )
    return (
        _within_tolerance(abs(edge.delta_w), target_watts, 0.2, 50.0)
        and topology_match
    )


def _simultaneous_timestamps(edges: list[NilmEdge]) -> set[datetime]:
    counts: dict[datetime, int] = {}
    for edge in edges:
        counts[edge.timestamp] = counts.get(edge.timestamp, 0) + 1
    return {timestamp for timestamp, count in counts.items() if count > 1}


def _simultaneous_unknown_event_count(edges: list[NilmEdge]) -> int:
    simultaneous = _simultaneous_timestamps(edges)
    return sum(1 for edge in edges if edge.timestamp in simultaneous)


def _estimated_kwh(watts: float, runtime_minutes: float) -> float:
    return round((float(watts) * float(runtime_minutes)) / 60000.0, 3)


def _sum_loads(loads: list[dict[str, Any]], key: str) -> float:
    return round(sum(_load_number(load, key) for load in loads), 3)


def _largest_load(loads: list[dict[str, Any]], key: str) -> str | None:
    identified_loads = [
        load for load in loads if str(load.get("signature_id") or "").strip()
    ]
    if not identified_loads:
        return None
    return str(
        max(identified_loads, key=lambda load: _load_number(load, key))["signature_id"]
    )


def _load_number(load: Mapping[str, Any], key: str) -> float:
    return _optional_float(load.get(key)) or 0.0


def _existing_component_state(
    existing_state: Mapping[str, Any],
    component: _UnknownLoadComponent,
) -> Mapping[str, Any]:
    loads = existing_state.get("unknown_loads") if existing_state else None
    if not isinstance(loads, list):
        return {}
    mappings = [load for load in loads if isinstance(load, Mapping)]
    for load in mappings:
        if load.get("component_id") == component.component_id:
            return load
    for load in mappings:
        if load.get("signature_id") in {
            component.component_id,
            component.on_signature.signature_id,
        } or load.get("on_signature_id") == component.on_signature.signature_id:
            return load
    for load in mappings:
        if (
            load.get("component_fingerprint") == component.component_fingerprint
            or load.get("on_signature_fingerprint")
            == component.component_fingerprint
        ):
            return load
    legacy_matches = [
        load
        for load in mappings
        if _legacy_load_matches_on_signature(load, component.on_signature)
    ]
    if len(legacy_matches) == 1:
        return legacy_matches[0]

    if component.pair_status == "paired" and component.off_signature is not None:
        paired_off_matches = [
            load
            for load in mappings
            if load.get("signature_id") == component.off_signature.signature_id
        ]
        if len(paired_off_matches) == 1:
            return paired_off_matches[0]
    return {}


def _legacy_load_matches_on_signature(
    load: Mapping[str, Any],
    signature: NilmSignature,
) -> bool:
    try:
        typical_watts = float(load.get("typical_watts"))
    except (TypeError, ValueError):
        return False
    if not _within_tolerance(
        typical_watts,
        abs(float(signature.median_delta_w)),
        0.2,
        50.0,
    ):
        return False
    stored_topology = str(load.get("split_phase_type") or "unknown")
    return (
        stored_topology == "unknown"
        or signature.split_phase_type == "unknown"
        or stored_topology == signature.split_phase_type
    )


def _existing_load_state(
    existing_state: Mapping[str, Any],
    signature_id: str,
) -> Mapping[str, Any]:
    """Return legacy state for callers outside component inventory construction."""

    loads = existing_state.get("unknown_loads") if existing_state else None
    if not isinstance(loads, list):
        return {}
    for load in loads:
        if isinstance(load, Mapping) and load.get("signature_id") == signature_id:
            return load
    return {}


def _within_tolerance(
    value: float,
    reference: float,
    ratio: float,
    floor: float,
) -> bool:
    return abs(value - reference) <= max(abs(reference) * ratio, floor)


def _likely_type(
    signature: NilmSignature,
    *,
    typical_watts: float,
    typical_var: float | None,
    typical_va: float | None,
    typical_power_factor: float | None,
    voltage_class: str,
) -> str:
    if not _has_enough_evidence(signature):
        return "unknown"

    if typical_var is None or typical_va is None or typical_power_factor is None:
        return "unknown"
    reactive_ratio = typical_var / max(typical_watts, 1.0)
    if (
        voltage_class == "240 V"
        and signature.split_phase_type == "balanced_240v"
        and typical_watts >= 1000.0
        and reactive_ratio <= 0.12
        and typical_power_factor >= 0.95
    ):
        return "heating_element_candidate"

    if (
        voltage_class == "120 V"
        and signature.split_phase_type in {"single_leg_a", "single_leg_b"}
        and typical_watts >= 150.0
        and reactive_ratio >= 0.25
        and typical_power_factor <= 0.9
    ):
        return "motor"

    if typical_va >= 100.0 and typical_var >= 75.0 and reactive_ratio >= 0.75:
        return "power_electronics"

    return "unknown"


def _has_enough_evidence(signature: NilmSignature) -> bool:
    return (
        signature.occurrence_count >= MIN_OCCURRENCES
        and signature.confidence >= MIN_CONFIDENCE
    )


def _voltage_class(split_phase_type: str) -> str:
    if split_phase_type == "balanced_240v":
        return "240 V"
    if split_phase_type in {"single_leg_a", "single_leg_b"}:
        return "120 V"
    if split_phase_type == "imbalanced_240v_or_mixed":
        return "mixed"
    return "unknown"


def _display_name(likely_type: str, voltage_class: str) -> str:
    if likely_type == "heating_element_candidate":
        return "Estimated 240 V heating element candidate"
    if likely_type == "motor":
        voltage = "120 V" if voltage_class == "120 V" else "unknown-voltage"
        return f"Estimated possible {voltage} motor-like unknown load"
    if likely_type == "power_electronics":
        return "Estimated possible power-electronics unknown load"
    return "Estimated unknown load"


def _evidence(
    signature: NilmSignature,
    *,
    likely_type: str,
    voltage_class: str,
    typical_watts: float,
    typical_var: float | None,
    typical_va: float | None,
    typical_power_factor: float | None,
) -> list[str]:
    evidence = [
        (
            f"Estimated from {signature.occurrence_count} recurring unmatched events "
            f"with confidence {signature.confidence:.2f}."
        ),
        (
            "Split-phase evidence suggests "
            f"{_voltage_label(voltage_class)} topology "
            f"({signature.split_phase_type}, dominant leg {signature.dominant_leg})."
        ),
        (
            f"Typical median change is {typical_watts:.1f} W, "
            f"{_optional_metric_text(typical_var, 1)} VAR, "
            f"{_optional_metric_text(typical_va, 1)} VA, "
            f"estimated PF {_optional_metric_text(typical_power_factor, 3)}."
        ),
    ]

    if not _has_enough_evidence(signature):
        evidence.append(
            "Limited recurring evidence; keep this as unknown until more samples "
            "are observed."
        )
    elif likely_type == "heating_element_candidate":
        evidence.append(
            "Possible heating element candidate: balanced 240 V, high W, "
            "low VAR, and PF near unity."
        )
    elif likely_type == "motor":
        evidence.append(
            "Possible motor-like pattern: single-leg 120 V, meaningful "
            "reactive power, and lower estimated PF."
        )
    elif likely_type == "power_electronics":
        evidence.append(
            "Possible power-electronics pattern: VA and VAR are high versus "
            "real power without the single-leg motor pattern."
        )
    else:
        evidence.append("No conservative helper pattern matched; keep this as unknown.")

    return evidence


def _voltage_label(voltage_class: str) -> str:
    if voltage_class == "120 V":
        return "possible 120 V"
    if voltage_class == "240 V":
        return "possible 240 V"
    if voltage_class == "mixed":
        return "mixed"
    return "unknown-voltage"


def _typical_power_factor(
    typical_watts: float,
    typical_va: float | None,
) -> float | None:
    if typical_va is None or typical_va <= 0.0:
        return None
    return round(min(typical_watts / typical_va, 1.0), 3)


def _rounded_abs(value: float | None) -> float | None:
    if value is None:
        return None
    return round(abs(float(value)), 3)


def _optional_abs(value: float | None) -> float | None:
    return None if value is None else abs(float(value))


def _optional_metric_text(value: float | None, decimals: int) -> str:
    return "unavailable" if value is None else f"{value:.{decimals}f}"
