const root = document.getElementById("results_root");
const storageId = root?.dataset.storageId || "";

const state = {
    overview: null,
    measurements: null,
    events: null,
    system: null,
    analysisLoaded: false,
    analysisLoading: false,
    tracks: new Map(),
    viewStart: 0,
    viewEnd: 1,
    cursorTime: null,
    drag: null,
    selectedVideo: null,
    activeVideoTrackKey: null,
    refreshTimer: null,
};

const elements = {
    title: document.getElementById("result_title"),
    status: document.getElementById("result_status"),
    meta: document.getElementById("result_meta"),
    refresh: document.getElementById("refresh_results"),
    error: document.getElementById("results_error"),
    globalLoading: document.getElementById("global_loading"),
    summary: document.getElementById("summary_cards"),
    experimentParameters: document.getElementById("experiment_parameters"),
    runtimeParameters: document.getElementById("runtime_parameters"),
    stageCount: document.getElementById("overview_stage_count"),
    stages: document.getElementById("overview_stages"),
    analysisSensorSelector: document.getElementById("analysis_sensor_selector"),
    analysisMeasurementSelector: document.getElementById("analysis_measurement_selector"),
    analysisEventSelector: document.getElementById("analysis_event_selector"),
    analysisVideoSelector: document.getElementById("analysis_video_selector"),
    analysisSystemSelector: document.getElementById("analysis_system_selector"),
    analysisWorkspace: document.getElementById("analysis_workspace"),
    analysisStageTrack: document.getElementById("analysis_stage_track"),
    analysisTracks: document.getElementById("analysis_tracks"),
    analysisEmpty: document.getElementById("analysis_empty"),
    analysisTimeAxis: document.getElementById("analysis_time_axis"),
    analysisRangeLabel: document.getElementById("analysis_range_label"),
    analysisCursorInfo: document.getElementById("analysis_cursor_info"),
    analysisZoomIn: document.getElementById("analysis_zoom_in"),
    analysisZoomOut: document.getElementById("analysis_zoom_out"),
    analysisFit: document.getElementById("analysis_fit"),
    videoViewer: document.getElementById("analysis_video_viewer"),
    videoPlayer: document.getElementById("video_player"),
    videoCamera: document.getElementById("video_camera"),
    videoTitle: document.getElementById("video_title"),
    videoMeta: document.getElementById("video_meta"),
    videoContext: document.getElementById("video_context"),
    videoLoading: document.getElementById("video_loading"),
    videoLoadingText: document.getElementById("video_loading_text"),
    videoError: document.getElementById("video_error"),
    videoClose: document.getElementById("video_close"),
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

function formatAxisTime(value) {
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) return "—";
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds - minutes * 60;
    if (minutes >= 60) {
        const hours = Math.floor(minutes / 60);
        const min = minutes % 60;
        return `${hours}:${String(min).padStart(2, "0")}:${String(Math.floor(remainder)).padStart(2, "0")}`;
    }
    return `${minutes}:${String(Math.floor(remainder)).padStart(2, "0")}`;
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

function setLoading(element, message) {
    element.innerHTML = `<div class="selector-loading"><span class="loading-spinner small" aria-hidden="true"></span><span>${escapeHtml(message)}</span></div>`;
}

function experimentDuration() {
    return Math.max(Number(state.overview?.timeline?.duration_s) || 0, 0.001);
}

function currentStages() {
    return Array.isArray(state.overview?.timeline?.stages) ? state.overview.timeline.stages : [];
}

function currentStageAt(time) {
    const t = Number(time);
    return currentStages().find(stage => {
        const start = Number(stage.start_s);
        const end = Number(stage.end_s);
        return Number.isFinite(start) && Number.isFinite(end) && t >= start && t <= end;
    }) || null;
}

async function loadResults() {
    if (!storageId) {
        showError("Missing local experiment ID.");
        return;
    }
    elements.refresh.disabled = true;
    elements.globalLoading.hidden = false;
    clearError();
    try {
        state.overview = await requestJson(`/api/results/${encodeURIComponent(storageId)}`);
        state.measurements = null;
        state.events = null;
        state.system = null;
        state.analysisLoaded = false;
        state.tracks.clear();
        state.selectedVideo = null;
        state.activeVideoTrackKey = null;
        const duration = experimentDuration();
        state.viewStart = 0;
        state.viewEnd = duration;
        state.cursorTime = null;
        renderHeader();
        renderSummary();
        renderOverview();
        renderAnalysisSelectorsBase();
        renderFiles();
        renderAnalysis();
    } catch (error) {
        showError(`Could not load experiment results: ${error.message}`);
        elements.title.textContent = "Experiment results unavailable";
    } finally {
        elements.refresh.disabled = false;
        elements.globalLoading.hidden = true;
    }
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
    const experimentFile = (state.overview.files || []).find(file => file.path === "experiment.json");
    const download = document.getElementById("download_experiment");
    if (experimentFile) {
        download.href = `/api/results/${encodeURIComponent(storageId)}/file?path=${encodeURIComponent("experiment.json")}&download=true`;
        download.hidden = false;
    }
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
        <article class="summary-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>
    `).join("");
}

function parameterItem(label, value) {
    return `<div class="parameter-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(valueOrDash(value))}</strong></div>`;
}

function renderOverview() {
    const experiment = state.overview.experiment || {};
    const runtime = state.overview.runtime || {};
    const summary = state.overview.summary || {};
    elements.experimentParameters.innerHTML = [
        ["Name", experiment.name],
        ["ID", experiment.id],
        ["pH", experiment.ph ?? experiment.exp_ph],
        ["Airflow", experiment.airflow ?? experiment.exp_airflow],
        ["Rotor speed", experiment.rotor_speed ?? experiment.exp_rotor_speed],
        ["Created", formatDate(experiment.local_created || experiment.creation_time)],
    ].map(([label, value]) => parameterItem(label, value)).join("");

    elements.runtimeParameters.innerHTML = [
        ["Status", summary.status || runtime.state],
        ["Run ID", storageId],
        ["Duration", formatSeconds(summary.duration_s)],
        ["Current stage", runtime.stage_name || runtime.current_stage_name],
        ["Stage state", runtime.stage_state],
        ["Updated", formatDate(runtime.updated_at || runtime.timestamp)],
    ].map(([label, value]) => parameterItem(label, value)).join("");

    const stages = currentStages();
    elements.stageCount.textContent = String(stages.length);
    elements.stages.innerHTML = stages.length ? stages.map((stage, index) => `
        <article class="stage-result-card">
            <header><strong>${escapeHtml(stage.stage_name || `Stage ${index + 1}`)}</strong><span>${escapeHtml(stage.stage_type || "stage")}</span></header>
            <small>${escapeHtml(stage.outcome || "")}</small>
            <div class="stage-result-metrics">
                <div><span>Start</span><strong>${escapeHtml(formatSeconds(stage.start_s))}</strong></div>
                <div><span>End</span><strong>${escapeHtml(formatSeconds(stage.end_s))}</strong></div>
            </div>
        </article>
    `).join("") : `<div class="empty-state">No stage timeline is available.</div>`;
}

function renderAnalysisSelectorsBase() {
    renderSensorSelectors();
    renderVideoSelectors();
    setLoading(elements.analysisMeasurementSelector, "Loading measurements…");
    setLoading(elements.analysisEventSelector, "Loading event journal…");
    setLoading(elements.analysisSystemSelector, "Loading system metrics…");
}

function selectorButton({ key, label, meta = "", kind }) {
    const active = state.tracks.has(key);
    return `<button type="button" class="selector-item${active ? " active" : ""}" data-track-key="${escapeHtml(key)}" data-track-kind="${escapeHtml(kind)}" aria-pressed="${active ? "true" : "false"}"><span><strong>${escapeHtml(label)}</strong>${meta ? `<small>${escapeHtml(meta)}</small>` : ""}</span><span class="selector-state">${active ? "−" : "+"}</span></button>`;
}

function renderSensorSelectors() {
    const sensors = state.overview?.sensors || [];
    const buttons = [];
    sensors.forEach(source => {
        (source.series || []).forEach(series => {
            const key = `sensor:${source.path}:${series.id}`;
            buttons.push(selectorButton({
                key,
                kind: "sensor",
                label: series.name || series.id,
                meta: `${source.name} · ${Number(series.numeric_count || 0).toLocaleString()} numeric sample(s)${series.unit ? ` · ${series.unit}` : ""}`,
            }));
        });
    });
    elements.analysisSensorSelector.innerHTML = buttons.length ? buttons.join("") : `<div class="selector-empty">No sensor series recorded.</div>`;
}

function groupVideosByCamera() {
    const groups = new Map();
    for (const video of state.overview?.videos || []) {
        const camera = video.camera_name || video.camera_id || "Camera";
        const key = String(camera);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(video);
    }
    for (const videos of groups.values()) {
        videos.sort((a, b) => (Number(a.start_elapsed_s) || 0) - (Number(b.start_elapsed_s) || 0));
    }
    return groups;
}

function renderVideoSelectors() {
    const groups = groupVideosByCamera();
    if (!groups.size) {
        elements.analysisVideoSelector.innerHTML = `<div class="selector-empty">No video recordings found.</div>`;
        return;
    }
    elements.analysisVideoSelector.innerHTML = [...groups.entries()].map(([camera, videos]) => {
        const key = `video:${camera}`;
        const codecs = [...new Set(videos.map(video => video.codec).filter(Boolean))].join(", ") || "codec unknown";
        return selectorButton({ key, kind: "video", label: camera, meta: `${videos.length} segment(s) · ${codecs}` });
    }).join("");
}

async function loadAnalysisData() {
    if (state.analysisLoaded || state.analysisLoading) return;
    state.analysisLoading = true;
    elements.analysisWorkspace.setAttribute("aria-busy", "true");
    try {
        const [measurements, events, system] = await Promise.allSettled([
            requestJson(`/api/results/${encodeURIComponent(storageId)}/measurements`),
            requestJson(`/api/results/${encodeURIComponent(storageId)}/events?offset=0&limit=5000`),
            requestJson(`/api/results/${encodeURIComponent(storageId)}/system?max_points=2500`),
        ]);
        state.measurements = measurements.status === "fulfilled" ? measurements.value : { variables: [], observations: [], error: measurements.reason?.message };
        state.events = events.status === "fulfilled" ? events.value : { events: [], error: events.reason?.message };
        state.system = system.status === "fulfilled" ? system.value : { columns: [], rows: [], error: system.reason?.message };
        renderMeasurementSelectors();
        renderEventSelectors();
        renderSystemSelectors();
        state.analysisLoaded = true;
    } finally {
        state.analysisLoading = false;
        elements.analysisWorkspace.setAttribute("aria-busy", "false");
    }
}

function renderMeasurementSelectors() {
    if (state.measurements?.error) {
        elements.analysisMeasurementSelector.innerHTML = `<div class="selector-error">${escapeHtml(state.measurements.error)}</div>`;
        return;
    }
    const variables = state.measurements?.variables || [];
    elements.analysisMeasurementSelector.innerHTML = variables.length ? variables.map(variable => selectorButton({
        key: `measurement:${variable.id}`,
        kind: "measurement",
        label: variable.name || variable.id,
        meta: `${Number(variable.count || 0).toLocaleString()} observation(s)${variable.unit ? ` · ${variable.unit}` : ""}`,
    })).join("") : `<div class="selector-empty">No operator measurements recorded.</div>`;
}

function classifyEvent(eventName) {
    const name = String(eventName || "").toUpperCase();
    if (name.includes("WARNING") || name.includes("ERROR") || name.includes("FAILED") || name.includes("SKIPPED") || name.includes("OFFLINE")) return "warning";
    if (name.includes("STAGE") || name.includes("TRANSITION") || name.includes("PAUSE") || name.includes("RESUME")) return "stage";
    if (name.includes("CAMERA") || name.includes("RECORDING")) return "camera";
    if (name.includes("SENSOR") || name.includes("SCALE") || name.includes("ATLAS")) return "sensor";
    return "other";
}

function renderEventSelectors() {
    if (state.events?.error) {
        elements.analysisEventSelector.innerHTML = `<div class="selector-error">${escapeHtml(state.events.error)}</div>`;
        return;
    }
    const events = state.events?.events || [];
    if (!events.length) {
        elements.analysisEventSelector.innerHTML = `<div class="selector-empty">No events recorded.</div>`;
        return;
    }
    const defs = [
        ["warning", "Warnings"],
        ["stage", "Stage events"],
        ["camera", "Camera events"],
        ["sensor", "Sensor events"],
        ["other", "Other events"],
    ];
    elements.analysisEventSelector.innerHTML = defs.map(([category, label]) => {
        const count = events.filter(event => classifyEvent(event.event) === category).length;
        return count ? selectorButton({ key: `event:${category}`, kind: "event", label, meta: `${count.toLocaleString()} event(s)` }) : "";
    }).join("") || `<div class="selector-empty">No plottable events recorded.</div>`;
}

function systemUnit(key) {
    const normalized = String(key).toLowerCase();
    if (normalized.includes("temp")) return "°C";
    if (normalized.includes("percent") || normalized.includes("usage")) return "%";
    if (normalized.includes("gb")) return "GB";
    if (normalized.includes("mb")) return "MB";
    if (normalized.includes("fps")) return "fps";
    return "";
}

function humanizeKey(key) {
    return String(key).replaceAll("_", " ").replace(/\b\w/g, match => match.toUpperCase());
}

function systemElapsedRows() {
    const rows = state.system?.rows || [];
    if (!rows.length) return [];
    const timestampKey = ["timestamp", "datetime", "time"].find(key => rows.some(row => row[key] != null));
    const firstTimestamp = timestampKey ? Date.parse(rows.find(row => row[timestampKey])?.[timestampKey] || "") : NaN;
    return rows.map((row, index) => {
        let elapsed = Number(row.run_elapsed_s ?? row.elapsed_s);
        if (!Number.isFinite(elapsed) && timestampKey) {
            const timestamp = Date.parse(row[timestampKey] || "");
            if (Number.isFinite(timestamp) && Number.isFinite(firstTimestamp)) elapsed = Math.max(0, (timestamp - firstTimestamp) / 1000);
        }
        if (!Number.isFinite(elapsed)) elapsed = index;
        return { ...row, __elapsed_s: elapsed };
    });
}

function renderSystemSelectors() {
    if (state.system?.error) {
        elements.analysisSystemSelector.innerHTML = `<div class="selector-error">${escapeHtml(state.system.error)}</div>`;
        return;
    }
    const rows = systemElapsedRows();
    const ignore = new Set(["timestamp", "datetime", "time", "run_elapsed_s", "elapsed_s", "timestamp_ns", "monotonic_ns"]);
    const columns = (state.system?.columns || []).filter(key => !ignore.has(key) && rows.some(row => Number.isFinite(Number(row[key]))));
    elements.analysisSystemSelector.innerHTML = columns.length ? columns.map(key => selectorButton({
        key: `system:${key}`,
        kind: "system",
        label: humanizeKey(key),
        meta: systemUnit(key) || "System metric",
    })).join("") : `<div class="selector-empty">No numeric system metrics recorded.</div>`;
}

function lookupTrackDefinition(key, kind) {
    if (kind === "sensor") {
        for (const source of state.overview?.sensors || []) {
            for (const series of source.series || []) {
                if (`sensor:${source.path}:${series.id}` === key) {
                    return { key, kind, label: series.name || series.id, unit: series.unit || "", source, series, data: null, loading: true, error: null };
                }
            }
        }
    }
    if (kind === "measurement") {
        const id = key.slice("measurement:".length);
        const variable = (state.measurements?.variables || []).find(item => String(item.id) === id);
        if (variable) {
            const points = (state.measurements.observations || [])
                .filter(item => String(item.variable_id || item.variable_name) === id)
                .map(item => ({ x: Number(item.run_elapsed_s), y: Number(item.value), raw: item }))
                .filter(point => Number.isFinite(point.x) && Number.isFinite(point.y));
            return { key, kind, label: variable.name || id, unit: variable.unit || "", variable, points, loading: false, error: null };
        }
    }
    if (kind === "event") {
        const category = key.slice("event:".length);
        const labelMap = { warning: "Warnings", stage: "Stage events", camera: "Camera events", sensor: "Sensor events", other: "Other events" };
        const events = (state.events?.events || []).filter(event => classifyEvent(event.event) === category && Number.isFinite(Number(event.run_elapsed_s)));
        return { key, kind, label: labelMap[category] || humanizeKey(category), category, events, loading: false, error: null };
    }
    if (kind === "video") {
        const camera = key.slice("video:".length);
        const videos = groupVideosByCamera().get(camera) || [];
        return { key, kind, label: camera, videos, loading: false, error: null };
    }
    if (kind === "system") {
        const metric = key.slice("system:".length);
        const points = systemElapsedRows().map(row => ({ x: Number(row.__elapsed_s), y: Number(row[metric]), raw: row })).filter(point => Number.isFinite(point.x) && Number.isFinite(point.y));
        return { key, kind, label: humanizeKey(metric), unit: systemUnit(metric), metric, points, loading: false, error: null };
    }
    return null;
}

async function toggleTrack(key, kind) {
    if (state.tracks.has(key)) {
        state.tracks.delete(key);
        if (state.activeVideoTrackKey === key) {
            state.activeVideoTrackKey = null;
            closeVideoPlayer();
        }
        renderAnalysisSelectors();
        renderTracks();
        return;
    }
    const track = lookupTrackDefinition(key, kind);
    if (!track) return;
    state.tracks.set(key, track);
    if (kind === "video") state.activeVideoTrackKey = key;
    renderAnalysisSelectors();
    renderTracks();
    if (kind === "sensor") await loadSensorTrack(track);
}

function renderAnalysisSelectors() {
    renderSensorSelectors();
    renderVideoSelectors();
    if (state.analysisLoaded) {
        renderMeasurementSelectors();
        renderEventSelectors();
        renderSystemSelectors();
    }
}

async function loadSensorTrack(track) {
    const requestId = (track.requestId || 0) + 1;
    track.requestId = requestId;
    track.loading = true;
    track.error = null;
    renderTracks();
    try {
        const params = new URLSearchParams({
            path: track.source.path,
            series: track.series.id,
            start: String(state.viewStart),
            end: String(state.viewEnd),
            max_points: "1800",
        });
        const data = await requestJson(`/api/results/${encodeURIComponent(storageId)}/series?${params}`);
        if (state.tracks.get(track.key) !== track || track.requestId !== requestId) return;
        track.data = data;
    } catch (error) {
        if (state.tracks.get(track.key) !== track || track.requestId !== requestId) return;
        track.error = error.message;
    } finally {
        if (state.tracks.get(track.key) !== track || track.requestId !== requestId) return;
        track.loading = false;
        renderTracks();
    }
}

function scheduleRangeRefresh() {
    clearTimeout(state.refreshTimer);
    state.refreshTimer = setTimeout(() => {
        for (const track of state.tracks.values()) {
            if (track.kind === "sensor") loadSensorTrack(track);
        }
    }, 260);
}

function setViewRange(start, end, { refresh = true } = {}) {
    const duration = experimentDuration();
    let a = Math.max(0, Math.min(Number(start), duration));
    let b = Math.max(0, Math.min(Number(end), duration));
    if (!Number.isFinite(a) || !Number.isFinite(b)) return;
    if (b < a) [a, b] = [b, a];
    const minWidth = Math.min(Math.max(duration * 0.002, 0.5), duration);
    if (b - a < minWidth) {
        const center = (a + b) / 2;
        a = Math.max(0, center - minWidth / 2);
        b = Math.min(duration, a + minWidth);
        a = Math.max(0, b - minWidth);
    }
    state.viewStart = a;
    state.viewEnd = b;
    renderAnalysis();
    if (refresh) scheduleRangeRefresh();
}

function zoomView(factor) {
    const center = state.cursorTime != null && state.cursorTime >= state.viewStart && state.cursorTime <= state.viewEnd
        ? state.cursorTime
        : (state.viewStart + state.viewEnd) / 2;
    const width = (state.viewEnd - state.viewStart) * factor;
    const leftRatio = (center - state.viewStart) / Math.max(state.viewEnd - state.viewStart, 1e-9);
    setViewRange(center - width * leftRatio, center + width * (1 - leftRatio));
}

function fitExperiment() {
    setViewRange(0, experimentDuration());
}

function renderAnalysis() {
    if (!state.overview) return;
    renderRangeLabel();
    renderStageTrack();
    renderTimeAxis();
    renderTracks();
    renderCursorInfo();
}

function renderRangeLabel() {
    elements.analysisRangeLabel.textContent = `${formatAxisTime(state.viewStart)} – ${formatAxisTime(state.viewEnd)} · ${formatSeconds(state.viewEnd - state.viewStart)}`;
}

function percentageForTime(time) {
    return ((Number(time) - state.viewStart) / Math.max(state.viewEnd - state.viewStart, 1e-9)) * 100;
}

function renderStageTrack() {
    const stages = currentStages().filter(stage => Number(stage.end_s) >= state.viewStart && Number(stage.start_s) <= state.viewEnd);
    if (!stages.length) {
        elements.analysisStageTrack.innerHTML = `<div class="empty-state compact">No stage information in this range.</div>`;
        return;
    }
    const html = stages.map((stage, index) => {
        const start = Math.max(Number(stage.start_s) || 0, state.viewStart);
        const end = Math.min(Number(stage.end_s) || start, state.viewEnd);
        const left = Math.max(0, percentageForTime(start));
        const width = Math.max(0.35, percentageForTime(end) - left);
        return `<button type="button" class="analysis-stage-segment stage-${index % 2}" style="left:${left}%;width:${width}%" data-stage-index="${currentStages().indexOf(stage)}" title="${escapeHtml(stage.stage_name || "Stage")}: ${escapeHtml(formatSeconds(stage.start_s))} – ${escapeHtml(formatSeconds(stage.end_s))}"><strong>${escapeHtml(stage.stage_name || `Stage ${index + 1}`)}</strong><span>${escapeHtml(stage.stage_type || "")}</span></button>`;
    }).join("");
    const cursor = Number.isFinite(Number(state.cursorTime)) && state.cursorTime >= state.viewStart && state.cursorTime <= state.viewEnd
        ? `<span class="shared-cursor stage-cursor" style="left:${percentageForTime(state.cursorTime)}%"></span>` : "";
    elements.analysisStageTrack.innerHTML = html + cursor;
}

function renderTimeAxis() {
    const ticks = 5;
    elements.analysisTimeAxis.innerHTML = Array.from({ length: ticks }, (_, index) => {
        const fraction = index / (ticks - 1);
        const time = state.viewStart + fraction * (state.viewEnd - state.viewStart);
        return `<span style="left:${fraction * 100}%">${escapeHtml(formatAxisTime(time))}</span>`;
    }).join("");
}

function trackSubtitle(track) {
    if (track.kind === "sensor") return `${track.source.name || "Sensor"}${track.unit ? ` · ${track.unit}` : ""}`;
    if (track.kind === "measurement") return `Operator measurement${track.unit ? ` · ${track.unit}` : ""}`;
    if (track.kind === "event") return `${track.events.length.toLocaleString()} event(s)`;
    if (track.kind === "video") return `${track.videos.length.toLocaleString()} segment(s)`;
    if (track.kind === "system") return `System metric${track.unit ? ` · ${track.unit}` : ""}`;
    return "";
}

function renderTracks() {
    const tracks = [...state.tracks.values()];
    elements.analysisEmpty.hidden = tracks.length > 0;
    elements.analysisTracks.querySelectorAll(".analysis-track-row").forEach(row => row.remove());
    for (const track of tracks) {
        const row = document.createElement("article");
        row.className = `analysis-track-row kind-${track.kind}`;
        row.dataset.trackKey = track.key;
        const compact = track.kind === "event" || track.kind === "video";
        row.innerHTML = `
            <div class="track-label">
                <div><strong>${escapeHtml(track.label)}</strong><span>${escapeHtml(trackSubtitle(track))}</span></div>
                <button class="track-remove" type="button" title="Remove track" aria-label="Remove ${escapeHtml(track.label)}">×</button>
            </div>
            <div class="track-canvas-wrap${compact ? " compact" : ""}">
                <canvas class="analysis-canvas" height="${compact ? 96 : 176}" aria-label="${escapeHtml(track.label)} timeline"></canvas>
                <div class="track-overlay" hidden></div>
            </div>`;
        row.querySelector(".track-remove").addEventListener("click", () => toggleTrack(track.key, track.kind));
        elements.analysisTracks.appendChild(row);
        const canvas = row.querySelector("canvas");
        bindCanvasInteractions(canvas, track);
        drawTrack(track, canvas, row.querySelector(".track-overlay"));
    }
}

function cssVar(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
}

function prepareCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const width = Math.max(10, rect.width || canvas.parentElement?.clientWidth || 600);
    const height = Math.max(60, Number(canvas.getAttribute("height")) || rect.height || 176);
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return { ctx, width, height };
}

function xForTime(time, width, left = 48, right = 12) {
    return left + ((Number(time) - state.viewStart) / Math.max(state.viewEnd - state.viewStart, 1e-9)) * Math.max(1, width - left - right);
}

function timeForCanvasX(clientX, canvas, left = 48, right = 12) {
    const rect = canvas.getBoundingClientRect();
    const usable = Math.max(1, rect.width - left - right);
    const px = Math.max(0, Math.min(usable, clientX - rect.left - left));
    return state.viewStart + (px / usable) * (state.viewEnd - state.viewStart);
}

function drawStageBands(ctx, width, height, left = 48, right = 12) {
    const stages = currentStages();
    ctx.save();
    stages.forEach((stage, index) => {
        const start = Math.max(Number(stage.start_s) || 0, state.viewStart);
        const end = Math.min(Number(stage.end_s) || start, state.viewEnd);
        if (end < state.viewStart || start > state.viewEnd || end <= start) return;
        const x1 = xForTime(start, width, left, right);
        const x2 = xForTime(end, width, left, right);
        ctx.fillStyle = index % 2 === 0 ? "rgba(47,111,237,0.055)" : "rgba(114,84,216,0.045)";
        ctx.fillRect(x1, 0, Math.max(1, x2 - x1), height);
        ctx.strokeStyle = "rgba(127,127,127,0.13)";
        ctx.beginPath();
        ctx.moveTo(x1, 0);
        ctx.lineTo(x1, height);
        ctx.stroke();
    });
    ctx.restore();
}

function drawSharedCursor(ctx, width, height, left = 48, right = 12) {
    if (!Number.isFinite(Number(state.cursorTime)) || state.cursorTime < state.viewStart || state.cursorTime > state.viewEnd) return;
    const x = xForTime(state.cursorTime, width, left, right);
    ctx.save();
    ctx.strokeStyle = cssVar("--text", "#222");
    ctx.globalAlpha = 0.42;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
    ctx.restore();
}

function drawDragSelection(ctx, width, height, left = 48, right = 12) {
    if (!state.drag || !Number.isFinite(state.drag.startTime) || !Number.isFinite(state.drag.endTime)) return;
    const a = Math.max(state.viewStart, Math.min(state.drag.startTime, state.drag.endTime));
    const b = Math.min(state.viewEnd, Math.max(state.drag.startTime, state.drag.endTime));
    if (b <= a) return;
    const x1 = xForTime(a, width, left, right);
    const x2 = xForTime(b, width, left, right);
    ctx.save();
    ctx.fillStyle = "rgba(47,111,237,0.13)";
    ctx.strokeStyle = "rgba(47,111,237,0.7)";
    ctx.fillRect(x1, 0, x2 - x1, height);
    ctx.strokeRect(x1, 0, x2 - x1, height);
    ctx.restore();
}

function visiblePoints(points) {
    return (points || []).filter(point => Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y)) && Number(point.x) >= state.viewStart && Number(point.x) <= state.viewEnd);
}

function drawNumericTrack(track, canvas, points, mode = "line") {
    const { ctx, width, height } = prepareCanvas(canvas);
    const left = 48;
    const right = 12;
    const top = 14;
    const bottom = 18;
    drawStageBands(ctx, width, height, left, right);
    const valid = visiblePoints(points);
    if (!valid.length) {
        drawSharedCursor(ctx, width, height, left, right);
        drawDragSelection(ctx, width, height, left, right);
        return false;
    }
    let minY = Math.min(...valid.map(point => Number(point.y)));
    let maxY = Math.max(...valid.map(point => Number(point.y)));
    if (minY === maxY) {
        const pad = Math.abs(minY) > 1e-9 ? Math.abs(minY) * 0.05 : 1;
        minY -= pad;
        maxY += pad;
    } else {
        const pad = (maxY - minY) * 0.08;
        minY -= pad;
        maxY += pad;
    }
    const yFor = value => top + (1 - (Number(value) - minY) / (maxY - minY)) * (height - top - bottom);
    const plotColor = mode === "points" ? cssVar("--success", "#18845b") : track.kind === "system" ? cssVar("--preview", "#7254d8") : cssVar("--accent", "#2f6fed");
    ctx.save();
    ctx.strokeStyle = "rgba(127,127,127,.16)";
    ctx.fillStyle = cssVar("--text-soft", "#666");
    ctx.font = "11px system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let i = 0; i < 3; i += 1) {
        const fraction = i / 2;
        const y = top + fraction * (height - top - bottom);
        const value = maxY - fraction * (maxY - minY);
        ctx.beginPath();
        ctx.moveTo(left, y);
        ctx.lineTo(width - right, y);
        ctx.stroke();
        ctx.fillText(formatNumber(value, 2), left - 6, y);
    }
    if (mode === "line") {
        ctx.strokeStyle = plotColor;
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        valid.forEach((point, index) => {
            const x = xForTime(point.x, width, left, right);
            const y = yFor(point.y);
            if (index === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
    } else {
        ctx.fillStyle = plotColor;
        for (const point of valid) {
            const x = xForTime(point.x, width, left, right);
            const y = yFor(point.y);
            ctx.beginPath();
            ctx.arc(x, y, 4, 0, Math.PI * 2);
            ctx.fill();
        }
    }
    ctx.restore();
    drawSharedCursor(ctx, width, height, left, right);
    drawDragSelection(ctx, width, height, left, right);
    return true;
}

function eventColor(category) {
    return {
        warning: cssVar("--warning", "#c47a12"),
        stage: cssVar("--accent", "#2f6fed"),
        camera: cssVar("--preview", "#7254d8"),
        sensor: cssVar("--success", "#18845b"),
        other: cssVar("--text-soft", "#666"),
    }[category] || cssVar("--text-soft", "#666");
}

function drawEventTrack(track, canvas) {
    const { ctx, width, height } = prepareCanvas(canvas);
    const left = 48;
    const right = 12;
    drawStageBands(ctx, width, height, left, right);
    const y = height / 2;
    ctx.strokeStyle = "rgba(127,127,127,.25)";
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(width - right, y);
    ctx.stroke();
    ctx.fillStyle = eventColor(track.category);
    let visible = 0;
    for (const event of track.events || []) {
        const time = Number(event.run_elapsed_s);
        if (!Number.isFinite(time) || time < state.viewStart || time > state.viewEnd) continue;
        visible += 1;
        const x = xForTime(time, width, left, right);
        ctx.beginPath();
        ctx.arc(x, y, track.category === "warning" ? 5 : 4, 0, Math.PI * 2);
        ctx.fill();
    }
    drawSharedCursor(ctx, width, height, left, right);
    drawDragSelection(ctx, width, height, left, right);
    return visible > 0;
}

function drawVideoTrack(track, canvas) {
    const { ctx, width, height } = prepareCanvas(canvas);
    const left = 48;
    const right = 12;
    drawStageBands(ctx, width, height, left, right);
    const top = 26;
    const barHeight = Math.max(20, height - 52);
    let visible = 0;
    for (const video of track.videos || []) {
        const start = Number(video.start_elapsed_s);
        let end = Number(video.end_elapsed_s);
        if (!Number.isFinite(start)) continue;
        if (!Number.isFinite(end)) end = start + (Number(video.duration_s) || 0);
        if (end < state.viewStart || start > state.viewEnd) continue;
        visible += 1;
        const x1 = xForTime(Math.max(start, state.viewStart), width, left, right);
        const x2 = xForTime(Math.min(Math.max(end, start + 0.1), state.viewEnd), width, left, right);
        ctx.fillStyle = video.needs_proxy ? "rgba(196,122,18,.32)" : "rgba(114,84,216,.33)";
        ctx.strokeStyle = video.needs_proxy ? cssVar("--warning", "#c47a12") : cssVar("--preview", "#7254d8");
        ctx.fillRect(x1, top, Math.max(2, x2 - x1), barHeight);
        ctx.strokeRect(x1, top, Math.max(2, x2 - x1), barHeight);
    }
    drawSharedCursor(ctx, width, height, left, right);
    drawDragSelection(ctx, width, height, left, right);
    return visible > 0;
}

function drawTrack(track, canvas, overlay) {
    overlay.hidden = true;
    overlay.textContent = "";
    if (track.loading) {
        overlay.hidden = false;
        overlay.innerHTML = `<span class="loading-spinner small"></span><span>Loading data…</span>`;
        prepareCanvas(canvas);
        return;
    }
    if (track.error) {
        overlay.hidden = false;
        overlay.textContent = track.error;
        prepareCanvas(canvas);
        return;
    }
    let hasData = false;
    if (track.kind === "sensor") hasData = drawNumericTrack(track, canvas, track.data?.points || [], "line");
    if (track.kind === "measurement") hasData = drawNumericTrack(track, canvas, track.points || [], "points");
    if (track.kind === "system") hasData = drawNumericTrack(track, canvas, track.points || [], "line");
    if (track.kind === "event") hasData = drawEventTrack(track, canvas);
    if (track.kind === "video") hasData = drawVideoTrack(track, canvas);
    if (!hasData) {
        overlay.hidden = false;
        overlay.textContent = track.kind === "sensor"
            ? "No numeric samples are available in the visible range."
            : "No data are available in the visible range.";
    }
}

function bindCanvasInteractions(canvas, track) {
    canvas.addEventListener("pointerdown", event => {
        const startTime = timeForCanvasX(event.clientX, canvas);
        state.drag = { pointerId: event.pointerId, canvas, startX: event.clientX, startTime, endTime: startTime };
        canvas.setPointerCapture?.(event.pointerId);
    });
    canvas.addEventListener("pointermove", event => {
        const time = timeForCanvasX(event.clientX, canvas);
        state.cursorTime = time;
        if (state.drag?.pointerId === event.pointerId) state.drag.endTime = time;
        drawAllTracksOnly();
        renderCursorInfo();
    });
    canvas.addEventListener("pointerup", event => {
        const drag = state.drag;
        const time = timeForCanvasX(event.clientX, canvas);
        state.cursorTime = time;
        if (drag && drag.pointerId === event.pointerId && Math.abs(event.clientX - drag.startX) > 10) {
            const start = Math.min(drag.startTime, time);
            const end = Math.max(drag.startTime, time);
            state.drag = null;
            setViewRange(start, end);
        } else {
            state.drag = null;
            syncVideoToTime(time, track);
            drawAllTracksOnly();
            renderCursorInfo();
        }
    });
    canvas.addEventListener("pointercancel", () => {
        state.drag = null;
        drawAllTracksOnly();
    });
    canvas.addEventListener("dblclick", () => fitExperiment());
}

function drawAllTracksOnly() {
    renderStageTrack();
    for (const track of state.tracks.values()) {
        const row = [...elements.analysisTracks.querySelectorAll(".analysis-track-row")].find(item => item.dataset.trackKey === track.key);
        if (!row) continue;
        drawTrack(track, row.querySelector("canvas"), row.querySelector(".track-overlay"));
    }
}

function nearestPoint(points, time) {
    let best = null;
    let bestDistance = Infinity;
    for (const point of points || []) {
        const x = Number(point.x);
        if (!Number.isFinite(x)) continue;
        const distance = Math.abs(x - time);
        if (distance < bestDistance) {
            best = point;
            bestDistance = distance;
        }
    }
    return best ? { point: best, distance: bestDistance } : null;
}

function renderCursorInfo() {
    if (!Number.isFinite(Number(state.cursorTime))) {
        elements.analysisCursorInfo.textContent = "Move over a track to inspect a time.";
        return;
    }
    const time = Number(state.cursorTime);
    const stage = currentStageAt(time);
    const pieces = [`${formatAxisTime(time)}`];
    if (stage) pieces.push(stage.stage_name || `Stage ${stage.stage_id}`);
    for (const track of state.tracks.values()) {
        if (track.kind === "sensor") {
            const nearest = nearestPoint(track.data?.points || [], time);
            if (nearest && nearest.distance <= Math.max((state.viewEnd - state.viewStart) * 0.025, 1)) pieces.push(`${track.label}: ${withUnit(nearest.point.y, track.unit)}`);
        } else if (track.kind === "measurement" || track.kind === "system") {
            const nearest = nearestPoint(track.points || [], time);
            if (nearest && nearest.distance <= Math.max((state.viewEnd - state.viewStart) * 0.025, 1)) pieces.push(`${track.label}: ${withUnit(nearest.point.y, track.unit)}`);
        }
    }
    elements.analysisCursorInfo.textContent = pieces.join(" · ");
}

function findVideoAtTime(videos, time) {
    return (videos || []).find(video => {
        const start = Number(video.start_elapsed_s);
        let end = Number(video.end_elapsed_s);
        if (!Number.isFinite(start)) return false;
        if (!Number.isFinite(end)) end = start + (Number(video.duration_s) || 0);
        return time >= start && time <= end;
    }) || null;
}

function syncVideoToTime(time, sourceTrack = null) {
    let videoTrack = sourceTrack?.kind === "video" ? sourceTrack : state.activeVideoTrackKey ? state.tracks.get(state.activeVideoTrackKey) : null;
    if (!videoTrack) videoTrack = [...state.tracks.values()].find(track => track.kind === "video") || null;
    if (!videoTrack) return;
    const video = findVideoAtTime(videoTrack.videos, time);
    if (!video) return;
    if (!state.selectedVideo || state.selectedVideo.path !== video.path) {
        selectVideo(video, time, videoTrack.key);
        return;
    }
    const desired = Math.max(0, time - Number(video.start_elapsed_s || 0));
    if (Number.isFinite(desired) && elements.videoPlayer.readyState >= 1) {
        try { elements.videoPlayer.currentTime = desired; } catch (_) {}
    }
}

function videoTechnicalSummary(video) {
    const parts = [];
    if (video.codec) parts.push(video.codec.toUpperCase());
    if (video.width && video.height) parts.push(`${video.width}×${video.height}`);
    if (Number.isFinite(Number(video.fps))) parts.push(`${formatNumber(video.fps, 2)} fps`);
    if (Number.isFinite(Number(video.duration_s))) parts.push(formatSeconds(video.duration_s));
    if (video.needs_proxy) parts.push("browser proxy required");
    return parts.join(" · ") || "Video metadata unavailable";
}

function selectVideo(video, runTime = null, trackKey = null) {
    state.selectedVideo = video;
    if (trackKey) state.activeVideoTrackKey = trackKey;
    elements.videoViewer.hidden = false;
    elements.videoCamera.textContent = video.camera_name || video.camera_id || "Camera";
    elements.videoTitle.textContent = video.name || "Recording";
    elements.videoMeta.textContent = videoTechnicalSummary(video);
    elements.videoError.hidden = true;
    elements.videoError.textContent = "";
    elements.videoLoading.hidden = false;
    elements.videoLoadingText.textContent = video.needs_proxy
        ? "Preparing browser-compatible video… this happens only once for this recording."
        : "Loading video…";
    elements.videoContext.innerHTML = [
        ["Run time", `<span data-video-runtime>${formatSeconds(video.start_elapsed_s)}</span>`],
        ["Start", formatSeconds(video.start_elapsed_s)],
        ["End", formatSeconds(video.end_elapsed_s)],
        ["Codec", video.codec || "unknown"],
        ["Original type", video.media_type || "unknown"],
    ].map(([label, value]) => `<span><strong>${escapeHtml(label)}:</strong> ${label === "Run time" ? value : escapeHtml(value)}</span>`).join("");

    elements.videoPlayer.pause();
    elements.videoPlayer.removeAttribute("src");
    while (elements.videoPlayer.firstChild) elements.videoPlayer.removeChild(elements.videoPlayer.firstChild);
    const source = document.createElement("source");
    source.src = video.stream_url;
    source.type = video.playback_media_type || "video/mp4";
    elements.videoPlayer.appendChild(source);
    elements.videoPlayer.dataset.pendingRunTime = Number.isFinite(Number(runTime)) ? String(runTime) : "";
    elements.videoPlayer.load();
    elements.videoViewer.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function closeVideoPlayer() {
    elements.videoPlayer.pause();
    elements.videoPlayer.removeAttribute("src");
    while (elements.videoPlayer.firstChild) elements.videoPlayer.removeChild(elements.videoPlayer.firstChild);
    elements.videoPlayer.load();
    elements.videoViewer.hidden = true;
    elements.videoLoading.hidden = true;
    elements.videoError.hidden = true;
    state.selectedVideo = null;
}

function renderFiles() {
    if (!state.overview) return;
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
            view.addEventListener("click", async () => {
                activateTab("analysis");
                await loadAnalysisData();
                const video = (state.overview.videos || []).find(item => item.path === file.path);
                if (!video) return;
                const camera = video.camera_name || video.camera_id || "Camera";
                const key = `video:${camera}`;
                if (!state.tracks.has(key)) await toggleTrack(key, "video");
                selectVideo(video, video.start_elapsed_s, key);
            });
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

async function previewFile(file) {
    elements.dialogTitle.textContent = file.path;
    elements.dialogBody.innerHTML = `<div class="loading-block"><span class="loading-spinner small"></span> Loading preview…</div>`;
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
        const content = data.kind === "json" && typeof data.content === "object" ? JSON.stringify(data.content, null, 2) : String(data.content ?? "");
        elements.dialogBody.innerHTML = `<pre>${escapeHtml(content)}${data.truncated ? "\n\n… preview truncated …" : ""}</pre>`;
    } catch (error) {
        elements.dialogBody.innerHTML = `<div class="results-error">${escapeHtml(error.message)}</div>`;
    }
}

async function activateTab(name) {
    document.querySelectorAll(".results-tab").forEach(button => button.classList.toggle("active", button.dataset.tab === name));
    document.querySelectorAll(".results-panel").forEach(panel => {
        const active = panel.dataset.panel === name;
        panel.hidden = !active;
        panel.classList.toggle("active", active);
    });
    if (name === "analysis") {
        await loadAnalysisData();
        requestAnimationFrame(() => renderAnalysis());
    }
    if (name === "files") renderFiles();
}

function bindSelector(container) {
    container.addEventListener("click", async event => {
        const button = event.target.closest("[data-track-key]");
        if (!button) return;
        await toggleTrack(button.dataset.trackKey, button.dataset.trackKind);
    });
}

function bindEvents() {
    elements.refresh.addEventListener("click", loadResults);
    document.querySelectorAll(".results-tab").forEach(button => button.addEventListener("click", () => activateTab(button.dataset.tab)));
    [elements.analysisSensorSelector, elements.analysisMeasurementSelector, elements.analysisEventSelector, elements.analysisVideoSelector, elements.analysisSystemSelector].forEach(bindSelector);
    elements.analysisStageTrack.addEventListener("click", event => {
        const button = event.target.closest("[data-stage-index]");
        if (!button) return;
        const stage = currentStages()[Number(button.dataset.stageIndex)];
        if (!stage) return;
        const start = Number(stage.start_s) || 0;
        const end = Number(stage.end_s);
        if (!Number.isFinite(end) || end <= start) return;
        const pad = Math.max((end - start) * 0.025, 0.25);
        setViewRange(start - pad, end + pad);
    });
    elements.analysisZoomIn.addEventListener("click", () => zoomView(0.5));
    elements.analysisZoomOut.addEventListener("click", () => zoomView(2));
    elements.analysisFit.addEventListener("click", fitExperiment);
    elements.fileSearch.addEventListener("input", renderFiles);
    elements.dialogClose.addEventListener("click", () => elements.dialog.close ? elements.dialog.close() : elements.dialog.removeAttribute("open"));
    elements.dialog.addEventListener("click", event => { if (event.target === elements.dialog) elements.dialog.close?.(); });
    elements.videoClose.addEventListener("click", closeVideoPlayer);

    elements.videoPlayer.addEventListener("loadstart", () => {
        if (!state.selectedVideo) return;
        elements.videoLoading.hidden = false;
        elements.videoLoadingText.textContent = state.selectedVideo.needs_proxy
            ? "Preparing browser-compatible video… this happens only once for this recording."
            : "Loading video…";
    });
    elements.videoPlayer.addEventListener("loadedmetadata", () => {
        const video = state.selectedVideo;
        if (!video) return;
        const pendingRunTime = Number(elements.videoPlayer.dataset.pendingRunTime);
        if (Number.isFinite(pendingRunTime) && Number.isFinite(Number(video.start_elapsed_s))) {
            const desired = Math.max(0, pendingRunTime - Number(video.start_elapsed_s));
            if (Number.isFinite(elements.videoPlayer.duration)) elements.videoPlayer.currentTime = Math.min(desired, Math.max(0, elements.videoPlayer.duration - 0.01));
        }
        elements.videoPlayer.dataset.pendingRunTime = "";
    });
    elements.videoPlayer.addEventListener("canplay", () => {
        elements.videoLoading.hidden = true;
        elements.videoError.hidden = true;
    });
    elements.videoPlayer.addEventListener("waiting", () => {
        if (!state.selectedVideo) return;
        elements.videoLoading.hidden = false;
        elements.videoLoadingText.textContent = "Buffering video…";
    });
    elements.videoPlayer.addEventListener("playing", () => { elements.videoLoading.hidden = true; });
    elements.videoPlayer.addEventListener("error", () => {
        const video = state.selectedVideo;
        elements.videoLoading.hidden = true;
        elements.videoError.hidden = false;
        const probeError = video?.probe?.error ? ` Probe: ${video.probe.error}` : "";
        elements.videoError.textContent = `Could not play this recording. Original codec: ${video?.codec || "unknown"}; MIME: ${video?.media_type || "unknown"}.${probeError}`;
    });
    elements.videoPlayer.addEventListener("timeupdate", () => {
        const video = state.selectedVideo;
        if (!video || video.start_elapsed_s == null) return;
        const runTime = Number(video.start_elapsed_s) + Number(elements.videoPlayer.currentTime || 0);
        state.cursorTime = runTime;
        const runtime = elements.videoContext.querySelector("[data-video-runtime]");
        if (runtime) runtime.textContent = formatSeconds(runTime);
        drawAllTracksOnly();
        renderCursorInfo();
    });
    elements.videoPlayer.addEventListener("seeking", () => {
        const video = state.selectedVideo;
        if (!video || video.start_elapsed_s == null) return;
        state.cursorTime = Number(video.start_elapsed_s) + Number(elements.videoPlayer.currentTime || 0);
        drawAllTracksOnly();
        renderCursorInfo();
    });

    window.addEventListener("resize", () => requestAnimationFrame(() => renderAnalysis()));
}

bindEvents();
loadResults();
