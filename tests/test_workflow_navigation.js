// Browser-independent checks for review vs. mutation in the calibration workflow.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const read = name => fs.readFileSync(path.join(__dirname,"../",name),"utf8");
const run = read("src/ui/js/run.js"), sensors = read("src/ui/js/sensors.js");
const sensorHtml = read("src/ui/html/sensors.html"), cameraHtml = read("src/ui/html/config_camera.html");

const edit = run.slice(run.indexOf('const sensorButton = event.target.closest("[data-edit-sensor]")'),
    run.indexOf('ui.select_physical_cell.addEventListener'));
assert.match(edit,/window\.location\.href = "\/sensors\?review="/);
assert.doesNotMatch(edit,/\/calibration\/sensors\/[^\n]*\/reopen/, "Review cannot reopen calibration");
assert.match(run,/data-edit-camera[^\n]*Recalibrate/, "Camera state change must be explicit");
assert.match(sensorHtml,/id="cancel_calibration_edit"/);
assert.match(cameraHtml,/id="cancel_camera_recalibration"/);
assert.match(sensors,/\/api\/digiflot\/calibration\/cancel/);

const start = sensors.indexOf("function calibrationMarkup(snapshot) {");
const end = sensors.indexOf("\nfunction sensorCard(snapshot)",start);
assert.ok(start>=0 && end>start);
const ctx = vm.createContext({
    state:{digiflot:{state:"Ready"},calibrationMode:false,maintenanceMode:false},
    calibrationItem:()=>({status:"passed",mode:"ph_points",chip_points:2,requested_points:2}),
    escapeHtml:value=>String(value), standaloneCalibrationMarkup:()=>"<unexpected/>"
});
const markup = vm.runInContext(sensors.slice(start,end)+
    '\ncalibrationMarkup({id:"pH1",type:"ph",status:"connected"});',ctx);
assert.match(markup,/Calibration review \(read-only\)/);
assert.match(markup,/data-sensor-id="pH1"/);
assert.match(markup,/>Recalibrate</);
assert.doesNotMatch(markup,/ph-calibrate|standalone-ph-calibrate/,
    "Review must not expose writes to an Atlas EZO circuit");

assert.match(sensors,/await refreshDigiFlotState\(\);\s*renderCards\(\);\s*showToast\("Recalibration started/);
console.log("Workflow navigation and read-only review checks passed");
