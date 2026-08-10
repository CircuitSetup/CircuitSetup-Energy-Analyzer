export function createNilmWorkspaceMethods({
  NILM_WORKSPACE_API_PATH,
  NILM_WORKSPACE_CALL_API_PATH,
  NILM_INTERVAL_EVIDENCE_API_PATH,
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
    this._invalidateNilmHelperHistoryRequests();
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
      this._nilmSyncHelperSelection(workspace);
      await this._loadNilmWorkspaceHistory(workspace, requestId, routeKey);
      if (!this._isCurrentRequest(requestId, routeKey)) {
        return;
      }
      await this._focusNilmRouteTarget(workspace, routeKey);
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
    this._invalidateNilmFocusedHistoryRequests();
    const token = (this._nilmHelperHistoryToken || 0) + 1;
    this._nilmHelperHistoryToken = token;
    const isCurrent = () => token === this._nilmHelperHistoryToken
      && this._isCurrentRequest(requestId, routeKey);
    const historyPath = this._nilmHistoryPathWithHelpers(workspace && workspace.history && workspace.history.api_path);
    const historyFetchPath = (workspace && workspace.history && workspace.history.fetch_path)
      ? this._nilmHistoryPathWithHelpers(workspace.history.fetch_path)
      : (historyPath ? `/api/${historyPath}` : "");
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
      if (!isCurrent()) {
        return;
      }
      this._nilmWorkspaceHistorySeries = Array.isArray(history) ? history : [];
      this._nilmWorkspaceHistoryError = "";
      this._nilmWorkspaceHistoryFailedRequest = null;
    } catch (error) {
      if (!isCurrent()) {
        return;
      }
      this._nilmWorkspaceHistoryError = this._panelTextFormat("errors.load_nilm_workspace_history", { message: error.message });
    } finally {
      if (isCurrent()) {
        this._nilmWorkspaceHistoryLoading = false;
        this._render();
      }
    }
  }

  _decisionSignature(sourceKey) {
    const match = /^(signature|session)_(\d+)$/.exec(String(sourceKey || ""));
    if (!match) {
      return null;
    }
    const index = Number.parseInt(match[2], 10);
    if (match[1] === "signature") {
      return this._nilmReviewSignatures()[index] || null;
    }
    const sessions = this._nilmWorkspace && Array.isArray(this._nilmWorkspace.sessions)
      ? this._nilmWorkspace.sessions
      : [];
    return sessions[index] && sessions[index].signature_review || null;
  }

  _nilmDecisionSession(sourceKey) {
    const match = /^session_(\d+)$/.exec(String(sourceKey || ""));
    if (!match) {
      return null;
    }
    const sessions = this._nilmWorkspace && Array.isArray(this._nilmWorkspace.sessions)
      ? this._nilmWorkspace.sessions
      : [];
    return sessions[Number.parseInt(match[1], 10)] || null;
  }

  async _applyNilmDecision(sourceKey) {
    const signature = this._decisionSignature(sourceKey);
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
      this._setInlineFeedback(sourceKey, "error", this._panelText("errors.nilm_decision_required"));
      return;
    }
    await this._callNilmAction(signature, sourceKey, actionKey, sourceKey);
  }

  async _callNilmAction(signature, sourceKey, actionKey, feedbackScope = sourceKey) {
    const action = signature && signature.actions && signature.actions[actionKey];
    if (!this._guardActionCall(action, `NILM ${actionKey}`, feedbackScope)) {
      return;
    }
    const reject = (message) => this._setInlineFeedback(feedbackScope, "error", message);
    const data = Object.assign({}, action.data || {});
    if (actionKey === "label" || actionKey === "assign") {
      const labelInput = this.shadowRoot.querySelector(`#nilm_label_${sourceKey}`);
      const existingAssignment = actionKey === "assign" ? this._nilmExistingAssignmentSelection(sourceKey) : null;
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
      const targetList = this.shadowRoot.querySelector(`#nilm_merge_targets_${sourceKey}`);
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
    const sourceSession = this._nilmDecisionSession(sourceKey);
    const previousKey = sourceSession
      ? `session:${sourceSession.session_id || sourceKey}`
      : `signature:${signature.signature_id || this._nilmSignatureFingerprint(signature)}`;
    const previousIndex = Math.max(
      0,
      previousItems.findIndex((item) => this._nilmReviewKey(item) === previousKey),
    );
    const busyKey = `nilm_${sourceKey}_${actionKey}`;
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
      if (await this._loadNilmIntervalOnGraph(interval, { edit: false, assignment })) {
        this._lastActionMessage = this._panelText("messages.loaded_interval_adjustment");
        this._render();
      }
      return;
    }
    const requests = [];
    if (actionKey === "save") {
      action = workspace && workspace.actions && workspace.actions.label_interval;
      const draft = this._nilmLabelIntervalDraft || {};
      const label = String(draft.label || "").trim();
      const applianceProfile = String(draft.appliance_profile || "").trim();
      const draftIntervals = this._nilmIntervalDraftItems();
      const removedIntervalIds = this._nilmRemovedIntervalIds || [];
      const editingExisting = draftIntervals.length > 0 && draftIntervals.every(
        (interval) => String(interval.interval_id || "").trim(),
      );
      if (!label || (!applianceProfile && !editingExisting && !removedIntervalIds.length)
          || (!draftIntervals.length && !removedIntervalIds.length)) {
        this._setNilmIntervalError(this._panelText("errors.nilm_interval_fields_required"));
        return;
      }
      const savedIntervals = [];
      for (const interval of draftIntervals) {
        const start = this._datetimeLocalToIso(interval.start, interval.start_millis);
        const end = this._datetimeLocalToIso(interval.end, interval.end_millis);
        if (!start || !end || Date.parse(end) <= Date.parse(start)) {
          this._setNilmIntervalError(this._panelText("errors.nilm_interval_fields_required"));
          return;
        }
        const saved = { start, end };
        const intervalId = String(interval.interval_id || "").trim();
        if (intervalId) saved.interval_id = intervalId;
        savedIntervals.push(saved);
      }
      const hasNewIntervals = savedIntervals.some(
        (interval) => !String(interval.interval_id || "").trim(),
      );
      const creatingAssignment = !String(draft.assignment_id || "").trim();

      data = {
        ...action && action.data || {},
        label,
        intervals: savedIntervals,
        removed_interval_ids: removedIntervalIds,
        appliance_id: String(draft.appliance_id || label).trim(),
      };

      // Prevent action.data from supplying a profile while an existing
      // assignment or saved interval is being edited.
      delete data.appliance_profile;

      if (draft.assignment_id) {
        data.assignment_id = draft.assignment_id;
      }

      if (action.service === "save_nilm_interval_changes") {
        // The combined service receives appliance_profile only when this
        // request creates a new assignment with at least one new interval.
        if (applianceProfile && hasNewIntervals && creatingAssignment) {
          data.appliance_profile = applianceProfile;
        }

        requests.push(data);
      } else {
        // Legacy services receive one request per interval. Include the
        // profile only on requests that create a new interval/assignment.
        savedIntervals.forEach((interval) => {
          const requestData = { ...data, ...interval };

          if (
            applianceProfile
            && !String(interval.interval_id || "").trim()
            && creatingAssignment
          ) {
            requestData.appliance_profile = applianceProfile;
          }

          requests.push(requestData);
        });
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
      if (actionKey === "delete") {
        const deletedId = String(intervals && intervals[index] && intervals[index].interval_id || "");
        const draftIntervals = this._nilmIntervalDraftItems();
        if (deletedId && draftIntervals.some((item) => item.interval_id === deletedId)) {
          this._nilmLabelIntervalDraft = this._emptyNilmLabelIntervalDraft();
          this._nilmActiveIntervalIndex = 0;
          this._nilmIntervalEditorOpen = false;
          this._nilmIntervalGraphSnapshot = null;
        }
      }
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
        this._nilmIntervalDraftSnapshot = null;
        this._nilmRemovedIntervalIds = [];
        this._nilmActiveIntervalIndex = 0;
        this._nilmIntervalEditorOpen = false;
        this._nilmIntervalGraphSnapshot = null;
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

  async _callNilmWorkspaceItemAction(collectionKey, index, actionKey, { confirmed = false } = {}) {
    if (collectionKey === "assignments" && actionKey === "save") {
      await this._saveNilmAssignmentChanges(index);
      return;
    }
    const workspace = this._nilmWorkspace;
    const items = workspace && workspace[collectionKey];
    const item = items && items[index];
    if (collectionKey === "assignments" && actionKey.startsWith("helper_")) {
      await this._handleNilmHelperAction(item, index, actionKey);
      return;
    }
    const action = item && item.actions && item.actions[actionKey];
    if (!this._guardActionCall(action, `NILM ${actionKey}`)) {
      return;
    }
    if (collectionKey === "assignments" && actionKey === "delete_permanently" && !confirmed) {
      this._requestNilmWorkspaceActionConfirmation(collectionKey, index, actionKey);
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
    if (routeUrl.searchParams.has("alert_id")) {
      return false;
    }
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
    if (actionKey === "confirm_primary") {
      return this._panelTextFormat("messages.confirmed_assignment", { name });
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
    this._beginNilmGraphIntent();
    this._nilmFocusedSignature = "";
    this._nilmFocusedOccurrenceIndex = -1;
    return this._nilmSelectedReviewKey;
  }

  _invalidateNilmFocusedHistoryRequests() {
    this._nilmFocusedHistoryToken += 1;
  }

  _beginNilmGraphIntent() {
    this._nilmGraphIntentToken = (this._nilmGraphIntentToken || 0) + 1;
    this._invalidateNilmFocusedHistoryRequests();
    this._nilmWorkspaceHistoryLoading = false;
    return this._nilmGraphIntentToken;
  }

  _isCurrentNilmGraphIntent(token) {
    return token === this._nilmGraphIntentToken;
  }

  _invalidateNilmHelperHistoryRequests() {
    this._nilmHelperHistoryToken = (this._nilmHelperHistoryToken || 0) + 1;
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
      ["nilmBoundaryHandle", "[data-nilm-boundary-handle]", "nilmBoundaryHandle"],
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
    return this._renderNilmWorkspace();
  }

  _nilmReviewSignatures() {
    const workspace = this._nilmWorkspace;
    if (workspace && workspace.status === "ok" && Array.isArray(workspace.signatures)) {
      return workspace.signatures;
    }
    const nilm = this._payload && this._payload.nilm;
    return (nilm && nilm.signatures) || [];
  }

  _renderNilmSignatureReview(signature, sourceKey, signatureIndex = null) {
    const restore = signature.actions && signature.actions.restore;
    return `
      ${signature.user_label ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.saved_label", { label: signature.user_label }))}</p>` : ""}
      ${signature.review_state ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.review_state", { state: this._friendlyFeature(signature.review_state) }))}</p>` : ""}
      ${signature.merged_into ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.merged_into", { value: signature.merged_into }))}</p>` : ""}
      ${this._renderNilmDecisionFlow(signature, sourceKey)}
      ${restore && signatureIndex !== null ? `<div class="actions"><button type="button" class="secondary" data-nilm-signature-index="${signatureIndex}" data-nilm-signature-action="restore">${this._escape(this._panelText("actions.labels.restore"))}</button></div>` : ""}
    `;
  }

  _nilmDecisionDraftKey(signature) {
    return this._nilmSignatureFingerprint(signature) || String(signature && signature.signature_id || "");
  }

  _nilmDecisionDraft(signature) {
    return this._nilmDecisionDrafts.get(this._nilmDecisionDraftKey(signature)) || { decision: "", identifyMode: "assign" };
  }

  _renderNilmDecisionFlow(signature, sourceKey) {
    const actions = signature && signature.actions ? signature.actions : {};
    const candidates = [
      ["identify", "mdi:tag-outline", "nilm_workspace.decision_identify", Boolean(actions.assign || actions.label)],
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
      ${identifyMode === "assign" ? this._renderNilmExistingAssignmentField(actions.assign, sourceKey, draft.assignmentId, key) : ""}
      ${this._renderNilmLabelField(signature, sourceKey)}
    ` : "";
    return `<div class="nilm-decision-flow">
      <fieldset class="decision-group nilm-decision-group">
        <legend>${this._escape(this._panelText("nilm_workspace.choose_decision"))}</legend>
        <div class="nilm-decision-options">
          ${candidates.map(([value, icon, textKey]) => `<label class="nilm-decision-option">
            <input type="radio" name="nilm_decision_${sourceKey}" value="${value}" data-nilm-decision data-nilm-decision-key="${this._escape(key)}" ${draft.decision === value ? "checked" : ""}>
            <ha-icon icon="${icon}"></ha-icon>
            <span>${this._escape(this._panelText(textKey))}</span>
          </label>`).join("")}
        </div>
      </fieldset>
      ${identifyFields}
      ${draft.decision === "merge" ? this._renderNilmMergeTarget(signature, sourceKey) : ""}
      <div class="actions">
        <button type="button" data-nilm-apply-decision="${this._escape(sourceKey)}" ${this._busyAction.startsWith(`nilm_${sourceKey}_`) ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.apply"))}</button>
      </div>
      ${this._renderInlineFeedback(sourceKey)}
    </div>`;
  }

  _renderNilmLabelField(signature, sourceKey) {
    const draftKey = this._nilmLabelDraftKey(signature);
    const currentLabel = this._nilmLabelDrafts.has(draftKey)
      ? this._nilmLabelDrafts.get(draftKey)
      : signature.user_label
      || signature.display_name
      || signature.likely_type
      || signature.display_label
      || "";
    return `
      <label class="nilm-label-field" for="nilm_label_${sourceKey}">
        <span class="muted">${this._escape(this._panelText("nilm_workspace.label_this_load"))}</span>
        <input
          id="nilm_label_${sourceKey}"
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
    const fingerprints = signature && (signature.signature_fingerprints || signature.signature_ids);
    const direct = signature
      && (signature.feedback_fingerprint || signature.signature_fingerprint || signature.signature_id);
    if (direct) return String(direct).trim();
    if (!Array.isArray(fingerprints)) return "";
    return String(
      fingerprints.find((fingerprint) => this._nilmSignatureSessions(fingerprint).length)
      || fingerprints[0]
      || ""
    ).trim();
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
      ? [{
        start: draft.start || "",
        end: draft.end || "",
        interval_id: draft.interval_id || "",
        start_millis: draft.start_millis ?? null,
        end_millis: draft.end_millis ?? null,
      }]
      : [];
  }

  _rememberNilmLabelIntervalDraft(input) {
    if (!input) {
      return;
    }
    if (input.dataset.nilmExistingAssignment === "label_interval") {
      const selected = this._nilmExistingAssignmentSelection("label_interval");
      const assignment = selected && ((this._nilmWorkspace && this._nilmWorkspace.assignments) || [])
        .find((item) => item.assignment_id === selected.assignment_id);
      this._nilmLabelIntervalDraft = {
        ...this._nilmLabelIntervalDraft,
        assignment_id: selected ? selected.assignment_id : "",
        label: selected ? selected.label : this._nilmLabelIntervalDraft.label,
        appliance_id: assignment ? assignment.appliance_id || "" : "",
        appliance_profile: assignment ? assignment.appliance_profile || "" : "",
      };
      this._render();
      return;
    }
    if (!input.dataset.nilmLabelIntervalInput) {
      return;
    }
    const field = input.dataset.nilmLabelIntervalInput;
    const index = Number.parseInt(input.dataset.nilmIntervalIndex || "-1", 10);
    if (index >= 0 && ["start", "end"].includes(field)) {
      if (field === "start" || field === "end") this._beginNilmGraphIntent();
      const intervals = this._nilmIntervalDraftItems().map((item) => ({ ...item }));
      const nextInterval = { ...(intervals[index] || {}), [field]: input.value };
      if (field === "start" || field === "end") nextInterval[`${field}_millis`] = null;
      intervals[index] = nextInterval;
      this._nilmLabelIntervalDraft = { ...this._nilmLabelIntervalDraft, intervals };
      this._nilmActiveIntervalIndex = index;
      this._render();
      this._scheduleNilmIntervalEvidence();
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
      this._beginNilmGraphIntent();
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
        start_millis: start,
        end_millis: end,
      };
      this._openNilmIntervalEditor(() => {
        this._nilmLabelIntervalDraft = { ...this._nilmLabelIntervalDraft, intervals };
        this._nilmActiveIntervalIndex = index;
      });
      this._render();
      this._scheduleNilmIntervalEvidence();
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
    this._beginNilmGraphIntent();
    const removed = this._nilmIntervalDraftItems()[index];
    const removedId = String(removed && removed.interval_id || "").trim();
    if (removedId) {
      this._nilmRemovedIntervalIds = [...new Set([
        ...(this._nilmRemovedIntervalIds || []),
        removedId,
      ])];
    }
    const intervals = this._nilmIntervalDraftItems().filter((_item, itemIndex) => itemIndex !== index);
    this._nilmLabelIntervalDraft = {
      ...this._nilmLabelIntervalDraft,
      intervals: intervals.length ? intervals : removedId ? [] : [{ start: "", end: "", interval_id: "" }],
    };
    this._nilmActiveIntervalIndex = Math.max(0, Math.min(index, this._nilmLabelIntervalDraft.intervals.length - 1));
    this._render();
  }

  _cancelNilmIntervalEditor() {
    this._beginNilmGraphIntent();
    if (!this._restoreNilmIntervalGraphSnapshot()) {
      this._nilmFocusedInterval = null;
    }
    this._nilmIntervalEditorOpen = false;
    this._nilmLabelIntervalDraft = this._nilmIntervalDraftSnapshot
      || this._emptyNilmLabelIntervalDraft();
    this._nilmIntervalDraftSnapshot = null;
    this._nilmRemovedIntervalIds = [];
    this._nilmActiveIntervalIndex = 0;
    this._clearNilmIntervalFeedback();
    this._render();
  }

  _openNilmIntervalEditor(updateDraft = null) {
    if (!this._nilmIntervalEditorOpen) {
      this._snapshotNilmIntervalGraph();
      this._nilmIntervalDraftSnapshot = {
        ...this._nilmLabelIntervalDraft,
        intervals: this._nilmIntervalDraftItems().map((interval) => ({ ...interval })),
      };
      this._nilmRemovedIntervalIds = [];
    }
    if (typeof updateDraft === "function") updateDraft();
    this._nilmIntervalEditorOpen = true;
  }

  _snapshotNilmIntervalGraph() {
    const history = this._nilmWorkspace && this._nilmWorkspace.history;
    this._nilmIntervalGraphSnapshot = {
      graphWindow: this._nilmGraphWindow ? { ...this._nilmGraphWindow } : null,
      focusedSignature: this._nilmFocusedSignature,
      focusedOccurrenceIndex: this._nilmFocusedOccurrenceIndex,
      focusedInterval: this._nilmFocusedInterval ? { ...this._nilmFocusedInterval } : null,
      history: history ? { ...history } : null,
      series: (this._nilmWorkspaceHistorySeries || []).map((series) => (
        Array.isArray(series) ? series.map((point) => ({ ...point })) : series
      )),
      historyError: this._nilmWorkspaceHistoryError,
      failedRequest: this._nilmWorkspaceHistoryFailedRequest ? {
        ...this._nilmWorkspaceHistoryFailedRequest,
        window: this._nilmWorkspaceHistoryFailedRequest.window
          ? { ...this._nilmWorkspaceHistoryFailedRequest.window }
          : null,
      } : null,
    };
  }

  _restoreNilmIntervalGraphSnapshot() {
    const snapshot = this._nilmIntervalGraphSnapshot;
    this._nilmIntervalGraphSnapshot = null;
    if (!snapshot) return false;
    this._nilmGraphWindow = snapshot.graphWindow ? { ...snapshot.graphWindow } : null;
    this._nilmFocusedSignature = snapshot.focusedSignature;
    this._nilmFocusedOccurrenceIndex = snapshot.focusedOccurrenceIndex;
    this._nilmFocusedInterval = snapshot.focusedInterval ? { ...snapshot.focusedInterval } : null;
    if (this._nilmWorkspace && snapshot.history) {
      this._nilmWorkspace.history = { ...snapshot.history };
    }
    this._nilmWorkspaceHistorySeries = snapshot.series;
    this._nilmWorkspaceHistoryError = snapshot.historyError;
    this._nilmWorkspaceHistoryFailedRequest = snapshot.failedRequest;
    return true;
  }

  _selectNilmDraftInterval(index) {
    if (!Number.isInteger(index) || index < 0 || index >= this._nilmIntervalDraftItems().length) {
      return;
    }
    this._beginNilmGraphIntent();
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
    return this._loadNilmSessionInterval({
      start: band && band.dataset.nilmSessionStart,
      end: band && band.dataset.nilmSessionEnd,
    });
  }

  _selectNilmSessionIntervalByIndex(index) {
    const sessions = Array.isArray(this._nilmWorkspace && this._nilmWorkspace.sessions)
      ? this._nilmWorkspace.sessions
      : [];
    return this._loadNilmSessionInterval(sessions[index]);
  }

  async _loadNilmSessionInterval(session) {
    const start = Date.parse(session && session.start || "");
    const end = Date.parse(session && session.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
    const assignment = ((this._nilmWorkspace && this._nilmWorkspace.assignments) || [])
      .find((item) => item.assignment_id === session.assignment_id);
    const loaded = await this._loadNilmIntervalOnGraph(session, {
      edit: true,
      assignment,
      clearSignature: true,
    });
    if (loaded !== true) return false;
    this._lastActionMessage = this._panelText("messages.loaded_nilm_session_interval");
    this._render();
    return true;
  }

  _setNilmIntervalDraft(interval, assignment = null) {
    const start = Date.parse(interval && interval.start || "");
    const end = Date.parse(interval && interval.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      return false;
    }
    this._openNilmIntervalEditor(() => {
      this._nilmLabelIntervalDraft = {
        ...this._nilmLabelIntervalDraft,
        label: interval.display_label || interval.label || assignment && assignment.display_name || this._nilmLabelIntervalDraft.label || "",
        appliance_id: interval.appliance_id || assignment && assignment.appliance_id || this._nilmLabelIntervalDraft.appliance_id || "",
        appliance_profile: assignment && assignment.appliance_profile || this._nilmLabelIntervalDraft.appliance_profile || "",
        assignment_id: interval.assignment_id || assignment && assignment.assignment_id || "",
        intervals: [{
          start: this._datetimeLocalFromMillis(start),
          end: this._datetimeLocalFromMillis(end),
          interval_id: interval.interval_id || "",
          start_millis: start,
          end_millis: end,
        }],
      };
      this._nilmActiveIntervalIndex = 0;
    });
    this._scheduleNilmIntervalEvidence();
    return true;
  }

  _nilmFocusedLabelInterval() {
    const focused = this._nilmFocusedInterval;
    if (!focused) return null;
    return (this._nilmWorkspace?.label_intervals || []).find((interval) => (
      Date.parse(interval.start || "") === focused.start
      && Date.parse(interval.end || "") === focused.end
    )) || null;
  }

  _editNilmFocusedInterval() {
    const interval = this._nilmFocusedLabelInterval();
    if (!interval) return false;
    const assignment = (this._nilmWorkspace?.assignments || []).find(
      (item) => item.assignment_id === interval.assignment_id,
    );
    if (!this._setNilmIntervalDraft(interval, assignment)) return false;
    this._render();
    return true;
  }

  async _loadNilmIntervalOnGraph(interval, options = {}) {
    const start = Date.parse(interval && interval.start || "");
    const end = Date.parse(interval && interval.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
    const intentToken = this._beginNilmGraphIntent();
    const padding = Math.max(5 * 60 * 1000, (end - start) * 0.2);
    const targetWindow = { start: start - padding, end: end + padding };
    if (options.edit) this._setNilmIntervalDraft(interval, options.assignment);
    const history = this._nilmWorkspace && this._nilmWorkspace.history;
    if (!history || !history.api_path) {
      if (options.edit) this._render();
      return false;
    }
    const loaded = await this._loadNilmWorkspaceHistoryForWindow(targetWindow);
    if (loaded !== true || !this._isCurrentNilmGraphIntent(intentToken)) return false;
    if (options.clearSignature) {
      this._nilmFocusedSignature = "";
      this._nilmFocusedOccurrenceIndex = -1;
      this._nilmFocusedInterval = null;
    }
    this._nilmGraphWindow = targetWindow;
    this._nilmFocusedInterval = { start, end };
    this._render();
    if (options.scroll !== false) {
      requestAnimationFrame(() => {
        if (!this._isCurrentNilmGraphIntent(intentToken)) return;
        const chart = this.shadowRoot.querySelector("[data-nilm-chart-select]");
        if (chart) chart.scrollIntoView({ block: "nearest" });
      });
    }
    return true;
  }

  async _syncNilmIntervalFieldToGraph(index) {
    this._beginNilmGraphIntent();
    const interval = this._nilmIntervalDraftItems()[index];
    const start = this._datetimeLocalToMillis(
      interval && interval.start,
      interval && interval.start_millis,
    );
    const end = this._datetimeLocalToMillis(
      interval && interval.end,
      interval && interval.end_millis,
    );
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      this._render();
      return;
    }
    const history = this._nilmWorkspace && this._nilmWorkspace.history;
    const loadedStart = Date.parse(history && history.start || "");
    const loadedEnd = Date.parse(history && history.end || "");
    const historyContainsInterval = Number.isFinite(loadedStart)
      && Number.isFinite(loadedEnd)
      && start >= loadedStart
      && end <= loadedEnd;
    if (!historyContainsInterval) {
      await this._loadNilmIntervalOnGraph({
        ...(interval || {}),
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
      }, { edit: false, scroll: false });
    } else {
      this._nilmFocusedInterval = { start, end };
      this._render();
    }
  }

  _updateNilmDraftBoundary(index, field, millis) {
    const intervals = this._nilmIntervalDraftItems().map((item) => ({ ...item }));
    const interval = intervals[index];
    const otherField = field === "start" ? "end" : "start";
    const other = this._datetimeLocalToMillis(
      interval && interval[otherField],
      interval && interval[`${otherField}_millis`],
    );
    if (!Number.isFinite(millis) || !Number.isFinite(other)) return false;
    if ((field === "start" && millis >= other) || (field === "end" && millis <= other)) return false;
    this._beginNilmGraphIntent();
    interval[field] = this._datetimeLocalFromMillis(millis);
    interval[`${field}_millis`] = millis;
    this._nilmLabelIntervalDraft = { ...this._nilmLabelIntervalDraft, intervals };
    this._nilmActiveIntervalIndex = index;
    this._nilmFocusedInterval = field === "start"
      ? { start: millis, end: other }
      : { start: other, end: millis };
    this._render();
    this._scheduleNilmIntervalEvidence();
    return true;
  }

  _selectNilmEdgeTime(marker) {
    const time = Date.parse(marker && marker.dataset.nilmEdgeTime || "");
    if (!Number.isFinite(time)) {
      return;
    }
    const field = String(marker.dataset.nilmEdgeDirection || "").toLowerCase() === "off"
      ? "end"
      : "start";
    this._beginNilmGraphIntent();
    const intervals = this._nilmIntervalDraftItems().map((item) => ({ ...item }));
    const index = Math.max(0, Math.min(this._nilmActiveIntervalIndex, intervals.length - 1));
    intervals[index] = {
      ...(intervals[index] || { start: "", end: "", interval_id: "" }),
      [field]: this._datetimeLocalFromMillis(time),
      [`${field}_millis`]: time,
    };
    this._openNilmIntervalEditor(() => {
      this._nilmLabelIntervalDraft = { ...this._nilmLabelIntervalDraft, intervals };
    });
    this._lastActionMessage = this._panelText("messages.loaded_nilm_edge_time");
    this._render();
    this._scheduleNilmIntervalEvidence();
  }

  async _focusNilmSignatureOnGraph(signatureFingerprint, options = {}) {
    const intentToken = this._beginNilmGraphIntent();
    const shouldScroll = options.scroll !== false;
    const canToggle = options.toggle !== false;
    if (canToggle && this._nilmFocusedSignature === signatureFingerprint) {
      this._nilmFocusedSignature = "";
      this._nilmFocusedOccurrenceIndex = -1;
      this._nilmFocusedInterval = null;
      this._nilmGraphWindow = null;
      this._lastActionMessage = this._panelText("messages.showing_all_nilm_sessions");
      if (shouldScroll) {
        this._renderAndScrollToTop();
      } else {
        this._render();
      }
      return true;
    }
    const occurrenceIndex = Math.max(
      0,
      this._nilmSignatureSessions(signatureFingerprint).length - 1,
    );
    const targetWindow = this._nilmSignatureGraphWindow(signatureFingerprint, occurrenceIndex);
    if (targetWindow) {
      const historyLoaded = await this._loadNilmWorkspaceHistoryForWindow(targetWindow);
      const isCurrent = this._isCurrentNilmGraphIntent(intentToken);
      if (historyLoaded !== true || !isCurrent) {
        return false;
      }
    }
    this._nilmFocusedSignature = signatureFingerprint;
    this._nilmFocusedInterval = null;
    this._nilmFocusedOccurrenceIndex = occurrenceIndex;
    const focused = this._focusNilmGraphWindowForSignature(signatureFingerprint, intentToken);
    this._lastActionMessage = focused
      ? this._panelText("messages.showing_selected_signature")
      : this._panelText("messages.no_paired_sessions");
    if (shouldScroll) {
      this._renderAndScrollToTop();
    } else {
      this._render();
    }
    return focused;
  }

  _focusNilmGraphWindowForSignature(signatureFingerprint, intentToken = null) {
    const targetWindow = this._nilmSignatureGraphWindow(signatureFingerprint);
    if (!targetWindow) {
      return false;
    }
    const bounds = this._nilmWorkspaceGraphWindow(this._nilmWorkspace) || {
      min: targetWindow.start,
      max: targetWindow.end,
    };
    return this._setNilmGraphWindow(targetWindow.start, targetWindow.end, bounds, intentToken);
  }

  _nilmSignatureGraphWindow(signatureFingerprint, occurrenceIndex = null) {
    const sessions = this._nilmSignatureSessions(signatureFingerprint);
    const index = Number.isInteger(occurrenceIndex)
      ? Math.max(0, Math.min(occurrenceIndex, sessions.length - 1))
      : signatureFingerprint === this._nilmFocusedSignature
        ? Math.max(0, Math.min(this._nilmFocusedOccurrenceIndex, sessions.length - 1))
        : sessions.length - 1;
    const occurrence = sessions[index];
    const start = Date.parse(occurrence && occurrence.start || "");
    const end = Date.parse(occurrence && occurrence.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end)) {
      return null;
    }
    const padding = Math.max((end - start) * 0.25, 5 * 60 * 1000);
    return { start: start - padding, end: end + padding };
  }

  _nilmSignatureSessions(signatureFingerprint) {
    return (((this._nilmWorkspace && this._nilmWorkspace.sessions) || []))
      .filter((session) => session.signature_fingerprint === signatureFingerprint
        && session.end && !session.ambiguous)
      .sort((left, right) => Date.parse(left.start || "") - Date.parse(right.start || ""));
  }

  _nilmFocusedOccurrence() {
    const sessions = this._nilmSignatureSessions(this._nilmFocusedSignature);
    if (!sessions.length) return null;
    const index = Math.max(0, Math.min(this._nilmFocusedOccurrenceIndex, sessions.length - 1));
    return sessions[index];
  }

  _nilmFocusedGraphEvidence(workspace) {
    const occurrence = this._nilmFocusedOccurrence();
    if (!this._nilmFocusedSignature || !occurrence) {
      return { sessions: [], edges: [] };
    }
    return {
      sessions: [{ ...occurrence, selected: true }],
      edges: [
        {
          timestamp: occurrence.start,
          direction: "on",
          delta_w: occurrence.on_delta_w,
          delta_var: occurrence.on_delta_var,
        },
        {
          timestamp: occurrence.end,
          direction: "off",
          delta_w: occurrence.off_delta_w,
          delta_var: occurrence.off_delta_var,
        },
      ],
    };
  }

  async _stepNilmOccurrence(step) {
    const sessions = this._nilmSignatureSessions(this._nilmFocusedSignature);
    if (!sessions.length) return;
    const current = Math.max(0, Math.min(this._nilmFocusedOccurrenceIndex, sessions.length - 1));
    const next = Math.max(0, Math.min(current + Number(step || 0), sessions.length - 1));
    if (next === current) return;
    const intentToken = this._beginNilmGraphIntent();
    const targetWindow = this._nilmSignatureGraphWindow(this._nilmFocusedSignature, next);
    if (targetWindow) {
      const historyLoaded = await this._loadNilmWorkspaceHistoryForWindow(targetWindow);
      const isCurrent = this._isCurrentNilmGraphIntent(intentToken);
      if (historyLoaded !== true || !isCurrent) {
        return;
      }
      this._nilmFocusedOccurrenceIndex = next;
      this._focusNilmGraphWindowForSignature(this._nilmFocusedSignature, intentToken);
    } else {
      this._nilmFocusedOccurrenceIndex = next;
    }
    this._render();
  }

  _renderNilmOccurrenceControls() {
    const sessions = this._nilmSignatureSessions(this._nilmFocusedSignature);
    const occurrence = this._nilmFocusedOccurrence();
    if (!occurrence) return "";
    const index = sessions.indexOf(occurrence);
    return `<div class="actions nilm-occurrence-controls" data-nilm-occurrence-controls>
      <button type="button" class="secondary" data-nilm-occurrence-step="-1" ${index <= 0 ? "disabled" : ""}>${this._escape(this._panelText("nilm_workspace.previous_occurrence"))}</button>
      <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.occurrence_summary", {
        start: this._formatDateTime(occurrence.start),
        end: this._formatDateTime(occurrence.end),
        duration: this._nilmSessionDuration(occurrence),
      }))}</p>
      <button type="button" class="secondary" data-nilm-occurrence-step="1" ${index >= sessions.length - 1 ? "disabled" : ""}>${this._escape(this._panelText("nilm_workspace.next_occurrence"))}</button>
    </div>`;
  }

  async _loadNilmWorkspaceHistoryForWindow(window, failedRequest = null) {
    this._invalidateNilmHelperHistoryRequests();
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
    const end = Number.isFinite(window.end)
      ? window.end
      : Number.isFinite(historyEnd) ? historyEnd : Date.now();
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
        start,
        end,
      ),
      fetchPath: this._nilmWorkspaceHistoryPathWithHours(
        history.fetch_path || `/api/${history.api_path}`,
        hours,
        start,
        end,
      ),
    };
  }

  _nilmWorkspaceHistoryPathWithHours(path, hours, start = null, end = null) {
    const url = new URL(
      path.startsWith("/") ? path : `/${path}`,
      window.location.origin,
    );
    url.searchParams.set("hours", String(hours));
    if (Number.isFinite(start)) url.searchParams.set("start", new Date(start).toISOString());
    if (Number.isFinite(end)) url.searchParams.set("end", new Date(end).toISOString());
    const nextPath = `${url.pathname}${url.search}`;
    return this._nilmHistoryPathWithHelpers(
      path.startsWith("/") ? nextPath : nextPath.replace(/^\//, ""),
    );
  }

  _nilmSyncHelperSelection(workspace) {
    this._nilmSelectedHelpers ||= {};
    const selected = this._nilmSelectedReviewItem(workspace);
    if (!selected || selected.kind !== "assignment") return;
    const id = selected.item.assignment_id;
    if (!(id in this._nilmSelectedHelpers)) {
      this._nilmSelectedHelpers[id] = (selected.item.helper_links || [])
        .map((link) => link.helper_circuit_id).slice(0, 4);
    }
  }

  _nilmHistoryPathWithHelpers(path) {
    if (!path) return path;
    this._nilmSyncHelperSelection(this._nilmWorkspace);
    const selected = this._nilmSelectedReviewItem(this._nilmWorkspace);
    const ids = selected && selected.kind === "assignment"
      ? (this._nilmSelectedHelpers && this._nilmSelectedHelpers[selected.item.assignment_id]) || []
      : [];
    const url = new URL(path.startsWith("/") ? path : `/${path}`, window.location.origin);
    url.searchParams.delete("helper_circuit_id");
    ids.slice(0, 4).forEach((id) => url.searchParams.append("helper_circuit_id", id));
    const result = `${url.pathname}${url.search}`;
    return path.startsWith("/") ? result : result.replace(/^\//, "");
  }

  async _handleNilmHelperAction(assignment, index, actionKey) {
    const manual = actionKey === "helper_manual";
    const [parsedKind, offset] = manual ? ["set", "-1"] : actionKey.slice(7).split("_");
    const kind = parsedKind;
    const items = (kind === "remove" || kind === "togglelink") ? assignment.helper_links : assignment.helper_candidates;
    const manualSelect = manual && this.shadowRoot.querySelector(`#nilm_helper_option_${index}`);
    const evidence = manual
      ? (assignment.helper_options || []).find((item) => item.helper_circuit_id === (manualSelect && manualSelect.value))
      : items && items[Number(offset)];
    if (!evidence) return;
    if (kind === "toggle" || kind === "togglelink") {
      this._nilmSelectedHelpers ||= {};
      const selected = new Set(this._nilmSelectedHelpers[assignment.assignment_id] || []);
      selected.has(evidence.helper_circuit_id) ? selected.delete(evidence.helper_circuit_id) : selected.add(evidence.helper_circuit_id);
      this._nilmSelectedHelpers[assignment.assignment_id] = [...selected].slice(0, 4);
      await this._loadNilmWorkspaceHistory();
      return;
    }
    const action = kind === "remove"
      ? evidence.actions && evidence.actions.remove
      : evidence.actions && evidence.actions.set;
    if (!this._guardActionCall(action, `NILM helper ${kind}`)) return;
    const data = { ...(action.data || {}) };
    await this._hass.callService(action.domain, action.service, data);
    const selected = new Set(this._nilmSelectedHelpers[assignment.assignment_id] || []);
    kind === "remove"
      ? selected.delete(evidence.helper_circuit_id)
      : selected.add(evidence.helper_circuit_id);
    this._nilmSelectedHelpers[assignment.assignment_id] = [...selected].slice(0, 4);
    await this._refreshNilmWorkspaceData();
    await this._loadNilmWorkspaceHistory();
    this._render();
  }

  _renderNilmHelperEvidence(assignment, index) {
    this._nilmSyncHelperSelection(this._nilmWorkspace);
    const selectedIds = new Set((this._nilmSelectedHelpers && this._nilmSelectedHelpers[assignment.assignment_id]) || []);
    const confirmedIds = new Set((assignment.helper_links || []).map((item) => item.helper_circuit_id));
    const renderEvidence = (item, offset, confirmed) => {
      const selected = selectedIds.has(item.helper_circuit_id);
      const name = item.helper_name || item.helper_circuit_id;
      return `<div class="nilm-helper-evidence" style="display:grid;gap:8px;min-width:0" data-nilm-helper-circuit-id="${this._escape(item.helper_circuit_id)}">
        <button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="helper_${confirmed ? "togglelink" : "toggle"}_${offset}" aria-pressed="${selected}" aria-label="${this._escape(this._panelTextFormat("nilm_workspace.helper_toggle", { name }))}">${this._escape(name)}</button>
        <span>${this._escape(this._panelTextFormat("nilm_workspace.helper_matched_starts", { matched: item.matched_on_count, total: item.source_on_count, name }))}</span>
        <span>${this._escape(this._panelTextFormat("nilm_workspace.helper_start_delay", { seconds: this._formatMetricValue(item.start_lag_seconds) }))}</span>
        ${confirmed ? `<span>${this._escape(this._panelText(`nilm_workspace.helper_relationship_${item.relationship}`))}</span><button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="helper_remove_${offset}">${this._escape(this._panelText("nilm_workspace.helper_remove"))}</button>` : `<span class="muted">${this._escape(this._panelText("nilm_workspace.helper_relationship_corroborates"))}</span><button type="button" data-nilm-assignment-index="${index}" data-nilm-assignment-action="helper_set_${offset}">${this._escape(this._panelText("nilm_workspace.helper_confirm"))}</button>`}
      </div>`;
    };
    const candidates = (assignment.helper_candidates || [])
      .map((item, offset) => ({ item, offset }))
      .filter(({ item }) => !confirmedIds.has(item.helper_circuit_id)
        && Number(item.matched_on_count) > 0
        && Number(item.source_on_count) > 0);
    const helperOptions = Array.isArray(assignment.helper_options) ? assignment.helper_options : [];
    const manual = helperOptions.length ? `<div class="nilm-helper-manual">
      <h3>${this._escape(this._panelText("nilm_workspace.helper_manual"))}</h3>
      <label for="nilm_helper_option_${index}">${this._escape(this._panelText("nilm_workspace.helper_select"))}</label>
      <select id="nilm_helper_option_${index}" data-nilm-helper-option data-nilm-assignment-index="${index}">
        ${helperOptions.map((item) => `<option value="${this._escape(item.helper_circuit_id || "")}">${this._escape(item.helper_name || item.helper_circuit_id || "")}</option>`).join("")}
      </select>
      <span class="muted">${this._escape(this._panelText("nilm_workspace.helper_relationship_corroborates"))}</span>
      <button type="button" data-nilm-assignment-index="${index}" data-nilm-assignment-action="helper_manual">${this._escape(this._panelText("nilm_workspace.helper_set"))}</button>
    </div>` : "";
    return `<div class="nilm-helper-list" data-nilm-helper-list><h3>${this._escape(this._panelText("nilm_workspace.helper_evidence"))}</h3>${(assignment.helper_links || []).map((item, offset) => renderEvidence(item, offset, true)).join("")}${candidates.map(({ item, offset }) => renderEvidence(item, offset, false)).join("")}${manual}</div>`;
  }

  _nilmReferenceDraft(assignment) {
    const key = String((assignment && assignment.assignment_id) || "");
    const existing = this._nilmReferenceDrafts.get(key);
    if (existing) return existing;
    const reference = (assignment && assignment.reference) || {};
    const window = this._nilmGraphWindow || this._nilmWorkspaceGraphWindow(this._nilmWorkspace) || {};
    const draft = {
      stateEntityId: reference.state_entity_id || "",
      powerEntityId: reference.power_entity_id || "",
      thresholdW: String(reference.threshold_w ?? 0),
      onThreshold: reference.on_threshold == null ? "" : String(reference.on_threshold),
      offThreshold: reference.off_threshold == null ? "" : String(reference.off_threshold),
      onDwellSeconds: reference.on_dwell_seconds == null ? "" : String(reference.on_dwell_seconds),
      offDwellSeconds: reference.off_dwell_seconds == null ? "" : String(reference.off_dwell_seconds),
      minimumIntervalSeconds: reference.minimum_interval_seconds == null ? "" : String(reference.minimum_interval_seconds),
      mergeGapSeconds: reference.merge_gap_seconds == null ? "" : String(reference.merge_gap_seconds),
      maximumUncertainGapSeconds: reference.maximum_unknown_gap_seconds == null ? "" : String(reference.maximum_unknown_gap_seconds),
      maximumPowerGapSeconds: reference.maximum_power_gap_seconds == null ? "" : String(reference.maximum_power_gap_seconds),
      start: this._datetimeLocalFromMillis(window.start),
      end: this._datetimeLocalFromMillis(window.end),
      startMillis: Number.isFinite(window.start) ? window.start : null,
      endMillis: Number.isFinite(window.end) ? window.end : null,
      open: false,
      error: "",
    };
    this._nilmReferenceDrafts.set(key, draft);
    return draft;
  }

  _renderNilmReferenceImportSummary(reference) {
    const summary = reference && reference.import_summary;
    if (!summary) return "";
    const count = (key) => Number.isInteger(summary[key]) && summary[key] >= 0 ? summary[key] : 0;
    const candidate = count("candidate_interval_count");
    const imported = count("imported_interval_count");
    const discarded = count("discarded_minimum_duration_count");
    const bridged = count("bridged_unknown_gap_count");
    const merged = count("merged_inactive_gap_count");
    const lowCoverage = count("low_coverage_interval_count");
    const warnings = Array.isArray(summary.warnings) ? summary.warnings.slice(0, 16) : [];
    return `<section class="nilm-reference-import-summary" data-nilm-reference-import-summary>
      <p>${this._escape(this._panelTextFormat("nilm_workspace.reference_import_summary", { imported, candidate }))}</p>
      ${discarded ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.reference_import_discarded", { count: discarded }))}</p>` : ""}
      ${(bridged || merged) ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.reference_import_gaps", { bridged, merged }))}</p>` : ""}
      ${lowCoverage ? `<p class="warning" data-nilm-reference-low-coverage>${this._escape(this._panelTextFormat("nilm_workspace.reference_import_low_coverage", { count: lowCoverage }))}</p>` : ""}
      ${warnings.length ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.reference_import_warnings"))}</p><ul>${warnings.map((warning) => `<li>${this._escape(String(warning))}</li>`).join("")}</ul>` : ""}
    </section>`;
  }

  _renderNilmReferenceSensors(assignment, index) {
    const reference = assignment && assignment.reference;
    if (!reference) return "";
    const draft = this._nilmReferenceDraft(assignment);
    const busy = this._busyAction === `nilm_reference_${index}`;
    return `<details ${draft.open ? "open" : ""} data-nilm-reference-details data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}">
      <summary>${this._escape(this._panelText("nilm_workspace.reference_sensors"))}</summary>
      <p class="muted">${this._escape(this._panelText("nilm_workspace.reference_description"))}</p>
      <div class="grid">
        <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_state"))}</span>
          <ha-entity-picker role="group" aria-label="${this._escape(this._panelText("nilm_workspace.reference_state"))}" data-nilm-reference-input="stateEntityId" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}"></ha-entity-picker>
        </label>
        <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_power"))}</span>
          <ha-entity-picker role="group" aria-label="${this._escape(this._panelText("nilm_workspace.reference_power"))}" data-nilm-reference-input="powerEntityId" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}"></ha-entity-picker>
        </label>
        ${!draft.stateEntityId ? `<label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_on_threshold"))}</span><input type="number" min="0" step="0.1" data-nilm-reference-input="onThreshold" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.onThreshold)}" placeholder="${this._escape(this._panelText("nilm_workspace.reference_auto"))}"></label>
        <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_off_threshold"))}</span><input type="number" min="0" step="0.1" data-nilm-reference-input="offThreshold" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.offThreshold)}" placeholder="${this._escape(this._panelText("nilm_workspace.reference_auto"))}"></label>` : ""}
        <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_range_start"))}</span><input type="datetime-local" data-nilm-reference-input="start" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.start)}"></label>
        <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_range_end"))}</span><input type="datetime-local" data-nilm-reference-input="end" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.end)}"></label>
      </div>
      <details class="nilm-reference-advanced">
        <summary>${this._escape(this._panelText("nilm_workspace.reference_advanced_settings"))}</summary>
        <p class="muted">${this._escape(this._panelText("nilm_workspace.reference_unknown_explanation"))}</p>
        <div class="grid">
          <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_on_dwell"))}</span><input type="number" min="0" step="0.1" data-nilm-reference-input="onDwellSeconds" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.onDwellSeconds)}" placeholder="${this._escape(this._panelText("nilm_workspace.reference_auto"))}"></label>
          <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_off_dwell"))}</span><input type="number" min="0" step="0.1" data-nilm-reference-input="offDwellSeconds" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.offDwellSeconds)}" placeholder="${this._escape(this._panelText("nilm_workspace.reference_auto"))}"></label>
          <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_minimum_duration"))}</span><input type="number" min="0" step="0.1" data-nilm-reference-input="minimumIntervalSeconds" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.minimumIntervalSeconds)}" placeholder="${this._escape(this._panelText("nilm_workspace.reference_auto"))}"></label>
          <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_merge_gap"))}</span><input type="number" min="0" step="0.1" data-nilm-reference-input="mergeGapSeconds" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.mergeGapSeconds)}" placeholder="${this._escape(this._panelText("nilm_workspace.reference_auto"))}"></label>
          <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_maximum_unknown_gap"))}</span><input type="number" min="0" step="0.1" data-nilm-reference-input="maximumUncertainGapSeconds" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.maximumUncertainGapSeconds)}" placeholder="${this._escape(this._panelText("nilm_workspace.reference_auto"))}"></label>
          <label class="nilm-label-field"><span class="muted">${this._escape(this._panelText("nilm_workspace.reference_maximum_power_gap"))}</span><input type="number" min="0" step="0.1" data-nilm-reference-input="maximumPowerGapSeconds" data-nilm-reference-key="${this._escape(assignment.assignment_id || "")}" value="${this._escape(draft.maximumPowerGapSeconds)}" placeholder="${this._escape(this._panelText("nilm_workspace.reference_auto"))}"></label>
        </div>
      </details>
      <p class="muted" data-nilm-reference-resolved-settings>${this._escape(this._panelTextFormat("nilm_workspace.reference_resolved_settings", { on: reference.on_threshold ?? reference.threshold_w ?? this._panelText("nilm_workspace.reference_auto"), off: reference.off_threshold ?? reference.threshold_w ?? this._panelText("nilm_workspace.reference_auto") }))}</p>
      ${reference.available ? `<p class="muted">${this._escape(reference.measured_power_w == null
        ? this._panelTextFormat("nilm_workspace.reference_live_state", { state: reference.is_running ? this._panelText("nilm_workspace.reference_on") : this._panelText("nilm_workspace.reference_off") })
        : this._panelTextFormat("nilm_workspace.reference_live", { state: reference.is_running ? this._panelText("nilm_workspace.reference_on") : this._panelText("nilm_workspace.reference_off"), power: this._formatMetricValue(reference.measured_power_w) }))}</p>` : ""}
      ${this._renderNilmReferenceImportSummary(reference)}
      ${draft.error ? `<p class="error" role="alert">${this._escape(draft.error)}</p>` : ""}
      <div class="actions">
        <button type="button" data-nilm-reference-action="link_import" data-nilm-reference-index="${index}" ${busy ? "disabled" : ""}>${this._escape(this._panelText("nilm_workspace.reference_link_import"))}</button>
        ${(reference.state_entity_id || reference.power_entity_id) ? `<button type="button" class="secondary" data-nilm-reference-action="refresh" data-nilm-reference-index="${index}" ${busy ? "disabled" : ""}>${this._escape(this._panelText("nilm_workspace.reference_refresh"))}</button>` : ""}
        ${reference.actions && reference.actions.remove ? `<button type="button" class="secondary" data-nilm-reference-action="remove" data-nilm-reference-index="${index}" ${busy ? "disabled" : ""}>${this._escape(this._panelText("nilm_workspace.reference_remove"))}</button>` : ""}
      </div>
    </details>`;
  }

  _rememberNilmReferenceDraft(input) {
    const key = input.dataset.nilmReferenceKey;
    const draft = this._nilmReferenceDrafts.get(key) || {};
    const field = input.dataset.nilmReferenceInput;
    const nextDraft = { ...draft, [field]: input.value, open: true, error: "" };
    if (field === "start" || field === "end") nextDraft[`${field}Millis`] = null;
    this._nilmReferenceDrafts.set(key, nextDraft);
  }

  _configureNilmReferencePickers() {
    for (const picker of this.shadowRoot.querySelectorAll("ha-entity-picker[data-nilm-reference-input]")) {
      const assignment = this._nilmWorkspace.assignments.find(
        (item) => item.assignment_id === picker.dataset.nilmReferenceKey,
      );
      const reference = assignment && assignment.reference || {};
      const draft = assignment ? this._nilmReferenceDraft(assignment) : {};
      const isPower = picker.dataset.nilmReferenceInput === "powerEntityId";
      const options = isPower ? reference.power_options || [] : reference.state_options || [];
      picker.hass = this._hass;
      picker.includeEntities = options.map((item) => item.entity_id);
      picker.value = isPower ? draft.powerEntityId || "" : draft.stateEntityId || "";
      picker.allowCustomEntity = false;
    }
  }

  async _callNilmReferenceAction(index, actionKey) {
    const assignment = this._nilmWorkspace && this._nilmWorkspace.assignments && this._nilmWorkspace.assignments[index];
    const reference = assignment && assignment.reference;
    const actions = reference && reference.actions;
    if (!assignment || !actions) return;
    const draft = this._nilmReferenceDraft(assignment);
    draft.open = true;
    draft.error = "";
    const stateEntityId = String(actionKey === "refresh" ? reference.state_entity_id || "" : draft.stateEntityId || "").trim();
    const powerEntityId = String(actionKey === "refresh" ? reference.power_entity_id || "" : draft.powerEntityId || "").trim();
    const referenceField = {
      onThreshold: "on_threshold",
      offThreshold: "off_threshold",
      onDwellSeconds: "on_dwell_seconds",
      offDwellSeconds: "off_dwell_seconds",
      minimumIntervalSeconds: "minimum_interval_seconds",
      mergeGapSeconds: "merge_gap_seconds",
      maximumUncertainGapSeconds: "maximum_unknown_gap_seconds",
      maximumPowerGapSeconds: "maximum_power_gap_seconds",
    };
    const settingValue = (field) => {
      const value = String(actionKey === "refresh" ? reference[referenceField[field]] ?? "" : draft[field] ?? "").trim();
      if (!value) return null;
      const parsed = Number(value);
      return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
    };
    const numericReference = !stateEntityId && Boolean(powerEntityId);
    const onThreshold = numericReference ? settingValue("onThreshold") : null;
    const offThreshold = numericReference ? settingValue("offThreshold") : null;
    const advancedSettings = {
      reference_on_dwell_seconds: settingValue("onDwellSeconds"),
      reference_off_dwell_seconds: settingValue("offDwellSeconds"),
      reference_minimum_interval_seconds: settingValue("minimumIntervalSeconds"),
      reference_merge_gap_seconds: settingValue("mergeGapSeconds"),
      reference_maximum_unknown_gap_seconds: settingValue("maximumUncertainGapSeconds"),
      reference_maximum_power_gap_seconds: settingValue("maximumPowerGapSeconds"),
    };
    const invalidSetting = [onThreshold, offThreshold, ...Object.values(advancedSettings)].some((value) => value === undefined);
    if (actionKey !== "remove" && (invalidSetting || (onThreshold != null && offThreshold != null && offThreshold > onThreshold))) {
      draft.error = invalidSetting
        ? this._panelText("errors.nilm_reference_settings_invalid")
        : this._panelText("errors.nilm_reference_threshold_order");
      this._render();
      return;
    }
    const thresholdW = onThreshold ?? Number(actionKey === "refresh" ? reference.threshold_w || 0 : draft.thresholdW || 0);
    const start = this._datetimeLocalToIso(draft.start, draft.startMillis);
    const end = this._datetimeLocalToIso(draft.end, draft.endMillis);
    if (actionKey !== "remove" && (!stateEntityId && !powerEntityId)) {
      draft.error = this._panelText("errors.nilm_reference_required");
      this._render();
      return;
    }
    if (actionKey !== "remove" && (!start || !end || end <= start)) {
      draft.error = this._panelText("errors.nilm_reference_range_required");
      this._render();
      return;
    }
    const actionContext = this._nilmWorkspaceActionContext();
    this._busyAction = `nilm_reference_${index}`;
    this._render();
    let service = actionKey;
    try {
      if (actionKey === "remove") {
        const action = actions.remove;
        service = action.service;
        await this._hass.callService(action.domain, action.service, { ...(action.data || {}) });
      } else {
        const setAction = actions.set;
        service = setAction.service;
        await this._hass.callService(setAction.domain, setAction.service, {
          ...(setAction.data || {}),
          ...(stateEntityId ? { reference_state_entity_id: stateEntityId } : {}),
          ...(powerEntityId ? { reference_power_entity_id: powerEntityId } : {}),
          ...(numericReference && Number.isFinite(thresholdW) && thresholdW >= 0
            ? { reference_threshold_w: thresholdW }
            : {}),
          ...(onThreshold == null ? {} : { reference_on_threshold: onThreshold }),
          ...(offThreshold == null ? {} : { reference_off_threshold: offThreshold }),
          ...Object.fromEntries(Object.entries(advancedSettings).filter(([, value]) => value != null)),
        });
        const action = actions.import;
        service = action.service;
        await this._hass.callService(action.domain, action.service, {
          ...(action.data || {}),
          ground_truth_entity_id: stateEntityId || powerEntityId,
          ...(powerEntityId ? { reference_power_entity_id: powerEntityId } : {}),
          ...(numericReference && Number.isFinite(thresholdW) && thresholdW >= 0 ? { threshold_w: thresholdW } : {}),
          start,
          end,
        });
      }
      if (!actionContext.isRouteCurrent()) return;
      await this._refreshNilmWorkspaceData(actionContext.requestId, actionContext.routeKey);
      if (!actionContext.isCurrent()) return;
      draft.open = true;
      draft.error = "";
      if (actionKey === "remove") {
        draft.stateEntityId = "";
        draft.powerEntityId = "";
        draft.thresholdW = "0";
      }
    } catch (error) {
      if (!actionContext.isCurrent()) return;
      draft.open = true;
      draft.error = this._panelTextFormat("errors.run_service", { service, message: error.message });
    } finally {
      if (this._busyAction === `nilm_reference_${index}`) this._busyAction = "";
      if (actionContext.isCurrent()) this._render();
    }
  }

  async _callNilmConfiguredPrimaryAction() {
    const primary = this._nilmWorkspace && this._nilmWorkspace.configured_primary;
    const action = primary && primary.suggestion && primary.suggestion.action;
    if (!this._guardActionCall(action, "NILM configured primary", "nilm-primary")) return;
    const actionContext = this._nilmWorkspaceActionContext();
    this._busyAction = "nilm_primary";
    this._render();
    try {
      await this._hass.callService(action.domain || "circuitsetup_energy_analyzer", action.service, { ...(action.data || {}) });
      const refreshed = await this._refreshNilmWorkspaceData(actionContext.requestId, actionContext.routeKey);
      if (!actionContext.isCurrent()) return;
      if (this._busyAction === "nilm_primary") this._busyAction = "";
      this._setInlineFeedback("nilm-primary", refreshed ? "success" : "error", refreshed
        ? this._panelText("messages.nilm_primary_confirmed")
        : this._panelText("errors.load_nilm_workspace"));
      this._render();
    } catch (error) {
      if (!actionContext.isCurrent()) return;
      if (this._busyAction === "nilm_primary") this._busyAction = "";
      this._setInlineFeedback("nilm-primary", "error", this._panelTextFormat("errors.run_service", { service: action.service, message: error.message }));
      this._render();
    }
  }

  _zoomNilmGraph(factor) {
    this._beginNilmGraphIntent();
    const window = this._nilmWorkspaceGraphWindow(this._nilmWorkspace);
    this._lastActionMessage = this._panelText("messages.updated_nilm_graph_window");
    this._zoomGraphWindow(window, factor, (next) => { this._nilmGraphWindow = next; });
  }

  _panNilmGraph(direction) {
    this._beginNilmGraphIntent();
    const window = this._nilmWorkspaceGraphWindow(this._nilmWorkspace);
    this._lastActionMessage = this._panelText("messages.updated_nilm_graph_window");
    this._panGraphWindow(window, direction, (next) => { this._nilmGraphWindow = next; });
  }

  _setNilmGraphWindow(start, end, bounds, intentToken = null) {
    const token = intentToken === null ? this._beginNilmGraphIntent() : intentToken;
    if (!this._isCurrentNilmGraphIntent(token)) return false;
    this._setGraphWindow(start, end, bounds, (next) => { this._nilmGraphWindow = next; });
    return true;
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

  _renderNilmMergeTarget(signature, sourceKey) {
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
      <div class="merge-targets" id="nilm_merge_targets_${sourceKey}" data-selected="${this._escape(selectedTarget)}">
        ${options.map((option) => this._nilmMergeTargetChip(sourceKey, option, option.value === selectedTarget)).join("")}
      </div>
    `;
  }

  _loadExpandedNilm() {
    const routeUrl = new URL(this._routeKey(), window.location.origin);
    routeUrl.searchParams.set(EXPAND_NILM_QUERY_PARAM, "1");
    this._navigate(`${routeUrl.pathname}${routeUrl.search}${routeUrl.hash}`);
  }

  _nilmMergeTargetChip(sourceKey, option, selected = false) {
    return `
      <button
        type="button"
        class="merge-target-chip"
        data-nilm-source-key="${this._escape(sourceKey)}"
        data-nilm-merge-target="${this._escape(option.value)}"
        aria-pressed="${selected}"
      >${this._escape(option.label)}</button>
    `;
  }

  _selectNilmMergeTarget(sourceKey, target) {
    const targetList = this.shadowRoot.querySelector(`#nilm_merge_targets_${sourceKey}`);
    if (!targetList || !target) {
      return;
    }
    targetList.dataset.selected = target;
    const signature = this._decisionSignature(sourceKey);
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
    const graphEvidence = this._nilmFocusedGraphEvidence(workspace);
    const graphBands = this._nilmGraphBands(workspace, graphEvidence.sessions);
    const intervalEditor = this._renderNilmLabelIntervalEditor(workspace);
    const intervalFeedback = this._renderNilmIntervalFeedback();
    return `
      <div class="nilm-workspace">
        ${this._renderNilmWorkspaceSummary(workspace)}
        ${this._renderNilmConfiguredPrimary(workspace)}
        ${this._renderNilmModelEvidence()}
        <section class="workspace-section nilm-graph-section section-surface">${this._renderNilmGraph(workspace, graphWindow, graphBands)}</section>
        ${intervalEditor || intervalFeedback ? `<section class="workspace-section nilm-interval-editor-section section-surface">${intervalEditor}${intervalFeedback}</section>` : ""}
        <section class="workspace-section section-surface">${this._renderNilmWorkspaceLanes(workspace)}</section>
        <section class="workspace-section section-surface">${this._renderNilmReviewLayout(workspace)}</section>
        ${this._renderNilmSecondaryCollections(workspace)}
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
    const sensitivity = workspace.sensitivity || {};
    const sensitivityAction = sensitivity.action && sensitivity.recommendation ? `
      <button type="button" class="secondary" data-nilm-sensitivity-action>${this._escape(this._panelTextFormat("nilm_workspace.use_sensitivity", { setting: this._friendlyFeature(sensitivity.recommendation) }))}</button>` : "";
    return `
      <section class="workspace-summary section-surface" data-nilm-workspace-summary aria-label="${this._escape(this._panelText("nilm_workspace.workspace_summary"))}">
        <div class="workspace-summary-item">
          <span>${this._escape(this._panelText("nilm_workspace.circuit"))}</span>
          <strong>${this._escape(circuit.name || circuit.circuit_id || this._panelText("common.unknown"))}</strong>
        </div>
        ${sourcePicker}
        <div class="workspace-summary-item" data-nilm-sensitivity>
          <span>${this._escape(this._panelText("nilm_workspace.sensitivity"))}</span>
          <strong>${this._escape(this._friendlyFeature(sensitivity.current || "balanced"))} · ${this._escape(this._formatMetricValue(sensitivity.effective_minimum_edge_w))} W</strong>
          ${sensitivityAction}
        </div>
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

  _renderNilmConfiguredPrimary(workspace) {
    const primary = workspace && workspace.configured_primary;
    if (!primary) return "";
    const current = primary.current_binding;
    const suggestion = primary.suggestion;
    const evidence = primary.evidence || {};
    const signature = primary.signature || (current
      ? { status: "established", signature_id: current.signature_id, display_label: current.display_label }
      : { status: "not_established" });
    const attribution = primary.attribution || {
      status: current ? "active" : "inactive",
      matching_detection_count: 0,
    };
    const signatureText = signature.status === "established"
      ? this._panelTextFormat("nilm_workspace.primary_signature_established", {
        load: signature.display_label || signature.signature_id || "",
        count: Number(signature.recurrence_count || 0),
      })
      : this._panelText("nilm_workspace.primary_signature_not_established");
    const attributionText = attribution.status === "active"
      ? this._panelTextFormat("nilm_workspace.primary_attribution_active", {
        count: Number(attribution.matching_detection_count || 0),
      })
      : this._panelText("nilm_workspace.primary_attribution_inactive");
    return `<section class="workspace-section section-surface" data-nilm-configured-primary>
      <h2>${this._escape(this._panelText("nilm_workspace.configured_primary"))}</h2>
      <strong>${this._escape(primary.display_name || primary.assignment_id || "")}</strong>
      <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.primary_configured", { name: primary.display_name || primary.assignment_id || "" }))}</p>
      <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.primary_evidence", { count: Number(evidence.confirmed_interval_count || 0) }))}</p>
      <p class="muted">${this._escape(signatureText)}</p>
      <p class="muted">${this._escape(attributionText)}</p>
      ${suggestion ? `<div data-nilm-primary-suggestion>
        <p><strong>${this._escape(suggestion.display_label || suggestion.signature_id || "")}</strong></p>
        ${suggestion.evidence_summary ? `<p class="muted">${this._escape(suggestion.evidence_summary)}</p>` : ""}
        ${suggestion.confidence !== undefined ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_confidence", { confidence: Math.round(Number(suggestion.confidence || 0) * 100) }))}</p>` : ""}
        ${suggestion.action ? `<button type="button" data-nilm-primary-confirm ${this._busyAction === "nilm_primary" ? "disabled" : ""}>${this._escape(this._panelText(current ? "nilm_workspace.primary_change" : "nilm_workspace.primary_confirm"))}</button>` : ""}
      </div>` : ""}
      ${this._renderInlineFeedback("nilm-primary")}
    </section>`;
  }

  _renderNilmModelEvidence() {
    return `<section class="workspace-section section-surface" data-nilm-model-evidence>
      <h2>${this._escape(this._panelText("nilm_workspace.model_evidence"))}</h2>
      <p class="muted">${this._escape(this._panelText("nilm_workspace.workflow_guidance"))}</p>
    </section>`;
  }

  async _applyNilmSensitivity() {
    const action = this._nilmWorkspace && this._nilmWorkspace.sensitivity && this._nilmWorkspace.sensitivity.action;
    if (!this._guardActionCall(action, "NILM sensitivity", "nilm-sensitivity")) return;
    await this._hass.callService(action.domain || "circuitsetup_energy_analyzer", action.service, { ...(action.data || {}) });
    await this._refreshNilmWorkspaceData();
    this._render();
  }

  _renderNilmGraph(workspace, graphWindow, graphBands) {
    const series = this._visibleNilmWorkspaceSeries(workspace, graphWindow);
    const graphEdges = this._nilmFocusedGraphEvidence(workspace).edges;
    const hasGraph = Boolean(graphWindow && series.length);
    const graphEmpty = !this._nilmWorkspaceHistoryLoading
      && !this._nilmWorkspaceHistoryError
      && !hasGraph;
    const focusedInterval = this._nilmFocusedLabelInterval();
    const graph = this._nilmWorkspaceHistoryLoading
      ? `<div class="loading-skeleton graph-loading-skeleton" data-loading-skeleton role="status" aria-label="${this._escape(this._panelText("chart.loading_history"))}"></div>`
      : this._nilmWorkspaceHistoryError
        ? `<div data-nilm-history-error><p class="muted">${this._escape(this._nilmWorkspaceHistoryError)}</p><button type="button" class="secondary" data-retry-nilm-history>${this._escape(this._panelText("common.retry"))}</button></div>`
        : hasGraph
          ? this._chartSvg(series, { graph_window_start: new Date(graphWindow.start).toISOString(), graph_window_end: new Date(graphWindow.end).toISOString(), y_axis_label: "W", nilm_select_interval: this._nilmIntervalEditorOpen, nilm_edges: graphEdges, nilm_sessions: graphBands })
          : `<p class="muted">${this._escape((workspace.history && workspace.history.missing_real_power_reason) || this._panelText("nilm_workspace.no_graph_history"))}</p>`;
    const intervalAction = !this._nilmIntervalEditorOpen
      ? graphEmpty
        ? `<div class="actions"><button type="button" class="secondary" data-nilm-open-interval-editor>${this._escape(this._panelText("nilm_workspace.label_interval"))}</button></div>`
        : hasGraph && focusedInterval
          ? `<div class="actions"><button type="button" class="secondary" data-nilm-edit-focused-interval>${this._escape(this._panelText("nilm_workspace.edit_interval"))}</button></div>`
          : ""
      : "";
    return `
      ${this._nilmFocusedSignature ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.focused_graph"))}</p>` : ""}
      ${this._renderNilmOccurrenceControls()}
      ${this._renderNilmGraphControls(graphWindow)}
      ${graph}
      ${intervalAction}
    `;
  }

  _nilmGraphBands(workspace, sessions) {
    const assignments = Array.isArray(workspace.assignments) ? workspace.assignments : [];
    const hiddenAssignments = new Set(assignments
      .filter((item) => ["ignored", "retired"].includes(String(item.lifecycle_state || "").toLowerCase()))
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
    const draftBands = this._nilmIntervalEditorOpen ? draftIntervals.flatMap((item, index) => {
      const start = this._datetimeLocalToMillis(item.start, item.start_millis);
      const end = this._datetimeLocalToMillis(item.end, item.end_millis);
      return Number.isFinite(start) && Number.isFinite(end) && end > start
        ? [{
          ...item,
          start: new Date(start).toISOString(),
          end: new Date(end).toISOString(),
          band_kind: "draft",
          draft_index: index,
          display_label: draft.label,
          selected: index === this._nilmActiveIntervalIndex,
        }]
        : [];
    }) : [];
    const focused = this._nilmFocusedInterval;
    const sessionBands = focused && !(sessions || []).length
      ? workspace.sessions || []
      : sessions || [];
    const focusedBands = [...sessionBands, ...labelBands].map((item) => ({
      ...item,
      selected: focused
        ? Date.parse(item.start || "") === focused.start
          && Date.parse(item.end || "") === focused.end
        : Boolean(item.selected),
    }));
    return [...focusedBands, ...draftBands];
  }

  _nilmAssignmentFocusInterval(assignment) {
    const fingerprints = new Set(assignment.signature_fingerprints || []);
    const session = [...(this._nilmWorkspace.sessions || [])]
      .filter((item) => item.end && !item.ambiguous && (
        item.assignment_id === assignment.assignment_id
        || fingerprints.has(item.signature_fingerprint)
      ))
      .sort((left, right) => Date.parse(right.end) - Date.parse(left.end))[0];
    if (session) return session;
    return [...(this._nilmWorkspace.label_intervals || [])]
      .filter((item) => item.assignment_id === assignment.assignment_id)
      .sort((left, right) => Date.parse(right.end) - Date.parse(left.end))[0] || null;
  }

  async _focusNilmReviewItem(reviewItem, options = {}) {
    if (!reviewItem) return false;
    if (reviewItem.kind === "signature") {
      const fingerprint = this._nilmSignatureFingerprint(reviewItem.item);
      if (!fingerprint) return false;
      return (await this._focusNilmSignatureOnGraph(
        fingerprint,
        { scroll: options.scroll === true, toggle: false },
      )) === true;
    }
    if (reviewItem.kind === "session") {
      return this._loadNilmSessionInterval(reviewItem.item);
    }
    const interval = reviewItem.kind === "assignment"
      ? this._nilmAssignmentFocusInterval(reviewItem.item)
      : reviewItem.item;
    const start = Date.parse(interval && interval.start || "");
    const end = Date.parse(interval && interval.end || "");
    this._beginNilmGraphIntent();
    this._nilmFocusedSignature = "";
    this._nilmFocusedOccurrenceIndex = -1;
    this._nilmFocusedInterval = null;
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
      this._lastActionMessage = reviewItem.kind === "assignment"
        ? this._panelText("messages.no_completed_assignment_interval")
        : "";
      await this._loadNilmWorkspaceHistory();
      this._render();
      return false;
    }
    this._lastActionMessage = "";
    return this._loadNilmIntervalOnGraph(interval, { edit: false, scroll: options.scroll !== false });
  }

  _renderNilmSecondaryCollections(workspace) {
    const unassignedSessions = (Array.isArray(workspace.sessions) ? workspace.sessions : [])
      .map((item, index) => ({ ...item, workspace_index: index }))
      .filter((item) => !String(item && item.assignment_id || "").trim());
    return `<section class="workspace-section section-surface" data-nilm-secondary-collections>
      <h2>${this._escape(this._panelText("nilm_workspace.secondary_details"))}</h2>
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
        ${workspace.source && workspace.source.source_kind === "mains" ? this._renderNilmWorkspaceList(this._panelText("nilm_workspace.known_load_overlays"), workspace.known_load_overlays, this._panelText("nilm_workspace.known_load_overlays_empty"), (item) => `
        <div class="metric">
          <span>${this._escape(item.circuit_id)}</span>
          <strong>${this._escape(item.name || item.circuit_id)}</strong>
          <p class="muted">${this._escape(this._overlayEntitySummary(item))}</p>
        </div>
      `, this._panelText("nilm_workspace.known_load_overlays_description")) : ""}
        ${workspace.source && workspace.source.source_kind === "mains" ? this._renderNilmWorkspaceList(this._panelText("nilm_workspace.solar_net_overlays"), workspace.solar_overlays, this._panelText("nilm_workspace.solar_net_overlays_empty"), (item) => `
        <div class="metric">
          <span>${this._escape(item.circuit_id)}</span>
          <strong>${this._escape(item.name || item.circuit_id)}</strong>
          <p class="muted">${this._escape(this._overlayEntitySummary(item))}</p>
        </div>
      `, this._panelText("nilm_workspace.solar_net_overlays_description")) : ""}
        ${this._renderNilmWorkspaceList(this._panelText("nilm_workspace.sessions_title"), unassignedSessions, this._panelText("nilm_workspace.sessions_empty"), (item, index) => `
        <div class="metric">
          <span>${this._escape(item.start || "")}</span>
          <strong>${this._escape(this._panelTextFormat("nilm_workspace.session_summary", { power: this._formatMetricValue(item.median_power_w), confidence: Math.round(Number(item.confidence || 0) * 100) }))}</strong>
          <p class="muted">${this._escape(item.end ? this._panelTextFormat("nilm_workspace.session_end", { end: item.end }) : this._panelText("common.open_session"))}</p>
          ${item.actions && item.actions.assign ? this._renderNilmSessionAssignField(item, item.workspace_index) : ""}
          ${item.actions && item.actions.assign ? `<div class="actions">
            <button type="button" class="secondary" data-nilm-session-index="${item.workspace_index}" data-nilm-session-action="assign" ${this._busyAction === `nilm_sessions_${item.workspace_index}_assign` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.assign_appliance"))}</button>
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
    </section>`;
  }

  _nilmLaneItems(workspace, laneKey = this._nilmActiveLane) {
    if (!workspace || !workspace.lanes) return [];
    const activeLaneKey = workspace.lanes[laneKey] ? laneKey : "needs_review";
    if (laneKey === this._nilmActiveLane) this._nilmActiveLane = activeLaneKey;
    const lane = workspace.lanes[activeLaneKey] || {};
    const signatureIds = new Set(Array.isArray(lane.signature_ids) ? lane.signature_ids : []);
    const assignmentIds = new Set(Array.isArray(lane.assignment_ids) ? lane.assignment_ids : []);
    const intervalIds = new Set(Array.isArray(lane.interval_ids) ? lane.interval_ids : []);
    const sessionIds = new Set(Array.isArray(lane.session_ids) ? lane.session_ids : []);
    const signatures = (Array.isArray(workspace && workspace.signatures) ? workspace.signatures : [])
      .map((item, index) => ({ kind: "signature", item, index }))
      .filter(({ item }) => signatureIds.has(item.signature_id));
    const assignments = (Array.isArray(workspace && workspace.assignments) ? workspace.assignments : [])
      .map((item, index) => ({ kind: "assignment", item, index }))
      .filter(({ item }) => assignmentIds.has(item.assignment_id));
    const intervals = (Array.isArray(workspace && workspace.label_intervals) ? workspace.label_intervals : [])
      .map((item, index) => ({ kind: "interval", item, index }))
      .filter(({ item }) => intervalIds.has(item.interval_id));
    const sessions = (Array.isArray(workspace && workspace.sessions) ? workspace.sessions : [])
      .map((item, index) => ({ kind: "session", item, index }))
      .filter(({ item }) => sessionIds.has(item.session_id));
    return [...signatures, ...assignments, ...intervals, ...sessions];
  }

  _nilmReviewKey(reviewItem) {
    const id = reviewItem.kind === "assignment"
      ? reviewItem.item.assignment_id
      : reviewItem.kind === "interval"
        ? reviewItem.item.interval_id
        : reviewItem.kind === "session"
          ? reviewItem.item.session_id
        : reviewItem.item.signature_id || this._nilmSignatureFingerprint(reviewItem.item);
    return `${reviewItem.kind}:${id}`;
  }

  _nilmSelectedReviewItem(workspace) {
    const items = this._nilmLaneItems(workspace);
    return items.find((item) => this._nilmReviewKey(item) === this._nilmSelectedReviewKey) || items[0] || null;
  }

  _selectNilmReviewItemForFocus(workspace, reviewItem) {
    const key = this._nilmReviewKey(reviewItem);
    const laneKey = Object.keys(workspace.lanes || {}).find((candidate) => (
      this._nilmLaneItems(workspace, candidate).some((item) => (
        this._nilmReviewKey(item) === key
      ))
    ));
    if (laneKey) {
      this._nilmActiveLane = laneKey;
      this._nilmSelectedReviewKey = key;
    }
    this._nilmSyncHelperSelection(workspace);
  }

  async _focusNilmRouteTarget(workspace, routeKey) {
    const params = new URL(routeKey, window.location.origin).searchParams;
    const candidates = [
      ["interval", "interval_id", workspace.label_intervals || [], "interval_id"],
      ["session", "session_id", workspace.sessions || [], "session_id"],
      ["assignment", "assignment_id", workspace.assignments || [], "assignment_id"],
    ];
    for (const [kind, parameter, items, idKey] of candidates) {
      const id = params.get(parameter) || "";
      const index = id ? items.findIndex((item) => item[idKey] === id) : -1;
      if (index < 0) continue;
      const reviewItem = { kind, item: items[index], index };
      this._selectNilmReviewItemForFocus(workspace, reviewItem);
      return this._focusNilmReviewItem(reviewItem, { scroll: false });
    }
    return false;
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
    const powerText = item.typical_power_source === "interval_average"
      ? `${this._panelText("nilm_workspace.average_power")}: ${this._formatMetricValue(power)} W`
      : `${this._formatMetricValue(power)} W`;
    const state = String(item.review_state || item.lifecycle_state || this._nilmActiveLane).toLowerCase();
    const stateLabel = state === "retired"
      ? this._panelText("nilm_workspace.lane_hidden")
      : this._friendlyFeature(state);
    const fingerprint = reviewItem.kind === "interval" ? "" : this._nilmSignatureFingerprint(item);
    const contextFacts = reviewItem.kind === "signature" ? [
      item.seen_count !== undefined
        ? `${this._panelText("nilm_workspace.fact_seen_count")}: ${item.seen_count}`
        : "",
      item.last_seen
        ? `${this._panelText("nilm_workspace.fact_last_seen")}: ${this._formatDateTime(item.last_seen)}`
        : "",
    ].filter(Boolean) : [];
    const ambiguity = reviewItem.kind === "session" && item.ambiguous
      ? `<span>${this._escape(this._panelText("nilm_workspace.session_ambiguous"))}</span>`
      : "";
    if (reviewItem.kind === "interval") {
      return `<button type="button" class="nilm-review-card" data-nilm-review-item="${this._escape(this._nilmReviewKey(reviewItem))}" aria-pressed="${selected}">
        <span class="review-card-heading"><strong>${this._escape(title)}</strong><span>${this._escape(this._panelText("nilm_workspace.lane_needs_review"))}</span></span>
        <span class="review-card-facts"><span>${this._escape(this._formatDateTime(item.start))}</span><span>${this._escape(this._formatDateTime(item.end))}</span></span>
      </button>`;
    }
    return `<button type="button" class="nilm-review-card" data-nilm-review-item="${this._escape(this._nilmReviewKey(reviewItem))}" ${fingerprint ? `data-nilm-signature-fingerprint="${this._escape(fingerprint)}"` : ""} aria-pressed="${selected}">
      <span class="review-card-heading"><strong>${this._escape(title)}</strong><span>${this._escape(stateLabel)}</span></span>
      <span class="power-meter" style="--power-percent:${this._nilmPowerPercent(reviewItem, reviewItems)}%"><span></span></span>
      <span class="review-card-facts"><span>${this._escape(powerText)}</span><span>${confidence}%</span></span>
      ${ambiguity ? `<span class="review-card-facts">${ambiguity}</span>` : ""}
      ${contextFacts.length ? `<span class="review-card-facts review-card-context">${contextFacts.map((fact) => `<span>${this._escape(fact)}</span>`).join("")}</span>` : ""}
      <progress max="100" value="${confidence}" aria-label="${this._escape(this._panelTextFormat("nilm_workspace.assignment_confidence", { confidence }))}"></progress>
    </button>`;
  }

  _renderNilmReviewInspector(reviewItem) {
    const item = reviewItem.item;
    const title = item.display_label || item.display_name || item.label || item.likely_type || item.appliance_id || this._panelText("common.unknown_load");
    const assignedIntervals = reviewItem.kind === "assignment"
      ? ((this._nilmWorkspace && this._nilmWorkspace.label_intervals) || [])
        .map((interval, index) => ({ interval, index }))
        .filter(({ interval }) => interval.assignment_id === item.assignment_id
          || (item.label_interval_ids || []).includes(interval.interval_id))
      : [];
    const content = reviewItem.kind === "assignment"
      ? `
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_confidence", { confidence: Math.round(Number(item.confidence || 0) * 100) }))}</p>
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_rates", { false_positive: Math.round(Number(item.false_positive_rate || 0) * 100), false_negative: Math.round(Number(item.false_negative_rate || 0) * 100) }))}</p>
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_errors", { power: this._formatMetricValue(item.median_power_error), energy: this._formatMetricValue(item.energy_estimate_error) }))}</p>
        ${assignedIntervals.length ? `<div class="entity-list" data-nilm-assigned-intervals>${assignedIntervals.map(({ interval, index }) => `<div class="metric">
          <span>${this._escape(this._panelText("common.labeled_interval"))}</span>
          <strong>${this._escape(this._formatNilmSessionRange(interval))}</strong>
          <div class="actions">
            <button type="button" class="secondary" data-nilm-label-interval-index="${index}" data-nilm-label-interval-action="adjust">${this._escape(this._panelText("actions.labels.show_on_graph"))}</button>
          </div>
        </div>`).join("")}</div>` : ""}
        ${this._renderNilmHelperEvidence(item, reviewItem.index)}
        ${this._renderNilmReferenceSensors(item, reviewItem.index)}
        ${this._renderNilmAssignmentEditFields(item, reviewItem.index)}
        ${this._renderNilmAssignmentActions(item, reviewItem.index)}
        ${this._renderInlineFeedback(this._nilmReviewKey(reviewItem))}
      `
      : reviewItem.kind === "interval"
        ? `<p class="muted">${this._escape(this._formatNilmSessionRange(item))}</p>
          <div class="actions"><button type="button" class="secondary" data-nilm-label-interval-index="${reviewItem.index}" data-nilm-label-interval-action="adjust">${this._escape(this._panelText("actions.labels.show_on_graph"))}</button></div>`
        : reviewItem.kind === "session"
          ? `
            <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_confidence", { confidence: Math.round(Number(item.confidence || 0) * 100) }))}</p>
            ${item.ambiguous ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.session_ambiguous"))}</p>` : ""}
            ${item.signature_review ? `
              <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.session_signature_review", { load: item.signature_review.display_label || item.signature_review.signature_id || "" }))}</p>
              ${this._renderNilmSignatureReview(item.signature_review, `session_${reviewItem.index}`)}
            ` : `
              ${this._renderNilmSessionAssignField(item, reviewItem.index)}
              ${item.actions && item.actions.assign ? `<div class="actions"><button type="button" data-nilm-session-index="${reviewItem.index}" data-nilm-session-action="assign">${this._escape(this._panelText("actions.labels.assign_appliance"))}</button></div>` : ""}
            `}
          `
        : `
        ${this._renderNilmSignatureFacts(item)}
        ${this._renderNilmSignatureReview(item, `signature_${reviewItem.index}`, reviewItem.index)}
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
    const laneDescription = (lane && lane.description)
      || (this._nilmActiveLane === "hidden" ? this._panelText("nilm_workspace.hidden_description") : "");
    const selectedItem = reviewItems.length ? this._nilmSelectedReviewItem(workspace) : null;
    const selectedKey = selectedItem ? this._nilmReviewKey(selectedItem) : "";
    return `<div class="nilm-review-layout" id="nilm_review_lane_panel" role="tabpanel" aria-labelledby="nilm_lane_${this._escape(this._nilmActiveLane)}">
      ${laneDescription ? `<p class="muted" data-nilm-lane-description>${this._escape(laneDescription)}</p>` : ""}
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
    this._beginNilmGraphIntent();
    this._nilmActiveLane = laneKey || "needs_review";
    this._nilmSelectedReviewKey = "";
    this._nilmFocusedSignature = "";
    this._nilmFocusedOccurrenceIndex = -1;
    this._nilmFocusedInterval = null;
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
      ["hidden", this._panelText("nilm_workspace.lane_hidden")],
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
        && (!session.end || (actions && (actions.validate || actions.reject)));
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
    const isOpen = !session.end;
    const confidence = session.confidence !== undefined
      ? `<p class="muted">${this._escape(this._panelTextFormat("appliance_detail.confidence_value", { confidence: this._formatConfidence(session.confidence) }))}</p>`
      : "";
    const lowConfidence = this._isLowNilmConfidence(session.confidence)
      ? `<p class="muted">${this._escape(this._nilmLowConfidenceExplanation(session))}</p>`
      : "";
    const duration = this._nilmSessionDuration(session);
    const validationActions = isOpen ? "" : `<div class="actions">
      ${actions.validate ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="validate" ${this._busyAction === `nilm_sessions_${index}_validate` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.correct"))}</button>` : ""}
      ${actions.reject ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="reject" ${this._busyAction === `nilm_sessions_${index}_reject` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.wrong_appliance_sentence"))}</button>` : ""}
      ${session.start && session.end ? `<button type="button" class="secondary" data-nilm-session-interval-index="${index}">${this._escape(this._panelText("actions.labels.adjust_interval"))}</button>` : ""}
    </div>`;
    return `
      <div class="metric" data-nilm-session-validation-card data-nilm-open="${isOpen}">
        <strong>${this._escape(this._panelTextFormat("nilm_workspace.predicted", { label }))}</strong>
        <span class="muted" data-nilm-session-range>${this._escape(this._formatNilmSessionRange(session))}</span>
        <p class="muted">${this._escape(isOpen
          ? this._panelTextFormat("nilm_workspace.provisional_confidence", { confidence: this._formatConfidence(session.confidence) })
          : this._panelTextFormat("nilm_workspace.estimated_by_nilm", { duration: duration ? `, ${duration}` : "" }))}</p>
        ${isOpen ? "" : confidence}
        ${isOpen ? "" : lowConfidence}
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.session_power_summary", { power: this._formatMetricValue(session.median_power_w), energy: this._formatMetricValue(session.estimated_energy_kwh) }))}</p>
        ${validationActions}
      </div>
    `;
  }

  _nilmLowConfidenceExplanation(session) {
    if (session && session.ambiguous) {
      return this._panelText("nilm_workspace.low_confidence_ambiguous");
    }
    if (Number(session && session.alternate_match_count) > 0) {
      return this._panelText("nilm_workspace.low_confidence_alternate_matches");
    }
    if (Number(session && session.overlap_count) > 0) {
      return this._panelText("nilm_workspace.low_confidence_overlap");
    }
    if (session && (session.known_load_masked || session.known_load_confidence != null)) {
      return this._panelText("nilm_workspace.low_confidence_known_load");
    }
    return this._panelText("nilm_workspace.low_confidence");
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
    addFact(this._panelText("nilm_workspace.fact_electrical_class"), signature.electrical_class ? this._friendlyFeature(signature.electrical_class) : undefined);
    const occurrence = signature.latest_session || {};
    addFact(this._panelText("nilm_workspace.fact_active_start"), occurrence.start ? this._formatDateTime(occurrence.start) : undefined);
    addFact(this._panelText("nilm_workspace.fact_active_stop"), occurrence.end ? this._formatDateTime(occurrence.end) : undefined);
    addFact(this._panelText("nilm_workspace.fact_active_duration"), occurrence.duration_seconds !== undefined ? this._formatDuration(occurrence.duration_seconds) : undefined);
    addFact(this._panelText("nilm_workspace.fact_seen_count"), signature.seen_count);
    const topology = String(signature.topology_applicability || "").toLowerCase();
    const showTopology = topology === "available" || (!topology && (signature.voltage_class || signature.dominant_leg));
    if (showTopology) {
      addFact(this._panelText("nilm_workspace.fact_voltage_class"), String(signature.voltage_class || "").toLowerCase() === "unknown" ? undefined : signature.voltage_class);
      addFact(this._panelText("nilm_workspace.fact_dominant_leg"), String(signature.dominant_leg || "").toLowerCase() === "unknown" ? undefined : signature.dominant_leg);
    }
    addFact(this._panelText("nilm_workspace.fact_known_load_overlap"), this._formatNilmSignatureFact(signature.known_load_overlap));
    addFact(this._panelText("nilm_workspace.fact_why_grouped"), signature.why_grouped);
    addFact(this._panelText("nilm_workspace.fact_last_seen"), signature.last_seen ? this._formatDateTime(signature.last_seen) : undefined);
    const requirement = topology === "unavailable" && signature.topology_requirement
      ? `<p class="muted" data-nilm-topology-requirement>${this._escape(signature.topology_requirement)}</p>`
      : "";
    if (!facts.length && !requirement) {
      return "";
    }
    return `${facts.map(([label, value]) => `<p class="muted">${this._escape(label)}: ${this._escape(this._formatMetricValue(value))}</p>`).join("")}${requirement}`;
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
    const invalidInterval = intervals.some((interval) => {
      const start = this._datetimeLocalToMillis(interval.start, interval.start_millis);
      const end = this._datetimeLocalToMillis(interval.end, interval.end_millis);
      return !Number.isFinite(start) || !Number.isFinite(end) || end <= start;
    });
    const saveBusy = this._busyAction === "nilm_label_interval_save" || invalidInterval ? "disabled" : "";
    const intervalEvidence = this._nilmIntervalEvidence;
    const savedIntervals = Array.isArray(workspace && workspace.label_intervals)
      ? workspace.label_intervals
      : [];
    return `<div class="metric" data-nilm-interval-editor>
        <h3>${this._escape(this._panelText("nilm_workspace.interval_prompt"))}</h3>
        <p class="muted">${this._escape(this._panelText("nilm_workspace.interval_prompt_detail"))}</p>
        <div class="nilm-interval-form nilm-interval-identity">
          ${this._renderNilmExistingAssignmentField(action, "label_interval", draft.assignment_id)}
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
          ${intervals.map((interval, index) => {
            const savedIndex = savedIntervals.findIndex((item) => item.interval_id === interval.interval_id);
            const saved = savedIndex >= 0 ? savedIntervals[savedIndex] : null;
            return `<div class="nilm-interval-row" data-nilm-interval-row="${index}" data-nilm-active="${index === this._nilmActiveIntervalIndex}">
            <div class="nilm-interval-row-heading">
              <strong>${this._escape(this._panelTextFormat("nilm_workspace.interval_number", { number: index + 1 }))}</strong>
              <span data-nilm-editing-indicator="${index}" ${index === this._nilmActiveIntervalIndex ? "" : "hidden"}>${this._escape(this._panelTextFormat("nilm_workspace.editing_interval", { number: index + 1 }))}</span>
              ${saved
                ? `<button type="button" class="secondary" data-nilm-remove-interval="${index}">${this._escape(this._panelText("actions.labels.remove_interval"))}</button>`
                : !interval.interval_id
                  ? `<button type="button" class="secondary" data-nilm-remove-interval="${index}">${this._escape(this._panelText("actions.labels.remove_interval"))}</button>`
                  : ""}
            </div>
            <div class="nilm-interval-form">
              <label><span class="muted">${this._escape(this._panelText("nilm_workspace.start"))}</span><input type="datetime-local" data-nilm-label-interval-input="start" data-nilm-interval-index="${index}" value="${this._escape(interval.start || "")}"></label>
              <label><span class="muted">${this._escape(this._panelText("nilm_workspace.end"))}</span><input type="datetime-local" data-nilm-label-interval-input="end" data-nilm-interval-index="${index}" value="${this._escape(interval.end || "")}"></label>
            </div>
          </div>`;
          }).join("")}
        </div>
        <div class="actions">
          <button type="button" data-nilm-label-interval-action="save" ${saveBusy}>${this._escape(this._panelText("actions.labels.save_interval"))}</button>
          <button type="button" class="secondary" data-nilm-cancel-interval-editor>${this._escape(this._panelText("actions.labels.cancel"))}</button>
        </div>
        ${this._renderNilmIntervalEvidence(intervalEvidence)}
      </div>`;
  }

  _nilmIntervalEvidenceRequest() {
    const interval = this._nilmIntervalDraftItems()[this._nilmActiveIntervalIndex] || {};
    const start = this._datetimeLocalToIso(interval.start, interval.start_millis);
    const end = this._datetimeLocalToIso(interval.end, interval.end_millis);
    const route = new URL(this._loadedRouteKey || window.location.href, window.location.origin);
    const entryId = route.searchParams.get("entry_id") || "";
    const circuitId = (this._nilmWorkspace && this._nilmWorkspace.circuit && this._nilmWorkspace.circuit.circuit_id)
      || route.searchParams.get("circuit_id") || "";
    if (!start || !end || Date.parse(end) <= Date.parse(start) || !entryId || !circuitId) return "";
    const params = new URLSearchParams({ entry_id: entryId, circuit_id: circuitId, start, end });
    return `${NILM_INTERVAL_EVIDENCE_API_PATH}?${params}`;
  }

  _scheduleNilmIntervalEvidence() {
    const path = this._nilmIntervalEvidenceRequest();
    this._nilmIntervalEvidence = null;
    const token = (this._nilmIntervalEvidenceToken || 0) + 1;
    const graphIntentToken = this._nilmGraphIntentToken;
    this._nilmIntervalEvidenceToken = token;
    if (this._nilmIntervalEvidenceTimer) clearTimeout(this._nilmIntervalEvidenceTimer);
    this._render();
    if (!path) return;
    this._nilmIntervalEvidenceTimer = setTimeout(() => {
      if (!this._isCurrentNilmGraphIntent(graphIntentToken)) return;
      this._requestNilmIntervalEvidence(path, token, graphIntentToken);
    }, 180);
  }

  async _requestNilmIntervalEvidence(path, token, graphIntentToken = this._nilmGraphIntentToken) {
    try {
      const payload = await this._requestJson(path, path);
      if (token !== this._nilmIntervalEvidenceToken
          || !this._isCurrentNilmGraphIntent(graphIntentToken)) return;
      this._nilmIntervalEvidence = payload && payload.interval_evidence || null;
    } catch (_error) {
      if (token !== this._nilmIntervalEvidenceToken
          || !this._isCurrentNilmGraphIntent(graphIntentToken)) return;
      this._nilmIntervalEvidence = null;
    }
    if (token === this._nilmIntervalEvidenceToken
        && this._isCurrentNilmGraphIntent(graphIntentToken)) this._render();
  }

  _renderNilmIntervalEvidence(evidence) {
    if (!evidence) return "";
    const metrics = [
      ["Start", evidence.start_transition_w, "W"], ["Stop", evidence.stop_transition_w, "W"],
      ["Average", evidence.average_power_w, "W"], ["Median", evidence.median_power_w, "W"],
      [Number.isFinite(Number(evidence.measured_energy_kwh)) ? "Measured energy" : "Partial energy", evidence.measured_energy_kwh ?? evidence.partial_energy_kwh, "kWh"],
      ["Source coverage", evidence.source_coverage, ""], ["Power coverage", evidence.power_coverage, ""],
    ].filter(([, value]) => Number.isFinite(Number(value)));
    const warnings = Array.isArray(evidence.quality_flags) && evidence.quality_flags.length
      ? `<p class="muted">Quality: ${this._escape(evidence.quality_flags.join(", "))}</p>` : "";
    return `<div class="muted" data-nilm-interval-evidence>${metrics.map(([label, value, unit]) => `${this._escape(label)}: ${this._escape(this._formatNumber(value))}${unit ? ` ${unit}` : ""}`).join(" · ")}${warnings}</div>`;
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
    const publication = item && item.publication;
    const publicationState = publication && publication.available === false
      ? `<p class="muted" data-nilm-publication-reason>${this._escape(publication.reason || "")}</p><button type="button" class="secondary" disabled>${this._escape(this._panelText("actions.labels.create_ha_device"))}</button>`
      : "";
    const detailButton = this._nilmApplianceDetailButton(item);
    if ((!actions || !Object.keys(actions).length) && !detailButton && !publicationState) {
      return "";
    }
    if (!actions || !Object.keys(actions).length) {
      return `${publicationState}<div class="actions">${detailButton}</div>`;
    }
    const hasSave = actions.rename || actions.change_profile;
    const saveDirty = this._nilmAssignmentHasChanges(item);
    return `${publicationState}
      <div class="actions">
        ${detailButton}
        ${hasSave ? `<button type="button" class="${saveDirty ? "" : "secondary"}" data-nilm-assignment-index="${index}" data-nilm-assignment-action="save" data-nilm-assignment-save-key="${this._escape(item.assignment_id || "")}" ${this._busyAction === `nilm_assignments_${index}_save` || !saveDirty ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.save"))}</button>` : ""}
        ${actions.merge ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="merge" ${this._busyAction === `nilm_assignments_${index}_merge` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.merge"))}</button>` : ""}
        ${actions.convert_to_direct_meter ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="convert_to_direct_meter" ${this._busyAction === `nilm_assignments_${index}_convert_to_direct_meter` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.convert_to_direct_meter"))}</button>` : ""}
        ${actions.confirm_primary ? `<button type="button" data-nilm-assignment-index="${index}" data-nilm-assignment-action="confirm_primary" ${this._busyAction === `nilm_assignments_${index}_confirm_primary` ? "disabled" : ""}>${this._escape(this._panelText("nilm_workspace.primary_confirm"))}</button>` : ""}
        ${actions.validate_history ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="validate_history" ${this._busyAction === `nilm_assignments_${index}_validate_history` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.validate_history"))}</button>` : ""}
        ${actions.publish ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="publish" ${this._busyAction === `nilm_assignments_${index}_publish` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.create_ha_device"))}</button>` : ""}
        ${actions.unpublish ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="unpublish" ${this._busyAction === `nilm_assignments_${index}_unpublish` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.remove_ha_device"))}</button>` : ""}
        ${actions.retire ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="retire" ${this._busyAction === `nilm_assignments_${index}_retire` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.remove_assignment"))}</button>` : ""}
        ${actions.restore ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="restore" ${this._busyAction === `nilm_assignments_${index}_restore` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.restore"))}</button>` : ""}
        ${actions.accept ? `<button type="button" data-nilm-assignment-index="${index}" data-nilm-assignment-action="accept" ${this._busyAction === `nilm_assignments_${index}_accept` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.accept_assignment"))}</button>` : ""}
        ${actions.delete_permanently ? `<button type="button" class="secondary" data-nilm-assignment-index="${index}" data-nilm-assignment-action="delete_permanently" ${this._busyAction === `nilm_assignments_${index}_delete_permanently` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.delete_permanently"))}</button>` : ""}
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
    const label = session && (session.display_label || session.display_name || session.appliance_id || session.assignment_id);
    return String(label || this._panelText("common.unknown_load")).trim();
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
    const metadata = new Map((this._nilmWorkspaceHistorySeries || []).flatMap((series) => {
      const first = Array.isArray(series) && series[0];
      const entityId = first && first.entity_id;
      return entityId ? [[entityId, first]] : [];
    }));
    return this._chartSeries(
      this._nilmWorkspaceHistorySeries,
      [],
      MAX_NILM_CHART_POINTS_PER_SERIES,
    ).flatMap((item) => {
      const source = metadata.get(item.entity_id) || {};
      const role = String(source.effective_role || source.sensor_role || "").trim().toLowerCase();
      const unit = String(source.source_unit || source.unit_of_measurement || item.unit || "").trim();
      const factor = unit === "MW" ? 1000000 : unit === "mW" ? 0.001 : unit.toLowerCase() === "kw" ? 1000 : unit.toLowerCase() === "w" ? 1 : null;
      if ((role && role !== "real_power") || factor === null) return [];
      return [{
        ...item,
        source_unit: unit,
        unit: "W",
        points: factor === 1 ? item.points : item.points.map((point) => ({
          ...point,
          value: point.value * factor,
        })),
      }];
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
