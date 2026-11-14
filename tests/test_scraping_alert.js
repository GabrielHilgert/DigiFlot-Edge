// Operator scraping signal: stale events, stage stop, display modes and audio separation.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const js = fs.readFileSync(path.join(__dirname, "../src/ui/js/run.js"),"utf8");
const css = fs.readFileSync(path.join(__dirname, "../src/ui/css/run.css"),"utf8");
const settingsHtml = fs.readFileSync(path.join(__dirname, "../src/ui/html/settings.html"),"utf8");
const settingsJs = fs.readFileSync(path.join(__dirname, "../src/ui/js/settings.js"),"utf8");

const document = {hidden:false,addEventListener(){}};
const window = {localStorage:{getItem:()=>null},sessionStorage:{getItem:()=>null}};
const ctx = vm.createContext({document,window,console});
vm.runInContext(js,ctx);
const classes = new Set(), signal={dataset:{}, offsetWidth:100,
    classList:{add:name=>classes.add(name),remove:name=>classes.delete(name)}};
ctx.signal=signal;ctx.events={beeps:0};
vm.runInContext("ui.scrape_signal=signal; beep=()=>events.beeps++;",ctx);
const handle = vm.runInContext("handleScrapingSignal",ctx);
const state=(seq,age,more={})=>({state:"Running",stage_state:"Active",
    scraping:{sequence:seq,age_s:age,enabled:true,method:"gpio",alerts_enabled:true,alert_style:"fullscreen",...more}});
handle(state(0,0));
assert.equal(classes.has("show"),false);
handle(state(1,.2,{alert_style:"banner"}));
assert.equal(classes.has("show"),true);
assert.equal(signal.dataset.style,"banner");
assert.equal(ctx.events.beeps,0,"GPIO mode must not emit a browser beep");
handle(state(2,8));
assert.equal(ctx.events.beeps,0,"Stale events must not be replayed");
handle(state(3,.1,{alerts_enabled:false,method:"audio"}));
assert.equal(classes.has("show"),false,"Visual checkbox hides overlay");
assert.equal(ctx.events.beeps,1,"Audio remains independent of visual checkbox");
handle({...state(4,.1),state:"Paused"});
assert.equal(classes.has("show"),false,"Paused states hide the active flash");
handle(state(5,.1));
assert.equal(classes.has("show"),true);
handle({...state(5,.1),stage_state:"Transition"});
assert.equal(classes.has("show"),false,"Stage transition must clear overlay");
document.hidden=true;
handle(state(6,.1));
assert.equal(classes.has("show"),false,"Hidden browser must not queue notifications");

assert.match(css, /@keyframes digiflot-scrape-flash/);
assert.match(css, /\.scrape-signal\[data-style="banner"\]/);
assert.match(css, /animation:digiflot-scrape-flash \.8s/);
assert.doesNotMatch(js,/scrapeFlashTimer|setTimeout\(\(\) => ui\.scrape_signal\.classList\.remove/);
for(const id of ["scraping_alerts_enabled","scraping_alert_style","scraping_gpio_pin"]){
    assert.match(settingsHtml,new RegExp('id="'+id+'"'));
    assert.ok(settingsJs.includes(id),"Settings must save "+id);
}
assert.match(settingsHtml,/Whole Screen Alert/);
assert.match(settingsHtml,/Compact Banner/);
assert.match(settingsHtml,/Show Scraping Alert/);
console.log("Scraping alert mode and stale-signal checks passed");
