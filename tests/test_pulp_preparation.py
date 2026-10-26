"""Tests for the additive, unit-safe Server -> Edge preparation contract."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lib.pulp_preparation import planned_inputs, derived_metrics, quantity


class PulpPreparationTests(unittest.TestCase):
    def test_nested_preparation_converts_mass_and_volume(self):
        recipe = {"metadata": {"pulp_preparation": {
            "dry_solids_mass": {"value": 1.5, "unit": "kg"},
            "water_volume": {"value": 1500, "unit": "mL"},
            "cell_volume": {"value": 2, "unit": "L"},
        }}}
        result = planned_inputs(recipe)
        self.assertEqual(result["feed_mass"]["value"], 1500)
        self.assertEqual(result["water_volume"]["value"], 1.5)
        self.assertEqual(result["working_cell_volume"]["value"], 2)
        self.assertEqual(result["feed_mass"]["source"], "recipe")

    def test_flat_legacy_fields_precede_nested_preparation(self):
        recipe = {
            "feed_mass": 800,
            "metadata": {"pulp_preparation": {"dry_solids_mass": {"value": 2, "unit": "kg"}}},
        }
        self.assertEqual(planned_inputs(recipe)["feed_mass"]["value"], 800)

    def test_null_invalid_and_unknown_units_are_not_invented(self):
        recipe = {"metadata": {"pulp_preparation": {
            "dry_solids_mass": {"value": 1, "unit": "mL"},
            "water_volume": {"value": -3, "unit": "L"},
            "cell_volume": None,
        }}}
        self.assertEqual(planned_inputs(recipe), {})
        self.assertIsNone(quantity({"value": 1, "unit": "unknown"}, "g"))
        self.assertIsNone(quantity(float("nan"), "g"))

    def test_calculated_volume_without_guessing_density(self):
        inputs = {"feed_mass": {"value": 1000, "unit": "g"},
                  "water_volume": {"value": 1.0, "unit": "L"},
                  "working_cell_volume": {"value": 2.0, "unit": "L"}}
        experiment = {"metadata": {"pulp_preparation": {
            "solids_density": {"value": 2.5, "unit": "g/cm³"}
        }}}
        result = derived_metrics(inputs, experiment)
        self.assertAlmostEqual(result["solids_volume_l"]["value"], 0.4)
        self.assertAlmostEqual(result["pulp_volume_l"]["value"], 1.4)
        self.assertAlmostEqual(result["fill_fraction"]["value"], 0.7)
        self.assertNotIn("pulp_density_g_ml", result)
        self.assertNotIn("solids_mass_fraction", result)

    def test_density_requires_explicit_water_density(self):
        inputs = {"feed_mass": {"value": 1000}, "water_volume": {"value": 1},
                  "working_cell_volume": {"value": 2}}
        experiment = {"metadata": {"pulp_preparation": {
            "solids_density": {"value": 2500, "unit": "kg/m³"},
            "water_density_g_ml": 1.0
        }}}
        result = derived_metrics(inputs, experiment)
        self.assertAlmostEqual(result["solids_mass_fraction"]["value"], 0.5)
        self.assertAlmostEqual(result["pulp_density_g_ml"]["value"], 2000 / 1400)

    def test_no_derived_values_with_missing_inputs(self):
        self.assertEqual(derived_metrics({}, {}), {})


if __name__ == "__main__":
    unittest.main()
