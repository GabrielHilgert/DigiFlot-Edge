"""Hardware-free checks for inventory publication and cell photo revisions."""
import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from lib.cell_inventory import build_inventory
from lib.vision.registry import VisionRegistry

class InventoryTests(unittest.TestCase):
    def test_registered_cells_and_configured_sensors_without_samples(self):
        with tempfile.TemporaryDirectory() as root:
            registry=VisionRegistry(root)
            cell=registry.save_cell({"name":"Labcell 4L","working_volume_l":4,
                "geometry":{"shape":"rectangular","height_mm":200,"width_mm":120}})
            atlas=SimpleNamespace(sensors=[{"name":"pH probe","type":"ph"}],
                                  sensor_id=lambda sensor:"atlas_ph")
            device=SimpleNamespace(cameras={1:object()},scales={"s":SimpleNamespace(id="scale_1",name="Mass")},
                atlas=atlas,bronkhorst={},wago={},plugin_sensors={},vision=SimpleNamespace(registry=registry))
            data=build_inventory(device)
            self.assertEqual(data["cells"][0]["id"],cell["id"])
            self.assertEqual(data["cells"][0]["working_volume_l"],4)
            self.assertIn("HIFIE",{s["short_name"] for s in data["sensors"]})
            self.assertEqual([s["short_name"] for s in data["sensors"] if s["id"]=="atlas_ph"],["pH"])
            self.assertNotIn("value",data["sensors"][0])
            self.assertNotIn("status",data["sensors"][0])

    def test_geometry_and_photo_revision_are_independent(self):
        with tempfile.TemporaryDirectory() as root:
            registry=VisionRegistry(root)
            original=registry.save_cell({"name":"Cell A"})
            same=registry.save_cell({"id":original["id"],"name":"Cell A"})
            self.assertEqual(original["revision"],same["revision"])
            data=b"RIFF" + b"1234" + b"WEBP" + b"thumbnail"
            image=registry.save_thumbnail(original["id"],data)
            self.assertEqual(image["revision"],1)
            self.assertEqual(registry.save_thumbnail(original["id"],data)["revision"],1)
            updated=registry.get_cell(original["id"])
            self.assertEqual(updated["revision"],original["revision"])
            self.assertEqual(updated["thumbnail"]["revision"],1)

if __name__=="__main__":unittest.main()
