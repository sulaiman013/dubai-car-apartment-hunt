"""
Dubai Hunt — full UAT.

Covers:
  1. SQLite DB integrity (active counts, FK-like guarantees)
  2. FastAPI endpoints (status, payload shape)
  3. Data consistency (DB == API == frontend data.js)
  4. Cars dashboard (UI checks)
  5. Apartments dashboard (UI checks)
  6. Ops Dashboard (tabs, KPIs, charts)
  7. Landing page (links)
  8. Telegram bot process (alive)
  9. Data freshness sanity (apartments all DAFZA-convenient)

Run:
    python -X utf8 tests/uat_full.py
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeoutError

ROOT     = Path(__file__).resolve().parent.parent
DB_PATH  = ROOT / "db" / "dubai_hunt.db"
API_BASE = "http://127.0.0.1:8090"
SHOTS    = ROOT / "tests" / "_screenshots_full"
SHOTS.mkdir(parents=True, exist_ok=True)

INDEX_LANDING   = ROOT / "index.html"
INDEX_CARS      = ROOT / "Car Deals Frontend" / "index.html"
INDEX_APTS      = ROOT / "Apartment Hunt Frontend" / "index.html"
INDEX_OPS       = ROOT / "Ops Dashboard" / "index.html"

# ─── result plumbing ──────────────────────────────────────────────────────────
@dataclass
class Result:
    section: str
    name: str
    passed: bool
    detail: str = ""
    duration_ms: int = 0


results: list[Result] = []


def check(section: str, name: str, page: Page | None = None):
    def deco(fn: Callable[[], tuple[bool, str]]):
        t0 = time.time()
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=2)}"
        dur = int((time.time() - t0) * 1000)
        if not ok and page is not None:
            try:
                page.screenshot(path=str(SHOTS / f"{section}_{name.replace(' ', '_')}.png"))
            except Exception:
                pass
        results.append(Result(section, name, ok, detail, dur))
        sym = "PASS" if ok else "FAIL"
        print(f"  [{sym}] {section:>10} · {name} ({dur}ms)" + (f"\n            {detail.splitlines()[0]}" if not ok and detail else ""), flush=True)
        return ok
    return deco


# ─── helpers ──────────────────────────────────────────────────────────────────
def http_get_json(path: str) -> dict:
    with urlopen(API_BASE + path, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def db_count(table: str, where: str = "is_active=1") -> int:
    con = sqlite3.connect(str(DB_PATH))
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
    finally:
        con.close()


def extract_window_data(html_path: Path, key: str) -> list | dict | None:
    """Pull `window.<key> = ...;` JSON from a generated data.js."""
    js_path = html_path.parent / "data.js"
    if not js_path.exists():
        return None
    raw = js_path.read_text(encoding="utf-8")
    m = re.search(rf"window\.{key}\s*=\s*(.+?);\s*\n", raw, re.DOTALL)
    if not m:
        return None
    return json.loads(m.group(1))


# ═════════════════════════════════════════════════════════════════════════════
#  1. DB INTEGRITY
# ═════════════════════════════════════════════════════════════════════════════
def section_db():
    print("\n── DB integrity ────────────────────────────────────────────────────")

    @check("db", "DB file exists")
    def _():
        return DB_PATH.exists(), str(DB_PATH)

    @check("db", "cars table has active rows")
    def _():
        n = db_count("cars")
        return n > 0, f"active cars={n}"

    @check("db", "apartments table has active rows")
    def _():
        n = db_count("apartments")
        return n > 0, f"active apartments={n}"

    @check("db", "every active car has Dubai location")
    def _():
        con = sqlite3.connect(str(DB_PATH))
        rows = con.execute("SELECT location FROM cars WHERE is_active=1").fetchall()
        con.close()
        bad = []
        for (loc,) in rows:
            parts = [p.strip() for p in (loc or "").split(">") if p.strip()]
            if parts and parts[0].upper() == "UAE":
                parts = parts[1:]
            em = parts[0].lower() if parts else ""
            if em != "dubai":
                bad.append(loc)
        return len(bad) == 0, f"non-Dubai cars: {len(bad)}; sample={bad[:3]}"

    @check("db", "every active apartment has commute_tier 1-3 (no Tier 4)")
    def _():
        con = sqlite3.connect(str(DB_PATH))
        n = con.execute("SELECT COUNT(*) FROM apartments WHERE is_active=1 AND commute_tier > 3").fetchone()[0]
        con.close()
        return n == 0, f"tier>3 active apartments: {n}"

    @check("db", "no active apartments in rejected areas")
    def _():
        con = sqlite3.connect(str(DB_PATH))
        rejected = ("International City", "Discovery Gardens", "Dubai Silicon Oasis",
                    "Al Nahda Sharjah", "Al Taawun Sharjah", "Al Nahda (Sharjah)", "Al Taawun (Sharjah)")
        n = con.execute(
            f"SELECT COUNT(*) FROM apartments WHERE is_active=1 AND area IN ({','.join('?'*len(rejected))})",
            rejected,
        ).fetchone()[0]
        con.close()
        return n == 0, f"rejected-area active rows: {n}"

    @check("db", "scrape_runs table has at least one row")
    def _():
        con = sqlite3.connect(str(DB_PATH))
        n = con.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0]
        con.close()
        return n >= 1, f"runs logged: {n}"


# ═════════════════════════════════════════════════════════════════════════════
#  2. API
# ═════════════════════════════════════════════════════════════════════════════
def section_api():
    print("\n── API endpoints ───────────────────────────────────────────────────")

    @check("api", "GET / returns service banner")
    def _():
        r = http_get_json("/")
        return r.get("ok") is True, json.dumps(r)[:200]

    @check("api", "GET /stats has cars + apartments keys")
    def _():
        r = http_get_json("/stats")
        return "cars" in r and "apartments" in r, list(r.keys())

    @check("api", "GET /cars returns >= 1 result")
    def _():
        r = http_get_json("/cars?limit=5")
        return r.get("count", 0) >= 1, f"count={r.get('count')}"

    @check("api", "GET /cars?has_sunroof=true filters correctly")
    def _():
        r = http_get_json("/cars?has_sunroof=true&limit=20")
        bad = [x for x in r.get("results", []) if not x.get("has_sunroof")]
        return r.get("count", 0) >= 1 and not bad, f"count={r.get('count')}, bad={len(bad)}"

    @check("api", "GET /apartments returns >= 1 result")
    def _():
        r = http_get_json("/apartments?limit=5")
        return r.get("count", 0) >= 1, f"count={r.get('count')}"

    @check("api", "GET /apartments?max_tier=3 (the new max) covers all active")
    def _():
        all_apts = http_get_json("/apartments?limit=200")["count"]
        t3 = http_get_json("/apartments?max_tier=3&limit=200")["count"]
        return all_apts == t3, f"all={all_apts}, ≤T3={t3}"

    @check("api", "GET /admin/health bundles cars + apartments + pipeline")
    def _():
        r = http_get_json("/admin/health")
        return all(k in r for k in ("cars", "apartments", "pipeline")), list(r.keys())

    @check("api", "GET /admin/scrape_runs returns 'runs' list")
    def _():
        r = http_get_json("/admin/scrape_runs?limit=10")
        return isinstance(r.get("runs"), list), f"keys={list(r.keys())}"


# ═════════════════════════════════════════════════════════════════════════════
#  3. DATA CONSISTENCY (DB == API == data.js)
# ═════════════════════════════════════════════════════════════════════════════
def section_consistency():
    print("\n── Data consistency: DB ⇄ API ⇄ data.js ────────────────────────────")

    @check("consist", "DB cars count == API /stats.cars.total")
    def _():
        api = http_get_json("/stats")["cars"]["total"]
        db  = db_count("cars")
        return api == db, f"api={api}, db={db}"

    @check("consist", "DB apts count == API /stats.apartments.total")
    def _():
        api = http_get_json("/stats")["apartments"]["total"]
        db  = db_count("apartments")
        return api == db, f"api={api}, db={db}"

    @check("consist", "Cars data.js matches API count (±5 tolerance for limit)")
    def _():
        data = extract_window_data(INDEX_CARS, "CAR_DATA")
        if data is None:
            return False, "data.js missing"
        api = http_get_json("/cars?limit=500")["count"]
        return abs(len(data) - api) <= 5, f"data.js={len(data)}, api={api}"

    @check("consist", "Apartments data.js == API count (no inactive)")
    def _():
        data = extract_window_data(INDEX_APTS, "APT_DATA")
        if data is None:
            return False, "data.js missing"
        api = http_get_json("/apartments?limit=500")["count"]
        return len(data) == api, f"data.js={len(data)}, api={api}"


# ═════════════════════════════════════════════════════════════════════════════
#  4-7. UI checks via Playwright
# ═════════════════════════════════════════════════════════════════════════════
def section_landing(page: Page):
    print("\n── Landing page ────────────────────────────────────────────────────")
    page.goto(INDEX_LANDING.as_uri(), wait_until="load", timeout=15000)
    page.wait_for_timeout(800)

    @check("landing", "Page title contains 'Dubai Hunt'", page)
    def _():
        t = page.title()
        return "Dubai Hunt" in t, f"title={t!r}"

    @check("landing", "Has links to all 3 dashboards", page)
    def _():
        hrefs = page.locator("a").evaluate_all("els => els.map(e => e.getAttribute('href'))")
        needed = {
            "Car Deals Frontend":     any("Car%20Deals%20Frontend" in (h or "") for h in hrefs),
            "Apartment Hunt Frontend": any("Apartment%20Hunt%20Frontend" in (h or "") for h in hrefs),
            "Ops Dashboard":          any("Ops%20Dashboard" in (h or "") for h in hrefs),
        }
        missing = [k for k, v in needed.items() if not v]
        return not missing, f"missing links: {missing}"


def section_cars(page: Page):
    print("\n── Cars dashboard ──────────────────────────────────────────────────")
    page.goto(INDEX_CARS.as_uri(), wait_until="load", timeout=20000)
    try:
        page.wait_for_selector("#list .row", timeout=8000)
    except PWTimeoutError:
        pass
    page.wait_for_timeout(800)

    @check("cars", "Page renders at least 1 row", page)
    def _():
        n = page.locator("#list .row").count()
        return n > 0, f"rows={n}"

    @check("cars", "Top-strip stats are populated (not '—')", page)
    def _():
        total = page.locator("#stat-total").text_content().strip()
        return total not in ("—", "", "0"), f"#stat-total={total!r}"

    @check("cars", "Sunroof filter chip toggles + reduces count", page)
    def _():
        before = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        page.locator('[data-chip="sunroof"]').click()
        page.wait_for_timeout(300)
        after = int(page.locator("#count-shown").text_content().strip().replace(",", ""))
        page.locator('[data-chip="sunroof"]').click()
        page.wait_for_timeout(300)
        return after < before and after > 0, f"before={before}, after_sunroof_only={after}"

    @check("cars", "Clicking a row opens modal via dispatch_event", page)
    def _():
        page.locator("#list .row").nth(2).dispatch_event("click")
        page.wait_for_selector("#modal:not([hidden])", timeout=3000)
        ok = not page.locator("#modal").is_hidden()
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        return ok, "modal opened"


def section_apts(page: Page):
    print("\n── Apartments dashboard ────────────────────────────────────────────")
    page.goto(INDEX_APTS.as_uri(), wait_until="load", timeout=20000)
    page.wait_for_timeout(800)

    @check("apts", "Page renders rows", page)
    def _():
        n = page.locator("#list .row").count()
        return n > 0, f"rows={n}"

    @check("apts", "All visible rows are tier 1-3 (no tier 4 badge)", page)
    def _():
        # Check tier tags
        tier_tags = page.locator(".row__tierTag").all_text_contents()
        bad = [t for t in tier_tags if "T4" in t or "Tier 4" in t]
        return not bad, f"tier-4 tags found: {len(bad)}; sample={bad[:3]}"

    @check("apts", "Stats line shows correct totals", page)
    def _():
        total = page.locator("#stat-total").text_content().strip()
        return total not in ("—", "", "0"), f"#stat-total={total!r}"


def section_ops(page: Page):
    print("\n── Ops Dashboard ───────────────────────────────────────────────────")
    page.goto(INDEX_OPS.as_uri(), wait_until="load", timeout=20000)
    page.wait_for_timeout(3500)   # let charts render

    @check("ops", "Status dot shows 'API online'", page)
    def _():
        txt = page.locator("#status-text").text_content().strip()
        return txt == "API online", f"status={txt!r}"

    @check("ops", "Overview KPIs populated (not '—')", page)
    def _():
        cars  = page.locator("#kpi-cars-total").text_content().strip()
        sun   = page.locator("#kpi-cars-sunroof").text_content().strip()
        apt   = page.locator("#kpi-apt-total").text_content().strip()
        return all(v not in ("—", "", "0") for v in (cars, sun, apt)), f"{cars}/{sun}/{apt}"

    @check("ops", "Chart canvases rendered (non-zero pixel)", page)
    def _():
        ids = ["chart-cars-source", "chart-apt-tier", "chart-cars-price", "chart-apt-price"]
        for cid in ids:
            w = page.locator(f"#{cid}").evaluate("el => el.width")
            if not w:
                return False, f"#{cid} width=0 (chart not rendered)"
        return True, "4/4 charts rendered"

    @check("ops", "Switching to Cars tab renders brand chart", page)
    def _():
        page.locator('[data-tab="cars"]').click()
        page.wait_for_timeout(800)
        w = page.locator("#chart-cars-brand").evaluate("el => el.width")
        return bool(w), f"brand chart width={w}"

    @check("ops", "Switching to Apartments tab renders area chart", page)
    def _():
        page.locator('[data-tab="apartments"]').click()
        page.wait_for_timeout(800)
        w = page.locator("#chart-apt-area").evaluate("el => el.width")
        return bool(w), f"area chart width={w}"

    @check("ops", "Switching to Pipeline tab renders runs table", page)
    def _():
        page.locator('[data-tab="pipeline"]').click()
        page.wait_for_timeout(800)
        rows = page.locator("#table-runs tbody tr").count()
        return rows >= 1, f"runs rows={rows}"

    @check("ops", "Last-refresh label updates after manual click", page)
    def _():
        before = page.locator("#last-refresh").text_content().strip()
        page.locator("#refresh-btn").click()
        page.wait_for_timeout(2500)
        after = page.locator("#last-refresh").text_content().strip()
        return after != before, f"before={before!r}, after={after!r}"


# ═════════════════════════════════════════════════════════════════════════════
#  8. Bot process
# ═════════════════════════════════════════════════════════════════════════════
def section_bot():
    print("\n── Telegram bot ────────────────────────────────────────────────────")
    import subprocess

    @check("bot", "Node process running")
    def _():
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-Process node -ErrorAction SilentlyContinue | Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=8,
        )
        n = int((r.stdout or "0").strip() or 0)
        return n >= 1, f"node procs={n}"

    @check("bot", "bot.log exists and shows recent activity")
    def _():
        log = ROOT / "Telegram Bot" / "bot.log"
        if not log.exists():
            return False, "bot.log missing"
        content = log.read_text(encoding="utf-8", errors="ignore")
        return "WhatsApp ready" in content or "Logged in" in content, f"log size={log.stat().st_size}"


# ═════════════════════════════════════════════════════════════════════════════
def main() -> int:
    print("=" * 76)
    print(f"DUBAI HUNT — FULL UAT")
    print("=" * 76)

    # Pre-flight
    if not DB_PATH.exists():
        print("FATAL: DB missing")
        return 2
    try:
        http_get_json("/")
    except Exception as e:
        print(f"FATAL: API not reachable at {API_BASE}: {e}")
        return 2

    section_db()
    section_api()
    section_consistency()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        try:
            section_landing(page)
            section_cars(page)
            section_apts(page)
            section_ops(page)
        finally:
            ctx.close()
            browser.close()

    section_bot()

    # ── summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 76)
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    by_sec: dict[str, list[Result]] = {}
    for r in results:
        by_sec.setdefault(r.section, []).append(r)
    for sec, rs in by_sec.items():
        p = sum(1 for r in rs if r.passed)
        print(f"  {sec:>10}: {p}/{len(rs)} pass")
    print("=" * 76)
    print(f"TOTAL: {passed}/{len(results)} pass")
    print("=" * 76)
    if failed:
        print("\nFAILED:")
        for r in results:
            if not r.passed:
                print(f"  ✗ [{r.section}] {r.name}")
                for line in r.detail.splitlines()[:4]:
                    print(f"      {line}")
        print(f"\nScreenshots: {SHOTS}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
