from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.circuitsetup_energy_analyzer import unknown_loads
from custom_components.circuitsetup_energy_analyzer.nilm import (
    NilmEdge,
    NilmSignature,
    cluster_recurring_signatures,
    nilm_signature_fingerprint,
    nilm_signature_fingerprint_v1,
)
from custom_components.circuitsetup_energy_analyzer.unknown_loads import (
    NilmSessionHistoryCoverage,
    build_unknown_load_inventory,
    estimate_unknown_load,
)

BASE_TIME = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)


def signature(
    signature_id: str,
    watts: float,
    var: float,
    va: float,
    *,
    delta_pf: float = 0.0,
    occurrence_count: int = 4,
    confidence: float = 0.7,
    split_phase_type: str = "unknown",
    dominant_leg: str = "unknown",
    median_leg_a_delta_w: float | None = None,
    median_leg_b_delta_w: float | None = None,
    leg_balance_ratio: float | None = None,
) -> NilmSignature:
    return NilmSignature(
        signature_id=signature_id,
        median_delta_w=watts,
        median_delta_var=var,
        median_delta_va=va,
        median_delta_pf=delta_pf,
        occurrence_count=occurrence_count,
        confidence=confidence,
        split_phase_type=split_phase_type,
        dominant_leg=dominant_leg,
        median_leg_a_delta_w=median_leg_a_delta_w,
        median_leg_b_delta_w=median_leg_b_delta_w,
        leg_balance_ratio=leg_balance_ratio,
    )


def edge(
    minutes: int,
    watts: float,
    *,
    var: float = 0.0,
    direction: str = "on",
    split_phase_type: str = "single_leg_a",
    dominant_leg: str = "a",
) -> NilmEdge:
    return NilmEdge(
        timestamp=BASE_TIME + timedelta(minutes=minutes),
        delta_w=watts,
        delta_var=var,
        delta_va=(watts**2 + var**2) ** 0.5,
        delta_pf=0.0,
        direction=direction,
        split_phase_type=split_phase_type,
        dominant_leg=dominant_leg,
    )


def test_directional_signatures_share_one_unknown_load_component() -> None:
    """ON/OFF clusters for one appliance must not duplicate its runtime or energy."""

    edges = [
        edge(0, 500.0, var=100.0, direction="on"),
        edge(10, -500.0, var=-100.0, direction="off"),
        edge(20, 500.0, var=100.0, direction="on"),
        edge(40, -500.0, var=-100.0, direction="off"),
        edge(50, 500.0, var=100.0, direction="on"),
        edge(80, -500.0, var=-100.0, direction="off"),
    ]

    signatures = cluster_recurring_signatures(edges)
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=signatures,
        edges=edges,
        now=BASE_TIME + timedelta(minutes=90),
    )

    assert len(signatures) == 2
    assert inventory["unknown_load_count"] == 1
    assert len(inventory["unknown_loads"]) == 1
    load = inventory["unknown_loads"][0]
    assert load["signature_id"].startswith("on-")
    assert load["off_signature_id"].startswith("off-")
    assert load["matched_on_edge_count"] == 3
    assert load["matched_off_edge_count"] == 3
    assert load["runtime_today_minutes"] == 60.0
    assert load["estimated_energy_today_kwh"] == 0.5
    assert inventory["unknown_estimated_energy_today_kwh"] == 0.5
    assert load["running_state"] == "probably_off"


def test_inventory_uses_stored_sessions_for_independent_runtime_windows() -> None:
    """Stored runs populate today, trailing-seven, and trailing-thirty separately."""

    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    component = signature("sig-windowed", 500.0, 100.0, 510.0)
    sessions = [
        {
            "session_id": "today",
            "component_id": "sig-windowed",
            "signature_fingerprint": "windowed-fingerprint",
            "start": "2026-08-09T10:00:00+00:00",
            "end": "2026-08-09T11:00:00+00:00",
        },
        {
            "session_id": "two-days-ago",
            "component_id": "sig-windowed",
            "signature_fingerprint": "windowed-fingerprint",
            "start": "2026-08-07T09:00:00+00:00",
            "end": "2026-08-07T10:30:00+00:00",
        },
        {
            "session_id": "ten-days-ago",
            "component_id": "sig-windowed",
            "signature_fingerprint": "windowed-fingerprint",
            "start": "2026-07-30T09:00:00+00:00",
            "end": "2026-07-30T11:00:00+00:00",
        },
        {
            "session_id": "thirty-five-days-ago",
            "component_id": "sig-windowed",
            "signature_fingerprint": "windowed-fingerprint",
            "start": "2026-07-05T09:00:00+00:00",
            "end": "2026-07-05T10:00:00+00:00",
        },
    ]

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[component],
        edges=[],
        sessions=sessions,
        now=now,
    )

    load = inventory["unknown_loads"][0]
    assert load["runtime_today_minutes"] == 60.0
    assert load["runtime_7_days_minutes"] == 150.0
    assert load["runtime_30_days_minutes"] == 270.0
    assert load["estimated_energy_today_kwh"] == 0.5
    assert load["estimated_energy_7_days_kwh"] == 1.25
    assert load["estimated_energy_30_days_kwh"] == 2.25


def test_session_windows_clip_boundaries_and_local_midnight() -> None:
    """Runs crossing a local day boundary contribute only their clipped duration."""

    component = signature("sig-boundary", 500.0, 100.0, 510.0)
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[component],
        edges=[],
        sessions=[
            {
                "session_id": "crosses-midnight",
                "component_id": "sig-boundary",
                "signature_fingerprint": "boundary",
                "start": "2026-03-08T04:30:00+00:00",
                "end": "2026-03-08T05:30:00+00:00",
            }
        ],
        now=datetime(2026, 3, 8, 16, 0, tzinfo=UTC),
        time_zone="America/New_York",
    )

    load = inventory["unknown_loads"][0]
    assert load["runtime_today_minutes"] == 30.0
    assert load["runtime_windows"]["today"]["coverage_start"] == (
        "2026-03-08T05:00:00+00:00"
    )
    assert load["runtime_windows"]["today"]["nominal_days"] == 0.458


def test_session_evidence_excludes_malformed_and_ambiguous_rows() -> None:
    """Invalid or non-unique evidence must not inflate a component's history."""

    now = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-evidence", 500.0, 100.0, 510.0)],
        edges=[],
        sessions=[
            {
                "session_id": "usable",
                "component_id": "sig-evidence",
                "signature_fingerprint": "evidence",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            },
            {
                "session_id": "bad-date",
                "component_id": "sig-evidence",
                "signature_fingerprint": "evidence",
                "start": "not-a-date",
                "end": "2026-08-09T11:00:00+00:00",
            },
            {
                "session_id": "ambiguous",
                "component_id": "sig-evidence",
                "signature_fingerprint": "evidence",
                "start": "2026-08-09T09:00:00+00:00",
                "end": "2026-08-09T10:00:00+00:00",
                "ambiguous": True,
            },
        ],
        now=now,
    )

    window = inventory["unknown_loads"][0]["runtime_windows"]["today"]
    assert inventory["unknown_loads"][0]["runtime_today_minutes"] == 60.0
    assert window["included_session_count"] == 1
    assert window["excluded_session_count"] == 2
    assert window["estimate_status"] == "partial_history"


def test_session_exclusions_are_component_and_window_specific() -> None:
    """Rejected evidence affects only its owners and intersecting windows."""

    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

    def owned_row(name: str, owner: str, age_days: int) -> dict[str, object]:
        start = now - timedelta(days=age_days)
        return {
            "session_id": name,
            "signature_id": owner,
            "signature_fingerprint": owner,
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=30)).isoformat(),
        }

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("on-a", 500.0, 100.0, 510.0),
            signature("on-b", 900.0, 100.0, 910.0),
            signature("on-c", 1_400.0, 100.0, 1_410.0),
        ],
        edges=[],
        sessions=[
            owned_row("a-covered", "on-a", 32),
            owned_row("b-covered", "on-b", 32),
            owned_row("c-covered", "on-c", 32),
            {
                **owned_row("ab-ambiguous", "on-a", 8),
                "on_signature_id": "on-b",
            },
            {
                "session_id": "expired-malformed-a",
                "signature_id": "on-a",
                "start": (now - timedelta(days=31)).isoformat(),
                "end": (now - timedelta(days=31, minutes=-30)).isoformat(),
            },
            {
                "session_id": "untimed-malformed-c",
                "signature_id": "on-c",
                "signature_fingerprint": "on-c",
                "start": "bad",
                "end": "bad",
            },
            {"session_id": "ownerless-malformed", "start": "bad", "end": "bad"},
        ],
        now=now,
    )

    loads = {load["on_signature_id"]: load for load in inventory["unknown_loads"]}
    for owner in ("on-a", "on-b"):
        assert loads[owner]["estimate_status_by_window"] == {
            "today": "complete",
            "7_days": "complete",
            "30_days": "ambiguous",
        }
        assert {
            name: window["excluded_session_count"]
            for name, window in loads[owner]["runtime_windows"].items()
        } == {"today": 0, "7_days": 0, "30_days": 1}
    assert loads["on-c"]["estimate_status_by_window"] == {
        "today": "partial_history",
        "7_days": "partial_history",
        "30_days": "partial_history",
    }
    assert inventory["session_history_diagnostics"] == {
        "invalid_count": 3,
        "unowned_count": 1,
    }


def test_duplicate_exclusions_are_order_stable() -> None:
    """Repeated rejected rows have one deterministic evidence identity."""

    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    baseline = {
        "session_id": "covered",
        "signature_id": "on-a",
        "signature_fingerprint": "on-a",
        "start": (now - timedelta(days=31)).isoformat(),
        "end": (now - timedelta(days=31, minutes=-30)).isoformat(),
    }
    duplicate = {
        "session_id": "recent-malformed",
        "signature_id": "on-a",
        "start": (now - timedelta(hours=1)).isoformat(),
        "end": (now - timedelta(minutes=30)).isoformat(),
    }
    ownerless = {
        "session_id": "ownerless-malformed",
        "start": "bad",
        "end": "bad",
    }

    def build(rows: list[dict[str, object]]) -> dict[str, object]:
        return build_unknown_load_inventory(
            circuit_id="mains",
            signatures=[signature("on-a", 500.0, 100.0, 510.0)],
            edges=[],
            sessions=rows,
            now=now,
        )

    single = build([baseline, duplicate, ownerless])
    forward = build(
        [baseline, duplicate, dict(duplicate), ownerless, dict(ownerless)]
    )
    reverse = build(
        [dict(ownerless), ownerless, dict(duplicate), duplicate, baseline]
    )

    assert single == forward == reverse
    windows = forward["unknown_loads"][0]["runtime_windows"]
    assert all(window["excluded_session_count"] == 1 for window in windows.values())
    assert forward["session_history_diagnostics"] == {
        "invalid_count": 2,
        "unowned_count": 1,
    }


def test_inconsistent_exclusion_intervals_remain_conservative() -> None:
    """A recent closed copy cannot disappear behind an expired open copy."""

    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("on-a", 500.0, 100.0, 510.0)],
        edges=[],
        sessions=[
            {
                "session_id": "covered",
                "signature_id": "on-a",
                "signature_fingerprint": "on-a",
                "start": (now - timedelta(days=32)).isoformat(),
                "end": (now - timedelta(days=32, minutes=-30)).isoformat(),
            },
            {
                "session_id": "conflicting-exclusion",
                "signature_id": "on-a",
                "start": (now - timedelta(days=31)).isoformat(),
                "end": None,
            },
            {
                "session_id": "conflicting-exclusion",
                "signature_id": "on-a",
                "start": (now - timedelta(days=31)).isoformat(),
                "end": (now - timedelta(minutes=30)).isoformat(),
            },
        ],
        now=now,
    )

    load = inventory["unknown_loads"][0]
    assert load["estimate_status_by_window"] == {
        "today": "partial_history",
        "7_days": "partial_history",
        "30_days": "partial_history",
    }
    assert all(
        window["excluded_session_count"] == 1
        for window in load["runtime_windows"].values()
    )


def test_cross_owner_duplicate_uses_one_conservative_interval() -> None:
    """Every candidate sees conflicting timing for a shared stable identity."""

    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

    def row(name: str, owner: str, start: datetime) -> dict[str, object]:
        return {
            "session_id": name,
            "signature_id": owner,
            "signature_fingerprint": owner,
            "start": start.isoformat(),
            "end": (start + timedelta(minutes=30)).isoformat(),
        }

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("on-a", 500.0, 100.0, 510.0),
            signature("on-b", 900.0, 100.0, 910.0),
        ],
        edges=[],
        sessions=[
            row("a-covered", "on-a", now - timedelta(days=32)),
            row("b-covered", "on-b", now - timedelta(days=32)),
            row("shared-conflict", "on-a", now - timedelta(days=31)),
            row("shared-conflict", "on-b", now - timedelta(hours=1)),
        ],
        now=now,
    )

    for load in inventory["unknown_loads"]:
        assert load["estimate_status_by_window"] == {
            "today": "ambiguous",
            "7_days": "ambiguous",
            "30_days": "ambiguous",
        }
        assert all(
            window["excluded_session_count"] == 1
            for window in load["runtime_windows"].values()
        )


def test_session_metadata_keeps_observation_starts_component_local() -> None:
    """A top-level boundary cannot become component history on rebuild."""

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-observation", 500.0, 100.0, 510.0)],
        edges=[],
        sessions=[
            {
                "session_id": "recent-run",
                "component_id": "sig-observation",
                "signature_fingerprint": "observation",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        session_history_max_items=100,
        existing_state={"observation_started_at": "2026-07-01T00:00:00+00:00"},
    )

    load = inventory["unknown_loads"][0]
    assert inventory["observation_started_at"] == "2026-07-01T00:00:00+00:00"
    assert load["observation_started_at"] == "2026-08-09T10:00:00+00:00"
    assert load["estimate_status"] == "partial_history"


def test_oversized_retention_identity_metadata_is_rejected_deterministically() -> None:
    """Persisted identity metadata cannot exceed its fixed storage contract."""

    limit = unknown_loads.NILM_SESSION_HISTORY_COVERAGE_IDENTITY_MAX_ITEMS
    aliases = [["session", f"session-{index:05d}"] for index in range(limit + 1)]
    payload = {
        "configured_max_items": 2,
        "source_count_before_retention": 5,
        "retained_count": 2,
        "was_truncated": True,
        "dropped_count": 3,
        "oldest_retained_at": "2026-08-08T00:00:00+00:00",
        "newest_retained_at": "2026-08-10T00:00:00+00:00",
        "_retention_identity_aliases": aliases,
        "_retention_identity_aliases_complete": True,
    }

    forward = unknown_loads.nilm_session_history_coverage_from_payload(payload)
    reverse = unknown_loads.nilm_session_history_coverage_from_payload(
        {**payload, "_retention_identity_aliases": list(reversed(aliases))}
    )

    assert forward is not None
    assert reverse is not None
    assert forward.retention_identity_aliases == ()
    assert reverse.retention_identity_aliases == ()
    assert forward.retention_identity_aliases_complete is False
    assert reverse.retention_identity_aliases_complete is False


def test_retention_identity_metadata_accepts_only_strict_string_aliases() -> None:
    """Malformed alias members cannot become asserted historical identities."""

    payload = {
        "configured_max_items": 2,
        "source_count_before_retention": 5,
        "retained_count": 2,
        "was_truncated": True,
        "dropped_count": 3,
        "oldest_retained_at": "2026-08-08T00:00:00+00:00",
        "newest_retained_at": "2026-08-10T00:00:00+00:00",
        "_retention_identity_aliases": [
            ["session", None],
            ["session", 7],
            ["session", True],
            ["session", {"not": "valid"}],
            [None, "value"],
            [7, "value"],
            [True, "value"],
            [{"not": "valid"}, "value"],
            ["invalid_kind", "value"],
            ["session", "   "],
            ["session", " valid-session "],
            ["on_edge", "valid-edge"],
        ],
        "_retention_identity_aliases_complete": True,
    }

    coverage = unknown_loads.nilm_session_history_coverage_from_payload(payload)

    assert coverage is not None
    assert coverage.retention_identity_aliases == (
        ("on_edge", "valid-edge"),
        ("session", "valid-session"),
    )
    assert coverage.retention_identity_aliases_complete is False
    roundtrip = unknown_loads._coverage_to_payload(coverage)
    assert roundtrip["_retention_identity_aliases"] == [
        ["on_edge", "valid-edge"],
        ["session", "valid-session"],
    ]
    assert roundtrip["_retention_identity_aliases_complete"] is False
    alias_repr = repr(roundtrip["_retention_identity_aliases"])
    assert "None" not in alias_repr
    assert "True" not in alias_repr
    assert "{'not': 'valid'}" not in alias_repr


def test_complete_retention_identity_metadata_round_trips_canonically() -> None:
    """A complete valid alias ledger remains complete, sorted, and deduplicated."""

    payload = {
        "configured_max_items": 2,
        "source_count_before_retention": 4,
        "retained_count": 2,
        "was_truncated": True,
        "dropped_count": 2,
        "oldest_retained_at": "2026-08-08T00:00:00+00:00",
        "newest_retained_at": "2026-08-10T00:00:00+00:00",
        "_retention_identity_aliases": [
            ["session", "z-session"],
            ["on_edge", "a-edge"],
            ["session", "z-session"],
        ],
        "_retention_identity_aliases_complete": True,
    }

    coverage = unknown_loads.nilm_session_history_coverage_from_payload(payload)

    assert coverage is not None
    assert coverage.retention_identity_aliases == (
        ("on_edge", "a-edge"),
        ("session", "z-session"),
    )
    assert coverage.retention_identity_aliases_complete is True
    assert unknown_loads._coverage_to_payload(coverage) == {
        **{key: value for key, value in payload.items() if not key.startswith("_")},
        "_retention_identity_aliases": [
            ["on_edge", "a-edge"],
            ["session", "z-session"],
        ],
        "_retention_identity_aliases_complete": True,
    }


def test_complete_retention_identity_metadata_requires_alias_per_drop() -> None:
    """A complete claim cannot contradict its own historical dropped count."""

    coverage = unknown_loads.nilm_session_history_coverage_from_payload(
        {
            "configured_max_items": 2,
            "source_count_before_retention": 5,
            "retained_count": 2,
            "was_truncated": True,
            "dropped_count": 3,
            "oldest_retained_at": "2026-08-08T00:00:00+00:00",
            "newest_retained_at": "2026-08-10T00:00:00+00:00",
            "_retention_identity_aliases": [
                ["session", "only-one"],
                ["session", "only-two"],
            ],
            "_retention_identity_aliases_complete": True,
        }
    )

    assert coverage is not None
    assert coverage.retention_identity_aliases_complete is False


def test_session_coverage_payload_bounds_identity_metadata_deterministically() -> None:
    """Inventory serialization enforces the identity metadata output bound."""

    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    limit = unknown_loads.NILM_SESSION_HISTORY_COVERAGE_IDENTITY_MAX_ITEMS
    aliases = tuple(
        ("session", f"session-{index:05d}") for index in range(limit + 1)
    )
    sessions = [
        {
            "session_id": "retained",
            "component_id": "on-a",
            "signature_fingerprint": "on-a",
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": now.isoformat(),
        }
    ]

    def build(identity_aliases: tuple[tuple[str, str], ...]) -> list[list[str]]:
        inventory = build_unknown_load_inventory(
            circuit_id="mains",
            signatures=[signature("on-a", 500.0, 100.0, 510.0)],
            edges=[],
            sessions=sessions,
            now=now,
            session_history_coverage=NilmSessionHistoryCoverage(
                configured_max_items=1,
                source_count_before_retention=2,
                retained_count=1,
                was_truncated=True,
                dropped_count=1,
                oldest_retained_at=now - timedelta(hours=1),
                newest_retained_at=now,
                retention_identity_aliases=identity_aliases,
            ),
        )
        return inventory["session_history_coverage"].get(  # type: ignore[return-value]
            "_retention_identity_aliases", []
        )

    forward = build(aliases)
    reverse = build(tuple(reversed(aliases)))

    assert forward == reverse == []


def test_duplicate_open_and_closed_session_id_is_ambiguous() -> None:
    """A stable ID with conflicting open/closed intervals is unusable evidence."""

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-dedup", 500.0, 100.0, 510.0)],
        edges=[],
        sessions=[
            {
                "session_id": "shared-copy",
                "component_id": "sig-dedup",
                "signature_fingerprint": "dedup",
                "on_edge_id": "open-edge",
                "start": "2026-08-09T10:00:00+00:00",
                "end": None,
            },
            {
                "session_id": "shared-copy",
                "component_id": "sig-dedup",
                "signature_fingerprint": "dedup",
                "on_edge_id": "closed-edge",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            },
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    load = inventory["unknown_loads"][0]
    assert load["runtime_today_minutes"] == 0.0
    assert load["current_runtime_minutes"] == 0.0
    assert load["running_state"] == "unknown"
    assert load["estimate_status_by_window"]["today"] == "ambiguous"
    assert load["runtime_windows"]["today"]["excluded_session_count"] == 1


def test_duplicate_open_and_closed_on_edge_id_is_ambiguous() -> None:
    """A shared ON edge with conflicting intervals is also unusable evidence."""

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-on-edge-dedup", 500.0, 100.0, 510.0)],
        edges=[],
        sessions=[
            {
                "session_id": "open-copy",
                "component_id": "sig-on-edge-dedup",
                "signature_fingerprint": "on-edge-dedup",
                "on_edge_id": "shared-edge",
                "start": "2026-08-09T10:00:00+00:00",
                "end": None,
            },
            {
                "session_id": "closed-copy",
                "component_id": "sig-on-edge-dedup",
                "signature_fingerprint": "on-edge-dedup",
                "on_edge_id": "shared-edge",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            },
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    load = inventory["unknown_loads"][0]
    assert load["runtime_today_minutes"] == 0.0
    assert load["running_state"] == "unknown"
    assert load["estimate_status_by_window"]["today"] == "ambiguous"
    assert load["runtime_windows"]["today"]["excluded_session_count"] == 1


def test_rebuild_keeps_component_observation_starts_separate() -> None:
    """One component's established history cannot extend another's coverage."""

    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    a_start = now - timedelta(days=31)
    b_start = now - timedelta(days=5)
    sessions = [
        {
            "session_id": "a-old",
            "component_id": "on-a",
            "signature_fingerprint": "on-a",
            "start": a_start.isoformat(),
            "end": (a_start + timedelta(minutes=30)).isoformat(),
        },
        {
            "session_id": "b-new",
            "component_id": "on-b",
            "signature_fingerprint": "on-b",
            "start": b_start.isoformat(),
            "end": (b_start + timedelta(minutes=30)).isoformat(),
        },
    ]
    coverage = NilmSessionHistoryCoverage(
        configured_max_items=2_000,
        source_count_before_retention=2,
        retained_count=2,
        was_truncated=False,
        dropped_count=0,
        oldest_retained_at=a_start,
        newest_retained_at=b_start + timedelta(minutes=30),
    )
    first = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("on-a", 500.0, 100.0, 510.0),
            signature("on-b", 900.0, 100.0, 910.0),
        ],
        edges=[],
        sessions=sessions,
        now=now,
        session_history_coverage=coverage,
    )
    second = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("on-a", 500.0, 100.0, 510.0),
            signature("on-b", 900.0, 100.0, 910.0),
        ],
        edges=[],
        sessions=sessions,
        now=now,
        session_history_coverage=coverage,
        existing_state=first,
    )

    by_signature = {
        load["on_signature_id"]: load for load in second["unknown_loads"]
    }
    assert by_signature["on-a"]["observation_started_at"] == a_start.isoformat()
    assert by_signature["on-b"]["observation_started_at"] == b_start.isoformat()


def test_partially_overlapping_closed_sessions_count_union_runtime_once() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-partial-overlap", 600.0, 100.0, 610.0)],
        edges=[],
        sessions=[
            {
                "session_id": "partial-one",
                "component_id": "sig-partial-overlap",
                "signature_fingerprint": "partial-overlap",
                "on_edge_id": "partial-edge-one",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            },
            {
                "session_id": "partial-two",
                "component_id": "sig-partial-overlap",
                "signature_fingerprint": "partial-overlap",
                "on_edge_id": "partial-edge-two",
                "start": "2026-08-09T10:30:00+00:00",
                "end": "2026-08-09T11:30:00+00:00",
            },
        ],
        now=datetime(2026, 8, 9, 13, 0, tzinfo=UTC),
    )

    load = inventory["unknown_loads"][0]
    assert load["runtime_today_minutes"] == 90.0
    assert load["estimated_energy_today_kwh"] == 0.9


def test_nested_closed_session_counts_outer_interval_once() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-nested-overlap", 600.0, 100.0, 610.0)],
        edges=[],
        sessions=[
            {
                "session_id": "outer",
                "component_id": "sig-nested-overlap",
                "signature_fingerprint": "nested-overlap",
                "on_edge_id": "outer-edge",
                "start": "2026-08-09T09:00:00+00:00",
                "end": "2026-08-09T12:00:00+00:00",
            },
            {
                "session_id": "inner",
                "component_id": "sig-nested-overlap",
                "signature_fingerprint": "nested-overlap",
                "on_edge_id": "inner-edge",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            },
        ],
        now=datetime(2026, 8, 9, 13, 0, tzinfo=UTC),
    )

    load = inventory["unknown_loads"][0]
    assert load["runtime_today_minutes"] == 180.0
    assert load["estimated_energy_today_kwh"] == 1.8


def test_session_ownership_accepts_a_matching_legacy_fingerprint() -> None:
    """A stored row's legacy fingerprint can still resolve one canonical ON owner."""

    component = signature("sig-legacy-fingerprint", 500.0, 100.0, 510.0)
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[component],
        edges=[],
        sessions=[
            {
                "session_id": "legacy-fingerprint-run",
                "component_id": "legacy-component-id",
                "signature_fingerprint": "retained-session-fingerprint",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        existing_state={
            "unknown_loads": [
                {
                    "component_id": "legacy-component-id",
                    "fingerprint": unknown_loads.nilm_signature_fingerprint(component),
                }
            ]
        },
    )

    assert inventory["unknown_loads"][0]["runtime_today_minutes"] == 60.0


def test_session_ownership_accepts_unique_computed_v1_fingerprint() -> None:
    """A unique retired v1 identity restores the matching component's history."""

    component = signature(
        "sig-computed-v1",
        500.0,
        100.0,
        510.0,
        split_phase_type="single_leg_a",
        dominant_leg="a",
        median_leg_a_delta_w=480.0,
        median_leg_b_delta_w=20.0,
        leg_balance_ratio=0.04,
    )
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[component],
        edges=[],
        sessions=[
            {
                "session_id": "computed-v1-run",
                "component_id": "retired-component-id",
                "signature_fingerprint": nilm_signature_fingerprint_v1(component),
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    load = inventory["unknown_loads"][0]
    assert load["runtime_today_minutes"] == 60.0
    assert load["estimated_energy_today_kwh"] == 0.5
    assert load["separation_status"] == "separable"


def test_session_ownership_rejects_collided_v1_fingerprint() -> None:
    """A shared retired v1 fingerprint remains excluded as ambiguous evidence."""

    first = signature(
        "sig-v1-collision-a",
        500.0,
        100.0,
        510.0,
        split_phase_type="single_leg_a",
        dominant_leg="a",
        median_leg_a_delta_w=480.0,
        median_leg_b_delta_w=20.0,
        leg_balance_ratio=0.04,
    )
    second = signature(
        "sig-v1-collision-b",
        500.0,
        100.0,
        510.0,
        split_phase_type="single_leg_a",
        dominant_leg="a",
        median_leg_a_delta_w=430.0,
        median_leg_b_delta_w=70.0,
        leg_balance_ratio=0.04,
    )
    assert nilm_signature_fingerprint_v1(first) == nilm_signature_fingerprint_v1(second)
    assert nilm_signature_fingerprint(first) != nilm_signature_fingerprint(second)

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[first, second],
        edges=[],
        sessions=[
            {
                "session_id": "collided-v1-run",
                "component_id": "retired-component-id",
                "signature_fingerprint": nilm_signature_fingerprint_v1(first),
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    for load in inventory["unknown_loads"]:
        assert load["separation_status"] == "ambiguous"
        assert load["runtime_today_minutes"] == 0.0
        assert load["estimated_energy_today_kwh"] == 0.0
        assert load["runtime_windows"]["today"]["included_session_count"] == 0


def test_unique_session_survives_raw_edge_component_ambiguity() -> None:
    """A uniquely owned session remains usable despite a contested raw edge."""

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("sig-500", 500.0, 100.0, 510.0),
            signature("sig-520", 520.0, 100.0, 510.0),
        ],
        edges=[edge(0, 510.0, var=100.0, direction="on")],
        sessions=[
            {
                "session_id": "owned-run",
                "component_id": "sig-500",
                "signature_fingerprint": "owned-session",
                "on_edge_id": "owned-edge",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    loads_by_signature_id = {
        item["signature_id"]: item for item in inventory["unknown_loads"]
    }
    load = loads_by_signature_id["sig-500"]
    assert load["ambiguous_edge_count"] == 1
    assert load["separation_status"] == "separable"
    assert load["runtime_today_minutes"] == 60.0
    assert load["estimated_energy_today_kwh"] == 0.5
    assert load["running_state"] == "probably_off"
    assert load["runtime_windows"]["today"]["included_session_count"] == 1

    sessionless_load = loads_by_signature_id["sig-520"]
    assert sessionless_load["ambiguous_edge_count"] == 1
    assert sessionless_load["separation_status"] == "ambiguous"
    assert sessionless_load["runtime_today_minutes"] == 0.0
    assert sessionless_load["estimated_energy_today_kwh"] == 0.0
    assert sessionless_load["runtime_windows"]["today"]["included_session_count"] == 0


def test_session_evidence_does_not_override_ambiguous_signature_pairing() -> None:
    """Session ownership cannot make an ambiguously paired signature separable."""

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("on-load", 500.0, 100.0, 510.0),
            signature("off-first", -500.0, -100.0, 510.0),
            signature("off-second", -500.0, -100.0, 510.0),
        ],
        edges=[],
        sessions=[
            {
                "session_id": "owned-run",
                "component_id": "on-load",
                "signature_fingerprint": "owned-session",
                "on_edge_id": "owned-edge",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    load = inventory["unknown_loads"][0]
    assert load["signature_pair_status"] == "ambiguous"
    assert load["separation_status"] == "ambiguous"
    assert load["runtime_today_minutes"] == 0.0
    assert load["estimated_energy_today_kwh"] == 0.0
    assert load["runtime_windows"]["today"]["included_session_count"] == 0


def test_multiple_open_sessions_make_current_runtime_ambiguous() -> None:
    """Two distinct active runs cannot be represented as one current runtime."""

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-open", 500.0, 100.0, 510.0)],
        edges=[],
        sessions=[
            {
                "session_id": "open-one",
                "component_id": "sig-open",
                "signature_fingerprint": "open",
                "on_edge_id": "edge-one",
                "start": "2026-08-09T10:00:00+00:00",
                "end": None,
            },
            {
                "session_id": "open-two",
                "component_id": "sig-open",
                "signature_fingerprint": "open",
                "on_edge_id": "edge-two",
                "start": "2026-08-09T11:00:00+00:00",
                "end": None,
            },
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    load = inventory["unknown_loads"][0]
    assert load["running_state"] == "unknown"
    assert load["current_runtime_minutes"] == 0.0
    assert load["runtime_today_minutes"] == 0.0
    assert load["estimate_status"] == "ambiguous"


def test_estimate_unknown_load_marks_reactive_signature_as_motor() -> None:
    result = estimate_unknown_load(
        signature(
            "sig-motor-b",
            520.0,
            330.0,
            616.0,
            delta_pf=-0.14,
            occurrence_count=5,
            confidence=0.74,
            split_phase_type="single_leg_b",
            dominant_leg="b",
        )
    )

    assert {
        "signature_id",
        "display_name",
        "likely_type",
        "voltage_class",
        "split_phase_type",
        "dominant_leg",
        "typical_watts",
        "typical_var",
        "typical_va",
        "typical_power_factor",
        "confidence",
        "occurrence_count",
        "evidence",
    } <= result.keys()
    assert result["signature_id"] == "sig-motor-b"
    assert result["likely_type"] == "motor"
    assert result["voltage_class"] == "120 V"
    assert result["split_phase_type"] == "single_leg_b"
    assert result["dominant_leg"] == "b"
    assert result["typical_watts"] == 520.0
    assert result["typical_var"] == 330.0
    assert result["typical_va"] == 616.0
    assert result["typical_power_factor"] == 0.844
    assert result["confidence"] == 0.74
    assert result["occurrence_count"] == 5
    assert "possible" in " ".join(result["evidence"]).lower()
    assert "diagnosis" not in result["display_name"].lower()


def test_estimate_unknown_load_marks_balanced_low_var_as_heat_candidate() -> None:
    result = estimate_unknown_load(
        signature(
            "sig-heat",
            4300.0,
            90.0,
            4310.0,
            delta_pf=0.01,
            occurrence_count=6,
            confidence=0.86,
            split_phase_type="balanced_240v",
            dominant_leg="balanced",
        )
    )

    assert result["likely_type"] == "heating_element_candidate"
    assert result["voltage_class"] == "240 V"
    assert result["dominant_leg"] == "balanced"
    assert result["typical_power_factor"] == 0.998
    assert "candidate" in result["display_name"].lower()
    assert "candidate" in " ".join(result["evidence"]).lower()


def test_estimate_unknown_load_marks_reactive_va_as_power_electronics() -> None:
    result = estimate_unknown_load(
        signature(
            "sig-electronics",
            180.0,
            190.0,
            265.0,
            delta_pf=-0.22,
            occurrence_count=4,
            confidence=0.66,
            split_phase_type="imbalanced_240v_or_mixed",
            dominant_leg="mixed",
        )
    )

    assert result["likely_type"] == "power_electronics"
    assert result["voltage_class"] == "mixed"
    assert result["typical_watts"] == 180.0
    assert result["typical_var"] == 190.0
    assert result["typical_va"] == 265.0
    assert result["typical_power_factor"] == 0.679
    assert "possible" in " ".join(result["evidence"]).lower()


def test_estimate_unknown_load_leaves_low_evidence_signature_unknown() -> None:
    result = estimate_unknown_load(
        signature(
            "sig-low-evidence",
            420.0,
            260.0,
            500.0,
            delta_pf=-0.18,
            occurrence_count=1,
            confidence=0.35,
            split_phase_type="single_leg_a",
            dominant_leg="a",
        )
    )

    assert result["likely_type"] == "unknown"
    assert result["voltage_class"] == "120 V"
    assert result["confidence"] == 0.35
    assert result["occurrence_count"] == 1
    assert "limited" in " ".join(result["evidence"]).lower()


def test_build_unknown_load_inventory_tracks_multiple_loads_separately() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature(
                "sig-resistive",
                300.0,
                15.0,
                301.0,
                occurrence_count=5,
                confidence=0.8,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            signature(
                "sig-motor",
                900.0,
                520.0,
                1040.0,
                delta_pf=-0.2,
                occurrence_count=6,
                confidence=0.85,
                split_phase_type="single_leg_b",
                dominant_leg="b",
            ),
        ],
        edges=[
            edge(0, 300.0, direction="on"),
            edge(30, -300.0, direction="off"),
            edge(
                60,
                900.0,
                var=520.0,
                direction="on",
                split_phase_type="single_leg_b",
                dominant_leg="b",
            ),
            edge(
                120,
                -900.0,
                var=-520.0,
                direction="off",
                split_phase_type="single_leg_b",
                dominant_leg="b",
            ),
        ],
        now=BASE_TIME + timedelta(hours=3),
        existing_state={},
    )

    assert inventory["unknown_load_count"] == 2
    assert inventory["active_unknown_load_count"] == 0
    assert inventory["ambiguous_unknown_load_count"] == 0
    assert inventory["unknown_estimated_energy_today_kwh"] == 1.05
    by_id = {load["signature_id"]: load for load in inventory["unknown_loads"]}
    assert by_id["sig-resistive"]["voltage_class"] == "120 V"
    assert by_id["sig-resistive"]["runtime_today_minutes"] == 30.0
    assert by_id["sig-resistive"]["estimated_energy_today_kwh"] == 0.15
    assert by_id["sig-motor"]["dominant_leg"] == "b"
    assert by_id["sig-motor"]["runtime_today_minutes"] == 60.0
    assert by_id["sig-motor"]["estimated_energy_today_kwh"] == 0.9
    assert by_id["sig-motor"]["running_state"] == "probably_off"


def test_build_unknown_load_inventory_tracks_currently_running_load() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature(
                "sig-running",
                600.0,
                360.0,
                700.0,
                occurrence_count=5,
                confidence=0.8,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            )
        ],
        edges=[edge(0, 600.0, var=360.0, direction="on")],
        now=BASE_TIME + timedelta(minutes=45),
        existing_state={},
    )

    load = inventory["unknown_loads"][0]
    assert inventory["active_unknown_load_count"] == 1
    assert load["running_state"] == "probably_on"
    assert load["current_runtime_minutes"] == 45.0
    assert load["estimated_energy_today_kwh"] == 0.45


def test_edge_compatible_inventory_includes_window_metadata() -> None:
    """Simple edge callers remain current-schema inventories after the metadata bump."""

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-edge-metadata", 500.0, 100.0, 510.0)],
        edges=[edge(0, 500.0, var=100.0, direction="on")],
        now=BASE_TIME + timedelta(minutes=30),
    )

    assert inventory["schema_version"] == 4
    assert inventory["runtime_window_definition"]["7_days"] == (
        "trailing_168_elapsed_hours_to_now"
    )
    assert inventory["unknown_loads"][0]["runtime_windows"]["today"][
        "estimate_status"
    ] == "partial_history"
    assert not unknown_loads.unknown_load_inventory_needs_rebuild(inventory)


def test_session_backed_builder_without_coverage_is_stable_and_current() -> None:
    """Direct public builders provide accepted retained-history provenance."""

    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    component = signature("sig-direct-session", 500.0, 100.0, 510.0)
    sessions = [
        {
            "session_id": "direct-run",
            "component_id": "sig-direct-session",
            "signature_fingerprint": "direct-session",
            "start": (now - timedelta(days=31)).isoformat(),
            "end": (now - timedelta(days=31, minutes=-30)).isoformat(),
        }
    ]
    first = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[component],
        edges=[],
        sessions=sessions,
        now=now,
    )
    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state=first,
        signature_payloads=[
            {
                "signature_id": component.signature_id,
                "median_delta_w": component.median_delta_w,
                "median_delta_var": component.median_delta_var,
                "median_delta_va": component.median_delta_va,
                "occurrence_count": component.occurrence_count,
                "confidence": component.confidence,
            }
        ],
        sessions=sessions,
        now=now,
    )

    assert first["estimate_provenance"] == "retained_session_history"
    assert first["session_history_coverage"]["source_count_before_retention"] == 1
    assert not unknown_loads.unknown_load_inventory_needs_rebuild(first)
    assert not unknown_loads.unknown_load_inventory_needs_rebuild(migrated)
    assert migrated["estimate_provenance"] == "retained_session_history"


def test_build_unknown_load_inventory_marks_overlapping_events_ambiguous() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("sig-a", 500.0, 100.0, 510.0),
            signature("sig-b", 540.0, 110.0, 551.0),
        ],
        edges=[edge(0, 500.0), edge(0, 540.0)],
        now=BASE_TIME + timedelta(minutes=10),
        existing_state={},
    )

    assert inventory["unknown_load_count"] == 2
    assert inventory["ambiguous_unknown_load_count"] == 2
    assert inventory["simultaneous_unknown_event_count"] == 2
    assert all(
        load["separation_status"] == "ambiguous"
        for load in inventory["unknown_loads"]
    )
    assert all(
        load["running_state"] == "unknown" for load in inventory["unknown_loads"]
    )
    assert all(
        load["estimated_energy_today_kwh"] == 0.0
        for load in inventory["unknown_loads"]
    )


def test_negative_or_conflicted_signatures_never_own_unknown_components() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("sig-negative", -500.0, -100.0, 510.0),
            signature("off-conflict", 500.0, 100.0, 510.0),
        ],
        edges=[
            edge(0, -500.0, var=-100.0, direction="off"),
            edge(10, 500.0, var=100.0, direction="on"),
        ],
        now=BASE_TIME + timedelta(minutes=20),
    )

    assert inventory["unknown_load_count"] == 0
    assert inventory["largest_unknown_load"] is None
    assert inventory["unknown_loads"] == []


def test_positive_only_component_uses_negative_edge_fallback() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-positive-only", 500.0, 100.0, 510.0)],
        edges=[
            edge(0, 500.0, var=100.0, direction="on"),
            edge(30, -500.0, var=-100.0, direction="off"),
        ],
        now=BASE_TIME + timedelta(minutes=40),
    )

    load = inventory["unknown_loads"][0]
    assert load["signature_pair_status"] == "on_only"
    assert load["off_signature_id"] is None
    assert load["matched_on_edge_count"] == 1
    assert load["matched_off_edge_count"] == 1
    assert load["runtime_today_minutes"] == 30.0
    assert load["estimated_energy_today_kwh"] == 0.25


def test_paired_off_edges_use_the_off_signature_prototype() -> None:
    on_signature = signature("on-prototype", 500.0, 100.0, 510.0)
    off_signature = signature("off-prototype", -550.0, -150.0, 570.0)
    component = unknown_loads._unknown_load_components(
        [on_signature, off_signature]
    )[0]

    score = unknown_loads._component_edge_score(
        component,
        edge(0, -550.0, var=-150.0, direction="off"),
    )

    assert component.off_signature == off_signature
    assert score is not None
    assert score > 0.99


def test_off_signatures_pair_with_topology_compatible_on_owner() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature(
                "on-a",
                500.0,
                100.0,
                510.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            signature(
                "on-b",
                500.0,
                100.0,
                510.0,
                split_phase_type="single_leg_b",
                dominant_leg="b",
            ),
            signature(
                "off-a",
                -500.0,
                -100.0,
                510.0,
                split_phase_type="single_leg_a",
                dominant_leg="a",
            ),
            signature(
                "off-b",
                -500.0,
                -100.0,
                510.0,
                split_phase_type="single_leg_b",
                dominant_leg="b",
            ),
        ],
        edges=[],
        now=BASE_TIME,
    )

    by_id = {load["signature_id"]: load for load in inventory["unknown_loads"]}
    assert by_id["on-a"]["off_signature_id"] == "off-a"
    assert by_id["on-b"]["off_signature_id"] == "off-b"


def test_close_off_pairing_is_marked_ambiguous_without_a_winner() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("on-load", 500.0, 100.0, 510.0),
            signature("off-first", -500.0, -100.0, 510.0),
            signature("off-second", -500.0, -100.0, 510.0),
        ],
        edges=[edge(0, 500.0, var=100.0, direction="on")],
        now=BASE_TIME + timedelta(minutes=30),
    )

    load = inventory["unknown_loads"][0]
    assert load["signature_pair_status"] == "ambiguous"
    assert load["off_signature_id"] is None
    assert load["alternate_signature_pair_count"] == 1
    assert load["running_state"] == "unknown"
    assert load["estimated_energy_today_kwh"] == 0.0


def test_close_component_competition_leaves_edge_unallocated() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("sig-500", 500.0, 100.0, 510.0),
            signature("sig-520", 520.0, 100.0, 510.0),
        ],
        edges=[edge(0, 510.0, var=100.0, direction="on")],
        now=BASE_TIME + timedelta(minutes=30),
    )

    assert inventory["ambiguous_unknown_load_count"] == 2
    assert inventory["unknown_estimated_energy_today_kwh"] == 0.0
    assert all(
        load["matched_on_edge_count"] == 0
        and load["separation_status"] == "ambiguous"
        for load in inventory["unknown_loads"]
    )


def test_canonical_on_review_state_wins_over_paired_off_duplicate() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("on-review", 500.0, 100.0, 510.0),
            signature("off-review", -500.0, -100.0, 510.0),
        ],
        edges=[
            edge(0, 500.0, var=100.0, direction="on"),
            edge(30, -500.0, var=-100.0, direction="off"),
        ],
        now=BASE_TIME + timedelta(minutes=40),
        existing_state={
            "unknown_loads": [
                {"signature_id": "on-review", "review_state": "assigned"},
                {"signature_id": "off-review", "review_state": "ignored"},
            ]
        },
    )

    assert inventory["unknown_load_count"] == 1
    assert inventory["unknown_loads"][0]["review_state"] == "assigned"


def test_metadata_migration_deduplicates_proven_off_row_without_edges() -> None:
    existing_state = {
        "circuit_id": "mains",
        "unknown_loads": [
            {
                "signature_id": "on-legacy",
                "typical_watts": 500.0,
                "split_phase_type": "single_leg_a",
                "review_state": "assigned",
                "first_seen": BASE_TIME.isoformat(),
                "last_seen": (BASE_TIME + timedelta(minutes=60)).isoformat(),
                "runtime_today_minutes": 60.0,
                "runtime_7_days_minutes": 60.0,
                "runtime_30_days_minutes": 60.0,
                "estimated_energy_today_kwh": 0.5,
                "estimated_energy_7_days_kwh": 0.5,
                "estimated_energy_30_days_kwh": 0.5,
                "running_state": "probably_off",
            },
            {
                "signature_id": "off-legacy",
                "typical_watts": 500.0,
                "split_phase_type": "single_leg_a",
                "review_state": "ignored",
                "runtime_today_minutes": 60.0,
                "estimated_energy_today_kwh": 0.5,
            },
        ],
    }
    signature_payloads = [
        {
            "signature_id": "on-legacy",
            "median_delta_w": 500.0,
            "median_delta_var": 100.0,
            "median_delta_va": 510.0,
            "median_delta_pf": 0.0,
            "occurrence_count": 3,
            "confidence": 0.6,
            "split_phase_type": "single_leg_a",
            "dominant_leg": "a",
        },
        {
            "signature_id": "off-legacy",
            "median_delta_w": -500.0,
            "median_delta_var": -100.0,
            "median_delta_va": 510.0,
            "median_delta_pf": 0.0,
            "occurrence_count": 3,
            "confidence": 0.6,
            "split_phase_type": "single_leg_a",
            "dominant_leg": "a",
        },
    ]

    assert unknown_loads.unknown_load_inventory_needs_rebuild(existing_state)
    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state=existing_state,
        signature_payloads=signature_payloads,
    )

    assert migrated["schema_version"] == 4
    assert migrated["unknown_load_count"] == 1
    assert migrated["unknown_estimated_energy_today_kwh"] == 0.5
    load = migrated["unknown_loads"][0]
    assert load["signature_id"] == "on-legacy"
    assert load["component_id"] == "on-legacy"
    assert load["off_signature_id"] == "off-legacy"
    assert load["review_state"] == "assigned"
    assert load["runtime_today_minutes"] == 60.0
    assert load["estimated_energy_today_kwh"] == 0.5


def test_metadata_migration_preserves_unclassifiable_legacy_row_once() -> None:
    existing_state = {
        "circuit_id": "mains",
        "unknown_loads": [
            {
                "display_name": "Legacy unknown load",
                "estimated_energy_today_kwh": "unavailable",
                "review_state": "new",
            }
        ],
    }

    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state=existing_state,
        signature_payloads=[],
    )

    assert migrated["schema_version"] == 4
    assert migrated["unknown_load_count"] == 1
    assert migrated["unknown_estimated_energy_today_kwh"] == 0.0
    assert migrated["largest_unknown_load"] is None
    assert migrated["unknown_loads"][0]["display_name"] == "Legacy unknown load"
    assert migrated["unknown_loads"][0]["legacy_identity_unresolved"] is True
    assert not unknown_loads.unknown_load_inventory_needs_rebuild(migrated)


def test_unique_paired_off_row_restores_review_state_when_on_row_is_missing() -> None:
    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[
            signature("on-review-fallback", 500.0, 100.0, 510.0),
            signature("off-review-fallback", -500.0, -100.0, 510.0),
        ],
        edges=[
            edge(0, 500.0, var=100.0, direction="on"),
            edge(30, -500.0, var=-100.0, direction="off"),
        ],
        now=BASE_TIME + timedelta(minutes=40),
        existing_state={
            "unknown_loads": [
                {
                    "signature_id": "off-review-fallback",
                    "review_state": "assigned",
                }
            ]
        },
    )

    assert inventory["unknown_loads"][0]["review_state"] == "assigned"


def test_migration_recomputes_windowed_values_when_sessions_are_available() -> None:
    """Migration must retain review identity while replacing stale numeric estimates."""

    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state={
            "unknown_loads": [
                {
                    "signature_id": "sig-migrate",
                    "review_state": "assigned",
                    "user_label": "Basement load",
                    "runtime_today_minutes": 999.0,
                }
            ]
        },
        signature_payloads=[
            {
                "signature_id": "sig-migrate",
                "median_delta_w": 500.0,
                "median_delta_var": 100.0,
                "median_delta_va": 510.0,
                "occurrence_count": 4,
                "confidence": 0.7,
            }
        ],
        sessions=[
            {
                "session_id": "migrated-run",
                "component_id": "sig-migrate",
                "signature_fingerprint": "migrate",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    load = migrated["unknown_loads"][0]
    assert migrated["schema_version"] == 4
    assert load["review_state"] == "assigned"
    assert load["user_label"] == "Basement load"
    assert load["runtime_today_minutes"] == 60.0


def test_migration_preserves_v2_leg_fingerprint_for_session_ownership() -> None:
    """Migration must retain v2 leg fields used to own persisted sessions."""

    producer_signature = NilmSignature(
        signature_id="sig-v2-legs",
        median_delta_w=500.0,
        median_delta_var=100.0,
        median_delta_va=510.0,
        median_delta_pf=0.0,
        occurrence_count=4,
        confidence=0.7,
        dominant_leg="a",
        split_phase_type="single_leg_a",
        median_leg_a_delta_w=480.0,
        median_leg_b_delta_w=20.0,
        leg_balance_ratio=0.04,
    )
    fingerprint = nilm_signature_fingerprint(producer_signature)

    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state={},
        signature_payloads=[
            {
                "signature_id": "sig-v2-legs",
                "median_delta_w": 500.0,
                "median_delta_var": 100.0,
                "median_delta_va": 510.0,
                "median_delta_pf": 0.0,
                "occurrence_count": 4,
                "confidence": 0.7,
                "dominant_leg": "a",
                "split_phase_type": "single_leg_a",
                "median_leg_a_delta_w": 480.0,
                "median_leg_b_delta_w": 20.0,
                "leg_balance_ratio": 0.04,
            }
        ],
        sessions=[
            {
                "session_id": "v2-leg-session",
                "component_id": "legacy-component-id",
                "signature_fingerprint": fingerprint,
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    load = migrated["unknown_loads"][0]
    assert load["component_fingerprint"] == fingerprint
    assert load["runtime_today_minutes"] == 60.0
    assert load["estimated_energy_today_kwh"] == 0.5
    assert load["runtime_windows"]["today"]["included_session_count"] == 1


def test_migration_preserves_v2_fingerprint_when_older_payload_omits_leg_fields(
) -> None:
    """Missing v2 leg fields retain the producer fingerprint used by sessions."""

    producer_signature = NilmSignature(
        signature_id="sig-v2-no-legs",
        median_delta_w=500.0,
        median_delta_var=100.0,
        median_delta_va=510.0,
        median_delta_pf=0.0,
        occurrence_count=4,
        confidence=0.7,
        dominant_leg="a",
        split_phase_type="single_leg_a",
        median_leg_a_delta_w=None,
        median_leg_b_delta_w=None,
        leg_balance_ratio=None,
    )
    fingerprint = nilm_signature_fingerprint(producer_signature)

    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state={},
        signature_payloads=[
            {
                "signature_id": "sig-v2-no-legs",
                "median_delta_w": 500.0,
                "median_delta_var": 100.0,
                "median_delta_va": 510.0,
                "median_delta_pf": 0.0,
                "occurrence_count": 4,
                "confidence": 0.7,
                "dominant_leg": "a",
                "split_phase_type": "single_leg_a",
            }
        ],
        sessions=[
            {
                "session_id": "v2-no-leg-session",
                "component_id": "retired-component-id",
                "signature_fingerprint": fingerprint,
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    load = migrated["unknown_loads"][0]
    assert load["component_fingerprint"] == fingerprint
    assert load["runtime_today_minutes"] == 60.0
    assert load["estimated_energy_today_kwh"] == 0.5
    assert load["runtime_windows"]["today"]["included_session_count"] == 1


def test_session_migration_preserves_legacy_rows_missing_current_components() -> None:
    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state={
            "unknown_loads": [
                {"signature_id": "sig-current", "review_state": "assigned"},
                {
                    "signature_id": "sig-missing",
                    "review_state": "labeled",
                    "user_label": "Legacy workshop load",
                    "estimated_energy_today_kwh": 0.25,
                },
            ]
        },
        signature_payloads=[
            {
                "signature_id": "sig-current",
                "median_delta_w": 500.0,
                "median_delta_var": 100.0,
                "median_delta_va": 510.0,
                "occurrence_count": 4,
                "confidence": 0.7,
            }
        ],
        sessions=[
            {
                "session_id": "current-run",
                "component_id": "sig-current",
                "signature_fingerprint": "current-fingerprint",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    by_signature = {
        load["signature_id"]: load for load in migrated["unknown_loads"]
    }
    assert migrated["unknown_load_count"] == 2
    assert by_signature["sig-current"]["runtime_today_minutes"] == 60.0
    assert by_signature["sig-missing"]["user_label"] == "Legacy workshop load"
    assert by_signature["sig-missing"]["estimate_status"] == "legacy_unverified"
    assert migrated["estimate_status"] == "legacy_unverified"


def test_session_migration_retains_legacy_row_when_no_component_is_classifiable(
) -> None:
    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state={
            "unknown_loads": [
                {
                    "signature_id": "sig-legacy-only",
                    "review_state": "assigned",
                    "user_label": "Unresolved legacy load",
                    "estimated_energy_today_kwh": 0.5,
                }
            ]
        },
        signature_payloads=[],
        sessions=[
            {
                "session_id": "unowned-run",
                "component_id": "removed-component",
                "signature_fingerprint": "removed-fingerprint",
                "start": "2026-08-09T10:00:00+00:00",
                "end": "2026-08-09T11:00:00+00:00",
            }
        ],
        now=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )

    assert migrated["unknown_load_count"] == 1
    assert migrated["unknown_loads"][0]["signature_id"] == "sig-legacy-only"
    assert migrated["unknown_loads"][0]["review_state"] == "assigned"
    assert migrated["estimate_status"] == "legacy_unverified"


def test_migration_without_sessions_marks_numeric_estimates_legacy_unverified() -> None:
    """Legacy values remain visible when their source sessions are unavailable."""

    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state={
            "unknown_loads": [
                {
                    "signature_id": "sig-legacy-status",
                    "typical_watts": 500.0,
                    "runtime_today_minutes": 60.0,
                    "estimated_energy_today_kwh": 0.5,
                    "review_state": "new",
                }
            ]
        },
        signature_payloads=[
            {
                "signature_id": "sig-legacy-status",
                "median_delta_w": 500.0,
                "median_delta_var": 100.0,
                "median_delta_va": 510.0,
                "occurrence_count": 4,
                "confidence": 0.7,
            }
        ],
    )

    assert migrated["unknown_loads"][0]["estimate_status"] == "legacy_unverified"
    assert migrated["estimate_status"] == "legacy_unverified"
    assert not unknown_loads.unknown_load_inventory_needs_rebuild(migrated)


def test_edge_only_inventory_treats_naive_legacy_timestamps_as_utc() -> None:
    """Legacy naive edge timestamps must not be compared directly to aware now."""

    inventory = build_unknown_load_inventory(
        circuit_id="mains",
        signatures=[signature("sig-naive-edge", 500.0, 100.0, 510.0)],
        edges=[
            NilmEdge(
                timestamp=datetime(2026, 6, 7, 12, 0),
                delta_w=500.0,
                delta_var=100.0,
                delta_va=510.0,
                delta_pf=0.0,
                direction="on",
                split_phase_type="single_leg_a",
                dominant_leg="a",
            )
        ],
        now=BASE_TIME + timedelta(minutes=30),
    )

    assert inventory["unknown_loads"][0]["runtime_today_minutes"] == 30.0


def test_migration_uses_earliest_per_load_observation_boundary() -> None:
    """A top-level omission must not discard reliable row-level first-seen evidence."""

    migrated = unknown_loads.migrate_unknown_load_inventory(
        circuit_id="mains",
        existing_state={
            "unknown_loads": [
                {
                    "signature_id": "sig-row-observation",
                    "typical_watts": 500.0,
                    "first_seen": "2026-06-01T00:00:00+00:00",
                    "runtime_today_minutes": 60.0,
                }
            ]
        },
        signature_payloads=[
            {
                "signature_id": "sig-row-observation",
                "median_delta_w": 500.0,
                "median_delta_var": 100.0,
                "median_delta_va": 510.0,
                "occurrence_count": 4,
                "confidence": 0.7,
            }
        ],
    )

    assert migrated["observation_started_at"] == "2026-06-01T00:00:00+00:00"
    assert migrated["unknown_loads"][0]["observation_started_at"] == (
        "2026-06-01T00:00:00+00:00"
    )


def test_stale_check_requires_metadata_for_unresolved_legacy_rows() -> None:
    """Opaque rows cannot bypass the schema-v3 runtime-window metadata contract."""

    state = {
        "schema_version": 3,
        "runtime_window_definition": {
            "today": "configured_local_midnight_to_now",
            "7_days": "trailing_168_elapsed_hours_to_now",
            "30_days": "trailing_720_elapsed_hours_to_now",
        },
        "estimate_status": "legacy_unverified",
        "unknown_loads": [{"legacy_identity_unresolved": True}],
    }

    assert unknown_loads.unknown_load_inventory_needs_rebuild(state)
