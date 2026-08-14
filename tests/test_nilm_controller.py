from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.circuitsetup_energy_analyzer.managers.nilm_controller import (
    NilmController,
    configured_primary_assignment_id,
    nilm_assignment_publication_reason,
)
from custom_components.circuitsetup_energy_analyzer.managers.store_persistence import (
    StorePersistenceManager,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    AlertEvidence,
    ApplianceProfile,
    CircuitConfig,
    CircuitEvent,
    CircuitMode,
    CircuitSample,
    EventType,
    NilmSourceKind,
    PowerFlowMode,
    Severity,
)
from custom_components.circuitsetup_energy_analyzer.nilm import (
    build_nilm_assignment_model,
    build_nilm_validation_profile,
)
from custom_components.circuitsetup_energy_analyzer.profiles import nilm_source_kind
from custom_components.circuitsetup_energy_analyzer.storage import (
    FeatureStoreData,
    feature_store_data_from_dict,
    feature_store_data_to_dict,
)


def test_off_only_nilm_assignment_cannot_publish() -> None:
    assert (
        nilm_assignment_publication_reason(
            {
                "assignment_id": "assignment-pump",
                "lifecycle_state": "published",
                "publish_entities": True,
                "signature_fingerprints": [
                    "direction=off|watts=0-100|var=0-100|va=0-100|pf=unknown|"
                    "split=unknown|leg=unknown|balance=unknown",
                    "unassigned",
                ],
            }
        )
        == (
        "A complete appliance run is still missing. Confirm one session with "
        "both the power-on and matching power-off transition so NILM can track "
        "state and energy before publishing."
        )
    )


def test_reviewed_on_off_model_requires_canonical_readiness_before_publish() -> None:
    reason = nilm_assignment_publication_reason(
        {
            "assignment_id": "assignment-pump",
            "lifecycle_state": "assigned",
            "signature_fingerprints": ["direction=off|watts=0-100"],
            "session_ids": ["session-complete"],
            "confidence": 0.85,
            "transition_prototypes": [
                {
                    "direction": direction,
                    "from_state_w": from_w,
                    "to_state_w": to_w,
                    "delta_w": delta_w,
                    "spread_w": 0.0,
                    "sample_count": 1,
                }
                for direction, from_w, to_w, delta_w in (
                    ("on", 0.0, 82.0, 82.0),
                    ("off", 82.0, 0.0, -82.0),
                )
            ],
        }
    )

    assert reason is not None


@pytest.mark.asyncio
async def test_synthetic_unassigned_session_cannot_be_assigned() -> None:
    controller = _nilm_controller(object())

    with pytest.raises(ValueError, match="complete detected component"):
        await controller.async_assign_nilm_session(
            "mains",
            "session-unassigned",
            label="Pump",
            signature_fingerprint="unassigned",
        )


@pytest.mark.asyncio
async def test_ambiguous_session_cannot_be_assigned_or_validated() -> None:
    """Direct service calls cannot turn read-only ambiguity into feedback."""
    controller = _nilm_controller(
        SimpleNamespace(
            store_data=FeatureStoreData(
                nilm_appliance_assignments_by_circuit={
                    "mains": [
                        {
                            "assignment_id": "assignment-pump",
                            "session_ids": ["session-ambiguous"],
                        }
                    ]
                },
                nilm_session_history_by_circuit={
                    "mains": [
                        {
                            "session_id": "session-ambiguous",
                            "ambiguous": True,
                        }
                    ]
                },
            )
        )
    )

    with pytest.raises(ValueError, match="(?i)ambiguous"):
        await controller.async_assign_nilm_session(
            "mains",
            "session-ambiguous",
            label="Pump",
        )
    with pytest.raises(ValueError, match="(?i)ambiguous"):
        await controller.async_validate_nilm_session(
            "mains",
            "session-ambiguous",
            assignment_id="assignment-pump",
        )


def test_ambiguous_finished_alert_feedback_is_rejected() -> None:
    """A stale ambiguous finished alert cannot mutate its assignment."""
    assignment = {
        "assignment_id": "assignment-pump",
    }
    controller = _nilm_controller(
        SimpleNamespace(
            store_data=FeatureStoreData(
                nilm_appliance_assignments_by_circuit={"mains": [assignment]},
                nilm_session_history_by_circuit={
                    "mains": [{
                        "session_id": "session-ambiguous",
                        "assignment_id": "assignment-pump",
                        "ambiguous": True,
                    }]
                },
            )
        )
    )
    alert = AlertEvidence(
        timestamp=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        circuit_id="mains",
        severity=Severity.INFO,
        message="Pump: a detected estimated run ended.",
        feature="nilm_appliance_finished",
        features={
            "source": "nilm",
            "assignment_id": "assignment-pump",
            "notification_key": "assignment-pump:session-ambiguous",
        },
    )

    with pytest.raises(ValueError, match="(?i)ambiguous"):
        controller.apply_alert_feedback(
            alert,
            "correct",
            datetime(2026, 8, 12, 12, 5, tzinfo=UTC),
        )

    assert assignment == {"assignment_id": "assignment-pump"}


def test_duplicate_finished_alert_feedback_is_idempotent_and_auditable() -> None:
    assignment = {
        "assignment_id": "assignment-pump",
        "lifecycle_state": "validated",
    }
    controller = _nilm_controller(
        SimpleNamespace(
            store_data=FeatureStoreData(
                nilm_appliance_assignments_by_circuit={"mains": [assignment]},
                nilm_session_history_by_circuit={
                    "mains": [
                        {
                            "session_id": "session-finished",
                            "assignment_id": "assignment-pump",
                            "ambiguous": False,
                        }
                    ]
                },
            )
        )
    )
    alert = AlertEvidence(
        timestamp=datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        circuit_id="mains",
        severity=Severity.INFO,
        message="Pump: a detected estimated run ended.",
        feature="nilm_appliance_finished",
        features={
            "source": "nilm",
            "assignment_id": "assignment-pump",
            "notification_key": "assignment-pump:session-finished",
        },
    )

    controller.apply_alert_feedback(alert, "correct", alert.timestamp)
    controller.apply_alert_feedback(alert, "correct", alert.timestamp)

    assert "confidence" not in assignment
    assert assignment["feedback_evidence_score"] == 0.05
    assert assignment["feedback_confirmed_count"] == 1
    assert assignment["feedback_evidence_events"] == [
        {
            "feedback_id": "session:session-finished",
            "outcome": "correct",
            "delta": 0.05,
            "timestamp": "2026-08-12T12:00:00+00:00",
            "score_after": 0.05,
        }
    ]


@pytest.mark.asyncio
async def test_history_validation_rejects_ambiguous_session_only() -> None:
    """Bulk validation cannot turn ambiguity into assignment feedback."""
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "assignment-pump",
        "session_ids": ["session-ambiguous"],
    }
    store_data = FeatureStoreData(
        nilm_appliance_assignments_by_circuit={"mains": [assignment]},
        nilm_label_intervals_by_circuit={
            "mains": [
                {
                    "interval_id": "interval-pump",
                    "assignment_id": "assignment-pump",
                    "ground_truth_entity_id": "sensor.pump_power",
                    "start": now.isoformat(),
                    "end": (now + timedelta(minutes=10)).isoformat(),
                }
            ]
        },
        nilm_session_history_by_circuit={
            "mains": [
                {
                    "session_id": "session-ambiguous",
                    "assignment_id": "assignment-pump",
                    "start": now.isoformat(),
                    "end": (now + timedelta(minutes=10)).isoformat(),
                    "ambiguous": True,
                }
            ]
        },
    )
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=store_data,
        state=SimpleNamespace(),
        async_set_updated_data=lambda _state: None,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
    )
    controller = NilmController(
        coordinator,
        label_interval_max_items=10,
        assignment_max_items=10,
    )
    before = deepcopy(store_data)

    with pytest.raises(ValueError, match="(?i)non-ambiguous"):
        await controller.async_validate_nilm_assignment_history(
            "mains", "assignment-pump"
        )

    assert store_data == before
    assert "confirmed_session_ids" not in assignment
    assert "rejected_session_ids" not in assignment


def test_nilm_controller_filters_known_load_events_from_registry() -> None:
    mains_config = SimpleNamespace(
        mode=CircuitMode.MAINS_NILM,
        appliance_profile=ApplianceProfile.MAINS_NILM,
    )
    controller = _nilm_controller(
        SimpleNamespace(
            circuit_registry=SimpleNamespace(
                known_load_circuit_ids=frozenset({"fridge"}),
                config_for_circuit=lambda _circuit_id: mains_config,
            ),
        )
    )
    timestamp = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    events = [
        CircuitEvent(timestamp, "mains", EventType.START),
        CircuitEvent(
            timestamp,
            "fridge",
            EventType.POWER_TRANSITION,
            features={"transition_delta_w": 100.0},
        ),
        CircuitEvent(timestamp, "hvac", EventType.START),
    ]

    assert [
        event.circuit_id for event in controller.known_load_events("mains", events)
    ] == ["fridge"]


def test_nilm_controller_keeps_detector_transition_for_masking_but_not_helpers(
) -> None:
    from custom_components.circuitsetup_energy_analyzer.operating_detection import (
        OperatingDetectionProfile,
        OperatingStateMachine,
        OperatingThresholdSource,
        ResolvedOperatingDetection,
    )

    mains_config = SimpleNamespace(
        mode=CircuitMode.MAINS_NILM,
        appliance_profile=ApplianceProfile.MAINS_NILM,
    )
    direct_config = _config(ApplianceProfile.HVAC_BLOWER)
    controller = _nilm_controller(
        SimpleNamespace(
            circuit_registry=SimpleNamespace(
                known_load_circuit_ids=frozenset({"variable-speed-load"}),
                config_for_circuit=lambda circuit_id: (
                    mains_config if circuit_id == "mains" else direct_config
                ),
            ),
        )
    )
    machine = OperatingStateMachine(
        ResolvedOperatingDetection(
            profile=OperatingDetectionProfile(25.0, 10.0, 10.0, 20.0, 60.0, 600.0),
            source=OperatingThresholdSource.PROFILE_DEFAULT,
            appliance_profile=ApplianceProfile.HVAC_BLOWER,
            circuit_mode=CircuitMode.SINGLE_PHASE,
        )
    )
    timestamp = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    events = []
    for seconds, watts in (
        (0, 5.0),
        (5, 500.0),
        (15, 500.0),
        (20, 500.0),
        (25, 500.0),
        (30, 900.0),
        (35, 900.0),
        (40, 900.0),
    ):
        events.extend(
            machine.process(
                CircuitSample(
                    timestamp=timestamp + timedelta(seconds=seconds),
                    circuit_id="variable-speed-load",
                    real_power=watts,
                    current=1.0,
                    voltage=120.0,
                    reactive_power=0.0,
                    apparent_power=watts,
                    power_factor=1.0,
                    frequency=60.0,
                    energy=0.0,
                )
            ).events
        )
    transition = next(
        event for event in events if event.event_type is EventType.POWER_TRANSITION
    )

    masked_event = next(controller.known_load_events("mains", [transition]))
    assert masked_event is transition
    assert tuple(controller.helper_candidate_events("mains", [transition])) == ()


def test_nilm_controller_filters_helpers_to_current_direct_loads() -> None:
    configs = {
        "mixed": _config(ApplianceProfile.MIXED, CircuitMode.MIXED),
        "hvac-2": _config(ApplianceProfile.HVAC_BLOWER),
        "solar": _config(
            ApplianceProfile.MOTOR_LOAD,
            power_flow=PowerFlowMode.GENERATION,
        ),
    }
    controller = _nilm_controller(
        SimpleNamespace(
            circuit_registry=SimpleNamespace(config_for_circuit=configs.get)
        )
    )
    events = [
        SimpleNamespace(circuit_id=value)
        for value in ("mixed", "hvac-2", "solar", "other-entry")
    ]

    assert [
        event.circuit_id
        for event in controller.helper_candidate_events("mixed", events)
    ] == ["hvac-2"]


@pytest.mark.parametrize(
    ("profile", "mode", "expected"),
    [
        (ApplianceProfile.MAINS_NILM, CircuitMode.MAINS_NILM, NilmSourceKind.MAINS),
        (ApplianceProfile.MAINS_NILM, CircuitMode.MIXED, NilmSourceKind.MAINS),
        (ApplianceProfile.MIXED, CircuitMode.MAINS_NILM, NilmSourceKind.MAINS),
        (ApplianceProfile.MIXED, CircuitMode.MIXED, NilmSourceKind.PURE_MIXED),
        (ApplianceProfile.HVAC_BLOWER, CircuitMode.MIXED, NilmSourceKind.PRIMARY_MIXED),
        (ApplianceProfile.MIXED, CircuitMode.SINGLE_PHASE, NilmSourceKind.PURE_MIXED),
        (ApplianceProfile.HVAC_BLOWER, CircuitMode.SINGLE_PHASE, None),
    ],
)
def test_nilm_source_kind_uses_explicit_configuration(
    profile: ApplianceProfile,
    mode: CircuitMode,
    expected: NilmSourceKind | None,
) -> None:
    assert nilm_source_kind(_config(profile=profile, mode=mode)) is expected


def test_nilm_source_kind_normalizes_mapping_values() -> None:
    config = _config(profile=ApplianceProfile.MIXED, mode=CircuitMode.MIXED)

    assert nilm_source_kind(
        {"appliance_profile": "mixed", "mode": "mixed"}
    ) is nilm_source_kind(config)
    assert nilm_source_kind({"appliance_profile": "invalid", "mode": "mixed"}) is None
    assert nilm_source_kind({"mode": "mixed"}) is None


def test_nilm_source_kind_never_uses_circuit_name() -> None:
    assert (
        nilm_source_kind(
            _config(
                circuit_id="mains",
                name="Mains",
                profile=ApplianceProfile.HVAC_BLOWER,
                mode=CircuitMode.SINGLE_PHASE,
            )
        )
        is None
    )


@pytest.mark.parametrize(
    "config",
    (
        SimpleNamespace(
            mode=CircuitMode.SINGLE_PHASE,
            appliance_profile=ApplianceProfile.MIXED,
            nilm_detection_enabled=True,
        ),
        SimpleNamespace(
            mode=CircuitMode.MIXED,
            appliance_profile=ApplianceProfile.MOTOR_LOAD,
            nilm_detection_enabled=True,
        ),
    ),
)
def test_nilm_controller_enables_mixed_sources_only_when_circuit_enabled(
    config: SimpleNamespace,
) -> None:
    disabled = _nilm_controller(SimpleNamespace(options={}, entry_data={}))

    off_config = SimpleNamespace(
        mode=config.mode,
        appliance_profile=config.appliance_profile,
        nilm_detection_enabled=False,
    )

    assert disabled.enabled_for_config(off_config) is False
    assert disabled.enabled_for_config(config) is True


@pytest.mark.parametrize(
    ("source_config", "expected_circuit_ids"),
    (
        (
            SimpleNamespace(
                mode=CircuitMode.MAINS_NILM,
                appliance_profile=ApplianceProfile.MAINS_NILM,
            ),
            ["fridge"],
        ),
        (
            SimpleNamespace(
                mode=CircuitMode.MIXED,
                appliance_profile=ApplianceProfile.HVAC_BLOWER,
            ),
            [],
        ),
        (
            SimpleNamespace(
                mode=CircuitMode.MIXED,
                appliance_profile=ApplianceProfile.MIXED,
            ),
            [],
        ),
        (
            SimpleNamespace(
                mode=CircuitMode.SINGLE_PHASE,
                appliance_profile=ApplianceProfile.REFRIGERATOR,
            ),
            [],
        ),
        (None, []),
    ),
)
def test_nilm_controller_masks_known_loads_only_for_mains(
    source_config: SimpleNamespace | None,
    expected_circuit_ids: list[str],
) -> None:
    controller = _nilm_controller(
        SimpleNamespace(
            circuit_registry=SimpleNamespace(
                known_load_circuit_ids=frozenset({"fridge"}),
                config_for_circuit=lambda _circuit_id: source_config,
            ),
        )
    )

    assert [
        event.circuit_id
        for event in controller.known_load_events(
            "source", [SimpleNamespace(circuit_id="fridge", event_type=EventType.START)]
        )
    ] == expected_circuit_ids


def test_nilm_controller_builds_signature_payloads_with_public_current_time() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    context_calls: list[datetime] = []

    def build_context(timestamp: datetime) -> SimpleNamespace:
        context_calls.append(timestamp)
        return SimpleNamespace(timestamp=timestamp)

    coordinator = SimpleNamespace(
        current_time=lambda: now,
        context_builder=SimpleNamespace(build=build_context),
    )
    controller = _nilm_controller(coordinator)
    controller.configure_processors(
        sample_processor=SimpleNamespace(
            _nilm_signature_payloads=(
                lambda circuit_id, signatures, context: {
                    "circuit_id": circuit_id,
                    "context": context,
                    "signatures": signatures,
                }
            )
        ),
        topology_processor=SimpleNamespace(),
        total_events_by_circuit={},
        unmatched_edges_by_circuit={},
    )

    payload = controller.signature_payloads("mains", [{"signature_id": "sig-1"}])

    assert payload["context"].timestamp == now
    assert payload["signatures"] == [{"signature_id": "sig-1"}]
    assert context_calls == [now]


def test_nilm_controller_owns_assignment_helper_behavior() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=SimpleNamespace(
            nilm_appliance_assignments_by_circuit={},
        ),
    )
    controller = NilmController(
        coordinator,
        label_interval_max_items=10,
        assignment_max_items=10,
    )

    assignment = controller.upsert_assignment(
        "mains",
        label="Kitchen Dishwasher",
        signature_fingerprint=" fingerprint-1 ",
        session_id=" session-1 ",
        label_interval_id=" interval-1 ",
        confidence="0.82",
    )
    updated = controller.upsert_assignment(
        "mains",
        label="Kitchen Dishwasher",
        signature_fingerprint="fingerprint-1",
        session_id="session-1",
        label_interval_id="interval-1",
        confidence="0.5",
    )

    assert updated["assignment_id"] == assignment["assignment_id"]
    assert updated["assignment_id"].startswith("assignment-")
    assert updated["appliance_id"] == "kitchen_dishwasher"
    assert updated["signature_fingerprints"] == ["fingerprint-1"]
    assert updated["session_ids"] == ["session-1"]
    assert updated["label_interval_ids"] == ["interval-1"]
    assert "confidence" not in updated
    assert "feedback_evidence_score" not in updated
    assert "confidence_kind" not in updated
    assert updated["role"] == "component"


@pytest.mark.asyncio
async def test_label_intervals_validate_and_retain_observed_transition_w() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    saved = await controller.async_label_nilm_interval(
        "mixed",
        label="Condensate pump",
        start="2026-06-02T10:00:00+00:00",
        end="2026-06-02T10:05:00+00:00",
        observed_transition_w=83.0,
    )

    assert saved["observed_transition_w"] == 83.0
    updated = await controller.async_label_nilm_interval(
        "mixed",
        label="Condensate pump",
        start="2026-06-02T10:01:00+00:00",
        end="2026-06-02T10:06:00+00:00",
        interval_id=saved["interval_id"],
    )
    assert updated["observed_transition_w"] == 83.0

    replaced = await controller.async_label_nilm_interval(
        "mixed",
        label="Condensate pump",
        start="2026-06-02T10:01:00+00:00",
        end="2026-06-02T10:06:00+00:00",
        interval_id=saved["interval_id"],
        observed_transition_w=91.0,
    )
    assert replaced["observed_transition_w"] == 91.0
    for invalid in (-1, float("inf"), float("nan"), "unknown", True, False):
        with pytest.raises(ValueError, match="observed transition"):
            await controller.async_label_nilm_interval(
                "mixed",
                label="Condensate pump",
                start="2026-06-02T11:00:00+00:00",
                end="2026-06-02T11:05:00+00:00",
                observed_transition_w=invalid,
            )


@pytest.mark.asyncio
async def test_direct_interval_create_move_and_delete_rebuilds_each_owner() -> None:
    """Every direct interval mutation refreshes the assignments it affects."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    first = {"assignment_id": "first", "label_interval_ids": []}
    second = {"assignment_id": "second", "label_interval_ids": []}
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [first, second]}
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    saved = await controller.async_label_nilm_interval(
        "mixed",
        label="Pump",
        start="2026-06-02T10:00:00+00:00",
        end="2026-06-02T10:05:00+00:00",
        assignment_id="first",
        observed_transition_w=80.0,
    )
    assert first["power_states_w"] == [0.0, 80.0]

    await controller.async_label_nilm_interval(
        "mixed",
        label="Pump",
        start="2026-06-02T10:00:00+00:00",
        end="2026-06-02T10:05:00+00:00",
        interval_id=saved["interval_id"],
        assignment_id="second",
        observed_transition_w=90.0,
    )
    assert first["label_interval_ids"] == []
    assert first["power_states_w"] == []
    assert second["power_states_w"] == [0.0, 90.0]

    assert await controller.async_delete_nilm_label_interval(
        "mixed", saved["interval_id"]
    )
    assert second["label_interval_ids"] == []
    assert second["power_states_w"] == []


@pytest.mark.asyncio
async def test_direct_interval_create_rebuilds_owner_of_retention_eviction() -> None:
    """Pruning an old interval detaches and refreshes its former owner."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    old_interval = {
        "interval_id": "old",
        "assignment_id": "first",
        "label": "Old pump",
        "start": "2026-06-01T10:00:00+00:00",
        "end": "2026-06-01T10:05:00+00:00",
        "observed_transition_w": 80.0,
        "confidence": 1.0,
    }
    first = {"assignment_id": "first", "label_interval_ids": ["old"]}
    first.update(
        build_nilm_assignment_model(first, (), label_intervals=[old_interval])
    )
    second = {"assignment_id": "second", "label_interval_ids": []}
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [first, second]},
            nilm_label_intervals_by_circuit={"mixed": [old_interval]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=1, assignment_max_items=10
    )

    saved = await controller.async_label_nilm_interval(
        "mixed",
        label="New pump",
        start="2026-06-02T10:00:00+00:00",
        end="2026-06-02T10:05:00+00:00",
        assignment_id="second",
        observed_transition_w=90.0,
    )

    assert [
        interval["interval_id"]
        for interval in coordinator.store_data.nilm_label_intervals_by_circuit["mixed"]
    ] == [saved["interval_id"]]
    assert first["label_interval_ids"] == []
    assert first["power_states_w"] == []
    assert second["power_states_w"] == [0.0, 90.0]


@pytest.mark.asyncio
@pytest.mark.parametrize("save_path", ("single", "batch"))
async def test_schema_2_interval_evidence_round_trips_through_save_paths(
    save_path: str,
) -> None:
    """Schema-2 extraction output remains available after controller persistence."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    evidence = {
        "evidence_schema_version": 2,
        "evidence_source": "manual_backend",
        "evidence_generated_at": "2026-06-02T12:00:00+00:00",
        "start_transition_w": 82.0,
        "stop_transition_w": -79.0,
        "median_power_w": 80.0,
        "average_power_w": 81.0,
        "measured_energy_kwh": 0.04,
        "partial_energy_kwh": 0.041,
        "source_coverage": 0.98,
        "power_coverage": 0.97,
        "maximum_source_skew_seconds": 2.0,
        "longest_power_gap_seconds": 8.0,
        "start_boundary_uncertainty_seconds": 1.0,
        "end_boundary_uncertainty_seconds": 1.5,
        "start_transition_eligible": True,
        "stop_transition_eligible": True,
        "plateau_eligible": True,
        "energy_complete": True,
        "evidence_confidence": 0.91,
        "power_confidence": 0.89,
        "quality_flags": ["complete", "stable_plateau"],
    }
    draft = {
        "interval_id": "schema-2",
        "start": "2026-06-02T10:00:00+00:00",
        "end": "2026-06-02T10:30:00+00:00",
    }

    if save_path == "single":
        saved = await controller.async_label_nilm_interval(
            "mixed", label="Pump", evidence=evidence, **draft
        )
    else:
        await controller.async_save_nilm_interval_changes(
            "mixed", label="Pump", intervals=[{**draft, "evidence": evidence}]
        )
        saved = coordinator.store_data.nilm_label_intervals_by_circuit["mixed"][0]

    assert {key: saved[key] for key in evidence} == evidence
    assert saved["observed_transition_w"] == 82.0
    assert saved["confidence"] == 0.91


@pytest.mark.asyncio
async def test_schema_2_start_only_evidence_is_the_only_transition_compatibility_value(
) -> None:
    """A schema-2 stop or interior value cannot become a legacy ON transition."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    saved = await controller.async_label_nilm_interval(
        "mixed",
        label="Pump",
        start="2026-06-02T10:00:00+00:00",
        end="2026-06-02T10:30:00+00:00",
        evidence={
            "evidence_schema_version": 2,
            "evidence_source": "manual_backend",
            "evidence_generated_at": "2026-06-02T12:00:00+00:00",
            "start_transition_w": None,
            "stop_transition_w": -120.0,
            "start_transition_eligible": False,
            "stop_transition_eligible": True,
            "plateau_eligible": False,
            "energy_complete": False,
            "source_coverage": 0.7,
            "power_coverage": 0.7,
            "evidence_confidence": 0.5,
            "power_confidence": 0.5,
            "quality_flags": ["interior_transition_present"],
        },
    )

    assert "observed_transition_w" not in saved


@pytest.mark.asyncio
async def test_schema_2_evidence_replaces_stale_client_electrical_fields() -> None:
    """Trusted schema-2 evidence replaces prior client-derived electrical data."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    stale = {
        "interval_id": "schema-2",
        "label": "Pump",
        "start": "2026-06-02T10:00:00+00:00",
        "end": "2026-06-02T10:30:00+00:00",
        "observed_transition_w": 9999.0,
        "median_power_w": 9999.0,
        "measured_energy_kwh": 9.999,
        "partial_energy_kwh": 9.999,
        "power_coverage": 1.0,
    }
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(
            nilm_label_intervals_by_circuit={"mixed": [stale]}
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    saved = await controller.async_label_nilm_interval(
        "mixed",
        label="Pump",
        start=stale["start"],
        end=stale["end"],
        interval_id="schema-2",
        observed_transition_w=7777.0,
        median_power_w=7777.0,
        measured_energy_kwh=7.777,
        evidence={
            "evidence_schema_version": 2,
            "evidence_source": "manual_backend",
            "evidence_generated_at": "2026-06-02T12:00:00+00:00",
            "start_transition_w": 75.0,
            "median_power_w": 72.0,
            "partial_energy_kwh": 0.035,
            "source_coverage": 0.8,
            "power_coverage": 0.8,
            "start_transition_eligible": True,
            "stop_transition_eligible": False,
            "plateau_eligible": True,
            "energy_complete": False,
            "evidence_confidence": 0.7,
            "power_confidence": 0.7,
            "quality_flags": ["incomplete_energy"],
        },
    )

    assert saved["observed_transition_w"] == 75.0
    assert saved["median_power_w"] == 72.0
    assert saved["partial_energy_kwh"] == 0.035
    assert "measured_energy_kwh" not in saved


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evidence",
    (
        {"evidence_schema_version": 3},
        {"evidence_schema_version": 2, "source_coverage": float("nan")},
        {"evidence_schema_version": 2, "power_confidence": float("inf")},
        {"evidence_schema_version": 2, "start_transition_eligible": 1},
        {"evidence_schema_version": 2, "quality_flags": ["x"] * 33},
        {"evidence_schema_version": 2, "quality_flags": ["x" * 129]},
    ),
)
async def test_invalid_schema_2_evidence_is_rejected_without_mutating_intervals(
    evidence: dict[str, object],
) -> None:
    """Malformed trusted evidence cannot partially create an interval collection."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    with pytest.raises(ValueError, match="evidence"):
        await controller.async_label_nilm_interval(
            "mixed",
            label="Pump",
            start="2026-06-02T10:00:00+00:00",
            end="2026-06-02T10:30:00+00:00",
            evidence=evidence,
        )

    assert coordinator.store_data.nilm_label_intervals_by_circuit == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quality_flags",
    (
        {"complete": True},
        {"complete"},
        (flag for flag in ("complete",)),
    ),
)
async def test_schema_2_evidence_rejects_non_list_quality_flags_before_mutation(
    quality_flags: object,
) -> None:
    """Only a concrete bounded list can cross the persistence boundary."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    evidence = {
        "evidence_schema_version": 2,
        "evidence_source": "manual_backend",
        "evidence_generated_at": "2026-06-02T12:00:00+00:00",
        "source_coverage": 1.0,
        "power_coverage": 1.0,
        "start_transition_eligible": False,
        "stop_transition_eligible": False,
        "plateau_eligible": False,
        "energy_complete": False,
        "evidence_confidence": 1.0,
        "power_confidence": 1.0,
        "quality_flags": quality_flags,
    }

    with pytest.raises(ValueError, match="quality_flags"):
        await controller.async_label_nilm_interval(
            "mixed",
            label="Pump",
            start="2026-06-02T10:00:00+00:00",
            end="2026-06-02T10:30:00+00:00",
            evidence=evidence,
        )

    assert coordinator.store_data.nilm_label_intervals_by_circuit == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    (
        {"start_transition_eligible": True},
        {"stop_transition_eligible": True},
        {"energy_complete": True},
        {"start_transition_w": -20.0},
        {"stop_transition_w": 20.0},
    ),
)
async def test_schema_2_evidence_rejects_inconsistent_transition_and_energy_fields(
    overrides: dict[str, object],
) -> None:
    """Eligibility and completeness claims require compatible observed values."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    evidence = {
        "evidence_schema_version": 2,
        "evidence_source": "reference_backend",
        "evidence_generated_at": "2026-06-02T12:00:00+00:00",
        "source_coverage": 1.0,
        "power_coverage": 1.0,
        "start_transition_eligible": False,
        "stop_transition_eligible": False,
        "plateau_eligible": False,
        "energy_complete": False,
        "evidence_confidence": 1.0,
        "power_confidence": 1.0,
        "quality_flags": [],
        **overrides,
    }

    with pytest.raises(ValueError, match="schema-2 evidence"):
        await controller.async_label_nilm_interval(
            "mixed",
            label="Pump",
            start="2026-06-02T10:00:00+00:00",
            end="2026-06-02T10:30:00+00:00",
            evidence=evidence,
        )

    assert coordinator.store_data.nilm_label_intervals_by_circuit == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "source",
        "start_transition_w",
        "stop_transition_w",
        "start_eligible",
        "stop_eligible",
        "observed",
    ),
    (
        ("manual_backend", 75.0, None, True, False, 75.0),
        ("reference_backend", None, -75.0, False, True, None),
    ),
)
async def test_schema_2_evidence_preserves_valid_one_sided_backend_evidence(
    source: str,
    start_transition_w: float | None,
    stop_transition_w: float | None,
    start_eligible: bool,
    stop_eligible: bool,
    observed: float | None,
) -> None:
    """Valid one-sided backend evidence remains accepted for each backend source."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    saved = await controller.async_label_nilm_interval(
        "mixed",
        label="Pump",
        start="2026-06-02T10:00:00+00:00",
        end="2026-06-02T10:30:00+00:00",
        evidence={
            "evidence_schema_version": 2,
            "evidence_source": source,
            "evidence_generated_at": "2026-06-02T12:00:00+00:00",
            "start_transition_w": start_transition_w,
            "stop_transition_w": stop_transition_w,
            "source_coverage": 1.0,
            "power_coverage": 1.0,
            "start_transition_eligible": start_eligible,
            "stop_transition_eligible": stop_eligible,
            "plateau_eligible": False,
            "energy_complete": False,
            "evidence_confidence": 1.0,
            "power_confidence": 1.0,
            "quality_flags": [],
        },
    )

    assert saved["evidence_source"] == source
    if observed is None:
        assert "observed_transition_w" not in saved
    else:
        assert saved["observed_transition_w"] == observed


def test_reference_evidence_rejects_bad_resolved_settings() -> None:
    evidence = {
        "evidence_schema_version": 2,
        "evidence_source": "reference_backend",
        "evidence_generated_at": "2026-06-02T12:00:00+00:00",
        "source_coverage": 1.0,
        "power_coverage": 0.0,
        "evidence_confidence": 1.0,
        "power_confidence": 0.0,
        "start_transition_eligible": False,
        "stop_transition_eligible": False,
        "plateau_eligible": False,
        "energy_complete": False,
        "quality_flags": [],
        "state_coverage": 1.0,
        "unknown_duration_seconds": 0.0,
        "merged_gap_count": 0,
        "left_censored": False,
        "right_censored": False,
        "resolved_reference_settings": {
            "on_threshold": 10.0,
            "off_threshold": 20.0,
            "on_dwell_seconds": 0.0,
            "off_dwell_seconds": 0.0,
            "minimum_interval_seconds": 0.0,
            "merge_gap_seconds": 0.0,
            "maximum_unknown_gap_seconds": 0.0,
            "maximum_power_gap_seconds": None,
        },
    }

    with pytest.raises(ValueError, match="resolved_reference_settings"):
        NilmController._validated_schema_2_evidence(evidence)
    evidence["resolved_reference_settings"].pop("maximum_power_gap_seconds")
    with pytest.raises(ValueError, match="resolved_reference_settings"):
        NilmController._validated_schema_2_evidence(evidence)


@pytest.mark.asyncio
async def test_batch_schema_2_validation_rolls_back_and_legacy_is_readable(
) -> None:
    """A bad schema-2 item changes neither legacy data nor membership."""
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    legacy = {
        "interval_id": "legacy",
        "label": "Pump",
        "start": "2026-06-02T10:00:00+00:00",
        "end": "2026-06-02T10:30:00+00:00",
        "observed_transition_w": 60.0,
    }
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(
            nilm_label_intervals_by_circuit={"mixed": [legacy]}
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    with pytest.raises(ValueError, match="evidence"):
        await controller.async_save_nilm_interval_changes(
            "mixed",
            label="Pump",
            intervals=[
                legacy,
                {
                    "interval_id": "bad",
                    "start": "2026-06-02T11:00:00+00:00",
                    "end": "2026-06-02T11:30:00+00:00",
                    "evidence": {
                        "evidence_schema_version": 2,
                        "quality_flags": ["x"] * 33,
                    },
                },
            ],
        )

    assert coordinator.store_data.nilm_label_intervals_by_circuit["mixed"] == [legacy]


@pytest.mark.asyncio
@pytest.mark.parametrize("save_path", ("label", "bulk", "assign"))
async def test_primary_interval_saves_establish_matching_signature(
    save_path: str,
) -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    fingerprint = "direction=on|watts=300-400"
    primary_id = configured_primary_assignment_id("hvac_2")
    primary = {
        "assignment_id": primary_id,
        "display_name": "HVAC 2",
        "appliance_id": "hvac_2",
        "role": "primary",
        "lifecycle_state": "needs_validation",
        "signature_fingerprints": [],
        "session_ids": [],
        "label_interval_ids": [],
    }
    signature = {
        "signature_id": "signature-hvac",
        "feedback_fingerprint": fingerprint,
        "review_state": "new",
    }
    session = {
        "session_id": "session-hvac",
        "signature_fingerprint": fingerprint,
        "start": "2026-06-02T10:00:00+00:00",
        "end": "2026-06-02T10:05:00+00:00",
        "ambiguous": False,
        "known_load_masked": False,
    }
    interval = {
        "interval_id": "interval-hvac",
        "label": "HVAC 2",
        "appliance_id": "hvac_2",
        "start": session["start"],
        "end": session["end"],
    }
    saves = AsyncMock()
    config = _config(
        ApplianceProfile.HVAC_BLOWER,
        CircuitMode.MIXED,
        "hvac_2",
        "HVAC 2",
    )
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        circuit_registry=SimpleNamespace(config_for_circuit=lambda _circuit_id: config),
        ignored_nilm_signatures=set(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"hvac_2": [primary]},
            nilm_label_intervals_by_circuit={"hvac_2": [interval]},
            nilm_signatures={"hvac_2": [signature]},
            nilm_session_history_by_circuit={"hvac_2": [session]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=saves,
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator,
        label_interval_max_items=10,
        assignment_max_items=10,
    )

    if save_path == "label":
        await controller.async_label_nilm_interval(
            "hvac_2",
            label="HVAC 2",
            start=interval["start"],
            end=interval["end"],
            assignment_id=primary_id,
            interval_id="interval-hvac",
        )
    elif save_path == "bulk":
        await controller.async_save_nilm_interval_changes(
            "hvac_2",
            label="HVAC 2",
            assignment_id=primary_id,
            intervals=[interval],
        )
    else:
        await controller.async_assign_nilm_interval(
            "hvac_2",
            "interval-hvac",
            label="HVAC 2",
            assignment_id=primary_id,
        )

    assert primary["signature_fingerprints"] == [fingerprint]
    assert signature["assignment_id"] == primary_id
    assert signature["review_state"] == "assigned"
    assert session["assignment_id"] == primary_id
    assert primary["session_ids"] == ["session-hvac"]
    assert saves.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "session_overrides",
        "primary_fingerprints",
        "signature_owner",
        "add_second_signature",
    ),
    (
        ({"ambiguous": True}, (), None, False),
        ({"known_load_masked": True}, (), None, False),
        ({"end": None}, (), None, False),
        ({"signature_fingerprint": "unassigned"}, (), None, False),
        ({}, (), None, True),
        ({}, (), "assignment-other", False),
        ({}, ("direction=on|watts=500-600",), None, False),
    ),
)
async def test_unsafe_primary_interval_evidence_does_not_auto_link_signature(
    session_overrides: dict[str, object],
    primary_fingerprints: tuple[str, ...],
    signature_owner: str | None,
    add_second_signature: bool,
) -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    fingerprint = "direction=on|watts=300-400"
    primary_id = configured_primary_assignment_id("hvac_2")
    primary = {
        "assignment_id": primary_id,
        "display_name": "HVAC 2",
        "appliance_id": "hvac_2",
        "role": "primary",
        "lifecycle_state": "needs_validation",
        "signature_fingerprints": list(primary_fingerprints),
        "session_ids": [],
        "label_interval_ids": [],
    }
    signature = {
        "signature_id": "signature-hvac",
        "feedback_fingerprint": fingerprint,
        "review_state": "new",
        **({"assignment_id": signature_owner} if signature_owner else {}),
    }
    session = {
        "session_id": "session-hvac",
        "signature_fingerprint": fingerprint,
        "start": "2026-06-02T10:00:00+00:00",
        "end": "2026-06-02T10:05:00+00:00",
        "ambiguous": False,
        "known_load_masked": False,
        **session_overrides,
    }
    interval = {
        "interval_id": "interval-hvac",
        "label": "HVAC 2",
        "appliance_id": "hvac_2",
        "start": "2026-06-02T10:00:00+00:00",
        "end": "2026-06-02T10:05:00+00:00",
    }
    signatures = [signature]
    sessions = [session]
    if add_second_signature:
        second_fingerprint = "direction=on|watts=500-600"
        signatures.append(
            {
                "signature_id": "signature-other",
                "feedback_fingerprint": second_fingerprint,
                "review_state": "new",
            }
        )
        sessions.append(
            {
                **session,
                "session_id": "session-other",
                "signature_fingerprint": second_fingerprint,
            }
        )
    other_assignments = (
        [
            {
                "assignment_id": "assignment-other",
                "signature_fingerprints": [fingerprint],
            }
        ]
        if signature_owner
        else []
    )
    saves = AsyncMock()
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        ignored_nilm_signatures=set(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "hvac_2": [primary, *other_assignments]
            },
            nilm_label_intervals_by_circuit={"hvac_2": [interval]},
            nilm_signatures={"hvac_2": signatures},
            nilm_session_history_by_circuit={"hvac_2": sessions},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=saves,
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator,
        label_interval_max_items=10,
        assignment_max_items=10,
    )

    await controller.async_save_nilm_interval_changes(
        "hvac_2",
        label="HVAC 2",
        assignment_id=primary_id,
        intervals=[interval],
    )

    assert primary["signature_fingerprints"] == list(primary_fingerprints)
    assert (
        "assignment_id" not in signature
        or signature["assignment_id"] == signature_owner
    )
    assert primary["session_ids"] == []
    assert coordinator.store_data.nilm_label_intervals_by_circuit["hvac_2"][0][
        "assignment_id"
    ] == primary_id
    assert saves.await_count == 1


@pytest.mark.asyncio
async def test_assign_primary_interval_rolls_back_auto_link_when_save_fails() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    fingerprint = "direction=on|watts=300-400"
    primary_id = configured_primary_assignment_id("hvac_2")
    store_data = FeatureStoreData(
        nilm_appliance_assignments_by_circuit={
            "hvac_2": [
                {
                    "assignment_id": primary_id,
                    "display_name": "HVAC 2",
                    "appliance_id": "hvac_2",
                    "role": "primary",
                    "lifecycle_state": "needs_validation",
                    "signature_fingerprints": [],
                    "session_ids": [],
                    "label_interval_ids": [],
                }
            ]
        },
        nilm_label_intervals_by_circuit={
            "hvac_2": [
                {
                    "interval_id": "interval-hvac",
                    "label": "HVAC 2",
                    "appliance_id": "hvac_2",
                    "start": "2026-06-02T10:00:00+00:00",
                    "end": "2026-06-02T10:05:00+00:00",
                }
            ]
        },
        nilm_signatures={
            "hvac_2": [
                {
                    "signature_id": "signature-hvac",
                    "feedback_fingerprint": fingerprint,
                    "review_state": "new",
                }
            ]
        },
        nilm_session_history_by_circuit={
            "hvac_2": [
                {
                    "session_id": "session-hvac",
                    "signature_fingerprint": fingerprint,
                    "start": "2026-06-02T10:00:00+00:00",
                    "end": "2026-06-02T10:05:00+00:00",
                    "ambiguous": False,
                    "known_load_masked": False,
                }
            ]
        },
    )
    before = deepcopy(store_data)
    config = _config(
        ApplianceProfile.HVAC_BLOWER,
        CircuitMode.MIXED,
        "hvac_2",
        "HVAC 2",
    )
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        circuit_registry=SimpleNamespace(config_for_circuit=lambda _circuit_id: config),
        ignored_nilm_signatures=set(),
        store_data=store_data,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(side_effect=RuntimeError("storage down")),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator,
        label_interval_max_items=10,
        assignment_max_items=10,
    )

    with pytest.raises(RuntimeError, match="storage down"):
        await controller.async_assign_nilm_interval(
            "hvac_2",
            "interval-hvac",
            label="HVAC 2",
            assignment_id=primary_id,
        )

    assert coordinator.store_data == before


@pytest.mark.asyncio
async def test_save_nilm_interval_changes_reassign_owner_rebuilds_models() -> None:
    saves = AsyncMock()
    assignment = {
        "assignment_id": "assignment-pump",
        "display_name": "Pump",
        "appliance_id": "pump",
        "label_interval_ids": ["old", "shared"],
        "signature_fingerprints": [],
        "session_ids": [],
    }
    other = {
        "assignment_id": "assignment-other",
        "label_interval_ids": ["shared"],
        "signature_fingerprints": [],
        "session_ids": [],
        "typical_duration_seconds": 300.0,
        "min_duration_seconds": 150.0,
        "max_duration_seconds": 600.0,
        "power_states_w": [0.0, 73.0],
        "transition_prototypes": [
            {"direction": "on", "delta_w": 73.0},
            {"direction": "off", "delta_w": -73.0},
        ],
    }
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment, other]},
            nilm_label_intervals_by_circuit={
                "mixed": [
                    {
                        "interval_id": "old",
                        "label": "Pump",
                        "start": "2026-06-02T10:00:00+00:00",
                        "end": "2026-06-02T10:05:00+00:00",
                        "assignment_id": "assignment-pump",
                    },
                    {
                        "interval_id": "shared",
                        "label": "Pump",
                        "start": "2026-06-02T10:10:00+00:00",
                        "end": "2026-06-02T10:15:00+00:00",
                        "assignment_id": "assignment-pump",
                        "observed_transition_w": 73.0,
                    },
                ]
            },
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=saves
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    saved = await controller.async_save_nilm_interval_changes(
        "mixed",
        label="Pump",
        assignment_id="assignment-pump",
        intervals=[
            {
                "interval_id": "shared",
                "start": "2026-06-02T10:11:00+00:00",
                "end": "2026-06-02T10:16:00+00:00",
                "observed_transition_w": 78.0,
            },
            {
                "interval_id": "new",
                "start": "2026-06-02T11:00:00+00:00",
                "end": "2026-06-02T11:05:00+00:00",
            },
        ],
        removed_interval_ids=("old",),
    )

    assert saved["assignment_id"] == "assignment-pump"
    assert assignment["label_interval_ids"] == ["shared", "new"]
    assert other["label_interval_ids"] == []
    assert "typical_duration_seconds" not in assignment
    assert "min_duration_seconds" not in assignment
    assert "max_duration_seconds" not in assignment
    assert assignment["power_states_w"] == [0.0, 78.0]
    assert [
        prototype["delta_w"] for prototype in assignment["transition_prototypes"]
    ] == [78.0, -78.0]
    assert "typical_duration_seconds" not in other
    assert "min_duration_seconds" not in other
    assert "max_duration_seconds" not in other
    assert other["power_states_w"] == []
    assert other["transition_prototypes"] == []
    assert coordinator.store_data.nilm_label_intervals_by_circuit["mixed"] == [
        {
            "interval_id": "old",
            "label": "Pump",
            "start": "2026-06-02T10:00:00+00:00",
            "end": "2026-06-02T10:05:00+00:00",
            "assignment_id": None,
        },
        {
            "interval_id": "shared",
            "mains_circuit_id": "mixed",
            "appliance_id": "pump",
            "label": "Pump",
            "start": "2026-06-02T10:11:00+00:00",
            "end": "2026-06-02T10:16:00+00:00",
            "source": "manual",
                "confidence": 1.0,
                "created_at": "2026-06-02T12:00:00+00:00",
                "updated_at": "2026-06-02T12:00:00+00:00",
                "observed_transition_w": 78.0,
                "assignment_id": "assignment-pump",
        },
        {
            "interval_id": "new",
            "mains_circuit_id": "mixed",
            "appliance_id": "pump",
            "label": "Pump",
            "start": "2026-06-02T11:00:00+00:00",
            "end": "2026-06-02T11:05:00+00:00",
            "source": "manual",
            "confidence": 1.0,
            "created_at": "2026-06-02T12:00:00+00:00",
            "updated_at": "2026-06-02T12:00:00+00:00",
            "assignment_id": "assignment-pump",
        },
    ]
    assert saves.await_count == 1


@pytest.mark.asyncio
async def test_assign_nilm_interval_transfers_owner_and_serializes_review() -> None:
    first_save_started = asyncio.Event()
    release_first_save = asyncio.Event()
    save_calls = 0

    async def save(_now: datetime) -> None:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            first_save_started.set()
            await release_first_save.wait()

    former = {
        "assignment_id": "assignment-former",
        "label_interval_ids": ["shared"],
        "typical_duration_seconds": 300.0,
        "min_duration_seconds": 150.0,
        "max_duration_seconds": 600.0,
        "power_states_w": [0.0, 73.0],
        "transition_prototypes": [
            {"direction": "on", "delta_w": 73.0},
            {"direction": "off", "delta_w": -73.0},
        ],
    }
    target = {
        "assignment_id": "assignment-target",
        "display_name": "Target",
        "appliance_id": "target",
        "label_interval_ids": [],
    }
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [former, target]},
            nilm_label_intervals_by_circuit={
                "mixed": [
                    {
                        "interval_id": "shared",
                        "label": "Target",
                        "appliance_id": "target",
                        "assignment_id": "assignment-former",
                        "observed_transition_w": 73.0,
                    }
                ]
            },
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=save
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    first = asyncio.create_task(
        controller.async_assign_nilm_interval(
            "mixed",
            "shared",
            label="Target",
            assignment_id="assignment-target",
        )
    )
    await first_save_started.wait()
    second = asyncio.create_task(
        controller.async_assign_nilm_interval(
            "mixed",
            "shared",
            label="Target",
            assignment_id="assignment-target",
        )
    )
    await asyncio.sleep(0)

    second_blocked = not second.done()

    release_first_save.set()
    assigned = await first
    await second

    assert second_blocked
    assert former["label_interval_ids"] == []
    assert former["power_states_w"] == []
    assert former["transition_prototypes"] == []
    assert "typical_duration_seconds" not in former
    assert "min_duration_seconds" not in former
    assert "max_duration_seconds" not in former
    assert assigned["label_interval_ids"] == ["shared"]
    assert target["power_states_w"] == [0.0, 73.0]
    assert [
        prototype["delta_w"] for prototype in target["transition_prototypes"]
    ] == [73.0, -73.0]
    assert (
        coordinator.store_data.nilm_label_intervals_by_circuit["mixed"][0][
            "assignment_id"
        ]
        == "assignment-target"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle_state", ("ignored", "retired"))
async def test_save_nilm_interval_changes_rejects_hidden_assignment(
    lifecycle_state: str,
) -> None:
    assignment = {
        "assignment_id": "assignment-pump",
        "lifecycle_state": lifecycle_state,
        "label_interval_ids": [],
    }
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]}
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=AsyncMock()
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    with pytest.raises(ValueError, match="active"):
        await controller.async_save_nilm_interval_changes(
            "mixed",
            label="Pump",
            assignment_id="assignment-pump",
            intervals=[],
        )

    assert coordinator.store_data == before


@pytest.mark.asyncio
async def test_save_nilm_interval_changes_rejects_stale_removed_owner() -> None:
    old_owner = {
        "assignment_id": "assignment-old",
        "lifecycle_state": "assigned",
        "label_interval_ids": [],
    }
    new_owner = {
        "assignment_id": "assignment-new",
        "lifecycle_state": "assigned",
        "label_interval_ids": ["interval-moved"],
    }
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [old_owner, new_owner]
            },
            nilm_label_intervals_by_circuit={
                "mixed": [
                    {
                        "interval_id": "interval-moved",
                        "assignment_id": "assignment-new",
                    }
                ]
            },
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=AsyncMock()
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    with pytest.raises(ValueError, match="no longer belongs"):
        await controller.async_save_nilm_interval_changes(
            "mixed",
            label="Old owner",
            assignment_id="assignment-old",
            intervals=[],
            removed_interval_ids=["interval-moved"],
        )

    assert coordinator.store_data == before


@pytest.mark.asyncio
async def test_save_nilm_interval_changes_rejects_removal_without_assignment() -> None:
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=AsyncMock()
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    with pytest.raises(ValueError, match="assignment_id"):
        await controller.async_save_nilm_interval_changes(
            "mixed",
            label="Pump",
            intervals=[],
            removed_interval_ids=["interval-1"],
        )


@pytest.mark.asyncio
async def test_save_nilm_interval_changes_enforces_interval_limit_atomically() -> None:
    saves = AsyncMock()
    assignment = {
        "assignment_id": "assignment-pump",
        "lifecycle_state": "assigned",
        "label_interval_ids": ["interval-1"],
    }
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]},
            nilm_label_intervals_by_circuit={
                "mixed": [
                    {
                        "interval_id": "interval-1",
                        "assignment_id": "assignment-pump",
                    }
                ]
            },
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=saves
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=2, assignment_max_items=10
    )
    draft = {
        "interval_id": "interval-2",
        "start": "2026-06-02T11:00:00+00:00",
        "end": "2026-06-02T11:05:00+00:00",
    }

    await controller.async_save_nilm_interval_changes(
        "mixed",
        label="Pump",
        assignment_id="assignment-pump",
        intervals=[draft],
    )
    at_limit = deepcopy(coordinator.store_data)

    with pytest.raises(ValueError, match="at most 2"):
        await controller.async_save_nilm_interval_changes(
            "mixed",
            label="Pump",
            assignment_id="assignment-pump",
            intervals=[
                {
                    **draft,
                    "interval_id": "interval-3",
                    "start": "2026-06-02T12:00:00+00:00",
                    "end": "2026-06-02T12:05:00+00:00",
                }
            ],
        )

    assert coordinator.store_data == at_limit
    assert saves.await_count == 1


@pytest.mark.asyncio
async def test_save_nilm_interval_changes_validates_before_mutation() -> None:
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [{"assignment_id": "assignment-pump"}]
            },
            nilm_label_intervals_by_circuit={"mixed": [{"interval_id": "old"}]},
            nilm_signatures={"mixed": [{"signature_id": "signature-1"}]},
            nilm_session_history_by_circuit={"mixed": [{"session_id": "session-1"}]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=AsyncMock()
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    with pytest.raises(ValueError, match="end must be after start"):
        await controller.async_save_nilm_interval_changes(
            "mixed",
            label="Pump",
            assignment_id="assignment-pump",
            intervals=[
                {
                    "interval_id": "bad",
                    "start": "2026-06-02T11:05:00+00:00",
                    "end": "2026-06-02T11:00:00+00:00",
                }
            ],
        )

    assert coordinator.store_data == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "draft",
    (
        {"confidence": float("nan")},
        {"observed_transition_w": -1},
        {"median_power_w": float("inf")},
        {"measured_energy_kwh": -1},
    ),
)
async def test_save_nilm_interval_changes_rejects_invalid_evidence_atomically(
    draft: dict[str, object],
) -> None:
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [{"assignment_id": "assignment-pump"}]
            },
            nilm_label_intervals_by_circuit={"mixed": [{"interval_id": "old"}]},
            nilm_signatures={"mixed": [{"signature_id": "signature-1"}]},
            nilm_session_history_by_circuit={"mixed": [{"session_id": "session-1"}]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=AsyncMock()
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    interval = {
        "interval_id": "bad",
        "start": "2026-06-02T11:00:00+00:00",
        "end": "2026-06-02T11:05:00+00:00",
        **draft,
    }

    with pytest.raises(ValueError):
        await controller.async_save_nilm_interval_changes(
            "mixed",
            label="Pump",
            assignment_id="assignment-pump",
            intervals=[interval],
        )

    assert coordinator.store_data == before


@pytest.mark.asyncio
async def test_removed_interval_does_not_match_former_assignment_by_label() -> None:
    assignment = {
        "assignment_id": "assignment-pump",
        "appliance_id": "pump",
        "display_name": "Pump",
        "label_interval_ids": ["label-1"],
        "session_ids": ["session-1"],
    }
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]},
            nilm_label_intervals_by_circuit={
                "mixed": [
                    {
                        "interval_id": "label-1",
                        "label": "Pump",
                        "appliance_id": "pump",
                        "ground_truth_entity_id": "sensor.pump_power",
                        "start": "2026-06-02T10:00:00+00:00",
                        "end": "2026-06-02T10:05:00+00:00",
                        "assignment_id": "assignment-pump",
                    }
                ]
            },
            nilm_session_history_by_circuit={
                "mixed": [
                    {
                        "session_id": "session-1",
                        "assignment_id": "assignment-pump",
                        "start": "2026-06-02T10:00:00+00:00",
                        "end": "2026-06-02T10:05:00+00:00",
                    }
                ]
            },
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=AsyncMock()
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    await controller.async_save_nilm_interval_changes(
        "mixed",
        label="Pump",
        assignment_id="assignment-pump",
        intervals=[],
        removed_interval_ids=["label-1"],
    )

    with pytest.raises(ValueError, match="No matching ground-truth"):
        await controller.async_validate_nilm_assignment_history(
            "mixed", "assignment-pump"
        )


@pytest.mark.asyncio
async def test_batch_rolls_back_after_multi_interval_failure() -> None:
    save = AsyncMock(side_effect=[RuntimeError("save failed"), None])
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {"assignment_id": "assignment-pump", "label_interval_ids": []}
                ]
            },
            nilm_label_intervals_by_circuit={"mixed": [{"interval_id": "old"}]},
            nilm_signatures={"mixed": [{"signature_id": "signature-1"}]},
            nilm_session_history_by_circuit={"mixed": [{"session_id": "session-1"}]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=save
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    with pytest.raises(RuntimeError, match="save failed"):
        await controller.async_save_nilm_interval_changes(
            "mixed",
            label="Pump",
            assignment_id="assignment-pump",
            intervals=[
                {
                    "interval_id": "new",
                    "start": "2026-06-02T11:00:00+00:00",
                    "end": "2026-06-02T11:05:00+00:00",
                },
                {
                    "interval_id": "second-new",
                    "start": "2026-06-02T11:10:00+00:00",
                    "end": "2026-06-02T11:15:00+00:00",
                },
            ],
        )

    assert coordinator.store_data == before
    assert save.await_count == 2


@pytest.mark.asyncio
async def test_delete_assignment_restores_state_after_save_failure() -> None:
    saved_states: list[FeatureStoreData] = []

    async def save(_now: datetime) -> None:
        saved_states.append(deepcopy(coordinator.store_data))
        if len(saved_states) == 1:
            raise RuntimeError("delete failed")

    reload = AsyncMock()
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {"assignment_id": "retired", "lifecycle_state": "retired"}
                ]
            },
            nilm_label_intervals_by_circuit={"mixed": [{"assignment_id": "retired"}]},
            nilm_signatures={"mixed": [{"assignment_id": "retired"}]},
            nilm_session_history_by_circuit={"mixed": [{"assignment_id": "retired"}]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=save
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
        config_entry_controller=SimpleNamespace(async_reload=reload),
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    controller._async_wait_for_assignment_entities = AsyncMock(return_value=False)

    with pytest.raises(RuntimeError, match="delete failed"):
        await controller.async_delete_nilm_appliance_assignment("mixed", "retired")

    assert coordinator.store_data == before
    assert len(saved_states) == 1
    assert reload.await_count == 0

    await controller.async_save_assignment_change()

    assert len(saved_states) == 2
    assert saved_states[1] == before
    assert reload.await_count == 1


@pytest.mark.asyncio
async def test_delete_assignment_rollback_survives_retention_copy() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    saved_states: list[FeatureStoreData] = []

    class FailingOnceStore:
        data: FeatureStoreData | None = None

        async def async_save(self) -> None:
            assert self.data is not None
            saved_states.append(deepcopy(self.data))
            if len(saved_states) == 1:
                raise RuntimeError("delete failed")

    reload = AsyncMock()
    store = FailingOnceStore()
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {"assignment_id": "retired", "lifecycle_state": "retired"}
                ]
            },
            nilm_label_intervals_by_circuit={
                "mixed": [{"interval_id": "interval-1", "assignment_id": "retired"}]
            },
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-1",
                        "assignment_id": "retired",
                        "review_state": "assigned",
                        "last_seen": now.isoformat(),
                    }
                ]
            },
            nilm_session_history_by_circuit={
                "mixed": [
                    {
                        "session_id": "session-1",
                        "assignment_id": "retired",
                        "end": now.isoformat(),
                    }
                ]
            },
        ),
        _store=store,
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
        config_entry_controller=SimpleNamespace(async_reload=reload),
    )
    coordinator.store_persistence = StorePersistenceManager(
        coordinator,
        retention_mode_for_circuit=lambda _circuit_id: object(),
        ha_time_zone=lambda: "UTC",
        weather_context_history_max_samples=10,
        water_context_history_max_samples=10,
        alert_history_max_age=timedelta(days=180),
        alert_history_max_items=100,
        alert_feedback_max_age=timedelta(days=365),
        alert_feedback_max_items=100,
        nilm_signatures_max_items=10,
        nilm_unknown_loads_max_items=10,
        nilm_session_history_max_age=timedelta(days=45),
        nilm_session_history_max_items=10,
        recommendation_history_max_age=timedelta(days=180),
        recommendation_history_max_items=100,
        recommendation_decisions_max_age=timedelta(days=180),
        recommendation_decisions_max_items=100,
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    controller._async_wait_for_assignment_entities = AsyncMock(return_value=False)

    with pytest.raises(RuntimeError, match="delete failed"):
        await controller.async_delete_nilm_appliance_assignment("mixed", "retired")

    assert coordinator.store_data == before
    assert reload.await_count == 0

    await controller.async_save_assignment_change()

    assert saved_states == [
        FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": []},
            nilm_label_intervals_by_circuit={"mixed": [{"interval_id": "interval-1"}]},
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-1",
                        "review_state": "new",
                        "last_seen": now.isoformat(),
                    }
                ]
            },
            nilm_session_history_by_circuit={
                "mixed": [{"session_id": "session-1", "end": now.isoformat()}]
            },
        ),
        before,
    ]
    assert coordinator.store_persistence.dirty is False
    assert reload.await_count == 1


@pytest.mark.asyncio
async def test_nilm_transactions_serialize_failed_save_before_delete() -> None:
    first_save_started = asyncio.Event()
    release_first_save = asyncio.Event()
    save_calls = 0

    async def save(_now: datetime) -> None:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            first_save_started.set()
            await release_first_save.wait()
            raise RuntimeError("save failed")

    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {
                        "assignment_id": "assignment-pump",
                        "lifecycle_state": "assigned",
                        "label_interval_ids": [],
                    },
                    {
                        "assignment_id": "assignment-retired",
                        "lifecycle_state": "retired",
                    },
                ]
            }
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=save
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    controller._async_wait_for_assignment_entities = AsyncMock(return_value=False)
    save_task = asyncio.create_task(
        controller.async_save_nilm_interval_changes(
            "mixed",
            label="Pump",
            assignment_id="assignment-pump",
            intervals=[
                {
                    "interval_id": "new",
                    "start": "2026-06-02T11:00:00+00:00",
                    "end": "2026-06-02T11:05:00+00:00",
                }
            ],
        )
    )
    await first_save_started.wait()
    delete_task = asyncio.create_task(
        controller.async_delete_nilm_appliance_assignment(
            "mixed", "assignment-retired"
        )
    )
    await asyncio.sleep(0)
    release_first_save.set()

    with pytest.raises(RuntimeError, match="save failed"):
        await save_task
    assert await delete_task is True
    assert [
        item["assignment_id"]
        for item in coordinator.store_data.nilm_appliance_assignments_by_circuit[
            "mixed"
        ]
    ] == ["assignment-pump"]
    assert (
        coordinator.store_data.nilm_label_intervals_by_circuit.get("mixed", []) == []
    )


@pytest.mark.asyncio
async def test_delete_retired_nilm_assignment_preserves_evidence() -> None:
    saves = AsyncMock()
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {
                        "assignment_id": "assignment-retired",
                        "lifecycle_state": "retired",
                    }
                ]
            },
            nilm_label_intervals_by_circuit={
                "mixed": [
                    {"interval_id": "label-1", "assignment_id": "assignment-retired"}
                ]
            },
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-1",
                        "assignment_id": "assignment-retired",
                        "review_state": "assigned",
                    }
                ]
            },
            nilm_session_history_by_circuit={
                "mixed": [
                    {"session_id": "session-1", "assignment_id": "assignment-retired"}
                ]
            },
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=saves
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    controller._async_wait_for_assignment_entities = AsyncMock(return_value=False)

    assert (
        await controller.async_delete_nilm_appliance_assignment(
            "mixed", "assignment-retired"
        )
        is True
    )
    assert coordinator.store_data.nilm_appliance_assignments_by_circuit["mixed"] == []
    assert (
        "assignment_id"
        not in coordinator.store_data.nilm_label_intervals_by_circuit["mixed"][0]
    )
    assert coordinator.store_data.nilm_signatures["mixed"][0] == {
        "signature_id": "signature-1",
        "review_state": "new",
    }
    assert (
        "assignment_id"
        not in coordinator.store_data.nilm_session_history_by_circuit["mixed"][0]
    )
    assert saves.await_count == 1


@pytest.mark.asyncio
async def test_delete_retired_nilm_assignment_preflights_entities_before_mutation() -> (
    None
):
    saves = AsyncMock()
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {"assignment_id": "retired", "lifecycle_state": "retired"}
                ]
            },
            nilm_label_intervals_by_circuit={"mixed": [{"assignment_id": "retired"}]},
            nilm_signatures={"mixed": [{"assignment_id": "retired"}]},
            nilm_session_history_by_circuit={"mixed": [{"assignment_id": "retired"}]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=saves
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    controller._async_wait_for_assignment_entities = AsyncMock(return_value=True)

    with pytest.raises(ValueError, match="Home Assistant entities"):
        await controller.async_delete_nilm_appliance_assignment("mixed", "retired")

    assert coordinator.store_data == before
    assert saves.await_count == 0


@pytest.mark.asyncio
async def test_delete_nilm_assignment_rejects_unknown_entity_state_before_mutation(
) -> None:
    saves = AsyncMock()
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {"assignment_id": "retired", "lifecycle_state": "retired"}
                ]
            },
            nilm_label_intervals_by_circuit={"mixed": [{"assignment_id": "retired"}]},
            nilm_signatures={"mixed": [{"assignment_id": "retired"}]},
            nilm_session_history_by_circuit={"mixed": [{"assignment_id": "retired"}]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=saves
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    controller._async_wait_for_assignment_entities = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="could not confirm"):
        await controller.async_delete_nilm_appliance_assignment("mixed", "retired")

    assert coordinator.store_data == before
    assert saves.await_count == 0


@pytest.mark.asyncio
async def test_delete_retired_nilm_assignment_once_when_entities_are_absent() -> None:
    saves = AsyncMock()
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {"assignment_id": "retired", "lifecycle_state": "retired"}
                ]
            },
            nilm_label_intervals_by_circuit={"mixed": [{"assignment_id": "retired"}]},
            nilm_signatures={"mixed": [{"assignment_id": "retired"}]},
            nilm_session_history_by_circuit={"mixed": [{"assignment_id": "retired"}]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=saves
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    controller._async_wait_for_assignment_entities = AsyncMock(return_value=False)

    assert (
        await controller.async_delete_nilm_appliance_assignment("mixed", "retired")
        is True
    )
    assert coordinator.store_data.nilm_appliance_assignments_by_circuit["mixed"] == []
    assert (
        "assignment_id"
        not in coordinator.store_data.nilm_label_intervals_by_circuit["mixed"][0]
    )
    assert coordinator.store_data.nilm_signatures["mixed"][0] == {"review_state": "new"}
    assert (
        "assignment_id"
        not in coordinator.store_data.nilm_session_history_by_circuit["mixed"][0]
    )
    assert saves.await_count == 1


@pytest.mark.asyncio
async def test_delete_nilm_assignment_rejects_active_and_preflights_entity_failure(
) -> None:
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {"assignment_id": "active", "lifecycle_state": "assigned"},
                    {"assignment_id": "retired", "lifecycle_state": "retired"},
                ]
            },
            nilm_label_intervals_by_circuit={"mixed": [{"assignment_id": "retired"}]},
            nilm_signatures={"mixed": [{"assignment_id": "retired"}]},
            nilm_session_history_by_circuit={"mixed": [{"assignment_id": "retired"}]},
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=AsyncMock()
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    before = deepcopy(coordinator.store_data)
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    controller._async_wait_for_assignment_entities = AsyncMock(return_value=True)

    with pytest.raises(ValueError, match="retired"):
        await controller.async_delete_nilm_appliance_assignment("mixed", "active")
    with pytest.raises(ValueError, match="removed first"):
        await controller.async_delete_nilm_appliance_assignment("mixed", "retired")

    assert coordinator.store_data == before


def test_upsert_assignment_preserves_existing_role_when_omitted() -> None:
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        store_data=FeatureStoreData(),
    )
    controller = _nilm_controller(coordinator)
    controller.upsert_assignment(
        "mixed",
        assignment_id="assignment-1",
        label="Load",
        role="primary",
    )

    assignment = controller.upsert_assignment(
        "mixed",
        assignment_id="assignment-1",
        label="Renamed",
    )

    assert assignment["role"] == "primary"


def test_nilm_reference_runtime_uses_state_then_power_only_fallback() -> None:
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        nilm_reference_runtime,
    )

    rows = {
        "switch.pump": SimpleNamespace(state="off", attributes={}),
        "sensor.pump_power": SimpleNamespace(
            state="0.084",
            attributes={"device_class": "power", "unit_of_measurement": "kW"},
        ),
    }
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(states=SimpleNamespace(get=rows.get))
    )

    state_reference = nilm_reference_runtime(
        coordinator,
        {
            "reference_state_entity_id": "switch.pump",
            "reference_power_entity_id": "sensor.pump_power",
            "reference_threshold_w": 25,
        },
    )
    assert state_reference == {
        "available": True,
        "is_running": False,
        "measured_power_w": 84.0,
        "source_entity_id": "switch.pump",
        "fallback_to_nilm": False,
        "state_mode": "binary_state",
    }

    power_reference = nilm_reference_runtime(
        coordinator,
        {
            "reference_power_entity_id": "sensor.pump_power",
            "reference_threshold_w": 100,
            "reference_on_threshold": 25,
        },
    )
    assert power_reference["is_running"] is True
    assert power_reference["source_entity_id"] == "sensor.pump_power"
    assert power_reference["state_mode"] == "stateless_numeric"

    legacy_power_reference = nilm_reference_runtime(
        coordinator,
        {
            "reference_power_entity_id": "sensor.pump_power",
            "reference_threshold_w": 100,
        },
    )
    assert legacy_power_reference["is_running"] is False
    assert legacy_power_reference["state_mode"] == "stateless_numeric"

    assert nilm_reference_runtime(
        coordinator,
        {
            "lifecycle_state": "retired",
            "reference_state_entity_id": "switch.pump",
        },
    )["fallback_to_nilm"] is True


@pytest.mark.asyncio
async def test_configured_primary_uses_configured_identity_and_role() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )
    from custom_components.circuitsetup_energy_analyzer.nilm_virtual import (
        published_nilm_virtual_appliance_states,
    )
    from custom_components.circuitsetup_energy_analyzer.profiles import (
        supports_direct_appliance_analysis,
    )

    config = _config(
        ApplianceProfile.HVAC_BLOWER,
        CircuitMode.MIXED,
        "mixed",
        "Upstairs Blower",
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-1",
                        "feedback_fingerprint": "fingerprint-1",
                        "confidence": 0.91,
                    }
                ]
            }
        ),
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.circuit_configs = (config,)
    assignment_id = configured_primary_assignment_id("mixed")

    first = await coordinator.async_assign_nilm_signature(
        "mixed",
        "signature-1",
        label="spoofed",
        appliance_profile="washer",
        assignment_id=assignment_id,
    )
    second = await coordinator.async_assign_nilm_signature(
        "mixed",
        "signature-1",
        label="changed",
        assignment_id=assignment_id,
    )

    assert first["assignment_id"] == second["assignment_id"] == assignment_id
    assert second["display_name"] == "Upstairs Blower"
    assert second["appliance_profile"] == ApplianceProfile.HVAC_BLOWER.value
    assert second["role"] == "primary"
    assert second["signature_fingerprints"] == ["fingerprint-1"]
    assert (
        len(coordinator.store_data.nilm_appliance_assignments_by_circuit["mixed"]) == 1
    )

    assigned = second
    await coordinator.async_assign_nilm_session(
        "mixed",
        "session-1",
        label="spoofed session",
        appliance_profile="washer",
        assignment_id=assignment_id,
    )
    validated = await coordinator.async_validate_nilm_session(
        "mixed",
        "session-1",
        assignment_id=assignment_id,
    )
    stored_assignment = coordinator.store_data.nilm_appliance_assignments_by_circuit[
        "mixed"
    ][0]
    stored_assignment.update(
        {
            "session_ids": [
                "publication-session-1",
                "publication-session-2",
                "publication-session-3",
            ],
            "confirmed_session_ids": [
                "publication-session-1",
                "publication-session-2",
                "publication-session-3",
            ],
            "rejected_session_ids": [],
            "feedback_evidence_score": 0.9,
            "model_fit": 0.9,
            "validation_evaluable_session_count": 3,
            "validation_precision": 1.0,
            "false_positive_rate": 0.0,
        }
    )
    coordinator.store_data.nilm_session_history_by_circuit["mixed"] = [
        {
            "session_id": f"publication-session-{index}",
            "assignment_id": assignment_id,
            "start": f"2026-05-{28 + index:02d}T12:00:00+00:00",
            "end": f"2026-05-{28 + index:02d}T12:20:00+00:00",
            "ambiguous": False,
            "energy_source": "residual_trace_measured",
            "known_source_coverage_min": 1.0,
            "known_source_coverage_time_weighted": 1.0,
            "stale_subtraction_prevented_count": 0,
            "partial_residual_point_count": 0,
            "negative_residual_point_count": 0,
        }
        for index in range(1, 4)
    ]
    published = await coordinator.async_publish_nilm_appliance_assignment(
        "mixed",
        assignment_id,
    )

    assert assigned["lifecycle_state"] == "assigned"
    assert validated["lifecycle_state"] == "validated"
    assert published["lifecycle_state"] == "published"
    assert published["role"] == "primary"
    virtual = published_nilm_virtual_appliance_states(coordinator)[0]
    assert virtual.assignment_id == assignment_id
    assert virtual.display_name == "Upstairs Blower (estimated)"
    assert not supports_direct_appliance_analysis(config)


@pytest.mark.asyncio
async def test_configured_primary_can_be_confirmed_without_rediscovery() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    config = _config(
        ApplianceProfile.HVAC_BLOWER,
        CircuitMode.MIXED,
        "mixed",
        "Upstairs Blower",
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-1",
                        "feedback_fingerprint": "fingerprint-1",
                        "confidence": 0.91,
                    }
                ]
            }
        ),
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.circuit_configs = (config,)
    assignment_id = configured_primary_assignment_id("mixed")
    assignment = await coordinator.async_assign_nilm_signature(
        "mixed",
        "signature-1",
        label="Upstairs Blower",
        assignment_id=assignment_id,
    )
    assignment["lifecycle_state"] = "needs_validation"

    confirmed = await coordinator.async_confirm_nilm_configured_primary(
        "mixed",
        assignment_id,
    )

    assert confirmed["lifecycle_state"] == "validated"
    assert confirmed["last_validation"] == "configured_primary"
    assert confirmed["last_validated_at"] == "2026-06-02T12:00:00+00:00"
    with pytest.raises(ValueError, match="configured primary"):
        await coordinator.async_confirm_nilm_configured_primary(
            "mixed",
            "assignment-other",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["session", "interval"])
async def test_primary_identity_survives_other_assignments(action: str) -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    config = _config(
        ApplianceProfile.HVAC_BLOWER,
        CircuitMode.MIXED,
        "mixed",
        "Blower",
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-1",
                        "feedback_fingerprint": "fp-1",
                    }
                ]
            },
            nilm_label_intervals_by_circuit={
                "mixed": [
                    {
                        "interval_id": "interval-1",
                        "label": "client interval",
                    }
                ]
            },
        ),
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.circuit_configs = (config,)
    assignment_id = configured_primary_assignment_id("mixed")
    await coordinator.async_assign_nilm_signature(
        "mixed",
        "signature-1",
        label="client",
        assignment_id=assignment_id,
    )

    if action == "session":
        assignment = await coordinator.async_assign_nilm_session(
            "mixed",
            "session-1",
            label="client session",
            appliance_profile="washer",
            assignment_id=assignment_id,
        )
    else:
        assignment = await coordinator.async_assign_nilm_interval(
            "mixed",
            "interval-1",
            label="client interval",
            appliance_profile="washer",
            assignment_id=assignment_id,
        )

    assert assignment["display_name"] == "Blower"
    assert assignment["appliance_profile"] == ApplianceProfile.HVAC_BLOWER.value
    assert assignment["role"] == "primary"


@pytest.mark.asyncio
async def test_configured_primary_replaces_the_previous_signature_binding() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    config = _config(
        ApplianceProfile.HVAC_BLOWER,
        CircuitMode.MIXED,
        "mixed",
        "Blower",
    )
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-1",
                        "feedback_fingerprint": "fingerprint-1",
                        "confidence": 0.9,
                    },
                    {
                        "signature_id": "signature-2",
                        "feedback_fingerprint": "fingerprint-2",
                        "confidence": 0.92,
                    },
                ]
            }
        ),
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.circuit_configs = (config,)
    assignment_id = configured_primary_assignment_id("mixed")

    await coordinator.async_assign_nilm_signature(
        "mixed", "signature-1", label="Blower", assignment_id=assignment_id
    )
    assignment = await coordinator.async_assign_nilm_signature(
        "mixed", "signature-2", label="Blower", assignment_id=assignment_id
    )

    signatures = coordinator.store_data.nilm_signatures["mixed"]
    assert assignment["signature_fingerprints"] == ["fingerprint-2"]
    assert "assignment_id" not in signatures[0]
    assert signatures[1]["assignment_id"] == assignment_id


@pytest.mark.asyncio
async def test_configured_primary_clears_legacy_fingerprint_binding() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    config = _config(
        ApplianceProfile.HVAC_BLOWER,
        CircuitMode.MIXED,
        "mixed",
        "Blower",
    )
    assignment_id = configured_primary_assignment_id("mixed")
    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-old",
                        "feedback_fingerprint": "fingerprint-old",
                        "confidence": 0.9,
                        "review_state": "assigned",
                        "user_label": "Blower",
                    },
                    {
                        "signature_id": "signature-new",
                        "feedback_fingerprint": "fingerprint-new",
                        "confidence": 0.92,
                    },
                ]
            },
            nilm_appliance_assignments_by_circuit={
                "mixed": [
                    {
                        "assignment_id": assignment_id,
                        "signature_fingerprints": ["fingerprint-old"],
                        "lifecycle_state": "assigned",
                        "confidence": 0.9,
                    }
                ]
            },
        ),
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.circuit_configs = (config,)

    await coordinator.async_assign_nilm_signature(
        "mixed", "signature-new", label="Blower", assignment_id=assignment_id
    )

    old_signature = coordinator.store_data.nilm_signatures["mixed"][0]
    assert old_signature["review_state"] == "new"
    assert "user_label" not in old_signature


@pytest.mark.asyncio
async def test_restore_nilm_item_reverses_hidden_lifecycles_and_persists() -> None:
    async def save(_now: datetime) -> None:
        return None

    assignments = [
        {
            "assignment_id": "assignment-ignored",
            "signature_fingerprints": ["fingerprint-ignored"],
            "session_ids": [],
            "label_interval_ids": [],
            "lifecycle_state": "ignored",
        },
        {
            "assignment_id": "assignment-retired",
            "signature_fingerprints": ["fingerprint-retired"],
            "session_ids": ["session-old"],
            "label_interval_ids": ["interval-old"],
            "lifecycle_state": "retired",
            "publish_entities": False,
        },
    ]
    signatures = [
        {
            "signature_id": "signature-ignored",
            "feedback_fingerprint": "fingerprint-ignored",
            "assignment_id": "assignment-ignored",
            "review_state": "ignored",
            "ignored": True,
        },
        {
            "signature_id": "signature-retired",
            "feedback_fingerprint": "fingerprint-retired",
            "assignment_id": "assignment-retired",
            "review_state": "assigned",
        },
    ]
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        ignored_nilm_signatures={("mixed", "signature-ignored")},
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": assignments},
            nilm_signatures={"mixed": signatures},
        ),
        state=SimpleNamespace(),
        refresh_ux_state_for_circuit=lambda *_args: None,
        async_set_updated_data=lambda _state: None,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(side_effect=save),
        ),
    )
    controller = NilmController(
        coordinator,
        label_interval_max_items=8,
        assignment_max_items=8,
    )
    controller.refresh_state = lambda *_args, **_kwargs: None

    restored_signature = await controller.async_restore_nilm_item(
        "mixed", signature_id="signature-ignored"
    )
    restored_retired = await controller.async_restore_nilm_item(
        "mixed", assignment_id="assignment-retired"
    )

    assert restored_signature["review_state"] == "new"
    assert "ignored" not in restored_signature
    assert "assignment_id" not in restored_signature
    assert not any(
        item["assignment_id"] == "assignment-ignored"
        for item in coordinator.store_data.nilm_appliance_assignments_by_circuit[
            "mixed"
        ]
    )
    assert restored_retired["lifecycle_state"] == "assigned"
    assert restored_retired["session_ids"] == ["session-old"]
    assert restored_retired["label_interval_ids"] == ["interval-old"]
    assert coordinator.store_persistence.async_save_if_dirty.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("assignment_id", "signature_id"),
    ((None, None), ("assignment-1", "signature-1")),
)
async def test_restore_nilm_item_requires_exactly_one_identifier(
    assignment_id: str | None,
    signature_id: str | None,
) -> None:
    controller = _nilm_controller(SimpleNamespace(store_data=FeatureStoreData()))

    with pytest.raises(ValueError, match="exactly one"):
        await controller.async_restore_nilm_item(
            "mixed",
            assignment_id=assignment_id,
            signature_id=signature_id,
        )


@pytest.mark.asyncio
async def test_restore_nilm_item_reverts_direct_meter_conversion() -> None:
    assignment = {
        "assignment_id": "assignment-condensate",
        "display_name": "Condensate Pump 2",
        "signature_fingerprints": ["fingerprint-condensate"],
        "session_ids": ["session-1"],
        "lifecycle_state": "converted",
        "conversion_state": "direct_meter",
        "direct_circuit_id": "ac2",
        "converted_at": "2026-06-01T12:00:00+00:00",
        "pre_conversion_lifecycle_state": "assigned",
        "keep_assignment_for_masking": True,
        "keep_published_estimate": False,
        "publish_entities": False,
    }
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        ignored_nilm_signatures=set(),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]},
            nilm_signatures={"mixed": []},
        ),
        state=SimpleNamespace(),
        refresh_ux_state_for_circuit=lambda *_args: None,
        async_set_updated_data=lambda _state: None,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
    )
    controller = _nilm_controller(coordinator)
    controller.refresh_state = lambda *_args, **_kwargs: None

    restored = await controller.async_restore_nilm_item(
        "mixed", assignment_id="assignment-condensate"
    )

    assert restored["lifecycle_state"] == "assigned"
    assert restored["session_ids"] == ["session-1"]
    for key in (
        "conversion_state",
        "direct_circuit_id",
        "converted_at",
        "pre_conversion_lifecycle_state",
        "keep_assignment_for_masking",
        "keep_published_estimate",
    ):
        assert key not in restored
    coordinator.store_persistence.async_save_if_dirty.assert_awaited_once()


@pytest.mark.asyncio
async def test_reserved_primary_is_rejected_outside_primary_mixed() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-1",
                        "feedback_fingerprint": "fingerprint-1",
                    }
                ]
            }
        ),
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.circuit_configs = (
        _config(ApplianceProfile.MIXED, CircuitMode.MIXED, "mixed", "Mixed"),
    )

    with pytest.raises(ValueError, match="configured primary"):
        await coordinator.async_assign_nilm_signature(
            "mixed",
            "signature-1",
            label="Dishwasher",
            assignment_id=configured_primary_assignment_id("mixed"),
        )


def test_nilm_assignment_identity_and_history_survive_restart() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    store_data = FeatureStoreData(
        nilm_session_history_by_circuit={
            "mixed": [
                {
                    "session_id": "session-old",
                    "assignment_id": "assignment-dishwasher",
                    "start": "2026-06-01T10:00:00+00:00",
                    "end": "2026-06-01T10:30:00+00:00",
                },
                {
                    "session_id": "session-other",
                    "assignment_id": "assignment-dryer",
                    "start": "2026-06-02T11:00:00+00:00",
                    "end": "2026-06-02T11:30:00+00:00",
                },
                {
                    "session_id": "session-new",
                    "assignment_id": "assignment-dishwasher",
                    "start": "2026-06-02T10:00:00+00:00",
                    "end": "2026-06-02T10:30:00+00:00",
                },
            ]
        }
    )
    controller = _nilm_controller(
        SimpleNamespace(current_time=lambda: now, store_data=store_data)
    )
    assignment = controller.upsert_assignment(
        "mixed",
        assignment_id="assignment-dishwasher",
        appliance_id="dishwasher",
        label="Kitchen Dishwasher",
        appliance_profile="dishwasher",
        session_id="session-new",
    )
    assignment.update(
        {
            "confirmed_session_ids": ["session-new"],
            "rejected_session_ids": ["session-old"],
            "last_validation": "correct",
        }
    )

    restored = feature_store_data_from_dict(feature_store_data_to_dict(store_data))
    restarted = _nilm_controller(
        SimpleNamespace(current_time=lambda: now, store_data=restored)
    )
    restored_assignment = restarted.assignment_for_id(
        "mixed",
        "assignment-dishwasher",
    )
    history = restarted.assignment_session_history(
        "mixed",
        "assignment-dishwasher",
    )

    assert restored_assignment["appliance_key"] == "nilm:assignment-dishwasher"
    assert restored_assignment["display_name"] == "Kitchen Dishwasher"
    assert restored_assignment["confirmed_session_ids"] == ["session-new"]
    assert restored_assignment["rejected_session_ids"] == ["session-old"]
    assert restored_assignment["last_validation"] == "correct"
    assert [session["session_id"] for session in history] == [
        "session-new",
        "session-old",
    ]


def test_rebuild_assignment_model_uses_home_assistant_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer.managers import (
        nilm_controller as controller_module,
    )

    captured_time_zones: list[str | None] = []

    def build_model(*_args: object, **kwargs: object) -> dict[str, object]:
        captured_time_zones.append(kwargs.get("time_zone"))
        return {}

    monkeypatch.setattr(controller_module, "build_nilm_assignment_model", build_model)
    coordinator = SimpleNamespace(
        context_builder=SimpleNamespace(time_zone=lambda: "America/New_York"),
        store_data=SimpleNamespace(
            nilm_session_history_by_circuit={"mains": []},
            nilm_label_intervals_by_circuit={"mains": []},
        ),
    )
    controller = _nilm_controller(coordinator)

    controller._rebuild_assignment_model("mains", {"assignment_id": "pump"})

    assert captured_time_zones == ["America/New_York"]


def test_hydration_normalizes_optional_assignment_model_fields_once() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "pump",
        "confirmed_session_ids": ["session-1"],
        "role": "component",
        "power_states_w": [0.0, 80.0],
        "transition_prototypes": [
            {
                "direction": "on",
                "from_state_w": 0.0,
                "to_state_w": 80.0,
                "delta_w": 80.0,
                "spread_w": 0.0,
            },
            {
                "direction": "off",
                "from_state_w": 80.0,
                "to_state_w": 0.0,
                "delta_w": -80.0,
                "spread_w": 0.0,
            },
        ],
        "model_confidence": 0.5,
        "model_revision": 0,
    }
    store_data = FeatureStoreData(
        nilm_appliance_assignments_by_circuit={"mixed": [assignment]},
        nilm_session_history_by_circuit={
            "mixed": [
                {
                    "session_id": "session-1",
                    "assignment_id": "pump",
                    "start": "2026-06-01T10:00:00+00:00",
                    "end": "2026-06-01T10:05:00+00:00",
                    "median_power_w": 83.0,
                    "on_delta_w": 83.0,
                    "off_delta_w": -83.0,
                    "on_delta_var": None,
                    "off_delta_var": None,
                    "on_edge_id": (
                        "on|2026-06-01T10:00:00+00:00|w=83.000|"
                        "var=27.000|unknown|unknown"
                    ),
                    "off_edge_id": (
                        "off|2026-06-01T10:05:00+00:00|w=-83.000|"
                        "var=-4.000|unknown|unknown"
                    ),
                    "confidence": 0.9,
                    "ambiguous": True,
                }
            ]
        },
    )
    dirty: list[bool] = []
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=store_data,
        store_persistence=SimpleNamespace(mark_dirty=lambda: dirty.append(True)),
    )
    controller = _nilm_controller(coordinator)

    controller.hydrate_state_from_store()

    assert assignment["model_schema_version"] == 2
    assert assignment["model_kind"] == "binary"
    assert assignment["role"] == "component"
    assert assignment["power_states_w"] == [0.0, 83.0]
    assert assignment["transition_prototypes"][0]["delta_var"] == 27.0
    assert assignment["transition_prototypes"][1]["delta_var"] == -4.0
    assert assignment["model_revision"] == 1
    assert dirty == [True]

    restarted_store = feature_store_data_from_dict(
        feature_store_data_to_dict(store_data)
    )
    restart_dirty: list[bool] = []
    restarted = _nilm_controller(
        SimpleNamespace(
            current_time=lambda: now,
            store_data=restarted_store,
            store_persistence=SimpleNamespace(
                mark_dirty=lambda: restart_dirty.append(True)
            ),
        )
    )
    restarted.hydrate_state_from_store()

    restarted_assignment = restarted_store.nilm_appliance_assignments_by_circuit[
        "mixed"
    ][0]
    assert restarted_assignment["model_schema_version"] == 2
    assert restarted_assignment["model_revision"] == 1
    assert restart_dirty == []

    for prototype in assignment["transition_prototypes"]:
        prototype.pop("delta_var")
        prototype.pop("spread_var")
    controller.hydrate_state_from_store()
    controller.hydrate_state_from_store()

    assert assignment["transition_prototypes"][0]["delta_var"] == 27.0
    assert assignment["transition_prototypes"][1]["delta_var"] == -4.0
    assert assignment["model_revision"] == 2
    assert dirty == [True, True]


def test_hydration_upgrades_v1_model_without_retained_evidence_once() -> None:
    assignment = {
        "assignment_id": "pump",
        "role": "component",
        "power_states_w": [0.0, 83.0],
        "transition_prototypes": [
            {
                "direction": "on",
                "from_state_w": 0.0,
                "to_state_w": 83.0,
                "delta_w": 83.0,
                "spread_w": 1.0,
            },
            {
                "direction": "off",
                "from_state_w": 83.0,
                "to_state_w": 0.0,
                "delta_w": -83.0,
                "spread_w": 1.0,
            },
        ],
        "model_confidence": 0.8,
        "model_revision": 4,
    }
    dirty: list[bool] = []
    coordinator = SimpleNamespace(
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]}
        ),
        store_persistence=SimpleNamespace(mark_dirty=lambda: dirty.append(True)),
    )

    controller = _nilm_controller(coordinator)
    controller.hydrate_state_from_store()
    controller.hydrate_state_from_store()

    assert assignment["model_schema_version"] == 2
    assert assignment["power_states_w"] == [0.0, 83.0]
    assert assignment["model_revision"] == 4
    assert dirty == [True]


def test_hydration_keeps_legacy_projection_when_matching_evidence_is_unusable() -> (
    None
):
    assignment = {
        "assignment_id": "pump",
        "confirmed_session_ids": ["malformed"],
        "role": "component",
        "power_states_w": [0.0, 83.0],
        "transition_prototypes": [
            {
                "direction": "on",
                "from_state_w": 0.0,
                "to_state_w": 83.0,
                "delta_w": 83.0,
                "spread_w": 1.0,
                "sample_count": 3,
            },
            {
                "direction": "off",
                "from_state_w": 83.0,
                "to_state_w": 0.0,
                "delta_w": -83.0,
                "spread_w": 1.0,
                "sample_count": 3,
            },
        ],
        "model_confidence": 0.8,
        "model_revision": 4,
    }
    dirty: list[bool] = []
    coordinator = SimpleNamespace(
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]},
            nilm_session_history_by_circuit={
                "mixed": [
                    {
                        "session_id": "malformed",
                        "assignment_id": "pump",
                        "on_delta_w": "unknown",
                        "off_delta_w": None,
                        "median_power_w": float("nan"),
                        "measured_energy_kwh": -1,
                    }
                ]
            },
        ),
        store_persistence=SimpleNamespace(mark_dirty=lambda: dirty.append(True)),
    )

    _nilm_controller(coordinator).hydrate_state_from_store()

    assert assignment["model_schema_version"] == 2
    assert assignment["power_states_w"] == [0.0, 83.0]
    assert {
        prototype["direction"] for prototype in assignment["transition_prototypes"]
    } == {"on", "off"}
    assert assignment["model_revision"] == 4
    assert dirty == [True]


def test_hydration_persists_changed_v2_profile_when_projection_is_unchanged() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    label_intervals = [
        {
            "interval_id": "interval-1",
            "assignment_id": "pump",
            "start": "2026-06-01T10:00:00+00:00",
            "end": "2026-06-01T10:05:00+00:00",
            "median_power_w": 83.0,
            "evidence_schema_version": 2,
            "plateau_eligible": True,
            "power_coverage": 1.0,
            "confidence": 0.9,
        }
    ]
    assignment = {
        "assignment_id": "pump",
        "label_interval_ids": ["interval-1"],
    }
    assignment.update(
        build_nilm_assignment_model(assignment, (), label_intervals=label_intervals)
    )
    assignment["run_profile"]["duration_s"]["median"] = 999.0
    assignment["model_fingerprint"] = "stale-fingerprint"
    assignment["model_revision"] = 1
    dirty: list[bool] = []
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]},
            nilm_label_intervals_by_circuit={"mixed": label_intervals},
        ),
        store_persistence=SimpleNamespace(mark_dirty=lambda: dirty.append(True)),
    )

    _nilm_controller(coordinator).hydrate_state_from_store()

    assert assignment["power_states_w"] == [0.0, 83.0]
    assert assignment["run_profile"]["duration_s"]["median"] == 300.0
    assert assignment["model_fingerprint"] != "stale-fingerprint"
    assert assignment["model_revision"] == 2
    assert dirty == [True]


def test_hydration_reopens_legacy_expected_signature_once() -> None:
    signature = {
        "signature_id": "signature-expected",
        "feedback_fingerprint": "fingerprint-expected",
        "review_state": "expected",
        "expected": True,
        "assignment_id": "assignment-expected",
    }
    expected_assignment = {
        "assignment_id": "assignment-expected",
        "lifecycle_state": "expected",
        "signature_fingerprints": ["fingerprint-expected"],
        "session_ids": ["session-expected"],
        "label_interval_ids": ["interval-expected"],
    }
    retained_assignment = {
        "assignment_id": "assignment-retained",
        "lifecycle_state": "assigned",
        "signature_fingerprints": ["fingerprint-retained"],
        "session_ids": [],
        "label_interval_ids": [],
    }
    session = {
        "session_id": "session-expected",
        "assignment_id": "assignment-expected",
    }
    interval = {
        "interval_id": "interval-expected",
        "assignment_id": "assignment-expected",
    }
    dirty: list[bool] = []
    coordinator = SimpleNamespace(
        store_data=FeatureStoreData(
            nilm_signatures={"mixed": [signature]},
            nilm_appliance_assignments_by_circuit={
                "mixed": [expected_assignment, retained_assignment]
            },
            nilm_session_history_by_circuit={"mixed": [session]},
            nilm_label_intervals_by_circuit={"mixed": [interval]},
        ),
        store_persistence=SimpleNamespace(mark_dirty=lambda: dirty.append(True)),
    )
    controller = _nilm_controller(coordinator)
    controller.refresh_state = lambda _circuit_id: None

    controller.hydrate_state_from_store()
    controller.hydrate_state_from_store()

    assert signature["review_state"] == "new"
    assert "expected" not in signature
    assert "assignment_id" not in signature
    assert coordinator.store_data.nilm_appliance_assignments_by_circuit["mixed"] == [
        retained_assignment
    ]
    assert "assignment_id" not in session
    assert "assignment_id" not in interval
    assert dirty == [True]


def test_component_runtime_state_is_runtime_only() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
    from custom_components.circuitsetup_energy_analyzer.managers.state_reducer import (
        StateReducer,
    )

    state = AnalyzerState()
    reducer = StateReducer()
    reducer.apply_update(
        state,
        ("nilm_component_runtime_by_circuit", "mixed"),
        {"pump": {"status": "on"}},
    )
    reducer.apply_update(
        state,
        ("nilm_reconciliation_by_circuit", "mixed"),
        {"consistent": True},
    )

    payload = feature_store_data_to_dict(FeatureStoreData())

    assert "nilm_component_runtime_by_circuit" not in payload
    assert "nilm_reconciliation_by_circuit" not in payload


def test_hydration_normalizes_malformed_optional_model_fields() -> None:
    assignment = {
        "assignment_id": "pump",
        "role": None,
        "power_states_w": [float("nan")],
        "transition_prototypes": None,
        "model_confidence": float("nan"),
        "model_revision": "bad",
    }
    coordinator = SimpleNamespace(
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]}
        )
    )

    _nilm_controller(coordinator).hydrate_state_from_store()

    assert assignment["role"] == "component"
    assert assignment["power_states_w"] == []
    assert assignment["transition_prototypes"] == []
    assert assignment["model_confidence"] == assignment["model_revision"] == 0


@pytest.mark.asyncio
async def test_assignment_merge_reowns_history_before_model_rebuild() -> None:
    async def noop(*_args: object) -> None:
        return None

    assignments = [
        {"assignment_id": "source", "confirmed_session_ids": ["source-session"]},
        {"assignment_id": "target", "confirmed_session_ids": ["target-session"]},
    ]
    history = [
        {
            "session_id": "source-session",
            "assignment_id": "source",
            "end": "2026-06-01T10:00:00+00:00",
            "on_delta_w": 100.0,
            "off_delta_w": -100.0,
            "confidence": 0.9,
        },
        {
            "session_id": "target-session",
            "assignment_id": "target",
            "end": "2026-06-02T10:00:00+00:00",
            "on_delta_w": 80.0,
            "off_delta_w": -80.0,
            "confidence": 0.9,
        },
        {
            "session_id": "other",
            "assignment_id": "other",
            "end": "2026-06-02T11:00:00+00:00",
            "on_delta_w": 500.0,
            "off_delta_w": -500.0,
            "confidence": 1.0,
        },
    ]
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": assignments},
            nilm_session_history_by_circuit={"mixed": history},
        ),
        state=SimpleNamespace(),
        async_set_updated_data=lambda _state: None,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=noop
        ),
        config_entry_controller=SimpleNamespace(async_reload=noop),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )

    merged = await controller.async_merge_nilm_assignments("mixed", "source", "target")

    assert history[0]["assignment_id"] == "target"
    assert merged["power_states_w"] == [0.0, 90.0]
    assert merged["transition_prototypes"][0]["sample_count"] == 2


@pytest.mark.asyncio
async def test_configured_primary_merge_keeps_labels_and_drops_invalid_binding(
) -> None:
    async def noop(*_args: object) -> None:
        return None

    target_id = configured_primary_assignment_id("hvac_1")
    assignments = [
        {
            "assignment_id": "reviewed-hvac",
            "signature_fingerprints": ["direction=on|watts=300-400"],
            "label_interval_ids": ["label-hvac"],
        },
        {
            "assignment_id": target_id,
            "signature_fingerprints": ["direction=off|watts=200-300"],
        },
    ]
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 8, 4, tzinfo=UTC),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"hvac_1": assignments},
            nilm_label_intervals_by_circuit={
                "hvac_1": [
                    {"interval_id": "label-hvac", "assignment_id": "reviewed-hvac"}
                ]
            },
        ),
        state=SimpleNamespace(),
        async_set_updated_data=lambda _state: None,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=noop
        ),
        config_entry_controller=SimpleNamespace(async_reload=noop),
    )

    merged = await _nilm_controller(coordinator).async_merge_nilm_assignments(
        "hvac_1", "reviewed-hvac", target_id
    )

    assert merged["signature_fingerprints"] == ["direction=on|watts=300-400"]
    assert merged["label_interval_ids"] == ["label-hvac"]
    assert coordinator.store_data.nilm_label_intervals_by_circuit["hvac_1"][0][
        "assignment_id"
    ] == target_id


@pytest.mark.asyncio
async def test_mixed_nilm_signature_review_keeps_stable_assignment_identity() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        store_data=FeatureStoreData(
            nilm_signatures={
                "mixed": [
                    {
                        "signature_id": "signature-dishwasher",
                        "feedback_fingerprint": "dishwasher-fingerprint",
                    }
                ]
            }
        ),
        now_fn=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    coordinator.circuit_configs = (
        CircuitConfig(
            circuit_id="mixed",
            name="Mixed",
            mode=CircuitMode.MIXED,
            appliance_profile=ApplianceProfile.MOTOR_LOAD,
        ),
    )

    assignment = await coordinator.async_assign_nilm_signature(
        "mixed",
        "signature-dishwasher",
        label="Dishwasher",
        appliance_id="dishwasher",
        assignment_id="assignment-dishwasher",
    )

    assert assignment["assignment_id"] == "assignment-dishwasher"
    assert assignment["appliance_key"] == "nilm:assignment-dishwasher"
    assert coordinator.store_data.nilm_signatures["mixed"][0]["assignment_id"] == (
        "assignment-dishwasher"
    )


@pytest.mark.asyncio
async def test_convert_nilm_assignment_to_direct_meter_preserves_history() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    async def async_noop(*_args: object) -> None:
        return None

    assignment = {
        "assignment_id": "assignment-dishwasher",
        "appliance_key": "nilm:assignment-dishwasher",
        "appliance_id": "dishwasher",
        "display_name": "Kitchen Dishwasher",
        "appliance_profile": "dishwasher",
        "mains_circuit_id": "mains",
        "signature_fingerprints": ["signature-1"],
        "session_ids": ["session-1", "session-2"],
        "confirmed_session_ids": ["session-1"],
        "rejected_session_ids": ["session-2"],
        "label_interval_ids": ["interval-1"],
        "last_validation": "wrong_appliance",
        "lifecycle_state": "published",
        "publish_entities": True,
        "created_device": True,
    }
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mains": [assignment]},
        ),
        state=SimpleNamespace(),
        async_set_updated_data=lambda _state: None,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=async_noop,
        ),
        config_entry_controller=SimpleNamespace(async_reload=async_noop),
    )
    controller = _nilm_controller(coordinator)

    converted = await controller.async_convert_nilm_assignment_to_direct_meter(
        "mains",
        "assignment-dishwasher",
        direct_circuit_id="dishwasher_direct",
    )

    assert converted["appliance_key"] == "nilm:assignment-dishwasher"
    assert converted["display_name"] == "Kitchen Dishwasher"
    assert converted["appliance_profile"] == "dishwasher"
    assert converted["signature_fingerprints"] == ["signature-1"]
    assert converted["session_ids"] == ["session-1", "session-2"]
    assert converted["confirmed_session_ids"] == ["session-1"]
    assert converted["rejected_session_ids"] == ["session-2"]
    assert converted["label_interval_ids"] == ["interval-1"]
    assert converted["last_validation"] == "wrong_appliance"
    assert converted["conversion_state"] == "direct_meter"
    assert converted["direct_circuit_id"] == "dishwasher_direct"
    assert converted["converted_at"] == now.isoformat()
    assert converted["publish_entities"] is False
    assert converted["created_device"] is False
    assert converted["keep_published_estimate"] is False

    with pytest.raises(ValueError, match="cannot republish"):
        await controller.async_publish_nilm_appliance_assignment(
            "mains",
            "assignment-dishwasher",
        )


def test_assignment_history_prefers_explicit_session_owner() -> None:
    store_data = FeatureStoreData(
        nilm_appliance_assignments_by_circuit={
            "mains": [
                {
                    "assignment_id": "assignment-one",
                    "session_ids": ["stale-session"],
                }
            ]
        },
        nilm_session_history_by_circuit={
            "mains": [
                {
                    "session_id": "stale-session",
                    "assignment_id": "assignment-two",
                }
            ]
        },
    )
    controller = _nilm_controller(SimpleNamespace(store_data=store_data))

    assert controller.assignment_session_history("mains", "assignment-one") == []


@pytest.mark.asyncio
async def test_nilm_helper_links_validate_persist_replace_and_remove() -> None:
    controller, assignment = _helper_link_controller()
    linked = await controller.async_set_nilm_helper_link(
        "mixed",
        "assignment-load",
        helper_circuit_id="helper",
        relationship="corroborates",
    )
    link = linked["helper_links"][0]
    assert link["helper_circuit_id"] == "helper"
    assert link["relationship"] == "corroborates"
    assert link["status"] == "confirmed"
    assert link["confidence"] == 0.91
    assert link["matched_on_count"] == link["confirmed_matched_on_count"] == 4
    assert link["matched_off_count"] == link["confirmed_matched_off_count"] == 5
    assert link["last_observed"] == "2026-06-02T11:00:00+00:00"
    forbidden = {
        "conversion_state",
        "direct_circuit_id",
        "keep_assignment_for_masking",
        "publish_entities",
    }
    assert not forbidden & assignment.keys()
    replaced = await controller.async_set_nilm_helper_link(
        "mixed",
        "assignment-load",
        helper_circuit_id="helper",
        relationship="direct_component",
    )
    assert len(replaced["helper_links"]) == 1
    assert replaced["helper_links"][0]["relationship"] == "direct_component"
    removed = await controller.async_remove_nilm_helper_link(
        "mixed",
        "assignment-load",
        helper_circuit_id="helper",
    )
    assert removed["helper_links"] == []


@pytest.mark.asyncio
async def test_nilm_reference_link_persists_updates_and_removes() -> None:
    controller, assignment = _helper_link_controller()
    assignment["label_interval_ids"] = ["label-1"]

    linked = await controller.async_set_nilm_reference_link(
        "mixed",
        "assignment-load",
        state_entity_id=" switch.load ",
        power_entity_id=" sensor.load_power ",
        threshold_w=12.5,
    )

    assert linked["reference_state_entity_id"] == "switch.load"
    assert linked["reference_power_entity_id"] == "sensor.load_power"
    assert linked["reference_threshold_w"] == 12.5
    assert linked["updated_at"] == "2026-06-02T12:00:00+00:00"

    retired = await controller.async_retire_nilm_appliance_assignment(
        "mixed", "assignment-load"
    )
    assert retired["reference_state_entity_id"] == "switch.load"
    assert retired["reference_power_entity_id"] == "sensor.load_power"

    removed = await controller.async_remove_nilm_reference_link(
        "mixed", "assignment-load"
    )
    assert "reference_state_entity_id" not in removed
    assert "reference_power_entity_id" not in removed
    assert "reference_threshold_w" not in removed
    assert removed["label_interval_ids"] == ["label-1"]


@pytest.mark.asyncio
async def test_nilm_reference_link_persists_canonical_settings_and_legacy_alias(
) -> None:
    controller, _ = _helper_link_controller()

    linked = await controller.async_set_nilm_reference_link(
        "mixed",
        "assignment-load",
        power_entity_id="sensor.load_power",
        on_threshold=20,
        off_threshold=12,
        on_dwell_seconds=3,
        off_dwell_seconds=4,
        minimum_interval_seconds=5,
        merge_gap_seconds=6,
        maximum_unknown_gap_seconds=7,
        maximum_power_gap_seconds=8,
    )

    assert linked["reference_on_threshold"] == 20.0
    assert linked["reference_off_threshold"] == 12.0
    assert linked["reference_on_dwell_seconds"] == 3.0
    assert linked["reference_off_dwell_seconds"] == 4.0
    assert linked["reference_minimum_interval_seconds"] == 5.0
    assert linked["reference_merge_gap_seconds"] == 6.0
    assert linked["reference_maximum_unknown_gap_seconds"] == 7.0
    assert linked["reference_maximum_power_gap_seconds"] == 8.0
    assert linked["reference_threshold_w"] == 20.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"on_threshold": 10, "off_threshold": 11}, "ordered"),
        ({"on_threshold": float("inf"), "off_threshold": 1}, "thresholds"),
        ({"on_dwell_seconds": -1}, "durations"),
    ],
)
async def test_nilm_reference_link_rejects_invalid_canonical_settings_before_mutation(
    settings: dict[str, object], message: str
) -> None:
    controller, assignment = _helper_link_controller()
    before = dict(assignment)

    with pytest.raises(ValueError, match=message):
        await controller.async_set_nilm_reference_link(
            "mixed",
            "assignment-load",
            power_entity_id="sensor.load_power",
            **settings,
        )

    assert assignment == before


@pytest.mark.asyncio
async def test_nilm_reference_link_uses_legacy_threshold_for_both_canonical_values(
) -> None:
    controller, _ = _helper_link_controller()

    linked = await controller.async_set_nilm_reference_link(
        "mixed",
        "assignment-load",
        power_entity_id="sensor.load_power",
        threshold_w=12.5,
    )

    assert linked["reference_on_threshold"] == 12.5
    assert linked["reference_off_threshold"] == 12.5


@pytest.mark.asyncio
async def test_nilm_reference_binary_link_omits_numeric_thresholds() -> None:
    controller, _ = _helper_link_controller()

    linked = await controller.async_set_nilm_reference_link(
        "mixed", "assignment-load", state_entity_id="switch.load", on_dwell_seconds=5
    )

    assert "reference_on_threshold" not in linked
    assert "reference_off_threshold" not in linked
    assert linked["reference_on_dwell_seconds"] == 5.0


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold", (-1, float("inf"), True))
async def test_nilm_reference_link_rejects_invalid_values(threshold: object) -> None:
    controller, _ = _helper_link_controller()

    with pytest.raises(ValueError):
        await controller.async_set_nilm_reference_link(
            "mixed",
            "assignment-load",
            threshold_w=threshold,
        )


@pytest.mark.asyncio
async def test_nilm_reference_link_rejects_incompatible_live_entities() -> None:
    controller, _ = _helper_link_controller()
    rows = {
        "sensor.not_state": SimpleNamespace(state="on", attributes={}),
        "sensor.pump_var": SimpleNamespace(
            state="12",
            attributes={
                "device_class": "reactive_power",
                "unit_of_measurement": "var",
            },
        ),
    }
    controller._coordinator.hass = SimpleNamespace(
        states=SimpleNamespace(get=rows.get)
    )

    with pytest.raises(ValueError, match="state entity"):
        await controller.async_set_nilm_reference_link(
            "mixed", "assignment-load", state_entity_id="sensor.not_state"
        )
    with pytest.raises(ValueError, match="power entity"):
        await controller.async_set_nilm_reference_link(
            "mixed", "assignment-load", power_entity_id="sensor.pump_var"
        )


@pytest.mark.asyncio
async def test_nilm_reference_history_updates_measured_interval_evidence() -> None:
    controller, assignment = _helper_link_controller()

    first = await controller.async_label_nilm_interval(
        "mixed",
        label="Pump",
        start="2026-06-02T10:00:00+00:00",
        end="2026-06-02T10:30:00+00:00",
        interval_id="reference-stable",
        assignment_id="assignment-load",
        ground_truth_entity_id="switch.pump",
        source="reference_sensor",
        median_power_w=80,
        measured_energy_kwh=0.04,
    )
    second = await controller.async_label_nilm_interval(
        "mixed",
        label="Pump",
        start="2026-06-02T10:00:00+00:00",
        end="2026-06-02T10:30:00+00:00",
        interval_id="reference-stable",
        assignment_id="assignment-load",
        ground_truth_entity_id="switch.pump",
        source="reference_sensor",
        median_power_w=84,
        measured_energy_kwh=0.042,
    )

    intervals = controller._coordinator.store_data.nilm_label_intervals_by_circuit[
        "mixed"
    ]
    assert len(intervals) == 1
    assert first["median_power_w"] == 80
    assert second["median_power_w"] == 84
    assert second["measured_energy_kwh"] == 0.042
    assert assignment["label_interval_ids"] == ["reference-stable"]


@pytest.mark.asyncio
async def test_reference_import_summary_persists_with_interval_batch() -> None:
    controller, assignment = _helper_link_controller()
    summary = {
        "candidate_interval_count": 2,
        "imported_interval_count": 1,
        "discarded_minimum_duration_count": 1,
        "bridged_unknown_gap_count": 1,
        "merged_inactive_gap_count": 0,
        "low_coverage_interval_count": 1,
        "warnings": ["incomplete_power_coverage"],
    }

    saved = await controller.async_save_nilm_interval_changes(
        "mixed",
        label="Pump",
        assignment_id="assignment-load",
        intervals=[
            {
                "interval_id": "reference-summary",
                "start": "2026-06-02T10:00:00+00:00",
                "end": "2026-06-02T10:30:00+00:00",
                "source": "reference_sensor",
            }
        ],
        reference_import_summary=summary,
    )

    assert assignment["reference_import_summary"] == summary
    assert saved["reference_import_summary"] == summary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "assignment", "helper", "relationship", "error"),
    (
        ("missing", "assignment-load", "helper", "corroborates", "source"),
        ("mixed", "missing", "helper", "corroborates", "assignment"),
        ("mixed", "assignment-load", "mixed", "corroborates", "itself"),
        ("mixed", "assignment-load", "missing", "corroborates", "helper"),
        ("mixed", "assignment-load", "helper", "unsupported", "relationship"),
        (
            "mixed",
            "assignment-load",
            "aggregate",
            "direct_component",
            "direct-appliance",
        ),
    ),
)
async def test_nilm_helper_links_reject_invalid_relationships(
    source: str,
    assignment: str,
    helper: str,
    relationship: str,
    error: str,
) -> None:
    controller, _ = _helper_link_controller()
    with pytest.raises(ValueError, match=error):
        await controller.async_set_nilm_helper_link(
            source,
            assignment,
            helper_circuit_id=helper,
            relationship=relationship,
        )


@pytest.mark.asyncio
async def test_nilm_helper_links_reject_fifth_and_second_direct_component() -> None:
    controller, assignment = _helper_link_controller()
    assignment["helper_links"] = [
        {"helper_circuit_id": f"old-{index}", "relationship": "corroborates"}
        for index in range(4)
    ]
    with pytest.raises(ValueError, match="four"):
        await controller.async_set_nilm_helper_link(
            "mixed",
            "assignment-load",
            helper_circuit_id="helper",
            relationship="direct_component",
        )
    assignment["helper_links"] = [
        {"helper_circuit_id": "helper", "relationship": "direct_component"}
    ]
    with pytest.raises(ValueError, match="direct_component"):
        await controller.async_set_nilm_helper_link(
            "mixed",
            "assignment-load",
            helper_circuit_id="helper-2",
            relationship="direct_component",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "helper", "error"),
    (
        ("missing", "helper", "source"),
        ("mixed", "mixed", "itself"),
        ("mixed", "missing", "helper"),
    ),
)
async def test_remove_nilm_helper_link_validates_resources(
    source: str,
    helper: str,
    error: str,
) -> None:
    controller, assignment = _helper_link_controller()
    assignment["helper_links"] = [{"helper_circuit_id": "helper"}]

    with pytest.raises(ValueError, match=error):
        await controller.async_remove_nilm_helper_link(
            source,
            "assignment-load",
            helper_circuit_id=helper,
        )


@pytest.mark.asyncio
async def test_nilm_helper_link_uses_newest_candidate_across_fingerprints() -> None:
    controller, assignment = _helper_link_controller()
    assignment["signature_fingerprints"] = ["older", "newer"]
    controller._coordinator.store_data.nilm_signatures["mixed"] = [
        {
            "feedback_fingerprint": "older",
            "helper_candidates": [
                {
                    "helper_circuit_id": "helper",
                    "confidence": 0.99,
                    "matched_on_count": 9,
                    "matched_off_count": 9,
                    "last_observed": "2026-06-01T12:00:00+00:00",
                }
            ],
        },
        {
            "feedback_fingerprint": "newer",
            "helper_candidates": [
                {
                    "helper_circuit_id": "helper",
                    "confidence": 0.8,
                    "matched_on_count": 5,
                    "matched_off_count": 6,
                    "last_observed": "2026-06-02T11:00:00+00:00",
                }
            ],
        },
    ]

    linked = await controller.async_set_nilm_helper_link(
        "mixed",
        "assignment-load",
        helper_circuit_id="helper",
        relationship="corroborates",
    )

    assert linked["helper_links"][0]["matched_on_count"] == 5
    assert linked["helper_links"][0]["confirmed_matched_off_count"] == 6


@pytest.mark.asyncio
async def test_nilm_helper_link_candidate_tie_is_storage_order_independent() -> None:
    async def selected_lag(reverse: bool) -> float:
        controller, assignment = _helper_link_controller()
        assignment["signature_fingerprints"] = ["alpha", "zeta"]
        signatures = [
            {
                "feedback_fingerprint": "alpha",
                "helper_candidates": [
                    {
                        "helper_circuit_id": "helper",
                        "confidence": 0.8,
                        "matched_on_count": 5,
                        "matched_off_count": 6,
                        "start_lag_seconds": 11,
                        "last_observed": "2026-06-02T11:00:00+00:00",
                    }
                ],
            },
            {
                "feedback_fingerprint": "zeta",
                "helper_candidates": [
                    {
                        "helper_circuit_id": "helper",
                        "confidence": 0.8,
                        "matched_on_count": 5,
                        "matched_off_count": 6,
                        "start_lag_seconds": 22,
                        "last_observed": "2026-06-02T11:00:00+00:00",
                    }
                ],
            },
        ]
        controller._coordinator.store_data.nilm_signatures["mixed"] = (
            list(reversed(signatures)) if reverse else signatures
        )
        linked = await controller.async_set_nilm_helper_link(
            "mixed",
            "assignment-load",
            helper_circuit_id="helper",
            relationship="corroborates",
        )
        return linked["helper_links"][0]["start_lag_seconds"]

    assert await selected_lag(False) == await selected_lag(True) == 22


@pytest.mark.asyncio
async def test_nilm_helper_link_normalizes_malformed_candidate_and_link_values() -> (
    None
):
    controller, assignment = _helper_link_controller()
    controller._coordinator.store_data.nilm_signatures["mixed"][0]["helper_candidates"][
        0
    ].update(
        {
            "confidence": "bad",
            "matched_on_count": "bad",
            "matched_off_count": None,
            "start_lag_seconds": "bad",
            "last_observed": "not-a-date",
        }
    )
    assignment["helper_links"] = [
        {
            "helper_circuit_id": "old",
            "relationship": "corroborates",
            "confidence": {"bad": True},
            "last_observed": ["bad"],
        }
    ]

    linked = await controller.async_set_nilm_helper_link(
        "mixed",
        "assignment-load",
        helper_circuit_id="helper",
        relationship="corroborates",
    )

    helper = next(
        link for link in linked["helper_links"] if link["helper_circuit_id"] == "helper"
    )
    assert helper["confidence"] == 0.0
    assert helper["matched_on_count"] == 0
    assert helper["matched_off_count"] == 0
    assert helper["start_lag_seconds"] is None
    assert helper["last_observed"] is None


def _helper_link_controller() -> tuple[NilmController, dict[str, object]]:
    async def noop(*_args: object) -> None:
        pass

    assignment: dict[str, object] = {
        "assignment_id": "assignment-load",
        "signature_fingerprints": ["load-fingerprint"],
    }
    configs = {
        "mixed": _config(ApplianceProfile.MIXED, CircuitMode.MIXED, "mixed"),
        "helper": _config(ApplianceProfile.HVAC_BLOWER, circuit_id="helper"),
        "helper-2": _config(ApplianceProfile.MOTOR_LOAD, circuit_id="helper-2"),
        "aggregate": _config(ApplianceProfile.MIXED, CircuitMode.MIXED, "aggregate"),
    }
    coordinator = SimpleNamespace(
        current_time=lambda: datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        circuit_registry=SimpleNamespace(config_for_circuit=configs.get),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]},
            nilm_signatures={
                "mixed": [
                    {
                        "feedback_fingerprint": "load-fingerprint",
                        "helper_candidates": [
                            {
                                "helper_circuit_id": "helper",
                                "confidence": 0.91,
                                "matched_on_count": 4,
                                "matched_off_count": 5,
                                "last_observed": "2026-06-02T11:00:00+00:00",
                            }
                        ],
                    }
                ]
            },
        ),
        state=SimpleNamespace(),
        async_set_updated_data=lambda _: None,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=noop
        ),
        config_entry_controller=SimpleNamespace(async_reload=noop),
    )
    return _nilm_controller(coordinator), assignment


def _config(
    profile: ApplianceProfile,
    mode: CircuitMode = CircuitMode.SINGLE_PHASE,
    circuit_id: str = "source",
    name: str = "Source",
    power_flow: PowerFlowMode = PowerFlowMode.LOAD,
) -> CircuitConfig:
    return CircuitConfig(
        circuit_id=circuit_id,
        name=name,
        appliance_profile=profile,
        mode=mode,
        power_flow=power_flow,
    )


def _nilm_controller(coordinator: object) -> NilmController:
    return NilmController(
        coordinator,
        label_interval_max_items=1,
        assignment_max_items=1,
    )


def _validation_feedback_controller(
    sessions: list[dict[str, object]],
    *,
    now_values: list[datetime],
    assignment: dict[str, object] | None = None,
) -> tuple[NilmController, dict[str, object]]:
    async def noop(*_args: object) -> None:
        return None

    stored_assignment = assignment or {
        "assignment_id": "assignment-pump",
        "model_revision": 7,
        "model_fingerprint": "model-seven",
    }
    coordinator = SimpleNamespace(
        current_time=lambda: now_values.pop(0),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [stored_assignment]},
            nilm_session_history_by_circuit={"mixed": sessions},
        ),
        state=SimpleNamespace(),
        async_set_updated_data=lambda _state: None,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None, async_save_if_dirty=noop
        ),
    )
    return _nilm_controller(coordinator), stored_assignment


@pytest.mark.asyncio
async def test_history_validation_does_not_score_model_training_examples(
) -> None:
    """A session cannot validate the model that was trained on it."""
    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    sessions = [
        {
            "session_id": f"session-{index}",
            "assignment_id": "assignment-pump",
            "start": (base + timedelta(days=index % 3)).isoformat(),
            "end": (
                base + timedelta(days=index % 3, minutes=10)
            ).isoformat(),
            "on_delta_w": 100.0,
            "off_delta_w": -100.0,
            "median_power_w": 100.0,
            "confidence": 1.0,
        }
        for index in range(6)
    ]
    confirmed_ids = [str(session["session_id"]) for session in sessions]
    model = build_nilm_assignment_model(
        {
            "assignment_id": "assignment-pump",
            "confirmed_session_ids": confirmed_ids,
        },
        sessions,
    )
    assignment: dict[str, object] = {
        "assignment_id": "assignment-pump",
        "session_ids": confirmed_ids,
        "confirmed_session_ids": confirmed_ids,
        "lifecycle_state": "validated",
        **model,
    }
    for session in sessions[:5]:
        session.update({
            "start_model_revision": model["model_revision"],
            "stop_model_revision": model["model_revision"],
            "start_model_fingerprint": model["model_fingerprint"],
            "stop_model_fingerprint": model["model_fingerprint"],
        })
    intervals = [
        {
            "interval_id": f"interval-{index}",
            "assignment_id": "assignment-pump",
            "ground_truth_entity_id": "sensor.pump_power",
            "start": session["start"],
            "end": session["end"],
            "validation_start": session["start"],
            "validation_end": session["end"],
            "median_power_w": 100.0,
        }
        for index, session in enumerate(sessions)
    ]

    async def noop(*_args: object) -> None:
        return None

    coordinator = SimpleNamespace(
        current_time=lambda: base + timedelta(days=10),
        store_data=FeatureStoreData(
            nilm_appliance_assignments_by_circuit={"mixed": [assignment]},
            nilm_label_intervals_by_circuit={"mixed": intervals},
            nilm_session_history_by_circuit={"mixed": sessions},
        ),
        state=SimpleNamespace(),
        async_set_updated_data=lambda _state: None,
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=noop,
        ),
    )
    controller = NilmController(
        coordinator,
        label_interval_max_items=100,
        assignment_max_items=100,
    )

    await controller.async_validate_nilm_assignment_history(
        "mixed", "assignment-pump"
    )

    assert assignment["model_revision"] == model["model_revision"]
    assert assignment["model_fingerprint"] == model["model_fingerprint"]
    assert assignment["validation_schema_version"] == 2
    assert assignment["validation_method"] == "one_to_one_iou"
    assert "validation_outcomes" not in assignment
    assert "validation_profiles_by_revision" not in assignment


@pytest.mark.asyncio
async def test_session_feedback_upserts_a_revision_matched_explicit_outcome() -> None:
    """Removing the upsert or prediction provenance must fail this test."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    controller, assignment = _validation_feedback_controller(
        [
            {
                "session_id": "session-1",
                "assignment_id": "assignment-pump",
                "start": now.isoformat(),
                "end": (now + timedelta(minutes=10)).isoformat(),
                "start_model_revision": 7,
                "stop_model_revision": 7,
                "start_model_fingerprint": "model-seven",
                "stop_model_fingerprint": "model-seven",
            }
        ],
        now_values=[now, now + timedelta(minutes=1)],
    )

    await controller.async_record_nilm_session_validation(
        "mixed", "session-1", assignment_id="assignment-pump", correct=True
    )
    await controller.async_record_nilm_session_validation(
        "mixed", "session-1", assignment_id="assignment-pump", correct=False
    )

    assert assignment["validation_outcomes"] == [
        {
            "outcome_id": "session-1",
            "session_id": "session-1",
            "source": "explicit_feedback",
            "outcome": "wrong",
            "timestamp": "2026-08-01T12:01:00+00:00",
            "model_revision": 7,
            "model_fingerprint": "model-seven",
        }
    ]


@pytest.mark.asyncio
async def test_duplicate_direct_session_feedback_is_idempotent() -> None:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    session = {
        "session_id": "session-1",
        "assignment_id": "assignment-pump",
        "start": now.isoformat(),
        "end": (now + timedelta(minutes=10)).isoformat(),
        "start_model_revision": 7,
        "stop_model_revision": 7,
        "start_model_fingerprint": "model-seven",
        "stop_model_fingerprint": "model-seven",
    }
    assignment: dict[str, object] = {
        "assignment_id": "assignment-pump",
        "session_ids": ["session-1"],
        "lifecycle_state": "validated",
        "model_revision": 7,
        "model_fingerprint": "model-seven",
    }
    controller, assignment = _validation_feedback_controller(
        [session],
        now_values=[now, now + timedelta(minutes=1)],
        assignment=assignment,
    )

    await controller.async_record_nilm_session_validation(
        "mixed", "session-1", assignment_id="assignment-pump", correct=True
    )
    after_first_feedback = deepcopy(assignment)

    await controller.async_record_nilm_session_validation(
        "mixed", "session-1", assignment_id="assignment-pump", correct=True
    )

    assert assignment == after_first_feedback
    assert "confidence" not in assignment
    assert assignment["feedback_evidence_score"] == 0.05
    assert assignment["feedback_evidence_events"] == [
        {
            "feedback_id": "session:session-1",
            "outcome": "correct",
            "delta": 0.05,
            "timestamp": now.isoformat(),
            "score_after": 0.05,
        }
    ]


@pytest.mark.asyncio
async def test_session_feedback_preserves_matching_schema_v2_ground_truth_outcome() -> (
    None
):
    """Removing another validation source during feedback upsert must fail."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "assignment-pump",
        "model_revision": 7,
        "model_fingerprint": "model-seven",
        "validation_schema_version": 2,
        "validation_method": "one_to_one_iou",
        "validation_outcomes": [
            {
                "outcome_id": "session-1",
                "session_id": "session-1",
                "source": "ground_truth",
                "outcome": "wrong",
                "timestamp": now.isoformat(),
                "model_revision": 7,
                "model_fingerprint": "model-seven",
            }
        ],
    }
    controller, assignment = _validation_feedback_controller(
        [
            {
                "session_id": "session-1",
                "assignment_id": "assignment-pump",
                "start": now.isoformat(),
                "end": (now + timedelta(minutes=10)).isoformat(),
                "start_model_revision": 7,
                "stop_model_revision": 7,
                "start_model_fingerprint": "model-seven",
                "stop_model_fingerprint": "model-seven",
            }
        ],
        now_values=[now],
        assignment=assignment,
    )

    await controller.async_record_nilm_session_validation(
        "mixed", "session-1", assignment_id="assignment-pump", correct=True
    )

    assert {
        (record["outcome_id"], record["source"])
        for record in assignment["validation_outcomes"]
    } == {("session-1", "ground_truth"), ("session-1", "explicit_feedback")}
    profile = assignment["validation_profiles_by_revision"]["7:model-seven"]
    assert profile["sample_count"] == 0
    assert profile["runtime_score"] is None


@pytest.mark.asyncio
async def test_session_feedback_profiles_become_eligible_only_at_support_and_day_gates(
) -> None:
    """Dropping either Task-3 gate or smoothing must fail this test."""
    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    sessions = [
        {
            "session_id": f"session-{index}",
            "assignment_id": "assignment-pump",
            "start": (base + timedelta(days=index % 3)).isoformat(),
            "end": (base + timedelta(days=index % 3, minutes=10)).isoformat(),
            "start_model_revision": 7,
            "stop_model_revision": 7,
            "start_model_fingerprint": "model-seven",
            "stop_model_fingerprint": "model-seven",
        }
        for index in range(5)
    ]
    controller, assignment = _validation_feedback_controller(
        sessions,
        now_values=[base + timedelta(days=index % 3) for index in range(5)],
    )

    for index in range(4):
        await controller.async_record_nilm_session_validation(
            "mixed", f"session-{index}", assignment_id="assignment-pump", correct=True
        )
    sparse = assignment["validation_profiles_by_revision"]["7:model-seven"]
    assert sparse["sample_count"] == 4
    assert sparse["runtime_score"] is None

    await controller.async_record_nilm_session_validation(
        "mixed", "session-4", assignment_id="assignment-pump", correct=False
    )

    profile = assignment["validation_profiles_by_revision"]["7:model-seven"]
    assert profile["sample_count"] == 5
    assert profile["distinct_days"] == 3
    assert profile["correct_count"] == 4
    assert profile["wrong_count"] == 1
    assert profile["runtime_eligible"] is True
    assert profile["runtime_score"] == pytest.approx(6 / 9)


@pytest.mark.asyncio
async def test_legacy_session_feedback_trains_without_runtime_validation_evidence(
) -> None:
    """Fabricating provenance from the current model must fail this test."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    controller, assignment = _validation_feedback_controller(
        [
            {
                "session_id": "legacy-confirmed",
                "assignment_id": "assignment-pump",
                "start": now.isoformat(),
                "end": (now + timedelta(minutes=10)).isoformat(),
            },
            {
                "session_id": "legacy-rejected",
                "assignment_id": "assignment-pump",
                "start": (now + timedelta(hours=1)).isoformat(),
                "end": (now + timedelta(hours=1, minutes=10)).isoformat(),
            }
        ],
        now_values=[now, now + timedelta(hours=1)],
    )

    await controller.async_record_nilm_session_validation(
        "mixed", "legacy-confirmed", assignment_id="assignment-pump", correct=True
    )
    await controller.async_record_nilm_session_validation(
        "mixed", "legacy-rejected", assignment_id="assignment-pump", correct=False
    )

    assert assignment["confirmed_session_ids"] == ["legacy-confirmed"]
    assert assignment["rejected_session_ids"] == ["legacy-rejected"]
    assert "validation_outcomes" not in assignment
    assert "validation_profiles_by_revision" not in assignment


@pytest.mark.asyncio
async def test_feedback_for_an_older_prediction_revision_stays_separate() -> None:
    """Reassigning old feedback to a rebuilt model must fail this test."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "assignment-pump",
        "model_revision": 8,
        "model_fingerprint": "model-eight",
    }
    controller, assignment = _validation_feedback_controller(
        [
            {
                "session_id": "older-session",
                "assignment_id": "assignment-pump",
                "start": now.isoformat(),
                "end": (now + timedelta(minutes=10)).isoformat(),
                "start_model_revision": 7,
                "stop_model_revision": 7,
                "start_model_fingerprint": "model-seven",
                "stop_model_fingerprint": "model-seven",
            }
        ],
        now_values=[now],
        assignment=assignment,
    )

    await controller.async_record_nilm_session_validation(
        "mixed", "older-session", assignment_id="assignment-pump", correct=True
    )

    assert assignment["validation_profiles_by_revision"] == {
        "7:model-seven": {
            "sample_count": 1,
            "effective_support": 1.0,
            "distinct_days": 1,
            "correct_count": 1,
            "wrong_count": 0,
            "reliability": 0.6,
            "runtime_eligible": False,
            "runtime_score": None,
            "source_counts": {"feedback": 1},
        }
    }
    assert build_nilm_validation_profile(assignment)["sample_count"] == 0


@pytest.mark.asyncio
async def test_overlap_only_history_fields_do_not_become_runtime_feedback_outcomes(
) -> None:
    """Treating legacy overlap history as feedback must fail this test."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "assignment-pump",
        "model_revision": 7,
        "model_fingerprint": "model-seven",
        "validation_schema_version": 1,
        "validation_method": "overlap",
        "validation_outcomes": [
            {
                "outcome_id": "legacy-overlap",
                "source": "ground_truth",
                "outcome": "correct",
                "timestamp": now.isoformat(),
                "model_revision": 7,
            }
        ],
    }
    controller, assignment = _validation_feedback_controller(
        [
            {
                "session_id": "session-1",
                "assignment_id": "assignment-pump",
                "start": now.isoformat(),
                "end": (now + timedelta(minutes=10)).isoformat(),
            }
        ],
        now_values=[now],
        assignment=assignment,
    )

    await controller.async_record_nilm_session_validation(
        "mixed", "session-1", assignment_id="assignment-pump", correct=True
    )

    assert assignment["validation_outcomes"] == [
        {
            "outcome_id": "legacy-overlap",
            "source": "ground_truth",
            "outcome": "correct",
            "timestamp": "2026-08-01T12:00:00+00:00",
            "model_revision": 7,
        }
    ]


@pytest.mark.asyncio
async def test_reference_schema_2_metadata_survives_legacy_and_manual_reload() -> None:
    """Feature-store serialization keeps all supported interval generations together."""
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    legacy = {
        "interval_id": "legacy",
        "label": "Pump",
        "start": "2026-08-01T09:00:00+00:00",
        "end": "2026-08-01T09:10:00+00:00",
    }
    coordinator = SimpleNamespace(
        current_time=lambda: now,
        store_data=FeatureStoreData(
            nilm_label_intervals_by_circuit={"mixed": [legacy]}
        ),
        store_persistence=SimpleNamespace(
            mark_dirty=lambda: None,
            async_save_if_dirty=AsyncMock(),
        ),
        async_set_updated_data=lambda _state: None,
        state=SimpleNamespace(),
    )
    controller = NilmController(
        coordinator, label_interval_max_items=10, assignment_max_items=10
    )
    manual_evidence = {
        "evidence_schema_version": 2,
        "evidence_source": "manual_backend",
        "evidence_generated_at": now.isoformat(),
        "source_coverage": 1.0,
        "power_coverage": 1.0,
        "start_transition_eligible": False,
        "stop_transition_eligible": False,
        "plateau_eligible": False,
        "energy_complete": False,
        "evidence_confidence": 0.9,
        "power_confidence": 0.9,
        "quality_flags": [],
    }
    reference_evidence = {
        "evidence_schema_version": 2,
        "evidence_source": "reference_backend",
        "evidence_generated_at": now.isoformat(),
        "source_coverage": 0.9,
        "power_coverage": 1.0,
        "start_transition_eligible": False,
        "stop_transition_eligible": False,
        "plateau_eligible": False,
        "energy_complete": False,
        "evidence_confidence": 0.72,
        "power_confidence": 0.9,
        "quality_flags": ["unknown_gap_bridged"],
        "ground_truth_entity_id": "switch.pump",
        "reference_power_entity_id": "sensor.pump_power",
        "state_coverage": 0.9,
        "unknown_duration_seconds": 60.0,
        "merged_gap_count": 0,
        "left_censored": False,
        "right_censored": False,
        "resolved_reference_settings": {
            "on_threshold": 50.0,
            "off_threshold": 25.0,
            "on_dwell_seconds": 0.0,
            "off_dwell_seconds": 0.0,
            "minimum_interval_seconds": 0.0,
            "merge_gap_seconds": 0.0,
            "maximum_unknown_gap_seconds": 120.0,
            "maximum_power_gap_seconds": None,
        },
    }

    await controller.async_label_nilm_interval(
        "mixed",
        label="Pump",
        start="2026-08-01T10:00:00+00:00",
        end="2026-08-01T10:10:00+00:00",
        interval_id="manual-schema-2",
        evidence=manual_evidence,
    )
    await controller.async_label_nilm_interval(
        "mixed",
        label="Pump",
        start="2026-08-01T11:00:00+00:00",
        end="2026-08-01T11:10:00+00:00",
        interval_id="reference-schema-2",
        source="reference_sensor",
        evidence=reference_evidence,
    )

    reloaded = feature_store_data_from_dict(
        feature_store_data_to_dict(coordinator.store_data)
    )
    intervals = reloaded.nilm_label_intervals_by_circuit["mixed"]
    assert [item["interval_id"] for item in intervals] == [
        "legacy",
        "manual-schema-2",
        "reference-schema-2",
    ]
    reference = intervals[-1]
    assert reference["source"] == "reference_sensor"
    assert reference["evidence_source"] == "reference_backend"
    assert reference["ground_truth_entity_id"] == "switch.pump"
    assert reference["reference_power_entity_id"] == "sensor.pump_power"
    assert reference["resolved_reference_settings"] == reference_evidence[
        "resolved_reference_settings"
    ]
