/* Interactive HIFIE tuning must be camera-free, unsaved and available before ROI setup. */
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const read=pathName=>fs.readFileSync(path.join(__dirname,"..",pathName),"utf8");
const html=read("src/ui/html/sensors.html"),js=read("src/ui/js/sensors.js");
const backend=read("src/lib/vision/service.py"),api=read("src/api/vision.py");
const interfaceCode=read("src/lib/virtual_sensors/interface.py");
const temporal=read("src/lib/virtual_sensors/temporal.py");
assert.ok(html.indexOf('class="virtual-tuning"') < html.indexOf('class="virtual-diagnostics"'));
assert.ok(html.indexOf('id="virtual_camera_step"') < html.indexOf('class="virtual-roi-config"'));
assert.ok(html.indexOf('class="virtual-roi-config"') < html.indexOf('class="virtual-tuning"'));
assert.ok(html.indexOf('id="virtual_detector_step"') < html.indexOf('class="virtual-diagnostics"'));
assert.match(js,/void loadVirtualRoiPlane\(\)\.then/);
assert.doesNotMatch(js.slice(js.indexOf("async function startVirtualDiagnostics()"),
    js.indexOf("function stopVirtualDiagnostics()")),/await virtualRoiTask/);
for(const id of ["virtual_quick_fields","virtual_tuning_status","virtual_reference_target",
    "virtual_fit_parameters","virtual_fit_thresholds","virtual_fit_status"])assert.match(html,new RegExp('id="'+id+'"'));
assert.match(js,/function virtualQuickSlider\(/);
assert.match(js,/function scheduleVirtualTuning\(/);
assert.match(js,/function virtualMarkReference\(/);
assert.match(js,/async function virtualFitParameters\(/);
assert.match(js,/temporal_prior_rows_px/);
assert.match(js,/ctx\.setLineDash\(\[3,5\]\)/);
assert.match(js,/virtualTuningEpoch/);
assert.match(js,/const config=virtualCollectInputs\(\)|config=virtualCollectInputs\(\)/);
assert.match(backend,/def preview_virtual_tuning\(/);
assert.match(backend,/def fit_virtual_tuning\(/);
assert.match(backend,/self\._tuning_frame = \{"image": transformed\.copy\(\)/);
assert.match(backend,/cached = self\._reference_frame/);
assert.match(backend,/str\(owner_id\) != owner/);
assert.doesNotMatch(backend.slice(backend.indexOf("def _tuning_input("),
    backend.indexOf("def _reference_rows(")),/self\._diagnostic_until|self\._diagnostic_owner_id|received_at/);
assert.match(backend,/def release_virtual_reference\(/);
assert.match(backend,/result\["reference_ready"\] = frozen is not None/);
assert.match(js,/if\(virtualTuningTask\)/);
assert.match(js,/await virtualTuningTask\.catch/);
assert.match(js,/function captureVirtualReference\(/);
assert.match(html,/id="virtual_reference_capture"/);
assert.match(api,/froth-interface\/tune-preview/);
assert.match(api,/froth-interface\/tune-fit/);
assert.match(backend,/if not self\._tuning_lock\.acquire\(blocking=False\):/);
assert.match(interfaceCode,/"temporal_filter": "off"/);
assert.match(interfaceCode,/temporal_state\.apply/);
assert.match(temporal,/mode == "vote_prior"/);
const preview=backend.slice(backend.indexOf("def preview_virtual_tuning("),backend.indexOf("def fit_virtual_tuning("));
for(const forbidden of ["capture_analysis_frame","start_preview","_capture(","save_virtual_profile("])
    assert.ok(!preview.includes(forbidden),"Preview must not "+forbidden);
const fit=backend.slice(backend.indexOf("def fit_virtual_tuning("),backend.indexOf("def diagnostic_preview(",backend.indexOf("def fit_virtual_tuning(")));
for(const forbidden of ["start_preview","capture_analysis_frame","save_virtual_profile("])
    assert.ok(!fit.includes(forbidden),"Fit must not "+forbidden);
const options={};
for(const method of ["dual_entropy_hybrid","mean_derivative"]){
    const context={virtualDraft:{method},virtualQuickSpecs:{}};
    vm.runInNewContext(js.slice(js.indexOf("function virtualQuickKeys()"),js.indexOf("function virtualQuickSlider("))+
        "\nvirtualQuickKeys",context);
    const list=context.virtualQuickKeys();
    assert.ok(list.includes("resolution_px")&&list.includes("temporal_strength"));
    assert.ok(list.includes(method==="mean_derivative"?"entropy_bins":"dual_entropy_bins"));
    assert.equal(list.includes("vote_sigma_px"),method==="dual_entropy_hybrid");
}
console.log("HIFIE cached-frame sliders, temporal prior and conservative reference fit wiring passed");
