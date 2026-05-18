"""Loader: read a JSON file of apartment records and UPSERT each into the DB.

Designed for the Bayut-from-laptop sync flow:
  - Laptop scrapes Bayut (where the residential IP works)
  - Laptop scp's the JSON to /tmp/bayut_sync.json on the VPS
  - VPS runs: python -m db.load_apartments_json /tmp/bayut_sync.json

Safe to run any time: UPSERT preserves all existing records, only adds/updates
the ones in the input file. Never deletes or marks inactive.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

# Allow running both as `python -m db.load_apartments_json` and as a script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.db import upsert_apartment   # type: ignore


def load(json_path: str) -> dict:
    p = Path(json_path)
    if not p.exists():
        raise SystemExit(f"file not found: {json_path}")

    with p.open(encoding="utf-8") as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise SystemExit(f"expected a JSON list, got {type(records).__name__}")

    inserted = updated = skipped = errors = 0
    by_source: dict[str, int] = {}
    by_area: dict[str, int] = {}
    for rec in records:
        try:
            result = upsert_apartment(rec)
            if result == "inserted":
                inserted += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1
            by_source[rec.get("source", "?")] = by_source.get(rec.get("source", "?"), 0) + 1
            area = rec.get("area", "?")
            by_area[area] = by_area.get(area, 0) + 1
        except Exception as e:
            errors += 1
            print(f"  ! upsert failed for ad_id={rec.get('ad_id')!r}: {e}", file=sys.stderr)

    return {
        "file":      str(p),
        "rows":      len(records),
        "inserted":  inserted,
        "updated":   updated,
        "skipped":   skipped,
        "errors":    errors,
        "by_source": by_source,
        "by_area":   by_area,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m db.load_apartments_json <path-to-json>", file=sys.stderr)
        return 2

    result = load(sys.argv[1])
    print("─" * 60)
    print(f"  Loaded:   {result['file']}")
    print(f"  Records:  {result['rows']}")
    print(f"  Inserted: {result['inserted']}")
    print(f"  Updated:  {result['updated']}")
    print(f"  Skipped:  {result['skipped']}")
    if result['errors']:
        print(f"  ERRORS:   {result['errors']}")
    print(f"  By source: {result['by_source']}")
    print(f"  By area:   {result['by_area']}")
    print("─" * 60)
    return 0 if result["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
