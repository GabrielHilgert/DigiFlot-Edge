const root = document.getElementById("results_root");
const storageId = root?.dataset.storageId || "";

const state = {
    overview: null,
    measurements: null,
    events: null,
    system: null,
    selectedSensor: null,
    sensorSeries: null,
    sensorTableOffset: 0,
    sensorTableLimit: 200,
    activeEventFilter: "all",
    selectedVideo: null,
};

const elements = {
    title: document.getElementById("result_title"),
    status: document.getElementById("result_status"),
    meta: document.getElementById("result_meta"),
    refresh: document.getElementById("refresh_results"),
    error: document.getElementById("results_error"),
    summary: document.getElementById("summary_cards"),
    timeline: document.getElementById("timeline"),
    timelineDuration: document.getElementById("timeline_duration"),
    experimentParameters: document.getElementById("experiment_parameters"),
    runtimeParameters: document.getElementById("runtime_parameters"),
    stageCount: document.getElementById("overview_stage_count"),
    stages: document.getElementById("overview_stages"),
    sensorCards: document.getElementById("sensor_cards"),
    sensorViewer: document.getElementById("sensor_viewer"),
    sensorViewerSource: document.getElementById("sensor_viewer_source"),
    sensorViewerTitle: document.getElementById("sensor_viewer_title"),
    sensorViewerStats: document.getElementById("sensor_viewer_stats"),
    sensorChart: document.getElementById("sensor_chart"),
    sensorChartEmpty: document.getElementById("sensor_chart_empty"),
    sensorTableToggle: document.getElementById("sensor_table_toggle"),
    sensorTableWrap: document.getElementById("sensor_table_wrap"),
    sensorTableInfo: document.getElementById("sensor_table_info"),
    sensorTableHead: document.getElementById("sensor_table_head"),
    sensorTableBody: document.getElementById("sensor_table_body"),
    sensorPrev: document.getElementById("sensor_prev"),
    sensorNext: document.getElementById("sensor_next"),
    measurementCards: document.getElementById("measurement_cards"),
    measurementTable: document.getElementById("measurement_table"),
    videoCards: document.getElementById("video_cards"),
    videoViewer: document.getElementById("video_viewer"),
    videoPlayer: document.getElementById("video_player"),
    videoCamera: document.getElementById("video_camera"),
    videoTitle: document.getElementById("video_title"),
    videoMeta: document.getElementById("video_meta"),
    videoContext: document.getElementById("video_context"),
    eventFilters: document.getElementById("event_filters"),
    eventsList: document.getElementById("events_list"),
    systemCards: document.getElementById("system_cards"),
    fileSearch: document.getElementById("file_search"),
    fileCount: document.getElementById("file_count"),
    fileList: document.getElementById("file_list"),
    dialog: document.getElementById("file_dialog"),
    dialogTitle: document.getElementById("file_dialog_title"),
    dialogBody: document.getElementById("file_dialog_body"),
    dialogClose: document.getElementById("file_dialog_close"),
    dialogDownload: document.getElementById("file_dialog_download"),
};

async function requestJson(url, options = {}) {
    const response = await fetch(url, {
        cache: "no-store",
        ...options,
        headers: { Accept: "application/json", ...(options.headers || {}) },
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            message = data.detail || message;
        } catch (_) {}
        throw new Error(message);
    }
    return response.json();
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatNumber(value, digits = 2) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "—";
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(number);
}

function formatSeconds(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) return "—";
    if (seconds < 60) return `${formatNumber(seconds, 1)} s`;
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = Math.floor(seconds % 60);
    return hours > 0
        ? `${hours}h ${String(minutes).padStart(2, "0")}m ${String(remainder).padStart(2, "0")}s`
        : `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

function formatBytes(value) {
    let bytes = Number(value);
    if (!Number.isFinite(bytes) || bytes < 0) return "—";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let index = 0;
    while (bytes >= 1024 && index < units.length - 1) {
        bytes /= 1024;
        index += 1;
    }
    return `${bytes.toFixed(index === 0 ? 0 : bytes < 10 ? 2 : 1)} ${units[index]}`;
}

function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString();
}

function valueOrDash(value) {
    return value === null || value === undefined || value === "" ? "—" : String(value);
}

function withUnit(value, unit, digits = 2) {
    const formatted = formatNumber(value, digits);
    return formatted === "—" ? formatted : `${formatted}${unit ? ` ${unit}` : ""}`;
}

function showError(message) {
    elements.error.hidden = false;
    elements.error.textContent = message;
}

function clearError() {
    elements.error.hidden = true;
    elements.error.textContent = "";
}

async function loadResults() {
    if (!storageId) {
        showError("Missing local experiment ID.");
        return;
    }
    elements.refresh.disabled = true;
    clearError();
    try {
        state.overview = await requestJson(`/api/results/${encodeURIComponent(storageId)}`);
        state.measurements = null;
        state.events = null;
        state.system = null;
        renderAll();
    } catch (error) {
        showError(`Could not load experiment results: ${error.message}`);
        elements.title.textContent = "Experiment results unavailable";
    } finally {
        elements.refresh.disabled = false;
    }
}

function renderAll() {
    renderHeader();
    renderSummary();
    renderTimeline();
    renderOverview();
    renderSensors();
    renderVideos();
    renderFiles();
    renderMeasurementOverview();
}

function renderHeader() {
    const { experiment = {}, runtime = {}, summary = {} } = state.overview;
    elements.title.textContent = experiment.name || `Experiment ${experiment.id ?? storageId}`;
    const status = summary.status || runtime.state || experiment.state || "Unknown";
    elements.status.textContent = status;
    elements.status.dataset.state = String(status).toLowerCase();

    const created = experiment.local_created || experiment.creation_time;
    const meta = [
        ["Run", storageId],
        ["Created", formatDate(created)],
        ["Duration", formatSeconds(summary.duration_s)],
        ["Experiment ID", valueOrDash(experiment.id)],
    ];
    elements.meta.innerHTML = meta.map(([label, value]) => `<span>${escapeHtml(label)} <strong>${escapeHtml(value)}</strong></span>`).join("");
}

function renderSummary() {
    const summary = state.overview.summary || {};
    const cards = [
        ["Duration", formatSeconds(summary.duration_s), summary.status || "Execution"],
        ["Sensor samples", Number(summary.sensor_samples || 0).toLocaleString(), `${summary.sensor_series || 0} variable(s)`],
        ["Measurements", Number(summary.measurements || 0).toLocaleString(), `${summary.measurement_variables || 0} variable(s)`],
        ["Videos", Number(summary.videos || 0).toLocaleString(), `${summary.sensor_files || 0} sensor file(s)`],
        ["Events", Number(summary.events || 0).toLocaleString(), "Persistent journal"],
        ["Data size", formatBytes(summary.size_bytes), `${summary.files || 0} file(s)`],
    ];
    elements.summary.innerHTML = cards.map(([label, value, note]) => `
        <article class="summary-card">
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
            <small>${escapeHtml(note)}</small>
        </article>
    `).join("");
}

function renderTimeline() {
    const timeline = state.overview.timeline || {};
    const duration = Math.max(Number(timeline.duration_s) || 0, 0.001);
    elements.timelineDuration.textContent = formatSeconds(duration);
    const stages = Array.isArray(timeline.stages) ? timeline.stages : [];
    const items = Array.isArray(timeline.items) ? timeline.items : [];

    const stageHtml = stages.map((stage) => {
        const start = Math.max(0, Number(stage.start_s) || 0);
        const end = Math.max(start, Number(stage.end_s) || start);
        const left = Math.min(100, Math.max(0, start / duration * 100));
        const width = Math.max(.35, Math.min(100 - left, (end - start) / duration * 100));
        const label = stage.stage_name || stage.stage_type || `Stage ${stage.stage_id ?? ""}`;
        return `<div class="timeline-stage" style="left:${left}%;width:${width}%" title="${escapeHtml(label)} · ${escapeHtml(formatSeconds(end - start))}"><span class="timeline-stage-label">${escapeHtml(label)}</span></div>`;
    }).join("");

    const markers = items
        .filter(item => Number.isFinite(Number(item.elapsed_s)))
        .slice(0, 500)
        .map(item => {
            const left = Math.min(100, Math.max(0, Number(item.elapsed_s) / duration * 100));
            const event = String(item.event || "");
            const kind = item.kind === "measurement"
                ? "measurement"
                : event.includes("WARNING") ? "warning"
                : event.includes("CAMERA") ? "camera" : "event";
            const title = item.kind === "measurement"
                ? `${item.variable_name || item.variable_id}: ${valueOrDash(item.value)} ${item.unit || ""}`
                : event.replaceAll("_", " ");
            return `<span class="timeline-marker ${kind}" style="left:${left}%" title="${escapeHtml(formatSeconds(item.elapsed_s))} · ${escapeHtml(title)}"></span>`;
        }).join("");

    elements.timeline.innerHTML = `
        <div class="timeline-stage-track">${stageHtml}${markers}</div>
        <div class="timeline-axis"><span>0:00</span><span>${escapeHtml(formatSeconds(duration))}</span></div>
    `;
}

function parameterItem(label, value) {
    return `<div class="parameter-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(valueOrDash(value))}</strong></div>`;
}

function renderOverview() {
    const experiment = state.overview.experiment || {};
    const runtime = state.overview.runtime || {};
    elements.experimentParameters.innerHTML = [
        ["Source", experiment.source],
        ["pH", experiment.pH ?? experiment.ph],
        ["Airflow", experiment.airflow == null ? null : `${experiment.airflow} L/min`],
        ["Rotor speed", experiment.rotor_speed == null ? null : `${experiment.rotor_speed} rpm`],
        ["Cell ID", experiment.cell_id],
        ["Group ID", experiment.group_id],
        ["User ID", experiment.user_id],
        ["Reagents", (experiment.reagents || []).length],
        ["Configured stages", (experiment.stages || []).length],
    ].map(([label, value]) => parameterItem(label, value)).join("");

    elements.runtimeParameters.innerHTML = [
        ["State", runtime.state || experiment.state],
        ["Run elapsed", formatSeconds(runtime.run_elapsed_s)],
        ["Current stage", runtime.current_stage?.name || runtime.stage_name],
        ["Stage state", runtime.stage_state],
        ["Stage attempt", runtime.stage_attempt],
        ["Saved", formatDate(runtime.saved_at)],
        ["Warnings", Array.isArray(runtime.warnings) ? runtime.warnings.length : 0],
        ["Recording", runtime.recording ? "Yes" : "No"],
        ["Scraping count", runtime.scraping_sequence],
    ].map(([label, value]) => parameterItem(label, value)).join("");

    const stages = experiment.stages || [];
    elements.stageCount.textContent = stages.length;
    elements.stages.innerHTML = stages.length ? stages.map((stage, index) => `
        <article class="stage-result-card">
            <header><div><strong>${escapeHtml(stage.name || `Stage ${index + 1}`)}</strong><small>${escapeHtml(stage.type || "stage")}</small></div><span>${String(index + 1).padStart(2, "0")}</span></header>
            <div class="stage-result-metrics">
                <div><span>Duration</span><strong>${escapeHtml(formatSeconds(stage.duration))}</strong></div>
                <div><span>pH</span><strong>${escapeHtml(valueOrDash(stage.ph ?? stage.pH))}</strong></div>
                <div><span>Airflow</span><strong>${escapeHtml(stage.airflow == null ? "—" : `${stage.airflow} L/min`)}</strong></div>
                <div><span>Rotor</span><strong>${escapeHtml(stage.rotor_speed == null ? "—" : `${stage.rotor_speed} rpm`)}</strong></div>
            </div>
        </article>
    `).join("") : `<div class="empty-state">No stages are recorded in experiment.json.</div>`;
}

function renderSensors() {
    const sensors = state.overview.sensors || [];
    if (!sensors.length) {
        elements.sensorCards.innerHTML = `<div class="empty-state">No sensor TSV files were found for this execution.</div>`;
        elements.sensorViewer.hidden = true;
        return;
    }
    elements.sensorCards.innerHTML = "";
    for (const source of sensors) {
        const card = document.createElement("article");
        card.className = "sensor-source-card";
        const header = document.createElement("div");
        header.className = "sensor-source-header";
        header.innerHTML = `<strong>${escapeHtml(source.name)}</strong><span>${Number(source.sample_count || 0).toLocaleString()} rows · ${escapeHtml(formatBytes(source.size_bytes))}</span>`;
        card.appendChild(header);
        for (const series of source.series || []) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "sensor-series-button";
            button.dataset.path = source.path;
            button.dataset.series = series.id;
            const unit = series.unit || "";
            button.innerHTML = `<span><strong>${escapeHtml(series.name)}</strong><small>${Number(series.count || 0).toLocaleString()} samples${unit ? ` · ${escapeHtml(unit)}` : ""}</small></span><span class="series-range">${escapeHtml(withUnit(series.min, unit))} – ${escapeHtml(withUnit(series.max, unit))}</span>`;
            button.addEventListener("click", () => selectSensorSeries(source, series, button));
            card.appendChild(button);
        }
        elements.sensorCards.appendChild(card);
    }
}

async function selectSensorSeries(source, series, button) {
    document.querySelectorAll(".sensor-series-button.active").forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    state.selectedSensor = { source, series };
    state.sensorTableOffset = 0;
    elements.sensorViewer.hidden = false;
    elements.sensorViewerSource.textContent = source.name;
    elements.sensorViewerTitle.textContent = series.name;
    elements.sensorViewerStats.textContent = `${Number(series.count || 0).toLocaleString()} samples · mean ${withUnit(series.mean, series.unit)} · range ${withUnit(series.min, series.unit)} to ${withUnit(series.max, series.unit)}`;
    elements.sensorChartEmpty.hidden = true;
    try {
        state.sensorSeries = await requestJson(`/api/results/${encodeURIComponent(storageId)}/series?path=${encodeURIComponent(source.path)}&series=${encodeURIComponent(series.id)}&max_points=1800`);
        drawLineChart(elements.sensorChart, state.sensorSeries.points || [], { unit: series.unit || "", xLabel: "Experiment time" });
        elements.sensorChartEmpty.hidden = !(state.sensorSeries.points || []).length;
        if (!elements.sensorTableWrap.hidden) await loadSensorTable();
        elements.sensorViewer.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
        showError(`Could not load sensor data: ${error.message}`);
    }
}

function chartCssColor(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
}

function drawLineChart(canvas, points, options = {}) {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const cssWidth = Math.max(rect.width, 300);
    const cssHeight = Math.max(rect.height || Number(canvas.getAttribute("height")) || 220, 180);
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(cssWidth * ratio);
    canvas.height = Math.round(cssHeight * ratio);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    const valid = (points || []).filter(point => Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y)));
    if (!valid.length) return;

    let minX = Math.min(...valid.map(point => Number(point.x)));
    let maxX = Math.max(...valid.map(point => Number(point.x)));
    let minY = Math.min(...valid.map(point => Number(point.y)));
    let maxY = Math.max(...valid.map(point => Number(point.y)));
    if (maxX === minX) maxX = minX + 1;
    if (maxY === minY) {
        const pad = Math.max(Math.abs(minY) * .05, 1);
        minY -= pad;
        maxY += pad;
    } else {
        const pad = (maxY - minY) * .08;
        minY -= pad;
        maxY += pad;
    }

    const padding = { left: 62, right: 18, top: 18, bottom: 38 };
    const width = cssWidth - padding.left - padding.right;
    const height = cssHeight - padding.top - padding.bottom;
    const text = chartCssColor("--text-soft", "#666");
    const grid = chartCssColor("--border", "#ddd");
    const accent = chartCssColor("--accent", "#2f6fed");
    ctx.font = "11px system-ui, sans-serif";
    ctx.lineWidth = 1;

    for (let i = 0; i <= 4; i += 1) {
        const y = padding.top + height * i / 4;
        const value = maxY - (maxY - minY) * i / 4;
        ctx.strokeStyle = grid;
        ctx.beginPath(); ctx.moveTo(padding.left, y); ctx.lineTo(cssWidth - padding.right, y); ctx.stroke();
        ctx.fillStyle = text;
        ctx.textAlign = "right";
        ctx.fillText(`${formatNumber(value, 2)}${options.unit ? ` ${options.unit}` : ""}`, padding.left - 8, y + 4);
    }

    for (let i = 0; i <= 4; i += 1) {
        const x = padding.left + width * i / 4;
        const value = minX + (maxX - minX) * i / 4;
        ctx.fillStyle = text;
        ctx.textAlign = i === 0 ? "left" : i === 4 ? "right" : "center";
        ctx.fillText(formatSeconds(value), x, cssHeight - 12);
    }

    ctx.strokeStyle = accent;
    ctx.lineWidth = 1.8;
    ctx.lineJoin = "round";
    ctx.beginPath();
    valid.forEach((point, index) => {
        const x = padding.left + (Number(point.x) - minX) / (maxX - minX) * width;
        const y = padding.top + (maxY - Number(point.y)) / (maxY - minY) * height;
        if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
}

async function loadSensorTable() {
    if (!state.selectedSensor) return;
    const { source, series } = state.selectedSensor;
    const params = new URLSearchParams({
        path: source.path,
        series: series.id,
        offset: String(state.sensorTableOffset),
        limit: String(state.sensorTableLimit),
    });
    try {
        const data = await requestJson(`/api/results/${encodeURIComponent(storageId)}/table?${params}`);
        const columns = data.columns || [];
        elements.sensorTableHead.innerHTML = `<tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr>`;
        elements.sensorTableBody.innerHTML = (data.rows || []).map(row => `<tr>${columns.map(column => `<td>${escapeHtml(valueOrDash(row[column]))}</td>`).join("")}</tr>`).join("");
        const start = data.total ? data.offset + 1 : 0;
        const end = Math.min(data.total, data.offset + (data.rows || []).length);
        elements.sensorTableInfo.textContent = `${start.toLocaleString()}–${end.toLocaleString()} of ${Number(data.total || 0).toLocaleString()} rows`;
        elements.sensorPrev.disabled = data.offset <= 0;
        elements.sensorNext.disabled = data.offset + data.limit >= data.total;
    } catch (error) {
        showError(`Could not load raw sensor table: ${error.message}`);
    }
}

async function loadMeasurements() {
    if (state.measurements) return state.measurements;
    state.measurements = await requestJson(`/api/results/${encodeURIComponent(storageId)}/measurements`);
    return state.measurements;
}

function renderMeasurementOverview() {
    const variables = state.overview.measurement_variables || [];
    if (!variables.length) {
        elements.measurementCards.innerHTML = `<div class="empty-state">No operator measurements were recorded.</div>`;
        elements.measurementTable.innerHTML = `<tr><td colspan="6">No observations.</td></tr>`;
        return;
    }
    elements.measurementCards.innerHTML = variables.map(variable => {
        const latest = variable.latest || {};
        return `<article class="measurement-card"><header><div><strong>${escapeHtml(variable.name)}</strong><span>${escapeHtml(variable.id)}</span></div><span>${Number(variable.count || 0).toLocaleString()} pts</span></header><div class="measurement-latest">${escapeHtml(withUnit(latest.value, variable.unit))}</div><div class="measurement-meta">Range ${escapeHtml(withUnit(variable.min, variable.unit))} – ${escapeHtml(withUnit(variable.max, variable.unit))}</div></article>`;
    }).join("");
}

async function renderMeasurementsFull() {
    try {
        const data = await loadMeasurements();
        renderMeasurementOverview();
        const rows = data.observations || [];
        elements.measurementTable.innerHTML = rows.length ? rows.slice().reverse().map(record => `
            <tr>
                <td>${escapeHtml(record.variable_name || record.variable_id || "—")}</td>
                <td>${escapeHtml(withUnit(record.value, record.unit))}</td>
                <td>${escapeHtml(record.sensor_name || record.source_type || "—")}</td>
                <td>${escapeHtml(formatSeconds(record.run_elapsed_s))}</td>
                <td>${escapeHtml(record.stage_name || record.stage_id || record.state || "—")}</td>
                <td>${escapeHtml(formatDate(record.captured_at || record.timestamp))}</td>
            </tr>
        `).join("") : `<tr><td colspan="6">No observations.</td></tr>`;
    } catch (error) {
        showError(`Could not load measurements: ${error.message}`);
    }
}

function renderVideos() {
    const videos = state.overview.videos || [];
    elements.videoCards.innerHTML = "";
    if (!videos.length) {
        elements.videoCards.innerHTML = `<div class="empty-state">No video files were found in this execution.</div>`;
        elements.videoViewer.hidden = true;
        return;
    }
    for (const video of videos) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "video-card";
        const stageText = video.start_stage_id == null ? "Stage not recorded" : `Stage ${video.start_stage_id}`;
        button.innerHTML = `<div class="video-thumb">▶</div><div class="video-card-body"><strong>${escapeHtml(video.camera_name || video.name)}</strong><span>${escapeHtml(video.name)} · ${escapeHtml(formatBytes(video.size_bytes))}</span><span>${escapeHtml(stageText)}${video.segment ? ` · Segment ${escapeHtml(video.segment)}` : ""}</span></div>`;
        button.addEventListener("click", () => selectVideo(video, button));
        elements.videoCards.appendChild(button);
    }
}

function selectVideo(video, button) {
    state.selectedVideo = video;
    document.querySelectorAll(".video-card.active").forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    elements.videoViewer.hidden = false;
    elements.videoPlayer.src = video.stream_url;
    elements.videoPlayer.load();
    elements.videoCamera.textContent = video.camera_name || "Camera";
    elements.videoTitle.textContent = video.name;
    elements.videoMeta.textContent = `${formatBytes(video.size_bytes)}${video.segment ? ` · Segment ${video.segment}` : ""}`;
    const rows = [
        ["Started", formatDate(video.start_timestamp)],
        ["Ended", formatDate(video.end_timestamp)],
        ["Experiment time", video.start_elapsed_s == null ? "—" : formatSeconds(video.start_elapsed_s)],
        ["Start stage", valueOrDash(video.start_stage_id)],
        ["End stage", valueOrDash(video.end_stage_id)],
        ["Attempt", valueOrDash(video.stage_attempt)],
    ];
    elements.videoContext.innerHTML = rows.map(([label, value]) => {
        const runtimeAttr = label === "Experiment time" ? ' data-video-runtime="true"' : "";
        return `<span>${escapeHtml(label)} <strong${runtimeAttr}>${escapeHtml(value)}</strong></span>`;
    }).join("");
    elements.videoViewer.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function classifyEvent(eventName) {
    const name = String(eventName || "").toUpperCase();
    if (name.includes("WARNING") || name.includes("ERROR") || name.includes("FAILED")) return "warning";
    if (name.includes("STAGE") || name.includes("TRANSITION") || name.includes("SCRAPING")) return "stage";
    if (name.includes("CAMERA")) return "camera";
    if (name.includes("SENSOR") || name.includes("SCALE") || name.includes("ATLAS")) return "sensor";
    return "other";
}

function eventDescription(event) {
    const data = event.data || {};
    if (data.message) return String(data.message);
    if (data.reason) return String(data.reason);
    const keys = Object.keys(data).filter(key => !["path", "start_monotonic_ns", "end_monotonic_ns"].includes(key));
    if (!keys.length) return "";
    return keys.slice(0, 5).map(key => `${key}: ${valueOrDash(data[key])}`).join(" · ");
}

async function loadEvents() {
    if (state.events) return state.events;
    state.events = await requestJson(`/api/results/${encodeURIComponent(storageId)}/events?limit=5000`);
    return state.events;
}

async function renderEvents() {
    try {
        const data = await loadEvents();
        const events = (data.events || []).filter(event => state.activeEventFilter === "all" || classifyEvent(event.event) === state.activeEventFilter);
        if (!events.length) {
            elements.eventsList.innerHTML = `<div class="empty-state">No events match this filter.</div>`;
            return;
        }
        elements.eventsList.innerHTML = events.map(event => {
            const category = classifyEvent(event.event);
            return `<article class="event-row ${category}"><span class="event-time">${escapeHtml(formatSeconds(event.run_elapsed_s))}</span><span class="event-dot"></span><div class="event-copy"><strong>${escapeHtml(String(event.event || "Event").replaceAll("_", " "))}</strong><span>${escapeHtml(eventDescription(event))}</span></div><span class="event-stage">${escapeHtml(event.stage_name || (event.stage_id == null ? "" : `Stage ${event.stage_id}`))}</span></article>`;
        }).join("");
    } catch (error) {
        showError(`Could not load event journal: ${error.message}`);
    }
}

async function loadSystem() {
    if (state.system) return state.system;
    state.system = await requestJson(`/api/results/${encodeURIComponent(storageId)}/system?max_points=1000`);
    return state.system;
}

async function renderSystem() {
    try {
        const data = await loadSystem();
        const rows = data.rows || [];
        if (!rows.length) {
            elements.systemCards.innerHTML = `<div class="empty-state">system_metrics.tsv is not available for this execution.</div>`;
            return;
        }
        const definitions = [
            ["temperature_c", "Temperature", "°C"],
            ["load1", "CPU load (1 min)", ""],
            ["disk_free_gb", "Free disk space", "GB"],
            ["load5", "CPU load (5 min)", ""],
        ].filter(([key]) => rows.some(row => Number.isFinite(Number(row[key]))));
        elements.systemCards.innerHTML = definitions.map(([key, label, unit], index) => `<article class="system-chart-card"><header><span>${escapeHtml(unit || "System")}</span><strong>${escapeHtml(label)}</strong></header><canvas id="system_chart_${index}" height="220"></canvas></article>`).join("");
        const firstTimestamp = Date.parse(rows[0]?.timestamp || "");
        definitions.forEach(([key, label, unit], index) => {
            const points = rows.map((row, rowIndex) => {
                const timestamp = Date.parse(row.timestamp || "");
                const x = Number.isFinite(timestamp) && Number.isFinite(firstTimestamp)
                    ? Math.max(0, (timestamp - firstTimestamp) / 1000)
                    : rowIndex;
                return { x, y: Number(row[key]) };
            }).filter(point => Number.isFinite(point.y));
            drawLineChart(document.getElementById(`system_chart_${index}`), points, { unit });
        });
    } catch (error) {
        showError(`Could not load system metrics: ${error.message}`);
    }
}

function renderFiles() {
    const query = (elements.fileSearch.value || "").trim().toLowerCase();
    const allFiles = state.overview.files || [];
    const files = allFiles.filter(file => !query || String(file.path).toLowerCase().includes(query));
    elements.fileCount.textContent = `${files.length.toLocaleString()} of ${allFiles.length.toLocaleString()} files`;
    if (!files.length) {
        elements.fileList.innerHTML = `<div class="empty-state">No files match the current search.</div>`;
        return;
    }
    elements.fileList.innerHTML = "";
    for (const file of files) {
        const row = document.createElement("div");
        row.className = "file-row";
        const kind = file.kind === "table" ? "TSV" : file.kind === "video" ? "VID" : file.kind.slice(0, 4).toUpperCase();
        row.innerHTML = `<span class="file-kind">${escapeHtml(kind)}</span><div class="file-name"><strong>${escapeHtml(file.name)}</strong><span>${escapeHtml(file.path)}</span></div><span class="file-size">${escapeHtml(formatBytes(file.size_bytes))}</span><div class="file-actions"></div>`;
        const actions = row.querySelector(".file-actions");
        if (["json", "jsonl", "table", "text"].includes(file.kind)) {
            const view = document.createElement("button");
            view.type = "button";
            view.className = "button button-secondary button-small";
            view.textContent = "View";
            view.addEventListener("click", () => previewFile(file));
            actions.appendChild(view);
        }
        if (file.kind === "video") {
            const view = document.createElement("button");
            view.type = "button";
            view.className = "button button-secondary button-small";
            view.textContent = "Play";
            view.addEventListener("click", () => openVideoFromFile(file));
            actions.appendChild(view);
        }
        const download = document.createElement("a");
        download.className = "button button-secondary button-small";
        download.textContent = "Download";
        download.href = `/api/results/${encodeURIComponent(storageId)}/file?path=${encodeURIComponent(file.path)}&download=true`;
        actions.appendChild(download);
        elements.fileList.appendChild(row);
    }
}

function openVideoFromFile(file) {
    activateTab("videos");
    const video = (state.overview.videos || []).find(item => item.path === file.path);
    if (!video) return;
    const buttons = [...document.querySelectorAll(".video-card")];
    const index = (state.overview.videos || []).findIndex(item => item.path === file.path);
    selectVideo(video, buttons[index] || document.createElement("button"));
}

async function previewFile(file) {
    elements.dialogTitle.textContent = file.path;
    elements.dialogBody.innerHTML = `<div class="loading-block">Loading preview…</div>`;
    elements.dialogDownload.href = `/api/results/${encodeURIComponent(storageId)}/file?path=${encodeURIComponent(file.path)}&download=true`;
    if (typeof elements.dialog.showModal === "function") elements.dialog.showModal();
    else elements.dialog.setAttribute("open", "");
    try {
        if (file.kind === "table") {
            const data = await requestJson(`/api/results/${encodeURIComponent(storageId)}/table?path=${encodeURIComponent(file.path)}&offset=0&limit=100`);
            const columns = data.columns || [];
            elements.dialogBody.innerHTML = `<div class="table-scroll"><table class="data-table"><thead><tr>${columns.map(column => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead><tbody>${(data.rows || []).map(row => `<tr>${columns.map(column => `<td>${escapeHtml(valueOrDash(row[column]))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>${data.total > 100 ? `<p class="file-preview-note">Showing first 100 of ${Number(data.total).toLocaleString()} rows.</p>` : ""}`;
            return;
        }
        const data = await requestJson(`/api/results/${encodeURIComponent(storageId)}/preview?path=${encodeURIComponent(file.path)}`);
        const content = data.kind === "json" && typeof data.content === "object"
            ? JSON.stringify(data.content, null, 2)
            : String(data.content ?? "");
        elements.dialogBody.innerHTML = `<pre>${escapeHtml(content)}${data.truncated ? "\n\n… preview truncated …" : ""}</pre>`;
    } catch (error) {
        elements.dialogBody.innerHTML = `<div class="results-error">${escapeHtml(error.message)}</div>`;
    }
}

function activateTab(name) {
    document.querySelectorAll(".results-tab").forEach(button => button.classList.toggle("active", button.dataset.tab === name));
    document.querySelectorAll(".results-panel").forEach(panel => {
        const active = panel.dataset.panel === name;
        panel.hidden = !active;
        panel.classList.toggle("active", active);
    });
    if (name === "measurements") renderMeasurementsFull();
    if (name === "events") renderEvents();
    if (name === "system") renderSystem();
    if (name === "files") renderFiles();
    if (name === "sensors" && state.sensorSeries) requestAnimationFrame(() => drawLineChart(elements.sensorChart, state.sensorSeries.points || [], { unit: state.selectedSensor?.series?.unit || "" }));
}

function bindEvents() {
    elements.refresh.addEventListener("click", loadResults);
    document.querySelectorAll(".results-tab").forEach(button => button.addEventListener("click", () => activateTab(button.dataset.tab)));
    elements.sensorTableToggle.addEventListener("click", async () => {
        const willShow = elements.sensorTableWrap.hidden;
        elements.sensorTableWrap.hidden = !willShow;
        elements.sensorTableToggle.textContent = willShow ? "Hide table" : "Show table";
        if (willShow) await loadSensorTable();
    });
    elements.sensorPrev.addEventListener("click", async () => {
        state.sensorTableOffset = Math.max(0, state.sensorTableOffset - state.sensorTableLimit);
        await loadSensorTable();
    });
    elements.sensorNext.addEventListener("click", async () => {
        state.sensorTableOffset += state.sensorTableLimit;
        await loadSensorTable();
    });
    elements.eventFilters.addEventListener("click", event => {
        const button = event.target.closest("[data-event-filter]");
        if (!button) return;
        state.activeEventFilter = button.dataset.eventFilter;
        elements.eventFilters.querySelectorAll(".filter-chip").forEach(item => item.classList.toggle("active", item === button));
        renderEvents();
    });
    elements.fileSearch.addEventListener("input", renderFiles);
    elements.dialogClose.addEventListener("click", () => elements.dialog.close ? elements.dialog.close() : elements.dialog.removeAttribute("open"));
    elements.dialog.addEventListener("click", event => {
        if (event.target === elements.dialog) elements.dialog.close?.();
    });
    elements.videoPlayer.addEventListener("timeupdate", () => {
        const video = state.selectedVideo;
        if (!video || video.start_elapsed_s == null) return;
        const runTime = Number(video.start_elapsed_s) + Number(elements.videoPlayer.currentTime || 0);
        const first = elements.videoContext.querySelector("[data-video-runtime]");
        if (first) first.textContent = formatSeconds(runTime);
    });
    window.addEventListener("resize", () => {
        if (state.sensorSeries && !elements.sensorViewer.hidden) drawLineChart(elements.sensorChart, state.sensorSeries.points || [], { unit: state.selectedSensor?.series?.unit || "" });
    });
}

bindEvents();
loadResults();
