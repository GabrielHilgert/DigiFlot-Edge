/* HIFIE variable channels, physical reference and volume source options. */
const fs=require("node:fs"),assert=require("node:assert/strict"),vm=require("node:vm");
const js=fs.readFileSync("src/ui/js/run.js","utf8");
const html=fs.readFileSync("src/ui/html/run.html","utf8");
for(const id of ["measurement_hifie_channel","measurement_hifie_output","measurement_hifie_reference"])
    assert.match(html,new RegExp('id="'+id+'"'));
assert.match(js,/hifie_channel=ui\.measurement_hifie_channel\.value/);
assert.match(js,/hifie_reference_id=ui\.measurement_hifie_reference\.value/);
assert.match(js,/hifie_output=ui\.measurement_hifie_output\.value/);
assert.match(js,/volume_models/);
assert.match(js,/model\.area_cm2/);
assert.match(js,/interface_mean_cm/);
assert.match(html,/value="interface_mean_cm"/);
assert.match(html,/id="measurement_hifie_model"/);
assert.match(js,/hifie_volume_model_id=ui\.measurement_hifie_model\.value/);
assert.match(js,/selected_volume_model_id/);
new vm.Script(js);
console.log("HIFIE derived measurement UI checks passed.");
