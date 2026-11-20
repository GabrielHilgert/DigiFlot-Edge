/* HIFIE retry must lead to detector/validation without requiring filter changes. */
const assert=require("node:assert/strict"),fs=require("node:fs"),vm=require("node:vm");
const source=fs.readFileSync("src/ui/js/sensors.js","utf8");
const listeners={}, calls=[];
const makeNode=id=>({id,open:id==="virtual_panel",disabled:false,dataset:{},checked:false,hidden:false,
    textContent:"",addEventListener:(type,fn)=>{listeners[id+":"+type]=fn;},
    scrollIntoView:()=>calls.push("scroll:"+id),
    querySelector:()=>({textContent:""})});
const ids=["virtual_roi_refresh","virtual_camera_continue","virtual_tuning_continue",
    "virtual_validation_test","virtual_test","virtual_panel","virtual_reference_confirm",
    "virtual_camera_step","virtual_detector_step","virtual_validation_step",
    "virtual_camera_ready","virtual_benchmark","virtual_validation_hint"];
const nodes=Object.fromEntries(ids.map(id=>[id,makeNode(id)]));
nodes.virtual_test.click=()=>calls.push("test-click");
nodes.virtual_reference_confirm.checked=true;
const context={document:{getElementById:id=>nodes[id]},virtualSessionGeneration:1,
    virtualDiagnosticsActive:false,virtualDiagnosticsDesired:false,virtualReferenceReady:true,
    virtualRoiPlane:{size:[128,120]},virtualRoiDirty:false,virtualDiagnostic:{image_size:[128,120]},
    stopVirtualDiagnostics:async()=>calls.push("stop"),loadVirtualRoiPlane:async()=>{calls.push("capture");return true;},
    runVirtualTuning:async()=>{calls.push("tuning");return true;},
    hifieUpdateNavigation:()=>calls.push("nav"),hifieGoToStep:step=>calls.push("step:"+step),
    virtualEffectiveRoi:()=>[0,0,10,10],startVirtualDiagnostics:async()=>{},hifieWorkflow:()=>{},
    showToast:message=>{throw Error("Unexpected toast: "+message);}};
const handler=source.slice(source.indexOf('document.getElementById("virtual_roi_refresh").addEventListener'),
    source.indexOf('document.getElementById("virtual_roi_reset").addEventListener'));
vm.runInNewContext(handler,context);
async function verify(){
    await listeners["virtual_roi_refresh:click"]({currentTarget:nodes.virtual_roi_refresh});
    assert.deepEqual(calls.slice(0,4),["capture","tuning","nav","step:detector"]);
    assert.equal(nodes.virtual_roi_refresh.disabled,false);
    calls.length=0;listeners["virtual_tuning_continue:click"]();
    assert.deepEqual(calls,["step:validation"]);
    calls.length=0;listeners["virtual_validation_test:click"]();
    assert.deepEqual(calls,["test-click"]);
    calls.length=0;listeners["virtual_camera_continue:click"]();
    assert.deepEqual(calls,["step:detector"]);
    // If the image exists but its cached detector ROI cannot be compiled,
    // the user still has a path to the validation step.
    calls.length=0;context.virtualReferenceReady=false;
    await listeners["virtual_roi_refresh:click"]({currentTarget:nodes.virtual_roi_refresh});
    assert.deepEqual(calls,["capture","nav","step:detector"]);
}
verify().then(()=>console.log("HIFIE manual retry → detector → validation passed"))
    .catch(error=>{console.error(error);process.exitCode=1;});
