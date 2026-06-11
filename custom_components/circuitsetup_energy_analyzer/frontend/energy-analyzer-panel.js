const EVIDENCE_API_PATH = "/api/circuitsetup_energy_analyzer/alert_evidence";
const EVIDENCE_CALL_API_PATH = "circuitsetup_energy_analyzer/alert_evidence";
const HISTORY_CALL_API_PREFIX = "history/period";
const ROUTE_CHANGE_EVENT = "circuitsetup-energy-analyzer-route-change";
const ROUTE_CHANGE_INSTALL_KEY = "__circuitsetupEnergyAnalyzerRouteChangeInstalled";
const ACTION_SERVICE_NAMES = {
  acknowledge: "acknowledge_alert",
  mark_expected: "mark_alert_expected",
  mark_unhelpful: "mark_alert_unhelpful",
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
    this._loadedRouteKey = "";
    this._evidenceRequestId = 0;
    this._listeningForRouteChanges = false;
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
    if (!action || !this._hass || !this._hass.callService) {
      return;
    }
    this._busyAction = actionKey;
    this._render();
    try {
      await this._hass.callService("circuitsetup_energy_analyzer", action.service, action.data || {});
      await this._loadEvidence({ routeKey: this._routeKey() });
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._render();
    }
  }

  _routeKey() {
    return `${window.location.pathname}${window.location.search}`;
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
      </style>
      <main class="shell">
        <section class="panel">
          <p class="status">${this._escape(statusText)}</p>
          <h1>${this._escape((circuit && circuit.name) || (alert && alert.circuit_id) || "Alert Evidence")}</h1>
          <p class="muted">${this._escape((alert && alert.message) || "Historical alert not found")}</p>
        </section>
        ${this._loading ? `<section class="panel"><p>Loading alert evidence...</p></section>` : ""}
        ${this._error ? `<section class="panel error"><p>${this._escape(this._error)}</p><button class="secondary" id="retry">Retry</button></section>` : ""}
        ${alert ? this._renderAlert(alert, circuit) : this._renderNotFound()}
      </main>
    `;

    this._listen("#retry", () => this._loadEvidence({ routeKey: this._routeKey() }));
    this._listen("#acknowledge", () => this._callAction("acknowledge"));
    this._listen("#mark_expected", () => this._callAction("mark_expected"));
    this._listen("#mark_unhelpful", () => this._callAction("mark_unhelpful"));
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
      <section class="panel summary">
        ${this._metric("Expected", alert.expected_value)}
        ${this._metric("Threshold", alert.threshold)}
        ${this._metric("Samples", alert.sample_count)}
        ${this._metric("First Seen", alert.first_seen)}
        ${this._metric("Last Seen", alert.last_seen)}
        ${this._metric("Check First", alert.what_to_check_first)}
      </section>
      <section class="panel">
        <h2>Evidence Window</h2>
        <p>${this._escape(alert.graph_window_start)} to ${this._escape(alert.graph_window_end)}</p>
      </section>
      <section class="panel">
        <h2>Graph</h2>
        ${this._renderChart()}
      </section>
      <section class="panel">
        <h2>Actions</h2>
        <div class="actions">
          <button id="acknowledge" ${this._disabled("acknowledge")}>Acknowledge</button>
          <button id="mark_expected" class="secondary" ${this._disabled("mark_expected")}>Mark Expected</button>
          <button id="mark_unhelpful" class="secondary" ${this._disabled("mark_unhelpful")}>Mark Unhelpful</button>
        </div>
      </section>
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

  _renderChart() {
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
    return this._chartSvg(series);
  }

  _chartSvg(series) {
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
    const minTime = Math.min(...allPoints.map((point) => point.time));
    const maxTime = Math.max(...allPoints.map((point) => point.time));
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
      return `<div class="legend-item"><span class="swatch" style="background:${color}"></span><code>${this._escape(item.entity_id)}</code></div>`;
    }).join("");
    const minLabel = this._formatNumber(minValue);
    const maxLabel = this._formatNumber(maxValue);
    const startLabel = new Date(minTime).toLocaleString();
    const endLabel = new Date(maxTime).toLocaleString();

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
        parsed.push({ entity_id: entityId, points });
      }
    }
    return parsed;
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
    return `
      <section class="panel">
        <h2>Historical alert not found</h2>
        <p class="muted">The alert from this notification is no longer available. Open a newer notification or review the appliance summary sensors for current evidence.</p>
      </section>
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
    return "Historical alert not found";
  }

  _metric(label, value) {
    return `<div class="metric"><span>${this._escape(label)}</span><strong>${this._escape(value === null || value === undefined ? "Unknown" : value)}</strong></div>`;
  }

  _disabled(actionKey) {
    return this._busyAction === actionKey ? "disabled" : "";
  }

  _formatNumber(value) {
    return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
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

customElements.define("circuitsetup-energy-analyzer-panel", CircuitSetupEnergyAnalyzerPanel);
