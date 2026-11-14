// Regression: physical reference labels must follow image Y, not creation order.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const source = fs.readFileSync(path.join(__dirname, "../src/ui/js/sensors.js"), "utf8");
const start = source.indexOf("function drawVirtualRoiOverlay() {");
const end = source.indexOf("\nasync function loadVirtualRoiPlane()", start);
assert.ok(start >= 0 && end > start, "Detection ROI drawing function must be present");

const labels = [];
const ctx = {clearRect(){}, beginPath(){}, moveTo(){}, lineTo(){}, stroke(){},
    fillRect(){}, strokeRect(){}, rect(){}, fill(){}, setLineDash(){}, save(){}, restore(){},
    measureText:text=>({width:text.length*7}), fillText:(text,x,y)=>labels.push({text,y})};
const canvas = {getContext:()=>ctx};
const legend = {innerHTML:""};
const elements = {virtual_roi_canvas:canvas, virtual_show_grid:{checked:false},
    virtual_roi_reference_levels:legend};
const refs = [
    {id:"outlet_level", name:"Outlet level", y_cm:-3.19},
    {id:"aruco_reference", name:"ArUco reference", y_cm:14},
    {id:"cell_top", name:"Cell Top", y_cm:-7.48},
    {id:"cell_bottom", name:"Cell Bottom", y_cm:18.40}
];
const context = {document:{getElementById:id=>elements[id]}, virtualRoiPlane:{
    size:[460,500], plane:{min_xy_cm:[0,-12],max_xy_cm:[20,20]}},
    virtualProfileData:{reference_lines:refs,named_references:{default_reference_id:"cell_bottom"}},
    virtualDraft:{reference_id:"cell_bottom"}, virtualRoiDrag:null,
    virtualEffectiveRoi:()=>null, paletteColor:(name,fallback)=>fallback,
    escapeHtml:value=>String(value)};
vm.runInNewContext(source.slice(start,end)+"\ndrawVirtualRoiOverlay();", context);

assert.deepEqual(labels.map(item=>item.text.split(" · ")[0]),
    ["Cell Top","Outlet level","ArUco reference","Cell Bottom"]);
for(const point of refs) {
    const label = labels.find(item=>item.text.startsWith(point.name+" · "));
    const expected = (point.y_cm+12)/32*500;
    assert.ok(label && Math.abs(label.y-expected)<20,
        point.name+" label must stay close to its own physical line");
}
assert.match(legend.innerHTML,/Cell Top/);
console.log("Froth Detection ROI physical reference label positions passed");
