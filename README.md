# Dubai Hunt 🚗 🏠

Personal data product that scrapes Dubai car listings (≤ AED 20K) and DAFZA-convenient 1BHK furnished apartments (≤ AED 6K/mo), serves them as dashboards and a REST API, and lets you chat with the data on Telegram.

## What's inside

```
┌──────────────────────────────────────────────────────────────────┐
│  Sources                                                         │
│  • Dubizzle UAE  • DubiCars  • YallaMotor  (cars)                │
│  • Bayut         • PropertyFinder         (apartments)           │
└────────────────────────────┬─────────────────────────────────────┘
                             │  Patchright (stealth Chromium)
                             ▼
                  ┌──────────────────────┐
                  │  SQLite (UPSERT)     │  ← canonical source of truth
                  │  db/dubai_hunt.db    │
                  └──────────┬───────────┘
                             │
            ┌────────────────┼───────────────────┐
            ▼                ▼                   ▼
       FastAPI         Telegram bot        Static dashboards
       /stats          (Gemini Flash       (cars · apartments
       /cars           Lite Preview         · ops)
       /apartments     via OpenRouter)
       /admin/health
```

## Live URLs (after deploy)
- `http://<vps-ip>/`                      — landing
- `http://<vps-ip>/Car%20Deals%20Frontend/`     — cars dashboard
- `http://<vps-ip>/Apartment%20Hunt%20Frontend/` — apartments dashboard
- `http://<vps-ip>/Ops%20Dashboard/`             — pipeline + inventory health
- `http://<vps-ip>/docs`                          — Swagger UI for the REST API
- `@Dubai_013_bot` on Telegram                    — natural-language chat

## Telegram bot commands
- `/stats`              — inventory totals
- `/refresh cars`       — re-scrape cars now (5-min cooldown)
- `/refresh apartments` — re-scrape apartments now
- `/refresh all`        — both
- `/help`               — usage examples

You can also ask in plain English: *"show me the cheapest sunroof cars under 15k"*, *"1bhk apartments in Deira"*, etc.

## Local dev quickstart
```bash
# Python deps
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi 'uvicorn[standard]' patchright playwright beautifulsoup4 lxml
python3 -m patchright install chromium

# Node deps (Telegram bot)
cd "Telegram Bot" && npm install && cd ..

# Initialise DB
python3 -X utf8 db/migrate_from_json.py

# Run the API
python3 -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8090

# Run the bot (in another terminal — set Telegram Bot/.env first)
cd "Telegram Bot" && node tg_bot.js
```

## Deploy to a VPS
See [`deploy/README.md`](deploy/README.md). The same `deploy/deploy.sh` works on any Ubuntu 22.04 host (Hostinger / Oracle Cloud / Hetzner / DigitalOcean).

## Folder map
- [`api/`](api/) — FastAPI service (serves API + dashboards on one port in prod)
- [`db/`](db/) — SQLite schema, queries, migration script
- [`Car Search - Dubai UAE/`](Car%20Search%20-%20Dubai%20UAE/) — cars scraper
- [`Apartment Search - Dubai/`](Apartment%20Search%20-%20Dubai/) — apartments scraper
- [`Car Deals Frontend/`](Car%20Deals%20Frontend/) — cars dashboard (static)
- [`Apartment Hunt Frontend/`](Apartment%20Hunt%20Frontend/) — apartments dashboard (static)
- [`Ops Dashboard/`](Ops%20Dashboard/) — pipeline + inventory health (Chart.js)
- [`Telegram Bot/`](Telegram%20Bot/) — Node.js bot
- [`deploy/`](deploy/) — one-shot Linux deploy script + README
- [`docs/`](docs/) — architecture, data model, scrapers, bot, ops, API
- [`tests/`](tests/) — Playwright UAT suite (37 checks)
- [`CLAUDE.md`](CLAUDE.md) — root project context
- [`memory.md`](memory.md) — user preferences + key decisions

## Secrets management
Two `.env` files (both gitignored):
- `Telegram Bot/.env` — `TELEGRAM_TOKEN`, `OPENROUTER_API_KEY`, `ALLOWED_USER_ID`, `MODEL`
- `.env` (project root, optional) — local notes only; not loaded by any script

After deploying to a fresh VPS, copy your local `Telegram Bot/.env` over manually:
```bash
scp 'Telegram Bot/.env' root@<vps-ip>:/root/dubai-hunt/Telegram\ Bot/.env
```

## License
Personal use. No license granted; do not redistribute the scraped data.
