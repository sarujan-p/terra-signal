"""SAT-SCOPE API entry point.  Run:  uvicorn main:app --reload --port 8000  (from backend/)"""
import os
import sys
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
from routers import auth, data, ndvi
from services import security


@asynccontextmanager
async def lifespan(_: FastAPI):
    security.init_db()
    yield


app = FastAPI(
    title="SAT-SCOPE Earth Intelligence API",
    description="Cross-variable Earth system trend detection. "
                "Data comes from backend/data_provider.py (bundled NASA archive, mock JSON, or live NASA).",
    version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(data.router)
app.include_router(ndvi.router)


@app.get("/")
def root():
    return {"name": "SAT-SCOPE API", "status": "online", "docs": "/docs", "data_source": config.DATA_SOURCE}


@app.get("/api/health")
def health():
    return {"status": "healthy", "data_source": config.DATA_SOURCE, "version": app.version}
