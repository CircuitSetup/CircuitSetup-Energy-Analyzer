export const EVIDENCE_API_PATH = "/api/circuitsetup_energy_analyzer/alert_evidence";
export const EVIDENCE_CALL_API_PATH = "circuitsetup_energy_analyzer/alert_evidence";
export const NILM_WORKSPACE_API_PATH = "/api/circuitsetup_energy_analyzer/nilm_workspace";
export const NILM_WORKSPACE_CALL_API_PATH = "circuitsetup_energy_analyzer/nilm_workspace";
export const APPLIANCE_DETAIL_API_PATH = "/api/circuitsetup_energy_analyzer/appliance_detail";
export const APPLIANCE_DETAIL_CALL_API_PATH = "circuitsetup_energy_analyzer/appliance_detail";
export const APPLIANCE_INSIGHTS_API_PATH = "/api/circuitsetup_energy_analyzer/appliance_insights";
export const APPLIANCE_INSIGHTS_CALL_API_PATH = "circuitsetup_energy_analyzer/appliance_insights";
export const SETUP_HEALTH_API_PATH = "/api/circuitsetup_energy_analyzer/setup_health";
export const SETUP_HEALTH_CALL_API_PATH = "circuitsetup_energy_analyzer/setup_health";
export const HISTORY_CALL_API_PREFIX = "history/period";
export const MAX_CHART_POINTS_PER_SERIES = 240;
export const NILM_LOW_CONFIDENCE_THRESHOLD = 0.8;
export const EXPAND_NILM_QUERY_PARAM = "include_all_nilm";
export const NILM_WORKSPACE_QUERY_PARAM = "nilm_workspace";
export const APPLIANCE_DETAIL_QUERY_PARAM = "appliance_detail";
export const APPLIANCE_INSIGHTS_QUERY_PARAM = "appliance_insights";
export const SETUP_HEALTH_QUERY_PARAM = "setup_health";
export const PANEL_URL_PATH = "circuitsetup-energy-analyzer-evidence";
export const REVIEW_SUGGESTED_SETTINGS_QUERY_PARAM = "review_suggested_settings";
export const LAST_ACTION_MESSAGE_STORAGE_KEY = "circuitsetupEnergyAnalyzerLastActionMessage";
export const ROUTE_CHANGE_EVENT = "circuitsetup-energy-analyzer-route-change";
export const ROUTE_CHANGE_INSTALL_KEY = "__circuitsetupEnergyAnalyzerRouteChangeInstalled";
export const NILM_EDGE_SNAP_MS = 5 * 60 * 1000;
export const ACTION_SERVICE_NAMES = {
  acknowledge: "acknowledge_alert",
  mark_expected: "mark_alert_expected",
  mark_confirmed: "mark_alert_confirmed",
  mark_unhelpful: "mark_alert_unhelpful",
  pause_alerts: "pause_alerts",
  relearn_baseline: "relearn_baseline",
  apply_setting_recommendation: "apply_setting_recommendation",
  dismiss_setting_recommendation: "dismiss_setting_recommendation",
  undo_setting_recommendation: "undo_setting_recommendation",
  reset_setting_recommendation: "reset_setting_recommendation",
};
export const CHART_COLORS = Array.from(
  { length: 32 },
  (_item, index) => `hsl(${(210 + index * 137.508) % 360} ${62 + index % 3 * 8}% ${42 + Math.floor(index / 3) % 3 * 8}%)`,
);
export const PANEL_METHOD_DEPENDENCIES = {
  APPLIANCE_DETAIL_API_PATH,
  APPLIANCE_DETAIL_CALL_API_PATH,
  APPLIANCE_INSIGHTS_API_PATH,
  APPLIANCE_INSIGHTS_CALL_API_PATH,
  SETUP_HEALTH_API_PATH,
  SETUP_HEALTH_CALL_API_PATH,
  NILM_WORKSPACE_API_PATH,
  NILM_WORKSPACE_CALL_API_PATH,
  HISTORY_CALL_API_PREFIX,
  MAX_CHART_POINTS_PER_SERIES,
  NILM_LOW_CONFIDENCE_THRESHOLD,
  EXPAND_NILM_QUERY_PARAM,
  NILM_WORKSPACE_QUERY_PARAM,
  APPLIANCE_DETAIL_QUERY_PARAM,
  APPLIANCE_INSIGHTS_QUERY_PARAM,
  SETUP_HEALTH_QUERY_PARAM,
  PANEL_URL_PATH,
  NILM_EDGE_SNAP_MS,
  CHART_COLORS,
};

function installRouteChangeDispatcher() {
  if (window[ROUTE_CHANGE_INSTALL_KEY]) {
    return;
  }
  window[ROUTE_CHANGE_INSTALL_KEY] = true;

  const dispatchRouteChange = () => {
    window.dispatchEvent(new Event(ROUTE_CHANGE_EVENT));
  };
  const originalPushState = history.pushState;
  const originalReplaceState = history.replaceState;

  history.pushState = function pushState(...args) {
    const result = originalPushState.apply(this, args);
    dispatchRouteChange();
    return result;
  };
  history.replaceState = function replaceState(...args) {
    const result = originalReplaceState.apply(this, args);
    dispatchRouteChange();
    return result;
  };
  window.addEventListener("popstate", dispatchRouteChange);
}

class CircuitSetupPanelComponent {
  constructor(host) {
    this.host = host;
  }
}

class CircuitSetupEvidenceSummary extends CircuitSetupPanelComponent {
  renderAlert(alert, circuit) {
    return this.host._renderAlertContent(alert, circuit);
  }

  renderFallbackActions() {
    return this.host._renderFallbackActionsContent();
  }
}

class CircuitSetupNilmWorkspace extends CircuitSetupPanelComponent {
  render() {
    return this.host._renderNilmWorkspaceContent();
  }
}

class CircuitSetupApplianceDetail extends CircuitSetupPanelComponent {
  render() {
    return this.host._renderApplianceDetailContent();
  }
}

class CircuitSetupApplianceInsights extends CircuitSetupPanelComponent {
  render() {
    return this.host._renderApplianceInsightsContent();
  }
}

class CircuitSetupSetupHealth extends CircuitSetupPanelComponent {
  render() {
    return this.host._renderSetupHealthContent();
  }
}

class CircuitSetupRecommendationCards extends CircuitSetupPanelComponent {
  renderSection(title, recommendationItems) {
    return this.host._renderRecommendationSectionContent(title, recommendationItems);
  }
}

class CircuitSetupEnergyAnalyzerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._evidenceSummary = new CircuitSetupEvidenceSummary(this);
    this._nilmWorkspaceComponent = new CircuitSetupNilmWorkspace(this);
    this._applianceDetailComponent = new CircuitSetupApplianceDetail(this);
    this._applianceInsightsComponent = new CircuitSetupApplianceInsights(this);
    this._setupHealthComponent = new CircuitSetupSetupHealth(this);
    this._recommendationCards = new CircuitSetupRecommendationCards(this);
    this._hass = null;
    this._payload = null;
    this._historySeries = [];
    this._nilmWorkspace = null;
    this._applianceDetail = null;
    this._applianceInsights = null;
    this._applianceInsights = null;
    this._applianceInsightsFilters = {
      running: false,
      needs_attention: false,
      nilm_estimated: false,
      learning: false,
      data_problem: false,
    };
    this._applianceInsightsSort = "default";
    this._applianceDetailHistorySeries = [];
    this._applianceDetailChartSeries = [];
    this._applianceDetailHistoryParsed = false;
    this._applianceDetailHistoryHours = 0;
    this._applianceDetailHistoryBounds = null;
    this._applianceDetailHistoryWindow = null;
    this._sumpDriverAnalysis = null;
    this._sumpDriverHistoryLoading = false;
    this._sumpDriverHistoryError = "";
    this._sumpDriverHiddenLayers = new Set();
    this._setupHealth = null;
    this._nilmWorkspaceHistorySeries = [];
    this._loading = true;
    this._historyLoading = false;
    this._nilmWorkspaceLoading = false;
    this._nilmWorkspaceHistoryLoading = false;
    this._applianceDetailLoading = false;
    this._applianceInsightsLoading = false;
    this._applianceDetailHistoryLoading = false;
    this._setupHealthLoading = false;
    this._error = "";
    this._historyError = "";
    this._nilmWorkspaceError = "";
    this._nilmWorkspaceHistoryError = "";
    this._nilmWorkspaceHistoryFailedRequest = null;
    this._applianceDetailError = "";
    this._applianceInsightsError = "";
    this._applianceInsightsLoading = false;
    this._applianceInsightsError = "";
    this._applianceDetailHistoryError = "";
    this._setupHealthError = "";
    this._busyAction = "";
    this._lastActionMessage = "";
    this._alertDecision = "";
    this._inlineFeedback = { scope: "", kind: "", message: "" };
    this._pendingConfirmationAction = "";
    this._loadedRouteKey = "";
    this._evidenceRequestId = 0;
    this._nilmWorkspaceMutationId = 0;
    this._nilmWorkspaceRefreshCycle = null;
    this._nilmFocusedHistoryToken = 0;
    this._listeningForRouteChanges = false;
    this._nilmLabelDrafts = new Map();
    this._nilmDecisionDrafts = new Map();
    this._nilmSessionLabelDrafts = new Map();
    this._nilmAssignmentDrafts = new Map();
    this._nilmOverlayVisibility = { known_load: true, solar: true };
    this._nilmFocusedSignature = "";
    this._nilmActiveLane = "needs_review";
    this._nilmSelectedReviewKey = "";
    this._nilmGraphWindow = null;
    this._nilmIntervalEditorOpen = false;
    this._nilmLabelIntervalDraft = this._emptyNilmLabelIntervalDraft();
    this._nilmActiveIntervalIndex = 0;
    this._nilmIntervalFailedAction = "";
    this._nilmIntervalFailedIndex = -1;
    this._nilmIntervalRefreshSuccessMessage = "";
    this._handleRouteChange = () => this._loadEvidenceIfRouteChanged();
  }

  set hass(hass) {
    this._hass = hass;
    if (this.isConnected) {
      this._loadEvidenceIfRouteChanged();
    }
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    installRouteChangeDispatcher();
    this._restoreStoredActionMessage();
    this._addRouteListeners();
    const recoveredHass = this._upgradeProperty("hass");
    this._upgradeProperty("panel");
    if (!recoveredHass && this._hass && this._hass.callApi) {
      this._loadEvidenceIfRouteChanged({ force: true });
    }
  }

  _upgradeProperty(name) {
    if (!Object.prototype.hasOwnProperty.call(this, name)) {
      return false;
    }
    const value = this[name];
    delete this[name];
    this[name] = value;
    return true;
  }

  disconnectedCallback() {
    this._removeRouteListeners();
  }

  _addRouteListeners() {
    if (this._listeningForRouteChanges) {
      return;
    }
    window.addEventListener(ROUTE_CHANGE_EVENT, this._handleRouteChange);
    window.addEventListener("location-changed", this._handleRouteChange);
    this._listeningForRouteChanges = true;
  }

  _removeRouteListeners() {
    if (!this._listeningForRouteChanges) {
      return;
    }
    window.removeEventListener(ROUTE_CHANGE_EVENT, this._handleRouteChange);
    window.removeEventListener("location-changed", this._handleRouteChange);
    this._listeningForRouteChanges = false;
  }

  _loadEvidenceIfRouteChanged(options = {}) {
    const routeKey = this._routeKey();
    if (!options.force && routeKey === this._loadedRouteKey) {
      return;
    }
    if (this._loadedRouteKey && routeKey !== this._loadedRouteKey) {
      this._lastActionMessage = "";
      this._alertDecision = "";
      this._inlineFeedback = { scope: "", kind: "", message: "" };
    }
    this._loadEvidence({ routeKey });
  }

  async _loadEvidence(options = {}) {
    const routeKey = options.routeKey || this._routeKey();
    const routeChanged = options.routeChanged
      ?? Boolean(this._loadedRouteKey && routeKey !== this._loadedRouteKey);
    const requestId = this._evidenceRequestId + 1;
    this._evidenceRequestId = requestId;
    this._invalidateNilmFocusedHistoryRequests();
    if (routeChanged) {
      this._busyAction = "";
      this._historyLoading = false;
      this._nilmActiveLane = "needs_review";
      this._nilmSelectedReviewKey = "";
    }
    this._loadedRouteKey = routeKey;
    this._loading = true;
    this._error = "";
    this._historyError = "";
    this._historySeries = [];
    this._nilmWorkspaceHistoryLoading = false;
    this._nilmWorkspace = null;
    this._applianceDetail = null;
    this._applianceDetailHistorySeries = [];
    this._applianceDetailHistoryHours = 0;
    this._applianceDetailHistoryBounds = null;
    this._applianceDetailHistoryWindow = null;
    this._sumpDriverAnalysis = null;
    this._sumpDriverHistoryLoading = false;
    this._sumpDriverHistoryError = "";
    this._sumpDriverHiddenLayers.clear();
    this._setupHealth = null;
    this._nilmWorkspaceError = "";
    this._nilmWorkspaceHistoryError = "";
    this._nilmWorkspaceHistoryFailedRequest = null;
    this._applianceDetailError = "";
    this._applianceDetailHistoryError = "";
    this._applianceDetailHistoryLoading = false;
    this._setupHealthError = "";
    this._setupHealthLoading = false;
    this._nilmWorkspaceHistorySeries = [];
    this._nilmLabelDrafts.clear();
    this._nilmDecisionDrafts.clear();
    this._nilmSessionLabelDrafts.clear();
    this._nilmAssignmentDrafts.clear();
    this._nilmFocusedSignature = "";
    this._nilmGraphWindow = null;
    this._nilmIntervalEditorOpen = false;
    this._nilmLabelIntervalDraft = this._emptyNilmLabelIntervalDraft();
    this._nilmActiveIntervalIndex = 0;
    this._nilmIntervalFailedAction = "";
    this._nilmIntervalFailedIndex = -1;
    this._nilmIntervalRefreshSuccessMessage = "";
    this._render();

    const routeUrl = new URL(routeKey, window.location.origin);
    const params = routeUrl.searchParams;
    const query = params.toString();
    const apiPath = `${EVIDENCE_CALL_API_PATH}${query ? `?${query}` : ""}`;
    const fetchPath = `${EVIDENCE_API_PATH}${query ? `?${query}` : ""}`;

    try {
      const payload = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._payload = payload;
      this._loading = false;
      this._render();
      if (this._routeRequestsApplianceDetail(routeKey)) {
        await this._loadApplianceDetail(requestId, routeKey);
      }
      if (this._routeRequestsApplianceInsights(routeKey)) {
        await this._loadApplianceInsights(requestId, routeKey);
      }
      if (this._routeRequestsSetupHealth(routeKey)) {
        await this._loadSetupHealth(requestId, routeKey);
      }
      const historySource = this._evidenceHistorySource();
      if (historySource) {
        await this._loadHistory(historySource, requestId, routeKey);
      }
      if (this._routeRequestsNilmWorkspace(routeKey)) {
        await this._loadNilmWorkspace(requestId, routeKey);
      }
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._payload = null;
      this._error = this._panelTextFormat("errors.load_alert_evidence", { path: fetchPath, message: error.message });
      this._loading = false;
      this._render();
    }
  }

  async _requestJson(apiPath, fetchPath) {
    if (this._hass && this._hass.callApi) {
      return this._hass.callApi("GET", apiPath);
    }
    throw new Error(`Home Assistant API is not ready for ${fetchPath}`);
  }

  async _postJson(apiPath, fetchPath, body) {
    if (this._hass && this._hass.callApi) {
      return this._hass.callApi("POST", apiPath, body);
    }
    throw new Error(`Home Assistant API is not ready for ${fetchPath}`);
  }

  _openOptionsFlow(action) {
    if (action && action.path) {
      this._navigate(action.path);
    }
    return Promise.resolve();
  }

  _openOptionsPath(path) {
    const url = new URL(path, window.location.origin);
    const params = new URLSearchParams(url.hash.replace(/^#/, ""));
    const entryId = params.get("config_entry");
    const optionsStep = params.get("options_step");
    if (entryId && optionsStep) {
      return this._openOptionsFlow({
        entry_id: entryId,
        circuit_id: params.get("circuit_id") || "",
        options_step: optionsStep,
        path,
      });
    }
    this._navigate(path);
    return Promise.resolve();
  }

  _requestActionConfirmation(actionKey) {
    this._pendingConfirmationAction = actionKey;
    this._render();
  }

  _cancelActionConfirmation() {
    this._pendingConfirmationAction = "";
    this._render();
  }

  _confirmPendingAction() {
    const actionKey = this._pendingConfirmationAction;
    this._pendingConfirmationAction = "";
    this._render();
    if (actionKey) {
      return this._callAction(actionKey);
    }
    return Promise.resolve();
  }

  _renderActionConfirmation() {
    if (this._pendingConfirmationAction !== "relearn_baseline") {
      return "";
    }
    return `
      <ha-dialog open heading="${this._escape(this._panelText("confirmations.relearn_title"))}">
        <p>${this._escape(this._panelText("confirmations.relearn_message"))}</p>
        <mwc-button slot="secondaryAction" id="cancel_action_confirmation">${this._escape(this._panelText("confirmations.cancel"))}</mwc-button>
        <mwc-button slot="primaryAction" id="confirm_action">${this._escape(this._panelText("confirmations.confirm_relearn"))}</mwc-button>
      </ha-dialog>
    `;
  }

  async _callAction(actionKey, options = {}) {
    const payloadActions = this._payload && this._payload.actions;
    const fallbackAlert = this._payload && this._payload.alert;
    const action = (payloadActions && payloadActions[actionKey]) || {
      service: ACTION_SERVICE_NAMES[actionKey],
      data: { alert_id: fallbackAlert && fallbackAlert.alert_id },
    };
    if (!this._guardActionCall(action, actionKey, options.feedbackScope)) {
      return;
    }
    if (action.entry_id && action.options_step) {
      await this._openOptionsFlow(action);
      return;
    }
    if (action.path) {
      this._navigate(action.path);
      return;
    }
    const actionContext = this._actionContext();
    this._busyAction = actionKey;
    if (options.feedbackScope && this._inlineFeedback.scope === options.feedbackScope) {
      this._inlineFeedback = { scope: "", kind: "", message: "" };
    }
    this._render();
    try {
      if (action.domain) {
        await this._hass.callService(action.domain, action.service, action.data || {});
      } else {
        await this._hass.callService("circuitsetup_energy_analyzer", action.service, action.data || {});
      }
      if (!actionContext.isCurrent()) {
        return;
      }
      const message = this._alertActionMessage(actionKey);
      this._busyAction = "";
      const routeKey = this._actionRefreshRouteKey(actionKey);
      const routeChanged = routeKey !== this._routeKey();
      if (routeChanged) {
        // Prevent the route dispatcher from starting a duplicate refresh.
        this._loadedRouteKey = routeKey;
        history.replaceState(history.state, "", routeKey);
      }
      const refresh = this._loadEvidence({ routeKey, routeChanged });
      const refreshRequestId = this._evidenceRequestId;
      await refresh;
      if (!this._isCurrentRequest(refreshRequestId, routeKey)) {
        return;
      }
      if (options.feedbackScope) {
        this._alertDecision = "";
        this._setInlineFeedback(options.feedbackScope, "success", message);
      } else {
        this._lastActionMessage = message;
        this._render();
        this._scrollToTop();
      }
    } catch (error) {
      if (!actionContext.isCurrent()) {
        return;
      }
      const message = this._panelTextFormat("errors.run_service", { service: action.service, message: error.message });
      this._busyAction = "";
      if (options.feedbackScope) {
        this._setInlineFeedback(options.feedbackScope, "error", message);
      } else {
        this._error = message;
        this._renderAndScrollToTop();
      }
    }
  }

  _setInlineFeedback(scope, kind, message) {
    this._inlineFeedback = { scope, kind, message };
    this._render();
    requestAnimationFrame(() => {
      const target = this.shadowRoot.querySelector(`[data-inline-feedback="${scope}"]`);
      if (target && typeof target.focus === "function") {
        target.focus({ preventScroll: true });
      }
    });
  }

  _renderInlineFeedback(scope) {
    const feedback = this._inlineFeedback;
    if (!feedback || feedback.scope !== scope || !feedback.message) {
      return "";
    }
    return `<p class="inline-feedback ${this._escape(feedback.kind)}" data-inline-feedback="${this._escape(scope)}" tabindex="-1" role="status" aria-live="polite">${this._escape(feedback.message)}</p>`;
  }

  _navigate(path) {
    if (!path) {
      return;
    }
    if (String(path).startsWith("/config/")) {
      window.location.assign(path);
      return;
    }
    history.pushState(null, "", path);
    window.dispatchEvent(
      new CustomEvent("location-changed", {
        detail: { replace: false },
        bubbles: true,
        composed: true,
      })
    );
    this._scrollToTop();
  }

  _guardActionCall(action, label, feedbackScope = "") {
    const reject = (message) => {
      if (feedbackScope) {
        this._setInlineFeedback(feedbackScope, "error", message);
      } else {
        this._error = message;
        this._renderAndScrollToTop();
      }
      return false;
    };
    if (!action) {
      return reject(this._panelTextFormat("errors.action_unavailable", { label }));
    }
    if (action.enabled === false) {
      return reject(action.unavailable_label || this._panelTextFormat("errors.action_unavailable_reason", { reason: action.unavailable_reason || label }));
    }
    if (action.path) {
      return true;
    }
    if (!action.service) {
      return reject(this._panelTextFormat("errors.action_service_missing", { label }));
    }
    if (!this._hass || !this._hass.callService) {
      return reject(this._panelText("errors.service_calls_unavailable"));
    }
    return true;
  }

  _renderAndScrollToTop() {
    this._render();
    this._scrollToTop();
  }

  _storeActionMessageForReload(message) {
    try {
      sessionStorage.setItem(LAST_ACTION_MESSAGE_STORAGE_KEY, message);
    } catch (_error) {
      // Storage can be unavailable in hardened browser sessions.
    }
  }

  _restoreStoredActionMessage() {
    try {
      const message = sessionStorage.getItem(LAST_ACTION_MESSAGE_STORAGE_KEY);
      if (message) {
        this._lastActionMessage = message;
        sessionStorage.removeItem(LAST_ACTION_MESSAGE_STORAGE_KEY);
      }
    } catch (_error) {
      // Storage can be unavailable in hardened browser sessions.
    }
  }

  _scrollToTop() {
    requestAnimationFrame(() => {
      this.scrollIntoView({ block: "start" });
      if (typeof window.scrollTo === "function") {
        window.scrollTo({ top: 0, behavior: "smooth" });
      }
    });
  }

  _routeKey() {
    return `${window.location.pathname}${window.location.search}`;
  }

  _routeRequestsSuggestedSettings(routeKey = this._routeKey()) {
    const routeUrl = new URL(routeKey, window.location.origin);
    return routeUrl.searchParams.get(REVIEW_SUGGESTED_SETTINGS_QUERY_PARAM) === "1";
  }

  _actionRefreshRouteKey(actionKey) {
    const routeUrl = new URL(this._routeKey(), window.location.origin);
    const alert = this._payload && this._payload.alert;
    const circuit = this._payload && this._payload.circuit;
    const circuitId = (alert && alert.circuit_id)
      || (circuit && circuit.circuit_id)
      || routeUrl.searchParams.get("circuit_id");
    const feature = (alert && alert.feature)
      || (this._payload && this._payload.requested_feature)
      || routeUrl.searchParams.get("feature");
    routeUrl.searchParams.delete("alert_id");
    if (circuitId) {
      routeUrl.searchParams.set("circuit_id", circuitId);
    }
    if (feature) {
      routeUrl.searchParams.set("feature", feature);
    }
    return `${routeUrl.pathname}${routeUrl.search}`;
  }

  _isCurrentRequest(requestId, routeKey) {
    return requestId === this._evidenceRequestId && routeKey === this._routeKey();
  }

  _actionContext() {
    const requestId = this._evidenceRequestId;
    const routeKey = this._routeKey();
    return {
      requestId,
      routeKey,
      isCurrent: () => this._isCurrentRequest(requestId, routeKey),
    };
  }

  _descendingNullableSortNumber(left, right) {
    const leftNumber = Number(left);
    const rightNumber = Number(right);
    const leftValid = left !== null && left !== undefined && Number.isFinite(leftNumber);
    const rightValid = right !== null && right !== undefined && Number.isFinite(rightNumber);
    if (!leftValid) return rightValid ? 1 : 0;
    if (!rightValid) return -1;
    return rightNumber - leftNumber;
  }

  _renderSuggestedSettingsBody() {
    return this._renderRecommendations() || `<section class="panel"><p class="muted">${this._escape(this._panelText("recommendations.no_suggested_settings"))}</p></section>`;
  }

  _evidenceText(path) {
    return this._panelText(`evidence.${path}`);
  }

  _panelText(path) {
    const parts = path.split(".");
    let value = this._panelTextObject();
    for (const part of parts) {
      if (!value || typeof value !== "object") {
        return "";
      }
      value = value[part];
    }
    return typeof value === "string" ? value : "";
  }

  _panelTextFormat(path, values = {}) {
    return this._panelText(path).replace(/\{([^}]+)\}/g, (_match, key) => (
      values[key] !== undefined && values[key] !== null ? String(values[key]) : ""
    ));
  }

  _panelTextObject() {
    const sources = [
      this._payload && this._payload.text,
      this._panel && this._panel.config && this._panel.config.text,
      this._dashboardConfig && this._dashboardConfig.text,
    ];
    for (const text of sources) {
      if (!text || typeof text !== "object") {
        continue;
      }
      if (text.evidence || text.common || text.headers) {
        return text;
      }
      if (text.fallbacks || text.actions) {
        return { evidence: text };
      }
    }
    return {};
  }

  _renderSimpleList(items, emptyText) {
    const safeItems = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!safeItems.length) {
      return emptyText ? `<p class="muted">${this._escape(emptyText)}</p>` : "";
    }
    return `<ul>${safeItems.map((item) => `<li>${this._escape(item)}</li>`).join("")}</ul>`;
  }

  _renderSettingImpactPreview(recommendation) {
    const preview = recommendation && recommendation.impact_preview;
    if (!preview || preview.available === false || Number(preview.observations_evaluated || 0) <= 0) {
      return "";
    }
    const stateChanges = preview.current_state_change_count !== null && preview.current_state_change_count !== undefined;
    const currentCount = stateChanges ? preview.current_state_change_count : preview.current_alert_count;
    const candidateCount = stateChanges ? preview.candidate_state_change_count : preview.candidate_alert_count;
    const countLabel = stateChanges
      ? this._panelText("recommendations.preview_state_changes")
      : this._panelText("recommendations.preview_alerts");
    const window = Number(preview.observations_evaluated || 0) > 0
      ? `<p>${this._escape(this._panelTextFormat("recommendations.preview_window", {
        count: preview.observations_evaluated,
        start: this._formatDateTime(new Date(preview.history_start)),
        end: this._formatDateTime(new Date(preview.history_end)),
      }))}</p>`
      : "";
    const examples = [
      preview.examples_removed && preview.examples_removed.length
        ? `<p>${this._escape(this._panelTextFormat("recommendations.preview_removed", { examples: preview.examples_removed.join(", ") }))}</p>`
        : "",
      preview.examples_added && preview.examples_added.length
        ? `<p>${this._escape(this._panelTextFormat("recommendations.preview_added", { examples: preview.examples_added.join(", ") }))}</p>`
        : "",
    ].join("");
    const limitations = Array.isArray(preview.limitations) && preview.limitations.length
      ? `<div class="recommendation-support-row" data-recommendation-support="limitations">
          <strong>${this._escape(this._panelText("recommendations.preview_limitations"))}:</strong>
          <span class="recommendation-support-copy">${this._escape(preview.limitations.join(" "))}</span>
        </div>`
      : "";
    return `<div class="setting-impact-preview">
        <div class="recommendation-support-row" data-recommendation-support="historical-impact">
          <strong>${this._escape(this._panelText("recommendations.preview_history"))}</strong>
          <div class="recommendation-support-copy">
            ${window}
            <p>${this._escape(this._panelTextFormat("recommendations.preview_count", { label: this._panelText("common.current"), count: currentCount, metric: countLabel }))}</p>
            <p>${this._escape(this._panelTextFormat("recommendations.preview_count", { label: this._panelText("common.suggested"), count: candidateCount, metric: countLabel }))}</p>
            ${examples}
          </div>
        </div>
        ${limitations}
    </div>`;
  }

  _overlayEntitySummary(item) {
    const count = (item.entity_ids || []).filter((entityId) => String(entityId || "").trim()).length;
    return count === 1
      ? this._panelTextFormat("nilm_workspace.sensor_count", { count, noun: this._panelText("common.sensor") })
      : this._panelTextFormat("nilm_workspace.sensor_count", { count, noun: this._panelText("common.sensors") });
  }

  _formatAxisTime(value, includeDate = false) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    try {
      return new Intl.DateTimeFormat(undefined, {
        timeZone: this._timeZone(),
        ...(includeDate ? { month: "short", day: "numeric" } : {}),
        hour: "numeric",
        minute: "2-digit",
      }).format(date);
    } catch (_error) {
      return this._formatDateTime(value);
    }
  }

  _listen(selector, handler) {
    const element = this.shadowRoot.querySelector(selector);
    if (element) {
      element.addEventListener("click", handler);
    }
  }

  _statusText(status) {
    if (status === "matched_alert") {
      return this._panelText("status.matched_alert");
    }
    if (status === "latest_for_circuit") {
      return this._panelText("status.latest_for_circuit");
    }
    if (status === "circuit_found_no_evidence") {
      return this._panelText("status.circuit_found_no_evidence");
    }
    return this._panelText("status.not_found");
  }

  _metric(label, value, icon = "") {
    const heading = icon
      ? `<span class="metric-heading"><ha-icon icon="${this._escape(icon)}"></ha-icon>${this._escape(label)}</span>`
      : `<span>${this._escape(label)}</span>`;
    return `<div class="metric">${heading}<strong>${this._escape(this._formatMetricValue(value))}</strong></div>`;
  }

  _finiteMetricValue(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  _renderActionGroup(title, description, buttons) {
    const renderedButtons = buttons.filter(Boolean);
    if (!renderedButtons.length) {
      return "";
    }
    return `
      <div class="action-group">
        <h3>${this._escape(title)}</h3>
        <p class="muted">${this._escape(description)}</p>
        <div class="actions">${renderedButtons.join("")}</div>
      </div>
    `;
  }

  _actionButton(actionKey, label, secondary = false, helperText = "") {
    const actions = this._payload && this._payload.actions;
    const action = actions && actions[actionKey];
    if (!action) {
      return "";
    }
    const reason = action.unavailable_label || action.unavailable_reason || "";
    const hintText = reason || helperText;
    const title = reason ? ` title="${this._escape(reason)}"` : "";
    const hint = hintText ? `<span class="action-reason">${this._escape(hintText)}</span>` : "";
    const icon = action.icon ? `<ha-icon icon="${this._escape(action.icon)}"></ha-icon>` : "";
    return `<span class="action-item"><button id="${actionKey}" class="${secondary ? "secondary" : ""}"${title} ${this._actionDisabled(actionKey, action)}>${icon}${this._escape(action.label || label)}</button>${hint}</span>`;
  }

  _changeSummary(alert) {
    if (alert.percent_change !== null && alert.percent_change !== undefined) {
      return this._panelTextFormat("chart.changed_by", { feature: alert.feature_name || this._friendlyFeature(alert.feature), percent: alert.percent_change });
    }
    const metrics = alert.contributing_metrics || {};
    const keys = Object.keys(metrics);
    if (keys.length) {
      return this._panelTextFormat("chart.changed_metrics", { metrics: keys.join(", ") });
    }
    return alert.what_happened || alert.message || this._panelText("chart.change_fallback");
  }

  _disabled(actionKey) {
    return this._busyAction === actionKey ? "disabled" : "";
  }

  _actionDisabled(actionKey, action) {
    return this._busyAction === actionKey || (action && action.enabled === false) ? "disabled" : "";
  }

  _formatPower(value) {
    return value === null || value === undefined ? this._panelText("common.unknown") : `${this._formatNumber(value)} W`;
  }

  _formatKwh(value) {
    return value === null || value === undefined ? this._panelText("common.unknown") : `${this._formatNumber(value)} kWh`;
  }

  _formatCost(value) {
    if (value === null || value === undefined) {
      return this._panelText("common.cost_unavailable") || "Cost unavailable";
    }
    const cost = Number(value);
    if (!Number.isFinite(cost)) {
      return this._panelText("common.unknown");
    }
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: this._currencyCode(),
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(cost);
  }

  _currencyCode() {
    return this._hass && this._hass.config && this._hass.config.currency
      ? String(this._hass.config.currency)
      : "USD";
  }

  _currencySymbol() {
    const part = new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: this._currencyCode(),
      currencyDisplay: "narrowSymbol",
    }).formatToParts(0).find((item) => item.type === "currency");
    return part ? part.value : this._currencyCode();
  }

  _formatDuration(value) {
    if (value === null || value === undefined) {
      return this._panelText("common.unknown");
    }
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) {
      return this._panelText("common.unknown");
    }
    const wholeSeconds = Math.max(0, Math.round(seconds));
    const hours = Math.floor(wholeSeconds / 3600);
    const minutes = Math.floor((wholeSeconds % 3600) / 60);
    const remainingSeconds = wholeSeconds % 60;
    return [
      hours ? `${hours}h` : "",
      minutes ? `${minutes}m` : "",
      remainingSeconds || (!hours && !minutes) ? `${remainingSeconds}s` : "",
    ].filter(Boolean).join(" ");
  }

  _formatConfidence(value) {
    const confidence = Number(value);
    if (!Number.isFinite(confidence)) {
      return this._panelText("common.unknown");
    }
    const normalized = confidence <= 1 ? confidence * 100 : confidence;
    return `${Math.round(normalized)}%`;
  }

  _formatChangePercent(value) {
    const number = Number(value);
    if (value === null || value === undefined || !Number.isFinite(number)) {
      return this._panelText("common.unknown");
    }
    const prefix = number > 0 ? "+" : "";
    return `${prefix}${this._formatNumber(number)}%`;
  }

  _formatComparisonValue(comparison, value) {
    if (value === null || value === undefined) {
      return this._panelText("common.unknown");
    }
    const unit = comparison && comparison.unit ? String(comparison.unit) : "";
    if (unit === "currency") {
      return this._formatCost(value);
    }
    if (unit === "%") {
      return `${this._formatNumber(value)}%`;
    }
    if (unit === "s") {
      return this._formatDuration(value);
    }
    return `${this._formatNumber(value)}${unit ? ` ${unit}` : ""}`;
  }

  _sourceLabel(sourceType) {
    const labels = {
      direct_meter: this._panelText("source_labels.direct_meter"),
      nilm_estimate: this._panelText("source_labels.nilm_estimate"),
      mixed: this._panelText("source_labels.mixed"),
      mains: this._panelText("source_labels.mains"),
      unknown: this._panelText("source_labels.unknown"),
    };
    return labels[sourceType] || this._panelText("common.unknown");
  }

  _formatNumber(value) {
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  _formatMetricValue(value) {
    if (value === null || value === undefined || value === "") {
      return this._panelText("common.unknown");
    }
    if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
      return this._formatDateTime(value);
    }
    return value;
  }

  _datetimeLocalToIso(value) {
    const raw = String(value || "").trim();
    if (!raw) {
      return "";
    }
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    return date.toISOString();
  }

  _datetimeLocalFromMillis(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "";
    }
    const local = new Date(date.getTime() - (date.getTimezoneOffset() * 60000));
    return local.toISOString().slice(0, 16);
  }

  _formatDateTime(value) {
    if (value === null || value === undefined || value === "") {
      return this._panelText("common.unknown");
    }
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    try {
      const parts = Object.fromEntries(
        new Intl.DateTimeFormat(undefined, {
          timeZone: this._timeZone(),
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "numeric",
          minute: "2-digit",
          hour12: true,
        }).formatToParts(date).map((part) => [part.type, part.value]),
      );
      return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}${String(parts.dayPeriod || "").toUpperCase()}`;
    } catch (_error) {
      const year = String(date.getFullYear());
      const month = String(date.getMonth() + 1).padStart(2, "0");
      const day = String(date.getDate()).padStart(2, "0");
      const minute = String(date.getMinutes()).padStart(2, "0");
      return this._formatDateParts(year, month, day, date.getHours(), minute);
    }
  }

  _timeZone() {
    return (
      (this._hass && this._hass.config && this._hass.config.time_zone)
      || Intl.DateTimeFormat().resolvedOptions().timeZone
      || this._panelText("common.local_time")
    );
  }

  _formatDateParts(year, month, day, hour, minute) {
    const suffix = hour >= 12 ? "PM" : "AM";
    const hour12 = hour % 12 || 12;
    return `${year}-${month}-${day} ${hour12}:${minute}${suffix}`;
  }

  _friendlyFeature(value) {
    const raw = String(value || "").trim();
    if (!raw) {
      return this._panelText("feature_labels.alert");
    }
    const labels = {
      hvac: this._panelText("feature_labels.hvac"),
      kwh: this._panelText("feature_labels.kwh"),
      nilm: this._panelText("feature_labels.nilm"),
      pf: this._panelText("feature_labels.pf"),
      s: this._panelText("feature_labels.s"),
      va: this._panelText("feature_labels.va"),
      var: this._panelText("feature_labels.var"),
    };
    return raw.split(/[_-]+/)
      .filter((token) => token)
      .map((token) => labels[token.toLowerCase()] || token.charAt(0).toUpperCase() + token.slice(1).toLowerCase())
      .join(" ") || this._panelText("feature_labels.alert");
  }

  _escape(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
}

export function registerEnergyAnalyzerPanel(registerDashboardGraphs, methodGroups = []) {
  for (const MethodGroup of methodGroups) {
    for (const name of Object.getOwnPropertyNames(MethodGroup.prototype)) {
      if (name !== "constructor") {
        Object.defineProperty(
          CircuitSetupEnergyAnalyzerPanel.prototype,
          name,
          Object.getOwnPropertyDescriptor(MethodGroup.prototype, name),
        );
      }
    }
  }
  if (!customElements.get("circuitsetup-energy-analyzer-panel")) {
    customElements.define("circuitsetup-energy-analyzer-panel", CircuitSetupEnergyAnalyzerPanel);
  }
  const DashboardGraphs = registerDashboardGraphs(CircuitSetupEnergyAnalyzerPanel);
  return {
    CircuitSetupEnergyAnalyzerPanel,
    CircuitSetupEnergyAnalyzerDashboardGraphs: DashboardGraphs,
  };
}
