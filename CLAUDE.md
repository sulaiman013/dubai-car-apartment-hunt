# Dubai Hunt — Project Context

A personal data product for **Sulaiman** (Data Engineer at Heidelberg Materials Trading, DAFZA):
- **Cars dashboard** — used cars in Dubai ≤ AED 20,000 (with AED 5K kept aside for maintenance, effective car budget AED 15K).
- **Apartments dashboard** — 1BHK furnished, DAFZA-adjacent, ≤ AED 6,000/month (≤ AED 70–72K/year).
- **Telegram bot** — natural-language queries against the scraped data, plus on-demand re-scrape triggers.

Everything is **personal use, single user, Bangladesh time zone (GMT+6)**.

## Tech stack at a glance

| Layer | What | Where |
|---|---|---|
| **DB** | SQLite (canonical truth, UPSERT, no overwrites) | `db/dubai_hunt.db` |
| **API** | FastAPI (read-only REST) on port 8090 | `api/main.py` |
| Scrapers | Python 3.13 + Patchright (invisible-headed bot-wall bypass) — UPSERT into SQLite, also dump JSON snapshots | `Car Search - Dubai UAE/`, `Apartment Search - Dubai/` |
| Frontends | Vanilla HTML/CSS/JS, dark-mode editorial UI | `Car Deals Frontend/`, `Apartment Hunt Frontend/` |
| Bot | Node 24 + native `fetch` (no libs), OpenRouter → Gemini Flash Lite Preview; calls the API, falls back to JSON if API is down | `Telegram Bot/` |
| Phone access | Cloudflare Quick Tunnel + Python `http.server` | `share_via_tunnel.bat` |
| Scheduler | Windows Task Scheduler | various `setup_*.ps1` |

## Folder map (root = `c:/Users/Lenovo/Desktop/dubai cars/`)

```
.
├── CLAUDE.md                        ← this file
├── memory.md                        ← user prefs + ongoing context
├── db/
│   ├── schema.sql                   ← SQLite tables (cars, apartments, scrape_runs)
│   ├── db.py                        ← shared helpers (upsert_car, upsert_apartment)
│   ├── queries.py                   ← read-side filters used by API + bot
│   ├── migrate_from_json.py         ← one-shot: existing JSON → SQLite
│   └── dubai_hunt.db                ← THE DATABASE (canonical truth)
├── api/
│   ├── main.py                      ← FastAPI service (port 8090)
│   └── start_api.bat                ← cmd launcher
├── docs/
│   ├── ARCHITECTURE.md              ← system flow
│   ├── DATA_MODEL.md                ← DB + JSON schemas
│   ├── SCRAPERS.md                  ← how scrapers work + bot-wall tricks
│   ├── API.md                       ← REST endpoints + query params
│   ├── FRONTENDS.md                 ← dashboards + UAT
│   ├── BOT.md                       ← Telegram bot internals
│   ├── TUNNEL.md                    ← cloudflared phone access
│   └── OPERATIONS.md                ← daily routines, troubleshooting, secrets
├── index.html                       ← landing page (linked from tunnel)
├── share_via_tunnel.{ps1,bat}       ← phone access launcher
├── Car Search - Dubai UAE/          ← cars scraper
│   ├── scrape_dubai_cars.py
│   ├── dubai_cars.json              ← live data
│   ├── dubai_cars.csv               ← live data (spreadsheet view)
│   └── setup_daily_scraper.ps1      ← scheduled task (18:00 BD)
├── Car Deals Frontend/              ← cars dashboard
│   ├── index.html
│   ├── app.js · styles.css
│   ├── prep_data.py                 ← rescore + emit data.js
│   └── data.js                      ← generated
├── Apartment Search - Dubai/        ← apartments scraper
│   ├── scrape_apartments.py
│   ├── apartments.json
│   └── apartments.csv
├── Apartment Hunt Frontend/         ← apartments dashboard (same shape as cars)
├── Telegram Bot/                    ← live chat (@Dubai_013_bot)
│   ├── tg_bot.js
│   ├── package.json
│   ├── .env                         ← TG token, allowlist, OpenRouter key
│   └── setup_autostart.ps1
└── tests/uat_frontend.py            ← Playwright UAT for cars dashboard (37 checks)
```

## Loaded sub-docs

Read these files for deeper context as needed:
- @docs/ARCHITECTURE.md — system-level flow + dependencies
- @docs/DATA_MODEL.md — DB tables + JSON snapshots
- @docs/SCRAPERS.md — how each scraper works, bot-wall workarounds
- @docs/API.md — REST endpoints + query params (FastAPI on :8090)
- @docs/BOT.md — Telegram bot tools, commands, refresh logic
- @docs/FRONTENDS.md — dashboards + UAT suite
- @docs/TUNNEL.md — phone access via cloudflared
- @docs/OPERATIONS.md — daily ops, scheduled tasks, secrets, troubleshooting
- @memory.md — user preferences, decisions, history

## Quick commands

```bash
# Force re-scrape now (cars)
python -X utf8 "Car Search - Dubai UAE/scrape_dubai_cars.py"

# Force re-scrape now (apartments)
python -X utf8 "Apartment Search - Dubai/scrape_apartments.py"

# Regenerate frontend data only
python -X utf8 "Car Deals Frontend/prep_data.py"
python -X utf8 "Apartment Hunt Frontend/prep_data.py"

# Phone access (Cloudflare Quick Tunnel)
powershell -ExecutionPolicy Bypass -File share_via_tunnel.ps1

# Bot manual control
Stop-Process -Name node                              # stop
cd "Telegram Bot"; node tg_bot.js                    # start in foreground
Start-ScheduledTask -TaskName DubaiHunt_TGbot        # via scheduler

# UAT (cars dashboard)
python -X utf8 tests/uat_frontend.py
```

## Scheduled Windows tasks

| Task name | Trigger | What it does |
|---|---|---|
| `DubaiCarHunt_Daily` | Daily 18:00 BD | Cars scrape → UPSERT to SQLite + JSON snapshot |
| `DubaiApartmentHunt_Daily` | Daily 18:30 BD | Apartments scrape → UPSERT to SQLite + JSON snapshot |
| `DubaiHunt_API` | At user logon | FastAPI on `127.0.0.1:8090` |
| `DubaiHunt_TGbot` | At user logon | Telegram bot (calls API) |

## Conventions

- **All dates** are stored ISO-8601 (`%Y-%m-%d`).
- **All prices** in AED. `price_aed` (cars: total; apartments: yearly). `monthly_aed` derived.
- **SQLite is the canonical source of truth.** JSON snapshots are derived (legacy + manual inspection).
- **Scrapers UPSERT** — they never delete. If a listing isn't seen this run, it gets `is_active=0` but stays in the DB. No more overwrite-loses-data bugs.
- **Bot calls the API** (`localhost:8090`). Falls back to JSON if the API is down.
- **Dashboards still read `data.js`** for now (no UI rewrite). prep_data.py regenerates it at end of each scrape.
- **Patchright `headless=False` + window-position=-2400,-2400** is the bot-wall bypass for Bayut + Dubizzle. See @docs/SCRAPERS.md.
