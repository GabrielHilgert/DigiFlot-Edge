const ui = {};
let latestState = null;
let physicalCells = [];
let physicalCellChoicesSignature = "";
let lastScrapingSequence = null;
let audioContext = null;
let scrapeFlashTimer = null;
const sensorPlotHistory = new Map();
const hiddenSensorPlots = new Set();
const lastSensorPlotTimestamp = new Map();
let measurementData = { revision: 0, count: 0, variables: [], observations: [] };
let measurementFetchInFlight = false;
let measurementSourceSignature = null;
let requiredInputsSignature = null;
let stageTimelineSignature = null;
let readyViewSignature = null;
let runStorageEstimateFor = null;
let monitorFrameRevision = 0, monitorFrame = null, monitorBusy = false, monitorRunId = null;
let imageHidden = false, measurementOpen = false;
try {
    imageHidden = window.localStorage?.getItem("digiflot-hide-froth-image") === "1";
    measurementOpen = window.sessionStorage?.getItem("digiflot-data-acquisition-open") === "1";
} catch (_) { /* Browser private mode: fall back to hidden data tab. */ }

function cacheUi() {
    [
        "experiment_name", "experiment_meta", "state_badge", "state_text",
        "cell_panel", "select_physical_cell_form", "select_physical_cell", "select_virtual_camera",
        "camera_panel", "camera_list", "sensor_panel", "sensor_list",
        "ready_panel", "ready_stage", "start_first_stage", "run_panel",
        "stage_type", "stage_name", "camera_indicator", "sensor_indicator",
        "active_view", "stage_timer", "stage_elapsed", "scraping_box", "scraping_alerts_enabled",
        "scraping_timer", "stage_parameters", "transition_view",
        "next_stage_name", "next_stage_message", "transition_timer",
        "start_now_button", "pause_button", "resume_button", "completed_panel",
        "reset_button", "error_panel", "error_title", "error_message",
        "error_reset_button", "abort_bar", "abort_button", "scrape_signal", "toast",
        "device_summary", "performance_summary", "warning_panel", "warning_list",
        "run_disk_free", "run_storage_estimate", "run_storage_status",
        "finish_stage_button", "skip_stage_button", "recovery_details", "transition_countdown", "run_performance_link",
        "recovery_actions", "error_close_actions", "retry_devices_button",
        "recovery_resume_button", "restart_stage_button", "recovery_skip_button",
        "recovery_abort_button", "operations_retry_devices",
        "live_sensor_panel", "live_sensor_grid", "measurement_panel",
        "measurement_launcher", "toggle_measurement_panel",
        "measurement_form", "measurement_variable_name", "measurement_variable_names",
        "measurement_source", "measurement_value_type", "measurement_sensor_value", "measurement_sensor_value_text",
        "measurement_sensor_age", "measurement_manual_fields", "measurement_manual_value", "measurement_manual_text",
        "measurement_manual_unit", "capture_measurement_button", "measurement_form_hint", "required_inputs_panel",
        "measurement_count", "measurement_summary_body", "measurement_history_body",
        "calibration_review_panel", "calibration_review_list", "run_stage_timeline", "run_stage_position"
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

function formatRunBytes(value) {
    const bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return "—";
    return `${(bytes / (1024 ** 3)).toFixed(2)} GiB`;
}

async function refreshRunStorage() {
    if (document.hidden) return;
    try {
        const data = await requestJson("/api/digiflot/system/health");
        ui.run_disk_free.textContent = formatRunBytes(data.storage?.free_bytes);
        const sample = data.system || {};
        const timestamp = Date.parse(sample.timestamp || "");
        const stale = !data.telemetry?.running || !Number.isFinite(timestamp)
            || Date.now() - timestamp > Math.max(60000, Number(data.telemetry?.experiment_interval_s || 10) * 2500);
        const critical = Number(data.storage?.free_bytes) < 2 ** 30 * Number(data.storage?.min_free_gb ?? 2);
        ui.run_storage_status.textContent = stale ? "Telemetry unavailable" : (critical ? "Critical disk space" : "Monitoring");
    } catch (error) {
        ui.run_storage_status.textContent = "Unavailable";
    }
}

async function refreshRunEstimate(state) {
    const key = state.storage_id;
    if (!key || key === runStorageEstimateFor || !Array.isArray(state.stages) || !state.stages.length) return;
    runStorageEstimateFor = key;
    try {
        const value = await requestJson("/api/digiflot/storage/estimate", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ experiment: { stages: state.stages } }),
        });
        if (runStorageEstimateFor === key) ui.run_storage_estimate.textContent = formatRunBytes(value.estimated_bytes);
    } catch (_) {
        if (runStorageEstimateFor === key) ui.run_storage_estimate.textContent = "Unavailable";
    }
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

function setWorkflow(data) {
    const order=["experiment","camera","references","sensor","froth","ready","run"];
    const state=data.state||"Idle", calibrated=Object.values(data.calibration?.sensors||{});
    const physical=calibrated.filter(s=>s.type!=="virtual_froth_interface");
    const physicalReady=physical.every(s=>["passed","skipped"].includes(s.status));
    let active=0;
    if(state==="CameraCalibration")active=1;
    else if(state==="SensorCalibration")active=!data.cell_selection?.references?.ready?2:!physicalReady?3:4;
    else if(state==="Ready")active=5;
    else if(["Running","Paused","Completed","Aborted","Error","RecoveryRequired"].includes(state))active=6;
    ui.workflowSteps.forEach(element=>{
        const index=order.indexOf(element.dataset.step);
        element.classList.toggle("done",index<active||state==="Completed");
        element.classList.toggle("active",index===active&&state!=="Completed");
    });
}

function hidePanels() {
    [ui.cell_panel, ui.camera_panel, ui.sensor_panel, ui.ready_panel, ui.run_panel, ui.completed_panel, ui.error_panel]
        .forEach((panel) => { panel.hidden = true; });
}

async function loadPhysicalCells() {
    try {
        const payload = await requestJson("/api/vision/cells");
        physicalCells = Array.isArray(payload) ? payload : (payload.cells || []);
        physicalCellChoicesSignature = "";
        if (latestState?.state === "CellSelection") renderCellSelection(latestState);
    } catch (error) { console.warn("Unable to load physical cells", error); }
}

function renderCellSelection(state) {
    ui.cell_panel.hidden = false;
    const cameras = state.cameras || [];
    const signature = JSON.stringify([physicalCells, cameras.map(camera => [camera.id, camera.name])]);
    if (signature === physicalCellChoicesSignature) return;
    physicalCellChoicesSignature = signature;
    const selectedId = state.cell_selection?.cell_id || state.execution_inputs?.cell_profile?.physical_cell_id || "";
    const selectedCamera = state.cell_selection?.camera_id ?? state.execution_inputs?.cell_profile?.virtual_camera_id;
    ui.select_physical_cell.innerHTML = '<option value="">Select a cell</option>' +
        physicalCells.map(cell => `<option value="${escapeHtml(cell.id)}">${escapeHtml(cell.name)} (${escapeHtml(cell.id)})</option>`).join("");
    ui.select_virtual_camera.innerHTML = '<option value="">Auto-select camera</option><option value="none">No virtual sensor</option>' +
        cameras.map(cam => `<option value="${escapeHtml(cam.id)}">${escapeHtml(cam.name)} · Camera ${escapeHtml(cam.id)}</option>`).join("");
    ui.select_physical_cell.value = selectedId;
    ui.select_virtual_camera.value = selectedCamera == null ? "" : String(selectedCamera);
    updateSelectedCellVolume();
}

function updateSelectedCellVolume() {
    const id=ui.select_physical_cell.value,cell=physicalCells.find(c=>String(c.id)===String(id));
    const target=document.getElementById("selected_cell_volume");
    if(!target)return;
    const input=document.getElementById("cell_volume_override");
    if(input && document.activeElement!==input)
        input.value=cell?.working_volume_l==null?"":String(cell.working_volume_l);
    target.textContent=cell ? (cell.working_volume_l!=null ?
        "Working cell volume: "+Number(cell.working_volume_l).toLocaleString()+" L (inherited; editable override in Ready)." :
        "This cell has no stored working volume. Set it in Cells or provide it before Run.") :
        "Select a cell to inherit its working volume and physical references.";
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
                    ${done ? `${openDisabled ? '<span class="button button-secondary">Unavailable</span>' : `<button class="button button-secondary" type="button" data-edit-camera="${escapeHtml(camera.id)}">Edit calibration</button>`}` : `
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
    return (state.atlas || []).find((item) => String(item.id) === String(id)) ||
        (state.virtual_sensors || []).find((item) => String(item.id) === String(id));
}

function renderSensorCalibration(state) {
    ui.sensor_panel.hidden = false;
    const refs=state.cell_selection?.references;
    const cellId=state.cell_selection?.cell_id||"";
    const cameraId=state.cell_selection?.camera_id??"";
    const anchor=document.getElementById("open_cell_references");
    anchor.href="/cells?cell="+encodeURIComponent(cellId)+"&camera="+encodeURIComponent(cameraId);
    document.getElementById("run_reference_state").textContent=refs?
        (refs.ready?"Default: "+refs.default_name+" · "+refs.count+" named references · revision "+refs.revision:
        "Default reference "+refs.default_name+" is not calibrated. Open Cells and place it before the Froth Interface test.") :
        "Select a physical cell and calibrate its named references first.";
    const sensors = Object.values(state.calibration?.sensors || {});
    ui.sensor_list.innerHTML = sensors.map((sensor) => {
        const snapshot = findSensorSnapshot(state, sensor.id) || {};
        const connection = snapshot.status || "unknown";
        const calibration = sensor.status || "pending";
        const virtual = sensor.type === "virtual_froth_interface";
        const type = virtual ? "Virtual sensor · Froth interface" : (sensor.type || "Sensor").replaceAll("_", " ");
        const origin = virtual ? `Camera ${sensor.source_camera_id ?? snapshot.source_camera_id ?? "—"} · ${state.cell_selection?.cell_name || state.execution_inputs?.cell_profile?.cell_name || "Selected cell"}` : "";
        const calibrationLabel = calibration === "passed" ? "Calibrated" : calibration === "pending" && virtual ? "Test required" : calibration.replaceAll("_", " ");
        return `
            <div class="sensor-summary-item ${virtual ? "virtual-sensor-summary" : ""}">
                <div>
                    <strong>${escapeHtml(sensor.name)}</strong>
                    <span class="sensor-kind">${escapeHtml(type)}</span>
                    ${origin ? `<span class="sensor-origin">${escapeHtml(origin)}</span>` : ""}
                </div>
                <div class="sensor-summary-states">
                    <span class="connection-state ${escapeHtml(connection)}">${escapeHtml(connection === "connected" && virtual ? "Camera connected" : connection)}</span>
                    <span class="calibration-status ${escapeHtml(calibration)}">${escapeHtml(calibrationLabel)}</span>
                </div>
            </div>`;
    }).join("") || "<p>No sensors configured.</p>";
}

function humanizeStageKey(key) {
    return String(key || "")
        .replaceAll("_", " ")
        .replace(/\b\w/g, char => char.toUpperCase());
}

function stageParameters(stage, state = null) {
    if (!stage) return "";
    const items = [];
    const push = (label, value) => {
        if (value === null || value === undefined || value === "" || typeof value === "object") return;
        items.push([label, value]);
    };

    push("Stage ID", stage.id);
    push("Attempt", state?.stage_attempt);
    push("Type", stage.type);
    push("Planned duration", stage.duration == null ? null : `${stage.duration} s`);
    push("Airflow", stage.airflow == null ? null : `${stage.airflow} L/min`);
    push("Rotor speed", stage.rotor_speed == null ? null : `${stage.rotor_speed} rpm`);
    push("Target pH", stage.ph ?? stage.pH);
    push("Reagent", stage.reagent_name || stage.reagent?.name);
    push("Concentration", stage.reagent?.concentration == null ? null : `${stage.reagent.concentration} %`);
    push("Volume", stage.reagent?.volume == null ? null : `${stage.reagent.volume} mL`);

    const known = new Set([
        "id", "name", "type", "duration", "airflow", "rotor_speed", "ph", "pH",
        "reagent_name", "reagent", "reagent_id", "policy",
    ]);
    for (const [key, value] of Object.entries(stage)) {
        if (known.has(key) || value === null || value === undefined || value === "" || typeof value === "object") continue;
        push(humanizeStageKey(key), typeof value === "boolean" ? (value ? "Yes" : "No") : value);
    }
    return items.map(([label, value]) => `
        <div class="parameter"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
    `).join("");
}

function renderCalibrationReview(state) {
    if (!ui.calibration_review_panel || !ui.calibration_review_list) return;
    const visible = ["SensorCalibration", "Ready"].includes(state.state);
    ui.calibration_review_panel.hidden = !visible;
    if (!visible) return;

    const items = [];
    for (const camera of Object.values(state.calibration?.cameras || {})) {
        const status = camera.status || "pending";
        const editable = camera.available !== false && ["passed", "skipped"].includes(status);
        items.push(`<div class="calibration-review-item"><span class="review-kind">Camera</span><strong>${escapeHtml(camera.name || `Camera ${camera.id}`)}</strong><span class="calibration-status ${escapeHtml(status)}">${escapeHtml(status)}</span>${editable ? `<button class="button button-secondary button-small" type="button" data-edit-camera="${escapeHtml(camera.id)}">Edit</button>` : ""}</div>`);
    }
    for (const sensor of Object.values(state.calibration?.sensors || {})) {
        const status = sensor.status || "pending";
        const editable = ["passed", "skipped"].includes(status);
        items.push(`<div class="calibration-review-item"><span class="review-kind">Sensor</span><strong>${escapeHtml(sensor.name || sensor.id)}</strong><span class="calibration-status ${escapeHtml(status)}">${escapeHtml(status)}</span>${editable ? `<button class="button button-secondary button-small" type="button" data-edit-sensor="${escapeHtml(sensor.id)}">Edit</button>` : ""}</div>`);
    }
    ui.calibration_review_list.innerHTML = items.join("") || `<span class="review-empty">No calibration entries.</span>`;
}

function renderMiniStageTimeline(state) {
    if (!ui.run_stage_timeline) return;
    const stages = Array.isArray(state.stages) ? state.stages : [];
    const currentIndex = Number.isInteger(state.current_stage_index) ? state.current_stage_index : -1;
    const signature = JSON.stringify([stages, currentIndex, state.stage_state, state.state === "Paused"]);
    if (signature === stageTimelineSignature) return;
    stageTimelineSignature = signature;
    if (!stages.length) {
        ui.run_stage_timeline.innerHTML = `<span class="mini-stage-empty">No stage metadata available.</span>`;
        if (ui.run_stage_position) ui.run_stage_position.textContent = "—";
        return;
    }
    if (ui.run_stage_position) {
        const displayIndex = currentIndex >= 0 ? currentIndex + 1 : 1;
        ui.run_stage_position.textContent = `Stage ${displayIndex} of ${stages.length}`;
    }
    const transition = state.stage_state === "Transition" || (state.state === "Paused" && state.transition_remaining_s != null);
    ui.run_stage_timeline.innerHTML = stages.map((stage, index) => {
        let klass = "upcoming";
        if (index < currentIndex) klass = "done";
        else if (index === currentIndex) klass = transition ? "done current-complete" : "current";
        else if (transition && index === currentIndex + 1) klass = "next";
        const duration = Math.max(1, Number(stage.duration) || 1);
        return `<div class="mini-stage-segment ${klass}" style="--stage-weight:${duration}" title="${escapeHtml(stage.name || `Stage ${index + 1}`)} · ${escapeHtml(stage.type || "stage")}"><span>${escapeHtml(stage.name || `Stage ${index + 1}`)}</span><small>${escapeHtml(stage.type || "")}</small></div>`;
    }).join("");
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
        ...(state.virtual_sensors || []),
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
    if (sensor?.timestamp_ms == null) return "Awaiting live measurement";
    const timestamp = Number(sensor.timestamp_ms);
    if (!Number.isFinite(timestamp)) return "No sample received";
    const age = Math.max(0, (Date.now() - timestamp) / 1000);
    if (age < 1) return "Updated <1 s ago";
    return `Updated ${age.toFixed(age < 10 ? 1 : 0)} s ago`;
}

function shouldStorePlotSample(sensor) {
    if (hiddenSensorPlots.has(String(sensor.id)) || sensor.timestamp_ms == null) return false;
    const timestamp = Number(sensor.timestamp_ms);
    if (!Number.isFinite(timestamp)) return false;
    const virtual = sensor.type === "virtual_froth_interface";
    const usable = virtual
        ? [sensor.channels?.froth_surface_cm, sensor.channels?.pulp_froth_interface_cm]
            .some(value => value != null && Number.isFinite(Number(value)))
        : sensor.value != null && Number.isFinite(Number(sensor.value));
    if (!usable) return false;
    const previous = lastSensorPlotTimestamp.get(String(sensor.id));
    if (previous != null && timestamp - previous < 900) return false;
    lastSensorPlotTimestamp.set(String(sensor.id), timestamp);
    return true;
}

function appendSensorPlotSample(sensor) {
    if (!shouldStorePlotSample(sensor)) return;
    const key = String(sensor.id), history = sensorPlotHistory.get(key) || [];
    const numeric = value => value == null || !Number.isFinite(Number(value)) ? null : Number(value);
    const virtual = sensor.type === "virtual_froth_interface";
    history.push({timestamp:Number(sensor.timestamp_ms), value:numeric(sensor.value), virtual,
        upper:virtual ? numeric(sensor.channels?.froth_surface_cm) : null,
        lower:virtual ? numeric(sensor.channels?.pulp_froth_interface_cm) : null});
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
        canvas.width = width; canvas.height = height;
    }
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, width, height);
    if (history.length < 2) return;
    const virtual = history.at(-1).virtual;
    const series = virtual ? [["upper","#0ea5e9"],["lower","#f59e0b"]] : [["value",null]];
    const values = history.flatMap(item => series.map(([key]) => item[key])).filter(value => value != null);
    if (!values.length) return;
    let min = Math.min(...values), max = Math.max(...values);
    if (max === min) { const pad=Math.max(Math.abs(max)*.01,.1); min-=pad;max+=pad; }
    const pad = 4 * ratio, fallback = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#2f6fed";
    ctx.lineWidth = 1.6 * ratio; ctx.lineJoin = "round"; ctx.lineCap = "round";
    for (const [key,color] of series) {
        ctx.beginPath(); let started=false;
        history.forEach((item,index) => {
            const value=item[key];
            if(value==null){started=false;return;}
            const x=pad+index/Math.max(1,history.length-1)*(width-2*pad);
            const y=height-pad-(value-min)/(max-min)*(height-2*pad);
            if(!started){ctx.moveTo(x,y);started=true;}else ctx.lineTo(x,y);
        });
        ctx.strokeStyle=color||fallback;ctx.stroke();
    }
}

function ensureSensorCard(sensor) {
    const key = String(sensor.id);
    let card = ui.live_sensor_grid.querySelector(`[data-live-sensor="${CSS.escape(key)}"]`);
    if (card) return card;
    card = document.createElement("article");
    const virtual = sensor.type === "virtual_froth_interface";
    card.className = "live-sensor-card" + (virtual ? " live-sensor-card-wide" : "");
    card.dataset.liveSensor = key;
    card.innerHTML = virtual ? `
        <div class="live-sensor-head"><div><h3></h3><span class="live-sensor-status"></span></div>
            <div class="run-virtual-actions">
                <button class="plot-toggle" type="button" data-image-toggle="1">Hide image</button>
                <button class="plot-toggle" type="button" data-plot-toggle="${escapeHtml(key)}">Hide plot</button>
            </div></div>
        <div class="run-virtual-layout">
            <div class="run-virtual-image-frame"><div class="run-virtual-image-surface">
                <img class="run-virtual-image" alt="Last detected rectified froth ROI" draggable="false">
                <canvas class="run-virtual-overlay" aria-hidden="true"></canvas></div>
                <span class="run-virtual-frame-age">Waiting for image…</span></div>
            <div class="run-virtual-side">
                <span class="run-virtual-value-label">Froth thickness</span>
                <div class="live-sensor-reading">—</div>
                <div class="run-virtual-boundaries"><span>Froth surface <strong class="run-virtual-froth">—</strong></span>
                    <span>Pulp–froth interface <strong class="run-virtual-pulp">—</strong></span></div>
                <div class="live-sensor-age">—</div>
                <div class="sensor-sparkline-wrap"><canvas class="sensor-sparkline" aria-label="Recent interface positions"></canvas></div>
            </div></div>` : `
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
        if (sensor.type === "virtual_froth_interface") {
            card.classList.toggle("live-sensor-card-wide", !imageHidden);
            card.classList.toggle("virtual-image-hidden", imageHidden);
            card.querySelector(".run-virtual-image-frame").hidden = imageHidden;
            card.querySelector("[data-image-toggle]").textContent = imageHidden ? "Show image" : "Hide image";
        }
        card.querySelector("h3").textContent = sensor.name || sensor.id;
        const status = card.querySelector(".live-sensor-status");
        status.textContent = sensor.status || "unknown";
        status.className = `live-sensor-status ${sensorIsOnline(sensor) ? "online" : "offline"}`;
        if (sensor.type === "virtual_froth_interface") {
            const display = key => sensor.channels?.[key] == null ? "—" : `${Number(sensor.channels[key]).toFixed(2)} cm`;
            card.querySelector(".live-sensor-reading").textContent = display("froth_thickness_cm").replace("—",sensor.value==null?"—":Number(sensor.value).toFixed(2)+" cm");
            card.querySelector(".run-virtual-froth").textContent=display("froth_surface_cm");
            card.querySelector(".run-virtual-pulp").textContent=display("pulp_froth_interface_cm");
            card.querySelector(".live-sensor-reading").classList.add("virtual-live-reading");
            status.textContent = sensor.measurement_mode === "experiment" ? "Live · experiment" :
                sensor.measurement_mode === "preview" ? "Live · preview" : "Waiting for lores";
        } else {
            card.querySelector(".live-sensor-reading").textContent = sensorDisplayValue(sensor);
        }
        card.querySelector(".live-sensor-age").textContent = sensorAgeText(sensor);
        const wrap = card.querySelector(".sensor-sparkline-wrap");
        const toggle = card.querySelector(".plot-toggle");
        wrap.hidden = hidden;
        toggle.textContent = hidden ? "Show plot" : "Hide plot";
        if (!hidden) drawSensorPlot(card.querySelector(".sensor-sparkline"), sensor.id);
        if (sensor.type === "virtual_froth_interface" && monitorFrame && !imageHidden)
            updateRunMonitorFrame(card, monitorFrame);
    });

    if (sensors.length === 0) {
        ui.live_sensor_grid.innerHTML = '<p class="empty-note">No sensors configured.</p>';
    }
}


function drawRunMonitorOverlay(card, frame) {
    const canvas=card.querySelector(".run-virtual-overlay"), ctx=canvas.getContext("2d");
    const [w,h]=frame.source_size;
    canvas.width=w;canvas.height=h;ctx.clearRect(0,0,w,h);
    for(const [key,color] of [["froth_row_px","#38bdf8"],["pulp_row_px","#fbbf24"]]){
        const y=frame[key];
        if(y==null||!Number.isFinite(Number(y)))continue;
        ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.lineWidth=Math.max(1.5,w/170);
        ctx.strokeStyle=color;ctx.stroke();
    }
}

function updateRunMonitorFrame(card, frame) {
    if(!frame||!card)return;
    const image=card.querySelector(".run-virtual-image");
    if(!image||image.dataset.revision===String(frame.revision))return;
    const surface=card.querySelector(".run-virtual-image-surface"),[w,h]=frame.source_size;
    surface.style.aspectRatio=w+" / "+h;
    const available=card.querySelector(".run-virtual-image-frame").clientWidth||280;
    const viewWidth=Math.min(available,Math.round(215*w/h));
    surface.style.width=viewWidth+"px";
    surface.style.height=Math.round(viewWidth*h/w)+"px";
    image.onload=()=>drawRunMonitorOverlay(card,frame);
    image.dataset.revision=String(frame.revision);
    image.src="data:image/jpeg;base64,"+frame.jpeg_base64;
    const time=new Date(frame.timestamp_ns/1e6).toLocaleTimeString();
    card.querySelector(".run-virtual-frame-age").textContent=
        (frame.valid?"Detection image":"Detection invalid")+" · "+time;
}

async function pollRunMonitor() {
    if(monitorBusy||document.hidden||ui.live_sensor_panel.hidden||!latestState||
        !["Ready","Running","Paused","Completed"].includes(latestState.state))return;
    const card=ui.live_sensor_grid.querySelector(".live-sensor-card-wide");
    if(!card || imageHidden || !card.isConnected || card.getBoundingClientRect().bottom < 0 ||
        card.getBoundingClientRect().top > window.innerHeight)return;
    monitorBusy=true;
    try {
        const width=Math.max(96,Math.min(512,Math.ceil(card.querySelector(".run-virtual-image-frame").clientWidth*
            Math.min(window.devicePixelRatio||1,1.5))));
        const payload=await requestJson("/api/vision/virtual-sensors/froth-interface/monitor",
            {method:"POST",headers:{"Content-Type":"application/json"},
             body:JSON.stringify({width,last_revision:monitorFrameRevision})});
        if(!payload?.enabled)return;
        if(payload.frame){
            if(String(payload.frame.cell_id)!==String(latestState.cell_selection?.cell_id))return;
            monitorFrameRevision=payload.revision;monitorFrame=payload.frame;
            monitorFrame.revision=payload.revision;
            updateRunMonitorFrame(card,monitorFrame);
        } else if(payload.error)card.querySelector(".run-virtual-frame-age").textContent=
            "Image unavailable (measurements continue): "+payload.error;
        if(monitorFrame){
            const age=Math.max(0,Math.floor(Date.now()/1000-monitorFrame.timestamp_ns/1e9));
            const label=card.querySelector(".run-virtual-frame-age");
            label.textContent=(monitorFrame.valid?"Detection image":"Detection invalid")+
                " · "+age+" s old"+(age>12?" · STALE":"");
            label.classList.toggle("stale",age>12);
        }
    } catch(error){
        card.querySelector(".run-virtual-frame-age").textContent=
            "Preview unavailable; measurements continue";
    } finally {monitorBusy=false;}
}

function measurementValueText(record) {
    if (!record || record.value == null) return "—";
    if (record.value_type === "text" || typeof record.value === "string" && !Number.isFinite(Number(record.value))) {
        return String(record.value);
    }
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
    const variable = (measurementData.variables || []).find(item => String(item.id) === String(variableId));
    if (!variable) return;
    ui.measurement_variable_name.value = variable.name || "";
    const input = (latestState?.execution_inputs?.items || []).find(item => item.id === variable.id);
    const expected = input?.unit || variable.unit || variable.latest?.unit || "";
    const accepted = variable.id === "feed_mass" ? ["g","kg","mg"] :
        variable.id === "water_volume" ? ["l","ml","m3","m³"] :
        expected ? [expected.toLowerCase()] : [];
    const matching = sensorSnapshots(latestState || {}).find(sensor =>
        sensorIsOnline(sensor) && sensor.value != null &&
        accepted.includes(String(sensor.unit || "").trim().toLowerCase()));
    const recentId = variable.latest?.source_type === "sensor" ? variable.latest.sensor_id : null;
    const recent = [...ui.measurement_source.options].find(option =>
        option.value === String(recentId) && !option.disabled);
    ui.measurement_value_type.value = "number";
    ui.measurement_source.value = recent?.value || (matching ? String(matching.id) : "manual");
    ui.measurement_manual_unit.value = expected;
    updateMeasurementSourcePreview();
    ui.measurement_variable_name.focus();
}

function currentMeasurementSource() {
    return sensorSnapshots(latestState || {}).find((item) => String(item.id) === String(ui.measurement_source.value));
}

function updateMeasurementSourcePreview() {
    const textMode = ui.measurement_value_type?.value === "text";
    if (textMode && ui.measurement_source.value !== "manual") ui.measurement_source.value = "manual";
    const manual = ui.measurement_source.value === "manual";
    ui.measurement_source.disabled = textMode;
    ui.measurement_manual_fields.hidden = !manual;
    ui.measurement_sensor_value.hidden = manual;
    ui.measurement_manual_value.hidden = textMode;
    ui.measurement_manual_text.hidden = !textMode;
    ui.measurement_manual_unit.closest(".form-field").hidden = textMode;
    if (manual) {
        ui.measurement_form_hint.textContent = textMode
            ? "Text notes are timestamped with the current experiment and stage context."
            : "Manual unit is optional. Experiment state and stage are stored automatically.";
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

function updateRequiredSensorLabels(state) {
    const sensors = new Map(sensorSnapshots(state).map(sensor => [String(sensor.id), sensor]));
    ui.required_inputs_panel?.querySelectorAll("[data-required-source] option").forEach(option => {
        const sensor = sensors.get(option.value);
        if (sensor) option.textContent = `${sensor.name || sensor.id} · ${sensorDisplayValue(sensor)}`;
    });
}

function renderRequiredInputs(state, {force = false, savedField = null} = {}) {
    const panel = ui.required_inputs_panel;
    if (!panel) return;
    const data = state.execution_inputs || {};
    const items = data.items || [];
    const suggestions = data.cell_suggestions || [];
    if (!items.length) {
        panel.hidden = true;
        requiredInputsSignature = null;
        return;
    }
    panel.hidden = false;
    // Live sensor values are deliberately excluded: changing the plot must
    // never replace input DOM nodes or discard an operator's unsaved text.
    const sensorStructure = sensorSnapshots(state).map(sensor => [
        String(sensor.id), sensor.name, sensor.unit, sensor.status, sensor.value != null,
    ]);
    const signature = JSON.stringify([data, sensorStructure]);
    if (!force && signature === requiredInputsSignature) {
        updateRequiredSensorLabels(state);
        return;
    }
    // If a sensor appears or a remote input changes while someone is typing,
    // defer reconciliation until focus leaves this panel.
    if (!force && panel.contains(document.activeElement)) {
        updateRequiredSensorLabels(state);
        return;
    }

    const drafts = new Map();
    panel.querySelectorAll("input[data-required-value], #execution_cell_name").forEach(input => {
        const key = input.id === "execution_cell_name" ? "cell" : input.dataset.requiredValue;
        const changed = input.value !== input.defaultValue ||
            (key === "cell" && input.dataset.physicalId !== input.getAttribute("data-physical-id"));
        if (changed && key !== savedField) {
            drafts.set(key, {value: input.value, physicalId: input.dataset.physicalId});
        }
    });
    const selectedSources = new Map();
    panel.querySelectorAll("[data-required-source]").forEach(select => {
        if (select.dataset.requiredSource !== savedField) {
            selectedSources.set(select.dataset.requiredSource, select.value);
        }
    });
    const selectedCell = panel.querySelector("#execution_cell_suggestion")?.value ?? "";
    const profile = data.cell_profile || {};
    const derived = Object.values(data.derived_metrics || {}).filter(item => item && Number.isFinite(Number(item.value)));
    const derivedMarkup = derived.length ? `
        <div class="required-inputs-heading">
            <div><strong>Derived from available measurements</strong><span>Estimates only; original inputs and observations are unchanged.</span></div>
        </div>
        <div class="required-input-grid">
            ${derived.map(item => {
                const isFraction = item.unit === "fraction";
                const value = isFraction ? Number(item.value) * 100 : Number(item.value);
                const unit = isFraction ? "%" : (item.unit || "");
                return `<div class="required-input-item complete">
                    <label>${escapeHtml(item.label || "Derived value")}</label>
                    <strong>${escapeHtml(value.toLocaleString(undefined, {maximumFractionDigits: 3}))} ${escapeHtml(unit)}</strong>
                    <small>Calculated, not directly measured</small>
                </div>`;
            }).join("")}
        </div>` : "";
    const suggestionOptions = suggestions.map((item, index) => {
        const name = item.cell_name || "Unnamed observed cell";
        const volume = item.working_volume_l != null ? `${Number(item.working_volume_l).toLocaleString()} L` : "volume unknown";
        return `<option value="${index}" data-name="${escapeHtml(item.cell_name || "")}" data-volume="${escapeHtml(item.working_volume_l ?? "")}" data-cell-id="${escapeHtml(item.physical_cell_id ?? "")}">${escapeHtml(name)} · ${escapeHtml(volume)} · ${escapeHtml(item.observations || 0)} run(s)</option>`;
    }).join("");
    ui.required_inputs_panel.innerHTML = `
        <div class="required-inputs-heading">
            <div><strong>Required before first stage</strong><span>${data.complete ? "All required execution inputs are available." : "Complete the missing values. Recipe values can be overridden for this execution."}</span></div>
            <span class="required-status ${data.complete ? "complete" : "incomplete"}">${data.complete ? "Ready" : `${(data.missing || []).length} missing`}</span>
        </div>
        <div class="cell-profile-row">
            <label>Known cell suggestion <span>(optional)</span>
                <select id="execution_cell_suggestion">
                    <option value="">Custom / unknown cell</option>
                    ${suggestionOptions}
                </select>
            </label>
            <label>Cell / vessel identity <span>(optional)</span>
                <input id="execution_cell_name" type="text" value="${escapeHtml(profile.cell_name || "")}" data-physical-id="${escapeHtml(profile.physical_cell_id ?? "")}" placeholder="e.g. Cell A">
            </label>
            <button class="button button-secondary" type="button" data-save-cell-profile>Save cell identity</button>
            <span class="cell-profile-hint">Selecting an observed cell can suggest its previous working volume. It never overwrites an existing execution value automatically.</span>
        </div>
        <div class="required-input-grid">
            ${items.map((item) => {
                const compatible = sensorSnapshots(state).filter(sensor =>
                    sensorIsOnline(sensor) && sensor.value != null &&
                    String(sensor.unit || "").trim().toLowerCase() === String(item.unit || "").trim().toLowerCase()
                );
                return `<div class="required-input-item ${item.value == null ? "missing" : "complete"}">
                    <label for="required_${escapeHtml(item.id)}">${escapeHtml(item.label)} <span>${escapeHtml(item.unit || "")}</span></label>
                    ${compatible.length ? `<select data-required-source="${escapeHtml(item.id)}"><option value="manual">Manual entry</option>${compatible.map(sensor => `<option value="${escapeHtml(sensor.id)}">${escapeHtml(sensor.name || sensor.id)} · ${escapeHtml(sensorDisplayValue(sensor))}</option>`).join("")}</select>` : ""}
                    <div>
                        <input id="required_${escapeHtml(item.id)}" data-required-value="${escapeHtml(item.id)}" type="number" step="any" value="${item.value == null ? "" : escapeHtml(item.value)}" placeholder="Required">
                        <button class="button button-primary" data-save-required="${escapeHtml(item.id)}" type="button">${item.value == null ? "Set" : "Update"}</button>
                    </div>
                    <small>${item.measurement_id ? "Execution value · auditable measurement" : (item.source === "recipe" ? "From recipe; change only if the actual run differs." : "Not provided by recipe.")}</small>
                </div>`;
            }).join("")}
        </div>
        ${derivedMarkup}`;
    requiredInputsSignature = signature;
    for (const [key, draft] of drafts) {
        const input = key === "cell" ? panel.querySelector("#execution_cell_name")
            : panel.querySelector(`[data-required-value="${CSS.escape(key)}"]`);
        if (!input) continue;
        input.value = draft.value;
        if (key === "cell") input.dataset.physicalId = draft.physicalId || "";
    }
    for (const [key, value] of selectedSources) {
        const select = panel.querySelector(`[data-required-source="${CSS.escape(key)}"]`);
        if (!select || ![...select.options].some(option => option.value === value && !option.disabled)) continue;
        select.value = value;
        const input = panel.querySelector(`[data-required-value="${CSS.escape(key)}"]`);
        if (input) input.disabled = value !== "manual";
    }
    const cellSelect = panel.querySelector("#execution_cell_suggestion");
    if (cellSelect && [...cellSelect.options].some(option => option.value === selectedCell)) {
        cellSelect.value = selectedCell;
    }
    updateRequiredSensorLabels(state);
}

function renderMeasurements(state) {
    const available = ["Ready","Running","Paused","Completed","RecoveryRequired"].includes(state.state);
    ui.measurement_launcher.hidden = !available;
    ui.measurement_panel.hidden = !available || !measurementOpen;
    ui.toggle_measurement_panel.setAttribute("aria-expanded", String(available && measurementOpen));
    ui.toggle_measurement_panel.innerHTML = measurementOpen ?
        'Close data acquisition <span aria-hidden="true">▴</span>' :
        'Data acquisition <span aria-hidden="true">▾</span>';
    if (!available || !measurementOpen) return;
    updateMeasurementSources(state);
    const remoteRevision = Number(state.measurements?.revision || 0);
    if (remoteRevision !== Number(measurementData.revision || 0)) loadMeasurements();
}

if(typeof window.setInterval==="function")window.setInterval(pollRunMonitor,2500);

function renderReady(state) {
    ui.ready_panel.hidden = false;
    const stage = state.next_stage;
    const executionInputs = state.execution_inputs || {};
    const signature = JSON.stringify([stage, state.stage_attempt, executionInputs.complete, executionInputs.items]);
    if (signature === readyViewSignature) return;
    readyViewSignature = signature;
    if (!stage) {
        ui.ready_stage.innerHTML = "<h3>No stage available</h3>";
        ui.start_first_stage.disabled = true;
        return;
    }
    ui.ready_stage.innerHTML = `
        <p class="eyebrow">First stage</p>
        <h3>${escapeHtml(stage.name || `Stage ${stage.id}`)}</h3>
        <p>${escapeHtml(stage.type || "")}</p>
        <div class="parameter-grid">${stageParameters(stage, state)}</div>`;
    ui.start_first_stage.disabled = executionInputs.complete === false;
    if (executionInputs.complete === false) {
        const labels = (executionInputs.items || []).filter(item => item.value == null).map(item => item.label);
        ui.ready_stage.insertAdjacentHTML("beforeend", `<p class="required-warning">Required before start: ${escapeHtml(labels.join(", "))}</p>`);
    }
}

function renderRun(state) {
    ui.run_panel.hidden = false;
    const stage = state.current_stage;
    renderMiniStageTimeline(state);
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
    const stageActionRelevant = !transition && Boolean(stage) && ["Running", "Paused"].includes(state.state);
    ui.finish_stage_button.hidden = !stageActionRelevant;
    ui.skip_stage_button.hidden = !stageActionRelevant;

    if (!transition) {
        ui.stage_timer.textContent = formatTime(state.stage_remaining_s);
        ui.stage_elapsed.textContent = `Elapsed ${formatTime(state.stage_elapsed_s)}`;
        ui.stage_parameters.innerHTML = stageParameters(stage, state);
        const scraping = state.scraping || {};
        ui.scraping_box.hidden = !scraping.enabled;
        if (scraping.enabled) {
            ui.scraping_timer.textContent = scraping.next_in_s == null ? "—" : `${Math.max(0, Number(scraping.next_in_s)).toFixed(1)} s`;
            const detail = ui.scraping_box.querySelector(".scraping-description");
            if (detail) detail.textContent = `Scraping signal every ${scraping.interval_s ?? "—"} s`;
            if (ui.scraping_alerts_enabled) ui.scraping_alerts_enabled.checked = scraping.alerts_enabled !== false;
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
    if(monitorRunId!==state.storage_id){
        monitorRunId=state.storage_id;monitorFrame=null;monitorFrameRevision=0;
    }
    latestState = state;
    setStateBadge(state.state);
    setWorkflow(state);
    renderOperations(state);
    renderCalibrationReview(state);

    ui.experiment_name.textContent = state.experiment?.name || "Experiment run";
    ui.experiment_meta.textContent = state.storage_id
        ? `Execution ${state.storage_id}`
        : "No local execution selected.";

    hidePanels();
    if (state.state === "CellSelection") renderCellSelection(state);
    else if (state.state === "CameraCalibration") renderCameraCalibration(state);
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

    ui.abort_bar.hidden = !["CellSelection", "CameraCalibration", "SensorCalibration", "Ready", "Running", "Paused", "RecoveryRequired"].includes(state.state);
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
    if (state.scraping?.alerts_enabled === false) {
        ui.scrape_signal.classList.remove("show");
        return;
    }
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
    ui.select_physical_cell_form.addEventListener("submit", async event => {
        event.preventDefault();
        const cellId = ui.select_physical_cell.value;
        if (!cellId) { showToast("Select a physical cell."); return; }
        const button = ui.select_physical_cell_form.querySelector('[type="submit"]');
        button.disabled = true;
        try {
            const cameraId = ui.select_virtual_camera.value;
            const volumeInput=document.getElementById("cell_volume_override");
            const cell=physicalCells.find(item=>String(item.id)===String(cellId));
            const rawVolume=volumeInput?.value?.trim()||"";
            const override=rawVolume!=="" && (cell?.working_volume_l==null ||
                Math.abs(Number(rawVolume)-Number(cell.working_volume_l))>1e-9);
            await action("/api/digiflot/calibration/cell/select",
                {cell_id:cellId, camera_id:cameraId === "none" ? "none" : (cameraId ? Number(cameraId) : null),
                 ...(override?{working_volume_l:Number(rawVolume)}:{})});
        } catch (_) { button.disabled = false; }
    });
    document.addEventListener("click", async (event) => {
        const cameraButton = event.target.closest("[data-edit-camera]");
        if (cameraButton) {
            cameraButton.disabled = true;
            try {
                await requestJson(`/api/digiflot/calibration/cameras/${encodeURIComponent(cameraButton.dataset.editCamera)}/reopen`, { method: "POST" });
                window.location.href = `/cameras?camera=${encodeURIComponent(cameraButton.dataset.editCamera)}&calibration=1`;
            } catch (error) {
                cameraButton.disabled = false;
                showToast(error.message);
            }
            return;
        }
        const sensorButton = event.target.closest("[data-edit-sensor]");
        if (sensorButton) {
            sensorButton.disabled = true;
            try {
                await requestJson(`/api/digiflot/calibration/sensors/${encodeURIComponent(sensorButton.dataset.editSensor)}/reopen`, { method: "POST" });
                window.location.href = "/sensors?calibration=1";
            } catch (error) {
                sensorButton.disabled = false;
                showToast(error.message);
            }
        }
    });
    ui.select_physical_cell.addEventListener("change",updateSelectedCellVolume);
    ui.start_first_stage.addEventListener("click", () => action("/api/digiflot/stages/start"));
    ui.start_now_button.addEventListener("click", () => action("/api/digiflot/stages/start"));
    ui.scraping_alerts_enabled.addEventListener("change", async () => {
        const selected = ui.scraping_alerts_enabled.checked;
        if (!selected) {
            ui.scrape_signal.classList.remove("show");
            window.clearTimeout(scrapeFlashTimer);
        }
        ui.scraping_alerts_enabled.disabled = true;
        try {
            await requestJson("/api/digiflot/scraping/alerts", {
                method:"POST", headers:{"Content-Type":"application/json"},
                body:JSON.stringify({enabled:selected})
            });
        } catch (error) {
            ui.scraping_alerts_enabled.checked = !selected;
            showToast(error.message);
        } finally { ui.scraping_alerts_enabled.disabled = false; }
    });
    ui.pause_button.addEventListener("click", () => action("/api/digiflot/pause"));
    ui.resume_button.addEventListener("click", () => action("/api/digiflot/resume"));
    ui.finish_stage_button.addEventListener("click", async () => {
        const confirmed = window.confirm("Finish the active stage early? The stage will remain valid and will be recorded as an early completion.");
        if (confirmed) await action("/api/digiflot/stages/finish-now", { reason: "Operator finished stage early" });
    });
    ui.skip_stage_button.addEventListener("click", async () => {
        const confirmed = window.confirm("Abort the active stage? It will be marked as skipped/invalid in the event log and the workflow will continue.");
        if (confirmed) await action("/api/digiflot/stages/skip", { reason: "Operator aborted active stage" });
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
        if (confirmed) {
            await action("/api/digiflot/abort", {reason:"Operator aborted from recovery",return_to_idle:true});
            window.location.replace("/");
        }
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
        const confirmed = window.confirm("Abort this experiment? Current acquisition will stop, but recorded data will be kept. The system will return to Idle.");
        if (!confirmed) return;
        await action("/api/digiflot/abort", {reason:"Operator aborted experiment",return_to_idle:true});
        window.location.replace("/");
    });

    ui.toggle_measurement_panel.addEventListener("click", () => {
        measurementOpen = !measurementOpen;
        try { window.sessionStorage?.setItem("digiflot-data-acquisition-open", measurementOpen ? "1":"0"); } catch (_) {}
        if (latestState) renderMeasurements(latestState);
        if (measurementOpen) loadMeasurements();
    });
    ui.live_sensor_grid.addEventListener("click", (event) => {
        const imageButton=event.target.closest("[data-image-toggle]");
        if (imageButton) {
            imageHidden=!imageHidden;
            try { window.localStorage?.setItem("digiflot-hide-froth-image",imageHidden?"1":"0"); } catch (_) {}
            if (latestState) renderLiveSensors(latestState);
            if (!imageHidden) pollRunMonitor();
            return;
        }
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
    ui.measurement_variable_name.addEventListener("change", () => {
        const match=(measurementData.variables||[]).find(v =>
            v.name.toLowerCase()===ui.measurement_variable_name.value.trim().toLowerCase());
        if(match)selectMeasurementVariable(match.id);
    });
    ui.measurement_summary_body.addEventListener("click", chooseMeasurementVariable);
    ui.measurement_summary_body.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const row = event.target.closest("[data-variable-id]");
        if (!row) return;
        event.preventDefault();
        selectMeasurementVariable(row.dataset.variableId);
    });

    ui.measurement_source.addEventListener("change", updateMeasurementSourcePreview);
    ui.measurement_value_type.addEventListener("change", updateMeasurementSourcePreview);

    ui.required_inputs_panel.addEventListener("change", (event) => {
        const sourceSelect = event.target.closest("[data-required-source]");
        if (sourceSelect) {
            const input = ui.required_inputs_panel.querySelector(`[data-required-value="${CSS.escape(sourceSelect.dataset.requiredSource)}"]`);
            if (input) input.disabled = sourceSelect.value !== "manual";
            return;
        }
        const select = event.target.closest("#execution_cell_suggestion");
        if (!select || !select.value) return;
        const option = select.options[select.selectedIndex];
        const name = option?.dataset.name || "";
        const volume = option?.dataset.volume || "";
        const nameInput = document.getElementById("execution_cell_name");
        if (nameInput && name) {
            nameInput.value = name;
            nameInput.dataset.physicalId = option?.dataset.cellId || "";
        }
        const volumeInput = ui.required_inputs_panel.querySelector('[data-required-value="working_cell_volume"]');
        if (volumeInput && !volumeInput.value && volume) volumeInput.value = volume;
    });

    // When the user leaves the required-input area, apply any deferred state
    // changes. Draft values are retained by renderRequiredInputs().
    ui.required_inputs_panel.addEventListener("focusout", () => {
        window.setTimeout(() => {
            if (latestState && !ui.required_inputs_panel.contains(document.activeElement)) {
                renderRequiredInputs(latestState);
            }
        }, 0);
    });

    ui.required_inputs_panel.addEventListener("input", (event) => {
        if (event.target.id === "execution_cell_name") {
            // A manually renamed vessel must not keep another vessel's stable ID.
            event.target.dataset.physicalId = "";
        }
    });

    ui.required_inputs_panel.addEventListener("click", async (event) => {
        const saveInput = event.target.closest("[data-save-required]");
        if (saveInput) {
            const id = saveInput.dataset.saveRequired;
            const input = ui.required_inputs_panel.querySelector(`[data-required-value="${CSS.escape(id)}"]`);
            const source = ui.required_inputs_panel.querySelector(`[data-required-source="${CSS.escape(id)}"]`)?.value || "manual";
            if (source === "manual" && (!input || input.value.trim() === "")) { showToast("Enter the required value."); return; }
            const item = (latestState?.execution_inputs?.items || []).find(entry => entry.id === id);
            saveInput.disabled = true;
            try {
                const payload = {variable_id:id, variable_name:item?.label || id, source_id:source, value_type:"number", role:"execution_input", category:"initial_condition"};
                if (source === "manual") { payload.value = input.value; payload.unit = item?.unit || null; }
                const result = await requestJson("/api/digiflot/measurements", {
                    method:"POST", headers:{"Content-Type":"application/json"},
                    body:JSON.stringify(payload)
                });
                if (latestState) latestState.execution_inputs = result.execution_inputs;
                renderRequiredInputs(latestState || {}, {force: true, savedField: id});
                showToast(`${item?.label || id} updated.`);
            } catch (error) { showToast(error.message); } finally { saveInput.disabled = false; }
            return;
        }
        const saveCell = event.target.closest("[data-save-cell-profile]");
        if (saveCell) {
            const cellInput = document.getElementById("execution_cell_name");
            const cellName = cellInput?.value?.trim() || "";
            const physicalCellId = cellInput?.dataset.physicalId || "";
            saveCell.disabled = true;
            try {
                const result = await requestJson("/api/digiflot/execution-inputs/cell-profile", {
                    method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({cell_name:cellName, physical_cell_id:physicalCellId})
                });
                if (latestState) latestState.execution_inputs = result;
                renderRequiredInputs(latestState || {}, {force: true, savedField: "cell"});
                showToast("Cell identity saved for this execution.");
            } catch (error) { showToast(error.message); } finally { saveCell.disabled = false; }
        }
    });

    ui.measurement_form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const variableName = ui.measurement_variable_name.value.trim();
        if (!variableName) {
            showToast("Enter a variable name.");
            return;
        }
        const valueType = ui.measurement_value_type.value || "number";
        const sourceId = valueType === "text" ? "manual" : (ui.measurement_source.value || "manual");
        const variableId=variableName.toLowerCase().replace(/[^a-z0-9]+/g,"_").replace(/^_+|_+$/g,"");
        const initialCondition=valueType==="number"&&["feed_mass","water_volume"].includes(variableId);
        const payload = {
            variable_name: variableName, variable_id: variableId,
            source_id: sourceId, value_type: valueType,
            role: valueType==="text"?"note":initialCondition?"execution_input":"measurement",
            category: valueType==="text"?"note":initialCondition?"initial_condition":"measurement",
        };
        if(initialCondition && sourceId==="manual" && !ui.measurement_manual_unit.value.trim())
            ui.measurement_manual_unit.value=variableId==="feed_mass"?"g":"L";
        if (sourceId === "manual") {
            const manualValue = valueType === "text" ? ui.measurement_manual_text.value : ui.measurement_manual_value.value;
            if (manualValue.trim() === "") {
                showToast(valueType === "text" ? "Enter a note." : "Enter a manual value.");
                return;
            }
            payload.value = manualValue;
            payload.unit = valueType === "text" ? null : (ui.measurement_manual_unit.value.trim() || null);
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
            if (latestState && result.execution_inputs) latestState.execution_inputs = result.execution_inputs;
            renderMeasurementTables();
            ui.measurement_manual_value.value = "";
            ui.measurement_manual_text.value = "";
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
        await Promise.all([loadPhysicalCells(), loadMeasurements()]);
    } catch (error) {
        showToast(error.message);
    }
    connectStateStream();
    if (latestState) refreshRunEstimate(latestState);
    refreshRunStorage();
    window.setInterval(refreshRunStorage, 30000);
}

document.addEventListener("DOMContentLoaded", initialise);
