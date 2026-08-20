from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
DOMAIN = ROOT / "custom_components" / "circuitsetup_energy_analyzer"


def test_removed_surfaces_stay_removed() -> None:
    for relative_path in (
        ".codex/scripts/update-codegraph.ps1",
        "docs/codegraph/generate_codegraph.py",
        "docs/codegraph/README.md",
        "docs/codegraph/CODEX_README.md",
        "custom_components/circuitsetup_energy_analyzer/demo.py",
        "custom_components/circuitsetup_energy_analyzer/demo_nilm_workspace.json",
        "custom_components/circuitsetup_energy_analyzer/managers/demo_data.py",
    ):
        assert not (ROOT / relative_path).exists()

    production_sources = {
        path: path.read_text(encoding="utf-8") for path in DOMAIN.rglob("*.py")
    }
    assert all(
        "CONF_DEMO_SOURCE_BUNDLE_ENABLED" not in source
        and "DemoDataSeeder" not in source
        and "DemoSourceSensor" not in source
        for source in production_sources.values()
    )

    assert all(
        "ModuleNotFoundError" not in source for source in production_sources.values()
    )

    panel = (DOMAIN / "frontend" / "energy-analyzer-panel-main.js").read_text(
        encoding="utf-8"
    )
    assert "class CircuitSetupPanelComponent" not in panel
    assert panel.count("this._applianceInsights = null;") == 1
    assert panel.count("this._applianceInsightsLoading = false;") == 1
    assert panel.count('this._applianceInsightsError = "";') == 1

    models = (DOMAIN / "models.py").read_text(encoding="utf-8")
    assert "HVAC_SYSTEM" not in models
