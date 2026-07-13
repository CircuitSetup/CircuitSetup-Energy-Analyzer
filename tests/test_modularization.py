from __future__ import annotations

from pathlib import Path

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
    assert "registerEnergyAnalyzerPanel(registerDashboardGraphs)" in entry
    assert f'?v={PANEL_MODULE_VERSION}' not in entry
