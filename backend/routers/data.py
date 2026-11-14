import gzip
import json
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

import config
from data_provider import DataError, get_provider
from routers.auth import current_user
from services import cache, dashboard

router = APIRouter(prefix="/api", tags=["data"], dependencies=[Depends(current_user)])
ADMIN1_BOUNDARIES = Path(__file__).resolve().parents[2] / "data" / "history" / "natural_earth_10m_admin_1.geojson.gz"
COUNTRY_BOUNDARIES = Path(__file__).resolve().parents[2] / "data" / "history" / "natural_earth_110m_countries.geojson"


@lru_cache(maxsize=1)
def _admin1_features():
    with gzip.open(ADMIN1_BOUNDARIES, "rt", encoding="utf-8") as stream:
        return json.load(stream)["features"]


@lru_cache(maxsize=1)
def _country_features():
    with COUNTRY_BOUNDARIES.open(encoding="utf-8") as stream:
        return json.load(stream)["features"]


def _dash(location: str) -> dict:
    try:
        return dashboard.get_dashboard(location)
    except dashboard.LocationDataUnavailable as e:
        raise HTTPException(404, f"Selected area data not available: {e.args[0]}.")
    except dashboard.LocationNotFound:
        raise HTTPException(404, f"Unknown location '{location}'. See GET /api/locations.")
    except DataError as e:
        raise HTTPException(503, f"Data source error: {e}")


@router.get("/locations")
def locations():
    try:
        locations = dashboard.list_locations()
        if any(item.get('id') == 'country_Australia' for item in locations):
            locations.append({
                'id': 'ndvi_Canberra_Australia', 'name': 'Canberra (MODIS study area)',
                'display_name': 'Canberra, Australia', 'scope': 'area',
                'country': 'Australia', 'country_id': 'country_Australia',
                'lat': -35.3, 'lon': 149.15, 'cells': 0,
                'ndvi_pilot': True, 'available_indicators': ['ndvi'],
            })
        return locations
    except DataError as e:
        raise HTTPException(503, f"Data source error: {e}")


@router.get("/map/areas/{country}")
def map_areas(country: str):
    try:
        features = _admin1_features()
    except (OSError, EOFError, json.JSONDecodeError) as e:
        raise HTTPException(503, "Administrative boundary data is unavailable.") from e

    areas = []
    for feature in features:
        properties = feature.get("properties") or {}
        if properties.get("admin") != country or not feature.get("geometry"):
            continue
        name = properties.get("name_en") or properties.get("name")
        if name:
            areas.append({"type": "Feature", "properties": {"name": name}, "geometry": feature["geometry"]})
    if not areas:
        raise HTTPException(404, f"No administrative boundaries are available for {country}.")
    return {"type": "FeatureCollection", "features": areas}


@router.get("/map/countries")
def map_countries():
    try:
        features = _country_features()
    except (OSError, json.JSONDecodeError) as e:
        raise HTTPException(503, "Country boundary data is unavailable.") from e

    countries = []
    for feature in features:
        properties = feature.get("properties") or {}
        name = properties.get("ADMIN") or properties.get("name")
        if name and feature.get("geometry"):
            countries.append({"type": "Feature", "properties": {"name": name}, "geometry": feature["geometry"]})
    if not countries:
        raise HTTPException(404, "No country boundaries are available.")
    return {"type": "FeatureCollection", "features": countries}


@router.get("/dashboard/{location}")
def get_dashboard(location: str):
    return _dash(location)


def _indicator(key: str):
    def endpoint(location: str):
        d = _dash(location)
        return {**d[key], "location": d["location"], "source_mode": d["source_mode"]}
    return endpoint


for _key, _path in (("temperature", "temperature"), ("vegetation", "vegetation"),
                    ("precipitation", "precipitation"), ("fire", "fire")):
    router.add_api_route(f"/{_path}/{{location}}", _indicator(_key), methods=["GET"], name=f"{_key}_indicator")


@router.get("/cache/{location}")
def cached(location: str):
    row = cache.load(dashboard.slug(location))
    return {"cached": True, **row} if row else {"cached": False, "message": "No cached dashboard yet."}


@router.get("/data-source")
def data_source():
    try:
        d = dashboard.get_dashboard(dashboard.list_locations()[0]["id"])
        sources, mode = d["sources"], d["source_mode"]
    except DataError as e:
        sources, mode = [], f"ERROR: {e}"
    return {"configured": config.DATA_SOURCE, "effective_mode": mode, "sources": sources,
            "firms_key_configured": bool(config.NASA_FIRMS_MAP_KEY)}


@router.post("/data/refresh")
def refresh():
    get_provider().refresh()
    dashboard.reset_memo()
    return {"message": "Data caches cleared; next request re-reads the data source."}
