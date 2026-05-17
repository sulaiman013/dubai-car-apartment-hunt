"""
End-to-end UAT — Dubai Hunt on Hostinger VPS (31.97.71.84).

Runs every reasonable test against the LIVE deploy:
  • Playwright against each dashboard (cars, apartments, ops)
  • Exhaustive API contract tests (filters, sorts, error codes)
  • DB integrity via SSH (schema, indexes, scrape_runs)
  • Telegram bot health (getMe, OpenRouter, log scan)
  • Operational checks (services, restarts, disk, memory)
  • Security checks (sshd, perms, CORS, traversal)

Run:  python -X utf8 tests/uat_e2e.py
"""
from __future__ import annotations

import json
import os
import re
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen, Request

# Some corporate / Windows Python builds ship with broken root CAs that fail
# on api.telegram.org's chain. Use certifi if available; else fall back to a
# permissive context — we're only doing GET on public APIs.
try:
    import certifi  # type: ignore
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl._create_unverified_context()

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "tests" / "_screenshots_e2e"
SHOTS.mkdir(parents=True, exist_ok=True)

VPS_IP = "31.97.71.84"
BASE = f"http://{VPS_IP}"
SSH_KEY = os.path.expanduser("~/.ssh/oracle_dubai")

# ─── result plumbing ──────────────────────────────────────────────────────────
@dataclass
class Check:
    section: str
    name: str
    passed: bool
    detail: str = ""

results: list[Check] = []
_current_section = "init"

def section(name: str):
    global _current_section
    _current_section = name
    print(f"\n\033[1;36m▶ {name}\033[0m")

def record(name: str, passed: bool, detail: str = "") -> bool:
    results.append(Check(_current_section, name, passed, detail))
    icon = "\033[32m✓\033[0m" if passed else "\033[31m✗\033[0m"
    extra = f"  ({detail})" if detail and not passed else (f"  — {detail}" if detail else "")
    print(f"  {icon} {name}{extra}")
    return passed

# ─── HTTP helpers ─────────────────────────────────────────────────────────────
def http_get(path: str, headers: dict | None = None, timeout: int = 10):
    """Return (status, body_bytes, headers_dict). Never raises."""
    url = f"{BASE}{path}"
    req = Request(url, headers=headers or {})
    try:
        with urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.getheaders())
    except Exception as e:
        # urllib raises HTTPError for 4xx/5xx — catch and surface
        code = getattr(e, "code", 0)
        body = getattr(e, "read", lambda: b"")() if hasattr(e, "read") else b""
        hdrs = dict(getattr(e, "headers", {}).items()) if hasattr(e, "headers") else {}
        return code, body, hdrs

def http_json(path: str, **kwargs):
    code, body, hdrs = http_get(path, **kwargs)
    try:
        return code, json.loads(body or b"{}"), hdrs
    except Exception as e:
        return code, {"_parse_error": str(e), "_raw": body[:300].decode("utf-8", "replace")}, hdrs

# ─── SSH helper ───────────────────────────────────────────────────────────────
def ssh(cmd: str, timeout: int = 30) -> tuple[int, str]:
    """Run a shell command on the VPS, return (exit_code, combined_output)."""
    full = [
        "ssh", "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={min(timeout, 15)}",
        f"root@{VPS_IP}", cmd,
    ]
    try:
        r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return -1, "(ssh timeout)"

# ─── SECTION 1 — Public endpoints ─────────────────────────────────────────────
def test_public_endpoints():
    section("1. Public endpoint reachability")
    endpoints = [
        ("/", 200, 500),
        ("/Car%20Deals%20Frontend/", 200, 5000),
        ("/Car%20Deals%20Frontend/app.js", 200, 5000),
        ("/Car%20Deals%20Frontend/data.js", 200, 5000),
        ("/Car%20Deals%20Frontend/styles.css", 200, 1000),
        ("/Apartment%20Hunt%20Frontend/", 200, 5000),
        ("/Apartment%20Hunt%20Frontend/app.js", 200, 5000),
        ("/Apartment%20Hunt%20Frontend/data.js", 200, 1000),
        ("/Apartment%20Hunt%20Frontend/styles.css", 200, 1000),
        ("/Ops%20Dashboard/", 200, 5000),
        ("/Ops%20Dashboard/app.js", 200, 5000),
        ("/docs", 200, 500),
        ("/redoc", 200, 500),
        ("/openapi.json", 200, 1000),
        ("/api/health", 200, 10),
        ("/stats", 200, 100),
    ]
    for path, want_code, min_bytes in endpoints:
        code, body, _ = http_get(path)
        ok = code == want_code and len(body) >= min_bytes
        record(f"GET {path}", ok, f"HTTP {code}, {len(body)} bytes (want {want_code}, ≥{min_bytes})")

# ─── SECTION 2 — API contracts ────────────────────────────────────────────────
def test_api_contracts():
    section("2. API contracts (filters, sorts, error codes)")

    # /stats shape
    code, data, _ = http_json("/stats")
    record("/stats — 200 + JSON", code == 200 and isinstance(data, dict))
    record("/stats has 'cars'", "cars" in data)
    record("/stats has 'apartments'", "apartments" in data)
    record("/stats.cars.total > 0", data.get("cars", {}).get("total", 0) > 0)

    # /cars baseline
    code, data, _ = http_json("/cars?limit=10")
    record("/cars baseline 200", code == 200)
    record("/cars baseline count > 0", data.get("count", 0) > 0)
    record("/cars baseline results is list", isinstance(data.get("results"), list))
    if data.get("results"):
        r0 = data["results"][0]
        for field in ["ad_id", "title", "price_aed", "has_sunroof", "url"]:
            record(f"/cars result has '{field}'", field in r0)

    # /cars sunroof filter
    code, data, _ = http_json("/cars?has_sunroof=true&limit=20")
    all_sunroof = all(r.get("has_sunroof") for r in data.get("results", []))
    record("/cars?has_sunroof=true — all results have sunroof", all_sunroof and data.get("count", 0) > 0)

    # /cars price cap
    code, data, _ = http_json("/cars?max_price=15000&limit=50")
    all_capped = all((r.get("price_aed") or 0) <= 15000 for r in data.get("results", []))
    record("/cars?max_price=15000 — all ≤ 15K", all_capped)

    # /cars sort price_asc — first <= last
    code, data, _ = http_json("/cars?sort=price_asc&limit=20")
    prices = [r.get("price_aed") for r in data.get("results", []) if r.get("price_aed")]
    record("/cars?sort=price_asc — ascending", len(prices) >= 2 and prices == sorted(prices))

    # /cars sort price_desc
    code, data, _ = http_json("/cars?sort=price_desc&limit=20")
    prices = [r.get("price_aed") for r in data.get("results", []) if r.get("price_aed")]
    record("/cars?sort=price_desc — descending", len(prices) >= 2 and prices == sorted(prices, reverse=True))

    # /cars brand filter
    code, data, _ = http_json("/cars?brand=Honda&limit=20")
    all_honda = all("honda" in (r.get("brand") or "").lower() for r in data.get("results", []))
    record("/cars?brand=Honda — all match", all_honda and data.get("count", 0) > 0)

    # /cars limit clamp
    code, data, _ = http_json("/cars?limit=3")
    record("/cars?limit=3 — count ≤ 3", data.get("count", 999) <= 3)

    # /apartments baseline
    code, data, _ = http_json("/apartments?limit=20")
    record("/apartments baseline 200", code == 200)
    record("/apartments baseline count > 0", data.get("count", 0) > 0)
    apts = data.get("results", [])
    record("/apartments — all 1 BHK", all(r.get("bedrooms") == 1 for r in apts))
    record("/apartments — all furnished", all(r.get("furnished") for r in apts))
    record("/apartments — all tier 1-3", all(1 <= (r.get("commute_tier") or 99) <= 3 for r in apts))
    # No Sharjah, DSO, Discovery Gardens, International City
    forbidden = re.compile(r"sharjah|silicon oasis|discovery gardens|international city", re.I)
    leaks = [r for r in apts if forbidden.search(r.get("full_location", "") or r.get("area", ""))]
    record("/apartments — no rejected areas (Sharjah/DSO/etc.)", not leaks,
           f"{len(leaks)} leaks" if leaks else "")

    # /apartments monthly cap
    code, data, _ = http_json("/apartments?max_monthly=5000&limit=20")
    all_capped = all((r.get("monthly_aed") or 0) <= 5000 for r in data.get("results", []))
    record("/apartments?max_monthly=5000 — all ≤ 5K", all_capped)

    # /apartments tier cap
    code, data, _ = http_json("/apartments?max_tier=2&limit=20")
    all_tier = all((r.get("commute_tier") or 99) <= 2 for r in data.get("results", []))
    record("/apartments?max_tier=2 — all ≤ tier 2", all_tier)

    # Single-record fetches
    code, data, _ = http_json("/cars?limit=1")
    if data.get("results"):
        ad_id = data["results"][0]["ad_id"]
        code2, data2, _ = http_json(f"/cars/{quote(ad_id, safe='')}")
        record(f"/cars/{{ad_id}} — round-trip", code2 == 200 and data2.get("ad_id") == ad_id)

    code, data, _ = http_json("/apartments?limit=1")
    if data.get("results"):
        ad_id = data["results"][0]["ad_id"]
        code2, data2, _ = http_json(f"/apartments/{quote(ad_id, safe='')}")
        record(f"/apartments/{{ad_id}} — round-trip", code2 == 200 and data2.get("ad_id") == ad_id)

    # Error codes
    code, _, _ = http_get("/cars/this-id-does-not-exist-12345")
    record("/cars/<bad-id> → 404", code == 404)
    code, _, _ = http_get("/cars?max_price=abc")
    record("/cars?max_price=abc → 422", code == 422)
    code, _, _ = http_get("/cars?limit=99999")
    record("/cars?limit=99999 → 422 (over cap)", code == 422)

    # OpenAPI spec is valid JSON with paths
    code, data, _ = http_json("/openapi.json")
    record("/openapi.json — valid + has /cars", code == 200 and "/cars" in (data.get("paths") or {}))

# ─── SECTION 3 — Security ─────────────────────────────────────────────────────
def test_security():
    section("3. Security posture")

    # CORS — evil origin
    code, _, hdrs = http_get("/stats", headers={"Origin": "https://evil.example.com"})
    aco = hdrs.get("access-control-allow-origin", "")
    record("CORS — evil origin not reflected", aco != "*" and "evil" not in aco,
           f"got '{aco}'")

    # CORS — allowed origin
    code, _, hdrs = http_get("/stats", headers={"Origin": f"http://{VPS_IP}"})
    aco = hdrs.get("access-control-allow-origin", "")
    record("CORS — VPS origin reflected", aco == f"http://{VPS_IP}", f"got '{aco}'")

    # Path traversal
    code, _, _ = http_get("/../../../etc/passwd")
    record("Traversal /../../../etc/passwd → not 200", code != 200)

    # SSH password login from outside (we already verified once; re-confirm)
    cmd = [
        "ssh", "-i", "nonexistent",
        "-o", "PasswordAuthentication=yes",
        "-o", "PubkeyAuthentication=no",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        f"root@{VPS_IP}", "echo SHOULD_NOT_REACH",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    denied = "publickey" in (r.stderr or "").lower() and "SHOULD_NOT_REACH" not in (r.stdout or "")
    record("SSH password auth denied (publickey-only)", denied)

    # Effective sshd config — single shot, parse each line individually
    rc, out = ssh("sshd -T 2>/dev/null")
    cfg = {line.split()[0].lower(): line.split()[1] for line in out.splitlines()
           if line and len(line.split()) >= 2}
    record("sshd: passwordauthentication = no", cfg.get("passwordauthentication") == "no",
           f"got '{cfg.get('passwordauthentication')}'")
    record("sshd: kbdinteractiveauthentication = no", cfg.get("kbdinteractiveauthentication") == "no",
           f"got '{cfg.get('kbdinteractiveauthentication')}'")
    record("sshd: permitemptypasswords = no", cfg.get("permitemptypasswords") == "no",
           f"got '{cfg.get('permitemptypasswords')}'")

    # File perms
    rc, out = ssh('stat -c "%a" "/root/dubai-hunt/Telegram Bot/.env"')
    record(".env perms = 600", out.strip() == "600", f"got {out}")
    rc, out = ssh('stat -c "%a" /root/dubai-hunt/db/dubai_hunt.db')
    record("DB perms = 600", out.strip() == "600", f"got {out}")

    # fail2ban running
    rc, out = ssh("systemctl is-active fail2ban")
    record("fail2ban active", out.strip() == "active")

    rc, out = ssh("fail2ban-client status sshd 2>/dev/null | grep -c sshd || true")
    record("fail2ban sshd jail enabled", int(out.strip() or 0) > 0)

# ─── SECTION 4 — Operational health ───────────────────────────────────────────
def test_operations():
    section("4. Operational health")

    rc, out = ssh("systemctl is-active dubai-hunt-api")
    record("dubai-hunt-api active", out.strip() == "active")
    rc, out = ssh("systemctl is-active dubai-hunt-bot")
    record("dubai-hunt-bot active", out.strip() == "active")

    # Restarts since boot — should be very low after a clean deploy
    rc, out = ssh("systemctl show dubai-hunt-api -p NRestarts --value")
    record("api NRestarts ≤ 2", int(out.strip() or 99) <= 2, f"got {out}")
    rc, out = ssh("systemctl show dubai-hunt-bot -p NRestarts --value")
    record("bot NRestarts ≤ 2", int(out.strip() or 99) <= 2, f"got {out}")

    # No errors in journal in last 5 min
    rc, out = ssh("journalctl -u dubai-hunt-api --since '5 min ago' -p err --no-pager 2>&1 | grep -v '^-- ' | head -1")
    record("api: no error-level logs (5m)", not out.strip(), out[:80])
    rc, out = ssh("journalctl -u dubai-hunt-bot --since '5 min ago' -p err --no-pager 2>&1 | grep -v '^-- ' | head -1")
    record("bot: no error-level logs (5m)", not out.strip(), out[:80])

    # Cron present
    rc, out = ssh("crontab -l 2>/dev/null | grep -c dubai-hunt")
    record("cron: 2 dubai-hunt entries", out.strip() == "2", f"got {out}")

    # Disk usage
    rc, out = ssh("df -h / | awk 'NR==2{print $5}' | tr -d %")
    try:
        usage = int(out.strip())
        record(f"disk usage < 80% (now {usage}%)", usage < 80)
    except Exception:
        record("disk usage parseable", False, out)

    # Memory
    rc, out = ssh("free -m | awk 'NR==2{printf \"%d\", $3*100/$2}'")
    try:
        usage = int(out.strip())
        record(f"memory usage < 80% (now {usage}%)", usage < 80)
    except Exception:
        record("memory usage parseable", False, out)

    # uname / kernel matches
    rc, out = ssh("uname -r")
    record("kernel reachable", bool(out.strip()), out[:50])

# ─── SECTION 5 — Database integrity ───────────────────────────────────────────
def test_db_integrity():
    section("5. Database integrity")

    DB = "/root/dubai-hunt/db/dubai_hunt.db"

    # pragma integrity
    rc, out = ssh(f"sqlite3 {DB} 'PRAGMA integrity_check;'")
    record("PRAGMA integrity_check = ok", out.strip() == "ok", out[:80])

    # tables
    rc, out = ssh(f"sqlite3 {DB} \".tables\"")
    tables = out.split()
    for t in ("cars", "apartments", "scrape_runs"):
        record(f"table '{t}' exists", t in tables)

    # counts
    for sql, label, expect_gt in [
        ("SELECT COUNT(*) FROM cars WHERE is_active=1", "cars active", 50),
        ("SELECT COUNT(*) FROM cars WHERE has_sunroof=1", "cars sunroof", 5),
        ("SELECT COUNT(*) FROM apartments WHERE is_active=1", "apartments active", 5),
    ]:
        rc, out = ssh(f"sqlite3 {DB} \"{sql}\"")
        try:
            n = int(out.strip())
            record(f"{label} > {expect_gt}", n > expect_gt, f"n={n}")
        except Exception:
            record(label, False, out)

    # Indexes exist on key columns
    rc, out = ssh(f"sqlite3 {DB} \"SELECT name FROM sqlite_master WHERE type='index'\"")
    indexes = out.split()
    record("at least 3 indexes defined", len(indexes) >= 3, f"got {len(indexes)}")

    # No rows with NULL ad_id (primary key)
    rc, out = ssh(f"sqlite3 {DB} \"SELECT COUNT(*) FROM cars WHERE ad_id IS NULL OR ad_id=''\"")
    record("cars: no empty ad_id", out.strip() == "0", f"got {out}")
    rc, out = ssh(f"sqlite3 {DB} \"SELECT COUNT(*) FROM apartments WHERE ad_id IS NULL OR ad_id=''\"")
    record("apartments: no empty ad_id", out.strip() == "0", f"got {out}")

# ─── SECTION 6 — Telegram bot health ──────────────────────────────────────────
def test_bot_health():
    section("6. Telegram bot health")

    # Read token from VPS (it's chmod 600 root-only; this works because we ssh as root)
    rc, token = ssh("grep '^TELEGRAM_TOKEN' '/root/dubai-hunt/Telegram Bot/.env' | cut -d= -f2")
    token = token.strip()
    record("TELEGRAM_TOKEN readable on VPS", bool(token) and len(token) > 20)

    if not token:
        return

    # getMe
    req = Request(f"https://api.telegram.org/bot{token}/getMe")
    try:
        with urlopen(req, timeout=10, context=_SSL_CTX) as r:
            data = json.loads(r.read())
        record("Telegram getMe ok=true", data.get("ok") is True)
        record("Bot username = @Dubai_013_bot", data.get("result", {}).get("username") == "Dubai_013_bot")
        record("Bot is_bot=true", data.get("result", {}).get("is_bot") is True)
    except Exception as e:
        record("Telegram getMe", False, str(e))

    # OpenRouter key validity (cheap models endpoint)
    rc, key = ssh("grep '^OPENROUTER_API_KEY' '/root/dubai-hunt/Telegram Bot/.env' | cut -d= -f2")
    key = key.strip()
    record("OPENROUTER_API_KEY readable", bool(key))

    if key:
        req = Request("https://openrouter.ai/api/v1/auth/key",
                      headers={"Authorization": f"Bearer {key}"})
        try:
            with urlopen(req, timeout=10, context=_SSL_CTX) as r:
                data = json.loads(r.read())
            record("OpenRouter key valid", "data" in data or "label" in data or "usage" in (data.get("data") or {}),
                   json.dumps(data)[:120])
        except Exception as e:
            record("OpenRouter key valid", False, str(e)[:120])

    # Bot process consuming updates — check logs for recent getUpdates pulls
    rc, out = ssh("journalctl -u dubai-hunt-bot --since '5 min ago' --no-pager 2>&1 | wc -l")
    record("Bot journal has activity in last 5 min", int(out.strip() or 0) > 0, f"lines={out.strip()}")

    # Check bot.log for errors (file-based log from systemd unit)
    rc, out = ssh("tail -200 '/root/dubai-hunt/Telegram Bot/bot.log' 2>/dev/null | grep -iE 'error|exception|409 conflict' | wc -l")
    record("Bot file-log has 0 recent errors", out.strip() == "0", f"errors={out}")

    # No 409 conflict (two bot instances)
    rc, out = ssh("journalctl -u dubai-hunt-bot --since '10 min ago' --no-pager 2>&1 | grep -c 'Conflict'")
    record("No 409 Conflict (single bot instance)", out.strip() == "0", f"conflicts={out}")

# ─── SECTION 7 — Playwright browser UAT ───────────────────────────────────────
def test_browser():
    section("7. Playwright — live dashboards in real browser")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        record("Playwright not installed", False, "pip install playwright && python -m playwright install chromium")
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})

        # ── CARS DASHBOARD ──
        page = ctx.new_page()
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        failed_requests = []
        page.on("requestfailed", lambda r: failed_requests.append(r.url))

        try:
            page.goto(f"{BASE}/Car%20Deals%20Frontend/", wait_until="networkidle", timeout=20000)
            record("Cars: page loaded", True)

            title = page.title()
            record(f"Cars: title set ('{title}')", bool(title) and len(title) > 5)

            # Count rendered rows/cards
            page.wait_for_selector(".row, .card, [data-id]", timeout=10000)
            n_rows = page.locator(".row, .card, [data-id]").count()
            record(f"Cars: ≥10 listings rendered (got {n_rows})", n_rows >= 10)

            # window.CAR_DATA populated
            n_data = page.evaluate("window.CAR_DATA?.length || 0")
            record(f"Cars: window.CAR_DATA has rows (got {n_data})", n_data > 50)

            # Stats badge / count visible
            body_text = page.inner_text("body").lower()
            record("Cars: 'sunroof' word present", "sunroof" in body_text)
            record("Cars: 'aed' word present", "aed" in body_text)

            # No console errors
            record("Cars: no JS console errors", len(console_errors) == 0,
                   f"{len(console_errors)} errors: {console_errors[:2]}")
            record("Cars: no failed requests", len(failed_requests) == 0,
                   f"{len(failed_requests)} failed: {failed_requests[:2]}")

            page.screenshot(path=str(SHOTS / "cars_live.png"), full_page=False)
        except Exception as e:
            record("Cars: page loaded", False, str(e)[:150])
            page.screenshot(path=str(SHOTS / "cars_FAIL.png"))
        finally:
            page.close()

        # ── APARTMENTS DASHBOARD ──
        page = ctx.new_page()
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        failed_requests = []
        page.on("requestfailed", lambda r: failed_requests.append(r.url))

        try:
            page.goto(f"{BASE}/Apartment%20Hunt%20Frontend/", wait_until="networkidle", timeout=20000)
            record("Apts: page loaded", True)
            title = page.title()
            record(f"Apts: title set ('{title}')", bool(title))

            page.wait_for_selector(".row, .card, [data-id]", timeout=10000)
            n_rows = page.locator(".row, .card, [data-id]").count()
            record(f"Apts: ≥5 listings rendered (got {n_rows})", n_rows >= 5)

            n_data = page.evaluate("window.APT_DATA?.length || 0")
            record(f"Apts: window.APT_DATA has rows (got {n_data})", n_data >= 5)

            body_text = page.inner_text("body").lower()
            record("Apts: 'dafza' or 'tier' present", "dafza" in body_text or "tier" in body_text)
            record("Apts: 'aed' word present", "aed" in body_text)

            # No rejected-area leakage in DOM
            for bad in ("sharjah", "silicon oasis", "international city", "discovery gardens"):
                record(f"Apts: '{bad}' not in DOM", bad not in body_text)

            record("Apts: no JS console errors", len(console_errors) == 0,
                   f"{len(console_errors)} errors: {console_errors[:2]}")
            record("Apts: no failed requests", len(failed_requests) == 0,
                   f"{len(failed_requests)} failed: {failed_requests[:2]}")

            page.screenshot(path=str(SHOTS / "apts_live.png"), full_page=False)
        except Exception as e:
            record("Apts: page loaded", False, str(e)[:150])
            page.screenshot(path=str(SHOTS / "apts_FAIL.png"))
        finally:
            page.close()

        # ── OPS DASHBOARD ──
        page = ctx.new_page()
        console_errors = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        failed_requests = []
        page.on("requestfailed", lambda r: failed_requests.append(r.url))

        try:
            page.goto(f"{BASE}/Ops%20Dashboard/", wait_until="networkidle", timeout=20000)
            record("Ops: page loaded", True)
            body_text = page.inner_text("body").lower()
            # Should contain a number for cars or a chart/canvas
            has_canvas = page.locator("canvas").count() > 0
            has_numbers = any(c.isdigit() for c in body_text)
            record("Ops: chart canvas or numeric content", has_canvas or has_numbers,
                   f"canvas={has_canvas} digits={has_numbers}")
            record("Ops: no JS console errors", len(console_errors) == 0,
                   f"{len(console_errors)} errors: {console_errors[:2]}")
            record("Ops: no failed requests", len(failed_requests) == 0,
                   f"{len(failed_requests)} failed: {failed_requests[:2]}")
            page.screenshot(path=str(SHOTS / "ops_live.png"), full_page=False)
        except Exception as e:
            record("Ops: page loaded", False, str(e)[:150])
            page.screenshot(path=str(SHOTS / "ops_FAIL.png"))
        finally:
            page.close()

        ctx.close()
        browser.close()

# ─── runner ───────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    print(f"\n\033[1mE2E UAT — Dubai Hunt @ {BASE}\033[0m")
    print(f"SSH key: {SSH_KEY}")

    test_public_endpoints()
    test_api_contracts()
    test_security()
    test_operations()
    test_db_integrity()
    test_bot_health()
    test_browser()

    # ─── final summary ─────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    by_section: dict[str, list[Check]] = {}
    for r in results:
        by_section.setdefault(r.section, []).append(r)
    for sec, items in by_section.items():
        ok = sum(1 for i in items if i.passed)
        n = len(items)
        bar = "✓" if ok == n else ("⚠" if ok > n // 2 else "✗")
        color = "\033[32m" if ok == n else ("\033[33m" if ok > n // 2 else "\033[31m")
        print(f"  {color}{bar}\033[0m  {sec:<45}  {ok}/{n}")

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    print("=" * 70)
    print(f"  TOTAL: {passed}/{total} passed   ({(passed/total*100):.0f}%)   in {time.time()-t0:.1f}s")
    print("=" * 70)

    if passed < total:
        print("\nFailures:")
        for r in results:
            if not r.passed:
                print(f"  ✗ [{r.section}] {r.name}  {r.detail}")

    sys.exit(0 if passed == total else 1)

if __name__ == "__main__":
    main()
