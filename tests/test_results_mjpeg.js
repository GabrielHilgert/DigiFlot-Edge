// MJPEG playback UI wiring regression; no browser, camera or video files required.
const assert=require("node:assert/strict"), fs=require("node:fs"), path=require("node:path");
const read=file=>fs.readFileSync(path.join(__dirname,"..",file),"utf8");
const html=read("src/ui/html/results.html"), js=read("src/ui/js/results.js"),
    css=read("src/ui/css/results.css"), scss=read("src/ui/scss/results.scss"),
    icons=read("src/ui/js/icons.js"), server=read("src/api/results_media.py");
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
// In fullscreen the player must fill available height, not retain the normal 720px cap.
for(const style of [css,scss]) {
    assert.match(style,/\.analysis-video-viewer:fullscreen\s*\{[^}]*display:flex; flex-direction:column;/);
    assert.match(style,/\.analysis-video-viewer:fullscreen\s*>\s*\.video-player-wrap\s*\{[^}]*flex:1 1 0;/);
    assert.match(style,/\.analysis-video-viewer:fullscreen\s*>\s*\.video-player-wrap\s*>\s*\.mjpeg-canvas:not\(\[hidden\]\)/);
    assert.match(style,/max-width:100%; max-height:100%; object-fit:contain;/);
    assert.match(style,/\.analysis-video-viewer:fullscreen\s*>\s*\.mjpeg-controls\s*\{[^}]*flex:0 0 auto;/);
    assert.match(style,/\.analysis-video-viewer:fullscreen\s*>\s*\.video-context\s*\{ display:none;/);
}
assert.match(js,/document\.fullscreenElement === elements\.videoViewer/);
assert.match(js,/document\.addEventListener\("fullscreenchange"/);
assert.match(js,/await document\.exitFullscreen\(\)/);
assert.match(js,/await elements\.videoViewer\.requestFullscreen\(\)/);
assert.match(js,/fullscreen \? "minimize" : "maximize"/);
assert.match(js,/parts\.push\("direct JPEG playback"\)/);
assert.match(icons,/"minimize":/);
assert.match(server,/if digiflot\.state == digiflot\.IDLE:/);
assert.match(server,/MAX_SESSIONS = 2/);
console.log("MJPEG results player wiring and idle-only behavior passed");
