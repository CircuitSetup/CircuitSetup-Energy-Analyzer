"""Stable frontend and authenticated API paths exposed by the panel."""

from .const import DOMAIN

PANEL_URL_PATH = "circuitsetup-energy-analyzer-evidence"
PANEL_ELEMENT_NAME = "circuitsetup-energy-analyzer-panel"
STATIC_URL_PATH = "/circuitsetup_energy_analyzer_static"
PANEL_MODULE_NAME = "energy-analyzer-panel.js"
PANEL_MODULE_VERSION = "20260713-12"

EVIDENCE_API_PATH = f"/api/{DOMAIN}/alert_evidence"
APPLIANCE_DETAIL_API_PATH = f"/api/{DOMAIN}/appliance_detail"
APPLIANCE_INSIGHTS_API_PATH = f"/api/{DOMAIN}/appliance_insights"
SETUP_HEALTH_API_PATH = f"/api/{DOMAIN}/setup_health"
NILM_WORKSPACE_API_PATH = f"/api/{DOMAIN}/nilm_workspace"
NILM_WORKSPACE_HISTORY_API_PATH = f"/api/{DOMAIN}/nilm_workspace_history"
