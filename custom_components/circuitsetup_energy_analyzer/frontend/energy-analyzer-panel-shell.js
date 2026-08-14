export class PanelShellMethods {
  _render() {
    const nilmFocus = this._nilmFocusState();
    const payload = this._payload;
    const alert = payload && payload.alert;
    const circuit = payload && payload.circuit;
    const nilmWorkspaceRoute = this._routeRequestsNilmWorkspace();
    const applianceDetailRoute = this._routeRequestsApplianceDetail();
    const applianceInsightsRoute = this._routeRequestsApplianceInsights();
    const setupHealthRoute = this._routeRequestsSetupHealth();
    const suggestedSettingsRoute = this._routeRequestsSuggestedSettings();
    const applianceDetail = this._applianceDetail && this._applianceDetail.detail;
    const selectedRecommendation = payload && payload.selected_recommendation;
    const selectedRecommendationLabel = selectedRecommendation
      && (selectedRecommendation.display_label || selectedRecommendation.title || this._panelText("recommendations.suggested_setting"));
    const statusText = selectedRecommendation
      ? this._panelText("headers.suggested_settings")
      : setupHealthRoute
      ? this._setupHealthText("heading")
      : suggestedSettingsRoute
      ? this._panelText("headers.suggested_settings")
      : applianceInsightsRoute
      ? this._panelText("headers.appliance_insights")
      : applianceDetailRoute
      ? this._panelText("headers.appliance_detail")
      : nilmWorkspaceRoute
      ? this._panelText("headers.nilm_workspace")
      : this._statusText(payload && payload.status);
    const headerTitle = selectedRecommendation
      ? this._panelText("recommendations.recommendation_evidence")
      : setupHealthRoute
      ? this._setupHealthText("heading")
      : suggestedSettingsRoute
      ? this._panelText("headers.suggested_settings")
      : applianceInsightsRoute
      ? this._panelText("headers.appliance_insights")
      : applianceDetailRoute
      ? (applianceDetail && applianceDetail.display_name) || this._panelText("headers.appliance_detail")
      : nilmWorkspaceRoute
      ? this._panelText("headers.nilm_workspace")
      : (circuit && circuit.name) || (alert && alert.circuit_id) || this._panelText("headers.alert_evidence");
    const headerMessage = selectedRecommendation
      ? this._panelTextFormat("recommendations.previewing_evidence", { label: selectedRecommendationLabel })
      : setupHealthRoute
      ? this._setupHealthText("header_message")
      : suggestedSettingsRoute
      ? this._panelText("headers.suggested_settings_message")
      : applianceInsightsRoute
      ? this._panelText("headers.appliance_insights_message")
      : applianceDetailRoute
      ? this._applianceDetailHeaderMessage(applianceDetail, this._applianceDetail)
      : nilmWorkspaceRoute
      ? circuit && circuit.name
        ? this._panelTextFormat("headers.nilm_workspace_message_for_circuit", { name: circuit.name })
        : this._panelText("headers.nilm_workspace_message")
      : (alert && alert.message) || (payload && payload.status === "circuit_found_no_evidence" ? this._evidenceText("fallbacks.current_circuit_message") : this._evidenceText("fallbacks.historical_heading"));
    const loadingText = setupHealthRoute
      ? this._setupHealthText("loading")
      : applianceInsightsRoute
      ? this._panelText("appliance_insights.loading")
      : this._evidenceText("loading");

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          background: var(--primary-background-color);
          color: var(--primary-text-color);
          display: block;
          font-family: inherit;
          min-height: 100vh;
          box-sizing: border-box;
          padding: 24px;
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
        .panel,
        .section-surface {
          background: var(--ha-card-background, var(--card-background-color));
          border: var(--ha-card-border-width, 1px) solid
            var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          box-shadow: var(--ha-card-box-shadow);
        }
        .panel {
          padding: 18px;
        }
        .page-header {
          display: grid;
          gap: 8px;
        }
        .page-header h1 {
          color: var(--primary-text-color, #000);
        }
        .summary {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 12px;
        }
        .appliance-daily-metrics {
          margin-top: 16px;
        }
        .evidence-section {
          display: grid;
          gap: 12px;
          min-width: 0;
        }
        .evidence-investigation {
          align-items: start;
          grid-template-columns: minmax(0, 1fr);
          gap: 24px;
        }
        .evidence-explanation {
          display: grid;
          gap: 20px;
        }
        .evidence-explanation section {
          display: grid;
          gap: 6px;
        }
        .section-surface {
          padding: 16px;
        }
        .legend {
          background: var(--card-background-color, #fff);
          padding: 16px 0 0;
        }
        .comparison-scale {
          min-height: 96px;
          margin: 4px 64px 0;
          position: relative;
        }
        .comparison-track {
          background: var(--divider-color, #d8dde6);
          border-radius: 3px;
          height: 6px;
          left: 0;
          position: absolute;
          right: 0;
          top: 42px;
        }
        .comparison-marker {
          bottom: 0;
          color: var(--primary-text-color, #1f2933);
          position: absolute;
          top: 0;
          transform: translateX(-50%);
          width: 2px;
        }
        .comparison-marker::before {
          background: var(--primary-color, #0b6bcb);
          content: "";
          height: 22px;
          left: 0;
          position: absolute;
          top: 32px;
          width: 2px;
        }
        .comparison-marker span,
        .comparison-marker strong {
          left: 50%;
          position: absolute;
          transform: translateX(-50%);
          white-space: nowrap;
        }
        .comparison-marker span {
          color: var(--secondary-text-color, #5f6b7a);
          font-size: 12px;
        }
        .comparison-marker strong {
          font-size: 14px;
        }
        .comparison-metric {
          color: var(--secondary-text-color, #5f6b7a);
          font-size: 13px;
        }
        .comparison-marker.expected span { top: 0; }
        .comparison-marker.expected strong { top: 18px; }
        .comparison-marker.align-left span,
        .comparison-marker.align-left strong {
          left: auto;
          right: 6px;
          transform: none;
        }
        .comparison-marker.align-right span,
        .comparison-marker.align-right strong {
          left: 6px;
          transform: none;
        }
        .comparison-marker.threshold span,
        .comparison-marker.observed span { top: 60px; }
        .comparison-marker.threshold strong,
        .comparison-marker.observed strong { top: 78px; }
        .comparison-marker.threshold::before {
          background: var(--warning-color, #f4b400);
        }
        .comparison-marker.observed::before {
          background: var(--error-color, #db4437);
        }
        .evidence-meta .metric,
        [data-evidence-comparison] .metric {
          background: transparent;
          border: 0;
          border-radius: 0;
          padding: 0;
        }
        [data-evidence-technical] > summary {
          box-sizing: border-box;
          cursor: pointer;
          font-size: 18px;
          font-weight: 700;
          line-height: 20px;
          min-height: 44px;
          padding: 12px 0;
        }
        .disclosure .summary {
          margin-top: 12px;
        }
        .decision-group {
          border: 0;
          display: grid;
          gap: 8px;
          margin: 0;
          min-width: 0;
          padding: 0;
        }
        .decision-group legend,
        .action-disclosure > summary {
          font-size: 18px;
          font-weight: 700;
        }
        .decision-group legend {
          padding: 0;
        }
        .decision-tiles {
          display: grid;
          gap: 10px;
          grid-template-columns: repeat(3, minmax(0, 1fr));
        }
        .decision-tile {
          align-items: start;
          border: 1px solid var(--divider-color, #d8dde6);
          border-radius: 6px;
          cursor: pointer;
          display: grid;
          gap: 10px;
          grid-template-columns: auto auto minmax(0, 1fr);
          min-width: 0;
          padding: 12px;
        }
        .decision-tile:has(input:checked) {
          border-color: var(--primary-color, #0b6bcb);
          box-shadow: inset 0 0 0 1px var(--primary-color, #0b6bcb);
        }
        .decision-tile input {
          margin: 3px 0 0;
        }
        .decision-tile ha-icon,
        .nilm-decision-option ha-icon {
          color: var(--secondary-text-color, #5f6b7a);
        }
        .decision-tile:has(input:checked) ha-icon,
        .decision-tile:has(input:checked) strong,
        .nilm-decision-option:has(input:checked) ha-icon,
        .nilm-decision-option:has(input:checked) strong {
          color: var(--primary-color, #0b6bcb);
        }
        .decision-tile span {
          display: grid;
          gap: 4px;
          min-width: 0;
        }
        .decision-tile small {
          color: var(--secondary-text-color, #5f6b7a);
          line-height: 1.35;
        }
        .response-section > button {
          justify-self: start;
        }
        .inline-feedback {
          border-left: 4px solid var(--success-color, #2e7d32);
          padding: 10px 12px;
        }
        .inline-feedback.error {
          border-left-color: var(--error-color, #db4437);
          color: var(--error-color, #db4437);
        }
        .action-disclosure > summary {
          box-sizing: border-box;
          cursor: pointer;
          line-height: 20px;
          min-height: 44px;
          padding: 12px 0;
        }
        .disclosure-content {
          display: grid;
          gap: 12px;
        }
        @media (min-width: 801px) {
          .evidence-investigation {
            grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
          }
        }
        @media (max-width: 720px) {
          .decision-tiles {
            grid-template-columns: minmax(0, 1fr);
          }
        }
        @media (max-width: 520px) {
          .comparison-scale {
            margin-inline: 44px;
          }
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
        .metric .metric-heading {
          align-items: center;
          display: flex;
          gap: 12px;
          line-height: 16px;
        }
        .metric-heading ha-icon {
          --mdc-icon-size: 16px;
          color: var(--secondary-text-color, #5f6b7a);
          flex: 0 0 16px;
          height: 16px;
          width: 16px;
        }
        .metric .setup-health-status {
          color: var(--primary-text-color, #212121);
        }
        .setup-health-status-ok ha-icon {
          color: var(--success-color, #2e7d32);
        }
        .setup-health-status-needs_attention ha-icon {
          color: var(--warning-color, #f9a825);
        }
        .setup-health-status-optional ha-icon {
          color: var(--secondary-text-color, #5f6b7a);
        }
        .setup-health-status-learning ha-icon {
          color: var(--primary-color, #0b6bcb);
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
          border-radius: 8px;
          padding: 5px 10px;
          background: var(--state-icon-active-color, #0b6bcb);
          color: var(--text-primary-color, #fff);
          font-weight: 700;
          font-size: 13px;
        }
        .safety-notice {
          border-color: var(--divider-color, #d8dde6);
          background: var(--card-background-color, #fff);
        }
        .safety-notice p {
          margin-top: 8px;
        }
        .chart-frame {
          font-family: inherit;
          overflow: visible;
          position: relative;
        }
        .chart {
          display: block;
          height: auto;
          min-height: 200px;
          width: 100%;
        }
        .chart[data-nilm-chart-select] {
          cursor: crosshair;
          touch-action: none;
        }
        .chart text {
          fill: var(--primary-text-color, #1f2933);
          font-size: 12px;
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
          border: 1px solid var(--divider-color, #d8dde6);
          border-radius: var(--ha-border-radius-sm, 4px);
          box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0, 0, 0, 0.16));
          box-sizing: border-box;
          color: var(--primary-text-color, #1f2933);
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
        .nilm-session-band[data-nilm-band-kind="label"] {
          fill: var(--success-color, #15803d);
        }
        .nilm-session-band[data-nilm-band-kind="draft"] {
          fill: var(--primary-color, #03a9f4);
          cursor: pointer;
        }
        .nilm-session-band[data-nilm-selected="true"] {
          opacity: 0.32 !important;
          stroke: var(--primary-color, #03a9f4);
          stroke-width: 3;
        }
        .nilm-boundary-handle {
          cursor: ew-resize;
          outline: none;
        }
        .nilm-boundary-handle-hit {
          stroke: transparent;
          stroke-width: 24;
        }
        .nilm-boundary-handle-line {
          pointer-events: none;
          stroke: var(--primary-color, #03a9f4);
          stroke-width: 4;
        }
        .nilm-boundary-handle:focus {
          outline: 2px solid var(--primary-color, #03a9f4);
          outline-offset: 2px;
        }
        .nilm-boundary-handle:focus .nilm-boundary-handle-line {
          stroke-width: 6;
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
          min-width: 0;
        }
        .swatch {
          border-radius: 50%;
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
          align-items: center;
          appearance: none;
          border: 1px solid var(--primary-color, #0b6bcb);
          border-radius: 6px;
          background: var(--primary-color, #0b6bcb);
          color: var(--text-primary-color, #fff);
          cursor: pointer;
          display: inline-flex;
          font: inherit;
          font-weight: 700;
          gap: 8px;
          justify-content: center;
          line-height: 1.2;
          min-height: 44px;
          padding: 10px 14px;
          text-decoration: none;
        }
        button.secondary, a.button.secondary {
          background: transparent;
          color: var(--primary-color, #0b6bcb);
        }
        .setup-health-actions {
          margin-top: 10px;
        }
        button:disabled {
          cursor: wait;
          opacity: 0.65;
        }
        button:focus-visible,
        a.button:focus-visible,
        .decision-tile:has(input:focus-visible),
        .nilm-decision-option:has(input:focus-visible),
        .nilm-lane:focus-visible,
        .nilm-review-card:focus-visible,
        .nilm-ambiguity-group-toggle:focus-visible,
        .nilm-review-card[aria-pressed="true"]:focus-visible {
          box-shadow:
            0 0 0 2px var(--card-background-color, #fff),
            0 0 0 5px var(--primary-color, #03a9f4);
          outline: none;
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
        .recommendation-layout {
          display: grid;
          gap: 16px;
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .recommendation-heading {
          grid-column: 1 / -1;
        }
        .recommendation-summary,
        .recommendation-support,
        .setting-impact-preview,
        .recommendation-support-copy {
          display: grid;
          gap: 8px;
          min-width: 0;
        }
        .recommendation-values {
          display: grid;
          gap: 6px;
          margin-top: 10px;
        }
        .recommendation-value {
          align-items: baseline;
          display: grid;
          gap: 12px;
          grid-template-columns: minmax(90px, auto) minmax(0, 1fr);
        }
        .recommendation-value span,
        .recommendation-value strong {
          font-size: 14px;
          margin: 0;
        }
        .recommendation-evidence-line {
          display: block;
        }
        .recommendation-support-row {
          align-items: start;
          color: var(--secondary-text-color, #5f6b7a);
          display: grid;
          font-size: 14px;
          gap: 12px;
          grid-template-columns: minmax(110px, 0.45fr) minmax(0, 1fr);
          min-width: 0;
        }
        .recommendation-support-copy {
          gap: 4px;
        }
        .recommendation-support-row .recommendation-support-copy,
        .recommendation-support-row .recommendation-evidence-line {
          color: inherit;
          font-size: inherit;
          margin: 0;
        }
        .recommendation-support-row > strong,
        .recommendation-support-row p,
        .recommendation-support-row .muted {
          color: inherit;
          font-size: inherit;
          margin: 0;
        }
        .recommendation-summary,
        .recommendation-support {
          align-content: start;
        }
        .recommendation-evidence-actions {
          margin-top: 16px;
        }
        .selected-recommendation-evidence .recommendation-summary,
        .selected-recommendation-evidence .recommendation-support {
          align-content: start;
        }
        .selected-recommendation-evidence h2,
        .selected-recommendation-evidence strong {
          color: var(--primary-text-color, #000);
        }
        .selected-recommendation-evidence p,
        .selected-recommendation-evidence .muted {
          color: var(--primary-text-color, #1f2933);
        }
        .selected-recommendation-evidence .recommendation-support-row,
        .selected-recommendation-evidence .recommendation-support-row strong,
        .selected-recommendation-evidence .recommendation-support-row p {
          color: var(--secondary-text-color, #5f6b7a);
        }
        .recommendation-evidence-graph {
          display: grid;
          gap: 8px;
          margin-top: 16px;
        }
        .appliance-insights-controls {
          align-items: end;
          display: grid;
          gap: 12px 24px;
          grid-template-columns: minmax(0, 1fr) minmax(180px, 240px);
        }
        .appliance-insights-filters {
          border: 0;
          display: flex;
          flex-wrap: wrap;
          gap: 10px 18px;
          margin: 0;
          padding: 0;
        }
        .appliance-insights-filters legend {
          font-weight: 700;
          margin-bottom: 8px;
          padding: 0;
          width: 100%;
        }
        .appliance-insights-filters label {
          align-items: center;
          display: inline-flex;
          gap: 6px;
          min-height: 32px;
        }
        .appliance-insights-sort {
          display: grid;
          gap: 6px;
        }
        .appliance-insights-sort select {
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #d8dde6);
          border-radius: 6px;
          color: var(--primary-text-color, #111827);
          font: inherit;
          min-height: 44px;
          padding: 8px 10px;
          width: 100%;
        }
        .appliance-insights-table-wrap {
          overflow-x: auto;
        }
        .appliance-insights-table {
          border-collapse: collapse;
          min-width: 920px;
          width: 100%;
        }
        .appliance-insights-table th,
        .appliance-insights-table td {
          border-bottom: 1px solid var(--divider-color, #d8dde6);
          padding: 12px 10px;
          text-align: left;
          vertical-align: top;
        }
        .appliance-insights-table th {
          color: var(--secondary-text-color, #5f6b7a);
          font-size: 12px;
          font-weight: 700;
        }
        .appliance-insights-table td:first-child {
          font-weight: 700;
        }
        .appliance-insights-table a {
          color: var(--primary-color, #0b6bcb);
          overflow-wrap: anywhere;
        }
        .appliance-insights-table small {
          color: var(--secondary-text-color, #5f6b7a);
          display: block;
          line-height: 1.35;
          margin-top: 4px;
        }
        .energy-change-list {
          display: grid;
          gap: 6px;
          margin: 12px 0 0;
          padding-left: 20px;
        }
        .appliance-comparison-table {
          border-collapse: collapse;
          width: 100%;
        }
        .appliance-comparison-table th,
        .appliance-comparison-table td {
          border-bottom: 1px solid var(--divider-color, #d8dde6);
          padding: 10px;
          text-align: left;
          vertical-align: top;
        }
        .appliance-comparison-table th,
        .appliance-comparison-table p {
          color: var(--secondary-text-color, #5f6b7a);
          font-size: 12px;
        }
        .appliance-comparison-table p { margin: 4px 0 0; }
        .appliance-comparison-table ha-icon { vertical-align: middle; }
        .appliance-comparison-as-of {
          font-size: var(--ha-font-size-s, 12px);
        }
        .appliance-section-heading {
          align-items: center;
          display: flex;
          gap: 12px;
          justify-content: space-between;
        }
        .appliance-graph-heading {
          align-items: flex-start;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .appliance-graph-toolbar,
        .appliance-period-controls {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .appliance-graph-toolbar [data-appliance-history-graph] {
          display: grid;
          gap: 4px;
        }
        .appliance-graph-toolbar {
          align-items: flex-start;
          flex-direction: column;
        }
        .appliance-period-button {
          background: var(--secondary-background-color, #f4f6f8);
          border-color: transparent;
          color: var(--primary-text-color, #1f2933);
          min-height: 36px;
          padding: 6px 9px;
          width: auto;
        }
        .appliance-period-button[aria-pressed="true"] {
          background: var(--primary-color, #0b6bcb);
          color: var(--text-primary-color, #fff);
        }
        .sump-driver-summary {
          display: grid;
          gap: 8px;
          grid-template-columns: repeat(4, minmax(0, 1fr));
          margin: 12px 0;
        }
        .sump-driver-summary-item {
          align-items: center;
          background: var(--secondary-background-color, #f4f6f8);
          border-radius: 8px;
          display: grid;
          gap: 4px 8px;
          grid-template-columns: auto minmax(0, 1fr);
          min-width: 0;
          padding: 10px;
        }
        .sump-driver-summary-item .muted {
          grid-column: 2;
          margin: 0;
        }
        .sump-driver-layers {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin: 10px 0;
        }
        .sump-driver-layer {
          background: var(--secondary-background-color, #f4f6f8);
          border-color: transparent;
          color: var(--primary-text-color, #1f2933);
          min-height: 36px;
          padding: 6px 9px;
        }
        .sump-driver-layer[aria-pressed="false"] {
          text-decoration: line-through;
        }
        .sump-driver-layer[aria-pressed="false"] .swatch {
          opacity: 0.35;
        }
        .sump-cycle-marker {
          opacity: 0.55;
          stroke-dasharray: 3 3;
          stroke-width: 2;
        }
        .sump-cycle-dot {
          stroke: var(--card-background-color, #fff);
          stroke-width: 2;
        }
        .appliance-behavior-grid {
          display: grid;
          gap: 12px;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          margin-top: 12px;
        }
        .appliance-detail-block {
          background: var(--secondary-background-color, #f4f6f8);
          border: 1px solid var(--divider-color, #d8dde6);
          border-radius: 8px;
          min-width: 0;
          padding: 14px;
        }
        .appliance-detail-block h3 {
          align-items: center;
          display: flex;
          font-size: 15px;
          gap: 8px;
          margin: 0 0 10px;
        }
        .appliance-detail-block h3 ha-icon {
          --mdc-icon-size: 20px;
          color: var(--primary-color, #0b6bcb);
        }
        .appliance-detail-block .entity-list,
        .appliance-detail-block .summary {
          grid-template-columns: 1fr;
        }
        .appliance-detail-block .metric {
          background: transparent;
          border: 0;
          border-bottom: 1px solid var(--divider-color, #d8dde6);
          border-radius: 0;
          padding: 8px 0;
        }
        .appliance-detail-block .metric:last-child {
          border-bottom: 0;
        }
        .metric .appliance-expectation-title {
          font-size: var(--ha-font-size-s, 13px);
        }
        .appliance-predictive-health {
          border-top: 1px solid var(--divider-color, #d8dde6);
          margin-top: 12px;
          padding-top: 12px;
        }
        .hvac-efficiency-layout {
          align-items: stretch;
          display: grid;
          gap: 16px;
          grid-template-columns: 210px minmax(0, 1fr);
          margin-top: 12px;
        }
        .hvac-efficiency-score {
          align-items: center;
          background: var(--secondary-background-color, #f4f6f8);
          border: 1px solid var(--divider-color, #d8dde6);
          border-radius: 8px;
          display: flex;
          flex-direction: column;
          justify-content: center;
          min-height: 175px;
          padding: 14px;
          text-align: center;
        }
        .hvac-efficiency-gauge {
          align-items: end;
          background: conic-gradient(from 270deg, var(--primary-color, #0b6bcb) 0 var(--hvac-score), var(--divider-color, #d8dde6) var(--hvac-score) 50%, transparent 50%);
          border-radius: 100% 100% 0 0;
          display: flex;
          height: 76px;
          justify-content: center;
          margin-bottom: 8px;
          overflow: hidden;
          position: relative;
          width: 150px;
        }
        .hvac-efficiency-gauge::before {
          background: var(--secondary-background-color, #f4f6f8);
          border-radius: 100% 100% 0 0;
          bottom: 0;
          content: "";
          height: 52px;
          position: absolute;
          width: 106px;
        }
        .hvac-efficiency-gauge strong {
          font-size: 28px;
          line-height: 1;
          position: relative;
          z-index: 1;
        }
        .hvac-efficiency-gauge.learning {
          --hvac-score: 0%;
        }
        .hvac-efficiency-thermostats,
        .hvac-efficiency-mode {
          display: grid;
          gap: 10px;
        }
        .hvac-efficiency-row {
          border: 1px solid var(--divider-color, #d8dde6);
          border-radius: 8px;
          padding: 12px;
        }
        .hvac-efficiency-row .metric {
          background: transparent;
        }
        .appliance-timeline {
          list-style: none;
          margin: 0;
          padding: 2px 0 0;
        }
        .appliance-timeline-item {
          display: grid;
          gap: 4px;
          min-height: 58px;
          padding: 0 0 18px 30px;
          position: relative;
        }
        .appliance-timeline-item::before {
          background: var(--divider-color, #d8dde6);
          bottom: 0;
          content: "";
          left: 8px;
          position: absolute;
          top: 12px;
          width: 2px;
        }
        .appliance-timeline-item::after {
          background: var(--primary-color, #0b6bcb);
          border: 3px solid var(--card-background-color, #fff);
          border-radius: 50%;
          content: "";
          height: 10px;
          left: 1px;
          position: absolute;
          top: 4px;
          width: 10px;
        }
        .appliance-timeline-item:last-child {
          padding-bottom: 0;
        }
        .appliance-timeline-item:last-child::before {
          display: none;
        }
        .appliance-timeline-item time {
          color: var(--secondary-text-color, #5f6b7a);
          font-size: 12px;
        }
        .appliance-timeline-item p {
          margin: 0;
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
          background: var(--ha-card-background, var(--card-background-color));
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          color: var(--primary-text-color, #111827);
          font: inherit;
          padding: 8px 10px;
        }
        .nilm-label-field select {
          background: var(--ha-card-background, var(--card-background-color));
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          color: var(--primary-text-color, #111827);
          font: inherit;
          min-width: 0;
          padding: 8px 10px;
        }
        .nilm-decision-options {
          display: grid;
          gap: 8px;
        }
        .nilm-decision-option {
          align-items: center;
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          cursor: pointer;
          display: grid;
          gap: 8px;
          grid-template-columns: auto 24px minmax(0, 1fr);
          padding: 10px;
        }
        .nilm-decision-option:has(input:checked) {
          border-color: var(--primary-color, #0b6bcb);
          box-shadow: inset 0 0 0 1px var(--primary-color, #0b6bcb);
        }
        .nilm-decision-option input {
          margin: 0;
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
        .nilm-interval-form input,
        .nilm-interval-form select {
          background: var(--ha-card-background, var(--card-background-color));
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
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
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          color: var(--primary-text-color, #111827);
          cursor: pointer;
          font: inherit;
          padding: 7px 11px;
        }
        .merge-target-chip[aria-pressed="true"] {
          background: var(--primary-color, #0b6bcb);
          border-color: var(--primary-color, #0b6bcb);
          color: var(--text-primary-color, #fff);
        }
        .workspace-section {
          background: var(--ha-card-background, var(--card-background-color));
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          display: grid;
          gap: 12px;
          min-width: 0;
        }
        .nilm-interval-rows {
          display: grid;
          gap: 10px;
          margin: 12px 0;
        }
        .nilm-interval-row {
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          display: grid;
          gap: 8px;
          padding: 10px;
        }
        .nilm-interval-row[data-nilm-active="true"] {
          border-color: var(--primary-color, #0b6bcb);
          box-shadow: inset 0 0 0 1px var(--primary-color, #0b6bcb);
        }
        .nilm-interval-row-heading {
          align-items: center;
          display: grid;
          gap: 8px;
          grid-template-columns: auto minmax(0, 1fr) auto;
        }
        .nilm-interval-row-heading span {
          color: var(--primary-color, #0b6bcb);
          font-size: 12px;
        }
        .nilm-workspace {
          display: grid;
          gap: 18px;
          min-width: 0;
        }
        .workspace-summary {
          align-items: end;
          display: grid;
          gap: 8px 20px;
          grid-template-columns: minmax(0, 1fr) auto minmax(180px, 0.8fr);
          min-width: 0;
        }
        .workspace-summary-item,
        .workspace-progress {
          display: grid;
          gap: 3px;
          min-width: 0;
        }
        .workspace-summary-item span,
        .workspace-progress span {
          color: var(--secondary-text-color, #5f6b7a);
          font-size: 12px;
        }
        .workspace-summary-item strong {
          overflow-wrap: anywhere;
        }
        .workspace-summary .nilm-label-field {
          margin-top: 0;
        }
        .workspace-progress {
          grid-template-columns: minmax(0, 1fr) auto;
        }
        .workspace-progress span {
          grid-column: 1 / -1;
        }
        .workspace-progress progress {
          accent-color: var(--primary-color, #0b6bcb);
          align-self: center;
          height: 8px;
          width: 100%;
        }
        .workspace-progress strong {
          font-size: 13px;
          white-space: nowrap;
        }
        .nilm-lanes {
          display: flex;
          gap: 8px;
          overflow-x: auto;
          padding-bottom: 4px;
        }
        .nilm-lane {
          background: var(--ha-card-background, var(--card-background-color));
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          color: var(--primary-text-color, #111827);
          flex: 0 0 auto;
          gap: 8px;
          min-height: 44px;
          padding-inline: 6px;
          white-space: nowrap;
        }
        .nilm-lane[aria-selected="true"] {
          border-color: var(--primary-color, #0b6bcb);
          box-shadow: inset 0 -2px 0 var(--primary-color, #0b6bcb);
          color: var(--primary-text-color, #111827);
        }
        .nilm-lane strong {
          align-items: center;
          background: var(--secondary-background-color, #f4f6f8);
          border-radius: 8px;
          display: inline-flex;
          justify-content: center;
          min-height: 24px;
          min-width: 24px;
          padding: 0 6px;
        }
        .nilm-review-layout {
          align-items: start;
          display: grid;
          gap: 16px;
          grid-template-columns: minmax(240px, 0.8fr) minmax(0, 1.6fr);
          min-width: 0;
        }
        .nilm-review-list {
          display: grid;
          gap: 10px;
          min-width: 0;
        }
        [data-nilm-lane-description] {
          grid-column: 1 / -1;
        }
        .nilm-review-card {
          background: var(--ha-card-background, var(--card-background-color));
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          color: var(--primary-text-color, #111827);
          display: grid;
          gap: 10px;
          justify-content: stretch;
          min-height: 132px;
          text-align: left;
          width: 100%;
        }
        .nilm-review-card[aria-pressed="true"] {
          border-color: var(--primary-color, #0b6bcb);
          box-shadow: inset 0 0 0 1px var(--primary-color, #0b6bcb);
        }
        .review-card-heading,
        .review-card-facts {
          align-items: baseline;
          display: flex;
          gap: 12px;
          justify-content: space-between;
          min-width: 0;
        }
        .review-card-heading {
          flex-wrap: wrap;
        }
        .review-card-context {
          flex-wrap: wrap;
        }
        .review-card-heading strong {
          overflow-wrap: anywhere;
        }
        .review-card-heading span,
        .review-card-facts {
          color: var(--secondary-text-color, #5f6b7a);
          font-size: 12px;
          overflow-wrap: anywhere;
        }
        .power-meter {
          background: var(--divider-color, #d8dde6);
          border-radius: 3px;
          display: block;
          height: 6px;
          overflow: hidden;
          width: 100%;
        }
        .power-meter > span {
          background: var(--primary-color, #0b6bcb);
          display: block;
          height: 100%;
          width: var(--power-percent, 0%);
        }
        .nilm-review-card progress {
          accent-color: var(--primary-color, #0b6bcb);
          height: 8px;
          width: 100%;
        }
        .nilm-review-inspector {
          background: var(--ha-card-background, var(--card-background-color));
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          display: grid;
          gap: 10px;
          min-width: 0;
        }
        .nilm-review-card[aria-pressed="true"] .review-card-heading strong {
          color: var(--primary-text-color, #111827);
        }
        .nilm-lane-empty {
          min-height: 44px;
          padding: 12px 0;
        }
        .nilm-ambiguity-audit {
          border-color: var(--divider-color, #d8dde6);
        }
        .nilm-ambiguity-audit > h2,
        .nilm-ambiguity-audit > p {
          margin: 0;
        }
        .nilm-ambiguity-details > p {
          margin: 0;
        }
        .nilm-ambiguity-groups,
        .nilm-ambiguity-occurrence-list {
          display: grid;
          gap: 10px;
          min-width: 0;
        }
        .nilm-ambiguity-group,
        .nilm-ambiguity-occurrence {
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          display: grid;
          gap: 8px;
          min-width: 0;
          padding: 10px;
        }
        .nilm-ambiguity-occurrence[data-nilm-selected="true"] {
          border-color: var(--primary-color, #03a9f4);
          box-shadow: 0 0 0 1px var(--primary-color, #03a9f4);
        }
        .nilm-ambiguity-group > p,
        .nilm-ambiguity-occurrence > p,
        .nilm-ambiguity-occurrence details > p {
          margin: 0;
          overflow-wrap: anywhere;
        }
        .nilm-ambiguity-group-toggle {
          align-items: center;
          display: flex;
          justify-content: space-between;
          min-width: 0;
          text-align: left;
          width: 100%;
        }
        .nilm-ambiguity-group-toggle > span {
          overflow-wrap: anywhere;
        }
        .nilm-ambiguity-occurrence details {
          min-width: 0;
        }
        .nilm-ambiguity-occurrence ul {
          margin: 0;
          overflow-wrap: anywhere;
          padding-inline-start: 20px;
        }
        .nilm-evidence-section {
          border-color: var(--divider-color, #d8dde6);
        }
        .nilm-evidence-details,
        .nilm-estimate-quality,
        .nilm-known-load-attributions,
        .nilm-known-load-attribution,
        .nilm-session-pagination {
          display: grid;
          gap: 10px;
          min-width: 0;
        }
        .nilm-evidence-details > summary {
          cursor: pointer;
          font-size: 18px;
          font-weight: 700;
          min-height: 44px;
          padding-block: 8px;
        }
        .nilm-evidence-summary {
          background: transparent;
          border: 0;
          color: var(--primary-text-color, #212121);
          cursor: pointer;
          font: inherit;
          font-size: 18px;
          font-weight: 700;
          min-height: 44px;
          padding: 8px 0;
          text-align: left;
        }
        .nilm-estimate-quality-rows,
        .nilm-known-load-attributions {
          display: grid;
          gap: 12px;
          min-width: 0;
        }
        .nilm-estimate-quality-row,
        .nilm-known-load-attribution {
          border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
          border-radius: var(--ha-card-border-radius, 12px);
          padding: 12px;
        }
        .nilm-estimate-quality-heading {
          align-items: center;
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          justify-content: space-between;
        }
        .nilm-quality-chip {
          border-radius: 8px;
          font-size: 12px;
          font-weight: 700;
          padding: 4px 8px;
        }
        .nilm-quality-complete {
          background: color-mix(in srgb, var(--success-color, #2e7d32) 18%, transparent);
          color: #1b5e20;
        }
        .nilm-quality-partial_history,
        .nilm-quality-legacy_unverified {
          background: color-mix(in srgb, var(--warning-color, #b26a00) 18%, transparent);
          color: var(--warning-color, #8a5200);
        }
        .nilm-quality-ambiguous {
          background: color-mix(in srgb, var(--error-color, #ba1a1a) 16%, transparent);
          color: var(--error-color, #ba1a1a);
        }
        .nilm-evidence-facts {
          display: grid;
          gap: 8px;
          grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
          margin: 0;
        }
        .nilm-evidence-facts > div {
          min-width: 0;
        }
        .nilm-evidence-facts dt {
          color: var(--secondary-text-color, #5f6b7a);
          font-size: 12px;
        }
        .nilm-evidence-facts dd {
          font-weight: 600;
          margin: 3px 0 0;
          overflow-wrap: anywhere;
        }
        .nilm-evidence-details-list {
          margin-block: 10px;
        }
        .nilm-known-load-attribution h4,
        .nilm-estimate-quality h3 {
          margin: 0;
        }
        .nilm-conservation-check {
          border-inline-start: 3px solid var(--primary-color, #03a9f4);
          margin: 0;
          padding-inline-start: 8px;
        }
        .nilm-rejected-candidates {
          margin: 8px 0 0;
          padding-inline-start: 20px;
        }
        .nilm-interval-quality {
          margin: 8px 0 0;
          overflow-wrap: anywhere;
        }
        .nilm-interval-quality-caution {
          color: var(--warning-color, #8a5200);
        }
        .nilm-interval-quality-blocking {
          color: var(--error-color, #ba1a1a);
        }
        .nilm-session-pagination {
          align-items: start;
          margin-top: 10px;
        }
        .sr-only {
          height: 1px;
          margin: -1px;
          overflow: hidden;
          padding: 0;
          position: absolute;
          width: 1px;
          clip: rect(0, 0, 0, 0);
          white-space: nowrap;
        }
        .icon-button,
        .nilm-graph-controls button {
          height: 44px;
          padding: 0;
          width: 44px;
        }
        .decision-tile,
        .nilm-lane,
        .nilm-review-card,
        .icon-button {
          min-height: 44px;
        }
        .loading-skeleton {
          background: var(--secondary-background-color, #f4f6f8);
          min-height: 180px;
          opacity: 0.72;
        }
        .graph-loading-skeleton {
          min-height: 340px;
        }
        .nilm-loading-skeleton {
          min-height: 480px;
        }
        @media (min-width: 801px) {
          .nilm-review-layout {
            grid-template-columns: minmax(240px, 0.8fr) minmax(0, 1.6fr);
          }
          .nilm-review-inspector {
            align-self: start;
            grid-column: 2;
            grid-row: auto;
            padding: 16px;
          }
        }
        @media (max-width: 800px) {
          :host {
            padding: 16px;
          }
          .evidence-investigation,
          .appliance-detail-overview,
          .appliance-behavior-grid,
          .hvac-efficiency-layout,
          .recommendation-layout,
          .nilm-review-layout {
            grid-template-columns: minmax(0, 1fr);
          }
          .nilm-review-card,
          .nilm-review-list,
          .nilm-review-inspector {
            grid-column: 1;
            grid-row: auto;
          }
          .workspace-summary {
            grid-template-columns: minmax(0, 1fr) auto;
          }
          .workspace-progress {
            grid-column: 1 / -1;
          }
          .nilm-evidence-facts {
            grid-template-columns: minmax(0, 1fr);
          }
          .appliance-insights-controls {
            grid-template-columns: minmax(0, 1fr);
          }
          .sump-driver-summary {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
          .appliance-insights-table {
            min-width: 0;
          }
          .appliance-insights-table thead {
            clip: rect(0 0 0 0);
            clip-path: inset(50%);
            height: 1px;
            overflow: hidden;
            position: absolute;
            white-space: nowrap;
            width: 1px;
          }
          .appliance-insights-table tbody,
          .appliance-insights-table tr,
          .appliance-insights-table td {
            display: block;
            width: 100%;
          }
          .appliance-insights-table tr {
            border-bottom: 1px solid var(--divider-color, #d8dde6);
            padding: 10px 0;
          }
          .appliance-insights-table td {
            border: 0;
            box-sizing: border-box;
            display: grid;
            gap: 12px;
            grid-template-columns: minmax(112px, 0.7fr) minmax(0, 1fr);
            padding: 7px 0;
          }
          .appliance-insights-table td::before {
            color: var(--secondary-text-color, #5f6b7a);
            content: attr(data-label);
            font-size: 12px;
            font-weight: 700;
          }
          .appliance-comparison-table,
          .appliance-comparison-table tbody,
          .appliance-comparison-table tr,
          .appliance-comparison-table td {
            display: block;
            width: 100%;
          }
          .appliance-comparison-table thead {
            clip: rect(0 0 0 0);
            clip-path: inset(50%);
            height: 1px;
            overflow: hidden;
            position: absolute;
            white-space: nowrap;
            width: 1px;
          }
          .appliance-comparison-table tr {
            border-bottom: 1px solid var(--divider-color, #d8dde6);
            padding: 8px 0;
          }
          .appliance-comparison-table td {
            border: 0;
            box-sizing: border-box;
            display: grid;
            gap: 8px;
            grid-template-columns: minmax(88px, 0.55fr) minmax(0, 1fr);
            padding: 5px 0;
          }
          .appliance-comparison-table td::before {
            color: var(--secondary-text-color, #5f6b7a);
            content: attr(data-label);
            font-size: 12px;
          }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            scroll-behavior: auto;
            transition-duration: 0.01ms !important;
          }
        }
      </style>
      <main class="shell">
        <header class="page-header">
          <p class="status">${this._escape(statusText)}</p>
          <h1>${this._escape(headerTitle)}</h1>
          <p class="muted">${this._escape(headerMessage)}</p>
          ${!setupHealthRoute && !suggestedSettingsRoute && !applianceInsightsRoute && !applianceDetailRoute && !nilmWorkspaceRoute && alert && alert.last_seen ? `<p class="muted evidence-timestamp"><strong>${this._escape(this._panelText("evidence.labels.last_seen"))}:</strong> ${this._escape(this._formatDateTime(alert.last_seen))}</p>` : ""}
        </header>
      ${this._loading ? `<section class="panel loading-skeleton ${nilmWorkspaceRoute ? "nilm-loading-skeleton" : ""}" data-loading-skeleton role="status" aria-label="${this._escape(loadingText)}"></section>` : ""}
      ${this._lastActionMessage ? `<section class="panel"><p>${this._escape(this._lastActionMessage)}</p></section>` : ""}
      ${this._error ? `<section class="panel error"><p>${this._escape(this._error)}</p><button class="secondary" id="retry">${this._escape(this._panelText("common.retry"))}</button></section>` : ""}
      ${selectedRecommendation ? this._renderSelectedRecommendationEvidence() : (this._routeRequestsSetupHealth() ? this._renderSetupHealthBody() : (this._routeRequestsSuggestedSettings() ? this._renderSuggestedSettingsBody() : (this._routeRequestsApplianceInsights() ? this._renderApplianceInsightsBody() : (this._routeRequestsApplianceDetail() ? this._renderApplianceDetailBody() : (this._routeRequestsNilmWorkspace() ? this._renderNilmWorkspaceBody() : this._renderEvidenceBody(alert, circuit))))))}
      ${this._renderActionConfirmation()}
      </main>
    `;

    this._attachChartInspectors();
    this._listen("#retry", () => this._loadEvidence({ routeKey: this._routeKey() }));
    this._listen("[data-retry-alert-history]", () => {
      const historySource = this._evidenceHistorySource();
      return historySource
        ? this._loadHistory(historySource, this._evidenceRequestId, this._loadedRouteKey || this._routeKey())
        : undefined;
    });
    this._listen("[data-retry-appliance-history]", () => (
      this._loadApplianceDetailHistories(
        this._applianceDetailHistoryHours,
        this._evidenceRequestId,
        this._loadedRouteKey || this._routeKey(),
        this._applianceDetailHistoryBounds?.max,
      )
    ));
    this._listen("[data-retry-sump-driver-history]", () => (
      this._loadSumpDriverHistory(
        this._applianceDetailHistoryHours,
        this._evidenceRequestId,
        this._loadedRouteKey || this._routeKey(),
        this._applianceDetailHistoryBounds?.max,
      )
    ));
    for (const button of this.shadowRoot.querySelectorAll("[data-appliance-history-period]")) {
      button.addEventListener("click", () => {
        this._loadApplianceDetailHistories(
          Number(button.dataset.applianceHistoryPeriod),
          this._evidenceRequestId,
          this._loadedRouteKey || this._routeKey(),
        );
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-appliance-daily-period]")) {
      button.addEventListener("click", () => {
        this._applianceDetailDailyPeriodDays = Number(button.dataset.applianceDailyPeriod);
        this._render();
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-sump-driver-layer]")) {
      button.addEventListener("click", () => {
        this._sumpDriverHiddenLayers ||= new Set();
        const layer = button.dataset.sumpDriverLayer;
        if (this._sumpDriverHiddenLayers.has(layer)) this._sumpDriverHiddenLayers.delete(layer);
        else this._sumpDriverHiddenLayers.add(layer);
        this._render();
      });
    }
    this._listen("[data-retry-nilm-workspace]", () => (
      this._loadNilmWorkspace(this._evidenceRequestId, this._loadedRouteKey || this._routeKey())
    ));
    this._listen("[data-nilm-sensitivity-action]", () => this._applyNilmSensitivity());
    for (const select of this.shadowRoot.querySelectorAll("[data-nilm-source-picker]")) {
      select.addEventListener("change", () => this._navigate(select.value));
    }
    this._listen("[data-retry-nilm-history]", () => {
      const failedRequest = this._nilmWorkspaceHistoryFailedRequest;
      return failedRequest
        ? this._loadNilmWorkspaceHistoryForWindow(
          failedRequest.window,
          failedRequest,
        )
        : this._loadNilmWorkspaceHistory(
          this._nilmWorkspace,
          this._evidenceRequestId,
          this._loadedRouteKey || this._routeKey(),
        );
    });
    this._listen("#apply_alert_decision", () => this._applyAlertDecision());
    for (const input of this.shadowRoot.querySelectorAll("[data-alert-decision]")) {
      input.addEventListener("change", () => {
        this._alertDecision = input.value;
        const applyButton = this.shadowRoot.querySelector("#apply_alert_decision");
        if (applyButton) {
          applyButton.disabled = false;
        }
      });
    }
    this._listen("#pause_alerts", () => this._callAction("pause_alerts"));
    this._listen("#relearn_baseline", () => this._requestActionConfirmation("relearn_baseline"));
    this._listen("#mark_circuit_mixed", () => this._requestActionConfirmation("mark_circuit_mixed"));
    this._listen("#cancel_action_confirmation", () => this._cancelActionConfirmation());
    this._listen("#confirm_action", () => this._confirmPendingAction());
    const confirmationDialog = this.shadowRoot.querySelector("#action_confirmation_dialog");
    if (confirmationDialog) {
      confirmationDialog.addEventListener("closed", () => {
        if (
          this._pendingConfirmationAction
          && this.shadowRoot.querySelector("#action_confirmation_dialog") === confirmationDialog
        ) {
          this._cancelActionConfirmation();
        }
      }, { once: true });
    }
    this._listen("#open_appliance_detail", () => this._callAction("open_appliance_detail"));
    this._listen("#open_load_separation", () => this._callAction("open_load_separation"));
    this._listen("#open_advanced_circuit_settings", () => this._callAction("open_advanced_circuit_settings"));
    this._listen("[data-save-weekly-digest]", () => this._saveWeeklyDigestSettings());
    for (const button of this.shadowRoot.querySelectorAll("[data-recommendation-action]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.recommendationIndex, 10);
        this._callRecommendationAction(index, button.dataset.recommendationAction);
      });
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-decision]")) {
      input.addEventListener("change", () => {
        const current = this._nilmDecisionDrafts.get(input.dataset.nilmDecisionKey) || { decision: "", identifyMode: "assign" };
        this._nilmDecisionDrafts.set(input.dataset.nilmDecisionKey, Object.assign({}, current, { decision: input.value }));
        this._render();
      });
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-identify-mode]")) {
      input.addEventListener("change", () => {
        const current = this._nilmDecisionDrafts.get(input.dataset.nilmDecisionKey) || { decision: "identify", identifyMode: "assign" };
        this._nilmDecisionDrafts.set(input.dataset.nilmDecisionKey, Object.assign({}, current, { identifyMode: input.value }));
        this._render();
      });
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-decision-assignment-key]")) {
      input.addEventListener("change", () => {
        const current = this._nilmDecisionDrafts.get(input.dataset.nilmDecisionAssignmentKey) || { decision: "identify", identifyMode: "assign" };
        this._nilmDecisionDrafts.set(input.dataset.nilmDecisionAssignmentKey, Object.assign({}, current, { assignmentId: input.value }));
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-apply-decision]")) {
      button.addEventListener("click", () => {
        this._applyNilmDecision(button.dataset.nilmApplyDecision);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-signature-action]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.nilmSignatureIndex || "-1", 10);
        const sourceKey = `signature_${index}`;
        const signature = this._decisionSignature(sourceKey);
        this._callNilmAction(signature, sourceKey, button.dataset.nilmSignatureAction);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-primary-confirm]")) {
      button.addEventListener("click", () => this._callNilmConfiguredPrimaryAction());
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-lane]")) {
      button.addEventListener("click", () => this._activateNilmLane(button.dataset.nilmLane));
      button.addEventListener("keydown", (event) => this._handleNilmLaneKeydown(event, button));
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-review-item]")) {
      button.addEventListener("click", () => {
        this._nilmSelectedReviewKey = button.dataset.nilmReviewItem;
        this._nilmSyncHelperSelection(this._nilmWorkspace);
        const reviewItem = this._nilmSelectedReviewItem(this._nilmWorkspace);
        this._render();
        void this._focusNilmReviewItem(
          reviewItem,
          { scroll: false },
        );
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-ambiguity-toggle]")) {
      button.addEventListener("click", () => {
        const focus = this._nilmFocusState(button);
        void this._toggleNilmAmbiguityAudit().finally(() => this._restoreNilmFocus(focus));
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-ambiguity-group]")) {
      button.addEventListener("click", () => {
        const focus = this._nilmFocusState(button);
        void this._toggleNilmAmbiguityGroup(
          button.dataset.nilmAmbiguityGroup,
        ).finally(() => this._restoreNilmFocus(focus));
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-ambiguity-load-groups]")) {
      button.addEventListener("click", () => {
        const focus = this._nilmFocusState(button);
        void this._loadNilmAmbiguityAuditGroupSummaries(
          this._nilmAmbiguityAudit(),
          { append: button.dataset.nilmAmbiguityAppend === "true" },
        ).finally(() => this._restoreNilmFocus(focus));
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-ambiguity-load-occurrences]")) {
      button.addEventListener("click", () => {
        const focus = this._nilmFocusState(button);
        const audit = this._nilmAmbiguityAudit();
        const group = this._nilmAmbiguityAuditGroup(
          audit,
          button.dataset.nilmAmbiguityLoadOccurrences,
        );
        if (group) {
          void this._loadNilmAmbiguityAuditGroup(
            audit,
            group,
            { append: true },
          ).finally(() => this._restoreNilmFocus(focus));
        }
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-load-more-sessions]")) {
      button.addEventListener("click", () => {
        const focus = this._nilmFocusState(button);
        void this._loadMoreNilmSessions().finally(() => this._restoreNilmFocus(focus));
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-ambiguity-open-graph]")) {
      button.addEventListener("click", () => {
        const item = this._nilmAmbiguityAuditItem(button.dataset.nilmAmbiguitySessionId);
        const focus = this._nilmFocusState(button);
        if (item) {
          void this._focusNilmAmbiguityOccurrence(item).finally(() => this._restoreNilmFocus(focus));
        }
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-ambiguity-create-interval]")) {
      button.addEventListener("click", () => {
        const item = this._nilmAmbiguityAuditItem(button.dataset.nilmAmbiguitySessionId);
        if (item) void this._createNilmAmbiguityManualInterval(item);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-occurrence-step]")) {
      button.addEventListener("click", () => {
        void this._stepNilmOccurrence(Number(button.dataset.nilmOccurrenceStep || 0));
      });
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-label-input]")) {
      input.addEventListener("input", () => this._rememberNilmLabelDraft(input));
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-label-interval-input]")) {
      const updateDraft = () => this._rememberNilmLabelIntervalDraft(input);
      if (input.dataset.nilmIntervalIndex !== undefined) {
        input.addEventListener("input", updateDraft);
        input.addEventListener("change", () => {
          updateDraft();
          void this._syncNilmIntervalFieldToGraph(
            Number.parseInt(input.dataset.nilmIntervalIndex || "-1", 10),
          );
        });
      } else {
        input.addEventListener("input", updateDraft);
        input.addEventListener("change", updateDraft);
      }
      input.addEventListener("focus", () => {
        const index = Number.parseInt(input.dataset.nilmIntervalIndex || "-1", 10);
        if (index >= 0) this._selectNilmDraftInterval(index);
      });
    }
    for (const select of this.shadowRoot.querySelectorAll('[data-nilm-existing-assignment="label_interval"]')) {
      const updateDraft = () => this._rememberNilmLabelIntervalDraft(select);
      select.addEventListener("input", updateDraft);
      select.addEventListener("change", updateDraft);
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-open-interval-editor]")) {
      button.addEventListener("click", () => {
        this._openNilmIntervalEditor(() => {
          if (!this._nilmIntervalDraftItems().length) {
            this._nilmLabelIntervalDraft = this._emptyNilmLabelIntervalDraft();
          }
          this._nilmActiveIntervalIndex = 0;
        });
        this._render();
        requestAnimationFrame(() => {
          const chart = this.shadowRoot.querySelector("[data-nilm-chart-select]");
          if (chart) chart.scrollIntoView({ block: "nearest" });
        });
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-edit-focused-interval]")) {
      button.addEventListener("click", () => {
        if (this._editNilmFocusedInterval()) {
          requestAnimationFrame(() => {
            const chart = this.shadowRoot.querySelector("[data-nilm-chart-select]");
            if (chart) chart.scrollIntoView({ block: "nearest" });
          });
        }
      });
    }
    for (const row of this.shadowRoot.querySelectorAll("[data-nilm-interval-row]")) {
      row.addEventListener("click", () => {
        this._selectNilmDraftInterval(Number.parseInt(row.dataset.nilmIntervalRow, 10));
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-remove-interval]")) {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._removeNilmDraftInterval(Number.parseInt(button.dataset.nilmRemoveInterval, 10));
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-cancel-interval-editor]")) {
      button.addEventListener("click", () => this._cancelNilmIntervalEditor());
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-session-label-input]")) {
      input.addEventListener("input", () => this._rememberNilmSessionLabelDraft(input));
    }
    for (const select of this.shadowRoot.querySelectorAll("[data-nilm-session-assignment-key]")) {
      const remember = () => this._rememberNilmSessionAssignmentDraft(select);
      select.addEventListener("input", remember);
      select.addEventListener("change", remember);
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-nilm-assignment-input]")) {
      input.addEventListener("input", () => this._rememberNilmAssignmentDraft(input));
      input.addEventListener("change", () => this._rememberNilmAssignmentDraft(input));
    }
    for (const input of this.shadowRoot.querySelectorAll('[data-nilm-reference-input]:not(ha-entity-picker)')) {
      const remember = () => this._rememberNilmReferenceDraft(input);
      input.addEventListener("input", remember);
      input.addEventListener("change", () => {
        remember();
        if (input.dataset.nilmReferenceInput === "stateEntityId") this._render();
      });
    }
    for (const picker of this.shadowRoot.querySelectorAll("ha-entity-picker[data-nilm-reference-input]")) {
      picker.addEventListener("value-changed", (event) => {
        picker.value = event.detail.value || "";
        this._rememberNilmReferenceDraft(picker);
        if (picker.dataset.nilmReferenceInput === "stateEntityId") this._render();
      });
    }
    this._configureNilmReferencePickers();
    for (const details of this.shadowRoot.querySelectorAll("[data-nilm-reference-details]")) {
      details.addEventListener("toggle", () => {
        const draft = this._nilmReferenceDrafts.get(details.dataset.nilmReferenceKey);
        if (draft) draft.open = details.open;
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-reference-action]")) {
      button.addEventListener("click", () => this._callNilmReferenceAction(
        Number.parseInt(button.dataset.nilmReferenceIndex || "-1", 10),
        button.dataset.nilmReferenceAction,
      ));
    }
    for (const chart of this.shadowRoot.querySelectorAll("[data-nilm-chart-select]")) {
      chart.addEventListener("pointerdown", (event) => this._startNilmChartSelection(event, chart));
    }
    for (const handle of this.shadowRoot.querySelectorAll("[data-nilm-boundary-handle]")) {
      const chart = handle.closest("[data-nilm-chart-select]");
      handle.addEventListener("pointerdown", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (!chart) return;
        const update = (moveEvent) => {
          const currentChart = this.shadowRoot.querySelector("[data-nilm-chart-select]") || chart;
          const time = this._snapNilmChartTimeToEdge(this._chartEventTime(moveEvent, currentChart), currentChart);
          this._updateNilmDraftBoundary(
            Number.parseInt(handle.dataset.nilmDraftIndex || "-1", 10),
            handle.dataset.nilmBoundaryHandle,
            time,
          );
        };
        const cleanup = () => {
          window.removeEventListener("pointermove", update);
          window.removeEventListener("pointerup", finish);
          window.removeEventListener("pointercancel", cancel);
        };
        const finish = (finishEvent) => {
          update(finishEvent);
          cleanup();
        };
        const cancel = () => cleanup();
        if (handle.setPointerCapture && event.pointerId !== undefined) {
          handle.setPointerCapture(event.pointerId);
        }
        window.addEventListener("pointermove", update);
        window.addEventListener("pointerup", finish, { once: true });
        window.addEventListener("pointercancel", cancel, { once: true });
      });
      handle.addEventListener("keydown", (event) => {
        const direction = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
        if (!direction || !chart) return;
        event.preventDefault();
        const index = Number.parseInt(handle.dataset.nilmDraftIndex || "-1", 10);
        const field = handle.dataset.nilmBoundaryHandle;
        const interval = this._nilmIntervalDraftItems()[index] || {};
        const current = Date.parse(interval[field] || "");
        const samples = [...new Set([...chart.querySelectorAll("[data-chart-point][data-chart-time]")]
          .map((point) => Number(point.dataset.chartTime))
          .filter(Number.isFinite))].sort((left, right) => left - right);
        const next = direction > 0
          ? samples.find((time) => time > current)
          : [...samples].reverse().find((time) => time < current);
        if (Number.isFinite(next)) this._updateNilmDraftBoundary(index, field, next);
      });
    }
    for (const band of this.shadowRoot.querySelectorAll("[data-nilm-session-start]")) {
      band.addEventListener("click", () => {
        if (band.dataset.nilmDraftIndex !== undefined) {
          this._selectNilmDraftInterval(Number.parseInt(band.dataset.nilmDraftIndex, 10));
          return;
        }
        if (band.dataset.nilmLabelIntervalIndex !== undefined) {
          this._callNilmLabelIntervalAction(
            Number.parseInt(band.dataset.nilmLabelIntervalIndex, 10),
            "adjust",
          );
          return;
        }
        this._selectNilmSessionInterval(band);
      });
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
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-graph-zoom]")) {
      button.addEventListener("click", () => this._zoomNilmGraph(Number(button.dataset.nilmGraphZoom)));
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-graph-pan]")) {
      button.addEventListener("click", () => this._panNilmGraph(Number(button.dataset.nilmGraphPan)));
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-appliance-history-graph-zoom]")) {
      button.addEventListener("click", () => this._zoomApplianceHistoryGraph(Number(button.dataset.applianceHistoryGraphZoom)));
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-appliance-history-graph-pan]")) {
      button.addEventListener("click", () => this._panApplianceHistoryGraph(Number(button.dataset.applianceHistoryGraphPan)));
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-merge-target]")) {
      button.addEventListener("click", () => {
        this._selectNilmMergeTarget(button.dataset.nilmSourceKey, button.dataset.nilmMergeTarget);
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
    this._listen(
      "[data-nilm-interval-refresh-retry]",
      () => this._retryNilmIntervalWorkspaceRefresh(),
    );
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-interval-retry]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.getAttribute("data-nilm-interval-retry-index") || "-1", 10);
        this._callNilmLabelIntervalAction(index, button.getAttribute("data-nilm-interval-retry"));
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-session-action]")) {
      button.addEventListener("click", () => {
        const index = Number.parseInt(button.dataset.nilmSessionIndex || "-1", 10);
        this._callNilmWorkspaceItemAction("sessions", index, button.dataset.nilmSessionAction);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-assignment-action]")) {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        const index = Number.parseInt(button.dataset.nilmAssignmentIndex || "-1", 10);
        this._callNilmWorkspaceItemAction("assignments", index, button.dataset.nilmAssignmentAction);
      });
    }
    for (const button of this.shadowRoot.querySelectorAll("[data-nilm-appliance-detail-path]")) {
      button.addEventListener("click", () => {
        this._navigate(button.dataset.nilmApplianceDetailPath);
      });
    }
    for (const input of this.shadowRoot.querySelectorAll("[data-appliance-insights-filter]")) {
      input.addEventListener("change", () => {
        this._applianceInsightsFilters[input.dataset.applianceInsightsFilter] = input.checked;
        this._render();
      });
    }
    const applianceInsightsSort = this.shadowRoot.querySelector("[data-appliance-insights-sort]");
    if (applianceInsightsSort) {
      applianceInsightsSort.addEventListener("change", () => {
        this._applianceInsightsSort = applianceInsightsSort.value;
        this._render();
      });
    }
    for (const link of this.shadowRoot.querySelectorAll("[data-appliance-insights-detail-path]")) {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        this._navigate(link.dataset.applianceInsightsDetailPath);
      });
    }
    for (const link of this.shadowRoot.querySelectorAll("[data-appliance-insights-source-path]")) {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        this._navigate(link.dataset.applianceInsightsSourcePath);
      });
    }
    for (const link of this.shadowRoot.querySelectorAll("[data-setup-health-path]")) {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        this._openOptionsPath(link.getAttribute("href"));
      });
    }
    this._restoreNilmFocus(nilmFocus);
  }
}
