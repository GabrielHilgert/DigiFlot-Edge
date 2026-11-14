const state = { settings: null, discovery: null };
const el = Object.fromEntries([
    "settings_state", "auto_advance_enabled", "transition_timeout_s", "scraping_interval", "scraping_method",
    "scraping_alerts_enabled", "scraping_alert_style", "scraping_gpio_pin", "scraping_gpio_pin_field", "scraping_gpio_warning",
    "save_performance", "telemetry_interval_s", "idle_telemetry_interval_s", "min_disk_free_gb", "storage_safety_margin_pct",
    "save_settings", "auto_advance_hint", "server_ip", "server_id", "server_name", "server_token",
    "server_status", "server_runtime_error", "server_restart_notice", "save_server", "autodetect", "save_devices",
    "camera_devices", "scale_devices", "atlas_devices", "discovery_errors", "restart_notice", "restart_program",
    "restart_status", "toast"
].map(id => [id, document.getElementById(id)]));

function esc(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
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

function toast(message, duration = 3000) {
    el.toast.textContent = message;
    el.toast.classList.add("show");
    clearTimeout(toast.t);
    toast.t = setTimeout(() => el.toast.classList.remove("show"), duration);
}

function updateAutoHint() {
    el.transition_timeout_s.disabled = !el.auto_advance_enabled.checked;
    el.auto_advance_hint.textContent = el.auto_advance_enabled.checked
        ? "After a stage ends, the next stage starts automatically after this delay unless the operator starts it sooner or pauses."
        : "Automatic advance is disabled. Transitions wait indefinitely for the operator to start the next stage.";
}

const GPIO_PHYSICAL_PINS = {4:7,5:29,6:31,12:32,13:33,16:36,17:11,18:12,19:35,20:38,21:40,22:15,23:16,24:18,25:22,26:37,27:13};
function updateScrapingOptions() {
    const gpio = el.scraping_method.value === "gpio";
    el.scraping_gpio_pin_field.hidden = !gpio;
    el.scraping_gpio_warning.hidden = !gpio;
    el.scraping_alert_style.disabled = !el.scraping_alerts_enabled.checked;
}

function configuredDiscovery(payload) {
    const configured = payload.configured || {};
    const atlas = configured.atlas_scientific || {};
    return {
        cameras: (configured.cameras || []).map(config => ({
            id: config.id,
            configured: true,
            detected: null,
            sensor_resolution: null,
            max_fps: null,
            config,
        })),
        scales: (configured.scales || []).map(config => ({
            port: config.port,
            configured: true,
            detected: null,
            serial_detected: null,
            scale_detected: null,
            description: "Configured scale",
            config,
        })),
        atlas: (atlas.sensors || []).map(config => ({
            address: config.address,
            type: config.type,
            name: config.name,
            configured: true,
            detected: null,
            config,
        })),
        atlas_bus: atlas.bus ?? 1,
        errors: [],
        scanned: false,
    };
}

function updateRestartControls(payload) {
    const idle = (payload.state || "Idle") === "Idle";
    const supported = Boolean(payload.restart_supported);
    const required = Boolean(payload.restart_required);

    el.restart_program.disabled = !idle || !supported;
    el.restart_program.classList.toggle("restart-required", required);

    if (!supported) {
        el.restart_status.textContent = "Local restart is unavailable because DigiFlot is not running through the installed systemd service.";
    } else if (!idle) {
        el.restart_status.textContent = `Restart is disabled while DigiFlot state is ${payload.state}.`;
    } else if (required) {
        el.restart_status.textContent = "A saved configuration differs from the active runtime. Restart DigiFlot to apply it.";
    } else {
        el.restart_status.textContent = "The local service is ready to restart if needed.";
    }
}

function applySettings(payload, resetDiscovery = false) {
    state.settings = payload;
    el.settings_state.textContent = payload.state || "Idle";

    const orchestration = payload.orchestration || {};
    el.auto_advance_enabled.checked = Boolean(orchestration.auto_advance_enabled);
    el.transition_timeout_s.value = orchestration.transition_timeout_s ?? 30;
    el.scraping_interval.value = orchestration.scraping_interval ?? 5;
    el.scraping_method.value = orchestration.scraping_method || "audio";
    el.scraping_alerts_enabled.checked = orchestration.scraping_alerts_enabled !== false;
    el.scraping_alert_style.value = orchestration.scraping_alert_style || "fullscreen";
    const options = orchestration.scraping_gpio_options || Object.keys(GPIO_PHYSICAL_PINS).map(Number);
    el.scraping_gpio_pin.innerHTML = options.map(pin =>
        `<option value="${pin}">GPIO ${pin} · physical pin ${GPIO_PHYSICAL_PINS[pin] || "?"}</option>`).join("");
    el.scraping_gpio_pin.value = String(orchestration.scraping_gpio_pin ?? 17);
    updateAutoHint();
    updateScrapingOptions();

    const performance = payload.performance || {};
    el.telemetry_interval_s.value = performance.telemetry_interval_s ?? 10;
    el.idle_telemetry_interval_s.value = performance.idle_telemetry_interval_s ?? 30;
    el.min_disk_free_gb.value = performance.min_disk_free_gb ?? 2;
    el.storage_safety_margin_pct.value = performance.storage_safety_margin_pct ?? 30;

    const server = payload.server || {};
    el.server_ip.value = server.ip || "";
    el.server_id.value = server.id ?? "";
    el.server_name.value = server.name || "";
    el.server_token.value = "";
    el.server_token.placeholder = server.token_configured
        ? "Configured — leave blank to keep current token"
        : "Enter server token";
    el.server_status.textContent = server.runtime_status || "Unknown";
    el.server_runtime_error.hidden = !server.runtime_error;
    el.server_runtime_error.textContent = server.runtime_error
        ? `Central server connection: ${server.runtime_error}`
        : "";
    el.server_restart_notice.hidden = !server.restart_required;
    el.restart_notice.hidden = !payload.hardware_restart_required;

    updateRestartControls(payload);

    if (resetDiscovery || !state.discovery) {
        state.discovery = configuredDiscovery(payload);
        render();
    }
}

async function load(resetDiscovery = false) {
    const payload = await json("/api/digiflot/settings", { cache: "no-store" });
    applySettings(payload, resetDiscovery);
    return payload;
}

function sensorEnabled(kind, item) {
    if (!item.configured || !["scale", "atlas"].includes(kind)) return true;
    return item.config?.enabled !== false;
}

function genericDeviceStatus(kind, item) {
    if (!sensorEnabled(kind, item)) return ["Disabled", "disabled"];
    if (item.configured && item.detected === null) return ["Configured / not scanned", "unknown"];
    if (item.configured && item.detected) return ["Configured", "configured"];
    if (item.configured && !item.detected) return ["Configured / offline", "offline"];
    if (item.detected) return ["Detected", "new"];
    return ["Unavailable", "offline"];
}

function scaleDeviceStatus(item) {
    if (!sensorEnabled("scale", item)) return ["Disabled", "disabled"];
    if (item.configured && item.scale_detected === null) return ["Configured / not scanned", "unknown"];
    if (item.configured && item.scale_detected) return ["Configured / scale online", "configured"];
    if (item.configured && item.serial_detected) return ["Configured / unconfirmed", "unknown"];
    if (item.configured) return ["Configured / offline", "offline"];
    if (item.scale_detected) return ["Scale detected", "new"];
    if (item.serial_detected) return ["Serial device / unknown", "unknown"];
    return ["Unavailable", "offline"];
}

function deviceStatus(kind, item) {
    return kind === "scale" ? scaleDeviceStatus(item) : genericDeviceStatus(kind, item);
}

function sensorEnableControl(kind, item) {
    if (!item.configured || !["scale", "atlas"].includes(kind)) return "";
    const enabled = sensorEnabled(kind, item);
    const id = item.config?.id ?? "";
    const port = item.config?.port ?? item.port ?? "";
    const address = item.config?.address ?? item.address ?? "";
    return `
        <label class="sensor-enable-control">
            <input class="sensor-enabled"
                   data-kind="${kind}"
                   data-id="${esc(id)}"
                   data-port="${esc(port)}"
                   data-address="${esc(address)}"
                   data-initial="${enabled ? "true" : "false"}"
                   type="checkbox" ${enabled ? "checked" : ""}>
            <span>Enabled</span>
        </label>`;
}

function row(kind, item, label, detail, selectable = true) {
    const [status, cls] = deviceStatus(kind, item);
    const key = kind === "camera" ? item.id : kind === "scale" ? item.port : item.address;
    const canSelect = Boolean(selectable && !item.configured && item.detected);
    const selection = canSelect
        ? `<input class="device-select" data-kind="${kind}" data-key="${esc(key)}" type="checkbox" aria-label="Select ${esc(label)}">`
        : `<span class="device-marker" aria-hidden="true">${item.configured ? "✓" : "·"}</span>`;
    const hint = canSelect ? `<small class="device-select-hint">Click card to select</small>` : "";
    const enableControl = sensorEnableControl(kind, item);

    return `
        <div class="device-row${canSelect ? " device-row-selectable" : ""}" data-selectable="${canSelect ? "true" : "false"}">
            ${selection}
            <span class="device-copy">
                <strong>${esc(label)}</strong>
                <small>${esc(detail)}</small>
                ${hint}
                ${enableControl}
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
        item.detected === null
            ? `ID ${item.id} · not scanned`
            : `${item.sensor_resolution?.join(" × ") || "Resolution unknown"}${item.max_fps ? ` · max ${Number(item.max_fps).toFixed(1)} fps` : ""}`,
        true,
    )).join("") || '<p class="muted">No configured cameras. Run auto-detect to scan for cameras.</p>';

    el.scale_devices.innerHTML = (discovery.scales || []).map(item => {
        const details = [item.config?.id || item.description || "Serial device", item.port];
        if (item.sample) details.push(item.sample);
        if (item.evidence) details.push(item.evidence);
        return row(
            "scale",
            item,
            item.config?.name || item.port,
            details.filter(Boolean).join(" · "),
            Boolean(item.scale_detected),
        );
    }).join("") || '<p class="muted">No configured scales. Run auto-detect to scan serial devices.</p>';

    el.atlas_devices.innerHTML = (discovery.atlas || []).map(item => row(
        "atlas",
        item,
        item.config?.name || item.name || item.type || `0x${Number(item.address).toString(16)}`,
        `Address ${item.address} · ${item.type || "EZO"}`,
        true,
    )).join("") || '<p class="muted">No configured Atlas sensors. Run auto-detect to scan known EZO addresses.</p>';

    const errors = discovery.errors || [];
    el.discovery_errors.hidden = !errors.length;
    el.discovery_errors.innerHTML = errors.map(item =>
        `<div><strong>${esc(item.source)}</strong>: ${esc(item.error)}</div>`
    ).join("");

    updateSaveButton();
}

function updateSaveButton() {
    const selected = document.querySelectorAll(".device-select:checked");
    const sensorStateChanged = [...document.querySelectorAll(".sensor-enabled")].some(box =>
        box.checked !== (box.dataset.initial === "true")
    );
    el.save_devices.disabled = selected.length === 0 && !sensorStateChanged;

    document.querySelectorAll(".device-row-selectable").forEach(card => {
        const checkbox = card.querySelector(".device-select");
        card.classList.toggle("selected", Boolean(checkbox?.checked));
        const hint = card.querySelector(".device-select-hint");
        if (hint) hint.textContent = checkbox?.checked ? "Selected" : "Click card to select";
    });
}

function selectedHardware() {
    const out = {
        cameras: [],
        scales: [],
        atlas: [],
        atlas_bus: state.discovery?.atlas_bus ?? 1,
        sensor_enabled: { scales: [], atlas: [] },
    };

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

    document.querySelectorAll(".sensor-enabled").forEach(box => {
        if (box.dataset.kind === "scale") {
            out.sensor_enabled.scales.push({
                id: box.dataset.id || null,
                port: box.dataset.port || null,
                enabled: box.checked,
            });
        } else if (box.dataset.kind === "atlas") {
            out.sensor_enabled.atlas.push({
                address: Number(box.dataset.address),
                enabled: box.checked,
            });
        }
    });

    return out;
}

el.auto_advance_enabled.addEventListener("change", updateAutoHint);
el.scraping_method.addEventListener("change", updateScrapingOptions);
el.scraping_alerts_enabled.addEventListener("change", updateScrapingOptions);

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
                scraping_alerts_enabled: el.scraping_alerts_enabled.checked,
                scraping_alert_style: el.scraping_alert_style.value,
                scraping_gpio_pin: Number(el.scraping_gpio_pin.value),
            }),
        });
        await load(false);
        toast("Settings saved.");
    } catch (error) {
        toast(error.message);
    } finally {
        el.save_settings.disabled = false;
    }
});

el.save_performance.addEventListener("click", async () => {
    el.save_performance.disabled = true;
    try {
        const performance = {
            telemetry_interval_s: Number(el.telemetry_interval_s.value),
            idle_telemetry_interval_s: Number(el.idle_telemetry_interval_s.value),
            min_disk_free_gb: Number(el.min_disk_free_gb.value),
            storage_safety_margin_pct: Number(el.storage_safety_margin_pct.value),
        };
        for (const [key, value] of Object.entries(performance)) {
            if (!Number.isFinite(value) || el[key].value.trim() === "") {
                throw new Error("Please enter valid telemetry and storage values.");
            }
        }
        await json("/api/digiflot/settings", {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ performance }),
        });
        await load(false);
        toast("Telemetry settings saved.");
    } catch (error) {
        toast(error.message);
    } finally {
        el.save_performance.disabled = false;
    }
});

el.save_server.addEventListener("click", async () => {
    el.save_server.disabled = true;
    try {
        const token = el.server_token.value.trim();
        const rawId = el.server_id.value.trim();
        if (!rawId) throw new Error("Cell ID is required.");
        const server = {
            ip: el.server_ip.value.trim(),
            id: Number(rawId),
            name: el.server_name.value.trim(),
        };
        if (token) server.token = token;

        const result = await json("/api/digiflot/settings", {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ server }),
        });
        el.server_token.value = "";
        await load(false);
        el.server_restart_notice.hidden = !result.restart_required;
        toast(result.server_changed ? "Server configuration saved. Restart required." : "Server configuration is unchanged.");
    } catch (error) {
        toast(error.message, 4500);
    } finally {
        el.save_server.disabled = false;
    }
});

el.autodetect.addEventListener("click", async () => {
    el.autodetect.disabled = true;
    el.autodetect.textContent = "Detecting…";
    try {
        state.discovery = await json("/api/digiflot/devices/discover", { method: "POST" });
        state.discovery.scanned = true;
        render();
        toast("Device scan complete.");
    } catch (error) {
        toast(error.message, 4500);
    } finally {
        el.autodetect.disabled = false;
        el.autodetect.textContent = "Auto-detect devices";
        window.DigiFlotIcons?.enhance(el.autodetect);
    }
});

document.addEventListener("click", event => {
    const card = event.target.closest(".device-row-selectable");
    if (!card || event.target.matches("input, label, span.sensor-enable-control")) return;
    const checkbox = card.querySelector(".device-select");
    if (!checkbox) return;
    checkbox.checked = !checkbox.checked;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
});

document.addEventListener("change", event => {
    if (event.target.classList?.contains("device-select") || event.target.classList?.contains("sensor-enabled")) {
        updateSaveButton();
    }
});

el.save_devices.addEventListener("click", async () => {
    const payload = selectedHardware();
    el.save_devices.disabled = true;
    try {
        const result = await json("/api/digiflot/devices/save", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });
        el.restart_notice.hidden = !result.restart_required;
        toast(result.changed ? "Hardware configuration saved. Restart required." : "No hardware configuration change was needed.");
        await load(false);
        state.discovery = await json("/api/digiflot/devices/discover", { method: "POST" });
        state.discovery.scanned = true;
        render();
    } catch (error) {
        toast(error.message, 4500);
    } finally {
        if (state.discovery) render();
    }
});

async function waitForRestart() {
    let sawOffline = false;
    for (let attempt = 0; attempt < 50; attempt += 1) {
        await sleep(750);
        try {
            const response = await fetch("/health", { cache: "no-store" });
            if (!response.ok) throw new Error("health check failed");
            if (sawOffline || attempt >= 8) {
                window.location.reload();
                return;
            }
        } catch (_) {
            sawOffline = true;
        }
    }
    el.restart_program.disabled = false;
    el.restart_program.textContent = "Restart DigiFlot"; window.DigiFlotIcons?.enhance(el.restart_program);
    toast("Restart was requested, but the local server did not return in time.", 6000);
}

el.restart_program.addEventListener("click", async () => {
    if (!window.confirm("Restart the local DigiFlot program now?")) return;
    el.restart_program.disabled = true;
    el.restart_program.textContent = "Restarting…";
    try {
        await json("/api/digiflot/restart", { method: "POST" });
        toast("Restart requested. Waiting for DigiFlot…", 5000);
        await waitForRestart();
    } catch (error) {
        el.restart_program.disabled = false;
        el.restart_program.textContent = "Restart DigiFlot"; window.DigiFlotIcons?.enhance(el.restart_program);
        toast(error.message, 5000);
    }
});

load(true).catch(error => toast(error.message, 5000));
