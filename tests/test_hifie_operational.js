// HIFIE branding, optional-sensor Skip and compact operational layout regression.
const assert=require("node:assert/strict"), fs=require("node:fs"), path=require("node:path"), vm=require("node:vm");
const read=file=>fs.readFileSync(path.join(__dirname,"..",file),"utf8");
const run=read("src/ui/js/run.js"), runHtml=read("src/ui/html/run.html"), runCss=read("src/ui/css/run.css");
const expHtml=read("src/ui/html/experiments.html"), expCss=read("src/ui/css/experiments.css"), expJs=read("src/ui/js/experiments.js");
const settingsHtml=read("src/ui/html/settings.html"), settingsCss=read("src/ui/css/settings.css");
const digiflot=read("src/lib/digiflot.py"), vision=read("src/lib/vision/service.py");

// Timeline remains a sibling before live sensors (not trapped inside the narrow run sidebar).
const timeline=runHtml.indexOf('id="run_stage_overview"'), sensors=runHtml.indexOf('id="live_sensor_panel"');
const sidebar=runHtml.indexOf('id="run_panel"');
assert.ok(timeline>0 && timeline<sensors && sensors<sidebar);
assert.match(runCss,/grid-template-areas:"timeline timeline" "sensors action" "sensors acquisition"/);
assert.match(runCss,/\.run-workspace\.is-dashboard\.acquisition-expanded\s*\{\s*grid-template-areas:"timeline timeline"/);
assert.match(run,/ui\.run_stage_overview\.hidden\s*=\s*false/);
assert.match(run,/ui\.run_stage_overview, ui\.run_panel/);
assert.match(runCss,/#run_stage_overview\[hidden\]/);
assert.match(runCss,/\.run-actions \[hidden\] \{ display:none !important;/);

// The compact card keeps essentials; technical metadata remains available separately.
const start=run.indexOf("function compactStageParameters("),end=run.indexOf("function renderCalibrationReview(",start);
assert.ok(start>0&&end>start);
const ctx=vm.createContext({escapeHtml:value=>String(value)});
const fn=vm.runInContext(run.slice(start,end)+"\ncompactStageParameters;",ctx);
const summary=fn({id:"id-123",type:"conditioning",duration:10,airflow:0,rotor_speed:700,ph:7,auto_name:true});
for(const value of ["Type","Airflow","Target pH","Rotor speed"])assert.ok(summary.includes(value),value);
for(const value of ["Stage ID","Attempt","Planned duration","Auto name","id-123"])assert.ok(!summary.includes(value),value);
assert.match(runHtml,/id="stage_technical_details"/);
assert.match(runCss,/\.stage-technical-details/);
assert.match(runCss,/transition-countdown strong \{ font-size:1\.45rem/);
assert.match(run,/toLowerCase\(\) !== "conditioning"/);
assert.match(run,/ui\.active_view\.classList\.toggle\("no-scraping"/);

// Stable internal ID, user-facing HIFIE label, and a working skip action.
assert.match(digiflot,/"id": "froth_interface", "name": "HIFIE \| Froth Interface Detection"/);
assert.match(digiflot,/self\.sensor_calibration\["froth_interface"\]\["name"\] = "HIFIE \| Froth Interface Detection"/);
assert.match(vision,/"id": "froth_interface", "name": "HIFIE \| Froth Interface Detection"/);
assert.match(runHtml,/data-step="froth"[^>]*>[\s\S]*?<strong>HIFIE<\/strong>/);
assert.match(run,/data-skip-sensor/);
assert.match(run,/api\/digiflot\/calibration\/sensors\//);
assert.match(run,/Skip HIFIE calibration for this execution/);

// Settings uses a real two-row grid and independent Disabled, Audio, GPIO signals.
assert.match(settingsHtml,/class="settings-grid orchestration-grid"/);
assert.match(settingsCss,/grid-template-areas:"advance delay interval output" "alert display gpio gpio"/);
assert.match(settingsHtml,/<option value="disabled">Disabled \(visual alert only\)<\/option>/);
assert.match(digiflot,/method not in \{"disabled", "audio", "gpio"\}/);

// Experiments remain searchable while the catalog scrolls and details open modally.
assert.match(expCss,/\.experiments-card \.table-frame\s*\{[\s\S]*?max-height:min\(61vh,680px\)/);
assert.match(expCss,/\.experiments-card \.experiment-table thead th\s*\{[\s\S]*?position:sticky/);
assert.match(expHtml,/<dialog id="experiment_details_dialog"/);
assert.match(expHtml,/id="close_detail_dialog"/);
assert.match(expJs,/elements\.detailDialog\.showModal\(\)/);
assert.match(expJs,/elements\.detailDialog\.close\(\)/);
console.log("HIFIE operational UI, settings and modal catalog regressions passed");
