# SAT-SCOPE — Earth System Trend Detective

**Vegetation contribution:** select Australia, then Canberra (MODIS study area)
in the existing location controls. This study area uses MOD13Q1 NDVI, a 2020-2024
seasonal baseline and 2025 observations. Other locations retain the original
archive; soil wetness is not NDVI. The original global archive remains the default.
Canberra has no aligned temperature/rain/fire data and is excluded from compound
analysis. The processed v2 review package is included at `data/ndvi/canberra_candidate_v2.zip`.
Enable it with the commands below.
No package means unavailable data, never fabricated observations.

The NDVI candidate is an offline review feature, not a completed production
integration. Scientific limitations are listed below.

### Check a local NDVI export

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe backend/scripts/verify_ndvi_export.py data/ndvi/canberra_candidate_v2.zip
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm --prefix frontend run build
```

The API and command-line checker use the same complete-package validator.
The Colab workflow is `notebooks/SAT_SCOPE_NDVI_Candidate_Validation.ipynb`;
it uses the shared modules in `backend/ml`. Keep downloaded raster data and
experimental candidate exports outside version control. The bundled v2 ZIP is
the reviewed handoff snapshot, not raw imagery.

### Run the bundled Canberra review

Clone the contribution branch and open its folder:

```powershell
git clone --branch feature/ndvi-hackathon-pilot https://github.com/Dinyyyd/terra-signal.git
cd terra-signal
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:SATSCOPE_NDVI_REVIEW_PACKAGE = (Resolve-Path data/ndvi/canberra_candidate_v2.zip).Path
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir backend --host 127.0.0.1 --port 8000
```

In a second terminal at the project root:

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

Open the frontend URL, sign in, and select Australia then Canberra (MODIS study
area). Set the environment variable in each new backend terminal. Raw rasters
are only needed to rerun the Colab processing, not to display this saved review.

### NDVI interpretation

The Canberra pilot compares 2025 MOD13Q1 observations with matching seasonal
periods in 2020-2024. It uses matched pixels with at least four historical
observations. Coverage of 80% and baseline NDVI of 0.1 are provisional reporting
limits, not calibrated accuracy thresholds. Lower NDVI does not establish
vegetation damage or its cause.

Composite labels are not exact acquisition dates; year-end pixels can come from
the following year. QA-accepted pixels include different land-cover types, and
regional medians can hide local changes. HLS comparisons assess agreement over
subsets, not ecological accuracy. Package validation checks internal consistency
and source hashes; it does not recheck the original rasters in Drive. Canberra
remains excluded from compound analysis until geography and observation periods
align with the other indicators.

NASA Space Apps Challenge · *Be An Earth System Trend Detective!*
© TerraSignal

React + Leaflet + Plotly dashboard, FastAPI backend, scikit-learn analytics (temperature Z-scores, vegetation deltas, precipitation quantiles, fire-detection DBSCAN, Isolation Forest) and SQLite. No Docker.

## Login
| Username | Password (default) |
|---|---|
| `sarujan` | `password` |

Change it in the app: **Settings → Change password** (min. 8 characters; other sessions are signed out). A banner reminds you while the default is still active. Users and password hashes (PBKDF2-SHA256) live in `data/sat_scope.sqlite`. To reset a forgotten password, delete that file and restart the API.

## Run
```bash
# terminal 1 – API
cd backend
python3 -m venv .venv && source .venv/bin/activate      # Windows: py -m venv .venv ; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000                    # docs: http://127.0.0.1:8000/docs

# terminal 2 – UI
cd frontend && npm install && npm run dev                # http://localhost:5173
```
Tests: `cd backend && pytest -q`

## Global NASA historical data
The default provider reads `data/history/nasa_power_global_monthly_2011_2025.json`, a bundled archive of monthly NASA POWER values sampled at global 5-degree cell centers. It contains complete 2011–2025 records for 2 m air temperature (`T2M`), corrected precipitation rate (`PRECTOTCORR`) and root-zone soil wetness (`GWETROOT`), when all three variables are available for a cell. Natural Earth boundaries attach country and local administrative-area names. The first selector switches between Global and every country; the dependent area selector lists that country's districts, states, provinces or other available local areas. Areas with no NASA grid sample remain selectable and are shown as unavailable. Charts use a same-calendar-month 2011–2020 baseline.

The archive is downloaded with:
```bash
cd backend
python scripts/download_nasa_power_history.py
```
The downloader is resumable and stores a temporary checkpoint under `data/history/` until it completes. It does not need NASA credentials. NASA POWER reports these meteorological variables as MERRA-2 reanalysis, **not direct satellite observations**. The grid consists of point samples at 5-degree spacing, not area-averages; Natural Earth land, country and 1:10m administrative boundaries select land cells and provide area names. The coarse grid will not cover every district or city. Historical fire detections are not included and are shown as unavailable rather than zero.
Root-zone wetness status thresholds are simple dashboard heuristics against the same-month baseline, not NASA-issued drought classifications.

## Data providers
Everything reads data through **`backend/data_provider.py`**.

| Option | How |
|---|---|
| Global historical archive (default) | `DATA_SOURCE=archive uvicorn main:app` |
| Replace the 4 demo JSON files | Overwrite `data/mock/*.json` using the schema documented at the top of `data_provider.py`, then set `DATA_SOURCE=mock`. |
| Use the built-in live adapters | `DATA_SOURCE=live NASA_FIRMS_MAP_KEY=<key> uvicorn main:app` |
| Your own pipeline | Subclass `DataProvider`, return the 4 datasets, register it in `PROVIDERS`. |

The optional live adapters use **FIRMS** VIIRS fires (key needed) and **NASA POWER** daily temperature and precipitation; MODIS NDVI remains a plug-in hook. In live mode, an indicator that fails falls back to the Sri Lanka mock file and is labelled *MOCK (fallback)* in Settings → Data source. Data is validated, so malformed files produce a clear error. If a source fails entirely, the last good result is served from the SQLite cache.

> POWER `TS` in live mode is reanalysis skin temperature, not MODIS LST. The bundled monthly archive instead uses `T2M` (2 m air temperature).

## What the app does
- Login, session tokens, password change, lockout after 5 failed attempts
- Country filter with Global and all countries, plus a dependent searchable local-area selector; areas without sampled data are explicitly marked unavailable
- Leaflet map: click a grid cell to load its local area; temperature, root-zone soil wetness, precipitation, and Isolation Forest outliers are shown for the archive
- Monthly historical charts (2011–2025) with 7-day, 1-month, 1-year, 5-year and 10-year windows, year/month selection, date filters, and interactive zoom
- Same-month baseline comparisons and an Isolation Forest using the indicators available in the selected source
- Regional hotspot ranking, plain-language explanation, auto-refresh every 5 minutes

## API (all but `/api/health` need `Authorization: Bearer <token>`)
`POST /api/auth/login` · `GET /api/auth/me` · `POST /api/auth/change-password` · `GET /api/locations` · `GET /api/dashboard/{location}` · `GET /api/{temperature|vegetation|precipitation|fire}/{location}` · `GET /api/cache/{location}` · `GET /api/data-source` · `POST /api/data/refresh`

## Notes
- The default archive covers land grid centers with complete values for all three NASA POWER variables; grid points are 5-degree samples, not area averages.
- NASA POWER's bundled meteorological variables are MERRA-2 reanalysis, not direct satellite observations. Root-zone soil wetness is not NDVI, and historical fire detections are unavailable in this archive.
- Trend windows only display records supplied by the active source. The optional Sri Lanka mock/live sources have shorter histories than the global archive.
- Isolation Forest flags the top 8% most isolated cells by design; a *compound anomaly* additionally needs ≥ 2 indicator flags.
- The token-signing secret is generated per database; set `CORS_ORIGINS` if you host the UI elsewhere.
