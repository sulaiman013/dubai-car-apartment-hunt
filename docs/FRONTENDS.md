# Frontends — Cars + Apartments Dashboards

Two static-file dashboards, same dark-mode editorial design. Built from a "UI demo" provided early in the project.

## Layout

Both pages share the same anatomy:

```
┌──────────────────────────────────────────────────────────────┐
│ TOP STRIP (sticky)                                           │
│ brand / sub  │  metaline: live counts · refreshed Xm ago     │
│ + "→ Apartments" or "→ Cars" link to switch                  │
├──────────────────────────────────────────────────────────────┤
│ TOOLBAR (sticky)                                             │
│ [/search]  [select]  [select]  [range popover]  ...  [sort]  │
│ [chips]                                       [view toggle]  │
├──────────────────────────────────────────────────────────────┤
│ FEEDHEAD                                                     │
│ "65 of 65 listings · 12 with sunroof"   [color legend]       │
│                                                              │
│ LIST view (default) — dense rows                             │
│ GRID view — photo cards                                      │
│                                                              │
│ EMPTY state — when filters yield nothing                     │
│ SENTINEL — for infinite scroll                               │
└──────────────────────────────────────────────────────────────┘
+ Modal: per-listing details + score breakdown + features
+ Foot: kbd shortcuts
```

## Cars dashboard — `Car Deals Frontend/`

Reads `window.CAR_DATA` (see @docs/DATA_MODEL.md).

### Filters
- Search (title, brand, location, features, description)
- Brand select (multi-source-of-truth list)
- Source select (Dubizzle / DubiCars / YallaMotor)
- Max price range popover
- Min score range popover

### Chips
- ☀️ Sunroof only
- ≤ 20K AED
- Low km (< 150k)
- Top 20
- Owner only

### Sort
- Sunroof first, then score (default)
- Best score
- Price asc / desc
- Newest year
- Lowest mileage

### Sunroof emphasis
- Gold left border on row
- Gold price color
- Gold "SUNROOF" tag inside title
- Stat in top strip + feedhead

### Keyboard
- `/` focus search
- `g` grid view, `l` list view
- `Esc` close modal

## Apartments dashboard — `Apartment Hunt Frontend/`

Mirrors the cars design.

Differences:
- **Tier-based color theme** instead of sunroof gold. Tier 1 = green, Tier 2 = blue, Tier 3 = amber, Tier 4 = red.
- Sort default: "Closest to DAFZA" (tier asc, then price asc).
- Filters: max monthly AED (slider), max commute tier (slider), area, source, amenity.
- Chips: T1 only / ≤ 5K AED / parking / gym & pool / ≥ 600 sqft.
- Modal additions: bedrooms / bathrooms / size / amenities / broker / agent.

## Data regeneration

```bash
# After scraping, prep_data.py is auto-run:
python -X utf8 "Car Deals Frontend/prep_data.py"
python -X utf8 "Apartment Hunt Frontend/prep_data.py"

# Outputs window.{CAR|APT}_DATA + window.{CAR|APT}_STATS into data.js
```

## Scoring (cars)
8-axis composite, all 0–100, weights in `prep_data.py`:
- `price` (0.20) — favors 12–16K AED
- `mileage` (0.16) — favors below model-specific lifetime
- `age` (0.10) — favors model's sweet-year range
- `reliability` (0.12) — fixed per-model 0–10
- `kpy` (0.10) — km/year sanity
- `value` (0.10) — price-per-year-of-age ratio
- `transmission` (0.04) — automatic preferred
- `sunroof` (0.18) — explicit boolean signal

## Scoring (apartments)
6-axis composite:
- `commute` (0.40) — tier-based
- `budget` (0.25) — favors cheap monthly
- `size` (0.15) — bigger = better
- `amenities` (0.10) — parking / gym / pool / balcony / security keywords
- `bathrooms` (0.05) — 2+ is a plus
- `image` (0.05) — image presence (visual confidence)

## UAT — `tests/uat_frontend.py`

Playwright suite, 37 checks against the cars dashboard:
- Page chrome (title, stats, refreshed label)
- Default render (sunroof-first, 60-row progressive load)
- Filters (search, brand, source, sunroof, budget, top-20, owner, price slider, score slider)
- Sort (price asc, year desc)
- View toggle (list ↔ grid)
- Keyboard (/, g, l)
- Modal (open, fields, score bars, features, link, close via Esc + backdrop)
- Empty state (appear + clear)
- Sunroof emphasis (tag + color)
- Responsive (390×844 no horizontal scroll)
- Dynamic counts

Re-run any time:
```bash
python -X utf8 tests/uat_frontend.py
```

Pass criteria: **37/37**.

## Apartments UAT
Not yet written — the apartments dashboard reuses 90% of the cars logic and visually inherits its behavior. UAT TBD if the user wants it.

## Known UI caveats

- `.list[hidden], .grid[hidden] { display: none !important }` is required to override `display: flex/grid` defaults. Without it, the `hidden` attribute is silently overridden.
- Sunroof rows use `oklch()` colors. Older Chromium returns `rgb()` for computed style; tests must accept both.
- Tunnel-served pages depend on the same-origin sibling folders. URL must keep the `/Car%20Deals%20Frontend/...` path.
