/* One EventSource handles all sensors, with HIFIE preview timeout and frozen cache. */
const fs=require("node:fs"),assert=require("node:assert/strict"),vm=require("node:vm");
const js=fs.readFileSync("src/ui/js/sensors.js","utf8"),py=fs.readFileSync("src/api/sensors.py","utf8");
assert.ok(py.indexOf('@router.get("/stream")')<py.indexOf('@router.get("/{sensor_id}")'));
assert.match(js,/connectSensorStream\(\);/);
assert.doesNotMatch(js,/state\.streams/);
const a=js.indexOf("function connectSensorStream()"),b=js.indexOf("async function loadSensors()",a);
const opened=[],updates=[];
class MockEventSource {constructor(url){this.url=url;this.closed=false;this.callbacks={};opened.push(this);}
    close(){this.closed=true;} addEventListener(name,callback){this.callbacks[name]=callback;}}
const context={state:{stream:null},EventSource:MockEventSource,updateCard:x=>updates.push(x),console};
vm.runInNewContext(js.slice(a,b)+"\nconnectSensorStream();connectSensorStream();",context);
assert.equal(opened.length,2);assert.equal(opened[0].closed,true);
assert.equal(context.state.stream.url,"/api/sensors/stream");
opened[1].callbacks.measurement({data:JSON.stringify({id:"scale_1"})});
opened[1].callbacks.measurement({data:JSON.stringify({id:"atlas-98"})});
assert.deepEqual(updates.map(x=>x.id),["scale_1","atlas-98"]);
assert.match(js,/virtualTuningController=controller/);
assert.match(js,/virtualTuningController\?\.abort\(\)/);
assert.match(js,/virtualFrozenDiagnostic=data\.diagnostic/);
new vm.Script(js);
console.log("Sensor multiplex and HIFIE UI checks passed");
