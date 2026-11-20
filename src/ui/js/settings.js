const state = { settings: null, discovery: null };
const el = Object.fromEntries([
    "settings_state", "auto_advance_enabled", "transition_timeout_s", "scraping_interval", "scraping_method",
    "scraping_alerts_enabled", "scraping_alert_style", "scraping_gpio_pin", "scraping_gpio_pin_field", "scraping_gpio_warning",
    "save_performance", "telemetry_interval_s", "idle_telemetry_interval_s", "min_disk_free_gb", "storage_safety_margin_pct",
    "save_settings", "auto_advance_hint", "server_ip", "server_id", "server_name", "server_token",
    "server_status", "server_runtime_error", "server_restart_notice", "save_server", "autodetect", "save_devices",
    "camera_devices", "scale_devices", "atlas_devices", "bronkhorst_devices", "wago_devices", "discovery_errors", "restart_notice", "restart_program",
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
        bronkhorst: (configured.bronkhorst || []).map(config => ({
            port: config.port, configured: true, detected: null, name: config.name, config,
        })),
        wago: (configured.wago || []).map(config => ({
            port: config.port, configured: true, detected: null, name: config.name, config,
        })),
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
    if (!item.configured || !["scale", "atlas", "bronkhorst", "wago"].includes(kind)) return true;
    return item.config?.enabled !== false;
}

function genericDeviceStatus(kind, item) {
    if (!sensorEnabled(kind, item)) return ["Disabled", "disabled"];
    if (item.configured && item.detected === null) return ["Configured / not scanned", "unknown"];
    if (item.configured && item.runtime_status === "unconfigured") return ["Register map required", "unknown"];
    if (item.configured && item.detected) return ["Configured", "configured"];
    if (item.configured && !item.detected) return ["Configured / offline", "offline"];
    if (item.detected) return ["Detected", "new"];
    if (item.configurable) return ["Unverified serial port", "unknown"];
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
    if (!item.configured || !["scale", "atlas", "bronkhorst", "wago"].includes(kind)) return "";
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

function row(kind, item, label, detail, selectable = true, controls = "") {
    const [status, cls] = deviceStatus(kind, item);
    const key = kind === "camera" ? item.id :
        ["scale", "bronkhorst", "wago"].includes(kind) ? item.port : item.address;
    const canSelect = Boolean(selectable && !item.configured && (item.detected || item.configurable));
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
                ${controls}
            </span>
            <span class="device-status ${cls}">${esc(status)}</span>
        </div>`;
}

function scaleIdentityControls(item) {
    if (item.configured) {
        if (!item.scale_detected || item.config?.connection) return "";
        return `<label class="scale-identity-controls"><input type="checkbox" class="remember-scale-connection"
            data-sensor-id="${esc(item.config?.id)}" checked> Remember this serial connection</label>`;
    }
    if (!item.scale_detected) return "";
    const offline = (state.discovery?.scales || []).filter(other =>
        other.configured && !other.scale_detected && other.config?.id);
    if (!offline.length) return "";
    const options = offline.map(other =>
        `<option value="${esc(other.config.id)}" ${offline.length === 1 ? "selected" : ""}>${esc(other.config.name || other.config.id)}${offline.length === 1 ? " (suggested)" : ""}</option>`).join("");
    return `<div class="scale-identity-controls">
        <label>Existing scale <select class="scale-reassignment" data-port="${esc(item.port)}">
            <option value="">Register as new scale</option>${options}</select></label>
        <label class="scale-confirm-label" hidden><input type="checkbox" class="scale-confirm">
            I verified this scale by changing its load and checking the new reading.</label>
    </div>`;
}

function processControls(kind, item) {
    if (kind === "wago" && (item.detected || item.configurable) && !item.configured) {
        const offline = (state.discovery?.wago || []).filter(candidate =>
            candidate.configured && !candidate.detected && candidate.config?.id);
        const options = offline.map(other => '<option value="' + esc(other.config.id) + '">' +
            esc(other.config.name || other.config.id) + '</option>').join("");
        const manual = item.configurable && !item.detected ?
            '<details><summary>RS-485 connection (not detected)</summary>' +
            '<label>Baud <select class="wago-baud"><option>9600</option><option>19200</option><option>38400</option><option>57600</option><option>115200</option></select></label>' +
            '<label>Parity <select class="wago-parity"><option>N</option><option>E</option><option>O</option></select></label>' +
            '<label>Modbus slave <input class="wago-slave" type="number" min="1" max="247" value="1"></label>' +
            '<small>Registration is unverified. Measurements remain unavailable until the correct manufacturer register map is configured.</small></details>' : '';
        return '<label class="sensor-enable-control"><input type="checkbox" class="wago-model-confirm">' +
            '<span>I verified this is a WAGO 879-1300 (Modbus alone does not identify the model)</span></label>' +
            (offline.length ? '<label>Identity <select class="wago-reassignment"><option value="">New meter</option>' +
                options + '</select></label>' : '') + manual;
    }
    if (kind === "bronkhorst" && item.configured)
        return '<label class="sensor-enable-control"><input type="checkbox" class="bronk-control-enabled" ' +
            'data-id="' + esc(item.config.id) + '" data-initial="' +
            Boolean(item.config.control_enabled) + '" ' + (item.config.control_enabled ? 'checked' : '') +
            '><span>Enable airflow control (after hardware verification)</span></label>';
    if (kind === "wago" && item.configured) {
        const registers = JSON.stringify(item.config.registers || {}, null, 2);
        return '<details class="wago-register-details"><summary>Modbus registers (verified 879-1300 map)</summary>' +
            '<textarea class="wago-register-map" data-id="' + esc(item.config.id) + '" rows="6" spellcheck="false">' +
            esc(registers) + '</textarea><small>Read-only register map in JSON. Do not use registers from other WAGO models without verification.</small></details>';
    }
    return "";
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
            scaleIdentityControls(item),
        );
    }).join("") || '<p class="muted">No configured scales. Run auto-detect to scan serial devices.</p>';

    el.atlas_devices.innerHTML = (discovery.atlas || []).map(item => row(
        "atlas",
        item,
        item.config?.name || item.name || item.type || `0x${Number(item.address).toString(16)}`,
        `Address ${item.address} · ${item.type || "EZO"}`,
        true,
    )).join("") || '<p class="muted">No configured Atlas sensors. Run auto-detect to scan known EZO addresses.</p>';

    for (const kind of ["bronkhorst", "wago"]) {
        const host = el[kind + "_devices"];
        if (!host) continue;
        host.innerHTML = (discovery[kind] || []).map(item => {
            const detail = [item.port, kind === "bronkhorst" ?
                [item.model, item.device_serial, item.unit].filter(Boolean).join(" · ") :
                (item.evidence || "Modbus RTU · RS-485"),
                item.error].filter(Boolean).join(" · ");
            return row(kind, item, item.config?.name || item.name ||
                (kind === "bronkhorst" ? "Bronkhorst MFC" : "Modbus device (model unverified)"),
                detail, true, processControls(kind, item));
        }).join("") || '<p class="muted">No configured devices. Use Auto-detect to scan serial interfaces.</p>';
    }

    const errors = discovery.errors || [];
    el.discovery_errors.hidden = !errors.length;
    el.discovery_errors.innerHTML = errors.map(item =>
        `<div><strong>${esc(item.source)}</strong>: ${esc(item.error)}</div>`
    ).join("");

    updateSaveButton();
}

function updateSaveButton() {
    const linkSelectors = [...document.querySelectorAll(".scale-reassignment")];
    linkSelectors.forEach(select => {
        const card = select.closest(".device-row"), active = Boolean(select.value);
        const box = card?.querySelector(".device-select");
        if (box) {
            if (active) box.checked = false;
            box.disabled = active;
            card.dataset.selectable = String(!active);
        }
        const confirmation = card?.querySelector(".scale-confirm-label");
        if (confirmation) confirmation.hidden = !active;
        if (!active && confirmation) confirmation.querySelector("input").checked = false;
    });
    const selected = [...document.querySelectorAll(".device-select:checked")];
    const sensorStateChanged = [...document.querySelectorAll(".sensor-enabled, .bronk-control-enabled")].some(box =>
        box.checked !== (box.dataset.initial === "true"));
    const invalidRegisters = [...document.querySelectorAll(".wago-register-map")].some(box => {
        try {
            const map = JSON.parse(box.value || "{}");
            return map === null || Array.isArray(map) || typeof map !== "object";
        } catch (_) { return true; }
    });
    const changedRegisters = [...document.querySelectorAll(".wago-register-map")].some(box => {
        try {
            const next = JSON.stringify(JSON.parse(box.value || "{}"));
            const item = (state.discovery?.wago || []).find(v => String(v.config?.id) === box.dataset.id);
            return next !== JSON.stringify(item?.config?.registers || {});
        } catch (_) { return true; }
    });
    const remembered = [...document.querySelectorAll(".remember-scale-connection:checked")];
    const assigned = linkSelectors.filter(select => select.value);
    const confirmed = assigned.filter(select => select.closest(".device-row")?.querySelector(".scale-confirm:checked"));
    const uniqueTargets = new Set(assigned.map(select => select.value)).size === assigned.length;
    const wagoUnchecked = [...document.querySelectorAll(".device-row:has(.device-select[data-kind='wago']:checked)")].some(
        card => !card.querySelector(".wago-model-confirm:checked"));
    const incomplete = confirmed.length !== assigned.length || !uniqueTargets ||
        wagoUnchecked || invalidRegisters;
    el.save_devices.disabled = incomplete ||
        !(selected.length || sensorStateChanged || changedRegisters || remembered.length || confirmed.length);
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
        bronkhorst: [],
        wago: [],
        control_changes: [],
        register_updates: [],
        atlas_bus: state.discovery?.atlas_bus ?? 1,
        sensor_enabled: { scales: [], atlas: [], bronkhorst: [], wago: [] },
        reassignments: [],
        remember_connections: [],
    };

    document.querySelectorAll(".device-select:checked").forEach(box => {
        const kind = box.dataset.kind;
        const key = box.dataset.key;
        const list = kind === "camera"
            ? state.discovery.cameras
            : kind === "scale" ? state.discovery.scales :
              kind === "atlas" ? state.discovery.atlas : state.discovery[kind];
        const item = list.find(value => String(
            kind === "camera" ? value.id :
                ["scale", "bronkhorst", "wago"].includes(kind) ? value.port : value.address
        ) === String(key));
        if (item) {
            const keyName = kind === "camera" ? "cameras" : kind === "scale" ? "scales" : kind;
            const card = box.closest(".device-row");
            out[keyName].push(kind === "wago" ? {...item,
                confirmed_model: Boolean(card?.querySelector(".wago-model-confirm:checked")),
                reassign_id: card?.querySelector(".wago-reassignment")?.value || null,
                manual_setup: Boolean(item.configurable && !item.detected),
                baudrate: Number(card?.querySelector(".wago-baud")?.value || item.baudrate || 9600),
                parity: card?.querySelector(".wago-parity")?.value || item.parity || "N",
                slave_id: Number(card?.querySelector(".wago-slave")?.value || item.slave_id || 1)} : item);
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
            out.sensor_enabled.atlas.push({address: Number(box.dataset.address), enabled: box.checked});
        } else if (["bronkhorst", "wago"].includes(box.dataset.kind)) {
            out.sensor_enabled[box.dataset.kind].push({id: box.dataset.id, enabled: box.checked});
        }
    });

    document.querySelectorAll(".bronk-control-enabled").forEach(box =>
        out.control_changes.push({id: box.dataset.id, control_enabled: box.checked}));
    document.querySelectorAll(".wago-register-map").forEach(box => {
        const value = JSON.parse(box.value || "{}");
        out.register_updates.push({id: box.dataset.id, registers: value});
    });

    document.querySelectorAll(".scale-reassignment").forEach(select => {
        if (!select.value) return;
        const confirmed = Boolean(select.closest(".device-row")?.querySelector(".scale-confirm:checked"));
        out.reassignments.push({ sensor_id: select.value, port: select.dataset.port, confirmed });
    });
    document.querySelectorAll(".remember-scale-connection:checked").forEach(box =>
        out.remember_connections.push(box.dataset.sensorId));

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
    if (!card || card.dataset.selectable !== "true" ||
        event.target.closest(".scale-identity-controls, details, .sensor-enable-control") ||
        event.target.matches("input, label, select, textarea, summary, span.sensor-enable-control")) return;
    const checkbox = card.querySelector(".device-select");
    if (!checkbox || checkbox.disabled) return;
    checkbox.checked = !checkbox.checked;
    checkbox.dispatchEvent(new Event("change", { bubbles: true }));
});

document.addEventListener("change", event => {
    if (["device-select", "sensor-enabled", "scale-reassignment", "scale-confirm",
        "bronk-control-enabled", "wago-model-confirm",
        "remember-scale-connection"].some(cls => event.target.classList?.contains(cls))) {
        updateSaveButton();
    }
});
document.addEventListener("input", event => {
    if (event.target.classList?.contains("wago-register-map")) updateSaveButton();
});

el.save_devices.addEventListener("click", async () => {
    let payload;
    try { payload = selectedHardware(); }
    catch (error) { toast("Invalid register map JSON: " + error.message, 4500); return; }
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

// Optional plugins are managed separately; no native device is moved to a plugin.
let activeSettingsTab = "general";

function showSettingsTab(tab, updateHash = true) {
    activeSettingsTab = tab === "plugins" ? "plugins" : "general";
    for (const name of ["general", "plugins"]) {
        const selected = name === activeSettingsTab;
        document.getElementById("settings_" + name).hidden = !selected;
        const button = document.getElementById("settings_tab_" + name);
        button.setAttribute("aria-selected", String(selected));
        button.tabIndex = selected ? 0 : -1;
    }
    if (updateHash) history.replaceState(null, "", activeSettingsTab === "plugins" ? "#plugins" : "#general");
    if (activeSettingsTab === "plugins") refreshPlugins().catch(error => toast(error.message, 5000));
}

async function refreshPlugins() {
    const target = document.getElementById("plugin_list");
    const result = await json("/api/digiflot/plugins", {cache: "no-store"});
    const idle = result.state === "Idle";
    target.innerHTML = (result.plugins || []).map(item => {
        const pending = item.enabled !== item.loaded;
        const status = item.error ? "Error" : pending ? "Restart required" :
            item.loaded ? "Running" : "Disabled";
        const display = (item.display || []).map(component => component.type + ": " + component.label).join(" · ");
        return `<article class="plugin-row">
            <div class="plugin-info">
                <div class="plugin-title"><strong>${esc(item.name)}</strong>
                    <span class="device-status ${item.loaded ? "configured" : "disabled"}">${esc(status)}</span></div>
                <small>${esc(item.id)}${item.version ? " · v" + esc(item.version) : ""}</small>
                <p>${esc(item.description || "No description supplied.")}</p>
                <div class="plugin-meta"><span>Calibration: ${esc(item.calibration)}</span>
                    <span>Display: ${esc(display || "Generic sensor card")}</span></div>
                ${item.error ? `<p class="plugin-error">${esc(item.error)}</p>` : ""}
            </div>
            <label class="plugin-switch">
                <span>${item.enabled ? "Enabled" : "Disabled"}</span>
                <input class="plugin-enabled" type="checkbox" data-plugin-id="${esc(item.id)}"
                    ${item.enabled ? "checked" : ""} ${!idle || (item.error && !item.enabled) ? "disabled" : ""}>
            </label>
        </article>`;
    }).join("") || '<p class="muted">No plugins installed. Add one in src/plugins/.</p>';
    const pending = (result.plugins || []).some(item => item.enabled !== item.loaded);
    document.getElementById("plugins_notice").hidden = !pending;
    document.getElementById("plugins_restart").hidden = !pending || !idle;
    document.getElementById("plugins_restart").disabled = !idle;
    window.DigiFlotIcons?.decorate(document.getElementById("settings_plugins"));
}

document.querySelectorAll("[data-settings-tab]").forEach(button =>
    button.addEventListener("click", () => showSettingsTab(button.dataset.settingsTab)));
document.getElementById("plugins_refresh").addEventListener("click", () =>
    refreshPlugins().catch(error => toast(error.message, 5000)));
document.getElementById("plugins_restart").addEventListener("click", () => el.restart_program.click());

document.getElementById("plugin_list").addEventListener("change", async event => {
    const box = event.target.closest(".plugin-enabled");
    if (!box) return;
    const enabled = box.checked;
    box.disabled = true;
    try {
        await json("/api/digiflot/plugins/" + encodeURIComponent(box.dataset.pluginId) + "/enabled", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({enabled}),
        });
        await load(false);
        await refreshPlugins();
        toast(enabled ? "Plugin enabled. Restart required." : "Plugin disabled. Restart required.");
    } catch (error) {
        box.checked = !enabled;
        toast(error.message, 5000);
        await refreshPlugins().catch(() => {});
    } finally { box.disabled = false; }
});

load(true).then(() => showSettingsTab(location.hash === "#plugins" ? "plugins" : "general", false))
    .catch(error => toast(error.message, 5000));
