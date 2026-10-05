const state = {
    serverCatalog: null,
    serverSync: null,
    serverExperiments: [],
    uploadedExperiments: [],
    localExperiments: [],
    groups: [],
    rows: [],
    selectedKey: null,
    loadingKey: null,
    activeRun: null,
    collapsedGroups: new Set(),
};


const elements = {
    status: document.getElementById("server_status"),
    statusText: document.getElementById("server_status_text"),
    refresh: document.getElementById("refresh_button"),
    sync: document.getElementById("sync_button"),
    upload: document.getElementById("upload_button"),
    file: document.getElementById("experiment_file"),
    search: document.getElementById("experiment_search"),
    count: document.getElementById("experiment_count"),
    body: document.getElementById("experiments_body"),
    catalogUserCount: document.getElementById("catalog_user_count"),
    catalogCampaignCount: document.getElementById("catalog_campaign_count"),
    catalogDefinitionCount: document.getElementById("catalog_definition_count"),
    catalogLocalCount: document.getElementById("catalog_local_count"),
    catalogSyncText: document.getElementById("catalog_sync_text"),
    start: document.getElementById("start_experiment_button"),
    activeBanner: document.getElementById("active_run_banner"),
    activeRunName: document.getElementById("active_run_name"),
    badge: document.getElementById("experiment_badge"),
    placeholder: document.getElementById("detail_placeholder"),
    content: document.getElementById("detail_content"),
    error: document.getElementById("detail_error"),
    name: document.getElementById("detail_name"),
    created: document.getElementById("detail_created"),
    modified: document.getElementById("detail_modified"),
    source: document.getElementById("detail_source"),
    state: document.getElementById("detail_state"),
    cell: document.getElementById("detail_cell"),
    user: document.getElementById("detail_user"),
    group: document.getElementById("detail_group"),
    repetitions: document.getElementById("detail_repetitions"),
    ph: document.getElementById("detail_ph"),
    airflow: document.getElementById("detail_airflow"),
    rotor: document.getElementById("detail_rotor"),
    reagentCount: document.getElementById("reagent_count"),
    reagents: document.getElementById("reagents_list"),
    stageCount: document.getElementById("stage_count"),
    stages: document.getElementById("stages_list"),
    executionCount: document.getElementById("execution_count"),
    executions: document.getElementById("executions_list"),
};


/* -------------------------------------------------------------------------- */
/* Requests                                                                   */
/* -------------------------------------------------------------------------- */

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        cache: "no-store",
        ...options,
        headers: {
            Accept: "application/json",
            ...(options.headers || {}),
        },
    });

    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            message = data.detail || message;
        } catch (_) {}
        throw new Error(message);
    }

    if (response.status === 204) return null;
    const text = await response.text();
    return text ? JSON.parse(text) : null;
}


async function saveExperiment(experiment) {
    return requestJson("/api/local/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(experiment),
    });
}


/* -------------------------------------------------------------------------- */
/* Loading                                                                    */
/* -------------------------------------------------------------------------- */

async function loadExperiments() {
    elements.refresh.disabled = true;
    if (elements.sync) elements.sync.disabled = true;
    setServerStatus("loading", "Loading");

    state.selectedKey = null;
    clearExperimentDetails();

    const [catalogResult, localResult, digiflotResult] = await Promise.allSettled([
        requestJson("/api/server/catalog"),
        requestJson("/api/local/experiments"),
        requestJson("/api/digiflot/state"),
    ]);

    if (catalogResult.status === "fulfilled") {
        const payload = catalogResult.value || {};
        state.serverCatalog = payload.catalog || { users: [], counts: {} };
        state.serverSync = payload.sync || null;
        state.serverExperiments = flattenServerCatalog(state.serverCatalog);
        renderServerStatus(state.serverSync);
    } else {
        state.serverCatalog = { users: [], counts: {} };
        state.serverSync = null;
        state.serverExperiments = [];
        setServerStatus("error", "Unavailable");
        console.error("Could not load Server catalog:", catalogResult.reason);
    }

    if (localResult.status === "fulfilled") {
        const payload = localResult.value;
        state.localExperiments = Array.isArray(payload) ? payload : (payload?.experiments || []);
    } else {
        state.localExperiments = [];
        console.error("Could not load local experiments:", localResult.reason);
    }

    const activeStates = new Set([
        "CameraCalibration", "SensorCalibration", "Ready",
        "Running", "Paused", "RecoveryRequired",
    ]);
    state.activeRun = (
        digiflotResult.status === "fulfilled"
        && digiflotResult.value?.storage_id
        && activeStates.has(digiflotResult.value?.state)
    ) ? digiflotResult.value : null;

    if (elements.activeBanner) {
        elements.activeBanner.hidden = !state.activeRun;
        if (state.activeRun) {
            elements.activeRunName.textContent = `${state.activeRun.experiment?.name || state.activeRun.storage_id} · ${state.activeRun.state}`;
        }
    }

    rebuildRows();
    renderCatalogSummary();
    renderExperiments();

    elements.refresh.disabled = false;
    if (elements.sync) elements.sync.disabled = false;
}


function flattenServerCatalog(catalog) {
    const rows = [];
    for (const user of catalog?.users || []) {
        for (const campaign of user?.campaigns || []) {
            for (const experiment of campaign?.experiments || []) {
                rows.push({
                    ...experiment,
                    _catalog: {
                        user: {
                            id: user?.id ?? null,
                            name: user?.name || "Unknown user",
                            counts: user?.counts || {},
                        },
                        campaign: {
                            id: campaign?.id ?? null,
                            name: campaign?.name || "Unassigned",
                            kind: campaign?.kind || "campaign",
                            status: campaign?.status ?? null,
                            counts: campaign?.counts || {},
                        },
                    },
                });
            }
        }
    }
    return rows;
}


function renderServerStatus(sync) {
    const raw = String(sync?.state || "offline").toLowerCase();
    if (raw === "connected") {
        setServerStatus("connected", sync?.mode === "v2" ? "Connected · API v2" : "Connected");
    } else if (raw === "syncing") {
        setServerStatus("loading", "Syncing");
    } else if (raw === "connecting") {
        setServerStatus("loading", "Connecting");
    } else {
        setServerStatus("error", "Offline · cached catalog");
    }
}


function renderCatalogSummary() {
    const users = state.serverCatalog?.users || [];
    const userCount = users.length;
    const campaignCount = users.reduce((total, user) => total + (user?.campaigns?.length || 0), 0);
    const definitionCount = state.serverExperiments.length + state.uploadedExperiments.length;
    if (elements.catalogUserCount) elements.catalogUserCount.textContent = userCount;
    if (elements.catalogCampaignCount) elements.catalogCampaignCount.textContent = campaignCount;
    if (elements.catalogDefinitionCount) elements.catalogDefinitionCount.textContent = definitionCount;
    if (elements.catalogLocalCount) elements.catalogLocalCount.textContent = state.localExperiments.length;

    if (elements.catalogSyncText) {
        const last = state.serverSync?.last_catalog_sync_at;
        const pending = Number(state.serverSync?.pending_executions || 0);
        const mode = state.serverSync?.mode ? String(state.serverSync.mode).toUpperCase() : "—";
        elements.catalogSyncText.textContent = last
            ? `API ${mode} · catalog ${formatDate(last, true)}${pending ? ` · ${pending} execution(s) pending sync` : ""}`
            : `API ${mode} · cached catalog${pending ? ` · ${pending} execution(s) pending sync` : ""}`;
    }
}


async function requestImmediateSync() {
    if (!elements.sync) return;
    const previous = elements.sync.textContent;
    elements.sync.disabled = true;
    elements.sync.textContent = "Sync requested…";
    try {
        const payload = await requestJson("/api/server/sync", { method: "POST" });
        state.serverSync = payload?.status || state.serverSync;
        renderServerStatus(state.serverSync);
        setTimeout(loadExperiments, 900);
    } catch (error) {
        setServerStatus("error", "Sync failed");
        console.error("Could not request Server sync:", error);
    } finally {
        setTimeout(() => {
            elements.sync.textContent = previous;
            elements.sync.disabled = false;
        }, 1100);
    }
}


/* -------------------------------------------------------------------------- */
/* Hierarchy / row model                                                      */
/* -------------------------------------------------------------------------- */

function rebuildRows() {
    const rows = [];
    const groups = [];
    const consumedLocal = new Set();

    const groupMap = new Map();
    const ensureUser = (key, label, data = {}, local = false) => {
        if (!groupMap.has(key)) {
            const node = { key, label, data, local, campaigns: [], campaignMap: new Map() };
            groupMap.set(key, node);
            groups.push(node);
        }
        return groupMap.get(key);
    };
    const ensureCampaign = (userNode, key, label, data = {}, local = false) => {
        if (!userNode.campaignMap.has(key)) {
            const node = { key, label, data, local, experiments: [] };
            userNode.campaignMap.set(key, node);
            userNode.campaigns.push(node);
        }
        return userNode.campaignMap.get(key);
    };

    for (const user of state.serverCatalog?.users || []) {
        const userKey = `user:server:${user?.id ?? user?.name ?? "unknown"}`;
        const userNode = ensureUser(userKey, user?.name || "Unknown user", user || {}, false);
        for (const campaign of user?.campaigns || []) {
            const campaignKey = `${userKey}:campaign:${campaign?.id ?? campaign?.name ?? "unassigned"}`;
            const campaignNode = ensureCampaign(userNode, campaignKey, campaign?.name || "Unassigned", campaign || {}, false);
            for (const experiment of campaign?.experiments || []) {
                const row = {
                    key: `server:${experiment.id}`,
                    kind: "definition",
                    source: "Server",
                    experiment,
                    catalog: { user, campaign },
                    userKey,
                    campaignKey,
                };
                rows.push(row);
                campaignNode.experiments.push(row);
                appendRelatedLocalRows(rows, campaignNode.experiments, row, consumedLocal);
            }
        }
    }

    if (state.uploadedExperiments.length) {
        const userNode = ensureUser("user:local", "Local", { counts: {} }, true);
        const campaignNode = ensureCampaign(userNode, "user:local:campaign:uploads", "Uploaded JSON", { kind: "local_import" }, true);
        for (const upload of state.uploadedExperiments) {
            const row = {
                key: upload.key,
                kind: "definition",
                source: "JSON",
                experiment: upload.experiment,
                catalog: null,
                userKey: userNode.key,
                campaignKey: campaignNode.key,
            };
            rows.push(row);
            campaignNode.experiments.push(row);
            appendRelatedLocalRows(rows, campaignNode.experiments, row, consumedLocal);
        }
    }

    const orphans = state.localExperiments.filter(local => !consumedLocal.has(local.storage_id));
    for (const local of orphans) {
        const context = local.experiment?._server?.context || {};
        const owner = context.owner || null;
        const campaign = context.campaign || null;
        const hasServerContext = Boolean(owner?.name || owner?.id != null || campaign?.name || campaign?.id != null);
        const existingUser = hasServerContext
            ? groups.find(group => (
                owner?.id != null && group.data?.id != null
                    ? String(group.data.id) === String(owner.id)
                    : String(group.label || "").trim().toLowerCase() === String(owner?.name || "").trim().toLowerCase()
            ))
            : null;
        const userKey = existingUser?.key || (hasServerContext
            ? `user:archived:${owner?.id ?? owner?.name ?? "server"}`
            : "user:local");
        const userLabel = hasServerContext ? (owner?.name || `User ${owner?.id}`) : "Local";
        const userNode = existingUser || ensureUser(userKey, userLabel, owner || { counts: {} }, !hasServerContext);
        const campaignKey = hasServerContext
            ? `${userKey}:campaign:${campaign?.id ?? campaign?.name ?? "unassigned"}`
            : "user:local:campaign:unassigned";
        const campaignLabel = hasServerContext ? (campaign?.name || "Archived campaign") : "Unassigned local data";
        const campaignData = hasServerContext
            ? { ...(campaign || {}), kind: campaign?.kind || "archived_local" }
            : { kind: "local_only" };
        const campaignNode = ensureCampaign(userNode, campaignKey, campaignLabel, campaignData, !hasServerContext);
        const catalog = hasServerContext ? { user: owner || {}, campaign: campaign || {} } : null;
        const row = createLocalRow(local, null, userNode.key, campaignNode.key, catalog);
        rows.push(row);
        campaignNode.experiments.push(row);
    }

    for (const group of groups) delete group.campaignMap;
    state.rows = rows;
    state.groups = groups;
}


function appendRelatedLocalRows(rows, campaignExperiments, parent, consumedLocal) {
    for (const local of state.localExperiments) {
        if (consumedLocal.has(local.storage_id)) continue;
        if (!sameExperimentIdentity(parent.experiment, local.experiment)) continue;

        consumedLocal.add(local.storage_id);
        const row = createLocalRow(local, parent.key, parent.userKey, parent.campaignKey, parent.catalog);
        rows.push(row);
        campaignExperiments.push(row);
    }
}


function createLocalRow(local, parentKey, userKey = "user:local", campaignKey = "user:local:campaign:unassigned", catalog = null) {
    return {
        key: `local:${local.storage_id}`,
        kind: "local",
        source: "Local",
        parentKey,
        userKey,
        campaignKey,
        catalog,
        storageId: local.storage_id,
        local,
        experiment: local.experiment,
    };
}


function sameExperimentIdentity(first, second) {
    if (!first || !second) return false;
    const firstId = first.id;
    const secondId = second.id;
    const validFirstId = firstId !== null && firstId !== undefined && String(firstId) !== "" && Number(firstId) >= 0;
    const validSecondId = secondId !== null && secondId !== undefined && String(secondId) !== "" && Number(secondId) >= 0;
    if (validFirstId && validSecondId) return String(firstId) === String(secondId);
    return String(first.name ?? "").trim().toLowerCase() === String(second.name ?? "").trim().toLowerCase();
}


function getRow(key) {
    return state.rows.find(row => row.key === key);
}


function childRows(parentKey) {
    return state.rows.filter(row => row.parentKey === parentKey);
}


function getRelatedLocalRuns(row) {
    if (!row) return [];
    if (row.kind === "local") return row.local ? [row.local] : [];
    return state.localExperiments.filter(local => sameExperimentIdentity(row.experiment, local.experiment));
}


function getResultRuns(row) {
    const runs = row?.kind === "local" ? (row.local ? [row.local] : []) : getRelatedLocalRuns(row);
    return runs
        .filter(local => Boolean(local.results?.available))
        .sort((a, b) => String(b.storage_id).localeCompare(String(a.storage_id)));
}


function openResults(storageId) {
    if (!storageId) return;
    window.location.href = `/results/${encodeURIComponent(storageId)}`;
}


function countRelatedLocal(row) {
    return getRelatedLocalRuns(row).length;
}


/* -------------------------------------------------------------------------- */
/* Hierarchical table                                                         */
/* -------------------------------------------------------------------------- */

function searchableRowText(row) {
    const experiment = row.experiment || {};
    const user = row.catalog?.user || {};
    const campaign = row.catalog?.campaign || {};
    return [
        experiment.id,
        experiment.name,
        experiment.origin,
        experiment.design_name,
        experiment.design_method,
        experiment.revision,
        experiment.state,
        row.local?.state,
        row.source,
        user.name,
        campaign.name,
        campaign.kind,
        campaign.status,
        row.storageId,
    ].map(value => String(value ?? "").toLowerCase()).join(" ");
}


function groupText(userNode, campaignNode = null) {
    return [
        userNode?.label,
        userNode?.data?.id,
        campaignNode?.label,
        campaignNode?.data?.id,
        campaignNode?.data?.kind,
        campaignNode?.data?.status,
    ].map(value => String(value ?? "").toLowerCase()).join(" ");
}


function renderExperiments() {
    const query = elements.search.value.trim().toLowerCase();
    elements.count.textContent = state.serverExperiments.length + state.uploadedExperiments.length;
    elements.body.innerHTML = "";

    if (!state.groups.length) {
        renderTableMessage("No experiments are available.");
        return;
    }

    let renderedExperiments = 0;

    for (const userNode of state.groups) {
        const userMatches = query && groupText(userNode).includes(query);
        const visibleCampaigns = [];

        for (const campaignNode of userNode.campaigns) {
            const campaignMatches = userMatches || (query && groupText(userNode, campaignNode).includes(query));
            const definitions = campaignNode.experiments.filter(row => !row.parentKey);
            const visibleDefinitions = [];

            for (const definition of definitions) {
                const children = childRows(definition.key);
                const definitionMatches = campaignMatches || !query || searchableRowText(definition).includes(query);
                const childMatches = children.filter(child => searchableRowText(child).includes(query));
                if (definitionMatches || childMatches.length) {
                    visibleDefinitions.push({ definition, children: definitionMatches ? children : childMatches });
                }
            }

            if (visibleDefinitions.length) visibleCampaigns.push({ campaignNode, visibleDefinitions });
        }

        if (!visibleCampaigns.length) continue;

        appendUserGroupRow(userNode, visibleCampaigns);
        const userCollapsed = !query && state.collapsedGroups.has(userNode.key);
        if (userCollapsed) continue;

        for (const { campaignNode, visibleDefinitions } of visibleCampaigns) {
            appendCampaignGroupRow(userNode, campaignNode, visibleDefinitions);
            const campaignCollapsed = !query && state.collapsedGroups.has(campaignNode.key);
            if (campaignCollapsed) continue;

            for (const { definition, children } of visibleDefinitions) {
                appendExperimentRow(definition, 2);
                renderedExperiments += 1;
                for (const child of children) appendExperimentRow(child, 3);
            }
        }
    }

    if (!renderedExperiments) {
        renderTableMessage(query ? "No experiments match the current search." : "No experiments are available.");
    }
}


function appendUserGroupRow(userNode, visibleCampaigns) {
    const row = document.createElement("tr");
    row.className = "catalog-group-row catalog-user-row";
    const collapsed = state.collapsedGroups.has(userNode.key);
    const experiments = visibleCampaigns.reduce((total, item) => total + item.visibleDefinitions.length, 0);
    const campaignCount = visibleCampaigns.length;
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.innerHTML = `<button class="catalog-toggle" type="button" aria-expanded="${!collapsed}"><span class="catalog-chevron">${collapsed ? "›" : "⌄"}</span><span class="catalog-group-copy"><strong>${escapeHtmlText(userNode.label)}</strong><small>${campaignCount} campaign${campaignCount === 1 ? "" : "s"} · ${experiments} experiment${experiments === 1 ? "" : "s"}</small></span></button>`;
    cell.querySelector("button").addEventListener("click", () => toggleGroup(userNode.key));
    row.appendChild(cell);
    elements.body.appendChild(row);
}


function appendCampaignGroupRow(userNode, campaignNode, visibleDefinitions) {
    const row = document.createElement("tr");
    row.className = "catalog-group-row catalog-campaign-row";
    const collapsed = state.collapsedGroups.has(campaignNode.key);
    const counts = campaignNode.data?.counts || {};
    const executed = Number(counts.executed || 0);
    const templates = Number(counts.templates || 0);
    const kind = humanizeCatalogKind(campaignNode.data?.kind);
    const status = campaignNode.data?.status;
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.innerHTML = `<button class="catalog-toggle campaign-toggle" type="button" aria-expanded="${!collapsed}"><span class="catalog-indent"></span><span class="catalog-chevron">${collapsed ? "›" : "⌄"}</span><span class="catalog-group-copy"><strong>${escapeHtmlText(campaignNode.label)}</strong><small>${visibleDefinitions.length} experiment${visibleDefinitions.length === 1 ? "" : "s"}${executed ? ` · ${executed} executed` : ""}${templates ? ` · ${templates} template${templates === 1 ? "" : "s"}` : ""}</small></span><span class="campaign-meta">${kind ? `<span class="campaign-kind">${escapeHtmlText(kind)}</span>` : ""}${status ? `<span class="campaign-status">${escapeHtmlText(status)}</span>` : ""}</span></button>`;
    cell.querySelector("button").addEventListener("click", () => toggleGroup(campaignNode.key));
    row.appendChild(cell);
    elements.body.appendChild(row);
}


function toggleGroup(key) {
    if (state.collapsedGroups.has(key)) state.collapsedGroups.delete(key);
    else state.collapsedGroups.add(key);
    renderExperiments();
}


function appendExperimentRow(rowData, level) {
    const experiment = rowData.experiment || {};
    const isActiveRun = rowData.kind === "local" && state.activeRun?.storage_id === rowData.storageId;
    const row = document.createElement("tr");
    row.className = `experiment-row hierarchy-level-${level}`;
    row.dataset.groupLevel = String(level);
    row.classList.add(rowData.kind === "local" ? "experiment-run-row" : "experiment-definition-row");
    if (rowData.kind === "local") row.classList.add("local-run-row");
    if (isActiveRun) row.classList.add("active-run-row");
    if (rowData.key === state.selectedKey) row.classList.add("selected");

    const idCell = document.createElement("td");
    idCell.className = "experiment-id";
    if (rowData.kind === "local") {
        const marker = document.createElement("span");
        marker.className = "local-run-marker";
        marker.textContent = "↳";
        idCell.appendChild(marker);
    }
    const id = experiment.id;
    idCell.append(document.createTextNode(id === null || id === undefined || Number(id) < 0 ? "Offline" : `#${id}`));

    const nameCell = document.createElement("td");
    nameCell.className = "experiment-name-cell";
    const name = document.createElement("strong");
    name.textContent = experiment.name || "Unnamed experiment";
    nameCell.appendChild(name);
    if (isActiveRun) {
        const activeLabel = document.createElement("span");
        activeLabel.className = "active-run-label";
        activeLabel.textContent = "● ACTIVE";
        nameCell.appendChild(activeLabel);
    }
    if (rowData.kind === "local" && !rowData.parentKey) {
        const localOnly = document.createElement("span");
        localOnly.className = "local-only-label";
        localOnly.textContent = "LOCAL ONLY";
        nameCell.appendChild(localOnly);
    }
    const meta = document.createElement("span");
    meta.className = "experiment-origin";
    meta.textContent = rowData.kind === "local"
        ? rowData.storageId
        : experiment.design_name
            ? `${experiment.design_name}${experiment.run_order != null ? ` · run ${experiment.run_order}` : ""}`
            : `Revision ${experiment.revision || 1}`;
    nameCell.appendChild(meta);

    const contextCell = document.createElement("td");
    const contextBadge = document.createElement("span");
    contextBadge.className = "source-badge";
    if (rowData.kind === "local") {
        contextBadge.textContent = "Recorded run";
    } else {
        contextBadge.textContent = experiment.is_template
            ? "Template"
            : experiment.origin === "design"
                ? `DoE${experiment.design_method ? ` · ${experiment.design_method}` : ""}`
                : humanizeCatalogKind(experiment.origin || rowData.source || "manual");
    }
    contextCell.appendChild(contextBadge);
    if (rowData.kind !== "local" && experiment.available_offline) {
        const cached = document.createElement("span");
        cached.className = "offline-cache-label";
        cached.textContent = "Cached";
        contextCell.appendChild(cached);
    }

    const executionCell = document.createElement("td");
    if (rowData.kind === "local") {
        const badge = document.createElement("span");
        badge.className = "experiment-state";
        badge.textContent = isActiveRun ? `${state.activeRun.state} · ACTIVE` : (rowData.local?.state || experiment.state || "Created");
        executionCell.appendChild(badge);
    } else {
        const executionCount = Number(experiment.execution_count || 0);
        if (executionCount > 0) {
            const wrap = document.createElement("div");
            wrap.className = "execution-summary";
            wrap.innerHTML = `<strong>${executionCount} execution${executionCount === 1 ? "" : "s"}</strong><span>${escapeHtmlText(experiment.last_execution_status || "Recorded")}${experiment.last_execution_at ? ` · ${escapeHtmlText(formatDate(experiment.last_execution_at))}` : ""}</span>`;
            executionCell.appendChild(wrap);
        } else {
            executionCell.textContent = "Not run";
        }
    }

    const modifiedCell = document.createElement("td");
    modifiedCell.textContent = formatDate(experiment.last_modified || experiment.local_created || rowData.local?.updated_at);

    const dataCell = document.createElement("td");
    dataCell.className = "local-data-cell";
    const resultRuns = getResultRuns(rowData);
    const allRuns = getRelatedLocalRuns(rowData);
    if (rowData.kind === "local" && resultRuns.length > 0) {
        const badge = document.createElement("span");
        badge.className = "local-data-badge available";
        badge.textContent = "● Results";
        dataCell.appendChild(badge);
    } else if (rowData.kind !== "local" && allRuns.length > 0) {
        const badge = document.createElement("span");
        badge.className = "local-data-badge available";
        badge.textContent = `${allRuns.length} local run${allRuns.length === 1 ? "" : "s"}`;
        dataCell.appendChild(badge);
    } else if (rowData.kind === "local") {
        const badge = document.createElement("span");
        badge.className = "local-data-badge pending";
        badge.textContent = "○ Metadata only";
        dataCell.appendChild(badge);
    } else if (Number(experiment.execution_count || 0) > 0) {
        const badge = document.createElement("span");
        badge.className = "server-history-badge";
        badge.textContent = "Server history";
        dataCell.appendChild(badge);
    } else {
        dataCell.textContent = "—";
    }

    const actionCell = document.createElement("td");
    actionCell.className = "table-action";
    const actions = document.createElement("div");
    actions.className = "row-actions";

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "button button-primary button-small";
    if (state.loadingKey === rowData.key) {
        openButton.textContent = "Opening…";
        openButton.disabled = true;
    } else if (rowData.kind === "local") {
        openButton.textContent = "Open";
    } else {
        openButton.textContent = "Start new";
        const syncState = String(state.serverSync?.state || "").toLowerCase();
        const serverAvailable = ["connected", "syncing"].includes(syncState);
        if (!experiment.available_offline && !serverAvailable && rowData.source === "Server") {
            openButton.disabled = true;
            openButton.title = "Recipe is not cached locally and the Server is offline.";
        }
    }
    openButton.addEventListener("click", async event => {
        event.stopPropagation();
        if (rowData.kind === "local") await openExperiment(rowData.key);
        else await startNewExperiment(rowData.key);
    });
    actions.appendChild(openButton);

    if (rowData.kind === "local" && resultRuns.length > 0 && !isActiveRun) {
        const resultsButton = document.createElement("button");
        resultsButton.type = "button";
        resultsButton.className = "button button-secondary button-small results-button";
        resultsButton.textContent = "Results";
        resultsButton.addEventListener("click", event => {
            event.stopPropagation();
            openResults(rowData.storageId);
        });
        actions.appendChild(resultsButton);
    }

    if (rowData.kind === "local" && !isActiveRun) {
        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.className = "button button-danger button-small";
        deleteButton.textContent = "Delete";
        deleteButton.addEventListener("click", async event => {
            event.stopPropagation();
            await deleteLocalExperiment(rowData.storageId);
        });
        actions.appendChild(deleteButton);
    }

    actionCell.appendChild(actions);
    row.append(idCell, nameCell, contextCell, executionCell, modifiedCell, dataCell, actionCell);
    row.addEventListener("click", () => openExperiment(rowData.key));
    elements.body.appendChild(row);
}


function humanizeCatalogKind(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const known = {
        manual: "Manual",
        design: "DoE",
        experimental_design: "DoE",
        template: "Template",
        unassigned: "Unassigned",
        local_import: "Local import",
        local_only: "Local data",
        archived_local: "Archived/local",
        Server: "Server",
    };
    return known[text] || text.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}


function renderTableMessage(
    message,
    isError = false,
) {
    elements.body.innerHTML = "";


    const row = (
        document.createElement(
            "tr"
        )
    );


    const cell = (
        document.createElement(
            "td"
        )
    );

    cell.colSpan = 7;

    cell.className = (
        "table-message"
    );


    if (isError) {
        cell.classList.add(
            "table-message-error"
        );
    }


    cell.textContent = message;


    row.appendChild(
        cell
    );

    elements.body.appendChild(
        row
    );
}


/* -------------------------------------------------------------------------- */
/* Open                                                                       */
/* -------------------------------------------------------------------------- */

async function openExperiment(
    key,
) {
    if (
        state.loadingKey !== null
    ) {
        return;
    }


    const row = (
        getRow(key)
    );


    if (!row) {
        return;
    }


    state.loadingKey = key;

    renderExperiments();

    showDetailLoading(
        row
    );


    try {
        const experiment = (
            await getExperimentForRow(
                row
            )
        );


        state.selectedKey = key;

        if (row.kind === "local" || row.source !== "Server") row.experiment = experiment;
        else row.recipe = experiment;


        renderExperiment(
            experiment,
            row,
        );

    } catch (error) {
        showDetailError(
            error.message
        );

    } finally {
        state.loadingKey = null;

        renderExperiments();
    }
}


async function getExperimentForRow(
    row,
) {
    if (
        row.kind === "local"
    ) {
        const payload = (
            await requestJson(
                `/api/local/experiments/${
                    encodeURIComponent(
                        row.storageId
                    )
                }`
            )
        );

        const experiment = payload.experiment;
        if (experiment && typeof experiment === "object") experiment._catalog = row.catalog || experiment._catalog || null;
        return experiment;
    }


    if (
        row.source === "Server"
    ) {
        const experiment = (
            await requestJson(
                `/api/server/experiments/${
                    encodeURIComponent(
                        row.experiment.id
                    )
                }`
            )
        );

        experiment.source = "Server";
        experiment._catalog = row.catalog || null;

        return experiment;
    }


    return row.experiment;
}


/* -------------------------------------------------------------------------- */
/* Create local experiment                                                    */
/* -------------------------------------------------------------------------- */

async function startNewExperiment(
    key,
) {
    if (
        state.loadingKey !== null
    ) {
        return;
    }


    const row = (
        getRow(key)
    );


    if (
        !row ||
        row.kind === "local"
    ) {
        return;
    }


    state.loadingKey = key;

    renderExperiments();


    try {
        const sourceExperiment = (
            await getExperimentForRow(
                row
            )
        );


        const experiment = (
            cloneObject(
                sourceExperiment
            )
        );


        experiment.source = (
            row.source
        );


        if (
            !experiment.state
        ) {
            experiment.state = (
                "Created"
            );
        }


        const local = (
            await saveExperiment(
                experiment
            )
        );


        state.localExperiments.push(
            local
        );


        rebuildRows();
        renderExperiments();


        const localKey = (
            `local:${local.storage_id}`
        );


        /*
         * Release the source-row lock before opening
         * the newly created local experiment.
         */
        state.loadingKey = null;


        await openExperiment(
            localKey
        );

    } catch (error) {
        showDetailError(
            error.message
        );

    } finally {
        state.loadingKey = null;

        renderExperiments();
    }
}


/* -------------------------------------------------------------------------- */
/* Delete local experiment                                                    */
/* -------------------------------------------------------------------------- */

async function deleteLocalExperiment(
    storageId,
) {
    const local = (
        state.localExperiments.find(
            item => (
                item.storage_id ===
                storageId
            )
        )
    );


    if (!local) {
        return;
    }


    const experiment = (
        local.experiment || {}
    );


    const confirmed = confirm(
        `Delete local execution "${experiment.name || storageId}"? This permanently removes videos, sensor data, runtime metadata and the event journal.`
    );


    if (!confirmed) {
        return;
    }


    try {
        await requestJson(
            `/api/local/experiments/${
                encodeURIComponent(
                    storageId
                )
            }`,
            {
                method: "DELETE",
            }
        );


        state.localExperiments = (
            state.localExperiments.filter(
                item => (
                    item.storage_id !==
                    storageId
                )
            )
        );


        const deletedKey = (
            `local:${storageId}`
        );


        if (
            state.selectedKey ===
            deletedKey
        ) {
            state.selectedKey = null;

            clearExperimentDetails();
        }


        rebuildRows();
        renderExperiments();

    } catch (error) {
        alert(
            `Could not delete experiment: ${error.message}`
        );
    }
}


/* -------------------------------------------------------------------------- */
/* Start campaign                                                             */
/* -------------------------------------------------------------------------- */

async function startExperimentCampaign() {
    const row = (
        getRow(
            state.selectedKey
        )
    );


    if (
        !row ||
        row.kind !== "local"
    ) {
        return;
    }


    if (state.activeRun?.storage_id === row.storageId) {
        window.location.href = "/run";
        return;
    }

    elements.start.disabled = true;


    try {
        /*
         * api.digiflot will coordinate the next steps:
         *
         * local experiment
         *      ↓
         * sensor calibration
         *      ↓
         * data acquisition
         *
         * Expected response:
         *
         * {
         *     "redirect_url": "/..."
         * }
         */
        const response = (
            await requestJson(
                `/api/digiflot/experiments/${
                    encodeURIComponent(
                        row.storageId
                    )
                }/start`,
                {
                    method: "POST",
                }
            )
        );


        if (
            !response?.redirect_url
        ) {
            throw new Error(
                "The server did not return a redirect URL."
            );
        }


        window.location.href = (
            response.redirect_url
        );

    } catch (error) {
        alert(
            `Could not start experiment: ${error.message}`
        );

        elements.start.disabled = false;
    }
}


/* -------------------------------------------------------------------------- */
/* JSON upload                                                                */
/* -------------------------------------------------------------------------- */

function startExperimentUpload() {
    elements.file.value = "";

    elements.file.click();
}


async function loadUploadedExperiment() {
    const file = (
        elements.file.files[0]
    );


    if (!file) {
        return;
    }


    try {
        const text = (
            await file.text()
        );


        const experiment = (
            JSON.parse(text)
        );


        if (
            !experiment ||
            Array.isArray(experiment) ||
            typeof experiment !== "object"
        ) {
            throw new Error(
                "Experiment JSON must contain an object."
            );
        }


        if (
            !String(
                experiment.name ?? ""
            ).trim()
        ) {
            throw new Error(
                "Experiment name is missing."
            );
        }


        experiment.source = "JSON";


        experiment.last_modified = (
            new Date()
                .toISOString()
                .slice(0, 19)
        );


        if (
            !experiment.state
        ) {
            experiment.state = (
                "Created"
            );
        }


        const key = (
            createUploadKey()
        );


        state.uploadedExperiments.push({
            key,
            experiment,
        });


        rebuildRows();
        renderExperiments();


        await openExperiment(
            key
        );

    } catch (error) {
        console.error(
            "Invalid experiment JSON:",
            error,
        );


        alert(
            `Could not load experiment: ${error.message}`
        );
    }
}


function createUploadKey() {
    if (
        typeof crypto !== "undefined" &&
        typeof crypto.randomUUID ===
        "function"
    ) {
        return (
            `upload:${crypto.randomUUID()}`
        );
    }


    return (
        `upload:${Date.now()}-${
            Math.random()
                .toString(16)
                .slice(2)
        }`
    );
}


/* -------------------------------------------------------------------------- */
/* Detail                                                                     */
/* -------------------------------------------------------------------------- */

function showDetailLoading(
    row,
) {
    elements.placeholder.hidden = false;
    elements.content.hidden = true;
    elements.error.hidden = true;

    elements.badge.hidden = false;
    elements.start.hidden = true;


    elements.badge.textContent = (
        row.kind === "local"
            ? "LOCAL"
            : row.source.toUpperCase()
    );


    elements.placeholder
        .querySelector("strong")
        .textContent = (
            "Loading experiment"
        );


    elements.placeholder
        .querySelector("p")
        .textContent = (
            row.kind === "local"
                ? "Loading the local experiment..."
                : "Loading experiment configuration..."
        );
}


function showDetailError(
    message,
) {
    elements.placeholder.hidden = true;
    elements.content.hidden = true;
    elements.error.hidden = false;

    elements.start.hidden = true;


    elements.error.textContent = (
        `Unable to load experiment: ${message}`
    );
}


function clearExperimentDetails() {
    elements.placeholder.hidden = false;
    elements.content.hidden = true;
    elements.error.hidden = true;

    elements.badge.hidden = true;
    elements.start.hidden = true;


    elements.placeholder
        .querySelector("strong")
        .textContent = (
            "No experiment selected"
        );


    elements.placeholder
        .querySelector("p")
        .textContent = (
            "Select an experiment from the list to open it."
        );
}


function renderExperiment(
    experiment,
    row,
) {
    elements.placeholder.hidden = true;
    elements.error.hidden = true;
    elements.content.hidden = false;

    elements.badge.hidden = false;


    if (
        row.kind === "local"
    ) {
        const experimentState = (
            experiment.state ||
            "Created"
        );


        elements.badge.textContent = (
            experimentState
        );


        elements.start.hidden = false;
        elements.start.disabled = false;


        const isActive = state.activeRun?.storage_id === row.storageId;
        elements.start.textContent = isActive
            ? "Open Active Run"
            : (experimentState === "Created" ? "Start Experiment" : "Open Experiment");

    } else {
        elements.badge.textContent = row.catalog?.campaign?.name
            ? `${row.source} · ${row.catalog.campaign.name}`
            : row.source;

        elements.start.hidden = true;
    }


    elements.name.textContent = (
        experiment.name ||
        `Experiment ${
            experiment.id ?? ""
        }`
    );


    elements.created.textContent = (
        formatDate(
            experiment.local_created ??
            experiment.creation_time,
            true,
        )
    );


    elements.modified.textContent = (
        formatDate(
            experiment.last_modified,
            true,
        )
    );


    const serverContext = experiment._server?.context || {};
    const catalogOwner = row.catalog?.user || experiment._catalog?.user || null;
    const catalogCampaign = row.catalog?.campaign || experiment._catalog?.campaign || null;

    elements.source.textContent = row.kind === "local"
        ? `Local · ${experiment.source || "Unknown"}`
        : `${row.source}${catalogCampaign?.kind ? ` · ${humanizeCatalogKind(catalogCampaign.kind)}` : ""}`;


    elements.state.textContent = (
        experiment.state ||
        (
            row.kind === "local"
                ? "Created"
                : "—"
        )
    );


    elements.cell.textContent = (
        valueOrDash(
            experiment.cell_id
        )
    );


    elements.user.textContent = valueOrDash(
        serverContext.owner?.name
        || catalogOwner?.name
        || experiment.user_name
        || experiment.user_id
    );


    elements.group.textContent = valueOrDash(
        serverContext.campaign?.name
        || catalogCampaign?.name
        || experiment.campaign_name
        || experiment.group_id
    );


    elements.repetitions.textContent = (
        valueOrDash(
            experiment.repetitions
        )
    );


    elements.ph.textContent = (
        formatNumber(
            experiment.pH ??
            experiment.ph
        )
    );


    elements.airflow.textContent = (
        formatWithUnit(
            experiment.airflow,
            "L/min",
        )
    );


    elements.rotor.textContent = (
        formatWithUnit(
            experiment.rotor_speed,
            "rpm",
        )
    );


    renderReagents(
        experiment.reagents || []
    );


    renderStages(
        experiment.stages || []
    );

    renderExecutions(row);
}


/* -------------------------------------------------------------------------- */
/* Executions                                                                 */
/* -------------------------------------------------------------------------- */

function renderExecutions(row) {
    if (!elements.executions || !elements.executionCount) return;

    const runs = getRelatedLocalRuns(row)
        .slice()
        .sort((a, b) => String(b.storage_id).localeCompare(String(a.storage_id)));

    elements.executionCount.textContent = runs.length;
    elements.executions.innerHTML = "";

    if (!runs.length) {
        elements.executions.appendChild(
            emptyBlock("No local executions are associated with this experiment yet.")
        );
        return;
    }

    for (const local of runs) {
        const experiment = local.experiment || {};
        const results = local.results || {};
        const runtime = local.runtime || {};
        const isActive = state.activeRun?.storage_id === local.storage_id;

        const card = document.createElement("article");
        card.className = "execution-card";
        if (isActive) card.classList.add("active");

        const info = document.createElement("div");
        info.className = "execution-info";
        info.innerHTML = `
            <div class="execution-title-line">
                <strong>${escapeHtmlText(formatDate(experiment.local_created, true))}</strong>
                <span class="execution-state">${escapeHtmlText(isActive ? state.activeRun.state : (local.state || experiment.state || "Created"))}</span>
                ${!local.parentKey && !row.parentKey && row.kind === "local" ? '<span class="execution-local-only">LOCAL</span>' : ''}
            </div>
            <span class="execution-id">${escapeHtmlText(local.storage_id)}</span>
            <div class="execution-metrics">
                <span><strong>${escapeHtmlText(formatDuration(results.duration_s ?? runtime.run_elapsed_s))}</strong> duration</span>
                <span><strong>${Number(results.sensor_files || 0)}</strong> sensor files</span>
                <span><strong>${Number(results.videos || 0)}</strong> videos</span>
                <span><strong>${Number(results.measurements || 0)}</strong> measurements</span>
                <span><strong>${escapeHtmlText(formatFileSize(results.size_bytes || 0))}</strong> data</span>
            </div>
        `;

        const actions = document.createElement("div");
        actions.className = "execution-actions";

        if (isActive) {
            const activeButton = document.createElement("a");
            activeButton.className = "button button-primary button-small";
            activeButton.href = "/run";
            activeButton.textContent = "Open active run";
            actions.appendChild(activeButton);
        } else if (results.available) {
            const resultButton = document.createElement("button");
            resultButton.type = "button";
            resultButton.className = "button button-primary button-small";
            resultButton.textContent = "View Results";
            resultButton.addEventListener("click", () => openResults(local.storage_id));
            actions.appendChild(resultButton);
        }

        if (!isActive) {
            const openButton = document.createElement("button");
            openButton.type = "button";
            openButton.className = "button button-secondary button-small";
            openButton.textContent = "Open run";
            openButton.addEventListener("click", () => openExperiment(`local:${local.storage_id}`));
            actions.appendChild(openButton);
        }

        card.append(info, actions);
        elements.executions.appendChild(card);
    }
}


function escapeHtmlText(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}


function formatDuration(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) return "—";
    if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
    const minutes = Math.floor(seconds / 60);
    const remainder = Math.floor(seconds % 60);
    return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}


function formatFileSize(value) {
    let bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes <= 0) return bytes === 0 ? "0 B" : "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let index = 0;
    while (bytes >= 1024 && index < units.length - 1) {
        bytes /= 1024;
        index += 1;
    }
    return `${bytes.toFixed(index === 0 ? 0 : bytes < 10 ? 2 : 1)} ${units[index]}`;
}


/* -------------------------------------------------------------------------- */
/* Reagents                                                                   */
/* -------------------------------------------------------------------------- */

function renderReagents(
    reagents,
) {
    elements.reagentCount.textContent = (
        reagents.length
    );


    elements.reagents.innerHTML = "";


    if (
        reagents.length === 0
    ) {
        elements.reagents.appendChild(
            emptyBlock(
                "No reagents configured."
            )
        );

        return;
    }


    for (
        const reagent
        of reagents
    ) {
        const item = (
            document.createElement(
                "div"
            )
        );

        item.className = (
            "reagent-item"
        );


        const heading = (
            document.createElement(
                "div"
            )
        );

        heading.className = (
            "item-heading"
        );


        const name = (
            document.createElement(
                "strong"
            )
        );

        name.textContent = (
            reagent.reagent_name ||
            `Reagent ${
                reagent.reagent_id
            }`
        );


        const id = (
            document.createElement(
                "span"
            )
        );

        id.textContent = (
            `ID ${
                valueOrDash(
                    reagent.reagent_id
                )
            }`
        );


        heading.append(
            name,
            id,
        );


        const values = (
            document.createElement(
                "div"
            )
        );

        values.className = (
            "item-values"
        );


        values.append(
            metric(
                "Concentration",

                formatWithUnit(
                    reagent.concentration,
                    "%",
                )
            ),

            metric(
                "Volume",

                formatWithUnit(
                    reagent.volume,
                    "mL",
                )
            ),
        );


        item.append(
            heading,
            values,
        );


        elements.reagents.appendChild(
            item
        );
    }
}


/* -------------------------------------------------------------------------- */
/* Stages                                                                     */
/* -------------------------------------------------------------------------- */

function renderStages(
    stages,
) {
    elements.stageCount.textContent = (
        stages.length
    );


    elements.stages.innerHTML = "";


    if (
        stages.length === 0
    ) {
        elements.stages.appendChild(
            emptyBlock(
                "No stages configured."
            )
        );

        return;
    }


    for (
        const [index, stage]
        of stages.entries()
    ) {
        const item = (
            document.createElement(
                "article"
            )
        );

        item.className = (
            "stage-item"
        );


        const header = (
            document.createElement(
                "div"
            )
        );

        header.className = (
            "stage-header"
        );


        const sequence = (
            document.createElement(
                "span"
            )
        );

        sequence.className = (
            "stage-index"
        );

        sequence.textContent = (
            String(index + 1)
                .padStart(2, "0")
        );


        const title = (
            document.createElement(
                "div"
            )
        );


        const name = (
            document.createElement(
                "strong"
            )
        );

        name.textContent = (
            stage.name ||
            `Stage ${index + 1}`
        );


        const type = (
            document.createElement(
                "span"
            )
        );

        type.className = (
            "stage-type"
        );

        type.textContent = (
            stage.type ||
            "stage"
        );


        title.append(
            name,
            type,
        );


        header.append(
            sequence,
            title,
        );


        const grid = (
            document.createElement(
                "div"
            )
        );

        grid.className = (
            "stage-grid"
        );


        grid.append(
            metric(
                "Duration",

                formatWithUnit(
                    stage.duration,
                    "s",
                )
            ),

            metric(
                "pH",

                formatNumber(
                    stage.ph ??
                    stage.pH
                )
            ),

            metric(
                "Airflow",

                formatWithUnit(
                    stage.airflow,
                    "L/min",
                )
            ),

            metric(
                "Rotor",

                formatWithUnit(
                    stage.rotor_speed,
                    "rpm",
                )
            ),

            metric(
                "Reagent",

                stage.reagent_name ||
                "—"
            ),
        );


        item.append(
            header,
            grid,
        );


        elements.stages.appendChild(
            item
        );
    }
}


/* -------------------------------------------------------------------------- */
/* Utilities                                                                  */
/* -------------------------------------------------------------------------- */

function metric(
    label,
    value,
) {
    const item = (
        document.createElement(
            "div"
        )
    );

    item.className = (
        "metric"
    );


    const labelElement = (
        document.createElement(
            "span"
        )
    );

    labelElement.textContent = (
        label
    );


    const valueElement = (
        document.createElement(
            "strong"
        )
    );

    valueElement.textContent = (
        value
    );


    item.append(
        labelElement,
        valueElement,
    );


    return item;
}


function emptyBlock(
    message,
) {
    const block = (
        document.createElement(
            "div"
        )
    );

    block.className = (
        "empty-block"
    );

    block.textContent = (
        message
    );

    return block;
}


function setServerStatus(
    status,
    text,
) {
    elements.status.className = (
        `state-badge state-${status}`
    );

    elements.statusText.textContent = (
        text
    );
}


function valueOrDash(
    value,
) {
    return (
        value === null ||
        value === undefined ||
        value === ""
    )
        ? "—"
        : String(value);
}


function formatNumber(
    value,
) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }


    const number = (
        Number(value)
    );


    return Number.isFinite(number)
        ? String(number)
        : String(value);
}


function formatWithUnit(
    value,
    unit,
) {
    const formatted = (
        formatNumber(value)
    );


    return (
        formatted === "—"
            ? formatted
            : `${formatted} ${unit}`
    );
}


function formatDate(
    value,
    includeTime = false,
) {
    if (!value) {
        return "—";
    }


    const date = (
        new Date(value)
    );


    if (
        Number.isNaN(
            date.getTime()
        )
    ) {
        return value;
    }


    return includeTime
        ? date.toLocaleString()
        : date.toLocaleDateString();
}


function cloneObject(
    value,
) {
    if (
        typeof structuredClone ===
        "function"
    ) {
        return structuredClone(
            value
        );
    }


    return JSON.parse(
        JSON.stringify(value)
    );
}


/* -------------------------------------------------------------------------- */
/* Events                                                                     */
/* -------------------------------------------------------------------------- */

elements.refresh.addEventListener(
    "click",
    loadExperiments,
);


if (elements.sync) {
    elements.sync.addEventListener(
        "click",
        requestImmediateSync,
    );
}


elements.search.addEventListener(
    "input",
    renderExperiments,
);


elements.upload.addEventListener(
    "click",
    startExperimentUpload,
);


elements.file.addEventListener(
    "change",
    loadUploadedExperiment,
);


elements.start.addEventListener(
    "click",
    startExperimentCampaign,
);


loadExperiments();