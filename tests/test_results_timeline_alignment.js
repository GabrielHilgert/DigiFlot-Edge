const assert = require("node:assert/strict"), fs = require("node:fs"), path = require("node:path"), vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../src/ui/js/results.js"), "utf8");

function extract(name) {
    const start = source.indexOf(`function ${name}(`);
    assert.ok(start >= 0, `Missing ${name}`);
    const following = source.slice(start).match(/\nfunction [A-Za-z_$][\w$]*\(/);
    return following ? source.slice(start, start + following.index) : source.slice(start);
}
const functions = ["xForTime", "percentageForTime", "renderStageTrack", "renderTimeAxis"].map(extract).join("\n");
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `Expected ${expected}, got ${actual}`);

for (const width of [640, 1000]) {
    const elements = {
        analysisStageTrack: { innerHTML: "", getBoundingClientRect: () => ({width}) },
        analysisTimeAxis: { innerHTML: "" },
    };
    const state = {viewStart:0, viewEnd:300, cursorTime:150};
    const stages = [
        {stage_name:"Stage 1", stage_type:"flotation", start_s:0, end_s:100},
        {stage_name:"Stage 2", stage_type:"flotation", start_s:150, end_s:210},
    ];
    const context = {state, elements, currentStages:() => stages, escapeHtml:String,
                     formatSeconds:String, formatAxisTime:String, Number, Math};
    vm.runInNewContext(functions, context);
    const x = time => context.xForTime(time, width) / width * 100;

    context.renderStageTrack();
    const segments = [...elements.analysisStageTrack.innerHTML.matchAll(/class="analysis-stage-segment[^"]*" style="left:([\d.]+)%;width:([\d.]+)%"/g)];
    assert.equal(segments.length, 2);
    close(Number(segments[0][1]), x(0));
    close(Number(segments[0][2]), x(100)-x(0));
    close(Number(segments[1][1]), x(150));
    close(Number(segments[1][2]), x(210)-x(150));
    assert.ok(x(150) > x(100), "The real inter-stage delay must remain visible");
    const cursor = elements.analysisStageTrack.innerHTML.match(/class="shared-cursor stage-cursor" style="left:([\d.]+)%"/);
    close(Number(cursor[1]), x(150));

    context.renderTimeAxis();
    const ticks = [...elements.analysisTimeAxis.innerHTML.matchAll(/left:([\d.]+)%/g)];
    assert.equal(ticks.length, 5);
    close(Number(ticks[0][1]), x(0));
    close(Number(ticks[4][1]), x(300));

    state.viewStart=60; state.viewEnd=240;
    context.renderStageTrack();
    const zoomed = [...elements.analysisStageTrack.innerHTML.matchAll(/class="analysis-stage-segment[^"]*" style="left:([\d.]+)%;width:([\d.]+)%"/g)];
    assert.equal(zoomed.length, 2);
    close(Number(zoomed[0][1]), x(60));
    close(Number(zoomed[1][1]), x(150));
    context.renderTimeAxis();
    const zoomedTicks = [...elements.analysisTimeAxis.innerHTML.matchAll(/left:([\d.]+)%/g)];
    close(Number(zoomedTicks[0][1]), x(60));
    close(Number(zoomedTicks[4][1]), x(240));
}
console.log("Results stages, cursor, axis and plot viewport alignment passed");
