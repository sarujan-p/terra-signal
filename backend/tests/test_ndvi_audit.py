"""Adversarial software checks, not validation of ecological accuracy."""
import json
import numpy as np
import pytest
from fastapi import HTTPException
from ml.ndvi_candidate import compare
from routers.ndvi import canberra_candidate


@pytest.mark.parametrize('kwargs', [
    {'minimum_years': 3.5}, {'minimum_years': True},
    {'minimum_baseline': float('nan')}, {'minimum_baseline': float('inf')},
    {'minimum_baseline': 1.1}, {'minimum_coverage': float('nan')},
    {'minimum_coverage': -1}, {'minimum_coverage': 101},
])
def test_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        compare(np.array([[0.4]]), [np.array([[0.5]])] * 5, np.ones((1, 1), bool), **kwargs)


@pytest.mark.parametrize('value', [2, -1, float('inf'), -float('inf')])
def test_bad_ndvi(value):
    with pytest.raises(ValueError):
        compare(np.array([[value]]), [np.array([[0.5]])] * 5, np.ones((1, 1), bool))


def test_all_missing_and_exact_coverage_boundary():
    area = np.ones((1, 5), bool)
    history = [np.full((1, 5), 0.5)] * 5
    result, *_ = compare(np.full((1, 5), np.nan), history, area)
    assert result['status'] == 'NO_VALID_DATA'
    assert result['current'] is None
    result, *_ = compare(np.array([[0.4, 0.4, 0.4, 0.4, np.nan]]), history, area)
    assert result['reportable'] is True
    assert result['matched_coverage_percent'] == 80
    assert result['change_percent'] == pytest.approx(-20)


@pytest.mark.parametrize('changes', [
    {'current': float('nan')}, {'current': True}, {'current': 1.2},
    {'reportable': 'false'}, {'matched_coverage_percent': 101},
    {'status': 'HEALTHY'}, {'status': 'ABOVE_BASELINE'},
    {'change_percent': -90}, {'absolute_difference': 0.2}, {'date': 'bad'},
])
def test_api_rejects_corrupt_summary(tmp_path, monkeypatch, changes):
    payload = dict(deployment_allowed=False, date='2025-12-19', reportable=True,
                   status='BELOW_BASELINE', matched_coverage_percent=95,
                   current=0.4, baseline=0.5, absolute_difference=-0.1, change_percent=-20)
    payload.update(changes)
    (tmp_path / 'candidate_latest.json').write_text(json.dumps(payload))
    monkeypatch.setenv('SATSCOPE_NDVI_REVIEW_DIR', str(tmp_path))
    with pytest.raises(HTTPException) as error:
        canberra_candidate()
    assert error.value.status_code == 503


def test_api_valid_summary(tmp_path, monkeypatch):
    payload = dict(deployment_allowed=False, date='2025-12-19', reportable=True,
                   status='BELOW_BASELINE', matched_coverage_percent=95,
                   current=0.4, baseline=0.5, absolute_difference=-0.1, change_percent=-20)
    (tmp_path / 'candidate_latest.json').write_text(json.dumps(payload))
    monkeypatch.setenv('SATSCOPE_NDVI_REVIEW_DIR', str(tmp_path))
    with pytest.raises(HTTPException) as error:
        canberra_candidate()
    assert error.value.status_code == 503  # Complete package now required.
