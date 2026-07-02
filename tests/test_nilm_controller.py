from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.circuitsetup_energy_analyzer.managers.nilm_controller import (
    NilmController,
)


def test_nilm_controller_filters_known_load_events_from_registry() -> None:
    controller = _nilm_controller(
        SimpleNamespace(
            circuit_registry=SimpleNamespace(
                known_load_circuit_ids=frozenset({"fridge"}),
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


def _nilm_controller(coordinator: object) -> NilmController:
    return NilmController(
        coordinator,
        label_interval_max_items=1,
        assignment_max_items=1,
    )
