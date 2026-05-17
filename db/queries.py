"""Read-side queries used by both the API and the bot's direct-DB path.

Only active listings (is_active=1) are returned by default.
"""
from __future__ import annotations

from typing import Any

from db.db import cur, _row_to_car, _row_to_apt, init_db


# ─── helpers ───────────────────────────────────────────────────────────────────
def _and(parts: list[str]) -> str:
    return " AND ".join(parts) if parts else "1=1"


# ─── cars ─────────────────────────────────────────────────────────────────────
def query_cars(
    *,
    has_sunroof: bool | None = None,
    max_price: int | None = None,
    min_price: int | None = None,
    max_km: int | None = None,
    min_year: int | None = None,
    brand: str | None = None,
    source: str | None = None,
    location: str | None = None,
    include_inactive: bool = False,
    sort: str = "sunroof_then_price",
    limit: int = 50,
) -> list[dict]:
    init_db()
    parts: list[str] = []
    params: list[Any] = []
    if not include_inactive: parts.append("is_active=1")
    if has_sunroof is not None: parts.append("has_sunroof=?"); params.append(1 if has_sunroof else 0)
    if max_price is not None: parts.append("price_aed<=?"); params.append(int(max_price))
    if min_price is not None: parts.append("price_aed>=?"); params.append(int(min_price))
    if max_km is not None:    parts.append("(km IS NULL OR km<=?)"); params.append(int(max_km))
    if min_year is not None:  parts.append("(year>=?)"); params.append(int(min_year))
    if brand:    parts.append("LOWER(brand) LIKE LOWER(?)"); params.append(f"%{brand}%")
    if source:   parts.append("source=?"); params.append(source)
    if location: parts.append("LOWER(location) LIKE LOWER(?)"); params.append(f"%{location}%")

    sort_clause = {
        "sunroof_then_price": "has_sunroof DESC, price_aed ASC",
        "sunroof_then_score": "has_sunroof DESC, year DESC, km ASC",
        "price_asc":  "price_aed ASC",
        "price_desc": "price_aed DESC",
        "year_desc":  "year DESC",
        "km_asc":     "km ASC",
        "newest":     "first_seen_at DESC",
    }.get(sort, "has_sunroof DESC, price_aed ASC")

    sql = f"SELECT * FROM cars WHERE {_and(parts)} ORDER BY {sort_clause} LIMIT {int(limit)}"
    with cur() as c:
        c.execute(sql, params)
        return [_row_to_car(r) for r in c.fetchall()]


def get_car(ad_id: str) -> dict | None:
    init_db()
    with cur() as c:
        c.execute("SELECT * FROM cars WHERE ad_id=?", (ad_id,))
        r = c.fetchone()
        return _row_to_car(r) if r else None


# ─── apartments ───────────────────────────────────────────────────────────────
def query_apartments(
    *,
    max_monthly: int | None = None,
    max_yearly: int | None = None,
    max_tier: int | None = None,
    area: str | None = None,
    amenity: str | None = None,
    min_size_sqft: int | None = None,
    include_inactive: bool = False,
    sort: str = "tier_then_price",
    limit: int = 50,
) -> list[dict]:
    init_db()
    parts: list[str] = []
    params: list[Any] = []
    if not include_inactive: parts.append("is_active=1")
    if max_monthly is not None: parts.append("monthly_aed<=?"); params.append(int(max_monthly))
    if max_yearly  is not None: parts.append("price_aed<=?");   params.append(int(max_yearly))
    if max_tier    is not None: parts.append("commute_tier<=?"); params.append(int(max_tier))
    if area:    parts.append("(LOWER(area) LIKE LOWER(?) OR LOWER(full_location) LIKE LOWER(?))"); params.extend([f"%{area}%", f"%{area}%"])
    if amenity: parts.append("LOWER(amenities) LIKE LOWER(?)"); params.append(f"%{amenity}%")
    if min_size_sqft is not None: parts.append("(size_sqft>=?)"); params.append(int(min_size_sqft))

    sort_clause = {
        "tier_then_price": "commute_tier ASC, price_aed ASC",
        "price_asc":  "price_aed ASC",
        "price_desc": "price_aed DESC",
        "size_desc":  "size_sqft DESC",
        "newest":     "first_seen_at DESC",
    }.get(sort, "commute_tier ASC, price_aed ASC")

    sql = f"SELECT * FROM apartments WHERE {_and(parts)} ORDER BY {sort_clause} LIMIT {int(limit)}"
    with cur() as c:
        c.execute(sql, params)
        return [_row_to_apt(r) for r in c.fetchall()]


def get_apartment(ad_id: str) -> dict | None:
    init_db()
    with cur() as c:
        c.execute("SELECT * FROM apartments WHERE ad_id=?", (ad_id,))
        r = c.fetchone()
        return _row_to_apt(r) if r else None


# ─── stats ────────────────────────────────────────────────────────────────────
def get_stats() -> dict:
    init_db()
    with cur() as c:
        c.execute("SELECT COUNT(*) FROM cars WHERE is_active=1")
        cars_total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM cars WHERE is_active=1 AND has_sunroof=1")
        cars_sun = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM cars WHERE is_active=1 AND price_aed BETWEEN 1 AND 20000")
        cars_under_20k = c.fetchone()[0]
        c.execute("SELECT brand, COUNT(*) FROM cars WHERE is_active=1 GROUP BY brand ORDER BY 2 DESC")
        cars_by_brand = {r[0]: r[1] for r in c.fetchall()}

        c.execute("SELECT COUNT(*) FROM apartments WHERE is_active=1")
        apt_total = c.fetchone()[0]
        c.execute("SELECT MIN(monthly_aed) FROM apartments WHERE is_active=1")
        apt_cheap = c.fetchone()[0]
        c.execute("SELECT commute_tier, COUNT(*) FROM apartments WHERE is_active=1 GROUP BY commute_tier")
        apt_by_tier = {f"tier_{r[0]}": r[1] for r in c.fetchall()}
        c.execute("SELECT area, COUNT(*) FROM apartments WHERE is_active=1 GROUP BY area ORDER BY 2 DESC")
        apt_by_area = {r[0]: r[1] for r in c.fetchall()}

        c.execute("SELECT MAX(scraped_at) FROM cars WHERE is_active=1")
        cars_last = c.fetchone()[0]
        c.execute("SELECT MAX(scraped_at) FROM apartments WHERE is_active=1")
        apts_last = c.fetchone()[0]

    return {
        "cars": {
            "total":      cars_total,
            "sunroof":    cars_sun,
            "under_20k":  cars_under_20k,
            "by_brand":   cars_by_brand,
            "last_seen":  cars_last,
        },
        "apartments": {
            "total":             apt_total,
            "cheapest_monthly":  apt_cheap,
            "by_tier":           apt_by_tier,
            "by_area":           apt_by_area,
            "last_seen":         apts_last,
        },
    }
