"""Offline matched-pixel NDVI candidate. Does not publish website data.

Descriptive changes only: no validated ecological labels or significance claims.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from .ndvi_pipeline import discover_rasters, _read_observation
except ImportError:  # Colab uploads both modules into the same directory.
    from ndvi_pipeline import discover_rasters, _read_observation

VERSION = "matched-pixel-candidate-2"


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def compare(current, history, area, minimum_years=4, minimum_coverage=80.0,
            minimum_baseline=0.1):
    """Same locations for current median and median of pixel baselines.

    Coverage 80% is a configurable pilot reporting rule, not a calibrated threshold.
    Low-coverage numerical summaries are diagnostic only; reportable values are null.
    """
    if (isinstance(minimum_years, bool) or not isinstance(minimum_years, (int, np.integer))
            or minimum_years < 3 or not np.isfinite(minimum_coverage)
            or not 0 <= minimum_coverage <= 100 or not np.isfinite(minimum_baseline)
            or not 0 < minimum_baseline <= 1):
        raise ValueError("Invalid comparison parameters")
    current, area = np.asarray(current), np.asarray(area)
    history = [np.asarray(h) for h in history]
    if area.dtype != bool or current.ndim != 2:
        raise ValueError("Expected a Boolean study mask and two-dimensional NDVI arrays")
    if not area.any() or current.shape != area.shape:
        raise ValueError("Empty or mismatched study mask")
    if any(h.shape != current.shape for h in history):
        raise ValueError("Mismatched historical grid")
    for values in [current, *history]:
        if np.isinf(values).any() or np.any(np.isfinite(values) & ((values < -0.2) | (values > 1))):
            raise ValueError("Expected scaled NDVI in [-0.2, 1], with NaN for missing pixels")
    stack = np.stack(history) if len(history) else np.empty((0, *current.shape))
    counts = np.isfinite(stack).sum(axis=0)
    supported = area & (counts >= minimum_years)
    baseline = np.full(current.shape, np.nan)
    if supported.any():
        baseline[supported] = np.nanmedian(stack[:, supported], axis=0)
    matched = supported & np.isfinite(current)
    n = int(matched.sum())
    coverage = 100 * n / int(area.sum())
    cur = float(np.median(current[matched])) if n else np.nan
    base = float(np.median(baseline[matched])) if n else np.nan
    delta = cur - base
    pct = 100 * delta / base if base >= minimum_baseline else np.nan
    if not (area & np.isfinite(current)).any():
        status = "NO_VALID_DATA"
    elif not n:
        status = "INSUFFICIENT_BASELINE"
    elif coverage < minimum_coverage:
        status = "INSUFFICIENT_COVERAGE"
    elif base < minimum_baseline:
        status = "LOW_BASELINE"
    else:
        status = "BELOW_BASELINE" if delta < 0 else "ABOVE_BASELINE" if delta > 0 else "AT_BASELINE"
    reportable = status in {"BELOW_BASELINE", "ABOVE_BASELINE", "AT_BASELINE"}
    result = {
        "status": status, "reportable": reportable,
        "current": cur if reportable else None,
        "baseline": base if reportable else None,
        "absolute_difference": delta if reportable else None,
        "change_percent": pct if reportable else None,
        "diagnostic_current": cur, "diagnostic_baseline": base,
        "diagnostic_change_percent": pct,
        "diagnostic_absolute_difference": delta,
        "matched_pixels": n, "study_pixels": int(area.sum()),
        "matched_coverage_percent": coverage,
        "current_valid_coverage_percent": 100 * int((area & np.isfinite(current)).sum()) / int(area.sum()),
        "historical_images": len(history),
        "minimum_pixel_history": int(counts[matched].min()) if n else 0,
        "median_paired_pixel_difference": float(np.median(current[matched] - baseline[matched])) if n else None,
        "pixels_below_baseline_percent": float(100 * np.mean(current[matched] < baseline[matched])) if n else None,
    }
    return clean(result), baseline, matched, counts


def run_candidate(raw_dir, output_dir, geometry_path, baseline_start=2020,
                  baseline_end=2024, evaluation_year=2025, minimum_years=4,
                  minimum_coverage=80.0, minimum_baseline=0.1):
    from rasterio.features import geometry_mask, bounds
    from rasterio.transform import xy

    if not baseline_start <= baseline_end < evaluation_year:
        raise ValueError("Baseline must precede evaluation")
    if not 3 <= minimum_years <= baseline_end - baseline_start + 1:
        raise ValueError("Insufficient baseline years for requested support")
    output_dir, raw_dir = Path(output_dir), Path(raw_dir)
    if "ndvi_processed" in {p.lower() for p in output_dir.resolve().parts}:
        raise ValueError("Candidate outputs cannot be written to the website data directory")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("Use a new empty candidate output directory; previous results are preserved")
    geometry_doc = json.loads(Path(geometry_path).read_text(encoding="utf-8"))
    geometries = ([f["geometry"] for f in geometry_doc["features"]]
                  if geometry_doc.get("type") == "FeatureCollection" else
                  [geometry_doc["geometry"]] if geometry_doc.get("type") == "Feature" else [geometry_doc])
    if not geometries or any(g.get("type") not in {"Polygon", "MultiPolygon"} for g in geometries):
        raise ValueError("Expected WGS84 Polygon or MultiPolygon study geometry")
    layers = discover_rasters(raw_dir)
    observations, inventory, series, seen = {}, [], [], set()
    grid = None
    for date in sorted(layers["ndvi"]):
        if not baseline_start <= date.year <= evaluation_year:
            continue
        period = (date.dayofyear - 1) // 16 + 1
        if (date.dayofyear - 1) % 16 != 0 or (date.year, period) in seen:
            raise ValueError(f"Unexpected or duplicate composite start: {date}")
        seen.add((date.year, period))
        paths = {name: values[date] for name, values in layers.items()}
        if any(not p.name.startswith("MOD13Q1.061_") for p in paths.values()):
            raise ValueError("Expected MOD13Q1.061 inputs only")
        values, valid, metadata = _read_observation(paths)
        current_grid = (metadata["shape"], metadata["transform"], metadata["crs"])
        if grid is None:
            grid = current_grid
            area = geometry_mask(geometries, out_shape=values.shape,
                                 transform=metadata["transform"], invert=True, all_touched=False)
            if not area.any():
                raise ValueError("Study polygon does not overlap raster pixel centres")
        elif current_grid != grid:
            raise ValueError("All dates must use the same raster grid")
        observations[date] = np.where(area & valid, values.astype(float), np.nan)
        v = observations[date][np.isfinite(observations[date])]
        series.append({"date": str(date.date()), "valid_pixels": len(v),
                       "valid_coverage_percent": 100 * len(v) / int(area.sum()),
                       "ndvi_median": float(np.median(v)) if len(v) else None})
        for layer, path in paths.items():
            inventory.append({"file": path.relative_to(raw_dir).as_posix(), "layer": layer,
                              "date": str(date.date()), "sha256": file_hash(path)})
    evaluation_dates = [d for d in observations if d.year == evaluation_year]
    if not evaluation_dates:
        raise ValueError("No evaluation observations")
    rows, sensitivity, maps = [], [], {}
    for date in evaluation_dates:
        period = (date.dayofyear - 1) // 16 + 1
        historical = [observations[d] for d in observations
                      if baseline_start <= d.year <= baseline_end
                      and (d.dayofyear - 1) // 16 + 1 == period]
        metrics, base, mask, counts = compare(observations[date], historical, area,
                                            minimum_years, minimum_coverage, minimum_baseline)
        end = min(date + pd.Timedelta(days=15), pd.Timestamp(date.year, 12, 31))
        rows.append({"date": str(date.date()), "nominal_calendar_end": str(end.date()),
                     "date_semantics": "Composite label, not pixel acquisition bounds",
                     "seasonal_period": period, **metrics})
        maps[date] = (base, mask, counts)
        for support in range(3, baseline_end - baseline_start + 2):
            test, *_ = compare(observations[date], historical, area, support,
                               minimum_coverage, minimum_baseline)
            sensitivity.append({"date": str(date.date()), "minimum_years": support, **test})
    # Persistence uses common locations and only consecutive available composites.
    persistence = []
    for before, after in zip(evaluation_dates, evaluation_dates[1:]):
        if (after - before).days != 16:
            continue
        base_a, mask_a, _ = maps[before]
        base_b, mask_b, _ = maps[after]
        common = mask_a & mask_b
        n = int(common.sum())
        both = ((observations[before][common] - base_a[common] < 0)
                & (observations[after][common] - base_b[common] < 0))
        persistence.append({"from_date": str(before.date()), "to_date": str(after.date()),
                            "common_pixels": n, "common_coverage_percent": 100 * n / int(area.sum()),
                            "below_baseline_both_percent": float(100 * both.mean()) if n else None})
    latest_date = evaluation_dates[-1]
    latest = rows[-1]
    base, mask, counts = maps[latest_date]
    features = []
    # No map when the region-level coverage rule fails; do not silently map a tiny subset.
    if latest["reportable"]:
        rr, cc = np.where(mask)
        xs, ys = xy(grid[1], rr, cc, offset="center")
        for r, c, x, y in zip(rr, cc, xs, ys):
            current, baseline = float(observations[latest_date][r, c]), float(base[r, c])
            delta = current - baseline
            status = ("LOW_BASELINE" if baseline < minimum_baseline else
                      "BELOW_BASELINE" if delta < 0 else "ABOVE_BASELINE" if delta > 0 else "AT_BASELINE")
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]},
                             "properties": {"date": latest["date"], "ndvi": current, "baseline": baseline,
                                            "absolute_difference": delta, "status": status,
                                            "change_percent": 100 * delta / baseline if baseline >= minimum_baseline else None,
                                            "baseline_observations": int(counts[r, c])}})
    bbox_list = [bounds(g) for g in geometries]
    bbox = [min(b[0] for b in bbox_list), min(b[1] for b in bbox_list),
            max(b[2] for b in bbox_list), max(b[3] for b in bbox_list)]
    manifest = {"schema_version": 2, "pipeline_version": VERSION,
                "validation_status": "AWAITING_INDEPENDENT_VALIDATION", "deployment_allowed": False,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "source": "MOD13Q1.061", "geometry": geometry_doc,
                "parameters": {"baseline_start": baseline_start, "baseline_end": baseline_end,
                               "evaluation_year": evaluation_year, "minimum_years": minimum_years,
                               "minimum_coverage_percent": minimum_coverage, "minimum_baseline": minimum_baseline},
                "coverage_rule_note": "Pilot reporting rule, not empirically calibrated",
                "qa": "pixel_reliability=0 and MODLAND bits=00; original scale metadata",
                "aggregation": "median(current) vs median(pixel historical medians) on identical locations",
                "missing_periods": {str(y): [p for p in range(1, 24) if (y, p) not in seen]
                                    for y in range(baseline_start, evaluation_year + 1)},
                "code_sha256": {p.name: file_hash(p) for p in [Path(__file__), Path(__file__).with_name("ndvi_pipeline.py")]},
                "versions": {p: importlib.metadata.version(p) for p in ["numpy", "pandas", "rasterio"]},
                "inputs": inventory}
    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(series).to_csv(output_dir / "observation_coverage.csv", index=False)
    pd.DataFrame(rows).to_csv(output_dir / "candidate_evaluation.csv", index=False)
    pd.DataFrame(sensitivity).to_csv(output_dir / "support_sensitivity.csv", index=False)
    pd.DataFrame(persistence).to_csv(output_dir / "spatial_persistence.csv", index=False)
    payload = {"pipeline_version": VERSION, "deployment_allowed": False,
               "validation_status": manifest["validation_status"], **latest}
    for name, obj in [("candidate_latest.json", payload), ("manifest.json", manifest),
                      ("candidate_vegetation.geojson", {"type": "FeatureCollection", "bbox": bbox,
                       "map_status": latest["status"], "features": features})]:
        (output_dir / name).write_text(json.dumps(clean(obj), indent=2, allow_nan=False), encoding="utf-8")
    return payload
