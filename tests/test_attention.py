from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from custom_components.circuitsetup_energy_analyzer import attention
from custom_components.circuitsetup_energy_analyzer.appliance_detail import (
    ApplianceExpectation,
)
from custom_components.circuitsetup_energy_analyzer.coordinator import AnalyzerState
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
)
from custom_components.circuitsetup_energy_analyzer.storage import FeatureStoreData

NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _expectation(
    expectation_id: str,
    *,
    title: str,
    status: str,
    source_type: str = "direct_meter",
    confidence: float = 0.9,
) -> ApplianceExpectation:
    return ApplianceExpectation(
        expectation_id=expectation_id,
        circuit_id=expectation_id.split(":", 1)[0],
        title=title,
        status=status,
        source_type=source_type,
        confidence=confidence,
        observed=title,
        expected="Normal appliance behavior.",
        why_it_matters="This finding needs review.",
        what_to_check_first=("Open appliance detail.",),
        evidence_path=None,
    )


def _detail(
    circuit_id: str,
    display_name: str,
    expectation: ApplianceExpectation,
    *,
    assignment_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        appliance_key=(f"nilm:{assignment_id}" if assignment_id else circuit_id),
        circuit_id=circuit_id,
        display_name=display_name,
        source_type="nilm_estimate" if assignment_id else "direct_meter",
        expectations=(expectation,),
        next_step="Open appliance detail.",
        assignment_id=assignment_id,
        mains_circuit_id=circuit_id if assignment_id else None,
    )


def _coordinator(
    monkeypatch,
    *,
    direct_details: tuple[SimpleNamespace, ...] = (),
    nilm_details: tuple[SimpleNamespace, ...] = (),
) -> SimpleNamespace:
    direct_by_id = {detail.circuit_id: detail for detail in direct_details}
    nilm_by_id = {detail.assignment_id: detail for detail in nilm_details}
    coordinator = SimpleNamespace(
        circuit_configs=tuple(
            SimpleNamespace(circuit_id=circuit_id, mode=CircuitMode.SINGLE_PHASE)
            for circuit_id in direct_by_id
        ),
        current_time=lambda: NOW,
        state=SimpleNamespace(),
        store_data=SimpleNamespace(),
    )
    monkeypatch.setattr(
        attention,
        "appliance_detail_for_circuit",
        lambda _coordinator, circuit_id: direct_by_id.get(circuit_id),
    )
    monkeypatch.setattr(
        attention,
        "nilm_virtual_appliance_states",
        lambda _coordinator, published_only=False: tuple(
            SimpleNamespace(assignment_id=assignment_id) for assignment_id in nilm_by_id
        ),
    )
    monkeypatch.setattr(
        attention,
        "appliance_detail_for_assignment",
        lambda _coordinator, assignment_id: nilm_by_id.get(assignment_id),
    )
    return coordinator


def test_blocking_setup_item_sorts_first(monkeypatch) -> None:
    setup = _detail(
        "dryer",
        "Dryer",
        _expectation(
            "dryer:data_quality",
            title="Source data needs review",
            status="not_enough_data",
        ),
    )
    behavior = _detail(
        "refrigerator",
        "Refrigerator",
        _expectation(
            "refrigerator:energy",
            title="Energy is above normal",
            status="watch",
        ),
    )
    coordinator = _coordinator(
        monkeypatch,
        direct_details=(behavior, setup),
    )

    items = attention.attention_items_for_coordinators((coordinator,))

    assert isinstance(items[0], attention.AttentionItem)
    assert [item.appliance_key for item in items] == ["dryer", "refrigerator"]
    assert items[0].category == "fix_setup_or_data"


def test_hidden_nilm_assignment_is_not_a_setup_attention_item(monkeypatch) -> None:
    hidden = _detail(
        "mains",
        "off-1",
        _expectation(
            "assignment-hidden:nilm_validation",
            title="NILM assignment needs validation",
            status="watch",
            source_type="nilm_estimate",
        ),
        assignment_id="assignment-hidden",
    )
    coordinator = _coordinator(monkeypatch, nilm_details=(hidden,))
    monkeypatch.setattr(
        attention,
        "nilm_virtual_appliance_states",
        lambda _coordinator, published_only=False: (
            SimpleNamespace(
                assignment_id="assignment-hidden",
                model_status="ignored",
            ),
        ),
    )

    assert attention.attention_items_for_coordinators((coordinator,)) == ()


def test_direct_electrical_item_sorts_before_nilm_validation(monkeypatch) -> None:
    electrical = _detail(
        "dryer",
        "Dryer",
        _expectation(
            "dryer:electrical",
            title="Electrical balance needs review",
            status="possible_issue",
        ),
    )
    nilm = _detail(
        "mains",
        "Dishwasher",
        _expectation(
            "assignment-dishwasher:nilm_validation",
            title="NILM assignment needs validation",
            status="watch",
            source_type="nilm_estimate",
            confidence=0.72,
        ),
        assignment_id="assignment-dishwasher",
    )
    coordinator = _coordinator(
        monkeypatch,
        direct_details=(electrical,),
        nilm_details=(nilm,),
    )

    items = attention.attention_items_for_coordinators((coordinator,))

    assert [item.appliance_key for item in items] == [
        "dryer",
        "nilm:assignment-dishwasher",
    ]
    assert [item.severity for item in items] == ["high", "medium"]


def test_normal_and_expected_appliances_are_omitted(monkeypatch) -> None:
    normal = _detail(
        "refrigerator",
        "Refrigerator",
        _expectation(
            "refrigerator:energy",
            title="Cycling looks normal",
            status="ok",
        ),
    )
    expected = _detail(
        "hvac",
        "HVAC",
        _expectation(
            "hvac:weather",
            title="Runtime fits weather context",
            status="expected",
        ),
    )
    coordinator = _coordinator(
        monkeypatch,
        direct_details=(normal, expected),
    )

    assert attention.attention_items_for_coordinators((coordinator,)) == ()


def test_attention_action_paths_select_one_appliance_detail(monkeypatch) -> None:
    direct = _detail(
        "dryer",
        "Dryer",
        _expectation(
            "dryer:electrical",
            title="Electrical balance needs review",
            status="possible_issue",
        ),
    )
    nilm = _detail(
        "mains",
        "Dishwasher",
        _expectation(
            "assignment-dishwasher:nilm_validation",
            title="NILM assignment needs validation",
            status="watch",
            source_type="nilm_estimate",
        ),
        assignment_id="assignment-dishwasher",
    )
    coordinator = _coordinator(
        monkeypatch,
        direct_details=(direct,),
        nilm_details=(nilm,),
    )

    items = attention.attention_items_for_coordinators((coordinator,))

    for item in items:
        parsed = urlparse(item.action_path or "")
        params = parse_qs(parsed.query)
        assert parsed.path == attention.PANEL_PATH
        assert params["appliance_detail"] == ["1"]
        assert bool(params.get("circuit_id")) != bool(params.get("assignment_id"))


def test_resolved_item_is_absent_on_next_payload(monkeypatch) -> None:
    expectation = _expectation(
        "dryer:data_quality",
        title="Source data needs review",
        status="not_enough_data",
    )
    detail = _detail("dryer", "Dryer", expectation)
    coordinator = _coordinator(monkeypatch, direct_details=(detail,))
    initial = attention.attention_items_for_coordinators((coordinator,))
    detail.expectations = (
        _expectation(
            "dryer:data_quality",
            title="Source data is ready",
            status="ok",
        ),
    )

    resolved = attention.attention_items_for_coordinators((coordinator,))

    assert [item.item_id for item in initial] == [
        "dryer:dryer:data_quality",
    ]
    assert resolved == ()


def test_nilm_attention_item_routes_to_assignment_detail(monkeypatch) -> None:
    nilm = _detail(
        "mains",
        "Dishwasher",
        _expectation(
            "assignment-dishwasher:nilm_validation",
            title="NILM assignment needs validation",
            status="watch",
            source_type="nilm_estimate",
        ),
        assignment_id="assignment-dishwasher",
    )
    coordinator = _coordinator(monkeypatch, nilm_details=(nilm,))

    item = attention.attention_items_for_coordinators((coordinator,))[0]
    params = parse_qs(urlparse(item.action_path or "").query)

    assert params == {
        "appliance_detail": ["1"],
        "assignment_id": ["assignment-dishwasher"],
    }


def test_low_confidence_behavior_sorts_after_nilm_validation(monkeypatch) -> None:
    behavior = _detail(
        "refrigerator",
        "Refrigerator",
        _expectation(
            "refrigerator:energy",
            title="Energy is above normal",
            status="watch",
            confidence=0.5,
        ),
    )
    nilm = _detail(
        "mains",
        "Dishwasher",
        _expectation(
            "assignment-dishwasher:nilm_validation",
            title="NILM assignment needs validation",
            status="watch",
            source_type="nilm_estimate",
        ),
        assignment_id="assignment-dishwasher",
    )
    coordinator = _coordinator(
        monkeypatch,
        direct_details=(behavior,),
        nilm_details=(nilm,),
    )

    items = attention.attention_items_for_coordinators((coordinator,))

    assert [item.appliance_key for item in items] == [
        "nilm:assignment-dishwasher",
        "refrigerator",
    ]


def test_validated_nilm_behavior_uses_behavior_category(monkeypatch) -> None:
    nilm = _detail(
        "mains",
        "Dishwasher",
        _expectation(
            "assignment-dishwasher:energy",
            title="Estimated energy is above normal",
            status="watch",
            source_type="nilm_estimate",
        ),
        assignment_id="assignment-dishwasher",
    )
    coordinator = _coordinator(monkeypatch, nilm_details=(nilm,))

    item = attention.attention_items_for_coordinators((coordinator,))[0]

    assert item.category == "review_appliance_behavior"


def test_real_learning_only_appliance_is_omitted() -> None:
    coordinator = SimpleNamespace(
        circuit_configs=(
            CircuitConfig(
                circuit_id="refrigerator",
                name="Refrigerator",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(),
            ),
        ),
        current_time=lambda: NOW,
        state=AnalyzerState(),
        store_data=FeatureStoreData(),
    )

    assert attention.attention_items_for_coordinators((coordinator,)) == ()
