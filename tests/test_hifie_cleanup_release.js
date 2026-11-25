/* Closing HIFIE must release camera ownership even when live diagnostics stop fails. */
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("src/ui/js/sensors.js","utf8");
const start=source.indexOf("function cleanupVirtualSession()"),end=source.indexOf("async function openVirtualCalibration()",start);
assert.ok(start>0&&end>start);
const actions=[];
const context={virtualSessionGeneration:0,virtualTuningEpoch:0,virtualTuningTimer:1,virtualTuningDirty:true,
    virtualReferenceReady:true,virtualDiagnosticSource:"live",virtualFrozenDiagnostic:{},
    virtualTuningController:{abort:()=>actions.push("abort-tuning")},
    virtualRoiController:{abort:()=>actions.push("abort-roi")},virtualDiagnosticsDesired:true,
    virtualBenchmarkTask:Promise.resolve(),virtualRoiTask:{},virtualCleanup:Promise.resolve(),
    window:{clearTimeout:()=>{},setTimeout:()=>2},
    stopVirtualDiagnostics:()=>Promise.reject(new Error("Camera stop timed out")),
    requestJson:async(url,options)=>{actions.push({url,method:options.method,signal:options.signal});return {released:true}},
    console:{warn:()=>{}} ,AbortController};
vm.createContext(context);
vm.runInContext(source.slice(start,end),context);
(async()=>{vm.runInContext("cleanupVirtualSession()",context);await context.virtualCleanup;
    assert.equal(context.virtualRoiTask,null);
    assert.ok(actions.some(item=>item&&item.url==="/api/vision/virtual-sensors/froth-interface/tune-release"));
    assert.ok(actions.includes("abort-tuning")&&actions.includes("abort-roi"));
    console.log("HIFIE cleanup releases camera ownership after diagnostics stop failure");
})().catch(err=>{console.error(err);process.exitCode=1;});
