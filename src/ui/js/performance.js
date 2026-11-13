const el = {};
let latest = null;
let evaluation = null;
let virtualChoiceTouched = false;

function cache() {
    ["profile_status","profile_date","recommended_rate","temperature","throttle_state","disk_free","load_state",
     "benchmark_title","benchmark_message","benchmark_state","rates","duration","start_benchmark","abort_benchmark",
     "live_test","current_rate","elapsed","live_temp","live_load","live_cpu_idle","live_ram_available",
     "cpu_used","cpu_idle","memory_used","memory_available","include_virtual","virtual_workload_status",
     "benchmark_results","profile_results","toast"]
        .forEach(id => el[id] = document.getElementById(id));
}

async function requestJson(url, options={}) {
    const response = await fetch(url, options);
    let data = null;
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(data?.detail || `${response.status} ${response.statusText}`);
    return data;
}

function toast(message) {
    el.toast.textContent = message;
    el.toast.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.toast.classList.remove("show"), 3000);
}

function fmt(value, digits=1, suffix="") {
    return value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value).toFixed(digits)}${suffix}`;
}

function ratesText(rates) {
    if (!rates || Object.keys(rates).length === 0) return "—";
    return Object.entries(rates).map(([id, rate]) => `C${id}: ${Number(rate)} fps`).join(" · ");
}

function headroomDetails(item) {
    const risk=item.headroom_risk||{},virtual=item.virtual_sensor||{};
    const resource="Minimum free: CPU "+fmt(item.cpu_free_min_pct,1,"%")+
        " · RAM "+fmt(item.memory_free_min_pct,1,"%");
    const exposure=risk.samples?
        " · <10% free: "+risk.low_samples+"/"+risk.samples+" samples ("+fmt(risk.observed_pct,1,"%")+
        "), indicative 95% upper bound "+fmt(risk.upper_bound_95_pct,1,"%"):
        " · CPU/RAM exposure estimate unavailable";
    const sensor=virtual.included ? " · Froth Interface "+virtual.samples+" frames, P95 "+
        fmt(virtual.p95_latency_ms,1," ms")+", missed "+(virtual.missed_intervals||0):
        " · Camera-only test (virtual detector not included)";
    return resource+exposure+sensor;
}

function resultRow(item) {
    const classification = String(
        item.classification || "UNKNOWN"
    );
    const className = classification
        .toLowerCase()
        .replaceAll("_", "-");

    return `<div class="result-row result-${className}">
        <strong>${ratesText(item.camera_rates)}</strong>
        <span>${classification.replaceAll("_", " ")}</span>
        <span>${fmt(item.max_temperature_c,1," °C")}</span>
        <p>${item.reason || ""}</p>
        <small class="result-resources">${headroomDetails(item)}</small>
    </div>`;
}

function benchmarkSummary(results) {
    const failed = (results || []).find(
        item => item.classification === "FAIL"
    );

    if (!failed) {
        return "All requested frame rates completed.";
    }

    return `Stopped after ${Number(failed.rate)} fps failed. Higher frame rates were not tested.`;
}

function render(status) {
    latest = status;
    const system = status.system || {};
    const profile = status.profile;
    const throttle = system.throttled || {};

    el.profile_status.textContent = evaluation?.status || (profile ? "SAVED" : "UNVALIDATED");
    el.profile_date.textContent = profile?.tested_at ? `Tested ${new Date(profile.tested_at).toLocaleString()}` : "No benchmark";
    el.recommended_rate.textContent = ratesText(profile?.recommended_camera_rates);
    el.temperature.textContent = fmt(system.temperature_c, 1, " °C");
    el.throttle_state.textContent = `Throttling ${throttle.current ? "ACTIVE" : "No"}`;
    el.disk_free.textContent = fmt(system.disk?.free_gb, 1, " GB");
    el.load_state.textContent = `Load ${fmt(system.load1, 2)}`;
    el.cpu_used.textContent = fmt(system.cpu?.used_pct,1,"%");
    el.cpu_idle.textContent = "Idle "+fmt(system.cpu?.free_pct,1,"%");
    el.memory_used.textContent = fmt(system.memory?.used_pct,1,"%");
    el.memory_available.textContent = "Available "+fmt(system.memory?.free_pct,1,"%");

    const running = status.state === "Running";
    el.benchmark_state.textContent = status.state || "Unavailable";
    el.start_benchmark.hidden = running;
    el.abort_benchmark.hidden = !running;
    el.live_test.hidden = !running;
    if (running) {
        el.benchmark_title.textContent = `Testing ${status.current_rate ?? "—"} fps`;
        el.current_rate.textContent = status.current_rate == null ? "—" : `${status.current_rate} fps`;
        el.elapsed.textContent = `${fmt(status.elapsed_s,1," s")}`;
        el.live_temp.textContent = fmt(system.temperature_c,1," °C");
        el.live_load.textContent = fmt(system.load1,2);
        el.live_cpu_idle.textContent = fmt(system.cpu?.free_pct,1,"%");
        el.live_ram_available.textContent = fmt(system.memory?.free_pct,1,"%");
    } else {
        if (status.state === "Completed") {
            el.benchmark_title.textContent = "Benchmark complete";
            el.benchmark_message.textContent = benchmarkSummary(
                status.results || []
            );
        } else if (status.state === "Aborted") {
            el.benchmark_title.textContent = "Benchmark aborted";
        } else if (status.state === "Failed") {
            el.benchmark_title.textContent = "Benchmark failed";
        } else {
            el.benchmark_title.textContent = "Ready";
        }
    }
    if (status.last_error) {
        el.benchmark_message.textContent = status.last_error;
    }

    el.benchmark_results.innerHTML = (status.results || []).map(resultRow).join("");
    el.profile_results.innerHTML = profile?.results?.length
        ? profile.results.map(resultRow).join("")
        : "<p>No saved profile.</p>";
}

function parseRates() {
    const rates = el.rates.value.split(",").map(v => Number.parseFloat(v.trim())).filter(Number.isFinite);
    if (!rates.length) throw new Error("Enter at least one frame rate.");
    return [...new Set(rates)].sort((a,b) => a-b);
}

async function refresh() {
    try {
        const workload=await requestJson("/api/digiflot/performance/virtual-workload");
        if(!virtualChoiceTouched)el.include_virtual.checked=Boolean(workload.available);
        el.include_virtual.disabled=!workload.available;
        const virtual=workload.configuration;
        el.virtual_workload_status.textContent=workload.available?
            "Virtual workload ready · Camera "+virtual.camera_id+" · "+virtual.method+
            " · sampling every "+virtual.sampling_interval_s+" s. Test uses both main encoders.":
            "Froth Interface unavailable: "+workload.reason+" Camera-only benchmarks remain possible.";
        evaluation = await requestJson("/api/digiflot/performance/evaluate", {method:"POST", headers:{"Content-Type":"application/json"}, body:"{}"});
        render(await requestJson("/api/digiflot/performance"));
    } catch (error) { toast(error.message); }
}

function bind() {
    el.include_virtual.addEventListener("change",()=>{virtualChoiceTouched=true;});
    el.start_benchmark.addEventListener("click", async () => {
        try {
            const rates = parseRates();
            const duration = Number.parseFloat(el.duration.value);
            await requestJson("/api/digiflot/performance/benchmark/start", {
                method:"POST", headers:{"Content-Type":"application/json"},
                body: JSON.stringify({rates, duration_s: duration, include_virtual:el.include_virtual.checked})
            });
        } catch (error) { toast(error.message); }
    });
    el.abort_benchmark.addEventListener("click", async () => {
        try { await requestJson("/api/digiflot/performance/benchmark/abort", {method:"POST"}); }
        catch (error) { toast(error.message); }
    });
}

function connect() {
    const source = new EventSource("/api/digiflot/performance/stream");
    source.addEventListener("performance", event => {
        try { render(JSON.parse(event.data)); } catch (error) { console.error(error); }
    });
    source.onerror = () => { source.close(); setTimeout(connect, 1500); };
}

async function init() {
    cache(); bind(); await refresh(); connect();
    setInterval(() => { if (latest?.state !== "Running") refresh(); }, 5000);
}

document.addEventListener("DOMContentLoaded", init);
