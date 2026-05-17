# Architecture

## Big picture

```
                ┌───────────────────────────────────────────────────┐
                │  Sources (UAE car + property marketplaces)        │
                │  • Dubizzle UAE  • DubiCars  • Bayut  • PF        │
                └────────────┬──────────────────────────────────────┘
                             │   (Patchright invisible-headed bypass)
                             ▼
            ┌────────────────────────────────────┐
  18:00 BD  │ Cars scraper (Python + Playwright) │
            │ scrape_dubai_cars.py               │
            └────────────────┬───────────────────┘
                             │
            ┌────────────────┴───────────────────┐
            │      dubai_cars.json  +  .csv      │  ←─── source of truth
            └────────────────┬───────────────────┘
                             │
                ┌────────────┴───────────┐
                ▼                        ▼
       prep_data.py             Telegram bot tools
       (scores + writes         (query_cars,
        data.js for             query_apartments,
        the dashboard)          get_stats)
                │                        │
                ▼                        ▼
       Dashboard (HTML/CSS/JS)   @Dubai_013_bot
       opened locally OR via      (Node + native fetch)
       cloudflared tunnel         OpenRouter → Gemini

  Same shape exists for apartments (18:30 BD task, apartments.json).
```

## Component responsibilities

### 1. Scrapers
- **Cars** — `Car Search - Dubai UAE/scrape_dubai_cars.py`
  - Sources: Dubizzle UAE (primary), DubiCars (secondary).
  - Uses **vanilla Playwright** (Dubizzle didn't need stealth for cars).
  - Targets a list of brand/model URLs (`TARGETS` at top of file).
  - Detail-page enrichment fetches features + sunroof keyword for listings missing structured data.
  - Output: `dubai_cars.json` + `dubai_cars.csv`.
- **Apartments** — `Apartment Search - Dubai/scrape_apartments.py`
  - Sources: Bayut (primary, per-area URLs), PropertyFinder (Dubai-wide + tier filter).
  - Uses **Patchright** with `headless=False` + window positioned off-screen (`--window-position=-2400,-2400`). Vanilla Playwright is detected by Bayut.
  - DAFZA-tier post-filter (tiers 1–4 by commute time, validated against Bayut's official "best near DAFZA metro" article).
  - Output: `apartments.json` + `apartments.csv`.

### 2. Dashboards
- Static files only. No build step, no framework.
- `prep_data.py` reads the source JSON, computes a score (8 sub-scores for cars, 6 for apartments), writes `data.js` exposing `window.CAR_DATA` / `window.APT_DATA` + `_STATS`.
- `index.html` + `app.js` + `styles.css`. Same dark-mode editorial theme (Inter + JetBrains Mono).
- See @docs/FRONTENDS.md for the full UI inventory.

### 3. Telegram bot
- Single-file Node 24 script (`Telegram Bot/tg_bot.js`).
- No npm dependencies — uses Node's built-in `fetch`.
- Long-polls `api.telegram.org/bot<TOKEN>/getUpdates`.
- Allowlist by numeric user ID.
- LLM = Google Gemini 3.1 Flash Lite Preview via OpenRouter, with **OpenAI-compatible function calling**.
- Tools: `query_cars`, `query_apartments`, `get_stats`. Reads JSON directly from disk on every call.
- `/refresh` keyword spawns the Python scrapers as subprocesses; bot reports back when they exit.
- See @docs/BOT.md.

### 4. Phone access
- `share_via_tunnel.bat` → PowerShell script → starts a local `python -m http.server` on 8765 serving the project root, then launches `cloudflared tunnel --url localhost:8765`. URL is ephemeral, prints to terminal.
- Landing page at root (`index.html`) links to both dashboards.
- See @docs/TUNNEL.md.

## Where the data flows

| Direction | Triggered by | Latency |
|---|---|---|
| Site → JSON | Daily Windows task at 18:00 / 18:30 BD; manual run; `/refresh` from bot | 3–8 min per kind |
| JSON → data.js (frontend) | `prep_data.py` runs at end of every scrape | < 1 s |
| JSON → bot reply | Bot reads on every tool call | ~0 ms (filesystem) |
| LLM tool call | Gemini chooses tool, bot executes, replies streamed | 2–5 s typical |

## Dependencies

### Python
- `playwright` (cars), `patchright` (apartments — drop-in replacement)
- Browsers installed via `python -m playwright install chromium`

### Node
- Node ≥ 18 (we use 24). Built-in `fetch`. No npm deps.

### Binaries
- **Cloudflared** at `C:\Users\Lenovo\cloudflared\cloudflared.exe`. Direct GitHub download (winget was unreliable).

### Cloud services / accounts
- OpenRouter (LLM via API key in `Telegram Bot/.env`)
- BotFather (Telegram bot ID + token)

## What's intentionally NOT here

- No databases. JSON files are simple, diff-friendly, manually inspectable.
- No frameworks on the frontend. The product is one user, ~200 listings; complexity buys nothing.
- No backend server beyond the bot. The dashboard is fully client-side.
- No auth on dashboards. The tunnel URL is the secret; rotate by restarting.
