// Tests the global request tracker without a browser or camera.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

const listeners = {}, requests = [], buttons = [];
const classList = () => {
    const items = new Set();
    return {add:x=>items.add(x), remove:x=>items.delete(x), toggle:(x,on)=>on?items.add(x):items.delete(x),
            contains:x=>items.has(x)};
};
const panel = {classList:classList(), querySelector(selector) {
    if(selector === ".operation-message")return this.message ||= {textContent:""};
    return {addEventListener() {}};
}, set innerHTML(html) {this.html=html;}};
const document = {
    body:{appendChild(child) {child.isConnected=true;}},
    addEventListener(name,callback) {listeners[name]=callback;},
    createElement() {return panel;}
};
let release = null;
const nativeFetch = (url,options={}) => {
    requests.push({url,options});
    if(url === "/api/digiflot/pause")return new Promise(resolve => {release=resolve;});
    return Promise.resolve({ok:true,status:200,clone(){return this;},json:async()=>({})});
};
const window = {fetch:nativeFetch, crypto:{randomUUID:()=>"tab-id-test"},
    addEventListener(name,callback){listeners[name]=callback;}};
const context = vm.createContext({window,document,location:{href:"http://pi.local/run",origin:"http://pi.local"},
    URL,Headers,performance:{now:()=>1000},navigator:{sendBeacon(){}},Blob,
    setInterval:()=>3,clearInterval:()=>{},setTimeout:()=>2,clearTimeout:()=>{}});
vm.runInContext(fs.readFileSync(path.join(__dirname,"../src/ui/js/operation-feedback.js"),"utf8"),context);

async function test() {
    assert.ok(window.DigiFlotOperations);
    const target={textContent:"Pause",dataset:{},disabled:false,isConnected:true,
        getAttribute:()=>null,setAttribute(){},removeAttribute(){},closest(){return this;}};
    listeners.click({target,preventDefault(){},stopImmediatePropagation(){}});
    const first=window.fetch("/api/digiflot/pause",{method:"POST"});
    assert.equal(window.DigiFlotOperations.pending(),true);
    assert.equal(target.disabled,true);
    assert.equal(target.dataset.operationPending,"true");
    await assert.rejects(window.fetch("/api/digiflot/resume",{method:"POST"}),/still running/);
    assert.equal(requests.length,1,"Concurrent write must not reach the API");
    release({ok:true,status:200,clone(){return this;},json:async()=>({})});
    await first;
    assert.equal(window.DigiFlotOperations.pending(),false);
    assert.equal(target.disabled,false);
    assert.equal(requests[0].options.headers.get("X-DigiFlot-Tab-Id"),"tab-id-test");

    const response409={ok:false,status:409,clone(){return this;},
        json:async()=>({detail:"Camera already in use in another browser tab"})};
    window.fetch = window.fetch;
    // The mock backend returns a conflict for the next camera preview request.
    const previous=requests.length;
    const underlying = nativeFetch;
    // Native fetch is captured when the wrapper installs. Use a separate tracker for 409.
    const context2={...context};
    const requests2=[], conflictWindow={fetch:(url,opts)=>{requests2.push({url,opts});return Promise.resolve(response409);},
        crypto:{randomUUID:()=>"second-tab"},addEventListener(){}};
    const msg={textContent:""},classNames=classList();
    const localPanel={classList:classNames,querySelector:s=>s===".operation-message"?msg:{addEventListener(){}},
        set innerHTML(value){}};
    const localDoc={body:{appendChild(){}},addEventListener(){},createElement(){return localPanel;}};
    context2.window=conflictWindow;context2.document=localDoc;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,"../src/ui/js/operation-feedback.js"),"utf8"),context2);
    await conflictWindow.fetch("/api/cameras/0/preview/start",{method:"POST"});
    assert.equal(requests2[0].opts.headers.get("X-DigiFlot-Tab-Id"),"second-tab");
    assert.match(msg.textContent,/another browser tab/);
    assert.equal(classNames.contains("error"),true);
    assert.equal(previous,1);
    assert.equal(underlying,nativeFetch);
    console.log("Global operation feedback and camera-tab conflict checks passed");
}
test().catch(error=>{console.error(error);process.exitCode=1;});
