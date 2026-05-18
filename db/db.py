"""SQLite helpers for Dubai Hunt. Single-file canonical store at db/dubai_hunt.db.

Usage:
    from db.db import upsert_car, upsert_apartment, get_cars, get_apartments, get_stats
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterable

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "dubai_hunt.db")
SCHEMA_PATH = os.path.join(DB_DIR, "schema.sql")


# ─── connection ────────────────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    """Idempotent. Creates schema if it doesn't exist + self-heals new columns."""
    con = _connect()
    try:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            con.executescript(f.read())
        # Self-healing migrations for columns added after the initial deploy.
        # sqlite has no IF NOT EXISTS on ADD COLUMN, so check first.
        existing = {r[1] for r in con.execute("PRAGMA table_info(cars)").fetchall()}
        if "listed_at" not in existing:
            con.execute("ALTER TABLE cars ADD COLUMN listed_at TEXT")
            con.execute("CREATE INDEX IF NOT EXISTS ix_cars_listed ON cars(listed_at)")
        con.commit()
    finally:
        con.close()


@contextmanager
def cur():
    con = _connect()
    try:
        yield con.cursor()
    finally:
        con.close()


# ─── helpers ───────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _pipe(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return " | ".join(str(x) for x in v)
    return str(v)


def _unpipe(s: str) -> list[str]:
    if not s:
        return []
    return [p.strip() for p in s.split("|") if p.strip()]


def _row_to_car(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["has_sunroof"] = bool(d.get("has_sunroof"))
    d["is_active"]   = bool(d.get("is_active"))
    d["features"]    = _unpipe(d.get("features") or "")
    return d


def _row_to_apt(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["furnished"] = bool(d.get("furnished"))
    d["is_active"] = bool(d.get("is_active"))
    d["amenities"] = _unpipe(d.get("amenities") or "")
    return d


# ─── upserts ───────────────────────────────────────────────────────────────────
CAR_COLS = (
    "ad_id source title brand year km price_aed transmission trim color body_type "
    "fuel seller_type location has_sunroof features description image url scraped_at "
    "listed_at"
).split()

def upsert_car(rec: dict) -> str:
    """Insert or update one car. Returns 'inserted' or 'updated'.

    `rec` is the dict shape produced by the scraper (matches Listing dataclass).
    """
    init_db()
    now = _now()
    payload = {
        "ad_id":         rec.get("ad_id") or "",
        "source":        rec.get("source") or "",
        "title":         rec.get("title") or "",
        "brand":         rec.get("brand") or "",
        "year":          rec.get("year"),
        "km":            rec.get("km"),
        "price_aed":     rec.get("price_aed") or 0,
        "transmission":  rec.get("transmission") or "",
        "trim":          rec.get("trim") or "",
        "color":         rec.get("color") or "",
        "body_type":     rec.get("body_type") or "",
        "fuel":          rec.get("fuel") or "",
        "seller_type":   rec.get("seller_type") or "",
        "location":      rec.get("location") or "",
        "has_sunroof":   1 if rec.get("has_sunroof") else 0,
        "features":      _pipe(rec.get("features")),
        "description":   rec.get("description") or "",
        "image":         rec.get("image") or "",
        "url":           rec.get("url") or "",
        "scraped_at":    rec.get("scraped_at") or now,
        "listed_at":     rec.get("listed_at") or None,   # ISO date when seller posted (Dubizzle only for now)
    }
    if not payload["ad_id"]:
        return "skipped"

    with cur() as c:
        c.execute("SELECT 1 FROM cars WHERE ad_id=?", (payload["ad_id"],))
        exists = c.fetchone() is not None
        if exists:
            sets = ", ".join(f"{k}=:{k}" for k in CAR_COLS if k != "ad_id")
            c.execute(f"UPDATE cars SET {sets}, is_active=1 WHERE ad_id=:ad_id", payload)
            return "updated"
        else:
            payload["first_seen_at"] = now
            cols = ", ".join(list(payload.keys()) + ["first_seen_at"])
            placeholders = ", ".join(f":{k}" for k in payload.keys())
            # build dynamic insert with first_seen_at
            c.execute(
                f"INSERT INTO cars ({', '.join(payload.keys())}, is_active) "
                f"VALUES ({', '.join(f':{k}' for k in payload.keys())}, 1)",
                payload,
            )
            return "inserted"


APT_COLS = (
    "ad_id source title price_aed monthly_aed bedrooms bathrooms size_sqft area "
    "commute_tier full_location furnished amenities image url broker agent_name "
    "agent_phone lat lon description scraped_at"
).split()

def upsert_apartment(rec: dict) -> str:
    init_db()
    now = _now()
    yearly  = int(rec.get("price_aed") or 0)
    monthly = int(rec.get("monthly_aed") or (yearly // 12 if yearly else 0))
    payload = {
        "ad_id":         rec.get("ad_id") or "",
        "source":        rec.get("source") or "",
        "title":         rec.get("title") or "",
        "price_aed":     yearly,
        "monthly_aed":   monthly,
        "bedrooms":      rec.get("bedrooms"),
        "bathrooms":     rec.get("bathrooms"),
        "size_sqft":     rec.get("size_sqft"),
        "area":          rec.get("area") or "",
        "commute_tier":  rec.get("commute_tier"),
        "full_location": rec.get("full_location") or "",
        "furnished":     1 if rec.get("furnished", True) else 0,
        "amenities":     _pipe(rec.get("amenities")),
        "image":         rec.get("image") or "",
        "url":           rec.get("url") or "",
        "broker":        rec.get("broker") or "",
        "agent_name":    rec.get("agent_name") or "",
        "agent_phone":   rec.get("agent_phone") or "",
        "lat":           rec.get("lat"),
        "lon":           rec.get("lon"),
        "description":   rec.get("description") or "",
        "scraped_at":    rec.get("scraped_at") or now,
    }
    if not payload["ad_id"]:
        return "skipped"

    with cur() as c:
        c.execute("SELECT 1 FROM apartments WHERE ad_id=?", (payload["ad_id"],))
        exists = c.fetchone() is not None
        if exists:
            sets = ", ".join(f"{k}=:{k}" for k in APT_COLS if k != "ad_id")
            c.execute(f"UPDATE apartments SET {sets}, is_active=1 WHERE ad_id=:ad_id", payload)
            return "updated"
        else:
            c.execute(
                f"INSERT INTO apartments ({', '.join(payload.keys())}, first_seen_at, is_active) "
                f"VALUES ({', '.join(f':{k}' for k in payload.keys())}, '{now}', 1)",
                payload,
            )
            return "inserted"


# ─── soft-deactivate (mark listings not seen in latest run) ────────────────────
def mark_inactive_cars(seen_ad_ids: Iterable[str]) -> int:
    """Mark cars NOT in `seen_ad_ids` as is_active=0. Doesn't delete them."""
    ids = list(set(seen_ad_ids))
    if not ids:
        return 0
    init_db()
    with cur() as c:
        # Build IN clause safely with parameterized placeholders
        placeholders = ",".join("?" * len(ids))
        c.execute(
            f"UPDATE cars SET is_active=0 WHERE ad_id NOT IN ({placeholders}) AND is_active=1",
            ids,
        )
        return c.rowcount or 0


def mark_inactive_apartments(seen_ad_ids: Iterable[str]) -> int:
    ids = list(set(seen_ad_ids))
    if not ids:
        return 0
    init_db()
    with cur() as c:
        placeholders = ",".join("?" * len(ids))
        c.execute(
            f"UPDATE apartments SET is_active=0 WHERE ad_id NOT IN ({placeholders}) AND is_active=1",
            ids,
        )
        return c.rowcount or 0


# ─── scrape_runs (audit trail) ────────────────────────────────────────────────
def start_scrape_run(kind: str, notes: str | None = None) -> int:
    """Insert a new in-progress run row. Returns the run id."""
    init_db()
    with cur() as c:
        c.execute(
            "INSERT INTO scrape_runs (kind, started_at, notes) VALUES (?, ?, ?)",
            (kind, _now(), notes or ""),
        )
        return c.lastrowid or 0


def finish_scrape_run(
    run_id: int,
    *,
    rows_seen: int = 0,
    rows_new: int = 0,
    rows_updated: int = 0,
    notes: str | None = None,
) -> None:
    if not run_id:
        return
    init_db()
    with cur() as c:
        # Preserve any existing notes, append if new ones provided.
        if notes:
            c.execute("SELECT notes FROM scrape_runs WHERE id=?", (run_id,))
            row = c.fetchone()
            existing = (row["notes"] or "") if row else ""
            merged = (existing + (" · " if existing else "") + notes)[:400]
        else:
            merged = None
        c.execute(
            """UPDATE scrape_runs
                  SET finished_at=:fin, rows_seen=:seen, rows_new=:new,
                      rows_updated=:upd, notes=COALESCE(:notes, notes)
                WHERE id=:id""",
            {
                "fin": _now(), "seen": int(rows_seen or 0),
                "new": int(rows_new or 0), "upd": int(rows_updated or 0),
                "notes": merged, "id": run_id,
            },
        )
