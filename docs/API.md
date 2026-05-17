# API — FastAPI service over the SQLite store

Single-port (8090) read-only REST API. Source of truth is `db/dubai_hunt.db`.

## Endpoints

| Method | Path | What |
|---|---|---|
| GET | `/` | Healthcheck + version |
| GET | `/stats` | Headline counts (cars + apartments) |
| GET | `/cars` | List cars (filters via query params) |
| GET | `/cars/{ad_id}` | One car |
| GET | `/apartments` | List apartments (filters via query params) |
| GET | `/apartments/{ad_id}` | One apartment |

## `/cars` query params

| Param | Type | Example | Meaning |
|---|---|---|---|
| `has_sunroof` | bool | `true` / `false` | filter by sunroof flag |
| `max_price` | int | `15000` | yearly cap in AED |
| `min_price` | int | `8000` | yearly floor |
| `max_km` | int | `200000` | mileage cap |
| `min_year` | int | `2010` | minimum model year |
| `brand` | str | `Honda Civic` or `Honda` | LIKE match on canonical brand |
| `source` | str | `Dubizzle` | exact match |
| `location` | str | `Deira` | LIKE match on location string |
| `sort` | str | `sunroof_then_price` (default), `price_asc`, `price_desc`, `year_desc`, `km_asc`, `newest` | order |
| `limit` | int | `50` (default), max `500` | rows returned |
| `include_inactive` | bool | `true` | also return rows scrapers haven't re-seen |

## `/apartments` query params

| Param | Type | Example | Meaning |
|---|---|---|---|
| `max_monthly` | int | `6000` | monthly AED ceiling |
| `max_yearly` | int | `72000` | yearly AED ceiling |
| `max_tier` | int | `2` | commute tier (1=DAFZA, 4=far) |
| `area` | str | `Al Qusais` | LIKE match on area OR full_location |
| `amenity` | str | `gym` | LIKE match on amenities |
| `min_size_sqft` | int | `500` | size floor |
| `sort` | str | `tier_then_price` (default), `price_asc`, `price_desc`, `size_desc`, `newest` | order |
| `limit` | int | `50` (default), max `500` | rows returned |
| `include_inactive` | bool | `true` | also return rows scrapers haven't re-seen |

## Response shape

```jsonc
// GET /cars?has_sunroof=true&max_price=15000&limit=3
{
  "count": 3,
  "results": [
    {
      "ad_id":       "dubizzle_...",
      "source":      "Dubizzle",
      "title":       "Honda Civic 2011 GCC | NEW TYRES ...",
      "brand":       "Honda Civic",
      "year":        2011,
      "km":          520000,
      "price_aed":   11000,
      "transmission":"Automatic",
      "has_sunroof": true,
      "features":    ["Sunroof", "Air Conditioning", ...],
      "url":         "https://dubai.dubizzle.com/...",
      "image":       "https://...jpeg",
      "scraped_at":  "2026-05-17T14:01:31",
      "first_seen_at":"2026-05-14T20:25:39",
      "is_active":   true
    }
  ]
}
```

## Run it

```powershell
# Manual start
cd "C:\Users\Lenovo\Desktop\dubai cars\api"
.\start_api.bat
# or
python -X utf8 -m uvicorn api.main:app --host 127.0.0.1 --port 8090

# Auto-starts at logon (scheduled task)
Get-ScheduledTask -TaskName DubaiHunt_API
Start-ScheduledTask -TaskName DubaiHunt_API
```

## Built-in OpenAPI docs

When the API is running, FastAPI exposes:
- `http://127.0.0.1:8090/docs` — Swagger UI
- `http://127.0.0.1:8090/redoc` — ReDoc
- `http://127.0.0.1:8090/openapi.json` — raw OpenAPI 3.1 spec

Use Swagger UI to try queries interactively in your browser.

## CORS

Currently `allow_origins=["*"]` (read-only personal use). If you ever tunnel it publicly, lock this down to the tunnel URL.

## Errors

- `404` — listing not found (one-listing endpoints).
- `422` — bad query param type (FastAPI's validation).
- `500` — DB unavailable. Check the API log.

## Where the bot fits

The Telegram bot's `query_cars` / `query_apartments` / `get_stats` tools call this API over `http://127.0.0.1:8090`. If the API is down, the bot **falls back to reading the JSON files directly** so it never goes silent.
