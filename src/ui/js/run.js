const ui = {};
let latestState = null;
let lastScrapingSequence = null;
let audioContext = null;
let scrapeFlashTimer = null;
const sensorPlotHistory = new Map();
const hiddenSensorPlots = new Set();
const lastSensorPlotTimestamp = new Map();
let measurementData = { revision: 0, count: 0, variables: [], observations: [] };
let measurementFetchInFlight = false;
let measurementSourceSignature = null;

function cacheUi() {
    [
        "experiment_name", "experiment_meta", "state_badge", "state_text",
        "camera_panel", "camera_list", "sensor_panel", "sensor_list",
        "ready_panel", "ready_stage", "start_first_stage", "run_panel",
        "stage_type", "stage_name", "camera_indicator", "sensor_indicator",
        "active_view", "stage_timer", "stage_elapsed", "scraping_box",
        "scraping_timer", "stage_parameters", "transition_view",
        "next_stage_name", "next_stage_message", "transition_timer",
        "start_now_button", "pause_button", "resume_button", "completed_panel",
        "reset_button", "error_panel", "error_title", "error_message",
        "error_reset_button", "abort_bar", "abort_button", "scrape_signal", "toast",
        "device_summary", "performance_summary", "warning_panel", "warning_list",
        "finish_stage_button", "skip_stage_button", "recovery_details", "transition_countdown", "run_performance_link",
        "recovery_actions", "error_close_actions", "retry_devices_button",
        "recovery_resume_button", "restart_stage_button", "recovery_skip_button",
        "recovery_abort_button", "operations_retry_devices",
        "live_sensor_panel", "live_sensor_grid", "measurement_panel",
        "measurement_form", "measurement_variable_name", "measurement_variable_names",
        "measurement_source", "measurement_sensor_value", "measurement_sensor_value_text",
        "measurement_sensor_age", "measurement_manual_fields", "measurement_manual_value",
        "measurement_manual_unit", "capture_measurement_button", "measurement_form_hint",
        "measurement_count", "measurement_summary_body", "measurement_history_body"
    ].forEach((id) => { ui[id] = document.getElementById(id); });
    ui.workflowSteps = [...document.querySelectorAll(".workflow-step")];
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
    ui.toast.textContent = message;
    ui.toast.classList.add("show");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => ui.toast.classList.remove("show"), 2800);
}

function stateClass(value) {
    return `state-${String(value || "muted").replace(/[^a-z0-9]/gi, "").toLowerCase()}`;
}

function setStateBadge(state) {
    ui.state_text.textContent = state;
    ui.state_badge.className = `state-badge ${stateClass(state)}`;
    ui.state_badge.innerHTML = `<span class="state-dot"></span><span id="state_text">${escapeHtml(state)}</span>`;
    ui.state_text = document.getElementById("state_text");
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatTime(seconds) {
    if (seconds == null || !Number.isFinite(Number(seconds))) return "--:--";
    const value = Math.max(0, Math.ceil(Number(seconds)));
    const minutes = Math.floor(value / 60);
    const remaining = value % 60;
    return `${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`;
}

function setWorkflow(state) {
    const order = ["camera", "sensor", "ready", "run"];
    let active = 0;
    if (state === "SensorCalibration") active = 1;
    else if (state === "Ready") active = 2;
    else if (["Running", "Paused", "Completed", "Aborted", "Error", "RecoveryRequired"].includes(state)) active = 3;

    ui.workflowSteps.forEach((element) => {
        const index = order.indexOf(element.dataset.step);
        element.classList.toggle("done", index < active || state === "Completed");
        element.classList.toggle("active", index === active && state !== "Completed");
    });
}

function hidePanels() {
    [ui.camera_panel, ui.sensor_panel, ui.ready_panel, ui.run_panel, ui.completed_panel, ui.error_panel]
        .forEach((panel) => { panel.hidden = true; });
}

function renderCameraCalibration(state) {
    ui.camera_panel.hidden = false;
    const cameras = Object.values(state.calibration?.cameras || {});
    ui.camera_list.innerHTML = cameras.map((camera) => {
        const status = camera.status || "pending";
        const exposure = camera.exposure;
        const exposureText = exposure?.exposure_time_us != null && exposure?.analogue_gain != null
            ? `${exposure.exposure_time_us} µs · gain ${Number(exposure.analogue_gain).toFixed(3)}`
            : (camera.error || "Exposure not calibrated yet");
        const done = ["passed", "skipped"].includes(status);
        const openDisabled = camera.available === false || status === "offline";
        return `
            <article class="calibration-item">
                <div class="calibration-item-head">
                    <div>
                        <h3>${escapeHtml(camera.name)}</h3>
                        <span class="calibration-status ${escapeHtml(status)}">${escapeHtml(status)}</span>
                    </div>
                </div>
                <p>${escapeHtml(exposureText)}</p>
                <div class="button-group compact-actions">
                    ${done ? '<span class="button button-secondary">Resolved</span>' : `
                        ${openDisabled ? '' : `<a class="button button-primary" href="/cameras?camera=${encodeURIComponent(camera.id)}&calibration=1">Open calibration</a>`}
                        <button class="button button-secondary" type="button" data-skip-camera="${escapeHtml(camera.id)}">Skip camera</button>
                    `}
                </div>
            </article>`;
    }).join("") || "<p>No cameras configured.</p>";
}

function findSensorSnapshot(state, id) {
    const scale = (state.scales || []).find((item) => String(item.id) === String(id));
    if (scale) return scale;
    return (state.atlas || []).find((item) => String(item.id) === String(id));
}

function renderSensorCalibration(state) {
    ui.sensor_panel.hidden = false;
    const sensors = Object.values(state.calibration?.sensors || {});
    ui.sensor_list.innerHTML = sensors.map((sensor) => {
        const snapshot = findSensorSnapshot(state, sensor.id) || {};
        const connection = snapshot.status || "unknown";
        const calibration = sensor.status || "pending";
        return `
            <div class="sensor-summary-item">
                <div>
                    <strong>${escapeHtml(sensor.name)}</strong>
                    <span>${escapeHtml(sensor.type || "sensor")}</span>
                </div>
                <div class="sensor-summary-states">
                    <span class="connection-state ${escapeHtml(connection)}">${escapeHtml(connection)}</span>
                    <span class="calibration-status ${escapeHtml(calibration)}">${escapeHtml(calibration)}</span>
                </div>
            </div>`;
    }).join("") || "<p>No sensors configured.</p>";
}

function stageParameters(stage) {
    if (!stage) return "";
    const items = [
        ["Duration", `${stage.duration ?? "—"} s`],
        ["Airflow", `${stage.airflow ?? "—"}`],
        ["Rotor speed", `${stage.rotor_speed ?? "—"} rpm`],
        ["Target pH", stage.ph ?? stage.pH ?? "—"],
    ];
    if (stage.reagent_name) items.push(["Reagent", stage.reagent_name]);
    if (stage.reagent?.concentration != null) items.push(["Concentration", `${stage.reagent.concentration} %`]);
    if (stage.reagent?.volume != null) items.push(["Volume", `${stage.reagent.volume} mL`]);
    return items.map(([label, value]) => `
        <div class="parameter"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
    `).join("");
}

function renderOperations(state) {
    const devices = state.devices || {};
    const all = [
        ...(devices.cameras || []),
        ...(devices.scales || []),
        ...(devices.atlas || []),
    ];
    const online = all.filter((item) => ["connected", "Recording", "Preview", "Idle"].includes(item.status) || item.state === "Recording").length;
    const offline = all.length - online;
    ui.device_summary.innerHTML = `<strong>${online}/${all.length}</strong> available${offline > 0 ? ` · <span class="summary-warning">${offline} unavailable</span>` : ''}`;

    const performance = state.performance || {};
    const perfStatus = performance.status || "UNAVAILABLE";
    const system = performance.system || {};
    const temp = system.temperature_c == null ? "—" : `${Number(system.temperature_c).toFixed(1)} °C`;
    ui.performance_summary.innerHTML = `<strong class="perf-${escapeHtml(perfStatus.toLowerCase())}">${escapeHtml(perfStatus)}</strong> · ${escapeHtml(temp)}`;

    const warnings = state.warnings || [];
    ui.warning_panel.hidden = warnings.length === 0;
    ui.warning_list.innerHTML = warnings.slice(-5).reverse().map((warning) => `
        <div class="warning-row">
            <span>${escapeHtml(warning.source || "system")}</span>
            <p>${escapeHtml(warning.message || "Warning")}</p>
        </div>`).join("");
}

function sensorSnapshots(state) {
    return [
        ...(state.scales || []),
        ...(state.atlas || []),
    ].filter((item) => item && item.id != null);
}

function sensorIsOnline(sensor) {
    return sensor?.status === "connected";
}

function sensorDisplayValue(sensor) {
    const raw = sensor?.value;
    if (raw == null || raw === "" || !Number.isFinite(Number(raw))) return "—";
    const decimals = Number.isFinite(Number(sensor?.decimals)) ? Number(sensor.decimals) : null;
    const value = decimals == null
        ? Number(raw).toLocaleString(undefined, { maximumFractionDigits: 4 })
        : Number(raw).toFixed(Math.max(0, Math.min(6, decimals)));
    return `${value}${sensor?.unit ? ` ${sensor.unit}` : ""}`;
}

function sensorAgeText(sensor) {
    const timestamp = Number(sensor?.timestamp_ms);
    if (!Number.isFinite(timestamp)) return "No sample received";
    const age = Math.max(0, (Date.now() - timestamp) / 1000);
    if (age < 1) return "Updated <1 s ago";
    return `Updated ${age.toFixed(age < 10 ? 1 : 0)} s ago`;
}

function shouldStorePlotSample(sensor) {
    if (hiddenSensorPlots.has(String(sensor.id))) return false;
    const timestamp = Number(sensor.timestamp_ms);
    if (!Number.isFinite(timestamp) || !Number.isFinite(Number(sensor.value))) return false;
    const previous = lastSensorPlotTimestamp.get(String(sensor.id));
    if (previous != null && timestamp - previous < 900) return false;
    lastSensorPlotTimestamp.set(String(sensor.id), timestamp);
    return true;
}

function appendSensorPlotSample(sensor) {
    if (!shouldStorePlotSample(sensor)) return;
    const key = String(sensor.id);
    const history = sensorPlotHistory.get(key) || [];
    history.push({ timestamp: Number(sensor.timestamp_ms), value: Number(sensor.value) });
    while (history.length > 60) history.shift();
    sensorPlotHistory.set(key, history);
}

function drawSensorPlot(canvas, sensorId) {
    if (!canvas || hiddenSensorPlots.has(String(sensorId))) return;
    const history = sensorPlotHistory.get(String(sensorId)) || [];
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const width = Math.max(1, Math.round(rect.width * ratio));
    const height = Math.max(1, Math.round(rect.height * ratio));
    if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
    }
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, width, height);
    if (history.length < 2) return;
    const values = history.map((item) => item.value);
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (max === min) {
        const pad = Math.max(Math.abs(max) * 0.01, 0.1);
        min -= pad;
        max += pad;
    }
    const pad = 4 * ratio;
    const color = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2f6fed";
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6 * ratio;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    history.forEach((item, index) => {
        const x = pad + (index / Math.max(1, history.length - 1)) * (width - 2 * pad);
        const y = height - pad - ((item.value - min) / (max - min)) * (height - 2 * pad);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();
}

function ensureSensorCard(sensor) {
    const key = String(sensor.id);
    let card = ui.live_sensor_grid.querySelector(`[data-live-sensor="${CSS.escape(key)}"]`);
    if (card) return card;
    card = document.createElement("article");
    card.className = "live-sensor-card";
    card.dataset.liveSensor = key;
    card.innerHTML = `
        <div class="live-sensor-head">
            <div>
                <h3></h3>
                <span class="live-sensor-status"></span>
            </div>
            <button class="plot-toggle" type="button" data-plot-toggle="${escapeHtml(key)}">Hide plot</button>
        </div>
        <div class="live-sensor-reading">—</div>
        <div class="live-sensor-age">—</div>
        <div class="sensor-sparkline-wrap"><canvas class="sensor-sparkline" aria-label="Recent sensor values"></canvas></div>`;
    ui.live_sensor_grid.appendChild(card);
    return card;
}

function renderLiveSensors(state) {
    const visible = ["Ready", "Running", "Paused", "Completed", "RecoveryRequired"].includes(state.state);
    ui.live_sensor_panel.hidden = !visible;
    if (!visible) return;

    const sensors = sensorSnapshots(state);
    if (sensors.length > 0) ui.live_sensor_grid.querySelector(".empty-note")?.remove();
    const activeKeys = new Set(sensors.map((item) => String(item.id)));
    [...ui.live_sensor_grid.querySelectorAll("[data-live-sensor]")].forEach((card) => {
        if (!activeKeys.has(card.dataset.liveSensor)) card.remove();
    });

    sensors.forEach((sensor) => {
        appendSensorPlotSample(sensor);
        const card = ensureSensorCard(sensor);
        const hidden = hiddenSensorPlots.has(String(sensor.id));
        card.querySelector("h3").textContent = sensor.name || sensor.id;
        const status = card.querySelector(".live-sensor-status");
        status.textContent = sensor.status || "unknown";
        status.className = `live-sensor-status ${sensorIsOnline(sensor) ? "online" : "offline"}`;
        card.querySelector(".live-sensor-reading").textContent = sensorDisplayValue(sensor);
        card.querySelector(".live-sensor-age").textContent = sensorAgeText(sensor);
        const wrap = card.querySelector(".sensor-sparkline-wrap");
        const toggle = card.querySelector(".plot-toggle");
        wrap.hidden = hidden;
        toggle.textContent = hidden ? "Show plot" : "Hide plot";
        if (!hidden) drawSensorPlot(card.querySelector("canvas"), sensor.id);
    });

    if (sensors.length === 0) {
        ui.live_sensor_grid.innerHTML = '<p class="empty-note">No sensors configured.</p>';
    }
}

function measurementValueText(record) {
    if (!record || record.value == null) return "—";
    const value = Number(record.value).toLocaleString(undefined, { maximumFractionDigits: 6 });
    return `${value}${record.unit ? ` ${record.unit}` : ""}`;
}

function measurementContext(record) {
    if (!record) return "—";
    if (record.stage_name) {
        const state = record.stage_state && record.stage_state !== "None" ? ` / ${record.stage_state}` : "";
        return `${record.stage_name}${state}`;
    }
    return record.state || "—";
}

function renderMeasurementTables() {
    const variables = measurementData.variables || [];
    const observations = measurementData.observations || [];
    ui.measurement_count.textContent = `${measurementData.count || observations.length} point${(measurementData.count || observations.length) === 1 ? "" : "s"}`;
    ui.measurement_variable_names.innerHTML = variables
        .map((item) => `<option value="${escapeHtml(item.name)}"></option>`).join("");

    ui.measurement_summary_body.innerHTML = variables.length
        ? variables.map((item) => `
            <tr class="measurement-variable-row" data-variable-id="${escapeHtml(item.id)}" tabindex="0" role="button" aria-label="Use ${escapeHtml(item.name)} for the next measurement">
                <td><strong>${escapeHtml(item.name)}</strong></td>
                <td>${escapeHtml(measurementValueText(item.latest))}</td>
                <td>${escapeHtml(item.points)}</td>
            </tr>`).join("")
        : '<tr><td colspan="3" class="empty-cell">No measurements captured yet.</td></tr>';

    const recent = observations.slice(-20).reverse();
    ui.measurement_history_body.innerHTML = recent.length
        ? recent.map((item) => {
            const source = item.source_type === "manual" ? "Manual" : (item.sensor_name || item.sensor_id || "Sensor");
            const time = item.captured_at ? new Date(item.captured_at).toLocaleTimeString() : "—";
            return `<tr>
                <td>${escapeHtml(item.variable_name)}</td>
                <td><strong>${escapeHtml(measurementValueText(item))}</strong></td>
                <td>${escapeHtml(source)}</td>
                <td>${escapeHtml(time)}</td>
                <td>${escapeHtml(measurementContext(item))}</td>
            </tr>`;
        }).join("")
        : '<tr><td colspan="5" class="empty-cell">No points captured yet.</td></tr>';
}

function selectMeasurementVariable(variableId) {
    const variable = (measurementData.variables || []).find((item) => String(item.id) === String(variableId));
    if (!variable) return;

    ui.measurement_variable_name.value = variable.name || "";
    const latest = variable.latest || {};

    if (latest.source_type === "sensor" && latest.sensor_id) {
        const option = [...ui.measurement_source.options].find(
            (item) => item.value === String(latest.sensor_id) && !item.disabled
        );
        ui.measurement_source.value = option ? option.value : "manual";
    } else {
        ui.measurement_source.value = "manual";
        ui.measurement_manual_unit.value = latest.unit || "";
    }

    updateMeasurementSourcePreview();
    ui.measurement_variable_name.focus();
}

function currentMeasurementSource() {
    return sensorSnapshots(latestState || {}).find((item) => String(item.id) === String(ui.measurement_source.value));
}

function updateMeasurementSourcePreview() {
    const manual = ui.measurement_source.value === "manual";
    ui.measurement_manual_fields.hidden = !manual;
    ui.measurement_sensor_value.hidden = manual;
    if (manual) {
        ui.measurement_form_hint.textContent = "Manual unit is optional. Experiment state and stage are stored automatically.";
        return;
    }
    const sensor = currentMeasurementSource();
    ui.measurement_sensor_value_text.textContent = sensorDisplayValue(sensor);
    ui.measurement_sensor_age.textContent = sensorAgeText(sensor);
    const timestamp = Number(sensor?.timestamp_ms);
    const stale = !Number.isFinite(timestamp) || Date.now() - timestamp > 5000;
    ui.measurement_sensor_value.classList.toggle("stale", stale);
    ui.measurement_form_hint.textContent = stale
        ? "This sensor value is stale. You can still capture it; its original sensor timestamp will be stored."
        : "The latest in-memory sensor value will be captured without an extra hardware read.";
}

function updateMeasurementSources(state) {
    const sensors = sensorSnapshots(state);
    const signature = JSON.stringify(sensors.map((sensor) => [
        String(sensor.id), sensor.name, sensor.type, sensor.status,
        sensor.value == null ? null : true, sensor.unit || null,
    ]));

    if (signature !== measurementSourceSignature) {
        const previous = ui.measurement_source.value;
        const onlineScale = sensors.find((item) => item.type === "scale" && sensorIsOnline(item) && item.value != null);
        const options = sensors.map((sensor) => {
            const enabled = sensorIsOnline(sensor) && sensor.value != null;
            const label = `${sensor.name || sensor.id}${sensor.unit ? ` (${sensor.unit})` : ""}${enabled ? "" : " — unavailable"}`;
            return `<option value="${escapeHtml(sensor.id)}" ${enabled ? "" : "disabled"}>${escapeHtml(label)}</option>`;
        });
        options.push('<option value="manual">Manual entry</option>');
        ui.measurement_source.innerHTML = options.join("");

        const previousOption = [...ui.measurement_source.options].find((option) => option.value === previous && !option.disabled);
        if (previousOption) ui.measurement_source.value = previous;
        else if (onlineScale) ui.measurement_source.value = String(onlineScale.id);
        else ui.measurement_source.value = "manual";
        measurementSourceSignature = signature;
    }
    updateMeasurementSourcePreview();
}

async function loadMeasurements() {
    if (measurementFetchInFlight) return;
    measurementFetchInFlight = true;
    try {
        const payload = await requestJson("/api/digiflot/measurements");
        measurementData = {
            revision: payload.revision || 0,
            count: payload.count || 0,
            variables: payload.variables || [],
            observations: payload.observations || [],
        };
        renderMeasurementTables();
    } catch (error) {
        console.error(error);
    } finally {
        measurementFetchInFlight = false;
    }
}

function renderMeasurements(state) {
    const visible = ["Ready", "Running", "Paused", "Completed", "RecoveryRequired"].includes(state.state);
    ui.measurement_panel.hidden = !visible;
    if (!visible) return;
    updateMeasurementSources(state);
    const remoteRevision = Number(state.measurements?.revision || 0);
    if (remoteRevision !== Number(measurementData.revision || 0)) loadMeasurements();
}

function renderReady(state) {
    ui.ready_panel.hidden = false;
    const stage = state.next_stage;
    if (!stage) {
        ui.ready_stage.innerHTML = "<h3>No stage available</h3>";
        ui.start_first_stage.disabled = true;
        return;
    }
    ui.ready_stage.innerHTML = `
        <p class="eyebrow">First stage</p>
        <h3>${escapeHtml(stage.name || `Stage ${stage.id}`)}</h3>
        <p>${escapeHtml(stage.type || "")}</p>
        <div class="parameter-grid">${stageParameters(stage)}</div>`;
    ui.start_first_stage.disabled = false;
}

function renderRun(state) {
    ui.run_panel.hidden = false;
    const stage = state.current_stage;
    const paused = state.state === "Paused";
    const transition = state.stage_state === "Transition" || (paused && state.transition_remaining_s != null);

    ui.stage_type.textContent = String(stage?.type || "stage").toUpperCase();
    ui.stage_name.textContent = stage?.name || "Experiment";
    ui.camera_indicator.className = `indicator ${state.recording ? "indicator-rec" : ""}`;
    ui.camera_indicator.textContent = state.recording ? "● CAMERAS REC" : "CAMERAS OFF";
    const sensorRecording = (state.scales || []).some((item) => item.recording) || (state.atlas || []).some((item) => item.recording);
    ui.sensor_indicator.className = `indicator ${sensorRecording ? "indicator-on" : ""}`;
    ui.sensor_indicator.textContent = sensorRecording ? "● SENSORS REC" : "SENSORS PARTIAL/OFF";

    ui.active_view.hidden = transition;
    ui.transition_view.hidden = !transition;
    ui.start_now_button.hidden = !transition;
    ui.pause_button.hidden = paused;
    ui.resume_button.hidden = !paused;
    ui.finish_stage_button.hidden = transition;
    ui.skip_stage_button.hidden = transition;

    if (!transition) {
        ui.stage_timer.textContent = formatTime(state.stage_remaining_s);
        ui.stage_elapsed.textContent = `Elapsed ${formatTime(state.stage_elapsed_s)}`;
        ui.stage_parameters.innerHTML = stageParameters(stage);
        const scraping = state.scraping || {};
        ui.scraping_box.hidden = !scraping.enabled;
        if (scraping.enabled) {
            ui.scraping_timer.textContent = scraping.next_in_s == null ? "—" : `${Math.max(0, Number(scraping.next_in_s)).toFixed(1)} s`;
            const detail = ui.scraping_box.querySelector("span:last-child");
            if (detail) detail.textContent = `Manual scraping signal every ${scraping.interval_s ?? "—"} s`;
        }
    } else {
        const next = state.next_stage;
        ui.next_stage_name.textContent = next?.name || "Next stage";
        ui.next_stage_message.textContent = next
            ? `${next.type || "Stage"} · ${next.duration ?? "—"} s`
            : "No next stage";
        const automatic = state.orchestration?.auto_advance_enabled !== false;
        if (automatic) {
            ui.transition_countdown.innerHTML = `<span>Automatic start in</span><strong id="transition_timer">${Math.max(0, Math.ceil(Number(state.transition_remaining_s || 0)))}</strong><span>seconds</span>`;
            ui.transition_timer = document.getElementById("transition_timer");
        } else {
            ui.transition_countdown.innerHTML = `<span>Automatic advance disabled</span><strong>Waiting</strong><span>Start the next stage when ready.</span>`;
        }
    }
    if (ui.run_performance_link) ui.run_performance_link.hidden = Boolean(state.navigation_locked);
}

function renderCompleted(state) {
    ui.completed_panel.hidden = false;
    const title = ui.completed_panel.querySelector("h2");
    const text = ui.completed_panel.querySelector("p");
    if (state.state === "Aborted") {
        title.textContent = "Experiment aborted";
        text.textContent = "Acquisition was stopped cleanly. Recorded data were kept and this execution can be deleted from the experiment list after closing it.";
    } else {
        title.textContent = "Experiment completed";
        text.textContent = "All available acquisition streams were finalized and the execution metadata was saved.";
    }
}

function renderError(state) {
    ui.error_panel.hidden = false;
    const recovery = state.state === "RecoveryRequired";
    ui.error_title.textContent = recovery ? "Recovery required" : "Experiment stopped";
    ui.error_message.textContent = state.last_error || "The execution cannot continue.";
    ui.recovery_actions.hidden = !recovery;
    ui.error_close_actions.hidden = recovery;
    ui.recovery_details.hidden = !recovery;
    if (recovery) {
        const details = state.recovery || {};
        ui.recovery_details.innerHTML = `
            <div><span>Stage</span><strong>${escapeHtml(state.current_stage?.name || "—")}</strong></div>
            <div><span>Attempt</span><strong>${escapeHtml(state.stage_attempt || 1)}</strong></div>
            <div><span>Elapsed</span><strong>${formatTime(details.stage_elapsed_s ?? state.stage_elapsed_s)}</strong></div>
            <div><span>Source</span><strong>${escapeHtml(details.source || "runtime")}</strong></div>`;
    }
}

function render(state) {
    latestState = state;
    setStateBadge(state.state);
    setWorkflow(state.state);
    renderOperations(state);

    ui.experiment_name.textContent = state.experiment?.name || "Experiment run";
    ui.experiment_meta.textContent = state.storage_id
        ? `Execution ${state.storage_id}`
        : "No local execution selected.";

    hidePanels();
    if (state.state === "CameraCalibration") renderCameraCalibration(state);
    else if (state.state === "SensorCalibration") renderSensorCalibration(state);
    else if (state.state === "Ready") renderReady(state);
    else if (["Running", "Paused"].includes(state.state)) renderRun(state);
    else if (["Completed", "Aborted"].includes(state.state)) renderCompleted(state);
    else if (["Error", "RecoveryRequired"].includes(state.state)) renderError(state);
    else if (state.state === "Idle") {
        ui.error_panel.hidden = false;
        ui.error_title.textContent = "No experiment selected";
        ui.error_message.textContent = "Select an experiment from the experiment list.";
    }

    ui.abort_bar.hidden = !["CameraCalibration", "SensorCalibration", "Ready", "Running", "Paused", "RecoveryRequired"].includes(state.state);
    renderLiveSensors(state);
    renderMeasurements(state);
    handleScrapingSignal(state);
}

function unlockAudio() {
    if (!audioContext) {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (AudioCtx) audioContext = new AudioCtx();
    }
    if (audioContext?.state === "suspended") audioContext.resume();
}

function beep() {
    unlockAudio();
    if (!audioContext) return;
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.22, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioContext.currentTime + 0.22);
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + 0.22);
}

function handleScrapingSignal(state) {
    const sequence = Number(state.scraping?.sequence || 0);
    if (lastScrapingSequence === null) {
        lastScrapingSequence = sequence;
        return;
    }
    if (sequence <= lastScrapingSequence) return;
    lastScrapingSequence = sequence;
    beep();
    ui.scrape_signal.classList.add("show");
    window.clearTimeout(scrapeFlashTimer);
    scrapeFlashTimer = window.setTimeout(() => ui.scrape_signal.classList.remove("show"), 700);
}

async function action(url, body = null) {
    unlockAudio();
    const options = { method: "POST" };
    if (body !== null) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(body);
    }
    try {
        return await requestJson(url, options);
    } catch (error) {
        showToast(error.message);
        throw error;
    }
}

function bindActions() {
    ui.start_first_stage.addEventListener("click", () => action("/api/digiflot/stages/start"));
    ui.start_now_button.addEventListener("click", () => action("/api/digiflot/stages/start"));
    ui.pause_button.addEventListener("click", () => action("/api/digiflot/pause"));
    ui.resume_button.addEventListener("click", () => action("/api/digiflot/resume"));
    ui.finish_stage_button.addEventListener("click", async () => {
        const confirmed = window.confirm("Finish the current stage now and keep it as a valid early completion?");
        if (confirmed) await action("/api/digiflot/stages/finish-now", { reason: "Operator finished stage early" });
    });
    ui.skip_stage_button.addEventListener("click", async () => {
        const confirmed = window.confirm("Skip the current stage? It will be marked as skipped in the event log.");
        if (confirmed) await action("/api/digiflot/stages/skip", { reason: "Operator skipped stage" });
    });
    ui.retry_devices_button.addEventListener("click", () => action("/api/digiflot/recovery/retry-devices"));
    ui.operations_retry_devices.addEventListener("click", () => action("/api/digiflot/recovery/retry-devices"));
    ui.recovery_resume_button.addEventListener("click", () => action("/api/digiflot/recovery/resume"));
    ui.restart_stage_button.addEventListener("click", async () => {
        const confirmed = window.confirm("Restart this stage from zero? The previous attempt remains recorded and will be marked invalid.");
        if (confirmed) await action("/api/digiflot/recovery/restart-stage", { reason: "Operator restarted stage during recovery" });
    });
    ui.recovery_skip_button.addEventListener("click", async () => {
        const confirmed = window.confirm("Skip this stage and continue to the next one?");
        if (confirmed) await action("/api/digiflot/stages/skip", { reason: "Operator skipped stage during recovery" });
    });
    ui.recovery_abort_button.addEventListener("click", async () => {
        const confirmed = window.confirm("Abort this experiment? Recorded data will be kept.");
        if (confirmed) await action("/api/digiflot/abort", { reason: "Operator aborted from recovery" });
    });
    ui.camera_list.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-skip-camera]");
        if (!button) return;
        const cameraId = button.dataset.skipCamera;
        const confirmed = window.confirm("Skip calibration for this camera? It will not be required for this execution.");
        if (confirmed) await action(`/api/digiflot/calibration/cameras/${encodeURIComponent(cameraId)}/skip`, { reason: "Operator skipped camera calibration" });
    });
    ui.reset_button.addEventListener("click", async () => {
        await action("/api/digiflot/reset");
        window.location.href = "/";
    });
    ui.error_reset_button.addEventListener("click", async () => {
        await action("/api/digiflot/reset");
        window.location.href = "/";
    });
    ui.abort_button.addEventListener("click", async () => {
        const confirmed = window.confirm("Abort this experiment? Current acquisition will stop, but recorded data will be kept.");
        if (!confirmed) return;
        await action("/api/digiflot/abort", { reason: "Operator aborted experiment" });
    });

    ui.live_sensor_grid.addEventListener("click", (event) => {
        const button = event.target.closest("[data-plot-toggle]");
        if (!button) return;
        const sensorId = String(button.dataset.plotToggle);
        if (hiddenSensorPlots.has(sensorId)) {
            hiddenSensorPlots.delete(sensorId);
            sensorPlotHistory.delete(sensorId);
            lastSensorPlotTimestamp.delete(sensorId);
        } else {
            hiddenSensorPlots.add(sensorId);
            sensorPlotHistory.delete(sensorId);
            lastSensorPlotTimestamp.delete(sensorId);
        }
        if (latestState) renderLiveSensors(latestState);
    });

    const chooseMeasurementVariable = (event) => {
        const row = event.target.closest("[data-variable-id]");
        if (!row) return;
        selectMeasurementVariable(row.dataset.variableId);
    };
    ui.measurement_summary_body.addEventListener("click", chooseMeasurementVariable);
    ui.measurement_summary_body.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const row = event.target.closest("[data-variable-id]");
        if (!row) return;
        event.preventDefault();
        selectMeasurementVariable(row.dataset.variableId);
    });

    ui.measurement_source.addEventListener("change", updateMeasurementSourcePreview);
    ui.measurement_form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const variableName = ui.measurement_variable_name.value.trim();
        if (!variableName) {
            showToast("Enter a variable name.");
            return;
        }
        const sourceId = ui.measurement_source.value || "manual";
        const payload = {
            variable_name: variableName,
            source_id: sourceId,
        };
        if (sourceId === "manual") {
            if (ui.measurement_manual_value.value.trim() === "") {
                showToast("Enter a manual value.");
                return;
            }
            payload.value = ui.measurement_manual_value.value;
            payload.unit = ui.measurement_manual_unit.value.trim() || null;
        }

        ui.capture_measurement_button.disabled = true;
        try {
            const result = await requestJson("/api/digiflot/measurements", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            measurementData.observations = [...(measurementData.observations || []), result.record];
            measurementData.revision = result.measurements?.revision || measurementData.revision;
            measurementData.count = result.measurements?.count || measurementData.observations.length;
            measurementData.variables = result.measurements?.variables || measurementData.variables;
            renderMeasurementTables();
            ui.measurement_manual_value.value = "";
            showToast(`Captured ${result.record.variable_name}: ${measurementValueText(result.record)}`);
        } catch (error) {
            showToast(error.message);
        } finally {
            ui.capture_measurement_button.disabled = false;
        }
    });
}

function connectStateStream() {
    const source = new EventSource("/api/digiflot/stream");
    source.addEventListener("state", (event) => {
        try { render(JSON.parse(event.data)); } catch (error) { console.error(error); }
    });
    source.onerror = async () => {
        source.close();
        try {
            render(await requestJson("/api/digiflot/state"));
        } catch (_) {}
        window.setTimeout(connectStateStream, 1200);
    };
}

async function initialise() {
    cacheUi();
    bindActions();
    try {
        render(await requestJson("/api/digiflot/state"));
        await loadMeasurements();
    } catch (error) {
        showToast(error.message);
    }
    connectStateStream();
}

document.addEventListener("DOMContentLoaded", initialise);
