const EVIDENCE_API_PATH = "/api/circuitsetup_energy_analyzer/alert_evidence";
const EVIDENCE_CALL_API_PATH = "circuitsetup_energy_analyzer/alert_evidence";
const ACTION_SERVICE_NAMES = {
  acknowledge: "acknowledge_alert",
  mark_expected: "mark_alert_expected",
  mark_unhelpful: "mark_alert_unhelpful",
};

class CircuitSetupEnergyAnalyzerPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._payload = null;
    this._loading = true;
    this._error = "";
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._payload && !this._loading) {
      this._loadEvidence();
    }
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    this._loadEvidence();
  }

  async _loadEvidence() {
    this._loading = true;
    this._error = "";
    this._render();
    const params = new URLSearchParams(window.location.search);
    const query = params.toString();
    const apiPath = `${EVIDENCE_CALL_API_PATH}${query ? `?${query}` : ""}`;
    const fetchPath = `${EVIDENCE_API_PATH}${query ? `?${query}` : ""}`;

    try {
      if (this._hass && this._hass.callApi) {
        this._payload = await this._hass.callApi("GET", apiPath);
      } else {
        const response = await fetch(fetchPath);
        if (!response.ok) {
          throw new Error(`${response.status} ${response.statusText}`);
        }
        this._payload = await response.json();
      }
    } catch (error) {
      this._payload = null;
      this._error = `Could not load alert evidence from ${fetchPath}: ${error.message}`;
    } finally {
      this._loading = false;
      this._render();
    }
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
      await this._loadEvidence();
    } catch (error) {
      this._error = `Could not run ${action.service}: ${error.message}`;
      this._busyAction = "";
      this._render();
    }
  }

  _render() {
    const payload = this._payload;
    const alert = payload && payload.alert;
    const circuit = payload && payload.circuit;
    const statusText = this._statusText(payload && payload.status);
    const graphUrl = this._historyUrl(alert);

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
        ul {
          margin: 10px 0 0;
          padding-left: 20px;
        }
        iframe {
          width: 100%;
          min-height: 420px;
          border: 1px solid var(--divider-color, #d8dde6);
          border-radius: 6px;
          background: var(--primary-background-color, #f7f8fa);
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
        button.secondary, a.button.secondary {
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
        ${alert ? this._renderAlert(alert, circuit, graphUrl) : this._renderNotFound()}
      </main>
    `;

    this._listen("#retry", () => this._loadEvidence());
    this._listen("#acknowledge", () => this._callAction("acknowledge"));
    this._listen("#mark_expected", () => this._callAction("mark_expected"));
    this._listen("#mark_unhelpful", () => this._callAction("mark_unhelpful"));
  }

  _renderAlert(alert, circuit, graphUrl) {
    const graphEntities = alert.graph_entities || [];
    const sourceEntities = alert.source_entities || [];
    return `
      <section class="panel summary">
        ${this._metric("Circuit", (circuit && circuit.name) || alert.circuit_id)}
        ${this._metric("Feature", alert.feature)}
        ${this._metric("Observed", alert.observed_value)}
        ${this._metric("Baseline", alert.baseline_value)}
        ${this._metric("Change", `${alert.percent_change}%`)}
        ${this._metric("Repeated", alert.repeated_count)}
      </section>
      <section class="panel">
        <h2>Evidence Window</h2>
        <p>${this._escape(alert.graph_window_start)} to ${this._escape(alert.graph_window_end)}</p>
      </section>
      <section class="panel">
        <h2>Graph</h2>
        ${graphEntities.length ? `<iframe title="Alert evidence history graph" src="${this._escape(graphUrl)}"></iframe>` : `<p class="muted">Graph entities are not available for this alert.</p>`}
        ${graphEntities.length ? `<p><a class="button secondary" href="${this._escape(graphUrl)}">Open history graph</a></p>` : ""}
      </section>
      <section class="panel">
        <h2>Graph entities</h2>
        ${this._entityList(graphEntities)}
      </section>
      <section class="panel">
        <h2>Source Entities</h2>
        ${this._entityList(sourceEntities)}
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

  _historyUrl(alert) {
    const entities = (alert && alert.graph_entities) || [];
    const query = new URLSearchParams();
    if (entities.length) {
      query.set("entity_id", entities.join(","));
    }
    if (alert && alert.graph_window_start) {
      query.set("start_date", alert.graph_window_start);
    }
    if (alert && alert.graph_window_end) {
      query.set("end_date", alert.graph_window_end);
    }
    const historyQuery = query.toString();
    return historyQuery ? `/history?${historyQuery}` : "/history?entity_id=";
  }

  _metric(label, value) {
    return `<div class="metric"><span>${this._escape(label)}</span><strong>${this._escape(value === null || value === undefined ? "Unknown" : value)}</strong></div>`;
  }

  _entityList(entities) {
    if (!entities || !entities.length) {
      return `<p class="muted">No entities were available for this evidence item.</p>`;
    }
    return `<ul>${entities.map((entityId) => `<li><code>${this._escape(entityId)}</code></li>`).join("")}</ul>`;
  }

  _disabled(actionKey) {
    return this._busyAction === actionKey ? "disabled" : "";
  }

  _escape(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
}

customElements.define("circuitsetup-energy-analyzer-panel", CircuitSetupEnergyAnalyzerPanel);
