// Regression checks for the live /run page. No DOM libraries or camera needed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

class Input {
    constructor(id, value, physicalId = "") {
        this.id = id;
        this.value = value;
        this.defaultValue = value;
        this.dataset = {requiredValue: id === "execution_cell_name" ? undefined : id, physicalId};
        this.attrs = {"data-physical-id": physicalId};
        this.disabled = false;
    }
    getAttribute(key) { return this.attrs[key] ?? null; }
}
class FakePanel {
    constructor() { this.writes = 0; this.fields = new Map(); this.hidden = false; this.focused = null; }
    set innerHTML(value) {
        this.writes++;
        this.html = value;
        this.fields = new Map();
        const cell = /<input id="execution_cell_name"[^>]*value="([^"]*)" data-physical-id="([^"]*)"/.exec(value);
        if (cell) this.fields.set("execution_cell_name", new Input("execution_cell_name", cell[1], cell[2]));
        for (const match of value.matchAll(/<input id="required_[^"]*" data-required-value="([^"]+)"[^>]*value="([^"]*)"/g)) {
            this.fields.set(match[1], new Input(match[1], match[2]));
        }
    }
    get innerHTML() { return this.html; }
    querySelectorAll(selector) {
        if (selector === "input[data-required-value], #execution_cell_name") return [...this.fields.values()];
        return [];
    }
    querySelector(selector) {
        if (selector === "#execution_cell_name") return this.fields.get("execution_cell_name") || null;
        const match = /\[data-required-value="([^"]+)"\]/.exec(selector);
        return match ? this.fields.get(match[1]) || null : null;
    }
    contains(element) { return [...this.fields.values()].includes(element); }
}

const document = {activeElement: null, addEventListener() {}};
const panel = new FakePanel();
const context = vm.createContext({document, panel, window: {}, CSS: {escape: x => String(x)}, console});
vm.runInContext(fs.readFileSync(path.join(__dirname, "../src/ui/js/run.js"), "utf8"), context);
vm.runInContext("ui.required_inputs_panel = panel", context);
const render = vm.runInContext("renderRequiredInputs", context);
const state = {
    execution_inputs: {items: [{id: "feed_mass", label: "Feed mass", unit: "g", value: null}], complete: false,
                       missing: ["feed_mass"], cell_profile: {cell_name: ""}, cell_suggestions: []},
    scales: [{id: "scale_1", type: "scale", name: "Scale", unit: "g", value: 42, status: "connected"}], atlas: [],
};

render(state);
assert.equal(panel.writes, 1, "Initial markup should be rendered once");
const input = panel.fields.get("feed_mass");
input.value = "123";
document.activeElement = input;

state.scales[0].value = 43;
render(state);
assert.equal(panel.writes, 1, "Live sensor readings must never recreate the form");
assert.equal(panel.fields.get("feed_mass").value, "123", "Operator draft must survive live update");

state.execution_inputs.items[0].value = 5;
render(state);
assert.equal(panel.writes, 1, "Even genuine changes must defer while input has focus");

document.activeElement = null;
render(state);
assert.equal(panel.writes, 2, "A deferred update should render after focus leaves");
assert.equal(panel.fields.get("feed_mass").value, "123", "Unsaved text must survive rebuild");

state.execution_inputs.items[0].value = 123;
render(state, {force: true, savedField: "feed_mass"});
assert.equal(panel.fields.get("feed_mass").value, "123", "Saved value should come from server response");

panel.fields.get("execution_cell_name").value = "Vessel 2";
state.execution_inputs.items[0].value = 124;
render(state);
assert.equal(panel.fields.get("execution_cell_name").value, "Vessel 2", "Cell identity draft must survive unrelated changes");
console.log("run.js DOM regression checks passed");
