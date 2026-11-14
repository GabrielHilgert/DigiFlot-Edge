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

// Server serializes canceled/reopened ROI requests; camera configuration is
// completed before a preview is started on either API route.
assert.match(vision,/self\._roi_snapshot_lock = threading\.Lock\(\)/);
assert.match(vision,/with self\._roi_snapshot_lock:/);
const plane=vision.slice(vision.indexOf("def virtual_detection_roi_preview("),vision.indexOf("def rectified_snapshot("));
assert.ok(plane.indexOf("camera.analysis_target_size = self._desired_lores_size") < plane.indexOf("self.digiflot.start_preview"));
const live=vision.slice(vision.indexOf("def diagnostic_preview("),vision.indexOf("def _virtual_context(",vision.indexOf("def diagnostic_preview(")));
assert.ok(live.indexOf("camera.analysis_target_size = self._desired_lores_size") < live.indexOf("self.digiflot.start_preview"));
console.log("Single-page sensor calibration and serialized HIFIE camera startup passed");
