from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    CONF_ENABLE_EXPERIMENTAL_NILM,
)
from custom_components.circuitsetup_energy_analyzer.managers.nilm_controller import (
    NilmController,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
)
from custom_components.circuitsetup_energy_analyzer.storage import (
    FeatureStoreData,
    feature_store_data_from_dict,
    feature_store_data_to_dict,
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
    disabled = _nilm_controller(
        SimpleNamespace(options={}, entry_data={})
    )
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
                mode=CircuitMode.MIXED,
                appliance_profile=ApplianceProfile.MOTOR_LOAD,
            ),
            [],
        ),
        (
            SimpleNamespace(
                mode=CircuitMode.SINGLE_PHASE,
                appliance_profile=ApplianceProfile.MIXED,
            ),
            [],
        ),
        (None, ["fridge"]),
    ),
)
def test_nilm_controller_masks_known_loads_only_for_known_nonmixed_sources(
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
            "mixed", [SimpleNamespace(circuit_id="fridge")]
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


def _nilm_controller(coordinator: object) -> NilmController:
    return NilmController(
        coordinator,
        label_interval_max_items=1,
        assignment_max_items=1,
    )
