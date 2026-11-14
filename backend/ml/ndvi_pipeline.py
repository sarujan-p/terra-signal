"""Process MOD13Q1 GeoTIFFs into SAT-SCOPE vegetation outputs.

The same module is intended for the production backend and Google Colab.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

DATE_PATTERN = re.compile(r"_(\d{8})T")
MIN_VALID_NDVI = -0.2
MAX_VALID_NDVI = 1.0


def _date_from_name(path: Path) -> pd.Timestamp:
    match = DATE_PATTERN.search(path.name)
    if not match:
        raise ValueError(f"Cannot find acquisition date in {path.name}")
    return pd.Timestamp(match.group(1))


def discover_rasters(raw_dir: Path) -> dict[str, dict[pd.Timestamp, Path]]:
    """Index the three required AppEEARS layers by composite date."""
    files = list(raw_dir.rglob("*.tif"))
    layers = {
        "ndvi": [p for p in files if "_NDVI_" in p.name],
        "reliability": [p for p in files if "pixel_reliability" in p.name],
        "quality": [p for p in files if "VI_Quality" in p.name],
    }
    indexed = {}
    for name, paths in layers.items():
        indexed[name] = {}
        for path in paths:
            date = _date_from_name(path)
            if date in indexed[name]:
                raise ValueError(f"Duplicate {name} raster for {date.date()}; use one area per run")
            indexed[name][date] = path
    missing = [name for name, values in indexed.items() if not values]
    if missing:
        counts = {name: len(values) for name, values in indexed.items()}
        raise ValueError(f"Missing required MOD13Q1 layers: {missing}; discovered {counts}")
    if not (set(indexed["ndvi"]) == set(indexed["reliability"]) == set(indexed["quality"])):
        raise ValueError("NDVI and QA dates do not match; download all three layers")
    return indexed


def _read_observation(paths: dict[str, Path]) -> tuple[np.ndarray, np.ndarray, dict]:
    """Return scaled NDVI, strict good-quality mask and raster metadata."""
    import rasterio

    with rasterio.open(paths["ndvi"]) as ndvi_src, \
         rasterio.open(paths["reliability"]) as reliability_src, \
         rasterio.open(paths["quality"]) as quality_src:
        aligned = (
            ndvi_src.shape == reliability_src.shape == quality_src.shape
            and ndvi_src.transform == reliability_src.transform == quality_src.transform
            and ndvi_src.crs == reliability_src.crs == quality_src.crs
        )
        if not aligned:
            raise ValueError(f"Raster alignment mismatch for {paths['ndvi'].name}")
        if ndvi_src.crs != rasterio.crs.CRS.from_epsg(4326):
            raise ValueError("Export AppEEARS data in geographic EPSG:4326 for this pipeline")

        raw = ndvi_src.read(1, masked=True)
        reliability = reliability_src.read(1, masked=True)
        quality = quality_src.read(1, masked=True)
        scale = float(ndvi_src.scales[0] or 1.0)
        offset = float(ndvi_src.offsets[0] or 0.0)
        if not np.isclose(scale, 0.0001) or offset != 0:
            raise ValueError("Expected packed MOD13Q1 NDVI with scale 0.0001 and offset 0")
        ndvi = raw.data.astype(np.float32) * scale + offset
        modland_qa = quality.data.astype(np.uint16) & 0b11
        valid = (
            ~np.ma.getmaskarray(raw)
            & ~np.ma.getmaskarray(reliability)
            & ~np.ma.getmaskarray(quality)
            & (raw.data >= -2000)
            & (raw.data <= 10000)
            & (reliability.data == 0)
            & (modland_qa == 0)
            & np.isfinite(ndvi)
            & (ndvi >= MIN_VALID_NDVI)
            & (ndvi <= MAX_VALID_NDVI)
        )
        metadata = {
            "shape": ndvi_src.shape,
            "transform": ndvi_src.transform,
            "crs": str(ndvi_src.crs),
            "bounds": list(ndvi_src.bounds),
            "scale": scale,
            "offset": offset,
        }
    return ndvi, valid, metadata


def build_time_series(
    raw_dir: Path,
    baseline_start: int = 2020,
    baseline_end: int = 2024,
    evaluation_year: int = 2025,
) -> tuple[pd.DataFrame, dict[str, dict[pd.Timestamp, Path]]]:
    if not baseline_start <= baseline_end < evaluation_year:
        raise ValueError("Baseline years must precede the evaluation year")
    layers = discover_rasters(raw_dir)
    dates = sorted(set(layers["ndvi"]) & set(layers["reliability"]) & set(layers["quality"]))
    start = pd.Timestamp(f"{baseline_start}-01-01")
    end = pd.Timestamp(f"{evaluation_year}-12-31")
    dates = [date for date in dates if start <= date <= end]
    if not dates:
        raise ValueError("No matched MOD13Q1 composites fall inside the requested analysis years")

    records = []
    reference = None
    for date in dates:
        paths = {name: values[date] for name, values in layers.items()}
        ndvi, valid, metadata = _read_observation(paths)
        grid = (metadata["shape"], metadata["transform"], metadata["crs"])
        if reference is not None and grid != reference:
            raise ValueError("All dates must use the same raster grid")
        reference = grid
        values = ndvi[valid]
        records.append({
            "date": date,
            "year": date.year,
            "day_of_year": date.dayofyear,
            "seasonal_period": (date.dayofyear - 1) // 16 + 1,
            "ndvi_mean": float(np.mean(values)) if values.size else np.nan,
            "ndvi_median": float(np.median(values)) if values.size else np.nan,
            "ndvi_std": float(np.std(values)) if values.size else np.nan,
            "valid_pixels": int(values.size),
            "total_pixels": int(ndvi.size),
            "valid_coverage_percent": float(values.size / ndvi.size * 100),
        })
    return pd.DataFrame(records).sort_values("date").reset_index(drop=True), layers


def evaluate_against_baseline(
    series: pd.DataFrame,
    baseline_start: int = 2020,
    baseline_end: int = 2024,
    evaluation_year: int = 2025,
    minimum_baseline_ndvi: float = 0.1,
) -> pd.DataFrame:
    """Compare each evaluation composite with its historical seasonal period."""
    historical = series[series["year"].between(baseline_start, baseline_end)].copy()
    current = series[series["year"] == evaluation_year].copy()
    if historical.empty or current.empty:
        raise ValueError("Both baseline years and the evaluation year require observations")

    def summarize(group: pd.DataFrame) -> pd.Series:
        values = group["ndvi_median"].dropna().to_numpy(dtype=float)
        median = float(np.median(values)) if values.size else np.nan
        mad = float(np.median(np.abs(values - median))) if values.size else np.nan
        std = float(np.std(values, ddof=1)) if values.size > 1 else np.nan
        candidates = [0.01]
        if np.isfinite(mad):
            candidates.append(1.4826 * mad)
        if np.isfinite(std):
            candidates.append(std)
        return pd.Series({
            "baseline_ndvi": median,
            "baseline_mean": float(np.mean(values)) if values.size else np.nan,
            "baseline_std": std,
            "baseline_mad": mad,
            "seasonal_sigma": max(candidates),
            "baseline_observations": int(values.size),
        })

    baseline = historical.groupby("seasonal_period", as_index=False).apply(
        summarize, include_groups=False
    ).reset_index(drop=True)
    result = current.merge(baseline, on="seasonal_period", how="left")
    result["absolute_difference"] = result["ndvi_median"] - result["baseline_ndvi"]
    safe = (result["baseline_ndvi"] >= minimum_baseline_ndvi) & (result["baseline_observations"] >= 3)
    result["change_percent"] = np.where(
        safe,
        result["absolute_difference"] / result["baseline_ndvi"] * 100,
        np.nan,
    )
    result["anomaly_score"] = result["absolute_difference"] / result["seasonal_sigma"]

    def classify(row: pd.Series) -> str:
        if not np.isfinite(row["ndvi_median"]):
            return "NO_VALID_DATA"
        if row["baseline_observations"] < 3 or not np.isfinite(row["anomaly_score"]):
            return "INSUFFICIENT_BASELINE"
        if row["baseline_ndvi"] < minimum_baseline_ndvi:
            return "LOW_BASELINE"
        if row["anomaly_score"] <= -2:
            return "DECLINE"
        if row["anomaly_score"] <= -1:
            return "STRESSED"
        if row["anomaly_score"] >= 2:
            return "GREENING"
        return "STABLE"

    result["status"] = result.apply(classify, axis=1)
    return result.sort_values("date").reset_index(drop=True)


def build_latest_geojson(
    layers: dict[str, dict[pd.Timestamp, Path]],
    evaluation: pd.DataFrame,
    baseline_start: int,
    baseline_end: int,
    minimum_baseline_ndvi: float = 0.1,
) -> dict:
    """Create pixel-centre map features for the latest evaluation composite."""
    from rasterio.transform import xy

    latest = evaluation.iloc[-1]
    latest_date = pd.Timestamp(latest["date"])
    period = int(latest["seasonal_period"])
    current_paths = {name: values[latest_date] for name, values in layers.items()}
    current, current_valid, metadata = _read_observation(current_paths)

    baseline_arrays = []
    for date in sorted(layers["ndvi"]):
        if baseline_start <= date.year <= baseline_end and (date.dayofyear - 1) // 16 + 1 == period:
            if not all(date in layers[name] for name in layers):
                continue
            paths = {name: values[date] for name, values in layers.items()}
            values, valid, other_metadata = _read_observation(paths)
            if other_metadata["shape"] != metadata["shape"] or other_metadata["transform"] != metadata["transform"]:
                raise ValueError("Baseline rasters do not align with the current raster")
            baseline_arrays.append(np.where(valid, values, np.nan))
    if len(baseline_arrays) < 3:
        raise ValueError("At least three aligned historical rasters are required for the decline map")

    stack = np.stack(baseline_arrays)
    counts = np.sum(np.isfinite(stack), axis=0)
    historical_pixels = counts >= 3
    baseline = np.full(current.shape, np.nan, dtype=np.float32)
    mad = np.full(current.shape, np.nan, dtype=np.float32)
    baseline[historical_pixels] = np.nanmedian(stack[:, historical_pixels], axis=0)
    mad[historical_pixels] = np.nanmedian(
        np.abs(stack[:, historical_pixels] - baseline[historical_pixels]), axis=0
    )
    std = np.full(current.shape, np.nan, dtype=np.float32)
    std[historical_pixels] = np.nanstd(stack[:, historical_pixels], axis=0, ddof=1)
    sigma = np.maximum(np.maximum(1.4826 * mad, std), 0.01)
    difference = current - baseline
    score = difference / sigma
    valid = current_valid & np.isfinite(baseline)
    rows, cols = np.where(valid)
    xs, ys = xy(metadata["transform"], rows, cols, offset="center")

    features = []
    for row, col, lon, lat in zip(rows, cols, xs, ys):
        base = float(baseline[row, col])
        diff = float(difference[row, col])
        anomaly = float(score[row, col])
        if base < minimum_baseline_ndvi:
            status, change = "LOW_BASELINE", None
        else:
            change = diff / base * 100
            status = "DECLINE" if anomaly <= -2 else "STRESSED" if anomaly <= -1 else \
                "GREENING" if anomaly >= 2 else "STABLE"
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
            "properties": {
                "date": latest_date.strftime("%Y-%m-%d"),
                "ndvi": round(float(current[row, col]), 4),
                "baseline": round(base, 4),
                "absolute_difference": round(diff, 4),
                "change_percent": round(float(change), 2) if change is not None else None,
                "anomaly_score": round(anomaly, 3),
                "status": status,
                "baseline_observations": int(counts[row, col]),
            },
        })
    return {"type": "FeatureCollection", "bbox": metadata["bounds"], "features": features}


def _clean_json_value(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def export_results(
    series: pd.DataFrame,
    evaluation: pd.DataFrame,
    geojson: dict,
    output_dir: Path,
    location: str,
    baseline_start: int,
    baseline_end: int,
    evaluation_year: int,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    series_out = series.copy()
    series_out["date"] = series_out["date"].dt.strftime("%Y-%m-%d")
    evaluation_out = evaluation.copy()
    evaluation_out["date"] = evaluation_out["date"].dt.strftime("%Y-%m-%d")
    series_out.to_csv(output_dir / "ndvi_time_series.csv", index=False)
    evaluation_out.to_csv(output_dir / "ndvi_evaluation.csv", index=False)
    (output_dir / "vegetation.geojson").write_text(json.dumps(geojson), encoding="utf-8")

    latest = evaluation.iloc[-1]
    coordinates = [feature["geometry"]["coordinates"] for feature in geojson["features"]]
    bounds = None
    if geojson.get("bbox"):
        west, south, east, north = geojson["bbox"]
        bounds = dict(west=west, south=south, east=east, north=north)
    elif coordinates:
        longitudes, latitudes = zip(*coordinates)
        bounds = {
            "west": min(longitudes), "south": min(latitudes),
            "east": max(longitudes), "north": max(latitudes),
        }
    latest_payload = {
        "location": location,
        "indicator": "NDVI",
        "source": "NASA MODIS Terra MOD13Q1.061",
        "current_date": latest["date"],
        "current": latest["ndvi_median"],
        "baseline": latest["baseline_ndvi"],
        "absolute_difference": latest["absolute_difference"],
        "change_percent": latest["change_percent"],
        "anomaly_score": latest["anomaly_score"],
        "status": latest["status"],
        "valid_pixels": latest["valid_pixels"],
        "valid_coverage_percent": latest["valid_coverage_percent"],
        "baseline_observations": latest["baseline_observations"],
        "baseline_period": f"{baseline_start}-{baseline_end}",
        "evaluation_year": evaluation_year,
        "temporal_resolution": "16-day composite",
        "quality_filter": "pixel_reliability=0 and MODLAND QA bits=00",
        "bounds": bounds,
        "trend_dates": evaluation["date"].tolist(),
        "trend_ndvi": evaluation["ndvi_median"].tolist(),
        "baseline_series": evaluation["baseline_ndvi"].tolist(),
    }
    latest_payload = {key: _clean_json_value(value) if not isinstance(value, list) else
                      [_clean_json_value(item) for item in value]
                      for key, value in latest_payload.items()}
    (output_dir / "latest.json").write_text(
        json.dumps(latest_payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    return latest_payload


def run_pipeline(
    raw_dir: Path,
    output_dir: Path,
    location: str = "Canberra_Australia",
    baseline_start: int = 2020,
    baseline_end: int = 2024,
    evaluation_year: int = 2025,
) -> dict:
    series, layers = build_time_series(raw_dir, baseline_start, baseline_end, evaluation_year)
    evaluation = evaluate_against_baseline(series, baseline_start, baseline_end, evaluation_year)
    geojson = build_latest_geojson(layers, evaluation, baseline_start, baseline_end)
    return export_results(
        series, evaluation, geojson, output_dir, location,
        baseline_start, baseline_end, evaluation_year,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Directory containing AppEEARS GeoTIFFs")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--location", default="Canberra_Australia")
    parser.add_argument("--baseline-start", type=int, default=2020)
    parser.add_argument("--baseline-end", type=int, default=2024)
    parser.add_argument("--evaluation-year", type=int, default=2025)
    args = parser.parse_args()
    result = run_pipeline(
        args.input, args.output, args.location,
        args.baseline_start, args.baseline_end, args.evaluation_year,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
