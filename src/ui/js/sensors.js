const HISTORY_LIMIT = 150;

const state = {
    sensors: new Map(),
    streams: new Map(),
    histories: new Map(),
    timestamps: new Map(),
    digiflot: null,
    calibrationMode: false,
    maintenanceMode: false,
    standaloneCalibration: new Map(),
};

const el = {
    pageTitle: document.getElementById("page_title"),
    pageDescription: document.getElementById("page_description"),
    experimentState: document.getElementById("experiment_state"),
    experimentStateText: document.getElementById("experiment_state_text"),
    calibrationBanner: document.getElementById("calibration_banner"),
    sensorGrid: document.getElementById("sensor_grid"),
    emptyState: document.getElementById("empty_state"),
    calibrationFooter: document.getElementById("calibration_footer"),
    calibrationProgress: document.getElementById("calibration_progress"),
    calibrationHint: document.getElementById("calibration_hint"),
    finishCalibration: document.getElementById("finish_calibration"),
    toast: document.getElementById("toast"),
};

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    let payload = null;
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
        throw new Error(payload?.detail || `${response.status} ${response.statusText}`);
    }
    return payload;
}

function showToast(message) {
    el.toast.textContent = message;
    el.toast.classList.add("show");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => el.toast.classList.remove("show"), 3200);
}

function statusLabel(status) {
    return {
        connected: "Online",
        offline: "Offline",
        starting: "Starting",
        error: "Error",
        stopped: "Stopped",
    }[status] || "Unknown";
}

function formatValue(value, snapshot = {}) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "—";
    return numeric.toFixed(Number(snapshot.decimals ?? 2));
}

function setExperimentState(value) {
    const normalized = String(value || "muted").replace(/[^a-z0-9]/gi, "").toLowerCase();
    el.experimentState.className = `state-badge state-${normalized}`;
    el.experimentState.innerHTML = `<span class="state-dot"></span><span id="experiment_state_text">${escapeHtml(value || "Unknown")}</span>`;
    el.experimentStateText = document.getElementById("experiment_state_text");
}

function calibrationItem(sensorId) {
    return state.digiflot?.calibration?.sensors?.[String(sensorId)] || null;
}

function standaloneCalibrationMarkup(snapshot) {
    if (!state.maintenanceMode || snapshot.status !== "connected" || String(snapshot.type || "").toLowerCase() !== "ph") return "";
    const progress = state.standaloneCalibration.get(String(snapshot.id)) || {mid:false, low:false};
    return `
        <div class="calibration-block ph-calibration">
            <div class="calibration-heading"><div><strong>Two-point pH calibration</strong><span>Maintenance mode. Calibrate pH 7 first, rinse the probe, then calibrate pH 4.</span></div></div>
            <div class="calibration-points">
                <div class="calibration-point ${progress.mid ? "done" : ""}">
                    <div><span class="point-index">1</span><div><strong>Midpoint</strong><small>Place the probe in the pH 7 buffer and wait for a stable live signal.</small></div></div>
                    <div class="point-action"><input class="buffer-value" data-point-value="mid" type="number" step="0.01" value="7.00"><button class="button ${progress.mid ? "button-secondary" : "button-primary"} standalone-ph-calibrate" data-sensor-id="${escapeHtml(snapshot.id)}" data-point="mid" type="button" ${progress.mid ? "disabled" : ""}>${progress.mid ? "Calibrated" : "Calibrate midpoint"}</button></div>
                </div>
                <div class="calibration-point ${progress.low ? "done" : ""}">
                    <div><span class="point-index">2</span><div><strong>Low point</strong><small>Rinse the probe, place it in the pH 4 buffer, and wait for stabilization.</small></div></div>
                    <div class="point-action"><input class="buffer-value" data-point-value="low" type="number" step="0.01" value="4.00" ${!progress.mid ? "disabled" : ""}><button class="button ${progress.low ? "button-secondary" : "button-primary"} standalone-ph-calibrate" data-sensor-id="${escapeHtml(snapshot.id)}" data-point="low" type="button" ${(!progress.mid || progress.low) ? "disabled" : ""}>${progress.low ? "Calibrated" : "Calibrate low point"}</button></div>
                </div>
            </div>
        </div>`;
}

function calibrationMarkup(snapshot) {
    if (!state.calibrationMode) return standaloneCalibrationMarkup(snapshot);

    const calibration = calibrationItem(snapshot.id);
    if (!calibration) {
        return `<div class="calibration-block muted"><strong>No calibration step</strong><span>This sensor is not part of the active calibration checklist.</span></div>`;
    }

    const connection = snapshot.status;
    if (connection !== "connected") {
        return `
            <div class="calibration-block offline-block">
                <div>
                    <strong>Unavailable</strong>
                    <span>This sensor is offline. It will be marked as unavailable when calibration is finished.</span>
                </div>
            </div>`;
    }

    if (calibration.status === "passed") {
        return `
            <div class="calibration-block complete-block">
                <div>
                    <strong>Calibration complete</strong>
                    <span>${calibration.mode === "two_point" ? "Two-point pH calibration stored by the EZO circuit." : "Sensor check completed."}</span>
                </div>
                <span class="calibration-pill passed">Passed</span>
            </div>`;
    }

    if (calibration.status === "skipped") {
        return `
            <div class="calibration-block skipped-block">
                <div>
                    <strong>Calibration skipped</strong>
                    <span>${escapeHtml(calibration.skip_reason || "Skipped by operator.")}</span>
                </div>
                <span class="calibration-pill skipped">Skipped</span>
            </div>`;
    }

    if (calibration.mode === "manual_tare") {
        return `
            <div class="calibration-block">
                <div>
                    <strong>Manual tare</strong>
                    <span>Press TARE on the physical scale. Confirm after the live reading is stable at zero.</span>
                </div>
                <div class="calibration-actions">
                    <button class="button button-secondary sensor-skip" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Skip tare</button>
                    <button class="button button-primary sensor-confirm" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Tare complete</button>
                </div>
            </div>`;
    }

    if (calibration.mode === "two_point") {
        const points = calibration.points || {};
        const mid = points.mid || { value: 7, status: "pending" };
        const low = points.low || { value: 4, status: "pending" };
        const midDone = mid.status === "passed";
        const lowDone = low.status === "passed";
        return `
            <div class="calibration-block ph-calibration">
                <div class="calibration-heading">
                    <div>
                        <strong>Two-point pH calibration</strong>
                        <span>Calibrate the midpoint first, rinse the probe, then calibrate the low point.</span>
                    </div>
                    <div class="calibration-heading-actions">
                        <span class="calibration-pill ${escapeHtml(calibration.status)}">${escapeHtml(calibration.status)}</span>
                        <button class="button button-secondary sensor-skip" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Skip calibration</button>
                    </div>
                </div>
                <div class="calibration-points">
                    <div class="calibration-point ${midDone ? "done" : ""}">
                        <div>
                            <span class="point-index">1</span>
                            <div><strong>Midpoint</strong><small>Place probe in the pH 7 buffer and wait for the plot to stabilize.</small></div>
                        </div>
                        <div class="point-action">
                            <input class="buffer-value" data-point-value="mid" type="number" step="0.01" value="${escapeHtml(mid.value ?? 7)}" aria-label="Midpoint buffer pH">
                            <button class="button ${midDone ? "button-secondary" : "button-primary"} ph-calibrate" data-sensor-id="${escapeHtml(snapshot.id)}" data-point="mid" type="button" ${midDone ? "disabled" : ""}>${midDone ? "Calibrated" : "Calibrate midpoint"}</button>
                        </div>
                    </div>
                    <div class="calibration-point ${lowDone ? "done" : ""}">
                        <div>
                            <span class="point-index">2</span>
                            <div><strong>Low point</strong><small>Rinse the probe, place it in the pH 4 buffer, and wait for stabilization.</small></div>
                        </div>
                        <div class="point-action">
                            <input class="buffer-value" data-point-value="low" type="number" step="0.01" value="${escapeHtml(low.value ?? 4)}" aria-label="Low-point buffer pH" ${!midDone ? "disabled" : ""}>
                            <button class="button ${lowDone ? "button-secondary" : "button-primary"} ph-calibrate" data-sensor-id="${escapeHtml(snapshot.id)}" data-point="low" type="button" ${(!midDone || lowDone) ? "disabled" : ""}>${lowDone ? "Calibrated" : "Calibrate low point"}</button>
                        </div>
                    </div>
                </div>
            </div>`;
    }

    return `
        <div class="calibration-block">
            <div>
                <strong>Live verification</strong>
                <span>No software calibration is configured for this sensor yet. Verify the signal is plausible and stable.</span>
            </div>
            <div class="calibration-actions">
                <button class="button button-secondary sensor-skip" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Skip check</button>
                <button class="button button-primary sensor-confirm" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Mark checked</button>
            </div>
        </div>`;
}

function sensorCard(snapshot) {
    const status = snapshot.status || "stopped";
    const hasValue = Number.isFinite(Number(snapshot.value));
    return `
        <article class="sensor-card" id="sensor-card-${escapeHtml(snapshot.id)}" data-sensor-id="${escapeHtml(snapshot.id)}">
            <header class="sensor-card-header">
                <div>
                    <span class="sensor-type">${escapeHtml(snapshot.type || "sensor")}</span>
                    <h2>${escapeHtml(snapshot.name || snapshot.id)}</h2>
                    <span class="sensor-device">${escapeHtml(snapshot.interface || "")} · ${escapeHtml(snapshot.device || "—")}</span>
                </div>
                <span class="sensor-status status-${escapeHtml(status)}"><span></span>${escapeHtml(statusLabel(status))}</span>
            </header>

            <div class="sensor-reading-row">
                <div class="sensor-reading">
                    <strong class="reading-value">${hasValue ? escapeHtml(formatValue(snapshot.value, snapshot)) : "—"}</strong>
                    <span class="reading-unit">${escapeHtml(snapshot.unit || "")}</span>
                </div>
                <div class="reading-details">
                    <div><span>Updated</span><strong class="last-update">${snapshot.timestamp_ms ? new Date(snapshot.timestamp_ms).toLocaleTimeString() : "—"}</strong></div>
                    <div><span>Rate</span><strong class="sample-rate">—</strong></div>
                    <div><span>Samples</span><strong class="sample-count">${escapeHtml(snapshot.sample_count ?? 0)}</strong></div>
                </div>
            </div>

            <div class="chart-frame">
                <canvas class="sensor-chart" aria-label="Live signal for ${escapeHtml(snapshot.name || snapshot.id)}"></canvas>
                <div class="chart-empty">${status === "offline" ? "Sensor offline" : "Waiting for measurements…"}</div>
            </div>
            <div class="chart-footer"><span class="chart-min">Min —</span><span class="chart-span">Span —</span><span class="chart-max">Max —</span></div>

            <div class="sensor-message ${snapshot.error ? "visible" : ""}">${snapshot.error ? escapeHtml(snapshot.error) : ""}</div>
            <div class="calibration-host">${calibrationMarkup(snapshot)}</div>
        </article>`;
}

function renderCards() {
    const snapshots = [...state.sensors.values()];
    el.emptyState.hidden = snapshots.length > 0;
    el.sensorGrid.innerHTML = snapshots.map(sensorCard).join("");

    for (const snapshot of snapshots) {
        const card = cardFor(snapshot.id);
        const canvas = card?.querySelector(".sensor-chart");
        if (canvas) {
            new ResizeObserver(() => drawChart(snapshot.id)).observe(canvas);
            drawChart(snapshot.id);
        }
    }
    bindCalibrationControls();
    updateCalibrationProgress();
}

function cardFor(sensorId) {
    return document.querySelector(`[data-sensor-id="${CSS.escape(String(sensorId))}"]`);
}

function updateCard(snapshot) {
    state.sensors.set(String(snapshot.id), snapshot);
    const card = cardFor(snapshot.id);
    if (!card) {
        renderCards();
        return;
    }

    const status = snapshot.status || "stopped";
    const statusNode = card.querySelector(".sensor-status");
    statusNode.className = `sensor-status status-${status}`;
    statusNode.innerHTML = `<span></span>${escapeHtml(statusLabel(status))}`;

    card.querySelector(".reading-value").textContent = formatValue(snapshot.value, snapshot);
    card.querySelector(".reading-unit").textContent = snapshot.unit || "";
    card.querySelector(".last-update").textContent = snapshot.timestamp_ms ? new Date(snapshot.timestamp_ms).toLocaleTimeString() : "—";
    card.querySelector(".sample-count").textContent = snapshot.sample_count ?? 0;

    const message = card.querySelector(".sensor-message");
    message.textContent = snapshot.error || "";
    message.classList.toggle("visible", Boolean(snapshot.error));

    const numeric = Number(snapshot.value);
    if (Number.isFinite(numeric) && snapshot.timestamp_ms) {
        appendHistory(snapshot.id, snapshot.timestamp_ms, numeric, snapshot.unit || "");
        updateRate(snapshot.id, snapshot.timestamp_ms);
    } else {
        const empty = card.querySelector(".chart-empty");
        if (empty) empty.textContent = status === "offline" ? "Sensor offline" : "Waiting for measurements…";
    }

    const host = card.querySelector(".calibration-host");
    if (host) {
        host.innerHTML = calibrationMarkup(snapshot);
        bindCalibrationControls(host);
    }
    updateCalibrationProgress();
}

function appendHistory(sensorId, timestamp, value, unit) {
    const id = String(sensorId);
    const history = state.histories.get(id) || [];
    if (history.at(-1)?.timestamp === timestamp) return;
    history.push({ timestamp, value, unit });
    if (history.length > HISTORY_LIMIT) history.shift();
    state.histories.set(id, history);
    drawChart(id);
}

function updateRate(sensorId, timestamp) {
    const id = String(sensorId);
    const times = state.timestamps.get(id) || [];
    if (!times.length || timestamp > times.at(-1)) times.push(timestamp);
    if (times.length > 40) times.shift();
    state.timestamps.set(id, times);

    const card = cardFor(id);
    if (!card || times.length < 2) return;
    const seconds = (times.at(-1) - times[0]) / 1000;
    if (seconds > 0) card.querySelector(".sample-rate").textContent = `${((times.length - 1) / seconds).toFixed(1)} Hz`;
}

function drawChart(sensorId) {
    const id = String(sensorId);
    const card = cardFor(id);
    const canvas = card?.querySelector(".sensor-chart");
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(rect.width));
    const height = Math.max(1, Math.round(rect.height));
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);

    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const history = state.histories.get(id) || [];
    const empty = card.querySelector(".chart-empty");
    if (history.length < 2) {
        empty.hidden = history.length > 0;
        return;
    }
    empty.hidden = true;

    const values = history.map(item => item.value);
    const observedMin = Math.min(...values);
    const observedMax = Math.max(...values);
    const span = observedMax - observedMin;
    const pad = span > 0 ? span * 0.15 : Math.max(Math.abs(observedMax) * 0.02, 0.05);
    const min = observedMin - pad;
    const max = observedMax + pad;
    const left = 12, right = 12, top = 14, bottom = 14;
    const plotWidth = Math.max(1, width - left - right);
    const plotHeight = Math.max(1, height - top - bottom);
    const css = getComputedStyle(document.documentElement);

    ctx.strokeStyle = css.getPropertyValue("--chart-grid").trim() || "#e7edf2";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
        const y = top + plotHeight * i / 3;
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(width - right, y);
        ctx.stroke();
    }

    const points = history.map((sample, index) => ({
        x: left + plotWidth * index / (history.length - 1),
        y: top + plotHeight * (1 - (sample.value - min) / (max - min)),
    }));

    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) ctx.lineTo(points[i].x, points[i].y);
    ctx.strokeStyle = css.getPropertyValue("--accent").trim() || "#2f6fed";
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();

    const snapshot = state.sensors.get(id) || {};
    const unit = history.at(-1)?.unit || "";
    card.querySelector(".chart-min").textContent = `Min ${formatValue(observedMin, snapshot)} ${unit}`.trim();
    card.querySelector(".chart-max").textContent = `Max ${formatValue(observedMax, snapshot)} ${unit}`.trim();
    card.querySelector(".chart-span").textContent = `Span ${formatValue(span, snapshot)} ${unit}`.trim();
}

async function refreshDigiFlotState() {
    state.digiflot = await requestJson("/api/digiflot/state");
    state.calibrationMode = state.digiflot.state === "SensorCalibration";
    state.maintenanceMode = state.digiflot.state === "Idle";
    setExperimentState(state.digiflot.state);

    el.calibrationBanner.hidden = !state.calibrationMode;
    el.calibrationFooter.hidden = !state.calibrationMode;
    el.pageTitle.textContent = state.calibrationMode ? "Sensor calibration" : "Sensor monitoring & calibration";
    el.pageDescription.textContent = state.calibrationMode
        ? "All configured sensors are monitored simultaneously. Calibrate supported devices while observing their live signals."
        : "Live measurements from every configured sensor. Supported sensors can be calibrated here without creating an experiment.";
}

function bindCalibrationControls(root = document) {
    root.querySelectorAll(".sensor-confirm").forEach(button => {
        if (button.dataset.bound) return;
        button.dataset.bound = "1";
        button.addEventListener("click", async () => {
            button.disabled = true;
            try {
                state.digiflot = await requestJson(`/api/digiflot/calibration/sensors/${encodeURIComponent(button.dataset.sensorId)}/confirm`, { method: "POST" });
                renderCards();
            } catch (error) {
                button.disabled = false;
                showToast(error.message);
            }
        });
    });

    root.querySelectorAll(".sensor-skip").forEach(button => {
        if (button.dataset.bound) return;
        button.dataset.bound = "1";
        button.addEventListener("click", async () => {
            button.disabled = true;
            try {
                state.digiflot = await requestJson(`/api/digiflot/calibration/sensors/${encodeURIComponent(button.dataset.sensorId)}/skip`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ reason: "Operator skipped calibration" }),
                });
                renderCards();
                showToast("Calibration skipped.");
            } catch (error) {
                button.disabled = false;
                showToast(error.message);
            }
        });
    });

    root.querySelectorAll(".ph-calibrate").forEach(button => {
        if (button.dataset.bound) return;
        button.dataset.bound = "1";
        button.addEventListener("click", async () => {
            const card = button.closest(".sensor-card");
            const point = button.dataset.point;
            const input = card.querySelector(`[data-point-value="${point}"]`);
            const value = Number(input.value);
            if (!Number.isFinite(value)) {
                showToast("Enter a valid calibration buffer value.");
                return;
            }
            button.disabled = true;
            button.textContent = "Calibrating…";
            try {
                state.digiflot = await requestJson(`/api/digiflot/calibration/sensors/${encodeURIComponent(button.dataset.sensorId)}/start`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ point, value }),
                });
                renderCards();
            } catch (error) {
                button.disabled = false;
                button.textContent = point === "mid" ? "Calibrate midpoint" : "Calibrate low point";
                showToast(error.message);
            }
        });
    });

    root.querySelectorAll(".standalone-ph-calibrate").forEach(button => {
        if (button.dataset.bound) return;
        button.dataset.bound = "1";
        button.addEventListener("click", async () => {
            const card = button.closest(".sensor-card");
            const point = button.dataset.point;
            const input = card.querySelector(`[data-point-value="${point}"]`);
            const value = Number(input.value);
            if (!Number.isFinite(value)) { showToast("Enter a valid calibration buffer value."); return; }
            button.disabled = true;
            button.textContent = "Calibrating…";
            try {
                await requestJson(`/api/sensors/${encodeURIComponent(button.dataset.sensorId)}/calibrate`, {
                    method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({point, value})
                });
                const progress = state.standaloneCalibration.get(String(button.dataset.sensorId)) || {mid:false, low:false};
                progress[point] = true;
                state.standaloneCalibration.set(String(button.dataset.sensorId), progress);
                renderCards();
                showToast(`${point === "mid" ? "Midpoint" : "Low point"} calibration completed.`);
            } catch (error) {
                button.disabled = false;
                button.textContent = point === "mid" ? "Calibrate midpoint" : "Calibrate low point";
                showToast(error.message);
            }
        });
    });
}

function updateCalibrationProgress() {
    if (!state.calibrationMode || !state.digiflot) return;
    const calibration = state.digiflot.calibration?.sensors || {};
    const snapshots = [...state.sensors.values()];
    const connected = snapshots.filter(item => item.status === "connected");
    const resolved = connected.filter(item => ["passed", "skipped"].includes(calibration[String(item.id)]?.status));
    const skipped = connected.filter(item => calibration[String(item.id)]?.status === "skipped");
    const offline = snapshots.filter(item => item.status !== "connected");

    el.calibrationProgress.textContent = `${resolved.length}/${connected.length} connected sensors ready`;
    const details = [];
    if (skipped.length) details.push(`${skipped.length} skipped by operator`);
    if (offline.length) details.push(`${offline.length} offline`);
    el.calibrationHint.textContent = details.length
        ? `${details.join(" · ")}. Skipped and offline sensors are recorded in the execution metadata.`
        : "Calibrate, check, or explicitly skip each connected sensor.";
    el.finishCalibration.disabled = resolved.length !== connected.length;
}

function connectSensor(snapshot) {
    const sensorId = String(snapshot.id);
    state.streams.get(sensorId)?.close();
    const source = new EventSource(`/api/sensors/${encodeURIComponent(sensorId)}/stream`);
    state.streams.set(sensorId, source);

    source.addEventListener("measurement", event => {
        try { updateCard(JSON.parse(event.data)); } catch (error) { console.error(error); }
    });

    source.onerror = () => {
        // EventSource reconnects automatically. Hardware state is independent
        // from the browser connection, so no device action is taken here.
    };
}

async function loadSensors() {
    const payload = await requestJson("/api/sensors");
    for (const snapshot of payload.sensors || []) {
        state.sensors.set(String(snapshot.id), snapshot);
    }
    renderCards();
    for (const snapshot of state.sensors.values()) connectSensor(snapshot);
}

async function initialise() {
    try {
        await refreshDigiFlotState();
        await loadSensors();
    } catch (error) {
        showToast(error.message);
        el.emptyState.hidden = false;
        el.emptyState.querySelector("h2").textContent = "Unable to load sensors";
        el.emptyState.querySelector("p").textContent = error.message;
    }
}

el.finishCalibration.addEventListener("click", async () => {
    el.finishCalibration.disabled = true;
    try {
        state.digiflot = await requestJson("/api/digiflot/calibration/sensors/complete", { method: "POST" });
        window.location.href = "/run";
    } catch (error) {
        el.finishCalibration.disabled = false;
        showToast(error.message);
    }
});

window.addEventListener("beforeunload", () => {
    for (const source of state.streams.values()) source.close();
});

initialise();
