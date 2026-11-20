/* Shared declarative plugin displays for Sensors, calibration and Run. */
(() => {
    const escapeHtml = value => String(value ?? "").replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;").replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;").replaceAll("'", "&#39;");

    function render(snapshot, context = "sensors") {
        if (snapshot?.type !== "plugin_sensor" || !Array.isArray(snapshot.display)) return "";
        const content = snapshot.display.map(item => {
            if (!item || !["metric", "gauge"].includes(item.type)) return "";
            const value = Number(snapshot.channels?.[item.key]);
            const available = snapshot.channels?.[item.key] != null && Number.isFinite(value);
            const precision = Math.max(0, Math.min(5, Number(item.decimals ?? 1) || 0));
            const number = available ? value.toFixed(precision) : "—";
            const label = escapeHtml(item.label || item.key), unit = escapeHtml(item.unit || "");
            if (item.type === "metric") return `<div class="plugin-display-metric">
                <span>${label}</span><strong>${number}${available && unit ? " " + unit : ""}</strong></div>`;
            const min = Number(item.min ?? 0), max = Number(item.max ?? 100);
            const validRange = Number.isFinite(min) && Number.isFinite(max) && max > min;
            const percent = validRange && available ? Math.min(100, Math.max(0, (value - min) / (max - min) * 100)) : 0;
            return `<div class="plugin-display-gauge">
                <div><span>${label}</span><strong>${number}${available && unit ? " " + unit : ""}</strong></div>
                <div class="plugin-display-track" role="meter" aria-label="${label}"
                    aria-valuemin="${validRange ? min : 0}" aria-valuemax="${validRange ? max : 100}"
                    ${available && validRange ? 'aria-valuenow="' + value + '"' : ""}>
                    <span style="width:${percent.toFixed(2)}%"></span></div></div>`;
        }).join("");
        if (!content) return "";
        return `<div class="plugin-display plugin-display-${escapeHtml(context)}">${content}</div>`;
    }
    window.DigiFlotPluginDisplays = Object.freeze({render});
})();
