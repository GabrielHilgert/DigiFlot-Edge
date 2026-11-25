/* Camera-first metrology, progressive shape marking, source view preference. */
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const js=fs.readFileSync("src/ui/js/cells.js","utf8");
const html=fs.readFileSync("src/ui/html/cells.html","utf8");
for(const id of ["cv_metrology_details","cv_metrology_mount","cv_marking_guide","cv_marking_title",
 "cv_marking_progress","cv_marking_instruction","cv_marking_cancel","cv_shape_method",
 "cv_shape_edge","cv_shape_finish","cv_shape_undo","cv_shape_progress"])
  assert.ok(html.includes('id="'+id+'"'),"Missing "+id);
assert.ok(js.includes("metrology.append(accordion('Reference-based physical dimensions'"));
assert.ok(js.includes("metrology.append(accordion('Relative scale between cameras'"));
assert.ok(js.includes("metrology.append($('cv_outlines_details'))"));
assert.ok(js.includes("await openBestCamera(camera,{focus:true})"));
assert.ok(js.includes("await openBestCamera(cameraId,{requireMetric:rectified,focus:true})"));
assert.ok(js.includes("...(!requireMetric?['raw']:[])"));
assert.ok(js.includes("state.shapePoints.push(picked)"));
assert.ok(js.includes("state.shapeDone=true;updateShapeReadout()"));
assert.ok(js.includes("const label=create('text'"),"Click markers must be numbered");
assert.ok(js.includes("state.relativePairs={reference:[],target:[]}"),"Clear incompatible pixel pairs");
assert.ok(!js.includes("state.measurePoints=[];state.relativePairs={reference:[],target:[]};\n    state.shapePoints=[]"),
  "showImage must not silently erase the current marks");
const fn=js.slice(js.indexOf("  function shapeInputCount("),js.indexOf("\n  function renderShapeList(){"));
const context={};
vm.runInNewContext(fn+"\nresult=[shapeVertices([[.2,.2],[.6,.3],[.5,.7]],'rectangle','three_corners'),"+
  "shapeVertices([[.6,.3],[.7,.6],[.4,.7],[.3,.4]],'rectangle','four_faces'),"+
  "shapeVertices([[.1,.2],[.7,.2],[.6,.7]],'polygon','vertices'),shapeInputCount('vertices')]",context);
assert.equal(context.result[0].length,4);
assert.ok(Math.abs(context.result[0][3][0]-.1)<1e-8);
assert.equal(context.result[1].length,4);
assert.ok(Math.abs(context.result[1][0][0]-.8)<1e-8);
assert.equal(context.result[2].length,3);
assert.equal(context.result[3],Infinity);
console.log("Progressive rotated/polygon shapes and camera-centric marking controls passed.");
