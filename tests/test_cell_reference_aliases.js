/* Legacy Cell Top/Bottom aliases stay addressable but do not clutter Cells selectors. */
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const ui=fs.readFileSync("src/ui/js/cells.js","utf8");
const start=ui.indexOf("  function referenceDisplayModel("),end=ui.indexOf("  function renderCellDimensionPairs(){",start);
assert.ok(start>0&&end>start,"referenceDisplayModel helper must exist");
const helper=ui.slice(start,end);
const base=[
    {id:"outlet_level",name:"Outlet level",type:"custom",position_cm:[0,0]},
    {id:"cell_top",name:"Cell top",type:"top",position_cm:[0,3]},
    {id:"cell_bottom",name:"Cell bottom",type:"bottom",position_cm:[0,15]},
    {id:"legacy_top",name:"Cell Top",type:"top",position_cm:[0,3]},
    {id:"legacy_bottom",name:"Cell Bottom",type:"bottom",position_cm:[0,15]},
    {id:"left",name:"Left Corner",type:"custom",position_cm:[-4,9]},
];
const run=points=>vm.runInNewContext(helper+"\nreferenceDisplayModel(points);",{points});
const display=run(base);
assert.equal(display.visible.length,4,"collapse physically identical names");
assert.equal(display.aliases.get("legacy_top"),"cell_top");
assert.equal(display.aliases.get("legacy_bottom"),"cell_bottom");
assert.equal(display.canonicalId("legacy_top"),"cell_top");
assert.equal(display.canonicalId("left"),"left");
assert.equal(base.length,6,"never modify saved reference identities");
const different=base.map(x=>({...x,position_cm:x.position_cm&&[...x.position_cm]}));
different[3].position_cm[1]=5;
const conflict=run(different);
assert.equal(conflict.canonicalId("legacy_top"),"legacy_top");
assert.ok(conflict.label(different[3]).includes("legacy · distinct position"));
assert.equal(conflict.visible.length,5,"keep conflicting physical positions available");
new vm.Script(ui);
console.log("Reference alias selector migration checks passed.");
