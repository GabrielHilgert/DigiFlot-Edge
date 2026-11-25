(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {cells: [], cameras: [], settings: {}, profile: null, cell: null,
    cameraId: null, cellId: null, association: null, pending: null, frame: null,
    roi: [0, 0, 1, 1], analysisRoi: null, roiDirty: false, view: 'raw', plane: null, drag: null, named:null, activePoint:null, pointClick:null, namedDirty:false, dimensionMeasurements:null,
    imageSpace:'raw',uiTool:'select',pickClick:null,panDrag:null,measurePoints:[],relativePairs:{reference:[],target:[]},
    capturedCameraId:null,capturedProfileRevision:null,capturedCalibrationId:null,
    measurePointIds:[],relativeSourcePoints:[],relativeSourceCm:[],relativeSourceCalibrationId:null,
    relativeSourceCameraRevision:null,relativeDestinationCameraId:null,relativeSourceCameraId:null,
    cameraRoles:{side:null,top:null},relativeRecord:null,zoom:1,panX:0,panY:0,showArchived:false};
  const text = (id, value) => { $(id).textContent = value == null ? '—' : String(value); };
  const numeric = id => { const raw = $(id).value.trim(); return raw === '' ? null : Number(raw); };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const toast = (message, error=false) => { text('vision_toast', message); $('vision_toast').dataset.error = error ? 'true' : 'false'; };

  async function api(path, options={}) {
    const init = {...options};
    if (init.body && typeof init.body !== 'string') {
      init.headers = {...init.headers, 'Content-Type':'application/json'};
      init.body = JSON.stringify(init.body);
    }
    const response = await fetch(`/api/vision${path}`, init);
    let data;
    try { data = await response.json(); } catch (_) { data = {}; }
    if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
    return data;
  }
  const action = callback => async () => { try { await callback(); } catch (err) { toast(err.message, true); } };
  const showImage = (data, view='raw') => {
    if (!data?.jpeg_base64) return;
    state.view = view;state.imageSpace=data.image_space||'raw';
    state.capturedCameraId=state.cameraId;
    state.capturedProfileRevision=state.profile?.revision??null;
    state.capturedCalibrationId=data.calibration_id||null;
    state.measurePoints=[];state.relativePairs={reference:[],target:[]};
    state.zoom=1;state.panX=0;state.panY=0;
    state.frame = data.frame || null;
    state.plane = data.plane || null;
    state.drag = null;
    $('roi_drag').hidden = true;
    $('roi_selection').hidden = true;
    $('image_help').textContent = view === 'rectified'
      ? 'Rectified plane: drag to select the physical analysis ROI. Save analysis ROI to apply it during recording.'
      : 'Raw camera: drag to adjust the sensor ROI. Open Rectified plane to select the physical analysis ROI.';
    $('camera_image').src = `data:image/jpeg;base64,${data.jpeg_base64}`;
    showWorkspaceStatus();
    applyCanvasViewport();
  };

  function arrangeCellsWorkspace() {
    // Move existing UI nodes, not clones: their IDs, handlers and stored settings survive.
    const grid=$('cv_original_layout'),registry=grid.querySelector('.cell-profile-card');
    const camera=grid.querySelector('.camera-profile-card'),calibration=document.querySelector('.vision-calibration-card');
    const dimensions=registry.querySelector('.cv-field-group'),volume=dimensions.querySelector('.cv-volume-card');
    const measured=dimensions.querySelector('.cv-dimension-card:not(.cv-resolved-card):not(.cv-nominal-card):not(.cv-volume-card)');
    $('cv_volume_mount').append(volume);$('cv_measure_mount').append(measured);
    $('cv_geometry_mount').append(dimensions,registry.querySelector('.cv-card-actions'));
    const arucoGroup=registry.querySelector('.cv-field-group'),legacyGroup=registry.querySelector('.cv-legacy-reference');
    const refs=calibration.querySelector('.cv-reference-editor'),image=calibration.querySelector('.cv-image-panel');
    const calibrationTools=calibration.querySelector('.cv-tools');
    $('cv_refs_mount').append(refs);
    $('cv_aruco_mount').append(arucoGroup,legacyGroup,calibrationTools);
    $('cv_image_mount').append(image);
    $('cv_camera_selector_mount').append(camera.querySelector('.cv-select-panel'));
    $('cv_camera_calib_mount').append(camera);
    const buttons=calibration.querySelector('.cv-card-head > .cv-inline-row');
    if(buttons)$('cv_preview_controls').append(...buttons.children);
    $('cv_registry_mount').append(registry);
    const management=document.createElement('div');management.className='cv-inline-row cv-registry-actions';
    management.innerHTML='<button type="button" class="button button-secondary" id="cv_rename_open" data-icon="settings">Rename</button>'+
      '<button type="button" class="button button-secondary" id="cv_archive_open" data-icon="folder-open">Archive / Delete</button>'+
      '<label class="cv-inline cv-archived-toggle"><input type="checkbox" id="cv_show_archived">Show archived</label>';
    registry.querySelector('.cv-card-head').append(management);
    $('cv_measure_mount').querySelector('.cv-dimension-card').classList.add('cv-existing-pair-editor');
    $('cv_geometry_mount').querySelector('.cv-resolved-card').classList.add('cv-resolved-visible');
    // Keep established camera / ROI / HIFIE nodes, but put their settings in
    // nested disclosures under the single full-width camera workspace.
    const calibrationPanel=$('cv_workspace_panels').querySelector('.cv-calibration-panel');
    $('cv_camera_accordion_mount').append(calibrationPanel);
    calibrationPanel.classList.remove('card','cv-workspace-panel');
    const accordion=(name,icon,content,expanded=false)=>{
      const details=document.createElement('details');details.className='cv-subaccordion';details.open=expanded;
      const summary=document.createElement('summary');summary.dataset.icon=icon;summary.textContent=name;
      details.append(summary,content);return details;
    };
    calibrationPanel.append(accordion('Optical profile & vision worker','sliders',$('cv_camera_calib_mount')));
    calibrationPanel.append(accordion('Relative camera calibration','crosshair',$('cv_relative_panel')));
    calibrationPanel.append(accordion('ArUco / planar calibration & analysis ROI','scan',$('cv_aruco_mount')));
    const mappings=$('cv_measure_mount').querySelector('.cv-existing-pair-editor');
    $('cv_measure_mount').append(accordion('Advanced named-reference mappings','settings',mappings));
    grid.remove();calibration.remove();
    window.DigiFlotIcons?.decorate(document);
  }

  function applyCanvasViewport(){
    const img=$('camera_image');
    img.style.transform='translate('+state.panX+'px,'+state.panY+'px) scale('+state.zoom+')';
    img.style.transformOrigin='center center';
    $('cv_zoom_fit').title=state.zoom===1?'Fit image':('Current zoom: '+Math.round(state.zoom*100)+'% · reset zoom');
    renderSelection();drawWorkspaceMeasurements();
  }
  function changeZoom(next){
    const value=Math.max(1,Math.min(8,Number(next)||1));
    if(value===1){state.panX=0;state.panY=0;}
    state.zoom=value;applyCanvasViewport();
  }
  function setWorkspaceTool(mode){
    state.uiTool=mode;
    for(const id of ['cv_pick_measure','cv_relative_pick_source','cv_relative_pick_reference','cv_relative_pick_target','cv_pan_mode']){
      const button=$(id);button.classList.toggle('cv-active-tool',
        (id==='cv_pick_measure'&&mode==='measure')||(id==='cv_pan_mode'&&mode==='pan')||
        (id==='cv_relative_pick_source'&&mode==='relative_source')||
        (id==='cv_relative_pick_reference'&&mode==='relative_reference')||
        (id==='cv_relative_pick_target'&&mode==='relative_target'));
      button.setAttribute('aria-pressed',String(button.classList.contains('cv-active-tool')));
    }
    $('image_help').textContent=mode==='pan'?'Drag to pan. Wheel to zoom. Fit returns to the original view.':
      mode==='measure'?'Click two EXISTING physical reference dots; no new references will be created.':
      mode==='relative_source'?'On the calibrated source plane, select two points spanning the known length.':
      mode.startsWith('relative_')?'Select two endpoints on the destination camera frame for this measurement.':
      state.view==='rectified'?'Rectified plane · place references or drag the analysis ROI.':
      'Raw camera · drag the sensor ROI. Use an existing saved calibration when available.';
  }
  function showWorkspaceStatus(){
    text('cv_view_status',state.view==='rectified'?'Rectified physical plane':
      state.imageSpace==='undistorted'?'Optically corrected camera image':'Raw camera image');
    const association=state.association,relative=state.relativeRecord;
    const valid=association&&association.camera_revision===state.profile?.revision&&
      association.cell_revision===state.cell?.revision;
    const status=valid?'Saved ArUco · metric':association?'Saved ArUco · review revisions':
      relative?'Relative scale · '+(relative.valid===false?'outdated':'estimated'):'Pixels only · calibrate';
    text('cv_calibration_status',status);
    text('cv_saved_summary',valid?'Saved ArUco homography is ready. Current markers are not needed. Re-detection is optional.':
      association?'Saved ArUco is available, but its camera or cell revision changed. Review before using metric results.':
      relative?'Relative camera estimate is saved independently. The ArUco association was not altered.':
      'No ArUco association for this camera. Select a calibrated source camera below to estimate its scale.');
    $('cv_rectified_view').disabled=!association;
    $('cv_reuse_saved_aruco').hidden=!association||valid;
    $('cv_reuse_saved_aruco').disabled=!association||valid;
    $('cv_raw_view').classList.toggle('cv-active-tool',state.view==='raw'&&state.imageSpace==='raw');
    $('cv_undistorted_view').classList.toggle('cv-active-tool',state.imageSpace==='undistorted');
    $('cv_rectified_view').classList.toggle('cv-active-tool',state.view==='rectified');
    const side=state.cameraRoles.side,top=state.cameraRoles.top;
    for(const [id,cam] of [['cv_side_camera',side],['cv_top_camera',top]]){
      const button=$(id);button.disabled=cam==null;
      button.classList.toggle('cv-active-tool',cam!=null&&String(cam)===String(state.cameraId));
    }
  }

  function drawWorkspaceMeasurements(){
    let overlay=$('cv_measure_overlay');
    if(!overlay){overlay=document.createElement('div');overlay.id='cv_measure_overlay';
      $('image_surface').append(overlay);}
    overlay.replaceChildren();
    const img=$('camera_image'),r=img.getBoundingClientRect(),outer=$('image_surface').getBoundingClientRect();
    if(!img.naturalWidth||!r.width)return;
    const ids=[$('cv_measure_from').value,$('cv_measure_to').value];
    const currentSource=String(state.cameraId)===String(state.relativeSourceCameraId);
    const currentTarget=String(state.cameraId)===String(state.relativeDestinationCameraId);
    const items=[
      {points:ids.every(Boolean)?ids.map(referencePointInView):[],color:'#49b8ef',label:'Physical dimension',
       axis:$('cv_measure_axis').value},
      {points:currentSource&&state.view==='rectified'?state.relativeSourcePoints:[],
       color:'#eab25f',label:'Calibrated source length',axis:$('cv_relative_source_axis').value},
      {points:currentTarget?state.relativePairs.reference:[],
       color:'#f2a74d',label:'Reference on destination',axis:$('cv_relative_reference_axis').value},
      {points:currentTarget?state.relativePairs.target:[],
       color:'#87d7b3',label:'Target dimension',axis:$('cv_relative_target_axis').value}
    ];
    const addLine=(a,b,color,guide=false)=>{
      const line=document.createElement('div');line.className='cv-measure-line'+(guide?' cv-projection-guide':'');
      const length=Math.hypot(b[0]-a[0],b[1]-a[1]);
      Object.assign(line.style,{left:a[0]+'px',top:a[1]+'px',width:length+'px',
        transform:'rotate('+Math.atan2(b[1]-a[1],b[0]-a[0])+'rad)',background:color});
      overlay.append(line);
    };
    for(const entry of items){
      const ps=(entry.points||[]).filter(p=>Array.isArray(p)&&p.every(Number.isFinite));
      const xy=ps.map(p=>[r.left-outer.left+p[0]*r.width,r.top-outer.top+p[1]*r.height]);
      for(const [i,p] of xy.entries()){
        const marker=document.createElement('span');marker.className='cv-measure-pin';
        marker.style.left=p[0]+'px';marker.style.top=p[1]+'px';marker.style.background=entry.color;
        marker.title=entry.label+' · point '+(i+1);overlay.append(marker);
      }
      if(xy.length!==2)continue;
      const [a,b]=xy;
      if(entry.axis==='horizontal'){
        addLine([a[0],a[1]],[b[0],a[1]],entry.color);
        addLine([b[0],a[1]],b,entry.color,true);
      }else if(entry.axis==='vertical'){
        addLine([a[0],a[1]],[a[0],b[1]],entry.color);
        addLine([a[0],b[1]],b,entry.color,true);
      }else addLine(a,b,entry.color);
    }
  }

  function captureWorkspacePoint(p){
    const mode=state.uiTool;
    if(mode==='measure'){
      const nearest=nearestReferenceOnImage(p);
      if(!nearest){
        text('cv_measure_status','No saved reference near that click. Use the existing markers, or place a named physical reference first.');
        return;
      }
      let ids=state.measurePointIds||[];
      if(ids.length>=2)ids=[];
      if(ids.includes(nearest.id)){text('cv_measure_status','Select two different physical references.');return;}
      ids.push(nearest.id);state.measurePointIds=ids;
      $('cv_measure_from').value=ids[0]||'';$('cv_measure_to').value=ids[1]||'';
      updateMeasurementPreview();return;
    }
    if(mode==='relative_source'){
      if(state.view!=='rectified'||!state.plane){
        text('cv_relative_source_status','Select a rectified image of the calibrated source.');return;
      }
      if(state.relativeSourcePoints.length>=2)state.relativeSourcePoints=[];
      const nearest=nearestReferenceOnImage(p);
      state.relativeSourcePoints.push(nearest?.point||p);
      if(state.relativeSourcePoints.length===2){
        state.relativeSourceCm=state.relativeSourcePoints.map(planePoint);
        state.relativeSourceCalibrationId=state.capturedCalibrationId;
        state.relativeSourceCameraRevision=state.capturedProfileRevision;
        const axis=$('cv_relative_source_axis').value;
        const length=projectedMetricValue(...state.relativeSourceCm,axis);
        text('cv_relative_source_status',length.toFixed(2)+' mm · '+axis+
          ' · source '+state.relativeSourceCameraId+' · next: pick the same length on destination');
        text('cv_relative_readout','Calibrated source length: '+length.toFixed(2)+' mm. Now select its matching endpoints on the other camera.');
      }else text('cv_relative_source_status','First source endpoint selected. Click the second.');
    }else if(mode==='relative_reference'||mode==='relative_target'){
      if(String(state.cameraId)!==String(state.relativeDestinationCameraId)){
        text('cv_relative_readout','Switch to the destination camera before picking its reference or target.');return;
      }
      const key=mode==='relative_reference'?'reference':'target',pair=state.relativePairs[key];
      if(pair.length>=2)pair.length=0;
      const nearest=nearestReferenceOnImage(p);pair.push(nearest?.point||p);
      text('cv_relative_readout',pair.length===1?'First '+key+' endpoint selected. Click the second.':
        'Selected '+key+' length on destination camera. '+state.relativePairs.reference.length+
        '/2 reference points, '+state.relativePairs.target.length+'/2 target points.');
    }
    drawWorkspaceMeasurements();relativeReadout();
  }

  function setCellForm(cell) {
    state.cell = cell;
    state.named = JSON.parse(JSON.stringify(cell?.reference_points || {default_reference_id:'outlet_level',points:[
      {id:'outlet_level',name:'Outlet level',type:'custom',position_cm:null,direction:'up',source:'unset'},
      {id:'aruco_reference',name:'ArUco reference',type:'aruco',position_cm:null,direction:'up',source:'automatic'},
      {id:'cell_top',name:'Cell top',type:'top',position_cm:null,direction:'down',source:'unset'},
      {id:'cell_bottom',name:'Cell bottom',type:'bottom',position_cm:null,direction:'up',source:'unset'}]}));
    state.activePoint=null;state.namedDirty=false;renderNamedPoints();
    state.dimensionMeasurements=cell?.dimension_measurements||{revision:0,pairs:{}};
    renderCellDimensionPairs();renderCellResolvedDimensions();renderVolumeEditor();
    $('cell_name').value = cell?.name || '';
    $('cell_volume').value = cell?.working_volume_l ?? '';
    const g = cell?.geometry || {};
    $('cell_shape').value = g.shape || 'custom';
    $('cell_height').value = g.height_mm ?? '';
    $('cell_width').value = g.width_mm ?? '';
    $('cell_depth').value = g.depth_mm ?? '';
    $('cell_collection_height').value = g.collection_height_mm ?? '';
    renderCellPhoto(cell);
    const ref=cell?.vertical_reference || {};
    $('cell_reference_mode').value = ref.mode || 'aruco_bottom';
    $('cell_top_y_cm').value = ref.cell_top_y_cm ?? '';
    $('cell_bottom_y_cm').value = ref.cell_bottom_y_cm ?? '';
    $('save_cell_reference').disabled = !cell?.id;
    text('cell_reference_status',cell?.id ?
      'Reference revision ' + (ref.revision ?? 0) + ' (does not invalidate ArUco)' :
      'Save the cell before its physical reference');
    const l = cell?.marker_layout || {marker_ids:[0,1,2], marker_size_cm:2, span_cm:14};
    l.marker_ids.forEach((v,i) => { $(`marker_${i}`).value = v; });
    $('marker_size').value = l.marker_size_cm;
    $('marker_span').value = l.span_cm;
  }


  const dimensionLabels={height_mm:'Height',width_mm:'Width / diameter',depth_mm:'Depth',collection_height_mm:'Collection height'};
  function renderCellResolvedDimensions(){
    const data=state.cell?.resolved_dimensions||{},dimensions=data.dimensions||{};
    const sources={measured:'Measured · ArUco',derived:'Derived · references',nominal:'Nominal fallback',
      relative_estimate:'Relative camera · estimated',relative_geometry:'Estimated / relative geometry',
      measured_geometry:'Measured geometry',mixed_geometry:'Mixed nominal / measured',nominal_geometry:'Nominal geometry'};
    const fmt=(value,digits=1)=>Number(value).toLocaleString(undefined,{maximumFractionDigits:digits});
    const rows=Object.entries(dimensionLabels).map(([field,label])=>{
      const item=dimensions[field];
      return '<div class="cv-metric"><span>'+label+'</span><strong>'+(item?fmt(item.value_mm)+' mm':'—')+
        '</strong><small>'+(item?sources[item.source]||item.source:'No dimension available')+'</small></div>';
    });
    rows.push('<div class="cv-metric"><span>Geometric cross-section</span><strong>'+
      (data.geometric_area_cm2!=null?fmt(data.geometric_area_cm2,2)+' cm²':'—')+
      '</strong><small>'+(sources[data.geometric_area_source]||'Not available · effective area uncalibrated')+'</small></div>');
    rows.push('<div class="cv-metric"><span>Geometric capacity</span><strong>'+
      (data.geometric_capacity_l!=null?fmt(data.geometric_capacity_l,3)+' L':'—')+
      '</strong><small>Geometric estimate · not the working volume</small></div>');
    if(data.effective_area_range_cm2){
      const [low,high]=data.effective_area_range_cm2;
      rows.push('<div class="cv-metric"><span>Calibrated effective area</span><strong>'+
        fmt(low,2)+(Math.abs(high-low)>1e-8?' – '+fmt(high,2):'')+' cm²</strong>'+
        '<small>Experimental V(h) · varies by height</small></div>');
    }
    $('cell_resolved_dimensions').innerHTML=rows.join('');
  }

  // Preserve old reference IDs in storage: a previously calibrated sensor may still use them.
  // Hide only exact duplicate display aliases, never two positions that disagree.
  function referenceDisplayModel(points=state.named?.points||[]){
    const fixed=new Map(points.filter(p=>p&&['cell_top','cell_bottom'].includes(p.id)).map(p=>[p.id,p]));
    const aliases=new Map();
    const samePosition=(a,b)=>a==null&&b==null||Array.isArray(a)&&Array.isArray(b)&&
      a.length===2&&b.length===2&&a.every((v,i)=>Math.abs(Number(v)-Number(b[i]))<1e-6);
    const targetFor=point=>{
      const name=String(point.name||'').trim().toLowerCase();
      return name==='cell top'?'cell_top':name==='cell bottom'?'cell_bottom':null;
    };
    for(const point of points){
      const target=targetFor(point),canonicalPoint=fixed.get(target);
      if(!target||point.id===target||!canonicalPoint)continue;
      if(point.direction===canonicalPoint.direction &&
         samePosition(point.position_cm,canonicalPoint.position_cm)){
        aliases.set(point.id,target);
      }
    }
    const visible=points.filter(point=>!aliases.has(point.id));
    const label=point=>{
      const target=targetFor(point);
      return target&&point.id!==target ?
        point.name+' (legacy · check position/direction)' : point.name;
    };
    return {visible,aliases,label,canonicalId:id=>aliases.get(id)||id};
  }

  const measurementAxisDefault={height_mm:'vertical',width_mm:'horizontal',
    depth_mm:'vertical',collection_height_mm:'vertical'};
  function renderCellDimensionPairs(){
    const host=$('cell_dimension_pairs'),view=referenceDisplayModel();
    const opts=[{id:'',name:'Not mapped'},...view.visible].map(p=>
      '<option value="'+esc(p.id)+'">'+esc(view.label(p))+'</option>').join('');
    const pairs=state.dimensionMeasurements?.pairs||{};
    host.innerHTML=['height_mm','width_mm','depth_mm','collection_height_mm'].map(field=>{
      const pair=pairs[field]||{};
      return '<div class="cv-dimension-pair" data-dimension-field="'+field+'"><strong>'+dimensionLabels[field]+'</strong>'+
        '<div class="cv-two"><label>From<select data-dimension-end="from_id">'+opts+'</select></label>'+
        '<label>To<select data-dimension-end="to_id">'+opts+'</select></label></div>'+
        '<label>Measurement axis<select data-dimension-end="axis">'+
        ['horizontal','vertical','direct'].map(axis=>'<option value="'+axis+'">'+
        ({horizontal:'Horizontal ΔX',vertical:'Vertical ΔY',direct:'Direct distance'}[axis])+'</option>').join('')+
        '</select></label></div>';
    }).join('');
    for(const row of host.querySelectorAll('[data-dimension-field]')){
      const pair=pairs[row.dataset.dimensionField]||{};
      for(const select of row.querySelectorAll('[data-dimension-end]'))
        select.value=select.dataset.dimensionEnd==='axis'?(pair.axis||'direct'):
          view.canonicalId(pair[select.dataset.dimensionEnd]||'');
    }
    $('save_dimension_pairs').disabled=!state.cellId;
    text('dimension_revision',state.cellId?
      'Measured mapping revision '+(state.dimensionMeasurements?.revision||0):'Save the cell first');
    renderMeasurementSelectors();
  }

  function renderMeasurementSelectors(){
    const field=$('cv_measure_target').value, pair=(state.dimensionMeasurements?.pairs||{})[field]||{};
    const view=referenceDisplayModel(),refOptions='<option value="">Select existing point</option>'+
      view.visible.map(point=>'<option value="'+esc(point.id)+'">'+esc(view.label(point))+
        (point.position_cm?'':' · not placed')+'</option>').join('');
    const from=$('cv_measure_from'),to=$('cv_measure_to');
    const before=[from.value,to.value];
    from.innerHTML=refOptions;to.innerHTML=refOptions;
    const defaults=field==='height_mm'?['cell_top','cell_bottom']:['',''];
    const values=[pair.from_id||defaults[0],pair.to_id||defaults[1]];
    from.value=values[0];to.value=values[1];
    if(!from.value)from.value=before[0]&&[...from.options].some(o=>o.value===before[0])?before[0]:'';
    if(!to.value)to.value=before[1]&&[...to.options].some(o=>o.value===before[1])?before[1]:'';
    $('cv_measure_axis').value=pair.axis||measurementAxisDefault[field];
    state.measurePointIds=[from.value,to.value].filter(Boolean);
    updateMeasurementPreview();
  }

  function physicalReferencePosition(refId,visited=new Set()){
    if(!refId||visited.has(refId))return null;
    visited.add(refId);
    const point=state.named?.points?.find(p=>p.id===refId);
    if(!point)return null;
    if(refId==='aruco_reference'){
      return [0,Math.max(Number(state.cell?.marker_layout?.span_cm||14),
        Number(state.cell?.marker_layout?.marker_size_cm||2))];
    }
    if(point.source==='derived'&&point.derived_from){
      const base=physicalReferencePosition(point.derived_from,visited);
      return base&&point.offset_y_cm!=null?[base[0],base[1]+Number(point.offset_y_cm)]:null;
    }
    return point.position_cm||null;
  }
  function referencePointInView(id){
    if(!id)return null;
    if(state.view==='rectified'&&state.plane){
      const point=physicalReferencePosition(id);if(!point)return null;
      const lo=state.plane.min_xy_cm,hi=state.plane.max_xy_cm;
      return [(point[0]-lo[0])/(hi[0]-lo[0]),(point[1]-lo[1])/(hi[1]-lo[1])];
    }
    const observation=state.cell?.reference_observations?.[String(state.cameraId)]?.observations?.[id];
    return observation&&observation.image_space===state.imageSpace&&
      observation.camera_revision===state.profile?.revision?observation.position_norm:null;
  }
  function nearestReferenceOnImage(point){
    const img=$('camera_image'),r=img.getBoundingClientRect();
    let closest=null,dist=Infinity;
    for(const ref of referenceDisplayModel().visible){
      const p=referencePointInView(ref.id);if(!p)continue;
      const d=Math.hypot((p[0]-point[0])*r.width,(p[1]-point[1])*r.height);
      if(d<dist){dist=d;closest={id:ref.id,point:p};}
    }
    return dist<=24?closest:null;
  }
  function projectedMetricValue(a,b,axis='direct'){
    const dx=Math.abs(a[0]-b[0]),dy=Math.abs(a[1]-b[1]);
    return (axis==='horizontal'?dx:axis==='vertical'?dy:Math.hypot(dx,dy))*10;
  }
  function updateMeasurementPreview(){
    const from=$('cv_measure_from').value,to=$('cv_measure_to').value,axis=$('cv_measure_axis').value;
    state.measurePointIds=[from,to].filter(Boolean);
    const a=physicalReferencePosition(from),b=physicalReferencePosition(to);
    if(a&&b&&from!==to){
      text('cv_measure_status',dimensionLabels[$('cv_measure_target').value]+': '+
        projectedMetricValue(a,b,axis).toFixed(2)+' mm · '+axis+' · existing references');
    }else text('cv_measure_status',from&&to?'References are not metrically placed on this cell.':
      'Choose two named points, or click two existing markers in the camera.');
    drawWorkspaceMeasurements();
  }

  async function saveCellDimensionPairs(){
    if(!state.cellId)throw new Error('Save the cell first');
    if(state.namedDirty)throw new Error('Save named references before assigning measured dimensions.');
    const pairs={};
    for(const row of $('cell_dimension_pairs').querySelectorAll('[data-dimension-field]')){
      const a=row.querySelector('[data-dimension-end="from_id"]').value;
      const b=row.querySelector('[data-dimension-end="to_id"]').value;
      if(a||b){
        if(!a||!b||a===b)throw new Error('Choose two different reference points for '+dimensionLabels[row.dataset.dimensionField]);
        pairs[row.dataset.dimensionField]={from_id:a,to_id:b,
          axis:row.querySelector('[data-dimension-end="axis"]').value};
      }
    }
    state.dimensionMeasurements=await api('/cells/'+encodeURIComponent(state.cellId)+'/dimensions',{
      method:'PUT',body:{pairs,expected_revision:state.dimensionMeasurements?.revision||0}});
    state.cell=await api('/cells/'+encodeURIComponent(state.cellId));
    state.dimensionMeasurements=state.cell.dimension_measurements;
    renderCellDimensionPairs();renderCellResolvedDimensions();
    toast('Measured geometry updated independently from nominal parameters.');
  }

  function volumePointRow(point={}){
    const value=(key)=>point[key]==null?'':esc(point[key]);
    return '<div class="cv-volume-point"><input type="number" step="any" data-fill="height_cm" value="'+value('height_cm')+
      '" aria-label="Height above selected reference (cm)" placeholder="cm">'+
      '<input type="number" step="any" min="0" data-fill="volume_l" value="'+value('volume_l')+
      '" aria-label="Known volume (L)" placeholder="L">'+
      '<button class="button button-secondary" type="button" data-volume-remove data-icon="x" aria-label="Remove fill point">×</button></div>';
  }

  function renderVolumeEditor(){
    const curve=state.cell?.volume_calibration||{},view=referenceDisplayModel();
    const datum=$('cell_volume_datum'),previous=view.canonicalId(curve.datum_reference_id||'cell_bottom');
    datum.innerHTML=view.visible.map(point=>'<option value="'+esc(point.id)+'">'+esc(view.label(point))+
      (point.position_cm==null&&point.source!=='automatic'?' · unplaced':'')+'</option>').join('');
    if(view.visible.some(point=>point.id===previous))datum.value=previous;
    $('cell_volume_points').innerHTML=(curve.raw_points?.length?curve.raw_points:[{}]).map(volumePointRow).join('');
    $('add_volume_point').disabled=!state.cellId;
    $('save_volume_curve').disabled=!state.cellId;
    const valid=curve.valid&&curve.points?.length>1;
    const label=!state.cellId?'Save the cell first to calibrate volume.' :
      !curve.points?.length?'No experimental V(h) calibration. Geometric fallback is used if available.' :
      !valid?'Reference points changed or became unavailable. Review and save the calibration again.' :
      'Current V(h) calibration · revision '+curve.revision+' · '+(curve.points.length-1)+
      ' known fills · interpolation by segments; linear extrapolation above last point'+
      (curve.bottom_source==='nominal_derived'?' · Cell bottom inferred from nominal height.':'.');
    text('cell_volume_status',label);
    const target=$('cell_volume_plot');
    if(!valid){target.replaceChildren();return;}
    const source=curve.points, maxH=Math.max(1,source.at(-1).height_cm),maxV=Math.max(.001,source.at(-1).volume_l);
    const X=h=>38+290*h/maxH,Y=v=>145-113*v/maxV;
    const path=source.map((p,i)=>(i?'L':'M')+X(p.height_cm).toFixed(1)+' '+Y(p.volume_l).toFixed(1)).join(' ');
    const circles=source.map(p=>'<circle cx="'+X(p.height_cm).toFixed(1)+'" cy="'+Y(p.volume_l).toFixed(1)+'" r="3.5"/>').join('');
    target.innerHTML='<svg viewBox="0 0 360 175" role="img" aria-label="Known fill volume from cell bottom">'+
      '<path class="cv-volume-axis" d="M38 20 V145 H338"/>'+
      '<path class="cv-volume-line" d="'+path+'"/><g class="cv-volume-points-markers">'+circles+'</g>'+
      '<text x="9" y="23">V (L)</text><text x="228" y="168">Height (cm)</text>'+
      '<text x="9" y="140">0</text><text x="315" y="159">'+maxH.toFixed(1)+'</text>'+
      '</svg>';
  }

  async function saveVolumeCurve(){
    if(!state.cellId)throw new Error('Save the cell first.');
    if(state.namedDirty)throw new Error('Save named references before calibrating V(h).');
    const points=[...$('cell_volume_points').querySelectorAll('.cv-volume-point')].map(row=>{
      const height=row.querySelector('[data-fill="height_cm"]').value.trim();
      const volume=row.querySelector('[data-fill="volume_l"]').value.trim();
      if(!height||!volume)throw new Error('Every fill point needs height (cm) and known volume (L).');
      return {height_cm:Number(height),volume_l:Number(volume)};
    });
    const curve=state.cell?.volume_calibration||{};
    await api('/cells/'+encodeURIComponent(state.cellId)+'/volume-calibration',{
      method:'PUT',body:{datum_reference_id:$('cell_volume_datum').value,points,
        expected_revision:curve.revision||0}});
    state.cell=await api('/cells/'+encodeURIComponent(state.cellId));
    renderCellResolvedDimensions();renderVolumeEditor();
    toast('Cell volume-height calibration saved. Future HIFIE volume estimates will prefer this curve.');
  }

  function renderNamedPoints() {
    const record=state.named||{points:[]},list=$('named_reference_list'),view=referenceDisplayModel(record.points);
    list.innerHTML=view.visible.map(p=>{
      const locked=['aruco_reference','outlet_level','cell_top','cell_bottom'].includes(p.id);
      const observation=state.cell?.reference_observations?.[String(state.cameraId)]?.observations?.[p.id];
      const pos=p.source==='automatic'?'Automatic from markers':p.position_cm?
        p.position_cm.map(n=>Number(n).toFixed(2)).join(', ')+' cm' :
        observation?'Observed on selected camera · '+observation.image_space:'No measured coordinates';
      return '<div class="cv-named-point'+(state.activePoint===p.id?' active':'')+'" data-ref-id="'+esc(p.id)+'">'+
        '<label><input type="radio" name="ref_default" value="'+esc(p.id)+'" '+(view.canonicalId(record.default_reference_id)===p.id?'checked':'')+' title="Default reference"></label>'+
        '<div class="cv-named-main"><input data-ref-field="name" value="'+esc(p.name)+'" '+(locked?'disabled':'')+' maxlength="80" aria-label="Name">'+
        '<small>'+esc(pos)+'</small><div class="cv-named-controls"><select data-ref-field="type" '+(locked?'disabled':'')+'>'+
        ['custom','top','bottom','aruco'].map(x=>'<option value="'+x+'" '+(x===p.type?'selected':'')+'>'+x+'</option>').join('')+
        '</select><select data-ref-field="direction" '+(locked?'disabled':'')+'>'+
        ['up','down'].map(x=>'<option value="'+x+'" '+(x===p.direction?'selected':'')+'>'+ (x==='up'?'Height ↑':'Depth ↓')+'</option>').join('')+
        '</select></div>'+
        '<div class="cv-named-controls"><select data-ref-field="source" '+(locked?'disabled':'')+'>'+
        ['unset','image_selection','measured','derived','reused','automatic'].map(x=>
            '<option value="'+x+'" '+(x===p.source?'selected':'')+'>'+x.replaceAll('_',' ')+'</option>').join('')+
        '</select>'+
        (p.source==='derived'?
            '<select data-ref-field="derived_from">'+record.points.filter(other=>other.id!==p.id).map(other=>
                '<option value="'+esc(other.id)+'" '+(other.id===p.derived_from?'selected':'')+'>'+esc(other.name)+'</option>').join('')+
            '</select></div><label class="cv-named-coord">ΔY from reference (cm) <input data-ref-field="offset_y_cm" type="number" step="any" value="'+esc(p.offset_y_cm??0)+'"></label>' :
            '</select></div><div class="cv-named-coord"><label>X cm <input data-ref-field="x_cm" type="number" step="any" value="'+esc(p.position_cm?.[0]??'')+'" placeholder="0"></label>'+
            '<label>Y cm <input data-ref-field="y_cm" type="number" step="any" value="'+esc(p.position_cm?.[1]??'')+'" placeholder="Measured level"></label></div>')+
        '</div><div class="cv-named-actions"><button class="button button-secondary" data-icon="'+(state.activePoint===p.id?'x':'crosshair')+'" data-icon-only data-ref-action="place" type="button" '+(p.id==='aruco_reference'?'disabled':'')+'>'+
        (state.activePoint===p.id?'Cancel':'Place')+'</button>'+
        (locked?'':'<button class="button button-secondary" data-icon="trash-2" data-icon-only data-ref-action="delete" type="button">Remove</button>')+'</div></div>';
    }).join('');
    window.DigiFlotIcons?.decorate(list);
    text('reference_status',!state.cellId?'Save the cell first':state.activePoint?
      state.view==='rectified'?
        'Click the reference on the rectified physical plane; coordinates will be saved in cm.':
        'Click the reference in this camera frame; it will be saved as a camera observation, without changing ArUco coordinates.':
      'Default: '+(view.visible.find(p=>p.id===view.canonicalId(record.default_reference_id))?.name||'—')+
      (state.namedDirty?' · Unsaved changes':''));
    $('reference_save').disabled=!state.cellId;
    drawNamedPoints();
  }

  function drawNamedPoints(){
    const layer=$('reference_overlays'),img=$('camera_image');layer.replaceChildren();
    if(!img.naturalWidth||!state.named)return;
    const rect=img.getBoundingClientRect(),outer=$('image_surface').getBoundingClientRect();
    Object.assign(layer.style,{left:rect.left-outer.left+'px',top:rect.top-outer.top+'px',
      width:rect.width+'px',height:rect.height+'px'});
    for(const point of referenceDisplayModel().visible){
      const xy=referencePointInView(point.id);
      if(!xy||!xy.every(Number.isFinite)||xy.some(v=>v<0||v>1))continue;
      const dot=document.createElement('span');dot.className='cv-physical-pin';
      if(point.id===state.activePoint||state.measurePointIds.includes(point.id))dot.classList.add('selected');
      dot.style.left=100*xy[0]+'%';dot.style.top=100*xy[1]+'%';
      dot.title=point.name+' · '+(state.view==='rectified'?'physical cm':'camera observation');
      layer.append(dot);
    }
  }

  async function saveNamedPoints() {
    if(!state.cellId)throw new Error('Save the cell first');
    state.named=await api('/cells/'+encodeURIComponent(state.cellId)+'/reference-points',
      {method:'PUT',body:state.named});state.namedDirty=false;
    state.cell=await api('/cells/'+encodeURIComponent(state.cellId));
    renderNamedPoints();renderCellDimensionPairs();renderCellResolvedDimensions();renderVolumeEditor();
    toast('Named references saved (revision '+state.named.revision+').');
  }

  async function reuseNamedPoints() {
    if(!state.cellId)throw new Error('Select a cell');
    if(!window.confirm('Confirm the ArUco ruler did not move relative to this cell. Reusing points otherwise gives incorrect coordinates.'))return;
    state.named=await api('/cells/'+encodeURIComponent(state.cellId)+'/reference-points');
    state.namedDirty=false;state.activePoint=null;
    if(state.view!=='rectified')await rectifiedSnapshot();
    renderNamedPoints();toast('Reprojected named points with the current ArUco geometry.');
  }

  function addNamedPoint() {
    if(!state.named)throw new Error('Select a cell first');
    const name=$('reference_new_name').value.trim(),type=$('reference_new_type').value;
    if(!name)throw new Error('Enter a reference name');
    if(['cell top','cell bottom','outlet level','aruco reference'].includes(name.toLowerCase()))
      throw new Error('This name is reserved for a fixed physical reference. Edit its coordinates instead.');
    const id='ref_'+Math.random().toString(36).slice(2,12);
    state.named.points.push({id,name,type,direction:type==='top'?'down':'up',
      position_cm:null,source:'unset'});
    state.activePoint=id;state.namedDirty=true;$('reference_new_name').value='';
    renderNamedPoints();
  }

  async function handleNamedPoint(event) {
    const row=event.target.closest('[data-ref-id]');if(!row||!state.named)return;
    const point=state.named.points.find(p=>p.id===row.dataset.refId);if(!point)return;
    if(event.target.name==='ref_default'){
      state.named.default_reference_id=point.id;state.namedDirty=true;renderNamedPoints();return;
    }
    const action=event.target.dataset.refAction;
    if(action==='place'){
      state.activePoint=state.activePoint===point.id?null:point.id;
      // In Rectified mode the click edits ArUco-local cm; in Raw/Undistorted
      // it stores a camera-specific observation without changing physical cm.
      renderNamedPoints();return;
    }
    if(action==='delete'){
      if(['aruco_reference','outlet_level','cell_top','cell_bottom'].includes(point.id))
        throw new Error('This physical reference is mandatory; clear its coordinates instead.');
      state.named.points=state.named.points.filter(p=>p.id!==point.id);
      if(state.named.default_reference_id===point.id)state.named.default_reference_id='aruco_reference';
      if(state.activePoint===point.id)state.activePoint=null;
      state.namedDirty=true;renderNamedPoints();return;
    }
    const field=event.target.dataset.refField;
    if(field==='x_cm'||field==='y_cm'){
      const value=event.target.value.trim();
      const previous=point.position_cm||[0,null];
      const x=field==='x_cm'?(value===''?0:Number(value)):previous[0];
      const y=field==='y_cm'?(value===''?null:Number(value)):previous[1];
      point.position_cm=y==null?null:[x,y];point.source=point.position_cm?'measured':'unset';
      state.namedDirty=true;renderNamedPoints();return;
    }
    if(field==='offset_y_cm'){
      point.offset_y_cm=event.target.value.trim()===''?null:Number(event.target.value);
      state.namedDirty=true;renderNamedPoints();return;
    }
    if(field&&field in point){
      point[field]=event.target.value;
      if(field==='type')point.direction=point.type==='top'?'down':'up';
      if(field==='source'&&point.source==='derived'){
        point.position_cm=null;
        point.derived_from=state.named.points.find(other=>other.id!==point.id)?.id||null;
        point.offset_y_cm=0;
      }
      state.namedDirty=true;
      if(field!=='name')renderNamedPoints();
      else text('reference_status','Unsaved name · Save references to apply');
    }
  }

  function cellPayload() {
    const shape = $('cell_shape').value;
    return {id: state.cellId || undefined, name: $('cell_name').value.trim(),
      working_volume_l: numeric('cell_volume'),
      geometry: {shape, height_mm:numeric('cell_height'), width_mm:numeric('cell_width'), depth_mm:numeric('cell_depth'), collection_height_mm:numeric('cell_collection_height')},
      marker_layout: {dictionary:'DICT_4X4_50', marker_ids:[0,1,2].map(i => Number($(`marker_${i}`).value)),
        marker_size_cm:numeric('marker_size'), span_cm:numeric('marker_span')}};
  }

  const cellImageFallback='/static/img/flotation-cell-placeholder.svg';
  let cropSource=null,cropPan={x:0,y:0},dragStart=null;
  function renderCellPhoto(cell){
    const hasPhoto=Boolean(cell?.thumbnail?.sha256),image=$('cell_thumbnail_preview');
    image.src=hasPhoto?`/api/vision/cells/${encodeURIComponent(cell.id)}/thumbnail?v=${cell.thumbnail.revision}`:cellImageFallback;
    image.onerror=()=>{image.onerror=null;image.src=cellImageFallback};
    $('cell_photo_status').textContent=hasPhoto?`Photo r${cell.thumbnail.revision}`:'No photo assigned';
    $('capture_cell_photo').disabled=!cell?.id;
    $('remove_cell_photo').hidden=!hasPhoto;
  }
  function drawCrop(){
    const canvas=$('cell_photo_canvas'),ctx=canvas.getContext('2d');
    ctx.clearRect(0,0,512,512);ctx.fillStyle='#f3f6f8';ctx.fillRect(0,0,512,512);
    if(!cropSource)return;
    const zoom=Number($('photo_zoom').value),scale=Math.max(512/cropSource.width,512/cropSource.height)*zoom;
    const w=cropSource.width*scale,h=cropSource.height*scale;
    const marginX=Math.max(0,(w-512)/2),marginY=Math.max(0,(h-512)/2);
    cropPan.x=Math.max(-marginX,Math.min(marginX,cropPan.x));
    cropPan.y=Math.max(-marginY,Math.min(marginY,cropPan.y));
    ctx.drawImage(cropSource,(512-w)/2+cropPan.x,(512-h)/2+cropPan.y,w,h);
  }
  async function takePhotoFrame(){
    const camera=$('photo_camera').value;if(!camera)throw Error('Choose a camera');
    $('photo_capture_frame').disabled=true;
    try{
      // One frame from the existing camera API, no new stream and no overlays.
      const result=await api(`/cameras/${encodeURIComponent(camera)}/snapshot?show_grid=false`);
      if(!result.jpeg_base64)throw Error('Camera did not provide a frame');
      cropSource=new Image();cropPan={x:0,y:0};$('photo_zoom').value='1';
      await new Promise((resolve,reject)=>{cropSource.onload=resolve;cropSource.onerror=reject;
        cropSource.src=`data:image/jpeg;base64,${result.jpeg_base64}`});
      drawCrop();$('photo_save').disabled=false;
    }finally{$('photo_capture_frame').disabled=false;}
  }
  const photoOwner='cell-thumbnail-'+Math.random().toString(36).slice(2);
  let photoOwnsPreview=false,photoHeartbeat=null,photoGeneration=0;
  async function photoRequest(url,options={}){
    const response=await fetch(url,options);
    if(!response.ok){
      const data=await response.json().catch(()=>({}));
      throw Error(data.detail||'Camera preview unavailable');
    }
    return response.json();
  }
  async function releasePhotoPreview(){
    photoGeneration++;
    if(photoHeartbeat!==null)clearInterval(photoHeartbeat);
    photoHeartbeat=null;$('cell_photo_live').removeAttribute('src');$('cell_photo_live').hidden=true;
    if(!photoOwnsPreview)return;
    photoOwnsPreview=false;
    try{
      await photoRequest('/api/cameras/preview/stop',{method:'POST',headers:{'X-DigiFlot-Tab-Id':photoOwner}});
    }catch(e){toast('Camera preview cleanup: '+e.message,true);}
  }
  async function preparePhotoPreview(){
    const camera=$('photo_camera').value,generation=++photoGeneration;
    if(!camera)throw Error('No camera is configured');
    $('photo_capture_frame').disabled=true;
    text('photo_camera_status','Starting camera preview…');
    const active=await photoRequest('/api/cameras');
    if(active.preview_camera_id!=null && String(active.preview_camera_id)!==String(camera)){
      throw Error('A different camera is in preview. Stop that preview before taking a cell photo.');
    }
    if(active.preview_camera_id==null){
      await photoRequest(`/api/cameras/${encodeURIComponent(camera)}/preview/start`,
        {method:'POST',headers:{'X-DigiFlot-Tab-Id':photoOwner}});
      photoOwnsPreview=true;
      photoHeartbeat=setInterval(async()=>{
        if(!photoOwnsPreview)return;
        try{
          await photoRequest('/api/cameras/preview/heartbeat',
            {method:'POST',headers:{'X-DigiFlot-Tab-Id':photoOwner}});
        }catch(e){text('photo_camera_status','Camera lease expired. Close and retry the photo dialog.');}
      },12000);
    }else{
      photoOwnsPreview=false; // Borrow existing preview; never stop another component's camera.
    }
    if(generation!==photoGeneration||!$('cell_photo_modal').open){
      if(photoOwnsPreview)await releasePhotoPreview();
      return;
    }
    $('cell_photo_live').src=`/api/cameras/${encodeURIComponent(camera)}/stream`;
    $('cell_photo_live').hidden=false;
    text('photo_camera_status','Live preview (shared lores stream)');
    $('photo_capture_frame').disabled=false;
  }
  async function openPhotoModal(){
    if(!state.cellId)throw Error('Save the cell before adding a photo');
    cropSource=null;cropPan={x:0,y:0};$('photo_save').disabled=true;
    $('photo_camera').innerHTML=state.cameras.map(c=>`<option value="${esc(c.id)}">${esc(c.name||c.id)}</option>`).join('');
    $('photo_camera').value=state.cameraId==null?String(state.cameras[0]?.id||''):String(state.cameraId);
    drawCrop();$('cell_photo_modal').showModal();
    await preparePhotoPreview();
  }
  async function savePhoto(){
    if(!cropSource||!state.cellId)throw Error('Capture a frame first');
    const image=$('cell_photo_canvas').toDataURL('image/webp',.76).split(',')[1];
    $('photo_save').disabled=true;
    try{
      const result=await api(`/cells/${encodeURIComponent(state.cellId)}/thumbnail`,
        {method:'PUT',body:{image_base64:image}});
      state.cell.thumbnail=result;renderCellPhoto(state.cell);$('cell_photo_modal').close();
      toast('Cell photo saved and queued for Server synchronization.');
    }finally{$('photo_save').disabled=false;}
  }
  async function removePhoto(){
    if(!state.cellId)return;
    await api(`/cells/${encodeURIComponent(state.cellId)}/thumbnail`,{method:'DELETE'});
    state.cell.thumbnail=null;renderCellPhoto(state.cell);
    toast('Cell photo removed; default icon will be shown.');
  }
  function showDimensionsGuide(){
    const g=state.cell?.geometry||{},resolved=state.cell?.resolved_dimensions?.dimensions||{};
    const fields=[['H · Height','height_mm'],['L · Width / diameter','width_mm'],
      ['W · Depth','depth_mm'],['h_collection','collection_height_mm']];
    $('cell_dimensions_values').innerHTML=fields.map(([name,key])=>{
      const best=resolved[key],nominal=g[key],source=best?.source||'unavailable';
      return '<div><dt>'+esc(name)+'</dt><dd>'+(best?esc(best.value_mm.toFixed(2))+' mm':'—')+
        '<small> · '+esc(source)+(nominal==null?'':' · nominal '+esc(nominal)+' mm')+'</small></dd></div>';
    }).join('');
    modal.showModal();
  }

  async function loadCell(id) {
    if(String(id||'')!==String(state.cellId||'')){
      state.relativeSourcePoints=[];state.relativeSourceCm=[];state.relativeSourceCameraId=null;
      state.relativeDestinationCameraId=null;state.relativeSourceCalibrationId=null;
      state.relativePairs={reference:[],target:[]};state.measurePointIds=[];
    }
    state.cellId = id || null;
    state.pending = null;
    $('confirm_aruco').disabled = true;
    setCellForm(id ? await api(`/cells/${encodeURIComponent(id)}`) : null);
    resetView();
    await loadAssociation();
    refreshCellActions();
    await refreshCameraRoles();
  }

  async function refreshCells(selectId=state.cellId) {
    state.cells = await api('/cells'+(state.showArchived?'?include_archived=true':''));
    $('cell_select').innerHTML = '<option value="">New cell / choose a cell</option>' + state.cells.map(c =>
      `<option value="${esc(c.id)}">${esc(c.name)}${c.archived?' [Archived]':''} · ${esc(c.id)}</option>`).join('');
    if (selectId && state.cells.some(c => c.id === selectId)) $('cell_select').value = selectId;
    await loadCell($('cell_select').value);
  }

  async function saveCell() {
    const data = cellPayload();
    if (!data.name) throw new Error('Enter a cell name');
    const path = state.cellId ? `/cells/${encodeURIComponent(state.cellId)}` : '/cells';
    const record = await api(path, {method:state.cellId ? 'PUT':'POST', body:data});
    await refreshCells(record.id);
    toast(`Cell ${record.name} saved (revision ${record.revision}).`);
  }

  async function saveCellReference() {
    if (!state.cellId) throw new Error('Save the physical cell first');
    const read=id=>$(id).value.trim()===''?null:Number($(id).value);
    const payload={mode:$('cell_reference_mode').value,
      cell_top_y_cm:read('cell_top_y_cm'),cell_bottom_y_cm:read('cell_bottom_y_cm')};
    const record=await api(`/cells/${encodeURIComponent(state.cellId)}/vertical-reference`,
      {method:'PUT',body:payload});
    const updated=await api(`/cells/${encodeURIComponent(state.cellId)}`);
    setCellForm(updated);
    toast(`Cell vertical reference saved (revision ${record.revision}).`);
  }

  function setCameraForm(profile) {
    state.profile = profile;
    state.roi = [...(profile?.roi_norm || [0,0,1,1])];
    $('optics_mode').value = profile?.optics?.mode || 'none';
    $('lens_preset').value = profile?.optics?.preset || 'leve';
    $('invert_markers').checked = Boolean(profile?.invert);
    text('roi_caption', `Camera ROI (sensor-normalized): [${state.roi.map(n => n.toFixed(3)).join(', ')}]`);
    $('lens_preset').disabled = $('optics_mode').value !== 'preset';
  }

  async function loadCamera(id) {
    state.cameraId = id == null || id === '' ? null : Number(id);
    state.pending = null;
    $('confirm_aruco').disabled = true;
    if (state.cameraId != null) setCameraForm(await api(`/cameras/${state.cameraId}/profile`));
    else setCameraForm(null);
    resetView();
    await loadAssociation();
  }

  async function importIntrinsics(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    const raw = JSON.parse(await file.text());
    const K = raw.K || raw.cam_matrix, D = raw.D || raw.dist;
    if (!Array.isArray(K) || !Array.isArray(D)) throw new Error('Calibration JSON needs K/D or cam_matrix/dist');
    const size = raw.reference_size || raw.image_size;
    if (!Array.isArray(size) || size.length !== 2) throw new Error('Calibration JSON needs reference_size [width,height]');
    state.profile.optics = {mode:'custom', K, D, reference_size:size, dist_model:raw.dist_model || 'standard',
      sensor_crop:raw.sensor_crop || null};
    $('optics_mode').value = 'custom';
    $('lens_preset').disabled = true;
    toast('Intrinsics imported. Save the camera profile to apply.');
  }

  async function saveCamera() {
    if (state.cameraId == null) throw new Error('Select a camera');
    const mode = $('optics_mode').value;
    const optics = mode === 'custom' ? (state.profile?.optics?.mode === 'custom' ? state.profile.optics : null)
      : mode === 'preset' ? {mode:'preset', preset:$('lens_preset').value} : {mode:'none'};
    if (!optics) throw new Error('Import intrinsic calibration JSON before selecting custom mode');
    const profile = await api(`/cameras/${state.cameraId}/profile`, {method:'PUT',
      body:{optics, roi_norm:state.roi, invert:$('invert_markers').checked}});
    setCameraForm(profile);
    toast(`Camera calibration saved (revision ${profile.revision}).`);
    await loadAssociation();
  }

  async function loadAssociation() {
    if (state.cellId == null || state.cameraId == null) {
      state.association = null;
      text('association_status','Select a camera and a cell.');
      text('last_calibration','—');
      state.analysisRoi = null; state.roiDirty = false;
      updateAnalysisCaption(); renderSelection();
      state.relativeRecord=null;showWorkspaceStatus();
      return;
    }
    state.association = await api(`/associations/${state.cameraId}/${encodeURIComponent(state.cellId)}`);
    const record = state.association;
    state.analysisRoi = record?.analysis_roi_cm ? [...record.analysis_roi_cm] : null;
    state.roiDirty = false;
    updateAnalysisCaption(); renderSelection();
    text('last_calibration',record?.calibration_id || 'None');
    const stale = record && (record.camera_revision !== state.profile?.revision || record.cell_revision !== state.cell?.revision);
    state.relativeRecord=await api('/associations/'+state.cameraId+'/'+encodeURIComponent(state.cellId)+'/relative').catch(()=>null);
    text('association_status',record ? `Using saved calibration #${record.revision}${stale?' (profile changed; review grid)':''}. Detect ArUco to update.` :
      state.relativeRecord?'Relative calibration is saved; ArUco not required for this view.':
      'No saved association yet. Use a relative scale or detect ArUco if markers are present.');
    await refreshCameraRoles();
    showWorkspaceStatus();
  }

  async function startPreview() {
    if (state.cameraId == null) throw new Error('Select a camera');
    const response = await fetch(`/api/cameras/${state.cameraId}/preview/start`,{method:'POST'});
    if (!response.ok) { const data=await response.json().catch(()=>({}));throw new Error(data.detail||'Preview start failed'); }
    toast('Preview started.');
    await refreshSnapshot();
  }
  async function stopPreview() {
    const response = await fetch('/api/cameras/preview/stop',{method:'POST'});
    if (!response.ok) throw new Error('Could not stop preview');
    toast('Preview stopped.');
  }
  async function refreshSnapshot() {
    if (state.cameraId == null) throw new Error('Select a camera');
    const query = state.cellId ? `?cell_id=${encodeURIComponent(state.cellId)}` : '';
    const result = await api(`/cameras/${state.cameraId}/snapshot${query}`);
    showImage(result, 'raw');
    if (result.calibration_id) text('last_calibration',result.calibration_id);
  }
  async function detect() {
    if (state.cameraId == null || state.cellId == null) throw new Error('Select a camera and cell');
    state.pending = null;
    $('confirm_aruco').disabled = true;
    const result = await api(`/associations/${state.cameraId}/${encodeURIComponent(state.cellId)}/detect`,{method:'POST'});
    showImage(result, 'raw');
    text('found_markers',result.detected_ids.join(', ') || 'None');
    text('rms_metric',result.candidate ? `${result.candidate.rms_px.toFixed(2)} px` : '—');
    text('scale_metric',result.candidate ? `${result.candidate.px_per_cm.toFixed(2)} px/cm` : '—');
    if (result.candidate_token) {
      state.pending = result.candidate_token;
      $('confirm_aruco').disabled = false;
      text('calibration_message','New grid preview only. Confirm to replace the last association (previous version retained).');
    } else text('calibration_message',result.error || 'Insufficient markers for calibration. The saved association was not changed.');
  }
  async function confirm() {
    if (!state.pending) throw new Error('Detect markers before confirming');
    const record = await api(`/associations/${state.cameraId}/${encodeURIComponent(state.cellId)}/confirm`,
      {method:'POST',body:{token:state.pending}});
    state.pending = null;
    $('confirm_aruco').disabled = true;
    await loadAssociation();
    toast(`Calibration ${record.calibration_id} confirmed and saved.`);
  }
  async function rectifiedSnapshot() {
    if (state.cameraId == null || state.cellId == null) throw new Error('Select a camera and cell');
    const result = await api(`/associations/${state.cameraId}/${encodeURIComponent(state.cellId)}/rectified`);
    showImage(result, 'rectified');
    text('calibration_message','Full rectified plane. Drag on the image to select an analysis ROI in local centimetres.');
  }
  async function saveSettings() {
    const cameraId = $('camera_select').value;
    const cellId = $('cell_select').value;
    state.settings = await api('/settings',{method:'PUT',body:{camera_id:cameraId || null, cell_id:cellId || null,
      enabled:$('vision_enabled').checked, sampling_interval_s:Number($('sample_interval').value)}});
    toast('Vision worker settings saved. Changes take effect on the next recording.');
    text('vision_state',state.settings.enabled ? 'Vision enabled' : 'Vision idle');
  }

  function resetView() {
    state.view = 'raw'; state.frame = null; state.plane = null; state.drag = null;
    state.relativePairs={reference:[],target:[]};state.measurePoints=[];
    state.zoom=1;state.panX=0;state.panY=0;
    $('camera_image').removeAttribute('src');
    $('roi_selection').hidden = true; $('roi_drag').hidden = true;
  }

  function updateAnalysisCaption() {
    const selected = state.analysisRoi;
    const available = Boolean(state.association);
    $('save_analysis_roi').disabled = !available || !selected;
    $('clear_analysis_roi').disabled = !available || (!selected && !state.association?.analysis_roi_cm);
    const coords = selected ? selected.map(n => Number(n).toFixed(2)).join(', ') : null;
    text('analysis_roi_caption', !available ? 'Confirm an ArUco calibration first.'
      : coords ? `Physical ROI [${coords}] cm${state.roiDirty ? ' — unsaved' : ' — saved'}`
      : 'No analysis ROI selected. Open Rectified plane to select an area.');
  }

  function pointOnImage(event) {
    const rect = $('camera_image').getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
            Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
  }

  function sensorPoint(point) {
    const crop = state.frame?.sensor_crop, sensor = state.profile?.sensor_size;
    if (!crop || !sensor) return point;
    return [(crop[0] + point[0] * crop[2]) / sensor[0],
            (crop[1] + point[1] * crop[3]) / sensor[1]];
  }

  function planePoint(point) {
    const plane = state.plane;
    if (!plane) return null;
    const min = plane.min_xy_cm, max = plane.max_xy_cm;
    return [min[0] + point[0] * (max[0] - min[0]),
            min[1] + point[1] * (max[1] - min[1])];
  }

  function positionBox(element, a, b) {
    const image = $('camera_image').getBoundingClientRect(), surface = $('image_surface').getBoundingClientRect();
    element.style.left = `${image.left-surface.left+Math.min(a[0],b[0])*image.width}px`;
    element.style.top = `${image.top-surface.top+Math.min(a[1],b[1])*image.height}px`;
    element.style.width = `${Math.abs(b[0]-a[0])*image.width}px`;
    element.style.height = `${Math.abs(b[1]-a[1])*image.height}px`;
    element.hidden = false;
  }

  function renderSelection() {
    const selection = $('roi_selection'), img = $('camera_image');
    selection.hidden = true;
    drawNamedPoints();
    if (!img.naturalWidth || !img.getAttribute('src')) return;
    let region = null;
    if (state.view === 'rectified' && state.plane && state.analysisRoi) {
      const min = state.plane.min_xy_cm, max = state.plane.max_xy_cm, roi = state.analysisRoi;
      region = [[(roi[0]-min[0])/(max[0]-min[0]), (roi[1]-min[1])/(max[1]-min[1])],
                [(roi[2]-min[0])/(max[0]-min[0]), (roi[3]-min[1])/(max[1]-min[1])]];
    } else if (state.view === 'raw' && state.frame && state.profile?.sensor_size) {
      const sensor = state.profile.sensor_size, crop = state.frame.sensor_crop, roi = state.roi;
      region = [[(roi[0]*sensor[0]-crop[0])/crop[2], (roi[1]*sensor[1]-crop[1])/crop[3]],
                [(roi[2]*sensor[0]-crop[0])/crop[2], (roi[3]*sensor[1]-crop[1])/crop[3]]];
    }
    if (!region) return;
    const a = region[0].map(v => Math.max(0,Math.min(1,v)));
    const b = region[1].map(v => Math.max(0,Math.min(1,v)));
    if (b[0]-a[0] < .002 || b[1]-a[1] < .002) return;
    positionBox(selection, a, b);
  }

  function drawDrag(event) {
    if (!state.drag) return;
    event.preventDefault();
    const point = pointOnImage(event);
    if (!point) return;
    state.drag.end = point;
    positionBox($('roi_drag'), state.drag.start, point);
  }

  function finishDrag(event) {
    if(state.pointClick){
      const p=pointOnImage(event)||state.pointClick,down=state.pointClick;state.pointClick=null;
      if(state.activePoint&&Math.hypot(p[0]-down[0],p[1]-down[1])<.025){
        const point=state.named.points.find(x=>x.id===state.activePoint);
        if(point&&state.view==='rectified'&&state.plane){
          point.position_cm=planePoint(p);point.source='image_selection';
          state.namedDirty=true;state.activePoint=null;renderNamedPoints();
        }else if(point&&state.cameraId!=null&&state.cellId){
          const currentId=state.cellId,cameraId=state.cameraId,referenceId=point.id;
          const previous=state.cell?.reference_observations?.[String(cameraId)];
          state.activePoint=null;renderNamedPoints();
          void api('/cells/'+encodeURIComponent(currentId)+'/reference-observations/'+cameraId,{
            method:'PUT',body:{reference_id:referenceId,position_norm:p,
              frame_size:[$('camera_image').naturalWidth,$('camera_image').naturalHeight],
              image_space:state.imageSpace,camera_revision:state.capturedProfileRevision,
              capture_camera_id:state.capturedCameraId,expected_revision:previous?.revision||0}
          }).then(async()=>{
            if(state.cellId!==currentId)return;
            state.cell=await api('/cells/'+encodeURIComponent(currentId));
            renderNamedPoints();toast('Camera observation saved. ArUco physical coordinates were preserved.');
          }).catch(error=>toast(error.message,true));
        }
      }
      return;
    }
    if (!state.drag) return;
    const a = state.drag.start, b = pointOnImage(event) || state.drag.end || a;
    state.drag = null; $('roi_drag').hidden = true;
    const low = [Math.min(a[0],b[0]), Math.min(a[1],b[1])];
    const high = [Math.max(a[0],b[0]), Math.max(a[1],b[1])];
    if (high[0]-low[0] < .01 || high[1]-low[1] < .01) return;
    if (state.view === 'rectified') {
      if (!state.plane || !state.association) return;
      const from = planePoint(low), to = planePoint(high);
      state.analysisRoi = [...from, ...to];
      state.roiDirty = true;
      updateAnalysisCaption();
    } else if (state.view === 'raw') {
      const from = sensorPoint(low), to = sensorPoint(high);
      state.roi = [...from, ...to].map(n => Math.max(0,Math.min(1,n)));
      text('roi_caption', `Camera ROI (sensor-normalized): [${state.roi.map(n=>n.toFixed(3)).join(', ')}]. Save camera to persist.`);
    }
    renderSelection();
  }

  async function saveAnalysisRoi() {
    if (state.cameraId == null || !state.cellId || !state.association || !state.analysisRoi)
      throw new Error('Confirm a calibration and select a region on the rectified plane');
    await api(`/associations/${state.cameraId}/${encodeURIComponent(state.cellId)}/roi`,
      {method:'PUT',body:{roi_cm:state.analysisRoi}});
    await loadAssociation();
    toast('Physical analysis ROI saved for this camera–cell pair.');
  }

  async function clearAnalysisRoi() {
    if (state.cameraId == null || !state.cellId || !state.association)
      throw new Error('Select a calibrated camera and cell');
    await api(`/associations/${state.cameraId}/${encodeURIComponent(state.cellId)}/roi`,
      {method:'PUT',body:{roi_cm:null}});
    await loadAssociation();
    toast('Analysis ROI cleared. The ArUco calibration was preserved.');
  }

  async function refreshCameraRoles(){
    if(!state.cellId){state.cameraRoles={side:null,top:null};showWorkspaceStatus();return;}
    const source=await Promise.all(state.cameras.map(async camera=>{
      const association=await api('/associations/'+encodeURIComponent(camera.id)+'/'+encodeURIComponent(state.cellId)).catch(()=>null);
      return {id:camera.id,association};
    }));
    const calibrated=source.find(item=>item.association&&
      item.association.camera_revision===item.association.camera_profile?.revision&&
      item.association.cell_revision===state.cell?.revision);
    const first=calibrated||source.find(item=>item.association)||source.find(item=>String(item.id)===String(state.settings.camera_id))||source[0];
    const second=source.find(item=>String(item.id)!==String(first?.id));
    state.cameraRoles={side:first?.id??null,top:second?.id??null};
    const sourceSelect=$('cv_relative_source'),destinationSelect=$('cv_relative_destination');
    const oldSource=sourceSelect.value,oldDest=destinationSelect.value;
    sourceSelect.innerHTML='<option value="">Select calibrated camera</option>'+source.filter(item=>
      item.association&&item.association.cell_revision===state.cell?.revision&&
      item.association.camera_revision===item.association.camera_profile?.revision)
      .map(item=>'<option value="'+esc(item.id)+'">'+esc(state.cameras.find(c=>
        String(c.id)===String(item.id))?.name||item.id)+' · confirmed ArUco</option>').join('');
    if([...sourceSelect.options].some(o=>o.value===oldSource))sourceSelect.value=oldSource;
    else if(first?.association&&[...sourceSelect.options].some(o=>o.value===String(first.id)))
      sourceSelect.value=String(first.id);
    const chosenSource=sourceSelect.value;
    destinationSelect.innerHTML='<option value="">Select target camera</option>'+source.filter(item=>
      String(item.id)!==chosenSource).map(item=>'<option value="'+esc(item.id)+'">'+
      esc(state.cameras.find(c=>String(c.id)===String(item.id))?.name||item.id)+'</option>').join('');
    if([...destinationSelect.options].some(o=>o.value===oldDest))destinationSelect.value=oldDest;
    else if([...destinationSelect.options].some(o=>o.value===String(state.cameraId)))
      destinationSelect.value=String(state.cameraId);
    else if(second&&[...destinationSelect.options].some(o=>o.value===String(second.id)))
      destinationSelect.value=String(second.id);
    showWorkspaceStatus();
  }
  async function selectCameraRole(role){
    const camera=state.cameraRoles[role];
    if(camera==null)throw new Error('No '+role+' camera is available.');
    if(String(camera)===String(state.cameraId))return;
    if(state.namedDirty&&!window.confirm('There are unsaved physical references. Switch cameras without saving?'))return;
    setWorkspaceTool('select');
    await loadCamera(camera);
    $('camera_select').value=String(camera);
    try{
      if(state.association && state.association.camera_revision===state.profile?.revision &&
          state.association.cell_revision===state.cell?.revision)await rectifiedSnapshot();
      else await refreshUndistortedSnapshot();
    }catch(error){toast('Camera selected. Start its preview if capture is unavailable: '+error.message,true);}
  }
  async function refreshUndistortedSnapshot(){
    if(state.cameraId==null)throw new Error('Select a camera first.');
    const data=await api('/cameras/'+encodeURIComponent(state.cameraId)+'/snapshot?undistorted=true&show_grid=false');
    showImage(data,'raw');
    if(!data.optics_corrected)toast('No intrinsic correction is saved; displaying the original pixels.');
  }
  async function switchRelativeCamera(cameraId,rectified){
    if(!cameraId||!state.cellId)throw new Error('Select a cell and camera before calibration.');
    if(String(cameraId)!==String(state.cameraId))await loadCamera(cameraId);
    $('camera_select').value=String(cameraId);
    if(rectified){
      if(!state.association||state.association.camera_revision!==state.profile?.revision||
          state.association.cell_revision!==state.cell?.revision)
        throw new Error('This source needs a current saved ArUco association; revalidate its original calibration first.');
      await rectifiedSnapshot();
    }else await refreshUndistortedSnapshot();
    $('cv_camera_calibration_details').open=true;
    $('cv_image_mount').scrollIntoView({behavior:'smooth',block:'center'});
  }
  async function pickRelativeSource(){
    const source=$('cv_relative_source').value,destination=$('cv_relative_destination').value;
    if(!source)throw new Error('Select the calibrated source camera.');
    if(!destination||source===destination)throw new Error('Select a different destination camera.');
    if($('cv_relative_reference').value===$('cv_relative_target').value)
      throw new Error('Select different known and target dimensions.');
    state.relativeSourceCameraId=source;state.relativeDestinationCameraId=destination;
    state.relativeSourcePoints=[];state.relativeSourceCm=[];
    state.relativePairs={reference:[],target:[]};
    await switchRelativeCamera(source,true);
    setWorkspaceTool('relative_source');
    text('cv_relative_source_status','Click two endpoints of the known physical length on the calibrated source view. Existing point markers are reused when nearby.');
  }
  async function pickRelativeDestination(which){
    if(state.relativeSourceCm.length!==2)
      throw new Error('First pick the known physical length on the calibrated source camera.');
    const destination=$('cv_relative_destination').value;
    if(!destination||destination===String(state.relativeSourceCameraId))
      throw new Error('Choose a different destination camera.');
    if(state.relativeDestinationCameraId!==destination){
      state.relativePairs={reference:[],target:[]};
      state.relativeDestinationCameraId=destination;
    }
    if(String(state.cameraId)!==destination||state.view==='rectified'){
      await switchRelativeCamera(destination,false);
    }else if(!state.frame||state.imageSpace!=='undistorted'){
      await refreshUndistortedSnapshot();
    }
    const key=which==='relative_reference'?'reference':'target';
    state.relativePairs[key]=[];
    setWorkspaceTool(which);drawWorkspaceMeasurements();
    text('cv_relative_readout',which==='relative_reference'?
      'Select the SAME physical length in the destination image (two endpoints).':
      'Now select the OTHER dimension in the same destination image (two endpoints).');
  }
  function relativeReadout(){
    const points=state.relativeSourceCm;
    if(points.length!==2)return;
    const sourceMM=projectedMetricValue(...points,$('cv_relative_source_axis').value);
    if(sourceMM<=0)return;
    const pair=state.relativePairs;
    if(pair.reference.length!==2||pair.target.length!==2){
      text('cv_relative_source_status',sourceMM.toFixed(2)+' mm · calibrated source · '+$('cv_relative_source_axis').value);
      return;
    }
    const img=$('camera_image'),pixels=(points,axis)=>{
      const x=Math.abs(points[1][0]-points[0][0])*img.naturalWidth;
      const y=Math.abs(points[1][1]-points[0][1])*img.naturalHeight;
      return axis==='horizontal'?x:axis==='vertical'?y:Math.hypot(x,y);
    };
    const d0=pixels(pair.reference,$('cv_relative_reference_axis').value);
    const d1=pixels(pair.target,$('cv_relative_target_axis').value);
    if(d0<=0)return;
    text('cv_relative_readout','Estimated '+$('cv_relative_target').selectedOptions[0].textContent+': '+
      (sourceMM*d1/d0).toFixed(2)+' mm · known '+sourceMM.toFixed(2)+' mm · scale ratio '+
      (d1/d0).toFixed(3)+' · approximate until perspective is calibrated.');
  }
  async function reuseSavedArUco(){
    if(!state.cellId||state.cameraId==null||!state.association)
      throw new Error('No saved ArUco calibration is available.');
    if(!window.confirm('Confirm the physical ArUco ruler has not moved relative to the cell, and the camera optics are unchanged. Revalidate the saved homography without detecting any marker?'))return;
    const saved=await api('/associations/'+state.cameraId+'/'+encodeURIComponent(state.cellId)+'/reuse',
      {method:'POST',body:{ruler_unchanged:true}});
    await loadAssociation();
    toast('Saved homography revalidated as '+saved.calibration_id+'. Previous version retained.');
  }

  async function saveRelativeCalibration(){
    if(!state.cellId)throw new Error('Select a cell.');
    const source=state.relativeSourceCameraId,destination=state.relativeDestinationCameraId;
    if(!source||!destination||String(state.cameraId)!==String(destination))
      throw new Error('Complete the source and destination measurements on their corresponding cameras.');
    if(state.relativeSourceCm.length!==2||
        state.relativePairs.reference.length!==2||state.relativePairs.target.length!==2)
      throw new Error('The calibrated length and BOTH destination lengths need two endpoints each.');
    if(state.view==='rectified'||!['raw','undistorted'].includes(state.imageSpace))
      throw new Error('Use the destination camera raw or undistorted image for its pixel-scale measurements.');
    const img=$('camera_image');
    if(!img.naturalWidth||!img.naturalHeight)throw new Error('Capture the destination camera image first.');
    const payload={source_camera_id:source,source_points_cm:state.relativeSourceCm,
      source_calibration_id:state.relativeSourceCalibrationId,
      source_camera_revision:state.relativeSourceCameraRevision,
      source_axis:$('cv_relative_source_axis').value,
      reference_field:$('cv_relative_reference').value,target_field:$('cv_relative_target').value,
      reference_pair:state.relativePairs.reference,target_pair:state.relativePairs.target,
      reference_axis:$('cv_relative_reference_axis').value,target_axis:$('cv_relative_target_axis').value,
      frame_size:[img.naturalWidth,img.naturalHeight],image_space:state.imageSpace,
      camera_revision:state.capturedProfileRevision,capture_camera_id:state.capturedCameraId,
      physical_plane:$('cv_relative_plane').value,expected_revision:state.relativeRecord?.revision||0};
    const record=await api('/associations/'+destination+'/'+encodeURIComponent(state.cellId)+'/relative',
      {method:'PUT',body:payload});
    state.relativeRecord={...record,valid:true};state.cell=await api('/cells/'+encodeURIComponent(state.cellId));
    renderCellResolvedDimensions();showWorkspaceStatus();
    text('cv_relative_readout','Saved · '+record.target_field+': '+record.target_mm.toFixed(2)+
      ' mm · metric source '+record.reference_mm.toFixed(2)+' mm · estimated target. Existing ArUco preserved.');
    toast('Relative camera calibration saved without replacing the source homography.');
    setWorkspaceTool('select');
  }
  async function saveVisualMeasurement(){
    if(!state.cellId)throw new Error('Select and save a cell first.');
    if(state.namedDirty)throw new Error('Save edited physical references before assigning a dimension.');
    const field=$('cv_measure_target').value,from=$('cv_measure_from').value,
      to=$('cv_measure_to').value,axis=$('cv_measure_axis').value;
    if(!from||!to||from===to)throw new Error('Choose two different existing physical references.');
    const a=physicalReferencePosition(from),b=physicalReferencePosition(to);
    if(!a||!b)throw new Error('Place the selected named references on a calibrated plane first.');
    if(projectedMetricValue(a,b,axis)<.01)
      throw new Error('The selected references have zero distance along this axis.');
    const pairs={...(state.dimensionMeasurements?.pairs||{}),[field]:{from_id:from,to_id:to,axis}};
    state.dimensionMeasurements=await api('/cells/'+encodeURIComponent(state.cellId)+'/dimensions',{
      method:'PUT',body:{pairs,expected_revision:state.dimensionMeasurements?.revision||0}});
    state.cell=await api('/cells/'+encodeURIComponent(state.cellId));
    state.dimensionMeasurements=state.cell.dimension_measurements;
    renderCellDimensionPairs();renderCellResolvedDimensions();renderVolumeEditor();
    text('cv_measure_status','Saved '+dimensionLabels[field]+': '+
      projectedMetricValue(a,b,axis).toFixed(2)+' mm · '+axis+' · '+from+' → '+to);
    toast('Dimension now uses existing physical references. No new points or ArUco revision were created.');
    setWorkspaceTool('select');
  }
  function refreshCellActions(){
    const has=Boolean(state.cellId),archived=Boolean(state.cell?.archived);
    for(const id of ['cv_rename_open','cv_archive_open'])$(id).disabled=!has;
    $('cv_archive_cell').textContent=archived?'Restore cell':'Archive cell';
    window.DigiFlotIcons?.decorate($('cv_archive_cell').parentElement);
    $('cv_delete_empty').disabled=!archived;
  }
  async function renameSelectedCell(){
    if(!state.cellId)throw new Error('Choose a saved cell.');
    const result=await api('/cells/'+encodeURIComponent(state.cellId)+'/name',
      {method:'PUT',body:{name:$('cv_rename_input').value.trim()}});
    $('cv_rename_dialog').close();await refreshCells(result.id);
    toast('Renamed without changing geometry or camera calibration revisions.');
  }
  async function archiveSelectedCell(){
    if(!state.cellId)throw new Error('Choose a saved cell.');
    const wasArchived=Boolean(state.cell?.archived);
    if(!window.confirm((wasArchived?'Restore':'Archive')+' '+state.cell.name+
      '? Archive keeps physical references, calibration history and measurements.'))return;
    const id=state.cellId;
    await api('/cells/'+encodeURIComponent(id)+'/archive',{method:'PUT',body:{archived:!wasArchived}});
    $('cv_delete_dialog').close();
    await refreshCells(!wasArchived?null:id);
    toast(wasArchived?'Cell restored.':'Cell archived. Its historical calibrations remain saved.');
  }
  async function deleteArchivedDraft(){
    if(!state.cellId||!state.cell?.archived)throw new Error('Archive this cell first.');
    const name=state.cell.name;
    if(window.prompt('Permanent deletion only works for an empty draft. Type DELETE '+name+
      ' to confirm:')!=='DELETE '+name)return;
    await api('/cells/'+encodeURIComponent(state.cellId),{method:'DELETE'});
    $('cv_delete_dialog').close();await refreshCells(null);
    toast('Unreferenced draft cell permanently deleted.');
  }

  async function initialize() {
    const data=await api('/status');state.settings=data.settings;state.cameras=data.cameras;
    $('camera_select').innerHTML='<option value="">Select a camera</option>'+data.cameras.map(c=>
      `<option value="${c.id}">${esc(c.name)} (#${c.id})</option>`).join('');
    $('vision_enabled').checked=Boolean(data.settings.enabled);
    $('sample_interval').value=data.settings.sampling_interval_s;
    text('vision_state',data.settings.enabled ? 'Vision enabled' : 'Vision idle');
    const initial = new URLSearchParams(window.location.search);
    $('return_to_sensor_calibration').hidden = !initial.has('cell') && !initial.has('camera');
    const cameraId = initial.get('camera') || data.settings.camera_id;
    const cellId = initial.get('cell') || data.settings.cell_id;
    if (cameraId != null) $('camera_select').value=cameraId;
    await refreshCells(cellId);
    await loadCamera($('camera_select').value);
    await refreshCameraRoles();
    refreshCellActions();
  }

  arrangeCellsWorkspace();
  $('capture_cell_photo').addEventListener('click',action(openPhotoModal));
  $('photo_camera').addEventListener('change',action(async()=>{
    await releasePhotoPreview();
    cropSource=null;$('photo_save').disabled=true;drawCrop();
    await preparePhotoPreview();
  }));
  $('cell_photo_modal').addEventListener('close',()=>{void releasePhotoPreview();});
  window.addEventListener('pagehide',()=>{if(photoOwnsPreview)void releasePhotoPreview();});
  $('remove_cell_photo').addEventListener('click',action(removePhoto));
  $('photo_capture_frame').addEventListener('click',action(takePhotoFrame));
  $('photo_save').addEventListener('click',action(savePhoto));
  $('photo_zoom').addEventListener('input',drawCrop);
  $('close_cell_photo').addEventListener('click',()=>$('cell_photo_modal').close());
  $('cell_dimensions_info').addEventListener('click',showDimensionsGuide);
  $('close_dimensions_guide').addEventListener('click',()=>$('cell_dimensions_modal').close());
  const cropCanvas=$('cell_photo_canvas');
  cropCanvas.addEventListener('pointerdown',event=>{if(!cropSource)return;
    dragStart={x:event.clientX,y:event.clientY,pan:{...cropPan}};cropCanvas.setPointerCapture(event.pointerId)});
  cropCanvas.addEventListener('pointermove',event=>{if(!dragStart)return;
    const r=cropCanvas.getBoundingClientRect(),ratio=512/r.width;
    cropPan={x:dragStart.pan.x+(event.clientX-dragStart.x)*ratio,y:dragStart.pan.y+(event.clientY-dragStart.y)*ratio};drawCrop()});
  cropCanvas.addEventListener('pointerup',()=>{dragStart=null});
  cropCanvas.addEventListener('pointercancel',()=>{dragStart=null});
  $('new_cell').addEventListener('click',action(async()=>{ $('cell_select').value='';await loadCell(null);toast('Enter a new physical cell.'); }));
  $('cell_select').addEventListener('change',action(async()=>loadCell($('cell_select').value)));
  $('save_cell').addEventListener('click',action(saveCell));
  $('cv_save_measure').addEventListener('click',action(saveVisualMeasurement));
  $('cv_rename_open').addEventListener('click',()=>{
    if(!state.cellId)return;$('cv_rename_input').value=state.cell?.name||'';
    $('cv_rename_dialog').showModal();$('cv_rename_input').focus();
  });
  $('cv_rename_close').addEventListener('click',()=>$('cv_rename_dialog').close());
  $('cv_rename_save').addEventListener('click',action(renameSelectedCell));
  $('cv_archive_open').addEventListener('click',()=>{
    if(!state.cellId)return;text('cv_delete_name',state.cell?.name||'');
    $('cv_delete_dialog').showModal();
  });
  $('cv_delete_close').addEventListener('click',()=>$('cv_delete_dialog').close());
  $('cv_archive_cell').addEventListener('click',action(archiveSelectedCell));
  $('cv_delete_empty').addEventListener('click',action(deleteArchivedDraft));
  $('cv_show_archived').addEventListener('change',action(async()=>{
    state.showArchived=$('cv_show_archived').checked;await refreshCells();
  }));
  $('save_dimension_pairs').addEventListener('click',action(saveCellDimensionPairs));
  $('add_volume_point').addEventListener('click',()=>{$('cell_volume_points').insertAdjacentHTML('beforeend',volumePointRow());});
  $('save_volume_curve').addEventListener('click',action(saveVolumeCurve));
  $('cell_volume_points').addEventListener('click',event=>{
    if(event.target.closest('[data-volume-remove]')){
      event.target.closest('.cv-volume-point').remove();
      if(!$('cell_volume_points').children.length)
        $('cell_volume_points').insertAdjacentHTML('beforeend',volumePointRow());
    }
  });
  $('save_cell_reference').addEventListener('click',action(saveCellReference));
  $('reference_add').addEventListener('click',action(addNamedPoint));
  $('reference_save').addEventListener('click',action(saveNamedPoints));
  $('reference_reuse').addEventListener('click',action(reuseNamedPoints));
  $('named_reference_list').addEventListener('click',e=>{if(e.target.dataset.refAction)action(()=>handleNamedPoint(e))();});
  $('named_reference_list').addEventListener('change',e=>action(()=>handleNamedPoint(e))());
  $('camera_select').addEventListener('change',action(async()=>{
    await loadCamera($('camera_select').value);
    showWorkspaceStatus();
  }));
  $('cv_side_camera').addEventListener('click',action(()=>selectCameraRole('side')));
  $('cv_top_camera').addEventListener('click',action(()=>selectCameraRole('top')));
  $('cv_raw_view').addEventListener('click',action(async()=>{
    if(state.cameraId==null)throw new Error('Select a camera.');
    const result=await api('/cameras/'+state.cameraId+'/snapshot?show_grid=false');
    showImage(result,'raw');
  }));
  $('cv_undistorted_view').addEventListener('click',action(refreshUndistortedSnapshot));
  $('cv_rectified_view').addEventListener('click',action(rectifiedSnapshot));
  $('cv_zoom_fit').addEventListener('click',()=>changeZoom(1));
  $('cv_zoom_in').addEventListener('click',()=>changeZoom(state.zoom*1.25));
  $('cv_zoom_out').addEventListener('click',()=>changeZoom(state.zoom/1.25));
  $('cv_pan_mode').addEventListener('click',()=>setWorkspaceTool(state.uiTool==='pan'?'select':'pan'));
  $('image_surface').addEventListener('wheel',event=>{
    if(!$('camera_image').naturalWidth)return;
    event.preventDefault();changeZoom(state.zoom*(event.deltaY<0?1.12:1/1.12));
  },{passive:false});
  $('cv_measure_target').addEventListener('change',renderMeasurementSelectors);
  for(const id of ['cv_measure_from','cv_measure_to','cv_measure_axis']){
    $(id).addEventListener('change',updateMeasurementPreview);
  }
  $('cv_pick_measure').addEventListener('click',()=>{
    state.measurePointIds=[];$('cv_measure_from').value='';$('cv_measure_to').value='';
    setWorkspaceTool('measure');
    text('cv_measure_status','Click an existing physical reference marker, then a different marker.');
    drawWorkspaceMeasurements();
  });
  $('cv_clear_measure').addEventListener('click',()=>{
    state.measurePointIds=[];state.measurePoints=[];$('cv_measure_from').value='';
    $('cv_measure_to').value='';setWorkspaceTool('select');
    text('cv_measure_status','Selection cleared; saved geometry is unchanged.');drawWorkspaceMeasurements();
  });
  $('cv_relative_pick_source').addEventListener('click',action(pickRelativeSource));
  $('cv_relative_pick_reference').addEventListener('click',action(()=>pickRelativeDestination('relative_reference')));
  $('cv_relative_pick_target').addEventListener('click',action(()=>pickRelativeDestination('relative_target')));
  $('cv_relative_source').addEventListener('change',()=>{
    state.relativeSourcePoints=[];state.relativeSourceCm=[];state.relativeSourceCameraId=null;
    state.relativePairs={reference:[],target:[]};void refreshCameraRoles();drawWorkspaceMeasurements();
  });
  for(const id of ['cv_relative_reference','cv_relative_target','cv_relative_source_axis',
    'cv_relative_reference_axis','cv_relative_target_axis'])
    $(id).addEventListener('change',()=>{relativeReadout();drawWorkspaceMeasurements();});
  $('cv_save_relative').addEventListener('click',action(saveRelativeCalibration));
  $('cv_reuse_saved_aruco').addEventListener('click',action(reuseSavedArUco));
  $('optics_mode').addEventListener('change',()=>{$('lens_preset').disabled=$('optics_mode').value!=='preset';});
  $('import_intrinsics').addEventListener('change',action(importIntrinsics));
  $('reset_roi').addEventListener('click',()=>{state.roi=[0,0,1,1];text('roi_caption','Camera ROI: full sensor. Save camera to persist.');renderSelection();});
  $('save_camera').addEventListener('click',action(saveCamera));
  $('save_vision_settings').addEventListener('click',action(saveSettings));
  $('start_preview').addEventListener('click',action(startPreview));
  $('stop_preview').addEventListener('click',action(stopPreview));
  $('refresh_snapshot').addEventListener('click',action(refreshSnapshot));
  $('detect_aruco').addEventListener('click',action(detect));
  $('confirm_aruco').addEventListener('click',action(confirm));
  $('test_rectification').addEventListener('click',action(rectifiedSnapshot));
  $('save_analysis_roi').addEventListener('click',action(saveAnalysisRoi));
  $('clear_analysis_roi').addEventListener('click',action(clearAnalysisRoi));
  const img=$('camera_image');
  img.addEventListener('load',()=>{
    renderSelection();drawWorkspaceMeasurements();
    const pair=state.relativePairs;
    if(pair.reference.length===2&&pair.target.length===2)relativeReadout();
  });
  window.addEventListener('resize',renderSelection);
  img.addEventListener('pointerdown',event=>{
    if(!img.naturalWidth || !img.getAttribute('src'))return;
    if(state.view==='rectified' && (!state.plane || !state.association))return;
    const p=pointOnImage(event);if(!p)return;
    event.preventDefault();
    if(state.uiTool==='pan'){
      state.panDrag={x:event.clientX,y:event.clientY,panX:state.panX,panY:state.panY};
      img.setPointerCapture(event.pointerId);return;
    }
    if(['measure','relative_source','relative_reference','relative_target'].includes(state.uiTool)){
      if(state.uiTool==='relative_source'&&state.view!=='rectified'){
        toast('The known source length must be selected on the rectified calibrated image.',true);return;
      }
      if(state.view==='rectified'&&['relative_reference','relative_target'].includes(state.uiTool)){
        toast('Select destination pixel lengths on a Raw or Undistorted image.',true);return;
      }
      state.pickClick={p,x:event.clientX,y:event.clientY};
      img.setPointerCapture(event.pointerId);return;
    }
    if(state.activePoint){
      state.pointClick=p;img.setPointerCapture(event.pointerId);return;
    }
    state.drag={start:p,end:p};
    img.setPointerCapture(event.pointerId);
  });
  img.addEventListener('pointermove',event=>{
    if(state.panDrag){
      state.panX=state.panDrag.panX+event.clientX-state.panDrag.x;
      state.panY=state.panDrag.panY+event.clientY-state.panDrag.y;
      applyCanvasViewport();return;
    }
    const p=pointOnImage(event);
    if(p){
      const metric=state.view==='rectified'&&state.plane?planePoint(p):null;
      text('cv_cursor_status',metric?'Plane: '+metric.map(v=>v.toFixed(2)).join(', ')+' cm':
        'Pixel: '+Math.round(p[0]*img.naturalWidth)+', '+Math.round(p[1]*img.naturalHeight));
    }
    if(!state.pickClick)drawDrag(event);
  });
  img.addEventListener('pointerup',event=>{
    if(state.panDrag){state.panDrag=null;return;}
    if(state.pickClick){
      const click=state.pickClick;state.pickClick=null;
      if(Math.hypot(click.x-event.clientX,click.y-event.clientY)<16){
        captureWorkspacePoint(pointOnImage(event)||click.p);
        if(state.relativePairs.reference.length===2&&state.relativePairs.target.length===2)
          relativeReadout();
      }
      return;
    }
    finishDrag(event);
  });
  img.addEventListener('pointercancel',()=>{
    state.drag=null;state.pointClick=null;state.pickClick=null;state.panDrag=null;$('roi_drag').hidden=true;
  });
  initialize().catch(err=>toast(err.message,true));
})();
