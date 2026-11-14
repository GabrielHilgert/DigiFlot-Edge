// A single calibration screen owns the live sensor streams and HIFIE camera.
// Hardware-independent regression for workflow routing and camera request order.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path");
const read=name=>fs.readFileSync(path.join(__dirname,"..",name),"utf8");
const app=read("src/app.py"),runHtml=read("src/ui/html/run.html"),run=read("src/ui/js/run.js");
const sensorsHtml=read("src/ui/html/sensors.html"),sensors=read("src/ui/js/sensors.js");
const vision=read("src/lib/vision/service.py");

assert.match(app,/if digiflot\.state == digiflot\.SENSOR_CALIBRATION:\s*return RedirectResponse\(url="\/sensors\?calibration=1", status_code=303\)/);
assert.doesNotMatch(runHtml,/id="sensor_list"|Open sensor calibration/);
assert.match(run,/if \(state\.state === "SensorCalibration"\) \{[\s\S]*?window\.location\.replace\("\/sensors\?calibration=1"\)/);
assert.match(sensorsHtml,/id="sensor_grid"/);
assert.match(sensorsHtml,/id="virtual_panel"/);
assert.match(sensorsHtml,/id="finish_calibration"/);
assert.match(sensors,/state\.digiflot = await requestJson\("\/api\/digiflot\/calibration\/sensors\/complete"/);
assert.match(sensors,/workflowLink\.href=state\.calibrationMode \? "\/cells" : "\/run"/);

// Initial snapshot must finish before background lores diagnostics can claim the camera.
const modal=sensors.slice(sensors.indexOf("async function openVirtualCalibration()"),
    sensors.indexOf("async function virtualSaveConfiguration()"));
assert.ok(modal.includes("await loadVirtualRoiPlane()"));
assert.ok(modal.includes("await startVirtualDiagnostics()"));
assert.ok(modal.indexOf("await loadVirtualRoiPlane()") < modal.indexOf("await startVirtualDiagnostics()"));
assert.doesNotMatch(modal,/void loadVirtualRoiPlane\(\)/);

// Subsequent manual refresh and modal close also quiesce the live request first.
const refresh=sensors.slice(sensors.indexOf('document.getElementById("virtual_roi_refresh").addEventListener'),
    sensors.indexOf('document.getElementById("virtual_roi_reset").addEventListener'));
assert.ok(refresh.indexOf("await stopVirtualDiagnostics()") < refresh.indexOf("await loadVirtualRoiPlane()"));
assert.ok(refresh.indexOf("await loadVirtualRoiPlane()") < refresh.indexOf("await startVirtualDiagnostics()"));
assert.match(sensors,/const pending=virtualDiagRequest;[\s\S]*?if\(pending\)await pending\.catch/);
assert.match(sensors,/virtualRoiController\?\.abort\(\)/);

// Camera owns one stable lores stream; modal and sensor never resize it.
assert.match(vision,/self\._roi_snapshot_lock = threading\.Lock\(\)/);
assert.match(vision,/with self\._roi_snapshot_lock:/);
const plane=vision.slice(vision.indexOf("def virtual_detection_roi_preview("),vision.indexOf("def rectified_snapshot("));
const live=vision.slice(vision.indexOf("def diagnostic_preview("),vision.indexOf("def _virtual_context(",vision.indexOf("def diagnostic_preview(")));
for (const entry of [plane,live]) {
    assert.match(entry,/self\.digiflot\.start_preview\(camera\.id, owner_id=owner_id\)/);
    assert.doesNotMatch(entry,/camera\.analysis_target_size\s*=/);
}
assert.doesNotMatch(vision.slice(vision.indexOf("def ensure_live_preview("),vision.indexOf("def _loop(")),/camera\.analysis_target_size\s*=/);
console.log("Single-page sensor calibration and serialized HIFIE camera startup passed");
