"""Known-answer checks for the offline candidate, not ecological accuracy tests."""
import json
import shutil
from contextlib import contextmanager
from uuid import uuid4
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from ml.ndvi_candidate import compare, run_candidate


@contextmanager
def workspace_temp():
    root = Path(__file__).parent / f"_tmp_candidate_{uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        assert root.resolve().is_relative_to(Path(__file__).parent.resolve())
        shutil.rmtree(root)


class CandidateTests(unittest.TestCase):
    def test_matched_locations_remove_spurious_sampling_difference(self):
        # Current only observes the greener half. No actual pixel has changed.
        history = [np.array([[0.2, 0.2, 0.8, 0.8]]) for _ in range(5)]
        current = np.array([[np.nan, np.nan, 0.8, 0.8]])
        result, _, mask, _ = compare(current, history, np.ones((1, 4), bool), minimum_coverage=50)
        self.assertEqual(result["change_percent"], 0)
        self.assertEqual(result["current"], result["baseline"])
        self.assertEqual(int(mask.sum()), 2)

    def test_coverage_is_not_a_health_label(self):
        result, *_ = compare(np.array([[0.3, np.nan]]), [np.array([[0.5, 0.5]])] * 5,
                             np.ones((1, 2), bool))
        self.assertEqual(result["status"], "INSUFFICIENT_COVERAGE")
        self.assertIsNone(result["change_percent"])
        self.assertAlmostEqual(result["diagnostic_change_percent"], -40)

    def test_empty_history_and_low_baseline(self):
        current, area = np.array([[0.02]]), np.ones((1, 1), bool)
        missing, *_ = compare(current, [], area)
        self.assertEqual(missing["status"], "INSUFFICIENT_BASELINE")
        low, *_ = compare(current, [np.array([[0.05]])] * 5, area)
        self.assertEqual(low["status"], "LOW_BASELINE")
        self.assertIsNone(low["change_percent"])

    def test_evaluation_not_in_baseline(self):
        history = [np.array([[0.5]])] * 5
        area = np.ones((1, 1), bool)
        a, *_ = compare(np.array([[0.1]]), history, area)
        b, *_ = compare(np.array([[0.9]]), history, area)
        self.assertEqual(a["baseline"], b["baseline"])
        self.assertAlmostEqual(a["change_percent"], -80)
        self.assertAlmostEqual(b["change_percent"], 80)

    def test_end_to_end_polygon_manifest_and_nondeployment(self):
        with workspace_temp() as folder:
            root = Path(folder)
            raw = root / "raw"
            raw.mkdir()
            geometry = {"type": "Polygon", "coordinates": [[[149, -35.02], [149.01, -35.02],
                         [149.01, -35], [149, -35], [149, -35.02]]]}
            geometry_path = root / "area.geojson"
            geometry_path.write_text(json.dumps(geometry))
            for year in range(2020, 2026):
                for layer, value, dtype, nodata, scale in [
                    ("NDVI", 3000 if year == 2025 else 5000, "int16", -3000, 0.0001),
                    ("pixel_reliability", 0, "int8", -1, 1),
                    ("VI_Quality", 0, "uint16", 65535, 1),
                ]:
                    path = raw / f"MOD13Q1.061__250m_16_days_{layer}_{year}0101T000000_aid0001.tif"
                    with rasterio.open(path, "w", driver="GTiff", count=1, height=2, width=2,
                                       dtype=dtype, nodata=nodata, crs="EPSG:4326",
                                       transform=from_origin(149, -35, 0.01, 0.01)) as dst:
                        dst.write(np.full((2, 2), value, dtype=dtype), 1)
                        dst.scales = (scale,)
            output = root / "candidate"
            result = run_candidate(raw, output, geometry_path)
            self.assertEqual(result["study_pixels"], 2)
            self.assertAlmostEqual(result["change_percent"], -40, places=4)
            self.assertEqual(result["status"], "BELOW_BASELINE")
            self.assertFalse(result["deployment_allowed"])
            self.assertFalse((output / "latest.json").exists())
            geo = json.loads((output / "candidate_vegetation.geojson").read_text())
            self.assertEqual(len(geo["features"]), 2)
            self.assertTrue(all(f["geometry"]["coordinates"][0] < 149.01 for f in geo["features"]))
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(len(manifest["inputs"]), 18)
            self.assertEqual(len(manifest["inputs"][0]["sha256"]), 64)
            self.assertIn(23, manifest["missing_periods"]["2025"])
            with self.assertRaisesRegex(ValueError, "new empty"):
                run_candidate(raw, output, geometry_path)
            with self.assertRaisesRegex(ValueError, "website"):
                run_candidate(raw, root / "ndvi_processed", geometry_path)


if __name__ == "__main__":
    unittest.main()
