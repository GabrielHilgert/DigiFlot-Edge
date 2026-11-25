/* New Cells layout must preserve legacy IDs and initialize before event wiring. */
const fs=require("node:fs"),vm=require("node:vm"),assert=require("node:assert/strict");
const html=fs.readFileSync("src/ui/html/cells.html","utf8");
const source=fs.readFileSync("src/ui/js/cells.js","utf8");
const css=fs.readFileSync("src/ui/css/cells.css","utf8");
for(const id of ["cv_registry_mount","cv_workspace","cv_image_mount","cv_measure_mount",
 "cv_refs_mount","cv_camera_calib_mount","cv_aruco_mount","cv_geometry_mount","cv_volume_mount",
 "cv_side_camera","cv_top_camera","cv_zoom_fit","cv_zoom_in","cv_zoom_out","cv_pan_mode",
 "cv_raw_view","cv_undistorted_view","cv_rectified_view","cv_relative_source",
 "cv_relative_pick_reference","cv_relative_pick_target","cv_save_relative",
 "cv_rename_dialog","cv_delete_dialog","cv_save_measure","cv_archive_cell","cv_delete_empty",
 "image_surface","camera_image","cell_select","camera_select","reference_overlays",
 "test_rectification","detect_aruco","confirm_aruco","cell_volume_datum"])
    assert.match(html,new RegExp('id="'+id+'"'),'Missing '+id);
assert.ok(html.indexOf('id="cv_registry_mount"')<html.indexOf('id="cv_workspace"'));
assert.ok(html.indexOf('id="cv_workspace"')<html.indexOf('id="cv_workspace_panels"'));
assert.ok(source.indexOf("  arrangeCellsWorkspace();")<source.indexOf("  $('capture_cell_photo').addEventListener"),
    "Move existing nodes before adding event handlers");
for(const literal of [
    "const dimensions=registry.querySelector('.cv-field-group')",
    "$('cv_image_mount').append(image)",
    "$('cv_refs_mount').append(refs)",
    "function saveVisualMeasurement(",
    "function saveRelativeCalibration(",
    "relativePairs:{reference:[],target:[]}",
    "function changeZoom(",
    "function archiveSelectedCell(",
    "function renameSelectedCell("]) assert.ok(source.includes(literal),"Missing "+literal);
assert.ok(css.includes("#cv_image_mount .cv-image-surface"));
new vm.Script(source);
console.log("Full-width Cells workspace and safe calibration controls checked.");
