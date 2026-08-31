const state = { discovery: null };
const el = Object.fromEntries([
    "settings_state", "auto_advance_enabled", "transition_timeout_s", "scraping_interval", "scraping_method",
    "save_settings", "auto_advance_hint", "autodetect", "save_devices", "camera_devices", "scale_devices",
    "atlas_devices", "discovery_errors", "restart_notice", "toast"
].map(id => [id, document.getElementById(id)]));

function esc(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

async function json(url, options = {}) {
    const response = await fetch(url, options);
    let payload = null;
    try { payload = await response.json(); } catch (_) {}
    if (!response.ok) {
        throw new Error(payload?.detail || `${response.status} ${response.statusText}`);
    }
    return payload;
}

function toast(message) {
    el.toast.textContent = message;
    el.toast.classList.add("show");
    clearTimeout(toast.t);
    toast.t = setTimeout(() => el.toast.classList.remove("show"), 3000);
}

function updateAutoHint() {
    el.transition_timeout_s.disabled = !el.auto_advance_enabled.checked;
    el.auto_advance_hint.textContent = el.auto_advance_enabled.checked
        ? "After a stage ends, the next stage starts automatically after this delay unless the operator starts it sooner or pauses."
        : "Automatic advance is disabled. Transitions wait indefinitely for the operator to start the next stage.";
}

async function load() {
    const payload = await json("/api/digiflot/settings");
    el.settings_state.textContent = payload.state || "Idle";
    const orchestration = payload.orchestration || {};
    el.auto_advance_enabled.checked = Boolean(orchestration.auto_advance_enabled);
    el.transition_timeout_s.value = orchestration.transition_timeout_s ?? 30;
    el.scraping_interval.value = orchestration.scraping_interval ?? 5;
    el.scraping_method.value = orchestration.scraping_method || "audio";
    updateAutoHint();
}

function genericDeviceStatus(item) {
    if (item.configured && item.detected) return ["Configured", "configured"];
    if (item.configured && !item.detected) return ["Configured / offline", "offline"];
    if (item.detected) return ["Detected", "new"];
    return ["Unavailable", "offline"];
}

function scaleDeviceStatus(item) {
    if (item.configured && item.scale_detected) return ["Configured / scale online", "configured"];
    if (item.configured && item.serial_detected) return ["Configured / unconfirmed", "unknown"];
    if (item.configured) return ["Configured / offline", "offline"];
    if (item.scale_detected) return ["Scale detected", "new"];
    if (item.serial_detected) return ["Serial device / unknown", "unknown"];
    return ["Unavailable", "offline"];
}

function deviceStatus(kind, item) {
    return kind === "scale" ? scaleDeviceStatus(item) : genericDeviceStatus(item);
}

function row(kind, item, label, detail, selectable = true) {
    const [status, cls] = deviceStatus(kind, item);
    const key = kind === "camera" ? item.id : kind === "scale" ? item.port : item.address;
    const canSelect = Boolean(selectable && !item.configured && item.detected);
    const selection = canSelect
        ? `<input class="device-select" data-kind="${kind}" data-key="${esc(key)}" type="checkbox" aria-label="Select ${esc(label)}">`
        : `<span class="device-marker" aria-hidden="true">${item.configured ? "✓" : "·"}</span>`;
    const hint = canSelect ? `<small class="device-select-hint">Click card to select</small>` : "";

    return `
        <div class="device-row${canSelect ? " device-row-selectable" : ""}" data-selectable="${canSelect ? "true" : "false"}">
            ${selection}
            <span class="device-copy">
                <strong>${esc(label)}</strong>
                <small>${esc(detail)}</small>
                ${hint}
            </span>
            <span class="device-status ${cls}">${esc(status)}</span>
        </div>`;
}

function render() {
    const discovery = state.discovery;
    if (!discovery) return;

    el.camera_devices.innerHTML = (discovery.cameras || []).map(item => row(
        "camera",
        item,
        item.config?.name || item.model || `Camera ${item.id}`,
        `${item.sensor_resolution?.join(" × ") || "Resolution unknown"}${item.max_fps ? ` · max ${Number(item.max_fps).toFixed(1)} fps` : ""}`,
        true,
    )).join("") || '<p class="muted">No cameras detected.</p>';

    el.scale_devices.innerHTML = (discovery.scales || []).map(item => {
        const details = [item.description || "Serial device"];
        if (item.sample) details.push(item.sample);
        if (item.evidence) details.push(item.evidence);
        return row(
            "scale",
            item,
            item.config?.name || item.port,
            details.join(" · "),
            Boolean(item.scale_detected),
        );
    }).join("") || '<p class="muted">No serial devices detected.</p>';

    el.atlas_devices.innerHTML = (discovery.atlas || []).map(item => row(
        "atlas",
        item,
        item.config?.name || item.name || item.type || `0x${Number(item.address).toString(16)}`,
        `Address ${item.address} · ${item.type || "EZO"}`,
        true,
    )).join("") || '<p class="muted">No Atlas EZO sensors detected at known addresses.</p>';

    const errors = discovery.errors || [];
    el.discovery_errors.hidden = !errors.length;
    el.discovery_errors.innerHTML = errors.map(item =>
        `<div><strong>${esc(item.source)}</strong>: ${esc(item.error)}</div>`
    ).join("");

    updateSaveButton();
}

function updateSaveButton() {
    const selected = document.querySelectorAll(".device-select:checked");
    el.save_devices.disabled = selected.length === 0;
    document.querySelectorAll(".device-row-selectable").forEach(card => {
        const checkbox = card.querySelector(".device-select");
        card.classList.toggle("selected", Boolean(checkbox?.checked));
        const hint = card.querySelector(".device-select-hint");
        if (hint) hint.textContent = checkbox?.checked ? "Selected" : "Click card to select";
    });
}

function selected() {
    const out = { cameras: [], scales: [], atlas: [], atlas_bus: state.discovery?.atlas_bus ?? 1 };
    document.querySelectorAll(".device-select:checked").forEach(box => {
        const kind = box.dataset.kind;
        const key = box.dataset.key;
        const list = kind === "camera"
            ? state.discovery.cameras
            : kind === "scale"
                ? state.discovery.scales
                : state.discovery.atlas;
        const item = list.find(value => String(
            kind === "camera" ? value.id : kind === "scale" ? value.port : value.address
        ) === String(key));
        if (item) {
            out[kind === "camera" ? "cameras" : kind === "scale" ? "scales" : "atlas"].push(item);
        }
    });
    return out;
}

el.auto_advance_enabled.addEventListener("change", updateAutoHint);

el.save_settings.addEventListener("click", async () => {
    el.save_settings.disabled = true;
    try {
        await json("/api/digiflot/settings", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                auto_advance_enabled: el.auto_advance_enabled.checked,
                transition_timeout_s: Number(el.transition_timeout_s.value),
                scraping_interval: Number(el.scraping_interval.value),
                scraping_method: el.scraping_method.value,
            }),
        });
        toast("Settings saved.");
    } catch (error) {
        toast(error.message);
    } finally {
        el.save_settings.disabled = false;
    }
});

el.autodetect.addEventListener("click", async () => {
    el.autodetect.disabled = true;
    el.autodetect.textContent = "Detecting…";
    try {
        state.discovery = await json("/api/digiflot/devices/discover", { method: "POST" });
        render();
        toast("Device scan complete.");
    } catch (error) {
        toast(error.message);
    } finally {
        el.autodetect.disabled = false;
        el.autodetect.textContent = "Auto-detect devices";
    }
});

document.addEventListener("click", event => {
    const card = event.target.closest(".device-row-selectable");
    if (!card || event.target.matches("input")) return;
    const checkbox = card.querySelector(".device-select");
    if (!checkbox) return;
    checkbox.checked = !checkbox.checked;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
});

document.addEventListener("change", event => {
    if (event.target.classList?.contains("device-select")) {
        updateSaveButton();
    }
});

el.save_devices.addEventListener("click", async () => {
    const payload = selected();
    el.save_devices.disabled = true;
    try {
        const result = await json("/api/digiflot/devices/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        el.restart_notice.hidden = !result.restart_required;
        toast(result.changed ? "Device configuration saved." : "No device configuration change was needed.");
        state.discovery = await json("/api/digiflot/devices/discover", { method: "POST" });
        render();
    } catch (error) {
        toast(error.message);
    } finally {
        if (state.discovery) render();
    }
});

load().catch(error => toast(error.message));
