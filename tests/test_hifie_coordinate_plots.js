// Hardware-free coordinate regression: bottom height and top depth both match image row order.
const assert=require("node:assert/strict"),fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const read=name=>fs.readFileSync(path.join(__dirname,"..",name),"utf8");
const run=read("src/ui/js/run.js"),sensors=read("src/ui/js/sensors.js");
const html=read("src/ui/html/run.html"),service=read("src/lib/vision/service.py");
const pick=(src,from,to)=>{const a=src.indexOf(from),b=src.indexOf(to,a+from.length);
    assert.ok(a>=0&&b>a,from+" must exist");return src.slice(a,b);};
const colors={surface:"#29AEE4",pulp:"#F47721"};
const context2D=()=>{
    const paths=[];let current=[];
    const ctx={paths,clearRect(){},scale(){},fillText(){},fill(){},arc(){},
        beginPath(){current=[];},moveTo(x,y){current.push([x,y]);},
        lineTo(x,y){current.push([x,y]);},
        stroke(){if(current.length)paths.push({color:this.strokeStyle,coords:[...current]});}};
    return ctx;
};
const firstBoundaryY=(ctx,color)=>{
    const line=ctx.paths.find(item=>item.color===color&&item.coords.length>1);
    assert.ok(line,"Missing series in "+color);return line.coords[0][1];
};
function testRun(direction,upper,lower){
    const ctx=context2D(),canvas={dataset:{},width:0,height:0,
        getBoundingClientRect:()=>({width:240,height:120}),getContext:()=>ctx};
    const points=[0,1].map(i=>({timestamp:i,virtual:true,referenceDirection:direction,upper,lower}));
    const context={hiddenSensorPlots:new Set(),sensorPlotHistory:new Map([["hifie",points]]),
        window:{devicePixelRatio:1},document:{documentElement:{}},
        getComputedStyle:()=>({getPropertyValue:()=>""})};
    const draw=vm.runInNewContext(pick(run,"function drawSensorPlot(", "function ensureSensorCard(")+"\ndrawSensorPlot",context);
    draw(canvas,"hifie");
    assert.ok(firstBoundaryY(ctx,colors.surface)<firstBoundaryY(ctx,colors.pulp),
        "Run should show froth surface above pulp interface: "+direction);
}
function testSensors(direction,upper,lower){
    const ctx=context2D(),stats=new Map(),card={querySelector:sel=>{
        if(!stats.has(sel))stats.set(sel,{hidden:false,textContent:""});return stats.get(sel);
    }};
    const context={document:{documentElement:{}},getComputedStyle:()=>({getPropertyValue:()=>""}),
        virtualInterfaceColors:()=>colors};
    const draw=vm.runInNewContext(pick(sensors,"function drawVirtualChart(", "function drawChart(")+"\ndrawVirtualChart",context);
    const points=[0,1].map(i=>({timestamp:i,upper,lower,direction}));
    draw(ctx,240,120,points,card);
    assert.ok(firstBoundaryY(ctx,colors.surface)<firstBoundaryY(ctx,colors.pulp),
        "Sensors should show froth surface above pulp interface: "+direction);
}
function testCalibration(direction,upper,lower){
    const ctx=context2D(),chart={getBoundingClientRect:()=>({width:320})},label={textContent:""};
    const context={virtualTestSeries:[{time_s:0,valid:true,froth_surface_cm:upper,pulp_froth_interface_cm:lower},
            {time_s:1,valid:true,froth_surface_cm:upper,pulp_froth_interface_cm:lower}],
        virtualProfileData:{reference_resolved:{direction,mode:direction==="up"?"cell_bottom":"cell_top"}},
        virtualCanvas:()=>ctx,virtualInterfaceColors:()=>colors,window:{devicePixelRatio:1},
        document:{documentElement:{},getElementById:id=>id==="virtual_test_chart"?chart:label},
        getComputedStyle:()=>({getPropertyValue:()=>""})};
    const draw=vm.runInNewContext(pick(sensors,"function drawVirtualTestTimeline(", "async function pollVirtualDiagnostics(")+
        "\ndrawVirtualTestTimeline",context);
    draw();
    assert.ok(firstBoundaryY(ctx,colors.surface)<firstBoundaryY(ctx,colors.pulp),
        "Calibration should show froth surface above pulp interface: "+direction);
    assert.match(label.textContent,direction==="up"?/Height ↑/:/Depth ↓/);
}
for(const [direction,upper,lower] of [["up",6,2],["down",3,7]]){
    testRun(direction,upper,lower);testSensors(direction,upper,lower);testCalibration(direction,upper,lower);
}
assert.match(html,/data-run-layout="standard"[^>]+data-icon="rows-3"/);
assert.match(html,/data-run-layout="compact"[^>]+data-icon="layout-dashboard"/);
assert.match(service,/ref_selected = profile\["config"\]\.get\("reference_id"\)/);
assert.match(sensors,/const chosen=virtualDraft\.reference_id\|\|''/);
assert.match(sensors,/Use cell reference \(no named override\)/);
console.log("Run/Calibration/Sensors physical plots, named reference selection and layout icons passed");
