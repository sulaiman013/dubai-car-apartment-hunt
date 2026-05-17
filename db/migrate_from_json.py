"""One-shot: read existing JSON files and upsert into the SQLite DB.
Safe to re-run — UPSERTs by ad_id. Existing rows get updated.
"""
import json
import os
import sys
from pathlib import Path

# Make `from db.db import ...` work whether called from project root or here.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db.db import init_db, upsert_car, upsert_apartment

CARS_JSON  = ROOT / "Car Search - Dubai UAE" / "dubai_cars.json"
APTS_JSON  = ROOT / "Apartment Search - Dubai" / "apartments.json"


def migrate_cars() -> tuple[int, int]:
    if not CARS_JSON.exists():
        return 0, 0
    rows = json.loads(CARS_JSON.read_text(encoding="utf-8"))
    ins = upd = 0
    for r in rows:
        result = upsert_car(r)
        if result == "inserted": ins += 1
        elif result == "updated": upd += 1
    return ins, upd


def migrate_apartments() -> tuple[int, int]:
    if not APTS_JSON.exists():
        return 0, 0
    rows = json.loads(APTS_JSON.read_text(encoding="utf-8"))
    ins = upd = 0
    for r in rows:
        result = upsert_apartment(r)
        if result == "inserted": ins += 1
        elif result == "updated": upd += 1
    return ins, upd


if __name__ == "__main__":
    init_db()
    print(f"DB at: {ROOT / 'db' / 'dubai_hunt.db'}")

    ins_c, upd_c = migrate_cars()
    print(f"Cars:       inserted {ins_c}, updated {upd_c}")

    ins_a, upd_a = migrate_apartments()
    print(f"Apartments: inserted {ins_a}, updated {upd_a}")

    # Quick sanity check
    from db.queries import get_stats
    import json as _json
    print("\nDB stats:")
    print(_json.dumps(get_stats(), indent=2, default=str))
