from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "circuitsetup_energy_analyzer"
FRONTEND = INTEGRATION / "frontend"


def test_appliance_detail_facade_reexports_read_models() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        appliance_detail,
        appliance_detail_models,
    )

    for name in (
        "ComparisonMode",
        "MetricComparison",
        "ApplianceExpectation",
        "ApplianceAlertSummary",
        "ApplianceDetail",
    ):
        assert getattr(appliance_detail, name) is getattr(appliance_detail_models, name)


def test_panel_facade_reexports_http_views() -> None:
    from custom_components.circuitsetup_energy_analyzer import panel, panel_views

    expected = {
        "AlertEvidenceView": "/api/circuitsetup_energy_analyzer/alert_evidence",
        "ApplianceDetailView": "/api/circuitsetup_energy_analyzer/appliance_detail",
        "ApplianceInsightsView": "/api/circuitsetup_energy_analyzer/appliance_insights",
        "SetupHealthView": "/api/circuitsetup_energy_analyzer/setup_health",
        "NilmWorkspaceView": "/api/circuitsetup_energy_analyzer/nilm_workspace",
        "NilmWorkspaceHistoryView": (
            "/api/circuitsetup_energy_analyzer/nilm_workspace_history"
        ),
    }
    for name, url in expected.items():
        facade_view = getattr(panel, name)
        assert facade_view is getattr(panel_views, name)
        assert facade_view.url == url
        assert facade_view.requires_auth is True


def test_frontend_entrypoint_loads_versioned_modules() -> None:
    from custom_components.circuitsetup_energy_analyzer.panel import (
        PANEL_MODULE_VERSION,
    )

    entry = (FRONTEND / "energy-analyzer-panel.js").read_text(encoding="utf-8")
    main = FRONTEND / "energy-analyzer-panel-main.js"
    dashboard = FRONTEND / "energy-analyzer-dashboard-graphs.js"

    assert main.exists()
    assert dashboard.exists()
    assert "new URL(import.meta.url).search" in entry
    assert '"./energy-analyzer-panel-main.js"' in entry
    assert '"./energy-analyzer-dashboard-graphs.js"' in entry
    assert '"./energy-analyzer-panel-shell.js"' in entry
    assert '"./energy-analyzer-appliance-views.js"' in entry
    assert '"./energy-analyzer-nilm-workspace.js"' in entry
    assert '"./energy-analyzer-evidence-views.js"' in entry
    assert "registerEnergyAnalyzerPanel(registerDashboardGraphs, [" in entry
    assert f'?v={PANEL_MODULE_VERSION}' not in entry


def test_frontend_routes_are_split_into_responsibility_modules() -> None:
    main = FRONTEND / "energy-analyzer-panel-main.js"
    modules = {
        "energy-analyzer-panel-shell.js": "_render()",
        "energy-analyzer-appliance-views.js": "_renderApplianceDetailContent()",
        "energy-analyzer-nilm-workspace.js": "_renderNilmWorkspaceContent()",
        "energy-analyzer-evidence-views.js": "_renderAlertContent(",
    }

    assert len(main.read_text(encoding="utf-8").splitlines()) < 3_000
    for filename, method in modules.items():
        source = (FRONTEND / filename).read_text(encoding="utf-8")
        assert method in source
        assert 'from "./energy-analyzer-panel-main.js"' not in source


def test_panel_facade_reexports_nilm_payload_builders() -> None:
    from custom_components.circuitsetup_energy_analyzer import panel, panel_nilm

    assert len(Path(panel.__file__).read_text(encoding="utf-8").splitlines()) < 2_500
    for name in (
        "_nilm_payload_for_circuit",
        "_nilm_assignment_payload",
        "_nilm_workspace_sessions",
        "_nilm_session_payload",
    ):
        assert getattr(panel, name) is getattr(panel_nilm, name)


def test_coordinator_facade_reexports_state_contracts() -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator, state

    assert coordinator.AnalyzerState is state.AnalyzerState
    assert coordinator.process_events_into_state is state.process_events_into_state
    assert coordinator._apply_state_update is state._apply_state_update


def test_coordinator_facade_reexports_nilm_unmatched_edge_limit() -> None:
    from custom_components.circuitsetup_energy_analyzer import (
        coordinator,
        runtime_factory,
    )

    assert (
        coordinator.NILM_UNMATCHED_EDGES_MAX_ITEMS_PER_CIRCUIT
        is runtime_factory.NILM_UNMATCHED_EDGES_MAX_ITEMS_PER_CIRCUIT
    )


def test_runtime_factory_preserves_processor_and_listener_wiring() -> None:
    from custom_components.circuitsetup_energy_analyzer import coordinator
    from custom_components.circuitsetup_energy_analyzer.runtime_factory import (
        initialize_runtime,
    )

    assert callable(initialize_runtime)
    instance = coordinator.EnergyAnalyzerCoordinator(SimpleNamespace())

    assert instance.pipeline._coordinator is instance
    assert instance.pipeline._event_processor is instance._event_processor
    assert instance.nilm_controller._sample_processor is instance._nilm_sample_processor
    assert (
        instance.source_updates._track_state_change_event
        is coordinator.async_track_state_change_event
    )
    assert (
        instance.source_updates._debounce_seconds
        == coordinator.SOURCE_STATE_UPDATE_DEBOUNCE_SECONDS
    )
    assert (
        instance.source_updates._max_batch_seconds
        == coordinator.SOURCE_STATE_UPDATE_MAX_BATCH_SECONDS
    )
