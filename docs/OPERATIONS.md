# Operations — Daily Routine, Secrets, Troubleshooting

## Daily routine (automatic)

| Time (BD, GMT+6) | What happens |
|---|---|
| Every logon | `DubaiHunt_TGbot` starts → bot online on Telegram |
| 18:00 | `DubaiCarHunt_Daily` runs cars scraper |
| 18:30 | `DubaiApartmentHunt_Daily` runs apartments scraper |
| After each scrape | Frontends auto-regenerate `data.js` |

You don't have to do anything. The next time you open the dashboard or message the bot, fresh data is there.

## Manual triggers

```powershell
# Run a scrape now (foreground, see logs)
python -X utf8 "Car Search - Dubai UAE\scrape_dubai_cars.py"
python -X utf8 "Apartment Search - Dubai\scrape_apartments.py"

# Or via scheduled task
Start-ScheduledTask -TaskName DubaiCarHunt_Daily
Start-ScheduledTask -TaskName DubaiApartmentHunt_Daily
```

```text
From Telegram:
  /refresh cars
  /refresh apartments
  /refresh all
```

## Scheduled task control

```powershell
# List all our tasks
Get-ScheduledTask | Where-Object { $_.TaskName -like "DubaiHunt*" -or $_.TaskName -like "DubaiCarHunt*" -or $_.TaskName -like "DubaiApartmentHunt*" }

# Disable temporarily
Disable-ScheduledTask -TaskName DubaiCarHunt_Daily

# Re-enable
Enable-ScheduledTask -TaskName DubaiCarHunt_Daily

# Remove
Unregister-ScheduledTask -TaskName DubaiCarHunt_Daily -Confirm:$false

# Recreate
powershell -ExecutionPolicy Bypass -File "Car Search - Dubai UAE\setup_daily_scraper.ps1"
```

## Bot control

```powershell
# Status (is the bot running?)
Get-Process node | Select-Object Id, StartTime

# View logs
Get-Content "Telegram Bot\bot.log" -Tail 50
Get-Content "Telegram Bot\bot.err" -Tail 50

# Restart cleanly (drop session, wait, start fresh)
Stop-Process -Name node
Start-Sleep -Seconds 10        # let Telegram release the long-poll lease
Start-ScheduledTask -TaskName DubaiHunt_TGbot
```

## Secrets inventory

| Secret | Where stored | Risk if leaked |
|---|---|---|
| `OPENROUTER_API_KEY` | `Telegram Bot/.env` | Someone can drain your OpenRouter credit |
| `TELEGRAM_TOKEN` | `Telegram Bot/.env` | Someone can hijack the bot account |
| Tunnel URL | Console (ephemeral) | Random snoop could browse listings |
| Cloudflared binary | `~/cloudflared/cloudflared.exe` | No secret stored |

### Rotate the OpenRouter key
1. Visit https://openrouter.ai/keys
2. **Delete** the old key
3. Click **Create Key**, name it (e.g., "dubai-hunt-tg-bot")
4. Copy the new key
5. Edit `Telegram Bot/.env` — replace `OPENROUTER_API_KEY=...`
6. Restart the bot: `Stop-Process -Name node; Start-Sleep 10; Start-ScheduledTask DubaiHunt_TGbot`

### Rotate the Telegram token
1. Open Telegram → @BotFather → `/revoke`
2. Pick `@Dubai_013_bot`
3. BotFather replies with a new token
4. Edit `.env` → `TELEGRAM_TOKEN=...`
5. Restart bot (same as above)

## Common troubleshooting

### Bot is silent
1. Check process: `Get-Process node`
2. Check log: `Get-Content "Telegram Bot\bot.log" -Tail 20`
3. Common cause: Telegram 409 conflict from a phantom process. Stop all `node`, wait 30 s, start once.

### Scraper returns 0 listings
1. Likely bot wall. Wait 1–4 hours, re-run.
2. Check `*_log.txt` for "no __NEXT_DATA__ after retries".
3. Verify older `.json.bak` is intact (data-loss guard).

### Dashboard shows old data
1. Hard refresh browser (Ctrl+Shift+R).
2. Tail the latest scrape log — was `prep_data.py` called at the end?
3. Manually run `python -X utf8 "Car Deals Frontend/prep_data.py"`.

### Phone tunnel URL expired
1. Re-run `share_via_tunnel.bat` — new URL prints in the cmd window.

### Patchright complains about lock files
```powershell
Get-Process chromium, chrome | Stop-Process -Force
Get-ChildItem "Apartment Search - Dubai\.auth\session" -Filter "Singleton*" -Recurse | Remove-Item -Force
```

### LLM replies are garbled markdown
1. `tg_bot.js` should already strip markdown. If you see leftover `*` or `[ ](...)`, the LLM is sneaking new patterns through.
2. Update `stripMarkdown()` regex set.

## Backup recommendations

Manually back up monthly:
- `*/dubai_cars.json`
- `*/apartments.json`
- `Telegram Bot/.env` (keep it offline!)

The frontends and scrapers can be regenerated from `git` (if you add one) or from this project tree. The data is what matters.

## Disk hygiene

| Folder | Approx size | Safe to delete? |
|---|---|---|
| `Telegram Bot/node_modules/` | < 1 MB (no deps) | regenerate via `npm install` |
| `Apartment Search - Dubai/.auth/` | ~100 MB | No — Patchright auth cache; deletion = re-pair NOT needed (no QR for Bayut) but heavy re-download |
| `tests/_screenshots/` | varies | Yes — only regenerated on UAT failures |
| `*.bak`, `*.shrunken` | tiny | Keep for now (data-loss guard outputs) |
