/* HIFIE preview must visibly render independently of the live camera mode. */
const fs=require("node:fs"),assert=require("node:assert/strict"),vm=require("node:vm");
const js=fs.readFileSync("src/ui/js/sensors.js","utf8");
const html=fs.readFileSync("src/ui/html/sensors.html","utf8");
const css=fs.readFileSync("src/ui/css/sensors.css","utf8");

assert.match(js,/function scheduleVirtualTuning\([\s\S]*?virtualDiagnosticSource="reference";/);
assert.match(js,/virtualDiagnosticSource="reference";\s*if\(!renderVirtualDiagnostic\(data\.diagnostic/);
assert.match(js,/virtualDiagStopTask/);
assert.match(js,/Camera preview still busy/);
assert.match(js,/Recording and processing are being verified/);
for(const name of ["virtual_diagnostic_empty","virtual_diagnostic_grid","virtual_fit_parameters",
    "virtual_diagnostics_toggle"])assert.match(html,new RegExp('id="'+name+'"'));
assert.match(css,/\.virtual-diagnostic-grid\[hidden\]/);
assert.match(css,/display:none !important/);
assert.match(html,/Fit to marks/);
assert.match(html,/View live camera/);
assert.match(html,/Apply &amp; preview/);

const start=js.indexOf("function renderVirtualDiagnostic(");
const stop=js.indexOf("function renderVirtualTestTimeline",start);
assert.ok(start>0&&stop>start);
const source=js.slice(start,stop);
const createNode=()=>({hidden:true,src:"",textContent:"",innerHTML:"",
    style:{setProperty:()=>{}},querySelector:()=>({textContent:""})});
const ids=["virtual_diagnostics_status","virtual_diagnostic_empty","virtual_diagnostic_grid",
    "virtual_image","virtual_entropy_image","virtual_diagnostic_positions"];
const nodes=Object.fromEntries(ids.map(id=>[id,createNode()]));
const context={virtualDiagnostic:null,document:{getElementById:id=>nodes[id],
    querySelectorAll:()=>[createNode()]},window:{requestAnimationFrame:()=>{}},
    drawVirtualOverlays:()=>{}};
vm.createContext(context);
vm.runInContext(source,context);
const valid={image_jpeg_base64:"AAA",entropy_jpeg_base64:"BBB",image_size:[120,100],
    method:"dual_entropy_hybrid",timestamp_ns:Date.now()*1e6,
    froth_surface_cm:3.5,pulp_froth_interface_cm:1.5};
assert.equal(vm.runInContext('renderVirtualDiagnostic('+JSON.stringify(valid)+',"Frozen frame")',context),true);
assert.equal(nodes.virtual_diagnostic_grid.hidden,false);
assert.equal(nodes.virtual_diagnostic_empty.hidden,true);
assert.match(nodes.virtual_image.src,/AAA/);
assert.match(nodes.virtual_entropy_image.src,/BBB/);
assert.match(nodes.virtual_diagnostics_status.textContent,/Frozen frame/);
console.log("HIFIE preview visibility and state separation passed.");
