// Standard/Compact dashboard structure and preference regression without browser dependencies.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const read = name => fs.readFileSync(path.join(__dirname, "../src/ui/", name), "utf8");
const html = read("html/run.html"), css = read("css/run.css"), js = read("js/run.js");

function index(id) { const at = html.indexOf('id="' + id + '"'); assert.ok(at >= 0, id + " missing"); return at; }
assert.ok(html.indexOf('class="run-health-row"') < index("operations_panel"));
assert.ok(index("operations_panel") < index("run_storage_status"));
assert.ok(index("run_workspace") < index("live_sensor_panel"));
assert.ok(index("live_sensor_panel") < index("measurement_launcher"));
assert.ok(index("measurement_launcher") < index("ready_panel"));
assert.ok(index("ready_panel") < index("run_panel"));
assert.ok(index("run_panel") < index("abort_bar"));
for (const id of ["run_workspace","live_sensor_panel","measurement_launcher","ready_panel","run_panel","abort_bar"]) {
    assert.equal((html.match(new RegExp('id="' + id + '"', "g")) || []).length, 1, id + " must not be duplicated");
}
assert.match(html,/data-run-layout="standard" aria-pressed="true"/);
assert.match(html,/data-run-layout="compact" aria-pressed="false"/);
assert.match(css,/\.run-health-row\s*\{\s*display:contents/);
assert.match(css,/\.run-workspace\s*\{\s*display:flex;\s*flex-direction:column/);
assert.match(css,/@media\(min-width:1101px\)/);
assert.match(css,/grid-template-areas:"sensors action" "sensors acquisition" "sensors abort"/);
assert.match(css,/\.run-workspace\.has-live\.acquisition-expanded/);
assert.match(css,/@media\(max-width:1100px\)/);
assert.match(js,/classList\.toggle\("acquisition-expanded"/);
assert.match(js,/classList\.toggle\("has-live"/);

// Check that the inner HTML panels are nested correctly after introducing wrappers.
const main = html.slice(html.indexOf("<main "), html.indexOf("</main>") + 7);
const tags = /<(\/?)((?:main|nav|section|div|header|form|h[1-3]|p|span|button|a|strong|label|table|thead|tbody|tr|td|th|select|option|textarea|datalist))(?=[\s>])[^>]*>/g;
const stack = []; let match;
while ((match = tags.exec(main))) {
    if (!match[1]) stack.push(match[2]);
    else assert.equal(stack.pop(), match[2], "HTML nesting mismatch at " + match.index);
}
assert.equal(stack.length,0,"Main content tags must be balanced");

const storage = new Map([["digiflot-run-layout","compact"]]);
const buttons = ["standard","compact"].map(value => ({
    dataset:{runLayout:value}, attributes:{},
    setAttribute(name,value){this.attributes[name]=value;}
}));
const document = {body:{dataset:{}},addEventListener(){}};
const window = {localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value)}};
const context = vm.createContext({document,window,console,buttons});
vm.runInContext(js,context);
vm.runInContext("ui.layoutButtons = buttons; applyRunLayout(runLayout, false);",context);
assert.equal(document.body.dataset.runLayout,"compact","Saved layout must apply on load");
assert.equal(buttons[1].attributes["aria-pressed"],"true");
assert.equal(buttons[0].attributes["aria-pressed"],"false");
vm.runInContext('applyRunLayout("standard")',context);
assert.equal(storage.get("digiflot-run-layout"),"standard");
assert.equal(buttons[0].attributes["aria-pressed"],"true");
vm.runInContext('applyRunLayout("compact")',context);
assert.equal(storage.get("digiflot-run-layout"),"compact");
assert.equal(buttons[1].attributes["aria-pressed"],"true");
console.log("Run dashboard layout and saved preference checks passed");
