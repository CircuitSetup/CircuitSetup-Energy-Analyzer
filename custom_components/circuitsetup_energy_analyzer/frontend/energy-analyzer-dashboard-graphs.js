export function registerDashboardGraphs(CircuitSetupEnergyAnalyzerPanel) {
  const RANGE_EVENT = "circuitsetup-dashboard-range-changed";
  const DATA_EVENT = "circuitsetup-dashboard-data-changed";
  const RANGE_KEY = "circuitsetup-energy-analyzer-dashboard-range";
  const dashboardSeries = new Map();

  const defaultRange = () => {
    const end = new Date();
    end.setHours(23, 59, 59, 999);
    const start = new Date(end);
    start.setHours(0, 0, 0, 0);
    return {
      start: start.toISOString(),
      end: end.toISOString(),
      compare: false,
    };
  };

  const validRange = (value) => {
    const timestamp = (candidate) => candidate instanceof Date
      ? candidate.getTime()
      : Date.parse(candidate);
    const start = timestamp(value && value.start);
    const end = timestamp(value && value.end);
    return Number.isFinite(start) && Number.isFinite(end) && end >= start
      ? { start: new Date(start).toISOString(), end: new Date(end).toISOString(), compare: Boolean(value.compare) }
      : defaultRange();
  };

  const storedRange = () => {
    try {
      return validRange(JSON.parse(localStorage.getItem(RANGE_KEY) || "null"));
    } catch (_error) {
      return defaultRange();
    }
  };

  const setDashboardRange = (value) => {
    const range = validRange(value);
    localStorage.setItem(RANGE_KEY, JSON.stringify(range));
    window.dispatchEvent(new CustomEvent(RANGE_EVENT, { detail: range }));
  };

  class DashboardCardBase extends CircuitSetupEnergyAnalyzerPanel {
    constructor() {
      super();
      this._dashboardConfig = {};
      this._hass = null;
      this._deferredHassRender = false;
      this._deferredRenderControl = null;
      this._dashboardRange = storedRange();
      this._handleDashboardRange = (event) => {
        this._dashboardRange = validRange(event.detail);
        this._historyKey = "";
        this._history = null;
        this._comparisonHistory = null;
        this._timelineKey = "";
        this._contributionLoadKey = "";
        this._rangeSummary = {};
        this._rollingContributionByCircuit = {};
        this._chartZoomWindows && this._chartZoomWindows.clear();
        this._render();
      };
    }

    connectedCallback() {
      super.connectedCallback();
      this._dashboardRange = storedRange();
      window.addEventListener(RANGE_EVENT, this._handleDashboardRange);
    }

    disconnectedCallback() {
      super.disconnectedCallback();
      window.removeEventListener(RANGE_EVENT, this._handleDashboardRange);
      if (dashboardSeries.delete(this)) {
        window.dispatchEvent(new Event(DATA_EVENT));
      }
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
      if (typeof this._refreshLiveData === "function") this._refreshLiveData();
      if (!localStorage.getItem(RANGE_KEY)) {
        const todayKey = this._chartDateKey(Date.now());
        this._dashboardRange = this._rangeFromDateKeys(todayKey, todayKey);
        setDashboardRange(this._dashboardRange);
      }
      const active = this.shadowRoot && this.shadowRoot.activeElement;
      if (active && active.matches("input, select, textarea")) {
        this._deferredHassRender = true;
        this._resumeAfterControlBlur(active);
        return;
      }
      this._deferredHassRender = false;
      this._render();
    }

    get hass() {
      return this._hass;
    }

    getCardSize() {
      return 6;
    }

    _resumeAfterControlBlur(control) {
      if (this._deferredRenderControl === control) return;
      this._deferredRenderControl = control;
      control.addEventListener("blur", () => {
        if (this._deferredRenderControl === control) {
          this._deferredRenderControl = null;
        }
        queueMicrotask(() => {
          if (!this._deferredHassRender) return;
          const active = this.shadowRoot && this.shadowRoot.activeElement;
          if (active && active.matches("input, select, textarea")) {
            this._resumeAfterControlBlur(active);
            return;
          }
          this._deferredHassRender = false;
          this._render();
        });
      }, { once: true });
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
      if (unit === "currency") {
        return this._formatCost(value);
      }
      const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
      const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value);
      return unit ? `${number} ${unit}` : number;
    }

    _formatEntity(entityId, fallbackUnit = "") {
      return this._formatValue(this._number(entityId), this._unit(entityId, fallbackUnit));
    }

    _applianceState(appliance) {
      const healthState = this._state(appliance.health_entity) || {};
      const electrical = String((healthState.attributes || {}).electrical_summary || "");
      const electricalIssue = Boolean(
        electrical && !["Normal", "Needs Metrics"].includes(electrical),
      );
      const health = electricalIssue
        ? electrical
        : String(healthState.state || "");
      const running = String((this._state(appliance.activity_entity) || {}).state || "").toLowerCase() === "running";
      return {
        ...appliance,
        power: this._sum(appliance.power_entities),
        energy: this._number(appliance.energy_today_entity),
        cost: this._number(appliance.cost_today_entity),
        health,
        running,
        issue: electricalIssue || /(attention|issue|warning|problem|alert|abnormal|high|low)/i.test(health),
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
        .dashboard-card { color: var(--primary-text-color, #111827); display: grid; font-family: Roboto, Noto, sans-serif; font-size: 14px; gap: 16px; line-height: 20px; padding: 16px; }
        h2, h3, p { margin: 0; }
        h2 { font-size: 24px; font-weight: 400; line-height: 32px; }
        h3 { font-size: 20px; font-weight: 400; line-height: 28px; }
        .muted { color: var(--secondary-text-color, #5b6470); }
        .kpis { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
        .metric { background: var(--secondary-background-color, #f4f6f8); border: 1px solid var(--divider-color, #d8dee6); border-radius: 6px; padding: 10px; }
        .metric span { color: var(--secondary-text-color, #5b6470); display: block; font-size: 12px; margin-bottom: 4px; }
        .metric strong { font-size: 16px; overflow-wrap: anywhere; }
        .metric small { display: block; margin-top: 4px; }
        .banner { align-items: center; border: 1px solid var(--warning-color, #b7791f); border-radius: 6px; display: flex; justify-content: space-between; padding: 10px; }
        .banner.ready { border-color: var(--success-color, #2e7d32); }
        .flow { display: grid; gap: 8px; }
        .flow-bar { background: var(--secondary-background-color, #e5e7eb); border-radius: 4px; display: flex; height: 18px; overflow: hidden; }
        .flow-known { background: var(--primary-color, #0b6bcb); }
        .flow-unassigned { background: var(--warning-color, #b7791f); }
        .flow-labels { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 13px; }
        .flow-labels > span, .appliance-heading { align-items: center; display: inline-flex; gap: 6px; }
        .flow-labels .swatch { flex: 0 0 auto; }
        .appliance-list, .appliance-grid { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); }
        button.appliance-tile { background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #d8dee6); border-radius: 6px; color: var(--primary-text-color, #111827); cursor: pointer; min-height: 96px; padding: 12px; text-align: left; }
        .appliance-heading ha-icon { --mdc-icon-size: 24px; }
        button.appliance-tile:focus-visible, button.control:focus-visible, select:focus-visible, input:focus-visible { outline: 2px solid var(--primary-color, #0b6bcb); outline-offset: 2px; }
        .appliance-meta { color: var(--secondary-text-color, #5b6470); display: grid; font-size: 13px; gap: 3px; margin-top: 6px; }
        .issue { color: var(--warning-color, #a15c00); font-weight: 600; }
        .contribution { display: grid; gap: 8px; margin-top: 12px; }
        .controls { align-items: center; display: flex; flex-wrap: wrap; gap: 8px; }
        button.control, select, input { background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #aeb7c2); border-radius: 4px; color: var(--primary-text-color, #111827); font: inherit; min-height: 36px; padding: 6px 10px; }
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
        .timeline-scale { display: grid; gap: 4px; grid-template-columns: minmax(90px, 1fr) minmax(160px, 4fr); }
        .timeline-axis { color: var(--secondary-text-color, #5b6470); display: grid; font-size: 11px; grid-template-columns: repeat(5, 1fr); }
        .timeline-axis span { text-align: center; }
        .timeline-axis span:first-child { text-align: left; }
        .timeline-axis span:last-child { text-align: right; }
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
        .legend-marker { --mdc-icon-size: 16px; }
        .summary-list { display: grid; gap: 8px; }
        .summary-list.compact-links { gap: 0; }
        .compact-links .summary-link { min-height: 0; padding: 0; }
        .summary-row, .summary-link { align-items: center; background: transparent; border: 0; color: var(--primary-text-color, #111827); display: flex; justify-content: space-between; min-height: 40px; padding: 4px 0; text-align: left; text-decoration: none; width: 100%; }
        button.summary-row { cursor: pointer; }
        .summary-row span:last-child { color: var(--secondary-text-color, #5b6470); margin-left: 12px; }
        .sr-only { clip: rect(0, 0, 0, 0); clip-path: inset(50%); height: 1px; overflow: hidden; position: absolute; white-space: nowrap; width: 1px; }
        @media (max-width: 520px) {
          .dashboard-card { padding: 12px; }
          .bar-row { grid-template-columns: minmax(80px, 1fr) minmax(70px, 2fr); }
          .bar-row strong { grid-column: 1 / -1; }
          .timeline-lane { grid-template-columns: 1fr; }
          .timeline-scale { grid-template-columns: 1fr; }
          .timeline-scale > span:first-child { display: none; }
        }
      `;
    }

    _publishDashboardSeries(series) {
      dashboardSeries.set(this, Array.isArray(series) ? series : []);
      window.dispatchEvent(new Event(DATA_EVENT));
    }

    _rangeLabel(range = this._dashboardRange) {
      const start = new Date(range.start);
      const end = new Date(range.end);
      const timeZone = this._timeZone();
      const parts = (date) => Object.fromEntries(new Intl.DateTimeFormat("en", {
        timeZone,
        month: "short",
        day: "numeric",
        year: "numeric",
      }).formatToParts(date).map((part) => [part.type, part.value]));
      const startParts = parts(start);
      const endParts = parts(end);
      if (startParts.year === endParts.year && startParts.month === endParts.month) {
        return startParts.day === endParts.day
          ? `${startParts.month} ${startParts.day}`
          : `${startParts.month} ${startParts.day}-${endParts.day}`;
      }
      return `${startParts.month} ${startParts.day}-${endParts.month} ${endParts.day}`;
    }

    _shiftDateKey(value, days) {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
      if (!match) return "";
      const date = new Date(Date.UTC(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3]) + days,
      ));
      return date.toISOString().slice(0, 10);
    }

    _zonedTimestamp(value, hour = 0, minute = 0, second = 0, millisecond = 0) {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
      if (!match) return Number.NaN;
      const target = Date.UTC(
        Number(match[1]),
        Number(match[2]) - 1,
        Number(match[3]),
        hour,
        minute,
        second,
      );
      let guess = target;
      try {
        const formatter = new Intl.DateTimeFormat("en-US", {
          timeZone: this._timeZone(),
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hourCycle: "h23",
        });
        for (let attempt = 0; attempt < 4; attempt += 1) {
          const parts = Object.fromEntries(formatter.formatToParts(new Date(guess))
            .map((part) => [part.type, part.value]));
          const rendered = Date.UTC(
            Number(parts.year),
            Number(parts.month) - 1,
            Number(parts.day),
            Number(parts.hour),
            Number(parts.minute),
            Number(parts.second),
          );
          const adjustment = target - rendered;
          if (!adjustment) break;
          guess += adjustment;
        }
      } catch (_error) {
        return target + millisecond;
      }
      return guess + millisecond;
    }

    _calendarRange(range = this._dashboardRange) {
      const startKey = this._chartDateKey(Date.parse(range.start));
      const endKey = this._chartDateKey(Date.parse(range.end));
      const days = Math.max(1, Math.round(
        (Date.parse(`${endKey}T00:00:00Z`) - Date.parse(`${startKey}T00:00:00Z`))
        / 86_400_000,
      ) + 1);
      return { startKey, endKey, days };
    }

    _rangeFromDateKeys(startKey, endKey, compare = false) {
      return {
        start: new Date(this._zonedTimestamp(startKey)).toISOString(),
        end: new Date(this._zonedTimestamp(endKey, 23, 59, 59, 999)).toISOString(),
        compare,
      };
    }

    _previousRange(range = this._dashboardRange) {
      const { startKey, days } = this._calendarRange(range);
      return this._rangeFromDateKeys(
        this._shiftDateKey(startKey, -days),
        this._shiftDateKey(startKey, -1),
        range.compare,
      );
    }

    _dashboardHistorySeries(payload, configuredEntities, rangeStart = Number.NEGATIVE_INFINITY) {
      const configs = new Map((configuredEntities || []).map((item) => [item.entity, item]));
      const parsed = [];
      for (const group of Array.isArray(payload) ? payload : []) {
        const rows = Array.isArray(group) ? group : [group];
        let entityId = "";
        const points = [];
        for (const row of rows.filter(Boolean)) {
          entityId = row.entity_id || entityId;
          const normalized = String(row.state || "").toLowerCase();
          const value = normalized === "on" ? 1 : normalized === "off" ? 0 : Number.parseFloat(row.state);
          const time = Date.parse(row.last_changed || row.last_updated || "");
          if (Number.isFinite(time)) {
            points.push({
              time: Math.max(rangeStart, time),
              value: Number.isFinite(value) ? value : null,
            });
          }
        }
        const config = configs.get(entityId);
        if (entityId && points.length) {
          parsed.push({
            entity_id: entityId,
            series_id: config && config.series_id || entityId,
            name: config && config.name || this._friendlyEntityName(entityId),
            unit: this._unit(entityId),
            axis: config && config.axis || "left",
            points: this._boundedChartPoints(points),
          });
        }
      }
      return parsed;
    }

    _groupDashboardHistorySeries(series) {
      const groups = new Map();
      for (const item of series) {
        const key = item.series_id || item.entity_id || item.name;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(item);
      }
      return [...groups.entries()].map(([seriesId, items]) => {
        if (items.length === 1) {
          return {
            ...items[0],
            series_id: seriesId,
            points: items[0].points.filter((point) => Number.isFinite(point.value)),
          };
        }
        const timestamps = [...new Set(items.flatMap((item) => (
          item.points.map((point) => point.time)
        )))].sort((left, right) => left - right);
        const pointIndexes = new Map(items.map((item) => [item, 0]));
        const latest = new Map();
        const points = [];
        for (const time of timestamps) {
          for (const item of items) {
            let index = pointIndexes.get(item);
            while (index < item.points.length && item.points[index].time <= time) {
              latest.set(item, item.points[index].value);
              index += 1;
            }
            pointIndexes.set(item, index);
          }
          const values = [...latest.values()].filter(Number.isFinite);
          if (values.length) {
            points.push({
              time,
              value: values.reduce((total, value) => total + value, 0),
            });
          }
        }
        return {
          ...items[0],
          entity_id: seriesId,
          series_id: seriesId,
          points: this._boundedChartPoints(points),
        };
      }).filter((item) => item.points.length);
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
      const unit = key === "energy" ? "kWh" : "currency";
      return `<section class="contribution">
        <h3>${this._escape(this._label("appliance_energy_cost", "Appliance Energy/Cost"))}</h3>
        <div class="controls">
          ${["energy", "cost"].map((mode) => `<button type="button" class="control" data-contribution-mode="${mode}" aria-pressed="${mode === this._contributionMode}">${this._escape(this._label(mode, mode))}</button>`).join("")}
        </div>
        <div class="bars">${top.map((item) => `<div class="bar-row"><span>${this._escape(item.name)}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${Math.max(item[key] / max * 100, 2)}%"></span></span><strong>${this._escape(this._formatValue(item[key], unit))}</strong></div>`).join("")}</div>
      </section>`;
    }
  }

  class CircuitSetupEnergyAnalyzerDateRange extends DashboardCardBase {
    constructor() {
      super();
      this._datePickerLoading = false;
      this._handleDashboardData = () => this._render();
    }

    connectedCallback() {
      super.connectedCallback();
      window.addEventListener(DATA_EVENT, this._handleDashboardData);
    }

    disconnectedCallback() {
      window.removeEventListener(DATA_EVENT, this._handleDashboardData);
      super.disconnectedCallback();
    }

    _render() {
      if (!this.shadowRoot || !this._dashboardConfig || !this._hass) return;
      this._ensureNativeDatePicker();
      const range = validRange(this._dashboardRange);
      const hasData = [...dashboardSeries.values()].some((series) => series.length);
      this.shadowRoot.innerHTML = `
        <ha-card>
          <style>
            ${this._styles()}
            .range-card { align-items: center; display: flex; gap: 8px; justify-content: space-between; }
            .range-picker { align-items: center; display: flex; min-width: 0; }
            .range-picker ha-date-range-picker { max-width: 100%; }
            .range-actions { align-items: center; display: flex; flex: 0 0 auto; }
            .range-actions ha-icon-button { align-items: center; cursor: pointer; display: inline-flex; height: 40px; justify-content: center; width: 40px; }
            .range-actions ha-icon-button[aria-pressed="true"] { color: var(--primary-color, #0b6bcb); }
            @media (max-width: 520px) {
              .range-card { align-items: stretch; flex-direction: column; }
              .range-actions { justify-content: flex-end; }
            }
          </style>
          <div class="dashboard-card range-card">
            <div class="range-picker">
              <ha-date-range-picker data-range-picker extended-presets backdrop></ha-date-range-picker>
              <strong class="sr-only" data-range-label>${this._escape(this._rangeLabel(range))}</strong>
            </div>
            <div class="range-actions">
              ${this._rangeAction("previous", "mdi:chevron-left", this._label("previous", "Previous"))}
              ${this._rangeAction("next", "mdi:chevron-right", this._label("next", "Next"))}
              ${this._rangeAction("now", "mdi:home-clock", this._label("now", "Now"))}
              <ha-icon-button data-range-compare aria-label="${this._escape(this._label("compare", "Compare"))}" title="${this._escape(this._label("compare", "Compare"))}" aria-pressed="${range.compare}">
                <ha-icon icon="${range.compare ? "mdi:checkbox-marked-outline" : "mdi:checkbox-blank-outline"}"></ha-icon>
              </ha-icon-button>
              <ha-icon-button data-range-download aria-label="${this._escape(this._label("download_data", "Download data"))}" title="${this._escape(this._label("download_data", "Download data"))}"${hasData ? "" : " disabled"}>
                <ha-icon icon="mdi:download"></ha-icon>
              </ha-icon-button>
            </div>
          </div>
        </ha-card>
      `;
      const picker = this.shadowRoot.querySelector("[data-range-picker]");
      picker.startDate = new Date(range.start);
      picker.endDate = new Date(range.end);
      picker.extendedPresets = true;
      picker.backdrop = true;
      picker.addEventListener("value-changed", (event) => {
        const value = event.detail && event.detail.value || {};
        setDashboardRange({
          start: value.startDate,
          end: value.endDate,
          compare: range.compare,
        });
      });
      for (const action of ["previous", "next", "now"]) {
        this.shadowRoot.querySelector(`[data-range-${action}]`).addEventListener("click", () => {
          this._shiftRange(action);
        });
      }
      this.shadowRoot.querySelector("[data-range-compare]").addEventListener("click", () => {
        setDashboardRange({ ...range, compare: !range.compare });
      });
      this.shadowRoot.querySelector("[data-range-download]").addEventListener("click", () => {
        if (hasData) this._downloadCsv(range);
      });
    }

    _rangeAction(action, icon, label) {
      return `<ha-icon-button data-range-${action} aria-label="${this._escape(label)}" title="${this._escape(label)}"><ha-icon icon="${icon}"></ha-icon></ha-icon-button>`;
    }

    _shiftRange(action) {
      const range = validRange(this._dashboardRange);
      const { startKey, endKey, days } = this._calendarRange(range);
      if (action === "previous") {
        setDashboardRange(this._previousRange(range));
        return;
      }
      if (action === "next") {
        setDashboardRange(this._rangeFromDateKeys(
          this._shiftDateKey(endKey, 1),
          this._shiftDateKey(endKey, days),
          range.compare,
        ));
        return;
      }
      const todayKey = this._chartDateKey(Date.now());
      setDashboardRange(this._rangeFromDateKeys(
        this._shiftDateKey(todayKey, 1 - days),
        todayKey,
        range.compare,
      ));
    }

    _downloadCsv(range) {
      const items = [];
      const labelCounts = new Map();
      const keyCounts = new Map();
      for (const series of dashboardSeries.values()) {
        for (const item of series) {
          if (item && item.name && Array.isArray(item.points) && item.points.length) {
            const labelCount = (labelCounts.get(item.name) || 0) + 1;
            const baseKey = item.series_id || item.entity_id || `series:${items.length}`;
            const keyCount = (keyCounts.get(baseKey) || 0) + 1;
            labelCounts.set(item.name, labelCount);
            keyCounts.set(baseKey, keyCount);
            items.push({
              item,
              key: `${baseKey}:${keyCount}`,
              label: labelCount === 1 ? item.name : `${item.name} (${labelCount})`,
            });
          }
        }
      }
      const exportTime = (point) => point.source_time ?? point.time;
      const times = [...new Set(items.flatMap(({ item }) => (
        item.points.map(exportTime)
      )))].sort((left, right) => left - right);
      const values = new Map(items.map(({ key, item }) => [
        key,
        new Map(item.points.map((point) => [exportTime(point), point.value])),
      ]));
      const csvValue = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
      const rows = [
        ["Timestamp", ...items.map(({ label }) => label)].map(csvValue).join(","),
        ...times.map((time) => [
          new Date(time).toISOString(),
          ...items.map(({ key }) => values.get(key).get(time) ?? ""),
        ].map(csvValue).join(",")),
      ];
      const url = URL.createObjectURL(new Blob([`${rows.join("\r\n")}\r\n`], {
        type: "text/csv;charset=utf-8",
      }));
      const link = document.createElement("a");
      link.href = url;
      link.download = `circuitsetup-energy-${range.start.slice(0, 10)}-${range.end.slice(0, 10)}.csv`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }

    async _ensureNativeDatePicker() {
      if (customElements.get("ha-date-range-picker") || this._datePickerLoading || !window.loadCardHelpers) return;
      this._datePickerLoading = true;
      try {
        const helpers = await window.loadCardHelpers();
        helpers.createCardElement({ type: "energy-date-selection" });
        await customElements.whenDefined("ha-date-range-picker");
        this._render();
      } catch (_error) {
        this._datePickerLoading = false;
      }
    }
  }

  class CircuitSetupEnergyAnalyzerContextGraph extends DashboardCardBase {
    constructor() {
      super();
      this._history = null;
      this._comparisonHistory = null;
      this._historyKey = "";
      this._historyError = "";
      this._historyLoadedAt = 0;
    }

    _render() {
      if (!this.shadowRoot || !this._dashboardConfig || !this._hass) return;
      const config = this._dashboardConfig;
      const entities = this._resolvedEntities(config);
      if ((config.water_contexts || []).length && !entities.some((item) => item.axis === "right")) {
        this.style.display = "none";
        this.shadowRoot.innerHTML = "";
        this._publishDashboardSeries([]);
        return;
      }
      this.style.display = "";
      this._ensureHistory(entities);
      const range = validRange(this._dashboardRange);
      const currentSeries = this._groupDashboardHistorySeries(
        this._normalizedPowerSeries(
          this._dashboardHistorySeries(this._history, entities, Date.parse(range.start)),
          config.y_axis_label,
        ),
      ).map((item, index) => ({ ...item, color_index: index }));
      const previousRange = this._previousRange(range);
      const currentStart = Date.parse(range.start);
      const currentDuration = Date.parse(range.end) - currentStart;
      const previousStart = Date.parse(previousRange.start);
      const previousDuration = Date.parse(previousRange.end) - previousStart;
      const comparisonSeries = range.compare
        ? this._groupDashboardHistorySeries(
          this._normalizedPowerSeries(
            this._dashboardHistorySeries(
              this._comparisonHistory,
              entities,
              Date.parse(previousRange.start),
            ),
            config.y_axis_label,
          ),
        ).map((item, index) => ({
          ...item,
          name: `${item.name} (${this._label("previous", "previous")})`,
          color_index: index,
          line_style: "dashed",
          points: item.points.map((point) => ({
            ...point,
            source_time: point.time,
            time: currentStart + (
              (point.time - previousStart) / Math.max(previousDuration, 1)
            ) * currentDuration,
          })),
        }))
        : [];
      const series = [...currentSeries, ...comparisonSeries];
      const leftSeries = series.find((item) => item.axis !== "right");
      const rightSeries = series.find((item) => item.axis === "right");
      const chart = series.length
        ? this._chartSvg(series, {
          graph_window_start: range.start,
          graph_window_end: range.end,
          y_axis_label: config.y_axis_label || (leftSeries && leftSeries.unit) || "W",
          ...(rightSeries ? { right_y_axis_label: rightSeries.unit || this._label("temperature", "Temperature") } : {}),
        })
        : `<p class="muted">${this._escape(this._historyError || this._label("no_history", "No history is available for this period."))}</p>`;
      this.shadowRoot.innerHTML = `
        <ha-card>
          <style>${this._styles()}</style>
          <div class="dashboard-card">
            <h2>${this._escape(config.title || "")}</h2>
            ${chart}
          </div>
        </ha-card>
      `;
      this._publishDashboardSeries(series);
      this._attachChartInspectors();
    }

    _normalizedPowerSeries(series, targetUnit = "") {
      const wattsPerUnit = { W: 1, kW: 1000 };
      const target = series.find((item) => item.axis !== "right" && wattsPerUnit[item.unit]);
      const normalizedUnit = wattsPerUnit[targetUnit] ? targetUnit : target && target.unit;
      if (!normalizedUnit) return series;
      return series.map((item) => {
        const scale = item.axis !== "right" && wattsPerUnit[item.unit];
        const factor = scale ? scale / wattsPerUnit[normalizedUnit] : 1;
        return factor === 1 ? item : {
          ...item,
          unit: normalizedUnit,
          points: item.points.map((point) => ({
            ...point,
            value: Number.isFinite(point.value) ? point.value * factor : point.value,
          })),
        };
      });
    }

    _resolvedEntities(config) {
      const entities = (config.entities || []).filter((item) => item && item.entity);
      const powerEntities = [];
      const flowEntities = [];
      for (const context of config.water_contexts || []) {
        const state = this._state(context.correlation_entity);
        const raw = state && state.attributes && state.attributes.flow_sensor_entities;
        const flows = (Array.isArray(raw) ? raw : typeof raw === "string" ? [raw] : [])
          .filter((entityId) => typeof entityId === "string" && entityId);
        if (!flows.length) continue;
        powerEntities.push(...(context.power_entities || []).map((entity) => ({
          entity,
          name: `${context.name} power`,
          series_id: context.series_id || `water:${context.name}`,
          axis: "left",
        })));
        flowEntities.push(...flows.map((entity) => ({
          entity,
          name: this._friendlyEntityName(entity),
          axis: "right",
        })));
      }
      return [...new Map([...entities, ...powerEntities, ...flowEntities]
        .map((item) => [item.entity, item])).values()];
    }

    _ensureHistory(entities) {
      const range = validRange(this._dashboardRange);
      const key = `${range.start}:${range.end}:${range.compare}:${entities.map((item) => item.entity).join(",")}`;
      if (!entities.length || key === this._historyKey) return;
      this._historyKey = key;
      this._historyLoadedAt = Date.now();
      const entityIds = entities.map((item) => item.entity);
      const previousRange = this._previousRange(range);
      const requests = [
        this._historyRequest(range.start, range.end, entityIds),
        range.compare
          ? this._historyRequest(
            previousRange.start,
            previousRange.end,
            entityIds,
          )
          : Promise.resolve([]),
      ];
      Promise.allSettled(requests).then(([history, comparison]) => {
        if (this._historyKey !== key) return;
        this._history = history.status === "fulfilled" ? history.value : [];
        this._comparisonHistory = comparison.status === "fulfilled" ? comparison.value : [];
        this._historyError = history.status === "fulfilled"
          ? ""
          : this._label("no_history", "No history is available for this period.");
        this._render();
      });
    }

    _refreshLiveData() {
      const { startKey, endKey } = this._calendarRange();
      const todayKey = this._chartDateKey(Date.now());
      if (
        startKey <= todayKey
        && endKey >= todayKey
        && Date.now() - this._historyLoadedAt >= 60_000
      ) {
        this._historyKey = "";
      }
    }

    _historyRequest(start, end, entityIds) {
      const { days: spanDays } = this._calendarRange({ start, end });
      if (spanDays <= 31) {
        const ids = encodeURIComponent(entityIds.join(","));
        const path = `history/period/${start}?filter_entity_id=${ids}&end_time=${encodeURIComponent(end)}&minimal_response=1&no_attributes=1`;
        return this._hass.callApi("GET", path);
      }
      if (typeof this._hass.callWS !== "function") return Promise.resolve([]);
      const period = spanDays <= 90
        ? "hour"
        : spanDays <= 730
          ? "day"
          : spanDays <= 5_110 ? "week" : "month";
      return this._hass.callWS({
        type: "recorder/statistics_during_period",
        start_time: start,
        end_time: end,
        statistic_ids: entityIds,
        period,
        types: ["mean"],
      }).then((result) => Object.entries(result || {}).map(([entityId, rows]) => (
        (rows || []).flatMap((row) => {
          const time = typeof row.start === "number" ? row.start : Date.parse(row.start);
          return row.mean !== null
            && row.mean !== undefined
            && Number.isFinite(Number(row.mean))
            && Number.isFinite(time) ? [{
            entity_id: entityId,
            state: row.mean,
            last_changed: new Date(time).toISOString(),
          }] : [];
        })
      )));
    }
  }

  class CircuitSetupEnergyAnalyzerSummary extends DashboardCardBase {
    _render() {
      if (!this.shadowRoot || !this._dashboardConfig || !this._hass) return;
      const config = this._dashboardConfig;
      const compactLinks = (config.links || []).length && !(config.entities || []).length;
      this.shadowRoot.innerHTML = `
        <ha-card>
          <style>${this._styles()}</style>
          <div class="dashboard-card">
            <h2>${this._escape(config.title || "")}</h2>
            ${config.description ? `<p class="muted">${this._escape(config.description)}</p>` : ""}
            <div class="summary-list${compactLinks ? " compact-links" : ""}">
              ${(config.entities || []).map((item) => {
                const state = this._state(item.entity);
                const unit = this._unit(item.entity);
                const monetary = state && state.attributes && state.attributes.device_class === "monetary"
                  || unit === this._currencyCode();
                const numeric = this._number(item.entity);
                const value = Number.isFinite(numeric)
                  ? this._formatValue(numeric, monetary ? "currency" : unit)
                  : state ? String(state.state) : this._label("unavailable", "Unavailable");
                return `<button type="button" class="summary-row" data-summary-entity="${this._escape(item.entity)}"><strong>${this._escape(item.name || this._friendlyEntityName(item.entity))}</strong><span>${this._escape(value)}</span></button>`;
              }).join("")}
              ${(config.links || []).map((item) => `<a class="summary-link" href="${this._escape(item.path)}"><strong>${this._escape(item.name)}</strong><ha-icon icon="mdi:chevron-right"></ha-icon></a>`).join("")}
            </div>
          </div>
        </ha-card>
      `;
      for (const row of this.shadowRoot.querySelectorAll("[data-summary-entity]")) {
        row.addEventListener("click", () => this.dispatchEvent(new CustomEvent("hass-more-info", {
          bubbles: true,
          composed: true,
          detail: { entityId: row.dataset.summaryEntity },
        })));
      }
    }
  }

  class CircuitSetupEnergyAnalyzerHouseFlow extends DashboardCardBase {
    constructor() {
      super();
      this._contributionMode = "energy";
      this._rollingContributionByCircuit = {};
      this._rangeSummary = {};
      this._contributionLoadKey = "";
      this._rangeTotalsLoadedAt = 0;
    }

    _render() {
      if (!this.shadowRoot || !this._dashboardConfig || !this._hass) return;
      const config = this._dashboardConfig;
      if (
        config.mode !== "mains"
        && !this._contributionLoadKey
      ) {
        this._loadRangeTotals();
      }
      const mains = config.primary_mains || {};
      const appliances = (config.appliances || []).map((item) => this._applianceState(item));
      const contributionAppliances = this._contributionAppliances(appliances);
      const knownPower = this._number(mains.monitored_power_entity)
        ?? appliances.reduce((total, item) => total + (item.power || 0), 0);
      const housePower = this._sum(mains.power_entities) ?? knownPower;
      const unassignedPower = this._number(mains.balance_power_entity);
      const coverage = this._number(mains.monitored_coverage_entity);
      const runningCount = appliances.filter((item) => item.running).length;
      const issueCount = appliances.filter((item) => item.issue).length;
      const energyToday = this._rangeSummary.energy ?? null;
      const costToday = this._rangeSummary.cost ?? null;
      const averageEnergy = config.primary_mains && mains.average_kwh_per_day_entity
        ? this._number(mains.average_kwh_per_day_entity)
        : null;
      const averageCost = config.primary_mains && mains.average_cost_per_day_entity
        ? this._number(mains.average_cost_per_day_entity)
        : null;
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
      const rangeLabel = this._rangeLabel();
      const flow = `
        <section class="flow">
          <h3>${this._escape(housePowerLabel)}: ${this._escape(this._formatValue(housePower, "W"))}</h3>
          <div class="flow-bar" role="img" aria-label="${this._escape(this._label("known_load_coverage", "Known load coverage"))} ${knownPercent.toFixed(0)}%">
            <span class="flow-known" style="width:${knownPercent}%"></span>
            <span class="flow-unassigned" style="width:${100 - knownPercent}%"></span>
          </div>
          <div class="flow-labels">
            <span><i class="swatch flow-known"></i>${this._escape(this._label("known_monitored_load", "Known monitored load"))}: ${this._escape(this._formatValue(knownPower, "W"))}</span>
            <span><i class="swatch flow-unassigned"></i>${this._escape(this._label("unassigned_load", "Unassigned load"))}: ${this._escape(this._formatValue(unassignedPower, "W"))}</span>
            <span><i class="swatch flow-known"></i>${this._escape(this._label("known_load_coverage", "Known load coverage"))}: ${this._escape(this._formatValue(coverage, "%"))}</span>
            ${mains.solar_surplus_power_entity ? `<span>${this._escape(this._label("solar_surplus", "Solar surplus"))}: ${this._escape(this._formatEntity(mains.solar_surplus_power_entity, "W"))}</span>` : ""}
          </div>
        </section>
      `;
      const homeContent = config.mode === "mains" ? "" : `
        <div class="kpis">
          ${this._metricHtml(housePowerLabel, housePower, "W")}
          ${this._metricHtml(`${this._label("energy", "Energy")} (${rangeLabel})`, energyToday, "kWh", averageEnergy)}
          ${this._metricHtml(`${this._label("cost", "Cost")} (${rangeLabel})`, costToday, "currency", averageCost)}
          ${this._metricHtml(this._label("running", "Running"), runningCount, "")}
          ${this._metricHtml(this._label("issues", "Issues"), issueCount, "")}
        </div>
        ${this._contributionHtml(contributionAppliances)}
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

    _metricHtml(label, value, unit, average = null) {
      return `<div class="metric"><span>${this._escape(label)}</span><strong>${this._escape(this._formatValue(value, unit))}</strong>${Number.isFinite(average) ? `<small>${this._escape(this._label("average", "Average"))}: ${this._escape(this._formatValue(average, unit))}</small>` : ""}</div>`;
    }

    _statusMetric(label, entityId) {
      const state = this._state(entityId);
      const value = state && !["unknown", "unavailable", ""].includes(String(state.state).toLowerCase())
        ? String(state.state)
        : this._label("unavailable", "Unavailable");
      return `<div class="metric"><span>${this._escape(label)}</span><strong>${this._escape(value)}</strong></div>`;
    }

    _contributionAppliances(appliances) {
      return appliances.map((appliance) => {
        const rolling = this._rollingContributionByCircuit[appliance.circuit_id] || {};
        return {
          ...appliance,
          energy: rolling.energy ?? null,
          cost: rolling.cost ?? null,
        };
      });
    }

    async _loadRangeTotals() {
      const appliances = this._dashboardConfig.appliances || [];
      const mains = this._dashboardConfig.primary_mains || {};
      const range = validRange(this._dashboardRange);
      const { startKey, endKey } = this._calendarRange(range);
      const todayKey = this._chartDateKey(Date.now());
      const entityIds = [...new Set([
        ...appliances.flatMap((item) => [...(item.power_entities || []), item.cost_today_entity]),
        ...(mains.power_entities || []),
        mains.cost_today_entity,
      ]
        .filter(Boolean))];
      const key = `${range.start}:${range.end}:${entityIds.join(",")}`;
      this._contributionLoadKey = key;
      this._rangeTotalsLoadedAt = Date.now();
      const start = Date.parse(range.start);
      const end = Math.max(start, Math.min(Date.parse(range.end), Date.now()));
      const liveStart = Math.max(start, this._zonedTimestamp(todayKey));
      const hasLiveWindow = startKey <= todayKey && endKey >= todayKey && end > liveStart;
      const historyPath = `history/period/${new Date(liveStart).toISOString()}?filter_entity_id=${encodeURIComponent(entityIds.join(","))}&end_time=${encodeURIComponent(new Date(end).toISOString())}&minimal_response=1&no_attributes=1`;
      const [insightsResult, historyResult] = await Promise.allSettled([
        this._hass.callApi("GET", this._dashboardConfig.api_path),
        entityIds.length && hasLiveWindow
          ? this._hass.callApi("GET", historyPath)
          : Promise.resolve([]),
      ]);
      if (this._contributionLoadKey !== key) return;
      const insights = insightsResult.status === "fulfilled" ? insightsResult.value || {} : {};
      const payload = historyResult.status === "fulfilled" ? historyResult.value : [];
      const liveAppliances = this._rollingTotals(payload, appliances, liveStart, end);
      const retainedItems = (insights.items || []).filter((item) => (
        !this._dashboardConfig.entry_id || item.entry_id === this._dashboardConfig.entry_id
      ));
      this._rollingContributionByCircuit = Object.fromEntries(appliances.map((appliance) => {
        const retained = retainedItems.find((item) => (
          item.circuit_id === appliance.circuit_id || item.appliance_key === appliance.circuit_id
        ));
        return [appliance.circuit_id, this._mergeRangeTotals(
          this._retainedRangeTotals(retained, startKey, endKey, todayKey),
          liveAppliances[appliance.circuit_id],
        )];
      }));
      const liveSummary = this._rollingTotals(payload, [{
        circuit_id: "mains",
        power_entities: mains.power_entities || [],
        cost_today_entity: mains.cost_today_entity,
      }], liveStart, end).mains;
      const retainedMains = (insights.whole_house || []).find((item) => (
        (!this._dashboardConfig.entry_id || item.entry_id === this._dashboardConfig.entry_id)
        && (!mains.circuit_id || item.circuit_id === mains.circuit_id)
      ));
      this._rangeSummary = this._mergeRangeTotals(
        this._retainedRangeTotals(retainedMains, startKey, endKey, todayKey),
        liveSummary,
      );
      this._render();
    }

    _refreshLiveData() {
      const { startKey, endKey } = this._calendarRange();
      const todayKey = this._chartDateKey(Date.now());
      if (
        startKey <= todayKey
        && endKey >= todayKey
        && Date.now() - this._rangeTotalsLoadedAt >= 60_000
      ) {
        this._contributionLoadKey = "";
      }
    }

    _retainedRangeTotals(item, startKey, endKey, todayKey) {
      const rows = (item && item.daily_totals || []).filter((row) => (
        String(row.date) >= startKey
        && String(row.date) <= endKey
        && String(row.date) < todayKey
      ));
      if (!rows.length) return startKey < todayKey ? { energy: null, cost: null } : {};
      const energy = rows.map((row) => Number(row.energy_kwh));
      const cost = rows.map((row) => (
        row.cost === null || row.cost === undefined ? Number.NaN : Number(row.cost)
      ));
      const sum = (values) => values.every(Number.isFinite)
        ? values.reduce((total, value) => total + value, 0)
        : null;
      return { energy: sum(energy), cost: sum(cost) };
    }

    _mergeRangeTotals(retained = {}, live = {}) {
      const combined = (stored, current) => {
        if (stored === null) return null;
        const values = [stored, current].filter(Number.isFinite);
        return values.length ? values.reduce((total, value) => total + value, 0) : null;
      };
      return {
        energy: combined(retained.energy, live && live.energy),
        cost: combined(retained.cost, live && live.cost),
      };
    }

    _rollingTotals(payload, appliances, start, end) {
      if (!Array.isArray(payload)) return {};
      const history = {};
      for (const group of payload) {
        const rows = Array.isArray(group) ? group : [group];
        let entityId = "";
        for (const row of rows.filter(Boolean)) {
          entityId = row.entity_id || entityId;
          if (!entityId) continue;
          (history[entityId] ||= []).push(row);
        }
      }
      return Object.fromEntries(appliances.map((appliance) => {
        const powerEntities = appliance.power_entities || [];
        const energyValues = powerEntities.map((entityId) => (
          this._integratedEnergy(
            history[entityId],
            start,
            end,
            this._unit(entityId) === "kW" ? 1000 : 1,
          )
        ));
        const energy = powerEntities.length && energyValues.every(Number.isFinite)
          ? energyValues.reduce((total, value) => total + value, 0)
          : null;
        const cost = appliance.cost_today_entity
          ? this._counterIncrease(history[appliance.cost_today_entity])
          : null;
        return [appliance.circuit_id, { energy, cost }];
      }));
    }

    _integratedEnergy(rows, start, end, wattsPerUnit = 1) {
      const points = (rows || []).map((row) => ({
        time: Date.parse(row.last_changed || row.last_updated || ""),
        value: Number(row.state),
      })).filter((point) => Number.isFinite(point.time) && point.time <= end)
        .sort((left, right) => left.time - right.time);
      let energy = 0;
      let previous = null;
      let sawValue = false;
      for (const point of points) {
        const time = Math.max(start, point.time);
        if (!Number.isFinite(point.value) || point.value < 0) {
          if (previous && time > previous.time) {
            energy += previous.value * wattsPerUnit * (time - previous.time) / 3_600_000 / 1_000;
          }
          previous = null;
          continue;
        }
        const value = point.value;
        sawValue = true;
        if (previous && time > previous.time) {
          energy += previous.value * wattsPerUnit * (time - previous.time) / 3_600_000 / 1_000;
        }
        previous = { time, value };
      }
      if (previous && end > previous.time) {
        energy += previous.value * wattsPerUnit * (end - previous.time) / 3_600_000 / 1_000;
      }
      return sawValue ? energy : null;
    }

    _counterIncrease(rows) {
      const values = (rows || []).map((row) => ({
        time: Date.parse(row.last_changed || row.last_updated || ""),
        value: Number(row.state),
      })).filter((point) => Number.isFinite(point.time))
        .sort((left, right) => left.time - right.time);
      let previous = null;
      let total = 0;
      for (const point of values) {
        if (!Number.isFinite(point.value) || point.value < 0) {
          previous = null;
          continue;
        }
        if (previous !== null) {
          total += point.value >= previous ? point.value - previous : point.value;
        }
        previous = point.value;
      }
      return previous === null ? null : total;
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
      const visible = appliances.filter((item) => (
        this._filter === "all"
          || this._filter === "running" && item.running
          || this._filter === "attention" && item.issue
      )).sort((left, right) => (
        Number(right.issue) - Number(left.issue)
          || Number(right.running) - Number(left.running)
          || (right.power || 0) - (left.power || 0)
          || String(left.name).localeCompare(String(right.name))
      ));
      const filters = [
        ["all", this._label("all", "All")],
        ["running", this._label("running", "Running")],
        ["attention", this._label("needs_attention", "Needs attention")],
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
              ${visible.map((item) => this._tile(item, !this._matchesSearch(item))).join("")}
            </div>
            <section class="timeline">
              <h3>${this._escape(this._label("run_timeline", "Run timeline"))}</h3>
              <div class="controls">
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
        for (const tile of this.shadowRoot.querySelectorAll("[data-appliance-id]")) {
          const item = appliances.find((candidate) => candidate.circuit_id === tile.dataset.applianceId);
          tile.hidden = !item || !this._matchesSearch(item);
        }
      });
      for (const tile of this.shadowRoot.querySelectorAll("[data-appliance-id]")) {
        tile.addEventListener("click", () => {
          const item = appliances.find((candidate) => candidate.circuit_id === tile.dataset.applianceId);
          this._navigate(item && item.detail_path);
        });
      }
      this._ensureTimeline(appliances);
    }

    _matchesSearch(item) {
      const search = this._search.toLowerCase();
      return !search || `${item.name} ${item.area || ""}`.toLowerCase().includes(search);
    }

    _tile(item, hidden = false) {
      const powerUnit = this._unit((item.power_entities || [])[0], "W");
      return `<button type="button" class="appliance-tile" data-appliance-id="${this._escape(item.circuit_id)}"${hidden ? " hidden" : ""}>
        <span class="appliance-heading"><ha-icon icon="${this._escape(item.icon || "mdi:power-plug-outline")}"></ha-icon><strong>${this._escape(item.name)}</strong></span>
        <div class="appliance-meta">
          ${item.area ? `<span>${this._escape(item.area)}</span>` : ""}
          <span class="${item.issue ? "issue" : ""}">${this._escape(item.issue ? this._label("needs_attention", "Needs attention") : item.running ? this._label("running", "Running") : this._label("idle", "Idle"))} · ${this._escape(this._formatValue(item.power, powerUnit))}</span>
          <span>${this._escape(this._label("energy_today", "Today"))}: ${this._escape(this._formatValue(item.energy, "kWh"))} · ${this._escape(this._formatValue(item.cost, "currency"))}</span>
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
      const selected = this._selectedTimelineAppliances(appliances).filter((item) => item.activity_entity);
      const ids = selected.map((item) => item.activity_entity);
      const range = this._timelineRange();
      const key = `${range.start}:${range.end}:${ids.join(",")}`;
      if (!ids.length || key === this._timelineKey) return;
      this._timelineKey = key;
      const path = `history/period/${range.start}?filter_entity_id=${encodeURIComponent(ids.join(","))}&end_time=${encodeURIComponent(range.end)}&minimal_response=1&no_attributes=1`;
      try {
        const rows = await this._hass.callApi("GET", path);
        if (this._timelineKey !== key) return;
        this._timelineRows = this._normalizeTimelineRows(rows);
      } catch (_error) {
        if (this._timelineKey !== key) return;
        this._timelineRows = [];
      }
      this._render();
    }

    _normalizeTimelineRows(payload) {
      if (!Array.isArray(payload)) return [];
      return payload.flatMap((group) => {
        const rows = Array.isArray(group) ? group : [group];
        let entityId = "";
        return rows.filter(Boolean).map((row) => {
          entityId = row.entity_id || entityId;
          return { ...row, entity_id: row.entity_id || entityId };
        });
      });
    }

    _timelineHtml(appliances) {
      const selected = this._selectedTimelineAppliances(appliances).filter((item) => item.activity_entity);
      const range = this._timelineRange();
      const start = Date.parse(range.start);
      const end = Date.parse(range.end);
      const observedEnd = Math.max(start, Math.min(end, Date.now()));
      const lanes = selected.map((item) => {
        const points = this._timelineRows.filter((row) => row.entity_id === item.activity_entity)
          .map((row) => ({
            time: Date.parse(row.last_changed || row.last_updated || ""),
            state: row.state,
          }))
          .filter((row) => Number.isFinite(row.time))
          .sort((left, right) => left.time - right.time);
        if (!points.length) return "";
        const stateAtStart = points.filter((point) => point.time <= start).at(-1);
        const windowPoints = [
          ...(stateAtStart ? [{ ...stateAtStart, time: start }] : []),
          ...points.filter((point) => point.time > start && point.time <= observedEnd),
        ];
        const bands = windowPoints.map((point, index) => ({
          ...point,
          end: windowPoints[index + 1] ? windowPoints[index + 1].time : observedEnd,
        })).filter((point) => String(point.state).toLowerCase() === "running" && point.end > point.time);
        return `<div class="timeline-lane"><span>${this._escape(item.name)}</span><span class="timeline-track">${bands.map((band) => `<span class="running-band" data-running-band style="left:${(band.time - start) / (end - start) * 100}%;width:${(band.end - band.time) / (end - start) * 100}%"></span>`).join("")}</span></div>`;
      }).filter(Boolean);
      const scale = `<div class="timeline-scale"><span></span><div class="timeline-axis" aria-label="${this._escape(this._rangeLabel(range))}">
        ${this._timelineTicks(start, end).map((label) => `<span data-timeline-tick>${this._escape(label)}</span>`).join("")}
      </div></div>`;
      return lanes.length ? `${lanes.join("")}${scale}` : `<p class="muted">${this._escape(this._label("no_history", "No running history is available for this period."))}</p>`;
    }

    _timelineRange() {
      const range = validRange(this._dashboardRange);
      const { endKey, days } = this._calendarRange(range);
      return days <= 31
        ? range
        : this._rangeFromDateKeys(this._shiftDateKey(endKey, -30), endKey);
    }

    _timelineTicks(start, end) {
      const format = new Intl.DateTimeFormat("en", {
        timeZone: this._timeZone(),
        month: "short",
        day: "numeric",
      });
      return [0, 0.25, 0.5, 0.75, 1].map((ratio) => (
        format.format(new Date(start + (end - start) * ratio))
      ));
    }
  }

  class CircuitSetupEnergyAnalyzerEnergyCost extends DashboardCardBase {
    constructor() {
      super();
      this._selection = "whole";
      this._insights = null;
      this._wholeHouse = [];
      this._loadRequested = false;
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
      const range = validRange(this._dashboardRange);
      const { startKey, endKey, days } = this._calendarRange(range);
      const historyRows = this._historyRows(items);
      const rows = historyRows.filter((row) => (
        String(row.date) >= startKey && String(row.date) <= endKey
      ));
      const energyPoints = rows.map((row) => ({
        time: this._dailyTimestamp(row.date),
        value: Number(row.energy_kwh),
      })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));
      const costPoints = rows.map((row) => ({
        time: this._dailyTimestamp(row.date),
        value: row.cost === null || row.cost === undefined ? Number.NaN : Number(row.cost),
        cost_source: row.cost_source,
      })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));
      const currency = this._currencySymbol();
      const previousStartKey = this._shiftDateKey(startKey, -days);
      const previousEndKey = this._shiftDateKey(startKey, -1);
      const previousRows = range.compare ? historyRows.filter((row) => (
        String(row.date) >= previousStartKey && String(row.date) <= previousEndKey
      )) : [];
      const shiftedPoint = (row, value) => ({
        source_time: this._dailyTimestamp(row.date),
        time: this._dailyTimestamp(this._shiftDateKey(
          startKey,
          Math.round((
            Date.parse(`${row.date}T00:00:00Z`)
            - Date.parse(`${previousStartKey}T00:00:00Z`)
          ) / 86_400_000),
        )),
        value,
      });
      const validPoint = (point) => (
        Number.isFinite(point.time) && Number.isFinite(point.value)
      );
      const previousEnergy = previousRows.map((row) => (
        shiftedPoint(row, Number(row.energy_kwh))
      )).filter(validPoint);
      const previousCost = previousRows.map((row) => shiftedPoint(
        row,
        row.cost === null || row.cost === undefined ? Number.NaN : Number(row.cost),
      )).filter(validPoint);
      const hasEnergy = energyPoints.length || previousEnergy.length;
      const hasCost = costPoints.length || previousCost.length;
      const series = [
        energyPoints.length && { name: this._label("energy", "Energy"), unit: "kWh", kind: "bar", color_index: 0, points: energyPoints },
        costPoints.length && { name: this._label("cost", "Cost"), unit: "currency", axis: hasEnergy ? "right" : "left", color_index: 1, points: costPoints },
        previousEnergy.length && { name: `${this._label("energy", "Energy")} (${this._label("previous", "previous")})`, unit: "kWh", line_style: "dashed", color_index: 0, points: previousEnergy },
        previousCost.length && { name: `${this._label("cost", "Cost")} (${this._label("previous", "previous")})`, unit: "currency", axis: hasEnergy ? "right" : "left", line_style: "dashed", color_index: 1, points: previousCost },
      ].filter(Boolean);
      const chart = series.length ? this._chartSvg(series, {
        graph_window_start: range.start,
        graph_window_end: range.end,
        y_axis_label: hasEnergy ? "kWh" : currency,
        ...(hasEnergy && hasCost ? { right_y_axis_label: currency } : {}),
      }) : `<p class="muted">${this._escape(this._label("no_history", "No completed-day history is available."))}</p>`;
      const unavailable = rows.some((row) => row.cost === null || row.cost === undefined);
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
              <div class="controls">
                <h3>${this._escape(this._label("completed_history", "Completed-day history"))}</h3>
                <select data-energy-selection aria-label="${this._escape(this._label("completed_history", "Completed-day history"))}">${selectedOptions}</select>
              </div>
              ${chart}
              ${unavailable ? `<p class="muted">${this._escape(this._label("unavailable", "Unavailable"))}</p>` : ""}
            </section>
          </div>
        </ha-card>
      `;
      const select = this.shadowRoot.querySelector("[data-energy-selection]");
      select.value = this._selection;
      select.addEventListener("change", () => {
        this._selection = select.value;
        this._render();
      });
      this._publishDashboardSeries(series);
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

    _dailyTimestamp(value) {
      return this._zonedTimestamp(value, 12);
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
            color: var(--primary-text-color, #111827);
            display: grid;
            font-family: Roboto, Noto, sans-serif;
            font-size: 14px;
            gap: 16px;
            line-height: 20px;
            padding: 16px;
          }
          h2, h3 {
            margin: 0;
          }
          h2 {
            font-size: 24px;
            font-weight: 400;
            line-height: 32px;
          }
          h3 {
            font-size: 20px;
            font-weight: 400;
            line-height: 28px;
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
          .legend-marker {
            --mdc-icon-size: 16px;
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
  if (!customElements.get("circuitsetup-energy-analyzer-context-graph")) {
    customElements.define("circuitsetup-energy-analyzer-context-graph", CircuitSetupEnergyAnalyzerContextGraph);
  }
  if (!customElements.get("circuitsetup-energy-analyzer-date-range")) {
    customElements.define("circuitsetup-energy-analyzer-date-range", CircuitSetupEnergyAnalyzerDateRange);
  }
  if (!customElements.get("circuitsetup-energy-analyzer-summary")) {
    customElements.define("circuitsetup-energy-analyzer-summary", CircuitSetupEnergyAnalyzerSummary);
  }
  return CircuitSetupEnergyAnalyzerDashboardGraphs;
}
