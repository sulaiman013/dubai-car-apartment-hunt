# Scrapers

## Cars — `Car Search - Dubai UAE/scrape_dubai_cars.py`

### Sources
1. **Dubizzle UAE** — primary. Hits `uae.dubizzle.com/motors/used-cars/{brand}/{model}/`. Parses `__NEXT_DATA__` JSON. Bot wall is occasional and IP-based; retry+backoff handles it.
2. **DubiCars** — secondary. Hits `dubicars.com/dubai/used/{brand}/{model}`. Parses JSON-LD ItemList. Currency in their schema is mis-labelled USD; converted via `USD_TO_AED = 3.6725`.
3. **YallaMotor** — currently broken (no ItemList JSON-LD). Graceful no-op.

### Targets list (`TARGETS` at top of file)

Expandable list of `(label, dubizzle_path, yallamotor_path, dubicars_path)` tuples. Current set:

- Hyundai Elantra, Honda Civic, Nissan Sunny
- Toyota Corolla, Yaris, Camry, Avalon, Prius
- Honda Accord, City, Jazz
- Hyundai Accent, Sonata, Creta
- Kia Cerato, Picanto, Rio
- Suzuki Swift, Baleno, Ciaz, Dzire
- Mazda 3, Mazda 6
- Mitsubishi Lancer EX, Attrage
- Chevrolet Aveo

### Key behaviors

- **Dubai-only filter:** location must start with "UAE > Dubai > ..." or be "Dubai" for non-breadcrumb sources. Enforced both in `scrape_dubizzle` (early skip) and `merge_dedupe` (belt-and-suspenders).
- **Detail-page enrichment:** Dubizzle moved feature sections off the search results page in May 2026. If a listing lacks structured year/km/features, we fetch its detail page (cached by ad_id to avoid re-fetches on daily runs).
- **Cache:** `PRIOR_DATA` dict loaded from previous `dubai_cars.json` at startup. Listings we've already enriched skip the detail-page fetch.
- **Throttle:** `DETAIL_FETCH_DELAY_S = 2.5` + cap `DETAIL_FETCH_CAP = 18` per model. Prevents Dubizzle bot wall.
- **Bot-wall recovery:** if the Chromium tab gets stuck on a `chrome-error://` page after a `ERR_CONNECTION_CLOSED`, we close and recreate it (`_recycle_page`).
- **Data-loss guard:** at final save, if the new run is < 60% of the prior `dubai_cars.json`, we refuse to overwrite the healthy file and write to `dubai_cars.json.shrunken` instead. Rolling backup at `dubai_cars.json.bak`.

### Sunroof detection
- Regex `SUNROOF_PATTERNS` matches `sunroof | sun roof | moonroof | moon roof | panoramic roof | panoramic sunroof` (case-insensitive).
- Sources scanned: listing title, features list, description, and raw detail-page HTML as a fallback.

## Apartments — `Apartment Search - Dubai/scrape_apartments.py`

### The crucial bot-wall trick

Bayut + PropertyFinder both **silently degrade** when they detect headless Chromium:
- They return a page that looks valid (1MB HTML, has `window.state`) but the `search.hits` array is empty.
- No error, no challenge page — just no data.

**Unlock:** **Patchright** (drop-in Playwright replacement) running with `headless: false` + `--window-position=-2400,-2400` + `--window-size=1920,1080`. The browser is fully real (passes fingerprinting) but lives at coordinates the user never sees.

```python
browser = pw.chromium.launch(
    headless=False,                # CRITICAL: True → empty results
    channel="chromium",
    args=[
        "--window-position=-2400,-2400",  # off-screen
        "--window-size=1920,1080",
        "--disable-blink-features=AutomationControlled",
    ],
)
```

Vanilla Playwright with stealth plugins is reported as "largely ineffective" against modern Cloudflare / fingerprinting in 2026; Patchright actively patches Chromium internals (TLS JA4 fingerprint, navigator properties).

### Sources
1. **Bayut** — primary. Per-area URLs `bayut.com/to-rent/apartments/dubai/{slug}/`. Parses the embedded `window.state` JSON.
   - Main results: `state.algolia.content.hits`
   - Recommendations: `state.search.recommendations.data.recommenderHits`
   - URL template: `https://www.bayut.com/property/details-{externalID}.html`
   - Image CDN: `https://images.bayut.com/thumbnails/{coverPhoto.id}-800x600.jpeg`
2. **PropertyFinder** — secondary. Dubai-wide search sorted by price ASC, paginated up to 20 pages, post-filtered by DAFZA-tier areas.
   - Parses `__NEXT_DATA__ → props.pageProps.searchResult.listings`.
   - Listings wrapped as `{listing_type:"property", property:{...}}`.

### DAFZA tier filter

Validated against [Bayut's official "best near DAFZA Metro" article](https://www.bayut.com/mybayut/top-residential-areas-near-dafza-metro-station/). Areas Bayut recommends (Al Twar, Al Qusais, Al Nahda, Deira) all in tier 1–2.

`AREA_TIERS` is a list of `(regex, tier, display_name)`. Used in:
- `_match_area(location_string)` — invoked on PF listings for post-filtering.
- Bayut per-area URLs use the tier from `BAYUT_AREAS` directly.

### Why Bayut's `?price_to=72000` URL filter doesn't work

Bayut returns higher-priced listings despite the URL param. Our post-filter (`if price > MAX_PRICE_AED: continue`) catches it. This is why Mirdif and Festival City currently yield 0 listings: their 1BHK furnished start at AED 86K+.

## Common patterns

- Both scrapers log to a per-folder `scrape_log.txt` (appended).
- Both write JSON + CSV side by side.
- Both end with calling the matching `prep_data.py` to regen the frontend's `data.js`.
- Both can be triggered via Telegram bot's `/refresh` command.

## When to manually intervene

| Symptom | Likely cause | Fix |
|---|---|---|
| 0 listings after a run | IP-blocked by Dubizzle / Bayut | Wait 1–4 h, re-run. Data-loss guard preserves last good file. |
| Same listings every day | Cache too aggressive | Delete `*.json.bak` and re-run; or clear the JSON file. |
| Patchright crash on startup | Orphaned Chromium holding `.cache` lock | `Stop-Process -Name chromium`; rerun. |
| Sunroof count collapses | Dubizzle JSON shape changed | See SCRAPERS.md "detail-page enrichment" → re-test selectors. |
