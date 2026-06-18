const EVIDENCE_API_PATH = "/api/circuitsetup_energy_analyzer/alert_evidence";
const EVIDENCE_CALL_API_PATH = "circuitsetup_energy_analyzer/alert_evidence";
const HISTORY_CALL_API_PREFIX = "history/period";
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
  deny_setting_recommendation: "deny_setting_recommendation",
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
    this._loading = true;
    this._historyLoading = false;
    this._error = "";
    this._historyError = "";
    this._busyAction = "";
    this._lastActionMessage = "";
    this._loadedRouteKey = "";
    this._evidenceRequestId = 0;
    this._listeningForRouteChanges = false;
    this._nilmLabelDrafts = new Map();
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
    this._nilmLabelDrafts.clear();
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
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._render();
    }
  }

  async _callNilmAction(index, actionKey) {
    const signatures = this._payload && this._payload.nilm && this._payload.nilm.signatures;
    const signature = signatures && signatures[index];
    const action = signature && signature.actions && signature.actions[actionKey];
    if (!this._guardActionCall(action, `NILM ${actionKey}`)) {
      return;
    }
    const data = Object.assign({}, action.data || {});
    if (actionKey === "label") {
      const labelInput = this.shadowRoot.querySelector(`#nilm_label_${index}`);
      const label = labelInput ? labelInput.value.trim() : "";
      if (!label) {
        this._error = "Enter a label for this NILM signature before saving.";
        this._render();
        return;
      }
      data.label = label;
    }
    if (actionKey === "merge") {
      const targetList = this.shadowRoot.querySelector(`#nilm_merge_targets_${index}`);
      const target = targetList ? targetList.dataset.selected || "" : "";
      if (!target) {
        this._error = "Choose a merge target before merging NILM signatures.";
        this._render();
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
      if (actionKey === "label") {
        this._nilmLabelDrafts.delete(this._nilmLabelDraftKey(signature));
      }
      this._lastActionMessage = this._nilmActionMessage(actionKey, data);
      this._busyAction = "";
      await this._loadEvidence({ routeKey: this._actionRefreshRouteKey(`nilm_${actionKey}`) });
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._render();
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
      await this._loadEvidence({ routeKey: this._routeKey() });
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._render();
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
  }

  _guardActionCall(action, label) {
    if (!action) {
      this._error = `Action unavailable: ${label}. Reload the evidence panel and try again.`;
      this._render();
      return false;
    }
    if (action.enabled === false) {
      this._error = action.unavailable_label || `Action unavailable: ${action.unavailable_reason || label}.`;
      this._render();
      return false;
    }
    if (action.path) {
      return true;
    }
    if (!action.service) {
      this._error = `Action unavailable: ${label}. The panel did not receive a service to call.`;
      this._render();
      return false;
    }
    if (!this._hass || !this._hass.callService) {
      this._error = "Home Assistant service calls are not available in this panel session. Reload Home Assistant and try again.";
      this._render();
      return false;
    }
    return true;
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
    return "Action complete.";
  }

  _recommendationActionMessage(actionKey) {
    const messages = {
      apply: "Recommendation applied.",
      deny: "Recommendation denied.",
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
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-merge-target]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.nilmIndex, 10);
        this._selectNilmMergeTarget(index, button.dataset.nilmMergeTarget);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-load-all-nilm]")) {
      button.addEventListener("click", () => this._loadExpandedNilm());
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
      ${this._renderNilmActions()}
    `;
  }

  _renderNilmActions() {
    const nilm = this._payload && this._payload.nilm;
    const signatures = nilm && nilm.signatures;
    if (!signatures || !signatures.length) {
      return "";
    }
    const totalCount = Number((nilm && nilm.signature_count) || signatures.length);
    const omittedCount = Number((nilm && nilm.signatures_omitted_count) || 0);
    const summary = omittedCount > 0
      ? `<p class="muted">Showing ${signatures.length} of ${totalCount} NILM signatures. ${omittedCount} more can be reviewed after loading the full slim NILM list. <button type="button" class="secondary" data-load-all-nilm>Load all NILM signatures</button></p>`
      : "";
    return `
      <section class="panel">
        <h2>NILM Review</h2>
        ${summary}
        ${signatures.map((signature, index) => `
          <div class="metric">
            <span>NILM signature</span>
            <strong>${this._escape(signature.display_label || signature.display_name || signature.likely_type || "Unknown load")}</strong>
            ${signature.user_label ? `<p class="muted">Saved label: ${this._escape(signature.user_label)}</p>` : ""}
            ${signature.review_state ? `<p class="muted">Review state: ${this._escape(this._friendlyFeature(signature.review_state))}</p>` : ""}
            ${signature.merged_into ? `<p class="muted">Merged into: ${this._escape(signature.merged_into)}</p>` : ""}
            ${this._renderNilmLabelField(signature, index)}
            ${this._renderNilmMergeTarget(signature, index)}
            <div class="actions">
              ${this._nilmActionButton(index, "label", "Save Label")}
              ${this._nilmActionButton(index, "ignore", "Ignore", true)}
              ${this._nilmActionButton(index, "mark_expected", "Mark Expected", true)}
              ${this._nilmActionButton(index, "merge", "Merge", true, !(signature.actions && signature.actions.merge && signature.actions.merge.target_options && signature.actions.merge.target_options.length))}
            </div>
          </div>
        `).join("")}
      </section>
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

  _renderRecommendations() {
    const recommendations = this._payload && this._payload.setting_recommendations;
    if (!recommendations || !recommendations.length) {
      return "";
    }
    return `
      <section class="panel">
        <h2>Suggested Settings</h2>
        <div class="entity-list">
          ${recommendations.map((recommendation, index) => `
            <div class="metric">
              <span>${this._escape(recommendation.feature || "Suggested setting")}</span>
              <strong>${this._escape(recommendation.display_label || recommendation.title || "Suggested setting")}</strong>
              ${recommendation.summary ? `<p class="muted">${this._escape(recommendation.summary)}</p>` : ""}
              ${recommendation.reason ? `<p class="muted">${this._escape(recommendation.reason)}</p>` : ""}
              <div class="entity-list">
                ${recommendation.current_value !== undefined ? `<code>Current: ${this._escape(recommendation.current_value)}</code>` : ""}
                ${recommendation.default_value !== undefined ? `<code>Default: ${this._escape(recommendation.default_value)}</code>` : ""}
                ${recommendation.suggested_value !== undefined ? `<code>Suggested: ${this._escape(recommendation.suggested_value)}</code>` : ""}
              </div>
              ${recommendation.expected_effect ? `<p class="muted">Expected effect: ${this._escape(recommendation.expected_effect)}</p>` : ""}
              ${recommendation.evidence_preview ? `<p class="muted">Evidence: ${this._escape(recommendation.evidence_preview)}</p>` : ""}
                <div class="actions">
                 ${this._recommendationActionButton(recommendation, index, "apply", "Apply")}
                 ${this._recommendationActionButton(recommendation, index, "deny", "Deny", true)}
                 ${this._recommendationActionButton(recommendation, index, "dismiss", "Dismiss", true)}
                 ${recommendation.actions && recommendation.actions.undo ? this._recommendationActionButton(recommendation, index, "undo", "Undo", true) : ""}
                 ${recommendation.actions && recommendation.actions.reset ? this._recommendationActionButton(recommendation, index, "reset", "Reset default", true) : ""}
                 ${recommendation.actions && recommendation.actions.preview ? this._recommendationActionButton(recommendation, index, "preview", "Preview evidence", true) : ""}
                </div>
            </div>
          `).join("")}
        </div>
      </section>
    `;
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

    return `
      <svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Alert evidence chart">
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

  _chartSeries() {
    const parsed = [];
    for (const series of this._historySeries || []) {
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
        parsed.push({ entity_id: entityId, name: this._friendlyEntityName(entityId), points });
      }
    }
    return parsed;
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
      ${this._renderRecommendations()}
      ${this._renderNilmActions()}
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
    const disabled = this._busyAction === busyKey || (action && action.enabled === false) ? "disabled" : "";
    const reason = action && (action.unavailable_label || action.unavailable_reason);
    const title = reason ? ` title="${this._escape(reason)}"` : "";
    return `<button data-recommendation-index="${index}" data-recommendation-action="${actionKey}" class="${secondary ? "secondary" : ""}"${title} ${disabled}>${this._escape(label)}</button>`;
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
