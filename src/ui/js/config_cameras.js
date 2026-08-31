const calibrationMode = document.body.dataset.calibrationMode === "true";

let selectedCameraId = null;
let activePreviewId = null;
let cameraData = null;
let loadedSnapshot = null;
let controlValues = {};
let cropSelectionMode = false;
let cropDrag = null;
let performanceEvaluation = null;
let performanceTimer = null;


const elements = {};


const structuralFieldIds = [
    "camera_name",
    "frame_rate",
    "recording_output_type",
    "pixel_format",
    "preview_width",
    "preview_height",
    "preview_frame_rate",
    "preview_quality",
    "calibration_frames",
    "settle_frames",
];


function cacheElements() {
    const ids = [
        "camera_select",
        "global_state_badge",
        "camera_state_badge",
        "hardware_id",
        "sensor_model",
        "sensor_resolution",
        "sensor_location",
        "sensor_rotation",
        "camera_name",
        "frame_rate",
        "recording_output_type",
        "frame_width",
        "frame_height",
        "pixel_format",
        "crop_enabled",
        "crop_x",
        "crop_y",
        "crop_width",
        "crop_height",
        "crop_hint",
        "crop_summary",
        "crop_x_display",
        "crop_y_display",
        "crop_width_display",
        "crop_height_display",
        "preview_stage",
        "preview_viewport",
        "crop_selection_layer",
        "crop_selection_box",
        "select_crop_button",
        "full_sensor_button",
        "preview_width",
        "preview_height",
        "preview_frame_rate",
        "preview_quality",
        "preview_image",
        "preview_placeholder",
        "preview_camera_label",
        "preview_resolution_label",
        "start_preview_button",
        "stop_preview_button",
        "exposure_time_us",
        "analogue_gain",
        "calibration_frames",
        "settle_frames",
        "exposure_summary",
        "apply_exposure_button",
        "calibrate_exposure_button",
        "advanced_controls_grid",
        "unsaved_indicator",
        "save_state_title",
        "save_state_message",
        "reset_button",
        "save_button",
        "confirm_calibration_button",
        "performance_guard",
        "performance_guard_status",
        "performance_guard_message",
        "use_recommended_fps",
        "toast_container",
    ];

    for (const id of ids) {
        elements[id] = document.getElementById(id);
    }
}


async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    const contentType = response.headers.get("content-type") || "";

    let data;
    if (contentType.includes("application/json")) {
        data = await response.json();
    } else {
        data = await response.text();
    }

    if (!response.ok) {
        let message = response.statusText;

        if (typeof data === "string" && data) {
            message = data;
        } else if (data?.detail) {
            message = typeof data.detail === "string"
                ? data.detail
                : JSON.stringify(data.detail);
        }

        throw new Error(message);
    }

    return data;
}


function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;

    elements.toast_container.appendChild(toast);

    requestAnimationFrame(() => {
        toast.classList.add("toast-visible");
    });

    window.setTimeout(() => {
        toast.classList.remove("toast-visible");
        window.setTimeout(() => toast.remove(), 220);
    }, 3500);
}


function formatMetadata(value) {
    if (value === null || value === undefined || value === "") {
        return "—";
    }

    if (Array.isArray(value)) {
        return value.join(" × ");
    }

    if (typeof value === "object") {
        return JSON.stringify(value);
    }

    return String(value);
}


function setStateBadge(element, state, fallback = null) {
    const label = fallback || state || "Unknown";
    const normalised = String(state || "muted").toLowerCase();

    element.className = "state-badge";

    if (normalised === "idle") {
        element.classList.add("state-idle");
    } else if (normalised === "preview") {
        element.classList.add("state-preview");
    } else if (normalised === "recording") {
        element.classList.add("state-recording");
    } else {
        element.classList.add("state-muted");
    }

    element.innerHTML = "";

    const dot = document.createElement("span");
    dot.className = "state-dot";

    const text = document.createTextNode(label);

    element.appendChild(dot);
    element.appendChild(text);
}


function setSaveState(dirty) {
    const recording = cameraData?.state === "Recording";
    const locked = cameraData !== null && !["Idle", "CameraCalibration"].includes(cameraData?.digiflot_state);
    const previewing = activePreviewId !== null;

    elements.unsaved_indicator.classList.toggle(
        "is-dirty",
        dirty
    );

    if (selectedCameraId === null) {
        elements.save_state_title.textContent = "No camera selected";
        elements.save_state_message.textContent =
            "Select a camera to edit its configuration.";
    } else if (recording || locked) {
        elements.save_state_title.textContent = "Configuration locked";
        elements.save_state_message.textContent =
            "Configuration changes are locked during an experiment.";
    } else if (previewing) {
        elements.save_state_title.textContent = "Preview active";
        elements.save_state_message.textContent =
            "Stop preview before saving structural changes.";
    } else if (dirty) {
        elements.save_state_title.textContent = "Unsaved changes";
        elements.save_state_message.textContent =
            "Save to update both the current and default config.json.";
    } else {
        elements.save_state_title.textContent = "Configuration saved";
        elements.save_state_message.textContent =
            "Current values match the stored camera configuration.";
    }

    elements.save_button.disabled = !dirty || recording || locked || previewing;
    elements.reset_button.disabled = !dirty || recording || locked || previewing;
}


function collectPayload() {
    if (!cameraData) {
        return null;
    }

    const exposureTime = parseOptionalInt(
        elements.exposure_time_us.value
    );
    const analogueGain = parseOptionalFloat(
        elements.analogue_gain.value
    );

    return {
        name: elements.camera_name.value.trim(),
        frame_size: outputSizeFromCrop(),
        frame_rate: Number.parseFloat(elements.frame_rate.value),
        format: elements.pixel_format.value,
        crop_region: elements.crop_enabled.checked
            ? [
                Number.parseInt(elements.crop_x.value, 10),
                Number.parseInt(elements.crop_y.value, 10),
                Number.parseInt(elements.crop_width.value, 10),
                Number.parseInt(elements.crop_height.value, 10),
            ]
            : null,
        recording: {
            output_type: elements.recording_output_type.value,
        },
        preview: {
            size: [
                Number.parseInt(elements.preview_width.value, 10),
                Number.parseInt(elements.preview_height.value, 10),
            ],
            frame_rate: Number.parseFloat(
                elements.preview_frame_rate.value
            ),
            quality: Number.parseInt(
                elements.preview_quality.value,
                10
            ),
            encoder_threads: Number.parseInt(
                cameraData.preview?.encoder_threads ?? 1,
                10
            ),
        },
        exposure: {
            exposure_time_us: exposureTime,
            analogue_gain: analogueGain,
            calibration_frames: Number.parseInt(
                elements.calibration_frames.value,
                10
            ),
            settle_frames: Number.parseInt(
                elements.settle_frames.value,
                10
            ),
        },
        controls: structuredClone(controlValues),
    };
}


function parseOptionalInt(value) {
    const trimmed = String(value).trim();
    if (!trimmed) {
        return null;
    }
    return Number.parseInt(trimmed, 10);
}


function parseOptionalFloat(value) {
    const trimmed = String(value).trim();
    if (!trimmed) {
        return null;
    }
    return Number.parseFloat(trimmed);
}


function updateDirtyState() {
    if (!cameraData || !loadedSnapshot) {
        setSaveState(false);
        return;
    }

    const current = collectPayload();
    const dirty = JSON.stringify(current) !== JSON.stringify(loadedSnapshot);

    setSaveState(dirty);
}


function updateCropFieldAvailability() {
    const hasCamera = cameraData !== null;
    const recording = cameraData?.state === "Recording";
    const locked = hasCamera && !["Idle", "CameraCalibration"].includes(cameraData?.digiflot_state);
    const previewingThisCamera = (
        activePreviewId !== null
        && activePreviewId === selectedCameraId
    );

    elements.select_crop_button.disabled =
        !hasCamera || recording || locked || !previewingThisCamera;
    elements.full_sensor_button.disabled =
        !hasCamera || recording || locked || !previewingThisCamera;
}


function updateFieldAvailability() {
    const hasCamera = cameraData !== null;
    const recording = cameraData?.state === "Recording";
    const locked = hasCamera && !["Idle", "CameraCalibration"].includes(cameraData?.digiflot_state);
    const previewing = activePreviewId !== null;

    for (const id of structuralFieldIds) {
        const element = elements[id];
        if (!element) {
            continue;
        }

        element.disabled = !hasCamera || recording || locked || previewing;
    }

    elements.exposure_time_us.disabled = !hasCamera || recording || locked;
    elements.analogue_gain.disabled = !hasCamera || recording || locked;

    updateCropFieldAvailability();

    elements.start_preview_button.disabled =
        !hasCamera || recording || locked || previewing;

    elements.stop_preview_button.disabled = !previewing;
    elements.calibrate_exposure_button.disabled =
        !hasCamera || recording || locked || !previewing || cropSelectionMode;
    elements.apply_exposure_button.disabled =
        !hasCamera || recording || locked || !previewing || cropSelectionMode;

    const controlInputs = elements.advanced_controls_grid.querySelectorAll(
        "input, select"
    );

    for (const input of controlInputs) {
        input.disabled = !hasCamera || recording || locked;
    }

    if (elements.confirm_calibration_button) {
        elements.confirm_calibration_button.disabled = !hasCamera || recording || locked;
    }

    updateDirtyState();
}


function setNumericCapability(element, capability, integer = false) {
    if (!capability) {
        return;
    }

    if (Number.isFinite(Number(capability.minimum))) {
        element.min = capability.minimum;
    }

    if (Number.isFinite(Number(capability.maximum))) {
        element.max = capability.maximum;
    }

    element.step = integer ? "1" : "any";
}


function populateCamera(data) {
    cameraData = data;
    selectedCameraId = data.id;
    activePreviewId = data.is_active_preview
        ? data.id
        : null;

    elements.hardware_id.textContent = data.hardware.id;
    elements.sensor_model.textContent = data.hardware.model || "Unknown";
    elements.sensor_resolution.textContent =
        `${data.hardware.sensor_resolution[0]} × ${data.hardware.sensor_resolution[1]}`;
    elements.sensor_location.textContent = formatMetadata(
        data.hardware.location
    );
    elements.sensor_rotation.textContent = formatMetadata(
        data.hardware.rotation
    );

    elements.camera_name.value = data.name;
    elements.frame_rate.value = data.frame_rate;
    elements.recording_output_type.value = data.recording.output_type;
    elements.frame_width.value = data.frame_size[0];
    elements.frame_height.value = data.frame_size[1];

    elements.pixel_format.innerHTML = "";
    for (const pixelFormat of data.capabilities.pixel_formats) {
        const option = document.createElement("option");
        option.value = pixelFormat;
        option.textContent = pixelFormat;
        elements.pixel_format.appendChild(option);
    }
    elements.pixel_format.value = data.format;

    const sensorWidth = data.hardware.sensor_resolution[0];
    const sensorHeight = data.hardware.sensor_resolution[1];
    elements.frame_width.max = sensorWidth;
    elements.frame_height.max = sensorHeight;
    elements.frame_rate.max = data.capabilities.max_sensor_fps;

    populateCrop(data);

    elements.preview_width.value = data.preview.size[0];
    elements.preview_height.value = data.preview.size[1];
    elements.preview_width.max = sensorWidth;
    elements.preview_height.max = sensorHeight;
    elements.preview_frame_rate.value = data.preview.frame_rate;
    elements.preview_frame_rate.max = data.frame_rate;
    elements.preview_quality.value = data.preview.quality;

    const exposure = data.exposure || {};
    elements.exposure_time_us.value =
        exposure.exposure_time_us ?? "";
    elements.analogue_gain.value =
        exposure.analogue_gain ?? "";
    elements.calibration_frames.value =
        exposure.calibration_frames ?? 30;
    elements.settle_frames.value =
        exposure.settle_frames ?? 5;

    setNumericCapability(
        elements.exposure_time_us,
        data.capabilities.exposure.ExposureTime,
        true
    );
    setNumericCapability(
        elements.analogue_gain,
        data.capabilities.exposure.AnalogueGain,
        false
    );

    updateExposureSummary();
    renderControls(data.capabilities.controls, data.controls || {});

    setStateBadge(
        elements.global_state_badge,
        data.digiflot_state
    );
    setStateBadge(
        elements.camera_state_badge,
        data.state,
        `${data.name} · ${data.state}`
    );

    elements.preview_camera_label.textContent = data.name;
    elements.preview_resolution_label.textContent =
        `${data.preview.size[0]} × ${data.preview.size[1]}`;
    updatePreviewViewportGeometry();

    const option = elements.camera_select.querySelector(
        `option[value="${data.id}"]`
    );
    if (option) {
        option.textContent = data.name;
    }

    loadedSnapshot = structuredClone(collectPayload());

    if (activePreviewId !== null) {
        showPreviewImage(data.id);
    } else {
        hidePreviewImage();
    }

    updateFieldAvailability();
}


function populateCrop(data) {
    const crop = data.crop_region;
    const full = data.capabilities.crop.maximum;

    elements.crop_enabled.checked = crop !== null;

    const values = crop || full;
    elements.crop_x.value = values[0];
    elements.crop_y.value = values[1];
    elements.crop_width.value = values[2];
    elements.crop_height.value = values[3];

    updateCropReadout();
}


function currentCropRegion() {
    if (!elements.crop_enabled.checked) {
        return null;
    }

    return [
        Number.parseInt(elements.crop_x.value, 10),
        Number.parseInt(elements.crop_y.value, 10),
        Number.parseInt(elements.crop_width.value, 10),
        Number.parseInt(elements.crop_height.value, 10),
    ];
}


function fullSensorRegion() {
    return cameraData?.capabilities?.crop?.maximum ?? null;
}


function sensorAspectRatio() {
    const full = fullSensorRegion();
    if (!full || full[3] <= 0) {
        return null;
    }

    return full[2] / full[3];
}


function evenInteger(value, minimum = 2) {
    let result = Math.max(minimum, Math.round(value));
    if (result % 2 !== 0) {
        result += 1;
    }
    return result;
}


function syncPreviewAspectRatio() {
    if (!cameraData) {
        return;
    }

    const full = fullSensorRegion();
    const aspect = sensorAspectRatio();
    if (!full || !aspect) {
        return;
    }

    let width = evenInteger(
        Number.parseInt(elements.preview_width.value, 10) || 640
    );
    width = Math.min(width, full[2] - (full[2] % 2));

    let height = evenInteger(width / aspect);
    if (height > full[3]) {
        height = full[3] - (full[3] % 2);
        width = evenInteger(height * aspect);
    }

    elements.preview_width.value = width;
    elements.preview_height.value = height;
    elements.preview_resolution_label.textContent = `${width} × ${height}`;
}


function updatePreviewViewportGeometry() {
    const aspect = sensorAspectRatio();
    if (!aspect) {
        return;
    }

    elements.preview_viewport.style.setProperty(
        "--sensor-aspect",
        String(aspect)
    );
    elements.preview_viewport.style.setProperty(
        "--preview-max-width",
        `${630 * aspect}px`
    );
}


function outputSizeFromCrop() {
    const full = fullSensorRegion();
    if (!full) {
        return [
            Number.parseInt(elements.frame_width.value, 10) || 2,
            Number.parseInt(elements.frame_height.value, 10) || 2,
        ];
    }

    const crop = currentCropRegion();
    const source = crop || full;

    return [source[2], source[3]];
}


function syncOutputSizeFromCrop() {
    const [width, height] = outputSizeFromCrop();
    elements.frame_width.value = width;
    elements.frame_height.value = height;
}


function updateCropReadout() {
    if (!cameraData) {
        elements.crop_summary.textContent = "Full sensor";
        for (const id of [
            "crop_x_display",
            "crop_y_display",
            "crop_width_display",
            "crop_height_display",
        ]) {
            elements[id].textContent = "—";
        }
        syncOutputSizeFromCrop();
        return;
    }

    const full = fullSensorRegion();
    const crop = currentCropRegion();

    if (crop === null) {
        elements.crop_summary.textContent =
            `Full sensor · ${full[2]} × ${full[3]} px`;
        elements.crop_x_display.textContent = full[0];
        elements.crop_y_display.textContent = full[1];
        elements.crop_width_display.textContent = full[2];
        elements.crop_height_display.textContent = full[3];
        elements.crop_hint.textContent =
            "The complete sensor area will be used for acquisition.";
    } else {
        elements.crop_summary.textContent =
            `${crop[2]} × ${crop[3]} px at (${crop[0]}, ${crop[1]})`;
        elements.crop_x_display.textContent = crop[0];
        elements.crop_y_display.textContent = crop[1];
        elements.crop_width_display.textContent = crop[2];
        elements.crop_height_display.textContent = crop[3];
        elements.crop_hint.textContent =
            "The highlighted region will be applied as ScalerCrop during acquisition.";
    }

    syncOutputSizeFromCrop();

    if (activePreviewId === selectedCameraId) {
        window.requestAnimationFrame(showExistingCropSelection);
    }
}


function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
}


function getPreviewContentRect() {
    if (
        !elements.preview_viewport.classList.contains("is-active")
        || !elements.preview_image.naturalWidth
        || !elements.preview_image.naturalHeight
    ) {
        return null;
    }

    const viewportRect = elements.preview_viewport.getBoundingClientRect();

    if (viewportRect.width <= 0 || viewportRect.height <= 0) {
        return null;
    }

    return {
        left: viewportRect.left,
        top: viewportRect.top,
        width: viewportRect.width,
        height: viewportRect.height,
        right: viewportRect.right,
        bottom: viewportRect.bottom,
        stageLeft: viewportRect.left,
        stageTop: viewportRect.top,
    };
}


function pointInPreview(event) {
    const rect = getPreviewContentRect();
    if (!rect) {
        return null;
    }

    return {
        x: clamp(event.clientX, rect.left, rect.right),
        y: clamp(event.clientY, rect.top, rect.bottom),
        rect,
    };
}


function drawCropSelection(startPoint, endPoint) {
    const rect = startPoint.rect;
    const left = Math.min(startPoint.x, endPoint.x);
    const top = Math.min(startPoint.y, endPoint.y);
    const width = Math.abs(endPoint.x - startPoint.x);
    const height = Math.abs(endPoint.y - startPoint.y);

    elements.crop_selection_box.style.left =
        `${left - rect.stageLeft}px`;
    elements.crop_selection_box.style.top =
        `${top - rect.stageTop}px`;
    elements.crop_selection_box.style.width = `${width}px`;
    elements.crop_selection_box.style.height = `${height}px`;
    elements.crop_selection_box.classList.add("is-visible");
}


function showExistingCropSelection() {
    const rect = getPreviewContentRect();
    const crop = currentCropRegion();

    if (!rect || !crop || !cameraData) {
        elements.crop_selection_box.classList.remove("is-visible");
        return;
    }

    const [fullX, fullY, fullWidth, fullHeight] = fullSensorRegion();

    const left = rect.left
        + ((crop[0] - fullX) / fullWidth) * rect.width;
    const top = rect.top
        + ((crop[1] - fullY) / fullHeight) * rect.height;
    const width = (crop[2] / fullWidth) * rect.width;
    const height = (crop[3] / fullHeight) * rect.height;

    elements.crop_selection_box.style.left =
        `${left - rect.stageLeft}px`;
    elements.crop_selection_box.style.top =
        `${top - rect.stageTop}px`;
    elements.crop_selection_box.style.width = `${width}px`;
    elements.crop_selection_box.style.height = `${height}px`;
    elements.crop_selection_box.classList.add("is-visible");
}


function sensorCropFromSelection(startPoint, endPoint) {
    const rect = startPoint.rect;
    const [fullX, fullY, fullWidth, fullHeight] = fullSensorRegion();
    const fullRight = fullX + fullWidth;
    const fullBottom = fullY + fullHeight;

    const left = Math.min(startPoint.x, endPoint.x);
    const top = Math.min(startPoint.y, endPoint.y);
    const right = Math.max(startPoint.x, endPoint.x);
    const bottom = Math.max(startPoint.y, endPoint.y);

    const nx0 = clamp((left - rect.left) / rect.width, 0, 1);
    const ny0 = clamp((top - rect.top) / rect.height, 0, 1);
    const nx1 = clamp((right - rect.left) / rect.width, 0, 1);
    const ny1 = clamp((bottom - rect.top) / rect.height, 0, 1);

    // Floor the starting edge and ceil the ending edge. This guarantees that
    // selecting exactly to the displayed border never produces +1 px outside
    // the real sensor after floating-point rounding.
    let x = fullX + Math.floor(nx0 * fullWidth);
    let y = fullY + Math.floor(ny0 * fullHeight);
    let sensorRight = fullX + Math.ceil(nx1 * fullWidth);
    let sensorBottom = fullY + Math.ceil(ny1 * fullHeight);

    x = clamp(x, fullX, fullRight - 2);
    y = clamp(y, fullY, fullBottom - 2);
    sensorRight = clamp(sensorRight, x + 2, fullRight);
    sensorBottom = clamp(sensorBottom, y + 2, fullBottom);

    let width = sensorRight - x;
    let height = sensorBottom - y;

    // Acquisition output uses the crop dimensions directly. Keep them even
    // for the YUV420/JPEG pipeline by trimming at most one pixel from the
    // right and bottom edges of the mouse selection.
    width -= width % 2;
    height -= height % 2;
    width = Math.max(2, width);
    height = Math.max(2, height);

    return [x, y, width, height];
}


function setCropSelectionMode(enabled) {
    cropSelectionMode = enabled;
    cropDrag = null;

    elements.crop_selection_layer.classList.toggle(
        "is-active",
        enabled
    );
    elements.preview_stage.classList.toggle(
        "crop-mode",
        enabled
    );
    elements.crop_selection_layer.setAttribute(
        "aria-hidden",
        enabled ? "false" : "true"
    );

    elements.select_crop_button.textContent = enabled
        ? "Cancel selection"
        : "Select crop";

    window.requestAnimationFrame(showExistingCropSelection);
}


async function startCropSelection() {
    if (activePreviewId !== selectedCameraId) {
        showToast("Start preview before selecting a crop.", "warning");
        return;
    }

    if (cropSelectionMode) {
        setCropSelectionMode(false);
        updateFieldAvailability();
        return;
    }

    setCropSelectionMode(true);
    updateFieldAvailability();
    elements.crop_hint.textContent =
        "Drag on the full-sensor preview. The camera image remains unchanged while you edit the crop.";
}


async function useFullSensor() {
    if (activePreviewId !== selectedCameraId) {
        showToast("Start preview before changing the crop.", "warning");
        return;
    }

    setCropSelectionMode(false);

    const full = fullSensorRegion();
    elements.crop_enabled.checked = false;
    elements.crop_x.value = full[0];
    elements.crop_y.value = full[1];
    elements.crop_width.value = full[2];
    elements.crop_height.value = full[3];

    updateCropReadout();
    updateDirtyState();
    updateFieldAvailability();
    showToast("Full sensor selected.", "success");
}


function onCropPointerDown(event) {
    if (!cropSelectionMode || event.button !== 0) {
        return;
    }

    const point = pointInPreview(event);
    if (!point) {
        return;
    }

    cropDrag = {
        pointerId: event.pointerId,
        start: point,
        current: point,
    };

    elements.crop_selection_layer.setPointerCapture(
        event.pointerId
    );
    drawCropSelection(point, point);
    event.preventDefault();
}


function onCropPointerMove(event) {
    if (
        !cropSelectionMode
        || !cropDrag
        || cropDrag.pointerId !== event.pointerId
    ) {
        return;
    }

    const point = pointInPreview(event);
    if (!point) {
        return;
    }

    cropDrag.current = point;
    drawCropSelection(cropDrag.start, point);
    event.preventDefault();
}


async function onCropPointerUp(event) {
    if (
        !cropSelectionMode
        || !cropDrag
        || cropDrag.pointerId !== event.pointerId
    ) {
        return;
    }

    const point = pointInPreview(event) || cropDrag.current;
    const startPoint = cropDrag.start;
    cropDrag = null;

    try {
        elements.crop_selection_layer.releasePointerCapture(
            event.pointerId
        );
    } catch (_) {
        // Pointer capture may already have been released by the browser.
    }

    const displayWidth = Math.abs(point.x - startPoint.x);
    const displayHeight = Math.abs(point.y - startPoint.y);

    if (displayWidth < 8 || displayHeight < 8) {
        showToast("Drag a larger crop region.", "warning");
        showExistingCropSelection();
        return;
    }

    const crop = sensorCropFromSelection(
        startPoint,
        point
    );

    elements.crop_enabled.checked = true;
    elements.crop_x.value = crop[0];
    elements.crop_y.value = crop[1];
    elements.crop_width.value = crop[2];
    elements.crop_height.value = crop[3];

    setCropSelectionMode(false);
    updateFieldAvailability();
    updateCropReadout();
    updateDirtyState();

    showToast(
        `Crop selected: ${crop[2]} × ${crop[3]} px.`,
        "success"
    );
}


function updateExposureSummary() {
    const exposure = elements.exposure_time_us.value;
    const gain = elements.analogue_gain.value;

    if (!exposure || !gain) {
        elements.exposure_summary.textContent =
            "No stored calibration. Calibrate this camera before recording.";
        elements.exposure_summary.classList.add("warning");
        return;
    }

    elements.exposure_summary.textContent =
        `Stored exposure: ${exposure} µs · analogue gain ${Number(gain).toFixed(2)}`;
    elements.exposure_summary.classList.remove("warning");
}


function renderControls(capabilities, values) {
    controlValues = {};
    elements.advanced_controls_grid.innerHTML = "";

    const names = Object.keys(capabilities || {});

    if (!names.length) {
        elements.advanced_controls_grid.innerHTML =
            '<div class="empty-controls">No supported DigiFlot controls were reported by this camera.</div>';
        return;
    }

    for (const name of names) {
        const capability = capabilities[name];
        const value = values[name] ?? capability.value ?? capability.default;
        controlValues[name] = value;

        const field = document.createElement("div");
        field.className = "control-field";

        const header = document.createElement("div");
        header.className = "control-field-header";

        const label = document.createElement("label");
        label.textContent = humaniseControlName(name);

        const range = document.createElement("span");
        range.className = "control-range";

        if (
            capability.minimum !== null
            && capability.minimum !== undefined
            && capability.maximum !== null
            && capability.maximum !== undefined
            && capability.type === "number"
        ) {
            range.textContent = `${capability.minimum} — ${capability.maximum}`;
        }

        header.appendChild(label);
        header.appendChild(range);
        field.appendChild(header);

        if (capability.type === "boolean") {
            const toggleLabel = document.createElement("label");
            toggleLabel.className = "switch-field control-switch";

            const input = document.createElement("input");
            input.type = "checkbox";
            input.checked = Boolean(value);
            input.dataset.controlName = name;

            const switchVisual = document.createElement("span");
            switchVisual.className = "switch";

            const status = document.createElement("span");
            status.textContent = input.checked ? "Enabled" : "Disabled";

            input.addEventListener("change", async () => {
                controlValues[name] = input.checked;
                status.textContent = input.checked ? "Enabled" : "Disabled";
                updateDirtyState();
                await applyControlLive(name, input.checked);
            });

            toggleLabel.appendChild(input);
            toggleLabel.appendChild(switchVisual);
            toggleLabel.appendChild(status);
            field.appendChild(toggleLabel);

        } else if (capability.type === "enum") {
            const select = document.createElement("select");
            select.dataset.controlName = name;

            for (const item of capability.options || []) {
                const option = document.createElement("option");
                option.value = item.value;
                option.textContent = item.label;
                select.appendChild(option);
            }

            select.value = String(value);
            select.addEventListener("change", async () => {
                const nextValue = Number.parseInt(select.value, 10);
                controlValues[name] = nextValue;
                updateDirtyState();
                await applyControlLive(name, nextValue);
            });

            field.appendChild(select);

        } else {
            const row = document.createElement("div");
            row.className = "control-slider-row";

            const slider = document.createElement("input");
            slider.type = "range";
            slider.min = capability.minimum;
            slider.max = capability.maximum;
            slider.step = controlStep(name, capability);
            slider.value = value;
            slider.dataset.controlName = name;

            const number = document.createElement("input");
            number.type = "number";
            number.min = capability.minimum;
            number.max = capability.maximum;
            number.step = slider.step;
            number.value = value;
            number.dataset.controlName = name;
            number.className = "control-number";

            slider.addEventListener("input", () => {
                number.value = slider.value;
                controlValues[name] = Number(slider.value);
                updateDirtyState();
            });

            slider.addEventListener("change", async () => {
                await applyControlLive(name, Number(slider.value));
            });

            number.addEventListener("input", () => {
                slider.value = number.value;
                controlValues[name] = Number(number.value);
                updateDirtyState();
            });

            number.addEventListener("change", async () => {
                await applyControlLive(name, Number(number.value));
            });

            row.appendChild(slider);
            row.appendChild(number);
            field.appendChild(row);
        }

        elements.advanced_controls_grid.appendChild(field);
    }
}


function humaniseControlName(name) {
    return name.replace(/([a-z])([A-Z])/g, "$1 $2");
}


function controlStep(name, capability) {
    if (name === "Brightness") {
        return "0.01";
    }

    const span = Number(capability.maximum) - Number(capability.minimum);
    if (span <= 4) {
        return "0.01";
    }

    return "0.1";
}


async function applyControlLive(name, value) {
    if (activePreviewId !== selectedCameraId) {
        return;
    }

    try {
        await requestJson(
            `/api/cameras/${selectedCameraId}/controls`,
            {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    controls: {
                        [name]: value,
                    },
                }),
            }
        );

        if (loadedSnapshot?.controls) {
            loadedSnapshot.controls[name] = value;
        }

        updateDirtyState();

    } catch (error) {
        showToast(error.message, "error");
    }
}


function renderPerformanceEvaluation(evaluation) {
    performanceEvaluation = evaluation || null;
    if (!elements.performance_guard) return;

    const status = evaluation?.status || "UNAVAILABLE";
    elements.performance_guard.dataset.status = status;
    elements.performance_guard_status.textContent = status;
    elements.performance_guard_message.textContent = evaluation?.reason || "Performance information is unavailable.";

    const recommended = evaluation?.recommended || {};
    const recommendedRate = recommended[String(selectedCameraId)] ?? recommended[selectedCameraId];
    const hasRecommendation = Number.isFinite(Number(recommendedRate));
    elements.use_recommended_fps.hidden = !hasRecommendation;
    if (hasRecommendation) {
        elements.use_recommended_fps.textContent = `Use ${Number(recommendedRate)} fps`;
        elements.use_recommended_fps.dataset.fps = String(recommendedRate);
    }
}

async function evaluatePerformance() {
    if (selectedCameraId === null || !cameraData) return null;
    const frameRate = Number.parseFloat(elements.frame_rate.value);
    if (!Number.isFinite(frameRate)) return null;

    try {
        const evaluation = await requestJson(
            "/api/digiflot/performance/evaluate",
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    camera_id: selectedCameraId,
                    frame_rate: frameRate,
                    camera_config: collectPayload(),
                }),
            }
        );
        renderPerformanceEvaluation(evaluation);
        return evaluation;
    } catch (error) {
        const evaluation = {
            status: "UNAVAILABLE",
            reason: error.message,
        };
        renderPerformanceEvaluation(evaluation);
        return evaluation;
    }
}

function schedulePerformanceEvaluation() {
    window.clearTimeout(performanceTimer);
    performanceTimer = window.setTimeout(evaluatePerformance, 220);
}

async function loadCamera(cameraId) {
    const data = await requestJson(
        `/api/cameras/${cameraId}`
    );

    populateCamera(data);
    await evaluatePerformance();
}


async function onCameraChanged() {
    const nextId = Number.parseInt(
        elements.camera_select.value,
        10
    );

    if (!Number.isFinite(nextId)) {
        return;
    }

    try {
        if (
            activePreviewId !== null
            && activePreviewId !== nextId
        ) {
            await stopPreview(true);
        }

        await loadCamera(nextId);

        if (
            calibrationMode
            && ["pending", "error"].includes(cameraData?.calibration?.status)
        ) {
            showToast("Calibrating exposure…", "info");
            await requestJson(
                `/api/digiflot/calibration/cameras/${nextId}/start`,
                { method: "POST" }
            );
            await loadCamera(nextId);
            showToast(
                "Exposure calibrated. Check crop and controls, then confirm the camera.",
                "success"
            );
        }
    } catch (error) {
        showToast(error.message, "error");
    }
}


async function saveConfiguration(options = {}) {
    if (selectedCameraId === null || !cameraData) {
        return false;
    }

    if (activePreviewId !== null) {
        showToast(
            "Stop preview before saving structural camera settings.",
            "warning"
        );
        return false;
    }

    const payload = collectPayload();
    const latestEvaluation = await evaluatePerformance();

    if (latestEvaluation?.status === "DANGEROUS" && !options.skipPerformanceConfirm) {
        const confirmed = window.confirm(
            `${latestEvaluation.reason || "This configuration failed a previous benchmark."} Continue with this camera configuration anyway?`
        );
        if (!confirmed) return false;
    }

    try {
        elements.save_button.disabled = true;
        elements.save_button.classList.add("is-loading");

        const result = await requestJson(
            `/api/cameras/${selectedCameraId}`,
            {
                method: "PUT",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(payload),
            }
        );

        populateCamera(result.camera);
        await evaluatePerformance();

        if (!options.silent) {
            showToast(
                "Camera configuration saved to current and default config.json.",
                "success"
            );
        }

        return true;

    } catch (error) {
        showToast(error.message, "error");
        return false;

    } finally {
        elements.save_button.classList.remove("is-loading");
        updateFieldAvailability();
    }
}


async function resetChanges() {
    if (selectedCameraId === null) {
        return;
    }

    try {
        await loadCamera(selectedCameraId);
        showToast("Unsaved changes reset.", "info");
    } catch (error) {
        showToast(error.message, "error");
    }
}


async function startPreview() {
    if (selectedCameraId === null) {
        return;
    }

    const dirty = loadedSnapshot
        && JSON.stringify(collectPayload()) !== JSON.stringify(loadedSnapshot);

    if (dirty) {
        const saved = await saveConfiguration({ silent: true });
        if (!saved) {
            return;
        }
    }

    try {
        elements.start_preview_button.disabled = true;
        elements.start_preview_button.classList.add("is-loading");

        const result = await requestJson(
            `/api/cameras/${selectedCameraId}/preview/start`,
            {
                method: "POST",
            }
        );

        activePreviewId = selectedCameraId;
        cameraData.state = "Preview";
        cameraData.digiflot_state = result.state;
        cameraData.is_active_preview = true;

        setStateBadge(
            elements.global_state_badge,
            result.state
        );
        setStateBadge(
            elements.camera_state_badge,
            "Preview",
            `${cameraData.name} · Preview`
        );

        showPreviewImage(selectedCameraId);
        updateFieldAvailability();

        showToast(
            `Preview started for ${cameraData.name}.`,
            "success"
        );

    } catch (error) {
        showToast(error.message, "error");

    } finally {
        elements.start_preview_button.classList.remove("is-loading");
        updateFieldAvailability();
    }
}


function showPreviewImage(cameraId) {
    updatePreviewViewportGeometry();
    elements.preview_placeholder.style.display = "none";
    elements.preview_viewport.classList.add("is-active");
    elements.preview_image.src =
        `/api/cameras/${cameraId}/stream?t=${Date.now()}`;
}


function hidePreviewImage() {
    setCropSelectionMode(false);
    elements.preview_image.removeAttribute("src");
    elements.preview_viewport.classList.remove("is-active");
    elements.crop_selection_box.classList.remove("is-visible");
    elements.preview_placeholder.style.display = "flex";
}


async function stopPreview(silent = false) {
    if (activePreviewId === null) {
        hidePreviewImage();
        return;
    }

    const cameraName = cameraData?.name || "camera";

    hidePreviewImage();

    try {
        elements.stop_preview_button.disabled = true;

        const result = await requestJson(
            "/api/cameras/preview/stop",
            {
                method: "POST",
            }
        );

        activePreviewId = null;

        if (cameraData) {
            cameraData.state = "Idle";
            cameraData.digiflot_state = result.state;
            cameraData.is_active_preview = false;

            setStateBadge(
                elements.global_state_badge,
                result.state
            );
            setStateBadge(
                elements.camera_state_badge,
                "Idle",
                `${cameraData.name} · Idle`
            );
        }

        if (!silent) {
            showToast(
                `Preview stopped for ${cameraName}.`,
                "info"
            );
        }

    } catch (error) {
        if (!silent) {
            showToast(error.message, "error");
        }

    } finally {
        activePreviewId = null;
        updateFieldAvailability();
    }
}


async function calibrateExposure() {
    if (activePreviewId !== selectedCameraId) {
        showToast("Start preview before calibrating exposure.", "warning");
        return;
    }

    try {
        elements.calibrate_exposure_button.disabled = true;
        elements.calibrate_exposure_button.classList.add("is-loading");
        elements.exposure_summary.textContent = "Calibrating auto exposure…";
        elements.exposure_summary.classList.remove("warning");

        const result = await requestJson(
            `/api/cameras/${selectedCameraId}/exposure/calibrate`,
            {
                method: "POST",
            }
        );

        elements.exposure_time_us.value = result.exposure_time_us;
        elements.analogue_gain.value = result.analogue_gain;

        if (loadedSnapshot?.exposure) {
            loadedSnapshot.exposure.exposure_time_us = result.exposure_time_us;
            loadedSnapshot.exposure.analogue_gain = result.analogue_gain;
        }

        if (cameraData?.exposure) {
            cameraData.exposure.exposure_time_us = result.exposure_time_us;
            cameraData.exposure.analogue_gain = result.analogue_gain;
        }

        updateExposureSummary();
        updateDirtyState();

        showToast(
            "Exposure calibrated and saved.",
            "success"
        );

    } catch (error) {
        showToast(error.message, "error");
        updateExposureSummary();

    } finally {
        elements.calibrate_exposure_button.classList.remove("is-loading");
        updateFieldAvailability();
    }
}


async function applyManualExposure() {
    if (activePreviewId !== selectedCameraId) {
        showToast("Start preview before applying exposure.", "warning");
        return;
    }

    const exposureTime = Number.parseInt(
        elements.exposure_time_us.value,
        10
    );
    const analogueGain = Number.parseFloat(
        elements.analogue_gain.value
    );

    if (!Number.isFinite(exposureTime) || !Number.isFinite(analogueGain)) {
        showToast("Enter a valid exposure time and analogue gain.", "warning");
        return;
    }

    try {
        elements.apply_exposure_button.disabled = true;
        elements.apply_exposure_button.classList.add("is-loading");

        const result = await requestJson(
            `/api/cameras/${selectedCameraId}/exposure`,
            {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    exposure_time_us: exposureTime,
                    analogue_gain: analogueGain,
                }),
            }
        );

        elements.exposure_time_us.value = result.exposure_time_us;
        elements.analogue_gain.value = result.analogue_gain;

        if (loadedSnapshot?.exposure) {
            loadedSnapshot.exposure.exposure_time_us = result.exposure_time_us;
            loadedSnapshot.exposure.analogue_gain = result.analogue_gain;
        }

        updateExposureSummary();
        updateDirtyState();

        showToast(
            "Manual exposure applied and saved.",
            "success"
        );

    } catch (error) {
        showToast(error.message, "error");

    } finally {
        elements.apply_exposure_button.classList.remove("is-loading");
        updateFieldAvailability();
    }
}


async function confirmRunCalibration() {
    if (!calibrationMode || selectedCameraId === null) {
        return;
    }

    try {
        elements.confirm_calibration_button.disabled = true;
        elements.confirm_calibration_button.classList.add("is-loading");

        if (activePreviewId !== null) {
            await stopPreview(true);
        }

        const saved = await saveConfiguration({ silent: true });
        if (!saved) {
            return;
        }

        await requestJson(
            `/api/digiflot/calibration/cameras/${selectedCameraId}/confirm`,
            { method: "POST" }
        );

        window.location.href = "/run";

    } catch (error) {
        showToast(error.message, "error");
    } finally {
        elements.confirm_calibration_button?.classList.remove("is-loading");
        updateFieldAvailability();
    }
}

function onConfigurationInput() {
    updateDirtyState();
    schedulePerformanceEvaluation();
}


function bindEvents() {
    elements.camera_select.addEventListener(
        "change",
        onCameraChanged
    );

    elements.start_preview_button.addEventListener(
        "click",
        startPreview
    );

    elements.stop_preview_button.addEventListener(
        "click",
        () => stopPreview(false)
    );

    elements.calibrate_exposure_button.addEventListener(
        "click",
        calibrateExposure
    );

    elements.apply_exposure_button.addEventListener(
        "click",
        applyManualExposure
    );

    elements.use_recommended_fps.addEventListener("click", () => {
        const value = Number.parseFloat(elements.use_recommended_fps.dataset.fps);
        if (!Number.isFinite(value)) return;
        elements.frame_rate.value = value;
        elements.preview_frame_rate.max = value;
        updateDirtyState();
        schedulePerformanceEvaluation();
    });

    elements.save_button.addEventListener(
        "click",
        () => saveConfiguration()
    );

    if (elements.confirm_calibration_button) {
        elements.confirm_calibration_button.addEventListener(
            "click",
            confirmRunCalibration
        );
    }

    elements.reset_button.addEventListener(
        "click",
        resetChanges
    );

    document.querySelectorAll(".camera-field").forEach((element) => {
        element.addEventListener("input", onConfigurationInput);
        element.addEventListener("change", onConfigurationInput);
    });

    elements.select_crop_button.addEventListener(
        "click",
        startCropSelection
    );

    elements.full_sensor_button.addEventListener(
        "click",
        useFullSensor
    );

    elements.crop_selection_layer.addEventListener(
        "pointerdown",
        onCropPointerDown
    );
    elements.crop_selection_layer.addEventListener(
        "pointermove",
        onCropPointerMove
    );
    elements.crop_selection_layer.addEventListener(
        "pointerup",
        onCropPointerUp
    );
    elements.crop_selection_layer.addEventListener(
        "pointercancel",
        onCropPointerUp
    );

    elements.preview_width.addEventListener("input", () => {
        syncPreviewAspectRatio();
        updateDirtyState();
    });

    elements.frame_rate.addEventListener("input", () => {
        elements.preview_frame_rate.max = elements.frame_rate.value;
        schedulePerformanceEvaluation();
    });

    elements.exposure_time_us.addEventListener(
        "input",
        updateExposureSummary
    );
    elements.analogue_gain.addEventListener(
        "input",
        updateExposureSummary
    );

    elements.preview_image.addEventListener("load", () => {
        updatePreviewViewportGeometry();
        showExistingCropSelection();
    });

    window.addEventListener("resize", () => {
        showExistingCropSelection();
    });

    elements.preview_image.addEventListener("error", () => {
        if (activePreviewId === null) {
            return;
        }

        showToast(
            "Preview stream disconnected.",
            "warning"
        );
    });

}


function initialiseEmptyState() {
    setStateBadge(
        elements.camera_state_badge,
        null,
        "No camera selected"
    );

    hidePreviewImage();
    setSaveState(false);
}


document.addEventListener("DOMContentLoaded", async () => {
    cacheElements();
    bindEvents();
    initialiseEmptyState();

    const requestedCamera = Number.parseInt(
        new URLSearchParams(window.location.search).get("camera"),
        10
    );

    if (Number.isFinite(requestedCamera)) {
        elements.camera_select.value = String(requestedCamera);
        await onCameraChanged();
    }
});
