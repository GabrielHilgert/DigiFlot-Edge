/* Shared offline SVG icons. Explicit opt-in: data-icon, optionally data-icon-only. */
(() => {
    "use strict";
    const ns="http://www.w3.org/2000/svg";
    const paths={
        "refresh-cw":'<path d="M20 11a8 8 0 0 0-14-5L3 9"/><path d="M3 3v6h6"/><path d="M4 13a8 8 0 0 0 14 5l3-3"/><path d="M21 21v-6h-6"/>',
        "rotate-ccw":'<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
        "cloud-upload":'<path d="M7 18H6a4 4 0 0 1-1-7.9A7 7 0 0 1 18 9a4 4 0 0 1 0 8h-1"/><path d="m12 20 0-9m-4 4 4-4 4 4"/>',
        "file-up":'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M12 19V11m-3 3 3-3 3 3"/>',
        "folder-open":'<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v3"/><path d="M3 9h18l-3 11H6z"/>',
        "chart":'<path d="M3 3v18h18"/><path d="m7 15 4-4 3 2 5-7"/>',
        "chart-line":'<path d="M3 3v18h18"/><path d="m7 17 4-6 3 2 5-7"/>',
        "trash-2":'<path d="M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15M10 10v7m4-7v7"/>',
        "plus":'<path d="M12 5v14M5 12h14"/>',
        "x":'<path d="M18 6 6 18M6 6l12 12"/>',
        "play":'<path d="m8 5 11 7-11 7z"/>',
        "square":'<rect x="5" y="5" width="14" height="14" rx="2"/>',
        "pause":'<path d="M9 5v14M15 5v14"/>',
        "skip-forward":'<path d="m5 4 12 8-12 8zM19 4v16"/>',
        "download":'<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>',
        "eye":'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
        "eye-off":'<path d="m3 3 18 18M10.5 5.1A11 11 0 0 1 12 5c6 0 10 7 10 7a15 15 0 0 1-3.2 3.8M7 6.2C4 8 2 12 2 12s4 7 10 7a11 11 0 0 0 4.1-.8"/><path d="M10 10a3 3 0 0 0 4 4"/>',
        "image":'<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="2"/><path d="m21 15-5-5L5 21"/>',
        "image-off":'<path d="M3 3 21 21M6 3h13a2 2 0 0 1 2 2v13M3 8v11a2 2 0 0 0 2 2h12M8 8h.01M4 17l4-4 2 2m6-5 5 5"/>',
        "activity":'<path d="M2 12h4l3-8 5 16 3-8h5"/>',
        "settings":'<circle cx="12" cy="12" r="3"/><path d="m9.8 2 4.4 0 .7 2.3 1.6.9 2.4-.6 2.2 3.8-1.7 1.8v1.8l1.7 1.8-2.2 3.8-2.4-.6-1.6.9-.7 2.3H9.8l-.7-2.3-1.6-.9-2.4.6-2.2-3.8 1.7-1.8v-1.8L2.9 8.4l2.2-3.8 2.4.6 1.6-.9z"/>',
        "save":'<path d="M4 3h14l3 3v15H3V3zM7 3v7h10V3M7 21v-8h10v8"/>',
        "power":'<path d="M12 2v10M5 5a9 9 0 1 0 14 0"/>',
        "sliders":'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2"/><circle cx="15" cy="17" r="2"/>',
        "wand":'<path d="m4 20 12-12 4 4-12 12zM3 5V2m-2 3h4M18 2v4m-2-2h4M21 15v4m-2-2h4"/>',
        "check":'<path d="m4 12 5 5L20 6"/>',
        "badge-check":'<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',
        "circle-dashed":'<path d="M12 3a9 9 0 0 1 6.4 2.6M21 12a9 9 0 0 1-2.6 6.4M12 21a9 9 0 0 1-6.4-2.6M3 12a9 9 0 0 1 2.6-6.4"/>',
        "crop":'<path d="M6 2v14a2 2 0 0 0 2 2h14M2 6h14a2 2 0 0 1 2 2v14"/>',
        "maximize":'<path d="M8 3H3v5M3 3l6 6M16 3h5v5m0-5-6 6M3 16v5h5m-5 0 6-6M21 16v5h-5m5 0-6-6"/>',
        "minimize":'<path d="M8 3v5H3m5 0L3 3m13 0v5h5m-5 0 5-5M8 21v-5H3m5 0-5 5m13 0v-5h5m-5 0 5 5"/>',
        "scan":'<path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3M21 16v3a2 2 0 0 1-2 2h-3M3 12h18"/>',
        "scan-search":'<path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M3 16v3a2 2 0 0 0 2 2h3"/><circle cx="15" cy="15" r="4"/><path d="m18 18 3 3"/>',
        "crosshair":'<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>',
        "eraser":'<path d="m21 13-9 9H7L2 17l11-13 8 8zM7 12l7 7M12 22h10"/>',
        "external-link":'<path d="M14 3h7v7m0-7-10 10M19 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h5"/>',
        "camera":'<path d="M3 7h4l2-3h6l2 3h4v13H3z"/><circle cx="12" cy="13" r="4"/>',
        "flask":'<path d="M9 2h6M10 2v7L4 19a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3L14 9V2M7 16h10"/>',
        "chevron-left":'<path d="m15 18-6-6 6-6"/>',
        "chevron-right":'<path d="m9 18 6-6-6-6"/>',
        "arrow-left":'<path d="m12 19-7-7 7-7M5 12h14"/>',
        "layout-dashboard":'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        "rows-3":'<path d="M4 5h16M4 12h16M4 19h16"/>',
        "hard-drive":'<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 14h.01M10 14h.01"/>',
        "gauge":'<path d="M5 17a9 9 0 1 1 14 0M12 12l4-4"/><circle cx="12" cy="12" r="2"/>',
        "video":'<rect x="3" y="5" width="14" height="14" rx="2"/><path d="m17 10 4-3v10l-4-3"/>',
        "file":'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6"/>',
        "search":'<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
        "zoom-in":'<circle cx="10" cy="10" r="7"/><path d="M7 10h6m-3-3v6m5 2 6 6"/>',
        "zoom-out":'<circle cx="10" cy="10" r="7"/><path d="M7 10h6m2 5 6 6"/>',
        "chevron-down":'<path d="m6 9 6 6 6-6"/>',
        "corner-up-left":'<path d="m9 14-5-5 5-5M4 9h10a6 6 0 0 1 6 6v5"/>',
        "monitor":'<rect x="2" y="3" width="20" height="15" rx="2"/><path d="M8 22h8M12 18v4"/>'
    };
    function svg(name) {
        if (!Object.hasOwn(paths,name)) return null;
        const element=document.createElementNS(ns,"svg");
        element.setAttribute("viewBox","0 0 24 24");
        element.setAttribute("fill","none");
        element.setAttribute("stroke","currentColor");
        element.setAttribute("stroke-width","1.8");
        element.setAttribute("stroke-linecap","round");
        element.setAttribute("stroke-linejoin","round");
        element.setAttribute("aria-hidden","true");
        element.setAttribute("focusable","false");
        element.classList.add("df-icon");
        element.dataset.name=name;
        element.innerHTML=paths[name];
        return element;
    }
    function enhance(el) {
        if (!el) return;
        const name=el.dataset?.icon, mark=name&&svg(name);
        if(!mark)return;
        const existing=Array.from(el.children).find(child=>child.classList?.contains("df-icon"));
        if(existing?.dataset.name===name) return;
        existing?.remove();
        if(el.hasAttribute("data-icon-only")){
            const label=el.getAttribute("aria-label")||el.getAttribute("title")||el.textContent.trim()||name;
            if (!el.hasAttribute("aria-label")) el.setAttribute("aria-label",label);
            if (!el.hasAttribute("title")) el.setAttribute("title",label);
            el.classList.add("df-icon-only");
        }
        el.classList.add("df-icon-control");
        el.prepend(mark);
    }
    function decorate(root=document) {
        if(root.matches?.("[data-icon]")) enhance(root);
        root.querySelectorAll?.("[data-icon]").forEach(enhance);
    }
    function set(el,name,label,only=false) {
        if(!el)return;
        if(el.dataset.icon===name && el.getAttribute("aria-label")===label && el.querySelector(":scope > .df-icon")?.dataset.name===name)return;
        el.dataset.icon=name;
        if(only)el.dataset.iconOnly="";
        if(label!=null){
            el.textContent=label;
            el.setAttribute("aria-label",label);
            el.setAttribute("title",label);
        }
        enhance(el);
    }
    window.DigiFlotIcons=Object.freeze({svg,enhance,decorate,set,names:Object.freeze(Object.keys(paths))});
    if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>decorate(),{once:true});
    else decorate();
})();
