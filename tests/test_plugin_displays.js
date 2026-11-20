const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const window = {};
vm.runInNewContext(fs.readFileSync("src/ui/js/plugin-displays.js", "utf8"), {window});

const sensor = {
    type: "plugin_sensor", channels: {temperature_c: 21.25, signal_pct: 75},
    display: [{type: "metric", key: "temperature_c", label: "Temperature", unit: "°C", decimals: 2},
              {type: "gauge", key: "signal_pct", label: "Signal", unit: "%", min: 0, max: 100}]
};
const display = window.DigiFlotPluginDisplays;
const sensors = display.render(sensor, "sensors");
const calibration = display.render(sensor, "calibration");
const run = display.render(sensor, "run");
for (const content of [sensors, calibration, run]) {
    assert.match(content, /21.25/);
    assert.match(content, /75.0 %/);
    assert.match(content, /width:75.00%/);
}
assert.match(calibration, /plugin-display-calibration/);
assert.match(run, /plugin-display-run/);
const untrusted = {...sensor, display: [{type: "metric", key: "temperature_c",
    label: '<script>alert("x")</script>', unit: "<img>"}]};
assert.doesNotMatch(display.render(untrusted, "sensors"), /<script>|<img>/);
assert.match(display.render(untrusted, "sensors"), /&lt;script&gt;/);
assert.equal(display.render({type: "scale", display: sensor.display}), "");
console.log("Plugin display rendering passed.");
