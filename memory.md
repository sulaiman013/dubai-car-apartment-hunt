# Memory — user preferences + ongoing decisions

## About the user

- **Name:** Sulaiman (@Smann on Telegram, Telegram ID `8760034436`)
- **Role:** Data Engineer at **Heidelberg Materials Trading**, office in **DAFZA** (Dubai Airport Free Zone — Green Line metro stop named "Dubai Airport Free Zone")
- **Location:** Bangladesh (GMT+6) — laptop runs here, scrapes/bots run on his time zone
- **WhatsApp Business:** +8801320357459 — primary phone number
- **WhatsApp Personal:** +8801726079568 — secondary
- **Telegram bot:** [@Dubai_013_bot](https://t.me/Dubai_013_bot)

## Hard preferences locked in

### Cars
- **Total cash budget:** AED 20,000
- **Reserved for post-buy maintenance:** AED 5,000 → effective acquisition budget: AED 15,000
- **Sunroof:** strong preference (we surface it as the headline feature)
- **Models initially named:** Hyundai Elantra, Honda Civic, Mitsubishi Lancer EX
- **Models added per his Telegram message (expanded list):**
  Toyota Yaris, Corolla, Camry, Avalon, Prius
  Honda Civic, Accord, City, Jazz
  Hyundai Elantra, Accent, Sonata, Creta
  Kia Cerato, Picanto, Rio
  Suzuki Swift, Baleno, Ciaz, Dzire
  Mazda 3, Mazda 6
  Mitsubishi Lancer EX, Attrage
  Chevrolet Aveo
  Nissan Sunny

### Apartments
- **Bedrooms:** 1 BHK strictly
- **Furnishing:** **Furnished only**
- **Yearly budget:** AED 70,000–72,000
- **Monthly budget:** AED 6,000
- **Commute:** **MUST be conveniently commutable to DAFZA**. Only Dubai-side, only tiers 1-3. Tier 4 areas are explicitly excluded — see "rejected areas" below.

**Allowed areas (tiered by drive time to DAFZA):**
- **Tier 1 (5-10 min):** Al Qusais, Al Twar, Hor Al Anz, **Al Nahda (Dubai)** ← next Green Line stop after DAFZA
- **Tier 2 (10-15 min):** Al Garhoud, Al Rashidiya, Deira, Al Mamzar (Dubai side), Al Rigga, Naif, Al Muraqqabat, Al Khabaisi, Port Saeed, Abu Hail
- **Tier 3 (15-20 min):** Mirdif, Dubai Festival City, Al Karama, Al Satwa, Bur Dubai

**REJECTED areas (do not re-add without explicit user re-approval):**
- International City — too far west, 25-35 min drive
- Discovery Gardens — Jebel Ali side, 40+ min
- Dubai Silicon Oasis (DSO) — south Dubai, ~25 min
- Al Nahda Sharjah — cross-emirate rush-hour pain
- Al Taawun Sharjah — Sharjah-side

## Decisions made (chronological)

- **2026-05-14** — Project bootstrapped. Started with WhatsApp Business `+880…3459` as the only number.
- **2026-05-14** — Switched cars scraper from Selenium+Chrome to Playwright+Chromium (no Chrome installed on this Lenovo).
- **2026-05-14** — Cars dashboard frontend swapped for the "UI demo" editorial dark theme (kept + extended for apartments).
- **2026-05-14** — Apartment scraper required **Patchright** (drop-in Playwright replacement) because Bayut + PropertyFinder both bot-walled vanilla Playwright. **Invisible-headed mode** (`headless=False` + `--window-position=-2400,-2400`) was the unlock — see @docs/SCRAPERS.md.
- **2026-05-16** — Cloudflare Quick Tunnel set up to phone-access dashboards. URL changes each restart; landing page at root links to both dashboards.
- **2026-05-17 (today)** — WhatsApp bot was attempted via `whatsapp-web.js`; abandoned because library doesn't reliably fire events for self-chat or for second-account-on-same-device flows. Pivoted to **Telegram bot** with OpenRouter + Gemini 3.1 Flash Lite Preview. Working end-to-end.
- **2026-05-17** — Allowlist locked to TG user `8760034436`. Bot autostart registered (`DubaiHunt_TGbot` scheduled task).
- **2026-05-17** — Markdown leaked into bot replies. Switched bot to **plain text** + LLM prompt forbids markdown + post-strip safety net.
- **2026-05-17** — Added `/refresh cars | apartments | all` with 5-min cooldown to trigger on-demand scrapes from Telegram.

## Open follow-ups

- Rotate **OpenRouter API key** (was pasted in chat) → https://openrouter.ai/keys.
- Rotate **Telegram token** if concerned (BotFather `/revoke`).
- Consider running an **early-morning re-scrape** (06:00 BD) for fresh weekend listings before checking before work.
- **YallaMotor scraping** still returns 0 — their listing JSON-LD ItemList disappeared. Out of scope unless we want to add a DOM-based scraper.

## Honest caveats kept in mind

- **Cars: Bayut equivalents not included** — we use Dubizzle + DubiCars for cars. Bayut is property-only.
- **Apartments: Bayut's `price_to` URL filter is broken** — they return higher-priced. Our post-filter catches it. That's why some areas (Mirdif, Festival City) return 0 — Dubai-side 1BHK furnished start at AED 86K+ there.
- **Bot-wall risk** if user spams `/refresh`. 5-min cooldown protects us.
- **Telegram bot ≠ WhatsApp.** User's original ask was WhatsApp; we pivoted because `whatsapp-web.js` is unreliable for self-chat. If WhatsApp ever becomes mandatory, options are: Twilio Sandbox (zero ban risk, ~$0.005/msg) or `whatsapp-web.js` with a second WhatsApp account on a different SIM.
