/* Idle HIFIE selection must not touch the running experiment state. */
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const ui=fs.readFileSync("src/ui/js/sensors.js","utf8");
const api=fs.readFileSync("src/api/vision.py","utf8");
const service=fs.readFileSync("src/lib/vision/service.py","utf8");
assert.match(ui,/state\.standaloneHifie=await requestJson\("\/api\/vision\/virtual-sensors\/froth-interface\/standalone"/);
assert.match(ui,/state\.maintenanceMode\s*\? "Saved benchmark is available for future experiments/);
assert.match(api,/@router\.put\("\/virtual-sensors\/froth-interface\/standalone"\)/);
assert.match(service,/def select_standalone_hifie\(/);
assert.match(service,/def _standalone_hifie_active\(/);
new vm.Script(ui);
console.log("Standalone HIFIE source checks passed");
