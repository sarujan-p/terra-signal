"""Opt-in local candidate review; separate from compound dashboard analytics."""
import os
from fastapi import APIRouter, Depends, HTTPException
from routers.auth import current_user
from services.ndvi_package import validate_package

router = APIRouter(prefix="/api/ndvi", tags=["NDVI candidate"], dependencies=[Depends(current_user)])


def review_package():
    path = os.getenv('SATSCOPE_NDVI_REVIEW_PACKAGE') or os.getenv('SATSCOPE_NDVI_REVIEW_DIR')
    if not path:
        raise HTTPException(503, 'NDVI candidate review is disabled; no observed dataset configured.')
    try:
        return validate_package(path)
    except ValueError as exc:
        raise HTTPException(503, 'NDVI candidate unavailable or invalid') from exc


@router.get('/canberra/review')
def complete_review():
    # One validated snapshot prevents mixing files from separate refreshes.
    return dict(review_package(), study_area='Canberra pilot', source='MOD13Q1.061',
                compound_eligible=False, mode='OFFLINE_CANDIDATE_REVIEW')


@router.get('/canberra/timeseries')
def review_timeseries():
    return {'study_area': 'Canberra pilot', 'rows': review_package()['timeseries']}


@router.get('/canberra/geojson')
def review_geojson():
    return review_package()['geojson']


@router.get("/canberra")
def canberra_candidate():
    """Return the latest summary from the same validated package as the map."""
    return {
        "study_area": "Canberra pilot",
        "country": "Australia",
        "indicator": "NDVI",
        "source": "MOD13Q1.061",
        "mode": "OFFLINE_CANDIDATE_REVIEW",
        "compound_eligible": False,
        "temporal_note": (
            "Composite start label; pixels may include early next-year acquisitions."
        ),
        "result": review_package()["result"],
    }
