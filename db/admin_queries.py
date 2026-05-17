"""Ops-dashboard queries: breakdowns, histograms, freshness, scrape-run history."""
from __future__ import annotations

from datetime import datetime, timedelta
from db.db import cur, init_db


# ─── helpers ───────────────────────────────────────────────────────────────────
def _bucket_count(rows: list[tuple], buckets: list[tuple[int | None, int | None, str]]) -> list[dict]:
    """Map a [(value, count)] result into named buckets."""
    out = [{"bucket": label, "count": 0, "lo": lo, "hi": hi} for lo, hi, label in buckets]
    for value, count in rows:
        if value is None:
            continue
        for b in out:
            lo, hi = b["lo"], b["hi"]
            ok = True
            if lo is not None and value < lo: ok = False
            if hi is not None and value > hi: ok = False
            if ok:
                b["count"] += int(count or 0)
                break
    return [{"bucket": b["bucket"], "count": b["count"]} for b in out]


# ─── cars ─────────────────────────────────────────────────────────────────────
def cars_health() -> dict:
    init_db()
    with cur() as c:
        c.execute("SELECT COUNT(*) FROM cars")
        total_all = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM cars WHERE is_active=1")
        active = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM cars WHERE is_active=0")
        inactive = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM cars WHERE is_active=1 AND has_sunroof=1")
        sunroof = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM cars WHERE is_active=1 AND price_aed BETWEEN 1 AND 20000")
        under_20k = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM cars WHERE is_active=1 AND price_aed BETWEEN 1 AND 15000")
        under_15k = c.fetchone()[0]
        c.execute("SELECT MIN(price_aed) FROM cars WHERE is_active=1 AND price_aed>0")
        cheapest = c.fetchone()[0]
        c.execute("SELECT MAX(price_aed) FROM cars WHERE is_active=1 AND price_aed<=20000")
        max_in_budget = c.fetchone()[0]
        c.execute("SELECT MAX(scraped_at) FROM cars WHERE is_active=1")
        last_seen = c.fetchone()[0]

        # by brand (top 15 + Other rollup)
        c.execute("""SELECT brand, COUNT(*) FROM cars WHERE is_active=1
                     GROUP BY brand ORDER BY 2 DESC LIMIT 100""")
        brand_rows = [(r[0], r[1]) for r in c.fetchall()]
        top15 = brand_rows[:15]
        other = sum(n for _, n in brand_rows[15:])
        by_brand = [{"brand": b, "count": n} for b, n in top15]
        if other > 0:
            by_brand.append({"brand": "Other", "count": other})

        # by source
        c.execute("SELECT source, COUNT(*) FROM cars WHERE is_active=1 GROUP BY source ORDER BY 2 DESC")
        by_source = [{"source": r[0], "count": r[1]} for r in c.fetchall()]

        # sunroof split
        c.execute("SELECT has_sunroof, COUNT(*) FROM cars WHERE is_active=1 GROUP BY has_sunroof")
        sun_split = {int(r[0]): r[1] for r in c.fetchall()}
        sunroof_split = [
            {"label": "Sunroof",    "count": sun_split.get(1, 0)},
            {"label": "No sunroof", "count": sun_split.get(0, 0)},
        ]

        # price histogram (cars: AED)
        c.execute("SELECT price_aed, 1 FROM cars WHERE is_active=1 AND price_aed>0")
        price_rows = c.fetchall()
        price_buckets = [
            (1,      5000,  "< 5K"),
            (5001,   10000, "5–10K"),
            (10001,  12500, "10–12.5K"),
            (12501,  15000, "12.5–15K"),
            (15001,  17500, "15–17.5K"),
            (17501,  20000, "17.5–20K"),
            (20001,  None,  "> 20K"),
        ]
        price_hist = _bucket_count(price_rows, price_buckets)

        # year distribution (post-2000)
        c.execute("SELECT year, COUNT(*) FROM cars WHERE is_active=1 AND year>=2000 GROUP BY year ORDER BY year")
        year_dist = [{"year": int(r[0]), "count": int(r[1])} for r in c.fetchall()]

        # km histogram
        c.execute("SELECT km, 1 FROM cars WHERE is_active=1 AND km IS NOT NULL")
        km_rows = c.fetchall()
        km_buckets = [
            (0,        50000,  "< 50k"),
            (50001,    100000, "50–100k"),
            (100001,   150000, "100–150k"),
            (150001,   200000, "150–200k"),
            (200001,   300000, "200–300k"),
            (300001,   None,   "> 300k"),
        ]
        km_hist = _bucket_count(km_rows, km_buckets)

        # freshness (scraped within X)
        now = datetime.now()
        c.execute("SELECT scraped_at FROM cars WHERE is_active=1")
        fresh_rows = c.fetchall()
        buckets = {"< 1h": 0, "1–6h": 0, "6–24h": 0, "1–3d": 0, "> 3d": 0}
        for (s,) in fresh_rows:
            if not s: continue
            try:
                dt = datetime.fromisoformat(s)
            except Exception:
                continue
            age = now - dt
            if age < timedelta(hours=1):     buckets["< 1h"] += 1
            elif age < timedelta(hours=6):   buckets["1–6h"] += 1
            elif age < timedelta(hours=24):  buckets["6–24h"] += 1
            elif age < timedelta(days=3):    buckets["1–3d"] += 1
            else:                            buckets["> 3d"] += 1
        freshness = [{"bucket": k, "count": v} for k, v in buckets.items()]

    return {
        "summary": {
            "total":          total_all,
            "active":         active,
            "inactive":       inactive,
            "sunroof":        sunroof,
            "under_15k":      under_15k,
            "under_20k":      under_20k,
            "cheapest":       cheapest,
            "max_in_budget":  max_in_budget,
            "last_seen":      last_seen,
        },
        "by_brand":      by_brand,
        "by_source":     by_source,
        "sunroof_split": sunroof_split,
        "price_hist":    price_hist,
        "year_dist":     year_dist,
        "km_hist":       km_hist,
        "freshness":     freshness,
    }


# ─── apartments ───────────────────────────────────────────────────────────────
def apartments_health() -> dict:
    init_db()
    with cur() as c:
        c.execute("SELECT COUNT(*) FROM apartments")
        total_all = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM apartments WHERE is_active=1")
        active = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM apartments WHERE is_active=0")
        inactive = c.fetchone()[0]
        c.execute("SELECT MIN(monthly_aed) FROM apartments WHERE is_active=1")
        cheapest = c.fetchone()[0]
        c.execute("SELECT MAX(monthly_aed) FROM apartments WHERE is_active=1")
        priciest = c.fetchone()[0]
        c.execute("SELECT MAX(scraped_at) FROM apartments WHERE is_active=1")
        last_seen = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM apartments WHERE is_active=1 AND monthly_aed<=6000")
        within_budget = c.fetchone()[0]

        c.execute("SELECT commute_tier, COUNT(*) FROM apartments WHERE is_active=1 GROUP BY commute_tier ORDER BY 1")
        by_tier = [{"tier": int(r[0] or 0), "count": int(r[1])} for r in c.fetchall()]

        c.execute("SELECT area, COUNT(*) FROM apartments WHERE is_active=1 GROUP BY area ORDER BY 2 DESC")
        by_area = [{"area": r[0], "count": r[1]} for r in c.fetchall()]

        c.execute("SELECT source, COUNT(*) FROM apartments WHERE is_active=1 GROUP BY source ORDER BY 2 DESC")
        by_source = [{"source": r[0], "count": r[1]} for r in c.fetchall()]

        # monthly price histogram
        c.execute("SELECT monthly_aed, 1 FROM apartments WHERE is_active=1 AND monthly_aed>0")
        price_rows = c.fetchall()
        price_buckets = [
            (0,    3000,  "< 3K"),
            (3001, 4000,  "3–4K"),
            (4001, 5000,  "4–5K"),
            (5001, 6000,  "5–6K"),
            (6001, None,  "> 6K"),
        ]
        price_hist = _bucket_count(price_rows, price_buckets)

        # size histogram
        c.execute("SELECT size_sqft, 1 FROM apartments WHERE is_active=1 AND size_sqft>0")
        size_rows = c.fetchall()
        size_buckets = [
            (0,    400,  "< 400 sqft"),
            (401,  600,  "400–600"),
            (601,  800,  "600–800"),
            (801,  1000, "800–1000"),
            (1001, None, "> 1000"),
        ]
        size_hist = _bucket_count(size_rows, size_buckets)

    return {
        "summary": {
            "total":         total_all,
            "active":        active,
            "inactive":      inactive,
            "cheapest":      cheapest,
            "priciest":      priciest,
            "within_budget": within_budget,
            "last_seen":     last_seen,
        },
        "by_tier":    by_tier,
        "by_area":    by_area,
        "by_source":  by_source,
        "price_hist": price_hist,
        "size_hist":  size_hist,
    }


# ─── pipeline / scrape runs ───────────────────────────────────────────────────
def scrape_runs(limit: int = 50) -> list[dict]:
    init_db()
    with cur() as c:
        c.execute("""SELECT id, kind, started_at, finished_at, rows_seen, rows_new,
                            rows_updated, notes
                     FROM scrape_runs
                     ORDER BY id DESC
                     LIMIT ?""", (int(limit),))
        out: list[dict] = []
        for r in c.fetchall():
            d = dict(r)
            d["duration_s"] = None
            if d.get("started_at") and d.get("finished_at"):
                try:
                    s = datetime.fromisoformat(d["started_at"])
                    f = datetime.fromisoformat(d["finished_at"])
                    d["duration_s"] = round((f - s).total_seconds())
                except Exception:
                    pass
            out.append(d)
        return out


def derived_pipeline_health() -> dict:
    """When scrape_runs is empty, derive freshness from listing scraped_at."""
    init_db()
    with cur() as c:
        c.execute("SELECT MAX(scraped_at) FROM cars WHERE is_active=1")
        cars_last = c.fetchone()[0]
        c.execute("SELECT MAX(scraped_at) FROM apartments WHERE is_active=1")
        apts_last = c.fetchone()[0]

        # recent inserts (last 24h)
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
        c.execute("SELECT COUNT(*) FROM cars WHERE first_seen_at >= ?", (cutoff,))
        cars_new_24h = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM apartments WHERE first_seen_at >= ?", (cutoff,))
        apts_new_24h = c.fetchone()[0]

    return {
        "cars_last_scraped":         cars_last,
        "apartments_last_scraped":   apts_last,
        "cars_new_last_24h":         cars_new_24h,
        "apartments_new_last_24h":   apts_new_24h,
    }
