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
    activeCalibrationSensorId: null,
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
    calibrationDrawer: document.getElementById("calibration_drawer"),
    calibrationDrawerTitle: document.getElementById("calibration_drawer_title"),
    calibrationDrawerBody: document.getElementById("calibration_drawer_body"),
    calibrationDrawerClose: document.getElementById("calibration_drawer_close"),
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
    if (value == null || value === "") return "—";
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
    const progress = state.standaloneCalibration.get(String(snapshot.id)) || {mid:false, low:false, high:false, requested_points:3};
    const requested = Number(progress.requested_points || 3);
    const steps = [
        ["mid", "Midpoint", 7, "Place the probe in the midpoint buffer and wait for a stable live signal."],
        ["low", "Low point", 4, "Rinse the probe, place it in the low buffer, and wait for stabilization."],
        ["high", "High point", 10, "Rinse the probe, place it in the high buffer, and wait for stabilization."],
    ].slice(0, requested);
    return `
        <div class="calibration-block ph-calibration" data-ph-sensor="${escapeHtml(snapshot.id)}">
            <div class="calibration-heading">
                <div><strong>pH calibration</strong><span>Use the best calibration your available buffers allow. Three points are recommended.</span></div>
                <label class="ph-mode-label">Points
                    <select class="ph-mode-select" data-standalone-mode="${escapeHtml(snapshot.id)}">
                        <option value="1" ${requested===1?"selected":""}>1 point</option>
                        <option value="2" ${requested===2?"selected":""}>2 points</option>
                        <option value="3" ${requested===3?"selected":""}>3 points · recommended</option>
                    </select>
                </label>
            </div>
            <div class="calibration-points">
                ${steps.map(([point,label,defaultValue,hint], index) => {
                    const done = Boolean(progress[point]);
                    const previousDone = index === 0 || Boolean(progress[steps[index - 1][0]]);
                    return `<div class="calibration-point ${done ? "done" : ""}">
                        <div><span class="point-index">${index + 1}</span><div><strong>${label}</strong><small>${hint}</small></div></div>
                        <div class="point-action"><input class="buffer-value" data-point-value="${point}" type="number" step="0.01" value="${defaultValue.toFixed(2)}" ${previousDone ? "" : "disabled"}><button class="button ${done ? "button-secondary" : "button-primary"} standalone-ph-calibrate" data-sensor-id="${escapeHtml(snapshot.id)}" data-point="${point}" type="button" ${(!previousDone || done) ? "disabled" : ""}>${done ? "Calibrated" : `Calibrate ${label.toLowerCase()}`}</button></div>
                    </div>`;
                }).join("")}
            </div>
        </div>`;
}

let virtualProfileData = null;
let virtualDraft = null;

const virtualMethods = ["mean_derivative", "cumulative_distribution", "heuristic_entropy",
    "dual_entropy", "dual_entropy_striped", "dual_entropy_hybrid"];
const virtualSelectOptions = {
    method: virtualMethods,
    selection_criteria: ["strong_candidates", "next_tp_after_pulp", "hybrid", "interpolate"],
    simplification_alg: ["turning_point", "reumann_witkam", "douglas_peucker", "opheim", "lang"]
};
const virtualFieldGroups = [
    ["Entropy and profile", ["entropy_radius","entropy_bins","sigma","threshold_froth","threshold_pulp",
        "min_row","cdf_foam","cdf_pulp","selection_criteria","simplification_alg","simplification_tol"]],
    ["Dual entropy / texture", ["x0_frac","x1_frac","min_y_frac","lower_search_start","lower_search_end",
        "min_thickness_px","sigma_rows","dual_entropy_radius","dual_entropy_bins","texture_ksize",
        "upper_threshold_q","lower_bias"]],
    ["Striped / hybrid vote", ["n_stripes","stripe_overlap","min_valid_stripes","vote_sigma_px","outlier_mad"]]
];

function virtualField(key) {
    const value = virtualDraft[key];
    const label = key.replaceAll("_"," ").replace(/\b\w/g, char => char.toUpperCase());
    if (virtualSelectOptions[key]) {
        return `<label>${escapeHtml(label)}<select data-virtual-param="${key}">${virtualSelectOptions[key]
            .map(opt => `<option value="${escapeHtml(opt)}" ${opt === value ? "selected" : ""}>${escapeHtml(opt.replaceAll("_"," "))}</option>`).join("")}</select></label>`;
    }
    return `<label>${escapeHtml(label)}<input data-virtual-param="${key}" type="number" step="any" value="${escapeHtml(value)}" required></label>`;
}

function virtualCollectInputs() {
    const panel = document.getElementById("virtual_panel");
    panel.querySelectorAll("[data-virtual-param]").forEach(input => {
        const key = input.dataset.virtualParam;
        virtualDraft[key] = typeof virtualDraft[key] === "number" ? Number(input.value) : input.value;
    });
    return {...virtualDraft};
}

function renderVirtualFields() {
    const main = document.getElementById("virtual_main_fields");
    main.innerHTML = ["method","resolution_px","sampling_interval_s"].map(virtualField).join("");
    document.getElementById("virtual_advanced_fields").innerHTML = virtualFieldGroups.map(([name,keys]) =>
        `<details ${name === "Entropy and profile" ? "open" : ""}><summary>${escapeHtml(name)}</summary>
        <div class="virtual-field-grid">${keys.map(virtualField).join("")}</div></details>`).join("");
}


let virtualDiagnostic = null, virtualTestSeries = [];
let virtualDiagnosticsActive = false, virtualDiagnosticsTimer = null, virtualDiagBusy = false, virtualDiagRevision = 0;

function virtualCanvas(canvas, width, height) {
    canvas.width = Math.max(1, Math.round(width)); canvas.height = Math.max(1, Math.round(height));
    return canvas.getContext("2d");
}

function drawVirtualOverlays() {
    if (!virtualDiagnostic) return;
    const d = virtualDiagnostic, width = d.image_size[0], height = d.image_size[1];
    for (const [name,dark] of [["virtual_image_overlay",false],["virtual_entropy_overlay",true]]) {
        const ctx = virtualCanvas(document.getElementById(name),width,height);
        if (document.getElementById("virtual_show_grid").checked && d.roi_cm?.length === 4) {
            const [x0,y0,x1,y1] = d.roi_cm;
            const spacing = Math.max(1, Math.ceil(Math.max(x1-x0,y1-y0)/14));
            ctx.strokeStyle = dark ? "rgba(255,255,255,.38)" : "rgba(255,255,255,.32)";
            ctx.lineWidth = 0.8;
            for (let x=Math.ceil(x0/spacing)*spacing;x<=x1;x+=spacing) {
                const px=(x-x0)/(x1-x0)*width;ctx.beginPath();ctx.moveTo(px,0);ctx.lineTo(px,height);ctx.stroke();
            }
            for (let y=Math.ceil(y0/spacing)*spacing;y<=y1;y+=spacing) {
                const py=(y-y0)/(y1-y0)*height;ctx.beginPath();ctx.moveTo(0,py);ctx.lineTo(width,py);ctx.stroke();
            }
        }
        const rows = [["froth_row_px","#38bdf8"],["pulp_row_px","#fbbf24"]];
        for (const [key,color] of rows) {
            if (d[key] == null || !Number.isFinite(Number(d[key]))) continue;
            ctx.beginPath();ctx.moveTo(0,Number(d[key]));ctx.lineTo(width,Number(d[key]));
            ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();
        }
    }
    drawVirtualProfiles();
}

function diagnosticProfileKeys(d) {
    const names = Object.keys(d.profiles || {});
    const priority = d.method === "dual_entropy_hybrid" ? ["upper_vote","lower_score","entropy","foamness"] :
        d.method === "dual_entropy_striped" ? ["upper_vote","lower_vote"] :
        d.method === "dual_entropy" ? ["entropy","foamness","lower_score"] :
        d.method === "mean_derivative" ? ["row_entropy","row_derivative"] :
        d.method === "cumulative_distribution" ? ["row_entropy","cumulative_entropy"] : ["row_entropy"];
    return priority.filter(key=>names.includes(key)).concat(names.filter(key=>!priority.includes(key))).slice(0,4);
}

function drawVirtualProfiles() {
    const d = virtualDiagnostic; if (!d) return;
    const width=360, height=d.image_size[1], canvas=document.getElementById("virtual_profile_canvas");
    const ctx=virtualCanvas(canvas,width,height), names=diagnosticProfileKeys(d);
    ctx.clearRect(0,0,width,height);
    const css=getComputedStyle(document.documentElement);
    ctx.strokeStyle=css.getPropertyValue("--chart-grid").trim()||"#9ca3af";
    ctx.lineWidth=.8;ctx.globalAlpha=.65;
    for(let i=0;i<=6;i++){const y=i*height/6;ctx.beginPath();ctx.moveTo(4,y);ctx.lineTo(width-5,y);ctx.stroke();}
    ctx.globalAlpha=1;
    const colors=["#f87171","#4ade80","#a78bfa","#fbbf24"];
    const barStart=313, barWidth=14, plotStart=10, plotWidth=290;
    for(let k=0;k<Math.min(2,names.length);k++){
        const values=d.profiles[names[k]]?.values||[];
        for(let j=0;j<values.length;j++){
            const shade=Math.max(0,Math.min(255,Math.round(values[j]*255)));
            const y=j/Math.max(1,values.length)*height;
            ctx.fillStyle="rgb("+shade+","+shade+","+shade+")";
            ctx.fillRect(barStart+k*(barWidth+5),y,barWidth,Math.max(1.2,height/Math.max(1,values.length)+.5));
        }
    }
    names.forEach((name,index)=>{
        const values=d.profiles[name]?.values||[]; if(!values.length)return;
        ctx.beginPath();
        values.forEach((value,i)=>{
            const x=plotStart+Number(value)*plotWidth, y=i/Math.max(1,values.length-1)*height;
            if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);
        });
        ctx.strokeStyle=colors[index%colors.length];ctx.lineWidth=1.8;ctx.stroke();
    });
    for(const [key,color] of [["froth_row_px","#38bdf8"],["pulp_row_px","#fbbf24"]]){
        if(d[key]==null)continue;
        ctx.beginPath();ctx.moveTo(0,d[key]);ctx.lineTo(width,d[key]);
        ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.setLineDash([4,3]);ctx.stroke();ctx.setLineDash([]);
    }
    document.getElementById("virtual_profile_legend").innerHTML=names.map((name,i)=>
        '<span><i style="--signal-color:'+colors[i%colors.length]+'"></i>'+escapeHtml(name.replaceAll("_"," "))+'</span>').join("");
}

function renderVirtualDiagnostic(diagnostic, label) {
    if (!diagnostic || !diagnostic.image_jpeg_base64 || !diagnostic.entropy_jpeg_base64) return;
    virtualDiagnostic=diagnostic;
    document.getElementById("virtual_diagnostic_grid").hidden=false;
    const w=diagnostic.image_size[0],h=diagnostic.image_size[1];
    document.querySelectorAll(".virtual-diagnostic-stage").forEach(node=>node.style.setProperty("--diagnostic-aspect",w+" / "+h));
    const original=document.getElementById("virtual_image"), entropy=document.getElementById("virtual_entropy_image");
    original.src="data:image/jpeg;base64,"+diagnostic.image_jpeg_base64;
    entropy.src="data:image/jpeg;base64,"+diagnostic.entropy_jpeg_base64;
    const positions=document.getElementById("virtual_diagnostic_positions");
    const value=n=>n==null?"—":Number(n).toFixed(2)+" cm";
    positions.hidden=false;
    positions.innerHTML="<span>Froth surface <strong>"+value(diagnostic.froth_surface_cm)+"</strong></span>"+
        "<span>Pulp–froth <strong>"+value(diagnostic.pulp_froth_interface_cm)+"</strong></span>";
    const time=diagnostic.timestamp_ns ? new Date(diagnostic.timestamp_ns/1e6).toLocaleTimeString() : "—";
    document.getElementById("virtual_diagnostics_status").textContent=label+" · "+time+" · "+diagnostic.method.replaceAll("_"," ");
    window.requestAnimationFrame(drawVirtualOverlays);
}

function renderVirtualTestTimeline(series=[]) {
    virtualTestSeries=Array.isArray(series)?series:[];
    const section=document.getElementById("virtual_test_history");
    section.hidden=!virtualTestSeries.length;
    document.getElementById("virtual_test_history_count").textContent=virtualTestSeries.length+
        " samples · "+virtualTestSeries.filter(x=>x.valid).length+" valid";
    if(!section.hidden)window.requestAnimationFrame(drawVirtualTestTimeline);
}

function drawVirtualTestTimeline() {
    if(!virtualTestSeries.length)return;
    const canvas=document.getElementById("virtual_test_chart"), rect=canvas.getBoundingClientRect();
    const dpr=Math.min(2,window.devicePixelRatio||1), w=Math.max(320,Math.round(rect.width*dpr)), h=Math.round(220*dpr);
    const ctx=virtualCanvas(canvas,w,h);
    ctx.scale(dpr,dpr);
    const width=w/dpr,height=h/dpr,left=52,right=20,top=18,bottom=36;
    const plotW=width-left-right,plotH=height-top-bottom,series=virtualTestSeries;
    const keys=[["froth_surface_cm","#0ea5e9"],["pulp_froth_interface_cm","#f59e0b"]];
    const points=series.flatMap(item=>keys.map(([key])=>item.valid?item[key]:null))
        .filter(value=>value!=null&&Number.isFinite(Number(value))).map(Number);
    if(!points.length){ctx.fillText("No valid boundaries in this test",left,top+40);return;}
    const lo=Math.min(...points),hi=Math.max(...points),pad=Math.max((hi-lo)*.1,.1),ymin=lo-pad,ymax=hi+pad;
    const tmax=Math.max(1,...series.map(item=>Number(item.time_s)||0));
    const xOf=t=>left+(Number(t)||0)/tmax*plotW;
    const yOf=v=>top+(ymax-Number(v))/(ymax-ymin)*plotH;
    const css=getComputedStyle(document.documentElement);
    ctx.font="11px system-ui";ctx.fillStyle=css.getPropertyValue("--text-soft").trim()||"#64748b";
    ctx.strokeStyle=css.getPropertyValue("--chart-grid").trim()||"#cbd5e1";ctx.lineWidth=1;
    for(let i=0;i<=4;i++){
        const y=top+i*plotH/4;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-right,y);ctx.stroke();
        ctx.fillText((ymax-i*(ymax-ymin)/4).toFixed(1),3,y+4);
    }
    for(let i=0;i<=4;i++){const t=i*tmax/4;ctx.fillText(t.toFixed(tmax<10?1:0)+" s",xOf(t)-12,height-10);}
    keys.forEach(([key,color])=>{
        ctx.beginPath();let ongoing=false;
        series.forEach(item=>{
            const value=item.valid?item[key]:null;
            if(value==null||!Number.isFinite(Number(value))){ongoing=false;return;}
            const x=xOf(item.time_s),y=yOf(value);
            if(!ongoing){ctx.moveTo(x,y);ongoing=true;}else ctx.lineTo(x,y);
        });
        ctx.strokeStyle=color;ctx.lineWidth=2.2;ctx.stroke();
        for(const item of series){const value=item.valid?item[key]:null;
            if(value==null)continue;ctx.beginPath();ctx.arc(xOf(item.time_s),yOf(value),2.2,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();}
    });
}

async function pollVirtualDiagnostics() {
    if(!virtualDiagnosticsActive||virtualDiagBusy||document.hidden||document.getElementById("virtual_panel").hidden)return;
    virtualDiagBusy=true;
    try {
        const payload=await requestJson("/api/vision/virtual-sensors/froth-interface/diagnostics",{
            method:"POST",headers:{"Content-Type":"application/json"},
            body:JSON.stringify({enabled:true,last_revision:virtualDiagRevision})
        });
        if(!virtualDiagnosticsActive)return;
        if(payload.diagnostic){virtualDiagRevision=payload.revision;renderVirtualDiagnostic(payload.diagnostic,"Live preview");}
        else if(!virtualDiagnostic)document.getElementById("virtual_diagnostics_status").textContent=
            "Waiting for the next lores diagnostic frame. Measurements continue independently.";
    } catch(error){
        document.getElementById("virtual_diagnostics_status").textContent="Live preview: "+error.message;
    } finally {virtualDiagBusy=false;}
}

async function startVirtualDiagnostics() {
    if(virtualDiagnosticsActive)return;
    virtualDiagnosticsActive=true;virtualDiagRevision=0;
    document.getElementById("virtual_diagnostics_toggle").textContent="Stop live diagnostics";
    await pollVirtualDiagnostics();
    virtualDiagnosticsTimer=window.setInterval(pollVirtualDiagnostics,2500);
}

function stopVirtualDiagnostics() {
    virtualDiagnosticsActive=false;
    if(virtualDiagnosticsTimer){window.clearInterval(virtualDiagnosticsTimer);virtualDiagnosticsTimer=null;}
    document.getElementById("virtual_diagnostics_toggle").textContent="Start live diagnostics";
    requestJson("/api/vision/virtual-sensors/froth-interface/diagnostics",{
        method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:false})
    }).catch(()=>{});
}

function virtualBenchmarkMarkup(result) {
    const target = document.getElementById("virtual_benchmark");
    target.dataset.passed = String(Boolean(result?.passed && result?.current !== false));
    const confirm = document.getElementById("virtual_confirm");
    confirm.disabled = !result?.passed || result?.current === false;
    if (!result) {
        target.textContent = "Mandatory: save settings and run a live timing/detection test before confirming.";
        return;
    }
    const fmt = n => Number.isFinite(Number(n)) ? Number(n).toFixed(1) : "—";
    target.innerHTML = `<strong>${result.passed && result.current !== false ? "Test passed" : "Test not accepted"}</strong>
        <div class="virtual-stats">
        <div><span>P95 latency</span><strong>${fmt(result.p95_ms)} ms</strong></div>
        <div><span>P99 latency</span><strong>${fmt(result.p99_ms)} ms</strong></div>
        <div><span>Deadline</span><strong>${fmt(result.deadline_ms)} ms</strong></div>
        <div><span>Main recording</span><strong>${fmt(result.main_recording_fps)} FPS (min ${fmt(result.min_recording_fps)})</strong></div>
        <div><span>Valid detections</span><strong>${fmt(Number(result.valid_fraction)*100)}%</strong></div>
        <div><span>lores</span><strong>${escapeHtml((result.lores_size||[]).join(" × "))}</strong></div>
        <div><span>Output ROI</span><strong>${escapeHtml((result.roi_resolution||[]).join(" × "))}</strong></div>
        </div><p>Samples are captured at the configured acquisition interval, with the main encoder recording simultaneously. The temporary video is discarded.</p>
        ${result.frame_reuse_detected ? '<p>Repeated camera timestamps detected; choose a lower acquisition rate or check the camera stream.</p>' : ''}
        ${result.errors?.length ? `<p>${escapeHtml(result.errors.join("; "))}</p>` : ""}`;
}

async function openVirtualCalibration() {
    if (!state.calibrationMode) return;
    const panel = document.getElementById("virtual_panel");
    const missing = document.getElementById("virtual_missing");
    const editor = document.getElementById("virtual_editor");
    panel.hidden = false;
    panel.scrollIntoView({behavior:"smooth",block:"start"});
    const cellId = state.digiflot?.cell_selection?.cell_id || "";
    const cameraId = state.digiflot?.cell_selection?.camera_id;
    document.getElementById("virtual_source").textContent = cameraId == null ? "No camera" : `Camera ${cameraId}`;
    document.getElementById("virtual_open_cells").href = `/cells?cell=${encodeURIComponent(cellId)}&camera=${encodeURIComponent(cameraId ?? "")}`;
    try {
        virtualProfileData = await requestJson("/api/vision/virtual-sensors/froth-interface/profile");
        virtualDraft = {...virtualProfileData.config};
        document.getElementById("virtual_geometry").textContent =
            `${cellId} · Camera ${cameraId} · Geometry ${virtualProfileData.geometry.calibration_id} · ${virtualProfileData.source} profile`;
        missing.hidden = true; editor.hidden = false;
        renderVirtualFields();
        virtualBenchmarkMarkup(virtualProfileData.test);
        renderVirtualTestTimeline(virtualProfileData.test?.series || []);
        if(virtualProfileData.test_diagnostic)
            renderVirtualDiagnostic(virtualProfileData.test_diagnostic,"Last calibration test");
        startVirtualDiagnostics().catch(error=>showToast(error.message));
    } catch (error) {
        missing.hidden = false; editor.hidden = true;
        stopVirtualDiagnostics();
        missing.querySelector("p").textContent = error.message;
    }
}

async function virtualSaveConfiguration() {
    const config = virtualCollectInputs();
    await requestJson("/api/vision/virtual-sensors/froth-interface/profile", {
        method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(config)
    });
    virtualBenchmarkMarkup(null);
    renderVirtualTestTimeline([]);
    virtualDiagnostic=null;
    document.getElementById("virtual_diagnostic_grid").hidden=true;
    document.getElementById("virtual_diagnostic_positions").hidden=true;
    document.getElementById("virtual_diagnostics_status").textContent=
        "Settings updated. Waiting for a diagnostic frame with the new parameters.";
}

async function virtualRunTest() {
    const button = document.getElementById("virtual_test");
    button.disabled = true; button.textContent = "Running calibration test…";
    try {
        await virtualSaveConfiguration();
        const result = await requestJson("/api/vision/virtual-sensors/froth-interface/benchmark", {
            method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({samples:20})
        });
        virtualBenchmarkMarkup({...result, current:true});
        renderVirtualTestTimeline(result.series || []);
        if(result.diagnostic)renderVirtualDiagnostic(result.diagnostic,"Calibration test");
        else document.getElementById("virtual_diagnostics_status").textContent=
            result.diagnostic_error || "The test ran, but no diagnostic entropy map was produced.";
        state.digiflot = await requestJson("/api/digiflot/state");
        updateCalibrationProgress();
        showToast(result.passed ? "Live test passed. Inspect the preview before confirming." :
            "Detection or timing criteria failed. Adjust the settings and test again.");
    } catch (error) {
        virtualBenchmarkMarkup(null);
        showToast(error.message);
    } finally {
        button.disabled = false; button.textContent = "Run calibration test";
    }
}

function calibrationMarkup(snapshot) {
    if (snapshot.type === "virtual_froth_interface") {
        if (!state.calibrationMode) return '<div class="calibration-block"><strong>Virtual camera-based sensor</strong><span>Configured in the experiment calibration workflow.</span></div>';
        const item = calibrationItem(snapshot.id) || {};
        return `<div class="calibration-block">
            <div><strong>Virtualized from Camera ${escapeHtml(snapshot.source_camera_id)}</strong>
            <span>Cell ${escapeHtml(snapshot.physical_cell_id)} · Geometry + live benchmark required</span></div>
            <div class="calibration-actions"><button class="button button-primary open-virtual-calibration" type="button">
            ${item.status === "passed" ? "Review virtual calibration" : "Configure / test virtual sensor"}</button>
            ${item.status !== "passed" && item.status !== "skipped" ? '<button class="button button-secondary sensor-skip" data-sensor-id="froth_interface" type="button">Skip virtual sensor</button>' : ""}
            ${item.status === "passed" || item.status === "skipped" ? '<button class="button button-secondary sensor-reopen" data-sensor-id="froth_interface" type="button">Reopen</button>' : ""}</div>
        </div>`;
    }
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
                <div class="calibration-heading-actions">
                    <span class="calibration-pill passed">Passed</span>
                    <button class="button button-secondary sensor-reopen" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Edit calibration</button>
                </div>
            </div>`;
    }

    if (calibration.status === "skipped") {
        return `
            <div class="calibration-block skipped-block">
                <div>
                    <strong>Calibration skipped</strong>
                    <span>${escapeHtml(calibration.skip_reason || "Skipped by operator.")}</span>
                </div>
                <div class="calibration-heading-actions">
                    <span class="calibration-pill skipped">Skipped</span>
                    <button class="button button-secondary sensor-reopen" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Edit calibration</button>
                </div>
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

    if (["two_point", "ph_points"].includes(calibration.mode)) {
        const points = calibration.points || {};
        const requested = Number(calibration.requested_points || (calibration.mode === "two_point" ? 2 : 3));
        const definitions = [
            ["mid", "Midpoint", 7, "Place probe in the midpoint buffer and wait for the plot to stabilize."],
            ["low", "Low point", 4, "Rinse the probe, place it in the low buffer, and wait for stabilization."],
            ["high", "High point", 10, "Rinse the probe, place it in the high buffer, and wait for stabilization."],
        ].slice(0, requested);
        return `
            <div class="calibration-block ph-calibration" data-ph-sensor="${escapeHtml(snapshot.id)}">
                <div class="calibration-heading">
                    <div>
                        <strong>pH calibration</strong>
                        <span>Choose 1, 2, or 3 points. Sequence: midpoint → low → high. Chip reports ${escapeHtml(calibration.chip_points ?? "—")} calibrated point(s).</span>
                    </div>
                    <div class="calibration-heading-actions">
                        <label class="ph-mode-label">Points
                            <select class="ph-mode-select" data-ph-mode="${escapeHtml(snapshot.id)}">
                                <option value="1" ${requested===1?"selected":""}>1 point</option>
                                <option value="2" ${requested===2?"selected":""}>2 points</option>
                                <option value="3" ${requested===3?"selected":""}>3 points · recommended</option>
                            </select>
                        </label>
                        <span class="calibration-pill ${escapeHtml(calibration.status)}">${escapeHtml(calibration.status)}</span>
                        <button class="button button-secondary sensor-skip" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Skip calibration</button>
                    </div>
                </div>
                <div class="calibration-points">
                    ${definitions.map(([point,label,defaultValue,hint], index) => {
                        const item = points[point] || {value:defaultValue,status:"pending"};
                        const done = item.status === "passed";
                        const previous = index === 0 ? true : (points[definitions[index - 1][0]] || {}).status === "passed";
                        return `<div class="calibration-point ${done ? "done" : ""}">
                            <div><span class="point-index">${index + 1}</span><div><strong>${label}</strong><small>${hint}</small></div></div>
                            <div class="point-action"><input class="buffer-value" data-point-value="${point}" type="number" step="0.01" value="${escapeHtml(item.value ?? defaultValue)}" ${previous ? "" : "disabled"}><button class="button ${done ? "button-secondary" : "button-primary"} ph-calibrate" data-sensor-id="${escapeHtml(snapshot.id)}" data-point="${point}" type="button" ${(!previous || done) ? "disabled" : ""}>${done ? "Calibrated" : `Calibrate ${label.toLowerCase()}`}</button></div>
                        </div>`;
                    }).join("")}
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
    const hasValue = snapshot.value != null && Number.isFinite(Number(snapshot.value));
    const virtual = snapshot.type === "virtual_froth_interface";
    const source = virtual ? `Camera ${snapshot.source_camera_id ?? "—"} · Cell ${snapshot.physical_cell_id || "—"}` : "";
    return `
        <article class="sensor-card ${virtual ? "sensor-virtual" : ""}" id="sensor-card-${escapeHtml(snapshot.id)}" data-sensor-id="${escapeHtml(snapshot.id)}">
            <header class="sensor-card-header">
                <div>
                    <span class="sensor-type">${virtual ? "Virtual camera sensor" : escapeHtml(snapshot.type || "sensor")}</span>
                    <h2>${escapeHtml(snapshot.name || snapshot.id)}</h2>
                    <span class="sensor-device">${virtual ? escapeHtml(source) : `${escapeHtml(snapshot.interface || "")} · ${escapeHtml(snapshot.device || "—")}`}</span>
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

            ${virtual ? `<div class="virtual-live-channels">
                <div><span>Froth surface</span><strong class="virtual-froth">—</strong></div>
                <div><span>Pulp–froth interface</span><strong class="virtual-pulp">—</strong></div>
                <div><span>Froth thickness</span><strong class="virtual-thickness">—</strong></div>
            </div><div class="virtual-chart-legend"><span class="virtual-legend-froth">Froth surface</span><span class="virtual-legend-pulp">Pulp–froth interface</span><small>Live · cm</small></div>` : ""}
            <div class="chart-frame">
                <canvas class="sensor-chart" aria-label="Live signal for ${escapeHtml(snapshot.name || snapshot.id)}"></canvas>
                <div class="chart-empty">${status === "offline" ? "Sensor offline" : virtual ? "Live acquisition starts after confirmation. Test frames are not plotted." : "Waiting for measurements…"}</div>
            </div>
            <div class="chart-footer"><span class="chart-min">Min —</span><span class="chart-span">Span —</span><span class="chart-max">Max —</span></div>

            <div class="sensor-message ${snapshot.error ? "visible" : ""}">${snapshot.error ? escapeHtml(snapshot.error) : ""}</div>
            <div class="calibration-host">${String(snapshot.type || "").toLowerCase() === "ph" && calibrationMarkup(snapshot) ? `<button class="button button-secondary open-calibration-drawer" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Calibrate / review pH</button>` : calibrationMarkup(snapshot)}</div>
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
    renderCalibrationDrawer();
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
    if (snapshot.type === "virtual_froth_interface") {
        const unitValue = key => snapshot.channels?.[key] == null ? "—" : `${formatValue(snapshot.channels[key], snapshot)} cm`;
        card.querySelector(".virtual-froth").textContent = unitValue("froth_surface_cm");
        card.querySelector(".virtual-pulp").textContent = unitValue("pulp_froth_interface_cm");
        card.querySelector(".virtual-thickness").textContent = unitValue("froth_thickness_cm");
        card.querySelector(".chart-empty").textContent = snapshot.status === "offline" ? "Camera unavailable" :
            snapshot.measurement_mode === "waiting" ? "Waiting for live lores acquisition. Test results are not plotted." :
            snapshot.reading_valid === false ? "Detection invalid: waiting for a valid interface" : "Acquiring live interface positions…";
    }
    card.querySelector(".reading-unit").textContent = snapshot.unit || "";
    card.querySelector(".last-update").textContent = snapshot.timestamp_ms ? new Date(snapshot.timestamp_ms).toLocaleTimeString() : "—";
    card.querySelector(".sample-count").textContent = snapshot.sample_count ?? 0;

    const message = card.querySelector(".sensor-message");
    message.textContent = snapshot.error || "";
    message.classList.toggle("visible", Boolean(snapshot.error));

    const numeric = snapshot.value == null ? NaN : Number(snapshot.value);
    if (snapshot.type === "virtual_froth_interface" && snapshot.timestamp_ms) {
        appendVirtualHistory(snapshot);
        updateRate(snapshot.id, snapshot.timestamp_ms);
    } else if (Number.isFinite(numeric) && snapshot.timestamp_ms) {
        appendHistory(snapshot.id, snapshot.timestamp_ms, numeric, snapshot.unit || "");
        updateRate(snapshot.id, snapshot.timestamp_ms);
    } else {
        const empty = card.querySelector(".chart-empty");
        if (empty && snapshot.type !== "virtual_froth_interface")
            empty.textContent = status === "offline" ? "Sensor offline" : "Waiting for measurements…";
    }

    const host = card.querySelector(".calibration-host");
    if (host) {
        host.innerHTML = String(snapshot.type || "").toLowerCase() === "ph" && calibrationMarkup(snapshot)
            ? `<button class="button button-secondary open-calibration-drawer" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Calibrate / review pH</button>`
            : calibrationMarkup(snapshot);
        bindCalibrationControls(host);
    }
    if (String(state.activeCalibrationSensorId) === String(snapshot.id)) renderCalibrationDrawer();
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

function appendVirtualHistory(snapshot) {
    const id = String(snapshot.id), history = state.histories.get(id) || [];
    if (history.at(-1)?.timestamp === snapshot.timestamp_ms) return;
    const numberOrNull = value => value == null || !Number.isFinite(Number(value)) ? null : Number(value);
    history.push({timestamp:snapshot.timestamp_ms, upper:numberOrNull(snapshot.channels?.froth_surface_cm),
        lower:numberOrNull(snapshot.channels?.pulp_froth_interface_cm), unit:"cm"});
    if (history.length > HISTORY_LIMIT) history.shift();
    state.histories.set(id, history);
    drawChart(id);
}

function drawVirtualChart(ctx, width, height, history, card) {
    const values = history.flatMap(sample => [sample.upper,sample.lower]).filter(value => value != null);
    const empty = card.querySelector(".chart-empty");
    if (!values.length) { empty.hidden=false; return; }
    empty.hidden=true;
    const minData=Math.min(...values), maxData=Math.max(...values), span=maxData-minData;
    const padding=Math.max(.06,span*.12);
    const bottom=minData-padding, top=maxData+padding;
    const t0=history[0].timestamp, t1=history.at(-1).timestamp;
    const left=14, right=14, upper=12, lower=14, plotWidth=width-left-right, plotHeight=height-upper-lower;
    const xOf=(sample,index)=>left+plotWidth*(t1>t0 ? (sample.timestamp-t0)/(t1-t0) : index/Math.max(1,history.length-1));
    const yOf=value=>upper+plotHeight*(1-(value-bottom)/(top-bottom));
    const css=getComputedStyle(document.documentElement);
    ctx.strokeStyle=css.getPropertyValue("--chart-grid").trim() || "#394350";
    ctx.lineWidth=1;
    for(let i=0;i<=3;i++){const y=upper+i*plotHeight/3;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(width-right,y);ctx.stroke();}
    for(const [key,color] of [["upper","#0ea5e9"],["lower","#f59e0b"]]){
        ctx.beginPath();let started=false;
        for(let i=0;i<history.length;i++){const value=history[i][key];if(value==null){started=false;continue;}
            const x=xOf(history[i],i),y=yOf(value);
            if(!started){ctx.moveTo(x,y);started=true;}else ctx.lineTo(x,y);
        }
        ctx.strokeStyle=color;ctx.lineWidth=2.2;ctx.lineCap="round";ctx.lineJoin="round";ctx.stroke();
    }
    card.querySelector(".chart-min").textContent=`Min ${minData.toFixed(2)} cm`;
    card.querySelector(".chart-max").textContent=`Max ${maxData.toFixed(2)} cm`;
    card.querySelector(".chart-span").textContent=`Span ${span.toFixed(2)} cm`;
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
    if (state.sensors.get(id)?.type === "virtual_froth_interface") {
        drawVirtualChart(ctx, width, height, history, card); return;
    }
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

function renderCalibrationDrawer() {
    const id = state.activeCalibrationSensorId;
    const snapshot = id == null ? null : state.sensors.get(String(id));
    if (!snapshot || String(snapshot.type || "").toLowerCase() !== "ph") {
        el.calibrationDrawer.hidden = true;
        return;
    }
    el.calibrationDrawer.hidden = false;
    el.calibrationDrawerTitle.textContent = `${snapshot.name || snapshot.id} · pH calibration`;
    el.calibrationDrawerBody.innerHTML = calibrationMarkup(snapshot);
    bindCalibrationControls(el.calibrationDrawerBody);
}

function bindCalibrationControls(root = document) {
    root.querySelectorAll(".open-virtual-calibration").forEach(button => {
        if (button.dataset.bound) return;
        button.dataset.bound = "1";
        button.addEventListener("click", openVirtualCalibration);
    });
    root.querySelectorAll(".open-calibration-drawer").forEach(button => {
        if (button.dataset.bound) return;
        button.dataset.bound = "1";
        button.addEventListener("click", () => {
            state.activeCalibrationSensorId = String(button.dataset.sensorId);
            renderCalibrationDrawer();
            el.calibrationDrawer.scrollIntoView({behavior:"smooth", block:"nearest"});
        });
    });
    root.querySelectorAll(".ph-mode-select").forEach(select => {
        if (select.dataset.bound) return;
        select.dataset.bound = "1";
        select.addEventListener("change", async () => {
            const id = select.dataset.standaloneMode || select.dataset.phMode;
            if (select.dataset.standaloneMode) {
                const progress = state.standaloneCalibration.get(String(id)) || {mid:false,low:false,high:false};
                progress.requested_points = Number(select.value);
                state.standaloneCalibration.set(String(id), progress);
                renderCalibrationDrawer();
                return;
            }
            select.disabled = true;
            try {
                state.digiflot = await requestJson(`/api/digiflot/calibration/sensors/${encodeURIComponent(id)}/mode`, {
                    method:"POST", headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({requested_points:Number(select.value)})
                });
                renderCards();
                state.activeCalibrationSensorId = String(id);
                renderCalibrationDrawer();
            } catch (error) {
                showToast(error.message);
                select.disabled = false;
            }
        });
    });
    root.querySelectorAll(".sensor-reopen").forEach(button => {
        if (button.dataset.bound) return;
        button.dataset.bound = "1";
        button.addEventListener("click", async () => {
            button.disabled = true;
            try {
                state.digiflot = await requestJson(`/api/digiflot/calibration/sensors/${encodeURIComponent(button.dataset.sensorId)}/reopen`, { method: "POST" });
                state.calibrationMode = true;
                renderCards();
                updateCalibrationProgress();
                showToast("Calibration reopened.");
            } catch (error) {
                button.disabled = false;
                showToast(error.message);
            }
        });
    });

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
            const host = button.closest(".calibration-block") || button.closest(".sensor-card");
            const point = button.dataset.point;
            const input = host.querySelector(`[data-point-value="${point}"]`);
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
                    body: JSON.stringify({ point, value, requested_points: Number(host.querySelector(".ph-mode-select")?.value || 3) }),
                });
                renderCards();
            } catch (error) {
                button.disabled = false;
                button.textContent = point === "mid" ? "Calibrate midpoint" : point === "low" ? "Calibrate low point" : "Calibrate high point";
                showToast(error.message);
            }
        });
    });

    root.querySelectorAll(".standalone-ph-calibrate").forEach(button => {
        if (button.dataset.bound) return;
        button.dataset.bound = "1";
        button.addEventListener("click", async () => {
            const host = button.closest(".calibration-block") || button.closest(".sensor-card");
            const point = button.dataset.point;
            const input = host.querySelector(`[data-point-value="${point}"]`);
            const value = Number(input.value);
            if (!Number.isFinite(value)) { showToast("Enter a valid calibration buffer value."); return; }
            button.disabled = true;
            button.textContent = "Calibrating…";
            try {
                await requestJson(`/api/sensors/${encodeURIComponent(button.dataset.sensorId)}/calibrate`, {
                    method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({point, value})
                });
                const progress = state.standaloneCalibration.get(String(button.dataset.sensorId)) || {mid:false, low:false, high:false, requested_points:3};
                progress.requested_points = Number(host.querySelector(".ph-mode-select")?.value || progress.requested_points || 3);
                progress[point] = true;
                state.standaloneCalibration.set(String(button.dataset.sensorId), progress);
                renderCards();
                showToast(`${point === "mid" ? "Midpoint" : point === "low" ? "Low point" : "High point"} calibration completed.`);
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

document.getElementById("virtual_close").addEventListener("click", () => {
    stopVirtualDiagnostics();
    document.getElementById("virtual_panel").hidden = true;
});
document.getElementById("virtual_diagnostics_toggle").addEventListener("click", () => {
    if(virtualDiagnosticsActive)stopVirtualDiagnostics();
    else startVirtualDiagnostics().catch(error=>showToast(error.message));
});
document.getElementById("virtual_show_grid").addEventListener("change", drawVirtualOverlays);
window.addEventListener("resize", () => {
    if(virtualTestSeries.length)window.requestAnimationFrame(drawVirtualTestTimeline);
});
document.getElementById("virtual_save").addEventListener("click", async () => {
    try { await virtualSaveConfiguration(); showToast("Profile saved. A new live test is required."); }
    catch (error) { showToast(error.message); }
});
document.getElementById("virtual_test").addEventListener("click", virtualRunTest);
document.getElementById("virtual_confirm").addEventListener("click", async () => {
    try {
        state.digiflot = await requestJson("/api/digiflot/calibration/sensors/froth_interface/confirm", {method:"POST"});
        updateCalibrationProgress();
        renderCards();
        showToast("Virtual sensor calibration confirmed.");
        stopVirtualDiagnostics();
        document.getElementById("virtual_panel").hidden = true;
    } catch (error) { showToast(error.message); }
});

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
    if(virtualDiagnosticsTimer)window.clearInterval(virtualDiagnosticsTimer);
    for (const source of state.streams.values()) source.close();
});

initialise();

if (el.calibrationDrawerClose) el.calibrationDrawerClose.addEventListener("click", () => { state.activeCalibrationSensorId = null; el.calibrationDrawer.hidden = true; });
