"""Validate the complete Canberra v2 review export; never infer ecological accuracy."""
import csv
import hashlib
import io
import json
import math
from datetime import date
from pathlib import Path
from statistics import median
from zipfile import ZipFile, BadZipFile

ROOT = Path(__file__).resolve().parents[2]
FILES = ('manifest.json', 'candidate_latest.json', 'candidate_evaluation.csv', 'candidate_vegetation.geojson')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def number(x):
    return type(x) in (int, float) and math.isfinite(x)


def close(a, b):
    return number(a) and number(b) and math.isclose(a, b, rel_tol=0, abs_tol=1e-6)


def strict_json(text):
    def pairs(items):
        result = {}
        for k, v in items:
            require(k not in result, 'Duplicate JSON key')
            result[k] = v
        return result
    def invalid(value):
        raise ValueError('Non-finite JSON')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def validate_package(path):
    """Read a ZIP or directory, validate all parts, return JSON-safe review data."""
    try:
        path = Path(path)
        if path.is_dir():
            texts = {n: (path / n).read_text(encoding='utf-8') for n in FILES}
        else:
            with ZipFile(path) as z:
                require(len(z.namelist()) == len(set(z.namelist())), 'Duplicate ZIP entries')
                require(all(n in z.namelist() for n in FILES), 'Missing package files')
                require(sum(z.getinfo(n).file_size for n in FILES) < 100_000_000, 'Package too large')
                texts = {n: z.read(n).decode('utf-8') for n in FILES}
        m, latest, geo = [strict_json(texts[n]) for n in (FILES[0], FILES[1], FILES[3])]
        require(m['source'] == 'MOD13Q1.061', 'Wrong product')
        require(m['pipeline_version'] == latest['pipeline_version'] == 'matched-pixel-candidate-2', 'Wrong version')
        require(m['deployment_allowed'] is False and latest['deployment_allowed'] is False, 'Deployment must remain disabled')
        require(m['geometry'] == strict_json((ROOT / 'backend/ml/canberra_ndvi.geojson').read_text()), 'Wrong study geometry')
        for name in ('ndvi_candidate.py', 'ndvi_pipeline.py'):
            require(hashlib.sha256((ROOT / 'backend/ml' / name).read_bytes()).hexdigest() == m['code_sha256'][name], 'Source hash mismatch')
        p = m['parameters']
        require(p == dict(baseline_start=2020, baseline_end=2024, evaluation_year=2025,
                         minimum_years=4, minimum_coverage_percent=80.0, minimum_baseline=0.1), 'Unexpected pilot policy')
        rows = list(csv.DictReader(io.StringIO(texts[FILES[2]])))
        require(bool(rows), 'Empty time series')
        keys = ('current', 'baseline', 'absolute_difference', 'change_percent', 'matched_pixels',
                'study_pixels', 'matched_coverage_percent', 'minimum_pixel_history')
        for row in rows:
            require(row['reportable'] in ('True', 'False'), 'Invalid CSV Boolean')
            row['reportable'] = row['reportable'] == 'True'
            for k in keys:
                row[k] = float(row[k]) if row[k] else None
        dates = [r['date'] for r in rows]
        require(dates == sorted(set(dates)), 'Duplicate or unsorted dates')
        for r in [*rows, latest]:
            d = date.fromisoformat(r['date'])
            require(d.year == 2025 and (d.timetuple().tm_yday - 1) % 16 == 0, 'Invalid composite date')
            require(type(r['reportable']) is bool, 'Invalid reportable flag')
            n, total = r['matched_pixels'], r['study_pixels']
            require(number(n) and number(total) and total > 0 and 0 <= n <= total and int(n) == n and int(total) == total, 'Invalid counts')
            require(close(r['matched_coverage_percent'], 100*n/total), 'Coverage/count mismatch')
            if r['reportable']:
                cur, base = r['current'], r['baseline']
                require(number(cur) and number(base) and -.2 <= cur <= 1 and .1 <= base <= 1, 'Invalid NDVI')
                require(r['matched_coverage_percent'] >= 80 and r['minimum_pixel_history'] >= 4, 'Insufficient reporting support')
                delta = cur-base
                require(close(r['absolute_difference'], delta) and close(r['change_percent'], 100*delta/base), 'Incorrect calculation')
                require(r['status'] == ('BELOW_BASELINE' if delta < 0 else 'ABOVE_BASELINE' if delta > 0 else 'AT_BASELINE'), 'Incorrect status')
            else:
                require(r['status'] in ('NO_VALID_DATA', 'INSUFFICIENT_BASELINE', 'INSUFFICIENT_COVERAGE', 'LOW_BASELINE'), 'Invalid unavailable status')
                require(all(r[k] is None for k in keys[:4]), 'Unavailable metrics must be null')
        require(latest['date'] == dates[-1], 'Stale latest summary')
        for k in (*keys, 'status', 'reportable'):
            a, b = latest[k], rows[-1][k]
            require(a == b if not number(a) else close(a,b), 'Latest/time-series mismatch: '+k)
        require(geo['type'] == 'FeatureCollection' and isinstance(geo['features'], list), 'Invalid map')
        features = geo['features']
        require(len(features) == (latest['matched_pixels'] if latest['reportable'] else 0), 'Map count mismatch')
        coords, currents, bases = set(), [], []
        for f in features:
            require(f['type'] == 'Feature' and f['geometry']['type'] == 'Point', 'Invalid map feature')
            xy = f['geometry']['coordinates']
            require(len(xy) == 2 and all(number(v) for v in xy), 'Invalid coordinates')
            x,y = xy
            require(149 <= x <= 149.3 and -35.45 <= y <= -35.15 and tuple(xy) not in coords, 'Wrong or duplicate map location')
            coords.add(tuple(xy))
            v = f['properties']; c,b = v['ndvi'],v['baseline']
            require(v['date'] == latest['date'] and 4 <= v['baseline_observations'] <= 5, 'Map support/date mismatch')
            require(number(c) and number(b) and -.2 <= c <= 1 and -.2 <= b <= 1, 'Invalid map NDVI')
            require(close(v['absolute_difference'],c-b), 'Invalid pixel difference')
            require(close(v['change_percent'],100*(c-b)/b) if b >= .1 else v['change_percent'] is None, 'Invalid pixel percentage')
            expected = 'LOW_BASELINE' if b < .1 else 'BELOW_BASELINE' if c < b else 'ABOVE_BASELINE' if c > b else 'AT_BASELINE'
            require(v['status'] == expected, 'Invalid pixel status')
            currents.append(c); bases.append(b)
        if features:
            require(close(median(currents),latest['current']) and close(median(bases),latest['baseline']), 'Map medians mismatch')
        return {'result': latest, 'timeseries': rows, 'geojson': geo,
                'validation_status': m['validation_status'], 'deployment_allowed': False}
    except (OSError, BadZipFile, KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError('Invalid NDVI package: '+str(exc)) from exc
