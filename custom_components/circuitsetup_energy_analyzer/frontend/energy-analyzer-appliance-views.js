export function createApplianceViewMethods({
  APPLIANCE_DETAIL_API_PATH,
  APPLIANCE_DETAIL_CALL_API_PATH,
  APPLIANCE_INSIGHTS_API_PATH,
  APPLIANCE_INSIGHTS_CALL_API_PATH,
  SETUP_HEALTH_API_PATH,
  SETUP_HEALTH_CALL_API_PATH,
  NILM_WORKSPACE_QUERY_PARAM,
  APPLIANCE_DETAIL_QUERY_PARAM,
  APPLIANCE_INSIGHTS_QUERY_PARAM,
  SETUP_HEALTH_QUERY_PARAM,
  PANEL_URL_PATH,
}) {
  return class ApplianceViewMethods {
  async _loadApplianceDetail(requestId = this._evidenceRequestId, routeKey = this._loadedRouteKey) {
    if (!this._routeRequestsApplianceDetail(routeKey)) {
      return;
    }
    const routeUrl = new URL(routeKey, window.location.origin);
    const params = new URLSearchParams();
    const circuit = this._payload && this._payload.circuit;
    const circuitId = routeUrl.searchParams.get("circuit_id") || (circuit && circuit.circuit_id) || "";
    const assignmentId = routeUrl.searchParams.get("assignment_id") || "";
    const entryId = routeUrl.searchParams.get("entry_id") || "";
    if (circuitId) {
      params.set("circuit_id", circuitId);
    }
    if (assignmentId) {
      params.set("assignment_id", assignmentId);
    }
    if (entryId) {
      params.set("entry_id", entryId);
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
      this._expectedScheduleDraft = this._scheduleDraftFromPayload(detail.expected_schedule);
      await this._loadApplianceDetailHistory(undefined, requestId, routeKey);
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._applianceDetailError = this._panelTextFormat("errors.load_appliance_detail", { path: fetchPath, message: error.message });
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._applianceDetailLoading = false;
        this._render();
      }
    }
  }

  async _loadApplianceDetailHistory(hours, requestId = this._evidenceRequestId, routeKey = this._loadedRouteKey) {
    const history = this._applianceDetail && this._applianceDetail.history;
    const entities = Array.isArray(history && history.entities) ? history.entities.filter(Boolean) : [];
    const embeddedSeries = Array.isArray(history && history.embedded_series) ? history.embedded_series : [];
    if (!entities.length && !embeddedSeries.length) {
      return;
    }
    const periods = Array.isArray(history.period_hours) ? history.period_hours.map(Number).filter(Number.isFinite) : [];
    const defaultHours = Number(history.default_hours);
    const requestedHours = periods.includes(Number(hours))
      ? Number(hours)
      : periods.includes(defaultHours)
        ? defaultHours
        : periods[0];
    if (!Number.isFinite(requestedHours) || requestedHours <= 0) {
      return;
    }
    const end = Date.now();
    const start = end - requestedHours * 60 * 60 * 1000;
    this._applianceDetailHistoryHours = requestedHours;
    this._applianceDetailHistoryBounds = { min: start, max: end };
    this._applianceDetailHistoryWindow = null;
    this._applianceDetailHistoryLoading = true;
    this._applianceDetailHistoryError = "";
    this._applianceDetailHistorySeries = [];
    this._applianceDetailChartSeries = [];
    this._applianceDetailHistoryParsed = false;
    this._render();

    if (embeddedSeries.length) {
      this._applianceDetailHistorySeries = embeddedSeries;
      this._applianceDetailChartSeries = this._chartSeries(
        embeddedSeries,
        history.entity_series,
      );
      this._applianceDetailHistoryParsed = true;
      this._applianceDetailHistoryLoading = false;
      this._render();
      return;
    }

    const apiPath = this._historyApiPathForEntities(
      entities,
      new Date(start).toISOString(),
      new Date(end).toISOString(),
    );
    const fetchPath = `/api/${apiPath}`;
    try {
      const historyRows = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._applianceDetailHistorySeries = Array.isArray(historyRows) ? historyRows : [];
      this._applianceDetailChartSeries = this._chartSeries(
        this._applianceDetailHistorySeries,
        history.entity_series,
      );
      this._applianceDetailHistoryParsed = true;
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._applianceDetailHistoryError = this._panelTextFormat("errors.load_appliance_history", { path: fetchPath, message: error.message });
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._applianceDetailHistoryLoading = false;
        this._render();
      }
    }
  }

  async _loadApplianceInsights(requestId = this._evidenceRequestId, routeKey = this._loadedRouteKey) {
    if (!this._routeRequestsApplianceInsights(routeKey)) {
      return;
    }
    this._applianceInsightsLoading = true;
    this._applianceInsightsError = "";
    this._render();
    try {
      const payload = await this._requestJson(
        APPLIANCE_INSIGHTS_CALL_API_PATH,
        APPLIANCE_INSIGHTS_API_PATH,
      );
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._applianceInsights = payload;
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._applianceInsights = null;
      this._applianceInsightsError = this._panelTextFormat(
        "errors.load_appliance_insights",
        { message: error.message },
      );
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._applianceInsightsLoading = false;
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
      this._setupHealthError = `${fetchPath}: ${error.message}`;
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._setupHealthLoading = false;
        this._render();
      }
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
    const actionContext = this._actionContext();
    const busyKey = `appliance_detail_${actionKey}`;
    this._busyAction = busyKey;
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
      const message = this._applianceDetailActionMessage(actionKey);
      this._busyAction = "";
      const routeKey = this._routeKey();
      const refresh = this._loadEvidence({ routeKey });
      const refreshRequestId = this._evidenceRequestId;
      await refresh;
      if (!this._isCurrentRequest(refreshRequestId, routeKey)) {
        return;
      }
      this._lastActionMessage = message;
      this._render();
      this._scrollToTop();
    } catch (error) {
      if (!actionContext.isCurrent()) {
        return;
      }
      this._error = this._panelTextFormat("errors.run_service", { service: action.service, message: error.message });
      this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  _routeRequestsApplianceDetail(routeKey = this._routeKey()) {
    const routeUrl = new URL(routeKey, window.location.origin);
    if (routeUrl.searchParams.get(APPLIANCE_DETAIL_QUERY_PARAM) === "1") {
      return true;
    }
    return routeUrl.searchParams.has("assignment_id")
      && routeUrl.searchParams.get(NILM_WORKSPACE_QUERY_PARAM) !== "1";
  }

  _routeRequestsApplianceInsights(routeKey = this._routeKey()) {
    const routeUrl = new URL(routeKey, window.location.origin);
    if (routeUrl.searchParams.get(APPLIANCE_INSIGHTS_QUERY_PARAM) === "1") {
      return true;
    }
    return routeUrl.pathname.endsWith(`/${PANEL_URL_PATH}`)
      && routeUrl.searchParams.size === 0;
  }

  _routeRequestsSetupHealth(routeKey = this._routeKey()) {
    const routeUrl = new URL(routeKey, window.location.origin);
    return routeUrl.searchParams.get(SETUP_HEALTH_QUERY_PARAM) === "1";
  }

  _applianceDetailActionMessage(actionKey) {
    const messages = {
      pause_alerts: "messages.alert_pause_updated",
      relearn_baseline: "messages.baseline_relearn_requested",
      open_advanced_circuit_settings: "messages.opening_advanced_settings",
      open_evidence: "messages.opening_evidence",
      review_nilm_assignment: "messages.opening_nilm_assignment_review",
    };
    return this._panelText(messages[actionKey] || "common.action_complete");
  }

  _renderApplianceInsightsBody() {
    return this._applianceInsightsComponent.render();
  }

  _renderApplianceInsightsContent() {
    if (this._applianceInsightsLoading) {
      return `<section class="panel"><p>${this._escape(this._panelText("appliance_insights.loading"))}</p></section>`;
    }
    if (this._applianceInsightsError) {
      return `<section class="panel error"><p>${this._escape(this._applianceInsightsError)}</p></section>`;
    }
    const items = this._visibleApplianceInsights();
    return `
      <section class="panel appliance-insights-controls">
        <fieldset class="appliance-insights-filters">
          <legend>${this._escape(this._panelText("appliance_insights.filters.heading"))}</legend>
          ${[
            ["running", this._panelText("appliance_insights.filters.running")],
            ["needs_attention", this._panelText("appliance_insights.filters.needs_attention")],
            ["nilm_estimated", this._panelText("appliance_insights.filters.nilm_estimated")],
            ["learning", this._panelText("appliance_insights.filters.learning")],
            ["data_problem", this._panelText("appliance_insights.filters.data_problem")],
          ].map(([key, label]) => `<label><input type="checkbox" data-appliance-insights-filter="${key}" ${this._applianceInsightsFilters[key] ? "checked" : ""}> ${this._escape(label)}</label>`).join("")}
        </fieldset>
        <label class="appliance-insights-sort">
          ${this._escape(this._panelText("appliance_insights.sorts.heading"))}
          <select data-appliance-insights-sort>
            ${[
              ["default", this._panelText("appliance_insights.sorts.default")],
              ["highest_energy", this._panelText("appliance_insights.sorts.highest_energy")],
              ["largest_change", this._panelText("appliance_insights.sorts.largest_change")],
              ["name", this._panelText("appliance_insights.sorts.name")],
            ].map(([value, label]) => `<option value="${value}" ${this._applianceInsightsSort === value ? "selected" : ""}>${this._escape(label)}</option>`).join("")}
          </select>
        </label>
      </section>
      <section class="panel">
        ${items.length ? this._renderApplianceInsightsTable(items) : `<p class="muted">${this._escape(this._panelText("appliance_insights.empty"))}</p>`}
      </section>
    `;
  }

  _visibleApplianceInsights() {
    const payloadItems = this._applianceInsights && this._applianceInsights.items;
    const filters = this._applianceInsightsFilters;
    const items = (Array.isArray(payloadItems) ? payloadItems : []).filter((item) => (
      (!filters.running || item.is_running)
      && (!filters.needs_attention || item.needs_attention)
      && (!filters.nilm_estimated || item.is_nilm)
      && (!filters.learning || item.is_learning)
      && (!filters.data_problem || item.has_data_problem)
    ));
    if (this._applianceInsightsSort === "highest_energy") {
      items.sort((left, right) => this._descendingNullableSortNumber(
        left.daily_energy_kwh,
        right.daily_energy_kwh,
      ));
    } else if (this._applianceInsightsSort === "largest_change") {
      items.sort((left, right) => this._descendingNullableSortNumber(
        left.today_vs_normal_percent === null || left.today_vs_normal_percent === undefined
          ? null
          : Math.abs(left.today_vs_normal_percent),
        right.today_vs_normal_percent === null || right.today_vs_normal_percent === undefined
          ? null
          : Math.abs(right.today_vs_normal_percent),
      ));
    } else if (this._applianceInsightsSort === "name") {
      items.sort((left, right) => String(left.display_name || "").localeCompare(String(right.display_name || "")));
    }
    return items;
  }

  _renderApplianceInsightsTable(items) {
    const columns = {
      appliance: this._panelText("appliance_insights.columns.appliance"),
      now: this._panelText("appliance_insights.columns.now"),
      energy: this._panelText("appliance_insights.columns.energy_today"),
      change: this._panelText("appliance_insights.columns.today_vs_normal"),
      source: this._panelText("appliance_insights.columns.source"),
      readiness: this._panelText("appliance_insights.columns.readiness_confidence"),
      attention: this._panelText("appliance_insights.columns.needs_attention"),
    };
    return `<div class="appliance-insights-table-wrap"><table class="appliance-insights-table">
      <thead><tr>${Object.values(columns).map((label) => `<th scope="col">${this._escape(label)}</th>`).join("")}</tr></thead>
      <tbody>${items.map((item) => {
        const quality = item.source_quality || {};
        const readiness = item.learning_readiness || {};
        const confidence = item.confidence !== null && item.confidence !== undefined
          ? this._formatConfidence(item.confidence)
          : "";
        return `<tr>
          <td data-label="${this._escape(columns.appliance)}"><a href="${this._escape(item.detail_path)}" data-appliance-insights-detail-path="${this._escape(item.detail_path)}">${this._escape(item.display_name || item.appliance_key)}</a></td>
          <td data-label="${this._escape(columns.now)}">${this._escape(item.activity_state || this._panelText("common.unknown"))}${item.current_power_w !== null && item.current_power_w !== undefined ? `<small>${this._escape(this._formatPower(item.current_power_w))}</small>` : ""}</td>
          <td data-label="${this._escape(columns.energy)}">${this._escape(this._formatKwh(item.daily_energy_kwh))}</td>
          <td data-label="${this._escape(columns.change)}">${this._escape(this._formatChangePercent(item.today_vs_normal_percent))}${item.energy_change_explanation ? `<small>${this._escape(item.energy_change_explanation.explanation)}</small>` : ""}</td>
          <td data-label="${this._escape(columns.source)}"><a href="${this._escape(item.source_path)}" data-appliance-insights-source-path="${this._escape(item.source_path)}">${this._escape(this._sourceLabel(item.source_type))}</a><small>${this._escape(quality.label || this._friendlyFeature(quality.status || "unknown"))}</small></td>
          <td data-label="${this._escape(columns.readiness)}">${this._escape(readiness.label || this._friendlyFeature(readiness.status || "unknown"))}${confidence ? `<small>${this._escape(this._panelTextFormat("appliance_insights.confidence", { confidence }))}</small>` : ""}</td>
          <td data-label="${this._escape(columns.attention)}">${this._escape(this._panelText(item.needs_attention ? "appliance_insights.yes" : "appliance_insights.no"))}</td>
        </tr>`;
      }).join("")}</tbody>
    </table></div>`;
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
      return `<section class="panel"><h2>${this._escape(this._setupHealthText("heading"))}</h2><p class="muted">${this._escape(this._setupHealthText("loading"))}</p></section>`;
    }
    if (this._setupHealthError) {
      return `<section class="panel error"><h2>${this._escape(this._setupHealthText("heading"))}</h2><p>${this._escape(this._setupHealthError)}</p></section>`;
    }
    const payload = this._setupHealth || {};
    if (payload.status && payload.status !== "ok") {
      return `
        <section class="panel">
          <h2>${this._escape(this._setupHealthText("heading"))}</h2>
          <p>${this._escape(payload.message || this._setupHealthText("unavailable.message"))}</p>
          <p class="muted">${this._escape(payload.next_step || this._setupHealthText("unavailable.next_step"))}</p>
        </section>
      `;
    }
    return `
      <section class="panel">
        <h2>${this._escape(this._setupHealthText("checklist_heading"))}</h2>
        ${this._renderSetupHealthChecklist(payload.checklist, payload.issues)}
      </section>
      <section class="panel" data-needs-attention>
        <h2>${this._escape(this._panelText("headers.needs_attention"))}</h2>
        ${this._renderNeedsAttention(payload.needs_attention)}
      </section>
      ${this._renderWeeklyDigest(payload.weekly_digest, payload.weekly_digest_settings)}
    `;
  }

  _renderWeeklyDigest(digest, settings = {}) {
    const report = digest || {};
    const sections = [
      ["biggest_changes", "weekly_digest.biggest_changes"],
      ["top_energy_users", "weekly_digest.top_energy_users"],
      ["unresolved_items", "weekly_digest.unresolved_items"],
      ["nilm_review_items", "weekly_digest.nilm_review_items"],
      ["load_shift_opportunities", "weekly_digest.load_shift_opportunities"],
    ];
    return `<section class="panel" data-weekly-digest>
      <h2>${this._escape(this._panelText("weekly_digest.heading"))}</h2>
      <div class="entity-list">
        <label><input type="checkbox" data-weekly-digest-enabled ${settings.enabled ? "checked" : ""}> ${this._escape(this._panelText("weekly_digest.enabled"))}</label>
        <label>${this._escape(this._panelText("weekly_digest.delivery"))}
          <select data-weekly-digest-delivery>
            ${["panel_only", "persistent_notification", "mobile_notification"].map((mode) => `<option value="${mode}" ${settings.delivery === mode ? "selected" : ""}>${this._escape(this._panelText(`weekly_digest.delivery_modes.${mode}`))}</option>`).join("")}
          </select>
        </label>
        <label>${this._escape(this._panelText("weekly_digest.notify_service"))}<input type="text" value="${this._escape(settings.notify_service || "")}" data-weekly-digest-notify-service></label>
      </div>
      <div class="actions"><button type="button" data-save-weekly-digest>${this._escape(this._panelText("actions.labels.save"))}</button></div>
      ${report.week_start ? `<p class="muted">${this._escape(this._panelTextFormat("weekly_digest.period", { start: report.week_start, end: report.week_end }))}</p>` : `<p class="muted">${this._escape(this._panelText("weekly_digest.no_report"))}</p>`}
      ${sections.map(([key, label]) => {
        const items = Array.isArray(report[key]) ? report[key] : [];
        return items.length ? `<h3>${this._escape(this._panelText(label))}</h3>${this._renderSimpleList(items.map((item) => `${item.display_name}: ${this._formatKwh(item.energy_kwh)}`), "")}` : "";
      }).join("")}
    </section>`;
  }

  async _saveWeeklyDigestSettings() {
    const panel = this.shadowRoot.querySelector("[data-weekly-digest]");
    if (!panel) {
      return;
    }
    const route = new URL(this._loadedRouteKey || this._routeKey(), window.location.origin);
    const entryId = route.searchParams.get("entry_id") || "";
    const query = entryId ? `?${new URLSearchParams({ entry_id: entryId })}` : "";
    const body = {
      enabled: panel.querySelector("[data-weekly-digest-enabled]").checked,
      delivery: panel.querySelector("[data-weekly-digest-delivery]").value,
      notify_service: panel.querySelector("[data-weekly-digest-notify-service]").value,
    };
    try {
      const result = await this._postJson(`${SETUP_HEALTH_CALL_API_PATH}${query}`, `${SETUP_HEALTH_API_PATH}${query}`, body);
      if (result && result.weekly_digest_settings) {
        this._setupHealth.weekly_digest_settings = result.weekly_digest_settings;
      }
      this._lastActionMessage = this._panelText("messages.weekly_digest_settings_saved");
    } catch (error) {
      this._lastActionMessage = this._panelTextFormat("errors.weekly_digest_settings_save", { message: error.message });
    }
    this._render();
  }

  _renderNeedsAttention(items) {
    const safeItems = Array.isArray(items) ? items : [];
    if (!safeItems.length) {
      return `<p class="muted">${this._escape(this._panelText("attention.none"))}</p>`;
    }
    const labels = {
      fix_setup_or_data: this._panelText("attention.fix_setup_or_data"),
      review_appliance_behavior: this._panelText("attention.review_appliance_behavior"),
      validate_nilm: this._panelText("attention.validate_nilm"),
    };
    return `<div class="entity-list">${safeItems.map((item) => `
      <div class="metric" data-attention-item="${this._escape(item.item_id || "")}">
        <span>${this._escape(labels[item.category] || this._friendlyFeature(item.category))}</span>
        <strong>${this._escape(item.display_name || item.appliance_key)}</strong>
        <p>${this._escape(item.reason || "")}</p>
        <p class="muted">${this._escape(item.next_step || "")}</p>
        ${item.action_path ? `<a class="button secondary" href="${this._escape(item.action_path)}">${this._escape(this._panelText("attention.open_detail"))}</a>` : ""}
      </div>
    `).join("")}</div>`;
  }

  _renderSetupHealthChecklist(items, issues) {
    const safeItems = Array.isArray(items) ? items : [];
    const rows = [
      ...this._renderSetupHealthIssueItems(issues),
      ...safeItems.map((item) => this._renderSetupHealthChecklistItem(item)),
    ];
    if (!rows.length) {
      return `<p class="muted">${this._escape(this._setupHealthText("empty_checklist"))}</p>`;
    }
    return `<div class="entity-list">${rows.join("")}</div>`;
  }

  _renderSetupHealthChecklistItem(item) {
    const affected = Array.isArray(item.affected_circuits) ? item.affected_circuits : [];
    const path = item.open_path || "";
    const description = item.why_it_matters || this._setupHealthChecklistText(item.item_id, "why_it_matters") || this._setupHealthText("fallbacks.review_item_reason");
    const title = item.title || this._setupHealthChecklistText(item.item_id, "title") || this._friendlyFeature(item.item_id || this._setupHealthText("fallbacks.setup_item"));
    const affectedLabel = this._setupHealthText("labels.affected");
    return `
      <div class="metric">
        <span>${this._escape(this._friendlyFeature(item.status || "unknown"))}</span>
        <strong>${this._escape(title)}</strong>
        <p>${this._escape(description)}</p>
        ${affected.length ? `<p class="muted">${this._escape(affectedLabel)}: ${this._escape(affected.join(", "))}</p>` : ""}
        ${item.fix ? this._setupHealthAction(path, item.fix) : ""}
      </div>
    `;
  }

  _renderSetupHealthIssueItems(issues) {
    const safeIssues = Array.isArray(issues) ? issues : [];
    return safeIssues.map((item) => `
      <div class="metric">
        <span>${this._escape(this._friendlyFeature(item.severity || item.state || "review"))}</span>
        <strong>${this._escape(item.fix || item.recommended_action || item.state || this._setupHealthText("fallbacks.review_setup"))}</strong>
        <p>${this._escape(item.reason || this._setupHealthText("fallbacks.review_item_reason"))}</p>
        ${item.affected_circuit_name || item.affected_circuit ? `<p class="muted">${this._escape(this._setupHealthText("labels.circuit"))}: ${this._escape(item.affected_circuit_name || item.affected_circuit)}</p>` : ""}
        ${this._setupHealthAction(item.open_path, item.fix || item.recommended_action)}
      </div>
    `);
  }

  _setupHealthAction(path, fallbackText) {
    if (!path) {
      return fallbackText ? `<p class="muted">${this._escape(fallbackText)}</p>` : "";
    }
    return `<div class="actions setup-health-actions"><a class="button secondary" data-setup-health-path href="${this._escape(path)}">${this._escape(this._setupHealthText("open_setting"))}</a></div>`;
  }

  _setupHealthChecklistText(itemId, key) {
    const checklist = this._setupHealthTextObject().checklist || {};
    const item = checklist[itemId] || {};
    return typeof item[key] === "string" ? item[key] : "";
  }

  _setupHealthText(path) {
    const parts = path.split(".");
    let value = this._setupHealthTextObject();
    for (const part of parts) {
      if (!value || typeof value !== "object") {
        return "";
      }
      value = value[part];
    }
    return typeof value === "string" ? value : "";
  }

  _setupHealthTextObject() {
    const text = this._setupHealth && this._setupHealth.text;
    if (text && (text.heading || text.checklist)) {
      return text;
    }
    return this._panelTextObject().setup_health || {};
  }

  _renderApplianceDetail() {
    return this._applianceDetailComponent.render();
  }

  _renderApplianceDetailContent() {
    if (this._applianceDetailLoading) {
      return `<section class="panel"><p>${this._escape(this._panelText("appliance_detail.loading"))}</p></section>`;
    }
    if (this._applianceDetailError) {
      return `<section class="panel error"><p>${this._escape(this._applianceDetailError)}</p></section>`;
    }
    const payload = this._applianceDetail || {};
    const detail = payload.detail;
    if (!detail) {
      return `
        <section class="panel">
          <h2>${this._escape(this._panelText("headers.appliance_detail"))}</h2>
          <p>${this._escape(payload.message || this._panelText("appliance_detail.fallback_message"))}</p>
          <p class="muted">${this._escape(payload.next_step || this._panelText("appliance_detail.fallback_next_step"))}</p>
        </section>
      `;
    }
    return `
      ${this._renderApplianceDetailHistory(payload.history)}
      <section class="panel summary">
        ${this._metric(this._panelText("appliance_detail.activity"), detail.activity_state, "mdi:play-circle-outline")}
        ${this._metric(this._panelText("appliance_detail.power"), this._formatPower(detail.current_power_w), "mdi:flash-outline")}
        ${this._metric(this._panelText("common.source"), this._sourceLabel(detail.source_type), "mdi:transmission-tower")}
        ${detail.source_type === "nilm_estimate" && (detail.mains_source || detail.mains_circuit_id) ? this._metric(this._panelText("appliance_detail.mains_source"), detail.mains_source || detail.mains_circuit_id, "mdi:home-lightning-bolt-outline") : ""}
        ${detail.source_quality ? this._metric(this._panelText("appliance_detail.data_quality"), detail.source_quality.label || this._friendlyFeature(detail.source_quality.status), "mdi:database-check-outline") : ""}
        ${detail.learning_readiness ? this._metric(this._panelText("appliance_detail.learning_readiness"), detail.learning_readiness.label || this._friendlyFeature(detail.learning_readiness.status), "mdi:school-outline") : ""}
        ${detail.confidence !== null && detail.confidence !== undefined ? this._metric(this._panelText("common.confidence"), this._formatConfidence(detail.confidence), "mdi:chart-bell-curve-cumulative") : ""}
      </section>
      <section class="panel summary">
        ${this._metric(this._panelText("appliance_detail.health"), detail.health_state, "mdi:heart-pulse")}
        ${this._metric(this._panelText("appliance_detail.electrical"), detail.electrical_state, "mdi:lightning-bolt")}
        ${this._metric(this._panelText("appliance_detail.energy"), detail.energy_state, "mdi:chart-line")}
        ${this._metric(this._panelText("appliance_detail.model"), detail.model_status || this._sourceLabel("direct_meter"), "mdi:cpu-64-bit")}
      </section>
      <section class="panel summary">
        ${this._metric(this._panelText("appliance_detail.energy_today"), this._formatKwh(detail.daily_energy_kwh), "mdi:calendar-today")}
        ${this._metric(this._panelText("appliance_detail.runtime_today"), this._formatDuration(detail.runtime_today_seconds), "mdi:timer-outline")}
        ${this._metric(this._panelText("appliance_detail.runs_today"), detail.run_count_today, "mdi:counter")}
        ${this._metric(this._panelText("appliance_detail.cost_today"), this._formatCost(detail.cost_today), "mdi:cash")}
      </section>
      <section class="panel">
        <h2>${this._escape(this._panelText("appliance_detail.session_timeline"))}</h2>
        ${this._renderSessionTimeline(detail.session_timeline)}
      </section>
      <section class="panel">
        <h2>${this._escape(this._panelText("appliance_detail.recent_timeline"))}</h2>
        ${this._renderApplianceTimeline(detail.recent_timeline)}
      </section>
      <section class="panel">
        <h2>${this._escape(this._panelText("appliance_detail.today_vs_normal"))}</h2>
        ${this._renderApplianceComparisons(detail.today_vs_normal)}
      </section>
      ${this._renderWhyEnergyChanged(detail.energy_change_explanation)}
      <section class="panel">
        <h2>${this._escape(this._panelText("appliance_detail.behavior_expectations"))}</h2>
        ${this._renderApplianceExpectations(detail.expectations)}
      </section>
      <section class="panel">
        <h2>${this._escape(this._panelText("appliance_detail.what_to_check_first"))}</h2>
        ${this._renderSimpleList(detail.what_to_check_first, detail.next_step || this._panelText("appliance_detail.no_immediate_check"))}
      </section>
      <section class="panel">
        <h2>${this._escape(this._panelText("appliance_detail.alerts_and_evidence"))}</h2>
        ${this._renderApplianceAlerts(detail.active_alerts)}
      </section>
      ${this._renderApplianceNotificationPreferences(payload.notification_preferences)}
      ${this._renderExpectedSchedule(payload.expected_schedule)}
      <section class="panel">
        <h2>${this._escape(this._panelText("appliance_detail.actions"))}</h2>
        ${this._renderApplianceActions(payload.actions)}
      </section>
    `;
  }

  _renderWhyEnergyChanged(energy_change_explanation) {
    const heading = this._panelText("appliance_detail.why_energy_changed");
    if (!energy_change_explanation) {
      return `<section class="panel"><h2>${this._escape(heading)}</h2><p class="muted">${this._escape(this._panelText("appliance_detail.energy_change_insufficient"))}</p></section>`;
    }
    const contributions = [
      ["runtime", energy_change_explanation.runtime_contribution_percent],
      ["running_power", energy_change_explanation.running_power_contribution_percent],
      ["cycle_count", energy_change_explanation.cycle_count_contribution_percent],
      ["unexplained", energy_change_explanation.unexplained_percent],
    ].filter(([, value]) => value !== null && value !== undefined && Math.abs(Number(value)) >= 0.05);
    return `<section class="panel" data-energy-change-explanation>
      <h2>${this._escape(heading)}</h2>
      <p>${this._escape(energy_change_explanation.explanation || "")}</p>
      ${contributions.length ? `<ul class="energy-change-list">${contributions.map(([key, value]) => `<li>${this._escape(this._panelTextFormat("appliance_detail.energy_change_contribution", {
        factor: this._panelText(`appliance_detail.energy_change_factors.${key}`),
        percent: this._formatChangePercent(value),
      }))}</li>`).join("")}</ul>` : ""}
    </section>`;
  }

  _renderApplianceNotificationPreferences(preferences) {
    if (!preferences) {
      return "";
    }
    const categories = [
      "finished_running",
      "unusual_runtime",
      "high_daily_energy",
      "electrical_issue",
      "capacity_demand_issue",
      "data_quality_issue",
      "nilm_review_needed",
    ];
    const deliveryModes = ["immediate", "daily_summary", "weekly_digest", "disabled"];
    return `<section class="panel" data-appliance-notifications>
      <h2>${this._escape(this._panelText("appliance_detail.notifications"))}</h2>
      <div class="entity-list">
        ${categories.map((category) => `<label><input type="checkbox" data-notification-category="${category}" ${preferences[category] ? "checked" : ""}> ${this._escape(this._panelText(`notifications.categories.${category}`))}</label>`).join("")}
        <label>${this._escape(this._panelText("notifications.delivery_mode"))}
          <select data-notification-delivery-mode>${deliveryModes.map((mode) => `<option value="${mode}" ${preferences.delivery_mode === mode ? "selected" : ""}>${this._escape(this._panelText(`notifications.delivery_modes.${mode}`))}</option>`).join("")}</select>
        </label>
        <label>${this._escape(this._panelText("notifications.minimum_confidence"))}<input type="number" min="0" max="1" step="0.05" value="${this._escape(preferences.minimum_confidence)}" data-notification-minimum-confidence></label>
        <label>${this._escape(this._panelText("notifications.cooldown_minutes"))}<input type="number" min="0" max="10080" step="5" value="${this._escape(preferences.cooldown_minutes)}" data-notification-cooldown></label>
        <label>${this._escape(this._panelText("notifications.quiet_hours_start"))}<input type="time" value="${this._escape(preferences.quiet_hours_start || "")}" data-notification-quiet-start></label>
        <label>${this._escape(this._panelText("notifications.quiet_hours_end"))}<input type="time" value="${this._escape(preferences.quiet_hours_end || "")}" data-notification-quiet-end></label>
      </div>
      <div class="actions"><button type="button" data-save-appliance-notifications>${this._escape(this._panelText("actions.labels.save"))}</button></div>
    </section>`;
  }

  async _saveApplianceNotificationPreferences() {
    const panel = this.shadowRoot.querySelector("[data-appliance-notifications]");
    if (!panel) {
      return;
    }
    const body = {};
    for (const input of panel.querySelectorAll("[data-notification-category]")) {
      body[input.dataset.notificationCategory] = input.checked;
    }
    body.delivery_mode = panel.querySelector("[data-notification-delivery-mode]").value;
    body.minimum_confidence = Number(panel.querySelector("[data-notification-minimum-confidence]").value);
    body.cooldown_minutes = Number(panel.querySelector("[data-notification-cooldown]").value);
    body.quiet_hours_start = panel.querySelector("[data-notification-quiet-start]").value || null;
    body.quiet_hours_end = panel.querySelector("[data-notification-quiet-end]").value || null;
    const route = new URL(this._loadedRouteKey || this._routeKey(), window.location.origin);
    const params = new URLSearchParams();
    for (const key of ["circuit_id", "assignment_id", "entry_id"]) {
      if (route.searchParams.get(key)) {
        params.set(key, route.searchParams.get(key));
      }
    }
    const query = params.toString();
    const apiPath = `${APPLIANCE_DETAIL_CALL_API_PATH}${query ? `?${query}` : ""}`;
    const fetchPath = `${APPLIANCE_DETAIL_API_PATH}${query ? `?${query}` : ""}`;
    try {
      const result = await this._postJson(apiPath, fetchPath, body);
      if (result && result.notification_preferences) {
        this._applianceDetail.notification_preferences = result.notification_preferences;
      }
      this._lastActionMessage = this._panelText("messages.notification_preferences_saved");
    } catch (error) {
      this._lastActionMessage = this._panelTextFormat("errors.notification_preferences_save", { message: error.message });
    }
    this._render();
  }

  _scheduleDraftFromPayload(expectedSchedule) {
    const settings = expectedSchedule && expectedSchedule.settings;
    if (!settings) {
      return null;
    }
    return {
      enabled: Boolean(settings.enabled),
      mode: settings.schedule_entity_id ? "entity" : "local",
      schedule_entity_id: settings.schedule_entity_id || null,
      windows: Array.isArray(settings.windows)
        ? settings.windows.map((window) => ({
          start: window.start || "08:00",
          end: window.end || "10:00",
          weekdays: Array.isArray(window.weekdays) ? window.weekdays.map(Number) : [],
        }))
        : [],
      minimum_duration_minutes: Number(settings.minimum_duration_minutes) || 15,
      required_repeats: Number(settings.required_repeats) || 3,
    };
  }

  _renderExpectedSchedule(expectedSchedule) {
    if (!expectedSchedule) {
      return "";
    }
    const draft = this._expectedScheduleDraft
      || this._scheduleDraftFromPayload(expectedSchedule)
      || { enabled: false, schedule_entity_id: null, windows: [], minimum_duration_minutes: 15, required_repeats: 3 };
    const mode = draft.mode || (draft.schedule_entity_id ? "entity" : "local");
    const entities = Array.isArray(expectedSchedule.schedule_entities)
      ? expectedSchedule.schedule_entities
      : [];
    const windows = draft.windows.length
      ? draft.windows
      : [{ start: "08:00", end: "10:00", weekdays: [0, 1, 2, 3, 4] }];
    const dayLabels = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
    const context = expectedSchedule.context;
    return `<section class="panel" data-expected-schedule>
      <h2>${this._escape(this._panelText("expected_schedule.heading"))}</h2>
      ${context ? `<p><strong>${this._escape(this._friendlyFeature(context.status))}</strong> ${this._escape(context.message || "")}</p>` : ""}
      <div class="entity-list">
        <label><input type="checkbox" data-schedule-enabled ${draft.enabled ? "checked" : ""}> ${this._escape(this._panelText("expected_schedule.enabled"))}</label>
        <fieldset class="schedule-mode" aria-label="${this._escape(this._panelText("expected_schedule.mode"))}">
          <label><input type="radio" name="expected-schedule-mode" value="entity" data-schedule-mode ${mode === "entity" ? "checked" : ""}> ${this._escape(this._panelText("expected_schedule.schedule_entity"))}</label>
          <label><input type="radio" name="expected-schedule-mode" value="local" data-schedule-mode ${mode === "local" ? "checked" : ""}> ${this._escape(this._panelText("expected_schedule.local_windows"))}</label>
        </fieldset>
        ${mode === "entity" ? `<label>${this._escape(this._panelText("expected_schedule.schedule_entity"))}
          <select data-schedule-entity>
            <option value="">${this._escape(this._panelText("expected_schedule.select_schedule"))}</option>
            ${entities.map((item) => `<option value="${this._escape(String(item.entity_id || ""))}" ${draft.schedule_entity_id === item.entity_id ? "selected" : ""}>${this._escape(item.name || this._friendlyEntityName(item))}</option>`).join("")}
          </select>
        </label>` : `<div class="schedule-windows">
          ${windows.map((window, index) => `<div class="schedule-window" data-schedule-window>
            <label>${this._escape(this._panelText("expected_schedule.start"))}<input type="time" value="${this._escape(window.start)}" data-schedule-window-start></label>
            <label>${this._escape(this._panelText("expected_schedule.end"))}<input type="time" value="${this._escape(window.end)}" data-schedule-window-end></label>
            <div class="schedule-weekdays" aria-label="${this._escape(this._panelText("expected_schedule.weekdays"))}">
              ${dayLabels.map((day, dayIndex) => `<label><input type="checkbox" value="${dayIndex}" data-schedule-weekday ${window.weekdays.includes(dayIndex) ? "checked" : ""}> ${this._escape(this._panelText(`expected_schedule.days.${day}`))}</label>`).join("")}
            </div>
            <button type="button" class="secondary icon-button" data-remove-schedule-window="${index}" title="${this._escape(this._panelText("expected_schedule.remove_window"))}" aria-label="${this._escape(this._panelText("expected_schedule.remove_window"))}"><ha-icon icon="mdi:trash-can-outline"></ha-icon></button>
          </div>`).join("")}
          <button type="button" class="secondary" data-add-schedule-window><ha-icon icon="mdi:plus"></ha-icon>${this._escape(this._panelText("expected_schedule.add_window"))}</button>
        </div>`}
        <label>${this._escape(this._panelText("expected_schedule.minimum_duration"))}<input type="number" min="1" max="1440" step="1" value="${this._escape(draft.minimum_duration_minutes)}" data-schedule-minimum-duration></label>
      </div>
      <div class="actions"><button type="button" data-save-expected-schedule>${this._escape(this._panelText("actions.labels.save"))}</button></div>
    </section>`;
  }

  _readExpectedScheduleForm() {
    const panel = this.shadowRoot.querySelector("[data-expected-schedule]");
    const current = this._expectedScheduleDraft || { required_repeats: 3 };
    if (!panel) {
      return current;
    }
    const mode = panel.querySelector("[data-schedule-mode]:checked")?.value || "local";
    const windows = Array.from(panel.querySelectorAll("[data-schedule-window]")).map((row) => ({
      start: row.querySelector("[data-schedule-window-start]").value,
      end: row.querySelector("[data-schedule-window-end]").value,
      weekdays: Array.from(row.querySelectorAll("[data-schedule-weekday]:checked")).map((input) => Number(input.value)),
    }));
    return {
      enabled: panel.querySelector("[data-schedule-enabled]").checked,
      mode,
      schedule_entity_id: mode === "entity" ? panel.querySelector("[data-schedule-entity]")?.value || null : null,
      windows,
      minimum_duration_minutes: Number(panel.querySelector("[data-schedule-minimum-duration]").value) || 15,
      required_repeats: Number(current.required_repeats) || 3,
    };
  }

  async _saveExpectedSchedule() {
    const body = this._readExpectedScheduleForm();
    const route = new URL(this._loadedRouteKey || this._routeKey(), window.location.origin);
    const params = new URLSearchParams();
    for (const key of ["circuit_id", "assignment_id", "entry_id"]) {
      if (route.searchParams.get(key)) {
        params.set(key, route.searchParams.get(key));
      }
    }
    const query = params.toString();
    const apiPath = `${APPLIANCE_DETAIL_CALL_API_PATH}${query ? `?${query}` : ""}`;
    const fetchPath = `${APPLIANCE_DETAIL_API_PATH}${query ? `?${query}` : ""}`;
    try {
      const result = await this._postJson(apiPath, fetchPath, { expected_schedule: body });
      if (result && result.expected_schedule_settings) {
        this._applianceDetail.expected_schedule.settings = result.expected_schedule_settings;
        this._expectedScheduleDraft = this._scheduleDraftFromPayload(this._applianceDetail.expected_schedule);
      }
      this._lastActionMessage = this._panelText("messages.expected_schedule_saved");
    } catch (error) {
      this._lastActionMessage = this._panelTextFormat("errors.expected_schedule_save", { message: error.message });
    }
    this._render();
  }

  _renderApplianceDetailHistory(history) {
    const entities = Array.isArray(history && history.entities) ? history.entities : [];
    if (!entities.length) {
      return "";
    }
    const periodHours = Array.isArray(history.period_hours) ? history.period_hours.map(Number).filter(Number.isFinite) : [];
    const window = this._applianceDetailHistoryGraphWindow();
    const parsedSeries = this._applianceDetailHistoryParsed
      ? this._applianceDetailChartSeries
      : this._chartSeries(this._applianceDetailHistorySeries, history.entity_series);
    const series = window ? this._visibleParsedChartSeries(parsedSeries, window) : [];
    const groupedSeries = this._chartSeriesByUnit(series);
    const chartOptions = {
      graph_window_start: window ? new Date(window.start).toISOString() : "",
      graph_window_end: window ? new Date(window.end).toISOString() : "",
    };
    const graph = this._applianceDetailHistoryLoading
      ? `<div class="loading-skeleton graph-loading-skeleton" data-loading-skeleton role="status" aria-label="${this._escape(this._panelText("chart.loading_history"))}"></div>`
      : this._applianceDetailHistoryError
        ? `<div data-appliance-history-error><p class="muted">${this._escape(this._applianceDetailHistoryError)}</p><button type="button" class="secondary" data-retry-appliance-history>${this._escape(this._panelText("common.retry"))}</button></div>`
        : window && groupedSeries.length
          ? groupedSeries.map(({ unit, series: unitSeries }) => this._chartSvg(
            unitSeries,
            Object.assign({}, chartOptions, { y_axis_label: unit }),
          )).join("")
          : `<p class="muted">${this._escape(this._panelText("appliance_detail.no_history"))}</p>`;
    return `
      <section class="panel" data-appliance-detail-history>
        <div class="actions">
          <label>${this._escape(this._panelText("appliance_detail.time_period"))}
            <select data-appliance-history-period>
              ${periodHours.map((hours) => `<option value="${hours}" ${hours === this._applianceDetailHistoryHours ? "selected" : ""}>${this._escape(this._applianceHistoryPeriodLabel(hours))}</option>`).join("")}
            </select>
          </label>
        </div>
        ${this._renderApplianceHistoryGraphControls(window)}
        <h2>${this._escape(this._panelText("appliance_detail.energy_history"))}</h2>
        ${graph}
      </section>
    `;
  }

  _applianceHistoryPeriodLabel(hours) {
    const labels = {
      24: "appliance_detail.history_24_hours",
      168: "appliance_detail.history_7_days",
      720: "appliance_detail.history_30_days",
    };
    return this._panelText(labels[hours] || "appliance_detail.history_7_days");
  }

  _renderApplianceTimeline(timeline) {
    const items = Array.isArray(timeline && timeline.items) ? timeline.items : [];
    if (!items.length) {
      const title = timeline && timeline.latest_title ? timeline.latest_title : this._panelText("appliance_detail.no_recent_activity");
      return `<p class="muted">${this._escape(title)}</p>`;
    }
    return `<ol class="appliance-timeline">${items.map((item) => `
      <li class="appliance-timeline-item">
        <time>${this._escape(this._formatDateTime(item.timestamp))}</time>
        <strong>${this._escape(item.title || this._friendlyFeature(item.kind || this._panelText("appliance_detail.activity")))}</strong>
        ${item.detail ? `<p class="muted">${this._escape(item.detail)}</p>` : ""}
      </li>
    `).join("")}</ol>`;
  }

  _renderApplianceComparisons(comparisons) {
    const items = Array.isArray(comparisons) ? comparisons : [];
    if (!items.length) {
      return `<p class="muted">${this._escape(this._panelText("appliance_detail.learning_ranges"))}</p>`;
    }
    return `<div class="appliance-comparison-grid">${items.map((item) => {
      const normal = item.normal_low !== null && item.normal_low !== undefined && item.normal_high !== null && item.normal_high !== undefined
        ? `${this._formatComparisonValue(item, item.normal_low)} - ${this._formatComparisonValue(item, item.normal_high)}`
        : this._panelText("common.learning");
      const hasProjection = item.projection_value !== null && item.projection_value !== undefined;
      const projectedStatus = hasProjection && item.full_period_normal_high !== null && item.full_period_normal_high !== undefined && item.projection_value > item.full_period_normal_high
        ? "higher"
        : hasProjection && item.full_period_normal_low !== null && item.full_period_normal_low !== undefined && item.projection_value < item.full_period_normal_low
          ? "lower"
          : "normal";
      const fullPeriod = item.full_period_normal_low !== null && item.full_period_normal_low !== undefined && item.full_period_normal_high !== null && item.full_period_normal_high !== undefined
        ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.completed_day_normal_range", { low: this._formatComparisonValue(item, item.full_period_normal_low), high: this._formatComparisonValue(item, item.full_period_normal_high) }))}</p>`
        : "";
      const configuredWarning = item.configured_warning_value !== null && item.configured_warning_value !== undefined
        ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.configured_warning", { value: this._formatComparisonValue({ unit: item.limit_unit || item.unit }, item.configured_warning_value) }))}</p>`
        : "";
      const configuredLimit = item.configured_limit_value !== null && item.configured_limit_value !== undefined
        ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.configured_limit", { value: this._formatComparisonValue({ unit: item.limit_unit || item.unit }, item.configured_limit_value) }))}</p>`
        : "";
      const asOf = item.as_of
        ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.as_of", { timestamp: this._formatDateTime(item.as_of) }))}</p>`
        : "";
      const projection = hasProjection
        ? `<p><strong>${this._escape(this._panelText("appliance_detail.projected_end_of_day"))}</strong> ${this._escape(this._formatComparisonValue(item, item.projection_value))}</p>
          ${item.projection_low !== null && item.projection_low !== undefined && item.projection_high !== null && item.projection_high !== undefined ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.projected_range", { low: this._formatComparisonValue(item, item.projection_low), high: this._formatComparisonValue(item, item.projection_high) }))}</p>` : ""}
          <p class="muted">${this._escape(this._panelTextFormat("appliance_detail.projected_status", { status: this._friendlyFeature(projectedStatus) }))}</p>
          ${item.projection_confidence !== null && item.projection_confidence !== undefined ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.projection_confidence", { confidence: this._formatConfidence(item.projection_confidence) }))}</p>` : ""}`
        : "";
      return `
        <div class="appliance-comparison">
          <span class="comparison-label">${this._escape(item.label || this._friendlyFeature(item.metric_id))}</span>
          <strong>${this._escape(this._formatComparisonValue(item, item.current_value))}</strong>
          <p class="comparison-summary">${this._escape(this._panelTextFormat("appliance_detail.comparison_summary", { normal, status: this._friendlyFeature(item.status) }))}</p>
          ${fullPeriod}
          ${configuredWarning}
          ${configuredLimit}
          ${asOf}
          ${projection}
          ${item.confidence !== null && item.confidence !== undefined ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.confidence_value", { confidence: this._formatConfidence(item.confidence) }))}</p>` : ""}
          ${item.source ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.source_value", { source: this._friendlyFeature(item.source) }))}</p>` : ""}
        </div>
      `;
    }).join("")}</div>`;
  }

  _renderApplianceExpectations(expectations) {
    const items = Array.isArray(expectations) ? expectations : [];
    if (!items.length) {
      return `<p class="muted">${this._escape(this._panelText("appliance_detail.not_enough_expectations"))}</p>`;
    }
    return `<div class="entity-list">${items.map((item) => `
      <div class="metric">
        <span>${this._escape(this._friendlyFeature(item.status))}</span>
        <strong>${this._escape(item.title || this._panelText("appliance_detail.expectation_title"))}</strong>
        <p>${this._escape(item.observed || this._panelText("appliance_detail.observed_learning"))}</p>
        <p class="muted">${this._escape(this._panelTextFormat("appliance_detail.expected_prefix", { expected: item.expected || this._panelText("appliance_detail.expected_learning") }))}</p>
        <p class="muted">${this._escape(item.why_it_matters || "")}</p>
        ${this._renderSimpleList(item.what_to_check_first, "")}
      </div>
    `).join("")}</div>`;
  }

  _renderApplianceAlerts(alerts) {
    const items = Array.isArray(alerts) ? alerts : [];
    if (!items.length) {
      return `<p class="muted">${this._escape(this._panelText("appliance_detail.no_active_alerts"))}</p>`;
    }
    return `<div class="entity-list">${items.map((item) => `
      <div class="metric">
        <span>${this._escape(this._friendlyFeature(item.severity || item.feature))}</span>
        <strong>${this._escape(item.message || this._friendlyFeature(item.feature))}</strong>
        <p class="muted">${this._escape(this._panelTextFormat("appliance_detail.repeated_count", { count: this._formatMetricValue(item.repeated_count) }))}</p>
        ${item.evidence_path ? `<a class="button secondary" href="${this._escape(item.evidence_path)}">${this._escape(this._panelText("actions.labels.open_evidence"))}</a>` : ""}
      </div>
    `).join("")}</div>`;
  }

  _renderApplianceActions(actions) {
    const available = actions || {};
    const alertButtons = [
      this._applianceAlertActionTile(available, "open_evidence", this._panelText("actions.labels.open_evidence"), "mdi:chart-line"),
      this._applianceAlertActionTile(available, "mark_correct", this._panelText("actions.labels.correct"), "mdi:check-circle-outline"),
      this._applianceAlertActionTile(available, "mark_wrong", this._panelText("actions.labels.wrong_appliance_sentence"), "mdi:close-circle-outline"),
      this._applianceAlertActionTile(available, "mark_expected", this._panelText("actions.labels.mark_expected"), "mdi:check-decagram", this._panelText("actions.helpers.mark_expected")),
      this._applianceAlertActionTile(available, "mark_unhelpful", this._panelText("actions.labels.not_helpful"), "mdi:message-alert-outline", this._panelText("actions.helpers.mark_unhelpful")),
    ].filter(Boolean);
    const buttons = [
      this._applianceActionButton(available, "adjust_interval", this._panelText("actions.labels.adjust_interval"), true),
      this._applianceActionButton(available, "review_nilm_assignment", this._panelText("actions.labels.review_nilm_assignment"), true),
      this._applianceActionButton(available, "pause_alerts", this._panelText("actions.labels.pause_alerts"), true),
      this._applianceActionButton(available, "relearn_baseline", this._panelText("actions.labels.relearn_baseline"), true),
      this._applianceActionButton(available, "open_advanced_circuit_settings", this._panelText("actions.labels.open_advanced_circuit_settings"), true),
    ].filter(Boolean);
    if (!alertButtons.length && !buttons.length) {
      return `<p class="muted">${this._escape(this._panelText("appliance_detail.no_actions"))}</p>`;
    }
    return `
      ${alertButtons.length ? `<div class="decision-tiles appliance-alert-actions">${alertButtons.join("")}</div>` : ""}
      ${buttons.length ? `<div class="actions appliance-general-actions">${buttons.join("")}</div>` : ""}
    `;
  }

  _applianceAlertActionTile(actions, actionKey, label, icon, helper = "") {
    const action = actions && actions[actionKey];
    if (!action) {
      return "";
    }
    const busyKey = `appliance_detail_${actionKey}`;
    const disabled = this._busyAction === busyKey || action.enabled === false ? "disabled" : "";
    const reason = action.unavailable_label || action.unavailable_reason || "";
    const title = reason ? ` title="${this._escape(reason)}"` : "";
    return `<button type="button" data-appliance-detail-action="${actionKey}" class="decision-tile appliance-alert-action"${title} ${disabled}><ha-icon icon="${icon}"></ha-icon><span><strong>${this._escape(action.label || label)}</strong>${helper ? `<small>${this._escape(helper)}</small>` : ""}</span></button>`;
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

  _zoomApplianceHistoryGraph(factor) {
    this._zoomGraphWindow(
      this._applianceDetailHistoryGraphWindow(),
      factor,
      (next) => { this._applianceDetailHistoryWindow = next; },
    );
  }

  _panApplianceHistoryGraph(direction) {
    this._panGraphWindow(
      this._applianceDetailHistoryGraphWindow(),
      direction,
      (next) => { this._applianceDetailHistoryWindow = next; },
    );
  }

  _renderApplianceHistoryGraphControls(window) {
    if (!window) {
      return "";
    }
    return this._renderHistoryGraphControls(
      window,
      "appliance-history-graph",
      "data-appliance-history-graph",
      this._panelTextFormat("appliance_detail.history_window", { start: this._formatDateTime(new Date(window.start)), end: this._formatDateTime(new Date(window.end)) }),
    );
  }

  _applianceDetailHistoryGraphWindow() {
    return this._historyGraphWindow(
      this._applianceDetailHistoryBounds,
      this._applianceDetailHistoryWindow,
    );
  }
  };
}
