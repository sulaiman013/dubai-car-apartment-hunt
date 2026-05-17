"""Generate scored apartment data for the frontend.

Source of truth:  SQLite (db/dubai_hunt.db), via db/queries.query_apartments().
Falls back to:    apartments.json snapshot, if the DB module can't be imported.
Writes:           data.js  (window.APT_DATA + window.APT_STATS).
"""
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
APT_JSON = os.path.join(ROOT, "Apartment Search - Dubai", "apartments.json")
OUT = os.path.join(HERE, "data.js")

# Make `from db.queries import ...` work when run from the project root or this dir.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

MONTHLY_BUDGET = 6000   # AED
YEAR_BUDGET = MONTHLY_BUDGET * 12

TIER_NAMES = {
    1: "DAFZA-adjacent (5-10 min)",
    2: "10-15 min",
    3: "15-20 min",
    # Tier 4 not used — only DAFZA-convenient areas are kept (see scraper config).
}


def score(a: dict) -> tuple[float, dict]:
    """Composite 0-100 score for the user (DAFZA-adjacent + budget + size + amenities)."""
    s: dict[str, float] = {}

    # Commute (lower tier = higher score). 40% weight.
    tier = a.get("commute_tier", 4)
    s["commute"] = {1: 100, 2: 80, 3: 60, 4: 40}.get(tier, 30)

    # Budget headroom (cheaper = better). 25% weight.
    price = a.get("price_aed") or 0
    monthly = a.get("monthly_aed") or 0
    if monthly == 0:
        s["budget"] = 0
    elif monthly <= 4000:
        s["budget"] = 100
    elif monthly <= 5000:
        s["budget"] = 90
    elif monthly <= 5500:
        s["budget"] = 80
    elif monthly <= MONTHLY_BUDGET:
        s["budget"] = 70 - (monthly - 5500) / 500 * 10
    else:
        # Over-budget; sharp penalty
        s["budget"] = max(0, 50 - (monthly - MONTHLY_BUDGET) / 100)

    # Size. 15% weight. 500-700 sqft is plenty for 1BHK; below 400 cramped.
    size = a.get("size_sqft") or 0
    if size == 0:
        s["size"] = 50
    elif size >= 700: s["size"] = 100
    elif size >= 550: s["size"] = 85
    elif size >= 450: s["size"] = 75
    elif size >= 350: s["size"] = 60
    else: s["size"] = 40

    # Amenities. 10% weight. Look for gym/pool/parking/balcony.
    amen = [str(x).lower() for x in (a.get("amenities") or [])]
    amen_bonus = 0
    for kw, b in [("parking", 10), ("gym", 8), ("pool", 7), ("balcony", 6), ("security", 4)]:
        if any(kw in x for x in amen):
            amen_bonus += b
    s["amenities"] = min(100, 40 + amen_bonus)

    # Bathrooms. 5% — a 1BHK with 2 baths is a plus.
    baths = a.get("bathrooms") or 1
    s["bathrooms"] = 100 if baths >= 2 else 70

    # Image present (visual confidence). 5%.
    s["image"] = 100 if a.get("image") else 40

    w = {
        "commute": 0.40, "budget": 0.25, "size": 0.15,
        "amenities": 0.10, "bathrooms": 0.05, "image": 0.05,
    }
    final = round(sum(s[k] * w[k] for k in w), 1)
    return final, s


def rating_label(score_val: float) -> str:
    if score_val >= 80: return "EXCELLENT"
    if score_val >= 65: return "GOOD"
    if score_val >= 50: return "FAIR"
    return "BELOW AVG"


def _load_from_db() -> list[dict] | None:
    """Preferred: read active apartments from the canonical SQLite store."""
    try:
        from db.queries import query_apartments  # type: ignore
    except Exception as e:
        print(f"(DB read unavailable: {e}; falling back to JSON snapshot)")
        return None
    rows = query_apartments(limit=500)   # only active by default
    return rows


def _load_from_json() -> list[dict]:
    """Legacy fallback: read the JSON snapshot file."""
    if not os.path.exists(APT_JSON):
        return []
    with open(APT_JSON, encoding="utf-8") as f:
        return json.load(f)


def load_apartments() -> list[dict]:
    raw = _load_from_db()
    if raw is None:
        raw = _load_from_json()
    out = []
    for a in raw:
        sc, sub = score(a)
        out.append({
            **a,
            "tier_name": TIER_NAMES.get(a.get("commute_tier", 4), "?"),
            "score": sc,
            "sub_scores": sub,
            "rating": rating_label(sc),
            "within_budget": (a.get("monthly_aed") or 0) <= MONTHLY_BUDGET,
        })
    return out


def main() -> None:
    rows = load_apartments()
    # Sort: tier asc, then price asc
    rows.sort(key=lambda r: (r["commute_tier"], r["price_aed"]))

    by_tier: dict[int, int] = {}
    by_area: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for r in rows:
        by_tier[r["commute_tier"]] = by_tier.get(r["commute_tier"], 0) + 1
        by_area[r["area"]] = by_area.get(r["area"], 0) + 1
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1

    stats = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(rows),
        "within_budget": sum(1 for r in rows if r["within_budget"]),
        "by_tier": {str(k): v for k, v in sorted(by_tier.items())},
        "by_area": by_area,
        "by_source": by_source,
        "monthly_budget": MONTHLY_BUDGET,
        "year_budget": YEAR_BUDGET,
    }
    if rows:
        cheapest = min(rows, key=lambda r: r["price_aed"])
        stats["cheapest"] = {
            "monthly_aed": cheapest["monthly_aed"],
            "area": cheapest["area"],
            "tier": cheapest["commute_tier"],
        }

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by prep_data.py -- DO NOT EDIT BY HAND\n")
        f.write("window.APT_DATA = ")
        json.dump(rows, f, ensure_ascii=False, indent=0)
        f.write(";\n")
        f.write("window.APT_STATS = ")
        json.dump(stats, f, ensure_ascii=False, indent=0)
        f.write(";\n")

    print(f"Apartments total:  {len(rows)}")
    print(f"Within budget:     {stats['within_budget']}")
    print(f"By tier:           {stats['by_tier']}")
    print(f"By area:           {by_area}")
    print(f"Saved: {OUT} ({os.path.getsize(OUT)//1024} KB)")


if __name__ == "__main__":
    main()
