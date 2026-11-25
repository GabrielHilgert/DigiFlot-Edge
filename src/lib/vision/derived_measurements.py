"""Convert HIFIE measurements between physical references, with geometric volume fallback."""
import math
from lib.vision.reference import resolve_vertical_reference

HIFIE_CHANNELS = ("froth_surface_cm", "pulp_froth_interface_cm", "froth_thickness_cm")


def geometric_area_cm2(cell):
    resolved = (cell or {}).get("resolved_dimensions") or {}
    if "geometric_area_cm2" in resolved:
        return resolved["geometric_area_cm2"]
    from lib.vision.cell_metrics import resolve_cell_dimensions
    return resolve_cell_dimensions(cell)["geometric_area_cm2"]

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


def derive_hifie_value(sensor, cell, options, channel, reference_id="current", output="height_cm"):
    """Read an existing sample only; do not capture another camera frame."""
    if channel not in HIFIE_CHANNELS or output not in ("height_cm", "volume_l"):
        raise ValueError("Invalid HIFIE interface or output quantity.")
    if not sensor.get("reading_valid"):
        raise ValueError("HIFIE does not have a valid current interface sample.")
    raw = (sensor.get("channels") or {}).get(channel)
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
    area = geometric_area_cm2(cell)
    used_reference = previous if reference_id == "current" else target
    model = None
    curve = cell.get("volume_calibration") or {}
    curve_result = None
    if output == "volume_l":
        if bottom is None:
            raise ValueError("Cell bottom is not calibrated. Define it in Cells.")
        if area is None and not curve.get("valid"):
            raise ValueError("Cell has no current volume calibration or geometric area; record height instead.")
        if bottom_height is None or bottom_height < -0.01:
            raise ValueError("Interface is below cell bottom; check physical references.")
        height_mm = (((cell.get("resolved_dimensions") or {}).get("dimensions") or {})
                     .get("height_mm") or {}).get("value_mm")
        if height_mm is None:
            height_mm = (cell.get("geometry") or {}).get("height_mm")
        if height_mm not in (None, "") and bottom_height > float(height_mm) / 10.0 + 0.01:
            raise ValueError("Interface is above the cell's physical height.")
        if curve.get("valid"):
            from lib.vision.cell_metrics import evaluate_volume_curve
            curve_result = evaluate_volume_curve(curve, bottom_height)
            value = curve_result["volume_l"]
            area = curve_result["effective_area_cm2"]
            model = "calibrated_volume_curve"
        else:
            value = max(0.0, bottom_height) * area / 1000.0
            model = "geometric_area"
        used_reference = bottom
    metadata = {"channel": channel, "output": output, "reference_id": used_reference.get("id", reference_id),
                "reference": used_reference, "sensor_reference": previous, "absolute_y_cm": absolute_y,
                "height_from_bottom_cm": bottom_height, "area_cm2": area, "volume_model": model,
                "area_source": ("volume_calibration" if curve_result else
                                (cell.get("resolved_dimensions") or {}).get("geometric_area_source")),
                "dimension_revision": (cell.get("resolved_dimensions") or {}).get("dimension_revision"),
                "volume_calibration_revision": curve.get("revision") if curve_result else None,
                "volume_extrapolated": curve_result["extrapolated"] if curve_result else False,
                "cell_id": cell.get("id"), "cell_revision": cell.get("revision")}
    return {"value": value, "unit": "L" if output == "volume_l" else "cm", "metadata": metadata}
