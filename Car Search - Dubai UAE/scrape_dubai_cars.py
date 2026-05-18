"""
Dubai/UAE Car Deal Scraper — Multi-source.

Targets:  26 models (Hyundai/Honda/Toyota/Nissan/Kia/Suzuki/Mazda/Mitsubishi/Chevrolet).
Sources:  Dubizzle UAE, DubiCars, CarSwitch, YallaMotor UAE.
Output:   dubai_cars.json + dubai_cars.csv
Sunroof:  detected from title + description + feature lists; saved as a boolean.

Anti-bot: Patchright with `headless=False` + window positioned at (-2400,-2400).
The browser is real (bypasses fingerprinting) but lives off-screen so daily
scheduled runs are invisible to the user.

Schedule: Daily at 18:00 Bangladesh time (= 16:00 Dubai).
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Iterable, Optional

# Patchright = drop-in stealth Playwright. Crucial for Dubizzle/Bayut bot walls.
from patchright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# ─── config ────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(HERE, "dubai_cars.json")
DATA_CSV = os.path.join(HERE, "dubai_cars.csv")
LOG_FILE = os.path.join(HERE, "scrape_log.txt")

MAX_PRICE_AED = int(os.environ.get("MAX_PRICE_AED", "25000"))   # listing cap
USD_TO_AED = 3.6725                                              # DubiCars schema quirk
DETAIL_FETCH_DELAY_S = 2.5    # throttle between Dubizzle detail-page fetches
DETAIL_FETCH_CAP = 18         # max detail fetches per model per run
PRIOR_DATA: dict[str, dict] = {}   # ad_id → previous listing dict (populated in main)

# Bot-wall circuit breaker. When Dubizzle returns its 'Pardon Our Interruption'
# page 3 models in a row, stop attempting Dubizzle for the rest of the run so
# we don't waste 25 min looping on bot-walled URLs. DubiCars takes over.
DUBIZZLE_CONSECUTIVE_FAILS = 0
DUBIZZLE_DISABLED = False
DUBIZZLE_CIRCUIT_BREAK = 3

TARGETS = [
    # (canonical brand, dubizzle slug, yallamotor slug, dubicars slug)
    # ── Original 6 ─────────────────────────────────────────────────────────────
    ("Hyundai Elantra",     ("hyundai",    "elantra"),     ("hyundai",    "elantra"),     ("hyundai",    "elantra")),
    ("Honda Civic",         ("honda",      "civic"),       ("honda",      "civic"),       ("honda",      "civic")),
    ("Nissan Sunny",        ("nissan",     "sunny"),       ("nissan",     "sunny"),       ("nissan",     "sunny")),
    ("Toyota Corolla",      ("toyota",     "corolla"),     ("toyota",     "corolla"),     ("toyota",     "corolla")),
    ("Toyota Yaris",        ("toyota",     "yaris"),       ("toyota",     "yaris"),       ("toyota",     "yaris")),
    ("Toyota Camry",        ("toyota",     "camry"),       ("toyota",     "camry"),       ("toyota",     "camry")),
    # ── Expanded: reliable + fuel-efficient + good-looking picks for Dubai ─────
    ("Toyota Avalon",       ("toyota",     "avalon"),      ("toyota",     "avalon"),      ("toyota",     "avalon")),
    ("Toyota Prius",        ("toyota",     "prius"),       ("toyota",     "prius"),       ("toyota",     "prius")),
    ("Honda Accord",        ("honda",      "accord"),      ("honda",      "accord"),      ("honda",      "accord")),
    ("Honda City",          ("honda",      "city"),        ("honda",      "city"),        ("honda",      "city")),
    ("Honda Jazz",          ("honda",      "jazz"),        ("honda",      "jazz"),        ("honda",      "jazz")),
    ("Hyundai Accent",      ("hyundai",    "accent"),      ("hyundai",    "accent"),      ("hyundai",    "accent")),
    ("Hyundai Sonata",      ("hyundai",    "sonata"),      ("hyundai",    "sonata"),      ("hyundai",    "sonata")),
    ("Hyundai Creta",       ("hyundai",    "creta"),       ("hyundai",    "creta"),       ("hyundai",    "creta")),
    ("Kia Cerato",          ("kia",        "cerato"),      ("kia",        "cerato"),      ("kia",        "cerato")),
    ("Kia Picanto",         ("kia",        "picanto"),     ("kia",        "picanto"),     ("kia",        "picanto")),
    ("Kia Rio",             ("kia",        "rio"),         ("kia",        "rio"),         ("kia",        "rio")),
    ("Suzuki Alto",         ("suzuki",     "alto"),        ("suzuki",     "alto"),        ("suzuki",     "alto")),
    ("Suzuki Swift",        ("suzuki",     "swift"),       ("suzuki",     "swift"),       ("suzuki",     "swift")),
    ("Suzuki Baleno",       ("suzuki",     "baleno"),      ("suzuki",     "baleno"),      ("suzuki",     "baleno")),
    ("Suzuki Ciaz",         ("suzuki",     "ciaz"),        ("suzuki",     "ciaz"),        ("suzuki",     "ciaz")),
    ("Suzuki Dzire",        ("suzuki",     "dzire"),       ("suzuki",     "dzire"),       ("suzuki",     "dzire")),
    ("Maruti Alto",         ("maruti",     "alto"),        ("maruti",     "alto"),        ("maruti",     "alto")),
    ("Mazda 3",             ("mazda",      "3"),           ("mazda",      "3"),           ("mazda",      "3")),
    ("Mazda 6",             ("mazda",      "6"),           ("mazda",      "6"),           ("mazda",      "6")),
    ("Mitsubishi Lancer EX",("mitsubishi", "lancer-ex"),   ("mitsubishi", "lancer-ex"),   ("mitsubishi", "lancer-ex")),
    ("Mitsubishi Attrage",  ("mitsubishi", "attrage"),     ("mitsubishi", "attrage"),     ("mitsubishi", "attrage")),
    ("Chevrolet Aveo",      ("chevrolet",  "aveo"),        ("chevrolet",  "aveo"),        ("chevrolet",  "aveo")),
]

SUNROOF_PATTERNS = re.compile(
    r"\b(sun[\s\-]?roof|moon[\s\-]?roof|panoramic[\s\-]?roof|panoramic[\s\-]?sunroof)\b",
    re.IGNORECASE,
)

# ─── logging ───────────────────────────────────────────────────────────────────
def log(msg: str = "") -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}" if msg else ""
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ─── unified record ────────────────────────────────────────────────────────────
@dataclass
class Listing:
    source: str
    brand: str
    title: str
    price_aed: int
    year: Optional[int]
    km: Optional[int]
    transmission: str
    trim: str
    location: str
    color: str
    body_type: str
    fuel: str
    seller_type: str
    has_sunroof: bool
    features: list[str] = field(default_factory=list)
    description: str = ""
    image: str = ""
    url: str = ""
    scraped_at: str = ""
    ad_id: str = ""
    listed_at: str = ""   # ISO date (yyyy-mm-dd) of when seller posted; "" if source doesn't expose it

    def csv_row(self) -> dict:
        d = asdict(self)
        d["features"] = " | ".join(self.features) if self.features else ""
        return d


# ─── helpers ───────────────────────────────────────────────────────────────────
def _has_sunroof(*texts: str | None) -> bool:
    blob = " ".join(t for t in texts if t)
    return bool(SUNROOF_PATTERNS.search(blob))


def _is_dubai(location: str | None) -> bool:
    """True iff the listing's location starts with (UAE >) Dubai > ...

    Accepts breadcrumb formats produced by Dubizzle ('UAE > Dubai > ...') and
    plain strings used by DubiCars ('Dubai') / YallaMotor ('Dubai').
    """
    if not location:
        return False
    parts = [p.strip() for p in str(location).split(">") if p.strip()]
    if not parts:
        return False
    if parts[0].upper() == "UAE":
        parts = parts[1:]
    return bool(parts) and parts[0].strip().lower() == "dubai"


def _coerce_int(v) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = re.sub(r"[^\d]", "", str(v))
    return int(s) if s else None


def _new_browser_context(pw):
    """Patchright in 'invisible headed' mode: real browser fingerprint, window
    placed off-screen so daily runs don't pop a window in your face.
    Headless mode is fingerprintable by 2026 bot walls; this bypasses Dubizzle's."""
    browser = pw.chromium.launch(
        headless=False,
        channel="chromium",
        args=[
            "--window-position=-2400,-2400",
            "--window-size=1920,1080",
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
    )
    return browser, ctx


def _safe_goto(page, url: str, wait: str = "load", timeout: int = 45000) -> bool:
    try:
        page.goto(url, wait_until=wait, timeout=timeout)
        page.wait_for_timeout(3500)  # let JS settle
        return True
    except PWTimeoutError:
        log(f"  timeout: {url}")
        return False
    except Exception as e:
        log(f"  err {type(e).__name__}: {url} - {e}")
        return False


def _is_page_broken(page) -> bool:
    """A Chromium tab that hit ERR_CONNECTION_CLOSED gets stuck on chrome-error://;
    subsequent goto's interrupt themselves. Detect and recover by recycling."""
    try:
        return str(page.url or "").startswith("chrome-error://")
    except Exception:
        return True


def _recycle_page(ctx, page):
    """Close a poisoned page and return a fresh one in the same context."""
    try:
        page.close()
    except Exception:
        pass
    new_page = ctx.new_page()
    log("  (recycled browser page after fatal error)")
    return new_page


def _year_from_title(title: str) -> int | None:
    """Pull a plausible model year (1995-2027) out of a free-text title."""
    if not title:
        return None
    matches = re.findall(r"\b(19[9]\d|20[0-2]\d)\b", title)
    if matches:
        # When multiple years appear, prefer the older one (it's usually the model year).
        years = [int(m) for m in matches]
        return min(years)
    return None


def _km_from_title(title: str) -> int | None:
    """Pull km out of titles like '177k KM', '125,000 km', '90000 km'."""
    if not title:
        return None
    # '177k KM' / '180k KM'
    m = re.search(r"(\d{2,3})\s*k\s*km", title, re.I)
    if m:
        return int(m.group(1)) * 1000
    # '125,000 km' or '125000 km'
    m = re.search(r"(\d{2,3}(?:[,. ]?\d{3}))\s*km\b", title, re.I)
    if m:
        return int(re.sub(r"[,. ]", "", m.group(1)))
    return None


def _dubizzle_detail_features(page, url: str) -> tuple[list[str], str, bool, dict]:
    """Fetch a Dubizzle detail page; return (features, description, sunroof_in_html, extra).

    extra is a dict potentially containing 'year', 'km', 'transmission',
    'seller_type', 'trim', 'color', 'body_type', 'fuel' parsed from the
    structured payload on the detail page (which still carries them even
    though the search-list response no longer does).

    Best-effort; never raises.
    """
    if not url or not _safe_goto(page, url, timeout=20000):
        return [], "", False, {}
    html = page.content()

    # Raw-HTML fallback: if 'sunroof' appears anywhere in the rendered DOM,
    # trust it. Works even when bot walls block the structured payload, as
    # long as some body text leaks through.
    sunroof_in_html = bool(SUNROOF_PATTERNS.search(html)) if len(html) > 2000 else False

    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        return [], "", sunroof_in_html, {}
    try:
        data = json.loads(m.group(1))
    except Exception:
        return [], "", sunroof_in_html, {}

    feats: list[str] = []
    description = ""
    extra: dict = {}

    feature_sections = (
        "Comfort & Convenience",
        "Driver Assistance & Safety",
        "Entertainment & Technology",
        "Exterior",
    )
    # detail-page field -> our extra key
    primitive_fields = {
        "Year": "year",
        "Kilometers": "km",
        "Transmission Type": "transmission",
        "Seller type": "seller_type",
        "Seller Type": "seller_type",
        "Trim": "trim",
        "Motors Trim": "trim",
        "Exterior Color": "color",
        "Body Type": "body_type",
        "Fuel Type": "fuel",
    }

    def walk(obj):
        nonlocal description
        if isinstance(obj, dict):
            # description (could be {"en": "..."} or plain str)
            if not description:
                desc = obj.get("description")
                if isinstance(desc, dict):
                    description = desc.get("en") or desc.get("ar") or ""
                elif isinstance(desc, str) and len(desc) > 20:
                    description = desc
            # feature sections inside a details map
            det = obj.get("details")
            if isinstance(det, dict):
                for sec in feature_sections:
                    v = (det.get(sec, {}) or {}).get("en", {})
                    if isinstance(v, dict):
                        val = v.get("value")
                        if isinstance(val, list):
                            feats.extend(str(x) for x in val)
                        elif isinstance(val, str) and val:
                            feats.append(val)
                # primitive fields (year, km, etc.)
                for src_key, dst_key in primitive_fields.items():
                    if dst_key in extra and extra[dst_key]:
                        continue
                    v = (det.get(src_key, {}) or {}).get("en", {})
                    if isinstance(v, dict):
                        val = v.get("value")
                        if val not in (None, "", []):
                            extra[dst_key] = val
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(data.get("props", {}).get("pageProps", {}))
    # de-dupe while preserving order
    seen: set[str] = set()
    unique = []
    for f in feats:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique, description.strip()[:600], sunroof_in_html, extra


# ─── source: Dubizzle ──────────────────────────────────────────────────────────
def scrape_dubizzle(page, brand_label: str, mk: str, mdl: str) -> list[Listing]:
    global DUBIZZLE_CONSECUTIVE_FAILS, DUBIZZLE_DISABLED
    out: list[Listing] = []
    if DUBIZZLE_DISABLED:
        log(f"  Dubizzle: SKIPPED (circuit breaker tripped earlier this run)")
        return out

    url = f"https://uae.dubizzle.com/motors/used-cars/{mk}/{mdl}/?price__lte={MAX_PRICE_AED}"
    log(f"  Dubizzle: {url}")

    # Retry on bot-wall response (HTML is ~1KB "Pardon Our Interruption").
    html = ""
    for attempt in range(2):   # was 3 retries; tightened to fail-fast → save time
        if not _safe_goto(page, url):
            DUBIZZLE_CONSECUTIVE_FAILS += 1
            if DUBIZZLE_CONSECUTIVE_FAILS >= DUBIZZLE_CIRCUIT_BREAK:
                DUBIZZLE_DISABLED = True
                log(f"  Dubizzle: CIRCUIT BREAKER tripped after {DUBIZZLE_CONSECUTIVE_FAILS} consecutive fails — disabling for the rest of this run")
            return out
        html = page.content()
        if len(html) > 50_000 and "__NEXT_DATA__" in html:
            break
        wait = 8 * (attempt + 1)  # 8s, 16s (was 12+24+36)
        log(f"  Dubizzle: looks like bot wall (len={len(html)}) — backing off {wait}s")
        time.sleep(wait)
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        log("  Dubizzle: no __NEXT_DATA__ after retries")
        DUBIZZLE_CONSECUTIVE_FAILS += 1
        if DUBIZZLE_CONSECUTIVE_FAILS >= DUBIZZLE_CIRCUIT_BREAK:
            DUBIZZLE_DISABLED = True
            log(f"  Dubizzle: CIRCUIT BREAKER tripped after {DUBIZZLE_CONSECUTIVE_FAILS} consecutive fails — disabling for the rest of this run")
        return out

    DUBIZZLE_CONSECUTIVE_FAILS = 0  # reset on success
    try:
        data = json.loads(m.group(1))
    except Exception as e:
        log(f"  Dubizzle: JSON parse failed: {e}")
        return out

    hits = []
    for act in data.get("props", {}).get("pageProps", {}).get("reduxWrapperActionsGIPP", []):
        payload = act.get("payload", {}) if isinstance(act, dict) else {}
        if isinstance(payload, dict) and isinstance(payload.get("hits"), list):
            hits = payload["hits"]
            break

    # Collect candidate listings (lightweight pass), then enrich each with a
    # detail-page fetch for features+description.
    candidates: list[dict] = []
    kept_non_dubai = 0
    for h in hits:
        try:
            price = _coerce_int(h.get("price")) or 0
            if price <= 0 or price > MAX_PRICE_AED:
                continue
            # Garbage filter: dealer placeholder ads use price=1 with km=1 and year=current.
            # Real used cars under AED 5K are vanishingly rare; treat as data pollution.
            if price < 5000:
                continue

            # Dubai-only filter (location_list is the source of truth for Dubizzle)
            loc_parts = (h.get("location_list") or {}).get("en", []) or []
            if not (len(loc_parts) > 1 and str(loc_parts[1]).strip().lower() == "dubai"):
                kept_non_dubai += 1
                continue

            name = (h.get("name") or {}).get("en") or ""
            details = h.get("details") or {}

            def detail(field_name: str):
                f = details.get(field_name, {}).get("en", {})
                return f.get("value")

            year = _coerce_int(detail("Year"))
            km = _coerce_int(detail("Kilometers"))
            trans = str(detail("Transmission Type") or "")
            trim = str(detail("Trim") or detail("Motors Trim") or "")
            color = str(detail("Exterior Color") or "")
            body_type = str(detail("Body Type") or "")
            fuel = str(detail("Fuel Type") or "")
            seller_type = str(detail("Seller Type") or detail("Seller type") or "")

            feats: list[str] = []
            for sec in ("Comfort & Convenience", "Driver Assistance & Safety", "Entertainment & Technology", "Exterior"):
                v = (details.get(sec, {}).get("en", {}) or {}).get("value")
                if isinstance(v, list):
                    feats.extend(str(x) for x in v)
                elif isinstance(v, str):
                    feats.append(v)

            location = " > ".join((h.get("location_list") or {}).get("en", []))
            absolute = (h.get("absolute_url") or {}).get("en") or ""
            image = ""
            ph = h.get("photo_thumbnails") or []
            if isinstance(ph, list) and ph:
                image = ph[0]

            sunroof = _has_sunroof(name, " ".join(feats))

            # Extract Dubizzle's posted-date from the `added` Unix timestamp.
            # Falls back to `created_at` if `added` is missing.
            listed_iso = ""
            ts = _coerce_int(h.get("added")) or _coerce_int(h.get("created_at"))
            if ts:
                try:
                    listed_iso = datetime.fromtimestamp(ts).date().isoformat()
                except Exception:
                    listed_iso = ""

            candidates.append({
                "_h": h,  # keep raw for late mutations
                "name": name, "price": price, "year": year, "km": km,
                "trans": trans, "trim": trim, "color": color,
                "body_type": body_type, "fuel": fuel, "seller_type": seller_type,
                "location": location, "absolute": absolute, "image": image,
                "feats": feats, "sunroof": sunroof,
                "listed_at": listed_iso,
            })
        except Exception as e:
            log(f"  Dubizzle: row error: {e}")
            continue

    # ─── Detail-page enrichment ──────────────────────────────────────────────
    # As of May 2026 Dubizzle dropped feature sections from the search payload;
    # they are only on the per-listing detail page. Fetch each candidate's
    # detail page to recover features + description (and thereby sunroof flag).
    enriched_sun = 0
    detail_fetches = 0
    cache_hits = 0
    for cand in candidates:
        feats = cand["feats"]
        desc = ""
        sunroof_html = False
        extra: dict = {}
        h = cand["_h"]
        ad_id = f"dubizzle_{h.get('uuid') or h.get('id') or ''}"

        # Cache: if we already enriched this listing in a previous run, reuse it.
        prior = PRIOR_DATA.get(ad_id)
        if prior and (prior.get("features") or prior.get("description")):
            feats = feats or prior.get("features") or []
            desc = prior.get("description") or ""
            # Reuse prior fields too (year/km/transmission/etc. only on detail page).
            for k in ("year", "km", "transmission", "seller_type", "trim", "color", "body_type", "fuel"):
                if prior.get(k):
                    extra[k] = prior[k]
            cache_hits += 1
        elif cand["absolute"] and detail_fetches < DETAIL_FETCH_CAP and not (cand["year"] and feats):
            try:
                more_feats, more_desc, sunroof_html, more_extra = _dubizzle_detail_features(page, cand["absolute"])
            except Exception as e:
                more_feats, more_desc, sunroof_html, more_extra = [], "", False, {}
                log(f"  Dubizzle: detail fetch failed for {cand['absolute']}: {e}")
            if more_feats:
                feats = more_feats
            if more_desc:
                desc = more_desc
            extra.update(more_extra)
            detail_fetches += 1
            time.sleep(DETAIL_FETCH_DELAY_S)

        # Final field assembly: prefer detail-page values, then candidate values,
        # then title-derived fallbacks.
        year_final = (
            extra.get("year")
            or cand["year"]
            or _year_from_title(cand["name"])
        )
        if year_final is not None:
            try: year_final = int(year_final)
            except Exception: pass
        km_final = extra.get("km") or cand["km"] or _km_from_title(cand["name"])
        if km_final is not None:
            try: km_final = int(km_final)
            except Exception: pass
        trans_final = extra.get("transmission") or cand["trans"]
        trim_final = extra.get("trim") or cand["trim"]
        color_final = extra.get("color") or cand["color"]
        body_final = extra.get("body_type") or cand["body_type"]
        fuel_final = extra.get("fuel") or cand["fuel"]
        seller_final = extra.get("seller_type") or cand["seller_type"]

        sunroof = _has_sunroof(cand["name"], " ".join(feats), desc) or sunroof_html
        if sunroof and not cand["sunroof"]:
            enriched_sun += 1

        h = cand["_h"]
        out.append(
            Listing(
                source="Dubizzle",
                brand=brand_label,
                title=cand["name"],
                price_aed=cand["price"],
                year=year_final,
                km=km_final,
                transmission=str(trans_final or ""),
                trim=str(trim_final or ""),
                location=cand["location"],
                color=str(color_final or ""),
                body_type=str(body_final or ""),
                fuel=str(fuel_final or ""),
                seller_type=str(seller_final or ""),
                has_sunroof=sunroof,
                features=feats,
                description=desc,
                image=cand["image"],
                url=cand["absolute"],
                scraped_at=datetime.now().isoformat(timespec="seconds"),
                ad_id=f"dubizzle_{h.get('uuid') or h.get('id') or ''}",
                listed_at=cand.get("listed_at", ""),
            )
        )

    log(f"  Dubizzle: kept {len(out)} Dubai listings (dropped {kept_non_dubai} non-Dubai of {len(hits)}; "
        f"cache hits={cache_hits}, detail fetches={detail_fetches}, +{enriched_sun} sunroofs from enrichment)")
    return out


# ─── source: YallaMotor ────────────────────────────────────────────────────────
def scrape_yallamotor(page, brand_label: str, mk: str, mdl: str) -> list[Listing]:
    out: list[Listing] = []
    url = f"https://uae.yallamotor.com/used-cars/{mk}/{mdl}"
    log(f"  YallaMotor: {url}")
    if not _safe_goto(page, url, timeout=60000):
        return out

    html = page.content()
    items = []
    for sc in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    ):
        try:
            data = json.loads(sc.group(1))
            if data.get("@type") == "ItemList":
                items = data.get("itemListElement", [])
                break
        except Exception:
            continue
    if not items:
        log("  YallaMotor: no ItemList JSON-LD")
        return out

    # Walk each item; fetch detail page for full Car schema.
    for it in items[:25]:  # cap per model per source
        item_url = it.get("url", "")
        if not item_url:
            continue
        if not _safe_goto(page, item_url, timeout=25000):
            continue
        src = page.content()

        car = None
        for sc in re.finditer(
            r'<script type="application/ld\+json">(.*?)</script>', src, re.DOTALL
        ):
            try:
                data = json.loads(sc.group(1))
                t = data.get("@type")
                if t == "Car" or (isinstance(t, list) and "Car" in t):
                    car = data
                    break
            except Exception:
                continue
        if not car:
            continue

        offer = car.get("offers") or {}
        price = _coerce_int(offer.get("price")) or 0
        if price <= 0 or price > MAX_PRICE_AED:
            continue
        # Garbage filter — see scrape_dubizzle(). YallaMotor's "1 AED placeholders"
        # for showroom-new cars were the source of the pollution previously visible
        # at the cheap end of /cars?sort=price_asc.
        if price < 5000:
            continue

        mileage = car.get("mileageFromOdometer") or {}
        km = _coerce_int(mileage.get("value"))
        year = _coerce_int(car.get("modelDate") or car.get("vehicleModelDate"))
        desc = car.get("description") or ""
        name = car.get("name") or ""
        sunroof = _has_sunroof(name, desc)

        place = offer.get("availableAtOrFrom") or {}
        location = place.get("name") or "UAE"

        out.append(
            Listing(
                source="YallaMotor",
                brand=brand_label,
                title=name,
                price_aed=price,
                year=year,
                km=km,
                transmission=str(car.get("vehicleTransmission") or ""),
                trim="",
                location=location,
                color=str(car.get("color") or ""),
                body_type=str(car.get("bodyType") or ""),
                fuel=str(car.get("fuelType") or ""),
                seller_type="",
                has_sunroof=sunroof,
                features=[],
                description=desc[:400],
                image=str(car.get("image") or ""),
                url=item_url,
                scraped_at=datetime.now().isoformat(timespec="seconds"),
                ad_id=f"yalla_{item_url.rstrip('/').split('-')[-1]}",
            )
        )

    log(f"  YallaMotor: kept {len(out)} listings")
    return out


# ─── source: DubiCars ──────────────────────────────────────────────────────────
def scrape_dubicars(page, brand_label: str, mk: str, mdl: str) -> list[Listing]:
    out: list[Listing] = []
    url = f"https://www.dubicars.com/dubai/used/{mk}/{mdl}?price=0-{MAX_PRICE_AED}"
    log(f"  DubiCars: {url}")
    if not _safe_goto(page, url, timeout=45000):
        return out

    html = page.content()
    items: list[dict] = []
    for sc in re.finditer(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    ):
        try:
            data = json.loads(sc.group(1))
        except Exception:
            continue
        graph = data.get("@graph") if isinstance(data, dict) else None
        if not graph:
            continue
        for n in graph:
            if n.get("@type") == "ItemList":
                items.extend(n.get("itemListElement", []) or [])

    log(f"  DubiCars: found {len(items)} schema items")
    for it in items:
        car = it.get("item") if isinstance(it, dict) else None
        if not isinstance(car, dict):
            continue
        offer = car.get("offers") or {}
        raw_price = _coerce_int(offer.get("price"))
        ccy = (offer.get("priceCurrency") or "").upper()
        if raw_price is None:
            continue
        # DubiCars labels AED prices as USD in schema — convert if USD AND number is small
        if ccy == "USD" and raw_price < 30000:
            price = round(raw_price * USD_TO_AED)
        else:
            price = raw_price
        if price <= 0 or price > MAX_PRICE_AED:
            continue
        # Garbage filter — see scrape_dubizzle()
        if price < 5000:
            continue

        name = car.get("name") or ""
        desc = car.get("description") or ""
        mileage = car.get("mileageFromOdometer") or {}
        km = _coerce_int(mileage.get("value"))
        year = _coerce_int(car.get("vehicleModelDate") or car.get("modelDate"))
        detail_url = car.get("url") or offer.get("url") or ""
        image = car.get("image") or ""

        sunroof = _has_sunroof(name, desc)

        out.append(
            Listing(
                source="DubiCars",
                brand=brand_label,
                title=name,
                price_aed=price,
                year=year,
                km=km,
                transmission=str(car.get("vehicleTransmission") or ""),
                trim="",
                location="Dubai",
                color=str(car.get("color") or ""),
                body_type=str(car.get("bodyType") or ""),
                fuel=str(car.get("fuelType") or ""),
                seller_type="",
                has_sunroof=sunroof,
                features=[],
                description=desc[:400],
                image=str(image),
                url=detail_url,
                scraped_at=datetime.now().isoformat(timespec="seconds"),
                ad_id=f"dubicars_{detail_url.rstrip('/').split('-')[-1].replace('.html','')}",
            )
        )
    log(f"  DubiCars: kept {len(out)} priced listings")
    return out


# ─── source: DubiCars generic (all brands under cap, paginated) ─────────────────
def _brand_from_name(name: str) -> str:
    """Best-effort: extract a brand label like 'Toyota Corolla' from a free-text title."""
    if not name:
        return "Other"
    n = name.lower()
    # Order matters — longer / more specific first.
    KNOWN_PAIRS = [
        ("mitsubishi lancer ex","Mitsubishi Lancer EX"),
        ("mitsubishi lancer",   "Mitsubishi Lancer"),
        ("mitsubishi attrage",  "Mitsubishi Attrage"),
        ("mitsubishi galant",   "Mitsubishi Galant"),
        ("mitsubishi pajero",   "Mitsubishi Pajero"),
        ("toyota corolla",      "Toyota Corolla"),
        ("toyota yaris",        "Toyota Yaris"),
        ("toyota camry",        "Toyota Camry"),
        ("toyota avalon",       "Toyota Avalon"),
        ("toyota prius",        "Toyota Prius"),
        ("toyota echo",         "Toyota Echo"),
        ("toyota previa",       "Toyota Previa"),
        ("toyota rav",          "Toyota RAV4"),
        ("honda civic",         "Honda Civic"),
        ("honda accord",        "Honda Accord"),
        ("honda city",          "Honda City"),
        ("honda jazz",          "Honda Jazz"),
        ("honda fit",           "Honda Jazz"),
        ("hyundai elantra",     "Hyundai Elantra"),
        ("hyundai accent",      "Hyundai Accent"),
        ("hyundai sonata",      "Hyundai Sonata"),
        ("hyundai creta",       "Hyundai Creta"),
        ("hyundai i10",         "Hyundai i10"),
        ("hyundai i20",         "Hyundai i20"),
        ("hyundai grand i10",   "Hyundai Grand i10"),
        ("hyundai tucson",      "Hyundai Tucson"),
        ("kia cerato",          "Kia Cerato"),
        ("kia picanto",         "Kia Picanto"),
        ("kia rio",             "Kia Rio"),
        ("kia optima",          "Kia Optima"),
        ("kia sportage",        "Kia Sportage"),
        ("suzuki alto",         "Suzuki Alto"),
        ("suzuki swift",        "Suzuki Swift"),
        ("suzuki baleno",       "Suzuki Baleno"),
        ("suzuki ciaz",         "Suzuki Ciaz"),
        ("suzuki dzire",        "Suzuki Dzire"),
        ("suzuki celerio",      "Suzuki Celerio"),
        ("suzuki jimny",        "Suzuki Jimny"),
        ("maruti alto",         "Maruti Alto"),
        ("nissan sunny",        "Nissan Sunny"),
        ("nissan sentra",       "Nissan Sentra"),
        ("nissan altima",       "Nissan Altima"),
        ("nissan tiida",        "Nissan Tiida"),
        ("nissan micra",        "Nissan Micra"),
        ("nissan versa",        "Nissan Versa"),
        ("nissan patrol",       "Nissan Patrol"),
        ("nissan xtrail",       "Nissan X-Trail"),
        ("nissan x-trail",      "Nissan X-Trail"),
        ("mazda 3",             "Mazda 3"),
        ("mazda 6",             "Mazda 6"),
        ("mazda 2",             "Mazda 2"),
        ("mazda cx",            "Mazda CX"),
        ("chevrolet aveo",      "Chevrolet Aveo"),
        ("chevrolet cruze",     "Chevrolet Cruze"),
        ("chevrolet spark",     "Chevrolet Spark"),
        ("chevrolet sonic",     "Chevrolet Sonic"),
        ("ford focus",          "Ford Focus"),
        ("ford figo",           "Ford Figo"),
        ("ford fiesta",         "Ford Fiesta"),
        ("ford ecosport",       "Ford EcoSport"),
        ("ford escape",         "Ford Escape"),
        ("renault symbol",      "Renault Symbol"),
        ("renault duster",      "Renault Duster"),
        ("renault captur",      "Renault Captur"),
        ("renault logan",       "Renault Logan"),
        ("dodge charger",       "Dodge Charger"),
        ("dodge dart",          "Dodge Dart"),
        ("dodge avenger",       "Dodge Avenger"),
        ("geely emgrand",       "Geely Emgrand"),
        ("geely",               "Geely"),
        ("mg rx",               "MG RX"),
        ("mg ",                 "MG"),
        ("datsun",              "Datsun"),
        ("peugeot 301",         "Peugeot 301"),
        ("peugeot 308",         "Peugeot 308"),
        ("peugeot",             "Peugeot"),
        ("volkswagen jetta",    "Volkswagen Jetta"),
        ("volkswagen passat",   "Volkswagen Passat"),
        ("volkswagen golf",     "Volkswagen Golf"),
        ("volkswagen",          "Volkswagen"),
    ]
    for kw, label in KNOWN_PAIRS:
        if kw in n:
            return label
    # Fall back to first word capitalized.
    words = name.split()
    return words[0].title() if words else "Other"


def scrape_dubicars_generic(page) -> list[Listing]:
    """Hit DubiCars 'all used cars in Dubai under cap' search across multiple pages.
    Returns a wide cross-brand haul. Brand auto-detected from listing names."""
    out: list[Listing] = []
    for page_num in range(1, 11):    # 10 pages × ~30 = up to 300 listings
        url = f"https://www.dubicars.com/dubai/used/under-{MAX_PRICE_AED}-aed-cars?page={page_num}"
        log(f"  DubiCars (generic) page {page_num}: {url}")
        if not _safe_goto(page, url, timeout=45000):
            continue

        html = page.content()
        items: list[dict] = []
        for sc in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL):
            try: data = json.loads(sc.group(1))
            except Exception: continue
            graph = data.get("@graph") if isinstance(data, dict) else None
            if not graph: continue
            for n in graph:
                if n.get("@type") == "ItemList":
                    items.extend(n.get("itemListElement", []) or [])

        if not items:
            log(f"  DubiCars (generic): page {page_num} empty → stopping pagination")
            break

        kept = 0
        for it in items:
            car = it.get("item") if isinstance(it, dict) else None
            if not isinstance(car, dict): continue
            offer = car.get("offers") or {}
            raw_price = _coerce_int(offer.get("price"))
            ccy = (offer.get("priceCurrency") or "").upper()
            if raw_price is None: continue
            if ccy == "USD" and raw_price < 30000:
                price = round(raw_price * USD_TO_AED)
            else:
                price = raw_price
            if price <= 0 or price > MAX_PRICE_AED: continue
            if price < 5000: continue   # garbage filter — see scrape_dubizzle()

            name = car.get("name") or ""
            desc = car.get("description") or ""
            mileage = car.get("mileageFromOdometer") or {}
            km = _coerce_int(mileage.get("value"))
            year = _coerce_int(car.get("vehicleModelDate") or car.get("modelDate"))
            detail_url = car.get("url") or offer.get("url") or ""
            image = car.get("image") or ""
            sunroof = _has_sunroof(name, desc)
            brand = _brand_from_name(name)

            out.append(Listing(
                source="DubiCars",
                brand=brand,
                title=name,
                price_aed=price,
                year=year,
                km=km,
                transmission=str(car.get("vehicleTransmission") or ""),
                trim="",
                location="Dubai",
                color=str(car.get("color") or ""),
                body_type=str(car.get("bodyType") or ""),
                fuel=str(car.get("fuelType") or ""),
                seller_type="",
                has_sunroof=sunroof,
                features=[],
                description=desc[:400],
                image=str(image),
                url=detail_url,
                scraped_at=datetime.now().isoformat(timespec="seconds"),
                ad_id=f"dubicars_{detail_url.rstrip('/').split('-')[-1].replace('.html','')}",
            ))
            kept += 1
        log(f"  DubiCars (generic) page {page_num}: {kept} of {len(items)} priced ≤ {MAX_PRICE_AED}")
        time.sleep(1.2)
    return out


# ─── pipeline ──────────────────────────────────────────────────────────────────

# Source priority for cross-source dedup: when the same physical car appears on
# multiple sites, keep the one from the source with the most data quality.
# Dubizzle exposes listed_at + features + seller_type → wins.
# DubiCars has detailed schema.org Car fields → second.
# YallaMotor has the leanest data → last.
_SOURCE_PRIORITY = {"Dubizzle": 0, "DubiCars": 1, "YallaMotor": 2, "CarSwitch": 3}


def _xsource_key(r: "Listing") -> tuple | None:
    """Bucket-fingerprint for matching the same physical car across sources.

    None when we can't fingerprint (missing year/km/price) → keep as-is.
    Buckets are intentionally lossy:
      - km bucketed to nearest 5,000  → tolerates seller-typed-slightly-different odometer
      - price bucketed to nearest 500 → tolerates currency rounding (AED vs USD-mislabeled-as-AED on DubiCars)
    """
    if not r.brand or not r.year or not r.km or not r.price_aed:
        return None
    brand_norm = re.sub(r"\s+", " ", r.brand.strip().lower())
    return (brand_norm, int(r.year), int(r.km) // 5000, int(r.price_aed) // 500)


def merge_dedupe(rows: Iterable[Listing]) -> list[Listing]:
    # Step 1: Dubai-only filter + within-source dedup (by ad_id).
    by_ad: dict[tuple, Listing] = {}
    dropped_non_dubai = 0
    for r in rows:
        if not _is_dubai(r.location):
            dropped_non_dubai += 1
            continue
        key = (r.ad_id,) if r.ad_id else (r.source, r.url)
        by_ad[key] = r
    if dropped_non_dubai:
        log(f"  merge_dedupe: dropped {dropped_non_dubai} non-Dubai listings")

    # Step 2: cross-source dedup. Same physical car on Dubizzle + DubiCars + YallaMotor
    # produces 3 ad_ids today; keep the one from the highest-priority source.
    survivors: dict[tuple, Listing] = {}
    unmatched: list[Listing] = []
    dropped_xsource = 0
    for r in by_ad.values():
        k = _xsource_key(r)
        if k is None:
            # Can't fingerprint → keep, can't be deduped
            unmatched.append(r)
            continue
        incumbent = survivors.get(k)
        if incumbent is None:
            survivors[k] = r
        else:
            # Merge: keep whichever source ranks higher
            keep = r if _SOURCE_PRIORITY.get(r.source, 99) < _SOURCE_PRIORITY.get(incumbent.source, 99) else incumbent
            drop = incumbent if keep is r else r
            # Carry over listed_at from the dropped record if winner doesn't have one
            if not keep.listed_at and drop.listed_at:
                keep.listed_at = drop.listed_at
            # Carry over features/sunroof too — small enrichment win
            if not keep.has_sunroof and drop.has_sunroof:
                keep.has_sunroof = True
            survivors[k] = keep
            dropped_xsource += 1
    if dropped_xsource:
        log(f"  merge_dedupe: cross-source dedup removed {dropped_xsource} duplicate listings")

    return list(survivors.values()) + unmatched


DATA_JSON_BAK = DATA_JSON + ".bak"


def save_outputs(rows: list[Listing], final: bool = False) -> None:
    """UPSERT each row into SQLite (the canonical store), then dump a JSON+CSV
    snapshot for backward compatibility (frontends + raw data export).

    UPSERT semantics → existing listings get updated, new ones inserted, OLD
    listings NOT touched even if the current run is short. This eliminates the
    overwrite-loses-data class of bugs the JSON-only pipeline had.
    """
    rows_sorted = sorted(
        rows,
        key=lambda r: (not r.has_sunroof, r.price_aed if r.price_aed else 9_999_999),
    )

    # ── 1. UPSERT to DB (canonical) ───────────────────────────────────────────
    try:
        # Make `from db.db import upsert_car` work even though we're a sibling dir.
        import sys as _sys
        _root = os.path.dirname(HERE)
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from db.db import upsert_car, mark_inactive_cars_for_source  # type: ignore
        ins = upd = 0
        for r in rows_sorted:
            res = upsert_car(asdict(r))
            if res == "inserted": ins += 1
            elif res == "updated": upd += 1
        log(f"DB: upserted {ins + upd} rows (inserted={ins}, updated={upd})")
        # Mark anything we didn't see this run as inactive ONLY on the final save
        # AND only when this was a full sweep (no BRANDS filter). Otherwise a
        # targeted scrape (e.g. BRANDS=maruti) would wrongly deactivate every
        # listing outside its scope.
        is_partial = bool(os.environ.get("BRANDS", "").strip())
        append_only = os.environ.get("APPEND_ONLY", "").strip() in ("1", "true", "yes")
        if final and not is_partial and not append_only:
            # Per-source deactivation: see apartments scraper for rationale.
            # A source that returned 0 listings is treated as a scrape failure —
            # its records stay active until the source recovers.
            by_source: dict[str, list[str]] = {}
            for r in rows_sorted:
                by_source.setdefault(r.source, []).append(r.ad_id)
            total = 0
            for src, seen_ids in by_source.items():
                if not seen_ids:
                    log(f"DB: skipping mark_inactive for {src} — returned 0 listings")
                    continue
                n = mark_inactive_cars_for_source(seen_ids, src)
                if n:
                    log(f"DB: marked {n} stale {src} cars as inactive")
                total += n
            if not total:
                log("DB: no cars deactivated (no stale rows in successfully-scraped sources)")
        elif final and is_partial:
            log("DB: skipping mark_inactive — partial run (BRANDS filter set)")
        elif final and append_only:
            log("DB: skipping mark_inactive — APPEND_ONLY mode (preserves all rows)")
    except Exception as e:
        log(f"DB upsert failed (continuing with JSON save): {e}")

    # ── 2. JSON snapshot (for legacy frontend prep + manual inspection) ───────
    if final and os.path.exists(DATA_JSON):
        try:
            import shutil
            shutil.copy2(DATA_JSON, DATA_JSON_BAK)
        except Exception:
            pass

    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rows_sorted], f, ensure_ascii=False, indent=2)

    if rows_sorted:
        fieldnames = list(rows_sorted[0].csv_row().keys())
        with open(DATA_CSV, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in rows_sorted:
                w.writerow(r.csv_row())

    log(f"Saved {len(rows_sorted)} -> {os.path.basename(DATA_JSON)}")
    log(f"Saved {len(rows_sorted)} -> {os.path.basename(DATA_CSV)}")


def regenerate_frontend_data() -> None:
    """Trigger prep_data.py so the frontend updates after every scrape."""
    import subprocess

    prep = os.path.join(
        os.path.dirname(HERE), "Car Deals Frontend", "prep_data.py"
    )
    if not os.path.exists(prep):
        log("(frontend prep_data.py not found, skipping)")
        return
    log(f"Running frontend prep: {prep}")
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", prep],
            capture_output=True,
            text=True,
            timeout=60,
        )
        for line in (result.stdout or "").splitlines():
            log(f"  prep: {line}")
        if result.returncode != 0:
            log(f"  prep STDERR: {result.stderr[:500]}")
        log(f"prep_data.py exit code: {result.returncode}")
    except Exception as e:
        log(f"prep_data.py failed: {e}")


def _db_helpers():
    """Lazy-load DB helpers. Avoids hard dependency at import time."""
    import sys as _sys
    _root = os.path.dirname(HERE)
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    from db.db import (
        start_scrape_run, finish_scrape_run,
        upsert_car as _uc, mark_inactive_cars as _mi,
    )  # type: ignore
    return start_scrape_run, finish_scrape_run, _uc, _mi


def main() -> int:
    log("=" * 60)
    log(f"DUBAI CAR SCRAPER -- daily run @ price <= AED {MAX_PRICE_AED:,}")
    log("=" * 60)

    # Open a scrape_runs row (best-effort — never fail the scrape if DB hiccups).
    run_id = 0
    try:
        start_scrape_run, _finish_scrape_run, _, _ = _db_helpers()
        notes_at_start = os.environ.get("BRANDS", "").strip()
        run_id = start_scrape_run(
            "cars",
            notes=("BRANDS=" + notes_at_start) if notes_at_start else "full sweep",
        )
        log(f"DB: opened scrape_runs row id={run_id}")
    except Exception as e:
        log(f"DB: couldn't open scrape_runs row: {e}")

    # Load yesterday's data into the in-memory cache so we can skip detail-page
    # fetches for listings we already enriched. Keeps daily runs sustainable
    # under Dubizzle's bot wall.
    global PRIOR_DATA
    if os.path.exists(DATA_JSON):
        try:
            with open(DATA_JSON, "r", encoding="utf-8") as f:
                prev = json.load(f)
            for r in prev:
                if r.get("ad_id"):
                    PRIOR_DATA[r["ad_id"]] = r
            log(f"Cache: loaded {len(PRIOR_DATA)} prior listings from {os.path.basename(DATA_JSON)}")
        except Exception as e:
            log(f"Cache: failed to load prior data: {e}")

    # Optional brand filter for targeted runs:
    #   BRANDS=suzuki python scrape_dubai_cars.py
    #   BRANDS="suzuki,maruti,toyota avalon" python scrape_dubai_cars.py
    brands_filter = os.environ.get("BRANDS", "").strip().lower()
    if brands_filter:
        keywords = [k.strip() for k in brands_filter.split(",") if k.strip()]
        global TARGETS
        before = len(TARGETS)
        TARGETS = [t for t in TARGETS if any(k in t[0].lower() for k in keywords)]
        log(f"BRANDS filter: keeping {len(TARGETS)}/{before} targets matching {keywords}")
        for t in TARGETS:
            log(f"  -> {t[0]}")

    all_rows: list[Listing] = []
    with sync_playwright() as pw:
        browser, ctx = _new_browser_context(pw)
        page = ctx.new_page()

        def run_source(fn, label, slug_tuple):
            """Wrap a source call so a poisoned tab doesn't kill the rest of the run."""
            nonlocal page
            try:
                rows = fn(page, label, *slug_tuple)
            except Exception as e:
                log(f"  {fn.__name__} raised {type(e).__name__}: {e}")
                rows = []
            if _is_page_broken(page):
                page = _recycle_page(ctx, page)
            return rows

        try:
            # PHASE 1: wide DubiCars sweep (all brands, paginated) — cheap, no bot wall.
            # This loads up the DB with everything under our cap before we per-model.
            log("[PHASE 1] DubiCars all-brands sweep")
            try:
                all_rows += scrape_dubicars_generic(page)
                save_outputs(merge_dedupe(all_rows))
            except Exception as e:
                log(f"  generic sweep error: {e}")

            # PHASE 2: per-model scrape across all three sources.
            log(f"\n[PHASE 2] Per-model scrape across {len(TARGETS)} models")
            for i, (label, dz, ym, dc) in enumerate(TARGETS, 1):
                log(f"[{i}/{len(TARGETS)}] {label}")
                all_rows += run_source(scrape_dubizzle, label, dz)
                all_rows += run_source(scrape_dubicars, label, dc)
                all_rows += run_source(scrape_yallamotor, label, ym)
                save_outputs(merge_dedupe(all_rows))
        finally:
            try:
                ctx.close()
            except Exception: pass
            try:
                browser.close()
            except Exception: pass

    rows = merge_dedupe(all_rows)
    save_outputs(rows, final=True)

    # Close the scrape_runs row.
    try:
        _, finish_scrape_run, _, _ = _db_helpers()
        # Counts: rows_seen=len(rows); we can't easily separate insert vs update
        # since save_outputs() handles that. Re-derive from DB diffs.
        from db.db import cur as _dbcur  # type: ignore
        with _dbcur() as c:
            c.execute("SELECT COUNT(*) FROM cars WHERE is_active=1")
            active_after = c.fetchone()[0]
        finish_scrape_run(
            run_id,
            rows_seen=len(rows),
            rows_new=0,        # see Pipeline tab — derived via first_seen_at
            rows_updated=0,
            notes=f"active_after={active_after}, dubizzle_disabled={DUBIZZLE_DISABLED}",
        )
        log(f"DB: closed scrape_runs row id={run_id}")
    except Exception as e:
        log(f"DB: couldn't close scrape_runs row: {e}")

    sunroof_n = sum(1 for r in rows if r.has_sunroof)
    log(f"DONE: {len(rows)} listings total, {sunroof_n} with sunroof confirmed")

    regenerate_frontend_data()
    return 0


if __name__ == "__main__":
    sys.exit(main())
