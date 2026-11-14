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
assert.match(js,/String\(snapshot\.type \|\| ""\)\.toLowerCase\(\) !== "ph"/);
assert.match(js,/if \(!snapshot \|\| String\(snapshot\.type \|\| ""\)\.toLowerCase\(\) !== "ph"\)/);
assert.match(js,/closeResolvedPhDialog\(button\.dataset\.sensorId\)/);
assert.match(js,/if \(sensor && String\(sensor\.type \|\| ""\)\.toLowerCase\(\) === "ph"\)/);
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
// Regression: calibration completion badges for scales and other non-pH sensors
// must remain in the card. pH uses a dialog but still shows a card status.
const vm=require("node:vm");
const begin=js.indexOf("function sensorCalibrationEntry(snapshot) {");
const end=js.indexOf("function sensorCard(snapshot) {",begin);
assert.ok(begin>=0 && end>begin);
const calibration={status:"passed",requested_points:2,points:{mid:{status:"passed"},low:{status:"passed"}}};
const context={state:{standaloneCalibration:new Map()},calibrationItem:()=>calibration,
    calibrationMarkup:()=>'<div class="calibration-block complete-block"><span class="calibration-pill passed">Passed</span></div>',
    escapeHtml:value=>String(value)};
const render=vm.runInNewContext(js.slice(begin,end)+"\nsensorCalibrationEntry;",context);
const scale=render({id:"scale1",type:"scale"});
assert.match(scale,/calibration-pill passed/);
assert.doesNotMatch(scale,/open-calibration-drawer/);
const ph=render({id:"ph1",type:"ph"});
assert.match(ph,/calibration-pill passed/);
assert.match(ph,/2\/2 calibration points completed/);
assert.match(ph,/open-calibration-drawer/);
const virtual=render({id:"froth_interface",type:"virtual_froth_interface"});
assert.doesNotMatch(virtual,/open-calibration-drawer/);
calibration.status="skipped";
assert.match(render({id:"ph1",type:"ph"}),/calibration-pill skipped/);
// Checklist results must remain visible in the card header after dialogs close.
assert.ok(js.includes('${calibrationIndicator(snapshot)}'));
assert.match(js, /class="sensor-card-badges"/);
assert.match(css, /\.calibration-indicator-checked/);
assert.match(css, /\.calibration-indicator-skipped/);
assert.match(css, /\.calibration-indicator-unavailable/);
assert.match(read("src/ui/js/icons.js"), /"circle-dashed"/);
context.state.calibrationMode=true;
context.state.digiflot={state:"SensorCalibration"};
const badge=vm.runInNewContext(js.slice(begin,end)+"\ncalibrationIndicator;",context);
calibration.status="passed";
assert.match(badge({id:"scale1",type:"scale"}), /data-calibration-status="checked"[\s\S]*data-icon="badge-check"/);
calibration.status="skipped";
assert.match(badge({id:"ph1",type:"ph"}), /data-calibration-status="skipped"[\s\S]*data-icon="skip-forward"/);
calibration.status="pending";
assert.match(badge({id:"froth_interface",type:"virtual_froth_interface"}), /data-calibration-status="pending"[\s\S]*data-icon="circle-dashed"/);
context.state.calibrationMode=false;
context.state.digiflot={state:"Ready"};
calibration.status="passed";
assert.match(badge({id:"scale1"}), /data-calibration-status="checked"/);
context.state.digiflot={state:"Idle"};
assert.equal(badge({id:"scale1"}),"");
console.log("Calibration modals, persistent status indicators and experiment styling passed");
