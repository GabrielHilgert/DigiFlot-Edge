(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {cells: [], cameras: [], settings: {}, profile: null, cell: null,
    cameraId: null, cellId: null, association: null, pending: null, frame: null,
    roi: [0, 0, 1, 1], analysisRoi: null, roiDirty: false, view: 'raw', plane: null, drag: null};
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
    state.view = view;
    state.frame = data.frame || null;
    state.plane = data.plane || null;
    state.drag = null;
    $('roi_drag').hidden = true;
    $('roi_selection').hidden = true;
    $('image_help').textContent = view === 'rectified'
      ? 'Rectified plane: drag to select the physical analysis ROI. Save analysis ROI to apply it during recording.'
      : 'Raw camera: drag to adjust the sensor ROI. Open Rectified plane to select the physical analysis ROI.';
    $('camera_image').src = `data:image/jpeg;base64,${data.jpeg_base64}`;
  };

  function setCellForm(cell) {
    state.cell = cell;
    $('cell_name').value = cell?.name || '';
    $('cell_volume').value = cell?.working_volume_l ?? '';
    const g = cell?.geometry || {};
    $('cell_shape').value = g.shape || 'custom';
    $('cell_height').value = g.height_mm ?? '';
    $('cell_width').value = g.width_mm ?? '';
    $('cell_depth').value = g.depth_mm ?? '';
    const l = cell?.marker_layout || {marker_ids:[0,1,2], marker_size_cm:2, span_cm:14};
    l.marker_ids.forEach((v,i) => { $(`marker_${i}`).value = v; });
    $('marker_size').value = l.marker_size_cm;
    $('marker_span').value = l.span_cm;
  }

  function cellPayload() {
    const shape = $('cell_shape').value;
    return {id: state.cellId || undefined, name: $('cell_name').value.trim(),
      working_volume_l: numeric('cell_volume'),
      geometry: {shape, height_mm:numeric('cell_height'), width_mm:numeric('cell_width'), depth_mm:numeric('cell_depth')},
      marker_layout: {dictionary:'DICT_4X4_50', marker_ids:[0,1,2].map(i => Number($(`marker_${i}`).value)),
        marker_size_cm:numeric('marker_size'), span_cm:numeric('marker_span')}};
  }

  async function loadCell(id) {
    state.cellId = id || null;
    state.pending = null;
    $('confirm_aruco').disabled = true;
    setCellForm(id ? await api(`/cells/${encodeURIComponent(id)}`) : null);
    resetView();
    await loadAssociation();
  }

  async function refreshCells(selectId=state.cellId) {
    state.cells = await api('/cells');
    $('cell_select').innerHTML = '<option value="">New cell / choose a cell</option>' + state.cells.map(c =>
      `<option value="${esc(c.id)}">${esc(c.name)} · ${esc(c.id)}</option>`).join('');
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
      return;
    }
    state.association = await api(`/associations/${state.cameraId}/${encodeURIComponent(state.cellId)}`);
    const record = state.association;
    state.analysisRoi = record?.analysis_roi_cm ? [...record.analysis_roi_cm] : null;
    state.roiDirty = false;
    updateAnalysisCaption(); renderSelection();
    text('last_calibration',record?.calibration_id || 'None');
    const stale = record && (record.camera_revision !== state.profile?.revision || record.cell_revision !== state.cell?.revision);
    text('association_status',record ? `Using saved calibration #${record.revision}${stale?' (profile changed; review grid)':''}. Detect ArUco to update.` : 'No saved association yet. Detect ArUco to create one.');
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

  async function initialize() {
    const data=await api('/status');state.settings=data.settings;state.cameras=data.cameras;
    $('camera_select').innerHTML='<option value="">Select a camera</option>'+data.cameras.map(c=>
      `<option value="${c.id}">${esc(c.name)} (#${c.id})</option>`).join('');
    $('vision_enabled').checked=Boolean(data.settings.enabled);
    $('sample_interval').value=data.settings.sampling_interval_s;
    text('vision_state',data.settings.enabled ? 'Vision enabled' : 'Vision idle');
    const initial = new URLSearchParams(window.location.search);
    const cameraId = initial.get('camera') || data.settings.camera_id;
    const cellId = initial.get('cell') || data.settings.cell_id;
    if (cameraId != null) $('camera_select').value=cameraId;
    await refreshCells(cellId);
    await loadCamera($('camera_select').value);
  }

  $('new_cell').addEventListener('click',action(async()=>{ $('cell_select').value='';await loadCell(null);toast('Enter a new physical cell.'); }));
  $('cell_select').addEventListener('change',action(async()=>loadCell($('cell_select').value)));
  $('save_cell').addEventListener('click',action(saveCell));
  $('camera_select').addEventListener('change',action(async()=>loadCamera($('camera_select').value)));
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
  img.addEventListener('load',renderSelection);
  window.addEventListener('resize',renderSelection);
  img.addEventListener('pointerdown',event=>{
    if(!img.naturalWidth || !img.getAttribute('src'))return;
    if(state.view==='rectified' && (!state.plane || !state.association))return;
    const p=pointOnImage(event);if(!p)return;
    event.preventDefault();
    state.drag={start:p,end:p};
    img.setPointerCapture(event.pointerId);
  });
  img.addEventListener('pointermove',drawDrag);
  img.addEventListener('pointerup',finishDrag);
  img.addEventListener('pointercancel',()=>{state.drag=null;$('roi_drag').hidden=true;});
  initialize().catch(err=>toast(err.message,true));
})();
