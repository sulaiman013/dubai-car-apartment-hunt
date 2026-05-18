"""Sync Bayut apartment listings from this laptop to the Hostinger VPS.

Why this exists:
  Bayut's bot wall consistently returns 0 listings to the VPS's datacenter IP,
  but works fine from a residential IP (this laptop). This script bridges that:

    1. Run scrape_bayut() locally (works — residential IP)
    2. Write the result to a sync JSON file
    3. scp the JSON to the VPS
    4. SSH the VPS to run db/load_apartments_json.py against it (UPSERT)

  Result: the VPS DB gets fresh Bayut data without ever needing to scrape it itself.

Usage (from the project root):
    python -X utf8 scripts/sync_bayut_to_vps.py

Requires:
    - The same venv that runs the scrapers (patchright installed)
    - ~/.ssh/oracle_dubai SSH key already authorized on the VPS
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

# ── config ────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = ROOT / "Apartment Search - Dubai"
SYNC_JSON_LOCAL = ROOT / "_sync_bayut.json"
SSH_KEY = Path(os.path.expanduser("~/.ssh/oracle_dubai"))
VPS = "root@31.97.71.84"
VPS_PROJECT = "/root/dubai-hunt"
VPS_TMP_PATH = "/tmp/bayut_sync.json"


def step(msg: str) -> None:
    print(f"\n\033[1;34m▶ {msg}\033[0m", flush=True)


def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}", flush=True)
    sys.exit(1)


def main() -> int:
    print("=" * 64)
    print("  Bayut → VPS sync")
    print("=" * 64)
    t_start = time.time()

    if not SSH_KEY.exists():
        fail(f"SSH key not found at {SSH_KEY}")

    # ── 1. Scrape Bayut locally ───────────────────────────────────────────────
    step("Scraping Bayut from this laptop (residential IP, no bot wall)")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(SCRAPER_DIR))
    # The scraper module name conflicts with itself when imported from both paths;
    # use importlib to load it cleanly under a unique name.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_scr_apt", SCRAPER_DIR / "scrape_apartments.py"
    )
    scr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scr)
    from patchright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            browser, ctx = scr._new_browser(pw)
            page = ctx.new_page()
            try:
                rows = scr.scrape_bayut(page)
            finally:
                try: ctx.close()
                except Exception: pass
                try: browser.close()
                except Exception: pass
    except Exception as e:
        fail(f"scraper crashed: {e}")

    if not rows:
        fail("Bayut returned 0 listings from the laptop too. Check Bayut.com manually — "
             "could be a real outage, or your IP got temp-flagged. Try again in 1-2h.")
    ok(f"got {len(rows)} Bayut apartments")

    # Print a per-tier breakdown for visibility
    by_tier: dict[int, int] = {}
    for r in rows:
        by_tier[r.commute_tier] = by_tier.get(r.commute_tier, 0) + 1
    print(f"    By DAFZA tier: {sorted(by_tier.items())}")
    cheapest = min(rows, key=lambda r: r.price_aed)
    print(f"    Cheapest:      AED {cheapest.price_aed:,}/yr in {cheapest.area} (tier {cheapest.commute_tier})")

    # ── 2. Write sync JSON ────────────────────────────────────────────────────
    step(f"Writing sync JSON → {SYNC_JSON_LOCAL.name}")
    now_iso = datetime.now().isoformat(timespec="seconds")
    payload = []
    for r in rows:
        d = asdict(r)
        d["scraped_at"] = now_iso
        payload.append(d)
    with SYNC_JSON_LOCAL.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    size_kb = SYNC_JSON_LOCAL.stat().st_size // 1024
    ok(f"wrote {len(payload)} rows, {size_kb} KB")

    # ── 3. scp to VPS ─────────────────────────────────────────────────────────
    step(f"Pushing to {VPS}:{VPS_TMP_PATH}")
    scp_cmd = [
        "scp", "-i", str(SSH_KEY),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
        str(SYNC_JSON_LOCAL),
        f"{VPS}:{VPS_TMP_PATH}",
    ]
    r = subprocess.run(scp_cmd, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"scp failed: {r.stderr.strip()}")
    ok("transferred")

    # ── 4. SSH-run the loader on VPS ──────────────────────────────────────────
    step("Importing on VPS via db/load_apartments_json.py")
    loader_cmd = (
        f"cd {VPS_PROJECT} && "
        f"{VPS_PROJECT}/.venv/bin/python -m db.load_apartments_json {VPS_TMP_PATH}"
    )
    ssh_cmd = [
        "ssh", "-i", str(SSH_KEY),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=30",
        VPS, loader_cmd,
    ]
    r = subprocess.run(ssh_cmd, capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        fail(f"VPS loader failed: {r.stderr.strip()}")
    ok("import complete")

    # ── 5. Regenerate the dashboard data.js so the website reflects the change ─
    step("Regenerating Apartment Hunt data.js on VPS")
    prep_cmd = f"{VPS_PROJECT}/.venv/bin/python -X utf8 '{VPS_PROJECT}/Apartment Hunt Frontend/prep_data.py' | tail -10"
    r = subprocess.run(
        ["ssh", "-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", VPS, prep_cmd],
        capture_output=True, text=True
    )
    print(r.stdout)
    ok("data.js refreshed")

    # ── done ──────────────────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    print(f"  ✅  Sync complete in {time.time() - t_start:.1f}s")
    print("=" * 64)
    print(f"  Verify:  https://31.97.71.84.sslip.io/Apartment%20Hunt%20Frontend/")
    print(f"  Stats:   https://31.97.71.84.sslip.io/stats")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
