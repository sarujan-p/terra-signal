import csv
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile
import pytest
from services.ndvi_package import ROOT, validate_package
from routers.ndvi import canberra_candidate


@pytest.fixture
def package_parts():
    r = dict(date='2025-12-19', reportable=True, status='BELOW_BASELINE',
             current=.4, baseline=.5, absolute_difference=-.1, change_percent=-20.,
             matched_pixels=1, study_pixels=1, matched_coverage_percent=100., minimum_pixel_history=5)
    latest = dict(r, pipeline_version='matched-pixel-candidate-2', deployment_allowed=False)
    m = dict(source='MOD13Q1.061', pipeline_version=latest['pipeline_version'], deployment_allowed=False,
             validation_status='AWAITING_INDEPENDENT_VALIDATION',
             geometry=json.loads((ROOT/'backend/ml/canberra_ndvi.geojson').read_text()),
             code_sha256={n:hashlib.sha256((ROOT/'backend/ml'/n).read_bytes()).hexdigest() for n in ['ndvi_candidate.py','ndvi_pipeline.py']},
             parameters=dict(baseline_start=2020,baseline_end=2024,evaluation_year=2025,minimum_years=4,minimum_coverage_percent=80.,minimum_baseline=.1))
    g = dict(type='FeatureCollection',features=[dict(type='Feature',geometry=dict(type='Point',coordinates=[149.1,-35.3]),properties=dict(date=r['date'],ndvi=.4,baseline=.5,absolute_difference=-.1,change_percent=-20.,baseline_observations=5,status='BELOW_BASELINE'))])
    return m, latest, [r], g


def write_package(path, parts):
    m,l,rows,g=parts
    s=io.StringIO();w=csv.DictWriter(s,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    with ZipFile(path,'w') as z:
        for n,v in [('manifest.json',m),('candidate_latest.json',l),('candidate_vegetation.geojson',g)]: z.writestr(n,json.dumps(v))
        z.writestr('candidate_evaluation.csv',s.getvalue())


def test_valid_package_and_route(tmp_path,monkeypatch,package_parts):
    p=tmp_path/'review.zip';write_package(p,package_parts)
    assert validate_package(p)['result']['change_percent']==-20
    monkeypatch.setenv('SATSCOPE_NDVI_REVIEW_PACKAGE',str(p))
    assert canberra_candidate()['compound_eligible'] is False


def test_http_review_routes(tmp_path, monkeypatch, package_parts):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.ndvi import router
    from routers.auth import current_user
    p = tmp_path/'review.zip'; write_package(p, package_parts)
    monkeypatch.setenv('SATSCOPE_NDVI_REVIEW_PACKAGE', str(p))
    app = FastAPI(); app.include_router(router)
    client = TestClient(app)
    assert client.get('/api/ndvi/canberra/review').status_code in (401, 403)
    app.dependency_overrides[current_user] = lambda: {'username': 'test'}
    result = client.get('/api/ndvi/canberra/review')
    assert result.status_code == 200
    assert result.json()['compound_eligible'] is False
    assert client.get('/api/ndvi/canberra/timeseries').json()['rows'][0]['current'] == .4
    assert len(client.get('/api/ndvi/canberra/geojson').json()['features']) == 1
    p.write_bytes(b'broken')
    assert client.get('/api/ndvi/canberra/review').status_code == 503


@pytest.mark.parametrize('fault',['date','value','geometry','hash','pixel','duplicate','missing','nan'])
def test_corruption(tmp_path,package_parts,fault):
    m,l,rows,g=package_parts
    if fault=='date': l['date']='2025-12-03'
    if fault=='value': rows[0]['change_percent']=-10
    if fault=='geometry': m['geometry']={}
    if fault=='hash': m['code_sha256']['ndvi_candidate.py']='wrong'
    if fault=='pixel': g['features'][0]['geometry']['coordinates']=[0,0]
    if fault=='duplicate': rows.append(dict(rows[0]))
    if fault=='missing': del l['baseline']
    if fault=='nan': l['current']=float('nan')
    p=tmp_path/'review.zip';write_package(p,package_parts)
    with pytest.raises(ValueError): validate_package(p)
