"use strict";
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const src=fs.readFileSync("src/ui/js/experiments.js","utf8");
const from=(a,b)=>{const start=src.indexOf(a),end=src.indexOf(b,start+1);assert(start>=0&&end>start);return src.slice(start,end)};
const formatter=from("function formatStorageBytes(value) {","async function loadSystemHealth(");
const loader=from("async function loadStorageEstimate(experiment, selectedKey) {","/* -------------------------------------------------------------------------- */\n/* Loading");
const elements=Object.fromEntries(["estimateSection","estimatedCapacity","estimatedNote","estimatedTotal",
  "estimatedVideo","estimatedAuxiliary"].map(id=>[id,{textContent:"",hidden:false}]));
const estimate={open_ended:true,estimated_bytes:null,bounded_stage_bytes:3e6,
  video_bytes:2e6,auxiliary_bytes:1e6,estimated_autonomy_s:3600,
  sufficient:true,margin_percent:30,reserve_bytes:2e9,
  cameras:[{source:"default",manual_used:true}],unplanned_transitions:true};
const context={elements,state:{selectedKey:"run-1"},formatDuration:v=>v+" seconds",requestJson:async()=>estimate};
vm.createContext(context);vm.runInContext(formatter+"\n"+loader,context);
assert.equal(vm.runInContext("formatStorageBytes(null)",context),"—");
(async()=>{
  await vm.runInContext("loadStorageEstimate({}, 'run-1')",context);
  assert.equal(elements.estimatedTotal.textContent,"Open-ended");
  assert.equal(elements.estimatedCapacity.textContent,"Runtime monitoring");
  assert.match(elements.estimatedVideo.textContent,/variable/);
  assert.match(elements.estimatedNote.textContent,/Manual stages have no fixed storage total/);
  assert.match(elements.estimatedNote.textContent,/3600 seconds/);
  assert.match(elements.estimatedNote.textContent,/not a guaranteed recording time/);
  console.log("Open-ended storage UI preserves unknown duration and warns about capacity.");
})().catch(e=>{console.error(e);process.exitCode=1});
