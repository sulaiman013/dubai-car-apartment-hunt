"""Generate scored Dubai-only car data for the frontend.

Source of truth:  SQLite (db/dubai_hunt.db) via db/queries.query_cars().
Falls back to:    dubai_cars.json snapshot if the DB module can't be imported.
Writes:           data.js (window.CAR_DATA + window.CAR_STATS).
"""
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DUBAI_JSON = os.path.join(ROOT, "Car Search - Dubai UAE", "dubai_cars.json")
OUT = os.path.join(HERE, "data.js")

# Allow `from db.queries import ...`
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CURRENT_YEAR = 2026

# Reliability + value profiles per model. Tuned for Dubai used market.
PROFILES = {
    "Hyundai Elantra": {"life": 350000, "rel": 7.5, "ppy": 800, "red": 240000, "sweet_km": [80000, 180000], "sweet_yr": [2011, 2017]},
    "Honda Civic":     {"life": 400000, "rel": 8.5, "ppy": 1000, "red": 280000, "sweet_km": [80000, 180000], "sweet_yr": [2008, 2014]},
    "Nissan Sunny":    {"life": 320000, "rel": 7.5, "ppy": 500, "red": 220000, "sweet_km": [60000, 160000], "sweet_yr": [2014, 2019]},
    "Toyota Corolla":  {"life": 500000, "rel": 9.5, "ppy": 900, "red": 300000, "sweet_km": [100000, 200000], "sweet_yr": [2009, 2015]},
    "Toyota Yaris":    {"life": 450000, "rel": 9.0, "ppy": 600, "red": 280000, "sweet_km": [80000, 180000], "sweet_yr": [2010, 2016]},
    "Toyota Camry":    {"life": 500000, "rel": 9.5, "ppy": 1100, "red": 320000, "sweet_km": [100000, 200000], "sweet_yr": [2009, 2015]},
}
DEFAULT_PROFILE = {"life": 350000, "rel": 7.0, "ppy": 700, "red": 230000, "sweet_km": [80000, 180000], "sweet_yr": [2010, 2016]}


def score(car: dict) -> tuple[float, dict]:
    """Return (final_score, sub_scores) on 0-100."""
    brand = car.get("brand", "")
    p = PROFILES.get(brand, DEFAULT_PROFILE)

    price = car.get("price_aed") or 0
    year = car.get("year") or 0
    km = car.get("km") or 0
    age = max(1, CURRENT_YEAR - year) if year else 15

    s: dict[str, float] = {}

    # Price (favor 12K-16K AED sweet spot in Dubai market)
    if 12000 <= price <= 16000:
        s["price"] = 100
    elif 9000 <= price < 12000:
        s["price"] = 80 + (price - 9000) / 3000 * 20
    elif 16000 < price <= 18000:
        s["price"] = 100 - (price - 16000) / 2000 * 25
    elif 7000 <= price < 9000:
        s["price"] = 55 + (price - 7000) / 2000 * 25
    elif 18000 < price <= 22000:
        s["price"] = max(50, 75 - (price - 18000) / 4000 * 25)
    elif price < 7000:
        s["price"] = max(10, 55 - (7000 - price) / 1000 * 10)
    else:
        s["price"] = max(0, 50 - (price - 22000) / 1000 * 15)

    # Mileage
    if km > 0:
        life = max(0.0, 1 - km / p["life"])
        lo, hi = p["sweet_km"]
        if lo <= km <= hi:
            life = min(1.0, life + 0.15)
        if km > p["red"]:
            life *= 0.55
        s["mileage"] = life * 100
    else:
        s["mileage"] = 40

    # Age
    age_n = max(0.0, min(1.0, 1 - (age - 5) / 20))
    lo, hi = p["sweet_yr"]
    if year and lo <= year <= hi:
        age_n = min(1.0, age_n + 0.15)
    s["age"] = age_n * 100

    s["reliability"] = (p["rel"] / 10) * 100

    # Km per year
    if km > 0 and age > 0:
        kpy = km / age
        if kpy <= 12000: s["kpy"] = 100
        elif kpy <= 18000: s["kpy"] = 85
        elif kpy <= 25000: s["kpy"] = 70
        elif kpy <= 35000: s["kpy"] = 50
        else: s["kpy"] = 25
    else:
        s["kpy"] = 50

    # Value (price per year of age vs benchmark)
    if age > 0 and price > 0:
        ppy = price / age
        ratio = ppy / p["ppy"]
        if 0.5 <= ratio <= 1.5:
            s["value"] = 90 + (1 - abs(ratio - 1)) * 10
        elif ratio < 0.5:
            s["value"] = 40 + ratio * 80
        else:
            s["value"] = max(0, 90 - (ratio - 1.5) * 60)
    else:
        s["value"] = 50

    s["transmission"] = 80 if "auto" in (car.get("transmission") or "").lower() else 50
    s["sunroof"] = 100 if car.get("has_sunroof") else 50

    w = {
        "price": 0.20, "mileage": 0.16, "age": 0.10, "reliability": 0.12,
        "kpy": 0.10, "value": 0.10, "transmission": 0.04, "sunroof": 0.18,
    }
    final = round(sum(s[k] * w[k] for k in w), 1)
    return final, s


def rating_label(score_val: float, sunroof: bool) -> str:
    if score_val >= 75: return "EXCELLENT"
    if score_val >= 60: return "GOOD"
    if score_val >= 45: return "FAIR"
    if score_val >= 30: return "BELOW AVG"
    return "POOR"


def _load_from_db() -> list[dict] | None:
    """Preferred: read active cars from the canonical SQLite store."""
    try:
        from db.queries import query_cars  # type: ignore
    except Exception as e:
        print(f"(DB read unavailable: {e}; falling back to JSON)")
        return None
    return query_cars(limit=500)


def _load_from_json() -> list[dict]:
    if not os.path.exists(DUBAI_JSON):
        return []
    with open(DUBAI_JSON, encoding="utf-8") as f:
        return json.load(f)


def load_dubai() -> list[dict]:
    cars = _load_from_db()
    if cars is None:
        cars = _load_from_json()

    out = []
    for c in cars:
        sc, sub = score(c)
        km = c.get("km")
        out.append({
            "id": c.get("ad_id", ""),
            "source": c.get("source", ""),
            "brand": c.get("brand", ""),
            "title": c.get("title", ""),
            "year": c.get("year"),
            "price": c.get("price_aed", 0),
            "currency": "AED",
            "km": km,
            "km_str": f"{km:,} km" if km else "N/A",
            "transmission": c.get("transmission", ""),
            "trim": c.get("trim", ""),
            "location": c.get("location", "Dubai"),
            "color": c.get("color", ""),
            "body_type": c.get("body_type", ""),
            "fuel": c.get("fuel", ""),
            "seller_type": c.get("seller_type", ""),
            "image": c.get("image", ""),
            "url": c.get("url", ""),
            "has_sunroof": bool(c.get("has_sunroof")),
            "features": c.get("features", []),
            "description": c.get("description", ""),
            "score": sc,
            "sub_scores": sub,
            "rating": rating_label(sc, c.get("has_sunroof", False)),
        })
    return out


def main() -> None:
    cars = load_dubai()
    cars.sort(key=lambda x: (not x["has_sunroof"], -x["score"]))

    stats = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(cars),
        "sunroof_count": sum(1 for c in cars if c["has_sunroof"]),
        "by_brand": {},
        "by_source": {},
    }
    for c in cars:
        stats["by_brand"][c["brand"]] = stats["by_brand"].get(c["brand"], 0) + 1
        stats["by_source"][c["source"]] = stats["by_source"].get(c["source"], 0) + 1

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// Auto-generated -- DO NOT EDIT BY HAND\n")
        f.write("// Run: python prep_data.py\n")
        f.write("window.CAR_DATA = ")
        json.dump(cars, f, ensure_ascii=False, indent=0)
        f.write(";\n")
        f.write("window.CAR_STATS = ")
        json.dump(stats, f, ensure_ascii=False, indent=0)
        f.write(";\n")

    print(f"Cars total:        {len(cars)}")
    print(f"With sunroof:      {stats['sunroof_count']}")
    print(f"By brand:          {stats['by_brand']}")
    print(f"By source:         {stats['by_source']}")
    print(f"Saved: {OUT} ({os.path.getsize(OUT)//1024} KB)")


if __name__ == "__main__":
    main()
