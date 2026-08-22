export function createNilmWorkspaceMethods({
  NILM_WORKSPACE_API_PATH,
  NILM_WORKSPACE_CALL_API_PATH,
  NILM_WORKSPACE_COLLECTION_API_PATH,
  NILM_WORKSPACE_ITEM_API_PATH,
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
    this._resetNilmSessionPagination();
    this._resetNilmRouteItemRequest();
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
      this._nilmSyncAmbiguityAudit(workspace);
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

  _resetNilmSessionPagination() {
    this._nilmSessionPageRequestToken = (this._nilmSessionPageRequestToken || 0) + 1;
    this._nilmSessionPageLoading = false;
    this._nilmSessionPageError = "";
    this._nilmSessionPageLiveMessage = "";
  }

  _resetNilmRouteItemRequest() {
    this._nilmWorkspaceItemRequestToken = (this._nilmWorkspaceItemRequestToken || 0) + 1;
    this._nilmRouteItemError = "";
  }

  _nilmSessionCollectionMeta(workspace = this._nilmWorkspace) {
    const meta = workspace && workspace.collection_meta && workspace.collection_meta.sessions;
    const totalCount = Number(meta && meta.total_count);
    const returnedCount = Number(meta && meta.returned_count);
    const nextCursor = String(meta && meta.next_cursor || "").trim();
    return {
      totalCount: Number.isFinite(totalCount) ? Math.max(0, totalCount) : 0,
      returnedCount: Number.isFinite(returnedCount) ? Math.max(0, returnedCount) : 0,
      truncated: Boolean(meta && meta.truncated),
      nextCursor: nextCursor || null,
    };
  }

  _nilmWorkspaceCollectionRequestPaths(
    collection,
    cursor = null,
    limit = 20,
    routeKey = this._loadedRouteKey || this._routeKey(),
  ) {
    const routeUrl = new URL(routeKey, window.location.origin);
    const workspaceCircuitId = this._nilmWorkspace?.circuit?.circuit_id;
    const payloadCircuitId = this._payload?.circuit?.circuit_id;
    const circuitId = workspaceCircuitId || payloadCircuitId || routeUrl.searchParams.get("circuit_id") || "";
    const entryId = routeUrl.searchParams.get("entry_id") || "";
    const params = new URLSearchParams({ collection: String(collection || "") });
    if (circuitId) params.set("circuit_id", circuitId);
    if (entryId) params.set("entry_id", entryId);
    if (cursor) params.set("cursor", String(cursor));
    params.set("limit", String(Math.max(1, Math.min(50, Number(limit) || 20))));
    const fetchPath = `${NILM_WORKSPACE_COLLECTION_API_PATH}?${params.toString()}`;
    return {
      apiPath: fetchPath.replace(/^\/api\//, ""),
      fetchPath,
    };
  }

  _isCurrentNilmSessionPageRequest(token, requestId, routeKey, workspace) {
    return token === this._nilmSessionPageRequestToken
      && this._isCurrentRequest(requestId, routeKey);
  }

  async _loadMoreNilmSessions() {
    const workspace = this._nilmWorkspace;
    const meta = this._nilmSessionCollectionMeta(workspace);
    if (!workspace || this._nilmSessionPageLoading || !meta.nextCursor) return false;
    const token = (this._nilmSessionPageRequestToken || 0) + 1;
    const requestId = this._evidenceRequestId;
    const routeKey = this._loadedRouteKey || this._routeKey();
    const { apiPath, fetchPath } = this._nilmWorkspaceCollectionRequestPaths(
      "sessions",
      meta.nextCursor,
      20,
      routeKey,
    );
    this._nilmSessionPageRequestToken = token;
    this._nilmSessionPageLoading = true;
    this._nilmSessionPageError = "";
    this._nilmSessionPageLiveMessage = "";
    this._render();
    try {
      const payload = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentNilmSessionPageRequest(token, requestId, routeKey, workspace)) {
        return false;
      }
      const existing = Array.isArray(workspace.sessions) ? workspace.sessions : [];
      const seen = new Set(existing.map((item) => String(item && item.session_id || "")).filter(Boolean));
      const appended = (Array.isArray(payload && payload.items) ? payload.items : [])
        .slice(0, 50)
        .filter((item) => {
          const id = String(item && item.session_id || "").trim();
          if (!id || seen.has(id)) return false;
          seen.add(id);
          return true;
        });
      const returnedCount = Number(payload && payload.returned_count);
      const totalCount = Number(payload && payload.total_count);
      this._nilmWorkspace = {
        ...workspace,
        sessions: [...existing, ...appended],
        collection_meta: {
          ...(workspace.collection_meta || {}),
          sessions: {
            total_count: Number.isFinite(totalCount) ? Math.max(0, totalCount) : meta.totalCount,
            returned_count: existing.length + appended.length,
            truncated: Boolean(payload && payload.truncated),
            next_cursor: payload && payload.next_cursor || null,
            page_returned_count: Number.isFinite(returnedCount) ? Math.max(0, returnedCount) : appended.length,
          },
        },
      };
      this._nilmSessionPageLiveMessage = this._panelTextFormat(
        "nilm_workspace.sessions_loaded",
        { count: appended.length },
      );
      return true;
    } catch (_error) {
      if (!this._isCurrentNilmSessionPageRequest(token, requestId, routeKey, workspace)) {
        return false;
      }
      this._nilmSessionPageError = this._panelText("nilm_workspace.sessions_load_failed");
      this._nilmSessionPageLiveMessage = this._nilmSessionPageError;
      return false;
    } finally {
      if (this._isCurrentNilmSessionPageRequest(token, requestId, routeKey, workspace)) {
        this._nilmSessionPageLoading = false;
        this._render();
      }
    }
  }

  _nilmAmbiguityAudit(workspace = this._nilmWorkspace) {
    const audit = workspace && workspace.ambiguity_audit;
    const totalCount = Number(audit && audit.total_count);
    const fetchPath = String(audit && audit.fetch_path || "").trim();
    return audit && Number.isFinite(totalCount) && totalCount > 0 && fetchPath
      ? audit
      : null;
  }

  _resetNilmAmbiguityAudit({ preserveExpanded = false } = {}) {
    const expanded = Boolean(preserveExpanded && this._nilmAmbiguityAuditExpanded);
    this._nilmAmbiguityAuditRequestToken = (this._nilmAmbiguityAuditRequestToken || 0) + 1;
    this._nilmAmbiguityAuditExpanded = expanded;
    this._nilmAmbiguityAuditLoading = false;
    this._nilmAmbiguityAuditError = "";
    this._nilmAmbiguityAuditItems = [];
    this._nilmAmbiguityAuditFetchedPath = "";
    this._nilmAmbiguityAuditNextCursor = null;
    this._nilmAmbiguityAuditTruncated = false;
    this._nilmAmbiguityAuditExpandedGroups = new Set();
    this._nilmAmbiguityAuditGroupResults = new Map();
    this._nilmAmbiguityAuditGroupSummaries = new Map();
    this._nilmAmbiguityAuditGroupSummariesLoading = false;
    this._nilmAmbiguityAuditGroupSummariesError = "";
    this._nilmAmbiguityAuditGroupSummariesNextCursor = null;
    this._nilmAmbiguityAuditGroupSummariesFetched = false;
  }

  _nilmSyncAmbiguityAudit(workspace, { invalidate = false } = {}) {
    const audit = this._nilmAmbiguityAudit(workspace);
    const fetchPath = String(audit && audit.fetch_path || "").trim();
    const sourceChanged = fetchPath !== this._nilmAmbiguityAuditSourcePath;
    if (sourceChanged || invalidate) {
      this._resetNilmAmbiguityAudit({
        preserveExpanded: invalidate && !sourceChanged && Boolean(audit),
      });
      this._nilmAmbiguityAuditSourcePath = fetchPath;
    }
    return this._nilmAmbiguityAuditExpanded ? audit : null;
  }

  _nilmAmbiguityAuditRequestPaths(fetchPath, groupId = "", params = {}) {
    const url = new URL(fetchPath || NILM_WORKSPACE_COLLECTION_API_PATH, window.location.origin);
    if (!url.searchParams.has("limit")) url.searchParams.set("limit", "20");
    const normalizedGroupId = String(groupId || "").trim();
    if (normalizedGroupId) url.searchParams.set("group_id", normalizedGroupId);
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && String(value).trim()) {
        url.searchParams.set(key, String(value));
      }
    }
    const requestPath = `${url.pathname}${url.search}`;
    return {
      apiPath: requestPath.replace(/^\/api\//, ""),
      fetchPath: requestPath,
    };
  }

  _isCurrentNilmAmbiguityAuditRequest(token, requestId, routeKey, fetchPath) {
    return token === this._nilmAmbiguityAuditRequestToken
      && this._isCurrentRequest(requestId, routeKey)
      && this._nilmAmbiguityAudit(this._nilmWorkspace)?.fetch_path === fetchPath;
  }

  _isCurrentNilmAmbiguityAuditGroupRequest(token, requestId, routeKey, fetchPath, groupId) {
    return this._isCurrentNilmAmbiguityAuditRequest(token, requestId, routeKey, fetchPath)
      && this._nilmAmbiguityAuditExpanded
      && Boolean(this._nilmAmbiguityAuditExpandedGroups?.has(groupId));
  }

  _isCurrentNilmAmbiguityAuditGroupSummariesRequest(token, requestId, routeKey, fetchPath) {
    return this._isCurrentNilmAmbiguityAuditRequest(token, requestId, routeKey, fetchPath)
      && this._nilmAmbiguityAuditExpanded;
  }

  _nilmAmbiguityAuditGroups(audit = this._nilmAmbiguityAudit()) {
    const groups = new Map();
    for (const group of Array.isArray(audit && audit.group_preview) ? audit.group_preview : []) {
      const groupId = String(group && group.group_id || "").trim();
      if (groupId) groups.set(groupId, group);
    }
    for (const [groupId, group] of this._nilmAmbiguityAuditGroupSummaries?.entries() || []) {
      if (groupId) groups.set(groupId, group);
    }
    return Array.from(groups.values()).sort((left, right) => {
      const countDelta = (Number(right?.occurrence_count) || 0)
        - (Number(left?.occurrence_count) || 0);
      if (countDelta) return countDelta;
      const leftLatest = Date.parse(left?.latest_at || "");
      const rightLatest = Date.parse(right?.latest_at || "");
      const latestDelta = (Number.isFinite(rightLatest) ? rightLatest : 0)
        - (Number.isFinite(leftLatest) ? leftLatest : 0);
      if (latestDelta) return latestDelta;
      return String(left?.group_id || "").localeCompare(String(right?.group_id || ""));
    });
  }

  _nilmAmbiguityAuditGroup(audit, groupId) {
    const id = String(groupId || "").trim();
    return this._nilmAmbiguityAuditGroups(audit).find((group) => (
      String(group && group.group_id || "").trim() === id
    )) || null;
  }

  _nilmAmbiguityAuditGroupItems(groupId) {
    const id = String(groupId || "").trim();
    return (this._nilmAmbiguityAuditItems || []).filter((item) => (
      String(item && item.group_id || "").trim() === id
    ));
  }

  async _toggleNilmAmbiguityAudit() {
    const audit = this._nilmAmbiguityAudit();
    if (!audit) return;
    this._nilmAmbiguityAuditExpanded = !this._nilmAmbiguityAuditExpanded;
    if (!this._nilmAmbiguityAuditExpanded) {
      this._nilmAmbiguityAuditRequestToken += 1;
      this._nilmAmbiguityAuditLoading = false;
      this._nilmAmbiguityAuditExpandedGroups = new Set();
      this._nilmAmbiguityAuditGroupResults = new Map();
      this._nilmAmbiguityAuditGroupSummaries = new Map();
      this._nilmAmbiguityAuditGroupSummariesLoading = false;
      this._nilmAmbiguityAuditGroupSummariesError = "";
      this._nilmAmbiguityAuditGroupSummariesNextCursor = null;
      this._nilmAmbiguityAuditGroupSummariesFetched = false;
      this._render();
      return;
    }
    this._render();
    await this._loadNilmAmbiguityAudit(audit);
  }

  async _loadNilmAmbiguityAudit(audit = this._nilmAmbiguityAudit()) {
    const sourcePath = String(audit && audit.fetch_path || "").trim();
    if (!sourcePath || this._nilmAmbiguityAuditLoading
      || this._nilmAmbiguityAuditFetchedPath === sourcePath) {
      return;
    }
    const token = this._nilmAmbiguityAuditRequestToken + 1;
    this._nilmAmbiguityAuditRequestToken = token;
    const requestId = this._evidenceRequestId;
    const routeKey = this._loadedRouteKey || this._routeKey();
    const { apiPath, fetchPath } = this._nilmAmbiguityAuditRequestPaths(sourcePath);
    this._nilmAmbiguityAuditLoading = true;
    this._nilmAmbiguityAuditError = "";
    this._render();
    try {
      const payload = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentNilmAmbiguityAuditRequest(token, requestId, routeKey, sourcePath)) {
        return;
      }
      this._nilmAmbiguityAuditItems = Array.isArray(payload && payload.items)
        ? payload.items.slice(0, 20)
        : [];
      this._nilmAmbiguityAuditNextCursor = payload && payload.next_cursor || null;
      this._nilmAmbiguityAuditTruncated = Boolean(payload && payload.truncated);
      this._nilmAmbiguityAuditFetchedPath = sourcePath;
      this._nilmAmbiguityAuditError = "";
    } catch (error) {
      if (!this._isCurrentNilmAmbiguityAuditRequest(token, requestId, routeKey, sourcePath)) {
        return;
      }
      this._nilmAmbiguityAuditError = this._panelTextFormat(
        "errors.load_nilm_workspace",
        { message: error.message },
      );
    } finally {
      if (this._isCurrentNilmAmbiguityAuditRequest(token, requestId, routeKey, sourcePath)) {
        this._nilmAmbiguityAuditLoading = false;
        this._render();
      }
    }
  }

  async _toggleNilmAmbiguityGroup(groupId) {
    const id = String(groupId || "").trim();
    if (!id) return;
    const groups = new Set(this._nilmAmbiguityAuditExpandedGroups || []);
    if (groups.has(id)) {
      groups.delete(id);
      const results = new Map(this._nilmAmbiguityAuditGroupResults || []);
      if (results.get(id)?.loading) results.delete(id);
      this._nilmAmbiguityAuditGroupResults = results;
    } else {
      groups.add(id);
    }
    this._nilmAmbiguityAuditExpandedGroups = groups;
    this._render();
    if (!groups.has(id)) return;
    const audit = this._nilmAmbiguityAudit();
    const group = this._nilmAmbiguityAuditGroup(audit, id);
    if (audit && group) await this._loadNilmAmbiguityAuditGroup(audit, group);
  }

  async _loadNilmAmbiguityAuditGroup(audit, group, { append = false } = {}) {
    const sourcePath = String(audit && audit.fetch_path || "").trim();
    const groupId = String(group && group.group_id || "").trim();
    const totalCount = Math.max(0, Number(group && group.occurrence_count) || 0);
    if (!sourcePath || !groupId) return;
    const globalItems = this._nilmAmbiguityAuditGroupItems(groupId);
    const globalFetchCoversGroup = this._nilmAmbiguityAuditFetchedPath === sourcePath
      && globalItems.length >= totalCount;
    const existing = this._nilmAmbiguityAuditGroupResults?.get(groupId);
    const cursor = append ? String(existing?.nextCursor || "").trim() : "";
    if (append) {
      if (!existing?.fetched || existing.loading || !cursor) return;
    } else if (globalFetchCoversGroup || existing?.loading || existing?.fetched) {
      return;
    }

    const token = this._nilmAmbiguityAuditRequestToken;
    const requestId = this._evidenceRequestId;
    const routeKey = this._loadedRouteKey || this._routeKey();
    const { apiPath, fetchPath } = this._nilmAmbiguityAuditRequestPaths(sourcePath, groupId, {
      cursor,
    });
    const results = this._nilmAmbiguityAuditGroupResults || new Map();
    results.set(groupId, {
      items: append ? existing?.items || [] : [],
      loading: true,
      fetched: Boolean(append && existing?.fetched),
      error: "",
      totalCount: Math.max(0, Number(existing?.totalCount) || totalCount),
      truncated: Boolean(append && existing?.truncated),
      nextCursor: append ? cursor : null,
    });
    this._nilmAmbiguityAuditGroupResults = results;
    this._render();
    try {
      const payload = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentNilmAmbiguityAuditGroupRequest(
        token, requestId, routeKey, sourcePath, groupId,
      )) return;
      const pageItems = Array.isArray(payload && payload.items)
        ? payload.items.slice(0, 20)
        : [];
      const itemBySessionId = new Map();
      for (const item of append ? existing?.items || [] : []) {
        const sessionId = String(item && item.session_id || "").trim();
        if (sessionId) itemBySessionId.set(sessionId, item);
      }
      for (const item of pageItems) {
        const sessionId = String(item && item.session_id || "").trim();
        if (sessionId) itemBySessionId.set(sessionId, item);
      }
      results.set(groupId, {
        items: Array.from(itemBySessionId.values()),
        loading: false,
        fetched: true,
        error: "",
        totalCount: Math.max(0, Number(payload && payload.total_count) || totalCount),
        truncated: Boolean(payload && payload.truncated),
        nextCursor: payload && payload.next_cursor || null,
      });
    } catch (error) {
      if (!this._isCurrentNilmAmbiguityAuditGroupRequest(
        token, requestId, routeKey, sourcePath, groupId,
      )) return;
      results.set(groupId, {
        items: append ? existing?.items || [] : [],
        loading: false,
        fetched: Boolean(append && existing?.fetched),
        error: this._panelTextFormat("errors.load_nilm_workspace", { message: error.message }),
        totalCount: Math.max(0, Number(existing?.totalCount) || totalCount),
        truncated: Boolean(append && existing?.truncated),
        nextCursor: append ? cursor : null,
      });
    } finally {
      if (this._isCurrentNilmAmbiguityAuditGroupRequest(
        token, requestId, routeKey, sourcePath, groupId,
      )) this._render();
    }
  }

  async _loadNilmAmbiguityAuditGroupSummaries(
    audit = this._nilmAmbiguityAudit(),
    { append = false } = {},
  ) {
    const sourcePath = String(audit && audit.fetch_path || "").trim();
    const cursor = append ? this._nilmAmbiguityAuditGroupSummariesNextCursor : null;
    if (!sourcePath || this._nilmAmbiguityAuditGroupSummariesLoading
      || (append && !cursor) || (!append && this._nilmAmbiguityAuditGroupSummariesFetched)) {
      return;
    }
    const token = this._nilmAmbiguityAuditRequestToken;
    const requestId = this._evidenceRequestId;
    const routeKey = this._loadedRouteKey || this._routeKey();
    const { apiPath, fetchPath } = this._nilmAmbiguityAuditRequestPaths(sourcePath, "", {
      view: "groups",
      cursor,
    });
    this._nilmAmbiguityAuditGroupSummariesLoading = true;
    this._nilmAmbiguityAuditGroupSummariesError = "";
    this._render();
    try {
      const payload = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentNilmAmbiguityAuditGroupSummariesRequest(
        token, requestId, routeKey, sourcePath,
      )) return;
      const summaries = append
        ? new Map(this._nilmAmbiguityAuditGroupSummaries)
        : new Map();
      for (const group of Array.isArray(payload && payload.groups) ? payload.groups : []) {
        const groupId = String(group && group.group_id || "").trim();
        if (groupId) summaries.set(groupId, group);
      }
      this._nilmAmbiguityAuditGroupSummaries = summaries;
      this._nilmAmbiguityAuditGroupSummariesNextCursor = payload && payload.next_cursor || null;
      this._nilmAmbiguityAuditGroupSummariesFetched = true;
    } catch (error) {
      if (!this._isCurrentNilmAmbiguityAuditGroupSummariesRequest(
        token, requestId, routeKey, sourcePath,
      )) return;
      this._nilmAmbiguityAuditGroupSummariesError = this._panelTextFormat(
        "errors.load_nilm_workspace",
        { message: error.message },
      );
    } finally {
      if (this._isCurrentNilmAmbiguityAuditGroupSummariesRequest(
        token, requestId, routeKey, sourcePath,
      )) {
        this._nilmAmbiguityAuditGroupSummariesLoading = false;
        this._render();
      }
    }
  }

  async _focusNilmAmbiguityOccurrence(item, options = {}) {
    const start = Date.parse(item && item.start || "");
    const end = Date.parse(item && item.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
    this._nilmFocusedAmbiguitySession = { ...item };
    const focused = await this._loadNilmIntervalOnGraph(item, {
      clearSignature: true,
      clearAmbiguity: false,
      edit: false,
      scroll: options.scroll !== false,
    });
    return focused === true;
  }

  async _createNilmAmbiguityManualInterval(item) {
    if (!(await this._focusNilmAmbiguityOccurrence(item))) return false;
    if (!this._setNilmIntervalDraft(item)) return false;
    this._render();
    return true;
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
            this._resetNilmSessionPagination();
            this._resetNilmRouteItemRequest();
            this._nilmWorkspaceHistoryLoading = false;
            this._nilmWorkspaceHistoryError = "";
            this._nilmWorkspaceHistoryFailedRequest = null;
            this._nilmWorkspace = workspace;
            const auditToReload = this._nilmSyncAmbiguityAudit(workspace, { invalidate: true });
            if (auditToReload) await this._loadNilmAmbiguityAudit(auditToReload);
            if (cycle !== this._nilmWorkspaceRefreshCycle
                || !this._isCurrentRequest(requestId, routeKey)) {
              return false;
            }
            if (generation !== cycle.requested) {
              continue;
            }
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

  _nilmSessionAssignmentPersisted(sessionId, assignmentId, onEdgeId = "") {
    const workspace = this._nilmWorkspace || {};
    const sessions = workspace.sessions || [];
    const stableOnEdgeId = String(onEdgeId || "").trim();
    const candidates = stableOnEdgeId
      ? sessions.filter((item) => String(item && item.on_edge_id || "").trim() === stableOnEdgeId)
      : sessions.filter((item) => item && (
        item.session_id === sessionId
        || (
          item._duration_bound_close
          && item._duration_bound_close.session_id === sessionId
        )
      ));
    const persistedCandidates = candidates.filter((session) => {
      const persistedAssignmentId = assignmentId || session.assignment_id;
      const assignment = (workspace.assignments || []).find(
        (item) => item.assignment_id === persistedAssignmentId,
      );
      return persistedAssignmentId && session.assignment_id === persistedAssignmentId
        && assignment && (assignment.session_ids || []).includes(session.session_id);
    });
    return persistedCandidates.length === 1;
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
    const sourceSession = this._nilmDecisionSession(sourceKey);
    const action = sourceSession && actionKey === "assign"
      ? sourceSession.actions && sourceSession.actions.assign
      : signature && signature.actions && signature.actions[actionKey];
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
      const requiresPersistedSessionAssignment = sourceSession && actionKey === "assign";
      if (!requiresPersistedSessionAssignment) {
        if (actionKey === "label" || actionKey === "assign") {
          this._nilmLabelDrafts.delete(this._nilmLabelDraftKey(signature));
        }
        this._nilmDecisionDrafts.delete(this._nilmDecisionDraftKey(signature));
      }
      if (!refreshed) {
        this._setInlineFeedback(
          feedbackScope,
          "error",
          this._panelTextFormat("messages.nilm_interval_action_refresh_failed", { message }),
        );
        return;
      }
      if (requiresPersistedSessionAssignment
        && !this._nilmSessionAssignmentPersisted(
          sourceSession.session_id,
          data.assignment_id,
          data.on_edge_id,
        )) {
        this._setInlineFeedback(
          "nilm-review",
          "error",
          this._panelText("errors.nilm_session_assignment_not_persisted"),
        );
        return;
      }
      if (requiresPersistedSessionAssignment) {
        this._nilmLabelDrafts.delete(this._nilmLabelDraftKey(signature));
        this._nilmDecisionDrafts.delete(this._nilmDecisionDraftKey(signature));
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
      const assigningExisting = Boolean(String(draft.assignment_id || "").trim());
      if (!label || (!applianceProfile && !assigningExisting && !editingExisting && !removedIntervalIds.length)
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
      const sessionDraftKey = collectionKey === "sessions"
        ? this._nilmSessionLabelDraftKey(item)
        : "";
      const labelInput = this.shadowRoot.querySelector(
        collectionKey === "sessions"
          ? `#nilm_session_label_${index}`
          : `#nilm_assignment_label_${index}`,
      );
      const selectedAssignmentId = sessionDraftKey
        && this._nilmSessionAssignmentDrafts.has(sessionDraftKey)
        ? this._nilmSessionAssignmentDrafts.get(sessionDraftKey)
        : null;
      const existingAssignment = this._nilmExistingAssignmentSelection(
        `${collectionKey}_${index}`,
        selectedAssignmentId,
        action.assignment_options,
      );
      const hasSessionLabelDraft = Boolean(
        sessionDraftKey && this._nilmSessionLabelDrafts.has(sessionDraftKey),
      );
      const sessionLabel = hasSessionLabelDraft
        ? this._nilmSessionLabelDrafts.get(sessionDraftKey)
        : "";
      const label = existingAssignment
        ? existingAssignment.label
        : hasSessionLabelDraft
        ? sessionLabel
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
      if (refreshed && collectionKey === "sessions" && actionKey === "assign"
        && !this._nilmSessionAssignmentPersisted(
          item.session_id,
          data.assignment_id,
          data.on_edge_id,
        )) {
        this._setInlineFeedback(
          "nilm-review",
          "error",
          this._panelText("errors.nilm_session_assignment_not_persisted"),
        );
        this._restoreNilmIntervalScroll(scrollTop);
        return;
      }
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
      ["nilmAmbiguityToggle", "[data-nilm-ambiguity-toggle]", "nilmAmbiguityToggle"],
      ["nilmAmbiguityGroup", "[data-nilm-ambiguity-group]", "nilmAmbiguityGroup"],
      ["nilmAmbiguityLoadGroups", "[data-nilm-ambiguity-load-groups]", "nilmAmbiguityLoadGroups"],
      ["nilmAmbiguityLoadOccurrences", "[data-nilm-ambiguity-load-occurrences]", "nilmAmbiguityLoadOccurrences"],
      ["nilmAmbiguityOpenGraph", "[data-nilm-ambiguity-open-graph]", "nilmAmbiguitySessionId"],
      ["nilmAmbiguityOccurrence", "[data-nilm-ambiguity-occurrence]", "nilmAmbiguityOccurrence"],
      ["nilmLoadMoreSessions", "[data-nilm-load-more-sessions]", "nilmLoadMoreSessions"],
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
    const key = input.dataset.nilmSessionLabelKey;
    this._nilmSessionLabelDrafts.set(key, input.value);
    for (const duplicate of this.shadowRoot.querySelectorAll("[data-nilm-session-label-key]")) {
      if (duplicate !== input && duplicate.dataset.nilmSessionLabelKey === key) {
        duplicate.value = input.value;
      }
    }
  }

  _rememberNilmSessionAssignmentDraft(select) {
    if (!select || !select.dataset.nilmSessionAssignmentKey) {
      return;
    }
    const key = select.dataset.nilmSessionAssignmentKey;
    this._nilmSessionAssignmentDrafts.set(key, select.value);
    for (const duplicate of this.shadowRoot.querySelectorAll("[data-nilm-session-assignment-key]")) {
      if (duplicate !== select && duplicate.dataset.nilmSessionAssignmentKey === key) {
        duplicate.value = select.value;
      }
    }
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

  _createNilmChartSelectionBand(chart) {
    const ownerDocument = chart && chart.ownerDocument;
    if (!ownerDocument || !ownerDocument.createElementNS) return null;
    const band = ownerDocument.createElementNS("http://www.w3.org/2000/svg", "rect");
    band.setAttribute("class", "nilm-session-band");
    band.setAttribute("data-nilm-band-kind", "draft");
    band.setAttribute("data-nilm-selected", "true");
    band.setAttribute("data-nilm-provisional-band", "true");
    band.setAttribute("pointer-events", "none");
    chart.appendChild(band);
    return band;
  }

  _updateNilmChartSelectionBand(band, startTime, endTime, chart) {
    if (!band) return;
    const chartStart = Number(chart.dataset.chartStart);
    const chartEnd = Number(chart.dataset.chartEnd);
    const chartLeft = Number(chart.dataset.chartLeft);
    const chartRight = Number(chart.dataset.chartRight);
    const chartTop = Number(chart.dataset.chartTop);
    const chartBottom = Number(chart.dataset.chartBottom);
    if (![chartStart, chartEnd, chartLeft, chartRight, chartTop, chartBottom]
      .every(Number.isFinite)
      || chartEnd <= chartStart
      || chartRight <= chartLeft
      || chartBottom <= chartTop) return;
    const x = (time) => chartLeft + (
      (Math.max(chartStart, Math.min(chartEnd, time)) - chartStart)
      / (chartEnd - chartStart)
    ) * (chartRight - chartLeft);
    const left = Math.min(x(startTime), x(endTime));
    const right = Math.max(x(startTime), x(endTime));
    band.setAttribute("x", left.toFixed(1));
    band.setAttribute("y", String(chartTop));
    band.setAttribute("width", Math.max(1, right - left).toFixed(1));
    band.setAttribute("height", String(chartBottom - chartTop));
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
    const pointerId = event.pointerId;
    const matchingPointer = (pointerEvent) => (
      pointerId === undefined
      || pointerEvent.pointerId === undefined
      || pointerEvent.pointerId === pointerId
    );
    const band = this._createNilmChartSelectionBand(chart);
    let lastTime = startTime;
    let completed = false;
    const update = (moveEvent) => {
      if (completed || !matchingPointer(moveEvent)) return;
      const nextTime = this._snapNilmChartTimeToEdge(
        this._chartEventTime(moveEvent, chart),
        chart,
      );
      if (!Number.isFinite(nextTime)) return;
      lastTime = nextTime;
      this._updateNilmChartSelectionBand(band, startTime, lastTime, chart);
    };
    const cleanup = () => {
      chart.removeEventListener("pointermove", update);
      chart.removeEventListener("pointerup", finish);
      chart.removeEventListener("pointerleave", leave);
      chart.removeEventListener("pointercancel", cancel);
      if (band) band.remove();
    };
    const finalize = () => {
      if (completed) return;
      completed = true;
      cleanup();
      const endTime = lastTime;
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
    const finish = (finishEvent) => {
      if (completed || !matchingPointer(finishEvent)) return;
      update(finishEvent);
      finalize();
    };
    const leave = (leaveEvent) => {
      if (completed || !matchingPointer(leaveEvent)) return;
      update(leaveEvent);
      finalize();
    };
    const cancel = (cancelEvent) => {
      if (completed || !matchingPointer(cancelEvent)) return;
      finalize();
    };
    this._updateNilmChartSelectionBand(band, startTime, startTime, chart);
    chart.addEventListener("pointermove", update);
    chart.addEventListener("pointerup", finish);
    chart.addEventListener("pointerleave", leave);
    chart.addEventListener("pointercancel", cancel);
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
    return this._loadNilmSessionInterval(sessions[index], { edit: true });
  }

  async _loadNilmSessionInterval(session, options = {}) {
    const start = Date.parse(session && session.start || "");
    const end = Date.parse(session && session.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
    const assignment = ((this._nilmWorkspace && this._nilmWorkspace.assignments) || [])
      .find((item) => item.assignment_id === session.assignment_id);
    const edit = options.edit === true;
    const loaded = await this._loadNilmIntervalOnGraph(session, {
      edit,
      assignment,
      clearSignature: true,
      scroll: options.scroll !== false,
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
    const intervals = this._nilmWorkspace?.label_intervals || [];
    const intervalId = String(focused.interval_id || "").trim();
    if (intervalId) {
      return intervals.find((interval) => (
        String(interval.interval_id || "").trim() === intervalId
      )) || null;
    }
    return intervals.find((interval) => (
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
    if (options.clearAmbiguity !== false) {
      this._nilmFocusedAmbiguitySession = null;
    }
    this._nilmGraphWindow = targetWindow;
    const intervalId = String(interval.interval_id || "").trim();
    this._nilmFocusedInterval = {
      start,
      end,
      ...(intervalId ? { interval_id: intervalId } : {}),
    };
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
      const intervalId = String(interval && interval.interval_id || "").trim();
      this._nilmFocusedInterval = {
        start,
        end,
        ...(intervalId ? { interval_id: intervalId } : {}),
      };
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
    const intervalId = String(interval.interval_id || "").trim();
    this._nilmFocusedInterval = {
      ...(field === "start" ? { start: millis, end: other } : { start: other, end: millis }),
      ...(intervalId ? { interval_id: intervalId } : {}),
    };
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
    const fingerprint = String(signatureFingerprint || "").trim();
    if (!fingerprint) return [];
    const workspace = this._nilmWorkspace || {};
    const signature = (workspace.signatures || []).find((item) => {
      const aliases = item && (item.signature_fingerprints || item.signature_ids);
      return [
        item && item.feedback_fingerprint,
        item && item.signature_fingerprint,
        item && item.signature_id,
        ...(Array.isArray(aliases) ? aliases : []),
      ].some((value) => String(value || "").trim() === fingerprint);
    });
    const sessionIds = new Set((signature && signature.session_ids || [])
      .map((value) => String(value || "").trim())
      .filter(Boolean));
    const sessions = (workspace.sessions || []).filter((session) => (
      session.end && !session.ambiguous && (
        session.signature_fingerprint === fingerprint
        || sessionIds.has(String(session.session_id || "").trim())
      )
    ));
    const latest = signature && signature.latest_session;
    const latestStart = Date.parse(latest && latest.start || "");
    const latestEnd = Date.parse(latest && latest.end || "");
    const latestId = String(latest && latest.session_id || "").trim();
    const includesLatest = Boolean(latest) && sessions.some((session) => (
      latestId
        ? String(session.session_id || "").trim() === latestId
        : session.start === latest.start && session.end === latest.end
    ));
    if (latest && !latest.ambiguous && Number.isFinite(latestStart)
      && Number.isFinite(latestEnd) && latestEnd > latestStart && !includesLatest) {
      sessions.push({ ...latest, signature_fingerprint: latest.signature_fingerprint || fingerprint });
    }
    return sessions.sort(
      (left, right) => Date.parse(left.start || "") - Date.parse(right.start || ""),
    );
  }

  _nilmFocusedOccurrence() {
    const sessions = this._nilmSignatureSessions(this._nilmFocusedSignature);
    if (!sessions.length) return null;
    const index = Math.max(0, Math.min(this._nilmFocusedOccurrenceIndex, sessions.length - 1));
    return sessions[index];
  }

  _nilmFocusedGraphEvidence(workspace) {
    const ambiguousOccurrence = this._nilmFocusedAmbiguitySession;
    if (ambiguousOccurrence) {
      return {
        sessions: [{ ...ambiguousOccurrence, selected: true }],
        edges: [
          {
            timestamp: ambiguousOccurrence.start,
            direction: "on",
            delta_w: ambiguousOccurrence.on_delta_w,
            delta_var: ambiguousOccurrence.on_delta_var,
          },
          {
            timestamp: ambiguousOccurrence.end,
            direction: "off",
            delta_w: ambiguousOccurrence.off_delta_w,
            delta_var: ambiguousOccurrence.off_delta_var,
          },
        ],
      };
    }
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
    const confirmedLinks = Array.isArray(assignment.helper_links)
      ? assignment.helper_links.filter(Boolean)
      : [];
    const helperCandidates = Array.isArray(assignment.helper_candidates)
      ? assignment.helper_candidates
      : [];
    const helperOptions = Array.isArray(assignment.helper_options) ? assignment.helper_options : [];
    const selectedIds = new Set((this._nilmSelectedHelpers && this._nilmSelectedHelpers[assignment.assignment_id]) || []);
    const confirmedIds = new Set(confirmedLinks.map((item) => item.helper_circuit_id));
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
    const candidates = helperCandidates
      .map((item, offset) => ({ item, offset }))
      .filter(({ item }) => !confirmedIds.has(item.helper_circuit_id)
        && Number(item.matched_on_count) > 0
        && Number(item.source_on_count) > 0);
    if (!confirmedLinks.length && !candidates.length && !helperOptions.length) {
      return "";
    }
    const helperPromptKey = confirmedIds.size
      ? "nilm_workspace.helper_manual_another"
      : "nilm_workspace.helper_manual";
    const manual = helperOptions.length ? `<div class="nilm-helper-manual">
      <h3>${this._escape(this._panelText(helperPromptKey))}</h3>
      <label for="nilm_helper_option_${index}">${this._escape(this._panelText("nilm_workspace.helper_select"))}</label>
      <select id="nilm_helper_option_${index}" data-nilm-helper-option data-nilm-assignment-index="${index}">
        ${helperOptions.map((item) => `<option value="${this._escape(item.helper_circuit_id || "")}">${this._escape(item.helper_name || item.helper_circuit_id || "")}</option>`).join("")}
      </select>
      <span class="muted">${this._escape(this._panelText("nilm_workspace.helper_relationship_corroborates"))}</span>
      <button type="button" data-nilm-assignment-index="${index}" data-nilm-assignment-action="helper_manual">${this._escape(this._panelText("nilm_workspace.helper_set"))}</button>
    </div>` : "";
    return `<div class="nilm-helper-list" data-nilm-helper-list><h3>${this._escape(this._panelText("nilm_workspace.helper_evidence"))}</h3><p class="muted">${this._escape(this._panelText("nilm_workspace.helper_evidence_description"))}</p>${confirmedLinks.map((item, offset) => renderEvidence(item, offset, true)).join("")}${candidates.map(({ item, offset }) => renderEvidence(item, offset, false)).join("")}${manual}</div>`;
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
        <p class="muted">${this._escape(this._panelText("nilm_workspace.reference_advanced_help"))}</p>
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
    const previous = primary && primary.current_binding;
    const suggestion = primary && primary.suggestion;
    const action = suggestion && suggestion.action;
    if (!this._guardActionCall(action, "NILM configured primary", "nilm-primary")) return;
    const actionContext = this._nilmWorkspaceActionContext();
    this._busyAction = "nilm_primary";
    this._render();
    try {
      await this._hass.callService(action.domain || "circuitsetup_energy_analyzer", action.service, { ...(action.data || {}) });
      await this._refreshNilmWorkspaceData(actionContext.requestId, actionContext.routeKey);
      if (!actionContext.isCurrent()) return;
      if (this._busyAction === "nilm_primary") this._busyAction = "";
      const resulting = this._nilmWorkspace
        && this._nilmWorkspace.configured_primary
        && this._nilmWorkspace.configured_primary.current_binding;
      const persisted = resulting && resulting.signature_id === suggestion.signature_id;
      if (!persisted) {
        const refreshedPrimary = this._nilmWorkspace && this._nilmWorkspace.configured_primary;
        if (refreshedPrimary && !refreshedPrimary.suggestion) refreshedPrimary.suggestion = suggestion;
      }
      this._setInlineFeedback("nilm-primary", persisted ? "success" : "error", persisted
        ? previous
          ? this._panelTextFormat("messages.nilm_primary_signature_changed", {
            previous: previous.display_label || previous.signature_id || "",
            current: resulting.display_label || resulting.signature_id || "",
          })
          : this._panelText("messages.nilm_primary_confirmed")
        : this._panelText("errors.nilm_primary_signature_not_persisted"));
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

  _renderNilmExistingAssignmentField(
    action,
    key,
    selectedAssignmentId = "",
    decisionKey = "",
    sessionAssignmentKey = "",
  ) {
    const options = action && Array.isArray(action.assignment_options)
      ? action.assignment_options
      : [];
    if (!options.length) {
      return "";
    }
    return `
      <label class="nilm-label-field">
        <span class="muted">${this._escape(this._panelText("nilm_workspace.existing_appliance"))}</span>
        <select data-nilm-existing-assignment="${this._escape(key)}" ${decisionKey ? `data-nilm-decision-assignment-key="${this._escape(decisionKey)}"` : ""} ${sessionAssignmentKey ? `data-nilm-session-assignment-key="${this._escape(sessionAssignmentKey)}"` : ""}>
          <option value="">${this._escape(this._panelText("nilm_workspace.new_appliance"))}</option>
          ${options.map((option) => `<option value="${this._escape(option.value || "")}" ${String(option.value || "") === String(selectedAssignmentId || "") ? "selected" : ""}>${this._escape(option.label || option.value || "")}</option>`).join("")}
        </select>
      </label>
    `;
  }

  _nilmExistingAssignmentSelection(key, selectedAssignmentId = null, assignmentOptions = []) {
    const select = this.shadowRoot.querySelector(`[data-nilm-existing-assignment="${key}"]`);
    const assignmentId = String(
      selectedAssignmentId === null ? (select && select.value) || "" : selectedAssignmentId,
    ).trim();
    if (!assignmentId) {
      return null;
    }
    const option = Array.isArray(assignmentOptions)
      ? assignmentOptions.find((item) => String(item && item.value || "") === assignmentId)
      : null;
    const selectedOption = select && select.value === assignmentId
      ? select.selectedOptions && select.selectedOptions[0]
      : null;
    return {
      assignment_id: assignmentId,
      label: String((option && option.label) || (selectedOption && selectedOption.textContent) || assignmentId).trim(),
    };
  }

  _renderNilmWorkspace() {
    return this._renderNilmWorkspaceContent();
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
        ${this._nilmRouteItemError ? `<p class="muted" data-nilm-deep-link-feedback role="status" aria-live="polite">${this._escape(this._nilmRouteItemError)}</p>` : ""}
        ${this._renderNilmWorkspaceSummary(workspace)}
        ${this._renderNilmConfiguredPrimary(workspace)}
        <section class="workspace-section nilm-graph-section section-surface">${this._renderNilmGraph(workspace, graphWindow, graphBands)}</section>
        ${intervalEditor || intervalFeedback ? `<section class="workspace-section nilm-interval-editor-section section-surface">${intervalEditor}${intervalFeedback}</section>` : ""}
        <section class="workspace-section section-surface" data-nilm-review-workspace>
          ${this._nilmActiveLane === "needs_review" ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.workflow_guidance"))}</p>` : ""}
          ${this._renderNilmWorkspaceLanes(workspace)}
          ${this._renderNilmReviewLayout(workspace)}
        </section>
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
        ${sourcePicker}
        <div class="workspace-summary-item" data-nilm-sensitivity>
          <span>${this._escape(this._panelText("nilm_workspace.sensitivity"))}</span>
          <strong>${this._escape(this._friendlyFeature(sensitivity.current || "balanced"))} · ${this._escape(this._formatMetricValue(sensitivity.effective_minimum_edge_w))} W</strong>
          ${sensitivityAction}
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
    const currentLabel = current && (current.display_label || current.signature_id || "");
    const suggestionLabel = suggestion && (suggestion.display_label || suggestion.signature_id || "");
    const suggestionEvidence = this._nilmConfidenceDescriptor(suggestion, "signature");
    return `<section class="workspace-section section-surface" data-nilm-configured-primary>
      <h2>${this._escape(this._panelText("nilm_workspace.configured_primary"))}</h2>
      <strong>${this._escape(primary.display_name || primary.assignment_id || "")}</strong>
      <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.primary_configured", { name: primary.display_name || primary.assignment_id || "" }))}</p>
      <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.primary_evidence", { count: Number(evidence.confirmed_interval_count || 0) }))}</p>
      <p class="muted">${this._escape(signatureText)}</p>
      <p class="muted">${this._escape(attributionText)}</p>
      ${current && suggestion ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.primary_current_signature", { load: currentLabel }))}</p>
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.primary_suggested_signature", { load: suggestionLabel }))}</p>` : ""}
      ${suggestion ? `<div data-nilm-primary-suggestion>
        ${current ? "" : `<p><strong>${this._escape(suggestionLabel)}</strong></p>`}
        ${suggestion.evidence_summary ? `<p class="muted">${this._escape(suggestion.evidence_summary)}</p>` : ""}
        ${suggestionEvidence ? `<p class="muted">${this._escape(suggestionEvidence.text)}</p>` : ""}
        ${suggestion.action ? `<button type="button" data-nilm-primary-confirm ${this._busyAction === "nilm_primary" ? "disabled" : ""}>${this._escape(current
          ? this._panelTextFormat("nilm_workspace.primary_change", { load: suggestionLabel })
          : this._panelText("nilm_workspace.primary_confirm"))}</button>` : ""}
      </div>` : ""}
      ${this._renderInlineFeedback("nilm-primary")}
    </section>`;
  }

  _nilmFiniteNumber(value) {
    if (typeof value !== "number" && (typeof value !== "string" || !value.trim())) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  _nilmFormatQuantity(value, unit) {
    const number = this._nilmFiniteNumber(value);
    return number === null
      ? this._panelText("common.unknown")
      : `${this._formatNumber(number)} ${unit}`;
  }

  _nilmFormatPercent(value) {
    const number = this._nilmFiniteNumber(value);
    if (number === null) return this._panelText("common.unknown");
    const ratio = Math.abs(number) > 1 ? number / 100 : number;
    return new Intl.NumberFormat(undefined, {
      style: "percent",
      maximumFractionDigits: 0,
    }).format(ratio);
  }

  _nilmHasPositiveEvidenceValue(value) {
    const number = this._nilmFiniteNumber(value);
    return number !== null && number > 0;
  }

  _nilmQualityLabelIsGeneric(label) {
    const normalized = String(label || "").trim().toLowerCase();
    const unknown = String(this._panelText("common.unknown") || "unknown").trim().toLowerCase();
    return !normalized || normalized === unknown || normalized.startsWith(`${unknown} `) || normalized.startsWith("unknown load");
  }

  _nilmEstimateQualityRowIsUseful(row, label) {
    if (!row) return false;
    const status = String(row.status || "legacy_unverified").trim().toLowerCase();
    const hasRetainedEvidence = [
      row.runtime_minutes,
      row.energy_kwh,
      row.included_session_count,
      row.power_coverage,
      row.coverage_days,
    ].some((value) => this._nilmHasPositiveEvidenceValue(value));
    if (status === "ambiguous") return hasRetainedEvidence;
    if (status === "legacy_unverified") {
      return hasRetainedEvidence || !this._nilmQualityLabelIsGeneric(label);
    }
    return hasRetainedEvidence || !this._nilmQualityLabelIsGeneric(label);
  }

  _nilmKnownLoadAttributionHasVisibleEvidence(record) {
    if (!record) return false;
    const rejected = Array.isArray(record.rejected_candidate_summaries)
      ? record.rejected_candidate_summaries.filter(Boolean)
      : [];
    const hasWatts = [
      record.aggregate_delta_w,
      record.explained_delta_w,
      record.residual_delta_w,
    ].some((value) => {
      const number = this._nilmFiniteNumber(value);
      return number !== null && Math.abs(number) >= 0.5;
    });
    const hasScore = [
      record.magnitude_score,
      record.time_score,
      record.topology_score,
      record.total_score,
    ].some((value) => this._nilmHasPositiveEvidenceValue(value));
    return hasWatts || rejected.length || hasScore;
  }

  _nilmConfidenceDescriptor(item, kind = "") {
    const record = item && typeof item === "object" ? item : {};
    const requestedKind = String(kind || "").trim().toLowerCase();
    const semanticKind = String(record.confidence_kind || "").trim().toLowerCase();
    const normalizedKind = requestedKind || semanticKind;
    let field = "";
    let labelKey = "";
    const hasEvidenceStrength = this._nilmFiniteNumber(record.evidence_strength) !== null;
    const hasPairingConfidence = this._nilmFiniteNumber(record.pairing_confidence) !== null;
    if (semanticKind === "evidence_strength" || (requestedKind === "signature" && hasEvidenceStrength)) {
      field = "evidence_strength";
      labelKey = "evidence_strength";
    } else if (semanticKind === "pairing_confidence" || (requestedKind === "session" && hasPairingConfidence)) {
      field = "pairing_confidence";
      labelKey = "pairing_confidence";
    } else if (normalizedKind === "assignment" || normalizedKind === "virtual") {
      if (semanticKind === "model_fit" && this._nilmFiniteNumber(record.model_fit ?? record.model_confidence) !== null) {
        field = this._nilmFiniteNumber(record.model_fit) !== null ? "model_fit" : "model_confidence";
        labelKey = "model_fit";
      } else if (this._nilmFiniteNumber(record.feedback_evidence_score) !== null) {
        field = "feedback_evidence_score";
        labelKey = "feedback_evidence_score";
      }
    }
    if (!field || !labelKey) return null;
    const rawValue = this._nilmFiniteNumber(record[field]);
    if (rawValue === null) return null;
    const value = Math.max(0, Math.min(1, rawValue));
    const percent = Math.round(value * 100);
    return {
      field,
      labelKey,
      value,
      percent,
      text: this._panelTextFormat(`nilm_workspace.${labelKey}`, {
        value: this._nilmFormatPercent(value),
      }),
    };
  }

  _nilmSignedWatts(value) {
    const number = this._nilmFiniteNumber(value);
    if (number === null) return this._panelText("common.unknown");
    const sign = number > 0 ? "+" : number < 0 ? "−" : "";
    return `${sign}${this._formatNumber(Math.abs(number))} W`;
  }

  _nilmEstimateStatus(status) {
    const key = String(status || "legacy_unverified").trim().toLowerCase();
    const labels = {
      complete: "quality_complete",
      partial_history: "quality_partial_history",
      ambiguous: "quality_ambiguous",
      legacy_unverified: "quality_legacy_estimate",
    };
    return this._panelText(`nilm_workspace.${labels[key] || labels.legacy_unverified}`);
  }

  _nilmQualityWindowLabel(window) {
    const key = String(window || "").trim().toLowerCase();
    const labels = {
      today: "quality_window_today",
      "7_days": "quality_window_7d",
      "7d": "quality_window_7d",
      "30_days": "quality_window_30d",
      "30d": "quality_window_30d",
    };
    return this._panelText(`nilm_workspace.${labels[key] || "quality_window_unknown"}`);
  }

  _nilmEnergySourceLabel(source) {
    const key = String(source || "").trim().toLowerCase();
    const labels = {
      measured: "energy_source_measured",
      partial: "energy_source_partial",
      fallback: "energy_source_fallback",
      estimated: "energy_source_estimated",
      transition_fallback: "energy_source_fallback",
      residual_trace_measured: "energy_source_measured",
      residual_trace_partial: "energy_source_partial",
      derived_from_power: "energy_source_derived_from_power",
      unavailable: "energy_source_unavailable",
    };
    return key
      ? this._panelText(`nilm_workspace.${labels[key] || "energy_source_unknown"}`)
      : this._panelText("common.unknown");
  }

  _nilmSelectionMethodLabel(value) {
    const key = String(value || "unattributed").trim().toLowerCase();
    const labels = {
      global_assignment: "attribution_selection_global",
      compound: "attribution_selection_compound",
      greedy: "attribution_selection_greedy",
      topology_rejected: "attribution_selection_topology_rejected",
      unattributed: "attribution_selection_unattributed",
    };
    return this._panelText(`nilm_workspace.${labels[key] || "attribution_selection_unattributed"}`);
  }

  _nilmTopologyLabel(value) {
    const key = String(value || "not_evaluated").trim().toLowerCase();
    const labels = {
      consistent: "attribution_topology_consistent",
      unknown_topology: "attribution_topology_unknown",
      not_evaluated: "attribution_topology_not_evaluated",
      not_attributed: "attribution_topology_not_attributed",
      topology_mismatch: "attribution_topology_mismatch",
      leg_mismatch: "attribution_topology_leg_mismatch",
      compound_unknown_topology: "attribution_topology_unknown",
      rejected: "attribution_topology_rejected",
      rejected_topology: "attribution_topology_rejected",
    };
    return this._panelText(`nilm_workspace.${labels[key] || "attribution_topology_not_evaluated"}`);
  }

  _renderNilmEstimateQualityRow(row) {
    const status = String(row && row.status || "legacy_unverified").trim().toLowerCase();
    const coverage = this._nilmFormatPercent(row && row.power_coverage);
    const runtime = this._nilmFormatQuantity(row && row.runtime_minutes, "min");
    const energy = this._nilmFormatQuantity(row && row.energy_kwh, "kWh");
    const sessions = this._nilmFiniteNumber(row && row.included_session_count);
    const excluded = this._nilmFiniteNumber(row && row.excluded_session_count);
    const requestedRange = [row && row.requested_start, row && row.requested_end]
      .filter(Boolean)
      .map((value) => this._formatDateTime(value))
      .join(" – ");
    const coverageRange = [row && row.coverage_start, row && row.coverage_end]
      .filter(Boolean)
      .map((value) => this._formatDateTime(value))
      .join(" – ");
    const source = this._nilmEnergySourceLabel(row && row.energy_source);
    const quality = this._nilmFiniteNumber(row && row.energy_quality);
    const sourceDetail = quality === null
      ? source
      : `${source} · ${this._panelTextFormat("nilm_workspace.energy_estimate_quality", { value: this._nilmFormatPercent(quality) })}`;
    const duration = this._nilmFiniteNumber(row && row.coverage_days);
    const longestGap = this._nilmFiniteNumber(row && row.longest_trace_gap_seconds);
    return `<article class="nilm-estimate-quality-row" data-nilm-estimate-quality-window="${this._escape(String(row && row.window || ""))}">
      <div class="nilm-estimate-quality-heading">
        <strong>${this._escape(this._nilmQualityWindowLabel(row && row.window))}</strong>
        <span class="nilm-quality-chip nilm-quality-${this._escape(status)}">${this._escape(this._nilmEstimateStatus(status))}</span>
      </div>
      <dl class="nilm-evidence-facts">
        <div><dt>${this._escape(this._panelText("nilm_workspace.quality_runtime"))}</dt><dd>${this._escape(runtime)}</dd></div>
        <div><dt>${this._escape(this._panelText("nilm_workspace.quality_energy"))}</dt><dd>${this._escape(energy)}</dd></div>
        <div><dt>${this._escape(this._panelText("nilm_workspace.quality_sessions"))}</dt><dd>${this._escape(sessions === null ? this._panelText("common.unknown") : this._formatNumber(sessions))}</dd></div>
        <div><dt>${this._escape(this._panelText("nilm_workspace.quality_power_coverage"))}</dt><dd>${this._escape(coverage)}</dd></div>
      </dl>
      <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.quality_energy_source", { source: sourceDetail }))}</p>
      <details>
        <summary>${this._escape(this._panelText("nilm_workspace.quality_details"))}</summary>
        <dl class="nilm-evidence-facts nilm-evidence-details-list">
          <div><dt>${this._escape(this._panelText("nilm_workspace.quality_observation_start"))}</dt><dd>${this._escape(this._formatDateTime(row && row.observation_started_at))}</dd></div>
          <div><dt>${this._escape(this._panelText("nilm_workspace.quality_requested_range"))}</dt><dd>${this._escape(requestedRange || this._panelText("common.unknown"))}</dd></div>
          <div><dt>${this._escape(this._panelText("nilm_workspace.quality_actual_coverage_range"))}</dt><dd>${this._escape(coverageRange || this._panelText("common.unknown"))}</dd></div>
          <div><dt>${this._escape(this._panelText("nilm_workspace.quality_covered_duration"))}</dt><dd>${this._escape(duration === null ? this._panelText("common.unknown") : this._nilmFormatQuantity(duration, this._panelText("nilm_workspace.quality_days_unit")))}</dd></div>
          <div><dt>${this._escape(this._panelText("nilm_workspace.quality_excluded_evidence"))}</dt><dd>${this._escape(excluded === null ? this._panelText("common.unknown") : this._formatNumber(excluded))}</dd></div>
          <div><dt>${this._escape(this._panelText("nilm_workspace.quality_longest_gap"))}</dt><dd>${this._escape(longestGap === null ? this._panelText("common.unknown") : this._nilmFormatQuantity(longestGap, "s"))}</dd></div>
        </dl>
        <p class="muted">${this._escape(this._panelText(row && row.retention_truncated ? "nilm_workspace.quality_retention_truncated" : "nilm_workspace.quality_retention_complete"))}</p>
      </details>
    </article>`;
  }

  _renderNilmKnownLoadAttribution(record) {
    const knownLoads = Array.isArray(record && record.known_load_labels)
      ? record.known_load_labels.filter(Boolean).slice(0, 8)
      : Array.isArray(record && record.known_circuit_ids)
        ? record.known_circuit_ids.filter(Boolean).slice(0, 8)
        : [];
    const offsets = Array.isArray(record && record.time_offsets_s)
      ? record.time_offsets_s.map((value) => this._nilmFormatQuantity(value, "s")).join(", ")
      : "";
    const topology = Array.isArray(record && record.topology_statuses)
      ? record.topology_statuses.filter(Boolean).map((value) => this._nilmTopologyLabel(value)).join(", ")
      : "";
    const rejected = Array.isArray(record && record.rejected_candidate_summaries)
      ? record.rejected_candidate_summaries.slice(0, 4)
      : [];
    const scoreRows = [
      ["attribution_magnitude_score", record && record.magnitude_score],
      ["attribution_time_score", record && record.time_score],
      ["attribution_topology_score", record && record.topology_score],
      ["attribution_total_score", record && record.total_score],
    ].filter(([, value]) => this._nilmFiniteNumber(value) !== null);
    return `<article class="nilm-known-load-attribution" data-nilm-known-load-attribution="${this._escape(String(record && record.attribution_id || ""))}">
      <h4>${this._escape(this._formatDateTime(record && record.timestamp))}</h4>
      <dl class="nilm-evidence-facts">
        <div><dt>${this._escape(this._panelText("nilm_workspace.attribution_aggregate_change"))}</dt><dd>${this._escape(this._nilmSignedWatts(record && record.aggregate_delta_w))}</dd></div>
        <div><dt>${this._escape(this._panelText("nilm_workspace.attribution_known_explanation"))}</dt><dd>${this._escape(`${this._nilmSignedWatts(record && record.explained_delta_w)} — ${knownLoads.join(" · ") || this._panelText("nilm_workspace.attribution_no_known_explanation")}`)}</dd></div>
        <div><dt>${this._escape(this._panelText("nilm_workspace.attribution_residual"))}</dt><dd>${this._escape(this._nilmSignedWatts(record && record.residual_delta_w))}</dd></div>
        <div><dt>${this._escape(this._panelText("nilm_workspace.attribution_selection"))}</dt><dd>${this._escape(this._nilmSelectionMethodLabel(record && record.selection_method))}</dd></div>
      </dl>
      <p class="muted nilm-conservation-check" data-nilm-conservation-check>${this._escape(this._panelTextFormat("nilm_workspace.attribution_conservation", {
        aggregate: this._nilmSignedWatts(record && record.aggregate_delta_w),
        explained: this._nilmSignedWatts(record && record.explained_delta_w),
        residual: this._nilmSignedWatts(record && record.residual_delta_w),
      }))}</p>
      <details>
        <summary>${this._escape(this._panelText("nilm_workspace.attribution_details"))}</summary>
        ${offsets ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.attribution_time_offset", { offsets }))}</p>` : ""}
        ${topology ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.attribution_topology", { topology }))}</p>` : ""}
        ${record && record.compound ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.attribution_compound"))}</p>` : ""}
        ${scoreRows.length ? `<dl class="nilm-evidence-facts nilm-evidence-details-list">${scoreRows.map(([label, value]) => `<div><dt>${this._escape(this._panelText(`nilm_workspace.${label}`))}</dt><dd>${this._escape(this._formatNumber(value))}</dd></div>`).join("")}</dl>` : ""}
        ${rejected.length ? `<ul class="nilm-rejected-candidates">${rejected.map((candidate) => `<li>${this._escape(this._panelTextFormat("nilm_workspace.attribution_rejected_candidate", {
          candidate: candidate.known_circuit_id || this._panelText("common.unknown"),
          reason: this._nilmTopologyLabel(candidate.topology_status || candidate.selection_status),
        }))}</li>`).join("")}</ul>` : ""}
      </details>
    </article>`;
  }

  _renderNilmEvidenceDetails(workspace) {
    const quality = (Array.isArray(workspace && workspace.signatures) ? workspace.signatures : [])
      .map((signature) => ({
        label: signature.display_label || signature.signature_id || this._panelText("common.unknown"),
        rows: Array.isArray(signature.estimate_quality) ? signature.estimate_quality
          .filter((row) => this._nilmEstimateQualityRowIsUseful(row, signature.display_label || signature.signature_id))
          .slice(0, 3) : [],
      }))
      .filter((item) => item.rows.length)
      .slice(0, 20);
    const attributions = (Array.isArray(workspace && workspace.known_load_attributions)
      ? workspace.known_load_attributions
      : [])
      .filter((record) => this._nilmKnownLoadAttributionHasVisibleEvidence(record))
      .slice(0, 20);
    if (!quality.length && !attributions.length) return "";
    return `<section class="workspace-section section-surface nilm-evidence-section" data-nilm-evidence-section>
      <details class="nilm-evidence-details" data-nilm-evidence-details>
        <summary>${this._escape(this._panelText("nilm_workspace.evidence_quality_title"))}</summary>
        <p class="muted">${this._escape(this._panelText("nilm_workspace.evidence_quality_summary"))}</p>
        ${quality.map((item) => `<section class="nilm-estimate-quality" data-nilm-estimate-quality>
          <h3>${this._escape(this._panelTextFormat("nilm_workspace.quality_for", { name: item.label }))}</h3>
          <div class="nilm-estimate-quality-rows">${item.rows.map((row) => this._renderNilmEstimateQualityRow(row)).join("")}</div>
        </section>`).join("")}
        ${attributions.length ? `<section class="nilm-known-load-attributions" data-nilm-known-load-attributions>
          <h3>${this._escape(this._panelText("nilm_workspace.attribution_title"))}</h3>
          ${attributions.map((record) => this._renderNilmKnownLoadAttribution(record)).join("")}
        </section>` : ""}
      </details>
    </section>`;
  }

  async _applyNilmSensitivity() {
    const action = this._nilmWorkspace && this._nilmWorkspace.sensitivity && this._nilmWorkspace.sensitivity.action;
    if (!this._guardActionCall(action, "NILM detection sensitivity", "nilm-sensitivity")) return;
    await this._hass.callService(action.domain || "circuitsetup_energy_analyzer", action.service, { ...(action.data || {}) });
    await this._refreshNilmWorkspaceData();
    this._render();
  }

  _renderNilmGraph(workspace, graphWindow, graphBands) {
    const series = this._visibleNilmWorkspaceSeries(workspace, graphWindow);
    const graphEdges = this._nilmFocusedGraphEvidence(workspace).edges;
    const hasGraph = Boolean(graphWindow && series.length);
    const focusedInterval = this._nilmFocusedLabelInterval();
    const graph = this._nilmWorkspaceHistoryLoading
      ? `<div class="loading-skeleton graph-loading-skeleton" data-loading-skeleton role="status" aria-label="${this._escape(this._panelText("chart.loading_history"))}"></div>`
      : this._nilmWorkspaceHistoryError
        ? `<div data-nilm-history-error><p class="muted">${this._escape(this._nilmWorkspaceHistoryError)}</p><button type="button" class="secondary" data-retry-nilm-history>${this._escape(this._panelText("common.retry"))}</button></div>`
        : hasGraph
          ? this._chartSvg(series, { graph_window_start: new Date(graphWindow.start).toISOString(), graph_window_end: new Date(graphWindow.end).toISOString(), y_axis_label: "W", nilm_select_interval: this._nilmIntervalEditorOpen, nilm_edges: graphEdges, nilm_sessions: graphBands })
          : `<p class="muted">${this._escape((workspace.history && workspace.history.missing_real_power_reason) || this._panelText("nilm_workspace.no_graph_history"))}</p>`;
    const canEditFocusedInterval = hasGraph && focusedInterval;
    const intervalAction = !this._nilmIntervalEditorOpen && !this._nilmWorkspaceHistoryError
      ? `<div class="actions"><button type="button" class="secondary" ${canEditFocusedInterval ? "data-nilm-edit-focused-interval" : "data-nilm-open-interval-editor"}>${this._escape(this._panelText(canEditFocusedInterval ? "nilm_workspace.edit_interval" : "nilm_workspace.label_interval"))}</button></div>`
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
    const focusedIntervalId = String(focused && focused.interval_id || "").trim();
    const focusedBands = [...sessionBands, ...labelBands].map((item) => ({
      ...item,
      selected: focused
        ? focusedIntervalId
          ? String(item.interval_id || "").trim() === focusedIntervalId
          : Date.parse(item.start || "") === focused.start
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
      return this._loadNilmSessionInterval(
        reviewItem.item,
        { scroll: options.scroll !== false },
      );
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

  _renderNilmAmbiguityAudit(workspace) {
    const audit = this._nilmAmbiguityAudit(workspace);
    if (!audit) return "";
    const totalCount = Math.max(0, Number(audit.total_count) || 0);
    const expanded = Boolean(this._nilmAmbiguityAuditExpanded);
    const contentId = "nilm_ambiguity_audit_content";
    const groupResults = this._nilmAmbiguityAuditGroupResults?.values() || [];
    const groupLoading = Array.from(groupResults).some((result) => result?.loading);
    const groupError = Array.from(this._nilmAmbiguityAuditGroupResults?.values() || [])
      .some((result) => result?.error);
    const groupSummariesLoading = Boolean(this._nilmAmbiguityAuditGroupSummariesLoading);
    const groupSummariesError = Boolean(this._nilmAmbiguityAuditGroupSummariesError);
    const status = this._nilmAmbiguityAuditLoading
      ? this._panelText("nilm_workspace.ambiguity_audit_loading")
      : this._nilmAmbiguityAuditError
        ? this._panelText("nilm_workspace.ambiguity_audit_load_failed")
        : groupLoading
          ? this._panelText("nilm_workspace.ambiguity_audit_loading")
          : groupError
            ? this._panelText("nilm_workspace.ambiguity_audit_load_failed")
            : groupSummariesLoading
              ? this._panelText("nilm_workspace.ambiguity_audit_loading")
              : groupSummariesError
                ? this._panelText("nilm_workspace.ambiguity_audit_load_failed")
                : expanded && this._nilmAmbiguityAuditFetchedPath === audit.fetch_path
                  ? this._panelText("nilm_workspace.ambiguity_audit_loaded")
                  : "";
    const groups = this._nilmAmbiguityAuditGroups(audit);
    return `<section class="workspace-section section-surface nilm-ambiguity-audit" data-nilm-ambiguity-audit>
      <details class="nilm-evidence-details nilm-ambiguity-details" data-nilm-ambiguity-details ${expanded ? "open" : ""}>
      <summary data-nilm-ambiguity-toggle="audit" aria-expanded="${expanded}" aria-controls="${contentId}" aria-describedby="nilm_ambiguity_audit_summary nilm_ambiguity_audit_no_action">${this._escape(this._panelText("nilm_workspace.ambiguity_audit_title"))}</summary>
      <p id="nilm_ambiguity_audit_summary"><strong>${this._escape(this._panelTextFormat("nilm_workspace.ambiguity_audit_summary", { count: totalCount }))}</strong></p>
      <p class="muted" data-nilm-ambiguity-no-action>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_no_action"))}</p>
      <p id="nilm_ambiguity_audit_no_action" class="sr-only">${this._escape(this._panelText("nilm_workspace.ambiguity_audit_no_action"))}</p>
      <p data-nilm-ambiguity-live aria-live="polite" aria-atomic="true" class="sr-only">${this._escape(status)}</p>
      <div id="${contentId}" data-nilm-ambiguity-content role="region" aria-label="${this._escape(this._panelText("nilm_workspace.ambiguity_audit_title"))}" ${expanded ? "" : "hidden"}>
        ${this._renderNilmAmbiguityAuditContent(groups, audit)}
      </div>
      </details>
    </section>`;
  }

  _renderNilmAmbiguityAuditContent(groups, audit) {
    if (this._nilmAmbiguityAuditLoading) {
      return `<p class="muted" data-nilm-ambiguity-loading>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_loading"))}</p>`;
    }
    if (this._nilmAmbiguityAuditError) {
      return `<p class="muted" data-nilm-ambiguity-error>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_load_failed"))}</p>`;
    }
    if (!groups.length) {
      return "";
    }
    const fetched = this._nilmAmbiguityAuditFetchedPath === this._nilmAmbiguityAudit()?.fetch_path;
    const more = this._nilmAmbiguityAuditTruncated
      ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.ambiguity_audit_bounded"))}</p>`
      : "";
    const totalGroups = Math.max(0, Number(audit && audit.group_count) || 0);
    const appendGroups = Boolean(this._nilmAmbiguityAuditGroupSummariesNextCursor);
    const canLoadMoreGroups = appendGroups
      || totalGroups > groups.length;
    const groupSummaryControl = canLoadMoreGroups
      ? `<button type="button" class="secondary" data-nilm-ambiguity-load-groups data-nilm-ambiguity-append="${appendGroups}" ${this._nilmAmbiguityAuditGroupSummariesLoading ? "disabled" : ""}>
          ${this._escape(this._panelTextFormat(
            appendGroups
              ? "nilm_workspace.ambiguity_audit_load_more_groups"
              : "nilm_workspace.ambiguity_audit_view_all_groups",
            { count: totalGroups },
          ))}
        </button>`
      : "";
    const groupSummaryError = this._nilmAmbiguityAuditGroupSummariesError
      ? `<p class="muted" data-nilm-ambiguity-groups-error>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_load_failed"))}</p>`
      : "";
    return `<div class="nilm-ambiguity-groups" data-nilm-ambiguity-groups>
      ${groups.map((group) => this._renderNilmAmbiguityAuditGroup(group, fetched)).join("")}
      ${more}
      ${groupSummaryError}
      ${groupSummaryControl}
    </div>`;
  }

  _renderNilmAmbiguityAuditGroup(group, fetched) {
    const groupId = String(group && group.group_id || "").trim();
    if (!groupId) return "";
    const expanded = Boolean(this._nilmAmbiguityAuditExpandedGroups?.has(groupId));
    const occurrenceId = `nilm_ambiguity_group_${this._escape(groupId)}`;
    const count = Math.max(0, Number(group.occurrence_count) || 0);
    const labels = Array.isArray(group.candidate_labels)
      ? group.candidate_labels.filter(Boolean).slice(0, 3)
      : [];
    const candidateText = labels.length
      ? labels.join(" · ")
      : this._friendlyFeature(group.category || "other");
    const globalItems = fetched ? this._nilmAmbiguityAuditGroupItems(groupId) : [];
    const groupResult = this._nilmAmbiguityAuditGroupResults?.get(groupId);
    const globalFetchCoversGroup = fetched && globalItems.length >= count;
    const groupLoaded = Boolean(groupResult?.fetched || globalFetchCoversGroup);
    const items = groupResult?.fetched ? groupResult.items : globalItems;
    return `<section class="nilm-ambiguity-group" data-nilm-ambiguity-group-card="${this._escape(groupId)}">
      <button type="button" class="secondary nilm-ambiguity-group-toggle" data-nilm-ambiguity-group="${this._escape(groupId)}" aria-expanded="${expanded}" aria-controls="${occurrenceId}">
        <span><strong>${this._escape(candidateText)}</strong></span>
        <span>${this._escape(this._panelTextFormat("nilm_workspace.ambiguity_audit_occurrences", { count }))}</span>
      </button>
      <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.ambiguity_audit_latest", { latest: this._formatDateTime(group.latest_at) }))}</p>
      <div id="${occurrenceId}" data-nilm-ambiguity-occurrences="${this._escape(groupId)}" ${expanded ? "" : "hidden"}>
        ${expanded ? this._renderNilmAmbiguityOccurrences(items, count, {
          loaded: groupLoaded,
          loading: Boolean(groupResult?.loading),
          error: groupResult?.error || "",
          nextCursor: groupResult?.nextCursor || null,
          groupId,
        }) : ""}
      </div>
    </section>`;
  }

  _renderNilmAmbiguityOccurrences(items, totalCount, state = {}) {
    if (state.loading && !items.length) {
      return `<p class="muted" data-nilm-ambiguity-group-loading>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_loading"))}</p>`;
    }
    if (state.error && !items.length) {
      return `<p class="muted" data-nilm-ambiguity-group-error>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_load_failed"))}</p>`;
    }
    if (!state.loaded) {
      return `<p class="muted" data-nilm-ambiguity-group-loading>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_loading"))}</p>`;
    }
    if (!items.length) {
      return `<p class="muted">${this._escape(this._panelText("nilm_workspace.ambiguity_audit_no_loaded_occurrences"))}</p>`;
    }
    const shown = Math.min(items.length, totalCount);
    const more = totalCount > shown
      ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.ambiguity_audit_showing_occurrences", { shown, total: totalCount }))}</p>`
      : "";
    const loading = state.loading
      ? `<p class="muted" data-nilm-ambiguity-group-loading>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_loading"))}</p>`
      : "";
    const error = state.error
      ? `<p class="muted" data-nilm-ambiguity-group-error>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_load_failed"))}</p>`
      : "";
    const groupId = String(state.groupId || "").trim();
    const loadMore = state.nextCursor && groupId
      ? `<button type="button" class="secondary" data-nilm-ambiguity-load-occurrences="${this._escape(groupId)}" ${state.loading ? "disabled" : ""}>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_load_more_occurrences"))}</button>`
      : "";
    return `<div class="nilm-ambiguity-occurrence-list">
      ${items.map((item) => this._renderNilmAmbiguityOccurrence(item)).join("")}
      ${more}
      ${loading}
      ${error}
      ${loadMore}
    </div>`;
  }

  _renderNilmAmbiguityOccurrence(item) {
    const sessionId = String(item && item.session_id || "").trim();
    if (!sessionId) return "";
    const selected = String(this._nilmFocusedAmbiguitySession?.session_id || "") === sessionId;
    const safeActions = new Set(Array.isArray(item.safe_actions) ? item.safe_actions : []);
    const candidates = Array.isArray(item.candidate_explanations)
      ? item.candidate_explanations.slice(0, 3)
      : [];
    const likelyCandidates = candidates.slice(0, 2)
      .map((candidate) => candidate.display_label || candidate.assignment_id || candidate.signature_fingerprint)
      .filter(Boolean);
    const reasonCodes = Array.isArray(item.ambiguity_reason_codes)
      ? item.ambiguity_reason_codes.filter(Boolean).slice(0, 3)
      : [];
    const facts = [
      this._formatDateTime(item.start),
      item.duration_seconds !== undefined && item.duration_seconds !== null
        ? this._nilmSessionDuration(item)
        : "",
      item.median_power_w !== undefined && item.median_power_w !== null
        ? `${this._formatMetricValue(item.median_power_w)} W`
        : "",
    ].filter(Boolean);
    return `<article class="nilm-ambiguity-occurrence" data-nilm-ambiguity-occurrence="${this._escape(sessionId)}" data-nilm-selected="${selected}">
      <strong>${this._escape(facts.join(" · "))}</strong>
      ${likelyCandidates.length ? `<p class="muted">${this._escape(likelyCandidates.join(" · "))}</p>` : ""}
      <p class="muted">${this._escape(this._friendlyFeature(item.ambiguity_category || "other"))}</p>
      <div class="actions">
        ${safeActions.has("open_on_graph") ? `<button type="button" class="secondary" data-nilm-ambiguity-open-graph data-nilm-ambiguity-session-id="${this._escape(sessionId)}">${this._escape(this._panelText("nilm_workspace.ambiguity_audit_open_graph"))}</button>` : ""}
        ${safeActions.has("create_manual_interval") ? `<button type="button" data-nilm-ambiguity-create-interval data-nilm-ambiguity-session-id="${this._escape(sessionId)}">${this._escape(this._panelText("nilm_workspace.ambiguity_audit_create_interval"))}</button>` : ""}
      </div>
      <details>
        <summary>${this._escape(this._panelText("nilm_workspace.ambiguity_audit_advanced"))}</summary>
        ${reasonCodes.length ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.ambiguity_audit_reason_codes", { codes: reasonCodes.join(", ") }))}</p>` : ""}
        ${candidates.length ? `<ul>${candidates.map((candidate) => `<li>${this._escape(this._nilmAmbiguityCandidateDetail(candidate))}</li>`).join("")}</ul>` : ""}
      </details>
    </article>`;
  }

  _nilmAmbiguityCandidateDetail(candidate) {
    const label = candidate.display_label || candidate.assignment_id || candidate.signature_fingerprint || candidate.candidate_id || "";
    const margin = Number(candidate.score_margin_from_best);
    return Number.isFinite(margin)
      ? this._panelTextFormat("nilm_workspace.ambiguity_audit_candidate_margin", {
        candidate: label,
        margin: this._formatMetricValue(margin),
      })
      : String(label);
  }

  _nilmAmbiguityAuditItem(sessionId) {
    const id = String(sessionId || "").trim();
    const globalItem = (this._nilmAmbiguityAuditItems || []).find((item) => (
      String(item && item.session_id || "").trim() === id
    ));
    if (globalItem) return globalItem;
    for (const result of this._nilmAmbiguityAuditGroupResults?.values() || []) {
      const item = (result?.items || []).find((candidate) => (
        String(candidate && candidate.session_id || "").trim() === id
      ));
      if (item) return item;
    }
    return null;
  }

  _renderNilmSessionPagination(workspace, visibleSessionCount = null) {
    const meta = this._nilmSessionCollectionMeta(workspace);
    const loaded = Array.isArray(workspace && workspace.sessions)
      ? workspace.sessions.length
      : 0;
    const visible = Number.isFinite(Number(visibleSessionCount))
      ? Math.max(0, Number(visibleSessionCount))
      : loaded;
    if (!meta.totalCount && !meta.nextCursor) return "";
    const hiddenLoaded = Math.max(0, loaded - visible);
    const visibleTotal = Math.max(visible, meta.totalCount - hiddenLoaded);
    const summary = this._panelTextFormat("nilm_workspace.sessions_showing", {
      shown: Math.min(visible, visibleTotal),
      total: visibleTotal,
    });
    const loadMore = meta.nextCursor
      ? `<button type="button" class="secondary" data-nilm-load-more-sessions ${this._nilmSessionPageLoading ? "disabled" : ""}>${this._escape(this._panelText("nilm_workspace.sessions_load_more"))}</button>`
      : "";
    return `<div class="nilm-session-pagination" data-nilm-session-pagination>
      <p class="muted" data-nilm-session-page-status>${this._escape(summary)}</p>
      <p class="sr-only" data-nilm-session-page-live aria-live="polite" aria-atomic="true">${this._escape(this._nilmSessionPageLiveMessage || this._nilmSessionPageError || "")}</p>
      ${this._nilmSessionPageError ? `<p class="muted" data-nilm-session-page-error>${this._escape(this._nilmSessionPageError)}</p>` : ""}
      ${loadMore}
    </div>`;
  }

  _renderNilmSecondaryCollections(workspace) {
    const needsReviewSessionIds = new Set(
      (Array.isArray(workspace?.lanes?.needs_review?.session_ids)
        ? workspace.lanes.needs_review.session_ids
        : [])
        .map((sessionId) => String(sessionId || "").trim())
        .filter(Boolean),
    );
    const unassignedSessions = (Array.isArray(workspace.sessions) ? workspace.sessions : [])
      .map((item, index) => ({ ...item, workspace_index: index }))
      .filter((item) => (
        !String(item && item.assignment_id || "").trim()
        && !needsReviewSessionIds.has(String(item && item.session_id || "").trim())
      ));
    const showDominantLeg = workspace.source && workspace.source.source_kind === "mains";
    const routeTarget = this._nilmRouteItemTarget(this._loadedRouteKey || this._routeKey());
    const hasSecondaryDetailsError = Boolean(
      this._nilmSessionPageError
      || this._nilmAmbiguityAuditError
      || this._nilmAmbiguityAuditGroupSummariesError
      || Array.from(this._nilmAmbiguityAuditGroupResults?.values() || []).some((result) => result?.error),
    );
    const shouldOpen = this._nilmSecondaryDetailsOpen
      || ["ambiguous_session", "known_load_attribution"].includes(routeTarget?.kind)
      || hasSecondaryDetailsError;
    const secondaryDetailsLabel = this._escape(this._panelText("nilm_workspace.secondary_details"));
    return `<details class="workspace-section section-surface" data-nilm-secondary-collections ${shouldOpen ? "open" : ""}>
      <summary>${secondaryDetailsLabel}</summary>
      <div class="nilm-secondary-collections-content">
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
        ${this._renderNilmWorkspaceList(this._panelText("nilm_workspace.sessions_title"), unassignedSessions, this._panelText("nilm_workspace.sessions_empty"), (item, index) => {
          const label = item.display_label || item.display_name || item.appliance_id || item.assignment_id || this._panelText("common.appliance");
          const isOpen = !item.end;
          const pairing = this._nilmConfidenceDescriptor(item, "session");
          const duration = this._nilmSessionDuration(item);
          const status = isOpen
            ? this._panelTextFormat("nilm_workspace.provisional_pairing_confidence", { value: pairing ? this._nilmFormatPercent(pairing.value) : this._panelText("common.unknown") })
            : this._panelTextFormat("nilm_workspace.estimated_by_nilm", { duration: duration ? `, ${duration}` : "" });
          const confidence = isOpen ? "" : pairing
            ? `<p class="muted">${this._escape(pairing.text)}</p>`
            : "";
          const lowConfidence = !isOpen && pairing && this._isLowNilmConfidence(pairing.value)
            ? `<p class="muted">${this._escape(this._nilmLowConfidenceExplanation(item))}</p>`
            : "";
          const powerSummary = this._panelTextFormat(
            isOpen ? "nilm_workspace.session_power_summary_open" : "nilm_workspace.session_power_summary",
            { power: this._formatMetricValue(item.median_power_w), energy: this._formatMetricValue(item.estimated_energy_kwh) },
          );
          return `
        <div class="metric">
          <strong>${this._escape(this._panelTextFormat("nilm_workspace.predicted", { label }))}</strong>
          ${this._renderNilmSessionTime(item)}
          <p class="muted">${this._escape(status)}</p>
          ${confidence}
          ${lowConfidence}
          <p class="muted">${this._escape(powerSummary)}</p>
          ${item.actions && item.actions.assign ? this._renderNilmSessionAssignField(item, item.workspace_index) : ""}
          ${item.actions && item.actions.assign ? `<div class="actions">
            <button type="button" class="secondary" data-nilm-session-index="${item.workspace_index}" data-nilm-session-action="assign" ${this._busyAction === `nilm_sessions_${item.workspace_index}_assign` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.assign_appliance"))}</button>
          </div>` : ""}
        </div>
      `;
        }, this._panelText("nilm_workspace.sessions_description"))}
        ${this._renderNilmSessionPagination(workspace, unassignedSessions.length)}
        ${this._renderNilmWorkspaceDetails(this._panelText("nilm_workspace.edges_title"), workspace.edges, this._panelText("nilm_workspace.edges_empty"), (item) => `
        <div class="metric">
          <strong>${this._escape(this._friendlyFeature(item.direction))}: ${this._escape(this._formatNilmWatts(item.delta_w))} W</strong>
          <span>${this._escape(this._formatDateTime(item.timestamp))}</span>
          ${showDominantLeg ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.fact_dominant_leg"))}: ${this._escape(String(item.dominant_leg || "").trim() || this._panelText("nilm_workspace.no_dominant_leg"))}</p>` : ""}
        </div>
        `, this._panelText("nilm_workspace.edges_description"), "data-nilm-edges-details")}
        ${this._renderNilmAmbiguityAudit(workspace)}
        ${this._renderNilmEvidenceDetails(workspace)}
      </div>
    </details>`;
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

  _nilmRouteItemTarget(routeKey) {
    const params = new URL(routeKey, window.location.origin).searchParams;
    const validKinds = new Set([
      "session",
      "ambiguous_session",
      "label_interval",
      "assignment",
      "signature",
      "known_load_attribution",
    ]);
    const explicitKind = String(
      params.get("nilm_item_kind") || params.get("item_kind") || "",
    ).trim().toLowerCase();
    const explicitId = String(
      params.get("nilm_item_id") || params.get("item_id") || "",
    ).trim();
    if (validKinds.has(explicitKind) && explicitId) {
      return { kind: explicitKind, id: explicitId };
    }
    const candidates = [
      ["label_interval", "interval_id"],
      ["session", "session_id"],
      ["ambiguous_session", "ambiguous_session_id"],
      ["assignment", "assignment_id"],
      ["signature", "signature_id"],
      ["known_load_attribution", "known_load_attribution_id"],
    ];
    for (const [kind, parameter] of candidates) {
      const id = String(params.get(parameter) || "").trim();
      if (id) return { kind, id };
    }
    return null;
  }

  _nilmWorkspaceItemRequestPaths(target, routeKey) {
    const routeUrl = new URL(routeKey, window.location.origin);
    const workspaceCircuitId = this._nilmWorkspace?.circuit?.circuit_id;
    const payloadCircuitId = this._payload?.circuit?.circuit_id;
    const circuitId = workspaceCircuitId || payloadCircuitId || routeUrl.searchParams.get("circuit_id") || "";
    const entryId = routeUrl.searchParams.get("entry_id") || "";
    const params = new URLSearchParams({ kind: target.kind, id: target.id });
    if (circuitId) params.set("circuit_id", circuitId);
    if (entryId) params.set("entry_id", entryId);
    const fetchPath = `${NILM_WORKSPACE_ITEM_API_PATH}?${params.toString()}`;
    return {
      apiPath: fetchPath.replace(/^\/api\//, ""),
      fetchPath,
    };
  }

  _isCurrentNilmWorkspaceItemRequest(token, requestId, routeKey) {
    return token === this._nilmWorkspaceItemRequestToken
      && this._isCurrentRequest(requestId, routeKey);
  }

  _nilmLoadedRouteItem(workspace, target) {
    if (target.kind === "ambiguous_session") {
      const item = this._nilmAmbiguityAuditItem(target.id);
      return item ? { kind: "ambiguous_session", item, index: -1 } : null;
    }
    const collections = {
      session: ["sessions", "session_id", "session"],
      label_interval: ["label_intervals", "interval_id", "interval"],
      assignment: ["assignments", "assignment_id", "assignment"],
      signature: ["signatures", "signature_id", "signature"],
      known_load_attribution: ["known_load_attributions", "attribution_id", "known_load_attribution"],
    };
    const definition = collections[target.kind];
    if (!definition) return null;
    const [collection, idKey, reviewKind] = definition;
    const items = Array.isArray(workspace && workspace[collection]) ? workspace[collection] : [];
    const index = items.findIndex((item) => String(item && item[idKey] || "") === target.id);
    if (index < 0) return null;
    const item = items[index];
    if (target.kind === "session" && (!item.end || item.ambiguous)) return null;
    return { kind: reviewKind, item, index };
  }

  async _fetchNilmWorkspaceExactItem(target, requestId, routeKey) {
    const token = (this._nilmWorkspaceItemRequestToken || 0) + 1;
    this._nilmWorkspaceItemRequestToken = token;
    this._nilmRouteItemError = "";
    const { apiPath, fetchPath } = this._nilmWorkspaceItemRequestPaths(target, routeKey);
    try {
      const payload = await this._requestJson(apiPath, fetchPath);
      if (!this._isCurrentNilmWorkspaceItemRequest(token, requestId, routeKey)) {
        return null;
      }
      if (!payload || !["ok", "retired"].includes(payload.status) || !payload.item) {
        this._nilmRouteItemError = this._panelTextFormat(
          "nilm_workspace.deep_link_not_found",
          { item: this._friendlyFeature(target.kind) },
        );
        this._render();
        return null;
      }
      return payload;
    } catch (_error) {
      if (!this._isCurrentNilmWorkspaceItemRequest(token, requestId, routeKey)) {
        return null;
      }
      this._nilmRouteItemError = this._panelText("nilm_workspace.deep_link_load_failed");
      this._render();
      return null;
    }
  }

  async _focusNilmExactItem(payload, target) {
    const item = payload && payload.item;
    if (!item) return false;
    if (target.kind === "ambiguous_session") {
      return this._focusNilmAmbiguityOccurrence(
        this._showNilmExactAmbiguityItem(item),
        { scroll: false },
      );
    }
    if (target.kind === "known_load_attribution") {
      return this._focusNilmExactItemRange(payload.focus, item);
    }
    const reviewKind = target.kind === "label_interval" ? "interval" : target.kind;
    const reviewItem = { kind: reviewKind, item, index: -1 };
    const focused = await this._focusNilmReviewItem(reviewItem, { scroll: false });
    return focused || this._focusNilmExactItemRange(payload.focus, item);
  }

  async _focusNilmExactItemRange(focus, fallback) {
    const interval = { ...fallback, ...(focus || {}) };
    const start = Date.parse(interval.start || "");
    const end = Date.parse(interval.end || "");
    if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return false;
    this._beginNilmGraphIntent();
    this._nilmFocusedSignature = "";
    this._nilmFocusedOccurrenceIndex = -1;
    this._nilmFocusedInterval = null;
    return this._loadNilmIntervalOnGraph(interval, {
      clearSignature: true,
      edit: false,
      scroll: false,
    });
  }

  _showNilmExactAmbiguityItem(item) {
    const sessionId = String(item && item.session_id || "").trim();
    if (!sessionId) return item;
    const auditItem = {
      ...item,
      // Do not trust a stale or malformed exact-item payload to surface an
      // editor action. Deep links deliberately retain graph-only audit access.
      safe_actions: ["open_on_graph"],
    };
    const groupId = String(auditItem.group_id || `exact-${sessionId}`).trim();
    auditItem.group_id = groupId;
    const groups = new Map(this._nilmAmbiguityAuditGroupSummaries || []);
    if (!this._nilmAmbiguityAuditGroup(this._nilmAmbiguityAudit(), groupId)) {
      const candidateLabels = Array.isArray(auditItem.candidate_explanations)
        ? auditItem.candidate_explanations
          .map((candidate) => candidate?.display_label || candidate?.assignment_id || candidate?.signature_fingerprint)
          .filter(Boolean)
          .slice(0, 3)
        : [];
      groups.set(groupId, {
        group_id: groupId,
        occurrence_count: 1,
        latest_at: auditItem.start || auditItem.end || "",
        candidate_labels: candidateLabels,
        category: auditItem.ambiguity_category || "other",
      });
    }
    this._nilmAmbiguityAuditGroupSummaries = groups;
    this._nilmAmbiguityAuditExpanded = true;
    this._nilmAmbiguityAuditExpandedGroups = new Set([
      ...(this._nilmAmbiguityAuditExpandedGroups || []),
      groupId,
    ]);
    const results = new Map(this._nilmAmbiguityAuditGroupResults || []);
    const prior = results.get(groupId) || {};
    const priorItems = Array.isArray(prior.items) ? prior.items : [];
    results.set(groupId, {
      ...prior,
      fetched: true,
      loading: false,
      error: "",
      items: [
        auditItem,
        ...priorItems.filter((candidate) => String(candidate?.session_id || "") !== sessionId),
      ],
    });
    this._nilmAmbiguityAuditGroupResults = results;
    this._render();
    return auditItem;
  }

  async _focusNilmRouteTarget(workspace, routeKey) {
    const target = this._nilmRouteItemTarget(routeKey);
    if (!target) return false;
    const loaded = this._nilmLoadedRouteItem(workspace, target);
    if (loaded) {
      if (loaded.kind === "ambiguous_session") {
        return this._focusNilmAmbiguityOccurrence(
          this._showNilmExactAmbiguityItem(loaded.item),
          { scroll: false },
        );
      }
      if (loaded.kind !== "known_load_attribution") {
        this._selectNilmReviewItemForFocus(workspace, loaded);
        return this._focusNilmReviewItem(loaded, { scroll: false });
      }
      return this._focusNilmExactItemRange(null, loaded.item);
    }
    const payload = await this._fetchNilmWorkspaceExactItem(
      target,
      this._evidenceRequestId,
      routeKey,
    );
    if (!payload) return false;
    return this._focusNilmExactItem(payload, target);
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
    const confidence = this._nilmConfidenceDescriptor(item, reviewItem.kind);
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
      <span class="review-card-facts"><span>${this._escape(powerText)}</span>${confidence ? `<span>${this._escape(confidence.text)}</span>` : ""}</span>
      ${ambiguity ? `<span class="review-card-facts">${ambiguity}</span>` : ""}
      ${contextFacts.length ? `<span class="review-card-facts review-card-context">${contextFacts.map((fact) => `<span>${this._escape(fact)}</span>`).join("")}</span>` : ""}
      ${confidence && confidence.labelKey !== "feedback_evidence_score" ? `<progress max="100" value="${confidence.percent}" aria-label="${this._escape(confidence.text)}"></progress>` : ""}
    </button>`;
  }

  _renderNilmReviewInspector(reviewItem) {
    const item = reviewItem.item;
    const title = item.display_label || item.display_name || item.label || item.likely_type || item.appliance_id || this._panelText("common.unknown_load");
    const falsePositiveRate = this._nilmFiniteNumber(item.false_positive_rate);
    const falseNegativeRate = this._nilmFiniteNumber(item.false_negative_rate);
    const percent = (value) => Math.round(Math.max(0, Math.min(1, value)) * 100);
    const validationRates = falsePositiveRate !== null && falseNegativeRate !== null
      ? `<p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_rates", {
        false_positive: percent(falsePositiveRate),
        false_negative: percent(falseNegativeRate),
      }))}</p>`
      : "";
    const sessionValidation = reviewItem.kind === "session"
      && item.assignment_id
      && item.end
      && !item.ambiguous
      && (item.actions?.validate || item.actions?.reject);
    const assignedIntervals = reviewItem.kind === "assignment"
      ? ((this._nilmWorkspace && this._nilmWorkspace.label_intervals) || [])
        .map((interval, index) => ({ interval, index }))
        .filter(({ interval }) => interval.assignment_id === item.assignment_id
          || (item.label_interval_ids || []).includes(interval.interval_id))
      : [];
    const content = reviewItem.kind === "assignment"
      ? `
        ${this._nilmConfidenceDescriptor(item, "assignment") ? `<p class="muted">${this._escape(this._nilmConfidenceDescriptor(item, "assignment").text)}</p>` : ""}
        ${validationRates}
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_median_power_error", { power: this._formatMetricValue(item.median_power_error) }))}</p>
        <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.assignment_energy_error", { energy: this._formatMetricValue(item.energy_estimate_error) }))}</p>
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
            ${sessionValidation ? `
              <strong>${this._escape(this._panelTextFormat("nilm_workspace.predicted", { label: title }))}</strong>
              ${this._renderNilmSessionTime(item)}
              <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.estimated_by_nilm", { duration: this._nilmSessionDuration(item) ? `, ${this._nilmSessionDuration(item)}` : "" }))}</p>
              ${this._nilmConfidenceDescriptor(item, "session") ? `<p class="muted">${this._escape(this._nilmConfidenceDescriptor(item, "session").text)}</p>` : ""}
              ${this._nilmConfidenceDescriptor(item, "session") && this._isLowNilmConfidence(this._nilmConfidenceDescriptor(item, "session").value) ? `<p class="muted">${this._escape(this._nilmLowConfidenceExplanation(item))}</p>` : ""}
              <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.session_power_summary", { power: this._formatMetricValue(item.median_power_w), energy: this._formatMetricValue(item.estimated_energy_kwh) }))}</p>
              ${this._renderNilmSessionValidationActions(item, reviewItem.index)}
            ` : `
              ${this._nilmConfidenceDescriptor(item, "session") ? `<p class="muted">${this._escape(this._nilmConfidenceDescriptor(item, "session").text)}</p>` : ""}
              ${item.ambiguous ? `<p class="muted">${this._escape(this._panelText("nilm_workspace.session_ambiguous"))}</p>` : ""}
              ${!item.assignment_id && item.signature_review ? `
              <p class="muted">${this._escape(this._panelTextFormat("nilm_workspace.session_signature_review", { load: item.signature_review.display_label || item.signature_review.signature_id || "" }))}</p>
              ${this._renderNilmSignatureReview(item.signature_review, `session_${reviewItem.index}`)}
              ` : !item.assignment_id ? `
              ${this._renderNilmSessionAssignField(item, reviewItem.index)}
              ${item.actions && item.actions.assign ? `<div class="actions"><button type="button" data-nilm-session-index="${reviewItem.index}" data-nilm-session-action="assign">${this._escape(this._panelText("actions.labels.assign_appliance"))}</button></div>` : ""}
              ` : ""}
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
    this._nilmFocusedAmbiguitySession = null;
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

  _renderNilmSessionValidationActions(session, index) {
    const actions = session && session.actions ? session.actions : {};
    if (!session?.end || session.ambiguous || (!actions.validate && !actions.reject)) return "";
    return `<div class="actions">
      ${actions.validate ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="validate" ${this._busyAction === `nilm_sessions_${index}_validate` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.correct"))}</button>` : ""}
      ${actions.reject ? `<button type="button" class="secondary" data-nilm-session-index="${index}" data-nilm-session-action="reject" ${this._busyAction === `nilm_sessions_${index}_reject` ? "disabled" : ""}>${this._escape(this._panelText("actions.labels.wrong_appliance_sentence"))}</button>` : ""}
      ${session.start && session.end ? `<button type="button" class="secondary" data-nilm-session-interval-index="${index}">${this._escape(this._panelText("actions.labels.adjust_interval"))}</button>` : ""}
    </div>`;
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

  _renderNilmSessionTime(session) {
    const start = this._formatDateTime(session && session.start);
    if (!session || !session.end) {
      return `<span class="muted" data-nilm-session-range><span>${this._escape(this._panelTextFormat("nilm_workspace.range_open", { start }))}</span></span>`;
    }
    return `<span class="muted nilm-session-range" data-nilm-session-range><span>${this._escape(start)}</span><span>${this._escape(this._formatDateTime(session.end))}</span></span>`;
  }

  _formatNilmWatts(value) {
    const number = Number(value);
    return Number.isFinite(number) ? this._formatNumber(number) : this._panelText("common.unknown");
  }

  _renderNilmSignatureFacts(signature) {
    const facts = [];
    const evidence = this._nilmConfidenceDescriptor(signature, "signature");
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
    if (!facts.length && !requirement && !evidence) {
      return "";
    }
    return `${evidence ? `<p class="muted">${this._escape(evidence.text)}</p>` : ""}${facts.map(([label, value]) => `<p class="muted">${this._escape(label)}: ${this._escape(this._formatMetricValue(value))}</p>`).join("")}${requirement}`;
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
        <h2>${this._escape(this._panelText("nilm_workspace.interval_prompt"))}</h2>
        <p class="muted">${this._escape(this._panelText("nilm_workspace.interval_prompt_detail"))}</p>
        <ul class="muted nilm-interval-guidance" data-nilm-interval-guidance>
          <li>${this._escape(this._panelText("nilm_workspace.interval_guidance_start"))}</li>
          <li>${this._escape(this._panelText("nilm_workspace.interval_guidance_end"))}</li>
          <li>${this._escape(this._panelText("nilm_workspace.interval_guidance_other_loads"))}</li>
          <li>${this._escape(this._panelText("nilm_workspace.interval_guidance_examples"))}</li>
        </ul>
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
    const metric = (label, value, unit = "", formatter = null) => {
      const number = this._nilmFiniteNumber(value);
      if (number === null) return null;
      const formatted = formatter ? formatter(number) : `${this._formatNumber(number)}${unit ? ` ${unit}` : ""}`;
      return `${this._panelText(`nilm_workspace.${label}`)}: ${formatted}`;
    };
    const measuredEnergy = this._nilmFiniteNumber(evidence.measured_energy_kwh);
    const energyValue = measuredEnergy === null
      ? evidence.partial_energy_kwh ?? evidence.estimated_energy_kwh
      : evidence.measured_energy_kwh;
    const energyLabel = measuredEnergy === null
      ? "interval_estimated_energy"
      : "interval_measured_energy";
    const startEligible = evidence.start_transition_eligible;
    const stopEligible = evidence.stop_transition_eligible;
    const boundaryQuality = typeof startEligible === "boolean" || typeof stopEligible === "boolean"
      ? startEligible && stopEligible
        ? this._panelText("nilm_workspace.interval_quality_good")
        : !startEligible && !stopEligible
          ? this._panelText("nilm_workspace.interval_quality_both_uncertain")
          : startEligible
            ? this._panelText("nilm_workspace.interval_quality_stop_uncertain")
            : this._panelText("nilm_workspace.interval_quality_start_uncertain")
      : "";
    const interiorTransitions = this._nilmFiniteNumber(evidence.interior_transition_count);
    const metrics = [
      metric("interval_start_transition", evidence.start_transition_w, "W"),
      metric("interval_stop_transition", evidence.stop_transition_w, "W"),
      metric("interval_average_power", evidence.average_power_w, "W"),
      metric("interval_median_power", evidence.median_power_w, "W"),
      metric(energyLabel, energyValue, "kWh"),
      metric("interval_source_coverage", evidence.source_coverage, "", (value) => this._nilmFormatPercent(value)),
      metric("interval_power_coverage", evidence.power_coverage, "", (value) => this._nilmFormatPercent(value)),
      metric("interval_source_skew", evidence.source_skew_seconds, "s"),
      boundaryQuality
        ? `${this._panelText("nilm_workspace.interval_boundary_quality")}: ${boundaryQuality}`
        : null,
      interiorTransitions === null
        ? null
        : `${this._panelText("nilm_workspace.interval_interior_transitions")}: ${this._formatNumber(interiorTransitions)}`,
    ].filter(Boolean);
    const qualityFlags = Array.isArray(evidence.quality_flags)
      ? evidence.quality_flags.map((flag) => this._nilmIntervalQualityMessage(flag))
      : [];
    const qualityText = qualityFlags.map((item) => item.text).filter(Boolean);
    const warnings = qualityText.length
      ? `<div class="nilm-interval-quality" data-nilm-interval-quality><strong>${this._escape(this._panelText("nilm_workspace.interval_quality"))}:</strong> ${qualityFlags.map((item) => `<span class="nilm-interval-quality-chip nilm-interval-quality-${this._escape(item.severity)}">${this._escape(item.text)}</span>`).join("")}</div>
        <details><summary>${this._escape(this._panelText("nilm_workspace.interval_quality_raw_details"))}</summary><p class="muted">${this._escape((evidence.quality_flags || []).join(", "))}</p></details>`
      : "";
    const summary = this._panelTextFormat("nilm_workspace.interval_evidence_summary", {
      metrics: metrics.join(" · ") || this._panelText("common.unknown"),
      quality: qualityText.join(" · ") || this._panelText("nilm_workspace.interval_quality_good"),
    });
    return `<div class="muted" data-nilm-interval-evidence role="status" aria-live="polite" aria-label="${this._escape(summary)}">${metrics.map((value) => this._escape(value)).join(" · ")}${warnings}</div>`;
  }

  _nilmIntervalQualityMessage(flag) {
    const code = String(flag || "").trim().toLowerCase();
    const messages = {
      complete: ["interval_quality_good", "informational"],
      stable_plateau: ["interval_quality_good", "informational"],
      start_uncertain: ["interval_quality_start_uncertain", "caution"],
      start_transition_ineligible: ["interval_quality_start_uncertain", "caution"],
      stop_transition_ineligible: ["interval_quality_stop_uncertain", "caution"],
      interior_transition_present: ["interval_quality_interior_transition", "caution"],
      multiple_load_changes: ["interval_quality_interior_transition", "blocking"],
      incomplete_power_coverage: ["interval_quality_power_incomplete", "caution"],
      power_gap: ["interval_quality_power_gap", "caution"],
      long_power_gap: ["interval_quality_power_gap", "caution"],
      missing_source: ["interval_quality_source_unavailable", "blocking"],
      stale_source: ["interval_quality_source_stale", "caution"],
      source_skew_exceeded: ["interval_quality_source_skew", "caution"],
      baseline_unavailable: ["interval_quality_baseline_unavailable", "caution"],
      one_sided_baseline: ["interval_quality_one_sided_baseline", "caution"],
      material_negative_net_power: ["interval_quality_material_negative", "blocking"],
      material_negative_power: ["interval_quality_material_negative", "blocking"],
      negative_power_clipped: ["interval_quality_negative_clipped", "caution"],
      unknown_gap_bridged: ["interval_quality_unknown_gap", "caution"],
    };
    const [key, severity] = messages[code] || ["interval_quality_additional_detail", "informational"];
    return { text: this._panelText(`nilm_workspace.${key}`), severity };
  }

  _renderNilmSessionAssignField(session, index) {
    const draftKey = this._nilmSessionLabelDraftKey(session);
    const currentLabel = this._nilmSessionLabelDrafts.has(draftKey)
      ? this._nilmSessionLabelDrafts.get(draftKey)
      : "";
    const selectedAssignmentId = this._nilmSessionAssignmentDrafts.has(draftKey)
      ? this._nilmSessionAssignmentDrafts.get(draftKey)
      : "";
    return `
      ${this._renderNilmExistingAssignmentField(session && session.actions && session.actions.assign, `sessions_${index}`, selectedAssignmentId, "", draftKey)}
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

  _renderNilmPublicationReadiness(readiness) {
    if (!readiness || typeof readiness !== "object") return "";
    const status = this._friendlyFeature(readiness.status || "learning");
    const gates = readiness.gates && typeof readiness.gates === "object"
      ? Object.entries(readiness.gates)
      : [];
    return `<div class="nilm-publication-readiness" data-nilm-publication-readiness>
      <p class="muted"><strong>${this._escape(this._panelText("nilm_workspace.publication_readiness"))}</strong></p>
      <p class="muted">${this._escape(status)}</p>
      ${gates.length ? `<details open><summary>${this._escape(this._panelText("nilm_workspace.publication_readiness_gates"))}</summary><ul>${gates.map(([gate, value]) => `<li>${this._escape(this._panelTextFormat("nilm_workspace.publication_gate", { gate: this._friendlyFeature(gate), status: this._friendlyFeature(value) }))}</li>`).join("")}</ul></details>` : ""}
    </div>`;
  }

  _renderNilmAssignmentActions(item, index) {
    const actions = item && item.actions;
    const publication = item && item.publication;
    const readiness = this._renderNilmPublicationReadiness(
      item && item.publication_readiness,
    );
    const publicationState = publication && publication.available === false
      ? `${readiness}<button type="button" class="secondary" disabled>${this._escape(this._panelText("actions.labels.create_ha_device"))}</button>`
      : readiness;
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
    const groundTruthCount = Number(metrics.ground_truth_interval_count ?? preview.length);
    const hasReferenceIntervals = preview.length > 0 || (Number.isFinite(groundTruthCount) && groundTruthCount > 0);
    if (!hasReferenceIntervals) {
      return "";
    }
    const validationCount = Number(
      metrics.evaluable_prediction_count
      ?? metrics.evaluable_session_count
      ?? metrics.validation_evaluable_session_count
      ?? (Number(metrics.true_positive_count || 0) + Number(metrics.false_positive_count || 0)),
    );
    return `
      <h3>${this._escape(this._panelText("nilm_workspace.validation"))}</h3>
      <p class="muted">${this._escape(this._panelText("nilm_workspace.validation_description"))}</p>
      <div class="summary">
        <div class="metric">
          <span>${this._escape(this._panelText("nilm_workspace.ground_truth"))}</span>
          <strong>${this._escape(Number.isFinite(groundTruthCount) ? groundTruthCount : preview.length)}</strong>
        </div>
        <div class="metric">
          <span>${this._escape(this._panelTextFormat("nilm_workspace.validation_precision", { count: Number.isFinite(validationCount) ? validationCount : 0 }))}</span>
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
          ${this._nilmPredictionComparisonLines(item)}
        </div>
      `, this._panelText("nilm_workspace.prediction_preview_description"))}
    `;
  }

  _nilmPredictionComparisonLines(item) {
    const powerValues = [
      item && item.measured_power_w,
      item && item.estimated_power_w,
      item && item.power_error_w,
    ].map((value) => this._nilmFiniteNumber(value));
    const energyValues = [
      item && item.measured_energy_kwh,
      item && item.estimated_energy_kwh,
      item && item.energy_error_kwh,
    ].map((value) => this._nilmFiniteNumber(value));
    const lines = [];
    if (powerValues.every((value) => value !== null)) {
      lines.push(this._panelTextFormat("nilm_workspace.prediction_power_comparison", {
        measured: this._nilmFormatQuantity(powerValues[0], "W"),
        estimated: this._nilmFormatQuantity(powerValues[1], "W"),
        error: this._nilmFormatQuantity(powerValues[2], "W"),
      }));
    }
    if (energyValues.every((value) => value !== null)) {
      lines.push(this._panelTextFormat("nilm_workspace.prediction_energy_comparison", {
        measured: this._nilmFormatQuantity(energyValues[0], "kWh"),
        estimated: this._nilmFormatQuantity(energyValues[1], "kWh"),
        error: this._nilmFormatQuantity(energyValues[2], "kWh"),
      }));
    }
    return lines.map((line) => `<p class="muted">${this._escape(line)}</p>`).join("");
  }

  _renderNilmWorkspaceList(title, items, emptyText, renderItem, description = "") {
    const safeItems = Array.isArray(items) ? items : [];
    return `
      <h3>${this._escape(title)}</h3>
      ${description ? `<p class="muted">${this._escape(description)}</p>` : ""}
      ${safeItems.length ? `<div class="entity-list">${safeItems.map(renderItem).join("")}</div>` : `<p class="muted">${this._escape(emptyText)}</p>`}
    `;
  }

  _renderNilmWorkspaceDetails(title, items, emptyText, renderItem, description = "", dataAttribute = "") {
    const safeItems = Array.isArray(items) ? items : [];
    const attribute = String(dataAttribute || "").trim();
    return `
      <details class="nilm-evidence-details" ${attribute}>
        <summary>${this._escape(title)}</summary>
        ${description ? `<p class="muted">${this._escape(description)}</p>` : ""}
        ${safeItems.length ? `<div class="entity-list">${safeItems.map(renderItem).join("")}</div>` : `<p class="muted">${this._escape(emptyText)}</p>`}
      </details>
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
