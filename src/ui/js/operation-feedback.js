/* Global API operation feedback. No polling, no dependencies, and no extra sensor work. */
(() => {
    "use strict";
    if (window.DigiFlotOperations) return;
    const originalFetch = window.fetch.bind(window);
    const tabId = (window.crypto?.randomUUID?.() || "tab-" + Date.now() + "-" + Math.random().toString(36).slice(2));
    const passive = /\/(?:monitor|stream|diagnostics|preview\/stop|storage\/estimate|performance\/evaluate|performance\/virtual-workload)(?:\/|$)/;
    const current = {count:0, exclusive:0, anchor:null, clickedAt:0, panel:null, text:null, timer:null, slow:null};
    let leaseTimer = null, ownedPreview = null;

    function ensurePanel() {
        if (current.panel || !document.body) return;
        const panel = document.createElement("div");
        panel.id = "app_operation_feedback";
        panel.className = "app-operation-feedback";
        panel.setAttribute("role", "status");
        panel.setAttribute("aria-live", "polite");
        panel.innerHTML = '<span class="operation-spinner" aria-hidden="true"></span><span class="operation-message"></span><button class="operation-dismiss" type="button" aria-label="Dismiss message">×</button>';
        document.body.appendChild(panel);
        panel.querySelector(".operation-dismiss").addEventListener("click", () => panel.classList.remove("visible"));
        current.panel = panel;
        current.text = panel.querySelector(".operation-message");
    }
    function notice(message, error=false, persist=false) {
        ensurePanel();
        if (!current.panel) return;
        current.panel.classList.toggle("error", error);
        current.panel.classList.toggle("working", !error && current.count > 0);
        current.text.textContent = message;
        current.panel.classList.add("visible");
        clearTimeout(current.timer);
        if (!persist) current.timer = setTimeout(() => {
            if (!current.count) current.panel?.classList.remove("visible");
        }, error ? 7500 : 2000);
    }
    function targetLabel(element, path) {
        if (/\/preview\/start$/.test(path)) return "Starting camera preview";
        if (/\/exposure\/calibrate$/.test(path)) return "Calibrating camera exposure";
        if (/\/detection-roi-preview$/.test(path)) return "Loading rectified camera plane";
        if (/\/rectified$/.test(path)) return "Processing rectified camera image";
        if (/\/benchmark$/.test(path)) return "Testing Froth Interface detection and timing";
        if (/\/performance\/benchmark\/start$/.test(path)) return "Starting system performance test";
        const label = element?.getAttribute("aria-label") || element?.textContent?.trim();
        if (label && label.length <= 70) return label;
        const part = path.split("/").filter(Boolean).slice(-2).join(" ").replaceAll("-", " ");
        return part ? part.charAt(0).toUpperCase() + part.slice(1) : "Processing request";
    }
    function mark(target, active) {
        if (!target || !target.isConnected || !("disabled" in target)) return;
        if (active) {
            target.dataset.operationPending = "true";
            target.dataset.operationWasDisabled = String(target.disabled);
            target.disabled = true;
            target.setAttribute("aria-busy", "true");
        } else if (target.dataset.operationPending === "true") {
            target.disabled = target.dataset.operationWasDisabled === "true";
            target.removeAttribute("aria-busy");
            delete target.dataset.operationPending;
            delete target.dataset.operationWasDisabled;
        }
    }
    function startLease() {
        if (leaseTimer) clearInterval(leaseTimer);
        leaseTimer = setInterval(async () => {
            if (!ownedPreview) return;
            try {
                const response = await originalFetch("/api/cameras/preview/heartbeat", {
                    method:"POST", headers:{"X-DigiFlot-Tab-Id":tabId}, cache:"no-store"
                });
                if (!response.ok) {
                    ownedPreview = null;
                    clearInterval(leaseTimer);
                    notice("Camera preview is no longer owned by this tab. Reload calibration.", true);
                }
            } catch (_) { /* Lost connection: the server lease will expire safely. */ }
        }, 8000);
    }
    document.addEventListener("click", event => {
        const target = event.target?.closest?.("button,input[type=submit],a.button");
        if (!target) return;
        if (current.exclusive > 0 && target.getAttribute("data-operation-allow") !== "true") {
            event.preventDefault();
            event.stopImmediatePropagation();
            notice("An operation is still running. Other changes are temporarily blocked.", false, true);
            return;
        }
        current.anchor = target;
        current.clickedAt = performance.now();
    }, true);
    window.addEventListener("pagehide", () => {
        if (!ownedPreview) return;
        const path = "/api/cameras/preview/stop?tab_id=" + encodeURIComponent(tabId);
        if (navigator.sendBeacon) navigator.sendBeacon(path, new Blob([], {type:"text/plain"}));
    });

    async function wrappedFetch(input, init={}) {
        const raw = typeof input === "string" ? input : input?.url;
        const url = new URL(raw || "/", location.href);
        if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) return originalFetch(input, init);
        const method = String(init.method || input?.method || "GET").toUpperCase();
        const headers = new Headers(init.headers || input?.headers);
        headers.set("X-DigiFlot-Tab-Id", tabId);
        const options = {...init, headers};
        const modifying = !["GET","HEAD","OPTIONS"].includes(method);
        const foreground = modifying && !passive.test(url.pathname);
        const clicked = performance.now()-current.clickedAt < 1000 ? current.anchor : null;
        const cameraRead = !modifying && url.pathname.endsWith("/detection-roi-preview");
        const foregroundRead = cameraRead || (!modifying && clicked &&
            /\/(?:snapshot|rectified|calibration|profile)(?:\/|$)/.test(url.pathname));
        const tracked = foreground || foregroundRead;
        // The ROI snapshot is cancellable and modal-local: never block the
        // entire page or its Close button while a rectified image loads.
        const exclusive = foreground;
        if (exclusive && current.exclusive) {
            notice("Finish the current operation before starting another.", false, true);
            throw new Error("Another operation is still running; wait for its result.");
        }
        let label = null;
        if (tracked) {
            current.count++;
            if (exclusive) current.exclusive++;
            label = targetLabel(clicked, url.pathname);
            mark(clicked, true);
            notice(label + "…");
            clearTimeout(current.slow);
            current.slow = setTimeout(() => {
                if (current.count) notice(cameraRead ? "Loading the camera plane. You can close calibration at any time." : label + " is still processing. Please do not retry.", false, true);
            }, 4000);
        }
        try {
            const response = await originalFetch(input, options);
            const diagnosticStart = url.pathname === "/api/vision/virtual-sensors/froth-interface/diagnostics"
                && (() => {try {return JSON.parse(options.body || "{}").enabled === true;} catch (_) {return false;}})();
            if ((url.pathname.match(/^\/api\/cameras\/\d+\/preview\/start$/) ||
                    url.pathname === "/api/vision/virtual-sensors/froth-interface/detection-roi-preview" ||
                    diagnosticStart) && response.ok) {
                ownedPreview = true;
                startLease();
            } else if (url.pathname === "/api/cameras/preview/stop" && response.ok) {
                ownedPreview = null;
                if (leaseTimer) clearInterval(leaseTimer);
            }
            if (response.status === 409 || (tracked && response.status >= 500)) {
                const body = await response.clone().json().catch(() => ({}));
                const detail = String(body.detail || "A conflicting operation is active");
                notice(response.status === 409 ? detail + " Check the other calibration tab." : detail, true, true);
            }
            return response;
        } catch (error) {
            if (tracked && error.name !== "AbortError") notice("Request failed: " + error.message, true, true);
            throw error;
        } finally {
            if (tracked) {
                current.count=Math.max(0,current.count-1);
                if (exclusive) current.exclusive=Math.max(0,current.exclusive-1);
                mark(clicked, false);
                clearTimeout(current.slow);
                if (!current.count && !current.panel?.classList.contains("error")) {
                    current.panel?.classList.remove("working");
                    current.timer=setTimeout(() => current.panel?.classList.remove("visible"), 800);
                }
            }
        }
    }
    window.fetch = wrappedFetch;
    window.DigiFlotOperations = {notice, tabId, pending:()=>current.exclusive>0};
})();
