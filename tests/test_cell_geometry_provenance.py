"""Reference-provenance geometry resolution, without camera hardware."""
import tempfile
import unittest

from lib.vision.cell_metrics import resolve_cell_dimensions, normalize_dimension_pairs
from lib.vision.reference import default_reference_points, normalize_reference_points, complete_reference_points
from lib.vision.registry import VisionRegistry


class GeometryProvenanceTests(unittest.TestCase):
    def points(self):
        library = default_reference_points()
        for point in library["points"]:
            if point["id"] == "cell_top":
                point.update(position_cm=[0., -12.], source="image_selection")
            if point["id"] == "cell_bottom":
                point.update(position_cm=[0., 8.], source="image_selection")
        library["points"].extend([
            {"id": "left", "name": "Left", "type": "custom", "position_cm": [-5., 0.],
             "direction": "up", "source": "image_selection"},
            {"id": "right", "name": "Right", "type": "custom", "position_cm": [5., 0.],
             "direction": "up", "source": "image_selection"}])
        return library

    def test_fixed_references_and_non_destructive_legacy(self):
        defaults = default_reference_points()
        self.assertEqual([x["id"] for x in defaults["points"][:2]], ["outlet_level", "aruco_reference"])
        self.assertIn("cell_top", {x["id"] for x in defaults["points"]})
        old = {"revision": 4, "default_reference_id": "outlet_level", "points": defaults["points"][:2]}
        migrated = complete_reference_points(old)
        self.assertEqual(len(migrated["points"]), 4)
        self.assertEqual(old["revision"], 4)
        with self.assertRaisesRegex(ValueError, "Mandatory"):
            normalize_reference_points(old)
        points = self.points()
        points["points"][2]["name"] = "Removed"
        with self.assertRaisesRegex(ValueError, "fixed name"):
            normalize_reference_points(points)

    def test_existing_unplaced_canonical_reuses_legacy_coordinates_without_deleting_id(self):
        points = default_reference_points()
        points["revision"] = 7
        points["points"].extend([
            {"id": "older_top", "name": "Cell Top", "type": "top",
             "position_cm": [3., -9.], "direction": "down", "source": "image_selection"},
            {"id": "older_bottom", "name": "Cell Bottom", "type": "bottom",
             "position_cm": [3., 12.], "direction": "up", "source": "measured"}])
        completed = complete_reference_points(points)
        lookup = {p["id"]: p for p in completed["points"]}
        self.assertEqual(lookup["cell_top"]["position_cm"], [3., -9.])
        self.assertEqual(lookup["cell_bottom"]["position_cm"], [3., 12.])
        self.assertEqual(lookup["older_top"]["position_cm"], [3., -9.])
        self.assertEqual(completed["revision"], 7)
        self.assertIsNone(next(p for p in points["points"] if p["id"] == "cell_top")["position_cm"])
        resolved = resolve_cell_dimensions({"reference_points": completed})
        self.assertAlmostEqual(resolved["dimensions"]["height_mm"]["value_mm"], 210.)

    def test_differing_canonical_and_legacy_positions_are_preserved(self):
        points = default_reference_points()
        points["points"][2].update({"position_cm": [0., -5.], "source": "measured"})
        points["points"].append({"id": "legacy_top", "name": "Cell Top", "type": "top",
                                 "position_cm": [0., -9.], "direction": "down", "source": "measured"})
        completed = complete_reference_points(points)
        by_id = {p["id"]: p for p in completed["points"]}
        self.assertEqual(by_id["cell_top"]["position_cm"], [0., -5.])
        self.assertEqual(by_id["legacy_top"]["position_cm"], [0., -9.])

    def test_measured_height_overrides_nominal_and_width_pair(self):
        cell = {"geometry": {"shape": "rectangular", "height_mm": 150, "width_mm": 130, "depth_mm": 80},
                "reference_points": self.points(), "marker_layout": {"span_cm": 14, "marker_size_cm": 2}}
        pairs = {"revision": 2, "pairs": {"width_mm": {"from_id": "left", "to_id": "right"}}}
        result = resolve_cell_dimensions(cell, pairs)
        self.assertAlmostEqual(result["dimensions"]["height_mm"]["value_mm"], 200)
        self.assertAlmostEqual(result["dimensions"]["width_mm"]["value_mm"], 100)
        self.assertEqual(result["dimensions"]["height_mm"]["source"], "measured")
        self.assertEqual(result["dimensions"]["depth_mm"]["source"], "nominal")
        self.assertAlmostEqual(result["geometric_area_cm2"], 80)
        self.assertEqual(result["geometric_area_source"], "mixed_geometry")
        self.assertEqual(result["dimension_revision"], 2)

    def test_nominal_fallback_and_no_unwarranted_area(self):
        cell = {"geometry": {"shape": "custom", "height_mm": 150},
                "reference_points": default_reference_points()}
        result = resolve_cell_dimensions(cell)
        self.assertEqual(result["dimensions"]["height_mm"]["source"], "nominal")
        self.assertIsNone(result["geometric_area_cm2"])
        self.assertIsNone(result["effective_area_cm2"])

    def test_persistent_mappings_do_not_mutate_nominal_or_aruco_revision(self):
        with tempfile.TemporaryDirectory() as path:
            registry = VisionRegistry(path)
            cell = registry.save_cell({"name": "Test", "geometry": {
                "shape": "rectangular", "height_mm": 150, "width_mm": 90, "depth_mm": 70}})
            registry.save_reference_points(cell["id"], self.points())
            record = registry.save_dimension_measurements(cell["id"], {
                "pairs": {"width_mm": {"from_id": "left", "to_id": "right"}}, "expected_revision": 0})
            self.assertEqual(record["revision"], 1)
            enriched = registry.get_cell(cell["id"])
            self.assertEqual(enriched["revision"], cell["revision"])
            self.assertEqual(enriched["dimension_measurements"]["revision"], 1)
            self.assertEqual(enriched["resolved_dimensions"]["dimensions"]["height_mm"]["source"], "measured")
            self.assertEqual(registry.save_dimension_measurements(cell["id"], {"pairs": record["pairs"]})["revision"], 1)
            with self.assertRaisesRegex(RuntimeError, "another tab"):
                registry.save_dimension_measurements(cell["id"], {"pairs": {}, "expected_revision": 0})

    def test_mapped_dimension_needs_both_positions(self):
        cell = {"geometry": {"shape": "cylindrical", "width_mm": 100},
                "reference_points": default_reference_points()}
        mapping = {"pairs": {"width_mm": {"from_id": "outlet_level", "to_id": "cell_top"}}}
        result = resolve_cell_dimensions(cell, mapping)
        self.assertEqual(result["dimensions"]["width_mm"]["source"], "nominal")
        self.assertAlmostEqual(result["geometric_area_cm2"], 25 * 3.141592653589793)
        with self.assertRaisesRegex(ValueError, "different"):
            normalize_dimension_pairs({"pairs": {"width_mm": {"from_id": "cell_top", "to_id": "cell_top"}}},
                                      default_reference_points())


if __name__ == "__main__":
    unittest.main()
