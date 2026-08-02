export function createNilmWorkspaceMethods({
  NILM_WORKSPACE_API_PATH,
  NILM_WORKSPACE_CALL_API_PATH,
  NILM_LOW_CONFIDENCE_THRESHOLD,
  EXPAND_NILM_QUERY_PARAM,
  NILM_WORKSPACE_QUERY_PARAM,
  NILM_EDGE_SNAP_MS,
  MAX_NILM_CHART_POINTS_PER_SERIES,
}) {
  return class NilmWorkspaceMethods {
  async _loadNilmWorkspace(requestId = this._evidenceRequestId, routeKey = this._loadedRouteKey) {
    if (!this._routeRequestsNilmWorkspace(routeKey)) {
      return;
    }
    const { apiPath, fetchPath } = this._nilmWorkspaceRequestPaths(routeKey);
    if (!apiPath) {
      return;
    }

    this._invalidateNilmFocusedHistoryRequests();
    this._nilmWorkspaceLoading = true;
    this._nilmWorkspaceError = "";
    this._nilmWorkspaceHistoryError = "";
    this._nilmWorkspaceHistoryFailedRequest = null;
    this._nilmWorkspaceHistorySeries = [];
    this._render();

    try {
      const workspace = await this._requestJson(apiPath || NILM_WORKSPACE_CALL_API_PATH, fetchPath);
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._nilmWorkspace = workspace;
      await this._loadNilmWorkspaceHistory(workspace, requestId, routeKey);
      const routeUrl = new URL(routeKey, window.location.origin);
      const sessionId = routeUrl.searchParams.get("session_id") || "";
      const routedSession = sessionId && Array.isArray(workspace.sessions)
        ? workspace.sessions.find((session) => session.session_id === sessionId)
        : null;
      if (routedSession) {
        this._loadNilmSessionInterval(routedSession);
      }
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._nilmWorkspace = null;
      this._nilmWorkspaceError = this._panelTextFormat("errors.load_nilm_workspace", { message: error.message });
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._nilmWorkspaceLoading = false;
        this._render();
      }
    }
  }

  _nilmWorkspaceRequestPaths(routeKey = this._loadedRouteKey || this._routeKey()) {
    const nilm = this._payload && this._payload.nilm;
    const routeUrl = new URL(routeKey, window.location.origin);
    const circuit = this._payload && this._payload.circuit;
    const circuitId = (circuit && circuit.circuit_id) || routeUrl.searchParams.get("circuit_id") || "";
    const entryId = routeUrl.searchParams.get("entry_id") || "";
    const params = new URLSearchParams();
    if (circuitId) {
      params.set("circuit_id", circuitId);
    }
    if (entryId) {
      params.set("entry_id", entryId);
    }
    const query = params.toString();
    const routeApiPath = routeUrl.searchParams.get(NILM_WORKSPACE_QUERY_PARAM) === "1" && query
      ? `${NILM_WORKSPACE_CALL_API_PATH}?${query}`
      : "";
    return {
      apiPath: (nilm && nilm.workspace_call_api_path) || routeApiPath,
      fetchPath: (nilm && nilm.workspace_api_path) || `${NILM_WORKSPACE_API_PATH}?${query}`,
    };
  }

  async _refreshNilmWorkspaceData(
    requestId = this._evidenceRequestId,
    routeKey = this._loadedRouteKey || this._routeKey(),
  ) {
    if (!this._routeRequestsNilmWorkspace(routeKey)) {
      return false;
    }
    let cycle = this._nilmWorkspaceRefreshCycle;
    if (!cycle || cycle.requestId !== requestId || cycle.routeKey !== routeKey) {
      cycle = { requestId, routeKey, requested: 0, running: false, task: null };
      this._nilmWorkspaceRefreshCycle = cycle;
    }
    cycle.requested += 1;
    if (!cycle.task || !cycle.running) {
      cycle.running = true;
      cycle.task = (async () => {
        try {
          while (true) {
            if (cycle !== this._nilmWorkspaceRefreshCycle
                || !this._isCurrentRequest(requestId, routeKey)) {
              return false;
            }
            const generation = cycle.requested;
            const { apiPath, fetchPath } = this._nilmWorkspaceRequestPaths(routeKey);
            if (!apiPath) {
              return false;
            }
            let workspace;
            try {
              workspace = await this._requestJson(apiPath, fetchPath);
            } catch (_error) {
              if (generation === cycle.requested) {
                return false;
              }
              continue;
            }
            if (cycle !== this._nilmWorkspaceRefreshCycle
                || !this._isCurrentRequest(requestId, routeKey)) {
              return false;
            }
            if (generation !== cycle.requested) {
              continue;
            }
            this._invalidateNilmFocusedHistoryRequests();
            this._nilmWorkspaceHistoryLoading = false;
            this._nilmWorkspaceHistoryError = "";
            this._nilmWorkspaceHistoryFailedRequest = null;
            this._nilmWorkspace = workspace;
            return true;
          }
        } finally {
          cycle.running = false;
        }
      })();
    }
    const task = cycle.task;
    try {
      return await task;
    } finally {
      if (cycle.task === task) {
        cycle.task = null;
      }
    }
  }

  async _loadNilmWorkspaceHistory(
    workspace = this._nilmWorkspace,
    requestId = this._evidenceRequestId,
    routeKey = this._loadedRouteKey,
  ) {
    if (!this._routeRequestsNilmWorkspace(routeKey)) {
      return;
    }
    const historyPath = workspace && workspace.history && workspace.history.api_path;
    const historyFetchPath = (workspace && workspace.history && workspace.history.fetch_path)
      || (historyPath ? `/api/${historyPath}` : "");
    this._nilmWorkspaceHistoryError = "";
    this._nilmWorkspaceHistoryFailedRequest = null;
    this._nilmWorkspaceHistorySeries = [];
    if (!historyPath) {
      return;
    }
    this._nilmWorkspaceHistoryLoading = true;
    this._render();
    try {
      const history = await this._requestJson(historyPath, historyFetchPath);
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._nilmWorkspaceHistorySeries = Array.isArray(history) ? history : [];
      this._nilmWorkspaceHistoryError = "";
      this._nilmWorkspaceHistoryFailedRequest = null;
    } catch (error) {
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      this._nilmWorkspaceHistoryError = this._panelTextFormat("errors.load_nilm_workspace_history", { message: error.message });
    } finally {
      if (this._isCurrentRequest(requestId, routeKey)) {
        this._nilmWorkspaceHistoryLoading = false;
        this._render();
      }
    }
  }

  async _applyNilmDecision(index) {
    const signature = this._nilmReviewSignatures()[index];
    if (!signature) {
      return;
    }
    const key = this._nilmDecisionDraftKey(signature);
    const draft = this._nilmDecisionDraft(signature);
    const identifyMode = signature.actions && signature.actions[draft.identifyMode]
      ? draft.identifyMode
      : signature.actions && signature.actions.assign
        ? "assign"
        : "label";
    const actionKey = draft.decision === "identify" ? identifyMode : draft.decision;
    if (!actionKey) {
      this._setInlineFeedback(key, "error", this._panelText("errors.nilm_decision_required"));
      return;
    }
    await this._callNilmAction(index, actionKey, key);
  }

  async _callNilmAction(index, actionKey, feedbackScope) {
    const signatures = this._nilmReviewSignatures();
    const signature = signatures && signatures[index];
    const action = signature && signature.actions && signature.actions[actionKey];
    if (!this._guardActionCall(action, `NILM ${actionKey}`, feedbackScope)) {
      return;
    }
    const reject = (message) => this._setInlineFeedback(feedbackScope, "error", message);
    const data = Object.assign({}, action.data || {});
    if (actionKey === "label" || actionKey === "assign") {
      const labelInput = this.shadowRoot.querySelector(`#nilm_label_${index}`);
      const existingAssignment = actionKey === "assign" ? this._nilmExistingAssignmentSelection(`signature_${index}`) : null;
      const label = existingAssignment ? existingAssignment.label : labelInput ? labelInput.value.trim() : "";
      if (!label) {
        reject(this._panelText("errors.nilm_signature_label_required"));
        return;
      }
      data.label = label;
      if (existingAssignment) {
        data.assignment_id = existingAssignment.assignment_id;
      }
    }
    if (actionKey === "merge") {
      const targetList = this.shadowRoot.querySelector(`#nilm_merge_targets_${index}`);
      const decisionDraft = this._nilmDecisionDraft(signature);
      const target = targetList ? targetList.dataset.selected || "" : decisionDraft.mergeTarget || "";
      if (!target) {
        reject(this._panelText("errors.nilm_merge_target_required"));
        return;
      }
      data.target_signature_id = target;
    }
    const actionContext = this._nilmWorkspaceActionContext();
    const previousItems = this._nilmLaneItems(this._nilmWorkspace);
    const previousKey = `signature:${signature.signature_id || this._nilmSignatureFingerprint(signature)}`;
    const previousIndex = Math.max(
      0,
      previousItems.findIndex((item) => this._nilmReviewKey(item) === previousKey),
    );
    const busyKey = `nilm_${index}_${actionKey}`;
    this._busyAction = busyKey;
    this._render();
    try {
      if (action.domain) {
        await this._hass.callService(action.domain, action.service, data);
      } else {
        await this._hass.callService("circuitsetup_energy_analyzer", action.service, data);
      }
      if (!actionContext.isRouteCurrent()) {
        return;
      }
      const message = this._nilmActionMessage(actionKey, data);
      const refreshed = await this._refreshNilmWorkspaceData(
        actionContext.requestId,
        actionContext.routeKey,
      );
      if (!actionContext.isRouteCurrent()) {
        return;
      }
      if (!actionContext.isCurrent()) {
        if (refreshed) this._render();
        return;
      }
      if (this._busyAction === busyKey) this._busyAction = "";
      if (actionKey === "label" || actionKey === "assign") {
        this._nilmLabelDrafts.delete(this._nilmLabelDraftKey(signature));
      }
      this._nilmDecisionDrafts.delete(this._nilmDecisionDraftKey(signature));
      if (!refreshed) {
        this._setInlineFeedback(
          feedbackScope,
          "error",
          this._panelTextFormat("messages.nilm_interval_action_refresh_failed", { message }),
        );
        return;
      }
      const remainingItems = this._nilmLaneItems(this._nilmWorkspace)
        .filter((item) => this._nilmReviewKey(item) !== previousKey);
      const nextItem = remainingItems[Math.min(previousIndex, Math.max(0, remainingItems.length - 1))] || null;
      this._nilmSelectedReviewKey = nextItem ? this._nilmReviewKey(nextItem) : "";
      if (nextItem && nextItem.kind === "signature") {
        const fingerprint = this._nilmSignatureFingerprint(nextItem.item);
        if (fingerprint) {
          await this._focusNilmSignatureOnGraph(fingerprint, { scroll: false, toggle: false });
          if (!actionContext.isCurrent()) {
            return;
          }
        }
      }
      this._setInlineFeedback("nilm-review", "success", message);
    } catch (error) {
      if (!actionContext.isCurrent()) {
        return;
      }
      const message = this._panelTextFormat("errors.run_service", { service: action.service, message: error.message });
      if (this._busyAction === busyKey) this._busyAction = "";
      reject(message);
    }
  }

  _clearNilmIntervalFeedback() {
    this._nilmIntervalFailedAction = "";
    this._nilmIntervalFailedIndex = -1;
    this._nilmIntervalRefreshSuccessMessage = "";
    if (this._inlineFeedback.scope === "nilm-interval") {
      this._inlineFeedback = { scope: "", kind: "", message: "" };
    }
  }

  _setNilmIntervalError(message, retryAction = "", retryIndex = -1) {
    this._nilmIntervalFailedAction = retryAction;
    this._nilmIntervalFailedIndex = retryIndex;
    this._setInlineFeedback("nilm-interval", "error", message);
  }

  _setNilmIntervalRefreshError(successMessage) {
    this._nilmIntervalFailedAction = "";
    this._nilmIntervalFailedIndex = -1;
    this._nilmIntervalRefreshSuccessMessage = successMessage;
    this._setInlineFeedback(
      "nilm-interval",
      "error",
      this._panelTextFormat("messages.nilm_interval_action_refresh_failed", {
        message: successMessage,
      }),
    );
  }

  _restoreNilmIntervalScroll(scrollTop) {
    if (!Number.isFinite(scrollTop) || typeof window.scrollTo !== "function") {
      return;
    }
    requestAnimationFrame(() => {
      requestAnimationFrame(() => window.scrollTo({ top: scrollTop, behavior: "auto" }));
    });
  }

  async _retryNilmIntervalWorkspaceRefresh() {
    const successMessage = this._nilmIntervalRefreshSuccessMessage;
    if (!successMessage) {
      return;
    }
    const actionContext = this._nilmWorkspaceActionContext();
    const scrollTop = Number(window.scrollY);
    const busyKey = "nilm_interval_refresh";
    this._busyAction = busyKey;
    this._render();
    const refreshed = await this._refreshNilmWorkspaceData(
      actionContext.requestId,
      actionContext.routeKey,
    );
    if (!actionContext.isRouteCurrent()) {
      return;
    }
    if (!actionContext.isCurrent()) {
      if (refreshed) this._render();
      return;
    }
    if (this._busyAction === busyKey) this._busyAction = "";
    if (!refreshed) {
      this._setNilmIntervalRefreshError(successMessage);
      this._restoreNilmIntervalScroll(scrollTop);
      return;
    }
    this._nilmIntervalRefreshSuccessMessage = "";
    this._setInlineFeedback("nilm-interval", "success", successMessage);
    this._restoreNilmIntervalScroll(scrollTop);
  }

  async _callNilmLabelIntervalAction(index, actionKey) {
    this._clearNilmIntervalFeedback();
    const workspace = this._nilmWorkspace;
    const intervals = workspace && workspace.label_intervals;
    let action = null;
    let data = {};
    if (actionKey === "adjust") {
      const interval = intervals && intervals[index];
      if (!interval) {
        this._setNilmIntervalError(this._panelText("errors.nilm_interval_required"));
        return;
      }
      const assignment = ((workspace && workspace.assignments) || []).find((item) => (
        item.assignment_id === interval.assignment_id
        || (item.label_interval_ids || []).includes(interval.interval_id)
      ));
      this._nilmLabelIntervalDraft = {
        label: String(interval.label || interval.appliance_id || ""),
        appliance_id: String(interval.appliance_id || ""),
        appliance_profile: String((assignment && assignment.appliance_profile) || ""),
        assignment_id: String(interval.assignment_id || assignment && assignment.assignment_id || ""),
        intervals: [{
          interval_id: String(interval.interval_id || ""),
          start: this._datetimeLocalFromMillis(Date.parse(interval.start || "")),
          end: this._datetimeLocalFromMillis(Date.parse(interval.end || "")),
        }],
      };
      this._nilmActiveIntervalIndex = 0;
      this._nilmIntervalEditorOpen = true;
      this._lastActionMessage = this._panelText("messages.loaded_interval_adjustment");
      this._render();
      return;
    }
    const requests = [];
    if (actionKey === "save") {
      action = workspace && workspace.actions && workspace.actions.label_interval;
      const draft = this._nilmLabelIntervalDraft || {};
      const label = String(draft.label || "").trim();
      const applianceProfile = String(draft.appliance_profile || "").trim();
      const draftIntervals = this._nilmIntervalDraftItems();
      if (!label || !applianceProfile || !draftIntervals.length) {
        this._setNilmIntervalError(this._panelText("errors.nilm_interval_fields_required"));
        return;
      }
      for (const interval of draftIntervals) {
        const start = this._datetimeLocalToIso(interval.start);
        const end = this._datetimeLocalToIso(interval.end);
        if (!start || !end || Date.parse(end) <= Date.parse(start)) {
          this._setNilmIntervalError(this._panelText("errors.nilm_interval_fields_required"));
          return;
        }
        data = {
          ...action && action.data || {},
          label,
          start,
          end,
          appliance_id: String(draft.appliance_id || label).trim(),
          appliance_profile: applianceProfile,
        };
        const intervalId = String(interval.interval_id || "").trim();
        if (intervalId) data.interval_id = intervalId;
        if (draft.assignment_id) data.assignment_id = draft.assignment_id;
        requests.push(data);
      }
    } else if (actionKey === "delete") {
      const interval = intervals && intervals[index];
      action = interval && interval.actions && interval.actions.delete;
      data = Object.assign({}, action && action.data || {});
    }
    if (!this._guardActionCall(action, `NILM label interval ${actionKey}`, "nilm-interval")) {
      return;
    }
    const busyKey = actionKey === "save"
      ? "nilm_label_interval_save"
      : `nilm_label_interval_${index}_${actionKey}`;
    const actionContext = this._nilmWorkspaceActionContext();
    const scrollTop = Number(window.scrollY);
    this._busyAction = busyKey;
    this._render();
    try {
      for (const requestData of requests.length ? requests : [data]) {
        if (action.domain) {
          await this._hass.callService(action.domain, action.service, requestData);
        } else {
          await this._hass.callService("circuitsetup_energy_analyzer", action.service, requestData);
        }
      }
      if (!actionContext.isRouteCurrent()) {
        return;
      }
      const message = actionKey === "save"
        ? this._panelTextFormat("messages.saved_interval_label", { label: data.label })
        : this._panelText("messages.deleted_interval_label");
      const refreshed = await this._refreshNilmWorkspaceData(
        actionContext.requestId,
        actionContext.routeKey,
      );
      if (!actionContext.isRouteCurrent()) {
        return;
      }
      if (!actionContext.isCurrent()) {
        if (refreshed) this._render();
        return;
      }
      if (actionKey === "save") {
        this._nilmLabelIntervalDraft = this._emptyNilmLabelIntervalDraft();
        this._nilmActiveIntervalIndex = 0;
        this._nilmIntervalEditorOpen = false;
        if (refreshed) {
          const savedAssignment = ((this._nilmWorkspace && this._nilmWorkspace.assignments) || [])
            .find((item) => (
              item.assignment_id === data.assignment_id
              || item.appliance_id === data.appliance_id
            ));
          this._nilmActiveLane = "needs_review";
          this._nilmSelectedReviewKey = savedAssignment
            ? `assignment:${savedAssignment.assignment_id}`
            : "";
        }
      }
      if (this._busyAction === busyKey) this._busyAction = "";
      if (refreshed) {
        this._nilmIntervalRefreshSuccessMessage = "";
        this._setInlineFeedback("nilm-interval", "success", message);
      } else {
        this._setNilmIntervalRefreshError(message);
      }
      this._restoreNilmIntervalScroll(scrollTop);
    } catch (error) {
      if (!actionContext.isCurrent()) {
        return;
      }
      if (this._busyAction === busyKey) this._busyAction = "";
      this._setNilmIntervalError(
        this._panelTextFormat("errors.run_service", { service: action.service, message: error.message }),
        actionKey,
        index,
      );
    }
  }

  async _callNilmWorkspaceItemAction(collectionKey, index, actionKey) {
    if (collectionKey === "assignments" && actionKey === "save") {
      await this._saveNilmAssignmentChanges(index);
      return;
    }
    const workspace = this._nilmWorkspace;
    const items = workspace && workspace[collectionKey];
    const item = items && items[index];
    const action = item && item.actions && item.actions[actionKey];
    if (!this._guardActionCall(action, `NILM ${actionKey}`)) {
      return;
    }
    const data = Object.assign({}, action.data || {});
    if (action.requires && action.requires.includes("label")) {
      const labelInput = this.shadowRoot.querySelector(
        collectionKey === "sessions"
          ? `#nilm_session_label_${index}`
          : `#nilm_assignment_label_${index}`,
      );
      const existingAssignment = this._nilmExistingAssignmentSelection(`${collectionKey}_${index}`);
      const label = existingAssignment
        ? existingAssignment.label
        : labelInput
        ? labelInput.value
        : item.display_name || item.label || item.appliance_id || "";
      if (!label || !label.trim()) {
        this._error = this._panelText("errors.nilm_session_label_required");
        this._renderAndScrollToTop();
        return;
      }
      data.label = label.trim();
      if (existingAssignment) {
        data.assignment_id = existingAssignment.assignment_id;
      }
      if (item.appliance_id && !data.appliance_id) {
        data.appliance_id = item.appliance_id;
      }
    }
    if (action.requires && action.requires.includes("appliance_profile")) {
      const profileInput = this.shadowRoot.querySelector(`#nilm_assignment_profile_${index}`);
      const profile = profileInput ? profileInput.value.trim() : "";
      if (!profile) {
        this._error = this._panelText("errors.nilm_assignment_type_required");
        this._renderAndScrollToTop();
        return;
      }
      data.appliance_profile = profile;
    }
    if (action.requires && action.requires.includes("target_assignment_id")) {
      const targetInput = this.shadowRoot.querySelector(`#nilm_assignment_merge_target_${index}`);
      const target = targetInput ? targetInput.value.trim() : "";
      if (!target) {
        this._error = this._panelText("errors.nilm_assignment_merge_required");
        this._renderAndScrollToTop();
        return;
      }
      data.target_assignment_id = target;
    }
    if (action.requires && action.requires.includes("direct_circuit_id")) {
      const targetInput = this.shadowRoot.querySelector(`#nilm_assignment_direct_target_${index}`);
      const target = targetInput ? targetInput.value.trim() : "";
      if (!target) {
        this._error = this._panelText("errors.nilm_direct_meter_required");
        this._renderAndScrollToTop();
        return;
      }
      data.direct_circuit_id = target;
    }
    const actionContext = this._nilmWorkspaceActionContext();
    const scrollTop = Number(window.scrollY);
    const busyKey = `nilm_${collectionKey}_${index}_${actionKey}`;
    this._busyAction = busyKey;
    this._render();
    try {
      if (action.domain) {
        await this._hass.callService(action.domain, action.service, data);
      } else {
        await this._hass.callService("circuitsetup_energy_analyzer", action.service, data);
      }
      if (!actionContext.isRouteCurrent()) {
        return;
      }
      const message = this._nilmWorkspaceActionMessage(actionKey, data, item);
      const refreshed = await this._refreshNilmWorkspaceData(
        actionContext.requestId,
        actionContext.routeKey,
      );
      if (!actionContext.isRouteCurrent()) {
        return;
      }
      if (!actionContext.isCurrent()) {
        if (refreshed) this._render();
        return;
      }
      if (this._busyAction === busyKey) this._busyAction = "";
      const feedbackScope = refreshed
        ? this._selectRefreshedNilmAssignment(item, data)
        : "nilm-review";
      this._setInlineFeedback(
        feedbackScope,
        refreshed ? "success" : "error",
        refreshed
          ? message
          : this._panelTextFormat("messages.nilm_interval_action_refresh_failed", { message }),
      );
      this._restoreNilmIntervalScroll(scrollTop);
    } catch (error) {
      if (!actionContext.isCurrent()) {
        return;
      }
      this._error = this._panelTextFormat("errors.run_service", { service: action.service, message: error.message });
      if (this._busyAction === busyKey) this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  async _saveNilmAssignmentChanges(index) {
    const workspace = this._nilmWorkspace;
    const assignments = workspace && workspace.assignments;
    const item = assignments && assignments[index];
    const actions = item && item.actions;
    if (!actions) {
      this._error = this._panelText("errors.nilm_assignment_save_unavailable");
      this._renderAndScrollToTop();
      return;
    }
    const calls = [];
    if (actions.rename) {
      const labelInput = this.shadowRoot.querySelector(`#nilm_assignment_label_${index}`);
      const label = labelInput ? labelInput.value.trim() : "";
      if (label && label !== String(item.display_name || "")) {
        calls.push({ actionKey: "rename", action: actions.rename, data: Object.assign({}, actions.rename.data || {}, { label }) });
      }
    }
    if (actions.change_profile) {
      const profileInput = this.shadowRoot.querySelector(`#nilm_assignment_profile_${index}`);
      const applianceProfile = profileInput ? profileInput.value.trim() : "";
      if (applianceProfile && applianceProfile !== String(item.appliance_profile || "")) {
        calls.push({ actionKey: "change_profile", action: actions.change_profile, data: Object.assign({}, actions.change_profile.data || {}, { appliance_profile: applianceProfile }) });
      }
    }
    if (!calls.length) {
      this._error = this._panelText("errors.nilm_assignment_no_changes");
      this._renderAndScrollToTop();
      return;
    }
    const actionContext = this._nilmWorkspaceActionContext();
    const scrollTop = Number(window.scrollY);
    const busyKey = `nilm_assignments_${index}_save`;
    this._busyAction = busyKey;
    this._render();
    let completedCalls = 0;
    try {
      for (const call of calls) {
        if (call.action.domain) {
          await this._hass.callService(call.action.domain, call.action.service, call.data);
        } else {
          await this._hass.callService("circuitsetup_energy_analyzer", call.action.service, call.data);
        }
        completedCalls += 1;
        if (!actionContext.isRouteCurrent()) {
          return;
        }
      }
      const message = this._nilmWorkspaceActionMessage("save", {}, item);
      const refreshed = await this._refreshNilmWorkspaceData(
        actionContext.requestId,
        actionContext.routeKey,
      );
      if (!actionContext.isRouteCurrent()) {
        return;
      }
      if (!actionContext.isCurrent()) {
        if (refreshed) this._render();
        return;
      }
      const draftKey = this._nilmAssignmentDraftKey(item);
      this._nilmAssignmentDrafts.delete(`${draftKey}:label`);
      this._nilmAssignmentDrafts.delete(`${draftKey}:appliance_profile`);
      if (this._busyAction === busyKey) this._busyAction = "";
      const feedbackScope = refreshed
        ? this._selectRefreshedNilmAssignment(
          item,
          {},
          "",
        )
        : "nilm-review";
      this._setInlineFeedback(
        feedbackScope,
        refreshed ? "success" : "error",
        refreshed
          ? message
          : this._panelTextFormat("messages.nilm_interval_action_refresh_failed", { message }),
      );
      this._restoreNilmIntervalScroll(scrollTop);
    } catch (error) {
      const refreshed = completedCalls && actionContext.isRouteCurrent()
        ? await this._refreshNilmWorkspaceData(actionContext.requestId, actionContext.routeKey)
        : false;
      if (!actionContext.isRouteCurrent()) {
        return;
      }
      if (!actionContext.isCurrent()) {
        if (refreshed) this._render();
        return;
      }
      this._error = this._panelTextFormat("errors.save_assignment", { message: error.message });
      if (this._busyAction === busyKey) this._busyAction = "";
      this._renderAndScrollToTop();
    }
  }

  _routeRequestsNilmWorkspace(routeKey = this._routeKey()) {
    const routeUrl = new URL(routeKey, window.location.origin);
    return routeUrl.searchParams.get(NILM_WORKSPACE_QUERY_PARAM) === "1"
      || routeUrl.pathname.endsWith("/nilm");
  }

  _nilmActionMessage(actionKey, data) {
    if (actionKey === "label") {
      return this._panelTextFormat("messages.saved_label", { label: data.label });
    }
    if (actionKey === "ignore") {
      return this._panelText("messages.ignored_signature");
    }
    if (actionKey === "mark_expected") {
      return this._panelText("messages.marked_signature_expected");
    }
    if (actionKey === "merge") {
      return this._panelText("messages.merged_signature");
    }
    if (actionKey === "assign") {
      return this._panelTextFormat("messages.assigned_signature", { label: data.label });
    }
    return this._panelText("common.action_complete");
  }

  _nilmWorkspaceActionMessage(actionKey, data, item) {
    const name = (data && data.label) || (item && (item.display_name || item.label)) || this._panelText("common.appliance");
    if (actionKey === "assign") {
      return this._panelTextFormat("messages.assigned_to", { name });
    }
    if (actionKey === "publish") {
      return this._panelText("messages.created_estimated_device");
    }
    if (actionKey === "unpublish") {
      return this._panelText("messages.removed_estimated_device");
    }
    if (actionKey === "retire") {
      return this._panelText("messages.removed_assignment");
    }
    if (actionKey === "save") {
      return this._panelText("messages.saved_assignment_changes");
    }
    if (actionKey === "rename") {
      return this._panelTextFormat("messages.renamed_assignment", { name });
    }
    if (actionKey === "change_profile") {
      return this._panelText("messages.changed_appliance_type");
    }
    if (actionKey === "validate_history") {
      return this._panelTextFormat("messages.validated_history", { name });
    }
    if (actionKey === "merge") {
      return this._panelTextFormat("messages.merged_assignment", { name });
    }
    if (actionKey === "validate") {
      return this._panelTextFormat("messages.confirmed_assignment", { name });
    }
    if (actionKey === "reject") {
      return this._panelTextFormat("messages.marked_assignment_for_review", { name });
    }
    return this._panelText("common.action_complete");
  }

  _nilmWorkspaceActionContext() {
    const actionContext = this._actionContext();
    const mutationId = this._nilmWorkspaceMutationId + 1;
    this._nilmWorkspaceMutationId = mutationId;
    return {
      requestId: actionContext.requestId,
      routeKey: actionContext.routeKey,
      isRouteCurrent: actionContext.isCurrent,
      isCurrent: () => actionContext.isCurrent()
        && mutationId === this._nilmWorkspaceMutationId,
    };
  }

  _selectRefreshedNilmAssignment(item, data = {}, preferredAssignmentId = "") {
    const workspace = this._nilmWorkspace || {};
    const assignments = Array.isArray(workspace.assignments) ? workspace.assignments : [];
    const candidateIds = [
      preferredAssignmentId,
      data.target_assignment_id,
      data.assignment_id,
      item && item.assignment_id,
    ].filter(Boolean);
    const sessionId = (item && item.session_id) || data.session_id || "";
    const assignment = candidateIds
      .map((assignmentId) => assignments.find((entry) => (
        entry.assignment_id === assignmentId
      )))
      .find(Boolean)
      || assignments.find((entry) => (
        sessionId && Array.isArray(entry.session_ids) && entry.session_ids.includes(sessionId)
      ));
    const assignmentId = assignment && assignment.assignment_id;
    const lane = assignmentId && Object.entries(workspace.lanes || {}).find(([, value]) => (
      Array.isArray(value.assignment_ids) && value.assignment_ids.includes(assignmentId)
    ));
    if (!lane) {
      return "nilm-review";
    }
    this._nilmActiveLane = lane[0];
    this._nilmSelectedReviewKey = `assignment:${assignmentId}`;
    this._nilmFocusedSignature = "";
    return this._nilmSelectedReviewKey;
  }

  _invalidateNilmFocusedHistoryRequests() {
    this._nilmFocusedHistoryToken += 1;
  }

  _isCurrentNilmFocusedHistoryRequest(token, requestId, routeKey) {
    return token === this._nilmFocusedHistoryToken
      && this._isCurrentRequest(requestId, routeKey);
  }

  _nilmFocusState(element = this.shadowRoot && this.shadowRoot.activeElement) {
    const dataset = element && element.dataset;
    if (!dataset) {
      return null;
    }
    const controls = [
      ["nilmDecision", "[data-nilm-decision]", "nilmDecisionKey"],
      ["nilmIdentifyMode", "[data-nilm-identify-mode]", "nilmDecisionKey"],
      ["nilmLane", "[data-nilm-lane]", "nilmLane"],
      ["nilmReviewItem", "[data-nilm-review-item]", "nilmReviewItem"],
    ];
    const control = controls.find(([flag]) => Object.prototype.hasOwnProperty.call(dataset, flag));
    return control ? {
      selector: control[1],
      dataKey: control[2],
      key: dataset[control[2]],
      value: element.value,
    } : null;
  }

  _restoreNilmFocus(state) {
    if (!state) {
      return;
    }
    requestAnimationFrame(() => {
      const target = Array.from(this.shadowRoot.querySelectorAll(state.selector)).find((element) => (
        element.dataset[state.dataKey] === state.key && element.value === state.value
      ));
      if (target && typeof target.focus === "function") {
        target.focus({ preventScroll: true });
      }
    });
  }

  _renderNilmWorkspaceBody() {
    return `${this._renderNilmWorkspace()}${this._renderRecommendations()}`;
  }

  _nilmReviewSignatures() {
    const workspace = this._nilmWorkspace;
    if (workspace && workspace.status === "ok" && Array.isArray(workspace.signatures)) {
      return workspace.signatures;
    }
    const nilm = this._payload && this._payload.nilm;
    return (nilm && nilm.signatures) || [];
  }

  _renderNilmSignatureReview(signature, index) {
    return `
      ${signature.user_label ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.saved_label", { label: signature.user_label }))}</p>` : ""}
      ${signature.review_state ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.review_state", { state: this._friendlyFeature(signature.review_state) }))}</p>` : ""}
      ${signature.merged_into ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.merged_into", { value: signature.merged_into }))}</p>` : ""}
      ${this._renderNilmDecisionFlow(signature, index)}
    `;
  }

  _nilmDecisionDraftKey(signature) {
    return this._nilmSignatureFingerprint(signature) || String(signature && signature.signature_id || "");
  }

  _nilmDecisionDraft(signature) {
    return this._nilmDecisionDrafts.get(this._nilmDecisionDraftKey(signature)) || { decision: "", identifyMode: "assign" };
  }

  _renderNilmDecisionFlow(signature, index) {
    const actions = signature && signature.actions ? signature.actions : {};
    const candidates = [
      ["identify", "mdi:tag-outline", "nilm_workspace.decision_identify", Boolean(actions.assign || actions.label)],
      ["mark_expected", "mdi:check-decagram", "nilm_workspace.decision_expected", Boolean(actions.mark_expected)],
      ["ignore", "mdi:eye-off-outline", "actions.labels.ignore", Boolean(actions.ignore)],
      ["merge", "mdi:source-merge", "actions.labels.merge", Boolean(actions.merge && actions.merge.target_options && actions.merge.target_options.length)],
    ].filter(([, , , available]) => available);
    if (!candidates.length) {
      return "";
    }
    const key = this._nilmDecisionDraftKey(signature);
    const draft = this._nilmDecisionDraft(signature);
    const identifyMode = actions[draft.identifyMode]
      ? draft.identifyMode
      : actions.assign
        ? "assign"
        : "label";
    const identifyFields = draft.decision === "identify" ? `
      <label class="nilm-label-field">
        <span class="muted">${this._escape(this._panelText("nilm_workspace.identify_outcome"))}</span>
        <select data-nilm-identify-mode data-nilm-decision-key="${this._escape(key)}">
          ${actions.assign ? `<option value="assign" ${identifyMode === "assign" ? "selected" : ""}>${this._escape(this._panelText("nilm_workspace.identify_assign"))}</option>` : ""}
          ${actions.label ? `<option value="label" ${identifyMode === "label" ? "selected" : ""}>${this._escape(this._panelText("nilm_workspace.identify_label_only"))}</option>` : ""}
        </select>
      </label>
      ${identifyMode === "assign" ? this._renderNilmExistingAssignmentField(actions.assign, `signature_${index}`, draft.assignmentId, key) : ""}
      ${this._renderNilmLabelField(signature, index)}
    ` : "";
    return `<div class="nilm-decision-flow">
      <fieldset class="decision-group nilm-decision-group">
        <legend>${this._escape(this._panelText("nilm_workspace.choose_decision"))}</legend>
        <div class="nilm-decision-options">
          ${candidates.map(([value, icon, textKey]) => `<label class="nilm-decision-option">
            <input type="radio" name="nilm_decision_${index}" value="${value}" data-nilm-decision data-nilm-decision-key="${this._escape(key)}" ${draft.decision === value ? "checked" : ""}>
            <ha-icon icon="${icon}"></ha-icon>
            <span>${this._escape(this._panelText(textKey))}</span>
          </label>`).join("")}
        </div>
      </fieldset>
      ${identifyFields}
      ${draft.decision === "merge" ? this._renderNilmMergeTarget(signature, index) : ""}
      <div class="actions">
        <button type="button" data-nilm-apply-decision="${index}" ${this._busyAction.startsWith(`nilm_${index}_`) ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.apply"))}</button>
      </div>
      ${this._renderInlineFeedback(key)}
    </div>`;
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
        <span class="muted">${this._escape(this._panelText("nilm_workspace.label_this_load"))}</span>
        <input
          id="nilm_label_${index}"
          type="text"
          data-nilm-label-input
          data-nilm-label-key="${this._escape(draftKey)}"
          value="${this._escape(currentLabel)}"
          placeholder="${this._escape(this._panelText("nilm_workspace.appliance_name"))}"
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

  _nilmSignatureFingerprint(signature) {
    return String((signature && (signature.feedback_fingerprint || signature.signature_fingerprint || signature.signature_id)) || "").trim();
  }

  _rememberNilmLabelDraft(input) {
    if (!input || !input.dataset.nilmLabelKey) {
      return;
    }
    this._nilmLabelDrafts.set(input.dataset.nilmLabelKey, input.value);
  }

  _emptyNilmLabelIntervalDraft() {
    return {
      label: "",
      appliance_id: "",
      appliance_profile: "",
      assignment_id: "",
      intervals: [{ start: "", end: "", interval_id: "" }],
    };
  }

  _nilmIntervalDraftItems() {
    const draft = this._nilmLabelIntervalDraft || {};
    if (Array.isArray(draft.intervals)) {
      return draft.intervals;
    }
    return draft.start || draft.end || draft.interval_id
      ? [{ start: draft.start || "", end: draft.end || "", interval_id: draft.interval_id || "" }]
      : [];
  }

  _rememberNilmLabelIntervalDraft(input) {
    if (!input || !input.dataset.nilmLabelIntervalInput) {
      return;
    }
    const field = input.dataset.nilmLabelIntervalInput;
    const index = Number.parseInt(input.dataset.nilmIntervalIndex || "-1", 10);
    if (index >= 0 && ["start", "end"].includes(field)) {
      const intervals = this._nilmIntervalDraftItems().map((item) => ({ ...item }));
      intervals[index] = { ...(intervals[index] || {}), [field]: input.value };
      this._nilmLabelIntervalDraft = { ...this._nilmLabelIntervalDraft, intervals };
      this._nilmActiveIntervalIndex = index;
      return;
    }
    this._nilmLabelIntervalDraft = {
      ...this._nilmLabelIntervalDraft,
      [field]: input.value,
    };
  }

  _rememberNilmSessionLabelDraft(input) {
    if (!input || !input.dataset.nilmSessionLabelKey) {
      return;
    }
    this._nilmSessionLabelDrafts.set(input.dataset.nilmSessionLabelKey, input.value);
  }

  _rememberNilmAssignmentDraft(input) {
    if (!input || !input.dataset.nilmAssignmentKey || !input.dataset.nilmAssignmentField) {
      return;
    }
    this._nilmAssignmentDrafts.set(`${input.dataset.nilmAssignmentKey}:${input.dataset.nilmAssignmentField}`, input.value);
    this._syncNilmAssignmentSaveButton(input.dataset.nilmAssignmentKey);
  }

  _nilmAssignmentHasChanges(item) {
    const key = this._nilmAssignmentDraftKey(item);
    return this._nilmAssignmentDraftValue(key, "label", item.display_name || "") !== String(item.display_name || "")
      || this._nilmAssignmentDraftValue(key, "appliance_profile", item.appliance_profile || "") !== String(item.appliance_profile || "");
  }

  _syncNilmAssignmentSaveButton(assignmentId) {
    const assignment = ((this._nilmWorkspace && this._nilmWorkspace.assignments) || [])
      .find((item) => item.assignment_id === assignmentId);
    const button = this.shadowRoot.querySelector(`[data-nilm-assignment-save-key="${assignmentId}"]`);
    if (!assignment || !button) return;
    const dirty = this._nilmAssignmentHasChanges(assignment);
    button.disabled = !dirty;
    if (button.classList) button.classList.toggle("secondary", !dirty);
  }

  _startNilmChartSelection(event, chart) {
    if (event.target && event.target.dataset && (
      event.target.dataset.nilmDraftIndex !== undefined
      || event.target.dataset.nilmLabelIntervalIndex !== undefined
      || event.target.dataset.nilmSessionStart
    )) {
      return;
    }
    const startTime = this._snapNilmChartTimeToEdge(this._chartEventTime(event, chart), chart);
    if (!Number.isFinite(startTime)) {
      return;
    }
    const finish = (finishEvent) => {
      chart.removeEventListener("pointercancel", cancel);
      const endTime = this._snapNilmChartTimeToEdge(this._chartEventTime(finishEvent, chart), chart);
      if (!Number.isFinite(endTime)) {
        return;
      }
      const start = Math.min(startTime, endTime);
      const end = Math.max(startTime, endTime);
      if (end <= start) {
        return;
      }
      const intervals = this._nilmIntervalDraftItems().map((item) => ({ ...item }));
      let index = Math.max(0, Math.min(this._nilmActiveIntervalIndex, intervals.length - 1));
      if (!intervals.length || (intervals[index] && (intervals[index].start || intervals[index].end))) {
        index = intervals.length;
        intervals.push({ start: "", end: "", interval_id: "" });
      }
      intervals[index] = {
        ...intervals[index],
        start: this._datetimeLocalFromMillis(start),
        end: this._datetimeLocalFromMillis(end),
      };
      this._nilmLabelIntervalDraft = { ...this._nilmLabelIntervalDraft, intervals };
      this._nilmActiveIntervalIndex = index;
      this._nilmIntervalEditorOpen = true;
      this._render();
    };
    const cancel = () => {
      chart.removeEventListener("pointerup", finish);
    };
    if (chart.setPointerCapture && event.pointerId !== undefined) {
      chart.setPointerCapture(event.pointerId);
    }
    chart.addEventListener("pointerup", finish, { once: true });
    chart.addEventListener("pointercancel", cancel, { once: true });
  }

  _removeNilmDraftInterval(index) {
    const intervals = this._nilmIntervalDraftItems().filter((_item, itemIndex) => itemIndex !== index);
    this._nilmLabelIntervalDraft = {
      ...this._nilmLabelIntervalDraft,
      intervals: intervals.length ? intervals : [{ start: "", end: "", interval_id: "" }],
    };
    this._nilmActiveIntervalIndex = Math.max(0, Math.min(index, this._nilmLabelIntervalDraft.intervals.length - 1));
    this._render();
  }

  _selectNilmDraftInterval(index) {
    if (!Number.isInteger(index) || index < 0 || index >= this._nilmIntervalDraftItems().length) {
      return;
    }
    this._nilmActiveIntervalIndex = index;
    for (const row of this.shadowRoot.querySelectorAll("[data-nilm-interval-row]")) {
      row.dataset.nilmActive = String(Number(row.dataset.nilmIntervalRow) === index);
    }
    for (const indicator of this.shadowRoot.querySelectorAll("[data-nilm-editing-indicator]")) {
      indicator.hidden = Number(indicator.dataset.nilmEditingIndicator) !== index;
    }
    for (const band of this.shadowRoot.querySelectorAll("[data-nilm-draft-index]")) {
      band.dataset.nilmSelected = String(Number(band.dataset.nilmDraftIndex) === index);
    }
  }

  _selectNilmSessionInterval(band) {
    this._loadNilmSessionInterval({
      start: band && band.dataset.nilmSessionStart,
      end: band && band.dataset.nilmSessionEnd,
    });
  }

  _selectNilmSessionIntervalByIndex(index) {
    const sessions = Array.isArray(this._nilmWorkspace && this._nilmWorkspace.sessions)
      ? this._nilmWorkspace.sessions
      : [];
    this._loadNilmSessionInterval(sessions[index]);
  }

  _loadNilmSessionInterval(session) {
    const start = Date.parse(session && session.start || "");
    const end = Date.parse(session && session.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return;
    }
    const assignment = ((this._nilmWorkspace && this._nilmWorkspace.assignments) || [])
      .find((item) => item.assignment_id === session.assignment_id);
    this._nilmLabelIntervalDraft = {
      ...this._nilmLabelIntervalDraft,
      label: session.display_label || assignment && assignment.display_name || this._nilmLabelIntervalDraft.label || "",
      appliance_id: session.appliance_id || assignment && assignment.appliance_id || this._nilmLabelIntervalDraft.appliance_id || "",
      appliance_profile: assignment && assignment.appliance_profile || this._nilmLabelIntervalDraft.appliance_profile || "",
      assignment_id: session.assignment_id || "",
      intervals: [{
        start: this._datetimeLocalFromMillis(start),
        end: this._datetimeLocalFromMillis(end),
        interval_id: "",
      }],
    };
    this._nilmActiveIntervalIndex = 0;
    this._nilmIntervalEditorOpen = true;
    this._lastActionMessage = this._panelText("messages.loaded_nilm_session_interval");
    this._render();
  }

  _selectNilmEdgeTime(marker) {
    const time = Date.parse(marker && marker.dataset.nilmEdgeTime || "");
    if (!Number.isFinite(time)) {
      return;
    }
    const field = String(marker.dataset.nilmEdgeDirection || "").toLowerCase() === "off"
      ? "end"
      : "start";
    const intervals = this._nilmIntervalDraftItems().map((item) => ({ ...item }));
    const index = Math.max(0, Math.min(this._nilmActiveIntervalIndex, intervals.length - 1));
    intervals[index] = {
      ...(intervals[index] || { start: "", end: "", interval_id: "" }),
      [field]: this._datetimeLocalFromMillis(time),
    };
    this._nilmLabelIntervalDraft = { ...this._nilmLabelIntervalDraft, intervals };
    this._nilmIntervalEditorOpen = true;
    this._lastActionMessage = this._panelText("messages.loaded_nilm_edge_time");
    this._render();
  }

  async _focusNilmSignatureOnGraph(signatureFingerprint, options = {}) {
    const shouldScroll = options.scroll !== false;
    const canToggle = options.toggle !== false;
    if (canToggle && this._nilmFocusedSignature === signatureFingerprint) {
      this._nilmFocusedSignature = "";
      this._nilmGraphWindow = null;
      this._lastActionMessage = this._panelText("messages.showing_all_nilm_sessions");
      if (shouldScroll) {
        this._renderAndScrollToTop();
      } else {
        this._render();
      }
      return;
    }
    this._nilmFocusedSignature = signatureFingerprint;
    const targetWindow = this._nilmSignatureGraphWindow(signatureFingerprint);
    if (targetWindow) {
      const historyLoaded = await this._loadNilmWorkspaceHistoryForWindow(targetWindow);
      if (historyLoaded === null) {
        return;
      }
    }
    const focused = this._focusNilmGraphWindowForSignature(signatureFingerprint);
    this._lastActionMessage = focused
      ? this._panelText("messages.showing_selected_signature")
      : this._panelText("messages.no_paired_sessions");
    if (shouldScroll) {
      this._renderAndScrollToTop();
    } else {
      this._render();
    }
  }

  _focusNilmGraphWindowForSignature(signatureFingerprint) {
    const targetWindow = this._nilmSignatureGraphWindow(signatureFingerprint);
    if (!targetWindow) {
      return false;
    }
    const bounds = this._nilmWorkspaceGraphWindow(this._nilmWorkspace) || {
      min: targetWindow.start,
      max: targetWindow.end,
    };
    this._setNilmGraphWindow(targetWindow.start, targetWindow.end, bounds);
    return true;
  }

  _nilmSignatureGraphWindow(signatureFingerprint) {
    const workspace = this._nilmWorkspace;
    const sessions = ((workspace && workspace.sessions) || [])
      .filter((session) => session.signature_fingerprint === signatureFingerprint);
    const starts = sessions.map((session) => Date.parse(session.start || "")).filter(Number.isFinite);
    const ends = sessions.map((session) => Date.parse(session.end || session.start || "")).filter(Number.isFinite);
    if (!starts.length || !ends.length) {
      return null;
    }
    const start = Math.min(...starts);
    const end = Math.max(...ends, start + 15 * 60 * 1000);
    const padding = Math.max((end - start) * 0.25, 15 * 60 * 1000);
    return { start: start - padding, end: end + padding };
  }

  async _loadNilmWorkspaceHistoryForWindow(window, failedRequest = null) {
    const workspace = this._nilmWorkspace;
    const history = workspace && workspace.history;
    if (!history || !history.api_path) {
      return false;
    }
    const request = failedRequest || this._nilmWorkspaceFocusedHistoryRequest(
      history,
      window,
    );
    const token = this._nilmFocusedHistoryToken + 1;
    this._nilmFocusedHistoryToken = token;
    const requestId = this._evidenceRequestId;
    const routeKey = this._loadedRouteKey || this._routeKey();
    const isCurrent = () => this._isCurrentNilmFocusedHistoryRequest(token, requestId, routeKey);
    if (!isCurrent()) {
      return null;
    }
    this._nilmWorkspaceHistoryError = "";
    this._nilmWorkspaceHistoryFailedRequest = null;
    this._nilmWorkspaceHistoryLoading = true;
    this._render();
    try {
      const rows = await this._requestJson(request.apiPath, request.fetchPath);
      if (!isCurrent()) {
        return null;
      }
      this._nilmWorkspaceHistorySeries = Array.isArray(rows) ? rows : [];
      this._nilmWorkspaceHistoryError = "";
      this._nilmWorkspaceHistoryFailedRequest = null;
      Object.assign(history, {
        api_path: request.apiPath,
        fetch_path: request.fetchPath,
        hours: request.hours,
        start: new Date(request.start).toISOString(),
        end: new Date(request.end).toISOString(),
      });
      return true;
    } catch (error) {
      if (!isCurrent()) {
        return null;
      }
      this._nilmWorkspaceHistorySeries = [];
      this._nilmWorkspaceHistoryError = this._panelTextFormat("errors.load_nilm_workspace_history", { message: error.message });
      this._nilmWorkspaceHistoryFailedRequest = request;
      return false;
    } finally {
      if (isCurrent()) {
        this._nilmWorkspaceHistoryLoading = false;
        this._render();
      }
    }
  }

  _nilmWorkspaceFocusedHistoryRequest(history, window) {
    const historyEnd = Date.parse(history.end || "");
    const end = Math.max(
      Number.isFinite(historyEnd) ? historyEnd : Date.now(),
      window.end,
    );
    const maxHours = Number(history.max_hours);
    const neededHours = Math.max(
      1,
      Math.ceil((end - window.start) / (60 * 60 * 1000)),
    );
    const hours = Number.isFinite(maxHours)
      ? Math.min(maxHours, neededHours)
      : neededHours;
    const start = end - hours * 60 * 60 * 1000;
    return {
      window: { start: window.start, end: window.end },
      hours,
      start,
      end,
      apiPath: this._nilmWorkspaceHistoryPathWithHours(
        history.api_path,
        hours,
      ),
      fetchPath: this._nilmWorkspaceHistoryPathWithHours(
        history.fetch_path || `/api/${history.api_path}`,
        hours,
      ),
    };
  }

  _nilmWorkspaceHistoryPathWithHours(path, hours) {
    const url = new URL(
      path.startsWith("/") ? path : `/${path}`,
      window.location.origin,
    );
    url.searchParams.set("hours", String(hours));
    const nextPath = `${url.pathname}${url.search}`;
    return path.startsWith("/") ? nextPath : nextPath.replace(/^\//, "");
  }

  _zoomNilmGraph(factor) {
    const window = this._nilmWorkspaceGraphWindow(this._nilmWorkspace);
    this._lastActionMessage = this._panelText("messages.updated_nilm_graph_window");
    this._zoomGraphWindow(window, factor, (next) => { this._nilmGraphWindow = next; });
  }

  _panNilmGraph(direction) {
    const window = this._nilmWorkspaceGraphWindow(this._nilmWorkspace);
    this._lastActionMessage = this._panelText("messages.updated_nilm_graph_window");
    this._panGraphWindow(window, direction, (next) => { this._nilmGraphWindow = next; });
  }

  _setNilmGraphWindow(start, end, bounds) {
    this._setGraphWindow(start, end, bounds, (next) => { this._nilmGraphWindow = next; });
  }

  _snapNilmChartTimeToEdge(time, chart) {
    if (!Number.isFinite(time) || !chart || !chart.dataset.nilmEdgeTimes) {
      return time;
    }
    let snapped = time;
    let closestDistance = NILM_EDGE_SNAP_MS + 1;
    for (const value of chart.dataset.nilmEdgeTimes.split(",")) {
      const edgeTime = Number(value);
      const distance = Math.abs(edgeTime - time);
      if (Number.isFinite(edgeTime) && distance <= NILM_EDGE_SNAP_MS && distance < closestDistance) {
        snapped = edgeTime;
        closestDistance = distance;
      }
    }
    return snapped;
  }

  _renderNilmMergeTarget(signature, index) {
    const action = signature && signature.actions && signature.actions.merge;
    const options = action && action.target_options;
    if (!options || !options.length) {
      return `<p class="muted">${this._escape(this._panelText("nilm_workspace.no_merge_target"))}</p>`;
    }
    const omittedCount = Number((action && action.target_options_omitted_count) || 0);
    const selectedTarget = this._nilmDecisionDraft(signature).mergeTarget || "";
    const summary = omittedCount > 0
      ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.merge_targets_summary", { shown: options.length, total: action.target_option_count, omitted: omittedCount }))} <button type="button" class="secondary" data-load-all-nilm>${this._escape(this._panelText("actions.labels.load_all_merge_targets"))}</button></p>`
      : "";
    return `
      <span class="muted">${this._escape(this._panelText("nilm_workspace.merge_into"))}</span>
      ${summary}
      <div class="merge-targets" id="nilm_merge_targets_${index}" data-selected="${this._escape(selectedTarget)}">
        ${options.map((option) => this._nilmMergeTargetChip(index, option, option.value === selectedTarget)).join("")}
      </div>
    `;
  }

  _loadExpandedNilm() {
    const routeUrl = new URL(this._routeKey(), window.location.origin);
    routeUrl.searchParams.set(EXPAND_NILM_QUERY_PARAM, "1");
    this._navigate(`${routeUrl.pathname}${routeUrl.search}${routeUrl.hash}`);
  }

  _nilmMergeTargetChip(index, option, selected = false) {
    return `
      <button
        type="button"
        class="merge-target-chip"
        data-nilm-index="${index}"
        data-nilm-merge-target="${this._escape(option.value)}"
        aria-pressed="${selected}"
      >${this._escape(option.label)}</button>
    `;
  }

  _selectNilmMergeTarget(index, target) {
    const targetList = this.shadowRoot.querySelector(`#nilm_merge_targets_${index}`);
    if (!targetList || !target) {
      return;
    }
    targetList.dataset.selected = target;
    const signature = this._nilmReviewSignatures()[index];
    if (signature) {
      const key = this._nilmDecisionDraftKey(signature);
      const current = this._nilmDecisionDraft(signature);
      this._nilmDecisionDrafts.set(key, Object.assign({}, current, { mergeTarget: target }));
    }
    for (const button of targetList.querySelectorAll("[data-nilm-merge-target]")) {
      button.setAttribute(
        "aria-pressed",
        button.dataset.nilmMergeTarget === target ? "true" : "false",
      );
    }
  }

  _renderNilmExistingAssignmentField(action, key, selectedAssignmentId = "", decisionKey = "") {
    const options = action && Array.isArray(action.assignment_options)
      ? action.assignment_options
      : [];
    if (!options.length) {
      return "";
    }
    return `
      <label class="nilm-label-field">
        <span class="muted">${this._escape(this._panelText("nilm_workspace.existing_appliance"))}</span>
        <select data-nilm-existing-assignment="${this._escape(key)}" ${decisionKey ? `data-nilm-decision-assignment-key="${this._escape(decisionKey)}"` : ""}>
          <option value="">${this._escape(this._panelText("nilm_workspace.new_appliance"))}</option>
          ${options.map((option) => `<option value="${this._escape(option.value || "")}" ${String(option.value || "") === String(selectedAssignmentId || "") ? "selected" : ""}>${this._escape(option.label || option.value || "")}</option>`).join("")}
        </select>
      </label>
    `;
  }

  _nilmExistingAssignmentSelection(key) {
    const select = this.shadowRoot.querySelector(`[data-nilm-existing-assignment="${key}"]`);
    const assignmentId = select ? String(select.value || "").trim() : "";
    if (!assignmentId) {
      return null;
    }
    const option = select.selectedOptions && select.selectedOptions[0];
    return {
      assignment_id: assignmentId,
      label: String((option && option.textContent) || assignmentId).trim(),
    };
  }

  _renderNilmWorkspace() {
    return this._nilmWorkspaceComponent.render();
  }

  _renderNilmWorkspaceContent() {
    if (this._nilmWorkspaceLoading) {
      const loadingText = this._panelText("nilm_workspace.loading");
      return `<section class="panel loading-skeleton nilm-loading-skeleton" data-loading-skeleton role="status" aria-label="${this._escape(loadingText)}"></section>`;
    }
    const workspace = this._nilmWorkspace;
    if (this._nilmWorkspaceError && (!workspace || workspace.status !== "ok")) {
      return `<section class="panel error" data-nilm-workspace-error><h2>${this._escape(this._panelText("headers.nilm_workspace"))}</h2><p>${this._escape(this._nilmWorkspaceError)}</p><button type="button" class="secondary" data-retry-nilm-workspace>${this._escape(this._panelText("common.retry"))}</button></section>`;
    }
    if (workspace && workspace.status !== "ok") {
      return `<section class="panel"><h2>${this._escape(this._panelText("headers.nilm_workspace"))}</h2><p class="muted">${this._escape(workspace.message || this._panelText("nilm_workspace.unavailable"))}</p></section>`;
    }
    if (!workspace || workspace.status !== "ok") {
      return "";
    }
    const graphWindow = this._nilmWorkspaceGraphWindow(workspace);
    const graphSessions = this._nilmFocusedSignature
      ? (workspace.sessions || []).filter((item) => item.signature_fingerprint === this._nilmFocusedSignature)
      : workspace.sessions;
    const graphBands = this._nilmGraphBands(workspace, graphSessions);
    const intervalEditor = this._renderNilmLabelIntervalEditor(workspace);
    const intervalFeedback = this._renderNilmIntervalFeedback();
    return `
      <div class="nilm-workspace">
        ${this._renderNilmWorkspaceSummary(workspace)}
        <section class="workspace-section nilm-graph-section section-surface">${this._renderNilmGraph(workspace, graphWindow, graphBands)}</section>
        ${intervalEditor || intervalFeedback ? `<section class="workspace-section nilm-interval-editor-section section-surface">${intervalEditor}${intervalFeedback}</section>` : ""}
        <section class="workspace-section section-surface">${this._renderNilmWorkspaceLanes(workspace)}</section>
        <section class="workspace-section section-surface">${this._renderNilmReviewLayout(workspace)}</section>
        <section class="workspace-section section-surface">${this._renderNilmSecondaryCollections(workspace)}</section>
      </div>
    `;
  }

  _renderNilmWorkspaceSummary(workspace) {
    const circuit = workspace && workspace.circuit || {};
    const laneCounts = workspace && workspace.lane_counts && typeof workspace.lane_counts === "object"
      ? workspace.lane_counts
      : {};
    const lanes = workspace && workspace.lanes && typeof workspace.lanes === "object"
      ? workspace.lanes
      : {};
    const needsReview = this._nilmLaneCount(lanes.needs_review || {}, laneCounts.needs_review);
    const total = Object.keys(laneCounts).reduce((sum, key) => {
      return sum + this._nilmLaneCount(lanes[key] || {}, laneCounts[key]);
    }, 0);
    const reviewed = Math.max(0, total - needsReview);
    const progressText = this._panelTextFormat("nilm_workspace.review_progress_value", { reviewed, total });
    const sources = Array.isArray(workspace.sources) ? workspace.sources : [];
    const sourcePicker = sources.length > 1 ? `
      <label class="nilm-label-field">
        <span class="muted">${this._escape(this._panelText("nilm_workspace.source_picker_label"))}</span>
        <select data-nilm-source-picker aria-label="${this._escape(this._panelText("nilm_workspace.source_picker_label"))}">
          ${sources.map((source) => `<option value="${this._escape(source.path || "")}" ${source.circuit_id === circuit.circuit_id ? "selected" : ""}>${this._escape(source.name || source.circuit_id || "")}</option>`).join("")}
        </select>
      </label>` : "";
    return `
      <section class="workspace-summary section-surface" data-nilm-workspace-summary aria-label="${this._escape(this._panelText("nilm_workspace.workspace_summary"))}">
        <div class="workspace-summary-item">
          <span>${this._escape(this._panelText("nilm_workspace.circuit"))}</span>
          <strong>${this._escape(circuit.name || circuit.circuit_id || this._panelText("common.unknown"))}</strong>
        </div>
        ${sourcePicker}
        <div class="workspace-summary-item">
          <span>${this._escape(this._panelText("nilm_workspace.lane_needs_review"))}</span>
          <strong>${needsReview}</strong>
        </div>
        <label class="workspace-progress">
          <span>${this._escape(this._panelText("nilm_workspace.review_progress"))}</span>
          <progress data-nilm-review-progress value="${reviewed}" max="${Math.max(1, total)}" aria-label="${this._escape(`${this._panelText("nilm_workspace.review_progress")}: ${progressText}`)}">${this._escape(progressText)}</progress>
          <strong>${this._escape(progressText)}</strong>
        </label>
      </section>
    `;
  }

  _renderNilmGraph(workspace, graphWindow, graphBands) {
    const series = this._visibleNilmWorkspaceSeries(workspace, graphWindow);
    const graph = this._nilmWorkspaceHistoryLoading
      ? `<div class="loading-skeleton graph-loading-skeleton" data-loading-skeleton role="status" aria-label="${this._escape(this._panelText("chart.loading_history"))}"></div>`
      : this._nilmWorkspaceHistoryError
        ? `<div data-nilm-history-error><p class="muted">${this._escape(this._nilmWorkspaceHistoryError)}</p><button type="button" class="secondary" data-retry-nilm-history>${this._escape(this._panelText("common.retry"))}</button></div>`
        : graphWindow && series.length
          ? this._chartSvg(series, { graph_window_start: new Date(graphWindow.start).toISOString(), graph_window_end: new Date(graphWindow.end).toISOString(), y_axis_label: "W", nilm_select_interval: this._nilmIntervalEditorOpen, nilm_edges: workspace.edges, nilm_sessions: graphBands })
          : `<p class="muted">${this._escape(this._panelText("nilm_workspace.no_graph_history"))}</p>`;
    return `
      ${this._nilmFocusedSignature ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.focused_graph"))}</p>` : ""}
      ${this._renderNilmGraphControls(graphWindow)}
      ${graph}
      ${!this._nilmIntervalEditorOpen ? `<div class="actions">
        <button type="button" class="secondary" data-nilm-open-interval-editor>${this._escape(this._panelText("nilm_workspace.label_interval"))}</button>
      </div>` : ""}
    `;
  }

  _nilmGraphBands(workspace, sessions) {
    const assignments = Array.isArray(workspace.assignments) ? workspace.assignments : [];
    const hiddenAssignments = new Set(assignments
      .filter((item) => ["ignored", "expected", "retired"].includes(String(item.lifecycle_state || "").toLowerCase()))
      .map((item) => item.assignment_id));
    const hiddenIntervalIds = new Set(assignments
      .filter((item) => hiddenAssignments.has(item.assignment_id))
      .flatMap((item) => item.label_interval_ids || []));
    const draft = this._nilmLabelIntervalDraft || {};
    const draftIntervals = this._nilmIntervalDraftItems();
    const editingIntervalIds = new Set(draftIntervals
      .map((item) => item.interval_id)
      .filter(Boolean));
    const labelBands = (workspace.label_intervals || []).flatMap((item, index) => (
      hiddenAssignments.has(item.assignment_id)
        || hiddenIntervalIds.has(item.interval_id)
        || editingIntervalIds.has(item.interval_id)
        ? []
        : [{ ...item, band_kind: "label", label_interval_index: index }]
    ));
    const draftBands = this._nilmIntervalEditorOpen ? draftIntervals.flatMap((item, index) => (
      item.start && item.end
        ? [{
          ...item,
          band_kind: "draft",
          draft_index: index,
          display_label: draft.label,
          selected: index === this._nilmActiveIntervalIndex,
        }]
        : []
    )) : [];
    return [...(sessions || []), ...labelBands, ...draftBands];
  }

  _renderNilmSecondaryCollections(workspace) {
    return `<details class="disclosure section-surface" data-nilm-secondary-details>
      <summary>${this._escape(this._panelText("nilm_workspace.secondary_details"))}</summary>
      <div class="disclosure-content">
        ${this._renderNilmSessionValidationCards(workspace)}
        ${this._renderNilmWorkspaceList(this._panelText("nilm_workspace.estimated_appliances_title"), workspace.virtual_appliances, this._panelText("nilm_workspace.estimated_appliances_empty"), (item) => `
        <div class="metric">
          <span>${this._escape(item.model_status || this._panelText("common.candidate"))}</span>
          <strong>${this._escape(item.display_name || item.appliance_id || this._panelText("common.estimated_appliance"))} - ${this._escape(item.is_running ? this._panelText("common.running") : this._panelText("common.idle"))}</strong>
          <p class="muted" data-field="estimated_daily_energy">${this._escape(this._panelTextFormat("nilm_workspace.estimated_appliance_summary", { power: this._formatMetricValue(item.estimated_power_w), energy: this._formatMetricValue(item.estimated_energy_kwh_today), confidence: Math.round(Number(item.confidence || 0) * 100) }))}</p>
          <div class="actions">${this._nilmApplianceDetailButton(item)}</div>
        </div>
      `, this._panelText("nilm_workspace.estimated_appliances_description"))}
        ${this._renderNilmValidation(workspace.validation)}
        ${this._renderNilmWorkspaceList(this._panelText("nilm_workspace.known_load_overlays"), workspace.known_load_overlays, this._panelText("nilm_workspace.known_load_overlays_empty"), (item) => `
        <div class="metric">
          <span>${this._escape(item.circuit_id)}</span>
          <strong>${this._escape(item.name || item.circuit_id)}</strong>
          <p class="muted">${this._escape(this._overlayEntitySummary(item))}</p>
        </div>
      `, this._panelText("nilm_workspace.known_load_overlays_description"))}
        ${this._renderNilmWorkspaceList(this._panelText("nilm_workspace.solar_net_overlays"), workspace.solar_overlays, this._panelText("nilm_workspace.solar_net_overlays_empty"), (item) => `
        <div class="metric">
          <span>${this._escape(item.circuit_id)}</span>
          <strong>${this._escape(item.name || item.circuit_id)}</strong>
          <p class="muted">${this._escape(this._overlayEntitySummary(item))}</p>
        </div>
      `, this._panelText("nilm_workspace.solar_net_overlays_description"))}
        ${this._renderNilmWorkspaceList(this._panelText("nilm_workspace.sessions_title"), workspace.sessions, this._panelText("nilm_workspace.sessions_empty"), (item, index) => `
        <div class="metric">
          <span>${this._escape(item.start || "")}</span>
          <strong>${this._escape(this._panelTextFormat("nilm_workspace.session_summary", { power: this._formatMetricValue(item.median_power_w), confidence: Math.round(Number(item.confidence || 0) * 100) }))}</strong>
          <p class="muted">${this._escape(item.end ? this._panelTextFormat("nilm_workspace.session_end", { end: item.end }) : this._panelText("common.open_session"))}</p>
          ${item.actions && item.actions.assign ? this._renderNilmSessionAssignField(item, index) : ""}
          ${item.actions && item.actions.assign ? `<div class="actions">
            <button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="assign" ${this._busyAction === `nilm_sessions_${index}_assign` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.assign_appliance"))}</button>
          </div>` : ""}
        </div>
      `, this._panelText("nilm_workspace.sessions_description"))}
        ${this._renderNilmWorkspaceList(this._panelText("nilm_workspace.edges_title"), workspace.edges, this._panelText("nilm_workspace.edges_empty"), (item) => `
        <div class="metric">
          <span>${this._escape(item.timestamp || "")}</span>
          <strong>${this._escape(this._friendlyFeature(item.direction))}: ${this._escape(this._formatMetricValue(item.delta_w))} W</strong>
          <p class="muted">${this._escape(item.split_phase_type || this._panelText("common.unknown"))}</p>
        </div>
        `, this._panelText("nilm_workspace.edges_description"))}
      </div>
    </details>`;
  }

  _nilmLaneItems(workspace, laneKey = this._nilmActiveLane) {
    const activeLaneKey = workspace.lanes[laneKey] ? laneKey : "needs_review";
    if (laneKey === this._nilmActiveLane) this._nilmActiveLane = activeLaneKey;
    const lane = workspace.lanes[activeLaneKey] || {};
    const signatureIds = new Set(Array.isArray(lane.signature_ids) ? lane.signature_ids : []);
    const assignmentIds = new Set(Array.isArray(lane.assignment_ids) ? lane.assignment_ids : []);
    const intervalIds = new Set(Array.isArray(lane.interval_ids) ? lane.interval_ids : []);
    const signatures = (Array.isArray(workspace && workspace.signatures) ? workspace.signatures : [])
      .map((item, index) => ({ kind: "signature", item, index }))
      .filter(({ item }) => signatureIds.has(item.signature_id));
    const assignments = (Array.isArray(workspace && workspace.assignments) ? workspace.assignments : [])
      .map((item, index) => ({ kind: "assignment", item, index }))
      .filter(({ item }) => assignmentIds.has(item.assignment_id));
    const intervals = (Array.isArray(workspace && workspace.label_intervals) ? workspace.label_intervals : [])
      .map((item, index) => ({ kind: "interval", item, index }))
      .filter(({ item }) => intervalIds.has(item.interval_id));
    return [...signatures, ...assignments, ...intervals];
  }

  _nilmReviewKey(reviewItem) {
    const id = reviewItem.kind === "assignment"
      ? reviewItem.item.assignment_id
      : reviewItem.kind === "interval"
        ? reviewItem.item.interval_id
        : reviewItem.item.signature_id || this._nilmSignatureFingerprint(reviewItem.item);
    return `${reviewItem.kind}:${id}`;
  }

  _nilmSelectedReviewItem(workspace) {
    const items = this._nilmLaneItems(workspace);
    return items.find((item) => this._nilmReviewKey(item) === this._nilmSelectedReviewKey) || items[0] || null;
  }

  _nilmPowerPercent(reviewItem, reviewItems) {
    const itemPower = (item) => Number(item.typical_power_w ?? item.estimated_power_w ?? item.median_power_w);
    const visiblePowers = reviewItems.map(({ item }) => itemPower(item)).filter(Number.isFinite);
    const maxPower = Math.max(0, ...visiblePowers);
    const power = itemPower(reviewItem.item);
    if (!Number.isFinite(power) || maxPower <= 0) {
      return 0;
    }
    return Math.max(0, Math.min(100, Math.round((power / maxPower) * 100)));
  }

  _renderNilmReviewCard(reviewItem, reviewItems, selected) {
    const item = reviewItem.item;
    const title = item.display_label || item.display_name || item.label || item.likely_type || this._panelText("common.unknown_load");
    const confidence = Math.max(0, Math.min(100, Math.round(Number(item.confidence || 0) * 100)));
    const power = item.typical_power_w ?? item.estimated_power_w ?? item.median_power_w;
    const fingerprint = reviewItem.kind === "signature" ? this._nilmSignatureFingerprint(item) : "";
    const contextFacts = reviewItem.kind === "signature" ? [
      item.seen_count !== undefined
        ? `${this._panelText("nilm_workspace.fact_seen_count")}: ${item.seen_count}`
        : "",
      item.last_seen
        ? `${this._panelText("nilm_workspace.fact_last_seen")}: ${this._formatDateTime(item.last_seen)}`
        : "",
    ].filter(Boolean) : [];
    if (reviewItem.kind === "interval") {
      return `<button type="button" class="nilm-review-card" data-nilm-review-item="${this._escape(this._nilmReviewKey(reviewItem))}" aria-pressed="${selected}">
        <span class="review-card-heading"><strong>${this._escape(title)}</strong><span>${this._escape(this._panelText("nilm_workspace.lane_needs_review"))}</span></span>
        <span class="review-card-facts"><span>${this._escape(this._formatDateTime(item.start))}</span><span>${this._escape(this._formatDateTime(item.end))}</span></span>
      </button>`;
    }
    return `<button type="button" class="nilm-review-card" data-nilm-review-item="${this._escape(this._nilmReviewKey(reviewItem))}" ${fingerprint ? `data-nilm-signature-fingerprint="${this._escape(fingerprint)}"` : ""} aria-pressed="${selected}">
      <span class="review-card-heading"><strong>${this._escape(title)}</strong><span>${this._escape(this._friendlyFeature(item.review_state || item.lifecycle_state || this._nilmActiveLane))}</span></span>
      <span class="power-meter" style="--power-percent:${this._nilmPowerPercent(reviewItem, reviewItems)}%"><span></span></span>
      <span class="review-card-facts"><span>${this._escape(this._formatMetricValue(power))} W</span><span>${confidence}%</span></span>
      ${contextFacts.length ? `<span class="review-card-facts review-card-context">${contextFacts.map((fact) => `<span>${this._escape(fact)}</span>`).join("")}</span>` : ""}
      <progress max="100" value="${confidence}" aria-label="${this._escape(this._panelTextFormat("nilm_workspace.assignment_confidence", { confidence }))}"></progress>
    </button>`;
  }

  _renderNilmReviewInspector(reviewItem) {
    const item = reviewItem.item;
    const title = item.display_label || item.display_name || item.label || item.likely_type || item.appliance_id || this._panelText("common.unknown_load");
    const content = reviewItem.kind === "assignment"
      ? `
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_confidence", { confidence: Math.round(Number(item.confidence || 0) * 100) }))}</p>
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_rates", { false_positive: Math.round(Number(item.false_positive_rate || 0) * 100), false_negative: Math.round(Number(item.false_negative_rate || 0) * 100) }))}</p>
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_errors", { power: this._formatMetricValue(item.median_power_error), energy: this._formatMetricValue(item.energy_estimate_error) }))}</p>
        ${this._renderNilmAssignmentEditFields(item, reviewItem.index)}
        ${this._renderNilmAssignmentActions(item, reviewItem.index)}
        ${this._renderInlineFeedback(this._nilmReviewKey(reviewItem))}
      `
      : reviewItem.kind === "interval"
        ? `<p class="muted">${this._escape(this._formatNilmSessionRange(item))}</p>
          <div class="actions"><button type="button" class="secondary" data-nilm-label-interval-index="${reviewItem.index}" data-nilm-label-interval-action="adjust">${this._escape(this._panelText("actions.labels.complete_interval"))}</button></div>`
        : `
        ${this._renderNilmSignatureFacts(item)}
        ${this._renderNilmSignatureReview(item, reviewItem.index)}
      `;
    return `<div class="nilm-review-inspector section-surface" data-nilm-review-inspector role="region" aria-label="${this._escape(title)}">
      <h2>${this._escape(title)}</h2>
      ${content}
    </div>`;
  }

  _renderNilmReviewLayout(workspace) {
    const reviewItems = this._nilmLaneItems(workspace);
    const lane = workspace && workspace.lanes && workspace.lanes[this._nilmActiveLane];
    const laneLabel = (lane && lane.label) || this._friendlyFeature(this._nilmActiveLane);
    const selectedItem = reviewItems.length ? this._nilmSelectedReviewItem(workspace) : null;
    const selectedKey = selectedItem ? this._nilmReviewKey(selectedItem) : "";
    return `<div class="nilm-review-layout" id="nilm_review_lane_panel" role="tabpanel" aria-labelledby="nilm_lane_${this._escape(this._nilmActiveLane)}">
      <div class="nilm-review-list section-surface">
      ${this._renderInlineFeedback("nilm-review")}
      ${reviewItems.length ? reviewItems.map((reviewItem) => {
        const selected = this._nilmReviewKey(reviewItem) === selectedKey;
        return this._renderNilmReviewCard(reviewItem, reviewItems, selected);
      }).join("") : `<p class="muted nilm-lane-empty" data-nilm-lane-empty role="status">${this._escape(this._panelTextFormat("nilm_workspace.lane_empty", { lane: laneLabel }))}</p>`}
      </div>
      ${selectedItem ? this._renderNilmReviewInspector(selectedItem) : ""}
    </div>`;
  }

  _activateNilmLane(laneKey) {
    this._nilmActiveLane = laneKey || "needs_review";
    this._nilmSelectedReviewKey = "";
    this._nilmFocusedSignature = "";
    this._render();
  }

  _handleNilmLaneKeydown(event, button) {
    const tabs = Array.from(this.shadowRoot.querySelectorAll("[data-nilm-lane]"));
    const index = tabs.indexOf(button);
    if (index < 0 || !tabs.length) {
      return;
    }
    const targetIndex = event.key === "ArrowRight"
      ? (index + 1) % tabs.length
      : event.key === "ArrowLeft"
      ? (index - 1 + tabs.length) % tabs.length
      : event.key === "Home"
      ? 0
      : event.key === "End"
      ? tabs.length - 1
      : -1;
    if (targetIndex < 0) {
      return;
    }
    event.preventDefault();
    const target = tabs[targetIndex];
    this._activateNilmLane(target.dataset.nilmLane);
    this._restoreNilmFocus({
      selector: "[data-nilm-lane]",
      dataKey: "nilmLane",
      key: target.dataset.nilmLane,
      value: target.value,
    });
  }

  _nilmLaneCount(lane, countValue) {
    const count = Number(countValue);
    return Number.isFinite(count)
      ? count
      : (Array.isArray(lane.assignment_ids) ? lane.assignment_ids.length : 0)
        + (Array.isArray(lane.signature_ids) ? lane.signature_ids.length : 0)
        + (Array.isArray(lane.interval_ids) ? lane.interval_ids.length : 0);
  }

  _renderNilmWorkspaceLanes(workspace) {
    const lanes = workspace && workspace.lanes && typeof workspace.lanes === "object"
      ? workspace.lanes
      : {};
    const laneCounts = workspace && workspace.lane_counts && typeof workspace.lane_counts === "object"
      ? workspace.lane_counts
      : {};
    const laneOrder = [
      ["needs_review", this._panelText("nilm_workspace.lane_needs_review")],
      ["assigned", this._panelText("nilm_workspace.lane_assigned")],
      ["published", this._panelText("nilm_workspace.lane_published")],
      ["ignored_expected", this._panelText("nilm_workspace.lane_ignored_expected")],
    ];
    if (!Object.keys(lanes).length && !Object.keys(laneCounts).length) {
      return "";
    }
    return `
      <div class="nilm-lanes" role="tablist" aria-label="${this._escape(this._panelText("nilm_workspace.review_lanes"))}">
        ${laneOrder.map(([key, fallbackLabel]) => {
          const lane = lanes[key] || {};
          const count = this._nilmLaneCount(lane, laneCounts[key]);
          const selected = this._nilmActiveLane === key;
          return `<button type="button" role="tab" class="nilm-lane" id="nilm_lane_${key}" data-nilm-lane="${key}" aria-controls="nilm_review_lane_panel" aria-selected="${selected}" tabindex="${selected ? "0" : "-1"}"><span>${this._escape(lane.label || fallbackLabel)}</span><strong>${count}</strong></button>`;
        }).join("")}
      </div>
    `;
  }

  _renderNilmSessionValidationCards(workspace) {
    const sessions = Array.isArray(workspace && workspace.sessions)
      ? workspace.sessions
      : [];
    const reviewedSessionIds = this._nilmReviewedSessionIds(workspace);
    const cards = sessions.map((session, index) => ({ session, index })).filter(({ session }) => {
      const actions = session && session.actions;
      const sessionId = String(session && session.session_id || "").trim();
      return session
        && session.assignment_id
        && (!sessionId || !reviewedSessionIds.has(sessionId))
        && actions
        && (actions.validate || actions.reject);
    });
    if (!cards.length) {
      return "";
    }
    return `
      <h3>${this._escape(this._panelText("nilm_workspace.session_validation"))}</h3>
      <div class="entity-list">
        ${cards.map(({ session, index }) => this._renderNilmSessionValidationCard(session, index)).join("")}
      </div>
    `;
  }

  _nilmReviewedSessionIds(workspace) {
    const reviewed = new Set();
    const assignments = Array.isArray(workspace && workspace.assignments)
      ? workspace.assignments
      : [];
    for (const assignment of assignments) {
      for (const key of ["confirmed_session_ids", "rejected_session_ids"]) {
        const ids = Array.isArray(assignment && assignment[key]) ? assignment[key] : [];
        for (const id of ids) {
          const sessionId = String(id || "").trim();
          if (sessionId) {
            reviewed.add(sessionId);
          }
        }
      }
    }
    return reviewed;
  }

  _renderNilmSessionValidationCard(session, index) {
    const actions = session && session.actions ? session.actions : {};
    const label = session.display_label || session.display_name || session.appliance_id || session.assignment_id || this._panelText("common.appliance");
    const confidence = session.confidence !== undefined
      ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.confidence_value", { confidence: this._formatConfidence(session.confidence) }))}</p>`
      : "";
    const lowConfidence = this._isLowNilmConfidence(session.confidence)
      ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.low_confidence"))}</p>`
      : "";
    const duration = this._nilmSessionDuration(session);
    return `
      <div class="metric">
        <span>${this._escape(this._formatNilmSessionRange(session))}</span>
        <strong>${this._escape(this._panelTextFormat("nilm_workspace.predicted", { label }))}</strong>
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.estimated_by_nilm", { duration: duration ? `, ${duration}` : "" }))}</p>
        ${confidence}
        ${lowConfidence}
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.session_power_summary", { power: this._formatMetricValue(session.median_power_w), energy: this._formatMetricValue(session.estimated_energy_kwh) }))}</p>
        <div class="actions">
          ${actions.validate ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="validate" ${this._busyAction === `nilm_sessions_${index}_validate` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.correct"))}</button>` : ""}
          ${actions.reject ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="reject" ${this._busyAction === `nilm_sessions_${index}_reject` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.wrong_appliance_sentence"))}</button>` : ""}
          ${session.start && session.end ? `<button type="button" class="secondary" data-nilm-session-interval-index="${index}">${this._escape(this._panelText("actions.labels.adjust_interval"))}</button>` : ""}
        </div>
      </div>
    `;
  }

  _nilmSessionDuration(session) {
    const explicitDuration = Number(session && session.duration_seconds);
    if (Number.isFinite(explicitDuration)) {
      return this._formatDuration(explicitDuration);
    }
    const start = Date.parse(session && session.start || "");
    const end = Date.parse(session && session.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return "";
    }
    return this._formatDuration((end - start) / 1000);
  }

  _formatNilmSessionRange(session) {
    const start = this._formatDateTime(session && session.start);
    if (!session || !session.end) {
      return this._panelTextFormat("nilm_workspace.range_open", { start });
    }
    return `${start} - ${this._formatDateTime(session.end)}`;
  }

  _renderNilmSignatureFacts(signature) {
    const facts = [];
    const addFact = (label, value) => {
      if (value !== null && value !== undefined && value !== "") {
        facts.push([label, value]);
      }
    };
    addFact(this._panelText("nilm_workspace.fact_typical_power"), signature.typical_power_w !== undefined ? `${this._formatMetricValue(signature.typical_power_w)} W` : undefined);
    addFact(this._panelText("nilm_workspace.fact_typical_duration"), signature.typical_duration_seconds !== undefined ? this._formatDuration(signature.typical_duration_seconds) : undefined);
    addFact(this._panelText("nilm_workspace.fact_seen_count"), signature.seen_count);
    addFact(this._panelText("nilm_workspace.fact_voltage_class"), signature.voltage_class);
    addFact(this._panelText("nilm_workspace.fact_dominant_leg"), signature.dominant_leg);
    addFact(this._panelText("nilm_workspace.fact_known_load_overlap"), this._formatNilmSignatureFact(signature.known_load_overlap));
    addFact(this._panelText("nilm_workspace.fact_why_grouped"), signature.why_grouped);
    addFact(this._panelText("nilm_workspace.fact_last_seen"), signature.last_seen ? this._formatDateTime(signature.last_seen) : undefined);
    if (!facts.length) {
      return "";
    }
    return facts.map(([label, value]) => `<p class="muted">${this._escape(label)}: ${this._escape(this._formatMetricValue(value))}</p>`).join("");
  }

  _formatNilmSignatureFact(value) {
    if (Array.isArray(value)) {
      return value.join(", ");
    }
    if (value && typeof value === "object") {
      return JSON.stringify(value);
    }
    return value;
  }

  _renderNilmIntervalFeedback() {
    const feedback = this._renderInlineFeedback("nilm-interval");
    const refreshButton = this._nilmIntervalRefreshSuccessMessage
      ? `<div class="actions"><button type="button" class="secondary" data-nilm-interval-refresh-retry ${this._busyAction === "nilm_interval_refresh" ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.retry_refresh"))}</button></div>`
      : "";
    const actionButton = !refreshButton && this._nilmIntervalFailedAction
      ? `<div class="actions"><button type="button" class="secondary" data-nilm-interval-retry="${this._escape(this._nilmIntervalFailedAction)}" data-nilm-interval-retry-index="${this._nilmIntervalFailedIndex}">${this._escape(this._panelText("common.retry"))}</button></div>`
      : "";
    return `${feedback}${refreshButton}${actionButton}`;
  }

  _renderNilmLabelIntervalEditor(workspace) {
    const draft = this._nilmLabelIntervalDraft || {};
    const intervals = this._nilmIntervalDraftItems();
    const editorOpen = this._nilmIntervalEditorOpen || intervals.some((item) => item.start || item.end);
    if (!editorOpen) {
      return "";
    }
    const action = workspace && workspace.actions && workspace.actions.label_interval;
    const profileOptions = action && Array.isArray(action.profile_options)
      ? action.profile_options
      : [];
    const saveBusy = this._busyAction === "nilm_label_interval_save" ? "disabled" : "";
    const intervalPreview = this._nilmLabelIntervalEnergyPreview();
    return `<div class="metric" data-nilm-interval-editor>
        <h3>${this._escape(this._panelText("nilm_workspace.interval_prompt"))}</h3>
        <p class="muted">${this._escape(this._panelText("nilm_workspace.interval_prompt_detail"))}</p>
        <div class="nilm-interval-form nilm-interval-identity">
          <label>
            <span class="muted">${this._escape(this._panelText("nilm_workspace.label"))}</span>
            <input type="text" data-nilm-label-interval-input="label" value="${this._escape(draft.label || "")}" placeholder="${this._escape(this._panelText("nilm_workspace.appliance_name"))}">
          </label>
          <label>
            <span class="muted">${this._escape(this._panelText("nilm_workspace.appliance_type"))}</span>
            <select data-nilm-label-interval-input="appliance_profile">
              <option value="">${this._escape(this._panelText("nilm_workspace.select_appliance_type"))}</option>
              ${profileOptions.map((option) => `<option value="${this._escape(option.value || "")}" ${String(option.value || "") === String(draft.appliance_profile || "") ? "selected" : ""}>${this._escape(option.label || option.value || "")}</option>`).join("")}
            </select>
          </label>
        </div>
        <div class="nilm-interval-rows">
          ${intervals.map((interval, index) => `<div class="nilm-interval-row" data-nilm-interval-row="${index}" data-nilm-active="${index === this._nilmActiveIntervalIndex}">
            <div class="nilm-interval-row-heading">
              <strong>${this._escape(this._panelTextFormat("nilm_workspace.interval_number", { number: index + 1 }))}</strong>
              <span data-nilm-editing-indicator="${index}" ${index === this._nilmActiveIntervalIndex ? "" : "hidden"}>${this._escape(this._panelTextFormat("nilm_workspace.editing_interval", { number: index + 1 }))}</span>
              <button type="button" class="secondary icon-button" data-nilm-remove-interval="${index}" title="${this._escape(this._panelText("actions.labels.remove_interval"))}" aria-label="${this._escape(this._panelText("actions.labels.remove_interval"))}"><ha-icon icon="mdi:delete-outline"></ha-icon></button>
            </div>
            <div class="nilm-interval-form">
              <label><span class="muted">${this._escape(this._panelText("nilm_workspace.start"))}</span><input type="datetime-local" data-nilm-label-interval-input="start" data-nilm-interval-index="${index}" value="${this._escape(interval.start || "")}"></label>
              <label><span class="muted">${this._escape(this._panelText("nilm_workspace.end"))}</span><input type="datetime-local" data-nilm-label-interval-input="end" data-nilm-interval-index="${index}" value="${this._escape(interval.end || "")}"></label>
            </div>
          </div>`).join("")}
        </div>
        <div class="actions">
          <button type="button" data-nilm-label-interval-action="save" ${saveBusy}>${this._escape(this._panelText("actions.labels.save_interval"))}</button>
        </div>
        ${intervalPreview ? `<p class="muted" data-field="nilm_interval_energy_preview">${this._escape(this._panelTextFormat("nilm_workspace.interval_energy_preview", { energy: this._formatNumber(intervalPreview.energy_kwh), duration: this._formatNumber(intervalPreview.duration_minutes), source: intervalPreview.source_name }))}</p>` : ""}
      </div>`;
  }

  _nilmLabelIntervalEnergyPreview() {
    const interval = this._nilmIntervalDraftItems()[this._nilmActiveIntervalIndex] || {};
    const start = new Date(interval.start || "").getTime();
    const end = new Date(interval.end || "").getTime();
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return null;
    }
    const series = this._nilmWorkspaceWattSeries();
    const powerSeries = series.find((item) => {
      const label = `${item.entity_id || ""} ${item.name || ""}`;
      return /power|watt|(?:^|[_\s-])w(?:$|[_\s-])/i.test(label);
    });
    const points = powerSeries && Array.isArray(powerSeries.points)
      ? powerSeries.points.filter((point) => point.time >= start && point.time <= end)
      : [];
    if (points.length < 2) {
      return null;
    }
    let wattHours = 0;
    for (let index = 1; index < points.length; index += 1) {
      const previous = points[index - 1];
      const current = points[index];
      const hours = (current.time - previous.time) / 3600000;
      if (hours > 0) {
        wattHours += ((previous.value + current.value) / 2) * hours;
      }
    }
    if (!Number.isFinite(wattHours)) {
      return null;
    }
    return {
      energy_kwh: Math.max(wattHours / 1000, 0),
      duration_minutes: (end - start) / 60000,
      source_name: powerSeries.name || powerSeries.entity_id || this._panelText("nilm_workspace.displayed_power_samples"),
    };
  }

  _renderNilmSessionAssignField(session, index) {
    const draftKey = this._nilmSessionLabelDraftKey(session);
    const currentLabel = this._nilmSessionLabelDrafts.has(draftKey)
      ? this._nilmSessionLabelDrafts.get(draftKey)
      : "";
    return `
      ${this._renderNilmExistingAssignmentField(session && session.actions && session.actions.assign, `sessions_${index}`)}
      <label class="nilm-label-field" for="nilm_session_label_${index}">
        <span class="muted">${this._escape(this._panelText("nilm_workspace.appliance_name"))}</span>
        <input
          id="nilm_session_label_${index}"
          type="text"
          data-nilm-session-label-input
          data-nilm-session-label-key="${this._escape(draftKey)}"
          value="${this._escape(currentLabel)}"
          placeholder="${this._escape(this._panelText("nilm_workspace.appliance_name"))}"
        >
      </label>
    `;
  }

  _nilmSessionLabelDraftKey(session) {
    return String((session && session.session_id) || "");
  }

  _renderNilmAssignmentEditFields(item, index) {
    const actions = item && item.actions;
    if (!actions || (!actions.rename && !actions.change_profile && !actions.merge && !actions.convert_to_direct_meter)) {
      return "";
    }
    const draftKey = this._nilmAssignmentDraftKey(item);
    const label = this._nilmAssignmentDraftValue(draftKey, "label", item.display_name || "");
    const profile = this._nilmAssignmentDraftValue(draftKey, "appliance_profile", item.appliance_profile || "");
    const profileOptions = actions.change_profile && Array.isArray(actions.change_profile.profile_options)
      ? actions.change_profile.profile_options
      : [];
    return `
      <div class="grid">
        ${actions.rename ? `<label class="nilm-label-field" for="nilm_assignment_label_${index}">
          <span class="muted">${this._escape(this._panelText("nilm_workspace.appliance_name"))}</span>
          <input id="nilm_assignment_label_${index}" type="text" data-nilm-assignment-input data-nilm-assignment-key="${this._escape(draftKey)}" data-nilm-assignment-field="label" value="${this._escape(label)}" placeholder="${this._escape(this._panelText("nilm_workspace.appliance_name"))}">
        </label>` : ""}
        ${actions.change_profile ? `<label class="nilm-label-field" for="nilm_assignment_profile_${index}">
          <span class="muted">${this._escape(this._panelText("nilm_workspace.appliance_type"))}</span>
          <select id="nilm_assignment_profile_${index}" data-nilm-assignment-input data-nilm-assignment-key="${this._escape(draftKey)}" data-nilm-assignment-field="appliance_profile">
            ${profileOptions.map((option) => `<option value="${this._escape(option.value || "")}" ${String(option.value || "") === String(profile) ? "selected" : ""}>${this._escape(option.label || option.value || "")}</option>`).join("")}
          </select>
        </label>` : ""}
        ${actions.merge ? `<label class="nilm-label-field" for="nilm_assignment_merge_target_${index}">
          <span class="muted">${this._escape(this._panelText("nilm_workspace.merge_into"))}</span>
          <select id="nilm_assignment_merge_target_${index}" data-nilm-assignment-merge-target>
            <option value="">${this._escape(this._panelText("actions.labels.do_not_merge"))}</option>
            ${(actions.merge.target_options || []).map((option) => `<option value="${this._escape(option.value || "")}">${this._escape(option.label || option.value || "")}</option>`).join("")}
          </select>
        </label>` : ""}
        ${actions.convert_to_direct_meter ? `<label class="nilm-label-field" for="nilm_assignment_direct_target_${index}">
          <span class="muted">${this._escape(this._panelText("nilm_workspace.direct_meter_circuit"))}</span>
          <select id="nilm_assignment_direct_target_${index}" data-nilm-assignment-direct-target>
            <option value="">${this._escape(this._panelText("nilm_workspace.select_direct_meter_circuit"))}</option>
            ${(actions.convert_to_direct_meter.target_options || []).map((option) => `<option value="${this._escape(option.value || "")}">${this._escape(option.label || option.value || "")}</option>`).join("")}
          </select>
        </label>` : ""}
      </div>
    `;
  }

  _nilmAssignmentDraftKey(item) {
    return String((item && item.assignment_id) || "");
  }

  _nilmAssignmentDraftValue(draftKey, field, fallback) {
    const key = `${draftKey}:${field}`;
    return this._nilmAssignmentDrafts.has(key)
      ? this._nilmAssignmentDrafts.get(key)
      : fallback;
  }

  _renderNilmAssignmentActions(item, index) {
    const actions = item && item.actions;
    const detailButton = this._nilmApplianceDetailButton(item);
    if ((!actions || !Object.keys(actions).length) && !detailButton) {
      return "";
    }
    if (!actions || !Object.keys(actions).length) {
      return `<div class="actions">${detailButton}</div>`;
    }
    const hasSave = actions.rename || actions.change_profile;
    const saveDirty = this._nilmAssignmentHasChanges(item);
    return `
      <div class="actions">
        ${detailButton}
        ${hasSave ? `<button type="button" class="${saveDirty ? "" : "secondary"}" data-nilm-assignment-index="${index}" data-nilm-assignment-action="save" data-nilm-assignment-save-key="${this._escape(item.assignment_id || "")}" ${this._busyAction === `nilm_assignments_${index}_save` || !saveDirty ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.save"))}</button>` : ""}
        ${actions.merge ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="merge" ${this._busyAction === `nilm_assignments_${index}_merge` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.merge"))}</button>` : ""}
        ${actions.convert_to_direct_meter ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="convert_to_direct_meter" ${this._busyAction === `nilm_assignments_${index}_convert_to_direct_meter` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.convert_to_direct_meter"))}</button>` : ""}
        ${actions.validate_history ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="validate_history" ${this._busyAction === `nilm_assignments_${index}_validate_history` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.validate_history"))}</button>` : ""}
        ${actions.publish ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="publish" ${this._busyAction === `nilm_assignments_${index}_publish` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.create_ha_device"))}</button>` : ""}
        ${actions.unpublish ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="unpublish" ${this._busyAction === `nilm_assignments_${index}_unpublish` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.remove_ha_device"))}</button>` : ""}
        ${actions.retire ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="retire" ${this._busyAction === `nilm_assignments_${index}_retire` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.remove_assignment"))}</button>` : ""}
      </div>
    `;
  }

  _nilmApplianceDetailButton(item) {
    const path = item && item.appliance_detail_path;
    if (!path) {
      return "";
    }
    return `<button type="button" class="secondary" data-nilm-appliance-detail-path="${this._escape(path)}">${this._escape(this._panelText("actions.labels.open_appliance_detail"))}</button>`;
  }

  _renderNilmValidation(validation) {
    if (!validation) {
      return "";
    }
    const metrics = validation.metrics || {};
    const preview = Array.isArray(validation.prediction_preview)
      ? validation.prediction_preview
      : [];
    return `
      <h3>${this._escape(this._panelText("nilm_workspace.validation"))}</h3>
      <p class="muted">${this._escape(this._panelText("nilm_workspace.validation_description"))}</p>
      <div class="summary">
        <div class="metric">
          <span>${this._escape(this._panelText("nilm_workspace.ground_truth"))}</span>
          <strong>${this._escape(metrics.ground_truth_interval_count || 0)}</strong>
        </div>
        <div class="metric">
          <span>${this._escape(this._panelText("nilm_workspace.precision"))}</span>
          <strong>${this._escape(Math.round(Number(metrics.precision || 0) * 100))}%</strong>
        </div>
        <div class="metric">
          <span>${this._escape(this._panelText("nilm_workspace.recall"))}</span>
          <strong>${this._escape(Math.round(Number(metrics.recall || 0) * 100))}%</strong>
        </div>
      </div>
      ${this._renderNilmWorkspaceList(this._panelText("nilm_workspace.prediction_preview"), preview, this._panelText("nilm_workspace.prediction_preview_empty"), (item) => `
        <div class="metric">
          <span>${this._escape(item.ground_truth_entity_id || "")}</span>
          <strong>${this._escape(item.label || this._panelText("nilm_workspace.ground_truth"))} - ${this._escape(item.prediction_status || this._panelText("nilm_workspace.prediction_missed"))}</strong>
          <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.prediction_overlap", { match: item.matched_assignment_id || this._panelText("nilm_workspace.no_matching_prediction"), seconds: this._formatMetricValue(item.overlap_seconds) }))}</p>
        </div>
      `, this._panelText("nilm_workspace.prediction_preview_description"))}
    `;
  }

  _renderNilmWorkspaceList(title, items, emptyText, renderItem, description = "") {
    const safeItems = Array.isArray(items) ? items : [];
    return `
      <h3>${this._escape(title)}</h3>
      ${description ? `<p class="muted">${this._escape(description)}</p>` : ""}
      ${safeItems.length ? `<div class="entity-list">${safeItems.map(renderItem).join("")}</div>` : `<p class="muted">${this._escape(emptyText)}</p>`}
    `;
  }

  _nilmSessionGraphLabel(session) {
    const label = session && (session.display_label || session.display_name || session.appliance_id || session.assignment_id || session.session_id);
    return String(label || "").trim();
  }

  _truncateNilmGraphLabel(label, maxLength) {
    const text = String(label || "").trim();
    if (!text || maxLength < 4 || text.length <= maxLength) {
      return text;
    }
    return `${text.slice(0, Math.max(1, maxLength - 3))}...`;
  }

  _renderNilmGraphControls(window) {
    if (!window) {
      return "";
    }
    return this._renderHistoryGraphControls(
      window,
      "nilm-graph",
      "data-nilm-workspace-graph",
      this._panelTextFormat("nilm_workspace.graph_window", { start: this._formatDateTime(new Date(window.start)), end: this._formatDateTime(new Date(window.end)) }),
    );
  }

  _nilmWorkspaceGraphWindow(workspace) {
    const history = (workspace && workspace.history) || {};
    return this._historyGraphWindow({
      min: Date.parse(history.start || ""),
      max: Date.parse(history.end || ""),
    }, this._nilmGraphWindow);
  }

  _visibleNilmWorkspaceSeries(_workspace, graphWindow) {
    return this._visibleParsedChartSeries(
      this._nilmWorkspaceWattSeries(),
      graphWindow,
    );
  }

  _nilmWorkspaceWattSeries() {
    return this._chartSeries(
      this._nilmWorkspaceHistorySeries,
      [],
      MAX_NILM_CHART_POINTS_PER_SERIES,
    ).map((item) => {
      const unit = String(item.unit || "").trim();
      const factor = unit === "MW" ? 1000000 : unit === "mW" ? 0.001 : unit.toLowerCase() === "kw" ? 1000 : 1;
      return {
        ...item,
        unit: "W",
        points: factor === 1 ? item.points : item.points.map((point) => ({
          ...point,
          value: point.value * factor,
        })),
      };
    });
  }

  _isLowNilmConfidence(value) {
    const confidence = Number(value);
    if (!Number.isFinite(confidence)) {
      return false;
    }
    const normalized = confidence <= 1 ? confidence : confidence / 100;
    return normalized < NILM_LOW_CONFIDENCE_THRESHOLD;
  }
  };
}
