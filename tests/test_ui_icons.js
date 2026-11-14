/* Offline UI icons, accessibility and HIFIE independent image/plot controls. */
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const read=file=>fs.readFileSync(path.join(__dirname,"..",file),"utf8");
const pages=["run","experiments","sensors","cells","config_camera","results","settings","performance"];
const navbar=read("src/ui/html/_navbar.html"),icons=read("src/ui/js/icons.js");
assert.match(navbar,/src="\{\{ url_for\('static', path='js\/icons\.js'\) \}\}\?v=20261114icons1"/);
for(const page of pages){
    const html=read("src/ui/html/"+page+".html");
    assert.match(html,/css\/common\.css'\) \}\}\?v=20261114icons1/,"shared CSS version: "+page);
    assert.match(html,/data-icon="[^"]+"/,"visible controls decorated: "+page);
}
assert.ok(!/https?:\/\/.*(?:lucide|fontawesome|unpkg)/i.test(navbar+icons),"icons require no CDN");
const events={};
const document={
    readyState:"loading",addEventListener:(type,fn)=>{events[type]=fn;},
    createElementNS:(ns,tag)=>{
        const attrs={};const names=new Set();const node={tagName:tag,dataset:{},children:[],
            classList:{add:x=>names.add(x),contains:x=>names.has(x)},
            setAttribute:(key,value)=>{attrs[key]=String(value);},getAttribute:key=>attrs[key],
            hasAttribute:key=>Object.hasOwn(attrs,key),innerHTML:""};
        return node;
    }
};
const window={};vm.runInNewContext(icons,{window,document,Object});
assert.ok(window.DigiFlotIcons,"icons exported");
function control(text){
    const attrs={},classes=new Set();
    return {
        dataset:{},children:[],_text:text,classList:{add:n=>classes.add(n),contains:n=>classes.has(n)},
        get textContent(){return this._text;},set textContent(v){this._text=String(v);this.children=[];},
        setAttribute(n,v){attrs[n]=String(v);},getAttribute:n=>attrs[n],hasAttribute:n=>Object.hasOwn(attrs,n),
        prepend(node){this.children.unshift(node);},querySelector(sel){return sel===":scope > .df-icon" ? this.children.find(n=>n.classList.contains("df-icon")) : null;}
    };
}
const imageButton=control("Hide image"), plotButton=control("Hide plot");
window.DigiFlotIcons.set(imageButton,"image-off","Hide image",true);
window.DigiFlotIcons.set(plotButton,"eye-off","Hide plot",true);
assert.equal(imageButton.querySelector(":scope > .df-icon").dataset.name,"image-off");
assert.equal(plotButton.querySelector(":scope > .df-icon").dataset.name,"eye-off");
assert.equal(imageButton.getAttribute("aria-label"),"Hide image");
assert.equal(plotButton.getAttribute("aria-label"),"Hide plot");
assert.equal(imageButton.getAttribute("title"),"Hide image");
assert.equal(plotButton.getAttribute("title"),"Hide plot");
assert.ok(imageButton.classList.contains("df-icon-only"));
window.DigiFlotIcons.set(imageButton,"image","Show image",true);
window.DigiFlotIcons.set(plotButton,"eye","Show plot",true);
assert.equal(imageButton.querySelector(":scope > .df-icon").dataset.name,"image");
assert.equal(plotButton.querySelector(":scope > .df-icon").dataset.name,"eye");
assert.equal(plotButton.getAttribute("aria-label"),"Show plot");
assert.equal(imageButton.getAttribute("aria-label"),"Show image");
const allNames=new Set(window.DigiFlotIcons.names);
for(const page of pages){
    const text=read("src/ui/html/"+page+".html");
    for(const [,name] of text.matchAll(/\bdata-icon="([^"]+)"/g))assert.ok(allNames.has(name),page+" unknown icon "+name);
}
const run=read("src/ui/js/run.js");
assert.match(run,/const toggle = card\.querySelector\("\[data-plot-toggle\]"\)/);
assert.doesNotMatch(run,/const toggle = card\.querySelector\("\.plot-toggle"\)/);
assert.match(run,/const imageControl = card\.querySelector\("\[data-image-toggle\]"\)/);
assert.match(run,/DigiFlotIcons\.set\(imageControl/);
assert.match(run,/DigiFlotIcons\.set\(toggle/);
assert.match(run,/data-image-toggle="1" data-icon="image-off" data-icon-only/);
assert.match(run,/data-plot-toggle="\$\{escapeHtml\(key\)\}" data-icon="eye-off" data-icon-only/);
for(const [page,file,needle] of [
    ["experiments","src/ui/js/experiments.js","DigiFlotIcons.set(resultsButton"],
    ["results","src/ui/js/results.js","DigiFlotIcons?.set(download"],
    ["cells","src/ui/js/cells.js","DigiFlotIcons?.decorate(list)"],
    ["sensors","src/ui/js/sensors.js","DigiFlotIcons?.decorate(el.sensorGrid)"]
])assert.ok(read(file).includes(needle),"dynamic icons on "+page);
console.log("Shared icon library, accessibility, dynamic actions and independent HIFIE controls passed");
