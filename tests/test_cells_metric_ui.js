/* Cells point snapping, projected distance and relative source camera flow. */
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const js=fs.readFileSync("src/ui/js/cells.js","utf8");
const html=fs.readFileSync("src/ui/html/cells.html","utf8");
function extract(start,end){const a=js.indexOf(start),b=js.indexOf(end,a+start.length);
  assert.ok(a>=0&&b>a,"Missing "+start+" / "+end);return js.slice(a,b);}
for(const id of ["cv_measure_axis","cv_measure_from","cv_measure_to","cv_relative_source_axis",
  "cv_relative_pick_source","cv_relative_destination","cv_relative_reference_axis",
  "cv_relative_target_axis","cv_camera_calibration_details","cv_camera_accordion_mount"])
  assert.ok(html.includes('id="'+id+'"'),"Missing "+id);
assert.ok(js.includes("calibrationPanel.classList.remove('card','cv-workspace-panel')"));
assert.ok(js.includes("accordion('ArUco / planar calibration & analysis ROI'"));
assert.ok(js.includes("accordion('Relative scale between cameras'"));
assert.ok(js.includes("cv_metrology_mount"));
assert.ok(js.includes("accordion('Reference-based physical dimensions'"));
assert.ok(js.includes("state.measurePointIds")&&js.includes("nearestReferenceOnImage(p)"));
assert.ok(!js.includes("measured_width_a"),"Direct measurements must not create redundant physical points.");
assert.ok(js.includes("switchRelativeCamera(source,true)"),"Known length must open calibrated source camera.");
assert.ok(js.includes("switchRelativeCamera(destination,false)"),"Target step must switch to uncalibrated destination.");
const projection=extract("  function projectedMetricValue(","\n  function updateMeasurementPreview()");
const obj=vm.runInNewContext(projection+"\n({h:projectedMetricValue([2,3],[8,11],'horizontal'),"+
  "v:projectedMetricValue([2,3],[8,11],'vertical'),d:projectedMetricValue([2,3],[8,11],'direct')})");
assert.equal(obj.h,60);assert.equal(obj.v,80);assert.equal(obj.d,100);
const refs={cv_measure_from:{value:""},cv_measure_to:{value:""}},state={uiTool:"measure",measurePointIds:[]};
const context={state,$:id=>refs[id],nearestReferenceOnImage:p=>({id:p[0]===.1?"cell_top":"cell_bottom",point:p}),
  updateMeasurementPreview:()=>{},updateMarkingGuide:()=>{},text:()=>{},drawWorkspaceMeasurements:()=>{},relativeReadout:()=>{}};
vm.runInNewContext(extract("  function captureWorkspacePoint(","\n  function setCellForm(")+
  "\ncaptureWorkspacePoint([.1,.2]);captureWorkspacePoint([.8,.7]);",context);
assert.deepEqual(state.measurePointIds,["cell_top","cell_bottom"]);
assert.equal(refs.cv_measure_from.value,"cell_top");
assert.equal(refs.cv_measure_to.value,"cell_bottom");
const controls={cv_relative_source:{value:"1"},cv_relative_destination:{value:"2"},
  cv_relative_reference:{value:"width_mm"},cv_relative_target:{value:"depth_mm"},
  cv_relative_source_status:{textContent:""},cv_relative_readout:{textContent:""}};
const trace=[],flowState={cameraId:2,frame:null,view:"raw",imageSpace:"raw",relativeSourceCm:[],
  relativeSourcePoints:[],relativePairs:{reference:[],target:[]},relativeSourceCameraId:null};
const flowContext={state:flowState,$:id=>controls[id],text:(id,value)=>{controls[id].textContent=value;},
  switchRelativeCamera:async(id,rectified)=>{trace.push([String(id),rectified]);
    flowState.cameraId=Number(id);flowState.view=rectified?"rectified":"raw";
    flowState.imageSpace=rectified?"raw":"undistorted";flowState.frame={};},
  setWorkspaceTool:mode=>{flowState.uiTool=mode;},drawWorkspaceMeasurements:()=>{}};
const flow=extract("  async function pickRelativeSource(){","\n  function relativeReadout(){");
(async()=>{
  const workflow=vm.runInNewContext(flow+"\n(async()=>{await pickRelativeSource();"+ 
    "state.relativeSourceCm=[[0,0],[10,0]];await pickRelativeDestination('relative_reference');})()",flowContext);
  await workflow;
  assert.deepEqual(trace,[["1",true],["2",false]]);
  assert.equal(flowState.uiTool,"relative_reference");
  assert.equal(flowState.relativeSourceCameraId,"1");
  assert.equal(flowState.relativeDestinationCameraId,"2");
  console.log("Cells axes, point reuse and source-to-destination switching passed.");
})().catch(error=>{console.error(error);process.exitCode=1;});
