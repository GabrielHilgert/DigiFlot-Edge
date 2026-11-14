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
    cancelCalibrationEdit: document.getElementById("cancel_calibration_edit"),
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
let virtualSessionGeneration = 0, virtualRoiController = null, virtualRoiTask = null;
let virtualCleanup = Promise.resolve(), virtualTestBusy = false, virtualDiagnosticsDesired = false;
let virtualBenchmarkTask = null;
let virtualSavedConfig = null;

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
    if (key === "sampling_interval_s") {
        const rate = 1 / Number(value || 1);
        return `<label>Sampling rate (Hz)<input id="virtual_sampling_rate" type="number" min="0.0166" max="5"
            step="any" value="${Number(rate.toPrecision(7))}" required></label>`;
    }
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
    const rate = Number(document.getElementById("virtual_sampling_rate").value);
    if (!Number.isFinite(rate) || rate < 1/60 || rate > 5) throw new Error("Sampling rate must be between 0.0167 and 5 Hz");
    // Avoid corrupting an unchanged interval via a rounded Hz display:
    // 0.3 s -> 3.333333 Hz -> 0.30000003 s must still match the saved proof.
    const displayedRate = Number((1 / Number(virtualDraft.sampling_interval_s || 1)).toPrecision(7));
    if (rate !== displayedRate) virtualDraft.sampling_interval_s = 1 / rate;
    const mode=document.getElementById("virtual_reference_mode").value;
    const custom=document.getElementById("virtual_reference_y").value.trim();
    virtualDraft.vertical_reference_mode=mode;
    virtualDraft.vertical_reference_y_cm=mode==="cell_default"||mode==="aruco_bottom"||custom===""?null:Number(custom);
    virtualDraft.reference_id=document.getElementById("virtual_named_reference").value||null;
    virtualDraft.vertical_reference_confirmed=document.getElementById("virtual_reference_confirm").checked;
    return {...virtualDraft};
}

function renderVirtualFields() {
    const main = document.getElementById("virtual_main_fields");
    main.innerHTML = ["method","resolution_px","sampling_interval_s"].map(virtualField).join("");
    document.getElementById("virtual_advanced_fields").innerHTML = virtualFieldGroups.map(([name,keys]) =>
        `<details><summary>${escapeHtml(name)}</summary>
        <div class="virtual-field-grid">${keys.map(virtualField).join("")}</div></details>`).join("");
    renderVirtualPresets();
}


function renderVirtualPresets() {
    const presets = virtualProfileData?.successful_presets || [];
    const host = document.getElementById("virtual_presets");
    host.hidden = !presets.length;
    if (!presets.length) return;
    const picker = document.getElementById("virtual_preset_select"), old = picker.value;
    picker.innerHTML = presets.map(item => {
        const roi = item.context?.detection_roi_cm?.map(v => Number(v).toFixed(1)).join(", ") || "—";
        const rate = Number(1 / item.config.sampling_interval_s).toPrecision(3);
        const name = `${rate} Hz · ROI [${roi}] cm · ${item.tested_at?.slice(0,10) || "tested"}`;
        return `<option value="${escapeHtml(item.id)}">${escapeHtml(name)}</option>`;
    }).join("");
    if (presets.some(item => item.id === old)) picker.value = old;
}

function restoreVirtualPreset() {
    const selected = document.getElementById("virtual_preset_select").value;
    const preset = (virtualProfileData?.successful_presets || []).find(item => item.id === selected);
    if (!preset) return;
    virtualDraft = {...preset.config};
    virtualRoiDirty = true;
    renderVirtualFields();
    renderVerticalReference();
    renderVirtualRoiCaption();
    drawVirtualRoiOverlay();
    virtualBenchmarkMarkup(null);
    renderVirtualTestTimeline([]);
    showToast("Previous passing settings restored. Save and run a new calibration test.");
}


function renderVerticalReference() {
    if(!virtualDraft)return;
    const library=virtualProfileData?.named_references||{points:[],default_reference_id:null};
    const named=document.getElementById("virtual_named_reference");
    named.innerHTML=library.points.map(point=>{
        const calibrated=point.position_cm||point.source==='automatic'||point.source==='derived';
        return '<option value="'+escapeHtml(point.id)+'">'+escapeHtml(point.name)+
            (calibrated?'':' · not calibrated')+'</option>';
    }).join("");
    const chosen=virtualDraft.reference_id||library.default_reference_id||'';
    named.value=chosen;
    const point=library.points.find(item=>item.id===chosen);
    document.getElementById("virtual_named_reference_info").textContent=point?
        point.name+' · '+(point.position_cm?point.position_cm.map(Number).map(v=>v.toFixed(2)).join(', ')+' cm':
            point.source==='automatic'?'Automatic ArUco reference':'Position not calibrated')+
            ' · '+(point.direction==='down'?'Depth downward':'Height upward')+
            ' · revision '+(library.revision||0):'Configure references in Cells first';
    const mode=virtualDraft.vertical_reference_mode||"cell_default";
    const select=document.getElementById("virtual_reference_mode");
    select.value=mode==="historical_offset"?"cell_default":mode;
    const override=document.getElementById("virtual_reference_y");
    override.value=virtualDraft.vertical_reference_y_cm??"";
    override.disabled=select.value==="cell_default"||select.value==="aruco_bottom";
    document.getElementById("virtual_reference_confirm").checked=Boolean(virtualDraft.vertical_reference_confirmed);
    const cell=virtualProfileData?.cell_vertical_reference||{},resolved=virtualProfileData?.reference_resolved;
    const source=select.value==="cell_default" ? "Cell default: "+(cell.mode||"aruco_bottom").replaceAll("_"," ") :
        "Sensor override: "+select.value.replaceAll("_"," ");
    let info=resolved?.y_cm!=null ? " · Saved reference Y = "+Number(resolved.y_cm).toFixed(2)+" cm" : "";
    if(select.value!=="cell_default" && select.value!=="aruco_bottom" && override.value.trim()==="")
        info+=" · Enter the physical Y coordinate if not already defined in Cells.";
    document.getElementById("virtual_reference_description").textContent=source+info+
        " · Height from bottom/ArUco is positive upward; depth from top is positive downward.";
}

function invalidateVerticalReference() {
    virtualDraft.vertical_reference_confirmed=false;
    document.getElementById("virtual_reference_confirm").checked=false;
    virtualBenchmarkMarkup(null);
    renderVirtualTestTimeline([]);
    renderVerticalReference();
}

let virtualDiagnostic = null, virtualTestSeries = [];
let virtualDiagnosticsActive = false, virtualDiagnosticsTimer = null, virtualDiagBusy = false, virtualDiagRevision = 0;
let virtualDiagRequest = null;

function paletteColor(name, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function virtualInterfaceColors() {
    // One palette for plots, diagnostics and horizontal interface markers.
    return {surface:paletteColor("--plot-froth-upper","#29AEE4"),
            pulp:paletteColor("--plot-pulp","#F47721")};
}

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
        const markerColors=virtualInterfaceColors();
        const rows = [["froth_row_px",markerColors.surface],["pulp_row_px",markerColors.pulp]];
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
    const colors=["#f87171","#4ade80",paletteColor("--plot-froth-upper","#29AEE4"),paletteColor("--plot-pulp-secondary","#E6AF11")];
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
    const markerColors=virtualInterfaceColors();
    for(const [key,color] of [["froth_row_px",markerColors.surface],["pulp_row_px",markerColors.pulp]]){
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
    const markerColors=virtualInterfaceColors();
    const keys=[["froth_surface_cm",markerColors.surface],["pulp_froth_interface_cm",markerColors.pulp]];
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
    if(!virtualDiagnosticsActive||virtualDiagBusy||document.hidden||!document.getElementById("virtual_panel").open)return;
    virtualDiagBusy=true;
    try {
        const pending=requestJson("/api/vision/virtual-sensors/froth-interface/diagnostics",{
            method:"POST",headers:{"Content-Type":"application/json"},
            body:JSON.stringify({enabled:true,last_revision:virtualDiagRevision})
        });
        virtualDiagRequest=pending;
        const payload=await pending;
        if(!virtualDiagnosticsActive)return;
        if(payload.diagnostic){virtualDiagRevision=payload.revision;renderVirtualDiagnostic(payload.diagnostic,"Live preview");}
        if(payload.error)document.getElementById("virtual_diagnostics_status").textContent=
            "Diagnostic rendering error: "+payload.error+" (sensor acquisition continues).";
        else if(!virtualDiagnostic)document.getElementById("virtual_diagnostics_status").textContent=
            "Waiting for the next lores diagnostic frame. Measurements continue independently.";
    } catch(error){
        document.getElementById("virtual_diagnostics_status").textContent="Live preview: "+error.message;
        if(/another browser tab|another calibration tab|belong to another/i.test(error.message)){
            virtualDiagnosticsDesired=false;
            void stopVirtualDiagnostics();
        }
    } finally {virtualDiagBusy=false;virtualDiagRequest=null;}
}

async function startVirtualDiagnostics() {
    if(virtualDiagnosticsActive)return;
    // A full-plane request and the live lores acquisition cannot race at startup.
    if(virtualRoiTask)await virtualRoiTask;
    if(!document.getElementById("virtual_panel").open)return;
    if(!virtualEffectiveRoi())throw new Error("Select and save a Detection ROI before starting live diagnostics");
    virtualDiagnosticsActive=true;virtualDiagRevision=0;
    document.getElementById("virtual_diagnostics_toggle").textContent="Stop live diagnostics";
    window.DigiFlotIcons?.enhance(document.getElementById("virtual_diagnostics_toggle"));
    await pollVirtualDiagnostics();
    if(virtualDiagnosticsActive)virtualDiagnosticsTimer=window.setInterval(pollVirtualDiagnostics,2500);
}

function stopVirtualDiagnostics() {
    virtualDiagnosticsActive=false;
    if(virtualDiagnosticsTimer){window.clearInterval(virtualDiagnosticsTimer);virtualDiagnosticsTimer=null;}
    document.getElementById("virtual_diagnostics_toggle").textContent="Start live diagnostics";
    window.DigiFlotIcons?.enhance(document.getElementById("virtual_diagnostics_toggle"));
    // A pending enable request must finish BEFORE disable, otherwise the old
    // response can re-enable preview after closing the modal or starting a test.
    const pending=virtualDiagRequest;
    return (async()=>{
        if(pending)await pending.catch(()=>{});
        await requestJson("/api/vision/virtual-sensors/froth-interface/diagnostics",{
            method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({enabled:false})
        }).catch(()=>{});
    })();
}


let virtualRoiPlane = null, virtualRoiDrag = null, virtualRoiDirty = false;

function virtualEffectiveRoi() {
    return virtualDraft?.detection_roi_cm || virtualProfileData?.geometry?.analysis_roi_cm || null;
}

function renderVirtualRoiCaption() {
    const roi = virtualEffectiveRoi(), target = document.getElementById("virtual_roi_label");
    const origin = virtualDraft?.detection_roi_cm ? "Detection ROI" : "Cells ROI (fallback)";
    target.textContent = roi ?
        origin + ": [" + roi.map(v=>Number(v).toFixed(2)).join(", ") + "] cm" +
        (virtualRoiDirty ? " · not saved" : "") + " · Drag to replace" :
        "No Detection ROI selected. Drag on the plane before running the calibration test.";
}

function virtualRoiPixelToCm(px, py) {
    const plane=virtualRoiPlane.plane, [w,h]=virtualRoiPlane.size;
    const [x0,y0]=plane.min_xy_cm, [x1,y1]=plane.max_xy_cm;
    return [x0+px/w*(x1-x0),y0+py/h*(y1-y0)];
}

function virtualRoiPointerPoint(event) {
    const canvas=document.getElementById("virtual_roi_canvas"), rect=canvas.getBoundingClientRect();
    if(rect.width<=0||rect.height<=0)return null;
    const x=Math.max(0,Math.min(canvas.width,(event.clientX-rect.left)/rect.width*canvas.width));
    const y=Math.max(0,Math.min(canvas.height,(event.clientY-rect.top)/rect.height*canvas.height));
    return [x,y];
}

function drawVirtualRoiOverlay() {
    if(!virtualRoiPlane)return;
    const canvas=document.getElementById("virtual_roi_canvas"),ctx=canvas.getContext("2d");
    const [w,h]=virtualRoiPlane.size,plane=virtualRoiPlane.plane;
    canvas.width=w;canvas.height=h;ctx.clearRect(0,0,w,h);
    if(document.getElementById("virtual_show_grid").checked){
        const [x0,y0]=plane.min_xy_cm,[x1,y1]=plane.max_xy_cm;
        const spacing=Math.max(1,Math.ceil(Math.max(x1-x0,y1-y0)/14));
        ctx.strokeStyle="rgba(255,255,255,.34)";ctx.lineWidth=Math.max(1,w/1000);
        for(let x=Math.ceil(x0/spacing)*spacing;x<=x1;x+=spacing){
            const px=(x-x0)/(x1-x0)*w;ctx.beginPath();ctx.moveTo(px,0);ctx.lineTo(px,h);ctx.stroke();
        }
        for(let y=Math.ceil(y0/spacing)*spacing;y<=y1;y+=spacing){
            const py=(y-y0)/(y1-y0)*h;ctx.beginPath();ctx.moveTo(0,py);ctx.lineTo(w,py);ctx.stroke();
        }
    }
    const roi = virtualEffectiveRoi();
    if(roi){
        const [x0,y0]=plane.min_xy_cm,[x1,y1]=plane.max_xy_cm;
        const left=(roi[0]-x0)/(x1-x0)*w,top=(roi[1]-y0)/(y1-y0)*h;
        const right=(roi[2]-x0)/(x1-x0)*w,bottom=(roi[3]-y0)/(y1-y0)*h;
        ctx.fillStyle="rgba(15,23,42,.36)";ctx.beginPath();ctx.rect(0,0,w,h);
        ctx.rect(left,top,right-left,bottom-top);ctx.fill("evenodd");
        ctx.strokeStyle=paletteColor("--plot-froth","#55BAE7");ctx.lineWidth=Math.max(2,w/500);
        ctx.strokeRect(left,top,right-left,bottom-top);
    }
    if(virtualRoiDrag){
        const [a,b]=[virtualRoiDrag.start,virtualRoiDrag.end];
        ctx.fillStyle="rgba(230,175,17,.17)";ctx.strokeStyle=paletteColor("--plot-pulp-secondary","#E6AF11");
        ctx.lineWidth=Math.max(2,w/500);ctx.setLineDash([8,5]);
        ctx.fillRect(Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.abs(a[0]-b[0]),Math.abs(a[1]-b[1]));
        ctx.strokeRect(Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.abs(a[0]-b[0]),Math.abs(a[1]-b[1]));
        ctx.setLineDash([]);
    }
    const lines=virtualProfileData?.reference_lines||[];
    const [minY,maxY]=[plane.min_xy_cm[1],plane.max_xy_cm[1]];
    const selected=virtualDraft?.reference_id||virtualProfileData?.named_references?.default_reference_id;
    const legend=document.getElementById("virtual_roi_reference_levels");
    legend.innerHTML=lines.length?lines.map(line=>{
        const visible=Number.isFinite(line.y_cm)&&line.y_cm>=minY&&line.y_cm<=maxY;
        const status=line.y_cm==null?"Not calibrated":visible?Number(line.y_cm).toFixed(2)+" cm":
            Number(line.y_cm).toFixed(2)+" cm · outside image";
        return '<span class="virtual-reference-level'+(line.id===selected?' selected':'')+'">'+
            '<i></i>'+escapeHtml(line.name)+': '+escapeHtml(status)+'</span>';
    }).join(""):"No cell reference points are saved.";
    // Place labels in image Y order, not in reference creation order.
    // Otherwise a point above the previous one can inherit its lower label position.
    const visibleLines=lines.filter(line=>Number.isFinite(line.y_cm)&&line.y_cm>=minY&&line.y_cm<=maxY)
        .sort((a,b)=>a.y_cm-b.y_cm);
    let previousLabel=-24;
    for(const line of visibleLines){
        const y=(line.y_cm-minY)/(maxY-minY)*h;
        const active=line.id===selected,ink=active?paletteColor("--plot-froth","#55BAE7"):paletteColor("--plot-pulp-secondary","#E6AF11");
        ctx.save();ctx.strokeStyle=ink;ctx.lineWidth=active?Math.max(2,w/320):Math.max(1,w/600);
        if(!active)ctx.setLineDash([7,5]);
        ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();
        ctx.setLineDash([]);ctx.font=Math.max(10,Math.min(16,w/48))+"px system-ui";
        const label=line.name+" · "+Number(line.y_cm).toFixed(1)+" cm";
        const labelY=Math.max(15,Math.min(h-5,Math.max(y-5,previousLabel+17)));
        previousLabel=labelY;
        const labelWidth=Math.min(w-10,ctx.measureText(label).width+10);
        ctx.fillStyle="rgba(12,25,35,.87)";ctx.fillRect(4,labelY-13,labelWidth,17);
        ctx.fillStyle=ink;ctx.fillText(label,9,labelY,Math.max(20,w-16));ctx.restore();
    }
}

async function loadVirtualRoiPlane() {
    if(virtualRoiTask)return virtualRoiTask;
    const generation=virtualSessionGeneration, controller=new AbortController();
    let timedOut=false;
    const timeout=window.setTimeout(()=>{timedOut=true;controller.abort();},25000);
    virtualRoiController=controller;
    const label=document.getElementById("virtual_roi_label");
    label.textContent="Loading the rectified camera plane…";
    const task=(async()=>{
        let payload;
        for(let attempt=0;attempt<3;attempt++){
            try {
                payload=await requestJson("/api/vision/virtual-sensors/froth-interface/detection-roi-preview",
                    {signal:controller.signal});
                break;
            } catch(error) {
                if(controller.signal.aborted || generation!==virtualSessionGeneration)throw error;
                const transient=/busy|in use|temporar|start camera|request failed|not available|unavailable/i.test(error.message);
                if(!transient || attempt===2)throw error;
                label.textContent=`Camera plane temporarily busy. Retrying (${attempt+1}/2)…`;
                await new Promise(resolve=>window.setTimeout(resolve,400*(attempt+1)));
            }
        }
        if(generation!==virtualSessionGeneration || !document.getElementById("virtual_panel").open)return false;
        virtualRoiPlane=payload;
        const stage=document.getElementById("virtual_roi_stage"),image=document.getElementById("virtual_roi_image");
        const [w,h]=payload.size;stage.hidden=false;
        stage.style.aspectRatio=w+" / "+h;
        stage.style.removeProperty("max-width");
        image.src="data:image/jpeg;base64,"+payload.jpeg_base64;
        renderVirtualRoiCaption();drawVirtualRoiOverlay();
        return true;
    })();
    virtualRoiTask=task;
    try {return await task;}
    catch(error){
        if(generation===virtualSessionGeneration && document.getElementById("virtual_panel").open) {
            if(timedOut) label.textContent="Camera plane timed out. Use Refresh to retry; calibration remains available.";
            else if(error.name!=="AbortError" && !controller.signal.aborted)
                label.textContent="Unable to load calibrated plane: "+error.message;
        }
        return false;
    }
    finally {window.clearTimeout(timeout);
        if(virtualRoiTask===task)virtualRoiTask=null;
        if(virtualRoiController===controller)virtualRoiController=null;}
}

function finishVirtualRoiDrag(event) {
    if(!virtualRoiDrag)return;
    const end=virtualRoiPointerPoint(event)||virtualRoiDrag.end;
    const start=virtualRoiDrag.start;
    virtualRoiDrag=null;
    if(Math.abs(end[0]-start[0])>=12 && Math.abs(end[1]-start[1])>=12) {
        const lo=[Math.min(start[0],end[0]),Math.min(start[1],end[1])];
        const hi=[Math.max(start[0],end[0]),Math.max(start[1],end[1])];
        virtualDraft.detection_roi_cm=[...virtualRoiPixelToCm(...lo),...virtualRoiPixelToCm(...hi)];
        virtualRoiDirty=true;
        virtualBenchmarkMarkup(null);
        document.getElementById("virtual_diagnostics_status").textContent=
            "Detection ROI changed. Save settings and run the calibration test again.";
    }
    renderVirtualRoiCaption();drawVirtualRoiOverlay();
}

function virtualBenchmarkMarkup(result) {
    const target = document.getElementById("virtual_benchmark");
    target.dataset.passed = String(Boolean(result?.passed && result?.current !== false));
    const confirm = document.getElementById("virtual_confirm");
    confirm.disabled = !result?.passed || result?.current === false;
    if (!result) {
        target.textContent = "Save settings to check for a matching passed test. If none exists, run a live calibration test.";
        return;
    }
    const fmt = n => Number.isFinite(Number(n)) ? Number(n).toFixed(1) : "—";
    const reused = Boolean(result.reused && result.passed && result.current !== false);
    const testedOn = result.tested_at ? new Date(result.tested_at).toLocaleString() : "";
    target.innerHTML = `<strong>${reused ? "Previously validated · test not required" :
        result.passed && result.current !== false ? "Test passed" : "Test not accepted"}</strong>
        ${reused ? `<p>Exact camera, crop, geometry, ROI, acquisition rate, detector settings and processing version match the last successful benchmark${testedOn ? " (" + escapeHtml(testedOn) + ")" : ""}. You can confirm this sensor without retesting.</p>` : ""}
        <div class="virtual-stats">
        <div><span>P95 latency</span><strong>${fmt(result.p95_ms)} ms</strong></div>
        <div><span>P99 latency</span><strong>${fmt(result.p99_ms)} ms</strong></div>
        <div><span>Deadline</span><strong>${fmt(result.deadline_ms)} ms</strong></div>
        <div><span>Main recording</span><strong>${fmt(result.main_recording_fps)} FPS (min ${fmt(result.min_recording_fps)})</strong></div>
        <div><span>Valid detections</span><strong>${fmt(Number(result.valid_fraction)*100)}%</strong></div>
        <div><span>lores</span><strong>${escapeHtml((result.lores_size||[]).join(" × "))}</strong></div>
        <div><span>Output ROI</span><strong>${escapeHtml((result.roi_resolution||[]).join(" × "))}</strong></div>
        </div>${reused ? "" : "<p>Samples were captured at the configured acquisition interval with the main encoder recording. The temporary video was discarded.</p>"}
        ${result.frame_reuse_detected ? '<p>Repeated camera timestamps detected; choose a lower acquisition rate or check the camera stream.</p>' : ''}
        ${result.errors?.length ? `<p>${escapeHtml(result.errors.join("; "))}</p>` : ""}`;
}

async function releaseVirtualCamera() {
    try {await requestJson("/api/cameras/preview/stop",{method:"POST"});}
    catch(error){if(!/another browser tab|another camera/i.test(error.message))
        console.warn("Could not release HIFIE camera preview:", error);}
}

function virtualHasUnsavedChanges() {
    if(!virtualSavedConfig || !virtualDraft)return false;
    try {return virtualRoiDirty || JSON.stringify(virtualCollectInputs())!==JSON.stringify(virtualSavedConfig);}
    catch(_) {return true;}
}

function requestVirtualClose() {
    const panel=document.getElementById("virtual_panel");
    if(!panel.open)return;
    if(virtualHasUnsavedChanges() && !window.confirm("Discard unsaved HIFIE settings?"))return;
    panel.close();
}

function cleanupVirtualSession() {
    ++virtualSessionGeneration;
    virtualRoiController?.abort();virtualRoiController=null;virtualRoiTask=null;
    virtualDiagnosticsDesired=false;
    const stop=stopVirtualDiagnostics();
    virtualCleanup=virtualCleanup.catch(()=>{}).then(async()=>{
        await stop;
        if(virtualBenchmarkTask)await virtualBenchmarkTask.catch(()=>{});
        await releaseVirtualCamera();
    });
}

async function openVirtualCalibration() {
    if (!state.calibrationMode)return;
    const panel=document.getElementById("virtual_panel");
    if(panel.open)return;
    const generation=++virtualSessionGeneration;
    const missing=document.getElementById("virtual_missing"),editor=document.getElementById("virtual_editor");
    panel.showModal();
    missing.hidden=true;editor.hidden=true;
    document.getElementById("virtual_modal_footer").hidden=true;
    virtualRoiDirty=false;virtualSavedConfig=null;
    try {
        await virtualCleanup;
        if(generation!==virtualSessionGeneration || !panel.open)return;
        const cellId=state.digiflot?.cell_selection?.cell_id || "";
        const cameraId=state.digiflot?.cell_selection?.camera_id;
        document.getElementById("virtual_source").textContent=cameraId==null?"No camera":`Camera ${cameraId}`;
        document.getElementById("virtual_open_cells").href=
            `/cells?cell=${encodeURIComponent(cellId)}&camera=${encodeURIComponent(cameraId??"")}`;
        document.getElementById("virtual_recalibrate_camera").href=document.getElementById("virtual_open_cells").href;
        document.getElementById("virtual_edit_named").href=document.getElementById("virtual_open_cells").href;
        const profile=await requestJson("/api/vision/virtual-sensors/froth-interface/profile");
        if(generation!==virtualSessionGeneration || !panel.open)return;
        virtualProfileData=profile;virtualDraft={...profile.config};
        document.getElementById("virtual_geometry").textContent=
            `${cellId} · Geometry ${profile.geometry.calibration_id} · ${profile.source} profile`;
        missing.hidden=true;editor.hidden=false;
        document.getElementById("virtual_modal_footer").hidden=false;
        document.getElementById("virtual_method_section").open=false;
        renderVirtualFields();renderVerticalReference();
        virtualSavedConfig=virtualCollectInputs();
        virtualRoiPlane=null;virtualRoiDirty=false;
        document.getElementById("virtual_roi_stage").hidden=true;
        renderVirtualRoiCaption();
        virtualBenchmarkMarkup(profile.test);renderVirtualTestTimeline(profile.test?.series||[]);
        if(profile.test_diagnostic)renderVirtualDiagnostic(profile.test_diagnostic,"Last calibration test");
        // First capture the calibrated plane, then start the background lores
        // diagnostics. Simultaneous Picamera2 acquisition broke some sessions.
        const planeReady=await loadVirtualRoiPlane();
        if(generation!==virtualSessionGeneration || !panel.open)return;
        if(planeReady && virtualEffectiveRoi()) {
            virtualDiagnosticsDesired=true;
            await startVirtualDiagnostics().catch(error=>{if(panel.open)showToast(error.message);});
        }
    } catch(error) {
        if(generation!==virtualSessionGeneration || !panel.open)return;
        missing.hidden=false;editor.hidden=true;
        document.getElementById("virtual_modal_footer").hidden=true;
        await stopVirtualDiagnostics();
        missing.querySelector("p").textContent=error.message;
    }
}

async function virtualSaveConfiguration() {
    const config = virtualCollectInputs();
    await requestJson("/api/vision/virtual-sensors/froth-interface/profile", {
        method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(config)
    });
    // Server is authoritative: after Save, an exact historical match may
    // immediately enable Confirm, without another recording benchmark.
    const refreshed = await requestJson("/api/vision/virtual-sensors/froth-interface/profile");
    virtualProfileData = refreshed;
    virtualProfileData.config={...config};
    renderVirtualPresets();
    virtualSavedConfig=JSON.parse(JSON.stringify(config));
    virtualRoiDirty=false;
    renderVirtualRoiCaption();
    virtualBenchmarkMarkup(refreshed.test);
    renderVirtualTestTimeline(refreshed.test?.series || []);
    virtualDiagnostic=null;
    document.getElementById("virtual_diagnostic_grid").hidden=true;
    document.getElementById("virtual_diagnostic_positions").hidden=true;
    document.getElementById("virtual_diagnostics_status").textContent=
        refreshed.test?.reused ? "Previous passing benchmark matches these settings. A new test is optional." :
            "Settings updated. Waiting for a diagnostic frame with the new parameters.";
    await refreshDigiFlotState();
}

async function virtualRunTest() {
    const panel=document.getElementById("virtual_panel"),generation=virtualSessionGeneration;
    const button=document.getElementById("virtual_test"),resumeDiagnostics=virtualDiagnosticsDesired;
    virtualTestBusy=true;
    button.disabled=true;button.textContent="Running test…";
    // The main camera encoder and diagnostic preview must never run concurrently.
    virtualRoiController?.abort();
    try {
        if(virtualDiagnosticsActive)await stopVirtualDiagnostics();
        if(!document.getElementById("virtual_reference_confirm").checked)
            throw new Error("Select and confirm a physical vertical reference before the calibration test");
        await virtualSaveConfiguration();
        const result=await requestJson("/api/vision/virtual-sensors/froth-interface/benchmark",{
            method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({samples:20})
        });
        if(generation!==virtualSessionGeneration || !panel.open)return;
        virtualBenchmarkMarkup({...result,current:true});
        renderVirtualTestTimeline(result.series||[]);
        if(result.diagnostic)renderVirtualDiagnostic(result.diagnostic,"Calibration test");
        else document.getElementById("virtual_diagnostics_status").textContent=
            result.diagnostic_error||"The test ran, but no diagnostic entropy map was produced.";
        state.digiflot=await requestJson("/api/digiflot/state");
        if(result.passed) {
            try {
                const fresh=await requestJson("/api/vision/virtual-sensors/froth-interface/profile");
                if(generation===virtualSessionGeneration && panel.open) {
                    virtualProfileData.successful_presets=fresh.successful_presets||[];
                    renderVirtualPresets();
                }
            } catch(error) {console.warn("Could not refresh successful HIFIE profiles:",error);}
        }
        if(generation===virtualSessionGeneration && panel.open) {
            updateCalibrationProgress();
            showToast(result.passed?"Live test passed. Inspect diagnostics before confirming.":
                "Detection or timing criteria failed. Adjust settings and test again.");
        }
    } catch(error) {
        if(generation===virtualSessionGeneration && panel.open) {
            virtualBenchmarkMarkup(null);showToast(error.message);
        }
    } finally {
        virtualTestBusy=false;
        button.disabled=false;button.textContent="Run test";
        window.DigiFlotIcons?.enhance(button);
        if(resumeDiagnostics && virtualDiagnosticsDesired && generation===virtualSessionGeneration && panel.open)
            await startVirtualDiagnostics().catch(error=>showToast(error.message));
    }
}

function calibrationMarkup(snapshot) {
    if (state.digiflot?.state === "Ready") {
        const item = calibrationItem(snapshot.id) || {};
        const status = item.status || "unconfigured";
        const details = item.mode === "ph_points"
            ? ` · ${item.chip_points ?? "—"} chip points · ${item.requested_points ?? "—"} requested`
            : item.mode === "virtual_interface"
                ? " · Live geometry and benchmark preserved until recalibration starts"
                : "";
        return `<div class="calibration-block complete-block">
            <div><strong>Calibration review (read-only)</strong>
                <span>Status: ${escapeHtml(status)}${escapeHtml(details)}. Review does not change experiment readiness.</span></div>
            <div class="calibration-actions">
                <span class="calibration-pill ${escapeHtml(status)}">${escapeHtml(status)}</span>
                <button class="button button-secondary sensor-reopen" data-icon="rotate-ccw" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Recalibrate</button>
            </div>
        </div>`;
    }
    if (snapshot.type === "virtual_froth_interface") {
        if (!state.calibrationMode) return '<div class="calibration-block"><strong>Virtual camera-based sensor</strong><span>Configured in the experiment calibration workflow.</span></div>';
        const item = calibrationItem(snapshot.id) || {};
        return `<div class="calibration-block">
            <div><strong>HIFIE · Camera ${escapeHtml(snapshot.source_camera_id)}</strong>
            <span>Cell ${escapeHtml(snapshot.physical_cell_id)} · Reuse matching passed calibration or run a test</span></div>
            <div class="calibration-actions"><span class="calibration-pill ${escapeHtml(item.status || "pending")}">${escapeHtml(item.status || "Pending")}</span>
            <button class="button button-primary open-virtual-calibration" data-icon="scan" type="button">
            ${item.status === "passed" ? "Review" : "Configure"}</button>
            ${item.status !== "passed" && item.status !== "skipped" ? '<button class="button button-secondary sensor-skip" data-icon="skip-forward" data-sensor-id="froth_interface" type="button">Skip HIFIE</button>' : ""}
            ${item.status === "passed" || item.status === "skipped" ? '<button class="button button-secondary sensor-reopen" data-icon="rotate-ccw" data-sensor-id="froth_interface" type="button">Reopen</button>' : ""}</div>
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
                    <button class="button button-secondary sensor-reopen" data-icon="rotate-ccw" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Edit calibration</button>
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
                    <button class="button button-secondary sensor-reopen" data-icon="rotate-ccw" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Edit calibration</button>
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
                    <button class="button button-secondary sensor-skip" data-icon="skip-forward" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Skip tare</button>
                    <button class="button button-primary sensor-confirm" data-icon="badge-check" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Tare complete</button>
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
                        <button class="button button-secondary sensor-skip" data-icon="skip-forward" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Skip calibration</button>
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
                <button class="button button-secondary sensor-skip" data-icon="skip-forward" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Skip check</button>
                <button class="button button-primary sensor-confirm" data-icon="badge-check" data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Mark checked</button>
            </div>
        </div>`;
}

function sensorCalibrationEntry(snapshot) {
    const markup = calibrationMarkup(snapshot);
    if (!markup) return "";
    // Only pH and HIFIE need full editors. Other sensors keep their original
    // inline checks, including Passed/Skipped badges and completion actions.
    if (String(snapshot.type || "").toLowerCase() !== "ph") return markup;
    const calibration = calibrationItem(snapshot.id);
    const standalone = state.standaloneCalibration.get(String(snapshot.id));
    const completed = calibration?.points
        ? Object.values(calibration.points).filter(point => point?.status === "passed").length
        : ["mid","low","high"].filter(point => standalone?.[point]).length;
    const requested = Number(calibration?.requested_points || standalone?.requested_points || 3);
    const rawStatus = String(calibration?.status ||
        (completed >= requested ? "passed" : completed ? "in_progress" : "pending")).toLowerCase();
    const status = ["passed","skipped","pending","in_progress","unavailable","failed"].includes(rawStatus)
        ? rawStatus : "pending";
    const label = {passed:"Passed",skipped:"Skipped",pending:"Pending",in_progress:"In progress",
        unavailable:"Unavailable",failed:"Failed"}[status];
    const progress = status === "skipped" ? (calibration?.skip_reason || "Skipped by operator")
        : Number.isFinite(requested) && requested > 0 ? `${completed}/${requested} calibration points completed` : "";
    return `<div class="calibration-block calibration-modal-entry">
        <div><strong>pH calibration</strong><span>${escapeHtml(progress)}</span></div>
        <div class="calibration-heading-actions">
            <span class="calibration-pill ${escapeHtml(status)}">${escapeHtml(label)}</span>
            <button class="button button-secondary open-calibration-drawer" data-icon="sliders"
                data-sensor-id="${escapeHtml(snapshot.id)}" type="button">Calibrate</button>
        </div>
    </div>`;
}

function calibrationIndicator(snapshot) {
    // Checklist status is independent from the live connection status.
    // Keep the indicator on the card, never inside the pH or HIFIE dialog.
    if (!state.calibrationMode && state.digiflot?.state !== "Ready") return "";
    const calibration = calibrationItem(snapshot.id);
    if (!calibration) return "";
    const status = String(calibration.status || "pending").toLowerCase();
    const indicator = {
        passed: ["checked", "badge-check", "Checked", "Calibration or sensor check completed"],
        skipped: ["skipped", "skip-forward", "Skipped", "Calibration explicitly skipped"],
        unavailable: ["unavailable", "circle-dashed", "Unavailable", "Sensor unavailable during calibration"],
        in_progress: ["pending", "circle-dashed", "In progress", "Calibration not yet completed"],
        failed: ["pending", "circle-dashed", "Not checked", "Calibration not yet completed"],
        pending: ["pending", "circle-dashed", "Not checked", "Sensor has not been checked or calibrated"]
    }[status] || ["pending", "circle-dashed", "Not checked", "Sensor has not been checked or calibrated"];
    const [kind, icon, label, title] = indicator;
    return `<span class="calibration-indicator calibration-indicator-${kind}" data-calibration-status="${kind}"
        data-icon="${icon}" title="${title}">${label}</span>`;
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
                <div class="sensor-card-badges">
                    <span class="sensor-status status-${escapeHtml(status)}"><span></span>${escapeHtml(statusLabel(status))}</span>
                    ${calibrationIndicator(snapshot)}
                </div>
            </header>

            <div class="sensor-reading-row">
                <div class="sensor-reading">
                    ${virtual ? '<span class="virtual-main-label">Froth thickness</span><div class="virtual-main-value">' : ""}
                    <strong class="reading-value">${hasValue ? escapeHtml(formatValue(snapshot.value, snapshot)) : "—"}</strong>
                    <span class="reading-unit">${escapeHtml(snapshot.unit || "")}</span>
                    ${virtual ? "</div>" : ""}
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
            <div class="calibration-host">${sensorCalibrationEntry(snapshot)}</div>
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
    window.DigiFlotIcons?.decorate(el.sensorGrid);
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
        host.innerHTML = sensorCalibrationEntry(snapshot);
        bindCalibrationControls(host);
        window.DigiFlotIcons?.decorate(host);
    }
    // Live samples must not rebuild an open modal form; that would erase draft
    // calibration values and interrupt the operator's focus on every reading.
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
    const markerColors=virtualInterfaceColors();
    for(const [key,color] of [["upper",markerColors.surface],["lower",markerColors.pulp]]){
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
    ctx.strokeStyle = css.getPropertyValue("--accent").trim() || paletteColor("--plot-froth","#55BAE7");
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

    const reviewing = state.digiflot.state === "Ready";
    const workflowLink=el.calibrationBanner.querySelector("a");
    if(workflowLink) {
        workflowLink.href=state.calibrationMode ? "/cells" : "/run";
        workflowLink.textContent=state.calibrationMode ? "Cell & references" : "Back to run";
        window.DigiFlotIcons?.enhance(workflowLink);
    }
    el.calibrationBanner.hidden = !state.calibrationMode && !reviewing;
    el.calibrationFooter.hidden = !state.calibrationMode;
    const heading = el.calibrationBanner.querySelector("strong");
    const detail = el.calibrationBanner.querySelector("span");
    if (heading) heading.textContent = reviewing ? "Review sensor calibration" : "Sensor calibration";
    if (detail) detail.textContent = reviewing
        ? "Review is read-only. Select Recalibrate for a deliberate workflow change; otherwise return to Run."
        : "Calibrate, confirm, or explicitly skip each connected sensor before returning to Run.";
    el.pageTitle.textContent = reviewing ? "Sensor calibration review" : state.calibrationMode ? "Sensor calibration" : "Sensor monitoring & calibration";
    el.pageDescription.textContent = reviewing
        ? "Review previously confirmed sensor checks without invalidating the experiment setup."
        : state.calibrationMode
            ? "All configured sensors are monitored simultaneously. Calibrate supported devices while observing their live signals."
            : "Live measurements from every configured sensor. Supported sensors can be calibrated here without creating an experiment.";
    updateCalibrationProgress();
}

function closeResolvedPhDialog(sensorId) {
    if (!el.calibrationDrawer.open || String(state.activeCalibrationSensorId) !== String(sensorId)) return;
    const calibration = calibrationItem(sensorId);
    const standalone = state.standaloneCalibration.get(String(sensorId));
    const standaloneDone = !state.calibrationMode && standalone &&
        ["mid","low","high"].slice(0,Number(standalone.requested_points || 3)).every(point => standalone[point]);
    if (["passed","skipped"].includes(calibration?.status) || standaloneDone) el.calibrationDrawer.close();
}

function renderCalibrationDrawer() {
    const id = state.activeCalibrationSensorId;
    const snapshot = id == null ? null : state.sensors.get(String(id));
    if (!snapshot || String(snapshot.type || "").toLowerCase() !== "ph") {
        if (el.calibrationDrawer.open) el.calibrationDrawer.close();
        return;
    }
    el.calibrationDrawerTitle.textContent = `${snapshot.name || snapshot.id} · calibration`;
    el.calibrationDrawerBody.innerHTML = calibrationMarkup(snapshot);
    bindCalibrationControls(el.calibrationDrawerBody);
    window.DigiFlotIcons?.decorate(el.calibrationDrawerBody);
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
            if (!el.calibrationDrawer.open) el.calibrationDrawer.showModal();
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
                await refreshDigiFlotState();
                renderCards();
                showToast("Recalibration started. Cancel before changes to restore the earlier approval.");
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
                closeResolvedPhDialog(button.dataset.sensorId);
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
                closeResolvedPhDialog(button.dataset.sensorId);
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
                closeResolvedPhDialog(button.dataset.sensorId);
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
    const edit = state.digiflot.calibration_edit;
    if (el.cancelCalibrationEdit) {
        el.cancelCalibrationEdit.hidden = !edit || Boolean(edit.dirty);
        el.cancelCalibrationEdit.disabled = !edit || Boolean(edit.dirty);
    }
    if (edit?.dirty) el.calibrationHint.textContent += " Existing approval cannot be restored after changes; finish or skip calibration.";
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

const virtualDialog = document.getElementById("virtual_panel");
virtualDialog.addEventListener("close", cleanupVirtualSession);
virtualDialog.addEventListener("cancel", event => {event.preventDefault();requestVirtualClose();});
// Clicking the backdrop must never dismiss calibration during an active camera request.
document.getElementById("virtual_close").addEventListener("click", requestVirtualClose);
document.getElementById("virtual_diagnostics_toggle").addEventListener("click", () => {
    if(virtualDiagnosticsActive) {
        virtualDiagnosticsDesired=false;
        void stopVirtualDiagnostics();
    } else {
        virtualDiagnosticsDesired=true;
        startVirtualDiagnostics().catch(error=>showToast(error.message));
    }
});
document.getElementById("virtual_preset_restore").addEventListener("click", () => {
    if(virtualHasUnsavedChanges() && !window.confirm("Replace unsaved settings with the previous passing profile?"))return;
    restoreVirtualPreset();
});
document.getElementById("virtual_advanced_fields").addEventListener("toggle", event => {
    if(event.target.tagName!=="DETAILS" || !event.target.open)return;
    document.querySelectorAll("#virtual_advanced_fields > details").forEach(node=>{
        if(node!==event.target)node.open=false;
    });
}, true);
document.getElementById("virtual_show_grid").addEventListener("change", () => {
    drawVirtualOverlays();drawVirtualRoiOverlay();
});
document.getElementById("virtual_named_reference").addEventListener("change",()=>{
    if(!virtualDraft)return;
    virtualDraft.reference_id=document.getElementById("virtual_named_reference").value;
    virtualDraft.vertical_reference_confirmed=false;
    document.getElementById("virtual_reference_confirm").checked=false;
    virtualBenchmarkMarkup(null);renderVirtualTestTimeline([]);renderVerticalReference();
    drawVirtualRoiOverlay();
});
document.getElementById("virtual_reference_mode").addEventListener("change",()=>{
    if(!virtualDraft)return;
    virtualDraft.vertical_reference_mode=document.getElementById("virtual_reference_mode").value;
    virtualDraft.vertical_reference_y_cm=null;
    invalidateVerticalReference();
});
document.getElementById("virtual_reference_y").addEventListener("input",()=>{
    if(!virtualDraft)return;
    const value=document.getElementById("virtual_reference_y").value.trim();
    virtualDraft.vertical_reference_y_cm=value===""?null:Number(value);
    virtualDraft.vertical_reference_confirmed=false;
    document.getElementById("virtual_reference_confirm").checked=false;
    virtualBenchmarkMarkup(null);renderVirtualTestTimeline([]);
    document.getElementById("virtual_reference_description").textContent=
        "Reference coordinate modified. Review and confirm it before the next calibration test.";
});
document.getElementById("virtual_reference_confirm").addEventListener("change",event=>{
    if(virtualDraft)virtualDraft.vertical_reference_confirmed=event.target.checked;
});
document.getElementById("virtual_refresh_geometry").addEventListener("click",async()=>{
    if(virtualHasUnsavedChanges() && !window.confirm("Discard unsaved changes and reload geometry?"))return;
    virtualDialog.close();
    await virtualCleanup;
    await openVirtualCalibration().catch(error=>showToast(error.message));
});
document.getElementById("virtual_roi_refresh").addEventListener("click", async event => {
    const button=event.currentTarget, generation=virtualSessionGeneration;
    const resume=virtualDiagnosticsActive || virtualDiagnosticsDesired;
    button.disabled=true;
    virtualDiagnosticsDesired=false;
    try {
        if(virtualDiagnosticsActive)await stopVirtualDiagnostics();
        const loaded=await loadVirtualRoiPlane();
        if(!document.getElementById("virtual_panel").open || generation!==virtualSessionGeneration)return;
        if(loaded && resume && virtualEffectiveRoi()){
            virtualDiagnosticsDesired=true;
            await startVirtualDiagnostics();
        } else if(!loaded) {
            showToast("The rectified plane could not be loaded. Use Refresh to try again.");
        }
    } catch(error){if(generation===virtualSessionGeneration)showToast(error.message);}
    finally{button.disabled=false;}
});
document.getElementById("virtual_roi_reset").addEventListener("click", () => {
    if(!virtualDraft)return;
    virtualDraft.detection_roi_cm=null;virtualRoiDirty=true;
    virtualBenchmarkMarkup(null);
    renderVirtualRoiCaption();drawVirtualRoiOverlay();
});
const virtualRoiCanvas=document.getElementById("virtual_roi_canvas");
virtualRoiCanvas.addEventListener("pointerdown", event=>{
    if(!virtualRoiPlane||!virtualDraft)return;
    const point=virtualRoiPointerPoint(event);
    if(!point)return;
    event.preventDefault();
    virtualRoiDrag={start:point,end:point};
    virtualRoiCanvas.setPointerCapture(event.pointerId);
    drawVirtualRoiOverlay();
});
virtualRoiCanvas.addEventListener("pointermove", event=>{
    if(!virtualRoiDrag)return;
    virtualRoiDrag.end=virtualRoiPointerPoint(event)||virtualRoiDrag.end;
    drawVirtualRoiOverlay();
});
virtualRoiCanvas.addEventListener("pointerup", finishVirtualRoiDrag);
virtualRoiCanvas.addEventListener("pointercancel", ()=>{
    virtualRoiDrag=null;drawVirtualRoiOverlay();
});
window.addEventListener("resize", () => {
    if(virtualTestSeries.length)window.requestAnimationFrame(drawVirtualTestTimeline);
});
document.getElementById("virtual_save").addEventListener("click", async () => {
    try { await virtualSaveConfiguration();
        showToast(virtualProfileData?.test?.reused ?
            "Exact previous calibration verified. You can confirm without a new test." :
            virtualProfileData?.test?.current && virtualProfileData?.test?.passed ?
                "Configuration already tested. Ready to confirm." : "Profile saved. Run a calibration test to confirm."); }
    catch (error) { showToast(error.message); }
});
document.getElementById("virtual_test").addEventListener("click", () => {
    if(virtualBenchmarkTask)return;
    const task=virtualRunTest();
    virtualBenchmarkTask=task;
    void task.finally(()=>{if(virtualBenchmarkTask===task)virtualBenchmarkTask=null;});
});
document.getElementById("virtual_confirm").addEventListener("click", async () => {
    try {
        state.digiflot = await requestJson("/api/digiflot/calibration/sensors/froth_interface/confirm", {method:"POST"});
        updateCalibrationProgress();
        renderCards();
        showToast("Virtual sensor calibration confirmed.");
        if (virtualDialog.open) virtualDialog.close();
    } catch (error) { showToast(error.message); }
});

async function initialise() {
    try {
        await refreshDigiFlotState();
        await loadSensors();
        const requested = new URLSearchParams(window.location.search).get("review");
        if (requested && state.digiflot.state === "Ready") {
            const card = cardFor(requested);
            card?.scrollIntoView({behavior:"smooth",block:"center"});
            const sensor = state.sensors.get(String(requested));
            if (sensor && String(sensor.type || "").toLowerCase() === "ph") {
                state.activeCalibrationSensorId = String(requested);
                renderCalibrationDrawer();
                if (!el.calibrationDrawer.open) el.calibrationDrawer.showModal();
            }
        }
    } catch (error) {
        showToast(error.message);
        el.emptyState.hidden = false;
        el.emptyState.querySelector("h2").textContent = "Unable to load sensors";
        el.emptyState.querySelector("p").textContent = error.message;
    }
}

if (el.cancelCalibrationEdit) el.cancelCalibrationEdit.addEventListener("click", async () => {
    el.cancelCalibrationEdit.disabled = true;
    try {
        await requestJson("/api/digiflot/calibration/cancel", {method:"POST"});
        window.location.href = "/run";
    } catch(error) {
        showToast(error.message);
        await refreshDigiFlotState();
        renderCards();
    }
});

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

if (el.calibrationDrawerClose) el.calibrationDrawerClose.addEventListener("click", () => el.calibrationDrawer.close());
el.calibrationDrawer.addEventListener("close", () => { state.activeCalibrationSensorId = null; });
el.calibrationDrawer.addEventListener("click", event => {
    if (event.target === el.calibrationDrawer) el.calibrationDrawer.close();
});
