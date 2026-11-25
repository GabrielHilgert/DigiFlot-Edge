/* Visual physical point editor, no-ArUco metric fallback and shape tool semantics. */
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const js=fs.readFileSync("src/ui/js/cells.js","utf8");
const html=fs.readFileSync("src/ui/html/cells.html","utf8");
function extract(start,end){const a=js.indexOf(start),b=js.indexOf(end,a+start.length);
  assert.ok(a>=0&&b>a,"Cannot find function "+start);return js.slice(a,b);}
for(const id of ["cv_add_point_tool","cv_point_modal","cv_point_name","cv_point_type","cv_point_direction",
  "cv_point_save","cv_point_reposition","cv_quick_refs","cv_shape_draw","cv_shape_save","cv_shape_type",
  "cv_shape_name","cv_shape_anchor","cv_shape_axis","cv_shape_list","cv_shape_overlay"])
  if(id==="cv_shape_overlay")assert.ok(js.includes("id='cv_shape_overlay'"));
  else assert.ok(html.includes('id="'+id+'"'),"Missing "+id);
assert.ok(js.includes("renderQuickReferences()"));
assert.ok(js.includes("openPointEditor(null,p,'measure')"),"Picking an empty area must offer naming a point.");
assert.ok(js.includes("action(()=>openPointEditor(point))()"),"Existing point must open the editor.");
assert.ok(js.includes("action(()=>openPointEditor(null,p))()"),"Empty camera click must create an editor draft.");
assert.ok(js.includes("point.position_cm=planePoint(position)"));
assert.ok(js.includes("reference-observations/"),"Non-ArUco camera observations remain independent.");
assert.ok(js.includes("state.visualShapes.items"),"Shape objects are independent from named points.");
const fn=extract("  function constrainShapePoints(","\n  function drawWorkspaceShapes()");
const context={$:id=>id==="camera_image"?{naturalWidth:800,naturalHeight:600}:{}};
const points=vm.runInNewContext(fn+"\nconstrainShapePoints([[.2,.2],[.6,.5]],'square')",context);
assert.ok(Math.abs((points[1][0]-points[0][0])*800-(points[1][1]-points[0][1])*600)<1e-8);
const source={value:"1"},destination={value:"2"},reference={value:"width_mm",
  selectedOptions:[{textContent:"Width"}]},target={value:"depth_mm"};
const elements={cv_relative_source:source,cv_relative_destination:destination,
  cv_relative_reference:reference,cv_relative_target:target};
const flowState={cellId:"cell_1",cell:{resolved_dimensions:{dimensions:{
  width_mm:{value_mm:160,source:"nominal"}}}},relativeSourceCm:[],relativeSourcePoints:[],
  relativeSourceMode:null,relativePairs:{reference:[],target:[]}};
const flowContext={state:flowState,$:id=>elements[id],switchRelativeCamera:async()=>{throw Error("No saved ArUco plane");},
  openBestCamera:async()=> "raw",setWorkspaceTool:()=>{},text:()=>{},toast:()=>{}};
const flow=extract("  async function pickRelativeSource(){","\n  async function pickRelativeDestination(which){");
vm.runInNewContext(flow+"\npickRelativeSource()",flowContext).then(()=>{
  assert.equal(flowState.relativeSourceLengthMm,160);
  assert.equal(flowState.relativeSourceMode,"resolved_dimension");
  assert.equal(flowState.relativeSourceCameraId,"1");
  assert.equal(flowState.relativeDestinationCameraId,"2");
  console.log("Cells point editor, shape constraints and unmarked camera fallback passed.");
}).catch(err=>{console.error(err);process.exitCode=1;});
