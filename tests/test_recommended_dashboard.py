from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from custom_components.circuitsetup_energy_analyzer.const import (
    DASHBOARD_LAYOUT_EXPERT,
    DASHBOARD_LAYOUT_SIMPLE,
    DASHBOARD_LAYOUT_STANDARD,
)
from custom_components.circuitsetup_energy_analyzer.dashboard import (
    DASHBOARD_URL_PATH,
    build_recommended_dashboard,
)
from custom_components.circuitsetup_energy_analyzer.models import (
    ApplianceProfile,
    CircuitConfig,
    CircuitMode,
    SensorRef,
    SensorRole,
)


def _circuits() -> tuple[CircuitConfig, ...]:
    return (
        CircuitConfig(
            circuit_id="fridge",
            name="Refrigerator",
            appliance_profile=ApplianceProfile.REFRIGERATOR,
            mode=CircuitMode.SINGLE_PHASE,
            sensors=(
                SensorRef("sensor.fridge_power", SensorRole.REAL_POWER),
                SensorRef("sensor.fridge_energy", SensorRole.ENERGY),
            ),
        ),
        CircuitConfig(
            circuit_id="mains",
            name="Mains NILM",
            appliance_profile=ApplianceProfile.MAINS_NILM,
            mode=CircuitMode.MAINS_NILM,
            sensors=(),
        ),
    )


def _circuit_dicts() -> list[dict[str, object]]:
    return [
        {
            **asdict(circuit),
            "appliance_profile": circuit.appliance_profile.value,
            "mode": circuit.mode.value,
        }
        for circuit in _circuits()
    ]


def _entity_refs(config: dict[str, object]) -> set[str]:
    refs: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            entity_id = value.get("entity")
            if isinstance(entity_id, str):
                refs.add(entity_id)
            entities = value.get("entities")
            if isinstance(entities, list):
                for item in entities:
                    if isinstance(item, str):
                        refs.add(item)
                    else:
                        walk(item)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(config)
    return refs


def _entity_ref_count(config: dict[str, object], entity_id: str) -> int:
    count = 0

    def walk(value: object) -> None:
        nonlocal count
        if isinstance(value, dict):
            if value.get("entity") == entity_id:
                count += 1
            entities = value.get("entities")
            if isinstance(entities, list):
                for item in entities:
                    if item == entity_id:
                        count += 1
                    else:
                        walk(item)
            for key, nested in value.items():
                if key == "entities":
                    continue
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(config)
    return count


def _markdown_contents(config: dict[str, object]) -> list[str]:
    contents: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            if value.get("type") == "markdown" and isinstance(
                value.get("content"),
                str,
            ):
                contents.append(value["content"])
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(config)
    return contents


def _registry_entry(
    entity_id: str,
    unique_id: str,
    *,
    disabled_by: str | None = None,
    circuit_id: str | None = None,
    entity_key: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        entity_id=entity_id,
        unique_id=unique_id,
        config_entry_id="entry-1",
        platform="circuitsetup_energy_analyzer",
        disabled_by=disabled_by,
        circuit_id=circuit_id,
        entity_key=entity_key,
    )


def test_simple_dashboard_layout_uses_core_appliance_entities() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_SIMPLE)
    refs = _entity_refs(dashboard)

    assert dashboard["title"] == "CircuitSetup Energy Analyzer"
    assert dashboard["views"][0]["path"] == DASHBOARD_URL_PATH
    assert {
        "sensor.fridge_health_summary",
        "sensor.fridge_activity_summary",
        "sensor.fridge_electrical_health",
        "sensor.fridge_energy_summary",
        "sensor.fridge_daily_energy_usage",
        "binary_sensor.fridge_running",
    } <= refs
    assert "sensor.fridge_metric_consistency_status" not in refs
    assert "sensor.fridge_alert_evidence" not in refs


def test_standard_dashboard_layout_adds_configured_feature_status_entities() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_STANDARD)
    refs = _entity_refs(dashboard)

    assert {
        "sensor.fridge_metric_consistency_status",
        "sensor.fridge_energy_usage_status",
        "sensor.mains_nilm_unknown_loads",
    } <= refs
    assert "sensor.fridge_alert_evidence" not in refs


def test_expert_dashboard_layout_adds_diagnostics_and_evidence_links() -> None:
    dashboard = build_recommended_dashboard(_circuits(), DASHBOARD_LAYOUT_EXPERT)
    refs = _entity_refs(dashboard)
    markdown = str(dashboard)

    assert {
        "sensor.fridge_alert_evidence",
        "sensor.fridge_power_quality_evidence",
        "sensor.fridge_energy_dashboard_status",
    } <= refs
    assert "/circuitsetup-energy-analyzer-evidence" in markdown


def test_dashboard_uses_entity_registry_ids_for_renamed_entities() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.kitchen_fridge_health": _registry_entry(
                        "sensor.kitchen_fridge_health",
                        "entry-1_fridge_health_summary",
                    ),
                    "sensor.kitchen_fridge_activity": _registry_entry(
                        "sensor.kitchen_fridge_activity",
                        "entry-1_fridge_activity_summary",
                    ),
                    "sensor.kitchen_fridge_electrical": _registry_entry(
                        "sensor.kitchen_fridge_electrical",
                        "entry-1_fridge_electrical_health",
                    ),
                    "sensor.kitchen_fridge_energy": _registry_entry(
                        "sensor.kitchen_fridge_energy",
                        "entry-1_fridge_energy_summary",
                    ),
                    "sensor.kitchen_fridge_daily_kwh": _registry_entry(
                        "sensor.kitchen_fridge_daily_kwh",
                        "entry-1_fridge_daily_energy_usage",
                    ),
                    "binary_sensor.kitchen_fridge_running_now": _registry_entry(
                        "binary_sensor.kitchen_fridge_running_now",
                        "entry-1_fridge_running",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert {
        "sensor.kitchen_fridge_health",
        "sensor.kitchen_fridge_activity",
        "sensor.kitchen_fridge_electrical",
        "sensor.kitchen_fridge_energy",
        "sensor.kitchen_fridge_daily_kwh",
        "binary_sensor.kitchen_fridge_running_now",
    } <= refs
    assert "sensor.fridge_health_summary" not in refs
    assert "binary_sensor.fridge_running" not in refs


def test_dashboard_uses_registry_metadata_when_unique_id_scheme_changes() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.renamed_health": _registry_entry(
                        "sensor.renamed_health",
                        "future-scheme-1",
                        circuit_id="fridge",
                        entity_key="health_summary",
                    ),
                    "sensor.renamed_activity": _registry_entry(
                        "sensor.renamed_activity",
                        "future-scheme-2",
                        circuit_id="fridge",
                        entity_key="activity_summary",
                    ),
                    "binary_sensor.renamed_running": _registry_entry(
                        "binary_sensor.renamed_running",
                        "future-scheme-3",
                        circuit_id="fridge",
                        entity_key="running",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert {
        "sensor.renamed_health",
        "sensor.renamed_activity",
        "binary_sensor.renamed_running",
    } <= refs
    assert "sensor.fridge_health_summary" not in refs
    assert "binary_sensor.fridge_running" not in refs


def test_dashboard_notes_ambiguous_metadata_matches_without_guessing() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.first_health": _registry_entry(
                        "sensor.first_health",
                        "future-scheme-1",
                        circuit_id="fridge",
                        entity_key="health_summary",
                    ),
                    "sensor.second_health": _registry_entry(
                        "sensor.second_health",
                        "future-scheme-2",
                        circuit_id="fridge",
                        entity_key="health_summary",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)
    markdown = "\n".join(_markdown_contents(dashboard))

    assert "sensor.first_health" not in refs
    assert "sensor.second_health" not in refs
    assert "sensor.fridge_health_summary" not in refs
    assert "Ambiguous entities: Health Summary" in markdown
    assert (
        "Next step: remove duplicate stale analyzer entities or reload the integration."
        in markdown
    )


def test_dashboard_does_not_suffix_match_nested_circuit_unique_ids() -> None:
    dashboard = build_recommended_dashboard(
        (
            CircuitConfig(
                circuit_id="fridge",
                name="Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(),
            ),
            CircuitConfig(
                circuit_id="kitchen_fridge",
                name="Kitchen Fridge",
                appliance_profile=ApplianceProfile.REFRIGERATOR,
                mode=CircuitMode.SINGLE_PHASE,
                sensors=(),
            ),
        ),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.kitchen_fridge_health": _registry_entry(
                        "sensor.kitchen_fridge_health",
                        "entry-1_kitchen_fridge_health_summary",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    markdown = "\n".join(_markdown_contents(dashboard))

    assert _entity_ref_count(dashboard, "sensor.kitchen_fridge_health") == 1
    assert "Fridge dashboard note" in markdown
    assert "Missing entities: Health Summary" in markdown


def test_dashboard_adds_helpful_notes_for_missing_and_disabled_entities() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "sensor.kitchen_fridge_health": _registry_entry(
                        "sensor.kitchen_fridge_health",
                        "entry-1_fridge_health_summary",
                    ),
                    "sensor.kitchen_fridge_activity": _registry_entry(
                        "sensor.kitchen_fridge_activity",
                        "entry-1_fridge_activity_summary",
                        disabled_by="integration",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)
    markdown = "\n".join(_markdown_contents(dashboard))

    assert "sensor.kitchen_fridge_health" in refs
    assert "sensor.kitchen_fridge_activity" not in refs
    assert "Refrigerator dashboard note" in markdown
    assert "Disabled entities: Activity Summary" in markdown
    assert "Next step: enable these entities from Home Assistant entity settings." in (
        markdown
    )
    assert (
        "Missing entities: Electrical Health, Energy Summary, Daily Energy Usage, "
        "Running"
        in markdown
    )
    assert (
        "Next step: reload the integration or review Entity Detail Level."
        in markdown
    )


def test_dashboard_does_not_guess_ids_when_registry_is_available_but_empty() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(entity_registry=SimpleNamespace(entities={})),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)
    markdown = "\n".join(_markdown_contents(dashboard))

    assert "sensor.fridge_health_summary" not in refs
    assert "binary_sensor.fridge_running" not in refs
    assert "Refrigerator dashboard note" in markdown
    assert (
        "Missing entities: Health Summary, Activity Summary, Electrical Health, "
        "Energy Summary, Daily Energy Usage, Running"
    ) in markdown
    assert (
        "Next step: reload the integration or review Entity Detail Level."
        in markdown
    )


def test_dashboard_uses_registry_ids_for_global_and_circuit_controls() -> None:
    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "select.layout_choice": _registry_entry(
                        "select.layout_choice",
                        "entry-1_dashboard_layout",
                    ),
                    "select.detail_choice": _registry_entry(
                        "select.detail_choice",
                        "entry-1_entity_detail_level",
                    ),
                    "button.mapping_now": _registry_entry(
                        "button.mapping_now",
                        "entry-1_run_mapping_checks",
                    ),
                    "button.refresh_suggestions": _registry_entry(
                        "button.refresh_suggestions",
                        "entry-1_recalculate_suggestions",
                    ),
                    "button.update_dashboard": _registry_entry(
                        "button.update_dashboard",
                        "entry-1_create_dashboard",
                    ),
                    "select.fridge_sensitivity": _registry_entry(
                        "select.fridge_sensitivity",
                        "entry-1_fridge_alert_sensitivity",
                    ),
                    "number.fridge_kwh_goal": _registry_entry(
                        "number.fridge_kwh_goal",
                        "entry-1_fridge_daily_energy_goal",
                    ),
                    "button.fridge_relearn": _registry_entry(
                        "button.fridge_relearn",
                        "entry-1_fridge_relearn_baseline",
                    ),
                    "button.fridge_start_maintenance": _registry_entry(
                        "button.fridge_start_maintenance",
                        "entry-1_fridge_start_maintenance",
                    ),
                    "button.fridge_end_maintenance": _registry_entry(
                        "button.fridge_end_maintenance",
                        "entry-1_fridge_end_maintenance",
                    ),
                    "button.fridge_pause_alerts": _registry_entry(
                        "button.fridge_pause_alerts",
                        "entry-1_fridge_pause_alerts",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert {
        "select.layout_choice",
        "select.detail_choice",
        "button.mapping_now",
        "button.refresh_suggestions",
        "button.update_dashboard",
        "select.fridge_sensitivity",
        "number.fridge_kwh_goal",
        "button.fridge_relearn",
        "button.fridge_start_maintenance",
        "button.fridge_end_maintenance",
        "button.fridge_pause_alerts",
    } <= refs
    assert "button.fridge_create_dashboard" not in refs


def test_dashboard_omits_unsupported_per_circuit_controls() -> None:
    dashboard = build_recommended_dashboard(
        (
            CircuitConfig(
                circuit_id="mains",
                name="Mains NILM",
                appliance_profile=ApplianceProfile.MAINS_NILM,
                mode=CircuitMode.MAINS_NILM,
                sensors=(SensorRef("sensor.mains_power", SensorRole.REAL_POWER),),
            ),
        ),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "select.mains_sensitivity": _registry_entry(
                        "select.mains_sensitivity",
                        "entry-1_mains_alert_sensitivity",
                    ),
                    "number.mains_kwh_goal": _registry_entry(
                        "number.mains_kwh_goal",
                        "entry-1_mains_daily_energy_goal",
                    ),
                    "button.mains_relearn": _registry_entry(
                        "button.mains_relearn",
                        "entry-1_mains_relearn_baseline",
                    ),
                    "button.mains_start_maintenance": _registry_entry(
                        "button.mains_start_maintenance",
                        "entry-1_mains_start_maintenance",
                    ),
                    "button.mains_pause_alerts": _registry_entry(
                        "button.mains_pause_alerts",
                        "entry-1_mains_pause_alerts",
                    ),
                }
            )
        ),
        entry_id="entry-1",
    )
    refs = _entity_refs(dashboard)

    assert "select.mains_sensitivity" in refs
    assert "number.mains_kwh_goal" not in refs
    assert "button.mains_relearn" not in refs
    assert "button.mains_start_maintenance" not in refs
    assert "button.mains_pause_alerts" not in refs


def test_dashboard_adds_notes_for_missing_disabled_and_unavailable_controls() -> None:
    class FakeStates:
        def get(self, entity_id: str) -> SimpleNamespace | None:
            if entity_id == "button.fridge_pause_alerts":
                return SimpleNamespace(state="unavailable")
            if entity_id == "button.fridge_end_maintenance":
                return SimpleNamespace(state="unknown")
            return SimpleNamespace(state="idle")

    dashboard = build_recommended_dashboard(
        _circuits(),
        DASHBOARD_LAYOUT_SIMPLE,
        hass=SimpleNamespace(
            entity_registry=SimpleNamespace(
                entities={
                    "select.layout_choice": _registry_entry(
                        "select.layout_choice",
                        "entry-1_dashboard_layout",
                        disabled_by="integration",
                    ),
                    "button.fridge_relearn": _registry_entry(
                        "button.fridge_relearn",
                        "entry-1_fridge_relearn_baseline",
                    ),
                    "button.fridge_end_maintenance": _registry_entry(
                        "button.fridge_end_maintenance",
                        "entry-1_fridge_end_maintenance",
                    ),
                    "button.fridge_pause_alerts": _registry_entry(
                        "button.fridge_pause_alerts",
                        "entry-1_fridge_pause_alerts",
                    ),
                }
            ),
            states=FakeStates(),
        ),
        entry_id="entry-1",
    )
    markdown = "\n".join(_markdown_contents(dashboard))

    assert "Dashboard controls note" in markdown
    assert "Disabled entities: Dashboard Layout" in markdown
    assert "Next step: enable these entities from Home Assistant entity settings." in (
        markdown
    )
    assert "Refrigerator controls note" in markdown
    assert "Missing entities: Alert Sensitivity, Daily Energy Goal" in markdown
    assert (
        "Next step: reload the integration or review Entity Detail Level."
        in markdown
    )
    assert "Unavailable entities: End Maintenance, Pause Alerts" in markdown
    assert "Next step: open the entity details and follow its availability reason." in (
        markdown
    )


class _FakeDashboardsCollection:
    def __init__(self, existing: bool) -> None:
        self._existing = existing
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []
        self.dashboard_stores: dict[str, _FakeLovelaceStorage] | None = None

    async def async_items(self) -> list[dict[str, object]]:
        if not self._existing:
            return []
        return [{"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}]

    async def async_create_item(self, data: dict[str, object]) -> dict[str, object]:
        self.created.append(data)
        item = {"id": DASHBOARD_URL_PATH, **data}
        if self.dashboard_stores is not None:
            self.dashboard_stores[DASHBOARD_URL_PATH] = _FakeLovelaceStorage(item)
        return item

    async def async_update_item(
        self,
        item_id: str,
        data: dict[str, object],
    ) -> dict[str, object]:
        self.updated.append((item_id, data))
        return {"id": item_id, **data}


class _FakeLovelaceStorage:
    def __init__(self, config: dict[str, object]) -> None:
        self.config = config
        self.saved: list[dict[str, object]] = []

    async def async_save(self, config: dict[str, object]) -> None:
        self.saved.append(config)


class _FakeAttributeDashboardsCollection:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.updated: list[tuple[str, dict[str, object]]] = []

    async def async_items(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                id="lovelace-circuitsetup-energy-analyzer",
                url_path=DASHBOARD_URL_PATH,
            )
        ]

    async def async_create_item(self, data: dict[str, object]) -> dict[str, object]:
        self.created.append(data)
        return {"id": DASHBOARD_URL_PATH, **data}

    async def async_update_item(
        self,
        item_id: str,
        data: dict[str, object],
    ) -> dict[str, object]:
        self.updated.append((item_id, data))
        return {"id": item_id, **data}


class _FakeSyncItemsDashboardsCollection(_FakeDashboardsCollection):
    def async_items(self) -> list[dict[str, object]]:  # type: ignore[override]
        if not self._existing:
            return []
        return [{"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}]


class _FakeExistingDashboardWithoutUpdate:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []

    async def async_items(self) -> list[dict[str, object]]:
        return [{"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}]

    async def async_create_item(self, data: dict[str, object]) -> dict[str, object]:
        self.created.append(data)
        return {"id": DASHBOARD_URL_PATH, **data}


@pytest.mark.asyncio
async def test_coordinator_creates_recommended_dashboard_with_selected_layout() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
    dashboards: dict[str, _FakeLovelaceStorage] = {}
    collection.dashboard_stores = dashboards
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": dashboards,
                "dashboards_collection": collection,
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert len(collection.created) == 1
    created = collection.created[0]
    assert created["url_path"] == DASHBOARD_URL_PATH
    assert created["mode"] == "storage"
    assert created["title"] == "CircuitSetup Energy Analyzer"
    assert "config" not in created
    assert "sensor.fridge_metric_consistency_status" in str(
        dashboards[DASHBOARD_URL_PATH].saved[0]
    )
    assert coordinator.last_dashboard_create_request["action"] == "created"
    assert (
        coordinator.last_dashboard_create_request["layout"]
        == DASHBOARD_LAYOUT_STANDARD
    )


@pytest.mark.asyncio
async def test_coordinator_updates_existing_recommended_dashboard() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=True)
    dashboard_store = _FakeLovelaceStorage(
        {"id": DASHBOARD_URL_PATH, "url_path": DASHBOARD_URL_PATH}
    )
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": {DASHBOARD_URL_PATH: dashboard_store},
                "dashboards_collection": collection,
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_EXPERT},
    )

    await coordinator.async_create_dashboard()

    assert collection.created == []
    assert len(collection.updated) == 1
    item_id, update = collection.updated[0]
    assert item_id == DASHBOARD_URL_PATH
    assert update["title"] == "CircuitSetup Energy Analyzer"
    assert "config" not in update
    assert "sensor.fridge_alert_evidence" in str(dashboard_store.saved[0])
    assert coordinator.last_dashboard_create_request["action"] == "updated"


@pytest.mark.asyncio
async def test_coordinator_updates_attribute_shaped_existing_dashboard() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeAttributeDashboardsCollection()
    dashboard_store = _FakeLovelaceStorage(
        {
            "id": "lovelace-circuitsetup-energy-analyzer",
            "url_path": DASHBOARD_URL_PATH,
        }
    )
    hass = SimpleNamespace(
        data={
            "lovelace": {
                "dashboards": {DASHBOARD_URL_PATH: dashboard_store},
                "dashboards_collection": collection,
            }
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert collection.created == []
    assert len(collection.updated) == 1
    item_id, update = collection.updated[0]
    assert item_id == "lovelace-circuitsetup-energy-analyzer"
    assert update["title"] == "CircuitSetup Energy Analyzer"
    assert dashboard_store.saved
    assert coordinator.last_dashboard_create_request["action"] == "updated"


@pytest.mark.asyncio
async def test_coordinator_reads_attribute_shaped_lovelace_data() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
    dashboards: dict[str, _FakeLovelaceStorage] = {}
    collection.dashboard_stores = dashboards
    hass = SimpleNamespace(
        data={
            "lovelace": SimpleNamespace(
                dashboards=dashboards,
                dashboards_collection=collection,
            )
        }
    )
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert len(collection.created) == 1
    assert dashboards[DASHBOARD_URL_PATH].saved
    assert coordinator.last_dashboard_create_request["action"] == "created"


@pytest.mark.asyncio
async def test_coordinator_creates_dashboard_from_current_lovelace_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as module
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeDashboardsCollection(existing=False)
    lovelace_data = SimpleNamespace(
        dashboards={},
        resources=object(),
        yaml_dashboards={},
    )
    collection.dashboard_stores = lovelace_data.dashboards

    async def load_collection(hass: object, data: object) -> object:
        assert data is lovelace_data
        return collection

    monkeypatch.setattr(
        module,
        "_async_load_lovelace_dashboards_collection",
        load_collection,
        raising=False,
    )
    hass = SimpleNamespace(data={"lovelace": lovelace_data})
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert len(collection.created) == 1
    created = collection.created[0]
    assert created["url_path"] == DASHBOARD_URL_PATH
    assert created["mode"] == "storage"
    assert "config" not in created
    stored_dashboard = lovelace_data.dashboards[DASHBOARD_URL_PATH]
    assert stored_dashboard.saved
    assert "sensor.fridge_metric_consistency_status" in str(
        stored_dashboard.saved[0]
    )
    assert coordinator.last_dashboard_create_request["action"] == "created"


@pytest.mark.asyncio
async def test_coordinator_handles_sync_lovelace_dashboard_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator as module
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeSyncItemsDashboardsCollection(existing=False)
    lovelace_data = SimpleNamespace(
        dashboards={},
        resources=object(),
        yaml_dashboards={},
    )
    collection.dashboard_stores = lovelace_data.dashboards

    async def load_collection(hass: object, data: object) -> object:
        assert data is lovelace_data
        return collection

    monkeypatch.setattr(
        module,
        "_async_load_lovelace_dashboards_collection",
        load_collection,
        raising=False,
    )
    hass = SimpleNamespace(data={"lovelace": lovelace_data})
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert len(collection.created) == 1
    assert lovelace_data.dashboards[DASHBOARD_URL_PATH].saved
    assert coordinator.last_dashboard_create_request["action"] == "created"


@pytest.mark.asyncio
async def test_coordinator_skips_duplicate_dashboard_when_update_unavailable() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    collection = _FakeExistingDashboardWithoutUpdate()
    hass = SimpleNamespace(data={"lovelace": {"dashboards_collection": collection}})
    coordinator = EnergyAnalyzerCoordinator(
        hass,
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert collection.created == []
    assert coordinator.last_dashboard_create_request["action"] == "unavailable"
    assert (
        coordinator.last_dashboard_create_request["reason"]
        == "dashboard_update_unavailable"
    )


@pytest.mark.asyncio
async def test_coordinator_records_reason_when_lovelace_collection_is_missing() -> None:
    from custom_components.circuitsetup_energy_analyzer.coordinator import (
        EnergyAnalyzerCoordinator,
    )

    coordinator = EnergyAnalyzerCoordinator(
        SimpleNamespace(data={}),
        entry_data={"circuits": _circuit_dicts()},
        options={"dashboard_layout": DASHBOARD_LAYOUT_STANDARD},
    )

    await coordinator.async_create_dashboard()

    assert coordinator.last_dashboard_create_request["action"] == "unavailable"
    assert (
        coordinator.last_dashboard_create_request["reason"]
        == "lovelace_dashboard_collection_unavailable"
    )
