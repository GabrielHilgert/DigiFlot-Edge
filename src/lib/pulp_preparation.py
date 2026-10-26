"""Recipe-to-execution pulp quantities and explicitly derived metrics.

The Server stores optional preparation quantities in metadata.pulp_preparation.
The Edge stores operator-confirmed quantities in execution_inputs. This module
bridges those representations without modifying the original scientific recipe.
"""
import math

UNITS = {
    "g": ("mass", 1.0),
    "kg": ("mass", 1000.0),
    "mg": ("mass", 0.001),
    "t": ("mass", 1_000_000.0),
    "l": ("volume", 1.0),
    "ml": ("volume", 0.001),
    "g/cm3": ("density", 1.0),
    "kg/m3": ("density", 0.001),
    "g/ml": ("density", 1.0),
}
FIELDS = {
    "working_cell_volume": ("L", ("working_cell_volume", "cell_volume", "working_volume")),
    "feed_mass": ("g", ("feed_mass", "dry_solids_mass", "ore_mass", "mass_of_solids", "solids_mass")),
    "water_volume": ("L", ("water_volume", "water_volume_l")),
}


def _number(value):
    if isinstance(value, bool) or value in ("", None):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def _unit_name(value):
    return (str(value or "").lower().strip()
            .replace("³", "3").replace("µ", "u").replace(" ", ""))


def quantity(value, unit):
    """Return a quantity in the requested unit, or None if incompatible.

    Unit-less historical numeric values are already expressed in the field's
    established unit. Structured values must state convertible units.
    """
    target = UNITS.get(_unit_name(unit))
    if target is None:
        return None
    supplied_unit = unit
    if isinstance(value, dict):
        supplied_unit = value.get("unit") or unit
        value = value.get("value")
    numeric = _number(value)
    supplied = UNITS.get(_unit_name(supplied_unit))
    if numeric is None or supplied is None or supplied[0] != target[0]:
        return None
    return numeric * supplied[1] / target[1]


def planned_inputs(experiment):
    """Read the historical flat and new nested Server formats.

    The old flat fields take precedence; an optional nested preparation only
    fills an input that was not explicitly provided elsewhere.
    """
    recipe = experiment if isinstance(experiment, dict) else {}
    metadata = recipe.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    pulp = metadata.get("pulp_preparation")
    pulp = pulp if isinstance(pulp, dict) else {}
    result = {}
    for field, (unit, aliases) in FIELDS.items():
        for origin, source in (
            (recipe, "recipe"),
            (metadata, "metadata"),
            (pulp, "metadata.pulp_preparation"),
        ):
            for key in aliases:
                if key not in origin:
                    continue
                value = quantity(origin[key], unit)
                if value is not None:
                    result[field] = {"value": value, "source": "recipe",
                                     "recipe_path": source + "." + key}
                    break
            if field in result:
                break
    return result


def derived_metrics(execution_inputs, experiment):
    """Compute only quantities supported by known inputs and densities.

    No water or solids density is silently substituted. The output is an
    informational snapshot: never persist derived values as measurements.
    """
    recipe = experiment if isinstance(experiment, dict) else {}
    metadata = recipe.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    pulp = metadata.get("pulp_preparation")
    pulp = pulp if isinstance(pulp, dict) else {}

    def reading(key, unit):
        item = (execution_inputs or {}).get(key)
        if isinstance(item, dict):
            return quantity({"value": item.get("value"), "unit": item.get("unit") or unit}, unit)
        return quantity(item, unit)

    solids_g = reading("feed_mass", "g")
    water_l = reading("water_volume", "L")
    cell_l = reading("working_cell_volume", "L")

    rho_solids = quantity(pulp.get("solids_density", metadata.get("solids_density")), "g/cm3")
    rho_water = quantity(pulp.get("water_density_g_ml", metadata.get("water_density_g_ml")), "g/ml")

    result = {}

    def add(key, value, unit, label):
        if value is not None and math.isfinite(value):
            result[key] = {"value": value, "unit": unit, "label": label, "source": "derived"}

    if solids_g is not None and rho_solids and rho_solids > 0:
        solids_l = (solids_g / rho_solids) / 1000.0
        add("solids_volume_l", solids_l, "L", "Estimated solids volume")
    else:
        solids_l = None

    if water_l is not None and solids_l is not None:
        pulp_l = water_l + solids_l
        add("pulp_volume_l", pulp_l, "L", "Estimated pulp volume")
        if cell_l is not None and cell_l > 0:
            add("fill_fraction", pulp_l / cell_l, "fraction", "Estimated cell fill fraction")
    else:
        pulp_l = None

    if solids_g is not None and water_l is not None and rho_water and rho_water > 0:
        water_g = water_l * 1000 * rho_water
        total_g = solids_g + water_g
        if total_g > 0:
            add("solids_mass_fraction", solids_g / total_g, "fraction", "Solids mass fraction")
            if pulp_l is not None and pulp_l > 0:
                add("pulp_density_g_ml", total_g / (pulp_l * 1000),
                    "g/mL", "Estimated pulp density")

    return result
