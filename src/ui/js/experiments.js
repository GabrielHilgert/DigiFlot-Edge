const state = {
    serverExperiments: [],
    uploadedExperiments: [],
    localExperiments: [],

    rows: [],

    selectedKey: null,
    loadingKey: null,
    activeRun: null,
};


const elements = {
    status: document.getElementById("server_status"),
    statusText: document.getElementById("server_status_text"),

    refresh: document.getElementById("refresh_button"),
    upload: document.getElementById("upload_button"),
    file: document.getElementById("experiment_file"),

    search: document.getElementById("experiment_search"),
    count: document.getElementById("experiment_count"),
    body: document.getElementById("experiments_body"),

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

async function requestJson(
    url,
    options = {},
) {
    const response = await fetch(
        url,
        {
            ...options,

            headers: {
                Accept: "application/json",
                ...(options.headers || {}),
            },
        }
    );


    if (!response.ok) {
        let message = (
            `HTTP ${response.status}`
        );

        try {
            const data = (
                await response.json()
            );

            message = (
                data.detail ||
                message
            );

        } catch (_) {
            // Keep HTTP status.
        }

        throw new Error(
            message
        );
    }


    if (response.status === 204) {
        return null;
    }


    const text = (
        await response.text()
    );


    if (!text) {
        return null;
    }


    return JSON.parse(
        text
    );
}


async function saveExperiment(
    experiment,
) {
    return requestJson(
        "/api/local/experiments",
        {
            method: "POST",

            headers: {
                "Content-Type": "application/json",
            },

            body: JSON.stringify(
                experiment
            ),
        }
    );
}


/* -------------------------------------------------------------------------- */
/* Loading                                                                    */
/* -------------------------------------------------------------------------- */

async function loadExperiments() {
    elements.refresh.disabled = true;

    setServerStatus(
        "loading",
        "Loading",
    );

    state.selectedKey = null;

    clearExperimentDetails();


    const [
        serverResult,
        localResult,
        digiflotResult,
    ] = await Promise.allSettled([
        requestJson(
            "/api/server/experiments"
        ),

        requestJson(
            "/api/local/experiments"
        ),

        requestJson(
            "/api/digiflot/state"
        ),
    ]);


    if (
        serverResult.status ===
        "fulfilled"
    ) {
        const payload = (
            serverResult.value
        );

        state.serverExperiments = (
            Array.isArray(payload)
                ? payload
                : (payload.experiments || [])
        );

        setServerStatus(
            "connected",
            "Connected",
        );

    } else {
        state.serverExperiments = [];

        setServerStatus(
            "error",
            "Offline",
        );
    }


    if (
        localResult.status ===
        "fulfilled"
    ) {
        const payload = (
            localResult.value
        );

        state.localExperiments = (
            Array.isArray(payload)
                ? payload
                : (payload.experiments || [])
        );

    } else {
        state.localExperiments = [];

        console.error(
            "Could not load local experiments:",
            localResult.reason,
        );
    }


    const activeStates = new Set([
        "CameraCalibration", "SensorCalibration", "Ready",
        "Running", "Paused", "RecoveryRequired"
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
    renderExperiments();

    elements.refresh.disabled = false;
}


/* -------------------------------------------------------------------------- */
/* Row model                                                                  */
/* -------------------------------------------------------------------------- */

function rebuildRows() {
    const rows = [];

    const consumedLocal = (
        new Set()
    );


    for (
        const experiment
        of state.serverExperiments
    ) {
        const row = {
            key: `server:${experiment.id}`,
            kind: "definition",
            source: "Server",
            experiment,
        };

        rows.push(
            row
        );

        appendRelatedLocalRows(
            rows,
            row,
            consumedLocal,
        );
    }


    for (
        const upload
        of state.uploadedExperiments
    ) {
        const row = {
            key: upload.key,
            kind: "definition",
            source: "JSON",
            experiment: upload.experiment,
        };

        rows.push(
            row
        );

        appendRelatedLocalRows(
            rows,
            row,
            consumedLocal,
        );
    }


    for (
        const local
        of state.localExperiments
    ) {
        if (
            consumedLocal.has(
                local.storage_id
            )
        ) {
            continue;
        }


        rows.push(
            createLocalRow(
                local,
                null,
            )
        );
    }


    state.rows = rows;
}


function appendRelatedLocalRows(
    rows,
    parent,
    consumedLocal,
) {
    for (
        const local
        of state.localExperiments
    ) {
        if (
            consumedLocal.has(
                local.storage_id
            )
        ) {
            continue;
        }


        if (
            !sameExperimentIdentity(
                parent.experiment,
                local.experiment,
            )
        ) {
            continue;
        }


        const localSource = (
            local.experiment?.source
        );


        if (
            localSource &&
            localSource !== parent.source
        ) {
            continue;
        }


        consumedLocal.add(
            local.storage_id
        );


        rows.push(
            createLocalRow(
                local,
                parent.key,
            )
        );
    }
}


function createLocalRow(
    local,
    parentKey,
) {
    return {
        key: (
            `local:${local.storage_id}`
        ),

        kind: "local",
        source: "Local",

        parentKey,

        storageId: local.storage_id,

        local,
        experiment: local.experiment,
    };
}


function sameExperimentIdentity(
    first,
    second,
) {
    if (
        !first ||
        !second
    ) {
        return false;
    }


    return (
        String(
            first.id ?? ""
        ) ===
        String(
            second.id ?? ""
        )
        &&
        String(
            first.name ?? ""
        ).trim() ===
        String(
            second.name ?? ""
        ).trim()
    );
}


function getRow(key) {
    return state.rows.find(
        row => (
            row.key === key
        )
    );
}


/* -------------------------------------------------------------------------- */
/* Table                                                                      */
/* -------------------------------------------------------------------------- */

function renderExperiments() {
    const query = (
        elements.search.value
            .trim()
            .toLowerCase()
    );


    const filtered = (
        state.rows.filter(
            row => {
                const experiment = (
                    row.experiment || {}
                );

                const fields = [
                    experiment.id,
                    experiment.name,
                    row.source,
                    experiment.source,
                    experiment.state,
                    row.local?.state,
                ];


                return (
                    !query ||
                    fields.some(
                        value => (
                            String(
                                value ?? ""
                            )
                            .toLowerCase()
                            .includes(query)
                        )
                    )
                );
            }
        )
    );


    elements.count.textContent = (
        state.rows.length
    );

    elements.body.innerHTML = "";


    if (
        filtered.length === 0
    ) {
        renderTableMessage(
            state.rows.length === 0
                ? "No experiments are available."
                : "No experiments match the current search."
        );

        return;
    }


    for (
        const rowData
        of filtered
    ) {
        const experiment = (
            rowData.experiment || {}
        );
        const isActiveRun = (
            rowData.kind === "local"
            && state.activeRun?.storage_id === rowData.storageId
        );


        const row = (
            document.createElement(
                "tr"
            )
        );

        row.className = (
            "experiment-row"
        );


        if (
            rowData.kind ===
            "local"
        ) {
            row.classList.add(
                "local-run-row"
            );
        }


        if (isActiveRun) {
            row.classList.add("active-run-row");
        }

        if (
            rowData.key ===
            state.selectedKey
        ) {
            row.classList.add(
                "selected"
            );
        }


        /* ID --------------------------------------------------------------- */

        const idCell = (
            document.createElement(
                "td"
            )
        );

        idCell.className = (
            "experiment-id"
        );


        if (
            rowData.kind ===
            "local"
        ) {
            const marker = (
                document.createElement(
                    "span"
                )
            );

            marker.className = (
                "local-run-marker"
            );

            marker.textContent = "↳";

            idCell.appendChild(
                marker
            );
        }


        const id = (
            experiment.id
        );


        const idText = (
            id === null ||
            id === undefined ||
            Number(id) < 0
                ? "Offline"
                : `#${id}`
        );


        idCell.append(
            document.createTextNode(
                idText
            )
        );


        /* Experiment ------------------------------------------------------- */

        const nameCell = (
            document.createElement(
                "td"
            )
        );


        const name = (
            document.createElement(
                "strong"
            )
        );


        name.textContent = (
            experiment.name ||
            "Unnamed experiment"
        );


        nameCell.appendChild(
            name
        );

        if (isActiveRun) {
            const activeLabel = document.createElement("span");
            activeLabel.className = "active-run-label";
            activeLabel.textContent = "● Active";
            nameCell.appendChild(activeLabel);
        }

        if (rowData.kind === "local" && !rowData.parentKey) {
            const localOnly = document.createElement("span");
            localOnly.className = "local-only-label";
            localOnly.textContent = "LOCAL ONLY";
            nameCell.appendChild(localOnly);
        }

        if (
            rowData.kind ===
            "local"
        ) {
            const localMeta = (
                document.createElement(
                    "span"
                )
            );

            localMeta.className = (
                "experiment-origin"
            );

            localMeta.textContent = (
                rowData.storageId
            );

            nameCell.appendChild(
                localMeta
            );
        }


        /* Source ----------------------------------------------------------- */

        const sourceCell = (
            document.createElement(
                "td"
            )
        );


        const source = (
            document.createElement(
                "span"
            )
        );

        source.className = (
            "source-badge"
        );


        if (
            rowData.kind ===
            "local"
        ) {
            source.textContent = (
                `Local · ${
                    experiment.source ||
                    "Unknown"
                }`
            );

        } else {
            source.textContent = (
                rowData.source
            );
        }


        sourceCell.appendChild(
            source
        );


        /* State ------------------------------------------------------------ */

        const stateCell = (
            document.createElement(
                "td"
            )
        );


        if (
            rowData.kind ===
            "local"
        ) {
            const stateBadge = (
                document.createElement(
                    "span"
                )
            );

            stateBadge.className = (
                "experiment-state"
            );

            stateBadge.textContent = isActiveRun
                ? `${state.activeRun.state} · ACTIVE`
                : (experiment.state || "Created");

            stateCell.appendChild(
                stateBadge
            );

        } else {
            stateCell.textContent = "—";
        }


        /* Modified --------------------------------------------------------- */

        const modifiedCell = (
            document.createElement(
                "td"
            )
        );


        modifiedCell.textContent = (
            formatDate(
                experiment.last_modified
            )
        );


        /* Local data ------------------------------------------------------- */

        const dataCell = document.createElement("td");
        dataCell.className = "local-data-cell";

        const resultRuns = getResultRuns(rowData);
        const allRuns = getRelatedLocalRuns(rowData);

        if (resultRuns.length > 0) {
            const badge = document.createElement("span");
            badge.className = "local-data-badge available";
            badge.textContent = resultRuns.length === 1
                ? "● Available"
                : `● ${resultRuns.length} runs`;
            dataCell.appendChild(badge);
        } else if (allRuns.length > 0) {
            const badge = document.createElement("span");
            badge.className = "local-data-badge pending";
            badge.textContent = "○ Local";
            dataCell.appendChild(badge);
        } else {
            dataCell.textContent = "—";
        }


        /* Actions ---------------------------------------------------------- */

        const actionCell = (
            document.createElement(
                "td"
            )
        );

        actionCell.className = (
            "table-action"
        );


        const actions = (
            document.createElement(
                "div"
            )
        );

        actions.className = (
            "row-actions"
        );


        const openButton = (
            document.createElement(
                "button"
            )
        );

        openButton.type = "button";

        openButton.className = (
            "button button-primary button-small"
        );


        if (
            state.loadingKey ===
            rowData.key
        ) {
            openButton.textContent = (
                "Opening..."
            );

            openButton.disabled = true;

        } else if (
            rowData.kind ===
            "local"
        ) {
            openButton.textContent = (
                "Open"
            );

        } else {
            openButton.textContent = (
                "Start New"
            );
        }


        openButton.addEventListener(
            "click",
            async event => {
                event.stopPropagation();


                if (
                    rowData.kind ===
                    "local"
                ) {
                    await openExperiment(
                        rowData.key
                    );

                } else {
                    await startNewExperiment(
                        rowData.key
                    );
                }
            }
        );


        actions.appendChild(
            openButton
        );

        if (resultRuns.length > 0 && !isActiveRun) {
            const latestResult = resultRuns[0];
            const resultsButton = document.createElement("button");
            resultsButton.type = "button";
            resultsButton.className = "button button-secondary button-small results-button";
            resultsButton.textContent = resultRuns.length > 1
                ? `Results (${resultRuns.length})`
                : "Results";
            resultsButton.addEventListener("click", event => {
                event.stopPropagation();
                openResults(latestResult.storage_id);
            });
            actions.appendChild(resultsButton);
        }


        /*
         * A local experiment can only be deleted
         * before the campaign starts.
         */
        if (
            rowData.kind === "local" &&
            !isActiveRun
        ) {
            const deleteButton = (
                document.createElement(
                    "button"
                )
            );

            deleteButton.type = (
                "button"
            );

            deleteButton.className = (
                "button button-danger button-small"
            );

            deleteButton.textContent = (
                "Delete"
            );


            deleteButton.addEventListener(
                "click",
                async event => {
                    event.stopPropagation();

                    await deleteLocalExperiment(
                        rowData.storageId
                    );
                }
            );


            actions.appendChild(
                deleteButton
            );
        }


        if (
            rowData.kind ===
            "definition"
        ) {
            const localCount = (
                countRelatedLocal(
                    rowData
                )
            );


            if (
                localCount > 0
            ) {
                const count = (
                    document.createElement(
                        "span"
                    )
                );

                count.className = (
                    "local-count"
                );

                count.textContent = (
                    `${localCount} local`
                );

                actions.appendChild(
                    count
                );
            }
        }


        actionCell.appendChild(
            actions
        );


        row.append(
            idCell,
            nameCell,
            sourceCell,
            stateCell,
            modifiedCell,
            dataCell,
            actionCell,
        );


        row.addEventListener(
            "click",
            () => openExperiment(
                rowData.key
            )
        );


        elements.body.appendChild(
            row
        );
    }
}


function getRelatedLocalRuns(row) {
    if (!row) return [];

    if (row.kind === "local") {
        const matches = state.localExperiments.filter(local =>
            sameExperimentIdentity(row.experiment, local.experiment)
            && (
                !row.experiment?.source
                || !local.experiment?.source
                || local.experiment.source === row.experiment.source
            )
        );
        return matches.length ? matches : (row.local ? [row.local] : []);
    }

    return state.localExperiments.filter(local =>
        sameExperimentIdentity(row.experiment, local.experiment)
        && (
            !local.experiment?.source
            || local.experiment.source === row.source
        )
    );
}


function getResultRuns(row) {
    const runs = row?.kind === "local"
        ? (row.local ? [row.local] : [])
        : getRelatedLocalRuns(row);

    return runs
        .filter(local => Boolean(local.results?.available))
        .sort((a, b) => String(b.storage_id).localeCompare(String(a.storage_id)));
}


function openResults(storageId) {
    if (!storageId) return;
    window.location.href = `/results/${encodeURIComponent(storageId)}`;
}


function countRelatedLocal(
    row,
) {
    return getRelatedLocalRuns(row).length;
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

        row.experiment = experiment;


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

        return payload.experiment;
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

        experiment.source = (
            "Server"
        );

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
        elements.badge.textContent = (
            row.source
        );

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


    elements.source.textContent = (
        row.kind === "local"
            ? `Local · ${
                experiment.source ||
                "Unknown"
            }`
            : row.source
    );


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


    elements.user.textContent = (
        valueOrDash(
            experiment.user_id
        )
    );


    elements.group.textContent = (
        valueOrDash(
            experiment.group_id
        )
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