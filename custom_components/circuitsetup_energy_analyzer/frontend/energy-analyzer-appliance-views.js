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
      await this._loadApplianceDetailHistories(undefined, requestId, routeKey);
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

  async _loadApplianceDetailHistories(hours, requestId, routeKey) {
    const context = this._applianceDetail?.detail?.sump_driver_context;
    const requestedHours = Number.isFinite(Number(hours))
      ? Number(hours)
      : Number(context?.default_hours) || undefined;
    await Promise.all([
      this._loadApplianceDetailHistory(requestedHours, requestId, routeKey),
      this._loadSumpDriverHistory(requestedHours, requestId, routeKey),
    ]);
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

  async _loadSumpDriverHistory(hours, requestId = this._evidenceRequestId, routeKey = this._loadedRouteKey) {
    const context = this._applianceDetail?.detail?.sump_driver_context;
    if (!context) {
      this._sumpDriverAnalysis = null;
      return;
    }
    const periods = Array.isArray(context.period_hours)
      ? context.period_hours.map(Number).filter(Number.isFinite)
      : [];
    const defaultHours = Number(context.default_hours);
    const requestedHours = periods.includes(Number(hours))
      ? Number(hours)
      : periods.includes(defaultHours)
        ? defaultHours
        : periods[0];
    const entities = this._sumpDriverHistoryEntities(context);
    if (!entities.length || !Number.isFinite(requestedHours) || requestedHours <= 0) {
      this._sumpDriverAnalysis = null;
      return;
    }
    const end = Date.now();
    const start = end - requestedHours * 60 * 60 * 1000;
    const historyStart = start - Math.max(Number(context.rain_response_window_minutes) || 0, 0) * 60_000;
    this._sumpDriverHistoryLoading = true;
    this._sumpDriverHistoryError = "";
    this._sumpDriverAnalysis = null;
    this._render();
    const attributeEntities = [...new Set([
      context.rain_intensity_entity_id,
      context.humidity_entity_id,
    ].filter(Boolean))];
    const stateEntities = entities.filter((entityId) => !attributeEntities.includes(entityId));
    const paths = [
      ...(stateEntities.length ? [this._historyApiPathForEntities(
        stateEntities,
        new Date(historyStart).toISOString(),
        new Date(end).toISOString(),
      )] : []),
      ...(attributeEntities.length ? [this._historyApiPathForEntities(
        attributeEntities,
        new Date(historyStart).toISOString(),
        new Date(end).toISOString(),
        { includeAttributes: true, significantChangesOnly: false },
      )] : []),
    ];
    const fetchPath = `/api/${paths[0]}`;
    try {
      const responses = await Promise.all(paths.map((apiPath) => this._requestJson(apiPath, `/api/${apiPath}`)));
      if (!this._isCurrentRequest(requestId, routeKey)) return;
      this._sumpDriverAnalysis = this._analyzeSumpDriverHistory(
        responses.flatMap((rows) => Array.isArray(rows) ? rows : []),
        context,
        start,
        end,
      );
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) return;
      this._sumpDriverHistoryError = this._panelTextFormat(
        "errors.load_appliance_history",
        { path: fetchPath, message: error.message },
      );
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._sumpDriverHistoryLoading = false;
        this._render();
      }
    }
  }

  _sumpDriverHistoryEntities(context) {
    return [...new Set([
      context.pump_activity_entity_id,
      ...(Array.isArray(context.compressor_activity_entity_ids) ? context.compressor_activity_entity_ids : []),
      ...(Array.isArray(context.blower_activity_entity_ids) ? context.blower_activity_entity_ids : []),
      context.rain_intensity_entity_id,
      context.rain_entity_id,
      context.humidity_entity_id,
    ].filter(Boolean))];
  }

  _sumpHistoryEvents(rows, entityId) {
    const series = rows.find((items) => Array.isArray(items) && items.some((item) => item?.entity_id === entityId)) || [];
    return series.map((item) => ({
      time: Date.parse(item.last_updated || item.last_changed || ""),
      state: item.state,
      attributes: item.attributes || {},
    })).filter((item) => Number.isFinite(item.time)).sort((left, right) => left.time - right.time);
  }

  _sumpActivityIntervals(events, end, completedOnly = false) {
    const intervals = [];
    let start = null;
    for (const event of events) {
      const state = String(event.state || "").toLowerCase();
      const running = state === "running";
      const stopped = state === "idle";
      if (running && start === null) start = event.time;
      if (stopped && start !== null) {
        if (event.time > start) intervals.push({ start, end: event.time, completed: true });
        start = null;
      }
      if (!running && !stopped) start = null;
    }
    if (start !== null && !completedOnly && end > start) {
      intervals.push({ start, end, completed: false });
    }
    return intervals;
  }

  _sumpActivityKnown(events, start, end) {
    let known = false;
    for (const event of events) {
      if (event.time > end) break;
      const state = String(event.state || "").toLowerCase();
      const valid = state === "running" || state === "idle";
      if (event.time <= start) {
        known = valid;
      } else if (!known || !valid) {
        return false;
      }
    }
    return known;
  }

  _sumpIntervalsOverlap(left, right) {
    return left.start < right.end && left.end > right.start;
  }

  _sumpHumidityValue(event) {
    const value = Number(event?.attributes?.humidity ?? event?.state);
    return Number.isFinite(value) && value >= 0 && value <= 100 ? value : null;
  }

  _sumpRainValue(event) {
    const stateValue = Number(event?.state);
    const value = Number.isFinite(stateValue)
      ? stateValue
      : Number(event?.attributes?.precipitation);
    return Number.isFinite(value) && value >= 0 ? value : null;
  }

  _sumpMedian(values) {
    const sorted = values.filter(Number.isFinite).sort((left, right) => left - right);
    if (!sorted.length) return null;
    const middle = Math.floor(sorted.length / 2);
    return sorted.length % 2
      ? sorted[middle]
      : (sorted[middle - 1] + sorted[middle]) / 2;
  }

  _sumpHumidityMedian(events, start, end) {
    let prior = null;
    const values = [];
    for (const event of events) {
      const value = this._sumpHumidityValue(event);
      if (event.time <= start) prior = value;
      if (event.time > start && event.time <= end) {
        if (value === null) return null;
        values.push(value);
      }
    }
    if (prior !== null) values.unshift(prior);
    return this._sumpMedian(values);
  }

  _sumpBinaryRainValue(event) {
    const state = String(event.state || "").trim().toLowerCase();
    if (["on", "true", "1", "wet", "rain", "raining", "detected", "hail", "lightning-rainy", "pouring", "rainy", "snowy-rainy"].includes(state)) return true;
    if (["off", "false", "0", "dry", "clear", "none", "clear-night", "cloudy", "exceptional", "fog", "lightning", "partlycloudy", "sunny", "windy", "windy-variant"].includes(state)) return false;
    return null;
  }

  _sumpBinaryRain(events, start, end) {
    let knownAtStart = false;
    let active = false;
    for (const event of events) {
      if (event.time <= start) {
        const value = this._sumpBinaryRainValue(event);
        knownAtStart = value !== null;
        active = value === true;
      }
    }
    if (active) return true;
    let complete = knownAtStart;
    for (const event of events) {
      if (event.time <= start) continue;
      if (event.time > end) break;
      const value = this._sumpBinaryRainValue(event);
      if (value === true) return true;
      if (value === null) complete = false;
    }
    return complete ? false : null;
  }

  _sumpRainAccumulation(events, start, end, multiplier) {
    let current = null;
    let cursor = start;
    let complete = false;
    let total = 0;
    for (const event of events) {
      const numeric = this._sumpRainValue(event);
      if (event.time <= start) {
        current = numeric;
        complete = numeric !== null;
        continue;
      }
      if (event.time > end) break;
      if (current !== null) total += current * ((event.time - cursor) / 3_600_000) * multiplier;
      current = numeric;
      cursor = event.time;
      if (numeric === null) complete = false;
    }
    if (current !== null) total += current * ((end - cursor) / 3_600_000) * multiplier;
    return complete ? Math.max(total, 0) : null;
  }

  _sumpRainBars(events, start, end, multiplier) {
    const hour = 3_600_000;
    const buckets = new Map();
    for (let index = 0; index < events.length; index += 1) {
      const event = events[index];
      const next = events[index + 1];
      const segmentEnd = Math.min(next?.time ?? end, end);
      let segmentStart = Math.max(event.time, start);
      const rate = this._sumpRainValue(event);
      if (rate === null || rate <= 0 || segmentEnd <= segmentStart) continue;
      while (segmentStart < segmentEnd) {
        const bucket = Math.floor(segmentStart / hour) * hour;
        const sliceEnd = Math.min(segmentEnd, bucket + hour);
        buckets.set(bucket, (buckets.get(bucket) || 0) + rate * ((sliceEnd - segmentStart) / hour) * multiplier);
        segmentStart = sliceEnd;
      }
    }
    return [...buckets].map(([time, value]) => ({ time: time + hour / 2, value }));
  }

  _sumpBinaryRainBars(events, start, end) {
    const points = [];
    const hour = 3_600_000;
    for (let index = 0; index < events.length; index += 1) {
      const event = events[index];
      if (this._sumpBinaryRainValue(event) !== true) continue;
      let segmentStart = Math.max(event.time, start);
      const segmentEnd = Math.min(events[index + 1]?.time ?? end, end);
      while (segmentEnd > segmentStart) {
        const sliceEnd = Math.min(segmentEnd, Math.floor(segmentStart / hour) * hour + hour);
        points.push({ time: segmentStart + (sliceEnd - segmentStart) / 2, value: 1 });
        segmentStart = sliceEnd;
      }
    }
    return points;
  }

  _sumpHumidityPoints(events, intervals) {
    return intervals.map((interval) => {
      const points = [];
      const values = events.filter((event) => event.time > interval.start && event.time < interval.end && this._sumpHumidityValue(event) !== null);
      const startValue = this._sumpHumidityMedian(events, interval.start, interval.start);
      const endValue = this._sumpHumidityMedian(events, interval.end, interval.end);
      if (startValue !== null) points.push({ time: interval.start, value: startValue });
      points.push(...values.map((event) => ({ time: event.time, value: this._sumpHumidityValue(event) })));
      if (endValue !== null) points.push({ time: interval.end, value: endValue });
      return this._boundedChartPoints(points);
    }).filter((points) => points.length);
  }

  _analyzeSumpDriverHistory(rows, context, start, end) {
    const events = (entityId) => this._sumpHistoryEvents(rows, entityId);
    const pumpIntervals = this._sumpActivityIntervals(events(context.pump_activity_entity_id), end, true)
      .filter((interval) => interval.end > start && interval.start < end);
    const compressorEvents = (context.compressor_activity_entity_ids || []).map((entityId) => [entityId, events(entityId)]);
    const compressorIntervals = compressorEvents.flatMap(([entityId, items]) => (
      this._sumpActivityIntervals(items, end).map((interval) => ({ ...interval, entityId }))
    ));
    const blowerEvents = (context.blower_activity_entity_ids || []).map((entityId) => [entityId, events(entityId)]);
    const blowerIntervals = blowerEvents.flatMap(([entityId, items]) => (
      this._sumpActivityIntervals(items, end).map((interval) => ({ ...interval, entityId }))
    ));
    const humidityEvents = events(context.humidity_entity_id);
    const intensityEvents = events(context.rain_intensity_entity_id);
    const binaryRainEvents = events(context.rain_entity_id);
    const unitEvent = intensityEvents.find((event) => event.attributes?.unit_of_measurement || event.attributes?.precipitation_unit);
    const rainUnit = String(unitEvent?.attributes?.unit_of_measurement || unitEvent?.attributes?.precipitation_unit || this._friendlyEntityUnit(context.rain_intensity_entity_id)).toLowerCase().replaceAll(" ", "");
    const rainMultiplier = /^mm\/(h|hr|hour)$/.test(rainUnit)
      ? 1
      : /^(in|inch|inches)\/(h|hr|hour)$/.test(rainUnit)
        ? 25.4
        : null;
    const numericRain = rainMultiplier !== null && intensityEvents.some((event) => this._sumpRainValue(event) !== null);
    const response = Math.max(Number(context.rain_response_window_minutes) || 0, 0) * 60_000;
    // ponytail: bounded 30-day scans; index events only if longer periods are added.
    const rainFor = (interval) => {
      const windowStart = interval.start - response;
      if (numericRain) {
        const amount = this._sumpRainAccumulation(intensityEvents, windowStart, interval.end, rainMultiplier);
        if (amount !== null) return { active: amount > 0, amount, fallback: false };
      }
      return { active: this._sumpBinaryRain(binaryRainEvents, windowStart, interval.end), amount: null, fallback: numericRain };
    };
    const baselineValues = compressorIntervals.filter((interval) => interval.completed).map((interval) => ({
      humidity: this._sumpHumidityMedian(humidityEvents, interval.start, interval.end),
      rain: rainFor(interval).active,
    })).filter((item) => item.rain === false && item.humidity !== null).map((item) => item.humidity);
    const baseline = baselineValues.length >= 15
      ? [...baselineValues].sort((left, right) => left - right)[Math.ceil(baselineValues.length * 0.9) - 1]
      : null;
    const cycles = pumpIntervals.map((cycle) => {
      const rain = rainFor(cycle);
      const compressors = compressorIntervals.filter((interval) => this._sumpIntervalsOverlap(interval, cycle));
      const blowers = blowerIntervals.filter((interval) => this._sumpIntervalsOverlap(interval, cycle));
      const compressorKnown = compressorEvents.every(([, items]) => this._sumpActivityKnown(items, cycle.start, cycle.end));
      const blowerKnown = blowerEvents.every(([, items]) => this._sumpActivityKnown(items, cycle.start, cycle.end));
      const humidityValues = compressors.map((interval) => this._sumpHumidityMedian(
        humidityEvents,
        Math.max(interval.start, cycle.start),
        Math.min(interval.end, cycle.end),
      )).filter((value) => value !== null);
      const humidity = humidityValues.length ? Math.max(...humidityValues) : null;
      const humidityKnown = compressorKnown && (!compressors.length || (baseline !== null && humidity !== null));
      const humidityHigh = compressors.length > 0 && humidityKnown && humidity > baseline;
      let category = "unclassified";
      if (rain.active !== null && humidityKnown) {
        category = rain.active && humidityHigh
          ? "combined"
          : rain.active
            ? "rain"
            : humidityHigh
              ? "hvac_humidity"
              : "unexplained";
      }
      return {
        ...cycle,
        category,
        rainAmount: rain.amount,
        rainActive: rain.active,
        rainFallback: rain.fallback,
        compressor: compressors.length > 0,
        blower: blowers.length ? true : blowerKnown ? false : null,
        humidity,
      };
    });
    const counts = Object.fromEntries(["rain", "hvac_humidity", "combined", "unexplained", "unclassified"].map((category) => [category, cycles.filter((cycle) => cycle.category === category).length]));
    return {
      start,
      end,
      cycles,
      counts,
      classifiedCount: cycles.length - counts.unclassified,
      compressorIntervals,
      blowerIntervals,
      humiditySegments: this._sumpHumidityPoints(humidityEvents, compressorIntervals),
      baseline,
      baselineCount: baselineValues.length,
      rainSource: numericRain ? "numeric" : "binary",
      rainFallbackUsed: cycles.some((cycle) => cycle.rainFallback),
      rainPoints: numericRain
        ? this._sumpRainBars(intensityEvents, start, end, rainMultiplier)
        : this._sumpBinaryRainBars(binaryRainEvents, start, end),
    };
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
      ["observed_alerts", "weekly_digest.observed_alerts"],
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
        const values = items.map((item) => key === "observed_alerts" ? item.display_name : `${item.display_name}: ${this._formatKwh(item.energy_kwh)}`);
        return items.length ? `<h3>${this._escape(this._panelText(label))}</h3>${this._renderSimpleList(values, "")}` : "";
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
      const result = this._savedResult(await this._postJson(`${SETUP_HEALTH_CALL_API_PATH}${query}`, `${SETUP_HEALTH_API_PATH}${query}`, body));
      if (result && result.weekly_digest_settings) {
        this._setupHealth.weekly_digest_settings = result.weekly_digest_settings;
      }
      this._lastActionMessage = this._panelText("messages.weekly_digest_settings_saved");
    } catch (error) {
      this._lastActionMessage = this._panelTextFormat("errors.weekly_digest_settings_save", { message: error.message });
    }
    this._render();
  }

  _savedResult(result) {
    if (result?.status !== "saved") {
      throw new Error(result?.message || result?.status || "Save failed");
    }
    return result;
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
    const status = ["ok", "needs_attention", "optional", "learning"].includes(item.status)
      ? item.status
      : "needs_attention";
    const statusIcon = {
      ok: "mdi:check-circle",
      needs_attention: "mdi:alert-circle",
      optional: "mdi:minus-circle-outline",
      learning: "mdi:progress-clock",
    }[status];
    const statusLabel = this._setupHealthText(`status_labels.${status}`)
      || this._friendlyFeature(status);
    const titleKey = status === "needs_attention"
      ? "title_attention"
      : status === "learning"
        ? "title_learning"
        : "title";
    const title = item.title
      || this._setupHealthChecklistText(item.item_id, titleKey)
      || this._setupHealthChecklistText(item.item_id, "title")
      || this._friendlyFeature(item.item_id || this._setupHealthText("fallbacks.setup_item"));
    const affectedLabel = this._setupHealthText("labels.affected");
    return `
      <div class="metric">
        <span class="metric-heading setup-health-status setup-health-status-${status}">
          <ha-icon icon="${statusIcon}" role="img" aria-label="${this._escape(statusLabel)}" title="${this._escape(statusLabel)}"></ha-icon>
          <strong>${this._escape(title)}</strong>
        </span>
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
    const alerts = Array.isArray(detail.active_alerts) ? detail.active_alerts : [];
    return `
      ${alerts.length ? `<section class="panel appliance-alert-banner">
        <h2>${this._escape(this._panelText("appliance_detail.alerts_and_evidence"))}</h2>
        ${this._renderApplianceAlerts(alerts)}
      </section>` : ""}
      ${this._renderApplianceDetailHistory(payload.history)}
      ${this._renderSumpDriverHistory(detail.sump_driver_context)}
      ${this._renderApplianceDailyCost(payload, detail)}
      <section class="panel">
        <h2>${this._escape(this._panelText("appliance_detail.today_vs_normal"))}</h2>
        ${this._renderApplianceComparisons(detail.today_vs_normal, detail.learning_readiness)}
      </section>
      ${this._renderApplianceBehaviorHealth(detail)}
      ${this._renderWaterFlowContext(detail.water_flow_context)}
      ${this._renderHvacEfficiency(detail.hvac_efficiency)}
    `;
  }

  _renderSumpDriverHistory(context) {
    if (!context) return "";
    const heading = this._panelText("appliance_detail.sump_driver_history");
    if (this._sumpDriverHistoryLoading) {
      return `<section class="panel" data-sump-driver-history><h2>${this._escape(heading)}</h2><div class="loading-skeleton graph-loading-skeleton" data-loading-skeleton role="status" aria-label="${this._escape(this._panelText("chart.loading_history"))}"></div></section>`;
    }
    if (this._sumpDriverHistoryError) {
      return `<section class="panel" data-sump-driver-history><h2>${this._escape(heading)}</h2><p class="muted">${this._escape(this._sumpDriverHistoryError)}</p><button type="button" class="secondary" data-retry-sump-driver-history>${this._escape(this._panelText("common.retry"))}</button></section>`;
    }
    const analysis = this._sumpDriverAnalysis;
    if (!analysis) {
      return `<section class="panel" data-sump-driver-history><h2>${this._escape(heading)}</h2><p class="muted">${this._escape(this._panelText("appliance_detail.sump_driver_unavailable"))}</p></section>`;
    }
    const hidden = this._sumpDriverHiddenLayers instanceof Set
      ? this._sumpDriverHiddenLayers
      : new Set();
    const visible = (layer) => !hidden.has(layer);
    const categoryLabels = {
      rain: this._panelText("appliance_detail.sump_driver_rain"),
      hvac_humidity: this._panelText("appliance_detail.sump_driver_hvac_humidity"),
      combined: this._panelText("appliance_detail.sump_driver_combined"),
      unexplained: this._panelText("appliance_detail.sump_driver_unexplained"),
      unclassified: this._panelText("appliance_detail.sump_driver_unclassified"),
    };
    const colors = {
      rain: "#2563eb",
      hvac_humidity: "#16a34a",
      combined: "#7c3aed",
      unexplained: "#64748b",
      unclassified: "#9ca3af",
    };
    const denominator = analysis.classifiedCount;
    const summary = ["rain", "hvac_humidity", "combined", "unexplained"].map((category) => {
      const count = analysis.counts[category] || 0;
      const percent = denominator ? Math.round((count / denominator) * 100) : 0;
      return `<div class="sump-driver-summary-item"><span class="swatch" style="background:${colors[category]}"></span><strong>${this._escape(`${categoryLabels[category]} ${count} of ${denominator} cycles`)}</strong><span class="muted">${percent}%</span></div>`;
    }).join("");
    const layerButtons = [
      ["rain", this._panelText("appliance_detail.sump_driver_rain_layer"), "#2563eb"],
      ["humidity", this._panelText("appliance_detail.sump_driver_humidity_layer"), "#16a34a"],
      ["compressor", this._panelText("appliance_detail.sump_driver_compressor_layer"), "#f97316"],
      ["blower", this._panelText("appliance_detail.sump_driver_blower_layer"), "#fbbf24"],
      ["cycles", this._panelText("appliance_detail.sump_driver_cycles_layer"), "#7c3aed"],
    ].map(([layer, label, color]) => `<button type="button" class="secondary sump-driver-layer" data-sump-driver-layer="${layer}" aria-pressed="${visible(layer)}"><span class="swatch" style="background:${color}"></span>${this._escape(label)}</button>`).join("");
    const hasHumidity = visible("humidity") && analysis.humiditySegments.length > 0;
    const rainSeries = visible("rain") && analysis.rainPoints.length
      ? [{
          name: analysis.rainSource === "numeric"
            ? this._panelText("appliance_detail.sump_driver_rain_accumulation")
            : this._panelText("appliance_detail.sump_driver_rain_active"),
          unit: analysis.rainSource === "numeric" ? "mm" : "",
          kind: "bar",
          axis: hasHumidity ? "right" : "left",
          color: "#2563eb",
          sump_layer: "rain",
          points: analysis.rainPoints,
        }]
      : [];
    const humiditySeries = hasHumidity
      ? analysis.humiditySegments.map((points) => ({
          name: this._panelText("appliance_detail.sump_driver_humidity"),
          unit: "%",
          color: "#16a34a",
          points,
        }))
      : [];
    if (hasHumidity && analysis.baseline !== null) {
      humiditySeries.push({
        name: this._panelText("appliance_detail.sump_driver_humidity_baseline"),
        unit: "%",
        color: "#15803d",
        line_style: "dashed",
        points: [
          { time: analysis.start, value: analysis.baseline },
          { time: analysis.end, value: analysis.baseline },
        ],
      });
    }
    const contextBands = [
      ...(visible("compressor") ? analysis.compressorIntervals.map((interval) => ({ ...interval, kind: "compressor", label: this._panelText("appliance_detail.sump_driver_compressor_layer"), color: "#f97316", opacity: 0.13 })) : []),
      ...(visible("blower") ? analysis.blowerIntervals.map((interval) => ({ ...interval, kind: "blower", label: this._panelText("appliance_detail.sump_driver_blower_layer"), color: "#fbbf24", opacity: 0.1 })) : []),
    ];
    const eventMarkers = visible("cycles") ? analysis.cycles.map((cycle) => {
      const rainDetail = cycle.rainAmount !== null
        ? `${this._formatNumber(cycle.rainAmount)} mm`
        : cycle.rainActive === null
          ? this._panelText("common.unknown")
          : cycle.rainActive
            ? this._panelText("appliance_detail.sump_driver_active")
            : this._panelText("appliance_detail.sump_driver_inactive");
      const humidityDetail = cycle.humidity === null ? this._panelText("common.unknown") : `${this._formatNumber(cycle.humidity)}%`;
      const blowerDetail = cycle.blower === null ? this._panelText("common.unknown") : cycle.blower ? "yes" : "no";
      const detail = `${categoryLabels[cycle.category]}; ${this._formatDateTime(new Date(cycle.start))}–${this._formatDateTime(new Date(cycle.end))}; Rain: ${rainDetail}; Compressor: ${cycle.compressor ? "yes" : "no"}; Humidity: ${humidityDetail}; Blower support: ${blowerDetail}`;
      return {
        time: cycle.start + (cycle.end - cycle.start) / 2,
        category: cycle.category,
        label: categoryLabels[cycle.category],
        detail,
        color: colors[cycle.category],
      };
    }) : [];
    const graphWindow = this._applianceDetailHistoryGraphWindow() || {
      start: analysis.start,
      end: analysis.end,
    };
    const graph = (rainSeries.length || humiditySeries.length || contextBands.length || eventMarkers.length)
      ? this._chartSvg([...humiditySeries, ...rainSeries], {
          y_axis_label: hasHumidity ? "%" : analysis.rainSource === "numeric" ? "mm" : this._panelText("appliance_detail.sump_driver_rain"),
          ...(hasHumidity && rainSeries.length ? { right_y_axis_label: analysis.rainSource === "numeric" ? "mm" : this._panelText("appliance_detail.sump_driver_rain") } : {}),
          graph_window_start: new Date(graphWindow.start).toISOString(),
          graph_window_end: new Date(graphWindow.end).toISOString(),
          history_entities: this._sumpDriverHistoryEntities(context),
          context_bands: contextBands,
          event_markers: eventMarkers,
          hide_legend: true,
        })
      : `<p class="muted">${this._escape(this._panelText("appliance_detail.sump_driver_no_cycles"))}</p>`;
    const baselineNote = analysis.baseline !== null
      ? this._panelTextFormat("appliance_detail.sump_driver_baseline_ready", { value: this._formatNumber(analysis.baseline), count: analysis.baselineCount })
      : this._panelTextFormat("appliance_detail.sump_driver_baseline_learning", { count: analysis.baselineCount, required: 15 });
    return `<section class="panel" data-sump-driver-history>
      <div class="appliance-section-heading"><h2>${this._escape(heading)}</h2><span class="status">${this._escape(`${analysis.cycles.length} ${this._panelText("appliance_detail.sump_driver_completed_cycles")}`)}</span></div>
      <div class="sump-driver-summary">${summary}</div>
      ${analysis.counts.unclassified ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.sump_driver_unclassified_note", { count: analysis.counts.unclassified }))}</p>` : ""}
      <div class="sump-driver-layers" role="group" aria-label="${this._escape(this._panelText("appliance_detail.sump_driver_layers"))}">${layerButtons}</div>
      ${graph}
      <p class="muted">${this._escape(baselineNote)}</p>
      ${analysis.rainSource === "binary" || analysis.rainFallbackUsed ? `<p class="muted">${this._escape(this._panelText("appliance_detail.sump_driver_binary_rain_note"))}</p>` : ""}
      <p class="muted">${this._escape(this._panelText("appliance_detail.sump_driver_disclaimer"))}</p>
    </section>`;
  }

  _renderApplianceBehaviorHealth(detail) {
    const expectations = detail.expectations;
    const timeline = detail.recent_timeline;
    let health = detail.appliance_health;
    const humanize = (value) => String(value || "")
      .replaceAll("_", " ")
      .replace(/^\w/, (letter) => letter.toUpperCase());
    const hasHealth = health && typeof health === "object" && !Array.isArray(health);
    health = hasHealth ? health : {};
    const status = String(health.status || "learning");
    const reason = String(health.reason || "");
    const statusLabel = this._panelText(`appliance_detail.predictive_health_status.${status}`) || humanize(status);
    const reasonLabel = this._panelText(`appliance_detail.predictive_health_reason.${reason}`) || humanize(reason);
    const sessionEvidence = health.feature === "repeated_short_cycle";
    const scope = sessionEvidence ? "sessions" : "days";
    const facts = [
      health.feature
        ? this._metric(this._panelText("appliance_detail.predictive_health_finding"), humanize(health.feature), "mdi:stethoscope")
        : "",
      Number.isFinite(Number(health.change_percent))
        ? this._metric(this._panelText("appliance_detail.predictive_health_change"), `${Number(health.change_percent)}%`, "mdi:percent")
        : "",
      Number.isFinite(Number(health.reference_count))
        ? this._metric(this._panelText("appliance_detail.predictive_health_reference"), `${Number(health.reference_count)} reference ${scope}`, "mdi:database-clock-outline")
        : "",
      Number.isFinite(Number(health.recent_count))
        ? this._metric(this._panelText("appliance_detail.predictive_health_recent"), `${Number(health.recent_count)} recent ${scope}`, "mdi:history")
        : "",
      health.last_eligible_date_or_session
        ? this._metric(this._panelText("appliance_detail.predictive_health_latest"), health.last_eligible_date_or_session, "mdi:calendar-check-outline")
        : "",
    ].filter(Boolean);
    const context = Object.entries(
      health.context && typeof health.context === "object" ? health.context : {},
    ).map(([key, value]) => `${key.replaceAll("_", " ")}: ${value}`);
    return `<section class="panel" data-appliance-behavior-health>
      <h2>${this._escape(this._panelText("appliance_detail.behavior_and_predictive_health"))}</h2>
      <div class="appliance-behavior-grid">
        <div class="appliance-detail-block" data-behavior-expectations>
          <h3><ha-icon icon="mdi:bullseye-arrow"></ha-icon>${this._escape(this._panelText("appliance_detail.behavior_expectations"))}</h3>
          ${this._renderApplianceExpectations(expectations)}
          <div class="appliance-predictive-health">
            <h3><ha-icon icon="mdi:heart-pulse"></ha-icon>${this._escape(this._panelText("appliance_detail.predictive_health"))}</h3>
            ${hasHealth ? `<p><strong>${this._escape(statusLabel)}</strong></p>
            ${reasonLabel ? `<p class="muted">${this._escape(reasonLabel)}</p>` : ""}
            ${facts.length ? `<div class="summary appliance-health-metrics">${facts.join("")}</div>` : ""}
            ${context.length ? `<p class="muted">${this._escape(this._panelText("appliance_detail.predictive_health_context"))}: ${this._escape(context.join(" · "))}</p>` : ""}` : `<p class="muted">${this._escape(this._panelText("common.unknown"))}</p>`}
          </div>
        </div>
        <div class="appliance-detail-block" data-appliance-now>
          <h3><ha-icon icon="mdi:clock-outline"></ha-icon>${this._escape(this._panelText("appliance_insights.columns.now"))}</h3>
          <div class="summary">
            ${this._metric(this._panelText("appliance_detail.activity"), detail.activity_state, "mdi:play-circle-outline")}
            ${this._metric(this._panelText("appliance_detail.power"), this._formatPower(detail.current_power_w), "mdi:flash-outline")}
            ${this._metric(this._panelText("appliance_detail.health"), detail.health_state, "mdi:heart-pulse")}
            ${this._metric(this._panelText("appliance_detail.energy"), detail.energy_state, "mdi:chart-line")}
          </div>
        </div>
        <div class="appliance-detail-block">
          <h3><ha-icon icon="mdi:history"></ha-icon>${this._escape(this._panelText("appliance_detail.recent_timeline"))}</h3>
          ${this._renderApplianceTimeline(timeline)}
        </div>
      </div>
    </section>`;
  }

  _renderWaterFlowContext(context) {
    if (!context || typeof context !== "object") return "";
    const number = (key) => this._finiteMetricValue(context[key]);
    const minutes = (key) => {
      const value = number(key);
      return value === null ? "" : `${this._formatNumber(value)} min`;
    };
    const status = String(context.status || "unconfigured");
    const statusLabel = this._panelText(
      `appliance_detail.water_flow_status.${status}`,
    ) || this._friendlyFeature(status);
    const flowState = context.flow_sensor_active === true
      ? this._panelText("appliance_detail.water_flow_active")
      : context.flow_sensor_active === false
        ? this._panelText("appliance_detail.water_flow_inactive")
        : "";
    const confidence = number("confidence");
    const facts = [
      flowState
        ? this._metric(
          this._panelText("appliance_detail.water_flow_state"),
          flowState,
          "mdi:water",
        )
        : "",
      minutes("flow_active_minutes")
        ? this._metric(
          this._panelText("appliance_detail.water_flow_active_minutes"),
          minutes("flow_active_minutes"),
          "mdi:timer-outline",
        )
        : "",
      minutes("appliance_runtime_minutes")
        ? this._metric(
          this._panelText("appliance_detail.water_flow_appliance_runtime"),
          minutes("appliance_runtime_minutes"),
          "mdi:washing-machine",
        )
        : "",
      minutes("mismatch_minutes")
        ? this._metric(
          this._panelText("appliance_detail.water_flow_mismatch_minutes"),
          minutes("mismatch_minutes"),
          "mdi:pipe-leak",
        )
        : "",
      minutes("flow_mismatch_threshold_minutes")
        ? this._metric(
          this._panelText("appliance_detail.water_flow_mismatch_threshold"),
          minutes("flow_mismatch_threshold_minutes"),
          "mdi:tune",
        )
        : "",
      confidence !== null
        ? this._metric(
          this._panelText("common.confidence"),
          this._formatConfidence(confidence),
          "mdi:chart-bell-curve-cumulative",
        )
        : "",
    ].filter(Boolean);
    const learning = context.learning && typeof context.learning === "object"
      ? context.learning
      : {};
    const observed = this._finiteMetricValue(
      learning.comparable_window_count,
    ) ?? 0;
    const required = this._finiteMetricValue(
      learning.required_comparable_windows,
    ) ?? 0;
    const mapped = [
      number("mapped_appliance_count") !== null
        ? `${this._panelText("appliance_detail.water_flow_mapped_appliances")}: ${this._formatNumber(number("mapped_appliance_count"))}`
        : "",
      minutes("mapped_appliance_runtime_minutes")
        ? `${this._panelText("appliance_detail.water_flow_mapped_runtime")}: ${minutes("mapped_appliance_runtime_minutes")}`
        : "",
      minutes("recent_related_runtime_minutes")
        ? `${this._panelText("appliance_detail.water_flow_recent_related_runtime")}: ${minutes("recent_related_runtime_minutes")}`
        : "",
      context.recent_flow_explains_activity === true
        ? this._panelText(
          "appliance_detail.water_flow_recent_explains_activity",
        )
        : "",
    ].filter(Boolean);
    const sources = Array.isArray(context.flow_sensors)
      ? context.flow_sensors.map((source) => (
        source && typeof source === "object"
          ? String(source.name || source.entity_id || "")
          : ""
      )).filter(Boolean)
      : [];
    const friendlySummary = String(context.friendly_summary || "");

    return `<section class="panel" data-water-flow-context>
      <div class="appliance-section-heading"><h2>${this._escape(this._panelText("appliance_detail.water_flow_context"))}</h2><span class="status">${this._escape(statusLabel)}</span></div>
      ${friendlySummary ? `<p class="muted">${this._escape(friendlySummary)}</p>` : ""}
      ${facts.length ? `<div class="summary appliance-health-metrics">${facts.join("")}</div>` : ""}
      <p class="muted">${this._escape(`${this._formatNumber(observed)} of ${this._formatNumber(required)} ${this._panelText("appliance_detail.water_flow_comparable_windows")}`)}</p>
      ${mapped.length ? `<p class="muted">${this._escape(mapped.join(" · "))}</p>` : ""}
      ${sources.length ? `<p class="muted">${this._escape(this._panelText("appliance_detail.water_flow_sources"))}: ${this._escape(sources.join(", "))}</p>` : ""}
    </section>`;
  }

  _renderHvacEfficiency(efficiency) {
    if (!efficiency || typeof efficiency !== "object") return "";
    const finite = (value) => value !== null
      && value !== undefined
      && value !== ""
      && Number.isFinite(Number(value));
    const temperatureUnit = String(
      this._hass?.config?.unit_system?.temperature || "",
    ).trim();
    const celsius = temperatureUnit === "°C";
    const temperatureValue = (value) => celsius
      ? (Number(value) - 32) / 1.8
      : Number(value);
    const status = String(efficiency.status || "learning");
    const statusLabel = this._panelText(`appliance_detail.hvac_efficiency_status.${status}`)
      || this._panelText("appliance_detail.hvac_efficiency_status.learning");
    const trend = String(efficiency.trend || "");
    const trendLabel = trend
      ? this._panelText(`appliance_detail.hvac_efficiency_trend.${trend}`)
      : "";
    const learning = efficiency.learning && typeof efficiency.learning === "object"
      ? efficiency.learning
      : {};
    const renderMode = (mode) => {
      const rows = Array.isArray(efficiency[mode]) ? efficiency[mode] : [];
      if (!rows.length) return "";
      return `<div class="hvac-efficiency-mode" data-hvac-mode="${mode}">
        <h3>${this._escape(this._panelText(`appliance_detail.hvac_efficiency_mode.${mode}`))}</h3>
        ${rows.map((row) => {
          const attribution = this._panelText(`appliance_detail.hvac_efficiency_attribution.${row.attribution || "direct"}`);
          const facts = [
            row.thermostat_name || row.thermostat_entity_id
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_thermostat"), row.thermostat_name || row.thermostat_entity_id, "mdi:thermostat")
              : "",
            this._metric(this._panelText("appliance_detail.hvac_efficiency_mode_label"), this._panelText(`appliance_detail.hvac_efficiency_mode.${mode}`), "mdi:hvac"),
            finite(row.score)
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_score"), `${this._formatNumber(row.score)} / 100`, "mdi:gauge")
              : "",
            finite(row.baseline_runtime_minutes)
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_baseline"), `${this._formatNumber(row.baseline_runtime_minutes)} min`, "mdi:database-clock-outline")
              : "",
            finite(row.recent_runtime_minutes)
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_recent"), `${this._formatNumber(row.recent_runtime_minutes)} min`, "mdi:history")
              : "",
            finite(row.outdoor_temperature_f)
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_outdoor_temperature"), `${this._formatNumber(temperatureValue(row.outdoor_temperature_f))}${temperatureUnit}`, "mdi:weather-sunny")
              : "",
            row.season
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_season"), row.season, "mdi:calendar-season")
              : "",
            row.weather_mode
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_weather_context"), row.weather_mode, "mdi:cloud-outline")
              : "",
            row.attribution
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_attribution_label"), attribution, "mdi:account-check-outline")
              : "",
            finite(row.reference_count)
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_reference_episodes"), `${row.reference_count} of ${Number(learning.required_reference || 50)} reference core days`, "mdi:counter")
              : "",
            finite(row.recent_count)
              ? this._metric(this._panelText("appliance_detail.hvac_efficiency_recent_episodes"), `${row.recent_count} of ${Number(learning.required_recent || 5)} recent core days`, "mdi:counter")
              : "",
          ].filter(Boolean);
          return `<article class="hvac-efficiency-row">
            ${facts.length ? `<div class="summary appliance-health-metrics">${facts.join("")}</div>` : ""}
            ${Array.isArray(row.supporting_blower_ids) && row.supporting_blower_ids.length
              ? `<p class="muted">${this._escape(this._panelText("appliance_detail.hvac_efficiency_supporting_blower"))}</p>`
              : ""}
          </article>`;
        }).join("")}
      </div>`;
    };
    const modes = `${renderMode("heating")}${renderMode("cooling")}`;
    const score = finite(efficiency.summary_score) ? Number(efficiency.summary_score) : null;
    const gauge = score !== null
      ? `<div class="hvac-efficiency-gauge" role="img" aria-label="${this._escape(`${this._panelText("appliance_detail.hvac_efficiency_score")}: ${this._formatNumber(score)} / 100`)}" style="--hvac-score:${Math.max(0, Math.min(200, score)) / 4}%"><strong>${this._escape(this._formatNumber(score))}</strong></div>`
      : `<div class="hvac-efficiency-gauge learning" data-hvac-learning="true" role="status" aria-label="${this._escape(statusLabel)}"><strong>—</strong></div>`;
    const learningProgress = `<div class="summary appliance-health-metrics hvac-learning-progress">
      ${this._metric(this._panelText("appliance_detail.hvac_efficiency_reference_episodes"), `${Number(learning.reference_count || 0)} / ${Number(learning.required_reference || 50)}`, "mdi:database-clock-outline")}
      ${this._metric(this._panelText("appliance_detail.hvac_efficiency_recent_episodes"), `${Number(learning.recent_count || 0)} / ${Number(learning.required_recent || 5)}`, "mdi:history")}
    </div>`;
    return `<section class="panel" data-hvac-efficiency>
      <div class="appliance-section-heading"><h2>${this._escape(this._panelText("appliance_detail.hvac_efficiency"))}</h2><span class="status">${this._escape(trendLabel || statusLabel)}</span></div>
      <div class="hvac-efficiency-layout">
        <div class="hvac-efficiency-score">
          ${gauge}
          <strong>${this._escape(this._panelText("appliance_detail.hvac_efficiency_score"))}</strong>
          ${score !== null ? `<span class="muted">${this._escape(this._panelText("appliance_detail.hvac_efficiency_score_note"))}</span>` : ""}
        </div>
        <div class="hvac-efficiency-thermostats">
          ${modes || `${learningProgress}<p class="muted">${this._escape(this._panelText("appliance_detail.hvac_efficiency_waiting"))}</p>`}
        </div>
      </div>
      ${finite(efficiency.threshold_pct) ? `<p class="muted hvac-efficiency-threshold">${this._escape(this._panelTextFormat("appliance_detail.hvac_efficiency_threshold_note", { value: `${this._formatNumber(efficiency.threshold_pct)}%` }))}</p>` : ""}
    </section>`;
  }

  _renderApplianceDailyCost(payload, detail) {
    const rows = Array.isArray(payload.daily_totals) ? payload.daily_totals : [];
    const dailyDateTimestamp = (value) => {
      const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
      if (!match) return Number.NaN;
      const [year, month, day] = match.slice(1).map(Number);
      const utcNoon = Date.UTC(year, month - 1, day, 12);
      const utcDate = new Date(utcNoon);
      if (utcDate.getUTCFullYear() !== year || utcDate.getUTCMonth() !== month - 1 || utcDate.getUTCDate() !== day) return Number.NaN;
      try {
        const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
          timeZone: this._timeZone(), year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
        }).formatToParts(utcDate).map((part) => [part.type, part.value]));
        return utcNoon - (Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute)) - utcNoon);
      } catch (_error) {
        return utcNoon;
      }
    };
    const series = (key) => rows.map((row) => ({
      time: dailyDateTimestamp(row.date),
      value: row[key] === null || row[key] === undefined ? Number.NaN : Number(row[key]),
    })).filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value));
    const energy = series("energy_kwh");
    const cost = series("cost");
    const currency = this._currencySymbol();
    const dailySeries = [
      energy.length && { name: this._panelText("appliance_detail.kwh_per_day"), unit: "kWh", points: energy },
      cost.length && { name: this._panelText("appliance_detail.cost_per_day"), unit: "currency", axis: energy.length ? "right" : "left", points: cost },
    ].filter(Boolean);
    const charts = dailySeries.length ? this._chartSvg(dailySeries, {
      y_axis_label: energy.length ? "kWh" : currency,
      ...(energy.length && cost.length ? { right_y_axis_label: currency } : {}),
    }) : "";
    return `<section class="panel" data-appliance-daily-cost>
      <h2>${this._escape(this._panelText("appliance_detail.daily_cost_and_energy"))}</h2>
      ${charts || `<p class="muted">${this._escape(this._panelText("appliance_detail.no_completed_days"))}</p>`}
      <div class="summary appliance-daily-metrics">
        ${this._metric(this._panelText("appliance_detail.kwh_today"), this._formatKwh(detail.daily_energy_kwh), "mdi:calendar-today")}
        ${this._metric(this._panelText("appliance_detail.average_kwh_per_day"), this._formatKwh(detail.average_kwh_per_day), "mdi:chart-line")}
        ${this._metric(this._panelText("appliance_detail.cost_today"), this._formatCost(detail.cost_today), "mdi:cash")}
        ${this._metric(this._panelText("appliance_detail.average_cost_per_day"), this._formatCost(detail.average_cost_per_day), "mdi:cash-multiple")}
      </div>
    </section>`;
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
    const groupedSeries = this._applianceDetailHistoryChartGroups(series);
    const powerFactorIndex = groupedSeries.findIndex(({ unit }) => unit === "PF");
    const ampsIndex = groupedSeries.findIndex(({ unit }) => unit === "A");
    if (powerFactorIndex >= 0 && ampsIndex >= 0 && powerFactorIndex !== ampsIndex + 1) {
      const [powerFactor] = groupedSeries.splice(powerFactorIndex, 1);
      groupedSeries.splice(groupedSeries.findIndex(({ unit }) => unit === "A") + 1, 0, powerFactor);
    }
    const chartOptions = {
      graph_window_start: window ? new Date(window.start).toISOString() : "",
      graph_window_end: window ? new Date(window.end).toISOString() : "",
    };
    const graph = this._applianceDetailHistoryLoading
      ? `<div class="loading-skeleton graph-loading-skeleton" data-loading-skeleton role="status" aria-label="${this._escape(this._panelText("chart.loading_history"))}"></div>`
      : this._applianceDetailHistoryError
        ? `<div data-appliance-history-error><p class="muted">${this._escape(this._applianceDetailHistoryError)}</p><button type="button" class="secondary" data-retry-appliance-history>${this._escape(this._panelText("common.retry"))}</button></div>`
        : window && groupedSeries.length
          ? groupedSeries.map(({ unit, rightUnit, series: unitSeries }) => this._chartSvg(
            unitSeries,
            Object.assign({}, chartOptions, {
              y_axis_label: unit,
              ...(rightUnit ? { right_y_axis_label: rightUnit } : {}),
            }),
          )).join("")
          : `<p class="muted">${this._escape(this._panelText("appliance_detail.no_history"))}</p>`;
    return `
      <section class="panel" data-appliance-detail-history>
        <div class="appliance-graph-heading">
          <h2>${this._escape(this._panelText("appliance_detail.graphs"))}</h2>
          <div class="appliance-graph-toolbar">
            <div class="appliance-period-controls" role="group" aria-label="${this._escape(this._panelText("appliance_detail.time_period"))}">
              ${periodHours.map((hours) => `<button type="button" class="secondary appliance-period-button" data-appliance-history-period="${hours}" aria-pressed="${hours === this._applianceDetailHistoryHours}">${this._escape(this._applianceHistoryPeriodLabel(hours))}</button>`).join("")}
            </div>
            ${this._renderApplianceHistoryGraphControls(window)}
          </div>
        </div>
        ${graph}
      </section>
    `;
  }

  _applianceDetailHistoryChartGroups(series) {
    const visible = series.filter((item) => {
      const unit = String(item.unit || "").toLowerCase();
      const entityId = String(item.entity_id || "").toLowerCase();
      return !unit.endsWith("va")
        && !unit.endsWith("var")
        && !/(?:^|_)(?:apparent_power|reactive_power)(?:_|$)|(?:^|_)(?:[km]?va|[km]?var)$/.test(entityId);
    });
    const watts = visible.filter((item) => item.unit === "W");
    const amps = visible.filter((item) => item.unit === "A");
    const groups = [];
    if (watts.length || amps.length) {
      groups.push({
        unit: watts.length ? "W" : "A",
        rightUnit: watts.length && amps.length ? "A" : "",
        series: [...watts, ...amps.map((item) => ({ ...item, axis: watts.length ? "right" : "left" }))],
      });
    }
    groups.push(...this._chartSeriesByUnit(
      visible.filter((item) => !["W", "A"].includes(String(item.unit))),
    ).map((group) => ({ ...group, rightUnit: "" })));
    return groups;
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
    const rawItems = Array.isArray(timeline && timeline.items) ? timeline.items : [];
    const seen = new Set();
    const items = rawItems.filter((item) => {
      const timestamp = Date.parse(item.timestamp || "");
      const displayedMinute = Number.isFinite(timestamp)
        ? Math.floor(timestamp / 60000)
        : item.timestamp;
      const key = [displayedMinute, item.title, item.detail].join("\u0000");
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
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

  _renderApplianceComparisons(comparisons, learningReadiness = {}) {
    const items = (Array.isArray(comparisons) ? comparisons : []).filter((item) => (
      item.current_value !== null
      && item.current_value !== undefined
      && (item.metric_id === "cost_today"
        || (item.normal_low !== null && item.normal_low !== undefined && item.normal_high !== null && item.normal_high !== undefined)
        || (item.full_period_normal_low !== null && item.full_period_normal_low !== undefined && item.full_period_normal_high !== null && item.full_period_normal_high !== undefined)
        || (item.configured_warning_value !== null && item.configured_warning_value !== undefined)
        || (item.configured_limit_value !== null && item.configured_limit_value !== undefined))
    ));
    if (!items.length) {
      const complete = Number(learningReadiness.days_complete);
      const required = Number(learningReadiness.days_required);
      if (Number.isFinite(complete) && Number.isFinite(required) && required > 0) {
        return `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.learning_progress", { complete, required }))}</p>`;
      }
      return `<p class="muted">${this._escape(learningReadiness.label || this._panelText("appliance_detail.learning_ranges"))}</p>`;
    }
    const asOf = items.find((item) => item.as_of)?.as_of;
    const icons = {
      current_power_w: "mdi:flash-outline",
      daily_energy_kwh: "mdi:chart-line",
      runtime_today_seconds: "mdi:timer-outline",
      run_count_today: "mdi:counter",
      demand_peak_w: "mdi:flash-triangle-outline",
      cost_today: "mdi:cash",
    };
    return `${asOf ? `<p class="muted appliance-comparison-as-of">${this._escape(this._panelTextFormat("appliance_detail.as_of", { timestamp: this._formatDateTime(asOf) }))}</p>` : ""}
      <table class="appliance-comparison-table" data-appliance-comparison-table>
        <thead><tr><th>Metric</th><th>Today</th><th>Normal</th><th>Projected</th></tr></thead>
        <tbody>${items.map((item) => {
      const normal = item.normal_low !== null && item.normal_low !== undefined && item.normal_high !== null && item.normal_high !== undefined
        ? `${this._formatComparisonValue(item, item.normal_low)} - ${this._formatComparisonValue(item, item.normal_high)}`
        : this._panelText("common.learning");
      const hasProjection = item.projection_value !== null && item.projection_value !== undefined;
      const fullPeriod = item.full_period_normal_low !== null && item.full_period_normal_low !== undefined && item.full_period_normal_high !== null && item.full_period_normal_high !== undefined
        ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.completed_day_normal_range", { low: this._formatComparisonValue(item, item.full_period_normal_low), high: this._formatComparisonValue(item, item.full_period_normal_high) }))}</p>`
        : "";
      const configuredWarning = item.configured_warning_value !== null && item.configured_warning_value !== undefined
        ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.configured_warning", { value: this._formatComparisonValue({ unit: item.limit_unit || item.unit }, item.configured_warning_value) }))}</p>`
        : "";
      const configuredLimit = item.configured_limit_value !== null && item.configured_limit_value !== undefined
        ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.configured_limit", { value: this._formatComparisonValue({ unit: item.limit_unit || item.unit }, item.configured_limit_value) }))}</p>`
        : "";
      const projection = hasProjection
        ? `<strong>${this._escape(this._formatComparisonValue(item, item.projection_value))}</strong>
          ${item.projection_low !== null && item.projection_low !== undefined && item.projection_high !== null && item.projection_high !== undefined ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.projected_range", { low: this._formatComparisonValue(item, item.projection_low), high: this._formatComparisonValue(item, item.projection_high) }))}</p>` : ""}`
        : this._panelText("common.unknown");
      return `
        <tr>
          <td data-label="Metric"><ha-icon icon="${icons[item.metric_id] || "mdi:chart-line"}"></ha-icon> ${this._escape(item.label || this._friendlyFeature(item.metric_id))}</td>
          <td data-label="Today"><strong>${this._escape(this._formatComparisonValue(item, item.current_value))}</strong><p class="muted">${this._escape(this._friendlyFeature(item.status))}</p>${configuredWarning}${configuredLimit}</td>
          <td data-label="Normal"><strong>${this._escape(normal)}</strong>${fullPeriod}</td>
          <td data-label="Projected">${projection}</td>
        </tr>`;
    }).join("")}</tbody></table>`;
  }

  _renderApplianceExpectations(expectations) {
    const items = Array.isArray(expectations) ? expectations : [];
    if (!items.length) {
      return `<p class="muted">${this._escape(this._panelText("appliance_detail.not_enough_expectations"))}</p>`;
    }
    return `<div class="entity-list">${items.map((item) => `
      <div class="metric">
        <span>${this._escape(this._friendlyFeature(item.status))}</span>
        <strong class="appliance-expectation-title">${this._escape(item.title || this._panelText("appliance_detail.expectation_title"))}</strong>
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

  _zoomApplianceHistoryGraph(factor) {
    const window = this._applianceDetailHistoryGraphWindow();
    if (!window || !Number.isFinite(factor) || factor <= 0) {
      return undefined;
    }
    const hour = 60 * 60 * 1000;
    const span = window.end - window.start;
    const fullSpan = window.max - window.min;
    if (factor < 1 || span < fullSpan) {
      const nextSpan = factor < 1
        ? span > 168 * hour
          ? 168 * hour
          : span > 24 * hour
            ? 24 * hour
            : Math.max(15 * 60 * 1000, span * factor)
        : span < 24 * hour
          ? Math.min(24 * hour, fullSpan)
          : span < 168 * hour
            ? Math.min(168 * hour, fullSpan)
            : fullSpan;
      const center = (window.start + window.end) / 2;
      this._setGraphWindow(
        center - nextSpan / 2,
        center + nextSpan / 2,
        window,
        (next) => { this._applianceDetailHistoryWindow = next; },
      );
      return undefined;
    }
    const history = this._applianceDetail && this._applianceDetail.history;
    const periods = Array.isArray(history && history.period_hours)
      ? history.period_hours.map(Number).filter(Number.isFinite).sort((left, right) => left - right)
      : [];
    const currentIndex = periods.indexOf(Number(this._applianceDetailHistoryHours));
    if (currentIndex < 0) {
      return undefined;
    }
    const nextIndex = Math.min(currentIndex + 1, periods.length - 1);
    if (nextIndex === currentIndex) {
      return undefined;
    }
    return this._loadApplianceDetailHistories(
      periods[nextIndex],
      this._evidenceRequestId,
      this._loadedRouteKey || this._routeKey(),
    );
  }

  _actionableApplianceChecks(checks) {
    return (Array.isArray(checks) ? checks : []).filter((item) => {
      const text = String(item || "").trim();
      return text && !/^no .+ (?:is |are )?needed/i.test(text) && !/^no action needed/i.test(text);
    });
  }

  _applianceDetailHeaderMessage(detail, payload = {}) {
    const nextStep = String((detail && detail.next_step) || (payload && payload.next_step) || "").trim();
    if (nextStep && !/alert|evidence/i.test(nextStep)) {
      return nextStep;
    }
    return this._panelText("headers.appliance_detail_message");
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
    const history = this._applianceDetail && this._applianceDetail.history;
    const canLoadMore = Array.isArray(history && history.period_hours)
      && history.period_hours.some((hours) => Number(hours) > this._applianceDetailHistoryHours);
    return this._renderHistoryGraphControls(
      window,
      "appliance-history-graph",
      "data-appliance-history-graph",
      this._panelTextFormat("appliance_detail.history_window", { start: this._formatDateTime(new Date(window.start)), end: this._formatDateTime(new Date(window.end)) }),
      canLoadMore,
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
