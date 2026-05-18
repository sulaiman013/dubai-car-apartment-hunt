"""
Dubai 1BHK furnished apartment scraper — DAFZA-adjacent areas, ≤ AED 72K/yr.

Sources:
  Bayut.com         — primary. Per-area URLs. Listings in `window.state`.
  PropertyFinder.ae — secondary. Open Dubai search + DAFZA-tier post-filter.

Anti-bot: Patchright with headed-but-off-screen Chromium.
  - headless=True triggers Bayut + PF bot walls.
  - headless=False positioned at (-2400,-2400) is undetectable AND invisible.

Output: apartments.json + apartments.csv (+ regenerates frontend data.js)
"""

from __future__ import annotations

import csv
import json
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Iterable

from patchright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


def jitter_sleep(base_seconds: float, spread: float = 0.5) -> None:
    """Sleep `base_seconds` ± up to `spread × base_seconds` of random jitter.

    Predictable inter-request timing is one of the strongest bot signals.
    Real humans browse with variable pauses (reading time, network hiccups,
    distractions). spread=0.5 means actual sleep is uniform in
    [base × 0.5, base × 1.5] — typically 50%–150% of nominal.
    """
    low  = max(0.1, base_seconds * (1 - spread))
    high = base_seconds * (1 + spread)
    time.sleep(random.uniform(low, high))

# ─── config ────────────────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(HERE, "apartments.json")
DATA_CSV  = os.path.join(HERE, "apartments.csv")
LOG_FILE  = os.path.join(HERE, "scrape_log.txt")

MAX_PRICE_AED = int(os.environ.get("MAX_PRICE_AED", "72000"))   # yearly cap

# Bayut area slugs grouped by DAFZA commute tier.
BAYUT_AREAS: list[tuple[str, str, int, str]] = [
    # (emirate, slug, tier, display_name)
    # USER CONSTRAINT: all areas here must have CONVENIENT commute to DAFZA
    # (the user's office at Heidelberg Materials Trading, Dubai Airport Free Zone).
    # Inconvenient areas (Intl City, Discovery Gardens, DSO, anything Sharjah-side)
    # are deliberately excluded — see memory.md.

    # ── Tier 1: DAFZA-adjacent — walkable or one Green Line stop ───────────────
    ("dubai",   "al-qusais",            1, "Al Qusais"),           # NEXT TO DAFZA metro
    ("dubai",   "al-twar",              1, "Al Twar"),             # walkable to DAFZA
    ("dubai",   "hor-al-anz",           1, "Hor Al Anz"),
    ("dubai",   "al-nahda",             1, "Al Nahda (Dubai)"),    # next Green Line stop after DAFZA
    # ── Tier 2: 10-15 min by car / few metro stops ────────────────────────────
    ("dubai",   "al-garhoud",           2, "Al Garhoud"),          # near airport, GGICO station
    ("dubai",   "al-rashidiya",         2, "Al Rashidiya"),        # Red Line terminus
    ("dubai",   "deira",                2, "Deira"),               # Red Line + Union transfer
    ("dubai",   "al-mamzar",            2, "Al Mamzar"),           # Dubai-side border, 12-15 min
    ("dubai",   "al-rigga",             2, "Al Rigga"),            # Red Line, near Union
    ("dubai",   "naif",                 2, "Naif"),                # near Baniyas Square
    ("dubai",   "al-muraqqabat",        2, "Al Muraqqabat"),       # Salah Al Din metro
    ("dubai",   "al-khabaisi",          2, "Al Khabaisi"),
    ("dubai",   "port-saeed",           2, "Port Saeed"),          # near Deira Creek
    ("dubai",   "abu-hail",             2, "Abu Hail"),            # Green Line station
    # ── Tier 3: 15-20 min — still acceptable, edge of convenient ──────────────
    ("dubai",   "mirdif",               3, "Mirdif"),
    ("dubai",   "dubai-festival-city",  3, "Dubai Festival City"),
    ("dubai",   "al-karama",            3, "Al Karama"),
    ("dubai",   "al-satwa",             3, "Al Satwa"),
    ("dubai",   "bur-dubai",            3, "Bur Dubai"),

    # EXPLICITLY EXCLUDED (commented out, do not re-add without re-asking):
    # ("dubai",   "international-city",   _, "International City"),   # too far west — 25-35 min drive
    # ("dubai",   "discovery-gardens",    _, "Discovery Gardens"),    # Jebel Ali side, 40+ min
    # ("dubai",   "dubai-silicon-oasis",  _, "Dubai Silicon Oasis"),  # south Dubai, ~25 min
    # ("sharjah", "al-nahda",             _, "Al Nahda (Sharjah)"),   # cross-emirate rush-hour pain
    # ("sharjah", "al-taawun",            _, "Al Taawun (Sharjah)"),  # Sharjah side
]

# DAFZA tier patterns for post-filtering generic search results (e.g., PF).
AREA_TIERS: list[tuple[re.Pattern, int, str]] = [
    # USER CONSTRAINT: only DAFZA-convenient Dubai areas. See BAYUT_AREAS above.
    # Anything not matching any pattern below is REJECTED by the post-filter.

    # ── Tier 1: DAFZA-adjacent or 1 stop on Green Line ────────────────────────
    (re.compile(r"\bal[\s-]+twar\b",          re.I), 1, "Al Twar"),
    (re.compile(r"\bal[\s-]+qusais\b",        re.I), 1, "Al Qusais"),
    (re.compile(r"\bhor[\s-]+al[\s-]+anz\b",  re.I), 1, "Hor Al Anz"),
    # Sharjah-side Al Nahda BEFORE Dubai Al Nahda to prevent mis-classification:
    (re.compile(r"al[\s-]+nahda.*sharjah|sharjah.*al[\s-]+nahda", re.I), 99, "REJECT_SHARJAH_NAHDA"),
    (re.compile(r"al[\s-]+nahda",             re.I), 1, "Al Nahda (Dubai)"),

    # ── Tier 2: 10-15 min ─────────────────────────────────────────────────────
    (re.compile(r"\bal[\s-]+garhoud\b",       re.I), 2, "Al Garhoud"),
    (re.compile(r"\bal[\s-]+rashidiya\b",     re.I), 2, "Al Rashidiya"),
    (re.compile(r"\bal[\s-]+rigga\b",         re.I), 2, "Al Rigga"),
    (re.compile(r"\bnaif\b",                  re.I), 2, "Naif"),
    (re.compile(r"\bal[\s-]+muraqqabat\b",    re.I), 2, "Al Muraqqabat"),
    (re.compile(r"\bdeira\b",                 re.I), 2, "Deira"),
    (re.compile(r"\bal[\s-]+mamzar\b",        re.I), 2, "Al Mamzar"),
    (re.compile(r"\babu[\s-]+hail\b",         re.I), 2, "Abu Hail"),
    (re.compile(r"\bport[\s-]+saeed\b",       re.I), 2, "Port Saeed"),
    (re.compile(r"\bal[\s-]+khabaisi\b",      re.I), 2, "Al Khabaisi"),

    # ── Tier 3: 15-20 min — edge of "convenient" ──────────────────────────────
    (re.compile(r"\bmirdif\b",                re.I), 3, "Mirdif"),
    (re.compile(r"festival[\s-]+city",        re.I), 3, "Dubai Festival City"),
    (re.compile(r"\bal[\s-]+karama\b",        re.I), 3, "Al Karama"),
    (re.compile(r"\bal[\s-]+satwa\b",         re.I), 3, "Al Satwa"),
    (re.compile(r"\bbur[\s-]+dubai\b",        re.I), 3, "Bur Dubai"),

    # Inconvenient areas are not matched here → _match_area returns None →
    # listing is dropped. Explicitly: International City, Discovery Gardens,
    # DSO, Al Nahda Sharjah, Al Taawun Sharjah.
]


# ─── logging ───────────────────────────────────────────────────────────────────
def log(msg: str = "") -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}" if msg else ""
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"), flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ─── data model ────────────────────────────────────────────────────────────────
@dataclass
class Apartment:
    source: str
    ad_id: str
    title: str
    price_aed: int        # YEARLY
    monthly_aed: int
    bedrooms: int
    bathrooms: int | None
    size_sqft: int | None
    area: str
    commute_tier: int     # 1-4 (lower = closer to DAFZA)
    full_location: str
    furnished: bool
    amenities: list[str]
    image: str
    url: str
    broker: str
    agent_name: str
    agent_phone: str
    lat: float | None
    lon: float | None
    description: str
    scraped_at: str

    def csv_row(self) -> dict:
        d = asdict(self)
        d["amenities"] = " | ".join(self.amenities) if self.amenities else ""
        return d


# ─── helpers ───────────────────────────────────────────────────────────────────
def _match_area(location_path: str) -> tuple[int, str] | None:
    """Return (tier, area_name) if location is a DAFZA-convenient area, else None.
    The sentinel tier 99 marks explicit-reject patterns (e.g. Sharjah Al Nahda)."""
    if not location_path:
        return None
    for pat, tier, name in AREA_TIERS:
        if pat.search(location_path):
            if tier == 99:
                return None         # explicit reject
            return tier, name
    return None


def _coerce_int(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = re.sub(r"[^\d]", "", str(v))
    return int(s) if s else None


def _new_browser(pw):
    """Patchright in 'invisible headed' mode: window placed off-screen so anti-bot
    sees a real browser fingerprint while the user sees nothing."""
    browser = pw.chromium.launch(
        headless=False,
        channel="chromium",
        args=[
            "--window-position=-2400,-2400",
            "--window-size=1920,1080",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
    )
    return browser, ctx


def _safe_goto(page, url: str, timeout: int = 30000, wait_until: str = "domcontentloaded") -> bool:
    try:
        page.goto(url, wait_until=wait_until, timeout=timeout)
        page.wait_for_timeout(5500)   # let SSR + first paint settle
        return True
    except PWTimeoutError:
        log(f"  timeout: {url}")
        return False
    except Exception as e:
        log(f"  err {type(e).__name__}: {url} - {e}")
        return False


def _extract_window_state(html: str) -> dict | None:
    """Balanced-brace extract Bayut's `window.state = {...}` blob."""
    m = re.search(r"window\.state\s*=\s*(\{)", html)
    if not m:
        return None
    start = m.start() + len("window.state = ")
    depth = 0
    for i, ch in enumerate(html[start : start + 2_500_000]):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start : start + i + 1])
                except Exception:
                    return None
    return None


# ─── source: Bayut ─────────────────────────────────────────────────────────────
def _bayut_normalize_hit(h: dict, emirate: str, area_slug: str, tier: int, area_name: str) -> Apartment | None:
    """Turn a Bayut Algolia hit dict into a unified Apartment record."""
    try:
        beds = _coerce_int(h.get("rooms"))
        if beds != 1:
            return None
        price = _coerce_int(h.get("price")) or 0
        freq = (h.get("rentFrequency") or "").lower()
        if freq != "yearly" or price <= 0 or price > MAX_PRICE_AED:
            return None
        if (h.get("furnishingStatus") or "").lower() != "furnished":
            return None

        external_id = str(h.get("externalID") or h.get("id") or "")
        title = (h.get("title") or "").strip()
        baths = _coerce_int(h.get("baths"))
        area_sqft = _coerce_int(h.get("area"))   # Bayut: sqft

        # Bayut listing URL: always /property/details-{externalID}.html.
        # The slug field is purely SEO; the real canonical is the externalID.
        url = f"https://www.bayut.com/property/details-{external_id}.html"

        # Location breadcrumbs
        locs = h.get("locations") or []
        loc_path = ", ".join(reversed([l.get("name") or "" for l in locs if l.get("name")]))

        # Cover image: coverPhoto has no URL; it has `id` and Bayut serves it
        # from `https://images.bayut.com/thumbnails/{id}-{width}x{height}.jpeg`.
        cover = h.get("coverPhoto") or {}
        cover_id = cover.get("id") or cover.get("externalID")
        image = (
            f"https://images.bayut.com/thumbnails/{cover_id}-800x600.jpeg"
            if cover_id
            else ""
        )

        # Amenities (Bayut puts them under 'amenities' as list of {category, amenities})
        amen_set: list[str] = []
        for grp in (h.get("amenities") or []):
            if isinstance(grp, dict):
                for a in (grp.get("amenities") or []):
                    n = a.get("name") if isinstance(a, dict) else str(a)
                    if n:
                        amen_set.append(n)

        # Contact / broker
        agency = h.get("agency") or {}
        broker = (agency.get("name") if isinstance(agency, dict) else "") or ""
        contact_name = h.get("contactName") or ""

        # Geo
        geo = h.get("geography") or {}
        lat = geo.get("lat")
        lon = geo.get("lng") or geo.get("lon")

        return Apartment(
            source="Bayut",
            ad_id=f"bayut_{external_id}",
            title=title,
            price_aed=price,
            monthly_aed=round(price / 12),
            bedrooms=beds,
            bathrooms=baths,
            size_sqft=area_sqft,
            area=area_name,
            commute_tier=tier,
            full_location=loc_path or f"{area_name}, {emirate.title()}",
            furnished=True,
            amenities=amen_set,
            image=image,
            url=url,
            broker=broker,
            agent_name=contact_name,
            agent_phone="",
            lat=float(lat) if isinstance(lat, (int, float)) else None,
            lon=float(lon) if isinstance(lon, (int, float)) else None,
            description=(h.get("description") or "")[:600],
            scraped_at=datetime.now().isoformat(timespec="seconds"),
        )
    except Exception as e:
        log(f"  Bayut: row error: {e}")
        return None


def scrape_bayut(page) -> list[Apartment]:
    out: list[Apartment] = []
    for emirate, slug, tier, area_name in BAYUT_AREAS:
        url = (
            f"https://www.bayut.com/to-rent/apartments/{emirate}/{slug}/"
            f"?furnishing_status=furnished&beds_in=1&price_to={MAX_PRICE_AED}"
            f"&rent_frequency=yearly"
        )
        log(f"  Bayut: {area_name} -> {url}")
        if not _safe_goto(page, url):
            continue
        html = page.content()
        state = _extract_window_state(html)
        if not state:
            log(f"  Bayut: {area_name}: no window.state")
            continue

        algolia = state.get("algolia", {}) or {}
        content = algolia.get("content", {}) or {}
        main_hits = content.get("hits") or []
        # Recommendations also include eligible listings — gather them as bonus
        rec_hits = (state.get("search", {}).get("recommendations", {}).get("data", {}) or {}).get("recommenderHits") or []

        kept = 0
        for h in main_hits + rec_hits:
            ap = _bayut_normalize_hit(h, emirate, slug, tier, area_name)
            if not ap:
                continue
            # Recommendations may belong to different areas — re-tier via location text.
            mt = _match_area(ap.full_location)
            if mt:
                ap.commute_tier, ap.area = mt
            out.append(ap)
            kept += 1
        log(f"  Bayut: {area_name}: kept {kept} (main={len(main_hits)}, recs={len(rec_hits)})")
        jitter_sleep(1.5)   # 0.75–2.25s between Bayut areas
    return out


# ─── source: Property Finder ───────────────────────────────────────────────────
def scrape_propertyfinder(page) -> list[Apartment]:
    """Per-area scrape using PF's furnished-1BR slug URLs.

    Background: the old Dubai-wide + price-ASC search returned 30 listings/page,
    all of which were the cheapest non-DAFZA places (Discovery Gardens, JVC, etc.)
    that the post-filter rejected, yielding zero kept. PF actually has clean
    per-area pages like:

        https://www.propertyfinder.ae/en/rent/dubai/
            furnished-1-bedroom-apartments-for-rent-{slug}.html?page={n}

    so we iterate those directly. We reuse the BAYUT_AREAS slugs since PF and
    Bayut use the same slug conventions for Dubai areas (deira, al-qusais, etc.).
    Some smaller areas 404 on PF — that's normal, we just log and continue.
    """
    out: list[Apartment] = []
    seen: set[str] = set()
    PF_BASE = ("https://www.propertyfinder.ae/en/rent/dubai/"
               "furnished-1-bedroom-apartments-for-rent-{slug}.html?page={page}")

    for emirate, slug, tier, area_name in BAYUT_AREAS:
        if emirate != "dubai":
            continue   # PF area pages here are Dubai-only

        zero_streak = 0
        area_kept = 0
        for page_num in range(1, 11):  # 33 listings/page × 10 = enough headroom
            url = PF_BASE.format(slug=slug, page=page_num)
            if not _safe_goto(page, url, wait_until="domcontentloaded"):
                break
            # PF returns a 404 page for slugs it doesn't know — bail this area
            if "404" in (page.title() or ""):
                log(f"  PF {area_name}: 404 (no such PF area page)")
                break

            html = page.content()
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if not m:
                log(f"  PF {area_name} p{page_num}: no NEXT_DATA")
                break
            try:
                data = json.loads(m.group(1))
            except Exception as e:
                log(f"  PF {area_name} p{page_num}: parse fail ({e})")
                break

            listings = (data.get("props", {}).get("pageProps", {})
                            .get("searchResult", {}).get("listings", []))
            if not listings:
                # First-page empty = no inventory; later-page empty = end of pagination
                break

            kept_on_page = 0
            for entry in listings:
                if entry.get("listing_type") != "property":
                    continue
                prop = entry.get("property") or {}
                pid = str(prop.get("id") or "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)

                price_obj = prop.get("price") or {}
                price = _coerce_int(price_obj.get("value")) or 0
                period = (price_obj.get("period") or "").lower()
                # Slug-search returns mixed rental periods — keep yearly only
                if period != "yearly" or price <= 0 or price > MAX_PRICE_AED:
                    continue

                # PF returns bedrooms as a STRING ('1', '2', '0' for studio) — coerce
                beds = _coerce_int(prop.get("bedrooms"))
                if beds != 1:
                    continue

                # Slug-search guarantees the location, but double-check the property's
                # tagged location matches our DAFZA-tier list (rejects listings that
                # PF mis-tags into a DAFZA-area slug page).
                loc = prop.get("location") or {}
                full_loc = loc.get("full_name") or loc.get("path_name") or ""
                tier_match = _match_area(full_loc)
                if not tier_match:
                    # Trust the URL slug as fallback so we don't drop genuine hits
                    # when PF's location string is unusual.
                    effective_tier, effective_area = tier, area_name
                else:
                    effective_tier, effective_area = tier_match

                coords = loc.get("coordinates") or {}
                images = prop.get("images") or []
                image = ""
                if images:
                    image = images[0].get("medium") or images[0].get("small") or ""
                size_obj = prop.get("size") or {}
                size_sqft = None
                if (size_obj.get("unit") or "").lower() == "sqft":
                    size_sqft = _coerce_int(size_obj.get("value"))
                amen = [a.get("name") for a in (prop.get("amenities") or [])
                        if isinstance(a, dict) and a.get("name")]
                broker = (prop.get("broker") or {}).get("name") or ""
                agent_name = (prop.get("agent") or {}).get("name") or ""
                agent_phone = (prop.get("broker") or {}).get("phone") or ""

                out.append(Apartment(
                    source="PropertyFinder",
                    ad_id=f"pf_{pid}",
                    title=(prop.get("title") or "").strip(),
                    price_aed=price,
                    monthly_aed=round(price / 12),
                    bedrooms=beds,
                    bathrooms=_coerce_int(prop.get("bathrooms")),
                    size_sqft=size_sqft,
                    area=effective_area,
                    commute_tier=effective_tier,
                    full_location=full_loc,
                    furnished=True,
                    amenities=amen,
                    image=image,
                    url=prop.get("share_url") or "",
                    broker=broker,
                    agent_name=agent_name.strip(),
                    agent_phone=agent_phone,
                    lat=float(coords["lat"]) if coords.get("lat") is not None else None,
                    lon=float(coords["lon"]) if coords.get("lon") is not None else None,
                    description="",
                    scraped_at=datetime.now().isoformat(timespec="seconds"),
                ))
                kept_on_page += 1

            area_kept += kept_on_page
            log(f"  PF {area_name} p{page_num}: kept {kept_on_page} of {len(listings)}")

            if kept_on_page == 0:
                zero_streak += 1
                if zero_streak >= 2:
                    break
            else:
                zero_streak = 0

            # PF defaults to ~33/page; if we got less than 25, we're near the end
            if len(listings) < 25:
                break

            jitter_sleep(1.2)   # 0.6–1.8s between PF pagination requests

        log(f"  PF {area_name}: TOTAL kept {area_kept}")
    return out


# ─── pipeline ──────────────────────────────────────────────────────────────────
def merge_dedupe(rows: Iterable[Apartment]) -> list[Apartment]:
    seen: dict[str, Apartment] = {}
    for r in rows:
        # If duplicate ad_id, prefer the one with richer data (more amenities).
        prev = seen.get(r.ad_id)
        if prev is None or len(r.amenities) > len(prev.amenities):
            seen[r.ad_id] = r
    return list(seen.values())


def save_outputs(rows: list[Apartment], final: bool = False) -> None:
    """UPSERT into SQLite + dump JSON+CSV snapshots for compatibility."""
    rows_sorted = sorted(rows, key=lambda r: (r.commute_tier, r.price_aed))

    # 1. UPSERT to DB (canonical)
    try:
        import sys as _sys
        _root = os.path.dirname(HERE)
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from db.db import upsert_apartment, mark_inactive_apartments_for_source  # type: ignore
        ins = upd = 0
        for r in rows_sorted:
            res = upsert_apartment(asdict(r))
            if res == "inserted": ins += 1
            elif res == "updated": upd += 1
        log(f"DB: upserted {ins + upd} rows (inserted={ins}, updated={upd})")
        # Only deactivate stale listings on a full sweep, never on a targeted
        # run (env-var AREAS filter, if we ever add one).
        is_partial = bool(os.environ.get("AREAS", "").strip())
        append_only = os.environ.get("APPEND_ONLY", "").strip() in ("1", "true", "yes")
        if final and not is_partial and not append_only:
            # Per-source deactivation: a source that returned 0 listings is treated
            # as a SCRAPE FAILURE (bot wall, network glitch, source rename) — its
            # records are preserved. Only sources that successfully scraped >=1
            # listing get their stale rows deactivated.
            by_source: dict[str, list[str]] = {}
            for r in rows_sorted:
                by_source.setdefault(r.source, []).append(r.ad_id)
            total_deactivated = 0
            for src, seen_ids in by_source.items():
                if not seen_ids:
                    log(f"DB: skipping mark_inactive for {src} — returned 0 listings (likely bot-walled)")
                    continue
                n = mark_inactive_apartments_for_source(seen_ids, src)
                if n:
                    log(f"DB: marked {n} stale {src} apartments as inactive")
                total_deactivated += n
            # Sources expected to be hit but absent from rows_sorted = scrape never ran them
            # (or all returned 0). We DON'T touch their records.
            if not total_deactivated:
                log("DB: no apartments deactivated (every contributing source either returned all known listings or none)")
        elif final and is_partial:
            log("DB: skipping mark_inactive — partial run (AREAS filter set)")
        elif final and append_only:
            log("DB: skipping mark_inactive — APPEND_ONLY mode (preserves all rows)")
    except Exception as e:
        log(f"DB upsert failed (continuing with JSON save): {e}")

    # 2. JSON snapshot
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
    prep = os.path.join(os.path.dirname(HERE), "Apartment Hunt Frontend", "prep_data.py")
    if not os.path.exists(prep):
        log("(frontend prep_data.py not found, skipping)")
        return
    log(f"Running frontend prep: {prep}")
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", prep],
            capture_output=True, text=True, timeout=60,
        )
        for line in (result.stdout or "").splitlines():
            log(f"  prep: {line}")
        if result.returncode != 0:
            log(f"  prep STDERR: {result.stderr[:500]}")
        log(f"prep_data.py exit code: {result.returncode}")
    except Exception as e:
        log(f"prep_data.py failed: {e}")


def _db_helpers():
    """Lazy-load DB helpers for the scrape_runs log."""
    import sys as _sys
    _root = os.path.dirname(HERE)
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    from db.db import start_scrape_run, finish_scrape_run, cur as _dbcur  # type: ignore
    return start_scrape_run, finish_scrape_run, _dbcur


def main() -> int:
    log("=" * 60)
    log(f"APARTMENT SCRAPER -- 1BHK furnished, yearly, <= AED {MAX_PRICE_AED:,}")
    log(f"DAFZA-adjacent areas, Patchright invisible-headed mode")
    log("=" * 60)

    # Audit-log open
    run_id = 0
    try:
        start_scrape_run, _finish, _ = _db_helpers()
        run_id = start_scrape_run("apartments", notes=f"areas={len(BAYUT_AREAS)}")
        log(f"DB: opened scrape_runs row id={run_id}")
    except Exception as e:
        log(f"DB: couldn't open scrape_runs row: {e}")

    all_rows: list[Apartment] = []
    with sync_playwright() as pw:
        browser, ctx = _new_browser(pw)
        page = ctx.new_page()
        try:
            log("\n[1/2] Bayut (per-area)")
            all_rows += scrape_bayut(page)
            log("\n[2/2] PropertyFinder (open + tier filter)")
            all_rows += scrape_propertyfinder(page)
        finally:
            try: ctx.close()
            except Exception: pass
            try: browser.close()
            except Exception: pass

    rows = merge_dedupe(all_rows)
    save_outputs(rows, final=True)

    by_tier: dict[int, int] = {}
    for r in rows:
        by_tier[r.commute_tier] = by_tier.get(r.commute_tier, 0) + 1
    log(f"DONE: {len(rows)} apartments. By tier: {sorted(by_tier.items())}")
    if rows:
        ch = min(rows, key=lambda r: r.price_aed)
        log(f"Cheapest: AED {ch.price_aed:,}/yr ({ch.monthly_aed:,}/mo) in {ch.area} (tier {ch.commute_tier})")

    # Audit-log close
    try:
        _, finish_scrape_run, dbcur = _db_helpers()
        with dbcur() as c:
            c.execute("SELECT COUNT(*) FROM apartments WHERE is_active=1")
            active_after = c.fetchone()[0]
        finish_scrape_run(
            run_id,
            rows_seen=len(rows),
            rows_new=0,
            rows_updated=0,
            notes=f"active_after={active_after}, by_tier={dict(sorted(by_tier.items()))}",
        )
        log(f"DB: closed scrape_runs row id={run_id}")
    except Exception as e:
        log(f"DB: couldn't close scrape_runs row: {e}")

    regenerate_frontend_data()
    return 0


if __name__ == "__main__":
    sys.exit(main())
