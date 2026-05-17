# Telegram Bot — `@Dubai_013_bot`

Personal natural-language interface to the scraped data. Single-file Node 24 script.

## Files

```
Telegram Bot/
├── tg_bot.js           main script (long-poll + LLM + tools + /refresh)
├── package.json        no dependencies (Node 24's built-in fetch)
├── .env                TG token, user ID, OpenRouter key, model
├── .env.example        with setup instructions
├── start_bot.bat       cmd launcher
├── setup_autostart.ps1 Windows scheduled task at logon
├── bot.log / bot.err   stdout / stderr captures
└── _test_answer.mjs    one-off LLM+tools smoke test
```

## Env vars (in `.env`)

```
TELEGRAM_TOKEN=8773619659:AAG5...    # from @BotFather
ALLOWED_USER_ID=8760034436           # only this Telegram user can chat
OPENROUTER_API_KEY=sk-or-v1-...      # https://openrouter.ai/keys
MODEL=google/gemini-3.1-flash-lite-preview
```

## How a message flows

```
You text @Dubai_013_bot
      │
      ▼
Bot's getUpdates poll picks it up (long-poll 50 s)
      │
      ▼
Allowlist check (must equal ALLOWED_USER_ID)
      │
      ▼
Built-in commands? (/help, /stats, /refresh ...)  yes → reply directly, done
      │ no
      ▼
sendTyping(chatId)  [shows "typing..." indicator]
      │
      ▼
answerQuestion(text)
   │
   │ — system prompt + user message →  OpenRouter (Gemini Flash Lite)
   │
   │ ← tool_calls: [{name: query_cars, args: {...}}, ...]
   │
   │ — execute tool against local JSON →
   │
   │ — feed tool result back to LLM →
   │
   │ ← final text reply
   ▼
stripMarkdown(reply)  → sendMessage(chatId, ...)
```

## Tools the LLM can call

### `query_cars(filters, sort, limit)`
Filters: `has_sunroof`, `max_price`, `min_price`, `max_km`, `min_year`, `brand`, `source`, `location`, `min_score`.
Sort: `sunroof_then_score` (default), `price_asc/desc`, `year_desc`, `km_asc`, `score`.
Returns up to `limit` (default 5, max 10) compact records.

### `query_apartments(filters, sort, limit)`
Filters: `max_monthly`, `max_yearly`, `max_tier`, `area`, `amenity`, `min_size_sqft`.
Sort: `tier_then_price` (default), `price_asc/desc`, `size_desc`.

### `get_stats()`
No args. Returns headline counts for cars + apartments.

## Built-in commands (regex-matched before LLM)

| Command | Behavior |
|---|---|
| `/start`, `/help` | Show help text |
| `/stats` | Inventory totals |
| `/refresh cars` | Spawn cars scraper subprocess |
| `/refresh apartments` (or `/refresh apt`) | Spawn apartments scraper subprocess |
| `/refresh all` (or `both`) | Both, sequentially |

`refresh` keyword **also works without the leading slash** (`refresh cars`).

## `/refresh` semantics

- **5-minute cooldown** per kind (`REFRESH_COOLDOWN_MS`).
- **One in-flight scrape per kind** (`inFlight[kind]`).
- Bot replies immediately:
  > "Refreshing cars now… this can take 3–8 minutes. I'll ping you when done."
- On subprocess exit, bot replies with:
  - Success: total / sunroof / under-20k breakdown
  - Failure: exit code + last 300 chars of stderr

Spawned as `python -X utf8 <script>` with `cwd=<scraper dir>`, `windowsHide: true`.

## Formatting discipline

Telegram parse modes break easily when LLMs emit unbalanced markdown. We chose **plain text only**:

1. **System prompt** explicitly forbids markdown:
   > "STRICT FORMATTING RULES: Do NOT use markdown: no asterisks, no underscores, no [text](url), no backticks, no #headings. Use line breaks for structure. Use the • character for bullets."
2. **`stripMarkdown(text)`** is a final safety net that:
   - Removes `**bold**` and `*emphasis*`
   - Removes `_italic_`
   - Replaces `[label](url)` with `label url`
   - Removes inline backticks
   - Converts leading `- ` or `* ` to `• `
   - Strips `#` headings

URLs are still preview-able in Telegram even without explicit markdown formatting.

## Allowlist + safety

- Hard match on numeric Telegram user ID (`from.id`).
- Mismatched users get **silent ignore** (no reply, no log of body) to avoid revealing bot existence.
- Bot's username is reasonably anonymous (`Dubai_013_bot`); no profile picture/about set unless user adds via BotFather.

## Local control

```powershell
# Status
Get-Process node | Select-Object Id, StartTime

# Stop
Stop-Process -Name node

# Start (foreground, see logs)
cd "Telegram Bot"; node tg_bot.js

# Start via scheduled task (background)
Start-ScheduledTask -TaskName DubaiHunt_TGbot

# Tail logs
Get-Content "Telegram Bot/bot.log" -Tail 20 -Wait
```

## OpenRouter cost

- `google/gemini-3.1-flash-lite-preview` is cheap. Typical question ≤ 0.001 USD (often free under their preview tier).
- Per question: 1 system prompt + 1 user msg + 1–3 tool round trips + 1 final reply. ~1–3K tokens per turn.

## Known limits / gotchas

- **One bot instance per token.** Two `getUpdates` pollers will hit 409 Conflict. Always stop the old process before starting a new one. We wait 10 s after stopping for Telegram's long-poll lease to expire.
- **The bot ignores the FIRST `/start` after pairing** unless `ALLOWED_USER_ID` is set or empty. Set it to capture the user ID, then lock it down.
- **Subprocess scrape eats CPU on the laptop.** Patchright spawns Chromium. If you're in a 60-fps game, hold off on `/refresh`.
