from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ENABLE_EXPERIMENTAL_NILM,
)
from custom_components.circuitsetup_energy_analyzer.managers.nilm_controller import (
    NilmController,
    configured_primary_assignment_id,
    nilm_assignment_publication_reason,
)
from custom_components.circuitsetup_energy_analyzer.managers.store_persistence import (
    StorePersistenceManager,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    NilmSourceKind,
    PowerFlowMode,
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


def test_reviewed_on_off_model_can_publish_without_rebinding_signature() -> None:
    assert (
        nilm_assignment_publication_reason(
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
        is None
    )


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
    events = [
        SimpleNamespace(circuit_id="mains"),
        SimpleNamespace(circuit_id="fridge"),
        SimpleNamespace(circuit_id="hvac"),
    ]

    assert [
        event.circuit_id for event in controller.known_load_events("mains", events)
    ] == ["fridge"]


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
        ),
        SimpleNamespace(
            mode=CircuitMode.MIXED,
            appliance_profile=ApplianceProfile.MOTOR_LOAD,
        ),
    ),
)
def test_nilm_controller_enables_mixed_sources_only_when_experimental(
    config: SimpleNamespace,
) -> None:
    disabled = _nilm_controller(SimpleNamespace(options={}, entry_data={}))
    enabled = _nilm_controller(
        SimpleNamespace(
            options={CONF_ENABLE_EXPERIMENTAL_NILM: True},
            entry_data={},
        )
    )

    assert disabled.enabled_for_config(config) is False
    assert enabled.enabled_for_config(config) is True


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
            "source", [SimpleNamespace(circuit_id="fridge")]
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
    assert updated["confidence"] == 0.82
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
async def test_save_nilm_interval_changes_restores_collections_after_save_failure() -> (
    None
):
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
                }
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
    }

    power_reference = nilm_reference_runtime(
        coordinator,
        {
            "reference_power_entity_id": "sensor.pump_power",
            "reference_threshold_w": 25,
        },
    )
    assert power_reference["is_running"] is True
    assert power_reference["source_entity_id"] == "sensor.pump_power"

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


def test_hydration_normalizes_optional_assignment_model_fields_once() -> None:
    now = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)
    assignment = {
        "assignment_id": "pump",
        "confirmed_session_ids": ["session-1"],
        "role": "component",
        "power_states_w": [],
        "transition_prototypes": [],
        "model_confidence": 0.0,
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
    controller.hydrate_state_from_store()

    assert assignment["role"] == "component"
    assert assignment["power_states_w"] == [0.0, 83.0]
    assert assignment["transition_prototypes"][0]["delta_var"] == 27.0
    assert assignment["transition_prototypes"][1]["delta_var"] == -4.0
    assert assignment["model_revision"] == 1
    assert dirty == [True]

    for prototype in assignment["transition_prototypes"]:
        prototype.pop("delta_var")
        prototype.pop("spread_var")
    controller.hydrate_state_from_store()
    controller.hydrate_state_from_store()

    assert assignment["transition_prototypes"][0]["delta_var"] == 27.0
    assert assignment["transition_prototypes"][1]["delta_var"] == -4.0
    assert assignment["model_revision"] == 2
    assert dirty == [True, True]


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
