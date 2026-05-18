"""Sync Bayut apartment listings from this laptop to the Hostinger VPS.

Why this exists:
  Bayut's bot wall consistently returns 0 listings to the VPS's datacenter IP,
  but works fine from a residential IP (this laptop). This script bridges that:

    1. Run scrape_bayut() locally (works — residential IP)
    2. Write the result to a sync JSON file
    3. scp the JSON to the VPS
    4. SSH the VPS to run db/load_apartments_json.py against it (UPSERT)

  Result: the VPS DB gets fresh Bayut data without ever needing to scrape it itself.

Usage:
    # ONE-TIME setup (visible browser opens — solve any CAPTCHA, then Enter):
    python -X utf8 scripts/sync_bayut_to_vps.py --auth

    # Every other run (silent, uses saved cookies):
    python -X utf8 scripts/sync_bayut_to_vps.py

Requires:
    - patchright installed (already on this laptop)
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
AUTH_DIR = SCRAPER_DIR / ".auth"
AUTH_STATE = AUTH_DIR / "bayut_state.json"   # cookies + localStorage from a human-solved CAPTCHA
SSH_KEY = Path(os.path.expanduser("~/.ssh/oracle_dubai"))
VPS = "root@31.97.71.84"
VPS_PROJECT = "/root/dubai-hunt"
VPS_TMP_PATH = "/tmp/bayut_sync.json"


# ── auth flow ─────────────────────────────────────────────────────────────────
def run_auth_setup():
    """Open Bayut in a visible browser so the user can solve any CAPTCHA,
    then AUTO-DETECT success by polling the page state and save cookies."""
    from patchright.sync_api import sync_playwright
    print("\n\033[1;36m▶ Auth setup — opening Bayut in a visible window\033[0m")
    print("  A Chromium window will pop up on a Bayut listings page.")
    print("  • If you see a CAPTCHA → solve it.")
    print("  • If you see real apartment listings → you're already through.")
    print("  This script will auto-detect success and save your session.")
    print("  No need to press anything here — just deal with the browser.\n")
    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False, channel="chromium",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}, locale="en-AE",
        )
        page = ctx.new_page()
        page.goto("https://www.bayut.com/to-rent/apartments/dubai/deira/"
                  "?furnishing_status=furnished&beds_in=1&price_to=72000&rent_frequency=yearly",
                  wait_until="domcontentloaded", timeout=60000)

        # Poll the page every 2 seconds. Two success conditions:
        #   - At least 3 listing links visible (a[href*="/property/details-"]) → DOM-rendered listings
        #   - window.state.algolia.content.hits has items → Bayut's own hydration succeeded
        # Time-out after 10 min so the user has plenty of time.
        print("  …waiting for Bayut listings to appear", end="", flush=True)
        success_js = """
        () => {
          try {
            const hits = window?.state?.algolia?.content?.hits;
            if (Array.isArray(hits) && hits.length > 0) return true;
          } catch(e) {}
          const links = document.querySelectorAll('a[href*="/property/details-"]');
          return links.length >= 3;
        }
        """
        try:
            for tick in range(300):  # 300 × 2s = 10 min max
                if page.evaluate(success_js):
                    print(" detected!", flush=True)
                    break
                time.sleep(2)
                if tick % 5 == 0:
                    print(".", end="", flush=True)
            else:
                print("\n  \033[33m⚠\033[0m 10-min timeout — saving whatever cookies are present anyway")
        except Exception as e:
            print(f"\n  \033[33m⚠\033[0m page poll error: {e} — saving current state")

        # Wait a couple extra seconds so any post-CAPTCHA cookie sets land.
        time.sleep(3)
        ctx.storage_state(path=str(AUTH_STATE))
        browser.close()

    size = AUTH_STATE.stat().st_size if AUTH_STATE.exists() else 0
    if size > 100:
        print(f"\n  \033[32m✓\033[0m Saved {size:,} bytes of session state to {AUTH_STATE.name}")
        return 0
    else:
        print(f"\n  \033[31m✗\033[0m Storage state empty — try again")
        return 1


def step(msg: str) -> None:
    print(f"\n\033[1;34m▶ {msg}\033[0m", flush=True)


def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}", flush=True)
    sys.exit(1)


def main() -> int:
    if "--auth" in sys.argv[1:]:
        return run_auth_setup()

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
    # Must register in sys.modules BEFORE exec_module so the @dataclass decorator's
    # `sys.modules.get(cls.__module__)` lookup inside Python 3.13's dataclasses
    # implementation succeeds. Otherwise it returns None and crashes on __dict__.
    sys.modules["_scr_apt"] = scr
    spec.loader.exec_module(scr)
    from patchright.sync_api import sync_playwright

    # Load the saved storage state (cookies + localStorage from human-solved CAPTCHA).
    # If it doesn't exist, instruct the user to run --auth once first.
    if not AUTH_STATE.exists():
        fail("No Bayut session saved.\n"
             "  Run this first to capture one (visible browser, solve CAPTCHA, press Enter):\n"
             "    python -X utf8 scripts/sync_bayut_to_vps.py --auth")

    def _scrape_with(pw, headless: bool):
        browser = pw.chromium.launch(
            headless=headless, channel="chromium",
            args=(["--window-position=-3000,-3000", "--window-size=1920,1080"] if not headless else []) + [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}, locale="en-AE",
            storage_state=str(AUTH_STATE),   # ← human-solved CAPTCHA cookies
        )
        page = ctx.new_page()
        try:
            return scr.scrape_bayut(page)
        finally:
            # Persist any updated cookies (Bayut rotates session tokens periodically)
            try: ctx.storage_state(path=str(AUTH_STATE))
            except Exception: pass
            try: ctx.close()
            except Exception: pass
            try: browser.close()
            except Exception: pass

    try:
        with sync_playwright() as pw:
            print("    (silent headless mode, using saved Bayut session)", flush=True)
            rows = _scrape_with(pw, headless=True)
            if not rows:
                print("    headless returned 0 — Bayut may have rotated session tokens.")
                print("    Run --auth again to refresh.", flush=True)
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
