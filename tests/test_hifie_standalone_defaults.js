/* HIFIE must automatically activate a valid last-used camera-cell pair on Idle. */
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const ui=fs.readFileSync("src/ui/js/sensors.js","utf8");
const service=fs.readFileSync("src/lib/vision/service.py","utf8");
const run=fs.readFileSync("src/lib/digiflot.py","utf8");
assert.match(ui,/state\.standaloneHifie\?\.suggested/);
assert.match(ui,/if\(suggestion\?\.ready && \(!active \|\| changed\)\)/);
assert.match(ui,/camera_id:suggestion\.camera_id/);
assert.match(ui,/info\.selected\|\|info\.suggested\|\|\{\}/);
assert.match(service,/def _suggest_standalone_hifie\(/);
assert.match(run,/last_used_camera_id.*chosen/);
new vm.Script(ui);
console.log("HIFIE last-used defaults UI checks passed.");
