"""Convert HIFIE measurements between physical references, with geometric volume fallback."""
import math
from lib.vision.reference import resolve_vertical_reference

HIFIE_CHANNELS = ("froth_surface_cm", "pulp_froth_interface_cm", "interface_mean_cm", "froth_thickness_cm")


def geometric_area_cm2(cell):
    resolved = (cell or {}).get("resolved_dimensions") or {}
    if "geometric_area_cm2" in resolved:
        return resolved["geometric_area_cm2"]
    from lib.vision.cell_metrics import resolve_cell_dimensions
    return resolve_cell_dimensions(cell)["geometric_area_cm2"]

def resolve_volume_model(cell, model_id=None):
    """Return one current model; reject explicit stale operator choices."""
    from lib.vision.cell_metrics import available_cell_volume_models
    info = (cell or {}).get("volume_models") or {}
    models = info.get("models")
    if models is None: models = available_cell_volume_models(cell or {})
    requested = model_id or info.get("selected_id") or (models[0]["id"] if models else None)
    selected = next((model for model in models if model["id"] == requested), None)
    if requested and selected is None:
        raise ValueError("Selected volume model is no longer valid for this cell; refresh Cells.")
    return selected


def available_volume_area(cell):
    """Return selected valid area for legacy callers, excluding experimental V(h)."""
    selected = resolve_volume_model(cell)
    return ((selected["area_cm2"], selected["area_source"]) if selected and selected.get("area_cm2") else
            (None, None))


def reference_choices(registry, cell_id, association):
    refs = [{"id": "current", "name": "HIFIE configured reference"}]
    if association is None:
        return refs
    for mode, name in (("cell_bottom", "Cell bottom"), ("cell_top", "Cell top")):
        try:
            ref = resolve_vertical_reference({"vertical_reference_mode": mode}, association)
            refs.append({"id": mode, "name": name, "direction": ref["direction"],
                         "y_cm": float(ref["y_cm"])})
        except (ValueError, KeyError, TypeError):
            pass
    for point in registry.reference_points(cell_id)["points"]:
        try:
            ref = resolve_vertical_reference({"reference_id": point["id"]}, association)
            refs.append({"id": point["id"], "name": point["name"], "direction": ref["direction"],
                         "y_cm": float(ref["y_cm"]), "reference_revision": ref.get("reference_revision")})
        except (ValueError, KeyError, TypeError):
            pass
    return refs


def derive_hifie_value(sensor, cell, options, channel, reference_id="current", output="height_cm", volume_model_id=None):
    """Read an existing sample only; do not capture another camera frame."""
    if channel not in HIFIE_CHANNELS or output not in ("height_cm", "volume_l"):
        raise ValueError("Invalid HIFIE interface or output quantity.")
    if not sensor.get("reading_valid"):
        raise ValueError("HIFIE does not have a valid current interface sample.")
    channels = sensor.get("channels") or {}
    if channel == "interface_mean_cm":
        ends = (channels.get("froth_surface_cm"), channels.get("pulp_froth_interface_cm"))
        raw = sum(float(v) for v in ends) / 2 if all(v is not None and math.isfinite(float(v)) for v in ends) else None
    else:
        raw = channels.get(channel)
    if raw is None:
        raise ValueError("Selected HIFIE interface has no measurement.")
    raw = float(raw)
    if not math.isfinite(raw):
        raise ValueError("HIFIE measurement must be finite.")
    if channel == "froth_thickness_cm" and output == "volume_l":
        raise ValueError("Froth thickness is not a liquid height; select an interface.")
    refs = {item["id"]: item for item in options["references"]}
    if reference_id not in refs:
        raise ValueError("Physical reference is not calibrated for this cell.")

    previous = sensor.get("reference") or {}
    direction, previous_y = previous.get("direction"), previous.get("y_cm")
    absolute_y = None
    if channel != "froth_thickness_cm" and previous_y is not None and direction in ("up", "down"):
        absolute_y = float(previous_y) + raw * (1 if direction == "down" else -1)
    target = refs[reference_id]
    value = raw
    if channel != "froth_thickness_cm" and reference_id != "current":
        if absolute_y is None:
            raise ValueError("The HIFIE sample has no absolute Y coordinate; keep its current reference.")
        value = absolute_y - target["y_cm"] if target["direction"] == "down" else target["y_cm"] - absolute_y

    bottom = refs.get("cell_bottom")
    bottom_height = bottom["y_cm"] - absolute_y if bottom and absolute_y is not None else None
    if channel != "froth_thickness_cm" and reference_id == "cell_bottom" and output == "height_cm":
        if value < -0.01:
            raise ValueError("HIFIE interface is below the configured Cell bottom. Check the physical bottom reference and camera-cell calibration.")
        value = max(0.0, value)  # Only neutralize floating-point noise.
    selected_model = resolve_volume_model(cell, volume_model_id) if output == "volume_l" else None
    area = selected_model.get("area_cm2") if selected_model else None
    area_source = selected_model.get("area_source") if selected_model else None
    used_reference = previous if reference_id == "current" else target
    model = None
    curve = cell.get("volume_calibration") or {}
    curve_result = None
    if output == "volume_l":
        if bottom is None:
            raise ValueError("Cell bottom is not calibrated. Define it in Cells.")
        if selected_model is None:
            raise ValueError("Cell has no current volume calibration or valid geometric/visual area; record height instead.")
        if bottom_height is None or bottom_height < -0.01:
            raise ValueError("Interface is below cell bottom; check physical references.")
        height_mm = selected_model.get("height_mm")
        if height_mm is None:
            height_mm = (((cell.get("resolved_dimensions") or {}).get("dimensions") or {})
                         .get("height_mm") or {}).get("value_mm")
        if height_mm not in (None, "") and bottom_height > float(height_mm) / 10.0 + 0.01:
            raise ValueError("Interface is above the cell's physical height.")
        if selected_model["kind"] == "experimental_curve":
            if not curve.get("valid"):
                raise ValueError("Experimental V(h) calibration has expired; revalidate it in Cells.")
            from lib.vision.cell_metrics import evaluate_volume_curve
            curve_result = evaluate_volume_curve(curve, bottom_height)
            value = curve_result["volume_l"]
            area = curve_result["effective_area_cm2"]
            model = "calibrated_volume_curve"
        else:
            value = max(0.0, bottom_height) * area / 1000.0
            model = "visual_outline_area" if selected_model["kind"] == "visual_outline" else "geometric_area"
        used_reference = bottom
    metadata = {"channel": channel, "output": output, "reference_id": used_reference.get("id", reference_id),
                "reference": used_reference, "sensor_reference": previous, "absolute_y_cm": absolute_y,
                "height_from_bottom_cm": bottom_height, "area_cm2": area, "volume_model": model,
                "volume_model_id": selected_model["id"] if selected_model else None,
                "volume_model_label": selected_model["label"] if selected_model else None,
                "volume_model_score": selected_model["score"] if selected_model else None,
                "area_source": "volume_calibration" if curve_result else area_source,
                "dimension_revision": (cell.get("resolved_dimensions") or {}).get("dimension_revision"),
                "volume_calibration_revision": curve.get("revision") if curve_result else None,
                "volume_extrapolated": curve_result["extrapolated"] if curve_result else False,
                "cell_id": cell.get("id"), "cell_revision": cell.get("revision")}
    return {"value": value, "unit": "L" if output == "volume_l" else "cm", "metadata": metadata}
