"""Authenticated Home Assistant HTTP views for the energy analyzer panel."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .const import DOMAIN
from .panel_contracts import (
    APPLIANCE_DETAIL_API_PATH,
    APPLIANCE_INSIGHTS_API_PATH,
    EVIDENCE_API_PATH,
    NILM_WORKSPACE_API_PATH,
    NILM_WORKSPACE_HISTORY_API_PATH,
    SETUP_HEALTH_API_PATH,
)

try:
    from homeassistant.components.http import HomeAssistantView, require_admin
except ModuleNotFoundError:

    class HomeAssistantView:  # type: ignore[no-redef]
        """Fallback base class for unit tests without Home Assistant installed."""

    def require_admin(method: Any) -> Any:
        """Preserve imports when Home Assistant is unavailable."""
        return method


class AlertEvidenceView(HomeAssistantView):
    """Authenticated API endpoint used by the dynamic alert evidence panel."""

    url = EVIDENCE_API_PATH
    name = f"api:{DOMAIN}:alert_evidence"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return alert evidence selected by query parameters."""
        from . import panel

        hass = request.app[panel.KEY_HASS]
        payload = panel.alert_evidence_payload(
            panel._loaded_coordinators(hass),
            alert_id=request.query.get("alert_id"),
            circuit_id=request.query.get("circuit_id"),
            feature=request.query.get("feature"),
            recommendation_id=request.query.get(panel.ATTR_RECOMMENDATION_ID),
            entry_id=request.query.get(panel.ATTR_ENTRY_ID),
            review_suggested_settings=panel._truthy_query(
                request.query.get("review_suggested_settings")
            ),
            include_all_nilm=panel._truthy_query(
                request.query.get("include_all_nilm")
            ),
        )
        return panel.web.json_response(payload)


class ApplianceDetailView(HomeAssistantView):
    """Authenticated appliance-centered detail endpoint."""

    url = APPLIANCE_DETAIL_API_PATH
    name = f"api:{DOMAIN}:appliance_detail"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return appliance detail selected by circuit or NILM assignment."""
        from . import panel

        hass = request.app[panel.KEY_HASS]
        payload = panel.appliance_detail_payload(
            panel._loaded_coordinators(hass),
            circuit_id=request.query.get("circuit_id"),
            assignment_id=request.query.get(panel.ATTR_ASSIGNMENT_ID),
            entry_id=request.query.get(panel.ATTR_ENTRY_ID),
        )
        return panel.web.json_response(payload)

    @require_admin
    async def post(self, request: Any) -> Any:
        """Persist appliance notification or expected-schedule settings."""
        from . import panel

        hass = request.app[panel.KEY_HASS]
        payload = await request.json()
        if isinstance(payload, Mapping) and "expected_schedule" in payload:
            result = await panel.async_set_appliance_expected_schedule(
                panel._loaded_coordinators(hass),
                circuit_id=request.query.get("circuit_id"),
                assignment_id=request.query.get(panel.ATTR_ASSIGNMENT_ID),
                values=payload.get("expected_schedule"),
                entry_id=request.query.get(panel.ATTR_ENTRY_ID),
            )
        else:
            result = await panel.async_set_appliance_notification_preferences(
                panel._loaded_coordinators(hass),
                circuit_id=request.query.get("circuit_id"),
                assignment_id=request.query.get(panel.ATTR_ASSIGNMENT_ID),
                values=payload,
                entry_id=request.query.get(panel.ATTR_ENTRY_ID),
            )
        return panel.web.json_response(result)


class ApplianceInsightsView(HomeAssistantView):
    """Authenticated integration-level appliance index endpoint."""

    url = APPLIANCE_INSIGHTS_API_PATH
    name = f"api:{DOMAIN}:appliance_insights"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return bounded direct and NILM appliance insights."""
        from . import panel

        hass = request.app[panel.KEY_HASS]
        return panel.web.json_response(
            panel.appliance_insights_payload(panel._loaded_coordinators(hass))
        )


class SetupHealthView(HomeAssistantView):
    """Authenticated read-only Setup Health endpoint."""

    url = SETUP_HEALTH_API_PATH
    name = f"api:{DOMAIN}:setup_health"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return the current integration setup checklist."""
        from . import panel

        hass = request.app[panel.KEY_HASS]
        payload = panel.setup_health_payload(
            panel._loaded_coordinators(hass),
            entry_id=request.query.get(panel.ATTR_ENTRY_ID),
        )
        return panel.web.json_response(payload)

    @require_admin
    async def post(self, request: Any) -> Any:
        """Persist weekly digest opt-in and delivery settings."""
        from . import panel

        hass = request.app[panel.KEY_HASS]
        result = await panel.async_set_weekly_digest_settings(
            panel._loaded_coordinators(hass),
            entry_id=request.query.get(panel.ATTR_ENTRY_ID),
            values=await request.json(),
        )
        return panel.web.json_response(result)


class NilmWorkspaceView(HomeAssistantView):
    """Authenticated read-only NILM workspace payload."""

    url = NILM_WORKSPACE_API_PATH
    name = f"api:{DOMAIN}:nilm_workspace"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return bounded NILM workspace data selected by query parameters."""
        from . import panel

        hass = request.app[panel.KEY_HASS]
        payload = panel.nilm_workspace_payload(
            panel._loaded_coordinators(hass),
            circuit_id=request.query.get("circuit_id"),
            hours=request.query.get("hours"),
            entry_id=request.query.get(panel.ATTR_ENTRY_ID),
        )
        return panel.web.json_response(payload)


class NilmWorkspaceHistoryView(HomeAssistantView):
    """Authenticated bounded history endpoint for the NILM workspace."""

    url = NILM_WORKSPACE_HISTORY_API_PATH
    name = f"api:{DOMAIN}:nilm_workspace_history"
    requires_auth = True

    async def get(self, request: Any) -> Any:
        """Return capped recorder history for NILM workspace charting."""
        from . import panel

        hass = request.app[panel.KEY_HASS]
        payload = await panel.nilm_workspace_history_payload(
            hass,
            panel._loaded_coordinators(hass),
            circuit_id=request.query.get("circuit_id"),
            hours=request.query.get("hours"),
            entry_id=request.query.get(panel.ATTR_ENTRY_ID),
        )
        return panel.web.json_response(payload)
