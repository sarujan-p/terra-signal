import gzip
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

TMP = Path(__file__).parent / "_tmp"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    mock = tmp_path / "mock"
    shutil.copytree(config.MOCK_DIR, mock)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.sqlite")
    monkeypatch.setattr(config, "MOCK_DIR", mock)
    import data_provider
    from services import dashboard, security
    monkeypatch.setattr(data_provider, "_instance", data_provider.MockJsonProvider(mock))
    dashboard.reset_memo()
    security._failures.clear()
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        c.mock_dir = mock
        yield c


def login(c, pw="password"):
    r = c.post("/api/auth/login", json={"username": "sarujan", "password": pw})
    return r


def auth(c):
    return {"Authorization": f"Bearer {login(c).json()['access_token']}"}


def test_canberra_catalog_is_separate_from_archive_cells(client, monkeypatch):
    from routers import data
    original = [{'id': 'country_Australia', 'scope': 'country', 'name': 'Australia', 'cells': 30}]
    monkeypatch.setattr(data.dashboard, 'list_locations', lambda: list(original))
    result = client.get('/api/locations', headers=auth(client))
    assert result.status_code == 200
    locations = result.json()
    assert locations[0] == original[0]
    pilot = locations[1]
    assert pilot['country_id'] == 'country_Australia'
    assert pilot['ndvi_pilot'] is True
    assert pilot['cells'] == 0
    assert pilot['available_indicators'] == ['ndvi']


def test_default_login_and_protection(client):
    assert client.get("/api/dashboard/Sri_Lanka").status_code == 401
    r = login(client)
    assert r.status_code == 200 and r.json()["user"]["is_default_password"] is True
    assert login(client, "wrong").status_code == 401


def test_api_description_omits_personal_author_credit(client):
    description = client.get("/openapi.json").json()["info"]["description"]
    assert "Author:" not in description
    assert "saru.contacts@gmail.com" not in description


def test_dashboard_shape(client):
    d = client.get("/api/dashboard/Sri_Lanka", headers=auth(client)).json()
    assert d["source_mode"] == "MOCK" and len(d["cells"]) == 100 and d["fire"]["clusters"] > 0
    assert [d[k]["label"] for k in ("temperature", "vegetation", "precipitation")] == [
        "Temperature", "Vegetation", "Precipitation"
    ]
    assert [s["indicator"] for s in d["sources"]] == [
        "Temperature", "Vegetation", "Precipitation", "Fire detection"
    ]
    assert "quantile" in d["methodology"]["precipitation"].lower()
    for k in ("temperature", "vegetation", "precipitation", "fire", "overall_anomaly", "explanation", "hotspots"):
        assert k in d
    for p in ("temperature", "vegetation", "precipitation", "fire"):
        assert client.get(f"/api/{p}/Sri_Lanka", headers=auth(client)).status_code == 200


def test_region_and_unknown(client):
    h = auth(client)
    assert len(client.get("/api/locations", headers=h).json()) > 10
    r = client.get("/api/dashboard/Jaffna", headers=h).json()
    assert r["scope"] == "region" and len(r["cells"]) == 2
    assert client.get("/api/dashboard/Atlantis", headers=h).status_code == 404


def test_map_area_boundaries(client, tmp_path, monkeypatch):
    from routers import data as data_router

    path = tmp_path / "admin1.geojson.gz"
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"admin": "Testland", "name_en": "North"},
             "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
            {"type": "Feature", "properties": {"admin": "Elsewhere", "name_en": "South"},
             "geometry": {"type": "Polygon", "coordinates": [[[1, 1], [2, 1], [2, 2], [1, 1]]]}}
        ]
    }
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(geojson, stream)
    monkeypatch.setattr(data_router, "ADMIN1_BOUNDARIES", path)
    data_router._admin1_features.cache_clear()
    try:
        response = client.get("/api/map/areas/Testland", headers=auth(client))
        assert response.status_code == 200
        assert [feature["properties"]["name"] for feature in response.json()["features"]] == ["North"]
        assert client.get("/api/map/areas/Missing", headers=auth(client)).status_code == 404
    finally:
        data_router._admin1_features.cache_clear()


def test_map_country_boundaries(client):
    response = client.get("/api/map/countries", headers=auth(client))
    assert response.status_code == 200
    names = {feature["properties"]["name"] for feature in response.json()["features"]}
    assert "Bangladesh" in names


def test_change_password_flow(client):
    h = auth(client)
    bad = client.post("/api/auth/change-password", headers=h, json={"current_password": "nope", "new_password": "Longer-pass1"})
    assert bad.status_code == 400
    short = client.post("/api/auth/change-password", headers=h, json={"current_password": "password", "new_password": "abc"})
    assert short.status_code == 422
    ok = client.post("/api/auth/change-password", headers=h, json={"current_password": "password", "new_password": "Longer-pass1"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 401           # old token revoked
    new_h = {"Authorization": f"Bearer {ok.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=new_h).json()["is_default_password"] is False
    assert login(client, "password").status_code == 401
    assert login(client, "Longer-pass1").status_code == 200


def test_lockout(client):
    for _ in range(5):
        assert login(client, "bad").status_code == 401
    assert login(client, "password").status_code == 429


def test_data_swap_is_picked_up(client):
    """Editing the data files (e.g. real NASA export) changes the dashboard with no code change."""
    h = auth(client)
    before = client.get("/api/dashboard/Sri_Lanka", headers=h).json()["temperature"]["current"]
    f = client.mock_dir / "temperature.json"
    d = json.loads(f.read_text())
    for r in d["observations"]:
        r["current"] += 5
    d["source_mode"] = "LIVE"
    f.write_text(json.dumps(d))
    os.utime(f, None)
    after = client.get("/api/dashboard/Sri_Lanka", headers=h).json()
    assert round(after["temperature"]["current"] - before, 1) == 5.0
    assert after["source_mode"] == "MIXED"


def test_bad_data_gives_clear_error_and_cache_fallback(client):
    h = auth(client)
    assert client.get("/api/dashboard/Sri_Lanka", headers=h).status_code == 200   # primes the cache
    f = client.mock_dir / "fires.json"
    f.write_text("{not json")
    os.utime(f, None)
    r = client.get("/api/dashboard/Sri_Lanka", headers=h)
    assert r.status_code == 200 and r.json()["served_from_cache"] is True
    assert client.get("/api/dashboard/Jaffna", headers=h).status_code == 503      # nothing cached for it
