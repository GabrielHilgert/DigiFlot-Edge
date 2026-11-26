"""HIFIE measurement source conversion; no camera is required for these tests."""
import math
import unittest
from lib.vision.derived_measurements import derive_hifie_value, geometric_area_cm2


class HifieMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.cell = {"id": "cellA", "revision": 4,
                     "geometry": {"shape": "cylindrical", "width_mm": 100, "height_mm": 200}}
        self.options = {"references": [
            {"id": "current", "name": "Sensor"},
            {"id": "cell_bottom", "name": "Bottom", "direction": "up", "y_cm": 20.0},
            {"id": "outlet", "name": "Outlet", "direction": "up", "y_cm": 5.0}]}
        self.sensor = {"reading_valid": True, "reference": {"y_cm": 5.0, "direction": "down"},
                       "channels": {"froth_surface_cm": 5.0, "pulp_froth_interface_cm": 7.0,
                                    "froth_thickness_cm": 2.0}}

    def test_reference_conversion(self):
        got = derive_hifie_value(self.sensor, self.cell, self.options, "pulp_froth_interface_cm", "cell_bottom")
        self.assertAlmostEqual(got["value"], 8.0)
        self.assertEqual(got["metadata"]["absolute_y_cm"], 12.0)

    def test_geometric_volume_uses_bottom_and_liters(self):
        got = derive_hifie_value(self.sensor, self.cell, self.options, "pulp_froth_interface_cm",
                                 "cell_bottom", "volume_l")
        self.assertAlmostEqual(got["value"], math.pi * 25 * 8 / 1000)
        self.assertEqual(got["metadata"]["volume_model"], "geometric_area")

    def test_without_area_height_is_still_available(self):
        self.cell["geometry"] = {"shape": "custom"}
        got = derive_hifie_value(self.sensor, self.cell, self.options, "froth_surface_cm")
        self.assertEqual(got["value"], 5)
        with self.assertRaisesRegex(ValueError, "area"):
            derive_hifie_value(self.sensor, self.cell, self.options, "froth_surface_cm",
                               "cell_bottom", "volume_l")

    def test_negative_height_is_not_forced_positive(self):
        self.sensor["channels"]["pulp_froth_interface_cm"] = 20
        with self.assertRaisesRegex(ValueError, "below"):
            derive_hifie_value(self.sensor, self.cell, self.options, "pulp_froth_interface_cm",
                               "cell_bottom", "volume_l")

    def test_thickness_not_volume(self):
        with self.assertRaisesRegex(ValueError, "thickness"):
            derive_hifie_value(self.sensor, self.cell, self.options, "froth_thickness_cm",
                               "cell_bottom", "volume_l")

    def test_interface_mean_is_derived_from_both_channels(self):
        got=derive_hifie_value(self.sensor,self.cell,self.options,"interface_mean_cm","cell_bottom","height_cm")
        self.assertAlmostEqual(got["value"],9.)
        self.assertEqual(got["metadata"]["channel"],"interface_mean_cm")
        self.assertEqual(got["unit"],"cm")
        self.sensor["channels"]["pulp_froth_interface_cm"]=None
        with self.assertRaisesRegex(ValueError,"no measurement"):
            derive_hifie_value(self.sensor,self.cell,self.options,"interface_mean_cm")

    def test_invalid_negative_bottom_height_is_not_silently_flipped(self):
        self.sensor["channels"]["pulp_froth_interface_cm"]=30.
        with self.assertRaisesRegex(ValueError,"below the configured Cell bottom"):
            derive_hifie_value(self.sensor,self.cell,self.options,"pulp_froth_interface_cm","cell_bottom")

    def test_explicit_volume_model_alternatives_and_auditable_selection(self):
        self.cell["volume_models"]={"selected_id":"geometry:low","models":[
            {"id":"geometry:low","label":"Measured section","kind":"geometric","area_cm2":100.,
             "area_source":"measured_geometry","score":750,"height_mm":200},
            {"id":"outline:shape_a","label":"Optical section","kind":"visual_outline","area_cm2":125.,
             "area_source":"visual_outline_estimate","score":800,"height_mm":200}]}
        default=derive_hifie_value(self.sensor,self.cell,self.options,"pulp_froth_interface_cm",
                                   "cell_bottom","volume_l")
        selected=derive_hifie_value(self.sensor,self.cell,self.options,"pulp_froth_interface_cm",
                                    "cell_bottom","volume_l",volume_model_id="outline:shape_a")
        self.assertAlmostEqual(default["value"],.8)
        self.assertAlmostEqual(selected["value"],1.)
        self.assertEqual(selected["metadata"]["volume_model_id"],"outline:shape_a")
        self.assertEqual(selected["metadata"]["volume_model"],"visual_outline_area")
        with self.assertRaisesRegex(ValueError,"no longer valid"):
            derive_hifie_value(self.sensor,self.cell,self.options,"pulp_froth_interface_cm",
                               "cell_bottom","volume_l",volume_model_id="outline:expired")

    def test_rectangular_area(self):
        self.assertEqual(geometric_area_cm2({"geometry": {"shape": "rectangular",
                         "width_mm": 100, "depth_mm": 80}}), 80)
        self.assertIsNone(geometric_area_cm2({"geometry": {"shape": "custom"}}))


if __name__ == "__main__":
    unittest.main()
