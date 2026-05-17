"""Dubai Hunt — REST API over the SQLite store.

Run:
    python -m uvicorn api.main:app --host 127.0.0.1 --port 8090

Endpoints:
    GET  /              healthcheck + version
    GET  /stats         headline counts (cars + apartments)
    GET  /cars          list cars (filters as query params)
    GET  /cars/{ad_id}  single car
    GET  /apartments    list apartments
    GET  /apartments/{ad_id}  single apartment
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow `from db.queries import ...` even when uvicorn launches us elsewhere
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query  # type: ignore
from fastapi.middleware.cors import CORSMiddleware  # type: ignore
from fastapi.responses import FileResponse  # type: ignore
from fastapi.staticfiles import StaticFiles  # type: ignore

from db.queries import (
    query_cars,
    query_apartments,
    get_car,
    get_apartment,
    get_stats,
)
from db.admin_queries import (
    cars_health,
    apartments_health,
    scrape_runs,
    derived_pipeline_health,
)

app = FastAPI(
    title="Dubai Hunt API",
    version="0.1.0",
    description="SQLite-backed REST API over scraped Dubai cars + apartments.",
)

# CORS: restrict to explicit origins (env-driven). Same-origin calls from the
# bundled dashboards don't need CORS at all; this matters only for file:// or
# tunnel access. Override via CORS_ORIGINS=https://a.example,https://b.example
_default_origins = "http://127.0.0.1:8090,http://localhost:8090,http://31.97.71.84"
_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", _default_origins).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ─── basic ────────────────────────────────────────────────────────────────────
# Note: GET / serves the landing page from disk (via StaticFiles mount at the bottom).
# Use /api/health for a programmatic liveness probe.

@app.get("/api/health")
def api_health():
    return {"ok": True, "service": "dubai-hunt-api", "version": "0.2.0"}


@app.get("/stats")
def stats():
    return get_stats()


# ─── cars ─────────────────────────────────────────────────────────────────────
@app.get("/cars")
def list_cars(
    has_sunroof: bool | None = None,
    max_price:   int  | None = None,
    min_price:   int  | None = None,
    max_km:      int  | None = None,
    min_year:    int  | None = None,
    brand:       str  | None = None,
    source:      str  | None = None,
    location:    str  | None = None,
    sort:        str  = Query("sunroof_then_price"),
    limit:       int  = Query(50, ge=1, le=500),
    include_inactive: bool = False,
):
    rows = query_cars(
        has_sunroof=has_sunroof,
        max_price=max_price, min_price=min_price,
        max_km=max_km, min_year=min_year,
        brand=brand, source=source, location=location,
        sort=sort, limit=limit, include_inactive=include_inactive,
    )
    return {"count": len(rows), "results": rows}


@app.get("/cars/{ad_id}")
def one_car(ad_id: str):
    r = get_car(ad_id)
    if not r:
        raise HTTPException(404, f"car {ad_id} not found")
    return r


# ─── apartments ───────────────────────────────────────────────────────────────
@app.get("/apartments")
def list_apartments(
    max_monthly:   int | None = None,
    max_yearly:    int | None = None,
    max_tier:      int | None = None,
    area:          str | None = None,
    amenity:       str | None = None,
    min_size_sqft: int | None = None,
    sort:          str = Query("tier_then_price"),
    limit:         int = Query(50, ge=1, le=500),
    include_inactive: bool = False,
):
    rows = query_apartments(
        max_monthly=max_monthly, max_yearly=max_yearly,
        max_tier=max_tier, area=area, amenity=amenity,
        min_size_sqft=min_size_sqft,
        sort=sort, limit=limit, include_inactive=include_inactive,
    )
    return {"count": len(rows), "results": rows}


@app.get("/apartments/{ad_id}")
def one_apt(ad_id: str):
    r = get_apartment(ad_id)
    if not r:
        raise HTTPException(404, f"apartment {ad_id} not found")
    return r


# ─── admin / ops dashboard endpoints ──────────────────────────────────────────
@app.get("/admin/health")
def admin_health():
    """One-stop bundle for the ops dashboard. Cars + apartments + pipeline."""
    return {
        "cars":       cars_health(),
        "apartments": apartments_health(),
        "pipeline":   derived_pipeline_health(),
    }


@app.get("/admin/cars")
def admin_cars():
    return cars_health()


@app.get("/admin/apartments")
def admin_apartments():
    return apartments_health()


@app.get("/admin/scrape_runs")
def admin_scrape_runs(limit: int = Query(50, ge=1, le=500)):
    return {"runs": scrape_runs(limit=limit)}


# ─── static files (dashboards + landing) ─────────────────────────────────────
# Mounted AFTER the API routes so explicit routes take priority. This lets one
# port serve both the API and the frontend dashboards. On the VM, port 80 then
# serves http://<ip>/ (landing) + http://<ip>/cars (API) + http://<ip>/Car%20Deals%20Frontend/ (cars dashboard).
app.mount("/", StaticFiles(directory=str(ROOT), html=True), name="root")


if __name__ == "__main__":
    import uvicorn  # type: ignore
    # Default to 8090 for local dev. The VM systemd unit overrides to 80.
    port = int(os.environ.get("PORT", "8090"))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port, reload=False)
