/* Cells preserve nominal inputs and render physical measurements separately. */
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const ui=fs.readFileSync("src/ui/js/cells.js","utf8");
const html=fs.readFileSync("src/ui/html/cells.html","utf8");
const ref=fs.readFileSync("src/lib/vision/reference.py","utf8");
for(const id of ["cell_resolved_dimensions","cell_dimension_pairs","save_dimension_pairs","cell_height","cell_width","cell_depth","cell_volume_datum","cell_volume_points","save_volume_curve"])
    assert.match(html,new RegExp('id="'+id+'"'));
assert.ok(html.indexOf("Available physical properties")<html.indexOf("Nominal Parameters"));
assert.match(ui,/function renderCellResolvedDimensions\(/);
assert.match(ui,/function saveCellDimensionPairs\(/);
assert.match(ui,/function saveVolumeCurve\(/);
assert.match(ui,/state\.cell\?\.resolved_dimensions/);
assert.match(ui,/\['aruco_reference','outlet_level','cell_top','cell_bottom'\]/);
assert.match(ref,/FIXED_REFERENCE_IDS/);
new vm.Script(ui);
console.log("Cells physical geometry and nominal UI checks passed.");
