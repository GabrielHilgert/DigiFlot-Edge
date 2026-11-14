// Native calibration dialog regression without camera or DOM dependencies.
const assert=require("node:assert/strict"), fs=require("node:fs"), path=require("node:path");
const read=file=>fs.readFileSync(path.join(__dirname,"..",file),"utf8");
const html=read("src/ui/html/sensors.html"),js=read("src/ui/js/sensors.js"),
    css=read("src/ui/css/sensors.css"),experimentCss=read("src/ui/css/experiments.css");
assert.match(html,/<dialog id="calibration_drawer"[^>]*aria-labelledby="calibration_drawer_title"/);
assert.match(html,/<dialog id="virtual_panel"[^>]*aria-labelledby="virtual_calibration_title"/);
assert.match(html,/id="virtual_close"[^>]*>Close<\/button>/);
assert.match(html,/id="calibration_drawer_close"[^>]*>Close<\/button>/);
assert.doesNotMatch(html,/<section id="calibration_drawer"/);
assert.doesNotMatch(html,/<section id="virtual_panel"/);
assert.match(js,/if \(!panel\.open\) panel\.showModal\(\)/);
assert.match(js,/function sensorCalibrationEntry\(snapshot\)/);
assert.match(js,/host\.innerHTML = sensorCalibrationEntry\(snapshot\)/);
assert.match(js,/sensor\.type !== "virtual_froth_interface"/);
assert.match(js,/if \(!el\.calibrationDrawer\.open\) el\.calibrationDrawer\.showModal\(\)/);
assert.match(js,/virtualDialog\.addEventListener\("close", \(\) => stopVirtualDiagnostics\(\)\)/);
assert.match(js,/if \(event\.target === virtualDialog\) virtualDialog\.close\(\)/);
assert.match(js,/if \(event\.target === el\.calibrationDrawer\) el\.calibrationDrawer\.close\(\)/);
assert.match(js,/if\(!virtualDiagnosticsActive\|\|virtualDiagBusy\|\|document\.hidden\|\|!document\.getElementById\("virtual_panel"\)\.open\)return/);
assert.match(css,/\.calibration-modal:not\(\[open\]\)\s*\{ display:none !important; \}/);
assert.match(css,/\.calibration-modal::backdrop/);
assert.match(css,/\.virtual-panel\.calibration-modal/);
assert.match(experimentCss,/box-shadow:0 10px 32px rgba\(0,0,0,\.16\)/);
assert.match(experimentCss,/background:rgba\(8,16,24,\.32\)/);
assert.doesNotMatch(experimentCss,/25px 95px|backdrop-filter:blur\(3px\)/);
console.log("Calibration modals and subtle experiment dialog styling passed");
