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
        assert parsed.path == "/circuitsetup-energy-analyzer-evidence"
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


def test_two_meter_warning_only_agrees_with_insights_and_clears() -> None:
    from custom_components.circuitsetup_energy_analyzer.appliance_insights import (
        appliance_insights_for_coordinators,
    )
    from tests.test_appliance_detail import _direct_coordinator

    meters = (_direct_coordinator(), _direct_coordinator())
    meters[1].entry_id = "entry-2"
    items = attention.attention_items_for_coordinators(meters)
    rows = appliance_insights_for_coordinators(meters)
    assert len(items) == 2
    for row in rows:
        assert row.needs_attention
        finding = row.as_dict()["finding"]
        item = next(i for i in items if i.entry_id == row.entry_id)
        assert (
            finding["reason"]
            == item.reason
            == "Kitchen Fridge is using more energy than usual."
        )
        assert row.entry_id in finding["action"]["path"]
        assert finding["alert_ids"] == item.as_dict()["alert_ids"]
    meters[0].state.active_alerts_by_circuit.clear()
    assert [i.entry_id for i in attention.attention_items_for_coordinators(meters)] == [
        "entry-2"
    ]
    assert [
        r.entry_id
        for r in appliance_insights_for_coordinators(meters)
        if r.needs_attention
    ] == ["entry-2"]


def test_stale_source_keeps_evidence_then_survives_maintenance() -> None:
    from tests.test_appliance_detail import _direct_coordinator

    coord = _direct_coordinator()
    checklist = coord.state.data_quality_checklist_by_circuit["fridge"]
    checklist.update(
        source_data_fresh=False, quality_issues=["sensor.fridge_power stale"]
    )
    (item,) = attention.attention_items_for_coordinators([coord])
    assert item.action == {
        "kind": "open_sensor",
        "label": "Open sensor",
        "entity_id": "sensor.fridge_power",
    }
    assert {action["kind"] for action in item.actions} == {
        "open_sensor",
        "review_evidence",
    }
    coord.hass = SimpleNamespace(states={})
    (missing,) = attention.attention_items_for_coordinators([coord])
    assert missing.action["kind"] == "open_setup_health"
    coord.hass.states["sensor.fridge_power"] = object()
    coord.state.maintenance_by_circuit["fridge"] = {"active": True}
    (item,) = attention.attention_items_for_coordinators([coord])
    assert not item.alert_ids
    assert item.action["kind"] == "open_sensor"
    for issues in (
        ["sensor.fridge_power stale", "sensor.fridge_energy stale"],
        ["stale"],
        ["sensor.removed stale"],
    ):
        checklist["quality_issues"] = issues
        (item,) = attention.attention_items_for_coordinators([coord])
        assert item.action["kind"] == "open_setup_health"
        assert parse_qs(urlparse(item.action["path"]).query)["entry_id"] == ["entry-1"]
    checklist.update(source_data_fresh=True, quality_issues=[])
    assert not attention.attention_items_for_coordinators([coord])


def test_feed_and_assignment_warnings_have_distinct_owners_after_conversion() -> None:
    from dataclasses import replace

    from tests.test_appliance_detail import (
        _config,
        _direct_coordinator,
        _nilm_coordinator,
    )

    coord = _nilm_coordinator()
    template = _direct_coordinator().state.active_alerts_by_circuit["fridge"][0]
    supply = replace(
        template, circuit_id="mains", feature="voltage_sag", message="Low feed voltage"
    )
    assigned = replace(
        template,
        circuit_id="mains",
        features={"assignment_id": "assignment-dishwasher"},
    )
    coord.hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_get_entry=lambda _: SimpleNamespace(title="Garage Meter")
        )
    )
    coord.entry_id = "garage"
    coord.state.active_alerts_by_circuit["mains"] = [supply, assigned]
    for converted in (False, True):
        if converted:
            coord.circuit_configs += (_config("dishwasher_direct"),)
            assignment = coord.store_data.nilm_appliance_assignments_by_circuit[
                "mains"
            ][0]
            assignment.update(
                conversion_state="direct_meter",
                direct_circuit_id="dishwasher_direct",
                publish_entities=False,
            )
        items = attention.attention_items_for_coordinators([coord])
        assert len(items) == 2
        feed = next(i for i in items if i.source_type == "mains")
        appliance = next(i for i in items if i.source_type != "mains")
        assert feed.display_name == "Garage Meter"
        assert feed.reason == supply.message
        assert appliance.source_type == (
            "direct_meter" if converted else "nilm_estimate"
        )
        assert len(feed.alert_ids) == len(appliance.alert_ids) == 1
        assert feed.alert_ids != appliance.alert_ids


def test_matching_expectation_and_warning_keep_one_evidence_action() -> None:
    from dataclasses import replace

    from tests.test_appliance_detail import _direct_coordinator

    coord = _direct_coordinator()
    detail = attention.appliance_detail_for_circuit(coord, "fridge")
    expected = _expectation(
        "fridge:energy", title="Energy is above normal", status="watch"
    )
    detail = replace(detail, expectations=(expected,))
    item = attention.attention_item_for_detail(coord, detail)
    assert item.reason == detail.active_alerts[0].message
    assert item.action["path"] == detail.active_alerts[0].evidence_path
    assert item.alert_ids == (detail.active_alerts[0].alert_id,)
    cleared = attention.attention_item_for_detail(
        coord, replace(detail, active_alerts=())
    )
    assert cleared.reason == expected.title
    assert cleared.alert_ids == ()
