// HIF-inspired design tokens, source coverage and readable primary controls.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const cssNames = ["common","run","sensors","cells","config_camera","experiments","performance","results","settings"];
const read = file => fs.readFileSync(path.join(root, file), "utf8");
const cssFiles = cssNames.map(name => ({name, content:read(`src/ui/css/${name}.css`)}));
const common = cssFiles[0].content;
const tokens = ["--hif-blue","--hif-dark-blue","--hif-orange","--action-background","--action-hover",
    "--interactive-text","--success-text","--warning-text","--danger-text","--preview-text",
    "--plot-froth","--plot-froth-upper","--plot-pulp","--plot-pulp-secondary",
    "--accent","--success","--warning","--danger","--preview"];
for(const token of tokens) assert.match(common, new RegExp(`${token.replaceAll("-","\\-")}\\s*:`), token + " must exist in common.css");
for(const {name,content} of cssFiles.slice(1)) {
    assert.doesNotMatch(content, /--accent\s*:/, name + " must use the shared palette");
    assert.doesNotMatch(content, /--success\s*:/, name + " must use the shared palette");
}
const legacy = /#(?:2f6fed|255ed0|18845b|c47a12|c74242|7254d8|38bdf8|0ea5e9|f59e0b|fbbf24)\b/i;
for(const {name,content} of cssFiles) assert.doesNotMatch(content,legacy,name+" still contains an old UI color");
for(const name of ["run","sensors","results"]) {
    const source=read(`src/ui/js/${name}.js`);
    assert.doesNotMatch(source,legacy,name+" JS still draws old colors");
}
for(const name of ["run","sensors","results","cells","config_camera","experiments","performance","settings"]){
    const page=read(`src/ui/html/${name}.html`);
    assert.match(page,/css\/common\.css'\)\s*\}\}\?v=20261114hif1/,name+" must load versioned tokens");
    assert.match(page,new RegExp(`css/${name}\\.css'\\)\\s*\\}\\}\\?v=20261114hif1`),name+" must load current CSS");
}
function luminance(hex){const rgb=hex.replace("#","").match(/../g).map(x=>parseInt(x,16)/255);
    const linear=rgb.map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
    return .2126*linear[0]+.7152*linear[1]+.0722*linear[2];}
function contrast(a,b){const x=luminance(a),y=luminance(b);
    return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
for(const [foreground,background] of [
    ["#FFFFFF","#00589C"],["#FFFFFF","#176FA6"],["#69B9E8","#23252B"],
    ["#5FC796","#23252B"],["#F28A7C","#23252B"],["#F1BE69","#23252B"]
])assert.ok(contrast(foreground,background)>=4.5,`${foreground} on ${background} must meet WCAG AA`);
console.log("HIF-inspired CSS palette and contrast checks passed");
