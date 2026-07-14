export function createEvidenceViewMethods({
  HISTORY_CALL_API_PREFIX,
  MAX_CHART_POINTS_PER_SERIES,
  CHART_COLORS,
}) {
  return class EvidenceViewMethods {
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
      this._historyError = this._panelTextFormat("errors.load_history", { path: fetchPath, message: error.message });
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._historyLoading = false;
        this._render();
      }
    }
  }

  async _applyAlertDecision() {
    if (!this._alertDecision) {
      this._setInlineFeedback("alert-response", "error", this._panelText("errors.alert_decision_required"));
      return;
    }
    await this._callAction(this._alertDecision, { feedbackScope: "alert-response" });
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
    const actionContext = this._actionContext();
    const busyKey = `recommendation_${index}_${actionKey}`;
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
      const message = this._recommendationActionMessage(actionKey);
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

  _alertActionMessage(actionKey) {
    const messages = {
      acknowledge: "messages.alert_acknowledged",
      mark_expected: "messages.marked_expected",
      mark_unhelpful: "messages.marked_unhelpful",
      pause_alerts: "messages.alert_pause_updated",
      relearn_baseline: "messages.baseline_relearn_requested",
    };
    return this._panelText(messages[actionKey] || "common.action_complete");
  }

  _recommendationActionMessage(actionKey) {
    const messages = {
      apply: "messages.recommendation_applied",
      dismiss: "messages.recommendation_dismissed",
      undo: "messages.recommendation_undone",
      reset: "messages.recommendation_reset",
    };
    return this._panelText(messages[actionKey] || "messages.recommendation_action_complete");
  }

  _renderEvidenceBody(alert, circuit) {
    return alert ? this._renderAlert(alert, circuit) : this._renderNotFound();
  }

  _renderAlert(alert, circuit) {
    return this._evidenceSummary.renderAlert(alert, circuit);
  }

  _renderAlertContent(alert, circuit) {
    return `
      <section class="evidence-section evidence-meta summary section-surface">
        ${this._metric(this._panelText("evidence.labels.feature"), alert.feature_name || this._friendlyFeature(alert.feature))}
        ${this._metric(this._panelText("evidence.labels.repeated"), alert.repeated_count)}
      </section>
      ${this._renderAlertComparison(alert)}
      ${this._renderSafetyNotice(alert)}
      <section class="evidence-section evidence-investigation">
        <div class="section-surface" data-evidence-graph>
          <h2>${this._escape(this._panelText("evidence.sections.graph"))}</h2>
          ${this._renderChart(alert)}
        </div>
        <div class="evidence-explanation" data-evidence-explanation>
          <section class="section-surface">
            <h2>${this._escape(this._panelText("evidence.sections.what_happened"))}</h2>
            <p>${this._escape(alert.what_happened || alert.message || this._panelText("evidence.fallbacks.what_happened"))}</p>
          </section>
          <section class="section-surface">
            <h2>${this._escape(this._panelText("evidence.sections.why_it_matters"))}</h2>
            <p>${this._escape(alert.why_it_matters || this._panelText("evidence.fallbacks.why_it_matters"))}</p>
          </section>
          <section class="section-surface">
            <h2>${this._escape(this._panelText("evidence.labels.check_first"))}</h2>
            <p>${this._escape(alert.what_to_check_first || this._changeSummary(alert))}</p>
          </section>
        </div>
      </section>
      ${this._renderAlertResponse()}
      <details class="evidence-section disclosure section-surface" data-evidence-technical>
        <summary>${this._escape(this._panelText("evidence.sections.technical_details"))}</summary>
        <div class="summary">
          ${this._metric(this._alertMetricLabel(alert, "baseline"), this._formatAlertMetricValue(alert, alert.baseline_value))}
          ${this._metric(this._alertMetricLabel(alert, "expected"), this._formatAlertMetricValue(alert, alert.expected_value))}
          ${this._metric(this._alertMetricLabel(alert, "threshold"), this._formatAlertMetricValue(alert, alert.threshold))}
          ${this._metric(this._panelText("evidence.labels.samples"), alert.sample_count)}
          ${this._metric(this._panelText("evidence.labels.first_seen"), this._formatDateTime(alert.first_seen))}
          ${this._metric(this._panelText("evidence.labels.last_seen"), this._formatDateTime(alert.last_seen))}
        </div>
      </details>
      ${this._renderActionDisclosure("pause", this._panelText("actions.groups.pause_title"), this._panelText("actions.groups.pause_description"), [
        this._actionButton("pause_alerts", this._panelText("actions.labels.pause_alerts"), true),
      ])}
      ${this._renderActionDisclosure("tune", this._panelText("actions.groups.tune_title"), this._panelText("actions.groups.tune_description"), [
        this._actionButton("open_appliance_detail", this._panelText("actions.labels.open_appliance_detail"), true),
        this._actionButton("relearn_baseline", this._panelText("actions.labels.relearn_baseline"), true),
        this._actionButton("open_advanced_circuit_settings", this._panelText("actions.labels.open_advanced_circuit_settings"), true),
      ])}
      ${this._renderAlertRecommendationsDisclosure()}
    `;
  }

  _renderAlertResponse() {
    const actions = (this._payload && this._payload.actions) || {};
    const choices = [
      ["acknowledge", "mdi:check", "actions.labels.dismiss", "actions.helpers.dismiss"],
      ["mark_expected", "mdi:check-decagram", "actions.labels.mark_expected", "actions.helpers.mark_expected"],
      ["mark_unhelpful", "mdi:message-alert-outline", "actions.labels.not_helpful", "actions.helpers.mark_unhelpful"],
    ].filter(([key]) => actions[key]);
    if (!choices.length) {
      return "";
    }
    const busy = choices.some(([key]) => this._busyAction === key);
    return `<section class="evidence-section response-section section-surface">
      <fieldset class="decision-group">
        <legend>${this._escape(this._panelText("actions.groups.respond_title"))}</legend>
        <p class="muted">${this._escape(this._panelText("actions.groups.respond_description"))}</p>
        <div class="decision-tiles">
          ${choices.map(([key, icon, label, helper]) => `<label class="decision-tile"><input type="radio" name="alert_decision" value="${key}" data-alert-decision ${this._alertDecision === key ? "checked" : ""} ${busy ? "disabled" : ""}><ha-icon icon="${icon}"></ha-icon><span><strong>${this._escape(this._panelText(label))}</strong><small>${this._escape(this._panelText(helper))}</small></span></label>`).join("")}
        </div>
      </fieldset>
      <button type="button" id="apply_alert_decision" ${this._alertDecision && !busy ? "" : "disabled"}>${this._escape(this._panelText("actions.labels.apply"))}</button>
      <div class="inline-feedback-region">${this._renderInlineFeedback("alert-response")}</div>
    </section>`;
  }

  _renderActionDisclosure(name, title, description, buttons) {
    const renderedButtons = buttons.filter(Boolean);
    if (!renderedButtons.length) {
      return "";
    }
    return `<details class="evidence-section disclosure action-disclosure section-surface" data-alert-disclosure="${name}">
      <summary>${this._escape(title)}</summary>
      <div class="disclosure-content">
        <p class="muted">${this._escape(description)}</p>
        <div class="actions">${renderedButtons.join("")}</div>
      </div>
    </details>`;
  }

  _renderAlertRecommendationsDisclosure() {
    const recommendations = this._renderRecommendations();
    if (!recommendations) {
      return "";
    }
    return `<details class="evidence-section disclosure action-disclosure section-surface" data-alert-disclosure="recommendations">
      <summary>${this._escape(this._panelText("actions.groups.recommendations_title"))}</summary>
      <div class="disclosure-content">${recommendations}</div>
    </details>`;
  }

  _zoomGraphWindow(window, factor, setWindow) {
    if (!window || !Number.isFinite(factor) || factor <= 0) {
      return;
    }
    const span = window.end - window.start;
    const nextSpan = Math.max(15 * 60 * 1000, Math.min(window.max - window.min, span * factor));
    const center = (window.start + window.end) / 2;
    this._setGraphWindow(center - nextSpan / 2, center + nextSpan / 2, window, setWindow);
  }

  _panGraphWindow(window, direction, setWindow) {
    if (!window || !Number.isFinite(direction)) {
      return;
    }
    const shift = (window.end - window.start) * direction;
    this._setGraphWindow(window.start + shift, window.end + shift, window, setWindow);
  }

  _setGraphWindow(start, end, bounds, setWindow) {
    if (start < bounds.min) {
      end += bounds.min - start;
      start = bounds.min;
    }
    if (end > bounds.max) {
      start -= end - bounds.max;
      end = bounds.max;
    }
    setWindow({
      start: Math.max(bounds.min, start),
      end: Math.min(bounds.max, end),
    });
    this._render();
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
      ${this._renderRecommendationSection(this._panelText("recommendations.suggested_settings"), grouped.pending)}
      ${this._renderRecommendationSection(this._panelText("recommendations.applied_suggested_settings"), grouped.applied)}
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
              <strong>${this._escape(recommendation.display_label || recommendation.title || this._panelText("recommendations.suggested_setting"))}</strong>
              ${recommendation.summary ? `<p class="muted">${this._escape(recommendation.summary)}</p>` : ""}
              ${recommendation.reason ? `<p class="muted">${this._escape(recommendation.reason)}</p>` : ""}
              ${this._recommendationValueRows(recommendation)}
              ${recommendation.expected_effect ? `<p class="muted">${this._escape(this._panelTextFormat("recommendations.expected_effect", { effect: recommendation.expected_effect }))}</p>` : ""}
              ${recommendation.evidence_preview ? `<p class="muted">${this._escape(this._panelTextFormat("recommendations.evidence", { evidence: recommendation.evidence_preview }))}</p>` : ""}
              ${this._renderSettingImpactPreview(recommendation)}
                <div class="actions">
                 ${recommendation.actions && recommendation.actions.preview ? this._recommendationActionButton(recommendation, originalIndex, "preview", this._panelText("actions.labels.preview_evidence"), true) : ""}
                 ${this._recommendationActionButton(recommendation, originalIndex, "apply", this._panelText("actions.labels.apply"))}
                 ${this._recommendationActionButton(recommendation, originalIndex, "dismiss", this._panelText("actions.labels.dismiss"), true)}
                 ${recommendation.actions && recommendation.actions.undo ? this._recommendationActionButton(recommendation, originalIndex, "undo", this._panelText("actions.labels.undo"), true) : ""}
                 ${recommendation.actions && recommendation.actions.reset ? this._recommendationActionButton(recommendation, originalIndex, "reset", this._panelText("actions.labels.reset_default"), true) : ""}
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
    const label = recommendation.display_label || recommendation.title || this._panelText("recommendations.suggested_setting");
    const evidenceCount = Number(recommendation.evidence_key_count || 0);
    const omittedCount = Number(recommendation.evidence_omitted_key_count || 0);
    const evidenceSummary = recommendation.evidence_preview
      ? `<p>${this._escape(recommendation.evidence_preview)}</p>`
      : `<p class="muted">${this._escape(this._panelText("recommendations.no_evidence_summary"))}</p>`;
    const omitted = omittedCount > 0
      ? this._panelTextFormat("recommendations.evidence_omitted", { count: omittedCount })
      : "";
    const countSummary = evidenceCount > 0
      ? `<p class="muted">${this._escape(this._panelTextFormat("recommendations.evidence_count", { count: evidenceCount, omitted }))}</p>`
      : "";
    return `
      <section class="panel">
        <h2>${this._escape(this._panelText("recommendations.recommendation_evidence"))}</h2>
        <p class="muted">${this._escape(this._panelTextFormat("recommendations.previewing_evidence", { label }))}</p>
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
      rows.push(`<code>${this._escape(this._panelTextFormat("recommendations.value_row", { label: this._panelText("common.current"), value: currentValue }))}</code>`);
    }
    if (recommendation.default_value !== undefined) {
      rows.push(`<code>${this._escape(this._panelTextFormat("recommendations.value_row", { label: this._panelText("common.default"), value: recommendation.default_value }))}</code>`);
    }
    if (suggestedValue !== undefined) {
      rows.push(`<code>${this._escape(this._panelTextFormat("recommendations.value_row", { label: this._panelText("common.suggested"), value: suggestedValue }))}</code>`);
    }
    return rows.length ? `<div class="entity-list">${rows.join("")}</div>` : "";
  }

  _renderSafetyNotice(alert) {
    if (!alert.safety_notice) {
      return "";
    }
    return `
      <section class="section-surface safety-notice">
        <h2>${this._escape(this._panelText("chart.safety_notice"))}</h2>
        <p>${this._escape(alert.safety_notice)}</p>
      </section>
    `;
  }

  _renderChart(alert) {
    if (this._historyLoading) {
      const loadingText = this._panelText("chart.loading_history");
      return `<div class="loading-skeleton graph-loading-skeleton" data-loading-skeleton role="status" aria-label="${this._escape(loadingText)}"></div>`;
    }
    if (this._historyError) {
      return `<div data-alert-history-error><p class="muted">${this._escape(this._historyError)}</p><button type="button" class="secondary" data-retry-alert-history>${this._escape(this._panelText("common.retry"))}</button></div>`;
    }
    const series = this._chartSeries();
    if (!series.length) {
      return `<p class="muted">${this._escape(this._panelText("chart.no_history"))}</p>`;
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
    const unit = alert.y_axis_label ? ` ${alert.y_axis_label}` : "";
    const pointTitle = (item, point) => this._panelTextFormat("chart.point_title", {
      name: item.name,
      value: this._formatNumber(point.value),
      unit,
      time: this._formatDateTime(new Date(point.time)),
    });

    const lines = series.map((item, index) => {
      const color = CHART_COLORS[index % CHART_COLORS.length];
      const points = item.points.map((point) => `${x(point.time).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
      const circles = item.points.map((point) => {
        const title = pointTitle(item, point);
        return `<circle cx="${x(point.time).toFixed(1)}" cy="${y(point.value).toFixed(1)}" r="3" fill="${color}"><title>${this._escape(title)}</title></circle>`;
      }).join("");
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
      return { time: markerTime, direction: edge.direction || this._panelText("nilm_workspace.nilm_edge") };
    }).filter(Boolean);
    const edgeMarkers = edgeItems.map((edge) => {
      const markerTime = edge.time;
      const markerX = x(markerTime).toFixed(1);
      const direction = this._friendlyFeature(edge.direction);
      return `<line class="nilm-edge-marker" x1="${markerX}" y1="${padTop}" x2="${markerX}" y2="${height - padBottom}" data-nilm-edge-time="${this._escape(new Date(markerTime).toISOString())}" data-nilm-edge-direction="${this._escape(edge.direction)}"><title>${this._escape(direction)}</title></line>`;
    }).join("");
    const sessionItems = (Array.isArray(alert.nilm_sessions) ? alert.nilm_sessions : []).map((session) => {
      const start = Date.parse(session && session.start || "");
      const end = Date.parse(session && session.end || "");
      if (!Number.isFinite(start) || !Number.isFinite(end) || end <= minTime || start >= maxTime) {
        return null;
      }
      const confidence = Number(session && session.confidence);
      const confidenceValue = Number.isFinite(confidence) ? Math.max(0, Math.min(1, confidence)) : null;
      return { session, start, end, confidenceValue };
    }).filter(Boolean);
    const sessionBands = sessionItems.map(({ session, start, end, confidenceValue }) => {
      const confidenceAttr = confidenceValue !== null ? ` data-nilm-session-confidence="${confidenceValue.toFixed(2)}"` : "";
      const lowConfidenceAttr = this._isLowNilmConfidence(confidenceValue) ? ' data-nilm-low-confidence="true"' : "";
      const selectedAttr = session.selected ? ' data-nilm-selected="true"' : "";
      const kindAttr = session.band_kind ? ` data-nilm-band-kind="${this._escape(session.band_kind)}"` : "";
      const draftAttr = Number.isInteger(session.draft_index) ? ` data-nilm-draft-index="${session.draft_index}"` : "";
      const labelIntervalAttr = Number.isInteger(session.label_interval_index) ? ` data-nilm-label-interval-index="${session.label_interval_index}"` : "";
      const confidenceStyle = confidenceValue !== null ? ` style="opacity:${(0.08 + confidenceValue * 0.2).toFixed(2)}"` : "";
      const confidenceLabel = confidenceValue !== null ? this._panelTextFormat("chart.session_confidence", { confidence: Math.round(confidenceValue * 100) }) : "";
      const left = x(Math.max(start, minTime));
      const right = x(Math.min(end, maxTime));
      const bandWidth = Math.max(right - left, 1);
      const label = this._nilmSessionGraphLabel(session);
      const visibleLabel = bandWidth >= 56 ? this._truncateNilmGraphLabel(label, Math.floor((bandWidth - 10) / 7)) : "";
      const sessionId = session.session_id || this._panelText("nilm_workspace.nilm_session");
      const title = label ? this._panelTextFormat("chart.session_title", { label, session_id: sessionId }) : sessionId;
      const labelText = visibleLabel ? `<text class="nilm-session-label" x="${(left + 6).toFixed(1)}" y="${(padTop + 17).toFixed(1)}" data-nilm-session-label="${this._escape(label)}">${this._escape(visibleLabel)}</text>` : "";
      return `<g data-nilm-session-label="${this._escape(label)}"><rect class="nilm-session-band" x="${left.toFixed(1)}" y="${padTop}" width="${bandWidth.toFixed(1)}" height="${height - padTop - padBottom}" data-nilm-session-start="${this._escape(session.start || "")}" data-nilm-session-end="${this._escape(session.end || "")}"${confidenceAttr}${lowConfidenceAttr}${selectedAttr}${kindAttr}${draftAttr}${labelIntervalAttr}${confidenceStyle}><title>${this._escape(title)}${confidenceLabel}</title></rect>${labelText}</g>`;
    }).join("");
    const edgeTimesAttr = edgeItems.length
      ? ` data-nilm-edge-times="${edgeItems.map((edge) => edge.time).join(",")}"`
      : "";
    const selectAttrs = alert.nilm_select_interval
      ? ` tabindex="0" data-nilm-chart-select="1" data-chart-start="${minTime}" data-chart-end="${maxTime}" data-chart-left="${padLeft}" data-chart-right="${width - padRight}"${edgeTimesAttr}`
      : "";
    const dataItems = [
      ...series.flatMap((item) => item.points.map((point) => pointTitle(item, point))),
      ...sessionItems.map(({ session, start, end, confidenceValue }) => {
        const label = this._nilmSessionGraphLabel(session);
        const sessionId = session.session_id || this._panelText("nilm_workspace.nilm_session");
        const title = label ? this._panelTextFormat("chart.session_title", { label, session_id: sessionId }) : sessionId;
        const confidence = confidenceValue !== null ? this._panelTextFormat("chart.session_confidence", { confidence: Math.round(confidenceValue * 100) }) : "";
        return `${title}: ${this._formatDateTime(new Date(start))} - ${this._formatDateTime(new Date(end))}${confidence}`;
      }),
      ...edgeItems.map((edge) => `${this._friendlyFeature(edge.direction)}: ${this._formatDateTime(new Date(edge.time))}`),
    ];
    const dataFallback = `<p class="muted chart-data-summary">${this._escape(this._panelTextFormat("chart.data_summary", { count: dataItems.length }))}</p>
      <details class="action-disclosure chart-data-fallback">
        <summary>${this._escape(this._panelText("chart.data_fallback"))}</summary>
        <ul>${dataItems.map((item) => `<li>${this._escape(item)}</li>`).join("")}</ul>
      </details>`;

    return `
      <svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${this._escape(this._panelText("chart.alert_evidence_label"))}"${selectAttrs}>
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
      <p class="muted">${this._escape(this._panelTextFormat("chart.graph_times", { time_zone: timeZoneLabel }))}</p>
      ${dataFallback}
    `;
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

  _renderHistoryGraphControls(window, prefix, containerAttribute, windowText) {
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
    const zoomInLabel = this._panelText("actions.labels.zoom_in");
    const zoomOutLabel = this._panelText("actions.labels.zoom_out");
    const panEarlierLabel = this._panelText("actions.labels.pan_earlier");
    const panLaterLabel = this._panelText("actions.labels.pan_later");
    return `<div ${containerAttribute}>
      <div class="actions nilm-graph-controls">
        <button type="button" class="secondary icon-button" data-${prefix}-zoom="0.5" title="${this._escape(zoomInLabel)}" aria-label="${this._escape(zoomInLabel)}" ${zoomInDisabled}><ha-icon icon="mdi:magnify-plus-outline"></ha-icon></button>
        <button type="button" class="secondary icon-button" data-${prefix}-zoom="2" title="${this._escape(zoomOutLabel)}" aria-label="${this._escape(zoomOutLabel)}" ${zoomOutDisabled}><ha-icon icon="mdi:magnify-minus-outline"></ha-icon></button>
        <button type="button" class="secondary icon-button" data-${prefix}-pan="-0.5" title="${this._escape(panEarlierLabel)}" aria-label="${this._escape(panEarlierLabel)}" ${panEarlierDisabled}><ha-icon icon="mdi:chevron-left"></ha-icon></button>
        <button type="button" class="secondary icon-button" data-${prefix}-pan="0.5" title="${this._escape(panLaterLabel)}" aria-label="${this._escape(panLaterLabel)}" ${panLaterDisabled}><ha-icon icon="mdi:chevron-right"></ha-icon></button>
      </div>
      <p class="muted" data-${prefix}-window>${this._escape(windowText)}</p>
    </div>`;
  }

  _historyGraphWindow(bounds, savedWindow) {
    const min = Number(bounds && bounds.min);
    const max = Number(bounds && bounds.max);
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
      return null;
    }
    const start = Math.max(min, Math.min(max - 1, savedWindow ? savedWindow.start : min));
    const end = Math.max(start + 1, Math.min(max, savedWindow ? savedWindow.end : max));
    return { start, end, min, max };
  }

  _chartSeries(historySeries = this._historySeries, entitySeries = []) {
    const units = new Map((Array.isArray(entitySeries) ? entitySeries : []).map((item) => [
      item.entity_id,
      String(item.unit || ""),
    ]));
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
          unit: units.get(entityId) || this._friendlyEntityUnit(entityId),
          points: this._boundedChartPoints(points),
        });
      }
    }
    return parsed;
  }

  _visibleChartSeries(historySeries, graphWindow) {
    return this._visibleParsedChartSeries(this._chartSeries(historySeries), graphWindow);
  }

  _visibleParsedChartSeries(parsedSeries, graphWindow) {
    return parsedSeries.map((item) => {
      if (!graphWindow) {
        return item;
      }
      return Object.assign({}, item, {
        points: item.points.filter((point) => point.time >= graphWindow.start && point.time <= graphWindow.end),
      });
    }).filter((item) => item.points.length);
  }

  _chartSeriesByUnit(series) {
    const groups = new Map();
    for (const item of series) {
      const unit = String(item.unit || "");
      if (!groups.has(unit)) groups.set(unit, []);
      groups.get(unit).push(item);
    }
    return Array.from(groups, ([unit, unitSeries]) => ({ unit, series: unitSeries }));
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

  _friendlyEntityUnit(entityId) {
    const state = this._hass && this._hass.states && this._hass.states[entityId];
    return String(state && state.attributes && state.attributes.unit_of_measurement || "");
  }

  _historyApiPath(alert) {
    const start = alert.graph_window_start || new Date(Date.now() - 86400000).toISOString();
    return this._historyApiPathForEntities(
      alert.graph_entities || [],
      start,
      alert.graph_window_end,
    );
  }

  _historyApiPathForEntities(entities, start, end) {
    const params = new URLSearchParams();
    params.set("filter_entity_id", entities.join(","));
    if (end) {
      params.set("end_time", end);
    }
    params.set("minimal_response", "1");
    params.set("no_attributes", "1");
    return `${HISTORY_CALL_API_PREFIX}/${encodeURIComponent(start)}?${params.toString()}`;
  }

  _renderNotFound() {
    if (this._loading) {
      return "";
    }
    const isCircuitFallback = this._payload && this._payload.status === "circuit_found_no_evidence";
    const title = isCircuitFallback ? this._evidenceText("fallbacks.current_circuit_heading") : this._evidenceText("fallbacks.historical_heading");
    const message = (this._payload && this._payload.message) || this._evidenceText("fallbacks.historical_message");
    const nextStep = (this._payload && this._payload.next_step) || this._evidenceText("fallbacks.historical_next_step");
    return `
      <section class="panel">
        <h2>${this._escape(title)}</h2>
        <p class="muted">${this._escape(message)} ${this._escape(nextStep)}</p>
      </section>
      ${this._renderInlineFeedback("alert-response")}
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
        <h2>${this._escape(this._evidenceText("actions.available_circuit_actions"))}</h2>
        ${this._renderActionGroup(this._panelText("actions.groups.pause_title"), this._panelText("actions.groups.pause_description"), [
          this._actionButton("pause_alerts", this._panelText("actions.labels.pause_alerts"), true),
        ])}
        ${this._renderActionGroup(this._panelText("actions.groups.tune_title"), this._panelText("actions.groups.tune_description"), [
          this._actionButton("open_appliance_detail", this._panelText("actions.labels.open_appliance_detail"), true),
          this._actionButton("relearn_baseline", this._panelText("actions.labels.relearn_baseline"), true),
          this._actionButton("open_advanced_circuit_settings", this._panelText("actions.labels.open_advanced_circuit_settings"), true),
        ])}
      </section>
      ${this._renderRecommendations()}
    `;
  }

  _alertComparisonScale(alert) {
    const observed = this._finiteMetricValue(alert && alert.observed_value);
    const expected = this._finiteMetricValue(
      alert && alert.expected_value !== null && alert.expected_value !== undefined
        ? alert.expected_value
        : alert && alert.baseline_value,
    );
    const threshold = this._finiteMetricValue(alert && alert.threshold);
    if (observed === null || expected === null) {
      return null;
    }
    const values = [observed, expected, threshold].filter((value) => value !== null);
    const low = Math.min(...values);
    const high = Math.max(...values);
    const padding = Math.max((high - low) * 0.15, Math.abs(high) * 0.05, 1);
    const min = low - padding;
    const max = high + padding;
    const position = (value) => Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
    return {
      observed,
      expected,
      threshold,
      percentChange: expected === 0 ? null : ((observed - expected) / Math.abs(expected)) * 100,
      markers: [
        { key: "expected", value: expected, position: position(expected) },
        ...(threshold === null ? [] : [{ key: "threshold", value: threshold, position: position(threshold) }]),
        { key: "observed", value: observed, position: position(observed) },
      ],
    };
  }

  _renderAlertComparison(alert) {
    const scale = this._alertComparisonScale(alert);
    const percentChange = scale && Number.isFinite(scale.percentChange) ? scale.percentChange : null;
    const change = percentChange === null
      ? this._panelText("evidence.change_unavailable")
      : `${percentChange > 0 ? "+" : ""}${this._formatNumber(percentChange)}%`;
    const changeAttribute = percentChange === null ? "unavailable" : this._formatNumber(percentChange);
    if (!scale) {
      return `<section class="evidence-section section-surface" data-evidence-comparison="fallback">
        <h2>${this._escape(this._panelText("evidence.sections.comparison"))}</h2>
        <div class="summary">
          ${this._metric(this._alertMetricLabel(alert, "observed"), this._formatAlertMetricValue(alert, alert && alert.observed_value))}
          ${this._metric(this._alertMetricLabel(alert, "expected"), this._formatAlertMetricValue(alert, alert && (alert.expected_value ?? alert.baseline_value)))}
        </div>
        <p class="comparison-change" data-comparison-change="${changeAttribute}"><strong>${this._escape(this._panelText("evidence.labels.change"))}:</strong> ${this._escape(change)}</p>
      </section>`;
    }
    const summaryValues = {
      observed: this._formatAlertMetricValue(alert, scale.observed),
      expected: this._formatAlertMetricValue(alert, scale.expected),
      change,
    };
    const metricSummary = Boolean(alert && alert.value_label);
    const summary = scale.threshold === null
      ? this._panelTextFormat(metricSummary ? "evidence.comparison_summary_metric" : "evidence.comparison_summary", {
        ...summaryValues,
        metric: alert && alert.value_label,
      })
      : this._panelTextFormat(metricSummary ? "evidence.comparison_summary_with_threshold_metric" : "evidence.comparison_summary_with_threshold", {
        ...summaryValues,
        metric: alert && alert.value_label,
        threshold: this._formatAlertMetricValue(alert, scale.threshold),
      });
    return `<section class="evidence-section comparison section-surface" data-evidence-comparison="visual">
      <h2>${this._escape(this._panelText("evidence.sections.comparison"))}</h2>
      <p class="comparison-change" data-comparison-change="${changeAttribute}"><strong>${this._escape(this._panelText("evidence.labels.change"))}:</strong> ${this._escape(change)}</p>
      ${alert && alert.value_label ? `<p class="comparison-metric">${this._escape(alert.value_label)}</p>` : ""}
      <div class="comparison-scale" role="img" aria-label="${this._escape(summary)}">
        <div class="comparison-track"></div>
        ${scale.markers.map((marker) => `<span class="comparison-marker ${marker.key}" data-comparison-marker="${marker.key}" style="left:${marker.position}%"><span>${this._escape(this._panelText(`evidence.labels.${marker.key}`))}</span><strong>${this._escape(this._formatAlertMetricValue(alert, marker.value))}</strong></span>`).join("")}
      </div>
    </section>`;
  }

  _alertMetricLabel(alert, roleKey) {
    const role = this._panelText(`evidence.labels.${roleKey}`);
    const metric = String(alert && alert.value_label || "").trim();
    return metric ? `${role} ${metric}` : role;
  }

  _formatAlertMetricValue(alert, value) {
    if (value === null || value === undefined || value === "") {
      return this._panelText("common.unknown");
    }
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return this._formatMetricValue(value);
    }
    if (alert && alert.value_format === "percentage") {
      return `${(number * 100).toLocaleString(undefined, {
        minimumFractionDigits: 3,
        maximumFractionDigits: 3,
      })}%`;
    }
    const formatted = number.toLocaleString(undefined, { maximumFractionDigits: 3 });
    const unit = this._alertMetricUnit(alert);
    return `${formatted}${unit ? ` ${unit}` : ""}`;
  }

  _alertMetricUnit(alert) {
    return String(alert && alert.value_unit || "").trim();
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
  };
}
