"""Small, configuration-only inventory for Server publication.

Never acquires camera frames or reads sensor values. Read-only metadata only.
"""
from __future__ import annotations

def _short_name(kind, name):
    kind=str(kind or "").lower()
    if kind in ("ph","ezo_ph"): return "pH"
    if kind=="virtual_froth_interface": return "HIFIE"
    if kind in ("wago",): return "WAGO"
    if kind in ("bronkhorst",): return "Airflow"
    if kind in ("scale",): return str(name or "Scale")[:20]
    return str(name or kind or "Sensor")[:20]

def build_inventory(digiflot):
    registry=getattr(getattr(digiflot,"vision",None),"registry",None)
    cells=[]
    if registry is not None:
        for entry in registry.list_cells():
            cells.append({key:entry.get(key) for key in
                ("id","name","revision","working_volume_l","geometry",
                 "reference_points_revision","vertical_reference_revision","thumbnail")})
    sensors=[]
    seen=set()
    def add(ident,name,kind,source,virtual=False,requires_cell=False):
        ident=str(ident or "").strip()
        if not ident or ident in seen: return
        seen.add(ident)
        sensors.append({"id":ident,"name":str(name or ident)[:80],
            "short_name":_short_name(kind,name),"type":str(kind),"source":source,
            "virtual":bool(virtual),"requires_cell":bool(requires_cell),"configured":True})
    for scale in digiflot.scales.values():
        add(scale.id,scale.name,"scale","scale")
    atlas=getattr(digiflot,"atlas",None)
    if atlas is not None:
        for sensor in atlas.sensors:
            add(atlas.sensor_id(sensor),sensor.get("name"),sensor.get("type","sensor"),"atlas")
    for driver,devices in (("bronkhorst",digiflot.bronkhorst),("wago",digiflot.wago)):
        for device in devices.values(): add(device.id,device.name,driver,driver)
    for device in digiflot.plugin_sensors.values():
        add(device.id,device.name,"plugin_sensor","plugin")
    if getattr(digiflot,"cameras",None) and registry is not None:
        add("froth_interface","HIFIE | Froth Interface Detection","virtual_froth_interface","vision",True,True)
    return {"schema_version":1,"cells":cells,"sensors":sensors}
