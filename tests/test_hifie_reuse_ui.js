// Exact repeat of a saved sampling interval must survive the Hz form round-trip.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const js=fs.readFileSync(path.join(__dirname,"../src/ui/js/sensors.js"),"utf8");
const getFunction=name=>{
    const start=js.indexOf("function "+name+"(");
    assert.ok(start>=0,"Missing "+name);
    const next=js.indexOf("\nfunction ",start+10);
    return js.slice(start,next<0?undefined:next);
};
const fields={
    virtual_panel:{querySelectorAll:()=>[]},
    virtual_sampling_rate:{value:"3.333333"},
    virtual_reference_mode:{value:"cell_default"},
    virtual_reference_y:{value:""},
    virtual_named_reference:{value:""},
    virtual_reference_confirm:{checked:true},
};
const context={virtualDraft:{sampling_interval_s:0.3,vertical_reference_confirmed:true},
    document:{getElementById:id=>fields[id]},Number};
const collect=vm.runInNewContext(getFunction("virtualCollectInputs")+"\nvirtualCollectInputs",context);
assert.equal(collect().sampling_interval_s,0.3,"Rounded Hz UI must preserve the exact saved interval");
fields.virtual_sampling_rate.value="2.5";
assert.equal(collect().sampling_interval_s,0.4,"Edited Hz must update the internal interval");
assert.match(js,/const refreshed = await requestJson\("\/api\/vision\/virtual-sensors\/froth-interface\/profile"\)/);
assert.match(js,/virtualBenchmarkMarkup\(refreshed\.test\)/);
assert.match(js,/Previously validated · test not required/);
assert.match(js,/You can confirm this sensor without retesting/);
console.log("HIFIE signed preset reuse and exact Hz conversion passed");
