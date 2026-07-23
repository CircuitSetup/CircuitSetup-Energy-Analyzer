export function registerDashboardGraphs(CircuitSetupEnergyAnalyzerPanel) {
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
    const title = this._dashboardConfig.title || this._panelText("dashboard_graphs.title");
    const body = this._loading
      ? `<p class="muted">${this._escape(this._panelText("dashboard_graphs.loading"))}</p>`
      : `
        ${this._renderDashboardNotificationGraph(alert)}
        ${workspace ? this._renderNilmWorkspaceSummary(workspace) : ""}
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
          .workspace-summary {
            align-items: end;
            display: grid;
            gap: 8px 16px;
            grid-template-columns: minmax(0, 1fr) auto minmax(160px, 0.8fr);
          }
          .workspace-summary-item,
          .workspace-progress {
            display: grid;
            gap: 3px;
            min-width: 0;
          }
          .workspace-summary-item span,
          .workspace-progress span {
            color: var(--secondary-text-color, #6b7280);
            font-size: 12px;
          }
          .workspace-progress {
            grid-template-columns: minmax(0, 1fr) auto;
          }
          .workspace-progress span {
            grid-column: 1 / -1;
          }
          .workspace-progress progress {
            accent-color: var(--primary-color, #03a9f4);
            height: 8px;
            width: 100%;
          }
          .workspace-progress strong {
            font-size: 13px;
            white-space: nowrap;
          }
          .detail-link {
            color: var(--primary-color, #0b6bcb);
            display: inline-block;
            font-weight: 600;
            margin-top: 8px;
          }
          .chart-frame {
            font-family: Roboto, Noto, sans-serif;
            overflow: visible;
            position: relative;
          }
          .chart {
            display: block;
            height: auto;
            max-width: 100%;
            min-height: 200px;
            width: 100%;
          }
          .chart [data-chart-point] {
            cursor: crosshair;
            opacity: 0.35;
            transition: opacity 120ms ease, r 120ms ease;
          }
          .chart [data-chart-point][data-selected="true"] {
            opacity: 1;
            r: 5px;
            stroke: var(--card-background-color, #fff);
            stroke-width: 2;
          }
          .chart-crosshair {
            display: none;
            pointer-events: none;
            stroke: var(--info-color, var(--primary-color, #03a9f4));
            stroke-width: 1;
          }
          .chart-crosshair[data-visible="true"] {
            display: block;
          }
          .chart-tooltip {
            background: var(--card-background-color, #fff);
            border: 1px solid var(--divider-color, #d8dee6);
            border-radius: var(--ha-border-radius-sm, 4px);
            box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0, 0, 0, 0.16));
            box-sizing: border-box;
            color: var(--primary-text-color, #111827);
            font-size: 12px;
            max-width: calc(100% - 16px);
            padding: 8px 10px;
            pointer-events: none;
            position: absolute;
            z-index: 2;
          }
          .chart-tooltip[aria-hidden="true"] {
            display: none;
          }
          .chart-tooltip-heading {
            display: block;
            white-space: nowrap;
          }
          .chart-tooltip-row {
            align-items: center;
            display: grid;
            gap: 6px;
            grid-template-columns: 10px minmax(0, 1fr) auto;
            margin-top: 4px;
          }
          .chart-tooltip-row > span:nth-child(2) {
            overflow-wrap: anywhere;
          }
          .chart-tooltip-marker {
            border-radius: 50%;
            height: 10px;
            width: 10px;
          }
          .axis,
          .grid {
            stroke: var(--divider-color, #d8dee6);
          }
          .axis-label,
          .chart text {
            fill: var(--primary-text-color, #111827);
            font-size: 12px;
          }
          .legend {
            align-items: center;
            display: flex;
            flex-wrap: wrap;
            font-size: 12px;
            gap: 8px;
            justify-content: center;
            margin-top: 8px;
          }
          .legend-item {
            align-items: center;
            display: inline-flex;
            gap: 6px;
          }
          .swatch {
            border-radius: 50%;
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
          @media (max-width: 520px) {
            .workspace-summary {
              grid-template-columns: minmax(0, 1fr) auto;
            }
            .workspace-progress {
              grid-column: 1 / -1;
            }
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

    this._attachChartInspectors();
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
    const description = alert.what_happened || alert.message || this._panelText("dashboard_graphs.latest_notification");
    return `
      <section>
        <h3>${this._escape(this._panelText("dashboard_graphs.latest_notification"))}</h3>
        <p>${this._escape(description)}</p>
        ${this._renderChart(alert)}
        <a class="detail-link" href="${this._escape(detailPath)}" data-dashboard-alert-detail>${this._escape(this._panelText("dashboard_graphs.view_notification_detail"))}</a>
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
      : `<p class="muted">${this._escape(this._panelText("nilm_workspace.no_graph_history"))}</p>`;
    return `
      <section>
        <h3>${this._escape(this._panelText("dashboard_graphs.title"))}</h3>
        ${graph}
      </section>
    `;
  }
}
  if (!customElements.get("circuitsetup-energy-analyzer-dashboard-graphs")) {
    customElements.define("circuitsetup-energy-analyzer-dashboard-graphs", CircuitSetupEnergyAnalyzerDashboardGraphs);
  }
  return CircuitSetupEnergyAnalyzerDashboardGraphs;
}
