export function registerDashboardGraphs(CircuitSetupEnergyAnalyzerPanel) {
  class DashboardCardBase extends CircuitSetupEnergyAnalyzerPanel {
    constructor() {
      super();
      this._dashboardConfig = {};
      this._hass = null;
    }

    setConfig(config) {
      this._dashboardConfig = config || {};
      if (config && config.text) {
        this.panel = { config: { text: config.text } };
      }
      this._render();
    }

    set hass(value) {
      this._hass = value;
      this._render();
    }

    get hass() {
      return this._hass;
    }

    getCardSize() {
      return 6;
    }

    _label(key, fallback) {
      return String((this._dashboardConfig.labels || {})[key] || fallback || "");
    }

    _state(entityId) {
      return entityId && this._hass && this._hass.states
        ? this._hass.states[entityId]
        : null;
    }

    _number(entityId) {
      const state = this._state(entityId);
      if (!state || ["unknown", "unavailable", ""].includes(String(state.state).toLowerCase())) {
        return null;
      }
      const value = Number(state.state);
      return Number.isFinite(value) ? value : null;
    }

    _sum(entityIds) {
      const values = (entityIds || []).map((entityId) => this._number(entityId)).filter(Number.isFinite);
      return values.length ? values.reduce((total, value) => total + value, 0) : null;
    }

    _unit(entityId, fallback = "") {
      const state = this._state(entityId);
      return String((state && state.attributes && state.attributes.unit_of_measurement) || fallback || "");
    }

    _formatValue(value, unit = "") {
      if (!Number.isFinite(value)) {
        return this._label("unavailable", "Unavailable");
      }
      const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
      const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value);
      return unit ? `${number} ${unit}` : number;
    }

    _formatEntity(entityId, fallbackUnit = "") {
      return this._formatValue(this._number(entityId), this._unit(entityId, fallbackUnit));
    }

    _applianceState(appliance) {
      const health = String((this._state(appliance.health_entity) || {}).state || "");
      const running = String((this._state(appliance.running_entity) || {}).state || "").toLowerCase() === "on";
      return {
        ...appliance,
        power: this._sum(appliance.power_entities),
        energy: this._number(appliance.energy_today_entity),
        cost: this._number(appliance.cost_today_entity),
        health,
        running,
        issue: /(attention|issue|warning|problem|alert|abnormal|high|low)/i.test(health),
      };
    }

    _navigate(path) {
      if (!path) return;
      history.pushState(null, "", path);
      window.dispatchEvent(new Event("location-changed"));
    }

    _styles() {
      return `
        :host { display: block; }
        * { box-sizing: border-box; letter-spacing: 0; }
        ha-card { background: var(--card-background-color, #fff); overflow: hidden; }
        .dashboard-card { color: var(--primary-text-color, #111827); display: grid; font-family: Roboto, Noto, sans-serif; gap: 16px; padding: 16px; }
        h2, h3, p { margin: 0; }
        h2 { font-size: 18px; }
        h3 { font-size: 15px; }
        .muted { color: var(--secondary-text-color, #5b6470); }
        .kpis { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
        .metric { background: var(--secondary-background-color, #f4f6f8); border: 1px solid var(--divider-color, #d8dee6); border-radius: 6px; padding: 10px; }
        .metric span { color: var(--secondary-text-color, #5b6470); display: block; font-size: 12px; margin-bottom: 4px; }
        .metric strong { font-size: 16px; overflow-wrap: anywhere; }
        .banner { align-items: center; border: 1px solid var(--warning-color, #b7791f); border-radius: 6px; display: flex; justify-content: space-between; padding: 10px; }
        .banner.ready { border-color: var(--success-color, #2e7d32); }
        .flow { display: grid; gap: 8px; }
        .flow-bar { background: var(--secondary-background-color, #e5e7eb); border-radius: 4px; display: flex; height: 18px; overflow: hidden; }
        .flow-known { background: var(--primary-color, #0b6bcb); }
        .flow-unassigned { background: var(--warning-color, #b7791f); }
        .flow-labels { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 13px; }
        .appliance-list, .appliance-grid { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }
        button.appliance-tile { background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #d8dee6); border-radius: 6px; color: var(--primary-text-color, #111827); cursor: pointer; min-height: 96px; padding: 12px; text-align: left; }
        button.appliance-tile:focus-visible, button.control:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--primary-color, #0b6bcb); outline-offset: 2px; }
        .appliance-meta { color: var(--secondary-text-color, #5b6470); display: grid; font-size: 13px; gap: 3px; margin-top: 6px; }
        .issue { color: var(--warning-color, #a15c00); font-weight: 600; }
        .controls { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
        button.control, select, input { background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #aeb7c2); border-radius: 4px; color: var(--primary-text-color, #111827); min-height: 36px; padding: 6px 10px; }
        button.control { cursor: pointer; }
        button.control[aria-selected="true"], button.control[aria-pressed="true"] { background: var(--primary-color, #0b6bcb); color: var(--text-primary-color, #fff); }
        input { min-width: min(240px, 100%); }
        .bars { display: grid; gap: 8px; }
        .bar-row { display: grid; gap: 8px; grid-template-columns: minmax(90px, 1fr) minmax(100px, 3fr) auto; }
        .bar-track { background: var(--secondary-background-color, #e5e7eb); border-radius: 3px; overflow: hidden; }
        .bar-fill { background: var(--primary-color, #0b6bcb); height: 100%; min-height: 14px; }
        .timeline { display: grid; gap: 8px; }
        .timeline-lane { display: grid; gap: 4px; grid-template-columns: minmax(90px, 1fr) minmax(160px, 4fr); }
        .timeline-track { background: var(--secondary-background-color, #e5e7eb); border-radius: 3px; height: 24px; overflow: hidden; position: relative; }
        .running-band { background: var(--success-color, #2e7d32); height: 100%; position: absolute; }
        .chart-frame { font-family: Roboto, Noto, sans-serif; overflow: visible; position: relative; }
        .chart { display: block; height: auto; max-width: 100%; min-height: 200px; width: 100%; }
        .chart [data-chart-point] { cursor: crosshair; opacity: 0.55; }
        .chart [data-chart-point][data-selected="true"] { opacity: 1; stroke: var(--card-background-color, #fff); stroke-width: 2; }
        .chart-crosshair { display: none; stroke: var(--info-color, var(--primary-color, #03a9f4)); }
        .chart-crosshair[data-visible="true"] { display: block; }
        .chart-tooltip { background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #d8dee6); border-radius: 4px; color: var(--primary-text-color, #111827); font-size: 12px; padding: 8px; pointer-events: none; position: absolute; z-index: 2; }
        .chart-tooltip[aria-hidden="true"] { display: none; }
        .chart-tooltip-row { align-items: center; display: grid; gap: 6px; grid-template-columns: 10px minmax(0, 1fr) auto; margin-top: 4px; }
        .chart-tooltip-marker, .swatch { border-radius: 50%; display: inline-block; height: 10px; width: 10px; }
        .axis, .grid { stroke: var(--divider-color, #d8dee6); }
        .axis-label, .chart text { fill: var(--primary-text-color, #111827); font-size: 12px; }
        .legend { display: flex; flex-wrap: wrap; font-size: 12px; gap: 8px; justify-content: center; margin-top: 8px; }
        .legend-item { align-items: center; display: inline-flex; gap: 6px; }
        @media (max-width: 520px) {
          .dashboard-card { padding: 12px; }
          .bar-row { grid-template-columns: minmax(80px, 1fr) minmax(70px, 2fr); }
          .bar-row strong { grid-column: 1 / -1; }
          .timeline-lane { grid-template-columns: 1fr; }
        }
      `;
    }

    _contributionHtml(appliances) {
      const key = this._contributionMode === "cost" ? "cost" : "energy";
      const values = appliances.filter((item) => Number.isFinite(item[key]))
        .sort((left, right) => right[key] - left[key]);
      const top = values.slice(0, 5);
      if (values.length > 5) {
        top.push({
          name: this._label("other", "Other"),
          [key]: values.slice(5).reduce((total, item) => total + item[key], 0),
        });
      }
      const max = Math.max(...top.map((item) => item[key]), 1);
      const unit = key === "energy" ? "kWh" : this._unit((values[0] || {}).cost_today_entity);
      return `<section>
        <div class="controls">
          <h3>${this._escape(this._label("today_by_appliance", "Today by appliance"))}</h3>
          ${["energy", "cost"].map((mode) => `<button type="button" class="control" data-contribution-mode="${mode}" aria-pressed="${mode === this._contributionMode}">${this._escape(this._label(mode, mode))}</button>`).join("")}
        </div>
        <div class="bars">${top.map((item) => `<div class="bar-row"><span>${this._escape(item.name)}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${Math.max(item[key] / max * 100, 2)}%"></span></span><strong>${this._escape(this._formatValue(item[key], unit))}</strong></div>`).join("")}</div>
      </section>`;
    }
  }

  class CircuitSetupEnergyAnalyzerHouseFlow extends DashboardCardBase {
    constructor() {
      super();
      this._contributionMode = "energy";
    }

    _render() {
      if (!this.shadowRoot || !this._dashboardConfig || !this._hass) return;
      const config = this._dashboardConfig;
      const mains = config.primary_mains || {};
      const appliances = (config.appliances || []).map((item) => this._applianceState(item));
      const active = appliances.filter((item) => item.issue || item.running || (item.power || 0) > 0)
        .sort((left, right) => Number(right.issue) - Number(left.issue)
          || Number(right.running) - Number(left.running)
          || (right.power || 0) - (left.power || 0)
          || String(left.name).localeCompare(String(right.name)));
      const knownPower = this._number(mains.monitored_power_entity)
        ?? appliances.reduce((total, item) => total + (item.power || 0), 0);
      const housePower = this._sum(mains.power_entities) ?? knownPower;
      const unassignedPower = this._number(mains.balance_power_entity);
      const coverage = this._number(mains.monitored_coverage_entity);
      const runningCount = appliances.filter((item) => item.running).length;
      const issueCount = appliances.filter((item) => item.issue).length;
      const energyToday = config.primary_mains && mains.daily_energy_usage_entity
        ? this._number(mains.daily_energy_usage_entity)
        : null;
      const costToday = config.primary_mains && mains.cost_today_entity
        ? this._number(mains.cost_today_entity)
        : null;
      const costUnit = this._unit(
        mains.cost_today_entity || (appliances.find((item) => item.cost_today_entity) || {}).cost_today_entity,
      );
      const healthState = this._state(config.setup_health_entity);
      const setupReady = healthState && String(healthState.state).toLowerCase() === "ready";
      const setup = healthState ? `
        <button type="button" class="banner ${setupReady ? "ready" : ""}" data-setup-health>
          <strong>${this._escape(this._label(setupReady ? "setup_ready" : "setup_attention", setupReady ? "Setup ready" : "Setup needs attention"))}</strong>
          <span>${this._escape(String(healthState.state))}</span>
        </button>
      ` : "";
      const knownPercent = Number.isFinite(coverage)
        ? Math.max(0, Math.min(100, coverage))
        : housePower > 0 ? Math.max(0, Math.min(100, knownPower / housePower * 100)) : 0;
      const housePowerLabel = config.primary_mains
        ? this._label("house_power", "House power")
        : this._label("known_monitored_load", "Known monitored load");
      const flow = `
        <section class="flow">
          <h3>${this._escape(housePowerLabel)}: ${this._escape(this._formatValue(housePower, "W"))}</h3>
          <div class="flow-bar" role="img" aria-label="${this._escape(this._label("known_load_coverage", "Known load coverage"))} ${knownPercent.toFixed(0)}%">
            <span class="flow-known" style="width:${knownPercent}%"></span>
            <span class="flow-unassigned" style="width:${100 - knownPercent}%"></span>
          </div>
          <div class="flow-labels">
            <span>${this._escape(this._label("known_monitored_load", "Known monitored load"))}: ${this._escape(this._formatValue(knownPower, "W"))}</span>
            <span>${this._escape(this._label("unassigned_load", "Unassigned load"))}: ${this._escape(this._formatValue(unassignedPower, "W"))}</span>
            <span>${this._escape(this._label("known_load_coverage", "Known load coverage"))}: ${this._escape(this._formatValue(coverage, "%"))}</span>
            ${mains.solar_surplus_power_entity ? `<span>${this._escape(this._label("solar_surplus", "Solar surplus"))}: ${this._escape(this._formatEntity(mains.solar_surplus_power_entity, "W"))}</span>` : ""}
          </div>
        </section>
      `;
      const homeContent = config.mode === "mains" ? "" : `
        <div class="kpis">
          ${this._metricHtml(housePowerLabel, housePower, "W")}
          ${this._metricHtml(this._label("energy_today", "Energy today"), energyToday, "kWh")}
          ${this._metricHtml(this._label("cost_today", "Cost today"), costToday, costUnit)}
          ${this._metricHtml(this._label("running", "Running"), runningCount, "")}
          ${this._metricHtml(this._label("issues", "Issues"), issueCount, "")}
        </div>
        <section>
          <h3>${this._escape(this._label("active_now", "Active now"))}</h3>
          <div class="appliance-list">
            ${active.length ? active.slice(0, 5).map((item) => this._applianceTile(item)).join("") : `<p class="muted">${this._escape(this._label("no_active_appliances", "No monitored appliances are active."))}</p>`}
          </div>
        </section>
        ${this._contributionHtml(appliances)}
      `;
      const nilm = config.mode === "mains" ? `
        <div class="kpis">
          ${this._metricHtml(this._label("unknown_loads", "NILM loads"), this._number(mains.nilm_unknown_loads_entity), "")}
          ${this._metricHtml(this._label("running", "Signatures"), this._number(mains.nilm_signature_count_entity), "")}
          ${mains.solar_surplus_power_entity ? this._metricHtml(this._label("solar_surplus", "Solar surplus"), this._number(mains.solar_surplus_power_entity), this._unit(mains.solar_surplus_power_entity, "W")) : ""}
          ${mains.solar_flow_status_entity ? this._statusMetric(this._label("solar_flow", "Solar flow"), mains.solar_flow_status_entity) : ""}
          ${mains.utility_comparison_status_entity ? this._statusMetric(this._label("utility_comparison", "Utility comparison"), mains.utility_comparison_status_entity) : ""}
        </div>
        ${(config.secondary_mains || []).length ? `<section>
          <h3>${this._escape(this._label("additional_mains", "Additional mains channels"))}</h3>
          <div class="kpis">
            ${(config.secondary_mains || []).map((item) => this._metricHtml(item.name, this._sum(item.power_entities), this._unit((item.power_entities || [])[0], "W"))).join("")}
          </div>
        </section>` : ""}
      ` : "";
      this.shadowRoot.innerHTML = `
        <ha-card>
          <style>${this._styles()}</style>
          <div class="dashboard-card">
            <h2>${this._escape(config.title || "Energy")}</h2>
            ${setup}
            ${config.mode === "mains" ? nilm : `<div class="kpis"></div>`}
            ${flow}
            ${homeContent}
          </div>
        </ha-card>
      `;
      const setupButton = this.shadowRoot.querySelector("[data-setup-health]");
      if (setupButton) setupButton.addEventListener("click", () => this._navigate(config.setup_health_path));
      for (const tile of this.shadowRoot.querySelectorAll("[data-appliance-id]")) {
        tile.addEventListener("click", () => {
          const item = appliances.find((candidate) => candidate.circuit_id === tile.dataset.applianceId);
          this._navigate(item && item.detail_path);
        });
      }
      for (const button of this.shadowRoot.querySelectorAll("[data-contribution-mode]")) {
        button.addEventListener("click", () => {
          this._contributionMode = button.dataset.contributionMode;
          this._render();
        });
      }
    }

    _metricHtml(label, value, unit) {
      return `<div class="metric"><span>${this._escape(label)}</span><strong>${this._escape(this._formatValue(value, unit))}</strong></div>`;
    }

    _statusMetric(label, entityId) {
      const state = this._state(entityId);
      const value = state && !["unknown", "unavailable", ""].includes(String(state.state).toLowerCase())
        ? String(state.state)
        : this._label("unavailable", "Unavailable");
      return `<div class="metric"><span>${this._escape(label)}</span><strong>${this._escape(value)}</strong></div>`;
    }

    _applianceTile(item) {
      return `<button type="button" class="appliance-tile" data-appliance-id="${this._escape(item.circuit_id)}">
        <strong>${this._escape(item.name)}</strong>
        <div class="appliance-meta">
          <span class="${item.issue ? "issue" : ""}">${this._escape(item.issue ? this._label("needs_attention", "Needs attention") : item.running ? this._label("running", "Running") : this._label("idle", "Idle"))}</span>
          <span>${this._escape(this._formatValue(item.power, this._unit((item.power_entities || [])[0], "W")))}</span>
        </div>
      </button>`;
    }

  }

  class CircuitSetupEnergyAnalyzerApplianceGrid extends DashboardCardBase {
    constructor() {
      super();
      this._filter = "all";
      this._search = "";
      this._timelineSelection = "running";
      this._timelineKey = "";
      this._timelineRows = [];
    }

    _render() {
      if (!this.shadowRoot || !this._dashboardConfig || !this._hass) return;
      const appliances = (this._dashboardConfig.appliances || []).map((item) => this._applianceState(item));
      const search = this._search.toLowerCase();
      const visible = appliances.filter((item) => (
        (!search || `${item.name} ${item.area || ""}`.toLowerCase().includes(search))
        && (this._filter === "all"
          || this._filter === "running" && item.running
          || this._filter === "attention" && item.issue
          || this._filter === "energy"
          || this._filter === "cost")
      )).sort((left, right) => (
        this._filter === "energy" ? (right.energy || 0) - (left.energy || 0)
          : this._filter === "cost" ? (right.cost || 0) - (left.cost || 0)
            : Number(right.issue) - Number(left.issue)
              || Number(right.running) - Number(left.running)
              || (right.power || 0) - (left.power || 0)
              || String(left.name).localeCompare(String(right.name))
      ));
      const filters = [
        ["all", this._label("all", "All")],
        ["running", this._label("running", "Running")],
        ["attention", this._label("needs_attention", "Needs attention")],
        ["energy", this._label("highest_energy", "Highest energy")],
        ["cost", this._label("highest_cost", "Highest cost")],
      ];
      const areas = [...new Set(appliances.map((item) => item.area).filter(Boolean))].sort();
      this.shadowRoot.innerHTML = `
        <ha-card>
          <style>${this._styles()}</style>
          <div class="dashboard-card">
            <h2>${this._escape(this._dashboardConfig.title || "Appliances")}</h2>
            <div class="controls" role="tablist" aria-label="${this._escape(this._dashboardConfig.title || "Appliances")}">
              ${filters.map(([key, label]) => `<button type="button" class="control" role="tab" data-filter="${key}" aria-selected="${key === this._filter}">${this._escape(label)}</button>`).join("")}
              <input type="search" data-appliance-search value="${this._escape(this._search)}" aria-label="${this._escape(this._label("search", "Search appliances"))}" placeholder="${this._escape(this._label("search", "Search appliances"))}">
            </div>
            <div class="appliance-grid">
              ${visible.map((item) => this._tile(item)).join("")}
            </div>
            <section class="timeline">
              <div class="controls">
                <h3>${this._escape(this._label("run_timeline", "Run timeline"))}</h3>
                <label>${this._escape(this._label("timeline_selection", "Timeline selection"))}
                  <select data-timeline-selection>
                    <option value="running">${this._escape(this._label("currently_running", "Currently running"))}</option>
                    ${areas.map((area) => `<option value="area:${this._escape(area)}">${this._escape(area)}</option>`).join("")}
                    ${appliances.map((item) => `<option value="${this._escape(item.circuit_id)}">${this._escape(item.name)}</option>`).join("")}
                  </select>
                </label>
              </div>
              ${this._timelineHtml(appliances)}
            </section>
          </div>
        </ha-card>
      `;
      const select = this.shadowRoot.querySelector("[data-timeline-selection]");
      select.value = this._timelineSelection;
      select.addEventListener("change", () => {
        this._timelineSelection = select.value;
        this._timelineKey = "";
        this._ensureTimeline(appliances);
      });
      for (const button of this.shadowRoot.querySelectorAll("[data-filter]")) {
        button.addEventListener("click", () => {
          this._filter = button.dataset.filter;
          this._render();
        });
      }
      this.shadowRoot.querySelector("[data-appliance-search]").addEventListener("input", (event) => {
        this._search = event.target.value;
        this._render();
      });
      for (const tile of this.shadowRoot.querySelectorAll("[data-appliance-id]")) {
        tile.addEventListener("click", () => {
          const item = appliances.find((candidate) => candidate.circuit_id === tile.dataset.applianceId);
          this._navigate(item && item.detail_path);
        });
      }
      this._ensureTimeline(appliances);
    }

    _tile(item) {
      const powerUnit = this._unit((item.power_entities || [])[0], "W");
      const costUnit = this._unit(item.cost_today_entity);
      return `<button type="button" class="appliance-tile" data-appliance-id="${this._escape(item.circuit_id)}">
        <strong>${this._escape(item.name)}</strong>
        <div class="appliance-meta">
          ${item.area ? `<span>${this._escape(item.area)}</span>` : ""}
          <span class="${item.issue ? "issue" : ""}">${this._escape(item.issue ? this._label("needs_attention", "Needs attention") : item.running ? this._label("running", "Running") : this._label("idle", "Idle"))} · ${this._escape(this._formatValue(item.power, powerUnit))}</span>
          <span>${this._escape(this._label("energy_today", "Today"))}: ${this._escape(this._formatValue(item.energy, "kWh"))} · ${this._escape(this._formatValue(item.cost, costUnit))}</span>
          <span>${this._escape(this._label("health", "Health"))}: ${this._escape(item.health || this._label("unavailable", "Unavailable"))}</span>
        </div>
      </button>`;
    }

    _selectedTimelineAppliances(appliances) {
      if (this._timelineSelection === "running") return appliances.filter((item) => item.running).slice(0, 5);
      if (this._timelineSelection.startsWith("area:")) {
        const area = this._timelineSelection.slice(5);
        return appliances.filter((item) => item.area === area).slice(0, 5);
      }
      return appliances.filter((item) => item.circuit_id === this._timelineSelection).slice(0, 1);
    }

    async _ensureTimeline(appliances) {
      const selected = this._selectedTimelineAppliances(appliances).filter((item) => item.running_entity);
      const ids = selected.map((item) => item.running_entity);
      const key = ids.join(",");
      if (!key || key === this._timelineKey) return;
      this._timelineKey = key;
      const start = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
      const path = `history/period/${start}?filter_entity_id=${encodeURIComponent(key)}&minimal_response&no_attributes`;
      try {
        const rows = await this._hass.callApi("GET", path);
        this._timelineRows = Array.isArray(rows) ? rows.flat().filter(Boolean) : [];
      } catch (_error) {
        this._timelineRows = [];
      }
      this._render();
    }

    _timelineHtml(appliances) {
      const selected = this._selectedTimelineAppliances(appliances).filter((item) => item.running_entity);
      const lanes = selected.map((item) => {
        const points = this._timelineRows.filter((row) => row.entity_id === item.running_entity)
          .map((row) => ({ time: Date.parse(row.last_changed), state: row.state }))
          .filter((row) => Number.isFinite(row.time))
          .sort((left, right) => left.time - right.time);
        if (!points.length) return "";
        const start = points[0].time;
        const end = Math.max(
          Date.now(),
          points[points.length - 1].time,
          start + 60 * 60 * 1000,
        );
        const bands = points.map((point, index) => ({
          ...point,
          end: points[index + 1] ? points[index + 1].time : end,
        })).filter((point) => point.state === "on" && point.end > point.time);
        return `<div class="timeline-lane"><span>${this._escape(item.name)}</span><span class="timeline-track">${bands.map((band) => `<span class="running-band" data-running-band style="left:${(band.time - start) / (end - start) * 100}%;width:${(band.end - band.time) / (end - start) * 100}%"></span>`).join("")}</span></div>`;
      }).filter(Boolean);
      return lanes.length ? lanes.join("") : `<p class="muted">${this._escape(this._label("no_history", "No running history is available for this period."))}</p>`;
    }
  }

  class CircuitSetupEnergyAnalyzerEnergyCost extends DashboardCardBase {
    constructor() {
      super();
      this._historyDays = 7;
      this._selection = "whole";
      this._insights = null;
      this._wholeHouse = [];
      this._loadRequested = false;
      this._contributionMode = "energy";
    }

    _render() {
      if (!this.shadowRoot || !this._dashboardConfig || !this._hass) return;
      if (!this._loadRequested) {
        this._loadRequested = true;
        this._loadInsights();
      }
      const items = (this._insights || []).filter((item) => (
        !this._dashboardConfig.entry_id || item.entry_id === this._dashboardConfig.entry_id
      ));
      if (!this._dashboardConfig.primary_mains && this._selection === "whole" && items.length) {
        this._selection = items[0].circuit_id || items[0].appliance_key;
      }
      const rows = this._historyRows(items).slice(-this._historyDays);
      const metrics = this._metricValues();
      const energyPoints = rows.map((row) => ({
        time: this._dailyTimestamp(row.date),
        value: Number(row.energy_kwh),
      })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));
      const costPoints = rows.map((row) => ({
        time: this._dailyTimestamp(row.date),
        value: row.cost === null || row.cost === undefined ? Number.NaN : Number(row.cost),
        cost_source: row.cost_source,
      })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));
      const currency = this._costUnit();
      const series = [
        energyPoints.length && { name: this._label("energy", "Energy"), unit: "kWh", kind: "bar", points: energyPoints },
        costPoints.length && { name: this._label("cost", "Cost"), unit: currency, axis: energyPoints.length ? "right" : "left", points: costPoints },
      ].filter(Boolean);
      const chart = series.length ? this._chartSvg(series, {
        y_axis_label: energyPoints.length ? "kWh" : currency,
        ...(energyPoints.length && costPoints.length ? { right_y_axis_label: currency } : {}),
      }) : `<p class="muted">${this._escape(this._label("no_history", "No completed-day history is available."))}</p>`;
      const unavailable = rows.some((row) => row.cost === null || row.cost === undefined);
      const appliances = (this._dashboardConfig.appliances || []).map((item) => this._applianceState(item));
      const selectedOptions = [
        ...(this._dashboardConfig.primary_mains
          ? [`<option value="whole">${this._escape(this._label("whole_house", "Whole house"))}</option>`]
          : []),
        ...items.map((item) => `<option value="${this._escape(item.circuit_id || item.appliance_key)}">${this._escape(item.display_name)}</option>`),
      ].join("");
      this.shadowRoot.innerHTML = `
        <ha-card>
          <style>${this._styles()}</style>
          <div class="dashboard-card">
            <h2>${this._escape(this._dashboardConfig.title || "Energy and costs")}</h2>
            <section>
              <h3>${this._escape(this._label("today_vs_normal", "Today versus normal"))}</h3>
              <div class="kpis">
                ${this._metricHtml(this._label("energy_today", "Energy today"), metrics.energyToday, "kWh", metrics.averageEnergy)}
                ${this._metricHtml(this._label("cost_today", "Cost today"), metrics.costToday, currency, metrics.averageCost)}
              </div>
            </section>
            <section>
              <div class="controls">
                <h3>${this._escape(this._label("completed_history", "Completed-day history"))}</h3>
                <select data-energy-selection aria-label="${this._escape(this._label("completed_history", "Completed-day history"))}">${selectedOptions}</select>
                ${[7, 30].map((days) => `<button type="button" class="control" data-history-days="${days}" aria-pressed="${days === this._historyDays}">${this._escape(this._label(days === 7 ? "seven_days" : "thirty_days", `${days} days`))}</button>`).join("")}
              </div>
              ${chart}
              ${unavailable ? `<p class="muted">${this._escape(this._label("unavailable", "Unavailable"))}</p>` : ""}
            </section>
            ${this._contributionHtml(appliances)}
          </div>
        </ha-card>
      `;
      const select = this.shadowRoot.querySelector("[data-energy-selection]");
      select.value = this._selection;
      select.addEventListener("change", () => {
        this._selection = select.value;
        this._render();
      });
      for (const button of this.shadowRoot.querySelectorAll("[data-history-days]")) {
        button.addEventListener("click", () => {
          this._historyDays = Number(button.dataset.historyDays);
          this._render();
        });
      }
      for (const button of this.shadowRoot.querySelectorAll("[data-contribution-mode]")) {
        button.addEventListener("click", () => {
          this._contributionMode = button.dataset.contributionMode;
          this._render();
        });
      }
      this._attachChartInspectors();
    }

    async _loadInsights() {
      try {
        const payload = await this._hass.callApi("GET", this._dashboardConfig.api_path);
        this._insights = Array.isArray(payload && payload.items) ? payload.items : [];
        this._wholeHouse = Array.isArray(payload && payload.whole_house) ? payload.whole_house : [];
      } catch (_error) {
        this._insights = [];
        this._wholeHouse = [];
      }
      this._render();
    }

    _historyRows(items) {
      if (this._selection !== "whole") {
        const selected = items.find((item) => (item.circuit_id || item.appliance_key) === this._selection);
        return Array.isArray(selected && selected.daily_totals) ? selected.daily_totals : [];
      }
      const mains = this._wholeHouse.find((item) => (
        !this._dashboardConfig.entry_id || item.entry_id === this._dashboardConfig.entry_id
      ));
      if (this._dashboardConfig.primary_mains) {
        return mains && Array.isArray(mains.daily_totals) ? mains.daily_totals : [];
      }
      const byDate = new Map();
      for (const item of items) {
        for (const row of item.daily_totals || []) {
          const current = byDate.get(row.date) || { date: row.date, energy_kwh: 0, cost: 0, cost_source: "recorded", cost_available: false };
          current.energy_kwh += Number(row.energy_kwh) || 0;
          if (row.cost !== null && row.cost !== undefined && Number.isFinite(Number(row.cost))) {
            current.cost += Number(row.cost);
            current.cost_available = true;
          }
          if (row.cost_source === "estimated") current.cost_source = "estimated";
          if (row.cost_source === "unavailable" && !current.cost_available) current.cost_source = "unavailable";
          byDate.set(row.date, current);
        }
      }
      return [...byDate.values()].sort((left, right) => String(left.date).localeCompare(String(right.date)))
        .map((row) => ({ ...row, cost: row.cost_available ? row.cost : null }));
    }

    _metricValues() {
      const appliances = this._dashboardConfig.appliances || [];
      const selected = this._selection === "whole"
        ? this._dashboardConfig.primary_mains
        : appliances.find((item) => item.circuit_id === this._selection);
      return {
        energyToday: selected ? this._number(selected.energy_today_entity || selected.daily_energy_usage_entity) : null,
        costToday: selected ? this._number(selected.cost_today_entity) : null,
        averageEnergy: selected ? this._number(selected.average_kwh_entity || selected.average_kwh_per_day_entity) : null,
        averageCost: selected ? this._number(selected.average_cost_entity || selected.average_cost_per_day_entity) : null,
      };
    }

    _metricHtml(label, value, unit, average) {
      const change = Number.isFinite(value) && Number.isFinite(average) && average > 0
        ? `${value >= average ? "+" : ""}${((value / average - 1) * 100).toFixed(0)}%`
        : "";
      return `<div class="metric"><span>${this._escape(label)}</span><strong>${this._escape(this._formatValue(value, unit))}</strong>${Number.isFinite(average) ? `<small>${this._escape(this._label("average", "Average"))}: ${this._escape(this._formatValue(average, unit))}${change ? ` · ${this._escape(change)}` : ""}</small>` : ""}</div>`;
    }

    _dailyTimestamp(value) {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
      return match ? Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12) : Number.NaN;
    }

    _costUnit() {
      const appliances = this._dashboardConfig.appliances || [];
      const entityId = (this._dashboardConfig.primary_mains || {}).cost_today_entity
        || (appliances.find((item) => item.cost_today_entity) || {}).cost_today_entity;
      return this._unit(entityId, (this._hass.config || {}).currency || "");
    }
  }

  class CircuitSetupEnergyAnalyzerDashboardGraphs extends CircuitSetupEnergyAnalyzerPanel {
  constructor() {
    super();
    this._dashboardConfig = {};
  }

  setConfig(config) {
    this._dashboardConfig = config || {};
    if (config && config.text) {
      this.panel = { config: { text: config.text } };
    }
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
  if (!customElements.get("circuitsetup-energy-analyzer-house-flow")) {
    customElements.define("circuitsetup-energy-analyzer-house-flow", CircuitSetupEnergyAnalyzerHouseFlow);
  }
  if (!customElements.get("circuitsetup-energy-analyzer-appliance-grid")) {
    customElements.define("circuitsetup-energy-analyzer-appliance-grid", CircuitSetupEnergyAnalyzerApplianceGrid);
  }
  if (!customElements.get("circuitsetup-energy-analyzer-energy-cost")) {
    customElements.define("circuitsetup-energy-analyzer-energy-cost", CircuitSetupEnergyAnalyzerEnergyCost);
  }
  return CircuitSetupEnergyAnalyzerDashboardGraphs;
}
