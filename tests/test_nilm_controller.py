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


def _nilm_controller(coordinator: object) -> NilmController:
    return NilmController(
        coordinator,
        clean_string_list=lambda value: [],
        append_unique=lambda values, value: None,
        nonnegative_float_value=lambda *args, **kwargs: 0.0,
        label_interval_datetime=lambda value, field: None,
        label_interval_id=lambda circuit_id, label, start, end: "interval",
        signature_fingerprint_value=lambda value, circuit_id: "fingerprint",
        signature_assignment_label=lambda value, circuit_id: "label",
        label_interval_max_items=1,
        round_optional_number=lambda value: None,
        assignment_interval_matches=lambda assignment, interval: False,
        overlap_seconds=lambda left, right: 0.0,
        validation_coverage_overlap_seconds=lambda left, right: 0.0,
        float_or_none=lambda value: None,
        datetime_or_none=lambda value: None,
        assignment_appliance_id=lambda label: label,
        assignment_id=lambda circuit_id, appliance_id: "assignment",
        assignment_max_items=1,
    )
