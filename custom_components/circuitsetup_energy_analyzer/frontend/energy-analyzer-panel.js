const EVIDENCE_API_PATH = "/api/circuitsetup_energy_analyzer/alert_evidence";
const EVIDENCE_CALL_API_PATH = "circuitsetup_energy_analyzer/alert_evidence";
const NILM_WORKSPACE_API_PATH = "/api/circuitsetup_energy_analyzer/nilm_workspace";
const NILM_WORKSPACE_CALL_API_PATH = "circuitsetup_energy_analyzer/nilm_workspace";
const HISTORY_CALL_API_PREFIX = "history/period";
const MAX_CHART_POINTS_PER_SERIES = 240;
const EXPAND_NILM_QUERY_PARAM = "include_all_nilm";
const ROUTE_CHANGE_EVENT = "circuitsetup-energy-analyzer-route-change";
const ROUTE_CHANGE_INSTALL_KEY = "__circuitsetupEnergyAnalyzerRouteChangeInstalled";
const ACTION_SERVICE_NAMES = {
  acknowledge: "acknowledge_alert",
  mark_expected: "mark_alert_expected",
  mark_unhelpful: "mark_alert_unhelpful",
  pause_alerts: "pause_alerts",
  start_maintenance: "start_maintenance",
  end_maintenance: "end_maintenance",
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

class CircuitSetupEnergyAnalyzerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._payload = null;
    this._historySeries = [];
    this._nilmWorkspace = null;
    this._nilmWorkspaceHistorySeries = [];
    this._loading = true;
    this._historyLoading = false;
    this._nilmWorkspaceLoading = false;
    this._error = "";
    this._historyError = "";
    this._nilmWorkspaceError = "";
    this._busyAction = "";
    this._lastActionMessage = "";
    this._loadedRouteKey = "";
    this._evidenceRequestId = 0;
    this._listeningForRouteChanges = false;
    this._nilmLabelDrafts = new Map();
    this._nilmSessionLabelDrafts = new Map();
    this._nilmAssignmentDrafts = new Map();
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
    this._nilmWorkspaceError = "";
    this._nilmWorkspaceHistorySeries = [];
    this._nilmLabelDrafts.clear();
    this._nilmSessionLabelDrafts.clear();
    this._nilmAssignmentDrafts.clear();
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
    const apiPath = (nilm && nilm.workspace_call_api_path) || "";
    if (!apiPath) {
      return;
    }

    const circuit = this._payload && this._payload.circuit;
    const fetchPath = (nilm && nilm.workspace_api_path)
      || `${NILM_WORKSPACE_API_PATH}?${new URLSearchParams({ circuit_id: (circuit && circuit.circuit_id) || "" }).toString()}`;
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
      this._lastActionMessage = "Action complete.";
      this._busyAction = "";
      await this._loadEvidence({ routeKey: this._actionRefreshRouteKey(actionKey) });
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
      const label = labelInput ? labelInput.value.trim() : "";
      if (!label) {
        this._error = "Enter a label for this NILM signature before saving.";
        this._renderAndScrollToTop();
        return;
      }
      data.label = label;
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
      data.label = String((interval && (interval.label || interval.appliance_id)) || "").trim();
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
    const workspace = this._nilmWorkspace;
    const items = workspace && workspace[collectionKey];
    const item = items && items[index];
    const action = item && item.actions && item.actions[actionKey];
    if (!this._guardActionCall(action, `NILM ${actionKey}`)) {
      return;
    }
    const data = Object.assign({}, action.data || {});
    if (action.requires && action.requires.includes("label")) {
      const labelInput = this.shadowRoot.querySelector(`#nilm_assignment_label_${index}`)
        || this.shadowRoot.querySelector(`#nilm_session_label_${index}`);
      const label = labelInput
        ? labelInput.value
        : item.display_name || item.label || item.appliance_id || "";
      if (!label || !label.trim()) {
        this._error = "Enter an appliance name before assigning this NILM session.";
        this._renderAndScrollToTop();
        return;
      }
      data.label = label.trim();
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
      return "Retired NILM appliance assignment.";
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
    const statusText = this._statusText(payload && payload.status);

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
          <h1>${this._escape((circuit && circuit.name) || (alert && alert.circuit_id) || "Alert Evidence")}</h1>
          <p class="muted">${this._escape((alert && alert.message) || "Historical alert not found")}</p>
        </section>
      ${this._loading ? `<section class="panel"><p>Loading alert evidence...</p></section>` : ""}
      ${this._lastActionMessage ? `<section class="panel"><p>${this._escape(this._lastActionMessage)}</p></section>` : ""}
      ${this._error ? `<section class="panel error"><p>${this._escape(this._error)}</p><button class="secondary" id="retry">Retry</button></section>` : ""}
      ${this._renderSelectedRecommendationEvidence()}
      ${alert ? this._renderAlert(alert, circuit) : this._renderNotFound()}
      </main>
    `;

    this._listen("#retry", () => this._loadEvidence({ routeKey: this._routeKey() }));
    this._listen("#acknowledge", () => this._callAction("acknowledge"));
    this._listen("#mark_expected", () => this._callAction("mark_expected"));
    this._listen("#mark_unhelpful", () => this._callAction("mark_unhelpful"));
    this._listen("#pause_alerts", () => this._callAction("pause_alerts"));
    this._listen("#start_maintenance", () => this._callAction("start_maintenance"));
    this._listen("#end_maintenance", () => this._callAction("end_maintenance"));
    this._listen("#relearn_baseline", () => this._callAction("relearn_baseline"));
    this._listen("#open_advanced_circuit_settings", () => this._callAction("open_advanced_circuit_settings"));
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
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-session-label-input]")) {
      input.addEventListener("input", () => this._rememberNilmSessionLabelDraft(input));
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-assignment-input]")) {
      input.addEventListener("input", () => this._rememberNilmAssignmentDraft(input));
    }
    for (const chart of this.shadowRoot.querySelectorAll("[data-nilm-chart-select]")) {
      chart.addEventListener("pointerdown", (event) => this._startNilmChartSelection(event, chart));
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
  }

  _renderAlert(alert, circuit) {
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
        <div class="actions">
          ${this._actionButton("acknowledge", "Acknowledge")}
          ${this._actionButton("mark_expected", "Mark Expected", true)}
          ${this._actionButton("mark_unhelpful", "Not Helpful", true)}
          ${this._actionButton("pause_alerts", "Pause Alerts", true)}
          ${this._actionButton("start_maintenance", "Start Maintenance", true)}
          ${this._actionButton("end_maintenance", "End Maintenance", true)}
          ${this._actionButton("relearn_baseline", "Relearn Baseline", true)}
          ${this._actionButton("open_advanced_circuit_settings", "Open Advanced Circuit Settings", true)}
        </div>
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
    return `
      ${signature.user_label ? `<p class="muted">Saved label: ${this._escape(signature.user_label)}</p>` : ""}
      ${signature.review_state ? `<p class="muted">Review state: ${this._escape(this._friendlyFeature(signature.review_state))}</p>` : ""}
      ${signature.merged_into ? `<p class="muted">Merged into: ${this._escape(signature.merged_into)}</p>` : ""}
      ${this._renderNilmLabelField(signature, index)}
      ${this._renderNilmMergeTarget(signature, index)}
      <div class="actions">
        ${this._nilmActionButton(index, "label", "Save Label")}
        ${this._nilmActionButton(index, "assign", "Assign Appliance", true)}
        ${this._nilmActionButton(index, "ignore", "Ignore", true)}
        ${this._nilmActionButton(index, "mark_expected", "Mark Expected", true)}
        ${this._nilmActionButton(index, "merge", "Merge", true, !(signature.actions && signature.actions.merge && signature.actions.merge.target_options && signature.actions.merge.target_options.length))}
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

  _startNilmChartSelection(event, chart) {
    const startTime = this._chartEventTime(event, chart);
    if (!Number.isFinite(startTime)) {
      return;
    }
    const finish = (finishEvent) => {
      chart.removeEventListener("pointercancel", cancel);
      const endTime = this._chartEventTime(finishEvent, chart);
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
                 ${this._recommendationActionButton(recommendation, originalIndex, "apply", "Apply")}
                 ${this._recommendationActionButton(recommendation, originalIndex, "dismiss", "Dismiss", true)}
                 ${recommendation.actions && recommendation.actions.undo ? this._recommendationActionButton(recommendation, originalIndex, "undo", "Undo", true) : ""}
                 ${recommendation.actions && recommendation.actions.reset ? this._recommendationActionButton(recommendation, originalIndex, "reset", "Reset default", true) : ""}
                 ${recommendation.actions && recommendation.actions.preview ? this._recommendationActionButton(recommendation, originalIndex, "preview", "Preview evidence", true) : ""}
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

  _renderNilmWorkspace() {
    if (this._nilmWorkspaceLoading) {
      return `<section class="panel"><h2>NILM Workspace</h2><p class="muted">Loading NILM workspace...</p></section>`;
    }
    const workspace = this._nilmWorkspace;
    if (this._nilmWorkspaceError && (!workspace || workspace.status !== "ok")) {
      return `<section class="panel error"><h2>NILM Workspace</h2><p>${this._escape(this._nilmWorkspaceError)}</p></section>`;
    }
    if (!workspace || workspace.status !== "ok") {
      return "";
    }
    const history = workspace.history || {};
    const series = this._chartSeries(this._nilmWorkspaceHistorySeries);
    const graph = series.length
      ? this._chartSvg(series, { graph_window_start: history.start, graph_window_end: history.end, nilm_select_interval: true })
      : `<p class="muted">No NILM workspace history samples were available for this graph window.</p>`;
    return `
      <section class="panel">
        <h2>NILM Workspace</h2>
        ${this._nilmWorkspaceError ? `<p class="muted">${this._escape(this._nilmWorkspaceError)}</p>` : ""}
        ${graph}
        ${this._renderNilmLabelIntervals(workspace)}
        ${this._renderNilmValidation(workspace.validation)}
        ${this._renderNilmWorkspaceList("Estimated Appliances", workspace.virtual_appliances, "No estimated appliances are available yet.", (item) => `
          <div class="metric">
            <span>${this._escape(item.model_status || "candidate")}</span>
            <strong>${this._escape(item.display_name || item.appliance_id || "Estimated appliance")} - ${this._escape(item.is_running ? "running" : "idle")}</strong>
            <p class="muted" data-field="estimated_daily_energy">${this._escape(this._formatMetricValue(item.estimated_power_w))} W, ${this._escape(this._formatMetricValue(item.estimated_energy_kwh_today))} kWh today, confidence ${this._escape(Math.round(Number(item.confidence || 0) * 100))}%</p>
          </div>
        `)}
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
        `)}
        ${this._renderNilmWorkspaceList("Known Load Overlays", workspace.known_load_overlays, "No known-load overlays are configured.", (item) => `
          <div class="metric">
            <span>${this._escape(item.circuit_id)}</span>
            <strong>${this._escape(item.name || item.circuit_id)}</strong>
            <p class="muted">${this._escape((item.entity_ids || []).join(", "))}</p>
          </div>
        `)}
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
        `)}
        ${this._renderNilmWorkspaceList("NILM Signatures", workspace.signatures, "No NILM signatures are available yet.", (item, index) => `
          <div class="metric">
            <span>${this._escape(item.review_state || `${Math.round(Number(item.confidence || 0) * 100)}% confidence`)}</span>
            <strong>${this._escape(item.display_label || item.display_name || item.likely_type || "Unknown load")}</strong>
            ${this._renderNilmSignatureReview(item, index)}
          </div>
        `)}
        ${this._renderNilmWorkspaceList("NILM Edges", workspace.edges, "No NILM edges are available yet.", (item) => `
          <div class="metric">
            <span>${this._escape(item.timestamp || "")}</span>
            <strong>${this._escape(this._friendlyFeature(item.direction))}: ${this._escape(this._formatMetricValue(item.delta_w))} W</strong>
            <p class="muted">${this._escape(item.split_phase_type || "unknown")}</p>
          </div>
        `)}
      </section>
    `;
  }

  _renderNilmLabelIntervals(workspace) {
    const draft = this._nilmLabelIntervalDraft || {};
    const intervals = Array.isArray(workspace && workspace.label_intervals)
      ? workspace.label_intervals
      : [];
    const saveBusy = this._busyAction === "nilm_label_interval_save" ? "disabled" : "";
    const generateBusy = this._busyAction === "nilm_label_interval_generate_sensor" ? "disabled" : "";
    return `
      <h3>Manual Labels</h3>
      <div class="metric">
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
            <input type="text" data-nilm-label-interval-input="ground_truth_entity_id" value="${this._escape(draft.ground_truth_entity_id || "")}" placeholder="sensor.dishwasher_power">
          </label>
        </div>
        <div class="actions">
          <button type="button" data-nilm-label-interval-action="save" ${saveBusy}>Save Interval</button>
          <button type="button" class="secondary" data-nilm-label-interval-action="generate_sensor" ${generateBusy}>Generate From Sensor</button>
        </div>
      </div>
      ${intervals.length ? `<div class="entity-list">${intervals.map((item, index) => `
        <div class="metric">
          <span>${this._escape(item.start || "")} - ${this._escape(item.end || "")}</span>
          <strong>${this._escape(item.label || item.appliance_id || "Labeled interval")}</strong>
          ${item.mains_entity_id ? `<p class="muted">${this._escape(item.mains_entity_id)}</p>` : ""}
          ${item.ground_truth_entity_id ? `<p class="muted">Ground Truth Sensor: ${this._escape(item.ground_truth_entity_id)}</p>` : ""}
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

  _renderNilmSessionAssignField(session, index) {
    const draftKey = this._nilmSessionLabelDraftKey(session);
    const currentLabel = this._nilmSessionLabelDrafts.has(draftKey)
      ? this._nilmSessionLabelDrafts.get(draftKey)
      : "";
    return `
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
    return `
      <div class="grid">
        ${actions.rename ? `<label class="nilm-label-field" for="nilm_assignment_label_${index}">
          <span class="muted">Appliance name</span>
          <input id="nilm_assignment_label_${index}" type="text" data-nilm-assignment-input data-nilm-assignment-key="${this._escape(draftKey)}" data-nilm-assignment-field="label" value="${this._escape(label)}" placeholder="Appliance name">
        </label>` : ""}
        ${actions.change_profile ? `<label class="nilm-label-field" for="nilm_assignment_profile_${index}">
          <span class="muted">Appliance type</span>
          <input id="nilm_assignment_profile_${index}" type="text" data-nilm-assignment-input data-nilm-assignment-key="${this._escape(draftKey)}" data-nilm-assignment-field="appliance_profile" value="${this._escape(profile)}" placeholder="dishwasher">
        </label>` : ""}
        ${actions.merge ? `<label class="nilm-label-field" for="nilm_assignment_merge_target_${index}">
          <span class="muted">Merge into</span>
          <select id="nilm_assignment_merge_target_${index}" data-nilm-assignment-merge-target>
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
    if (!actions || !Object.keys(actions).length) {
      return "";
    }
    return `
      <div class="actions">
        ${actions.rename ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="rename" ${this._busyAction === `nilm_assignments_${index}_rename` ? "disabled" : ""}>Rename Appliance</button>` : ""}
        ${actions.change_profile ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="change_profile" ${this._busyAction === `nilm_assignments_${index}_change_profile` ? "disabled" : ""}>Change Type</button>` : ""}
        ${actions.validate_history ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="validate_history" ${this._busyAction === `nilm_assignments_${index}_validate_history` ? "disabled" : ""}>Validate History</button>` : ""}
        ${actions.merge ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="merge" ${this._busyAction === `nilm_assignments_${index}_merge` ? "disabled" : ""}>Merge Assignment</button>` : ""}
        ${actions.publish ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="publish" ${this._busyAction === `nilm_assignments_${index}_publish` ? "disabled" : ""}>Publish Entities</button>` : ""}
        ${actions.unpublish ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="unpublish" ${this._busyAction === `nilm_assignments_${index}_unpublish` ? "disabled" : ""}>Disable Publishing</button>` : ""}
        ${actions.retire ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="retire" ${this._busyAction === `nilm_assignments_${index}_retire` ? "disabled" : ""}>Retire</button>` : ""}
      </div>
    `;
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
      `)}
    `;
  }

  _renderNilmWorkspaceList(title, items, emptyText, renderItem) {
    const safeItems = Array.isArray(items) ? items : [];
    return `
      <h3>${this._escape(title)}</h3>
      ${safeItems.length ? `<div class="entity-list">${safeItems.map(renderItem).join("")}</div>` : `<p class="muted">${this._escape(emptyText)}</p>`}
    `;
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
    const startLabel = this._formatDateTime(alert.graph_window_start || minTime);
    const endLabel = this._formatDateTime(alert.graph_window_end || maxTime);
    const selectAttrs = alert.nilm_select_interval
      ? ` data-nilm-chart-select="1" data-chart-start="${minTime}" data-chart-end="${maxTime}" data-chart-left="${padLeft}" data-chart-right="${width - padRight}"`
      : "";

    return `
      <svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Alert evidence chart"${selectAttrs}>
        <line class="axis" x1="${padLeft}" y1="${height - padBottom}" x2="${width - padRight}" y2="${height - padBottom}"></line>
        <line class="axis" x1="${padLeft}" y1="${padTop}" x2="${padLeft}" y2="${height - padBottom}"></line>
        <line class="grid" x1="${padLeft}" y1="${padTop}" x2="${width - padRight}" y2="${padTop}"></line>
        <text x="8" y="${padTop + 4}">${this._escape(maxLabel)}</text>
        <text x="8" y="${height - padBottom + 4}">${this._escape(minLabel)}</text>
        <text x="${padLeft}" y="${height - 12}">${this._escape(startLabel)}</text>
        <text x="${width - padRight}" y="${height - 12}" text-anchor="end">${this._escape(endLabel)}</text>
        ${lines}
      </svg>
      <div class="legend">${legend}</div>
    `;
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
    const actions = this._payload && this._payload.actions;
    if (!actions || !Object.keys(actions).length) {
      return "";
    }
    return `
      <section class="panel">
        <h2>Available Circuit Actions</h2>
        <div class="actions">
          ${this._actionButton("pause_alerts", "Pause Alerts", true)}
          ${this._actionButton("start_maintenance", "Start Maintenance", true)}
          ${this._actionButton("end_maintenance", "End Maintenance", true)}
          ${this._actionButton("relearn_baseline", "Relearn Baseline", true)}
          ${this._actionButton("open_advanced_circuit_settings", "Open Advanced Circuit Settings", true)}
        </div>
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

  _actionButton(actionKey, label, secondary = false) {
    const actions = this._payload && this._payload.actions;
    const action = actions && actions[actionKey];
    if (!action) {
      return "";
    }
    const reason = action.unavailable_label || action.unavailable_reason || "";
    const title = reason ? ` title="${this._escape(reason)}"` : "";
    const hint = reason ? `<span class="action-reason">${this._escape(reason)}</span>` : "";
    return `<span class="action-item"><button id="${actionKey}" class="${secondary ? "secondary" : ""}"${title} ${this._actionDisabled(actionKey, action)}>${this._escape(label)}</button>${hint}</span>`;
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
    const year = String(date.getFullYear());
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    const minute = String(date.getMinutes()).padStart(2, "0");
    return this._formatDateParts(year, month, day, date.getHours(), minute);
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

if (!customElements.get("circuitsetup-energy-analyzer-panel")) {
  customElements.define("circuitsetup-energy-analyzer-panel", CircuitSetupEnergyAnalyzerPanel);
}
