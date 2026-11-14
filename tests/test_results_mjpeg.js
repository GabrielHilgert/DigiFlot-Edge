// MJPEG playback UI wiring regression; no browser, camera or video files required.
const assert=require("node:assert/strict"), fs=require("node:fs"), path=require("node:path");
const read=file=>fs.readFileSync(path.join(__dirname,"..",file),"utf8");
const html=read("src/ui/html/results.html"), js=read("src/ui/js/results.js"),
    css=read("src/ui/css/results.css"), server=read("src/api/results_media.py");
for(const id of ["mjpeg_canvas","mjpeg_controls","mjpeg_play","mjpeg_prev","mjpeg_next",
                 "mjpeg_seek","mjpeg_time","mjpeg_rate","mjpeg_fullscreen"])
    assert.match(html,new RegExp('id="'+id+'"'));
assert.match(html,/<video id="video_player"[^>]*controls/);
assert.match(js,/function isMjpegVideo\(video\)/);
assert.match(js,/function openMjpegPlayer\(video, runTime\)/);
assert.match(js,/new WebSocket\(url\)/);
assert.match(js,/data\.slice\(8\)/);
assert.match(js,/new DataView\(data\)\.getFloat64\(0, false\)/);
assert.match(js,/createImageBitmap\(new Blob/);
assert.match(js,/seekMjpeg\(desired, mjpegState\.playing\)/);
assert.match(js,/if \(mjpeg\) \{\s*openMjpegPlayer\(video, runTime\)/);
assert.match(js,/if \(name !== "analysis" && isMjpegVideo\(state\.selectedVideo\)\) closeVideoPlayer\(\)/);
assert.match(js,/window\.addEventListener\("pagehide", stopMjpegSession\)/);
assert.match(css,/\.mjpeg-canvas\[hidden\]/);
assert.match(server,/if digiflot\.state == digiflot\.IDLE:/);
assert.match(server,/MAX_SESSIONS = 2/);
console.log("MJPEG results player wiring and idle-only behavior passed");
