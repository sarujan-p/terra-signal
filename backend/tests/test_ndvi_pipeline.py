"""Tests use small synthetic rasters, never fabricated NASA observations."""

import json
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
try:
    import rasterio
    from rasterio.transform import from_origin
except ImportError:
    rasterio = None
    from_origin = None

from ml.ndvi_pipeline import discover_rasters, evaluate_against_baseline, run_pipeline


class NdviPipelineTests(unittest.TestCase):

    @unittest.skipIf(rasterio is None, "Rasterio unavailable")
    def test_duplicate_and_missing_qa_dates_are_rejected(self):
        self._add_date("20200101", 5000)
        source = next(self.raw.glob("*NDVI*"))
        duplicate = self.raw / source.name.replace("aid0001", "aid0002")
        shutil.copyfile(source, duplicate)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            discover_rasters(self.raw)
        duplicate.unlink()
        self._add_date("20210101", 5000)
        next(self.raw.glob("*VI_Quality*20210101*")).unlink()
        with self.assertRaisesRegex(ValueError, "dates do not match"):
            discover_rasters(self.raw)

    @unittest.skipIf(rasterio is None, "Rasterio unavailable")
    def test_map_requires_three_valid_baseline_values_per_pixel(self):
        for year in range(2020, 2026):
            self._add_date(f"{year}0101", 5000)
        for year in range(2020, 2023):
            path = next(self.raw.glob(f"*pixel_reliability*{year}0101*"))
            with rasterio.open(path, "r+") as src:
                values = src.read(1)
                values[1, 1] = 3
                src.write(values, 1)
        run_pipeline(self.raw, self.output)
        features = json.loads((self.output / "vegetation.geojson").read_text())["features"]
        self.assertEqual(len(features), 5)
        self.assertTrue(all(f["properties"]["baseline_observations"] >= 3 for f in features))

    def setUp(self):
        self.root = Path(__file__).parent / f"_tmp_ndvi_{uuid4().hex}"
        self.raw = self.root / "raw"
        self.output = self.root / "output"
        self.raw.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, path, values, dtype, nodata, scale=1.0):
        with rasterio.open(
            path, "w", driver="GTiff", height=3, width=3, count=1,
            dtype=dtype, crs="EPSG:4326", transform=from_origin(149, -35.1, 0.01, 0.01),
            nodata=nodata,
        ) as dst:
            dst.write(np.asarray(values, dtype=dtype), 1)
            dst.scales = (scale,)

    def _add_date(self, date, raw_ndvi):
        stem = f"MOD13Q1.061__250m_16_days_{{layer}}_{date}T000000_aid0001.tif"
        ndvi = np.full((3, 3), raw_ndvi, dtype=np.int16)
        ndvi[0, 0] = -3000
        reliability = np.zeros((3, 3), dtype=np.int8)
        reliability[0, 1] = 1
        quality = np.zeros((3, 3), dtype=np.uint16)
        quality[0, 2] = 2
        self._write(self.raw / stem.format(layer="NDVI"), ndvi, "int16", -3000, 0.0001)
        self._write(self.raw / stem.format(layer="pixel_reliability"), reliability, "int8", -1)
        self._write(self.raw / stem.format(layer="VI_Quality"), quality, "uint16", 65535)

    @unittest.skipIf(rasterio is None, "Rasterio is blocked by the local application-control policy")
    def test_full_pipeline_exports_seasonal_decline(self):
        for year, raw in zip(range(2020, 2026), [5000, 5200, 4800, 5100, 4900, 3000]):
            self._add_date(f"{year}0101", raw)

        result = run_pipeline(self.raw, self.output)
        self.assertEqual(result["source"], "NASA MODIS Terra MOD13Q1.061")
        self.assertEqual(result["status"], "DECLINE")
        self.assertAlmostEqual(result["current"], 0.3, places=4)
        self.assertAlmostEqual(result["baseline"], 0.5, places=4)
        self.assertAlmostEqual(result["absolute_difference"], -0.2, places=4)
        self.assertEqual(result["valid_pixels"], 6)
        self.assertEqual(result["baseline_observations"], 5)
        self.assertTrue((self.output / "ndvi_time_series.csv").is_file())
        self.assertTrue((self.output / "ndvi_evaluation.csv").is_file())
        latest = json.loads((self.output / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual(latest["current_date"], "2025-01-01")
        geojson = json.loads((self.output / "vegetation.geojson").read_text(encoding="utf-8"))
        self.assertEqual(geojson["type"], "FeatureCollection")
        self.assertEqual(len(geojson["features"]), 6)

    def test_low_baseline_suppresses_percentage_classification(self):
        rows = []
        for year, value in zip(range(2020, 2026), [0.04, 0.05, 0.06, 0.05, 0.04, 0.02]):
            rows.append({
                "date": pd.Timestamp(f"{year}-01-01"), "year": year,
                "day_of_year": 1, "seasonal_period": 1,
                "ndvi_mean": value, "ndvi_median": value, "ndvi_std": 0.01,
                "valid_pixels": 9, "total_pixels": 9, "valid_coverage_percent": 100.0,
            })
        result = evaluate_against_baseline(pd.DataFrame(rows))
        self.assertEqual(result.iloc[0]["status"], "LOW_BASELINE")
        self.assertTrue(np.isnan(result.iloc[0]["change_percent"]))
        self.assertAlmostEqual(result.iloc[0]["absolute_difference"], -0.03, places=4)



if __name__ == "__main__":
    unittest.main()
