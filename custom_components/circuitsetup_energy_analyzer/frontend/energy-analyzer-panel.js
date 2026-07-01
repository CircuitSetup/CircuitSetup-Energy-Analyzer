const EVIDENCE_API_PATH = "/api/circuitsetup_energy_analyzer/alert_evidence";
const EVIDENCE_CALL_API_PATH = "circuitsetup_energy_analyzer/alert_evidence";
const NILM_WORKSPACE_API_PATH = "/api/circuitsetup_energy_analyzer/nilm_workspace";
const NILM_WORKSPACE_CALL_API_PATH = "circuitsetup_energy_analyzer/nilm_workspace";
const APPLIANCE_DETAIL_API_PATH = "/api/circuitsetup_energy_analyzer/appliance_detail";
const APPLIANCE_DETAIL_CALL_API_PATH = "circuitsetup_energy_analyzer/appliance_detail";
const SETUP_HEALTH_API_PATH = "/api/circuitsetup_energy_analyzer/setup_health";
const SETUP_HEALTH_CALL_API_PATH = "circuitsetup_energy_analyzer/setup_health";
const HISTORY_CALL_API_PREFIX = "history/period";
const MAX_CHART_POINTS_PER_SERIES = 240;
const NILM_LOW_CONFIDENCE_THRESHOLD = 0.8;
const EXPAND_NILM_QUERY_PARAM = "include_all_nilm";
const NILM_WORKSPACE_QUERY_PARAM = "nilm_workspace";
const APPLIANCE_DETAIL_QUERY_PARAM = "appliance_detail";
const SETUP_HEALTH_QUERY_PARAM = "setup_health";
const ROUTE_CHANGE_EVENT = "circuitsetup-energy-analyzer-route-change";
const ROUTE_CHANGE_INSTALL_KEY = "__circuitsetupEnergyAnalyzerRouteChangeInstalled";
const NILM_EDGE_SNAP_MS = 5 * 60 * 1000;
const ACTION_SERVICE_NAMES = {
  acknowledge: "acknowledge_alert",
  mark_expected: "mark_alert_expected",
  mark_unhelpful: "mark_alert_unhelpful",
  pause_alerts: "pause_alerts",
  relearn_baseline: "relearn_baseline",
  apply_setting_recommendation: "apply_setting_recommendation",
  dismiss_setting_recommendation: "dismiss_setting_recommendation",
  undo_setting_recommendation: "undo_setting_recommendation",
  reset_setting_recommendation: "reset_setting_recommendation",
};
const CHART_COLORS = ["#0b6bcb", "#d97706", "#15803d", "#be123c", "#7c3aed", "#0f766e"];

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
    this._setupHealthComponent = new CircuitSetupSetupHealth(this);
    this._recommendationCards = new CircuitSetupRecommendationCards(this);
    this._hass = null;
    this._payload = null;
    this._historySeries = [];
    this._nilmWorkspace = null;
    this._applianceDetail = null;
    this._setupHealth = null;
    this._nilmWorkspaceHistorySeries = [];
    this._loading = true;
    this._historyLoading = false;
    this._nilmWorkspaceLoading = false;
    this._applianceDetailLoading = false;
    this._setupHealthLoading = false;
    this._error = "";
    this._historyError = "";
    this._nilmWorkspaceError = "";
    this._applianceDetailError = "";
    this._setupHealthError = "";
    this._busyAction = "";
    this._lastActionMessage = "";
    this._loadedRouteKey = "";
    this._evidenceRequestId = 0;
    this._listeningForRouteChanges = false;
    this._nilmLabelDrafts = new Map();
    this._nilmSessionLabelDrafts = new Map();
    this._nilmAssignmentDrafts = new Map();
    this._nilmOverlayVisibility = { known_load: true, solar: true };
    this._nilmFocusedSignature = "";
    this._nilmGraphWindow = null;
    this._nilmLabelIntervalDraft = { start: "", end: "", label: "", appliance_id: "", ground_truth_entity_id: "" };
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
    this._addRouteListeners();
    this._loadEvidenceIfRouteChanged({ force: true });
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
    this._loadEvidence({ routeKey });
  }

  async _loadEvidence(options = {}) {
    const routeKey = options.routeKey || this._routeKey();
    const requestId = this._evidenceRequestId + 1;
    this._evidenceRequestId = requestId;
    this._loadedRouteKey = routeKey;
    this._loading = true;
    this._error = "";
    this._historyError = "";
    this._historySeries = [];
    this._nilmWorkspace = null;
    this._applianceDetail = null;
    this._setupHealth = null;
    this._nilmWorkspaceError = "";
    this._applianceDetailError = "";
    this._setupHealthError = "";
    this._setupHealthLoading = false;
    this._nilmWorkspaceHistorySeries = [];
    this._nilmLabelDrafts.clear();
    this._nilmSessionLabelDrafts.clear();
    this._nilmAssignmentDrafts.clear();
    this._nilmFocusedSignature = "";
    this._nilmGraphWindow = null;
    this._nilmLabelIntervalDraft = { start: "", end: "", label: "", appliance_id: "", ground_truth_entity_id: "" };
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
      if (this._routeRequestsSetupHealth(routeKey)) {
        await this._loadSetupHealth(requestId, routeKey);
      }
      const alert = this._payload && this._payload.alert;
      if (alert && alert.graph_entities && alert.graph_entities.length) {
        await this._loadHistory(alert, requestId, routeKey);
      }
      await this._loadNilmWorkspace(requestId, routeKey);
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._payload = null;
      this._error = `Could not load alert evidence from ${fetchPath}: ${error.message}`;
      this._loading = false;
      this._render();
    }
  }

  async _loadHistory(alert, requestId = this._evidenceRequestId, routeKey = this._loadedRouteKey) {
    this._historyLoading = true;
    this._historyError = "";
    this._historySeries = [];
    this._render();

    const apiPath = this._historyApiPath(alert);
    const fetchPath = `/api/${apiPath}`;
    try {
      const history = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._historySeries = Array.isArray(history) ? history : [];
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._historyError = `Could not load history samples from ${fetchPath}: ${error.message}`;
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._historyLoading = false;
        this._render();
      }
    }
  }

  async _loadNilmWorkspace(requestId = this._evidenceRequestId, routeKey = this._loadedRouteKey) {
    const nilm = this._payload && this._payload.nilm;
    const routeUrl = new URL(routeKey, window.location.origin);
    const circuit = this._payload && this._payload.circuit;
    const circuitId = (circuit && circuit.circuit_id) || routeUrl.searchParams.get("circuit_id") || "";
    const query = circuitId ? new URLSearchParams({ circuit_id: circuitId }).toString() : "";
    const routeApiPath = routeUrl.searchParams.get(NILM_WORKSPACE_QUERY_PARAM) === "1" && query
      ? `${NILM_WORKSPACE_CALL_API_PATH}?${query}`
      : "";
    const apiPath = (nilm && nilm.workspace_call_api_path) || routeApiPath;
    if (!apiPath) {
      return;
    }

    const fetchPath = (nilm && nilm.workspace_api_path)
      || `${NILM_WORKSPACE_API_PATH}?${query}`;
    this._nilmWorkspaceLoading = true;
    this._nilmWorkspaceError = "";
    this._nilmWorkspaceHistorySeries = [];
    this._render();

    try {
      const workspace = await this._requestJson(apiPath || NILM_WORKSPACE_CALL_API_PATH, fetchPath);
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._nilmWorkspace = workspace;
      const historyPath = workspace && workspace.history && workspace.history.api_path;
      const historyFetchPath = (workspace && workspace.history && workspace.history.fetch_path)
        || (historyPath ? `/api/${historyPath}` : "");
      if (historyPath) {
        try {
          const history = await this._requestJson(historyPath, historyFetchPath);
          if (!this._isCurrentRequest(requestId, routeKey)) {
            return;
          }
          this._nilmWorkspaceHistorySeries = Array.isArray(history) ? history : [];
        } catch (error) {
          if (!this._isCurrentRequest(requestId, routeKey)) {
            return;
          }
          this._nilmWorkspaceError = `Could not load NILM workspace history: ${error.message}`;
        }
      }
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._nilmWorkspaceError = `Could not load NILM workspace: ${error.message}`;
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._nilmWorkspaceLoading = false;
        this._render();
      }
    }
  }

  async _loadApplianceDetail(requestId = this._evidenceRequestId, routeKey = this._loadedRouteKey) {
    if (!this._routeRequestsApplianceDetail(routeKey)) {
      return;
    }
    const routeUrl = new URL(routeKey, window.location.origin);
    const params = new URLSearchParams();
    const circuit = this._payload && this._payload.circuit;
    const circuitId = routeUrl.searchParams.get("circuit_id") || (circuit && circuit.circuit_id) || "";
    const assignmentId = routeUrl.searchParams.get("assignment_id") || "";
    if (circuitId) {
      params.set("circuit_id", circuitId);
    }
    if (assignmentId) {
      params.set("assignment_id", assignmentId);
    }
    const query = params.toString();
    const apiPath = `${APPLIANCE_DETAIL_CALL_API_PATH}${query ? `?${query}` : ""}`;
    const fetchPath = `${APPLIANCE_DETAIL_API_PATH}${query ? `?${query}` : ""}`;

    this._applianceDetailLoading = true;
    this._applianceDetailError = "";
    this._render();

    try {
      const detail = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._applianceDetail = detail;
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._applianceDetailError = `Could not load Appliance Detail from ${fetchPath}: ${error.message}`;
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._applianceDetailLoading = false;
        this._render();
      }
    }
  }

  async _loadSetupHealth(requestId = this._evidenceRequestId, routeKey = this._loadedRouteKey) {
    if (!this._routeRequestsSetupHealth(routeKey)) {
      return;
    }
    const routeUrl = new URL(routeKey, window.location.origin);
    const params = new URLSearchParams();
    const entryId = routeUrl.searchParams.get("entry_id") || "";
    if (entryId) {
      params.set("entry_id", entryId);
    }
    const query = params.toString();
    const apiPath = `${SETUP_HEALTH_CALL_API_PATH}${query ? `?${query}` : ""}`;
    const fetchPath = `${SETUP_HEALTH_API_PATH}${query ? `?${query}` : ""}`;

    this._setupHealthLoading = true;
    this._setupHealthError = "";
    this._render();

    try {
      const payload = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._setupHealth = payload;
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._setupHealthError = `Could not load Setup Health from ${fetchPath}: ${error.message}`;
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._setupHealthLoading = false;
        this._render();
      }
    }
  }

  async _requestJson(apiPath, fetchPath) {
    if (this._hass && this._hass.callApi) {
      return this._hass.callApi("GET", apiPath);
    }
    const response = await fetch(fetchPath);
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  async _callAction(actionKey) {
    const payloadActions = this._payload && this._payload.actions;
    const fallbackAlert = this._payload && this._payload.alert;
    const action = (payloadActions && payloadActions[actionKey]) || {
      service: ACTION_SERVICE_NAMES[actionKey],
      data: { alert_id: fallbackAlert && fallbackAlert.alert_id },
    };
    if (!this._guardActionCall(action, actionKey)) {
      return;
    }
    if (action.path) {
      this._navigate(action.path);
      return;
    }
    this._busyAction = actionKey;
    this._render();
    try {
      if (action.domain) {
        await this._hass.callService(action.domain, action.service, action.data || {});
      } else {
        await this._hass.callService("circuitsetup_energy_analyzer", action.service, action.data || {});
      }
      this._lastActionMessage = this._alertActionMessage(actionKey);
      this._busyAction = "";
      await this._loadEvidence({ routeKey: this._actionRefreshRouteKey(actionKey) });
      this._scrollToTop();
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  async _callApplianceDetailAction(actionKey) {
    const payload = this._applianceDetail || {};
    const actions = payload.actions || {};
    const action = actions[actionKey];
    if (!this._guardActionCall(action, `appliance detail ${actionKey}`)) {
      return;
    }
    if (action.path) {
      this._navigate(action.path);
      return;
    }
    const busyKey = `appliance_detail_${actionKey}`;
    this._busyAction = busyKey;
    this._render();
    try {
      if (action.domain) {
        await this._hass.callService(action.domain, action.service, action.data || {});
      } else {
        await this._hass.callService("circuitsetup_energy_analyzer", action.service, action.data || {});
      }
      this._lastActionMessage = this._applianceDetailActionMessage(actionKey);
      this._busyAction = "";
      await this._loadEvidence({ routeKey: this._routeKey() });
      this._scrollToTop();
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  async _callNilmAction(index, actionKey) {
    const signatures = this._nilmReviewSignatures();
    const signature = signatures && signatures[index];
    const action = signature && signature.actions && signature.actions[actionKey];
    if (!this._guardActionCall(action, `NILM ${actionKey}`)) {
      return;
    }
    const data = Object.assign({}, action.data || {});
    if (actionKey === "label" || actionKey === "assign") {
      const labelInput = this.shadowRoot.querySelector(`#nilm_label_${index}`);
      const existingAssignment = actionKey === "assign" ? this._nilmExistingAssignmentSelection(`signature_${index}`) : null;
      const label = existingAssignment ? existingAssignment.label : labelInput ? labelInput.value.trim() : "";
      if (!label) {
        this._error = "Enter a label for this NILM signature before saving.";
        this._renderAndScrollToTop();
        return;
      }
      data.label = label;
      if (existingAssignment) {
        data.assignment_id = existingAssignment.assignment_id;
      }
    }
    if (actionKey === "merge") {
      const targetList = this.shadowRoot.querySelector(`#nilm_merge_targets_${index}`);
      const target = targetList ? targetList.dataset.selected || "" : "";
      if (!target) {
        this._error = "Choose a merge target before merging NILM signatures.";
        this._renderAndScrollToTop();
        return;
      }
      data.target_signature_id = target;
    }
    const busyKey = `nilm_${index}_${actionKey}`;
    this._busyAction = busyKey;
    this._render();
    try {
      if (action.domain) {
        await this._hass.callService(action.domain, action.service, data);
      } else {
        await this._hass.callService("circuitsetup_energy_analyzer", action.service, data);
      }
      if (actionKey === "label" || actionKey === "assign") {
        this._nilmLabelDrafts.delete(this._nilmLabelDraftKey(signature));
      }
      this._lastActionMessage = this._nilmActionMessage(actionKey, data);
      this._busyAction = "";
      await this._loadEvidence({ routeKey: this._actionRefreshRouteKey(`nilm_${actionKey}`) });
      this._scrollToTop();
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  async _callNilmLabelIntervalAction(index, actionKey) {
    const workspace = this._nilmWorkspace;
    const intervals = workspace && workspace.label_intervals;
    let action = null;
    let data = {};
    if (actionKey === "adjust") {
      const interval = intervals && intervals[index];
      if (!interval) {
        this._error = "Choose a saved NILM interval before adjusting it.";
        this._renderAndScrollToTop();
        return;
      }
      this._nilmLabelIntervalDraft = {
        interval_id: String(interval.interval_id || ""),
        start: this._datetimeLocalFromMillis(Date.parse(interval.start || "")),
        end: this._datetimeLocalFromMillis(Date.parse(interval.end || "")),
        label: String(interval.label || interval.appliance_id || ""),
        appliance_id: String(interval.appliance_id || ""),
        ground_truth_entity_id: String(interval.ground_truth_entity_id || ""),
      };
      this._lastActionMessage = "Loaded interval label for adjustment.";
      this._renderAndScrollToTop();
      return;
    }
    if (actionKey === "save" || actionKey === "generate_sensor") {
      action = workspace && workspace.actions && (
        actionKey === "generate_sensor"
          ? workspace.actions.sensor_label_interval
          : workspace.actions.label_interval
      );
      data = Object.assign({}, action && action.data || {});
      const draft = this._nilmLabelIntervalDraft || {};
      const label = String(draft.label || "").trim();
      const start = this._datetimeLocalToIso(draft.start);
      const end = this._datetimeLocalToIso(draft.end);
      if (!label || !start || !end) {
        this._error = "Choose start, end, and label before saving a NILM interval.";
        this._renderAndScrollToTop();
        return;
      }
      data.label = label;
      data.start = start;
      data.end = end;
      data.appliance_id = String(draft.appliance_id || label).trim();
      const intervalId = String(draft.interval_id || "").trim();
      if (intervalId) {
        data.interval_id = intervalId;
      }
      const groundTruthEntityId = String(draft.ground_truth_entity_id || "").trim();
      if (actionKey === "generate_sensor" && !groundTruthEntityId) {
        this._error = "Choose a ground truth sensor before generating NILM intervals.";
        this._renderAndScrollToTop();
        return;
      }
      if (groundTruthEntityId) {
        data.ground_truth_entity_id = groundTruthEntityId;
        data.source = "sensor";
      }
    } else if (actionKey === "delete") {
      const interval = intervals && intervals[index];
      action = interval && interval.actions && interval.actions.delete;
      data = Object.assign({}, action && action.data || {});
    } else if (actionKey === "assign") {
      const interval = intervals && intervals[index];
      action = interval && interval.actions && interval.actions.assign;
      data = Object.assign({}, action && action.data || {});
      const existingAssignment = this._nilmExistingAssignmentSelection(`label_intervals_${index}`);
      data.label = existingAssignment
        ? existingAssignment.label
        : String((interval && (interval.label || interval.appliance_id)) || "").trim();
      if (existingAssignment) {
        data.assignment_id = existingAssignment.assignment_id;
      }
      if (!data.label) {
        this._error = "Add a label to this NILM interval before assigning it.";
        this._renderAndScrollToTop();
        return;
      }
      if (interval && interval.appliance_id) {
        data.appliance_id = interval.appliance_id;
      }
    }
    if (!this._guardActionCall(action, `NILM label interval ${actionKey}`)) {
      return;
    }
    const busyKey = actionKey === "save" || actionKey === "generate_sensor"
      ? `nilm_label_interval_${actionKey}`
      : `nilm_label_interval_${index}_${actionKey}`;
    this._busyAction = busyKey;
    this._render();
    try {
      if (action.domain) {
        await this._hass.callService(action.domain, action.service, data);
      } else {
        await this._hass.callService("circuitsetup_energy_analyzer", action.service, data);
      }
      this._lastActionMessage = actionKey === "save"
        ? `Saved interval label: ${data.label}.`
        : actionKey === "generate_sensor"
          ? `Generated sensor labels for ${data.label}.`
          : actionKey === "assign"
            ? `Assigned interval to ${data.label}.`
            : "Deleted interval label.";
      if (actionKey === "save" || actionKey === "generate_sensor") {
        this._nilmLabelIntervalDraft = { start: "", end: "", label: "", appliance_id: "", ground_truth_entity_id: "" };
      }
      this._busyAction = "";
      await this._loadEvidence({ routeKey: this._actionRefreshRouteKey("nilm_label_interval") });
      this._scrollToTop();
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  async _callNilmWorkspaceItemAction(collectionKey, index, actionKey) {
    if (collectionKey === "assignments" && actionKey === "save") {
      await this._saveNilmAssignmentChanges(index);
      return;
    }
    const workspace = this._nilmWorkspace;
    const items = workspace && workspace[collectionKey];
    const item = items && items[index];
    const action = item && item.actions && item.actions[actionKey];
    if (!this._guardActionCall(action, `NILM ${actionKey}`)) {
      return;
    }
    const data = Object.assign({}, action.data || {});
    if (action.requires && action.requires.includes("label")) {
      const labelInput = this.shadowRoot.querySelector(
        collectionKey === "sessions"
          ? `#nilm_session_label_${index}`
          : `#nilm_assignment_label_${index}`,
      );
      const existingAssignment = this._nilmExistingAssignmentSelection(`${collectionKey}_${index}`);
      const label = existingAssignment
        ? existingAssignment.label
        : labelInput
        ? labelInput.value
        : item.display_name || item.label || item.appliance_id || "";
      if (!label || !label.trim()) {
        this._error = "Enter an appliance name before assigning this NILM session.";
        this._renderAndScrollToTop();
        return;
      }
      data.label = label.trim();
      if (existingAssignment) {
        data.assignment_id = existingAssignment.assignment_id;
      }
      if (item.appliance_id && !data.appliance_id) {
        data.appliance_id = item.appliance_id;
      }
    }
    if (action.requires && action.requires.includes("appliance_profile")) {
      const profileInput = this.shadowRoot.querySelector(`#nilm_assignment_profile_${index}`);
      const profile = profileInput ? profileInput.value.trim() : "";
      if (!profile) {
        this._error = "Enter an appliance type before changing this NILM assignment.";
        this._renderAndScrollToTop();
        return;
      }
      data.appliance_profile = profile;
    }
    if (action.requires && action.requires.includes("target_assignment_id")) {
      const targetInput = this.shadowRoot.querySelector(`#nilm_assignment_merge_target_${index}`);
      const target = targetInput ? targetInput.value.trim() : "";
      if (!target) {
        this._error = "Choose an assignment to merge into.";
        this._renderAndScrollToTop();
        return;
      }
      data.target_assignment_id = target;
    }
    const busyKey = `nilm_${collectionKey}_${index}_${actionKey}`;
    this._busyAction = busyKey;
    this._render();
    try {
      if (action.domain) {
        await this._hass.callService(action.domain, action.service, data);
      } else {
        await this._hass.callService("circuitsetup_energy_analyzer", action.service, data);
      }
      this._lastActionMessage = this._nilmWorkspaceActionMessage(actionKey, data, item);
      this._busyAction = "";
      await this._loadEvidence({ routeKey: this._actionRefreshRouteKey(`nilm_${actionKey}`) });
      this._scrollToTop();
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  async _saveNilmAssignmentChanges(index) {
    const workspace = this._nilmWorkspace;
    const assignments = workspace && workspace.assignments;
    const item = assignments && assignments[index];
    const actions = item && item.actions;
    if (!actions) {
      this._error = "Action unavailable: NILM assignment save.";
      this._renderAndScrollToTop();
      return;
    }
    const calls = [];
    if (actions.rename) {
      const labelInput = this.shadowRoot.querySelector(`#nilm_assignment_label_${index}`);
      const label = labelInput ? labelInput.value.trim() : "";
      if (label && label !== String(item.display_name || "")) {
        calls.push({ actionKey: "rename", action: actions.rename, data: Object.assign({}, actions.rename.data || {}, { label }) });
      }
    }
    if (actions.change_profile) {
      const profileInput = this.shadowRoot.querySelector(`#nilm_assignment_profile_${index}`);
      const applianceProfile = profileInput ? profileInput.value.trim() : "";
      if (applianceProfile && applianceProfile !== String(item.appliance_profile || "")) {
        calls.push({ actionKey: "change_profile", action: actions.change_profile, data: Object.assign({}, actions.change_profile.data || {}, { appliance_profile: applianceProfile }) });
      }
    }
    if (actions.merge) {
      const targetInput = this.shadowRoot.querySelector(`#nilm_assignment_merge_target_${index}`);
      const targetAssignmentId = targetInput ? targetInput.value.trim() : "";
      if (targetAssignmentId) {
        calls.push({ actionKey: "merge", action: actions.merge, data: Object.assign({}, actions.merge.data || {}, { target_assignment_id: targetAssignmentId }) });
      }
    }
    if (!calls.length) {
      this._error = "No assignment changes to save.";
      this._renderAndScrollToTop();
      return;
    }
    this._busyAction = `nilm_assignments_${index}_save`;
    this._render();
    try {
      for (const call of calls) {
        if (call.action.domain) {
          await this._hass.callService(call.action.domain, call.action.service, call.data);
        } else {
          await this._hass.callService("circuitsetup_energy_analyzer", call.action.service, call.data);
        }
      }
      const draftKey = this._nilmAssignmentDraftKey(item);
      this._nilmAssignmentDrafts.delete(`${draftKey}:label`);
      this._nilmAssignmentDrafts.delete(`${draftKey}:appliance_profile`);
      this._lastActionMessage = this._nilmWorkspaceActionMessage("save", {}, item);
      this._busyAction = "";
      await this._loadEvidence({ routeKey: this._actionRefreshRouteKey("nilm_save_assignment") });
      this._scrollToTop();
    } catch (error) {
      this._error = `Could not save assignment changes: ${error.message}`;
      this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  async _callRecommendationAction(index, actionKey) {
    const recommendations = this._payload && this._payload.setting_recommendations;
    const recommendation = recommendations && recommendations[index];
    const action = recommendation && recommendation.actions && recommendation.actions[actionKey];
    if (!this._guardActionCall(action, `recommendation ${actionKey}`)) {
      return;
    }
    if (action.path) {
      this._navigate(action.path);
      return;
    }
    const busyKey = `recommendation_${index}_${actionKey}`;
    this._busyAction = busyKey;
    this._render();
    try {
      if (action.domain) {
        await this._hass.callService(action.domain, action.service, action.data || {});
      } else {
        await this._hass.callService("circuitsetup_energy_analyzer", action.service, action.data || {});
      }
      this._lastActionMessage = this._recommendationActionMessage(actionKey);
      this._busyAction = "";
      await this._loadEvidence({ routeKey: this._routeKey() });
      this._scrollToTop();
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  _navigate(path) {
    if (!path) {
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

  _guardActionCall(action, label) {
    if (!action) {
      this._error = `Action unavailable: ${label}. Reload the evidence panel and try again.`;
      this._renderAndScrollToTop();
      return false;
    }
    if (action.enabled === false) {
      this._error = action.unavailable_label || `Action unavailable: ${action.unavailable_reason || label}.`;
      this._renderAndScrollToTop();
      return false;
    }
    if (action.path) {
      return true;
    }
    if (!action.service) {
      this._error = `Action unavailable: ${label}. The panel did not receive a service to call.`;
      this._renderAndScrollToTop();
      return false;
    }
    if (!this._hass || !this._hass.callService) {
      this._error = "Home Assistant service calls are not available in this panel session. Reload Home Assistant and try again.";
      this._renderAndScrollToTop();
      return false;
    }
    return true;
  }

  _renderAndScrollToTop() {
    this._render();
    this._scrollToTop();
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

  _routeRequestsNilmWorkspace() {
    const routeUrl = new URL(this._routeKey(), window.location.origin);
    return routeUrl.searchParams.get(NILM_WORKSPACE_QUERY_PARAM) === "1";
  }

  _routeRequestsApplianceDetail(routeKey = this._routeKey()) {
    const routeUrl = new URL(routeKey, window.location.origin);
    if (routeUrl.searchParams.get(APPLIANCE_DETAIL_QUERY_PARAM) === "1") {
      return true;
    }
    return routeUrl.searchParams.has("assignment_id")
      && routeUrl.searchParams.get(NILM_WORKSPACE_QUERY_PARAM) !== "1";
  }

  _routeRequestsSetupHealth(routeKey = this._routeKey()) {
    const routeUrl = new URL(routeKey, window.location.origin);
    return routeUrl.searchParams.get(SETUP_HEALTH_QUERY_PARAM) === "1";
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
    if (actionKey.startsWith("nilm_")) {
      routeUrl.searchParams.set(EXPAND_NILM_QUERY_PARAM, routeUrl.searchParams.get(EXPAND_NILM_QUERY_PARAM) || "1");
    }
    const refreshRouteKey = `${routeUrl.pathname}${routeUrl.search}`;
    if (refreshRouteKey !== this._routeKey()) {
      history.replaceState(null, "", refreshRouteKey);
    }
    return refreshRouteKey;
  }

  _nilmActionMessage(actionKey, data) {
    if (actionKey === "label") {
      return `Saved label: ${data.label}.`;
    }
    if (actionKey === "ignore") {
      return "Ignored signature.";
    }
    if (actionKey === "mark_expected") {
      return "Marked signature expected.";
    }
    if (actionKey === "merge") {
      return "Merged signature.";
    }
    if (actionKey === "assign") {
      return `Assigned signature to ${data.label}.`;
    }
    return "Action complete.";
  }

  _alertActionMessage(actionKey) {
    const messages = {
      acknowledge: "Alert acknowledged.",
      mark_expected: "Marked as expected behavior.",
      mark_unhelpful: "Marked as not helpful.",
      pause_alerts: "Alert pause updated.",
      relearn_baseline: "Baseline relearn requested.",
    };
    return messages[actionKey] || "Action complete.";
  }

  _applianceDetailActionMessage(actionKey) {
    const messages = {
      pause_alerts: "Alert pause updated.",
      relearn_baseline: "Baseline relearn requested.",
      open_advanced_circuit_settings: "Opening Advanced Circuit Settings.",
      open_evidence: "Opening evidence.",
      review_nilm_assignment: "Opening NILM assignment review.",
    };
    return messages[actionKey] || "Action complete.";
  }

  _nilmWorkspaceActionMessage(actionKey, data, item) {
    const name = (data && data.label) || (item && (item.display_name || item.label)) || "appliance";
    if (actionKey === "assign") {
      return `Assigned to ${name}.`;
    }
    if (actionKey === "publish") {
      return "Published estimated appliance entities.";
    }
    if (actionKey === "unpublish") {
      return "Disabled estimated appliance publishing.";
    }
    if (actionKey === "retire") {
      return "Removed appliance assignment.";
    }
    if (actionKey === "save") {
      return "Saved assignment changes.";
    }
    if (actionKey === "rename") {
      return `Renamed assignment to ${name}.`;
    }
    if (actionKey === "change_profile") {
      return "Changed appliance type.";
    }
    if (actionKey === "validate_history") {
      return `Validated ${name} history.`;
    }
    if (actionKey === "merge") {
      return `Merged ${name}.`;
    }
    if (actionKey === "validate") {
      return `Confirmed ${name}.`;
    }
    if (actionKey === "reject") {
      return `Marked ${name} for review.`;
    }
    return "Action complete.";
  }

  _recommendationActionMessage(actionKey) {
    const messages = {
      apply: "Recommendation applied.",
      dismiss: "Recommendation dismissed.",
      undo: "Recommendation change undone.",
      reset: "Recommendation setting reset to default.",
    };
    return messages[actionKey] || "Recommendation action complete.";
  }

  _isCurrentRequest(requestId, routeKey) {
    return requestId === this._evidenceRequestId && routeKey === this._routeKey();
  }

  _render() {
    const payload = this._payload;
    const alert = payload && payload.alert;
    const circuit = payload && payload.circuit;
    const nilmWorkspaceRoute = this._routeRequestsNilmWorkspace();
    const applianceDetailRoute = this._routeRequestsApplianceDetail();
    const setupHealthRoute = this._routeRequestsSetupHealth();
    const applianceDetail = this._applianceDetail && this._applianceDetail.detail;
    const statusText = setupHealthRoute
      ? "Setup Health"
      : applianceDetailRoute
      ? "Appliance Detail"
      : nilmWorkspaceRoute
      ? "NILM Workspace"
      : this._statusText(payload && payload.status);
    const headerTitle = setupHealthRoute
      ? "Setup Health"
      : applianceDetailRoute
      ? (applianceDetail && applianceDetail.display_name) || "Appliance Detail"
      : nilmWorkspaceRoute
      ? "NILM Workspace"
      : (circuit && circuit.name) || (alert && alert.circuit_id) || "Alert Evidence";
    const headerMessage = setupHealthRoute
      ? (this._setupHealth && this._setupHealth.next_step) || "Guided setup checklist for appliance energy analysis."
      : applianceDetailRoute
      ? (applianceDetail && applianceDetail.next_step) || (this._applianceDetail && this._applianceDetail.next_step) || "Appliance behavior summary."
      : nilmWorkspaceRoute
      ? `Mains NILM graph and review${circuit && circuit.name ? ` for ${circuit.name}` : ""}.`
      : (alert && alert.message) || "Historical alert not found";
    const loadingText = setupHealthRoute ? "Loading Setup Health..." : "Loading alert evidence...";

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          min-height: 100vh;
          box-sizing: border-box;
          padding: 24px;
          color: var(--primary-text-color, #1f2933);
          background: var(--primary-background-color, #f7f8fa);
          font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
        }
        .shell {
          max-width: 1120px;
          margin: 0 auto;
          display: grid;
          gap: 16px;
        }
        h1, h2, p {
          margin: 0;
        }
        h1 {
          font-size: 28px;
          line-height: 1.2;
        }
        h2 {
          font-size: 18px;
        }
        .panel {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #d8dde6);
          border-radius: 8px;
          padding: 18px;
          box-shadow: var(--ha-card-box-shadow, 0 1px 3px rgba(15, 23, 42, 0.12));
        }
        .summary {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 12px;
        }
        .metric {
          border: 1px solid var(--divider-color, #d8dde6);
          border-radius: 6px;
          padding: 12px;
          background: var(--secondary-background-color, #f4f6f8);
        }
        .metric span {
          display: block;
          color: var(--secondary-text-color, #5f6b7a);
          font-size: 12px;
          margin-bottom: 4px;
        }
        .metric strong {
          font-size: 18px;
        }
        .muted {
          color: var(--secondary-text-color, #5f6b7a);
        }
        .status {
          display: inline-flex;
          width: fit-content;
          border-radius: 999px;
          padding: 5px 10px;
          background: var(--state-icon-active-color, #0b6bcb);
          color: var(--text-primary-color, #fff);
          font-weight: 700;
          font-size: 13px;
        }
        .safety-notice {
          border-color: var(--warning-color, #f4b400);
          background: var(--secondary-background-color, #fff8e1);
        }
        .safety-notice p {
          margin-top: 8px;
        }
        .chart {
          width: 100%;
          min-height: 340px;
        }
        .chart[data-nilm-chart-select] {
          cursor: crosshair;
          touch-action: none;
        }
        .chart text {
          fill: var(--secondary-text-color, #5f6b7a);
          font-size: 12px;
        }
        .axis, .grid {
          stroke: var(--divider-color, #d8dde6);
        }
        .nilm-edge-marker {
          stroke: var(--warning-color, #f59e0b);
          stroke-dasharray: 4 3;
          stroke-width: 2;
        }
        .nilm-session-band {
          fill: var(--warning-color, #f59e0b);
          opacity: 0.12;
        }
        .nilm-session-band[data-nilm-low-confidence="true"] {
          stroke: var(--warning-color, #f59e0b);
          stroke-dasharray: 4 3;
          stroke-width: 2;
        }
        .chart .nilm-session-label {
          fill: var(--primary-text-color, #1f2937);
          font-size: 11px;
          font-weight: 700;
          paint-order: stroke;
          pointer-events: none;
          stroke: var(--card-background-color, #fff);
          stroke-width: 3px;
        }
        .legend {
          display: grid;
          gap: 6px;
          margin-top: 12px;
        }
        .legend-item {
          align-items: center;
          display: flex;
          gap: 8px;
          min-width: 0;
        }
        .swatch {
          border-radius: 999px;
          display: inline-block;
          height: 10px;
          width: 10px;
        }
        ul {
          margin: 10px 0 0;
          padding-left: 20px;
        }
        .actions {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
        }
        .action-group {
          display: grid;
          gap: 8px;
          margin-top: 12px;
        }
        .action-group h3 {
          font-size: 1rem;
          margin: 0;
        }
        .action-item {
          display: inline-flex;
          flex-direction: column;
          gap: 4px;
          max-width: 220px;
        }
        .action-reason {
          color: var(--secondary-text-color, #6b7280);
          font-size: 0.78rem;
          line-height: 1.3;
        }
        button, a.button {
          appearance: none;
          border: 1px solid var(--primary-color, #0b6bcb);
          border-radius: 6px;
          background: var(--primary-color, #0b6bcb);
          color: var(--text-primary-color, #fff);
          cursor: pointer;
          font: inherit;
          font-weight: 700;
          padding: 10px 14px;
          text-decoration: none;
        }
        button.secondary {
          background: transparent;
          color: var(--primary-color, #0b6bcb);
        }
        button:disabled {
          cursor: wait;
          opacity: 0.65;
        }
        .error {
          border-color: var(--error-color, #db4437);
          color: var(--error-color, #db4437);
        }
        .entity-list {
          display: grid;
          gap: 8px;
          margin-top: 10px;
        }
        code {
          background: var(--secondary-background-color, #f4f6f8);
          border-radius: 4px;
          padding: 2px 5px;
        }
        .nilm-label-field {
          display: grid;
          gap: 4px;
          margin-top: 10px;
        }
        .nilm-label-field input {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #d8dee6);
          border-radius: 8px;
          color: var(--primary-text-color, #111827);
          font: inherit;
          padding: 8px 10px;
        }
        .nilm-interval-form {
          display: grid;
          gap: 10px;
          grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
          margin: 12px 0;
        }
        .nilm-interval-form label {
          display: grid;
          gap: 4px;
        }
        .nilm-interval-form input {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #d8dee6);
          border-radius: 8px;
          color: var(--primary-text-color, #111827);
          font: inherit;
          padding: 8px 10px;
          min-width: 0;
        }
        .merge-targets {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          margin-top: 8px;
        }
        .merge-target-chip {
          background: var(--secondary-background-color, #f4f6f8);
          border: 1px solid var(--divider-color, #d8dee6);
          border-radius: 999px;
          color: var(--primary-text-color, #111827);
          cursor: pointer;
          font: inherit;
          padding: 7px 11px;
        }
        .merge-target-chip[aria-pressed="true"] {
          background: var(--primary-color, #03a9f4);
          border-color: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
        }
      </style>
      <main class="shell">
        <section class="panel">
          <p class="status">${this._escape(statusText)}</p>
          <h1>${this._escape(headerTitle)}</h1>
          <p class="muted">${this._escape(headerMessage)}</p>
        </section>
      ${this._loading ? `<section class="panel"><p>${this._escape(loadingText)}</p></section>` : ""}
      ${this._lastActionMessage ? `<section class="panel"><p>${this._escape(this._lastActionMessage)}</p></section>` : ""}
      ${this._error ? `<section class="panel error"><p>${this._escape(this._error)}</p><button class="secondary" id="retry">Retry</button></section>` : ""}
      ${this._renderSelectedRecommendationEvidence()}
      ${this._routeRequestsSetupHealth() ? this._renderSetupHealthBody() : (this._routeRequestsApplianceDetail() ? this._renderApplianceDetailBody() : (this._routeRequestsNilmWorkspace() ? this._renderNilmWorkspaceBody() : this._renderEvidenceBody(alert, circuit)))}
      </main>
    `;

    this._listen("#retry", () => this._loadEvidence({ routeKey: this._routeKey() }));
    this._listen("#acknowledge", () => this._callAction("acknowledge"));
    this._listen("#mark_expected", () => this._callAction("mark_expected"));
    this._listen("#mark_unhelpful", () => this._callAction("mark_unhelpful"));
    this._listen("#pause_alerts", () => this._callAction("pause_alerts"));
    this._listen("#relearn_baseline", () => this._callAction("relearn_baseline"));
    this._listen("#open_appliance_detail", () => this._callAction("open_appliance_detail"));
    this._listen("#open_advanced_circuit_settings", () => this._callAction("open_advanced_circuit_settings"));
    for (const button of this.shadowRoot.querySelectorAll("[data-appliance-detail-action]")) {
      button.addEventListener("click", () => {
        this._callApplianceDetailAction(button.dataset.applianceDetailAction);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-recommendation-action]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.recommendationIndex, 10);
        this._callRecommendationAction(index, button.dataset.recommendationAction);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-action]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.nilmIndex, 10);
        this._callNilmAction(index, button.dataset.nilmAction);
      });
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-label-input]")) {
      input.addEventListener("input", () => this._rememberNilmLabelDraft(input));
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-label-interval-input]")) {
      input.addEventListener("input", () => this._rememberNilmLabelIntervalDraft(input));
      input.addEventListener("change", () => this._rememberNilmLabelIntervalDraft(input));
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-session-label-input]")) {
      input.addEventListener("input", () => this._rememberNilmSessionLabelDraft(input));
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-assignment-input]")) {
      input.addEventListener("input", () => this._rememberNilmAssignmentDraft(input));
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-overlay-toggle]")) {
      input.addEventListener("change", () => this._toggleNilmOverlaySeries(input));
    }
    for (const chart of this.shadowRoot.querySelectorAll("[data-nilm-chart-select]")) {
      chart.addEventListener("pointerdown", (event) => this._startNilmChartSelection(event, chart));
    }
    for (const band of this.shadowRoot.querySelectorAll("[data-nilm-session-start]")) {
      band.addEventListener("click", () => this._selectNilmSessionInterval(band));
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-session-interval-index]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.nilmSessionIntervalIndex || "-1", 10);
        this._selectNilmSessionIntervalByIndex(index);
      });
    }
    for (const marker of this.shadowRoot.querySelectorAll("[data-nilm-edge-time]")) {
      marker.addEventListener("click", () => this._selectNilmEdgeTime(marker));
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-signature-focus]")) {
      button.addEventListener("click", () => {
        void this._focusNilmSignatureOnGraph(button.dataset.nilmSignatureFocus);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-graph-zoom]")) {
      button.addEventListener("click", () => this._zoomNilmGraph(Number(button.dataset.nilmGraphZoom)));
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-graph-pan]")) {
      button.addEventListener("click", () => this._panNilmGraph(Number(button.dataset.nilmGraphPan)));
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-merge-target]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.nilmIndex, 10);
        this._selectNilmMergeTarget(index, button.dataset.nilmMergeTarget);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-load-all-nilm]")) {
      button.addEventListener("click", () => this._loadExpandedNilm());
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-label-interval-action]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.nilmLabelIntervalIndex || "-1", 10);
        this._callNilmLabelIntervalAction(index, button.dataset.nilmLabelIntervalAction);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-session-action]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.nilmSessionIndex || "-1", 10);
        this._callNilmWorkspaceItemAction("sessions", index, button.dataset.nilmSessionAction);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-assignment-action]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.nilmAssignmentIndex || "-1", 10);
        this._callNilmWorkspaceItemAction("assignments", index, button.dataset.nilmAssignmentAction);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-appliance-detail-path]")) {
      button.addEventListener("click", () => {
        this._navigate(button.dataset.nilmApplianceDetailPath);
      });
    }
  }

  _renderApplianceDetailBody() {
    return `${this._renderApplianceDetail()}${this._renderRecommendations()}`;
  }

  _renderSetupHealthBody() {
    return this._renderSetupHealth();
  }

  _renderSetupHealth() {
    return this._setupHealthComponent.render();
  }

  _renderSetupHealthContent() {
    if (this._setupHealthLoading) {
      return `<section class="panel"><h2>Setup Health</h2><p class="muted">Loading Setup Health...</p></section>`;
    }
    if (this._setupHealthError) {
      return `<section class="panel error"><h2>Setup Health</h2><p>${this._escape(this._setupHealthError)}</p></section>`;
    }
    const payload = this._setupHealth || {};
    if (payload.status && payload.status !== "ok") {
      return `
        <section class="panel">
          <h2>Setup Health</h2>
          <p>${this._escape(payload.message || "Setup Health is not available right now.")}</p>
          <p class="muted">${this._escape(payload.next_step || "Reload the integration, then try again.")}</p>
        </section>
      `;
    }
    const readyCount = payload.checklist_ready_count === null || payload.checklist_ready_count === undefined
      ? "Unknown"
      : payload.checklist_ready_count;
    const totalCount = payload.checklist_total_count === null || payload.checklist_total_count === undefined
      ? "Unknown"
      : payload.checklist_total_count;
    return `
      <section class="panel summary">
        ${this._metric("Status", payload.state || "Learning")}
        ${this._metric("Next Step", payload.next_step || "No setup action needed")}
        ${this._metric("Checklist", `${readyCount} / ${totalCount}`)}
        ${this._metric("Issues", this._formatMetricValue(payload.issue_count))}
      </section>
      <section class="panel">
        <h2>Setup Checklist</h2>
        <p class="muted">${this._escape(payload.message || "Review setup items that affect appliance analysis.")}</p>
        ${this._renderSetupHealthChecklist(payload.checklist, payload.open_path)}
      </section>
      <section class="panel">
        <h2>What To Check First</h2>
        ${this._renderSetupHealthIssues(payload.issues, payload.next_step)}
      </section>
    `;
  }

  _renderSetupHealthChecklist(items, fallbackOpenPath) {
    const safeItems = Array.isArray(items) ? items : [];
    if (!safeItems.length) {
      return `<p class="muted">No setup checklist items are available yet.</p>`;
    }
    return `<div class="entity-list">${safeItems.map((item) => {
      const affected = Array.isArray(item.affected_circuits) ? item.affected_circuits : [];
      const path = item.open_path || fallbackOpenPath || "";
      return `
        <div class="metric">
          <span>${this._escape(this._friendlyFeature(item.status || "unknown"))}</span>
          <strong>${this._escape(item.title || item.item_id || "Setup item")}</strong>
          <p>${this._escape(item.why_it_matters || "This affects appliance analysis quality.")}</p>
          ${affected.length ? `<p class="muted">Affected: ${this._escape(affected.join(", "))}</p>` : ""}
          ${item.fix ? (path ? `<a class="button secondary" href="${this._escape(path)}">${this._escape(item.fix)}</a>` : `<p class="muted">${this._escape(item.fix)}</p>`) : ""}
        </div>
      `;
    }).join("")}</div>`;
  }

  _renderSetupHealthIssues(issues, fallbackText) {
    const safeIssues = Array.isArray(issues) ? issues : [];
    if (!safeIssues.length) {
      return `<p class="muted">${this._escape(fallbackText || "No setup problems were found.")}</p>`;
    }
    return `<div class="entity-list">${safeIssues.map((item) => `
      <div class="metric">
        <span>${this._escape(item.severity || item.state || "review")}</span>
        <strong>${this._escape(item.fix || item.recommended_action || item.state || "Review setup")}</strong>
        <p>${this._escape(item.reason || "Review this setup item before relying on appliance guidance.")}</p>
        ${item.affected_circuit_name || item.affected_circuit ? `<p class="muted">Circuit: ${this._escape(item.affected_circuit_name || item.affected_circuit)}</p>` : ""}
        ${item.open_path ? `<a class="button secondary" href="${this._escape(item.open_path)}">Open Setup</a>` : ""}
      </div>
    `).join("")}</div>`;
  }

  _renderApplianceDetail() {
    return this._applianceDetailComponent.render();
  }

  _renderApplianceDetailContent() {
    if (this._applianceDetailLoading) {
      return `<section class="panel"><p>Loading Appliance Detail...</p></section>`;
    }
    if (this._applianceDetailError) {
      return `<section class="panel error"><p>${this._escape(this._applianceDetailError)}</p></section>`;
    }
    const payload = this._applianceDetail || {};
    const detail = payload.detail;
    if (!detail) {
      return `
        <section class="panel">
          <h2>Appliance Detail</h2>
          <p>${this._escape(payload.message || "No appliance detail is available for the requested appliance.")}</p>
          <p class="muted">${this._escape(payload.next_step || "Open the generated dashboard or review the appliance summary sensors.")}</p>
        </section>
      `;
    }
    return `
      <section class="panel summary">
        ${this._metric("Activity", detail.activity_state)}
        ${this._metric("Power", this._formatPower(detail.current_power_w))}
        ${this._metric("Source", this._sourceLabel(detail.source_type))}
        ${detail.confidence !== null && detail.confidence !== undefined ? this._metric("Confidence", this._formatConfidence(detail.confidence)) : ""}
      </section>
      <section class="panel summary">
        ${this._metric("Health", detail.health_state)}
        ${this._metric("Electrical", detail.electrical_state)}
        ${this._metric("Energy", detail.energy_state)}
        ${this._metric("Model", detail.model_status || "Direct meter")}
      </section>
      <section class="panel summary">
        ${this._metric("Energy Today", this._formatKwh(detail.daily_energy_kwh))}
        ${this._metric("Runtime Today", this._formatDuration(detail.runtime_today_seconds))}
        ${this._metric("Runs Today", detail.run_count_today)}
        ${this._metric("Cost Today", this._formatCost(detail.cost_today))}
      </section>
      <section class="panel">
        <h2>Recent Timeline</h2>
        ${this._renderApplianceTimeline(detail.recent_timeline)}
      </section>
      <section class="panel">
        <h2>Today vs Normal</h2>
        ${this._renderApplianceComparisons(detail.today_vs_normal)}
      </section>
      <section class="panel">
        <h2>Behavior Expectations</h2>
        ${this._renderApplianceExpectations(detail.expectations)}
      </section>
      <section class="panel">
        <h2>What To Check First</h2>
        ${this._renderSimpleList(detail.what_to_check_first, detail.next_step || "No immediate check is needed.")}
      </section>
      <section class="panel">
        <h2>Alerts and Evidence</h2>
        ${this._renderApplianceAlerts(detail.active_alerts)}
      </section>
      <section class="panel">
        <h2>Actions</h2>
        ${this._renderApplianceActions(payload.actions)}
      </section>
    `;
  }

  _renderApplianceTimeline(timeline) {
    const items = Array.isArray(timeline && timeline.items) ? timeline.items : [];
    if (!items.length) {
      const title = timeline && timeline.latest_title ? timeline.latest_title : "No recent activity";
      return `<p class="muted">${this._escape(title)}</p>`;
    }
    return `<div class="entity-list">${items.map((item) => `
      <div class="metric">
        <span>${this._escape(this._formatDateTime(item.timestamp))}</span>
        <strong>${this._escape(item.title || this._friendlyFeature(item.kind || "activity"))}</strong>
        <p class="muted">${this._escape(item.detail || "")}</p>
      </div>
    `).join("")}</div>`;
  }

  _renderApplianceComparisons(comparisons) {
    const items = Array.isArray(comparisons) ? comparisons : [];
    if (!items.length) {
      return `<p class="muted">Learning normal ranges for this appliance.</p>`;
    }
    return `<div class="entity-list">${items.map((item) => {
      const normal = item.normal_low !== null && item.normal_low !== undefined && item.normal_high !== null && item.normal_high !== undefined
        ? `${this._formatComparisonValue(item, item.normal_low)} - ${this._formatComparisonValue(item, item.normal_high)}`
        : "Learning";
      return `
        <div class="metric">
          <span>${this._escape(item.label || this._friendlyFeature(item.metric_id))}</span>
          <strong>${this._escape(this._formatComparisonValue(item, item.current_value))}</strong>
          <p class="muted">Normal ${this._escape(normal)}. Status ${this._escape(this._friendlyFeature(item.status))}.</p>
          ${item.confidence !== null && item.confidence !== undefined ? `<p class="muted">Confidence ${this._escape(this._formatConfidence(item.confidence))}</p>` : ""}
          ${item.source ? `<p class="muted">Source ${this._escape(this._friendlyFeature(item.source))}</p>` : ""}
        </div>
      `;
    }).join("")}</div>`;
  }

  _renderApplianceExpectations(expectations) {
    const items = Array.isArray(expectations) ? expectations : [];
    if (!items.length) {
      return `<p class="muted">Not enough data for appliance-specific expectations yet.</p>`;
    }
    return `<div class="entity-list">${items.map((item) => `
      <div class="metric">
        <span>${this._escape(this._friendlyFeature(item.status))}</span>
        <strong>${this._escape(item.title || "Appliance expectation")}</strong>
        <p>${this._escape(item.observed || "Observed behavior is still learning.")}</p>
        <p class="muted">Expected: ${this._escape(item.expected || "Normal appliance behavior is still learning.")}</p>
        <p class="muted">${this._escape(item.why_it_matters || "")}</p>
        ${this._renderSimpleList(item.what_to_check_first, "")}
      </div>
    `).join("")}</div>`;
  }

  _renderApplianceAlerts(alerts) {
    const items = Array.isArray(alerts) ? alerts : [];
    if (!items.length) {
      return `<p class="muted">No active appliance alerts were found.</p>`;
    }
    return `<div class="entity-list">${items.map((item) => `
      <div class="metric">
        <span>${this._escape(this._friendlyFeature(item.severity || item.feature))}</span>
        <strong>${this._escape(item.message || this._friendlyFeature(item.feature))}</strong>
        <p class="muted">Repeated ${this._escape(this._formatMetricValue(item.repeated_count))} times.</p>
        ${item.evidence_path ? `<a class="button secondary" href="${this._escape(item.evidence_path)}">Open Evidence</a>` : ""}
      </div>
    `).join("")}</div>`;
  }

  _renderApplianceActions(actions) {
    const available = actions || {};
    const buttons = [
      this._applianceActionButton(available, "open_evidence", "Open Evidence"),
      this._applianceActionButton(available, "review_nilm_assignment", "Review NILM Assignment", true),
      this._applianceActionButton(available, "mark_expected", "Mark Expected", true),
      this._applianceActionButton(available, "mark_unhelpful", "Not Helpful", true),
      this._applianceActionButton(available, "pause_alerts", "Pause Alerts", true),
      this._applianceActionButton(available, "relearn_baseline", "Relearn Baseline", true),
      this._applianceActionButton(available, "open_advanced_circuit_settings", "Open Advanced Circuit Settings", true),
    ].filter(Boolean);
    return buttons.length ? `<div class="actions">${buttons.join("")}</div>` : `<p class="muted">No actions are available for this appliance right now.</p>`;
  }

  _applianceActionButton(actions, actionKey, label, secondary = false) {
    const action = actions && actions[actionKey];
    if (!action) {
      return "";
    }
    const busyKey = `appliance_detail_${actionKey}`;
    const disabled = this._busyAction === busyKey || action.enabled === false ? "disabled" : "";
    const reason = action.unavailable_label || action.unavailable_reason || "";
    const title = reason ? ` title="${this._escape(reason)}"` : "";
    return `<button type="button" data-appliance-detail-action="${actionKey}" class="${secondary ? "secondary" : ""}"${title} ${disabled}>${this._escape(action.label || label)}</button>`;
  }

  _renderSimpleList(items, emptyText) {
    const safeItems = Array.isArray(items) ? items.filter(Boolean) : [];
    if (!safeItems.length) {
      return emptyText ? `<p class="muted">${this._escape(emptyText)}</p>` : "";
    }
    return `<ul>${safeItems.map((item) => `<li>${this._escape(item)}</li>`).join("")}</ul>`;
  }

  _renderEvidenceBody(alert, circuit) {
    return alert ? this._renderAlert(alert, circuit) : this._renderNotFound();
  }

  _renderNilmWorkspaceBody() {
    return `${this._renderNilmWorkspace()}${this._renderRecommendations()}`;
  }

  _renderAlert(alert, circuit) {
    return this._evidenceSummary.renderAlert(alert, circuit);
  }

  _renderAlertContent(alert, circuit) {
    return `
      <section class="panel summary">
        ${this._metric("Circuit", (circuit && circuit.name) || alert.circuit_id)}
        ${this._metric("Feature", alert.feature_name || this._friendlyFeature(alert.feature))}
        ${this._metric("Observed", alert.observed_value)}
        ${this._metric("Baseline", alert.baseline_value)}
        ${this._metric("Change", `${alert.percent_change}%`)}
        ${this._metric("Repeated", alert.repeated_count)}
      </section>
      ${this._renderSafetyNotice(alert)}
      <section class="panel">
        <h2>What Happened</h2>
        <p>${this._escape(alert.what_happened || alert.message || "The analyzer found repeated evidence for this circuit.")}</p>
      </section>
      <section class="panel">
        <h2>Why It Matters</h2>
        <p>${this._escape(alert.why_it_matters || "Repeated analyzer evidence means this circuit is no longer matching its recent learned or configured behavior.")}</p>
      </section>
      <section class="panel">
        <h2>What Changed</h2>
        <p>${this._escape(this._changeSummary(alert))}</p>
      </section>
      <section class="panel summary">
        ${this._metric("Expected", alert.expected_value)}
        ${this._metric("Threshold", alert.threshold)}
        ${this._metric("Samples", alert.sample_count)}
        ${this._metric("First Seen", this._formatDateTime(alert.first_seen))}
        ${this._metric("Last Seen", this._formatDateTime(alert.last_seen))}
        ${this._metric("Check First", alert.what_to_check_first)}
      </section>
      <section class="panel">
        <h2>Graph</h2>
        ${this._renderChart(alert)}
      </section>
      ${this._renderNilmWorkspace()}
      <section class="panel">
        <h2>Actions</h2>
        ${this._renderActionGroup("Respond to this alert", "Review the graph, then choose how the analyzer should treat this alert.", [
          this._actionButton("acknowledge", "Acknowledge"),
          this._actionButton("mark_expected", "Mark Expected", true),
          this._actionButton("mark_unhelpful", "Not Helpful", true),
        ])}
        ${this._renderActionGroup("Pause alerts for maintenance", "Use this when the appliance is being serviced or intentionally behaving differently.", [
          this._actionButton("pause_alerts", "Pause Alerts", true),
        ])}
        ${this._renderActionGroup("Tune this circuit", "Use these when the appliance summary looks wrong or the learned baseline is stale.", [
          this._actionButton("open_appliance_detail", "Open Appliance Detail", true),
          this._actionButton("relearn_baseline", "Relearn Baseline", true),
          this._actionButton("open_advanced_circuit_settings", "Open Advanced Circuit Settings", true),
        ])}
      </section>
      ${this._renderRecommendations()}
    `;
  }

  _nilmReviewSignatures() {
    const workspace = this._nilmWorkspace;
    if (workspace && workspace.status === "ok" && Array.isArray(workspace.signatures)) {
      return workspace.signatures;
    }
    const nilm = this._payload && this._payload.nilm;
    return (nilm && nilm.signatures) || [];
  }

  _renderNilmSignatureReview(signature, index) {
    const graphFingerprint = this._nilmWorkspace && this._nilmWorkspace.status === "ok" ? this._nilmSignatureFingerprint(signature) : "";
    return `
      ${signature.user_label ? `<p class="muted">Saved label: ${this._escape(signature.user_label)}</p>` : ""}
      ${signature.review_state ? `<p class="muted">Review state: ${this._escape(this._friendlyFeature(signature.review_state))}</p>` : ""}
      ${signature.merged_into ? `<p class="muted">Merged into: ${this._escape(signature.merged_into)}</p>` : ""}
      ${this._renderNilmExistingAssignmentField(signature && signature.actions && signature.actions.assign, `signature_${index}`)}
      ${this._renderNilmLabelField(signature, index)}
      ${this._renderNilmMergeTarget(signature, index)}
      <div class="actions">
        ${this._nilmActionButton(index, "label", "Save Label")}
        ${this._nilmActionButton(index, "assign", "Assign Appliance", true)}
        ${this._nilmActionButton(index, "ignore", "Ignore", true)}
        ${this._nilmActionButton(index, "mark_expected", "Mark Expected", true)}
        ${this._nilmActionButton(index, "merge", "Merge", true, !(signature.actions && signature.actions.merge && signature.actions.merge.target_options && signature.actions.merge.target_options.length))}
        ${graphFingerprint ? `<button type="button" class="secondary" data-nilm-signature-focus="${this._escape(graphFingerprint)}">Show on Graph</button>` : ""}
      </div>
    `;
  }

  _renderNilmLabelField(signature, index) {
    const draftKey = this._nilmLabelDraftKey(signature);
    const currentLabel = this._nilmLabelDrafts.has(draftKey)
      ? this._nilmLabelDrafts.get(draftKey)
      : signature.user_label
      || signature.display_name
      || signature.likely_type
      || signature.display_label
      || "";
    return `
      <label class="nilm-label-field" for="nilm_label_${index}">
        <span class="muted">Label this load</span>
        <input
          id="nilm_label_${index}"
          type="text"
          data-nilm-label-input
          data-nilm-label-key="${this._escape(draftKey)}"
          value="${this._escape(currentLabel)}"
          placeholder="Appliance name"
        >
      </label>
    `;
  }

  _nilmLabelDraftKey(signature) {
    return String(
      (signature && (signature.signature_id || signature.id || signature.display_label))
      || ""
    );
  }

  _nilmSignatureFingerprint(signature) {
    return String((signature && (signature.feedback_fingerprint || signature.signature_fingerprint || signature.signature_id)) || "").trim();
  }

  _rememberNilmLabelDraft(input) {
    if (!input || !input.dataset.nilmLabelKey) {
      return;
    }
    this._nilmLabelDrafts.set(input.dataset.nilmLabelKey, input.value);
  }

  _rememberNilmLabelIntervalDraft(input) {
    if (!input || !input.dataset.nilmLabelIntervalInput) {
      return;
    }
    this._nilmLabelIntervalDraft = Object.assign({}, this._nilmLabelIntervalDraft, {
      [input.dataset.nilmLabelIntervalInput]: input.value,
    });
  }

  _rememberNilmSessionLabelDraft(input) {
    if (!input || !input.dataset.nilmSessionLabelKey) {
      return;
    }
    this._nilmSessionLabelDrafts.set(input.dataset.nilmSessionLabelKey, input.value);
  }

  _rememberNilmAssignmentDraft(input) {
    if (!input || !input.dataset.nilmAssignmentKey || !input.dataset.nilmAssignmentField) {
      return;
    }
    this._nilmAssignmentDrafts.set(`${input.dataset.nilmAssignmentKey}:${input.dataset.nilmAssignmentField}`, input.value);
  }

  _toggleNilmOverlaySeries(input) {
    this._nilmOverlayVisibility[input.dataset.nilmOverlayToggle] = input.checked;
    this._render();
  }

  _startNilmChartSelection(event, chart) {
    const startTime = this._snapNilmChartTimeToEdge(this._chartEventTime(event, chart), chart);
    if (!Number.isFinite(startTime)) {
      return;
    }
    const finish = (finishEvent) => {
      chart.removeEventListener("pointercancel", cancel);
      const endTime = this._snapNilmChartTimeToEdge(this._chartEventTime(finishEvent, chart), chart);
      if (!Number.isFinite(endTime)) {
        return;
      }
      const start = Math.min(startTime, endTime);
      const end = Math.max(startTime, endTime);
      if (end <= start) {
        return;
      }
      this._nilmLabelIntervalDraft = Object.assign({}, this._nilmLabelIntervalDraft, {
        start: this._datetimeLocalFromMillis(start),
        end: this._datetimeLocalFromMillis(end),
      });
      this._render();
    };
    const cancel = () => {
      chart.removeEventListener("pointerup", finish);
    };
    if (chart.setPointerCapture && event.pointerId !== undefined) {
      chart.setPointerCapture(event.pointerId);
    }
    chart.addEventListener("pointerup", finish, { once: true });
    chart.addEventListener("pointercancel", cancel, { once: true });
  }

  _selectNilmSessionInterval(band) {
    this._loadNilmSessionInterval({
      start: band && band.dataset.nilmSessionStart,
      end: band && band.dataset.nilmSessionEnd,
    });
  }

  _selectNilmSessionIntervalByIndex(index) {
    const sessions = Array.isArray(this._nilmWorkspace && this._nilmWorkspace.sessions)
      ? this._nilmWorkspace.sessions
      : [];
    this._loadNilmSessionInterval(sessions[index]);
  }

  _loadNilmSessionInterval(session) {
    const start = Date.parse(session && session.start || "");
    const end = Date.parse(session && session.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return;
    }
    this._nilmLabelIntervalDraft = Object.assign({}, this._nilmLabelIntervalDraft, {
      start: this._datetimeLocalFromMillis(start),
      end: this._datetimeLocalFromMillis(end),
    });
    this._lastActionMessage = "Loaded NILM session interval.";
    this._renderAndScrollToTop();
  }

  _selectNilmEdgeTime(marker) {
    const time = Date.parse(marker && marker.dataset.nilmEdgeTime || "");
    if (!Number.isFinite(time)) {
      return;
    }
    const field = String(marker.dataset.nilmEdgeDirection || "").toLowerCase() === "off"
      ? "end"
      : "start";
    this._nilmLabelIntervalDraft = Object.assign({}, this._nilmLabelIntervalDraft, {
      [field]: this._datetimeLocalFromMillis(time),
    });
    this._lastActionMessage = "Loaded NILM edge time.";
    this._renderAndScrollToTop();
  }

  async _focusNilmSignatureOnGraph(signatureFingerprint) {
    if (this._nilmFocusedSignature === signatureFingerprint) {
      this._nilmFocusedSignature = "";
      this._nilmGraphWindow = null;
      this._lastActionMessage = "Showing all NILM graph sessions.";
      this._renderAndScrollToTop();
      return;
    }
    this._nilmFocusedSignature = signatureFingerprint;
    const targetWindow = this._nilmSignatureGraphWindow(signatureFingerprint);
    if (targetWindow) {
      await this._loadNilmWorkspaceHistoryForWindow(targetWindow);
    }
    const focused = this._focusNilmGraphWindowForSignature(signatureFingerprint);
    this._lastActionMessage = focused
      ? "Showing graph sessions for selected signature."
      : "No paired sessions matched this signature yet.";
    this._renderAndScrollToTop();
  }

  _focusNilmGraphWindowForSignature(signatureFingerprint) {
    const targetWindow = this._nilmSignatureGraphWindow(signatureFingerprint);
    if (!targetWindow) {
      return false;
    }
    const bounds = this._nilmWorkspaceGraphWindow(this._nilmWorkspace) || {
      min: targetWindow.start,
      max: targetWindow.end,
    };
    this._setNilmGraphWindow(targetWindow.start, targetWindow.end, bounds);
    return true;
  }

  _nilmSignatureGraphWindow(signatureFingerprint) {
    const workspace = this._nilmWorkspace;
    const sessions = ((workspace && workspace.sessions) || [])
      .filter((session) => session.signature_fingerprint === signatureFingerprint);
    const starts = sessions.map((session) => Date.parse(session.start || "")).filter(Number.isFinite);
    const ends = sessions.map((session) => Date.parse(session.end || session.start || "")).filter(Number.isFinite);
    if (!starts.length || !ends.length) {
      return null;
    }
    const start = Math.min(...starts);
    const end = Math.max(...ends, start + 15 * 60 * 1000);
    const padding = Math.max((end - start) * 0.25, 15 * 60 * 1000);
    return { start: start - padding, end: end + padding };
  }

  async _loadNilmWorkspaceHistoryForWindow(window) {
    const workspace = this._nilmWorkspace;
    const history = workspace && workspace.history;
    if (!history || !history.api_path) {
      return false;
    }
    const historyEnd = Date.parse(history.end || "");
    const end = Math.max(
      Number.isFinite(historyEnd) ? historyEnd : Date.now(),
      window.end,
    );
    const maxHours = Number(history.max_hours);
    const neededHours = Math.max(
      1,
      Math.ceil((end - window.start) / (60 * 60 * 1000)),
    );
    const hours = Number.isFinite(maxHours) ? Math.min(maxHours, neededHours) : neededHours;
    const start = end - hours * 60 * 60 * 1000;
    const apiPath = this._nilmWorkspaceHistoryPathWithHours(history.api_path, hours);
    const fetchPath = this._nilmWorkspaceHistoryPathWithHours(
      history.fetch_path || `/api/${history.api_path}`,
      hours,
    );
    try {
      const rows = await this._requestJson(apiPath, fetchPath);
      this._nilmWorkspaceHistorySeries = Array.isArray(rows) ? rows : [];
      this._nilmWorkspaceError = "";
      Object.assign(history, {
        api_path: apiPath,
        fetch_path: fetchPath,
        hours,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
      });
      return true;
    } catch (error) {
      this._nilmWorkspaceError = `Could not load NILM workspace history: ${error.message}`;
      return false;
    }
  }

  _nilmWorkspaceHistoryPathWithHours(path, hours) {
    const url = new URL(
      path.startsWith("/") ? path : `/${path}`,
      window.location.origin,
    );
    url.searchParams.set("hours", String(hours));
    const nextPath = `${url.pathname}${url.search}`;
    return path.startsWith("/") ? nextPath : nextPath.replace(/^\//, "");
  }

  _zoomNilmGraph(factor) {
    const window = this._nilmWorkspaceGraphWindow(this._nilmWorkspace);
    if (!window || !Number.isFinite(factor) || factor <= 0) {
      return;
    }
    const span = window.end - window.start;
    const nextSpan = Math.max(15 * 60 * 1000, Math.min(window.max - window.min, span * factor));
    const center = (window.start + window.end) / 2;
    this._lastActionMessage = "Updated NILM graph window.";
    this._setNilmGraphWindow(center - nextSpan / 2, center + nextSpan / 2, window);
  }

  _panNilmGraph(direction) {
    const window = this._nilmWorkspaceGraphWindow(this._nilmWorkspace);
    if (!window || !Number.isFinite(direction)) {
      return;
    }
    const shift = (window.end - window.start) * direction;
    this._lastActionMessage = "Updated NILM graph window.";
    this._setNilmGraphWindow(window.start + shift, window.end + shift, window);
  }

  _setNilmGraphWindow(start, end, bounds) {
    if (start < bounds.min) {
      end += bounds.min - start;
      start = bounds.min;
    }
    if (end > bounds.max) {
      start -= end - bounds.max;
      end = bounds.max;
    }
    this._nilmGraphWindow = {
      start: Math.max(bounds.min, start),
      end: Math.min(bounds.max, end),
    };
    this._render();
  }

  _snapNilmChartTimeToEdge(time, chart) {
    if (!Number.isFinite(time) || !chart || !chart.dataset.nilmEdgeTimes) {
      return time;
    }
    let snapped = time;
    let closestDistance = NILM_EDGE_SNAP_MS + 1;
    for (const value of chart.dataset.nilmEdgeTimes.split(",")) {
      const edgeTime = Number(value);
      const distance = Math.abs(edgeTime - time);
      if (Number.isFinite(edgeTime) && distance <= NILM_EDGE_SNAP_MS && distance < closestDistance) {
        snapped = edgeTime;
        closestDistance = distance;
      }
    }
    return snapped;
  }

  _chartEventTime(event, chart) {
    const rect = chart.getBoundingClientRect();
    const viewBox = String(chart.getAttribute("viewBox") || "").split(/\s+/).map(Number);
    const width = Number.isFinite(viewBox[2]) ? viewBox[2] : 900;
    const left = Number(chart.dataset.chartLeft);
    const right = Number(chart.dataset.chartRight);
    const start = Number(chart.dataset.chartStart);
    const end = Number(chart.dataset.chartEnd);
    if (!rect.width || !Number.isFinite(left) || !Number.isFinite(right) || right <= left || !Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return Number.NaN;
    }
    const viewX = ((event.clientX - rect.left) / rect.width) * width;
    const ratio = Math.max(0, Math.min(1, (viewX - left) / (right - left)));
    return start + ((end - start) * ratio);
  }

  _renderRecommendations() {
    const recommendations = this._payload && this._payload.setting_recommendations;
    if (!recommendations || !recommendations.length) {
      return "";
    }
    const grouped = this._recommendationsByStatus(recommendations);
    return `
      ${this._renderRecommendationSection("Suggested Settings", grouped.pending)}
      ${this._renderRecommendationSection("Applied Suggested Settings", grouped.applied)}
    `;
  }

  _recommendationsByStatus(recommendations) {
    return recommendations.reduce((grouped, recommendation, originalIndex) => {
      const status = String((recommendation && recommendation.status) || "pending");
      const item = { recommendation, originalIndex };
      if (status === "applied") {
        grouped.applied.push(item);
      } else if (status === "pending") {
        grouped.pending.push(item);
      }
      return grouped;
    }, { pending: [], applied: [] });
  }

  _renderRecommendationSection(title, recommendationItems) {
    return this._recommendationCards.renderSection(title, recommendationItems);
  }

  _renderRecommendationSectionContent(title, recommendationItems) {
    if (!recommendationItems.length) {
      return "";
    }
    return `
      <section class="panel">
        <h2>${this._escape(title)}</h2>
        <div class="entity-list">
          ${recommendationItems.map(({ recommendation, originalIndex }) => `
            <div class="metric">
              <strong>${this._escape(recommendation.display_label || recommendation.title || "Suggested setting")}</strong>
              ${recommendation.summary ? `<p class="muted">${this._escape(recommendation.summary)}</p>` : ""}
              ${recommendation.reason ? `<p class="muted">${this._escape(recommendation.reason)}</p>` : ""}
              ${this._recommendationValueRows(recommendation)}
              ${recommendation.expected_effect ? `<p class="muted">Expected effect: ${this._escape(recommendation.expected_effect)}</p>` : ""}
              ${recommendation.evidence_preview ? `<p class="muted">Evidence: ${this._escape(recommendation.evidence_preview)}</p>` : ""}
                <div class="actions">
                 ${recommendation.actions && recommendation.actions.preview ? this._recommendationActionButton(recommendation, originalIndex, "preview", "Preview evidence", true) : ""}
                 ${this._recommendationActionButton(recommendation, originalIndex, "apply", "Apply")}
                 ${this._recommendationActionButton(recommendation, originalIndex, "dismiss", "Dismiss", true)}
                 ${recommendation.actions && recommendation.actions.undo ? this._recommendationActionButton(recommendation, originalIndex, "undo", "Undo", true) : ""}
                 ${recommendation.actions && recommendation.actions.reset ? this._recommendationActionButton(recommendation, originalIndex, "reset", "Reset default", true) : ""}
                </div>
            </div>
          `).join("")}
        </div>
      </section>
    `;
  }

  _renderSelectedRecommendationEvidence() {
    const recommendation = this._payload && this._payload.selected_recommendation;
    if (!recommendation) {
      return "";
    }
    const label = recommendation.display_label || recommendation.title || "Suggested setting";
    const evidenceCount = Number(recommendation.evidence_key_count || 0);
    const omittedCount = Number(recommendation.evidence_omitted_key_count || 0);
    const evidenceSummary = recommendation.evidence_preview
      ? `<p>${this._escape(recommendation.evidence_preview)}</p>`
      : `<p class="muted">No compact evidence summary is available for this recommendation.</p>`;
    const countSummary = evidenceCount > 0
      ? `<p class="muted">${this._escape(evidenceCount)} evidence fields were captured${omittedCount > 0 ? `; ${this._escape(omittedCount)} are hidden from this compact preview.` : "."}</p>`
      : "";
    return `
      <section class="panel">
        <h2>Recommendation Evidence</h2>
        <p class="muted">Previewing evidence for ${this._escape(label)}.</p>
        ${recommendation.reason ? `<p class="muted">${this._escape(recommendation.reason)}</p>` : ""}
        ${this._recommendationValueRows(recommendation)}
        ${evidenceSummary}
        ${countSummary}
      </section>
    `;
  }

  _recommendationValueRows(recommendation) {
    const status = String((recommendation && recommendation.status) || "pending");
    const applied = status === "applied";
    const currentValue = applied && recommendation.suggested_value !== undefined ? recommendation.suggested_value : recommendation.current_value;
    const suggestedValue = applied ? undefined : recommendation.suggested_value;
    const rows = [];
    if (currentValue !== undefined) {
      rows.push(`<code>Current: ${this._escape(currentValue)}</code>`);
    }
    if (recommendation.default_value !== undefined) {
      rows.push(`<code>Default: ${this._escape(recommendation.default_value)}</code>`);
    }
    if (suggestedValue !== undefined) {
      rows.push(`<code>Suggested: ${this._escape(suggestedValue)}</code>`);
    }
    return rows.length ? `<div class="entity-list">${rows.join("")}</div>` : "";
  }

  _renderNilmMergeTarget(signature, index) {
    const action = signature && signature.actions && signature.actions.merge;
    const options = action && action.target_options;
    if (!options || !options.length) {
      return `<p class="muted">No other signature is available to merge into yet.</p>`;
    }
    const omittedCount = Number((action && action.target_options_omitted_count) || 0);
    const summary = omittedCount > 0
      ? `<p class="muted">Showing ${options.length} of ${action.target_option_count} merge targets. ${omittedCount} more can be selected after loading the full slim NILM list. <button type="button" class="secondary" data-load-all-nilm>Load all merge targets</button></p>`
      : "";
    return `
      <span class="muted">Merge into</span>
      ${summary}
      <div class="merge-targets" id="nilm_merge_targets_${index}" data-selected="">
        ${options.map((option) => this._nilmMergeTargetChip(index, option)).join("")}
      </div>
    `;
  }

  _loadExpandedNilm() {
    const routeUrl = new URL(this._routeKey(), window.location.origin);
    routeUrl.searchParams.set(EXPAND_NILM_QUERY_PARAM, "1");
    history.replaceState(null, "", `${routeUrl.pathname}${routeUrl.search}${routeUrl.hash}`);
  }

  _nilmMergeTargetChip(index, option) {
    return `
      <button
        type="button"
        class="merge-target-chip"
        data-nilm-index="${index}"
        data-nilm-merge-target="${this._escape(option.value)}"
        aria-pressed="false"
      >${this._escape(option.label)}</button>
    `;
  }

  _selectNilmMergeTarget(index, target) {
    const targetList = this.shadowRoot.querySelector(`#nilm_merge_targets_${index}`);
    if (!targetList || !target) {
      return;
    }
    targetList.dataset.selected = target;
    for (const button of targetList.querySelectorAll("[data-nilm-merge-target]")) {
      button.setAttribute(
        "aria-pressed",
        button.dataset.nilmMergeTarget === target ? "true" : "false",
      );
    }
  }

  _renderNilmExistingAssignmentField(action, key) {
    const options = action && Array.isArray(action.assignment_options)
      ? action.assignment_options
      : [];
    if (!options.length) {
      return "";
    }
    return `
      <label class="nilm-label-field">
        <span class="muted">Existing appliance</span>
        <select data-nilm-existing-assignment="${this._escape(key)}">
          <option value="">New appliance</option>
          ${options.map((option) => `<option value="${this._escape(option.value || "")}">${this._escape(option.label || option.value || "")}</option>`).join("")}
        </select>
      </label>
    `;
  }

  _nilmExistingAssignmentSelection(key) {
    const select = this.shadowRoot.querySelector(`[data-nilm-existing-assignment="${key}"]`);
    const assignmentId = select ? String(select.value || "").trim() : "";
    if (!assignmentId) {
      return null;
    }
    const option = select.selectedOptions && select.selectedOptions[0];
    return {
      assignment_id: assignmentId,
      label: String((option && option.textContent) || assignmentId).trim(),
    };
  }

  _renderNilmWorkspace() {
    return this._nilmWorkspaceComponent.render();
  }

  _renderNilmWorkspaceContent() {
    if (this._nilmWorkspaceLoading) {
      return `<section class="panel"><h2>NILM Workspace</h2><p class="muted">Loading NILM workspace...</p></section>`;
    }
    const workspace = this._nilmWorkspace;
    if (this._nilmWorkspaceError && (!workspace || workspace.status !== "ok")) {
      return `<section class="panel error"><h2>NILM Workspace</h2><p>${this._escape(this._nilmWorkspaceError)}</p></section>`;
    }
    if (workspace && workspace.status !== "ok") {
      return `<section class="panel"><h2>NILM Workspace</h2><p class="muted">${this._escape(workspace.message || "No NILM workspace is available for this circuit.")}</p></section>`;
    }
    if (!workspace || workspace.status !== "ok") {
      return "";
    }
    const history = workspace.history || {};
    const graphWindow = this._nilmWorkspaceGraphWindow(workspace);
    const series = this._visibleNilmWorkspaceSeries(workspace, graphWindow);
    const graphSessions = this._nilmFocusedSignature
      ? (workspace.sessions || []).filter((item) => item.signature_fingerprint === this._nilmFocusedSignature)
      : workspace.sessions;
    const nextReviewItem = this._nilmReviewItems(workspace)[0];
    const nextReviewIndex = nextReviewItem ? nextReviewItem.index : -1;
    const graph = graphWindow && series.length
      ? this._chartSvg(series, { graph_window_start: new Date(graphWindow.start).toISOString(), graph_window_end: new Date(graphWindow.end).toISOString(), nilm_select_interval: true, nilm_edges: workspace.edges, nilm_sessions: graphSessions })
      : `<p class="muted">No NILM workspace history samples were available for this graph window.</p>`;
    return `
      <section class="panel">
        <h2>NILM Workspace</h2>
        <p class="muted">Review mains load changes, labels, and assignments used by NILM.</p>
        ${this._nilmWorkspaceError ? `<p class="muted">${this._escape(this._nilmWorkspaceError)}</p>` : ""}
        ${this._nilmFocusedSignature ? `<p class="muted">Showing graph sessions matching selected signature.</p>` : ""}
        ${this._renderNilmReviewQueue(workspace)}
        ${this._renderNilmWorkspaceLanes(workspace)}
        ${this._renderNilmSessionValidationCards(workspace)}
        ${this._renderNilmWorkspaceList("NILM Signatures", workspace.signatures, "No NILM signatures are available yet.", (item, index) => `
          <div class="metric">
            <span>${this._escape(item.review_state || `${Math.round(Number(item.confidence || 0) * 100)}% confidence`)}</span>
            <strong>${this._escape(item.display_label || item.display_name || item.likely_type || "Unknown load")}</strong>
            ${this._renderNilmSignatureFacts(item)}
            ${index === nextReviewIndex ? `<p class="muted">Use Needs review above for this signature's actions.</p>` : this._renderNilmSignatureReview(item, index)}
          </div>
        `, "Signatures group similar sessions that may be the same appliance.")}
        ${this._renderNilmLabelIntervals(workspace)}
        ${this._renderNilmWorkspaceList("Estimated Appliances", workspace.virtual_appliances, "No estimated appliances are available yet.", (item) => `
          <div class="metric">
            <span>${this._escape(item.model_status || "candidate")}</span>
            <strong>${this._escape(item.display_name || item.appliance_id || "Estimated appliance")} - ${this._escape(item.is_running ? "running" : "idle")}</strong>
            <p class="muted" data-field="estimated_daily_energy">${this._escape(this._formatMetricValue(item.estimated_power_w))} W, ${this._escape(this._formatMetricValue(item.estimated_energy_kwh_today))} kWh today, confidence ${this._escape(Math.round(Number(item.confidence || 0) * 100))}%</p>
            <div class="actions">${this._nilmApplianceDetailButton(item)}</div>
          </div>
        `, "Estimated appliances are NILM's current best grouped load guesses.")}
        ${this._renderNilmWorkspaceList("Appliance Assignments", workspace.assignments, "No appliance assignments are saved yet.", (item, index) => `
          <div class="metric">
            <span>${this._escape(item.lifecycle_state || "assigned")}</span>
            <strong>${this._escape(item.display_name || item.appliance_id || "Assigned appliance")}</strong>
            <p class="muted">Confidence ${this._escape(Math.round(Number(item.confidence || 0) * 100))}%</p>
            <p class="muted">False positives ${this._escape(Math.round(Number(item.false_positive_rate || 0) * 100))}%, False negatives ${this._escape(Math.round(Number(item.false_negative_rate || 0) * 100))}%</p>
            <p class="muted">Median power error ${this._escape(this._formatMetricValue(item.median_power_error))} W, Energy error ${this._escape(this._formatMetricValue(item.energy_estimate_error))} kWh</p>
            ${this._renderNilmAssignmentEditFields(item, index)}
            ${this._renderNilmAssignmentActions(item, index)}
          </div>
        `, "Assignments save a signature as a named appliance for future review.")}
        ${this._renderNilmOverlayToggles(workspace)}
        ${this._renderNilmGraphControls(graphWindow)}
        ${graph}
        ${this._renderNilmValidation(workspace.validation)}
        ${this._renderNilmWorkspaceList("Known Load Overlays", workspace.known_load_overlays, "No known-load overlays are configured.", (item) => `
          <div class="metric">
            <span>${this._escape(item.circuit_id)}</span>
            <strong>${this._escape(item.name || item.circuit_id)}</strong>
            <p class="muted">${this._escape(this._overlayEntitySummary(item))}</p>
          </div>
        `, "Known loads mark configured circuits so NILM can separate expected usage.")}
        ${this._renderNilmWorkspaceList("Solar/Net Overlays", workspace.solar_overlays, "No solar or net-flow overlays are configured.", (item) => `
          <div class="metric">
            <span>${this._escape(item.circuit_id)}</span>
            <strong>${this._escape(item.name || item.circuit_id)}</strong>
            <p class="muted">${this._escape(this._overlayEntitySummary(item))}</p>
          </div>
        `, "Solar and net-flow overlays help explain import/export changes on mains.")}
        ${this._renderNilmWorkspaceList("NILM Sessions", workspace.sessions, "No paired NILM sessions are available yet.", (item, index) => `
          <div class="metric">
            <span>${this._escape(item.start || "")}</span>
            <strong>${this._escape(this._formatMetricValue(item.median_power_w))} W, confidence ${this._escape(Math.round(Number(item.confidence || 0) * 100))}%</strong>
            <p class="muted">${this._escape(item.end ? `Ended ${item.end}` : "Open session")}</p>
            ${item.actions && item.actions.assign ? this._renderNilmSessionAssignField(item, index) : ""}
            ${item.actions ? `<div class="actions">
              ${item.actions.assign ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="assign" ${this._busyAction === `nilm_sessions_${index}_assign` ? "disabled" : ""}>Assign Appliance</button>` : ""}
              ${item.actions.validate ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="validate" ${this._busyAction === `nilm_sessions_${index}_validate` ? "disabled" : ""}>Confirm Appliance</button>` : ""}
              ${item.actions.reject ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="reject" ${this._busyAction === `nilm_sessions_${index}_reject` ? "disabled" : ""}>Wrong Appliance</button>` : ""}
            </div>` : ""}
          </div>
        `, "Sessions pair on/off edges into likely appliance runs.")}
        ${this._renderNilmWorkspaceList("NILM Edges", workspace.edges, "No NILM edges are available yet.", (item) => `
          <div class="metric">
            <span>${this._escape(item.timestamp || "")}</span>
            <strong>${this._escape(this._friendlyFeature(item.direction))}: ${this._escape(this._formatMetricValue(item.delta_w))} W</strong>
            <p class="muted">${this._escape(item.split_phase_type || "unknown")}</p>
          </div>
        `, "Edges are detected power changes before they are paired into sessions.")}
      </section>
    `;
  }

  _nilmReviewItems(workspace) {
    const signatures = Array.isArray(workspace && workspace.signatures) ? workspace.signatures : [];
    const doneStates = new Set(["expected", "ignored", "confirmed"]);
    return signatures.map((signature, index) => ({ signature, index })).filter(({ signature }) => {
      const state = String((signature && signature.review_state) || "").toLowerCase();
      return !(signature && signature.user_label) && !doneStates.has(state);
    });
  }

  _renderNilmReviewQueue(workspace) {
    const reviewItems = this._nilmReviewItems(workspace);
    if (!reviewItems.length) {
      return `
        <div class="action-group">
          <h3>Needs review</h3>
          <p class="muted">No signatures need labels or decisions.</p>
        </div>
      `;
    }
    const { signature, index } = reviewItems[0];
    const count = reviewItems.length;
    const title = signature.display_label || signature.display_name || signature.likely_type || "Unknown load";
    return `
      <div class="action-group">
        <h3>Needs review</h3>
        <p class="muted">${this._escape(count)} ${count === 1 ? "signature needs" : "signatures need"} labels or decisions.</p>
        <div class="metric">
          <span>Next to review</span>
          <strong>${this._escape(title)}</strong>
          ${signature.confidence !== undefined ? `<p class="muted">Confidence ${this._escape(Math.round(Number(signature.confidence || 0) * 100))}%</p>` : ""}
          ${this._renderNilmSignatureFacts(signature)}
          ${this._renderNilmSignatureReview(signature, index)}
        </div>
      </div>
    `;
  }

  _renderNilmWorkspaceLanes(workspace) {
    const lanes = workspace && workspace.lanes && typeof workspace.lanes === "object"
      ? workspace.lanes
      : {};
    const laneCounts = workspace && workspace.lane_counts && typeof workspace.lane_counts === "object"
      ? workspace.lane_counts
      : {};
    const laneOrder = [
      ["needs_review", "Needs Review"],
      ["assigned", "Assigned"],
      ["needs_validation", "Needs Validation"],
      ["ready_to_publish", "Ready to Publish"],
      ["published", "Published"],
      ["ignored_expected", "Ignored / Expected"],
    ];
    if (!Object.keys(lanes).length && !Object.keys(laneCounts).length) {
      return "";
    }
    return `
      <div class="action-group">
        <h3>Review lanes</h3>
        <div class="summary">
          ${laneOrder.map(([key, fallbackLabel]) => {
            const lane = lanes[key] || {};
            const countValue = Number(laneCounts[key]);
            const count = Number.isFinite(countValue)
              ? countValue
              : (Array.isArray(lane.assignment_ids) ? lane.assignment_ids.length : 0)
                + (Array.isArray(lane.signature_ids) ? lane.signature_ids.length : 0);
            return `
              <div class="metric">
                <span>${this._escape(lane.label || fallbackLabel)}</span>
                <strong>${this._escape(count)} ${count === 1 ? "item" : "items"}</strong>
              </div>
            `;
          }).join("")}
        </div>
      </div>
    `;
  }

  _renderNilmSessionValidationCards(workspace) {
    const sessions = Array.isArray(workspace && workspace.sessions)
      ? workspace.sessions
      : [];
    const reviewedSessionIds = this._nilmReviewedSessionIds(workspace);
    const cards = sessions.map((session, index) => ({ session, index })).filter(({ session }) => {
      const actions = session && session.actions;
      const sessionId = String(session && session.session_id || "").trim();
      return session
        && session.assignment_id
        && (!sessionId || !reviewedSessionIds.has(sessionId))
        && actions
        && (actions.validate || actions.reject);
    }).slice(0, 5);
    if (!cards.length) {
      return "";
    }
    return `
      <h3>Session Validation</h3>
      <div class="entity-list">
        ${cards.map(({ session, index }) => this._renderNilmSessionValidationCard(workspace, session, index)).join("")}
      </div>
    `;
  }

  _nilmReviewedSessionIds(workspace) {
    const reviewed = new Set();
    const assignments = Array.isArray(workspace && workspace.assignments)
      ? workspace.assignments
      : [];
    for (const assignment of assignments) {
      for (const key of ["confirmed_session_ids", "rejected_session_ids"]) {
        const ids = Array.isArray(assignment && assignment[key]) ? assignment[key] : [];
        for (const id of ids) {
          const sessionId = String(id || "").trim();
          if (sessionId) {
            reviewed.add(sessionId);
          }
        }
      }
    }
    return reviewed;
  }

  _renderNilmSessionValidationCard(workspace, session, index) {
    const actions = session && session.actions ? session.actions : {};
    const label = session.display_label || session.display_name || session.appliance_id || session.assignment_id || "appliance";
    const confidence = session.confidence !== undefined
      ? `<p class="muted">Confidence ${this._escape(this._formatConfidence(session.confidence))}</p>`
      : "";
    const lowConfidence = this._isLowNilmConfidence(session.confidence)
      ? `<p class="muted">Low confidence</p>`
      : "";
    const duration = this._nilmSessionDuration(session);
    const ignoreIndex = this._nilmSignatureIndexForSession(workspace, session);
    const ignoreSignature = ignoreIndex >= 0 && workspace.signatures
      ? workspace.signatures[ignoreIndex]
      : null;
    return `
      <div class="metric">
        <span>${this._escape(this._formatNilmSessionRange(session))}</span>
        <strong>Predicted ${this._escape(label)}</strong>
        <p class="muted">Estimated by NILM${duration ? `, ${this._escape(duration)}` : ""}</p>
        ${confidence}
        ${lowConfidence}
        <p class="muted">${this._escape(this._formatMetricValue(session.median_power_w))} W, ${this._escape(this._formatMetricValue(session.estimated_energy_kwh))} kWh estimated</p>
        <div class="actions">
          ${actions.validate ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="validate" ${this._busyAction === `nilm_sessions_${index}_validate` ? "disabled" : ""}>Correct</button>` : ""}
          ${actions.reject ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="reject" ${this._busyAction === `nilm_sessions_${index}_reject` ? "disabled" : ""}>Wrong appliance</button>` : ""}
          ${session.start && session.end ? `<button type="button" class="secondary" data-nilm-session-interval-index="${index}">Adjust Interval</button>` : ""}
          ${ignoreSignature && ignoreSignature.actions && ignoreSignature.actions.ignore ? this._nilmActionButton(ignoreIndex, "ignore", "Ignore Similar", true) : ""}
        </div>
      </div>
    `;
  }

  _nilmSessionDuration(session) {
    const explicitDuration = Number(session && session.duration_seconds);
    if (Number.isFinite(explicitDuration)) {
      return this._formatDuration(explicitDuration);
    }
    const start = Date.parse(session && session.start || "");
    const end = Date.parse(session && session.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return "";
    }
    return this._formatDuration((end - start) / 1000);
  }

  _formatNilmSessionRange(session) {
    const start = this._formatDateTime(session && session.start);
    if (!session || !session.end) {
      return `${start} - open`;
    }
    return `${start} - ${this._formatDateTime(session.end)}`;
  }

  _nilmSignatureIndexForSession(workspace, session) {
    const fingerprint = String(session && session.signature_fingerprint || "").trim();
    if (!fingerprint || !Array.isArray(workspace && workspace.signatures)) {
      return -1;
    }
    return workspace.signatures.findIndex((signature) => (
      this._nilmSignatureFingerprint(signature) === fingerprint
    ));
  }

  _renderNilmSignatureFacts(signature) {
    const facts = [];
    const addFact = (label, value) => {
      if (value !== null && value !== undefined && value !== "") {
        facts.push([label, value]);
      }
    };
    addFact("Typical power", signature.typical_power_w !== undefined ? `${this._formatMetricValue(signature.typical_power_w)} W` : undefined);
    addFact("Typical duration", signature.typical_duration_seconds !== undefined ? this._formatDuration(signature.typical_duration_seconds) : undefined);
    addFact("Seen count", signature.seen_count);
    addFact("Voltage class", signature.voltage_class);
    addFact("Dominant leg", signature.dominant_leg);
    addFact("Known-load overlap", this._formatNilmSignatureFact(signature.known_load_overlap));
    addFact("Why grouped", signature.why_grouped);
    addFact("Last seen", signature.last_seen ? this._formatDateTime(signature.last_seen) : undefined);
    if (!facts.length) {
      return "";
    }
    return facts.map(([label, value]) => `<p class="muted">${this._escape(label)}: ${this._escape(this._formatMetricValue(value))}</p>`).join("");
  }

  _formatNilmSignatureFact(value) {
    if (Array.isArray(value)) {
      return value.join(", ");
    }
    if (value && typeof value === "object") {
      return JSON.stringify(value);
    }
    return value;
  }

  _renderNilmLabelIntervals(workspace) {
    const draft = this._nilmLabelIntervalDraft || {};
    const intervals = Array.isArray(workspace && workspace.label_intervals)
      ? workspace.label_intervals
      : [];
    const sensorAction = workspace && workspace.actions && workspace.actions.sensor_label_interval;
    const groundTruthOptions = sensorAction && Array.isArray(sensorAction.ground_truth_options)
      ? sensorAction.ground_truth_options
      : [];
    const saveBusy = this._busyAction === "nilm_label_interval_save" ? "disabled" : "";
    const generateBusy = this._busyAction === "nilm_label_interval_generate_sensor" || !groundTruthOptions.length ? "disabled" : "";
    const intervalPreview = this._nilmLabelIntervalEnergyPreview();
    return `
      <h3>Manual Labels</h3>
      <p class="muted">Manual labels teach NILM which appliance was running during a time range.</p>
      <div class="metric">
        <p class="muted"><strong>Was this appliance running here?</strong> Review the selected graph window, then save the appliance name if the interval matches.</p>
        <div class="nilm-interval-form">
          <label>
            <span class="muted">Start</span>
            <input type="datetime-local" data-nilm-label-interval-input="start" value="${this._escape(draft.start || "")}">
          </label>
          <label>
            <span class="muted">End</span>
            <input type="datetime-local" data-nilm-label-interval-input="end" value="${this._escape(draft.end || "")}">
          </label>
          <label>
            <span class="muted">Label</span>
            <input type="text" data-nilm-label-interval-input="label" value="${this._escape(draft.label || "")}" placeholder="Appliance name">
          </label>
          <label>
            <span class="muted">Ground Truth Sensor</span>
            ${groundTruthOptions.length ? `<select data-nilm-label-interval-input="ground_truth_entity_id">
              <option value="">Select sensor</option>
              ${groundTruthOptions.map((option) => `<option value="${this._escape(option.value || "")}" ${String(option.value || "") === String(draft.ground_truth_entity_id || "") ? "selected" : ""}>${this._escape(option.label || option.value || "")}</option>`).join("")}
            </select>` : `<p class="muted">No ground-truth sensors are available from known-load circuits.</p>`}
          </label>
        </div>
        <div class="actions">
          <button type="button" data-nilm-label-interval-action="save" ${saveBusy}>Save Interval</button>
          <button type="button" class="secondary" data-nilm-label-interval-action="generate_sensor" ${generateBusy}>Generate From Sensor</button>
        </div>
        ${intervalPreview ? `<p class="muted" data-field="nilm_interval_energy_preview">Estimated energy ${this._escape(this._formatNumber(intervalPreview.energy_kwh))} kWh over ${this._escape(this._formatNumber(intervalPreview.duration_minutes))} minutes from ${this._escape(intervalPreview.source_name)}.</p>` : ""}
      </div>
      ${intervals.length ? `<div class="entity-list">${intervals.map((item, index) => `
        <div class="metric">
          <span>${this._escape(item.start || "")} - ${this._escape(item.end || "")}</span>
          <strong>${this._escape(item.label || item.appliance_id || "Labeled interval")}</strong>
          ${item.mains_entity_id ? `<p class="muted">${this._escape(item.mains_entity_id)}</p>` : ""}
          ${item.ground_truth_entity_id ? `<p class="muted">Ground Truth Sensor: ${this._escape(item.ground_truth_entity_id)}</p>` : ""}
          ${item.actions && item.actions.assign ? this._renderNilmExistingAssignmentField(item.actions.assign, `label_intervals_${index}`) : ""}
          <div class="actions">
            ${item.actions && item.actions.assign ? `<button
              type="button"
              class="secondary"
              data-nilm-label-interval-index="${index}"
              data-nilm-label-interval-action="assign"
              ${this._busyAction === `nilm_label_interval_${index}_assign` ? "disabled" : ""}
            >Assign Appliance</button>` : ""}
            <button
              type="button"
              class="secondary"
              data-nilm-label-interval-index="${index}"
              data-nilm-label-interval-action="adjust"
            >Adjust Label</button>
            <button
              type="button"
              class="secondary"
              data-nilm-label-interval-index="${index}"
              data-nilm-label-interval-action="delete"
              ${this._busyAction === `nilm_label_interval_${index}_delete` ? "disabled" : ""}
            >Delete Label</button>
          </div>
        </div>
      `).join("")}</div>` : `<p class="muted">No manual NILM labels are saved yet.</p>`}
    `;
  }

  _nilmLabelIntervalEnergyPreview() {
    const draft = this._nilmLabelIntervalDraft || {};
    const start = new Date(draft.start || "").getTime();
    const end = new Date(draft.end || "").getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return null;
    }
    const series = this._chartSeries(this._nilmWorkspaceHistorySeries);
    const powerSeries = series.find((item) => {
      const label = `${item.entity_id || ""} ${item.name || ""}`;
      return /power|watt|(?:^|[_\s-])w(?:$|[_\s-])/i.test(label);
    });
    const points = powerSeries && Array.isArray(powerSeries.points)
      ? powerSeries.points.filter((point) => point.time >= start && point.time <= end)
      : [];
    if (points.length < 2) {
      return null;
    }
    let wattHours = 0;
    for (let index = 1; index < points.length; index += 1) {
      const previous = points[index - 1];
      const current = points[index];
      const hours = (current.time - previous.time) / 3600000;
      if (hours > 0) {
        wattHours += ((previous.value + current.value) / 2) * hours;
      }
    }
    if (!Number.isFinite(wattHours)) {
      return null;
    }
    return {
      energy_kwh: Math.max(wattHours / 1000, 0),
      duration_minutes: (end - start) / 60000,
      source_name: powerSeries.name || powerSeries.entity_id || "displayed power samples",
    };
  }

  _renderNilmSessionAssignField(session, index) {
    const draftKey = this._nilmSessionLabelDraftKey(session);
    const currentLabel = this._nilmSessionLabelDrafts.has(draftKey)
      ? this._nilmSessionLabelDrafts.get(draftKey)
      : "";
    return `
      ${this._renderNilmExistingAssignmentField(session && session.actions && session.actions.assign, `sessions_${index}`)}
      <label class="nilm-label-field" for="nilm_session_label_${index}">
        <span class="muted">Appliance name</span>
        <input
          id="nilm_session_label_${index}"
          type="text"
          data-nilm-session-label-input
          data-nilm-session-label-key="${this._escape(draftKey)}"
          value="${this._escape(currentLabel)}"
          placeholder="Appliance name"
        >
      </label>
    `;
  }

  _nilmSessionLabelDraftKey(session) {
    return String((session && session.session_id) || "");
  }

  _renderNilmAssignmentEditFields(item, index) {
    const actions = item && item.actions;
    if (!actions || (!actions.rename && !actions.change_profile && !actions.merge)) {
      return "";
    }
    const draftKey = this._nilmAssignmentDraftKey(item);
    const label = this._nilmAssignmentDraftValue(draftKey, "label", item.display_name || "");
    const profile = this._nilmAssignmentDraftValue(draftKey, "appliance_profile", item.appliance_profile || "");
    const profileOptions = actions.change_profile && Array.isArray(actions.change_profile.profile_options)
      ? actions.change_profile.profile_options
      : [];
    return `
      <div class="grid">
        ${actions.rename ? `<label class="nilm-label-field" for="nilm_assignment_label_${index}">
          <span class="muted">Appliance name</span>
          <input id="nilm_assignment_label_${index}" type="text" data-nilm-assignment-input data-nilm-assignment-key="${this._escape(draftKey)}" data-nilm-assignment-field="label" value="${this._escape(label)}" placeholder="Appliance name">
        </label>` : ""}
        ${actions.change_profile ? `<label class="nilm-label-field" for="nilm_assignment_profile_${index}">
          <span class="muted">Appliance type</span>
          <select id="nilm_assignment_profile_${index}" data-nilm-assignment-input data-nilm-assignment-key="${this._escape(draftKey)}" data-nilm-assignment-field="appliance_profile">
            ${profileOptions.map((option) => `<option value="${this._escape(option.value || "")}" ${String(option.value || "") === String(profile) ? "selected" : ""}>${this._escape(option.label || option.value || "")}</option>`).join("")}
          </select>
        </label>` : ""}
        ${actions.merge ? `<label class="nilm-label-field" for="nilm_assignment_merge_target_${index}">
          <span class="muted">Merge into</span>
          <select id="nilm_assignment_merge_target_${index}" data-nilm-assignment-merge-target>
            <option value="">Do not merge</option>
            ${(actions.merge.target_options || []).map((option) => `<option value="${this._escape(option.value || "")}">${this._escape(option.label || option.value || "")}</option>`).join("")}
          </select>
        </label>` : ""}
      </div>
    `;
  }

  _nilmAssignmentDraftKey(item) {
    return String((item && item.assignment_id) || "");
  }

  _nilmAssignmentDraftValue(draftKey, field, fallback) {
    const key = `${draftKey}:${field}`;
    return this._nilmAssignmentDrafts.has(key)
      ? this._nilmAssignmentDrafts.get(key)
      : fallback;
  }

  _renderNilmAssignmentActions(item, index) {
    const actions = item && item.actions;
    const detailButton = this._nilmApplianceDetailButton(item);
    if ((!actions || !Object.keys(actions).length) && !detailButton) {
      return "";
    }
    if (!actions || !Object.keys(actions).length) {
      return `<div class="actions">${detailButton}</div>`;
    }
    const hasSave = actions.rename || actions.change_profile || actions.merge;
    return `
      <div class="actions">
        ${detailButton}
        ${hasSave ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="save" ${this._busyAction === `nilm_assignments_${index}_save` ? "disabled" : ""}>Save Assignment</button>` : ""}
        ${actions.validate_history ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="validate_history" ${this._busyAction === `nilm_assignments_${index}_validate_history` ? "disabled" : ""}>Validate History</button>` : ""}
        ${actions.publish ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="publish" ${this._busyAction === `nilm_assignments_${index}_publish` ? "disabled" : ""}>Publish Entities</button>` : ""}
        ${actions.unpublish ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="unpublish" ${this._busyAction === `nilm_assignments_${index}_unpublish` ? "disabled" : ""}>Disable Publishing</button>` : ""}
        ${actions.retire ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="retire" ${this._busyAction === `nilm_assignments_${index}_retire` ? "disabled" : ""}>Remove Assignment</button>` : ""}
      </div>
    `;
  }

  _nilmApplianceDetailButton(item) {
    const path = item && item.appliance_detail_path;
    if (!path) {
      return "";
    }
    return `<button type="button" class="secondary" data-nilm-appliance-detail-path="${this._escape(path)}">Open Appliance Detail</button>`;
  }

  _renderNilmValidation(validation) {
    if (!validation) {
      return "";
    }
    const metrics = validation.metrics || {};
    const preview = Array.isArray(validation.prediction_preview)
      ? validation.prediction_preview
      : [];
    return `
      <h3>Validation</h3>
      <p class="muted">Validation compares saved labels with NILM's predicted sessions.</p>
      <div class="summary">
        <div class="metric">
          <span>Ground truth</span>
          <strong>${this._escape(metrics.ground_truth_interval_count || 0)}</strong>
        </div>
        <div class="metric">
          <span>Precision</span>
          <strong>${this._escape(Math.round(Number(metrics.precision || 0) * 100))}%</strong>
        </div>
        <div class="metric">
          <span>Recall</span>
          <strong>${this._escape(Math.round(Number(metrics.recall || 0) * 100))}%</strong>
        </div>
      </div>
      ${this._renderNilmWorkspaceList("Prediction Preview", preview, "No ground-truth sensor intervals are saved yet.", (item) => `
        <div class="metric">
          <span>${this._escape(item.ground_truth_entity_id || "")}</span>
          <strong>${this._escape(item.label || "Ground truth")} - ${this._escape(item.prediction_status || "missed")}</strong>
          <p class="muted">${this._escape(item.matched_assignment_id || "No matching NILM prediction")} ${this._escape(this._formatMetricValue(item.overlap_seconds))} seconds overlap</p>
        </div>
      `, "Preview compares saved labels with NILM's predicted sessions.")}
    `;
  }

  _renderNilmWorkspaceList(title, items, emptyText, renderItem, description = "") {
    const safeItems = Array.isArray(items) ? items : [];
    return `
      <h3>${this._escape(title)}</h3>
      ${description ? `<p class="muted">${this._escape(description)}</p>` : ""}
      ${safeItems.length ? `<div class="entity-list">${safeItems.map(renderItem).join("")}</div>` : `<p class="muted">${this._escape(emptyText)}</p>`}
    `;
  }

  _overlayEntitySummary(item) {
    const count = (item.entity_ids || []).filter((entityId) => String(entityId || "").trim()).length;
    return count === 1 ? "1 sensor" : `${count} sensors`;
  }

  _renderSafetyNotice(alert) {
    if (!alert.safety_notice) {
      return "";
    }
    return `
      <section class="panel safety-notice">
        <h2>Safety Notice</h2>
        <p>${this._escape(alert.safety_notice)}</p>
      </section>
    `;
  }

  _renderChart(alert) {
    if (this._historyLoading) {
      return `<p class="muted">Loading history samples...</p>`;
    }
    if (this._historyError) {
      return `<p class="muted">${this._escape(this._historyError)}</p>`;
    }
    const series = this._chartSeries();
    if (!series.length) {
      return `<p class="muted">No history samples were available for this graph window.</p>`;
    }
    return this._chartSvg(series, alert);
  }

  _chartSvg(series, alert) {
    const width = 900;
    const height = 320;
    const padLeft = 54;
    const padRight = 24;
    const padTop = 18;
    const padBottom = 42;
    const allPoints = [];
    for (const item of series) {
      for (const point of item.points) {
        allPoints.push(point);
      }
    }
    const sampleMinTime = Math.min(...allPoints.map((point) => point.time));
    const sampleMaxTime = Math.max(...allPoints.map((point) => point.time));
    const graphStart = Date.parse(alert.graph_window_start);
    const graphEnd = Date.parse(alert.graph_window_end);
    const minTime = Number.isFinite(graphStart) ? graphStart : sampleMinTime;
    const maxTime = Number.isFinite(graphEnd) && graphEnd > minTime ? graphEnd : sampleMaxTime;
    const minValue = Math.min(...allPoints.map((point) => point.value));
    const maxValue = Math.max(...allPoints.map((point) => point.value));
    const timeRange = Math.max(maxTime - minTime, 1);
    const valueRange = Math.max(maxValue - minValue, 1);
    const x = (time) => padLeft + ((time - minTime) / timeRange) * (width - padLeft - padRight);
    const y = (value) => padTop + (1 - ((value - minValue) / valueRange)) * (height - padTop - padBottom);

    const lines = series.map((item, index) => {
      const color = CHART_COLORS[index % CHART_COLORS.length];
      const points = item.points.map((point) => `${x(point.time).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
      const circles = item.points.map((point) => `<circle cx="${x(point.time).toFixed(1)}" cy="${y(point.value).toFixed(1)}" r="3" fill="${color}"></circle>`).join("");
      return `<polyline fill="none" stroke="${color}" stroke-width="2.5" points="${points}"></polyline>${circles}`;
    }).join("");
    const legend = series.map((item, index) => {
      const color = CHART_COLORS[index % CHART_COLORS.length];
      return `<div class="legend-item"><span class="swatch" style="background:${color}"></span><strong>${this._escape(item.name)}</strong></div>`;
    }).join("");
    const minLabel = this._formatNumber(minValue);
    const maxLabel = this._formatNumber(maxValue);
    const timeTicks = this._chartTimeTicks(minTime, maxTime, x);
    const timeGridLines = timeTicks.slice(1, -1).map((tick) => `<line class="grid time-grid" x1="${tick.x}" y1="${padTop}" x2="${tick.x}" y2="${height - padBottom}"></line>`).join("");
    const timeTickLabels = timeTicks.map((tick) => `<text x="${tick.x}" y="${height - 12}" text-anchor="${tick.anchor}">${this._escape(tick.label)}</text>`).join("");
    const yAxisLabel = alert.y_axis_label ? `<text class="axis-label" transform="translate(16 ${((height + padTop - padBottom) / 2).toFixed(1)}) rotate(-90)" text-anchor="middle">${this._escape(alert.y_axis_label)}</text>` : "";
    const timeZoneLabel = this._timeZone();
    const edgeItems = (Array.isArray(alert.nilm_edges) ? alert.nilm_edges : []).map((edge) => {
      const markerTime = Date.parse(edge && edge.timestamp || "");
      if (!Number.isFinite(markerTime) || markerTime < minTime || markerTime > maxTime) {
        return null;
      }
      return { time: markerTime, direction: edge.direction || "NILM edge" };
    }).filter(Boolean);
    const edgeMarkers = edgeItems.map((edge) => {
      const markerTime = edge.time;
      const markerX = x(markerTime).toFixed(1);
      const direction = this._friendlyFeature(edge.direction);
      return `<line class="nilm-edge-marker" x1="${markerX}" y1="${padTop}" x2="${markerX}" y2="${height - padBottom}" data-nilm-edge-time="${this._escape(new Date(markerTime).toISOString())}" data-nilm-edge-direction="${this._escape(edge.direction)}"><title>${this._escape(direction)}</title></line>`;
    }).join("");
    const sessionBands = (Array.isArray(alert.nilm_sessions) ? alert.nilm_sessions : []).map((session) => {
      const start = Date.parse(session && session.start || "");
      const end = Date.parse(session && session.end || "");
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= minTime || start >= maxTime) {
        return "";
      }
      const confidence = Number(session && session.confidence);
      const confidenceValue = Number.isFinite(confidence) ? Math.max(0, Math.min(1, confidence)) : null;
      const confidenceAttr = confidenceValue !== null ? ` data-nilm-session-confidence="${confidenceValue.toFixed(2)}"` : "";
      const lowConfidenceAttr = this._isLowNilmConfidence(confidenceValue) ? ' data-nilm-low-confidence="true"' : "";
      const confidenceStyle = confidenceValue !== null ? ` style="opacity:${(0.08 + confidenceValue * 0.2).toFixed(2)}"` : "";
      const confidenceLabel = confidenceValue !== null ? `, confidence ${Math.round(confidenceValue * 100)}%` : "";
      const left = x(Math.max(start, minTime));
      const right = x(Math.min(end, maxTime));
      const bandWidth = Math.max(right - left, 1);
      const label = this._nilmSessionGraphLabel(session);
      const visibleLabel = bandWidth >= 56 ? this._truncateNilmGraphLabel(label, Math.floor((bandWidth - 10) / 7)) : "";
      const title = label ? `${label} (${session.session_id || "NILM session"})` : session.session_id || "NILM session";
      const labelText = visibleLabel ? `<text class="nilm-session-label" x="${(left + 6).toFixed(1)}" y="${(padTop + 17).toFixed(1)}" data-nilm-session-label="${this._escape(label)}">${this._escape(visibleLabel)}</text>` : "";
      return `<g data-nilm-session-label="${this._escape(label)}"><rect class="nilm-session-band" x="${left.toFixed(1)}" y="${padTop}" width="${bandWidth.toFixed(1)}" height="${height - padTop - padBottom}" data-nilm-session-start="${this._escape(session.start || "")}" data-nilm-session-end="${this._escape(session.end || "")}"${confidenceAttr}${lowConfidenceAttr}${confidenceStyle}><title>${this._escape(title)}${confidenceLabel}</title></rect>${labelText}</g>`;
    }).join("");
    const edgeTimesAttr = edgeItems.length
      ? ` data-nilm-edge-times="${edgeItems.map((edge) => edge.time).join(",")}"`
      : "";
    const selectAttrs = alert.nilm_select_interval
      ? ` data-nilm-chart-select="1" data-chart-start="${minTime}" data-chart-end="${maxTime}" data-chart-left="${padLeft}" data-chart-right="${width - padRight}"${edgeTimesAttr}`
      : "";

    return `
      <svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Alert evidence chart"${selectAttrs}>
        <line class="axis" x1="${padLeft}" y1="${height - padBottom}" x2="${width - padRight}" y2="${height - padBottom}"></line>
        <line class="axis" x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${height - padBottom}"></line>
        <line class="grid" x1="${padLeft}" y1="${padTop}" x2="${width - padRight}" y2="${padTop}"></line>
        ${timeGridLines}
        ${yAxisLabel}
        ${sessionBands}
        <text x="8" y="${padTop + 4}">${this._escape(maxLabel)}</text>
        <text x="8" y="${height - padBottom + 4}">${this._escape(minLabel)}</text>
        ${timeTickLabels}
        ${edgeMarkers}
        ${lines}
      </svg>
      <div class="legend">${legend}</div>
      <p class="muted">Graph times shown in ${this._escape(timeZoneLabel)}.</p>
    `;
  }

  _nilmSessionGraphLabel(session) {
    const label = session && (session.display_label || session.display_name || session.appliance_id || session.assignment_id || session.session_id);
    return String(label || "").trim();
  }

  _truncateNilmGraphLabel(label, maxLength) {
    const text = String(label || "").trim();
    if (!text || maxLength < 4 || text.length <= maxLength) {
      return text;
    }
    return `${text.slice(0, Math.max(1, maxLength - 3))}...`;
  }

  _chartTimeTicks(minTime, maxTime, x) {
    const count = 5;
    const includeDate = this._chartDateKey(minTime) !== this._chartDateKey(maxTime);
    return Array.from({ length: count }, (_item, index) => {
      const ratio = count === 1 ? 0 : index / (count - 1);
      const time = minTime + (maxTime - minTime) * ratio;
      return {
        x: x(time).toFixed(1),
        label: this._formatAxisTime(time, includeDate),
        anchor: index === 0 ? "start" : index === count - 1 ? "end" : "middle",
      };
    });
  }

  _chartDateKey(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    try {
      return new Intl.DateTimeFormat("en-CA", {
        timeZone: this._timeZone(),
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(date);
    } catch (_error) {
      return date.toDateString();
    }
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

  _renderNilmOverlayToggles(workspace) {
    const hasKnown = (workspace.known_load_overlays || []).some((item) => (item.entity_ids || []).length);
    const hasSolar = (workspace.solar_overlays || []).some((item) => (item.entity_ids || []).length);
    if (!hasKnown && !hasSolar) {
      return "";
    }
    return `<div class="actions">
      ${hasKnown ? `<label><input type="checkbox" data-nilm-overlay-toggle="known_load" ${this._nilmOverlayVisibility.known_load ? "checked" : ""}> Show known-load overlays</label>` : ""}
      ${hasSolar ? `<label><input type="checkbox" data-nilm-overlay-toggle="solar" ${this._nilmOverlayVisibility.solar ? "checked" : ""}> Show solar/net overlays</label>` : ""}
    </div>`;
  }

  _renderNilmGraphControls(window) {
    if (!window) {
      return "";
    }
    const span = window.end - window.start;
    const fullSpan = window.max - window.min;
    const minSpan = 15 * 60 * 1000;
    const zoomInDisabled = span <= minSpan ? "disabled" : "";
    const zoomOutDisabled = span >= fullSpan ? "disabled" : "";
    const panEarlierDisabled = window.start <= window.min ? "disabled" : "";
    const panLaterDisabled = window.end >= window.max ? "disabled" : "";
    return `<div data-nilm-workspace-graph>
      <div class="actions">
        <button type="button" class="secondary" data-nilm-graph-zoom="0.5" ${zoomInDisabled}>Zoom In</button>
        <button type="button" class="secondary" data-nilm-graph-zoom="2" ${zoomOutDisabled}>Zoom Out</button>
        <button type="button" class="secondary" data-nilm-graph-pan="-0.5" ${panEarlierDisabled}>Pan Earlier</button>
        <button type="button" class="secondary" data-nilm-graph-pan="0.5" ${panLaterDisabled}>Pan Later</button>
      </div>
      <p class="muted" data-nilm-graph-window>Showing NILM graph window ${this._escape(this._formatDateTime(new Date(window.start)))} - ${this._escape(this._formatDateTime(new Date(window.end)))}.</p>
    </div>`;
  }

  _nilmWorkspaceGraphWindow(workspace) {
    const history = (workspace && workspace.history) || {};
    const min = Date.parse(history.start || "");
    const max = Date.parse(history.end || "");
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
      return null;
    }
    const start = Math.max(min, Math.min(max - 1, this._nilmGraphWindow ? this._nilmGraphWindow.start : min));
    const end = Math.max(start + 1, Math.min(max, this._nilmGraphWindow ? this._nilmGraphWindow.end : max));
    return { start, end, min, max };
  }

  _chartSeries(historySeries = this._historySeries) {
    const parsed = [];
    for (const series of historySeries || []) {
      if (!Array.isArray(series) || !series.length) {
        continue;
      }
      const entityId = series[0].entity_id || "unknown";
      const points = [];
      for (const state of series) {
        const value = Number.parseFloat(state.state);
        const timestamp = Date.parse(state.last_changed || state.last_updated || "");
        if (Number.isFinite(value) && Number.isFinite(timestamp)) {
          points.push({ time: timestamp, value });
        }
      }
      if (points.length) {
        parsed.push({
          entity_id: entityId,
          name: this._friendlyEntityName(entityId),
          points: this._boundedChartPoints(points),
        });
      }
    }
    return parsed;
  }

  _visibleNilmWorkspaceSeries(workspace, graphWindow) {
    const knownIds = new Set((workspace.known_load_overlays || []).flatMap((item) => item.entity_ids || []));
    const solarIds = new Set((workspace.solar_overlays || []).flatMap((item) => item.entity_ids || []));
    return this._chartSeries(this._nilmWorkspaceHistorySeries).map((item) => {
      if (!graphWindow) {
        return item;
      }
      return Object.assign({}, item, {
        points: item.points.filter((point) => point.time >= graphWindow.start && point.time <= graphWindow.end),
      });
    }).filter((item) => item.points.length).filter((item) => {
      if (!this._nilmOverlayVisibility.known_load && knownIds.has(item.entity_id)) {
        return false;
      }
      if (!this._nilmOverlayVisibility.solar && solarIds.has(item.entity_id)) {
        return false;
      }
      return true;
    });
  }

  _boundedChartPoints(points) {
    if (!points.length || points.length <= MAX_CHART_POINTS_PER_SERIES) {
      return points;
    }
    const step = Math.ceil(points.length / MAX_CHART_POINTS_PER_SERIES);
    return points.filter((point, index) => index % step === 0);
  }

  _friendlyEntityName(entityId) {
    const state = this._hass && this._hass.states && this._hass.states[entityId];
    const friendlyName = state && state.attributes && state.attributes.friendly_name;
    if (typeof friendlyName === "string" && friendlyName.trim()) {
      return friendlyName.trim();
    }
    const objectId = String(entityId || "")
      .replace(/^[^.]+\./, "")
      .replace(/^(cs|circuitsetup)_energy_analyzer_/, "");
    return this._friendlyFeature(objectId || entityId);
  }

  _historyApiPath(alert) {
    const entities = alert.graph_entities || [];
    const start = alert.graph_window_start || new Date(Date.now() - 86400000).toISOString();
    const params = new URLSearchParams();
    params.set("filter_entity_id", entities.join(","));
    if (alert.graph_window_end) {
      params.set("end_time", alert.graph_window_end);
    }
    params.set("minimal_response", "1");
    params.set("no_attributes", "1");
    return `${HISTORY_CALL_API_PREFIX}/${encodeURIComponent(start)}?${params.toString()}`;
  }

  _renderNotFound() {
    if (this._loading) {
      return "";
    }
    const message = (this._payload && this._payload.message) || "The alert from this notification is no longer available.";
    const nextStep = (this._payload && this._payload.next_step) || "Open a newer notification or review the appliance summary sensors for current evidence.";
    return `
      <section class="panel">
        <h2>Historical alert not found</h2>
        <p class="muted">${this._escape(message)} ${this._escape(nextStep)}</p>
      </section>
      ${this._renderFallbackActions()}
    `;
  }

  _renderFallbackActions() {
    return this._evidenceSummary.renderFallbackActions();
  }

  _renderFallbackActionsContent() {
    const actions = this._payload && this._payload.actions;
    if (!actions || !Object.keys(actions).length) {
      return "";
    }
    return `
      <section class="panel">
        <h2>Available Circuit Actions</h2>
        ${this._renderActionGroup("Pause alerts for maintenance", "Use this when the appliance is being serviced or intentionally behaving differently.", [
          this._actionButton("pause_alerts", "Pause Alerts", true),
        ])}
        ${this._renderActionGroup("Tune this circuit", "Use these when the appliance summary looks wrong or the learned baseline is stale.", [
          this._actionButton("open_appliance_detail", "Open Appliance Detail", true),
          this._actionButton("relearn_baseline", "Relearn Baseline", true),
          this._actionButton("open_advanced_circuit_settings", "Open Advanced Circuit Settings", true),
        ])}
      </section>
      ${this._renderNilmWorkspace()}
      ${this._renderRecommendations()}
    `;
  }

  _listen(selector, handler) {
    const element = this.shadowRoot.querySelector(selector);
    if (element) {
      element.addEventListener("click", handler);
    }
  }

  _statusText(status) {
    if (status === "matched_alert") {
      return "Matched alert";
    }
    if (status === "latest_for_circuit") {
      return "Latest evidence for circuit";
    }
    if (status === "circuit_found_no_evidence") {
      return "Circuit actions available";
    }
    return "Historical alert not found";
  }

  _metric(label, value) {
    return `<div class="metric"><span>${this._escape(label)}</span><strong>${this._escape(this._formatMetricValue(value))}</strong></div>`;
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

  _actionButton(actionKey, label, secondary = false) {
    const actions = this._payload && this._payload.actions;
    const action = actions && actions[actionKey];
    if (!action) {
      return "";
    }
    const reason = action.unavailable_label || action.unavailable_reason || "";
    const title = reason ? ` title="${this._escape(reason)}"` : "";
    const hint = reason ? `<span class="action-reason">${this._escape(reason)}</span>` : "";
    return `<span class="action-item"><button id="${actionKey}" class="${secondary ? "secondary" : ""}"${title} ${this._actionDisabled(actionKey, action)}>${this._escape(action.label || label)}</button>${hint}</span>`;
  }

  _nilmActionButton(index, actionKey, label, secondary = false, disabled = false) {
    const busyKey = `nilm_${index}_${actionKey}`;
    return `<button data-nilm-index="${index}" data-nilm-action="${actionKey}" class="${secondary ? "secondary" : ""}" ${disabled ? "disabled" : this._disabled(busyKey)}>${this._escape(label)}</button>`;
  }

  _recommendationActionButton(recommendation, index, actionKey, label, secondary = false) {
    const busyKey = `recommendation_${index}_${actionKey}`;
    const action = recommendation && recommendation.actions && recommendation.actions[actionKey];
    if (!action) {
      return "";
    }
    if (action.enabled === false && this._shouldHideUnavailableRecommendationAction(actionKey, action)) {
      return "";
    }
    const disabled = this._busyAction === busyKey || (action && action.enabled === false) ? "disabled" : "";
    const reason = action && (action.unavailable_label || action.unavailable_reason);
    const title = reason ? ` title="${this._escape(reason)}"` : "";
    return `<button data-recommendation-index="${index}" data-recommendation-action="${actionKey}" class="${secondary ? "secondary" : ""}"${title} ${disabled}>${this._escape(label)}</button>`;
  }

  _shouldHideUnavailableRecommendationAction(actionKey, action) {
    if (!action || !action.unavailable_reason) {
      return false;
    }
    return ["apply", "dismiss", "undo"].includes(actionKey)
      && ["not_pending", "not_applied"].includes(action.unavailable_reason);
  }

  _changeSummary(alert) {
    if (alert.percent_change !== null && alert.percent_change !== undefined) {
      return `${alert.feature_name || this._friendlyFeature(alert.feature)} changed by ${alert.percent_change}%.`;
    }
    const metrics = alert.contributing_metrics || {};
    const keys = Object.keys(metrics);
    if (keys.length) {
      return `Changed metrics: ${keys.join(", ")}.`;
    }
    return alert.what_happened || alert.message || "The analyzer found a repeated change.";
  }

  _disabled(actionKey) {
    return this._busyAction === actionKey ? "disabled" : "";
  }

  _actionDisabled(actionKey, action) {
    return this._busyAction === actionKey || (action && action.enabled === false) ? "disabled" : "";
  }

  _formatPower(value) {
    return value === null || value === undefined ? "Unknown" : `${this._formatNumber(value)} W`;
  }

  _formatKwh(value) {
    return value === null || value === undefined ? "Unknown" : `${this._formatNumber(value)} kWh`;
  }

  _formatCost(value) {
    return value === null || value === undefined ? "Unknown" : `$${this._formatNumber(value)}`;
  }

  _formatDuration(value) {
    if (value === null || value === undefined) {
      return "Unknown";
    }
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) {
      return "Unknown";
    }
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.round((seconds % 3600) / 60);
    if (hours && minutes) {
      return `${hours}h ${minutes}m`;
    }
    if (hours) {
      return `${hours}h`;
    }
    return `${minutes}m`;
  }

  _formatConfidence(value) {
    const confidence = Number(value);
    if (!Number.isFinite(confidence)) {
      return "Unknown";
    }
    const normalized = confidence <= 1 ? confidence * 100 : confidence;
    return `${Math.round(normalized)}%`;
  }

  _isLowNilmConfidence(value) {
    const confidence = Number(value);
    if (!Number.isFinite(confidence)) {
      return false;
    }
    const normalized = confidence <= 1 ? confidence : confidence / 100;
    return normalized < NILM_LOW_CONFIDENCE_THRESHOLD;
  }

  _formatComparisonValue(comparison, value) {
    if (value === null || value === undefined) {
      return "Unknown";
    }
    const unit = comparison && comparison.unit ? String(comparison.unit) : "";
    if (unit === "%") {
      return `${this._formatNumber(value)}%`;
    }
    return `${this._formatNumber(value)}${unit ? ` ${unit}` : ""}`;
  }

  _sourceLabel(sourceType) {
    const labels = {
      direct_meter: "Direct meter",
      nilm_estimate: "Estimated by NILM",
      mixed: "Mixed circuit",
      mains: "Mains",
      unknown: "Unknown",
    };
    return labels[sourceType] || "Unknown";
  }

  _formatNumber(value) {
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  _formatMetricValue(value) {
    if (value === null || value === undefined || value === "") {
      return "Unknown";
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
      return "Unknown";
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
      || "local time"
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
      return "Alert";
    }
    const labels = {
      hvac: "HVAC",
      kwh: "kWh",
      nilm: "NILM",
      pf: "PF",
      s: "Seconds",
      va: "VA",
      var: "VAR",
    };
    return raw.split(/[_-]+/)
      .filter((token) => token)
      .map((token) => labels[token.toLowerCase()] || token.charAt(0).toUpperCase() + token.slice(1).toLowerCase())
      .join(" ") || "Alert";
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

class CircuitSetupEnergyAnalyzerDashboardGraphs extends CircuitSetupEnergyAnalyzerPanel {
  constructor() {
    super();
    this._dashboardConfig = {};
  }

  setConfig(config) {
    this._dashboardConfig = config || {};
    this._loadedRouteKey = "";
  }

  getCardSize() {
    return 7;
  }

  _routeKey() {
    const configuredPath = this._dashboardConfig.detail_path
      || "/circuitsetup-energy-analyzer-evidence?nilm_workspace=1&circuit_id=mains";
    const url = new URL(configuredPath, window.location.origin);
    if (!url.searchParams.get("circuit_id")) {
      url.searchParams.set("circuit_id", this._dashboardConfig.circuit_id || "mains");
    }
    return `${url.pathname}${url.search}`;
  }

  _routeRequestsNilmWorkspace() {
    return true;
  }

  _render() {
    const loaded = !this._loading && !this._nilmWorkspaceLoading;
    if (loaded && !this._hasDashboardAppliance()) {
      this.shadowRoot.innerHTML = "";
      return;
    }

    const alert = this._payload && this._payload.alert;
    const workspace = this._nilmWorkspace && this._nilmWorkspace.status === "ok"
      ? this._nilmWorkspace
      : null;
    const title = this._dashboardConfig.title || "NILM mains power";
    const body = this._loading
      ? `<p class="muted">Loading NILM graphs...</p>`
      : `
        ${this._renderDashboardNotificationGraph(alert)}
        ${this._renderNilmWorkspaceLanes(workspace)}
        ${this._renderDashboardNilmMainsGraph(workspace)}
      `;

    this.shadowRoot.innerHTML = `
      <ha-card>
        <style>
          .dashboard-graphs {
            display: grid;
            gap: 16px;
            padding: 16px;
          }
          h2, h3 {
            margin: 0;
          }
          h2 {
            font-size: 18px;
          }
          h3 {
            font-size: 15px;
          }
          p {
            margin: 8px 0 0;
          }
          .muted {
            color: var(--secondary-text-color, #6b7280);
          }
          .summary {
            display: grid;
            gap: 10px;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
          }
          .metric {
            background: var(--secondary-background-color, #f4f6f8);
            border: 1px solid var(--divider-color, #d8dee6);
            border-radius: 6px;
            padding: 10px;
          }
          .metric span {
            color: var(--secondary-text-color, #6b7280);
            display: block;
            font-size: 12px;
            margin-bottom: 4px;
          }
          .metric strong {
            font-size: 16px;
          }
          .action-group {
            display: grid;
            gap: 8px;
          }
          .dashboard-chart-link {
            color: inherit;
            display: block;
            text-decoration: none;
          }
          .dashboard-chart-link:focus {
            outline: 2px solid var(--primary-color, #03a9f4);
            outline-offset: 3px;
          }
          .detail-link {
            color: var(--primary-color, #03a9f4);
            display: inline-block;
            font-weight: 600;
            margin-top: 8px;
          }
          .chart {
            height: auto;
            max-width: 100%;
            width: 100%;
          }
          .axis,
          .grid {
            stroke: var(--divider-color, #d8dee6);
          }
          .axis-label,
          .chart text {
            fill: var(--secondary-text-color, #6b7280);
            font-size: 12px;
          }
          .legend {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 8px;
          }
          .legend-item {
            align-items: center;
            display: inline-flex;
            gap: 6px;
            font-size: 12px;
          }
          .swatch {
            border-radius: 999px;
            display: inline-block;
            height: 10px;
            width: 10px;
          }
          .nilm-session-band {
            cursor: default;
            fill: var(--primary-color, #03a9f4);
          }
          .nilm-session-band[data-nilm-low-confidence="true"] {
            stroke: var(--warning-color, #f59e0b);
            stroke-dasharray: 4 3;
            stroke-width: 2;
          }
          .nilm-session-label {
            fill: var(--primary-text-color, #111827);
            font-size: 12px;
            pointer-events: none;
          }
          .nilm-edge-marker {
            stroke: var(--warning-color, #f59e0b);
            stroke-dasharray: 4 3;
            stroke-width: 2;
          }
        </style>
        <div class="dashboard-graphs">
          <h2>${this._escape(title)}</h2>
          ${this._error ? `<p class="muted">${this._escape(this._error)}</p>` : ""}
          ${this._nilmWorkspaceError ? `<p class="muted">${this._escape(this._nilmWorkspaceError)}</p>` : ""}
          ${body}
        </div>
      </ha-card>
    `;

    for (const link of this.shadowRoot.querySelectorAll("[data-dashboard-alert-detail]")) {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        this._navigate(link.getAttribute("href"));
      });
    }
  }

  _hasDashboardAppliance() {
    const workspace = this._nilmWorkspace;
    if (workspace && workspace.status === "ok") {
      return Boolean(
        Number(workspace.assignment_count || 0) > 0
        || Number(workspace.virtual_appliance_count || 0) > 0
        || this._nilmWorkspaceHasLaneItems(workspace)
        || (Array.isArray(workspace.assignments) && workspace.assignments.length)
        || (Array.isArray(workspace.virtual_appliances) && workspace.virtual_appliances.length)
      );
    }
    return (this._dashboardConfig.appliance_power_entities || []).some(
      (entityId) => this._hass && this._hass.states && this._hass.states[entityId],
    );
  }

  _nilmWorkspaceHasLaneItems(workspace) {
    const laneCounts = workspace && workspace.lane_counts && typeof workspace.lane_counts === "object"
      ? workspace.lane_counts
      : {};
    if (Object.values(laneCounts).some((value) => Number(value || 0) > 0)) {
      return true;
    }
    const lanes = workspace && workspace.lanes && typeof workspace.lanes === "object"
      ? workspace.lanes
      : {};
    return Object.values(lanes).some((lane) => {
      if (!lane || typeof lane !== "object") {
        return false;
      }
      return (Array.isArray(lane.assignment_ids) && lane.assignment_ids.length > 0)
        || (Array.isArray(lane.signature_ids) && lane.signature_ids.length > 0);
    });
  }

  _renderDashboardNotificationGraph(alert) {
    if (!alert) {
      return "";
    }
    const detailPath = alert.evidence_path || this._dashboardConfig.detail_path || this._routeKey();
    const description = alert.what_happened || alert.message || "Latest related notification";
    return `
      <section>
        <h3>Latest related notification</h3>
        <p>${this._escape(description)}</p>
        <a class="dashboard-chart-link" href="${this._escape(detailPath)}" data-dashboard-alert-detail>
          ${this._renderChart(alert)}
          <span class="detail-link">View notification detail</span>
        </a>
      </section>
    `;
  }

  _renderDashboardNilmMainsGraph(workspace) {
    if (!workspace) {
      return "";
    }
    const graphWindow = this._nilmWorkspaceGraphWindow(workspace);
    const series = this._visibleNilmWorkspaceSeries(workspace, graphWindow);
    const graph = graphWindow && series.length
      ? this._chartSvg(series, {
        graph_window_start: new Date(graphWindow.start).toISOString(),
        graph_window_end: new Date(graphWindow.end).toISOString(),
        nilm_sessions: workspace.sessions,
        y_axis_label: "W",
      })
      : `<p class="muted">No NILM workspace history samples were available for this graph window.</p>`;
    return `
      <section>
        <h3>NILM mains power</h3>
        ${graph}
      </section>
    `;
  }
}

if (!customElements.get("circuitsetup-energy-analyzer-panel")) {
  customElements.define("circuitsetup-energy-analyzer-panel", CircuitSetupEnergyAnalyzerPanel);
}

if (!customElements.get("circuitsetup-energy-analyzer-dashboard-graphs")) {
  customElements.define("circuitsetup-energy-analyzer-dashboard-graphs", CircuitSetupEnergyAnalyzerDashboardGraphs);
}
