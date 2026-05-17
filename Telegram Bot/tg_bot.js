// ============================================================
//  Dubai Hunt — Telegram bot
//  Long-polls api.telegram.org/getUpdates; routes natural-language
//  questions through OpenRouter (Gemini); answers from the local
//  scraped JSON for cars + apartments.
//
//  No npm libraries needed beyond Node 18+'s built-in `fetch`.
// ============================================================
import { promises as fs } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { spawn } from 'child_process';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(__dirname);
const CARS_JSON = path.join(ROOT, 'Car Search - Dubai UAE', 'dubai_cars.json');
const APT_JSON  = path.join(ROOT, 'Apartment Search - Dubai', 'apartments.json');
const API_BASE  = process.env.API_BASE || 'http://127.0.0.1:8090';

// ─── env loader ───────────────────────────────────────────────────────────────
async function loadDotEnv(p) {
  try {
    const txt = await fs.readFile(p, 'utf-8');
    const out = {};
    for (const line of txt.split('\n')) {
      const m = line.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)\s*$/);
      if (m && !line.trim().startsWith('#')) out[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
    }
    return out;
  } catch { return {}; }
}
const ENV = await loadDotEnv(path.join(__dirname, '.env'));
const TELEGRAM_TOKEN     = ENV.TELEGRAM_TOKEN;
const ALLOWED_USER_ID    = parseInt(ENV.ALLOWED_USER_ID || '0');
const OPENROUTER_API_KEY = ENV.OPENROUTER_API_KEY;
const MODEL              = ENV.MODEL || 'google/gemini-3.1-flash-lite-preview';

if (!TELEGRAM_TOKEN)     { console.error('Missing TELEGRAM_TOKEN in .env');     process.exit(1); }
if (!OPENROUTER_API_KEY) { console.error('Missing OPENROUTER_API_KEY in .env'); process.exit(1); }
if (!ALLOWED_USER_ID)    { console.warn('⚠  ALLOWED_USER_ID is 0 — bot will reply to ANYONE. Set it in .env to lock down.'); }

const TG_API = `https://api.telegram.org/bot${TELEGRAM_TOKEN}`;

// ─── data tools: now call the FastAPI service over HTTP ─────────────────────
// Falls back to reading the JSON files directly if the API is unreachable
// (e.g. you ran the bot but forgot to start the API).
async function apiGet(pathAndQuery) {
  try {
    const r = await fetch(`${API_BASE}${pathAndQuery}`, { signal: AbortSignal.timeout(8000) });
    if (!r.ok) throw new Error(`API ${r.status}`);
    return await r.json();
  } catch (e) {
    console.warn(`API call failed (${pathAndQuery}): ${e.message} — falling back to JSON file`);
    return null;
  }
}

function buildQS(obj) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(obj || {})) {
    if (v === undefined || v === null || v === '') continue;
    sp.set(k, String(v));
  }
  const q = sp.toString();
  return q ? `?${q}` : '';
}

async function loadCarsFile() {
  try { return JSON.parse(await fs.readFile(CARS_JSON, 'utf-8')); } catch { return []; }
}
async function loadAptsFile() {
  try { return JSON.parse(await fs.readFile(APT_JSON, 'utf-8')); } catch { return []; }
}

const clampLimit = n => Math.max(1, Math.min(10, parseInt(n) || 5));
const matchAny = (text, words) => {
  if (!words) return true;
  const arr = Array.isArray(words) ? words : [words];
  const t = (text || '').toLowerCase();
  return arr.some(w => t.includes(String(w).toLowerCase()));
};

async function tool_query_cars(args) {
  const limit = clampLimit(args.limit);
  const qs = buildQS({
    has_sunroof: args.has_sunroof,
    max_price:   args.max_price,
    min_price:   args.min_price,
    max_km:      args.max_km,
    min_year:    args.min_year,
    brand:       args.brand,
    source:      args.source,
    location:    args.location,
    sort:        args.sort || 'sunroof_then_price',
    limit,
  });
  const api = await apiGet(`/cars${qs}`);
  if (api) {
    return {
      total_matched: api.count,
      results: api.results.map(c => ({
        title: c.title || c.brand, brand: c.brand, year: c.year, km: c.km,
        price_aed: c.price_aed, has_sunroof: !!c.has_sunroof,
        location: c.location, source: c.source, url: c.url, image: c.image,
      })),
    };
  }
  // ── Fallback path: read JSON directly if API is down ────────────────────
  const cars = await loadCarsFile();
  let out = cars;
  if (args.has_sunroof !== undefined) out = out.filter(c => Boolean(c.has_sunroof) === Boolean(args.has_sunroof));
  if (args.max_price) out = out.filter(c => (c.price_aed || 0) <= +args.max_price);
  if (args.min_price) out = out.filter(c => (c.price_aed || 0) >= +args.min_price);
  if (args.brand)     out = out.filter(c => matchAny(c.brand, args.brand));
  if (args.location)  out = out.filter(c => matchAny(c.location, args.location));
  out = out.sort((a, b) => ((b.has_sunroof?1:0)-(a.has_sunroof?1:0)) || (a.price_aed - b.price_aed));
  return {
    total_matched: out.length,
    results: out.slice(0, limit).map(c => ({
      title: c.title || c.brand, brand: c.brand, year: c.year, km: c.km,
      price_aed: c.price_aed, has_sunroof: !!c.has_sunroof,
      location: c.location, source: c.source, url: c.url, image: c.image,
    })),
  };
}

async function tool_query_apartments(args) {
  const limit = clampLimit(args.limit);
  const qs = buildQS({
    max_monthly:   args.max_monthly,
    max_yearly:    args.max_yearly,
    max_tier:      args.max_tier,
    area:          args.area,
    amenity:       args.amenity,
    min_size_sqft: args.min_size_sqft,
    sort:          args.sort || 'tier_then_price',
    limit,
  });
  const api = await apiGet(`/apartments${qs}`);
  if (api) {
    return {
      total_matched: api.count,
      results: api.results.map(a => ({
        title: a.title || a.area, area: a.area, commute_tier: a.commute_tier,
        monthly_aed: a.monthly_aed, yearly_aed: a.price_aed,
        bedrooms: a.bedrooms, bathrooms: a.bathrooms, size_sqft: a.size_sqft,
        furnished: !!a.furnished, amenities: (a.amenities || []).slice(0, 8),
        source: a.source, url: a.url, image: a.image,
      })),
    };
  }
  // Fallback
  const rows = await loadAptsFile();
  let out = rows;
  if (args.max_monthly) out = out.filter(a => (a.monthly_aed || 0) <= +args.max_monthly);
  if (args.max_tier)    out = out.filter(a => (a.commute_tier || 5) <= +args.max_tier);
  if (args.area)        out = out.filter(a => matchAny(a.area + ' ' + (a.full_location || ''), args.area));
  out = out.sort((a, b) => (a.commute_tier - b.commute_tier) || (a.price_aed - b.price_aed));
  return {
    total_matched: out.length,
    results: out.slice(0, limit).map(a => ({
      title: a.title || a.area, area: a.area, commute_tier: a.commute_tier,
      monthly_aed: a.monthly_aed, yearly_aed: a.price_aed,
      bedrooms: a.bedrooms, bathrooms: a.bathrooms, size_sqft: a.size_sqft,
      furnished: !!a.furnished, amenities: (a.amenities || []).slice(0, 8),
      source: a.source, url: a.url, image: a.image,
    })),
  };
}

async function tool_get_stats() {
  const api = await apiGet('/stats');
  if (api) return api;
  // Fallback
  const [cars, apts] = await Promise.all([loadCarsFile(), loadAptsFile()]);
  const tierCount = {};
  for (const a of apts) tierCount[`tier_${a.commute_tier}`] = (tierCount[`tier_${a.commute_tier}`] || 0) + 1;
  return {
    cars: {
      total: cars.length,
      sunroof: cars.filter(c => c.has_sunroof).length,
      under_20k: cars.filter(c => (c.price_aed||0) > 0 && (c.price_aed||0) <= 20000).length,
    },
    apartments: {
      total: apts.length,
      by_tier: tierCount,
      cheapest_monthly: apts.length ? Math.min(...apts.map(a => a.monthly_aed)) : null,
    },
  };
}

const TOOLS = {
  query_cars: tool_query_cars,
  query_apartments: tool_query_apartments,
  get_stats: tool_get_stats,
};

const TOOL_DEFS = [
  {
    type: 'function',
    function: {
      name: 'query_cars',
      description: 'Search the user\'s scraped Dubai car listings. Returns up to `limit` results (default 5).',
      parameters: {
        type: 'object',
        properties: {
          has_sunroof: { type: 'boolean' },
          max_price:   { type: 'integer', description: 'max price AED' },
          min_price:   { type: 'integer' },
          max_km:      { type: 'integer' },
          min_year:    { type: 'integer' },
          brand:       { type: 'string', description: 'brand/model keyword e.g. "Honda Civic"' },
          source:      { type: 'string' },
          location:    { type: 'string' },
          min_score:   { type: 'integer' },
          sort: { type: 'string', enum: ['sunroof_then_score','price_asc','price_desc','year_desc','km_asc','score'] },
          limit: { type: 'integer' },
        },
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'query_apartments',
      description: 'Search 1BHK furnished apartments near DAFZA. Returns up to `limit` results.',
      parameters: {
        type: 'object',
        properties: {
          max_monthly:   { type: 'integer', description: 'max monthly AED (user budget 6000)' },
          max_yearly:    { type: 'integer' },
          max_tier:      { type: 'integer', description: '1=DAFZA-adjacent, 4=20-30 min commute' },
          area:          { type: 'string' },
          amenity:       { type: 'string' },
          min_size_sqft: { type: 'integer' },
          sort: { type: 'string', enum: ['tier_then_price','price_asc','price_desc','size_desc'] },
          limit: { type: 'integer' },
        },
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'get_stats',
      description: 'Get headline counts for cars and apartments inventory.',
      parameters: { type: 'object', properties: {} },
    },
  },
];

const SYSTEM_PROMPT = `You are the user's personal Dubai listings concierge on Telegram.

USER BUDGETS:
- Cars: TOTAL cash budget is AED 20,000. SHOW listings up to AED 20,000. Do NOT artificially cap at 15K. The user mentally sets aside ~AED 5,000 for post-purchase maintenance, but that's a personal note — listings under 20K are all on the table. If the user asks for "all cars" or "show me cars", do NOT apply a price filter unless they explicitly mention one.
- Apartments: AED 6,000/month or AED 72,000/year. The user works at Heidelberg Materials Trading in DAFZA (Dubai Airport Free Zone — Green Line metro). They prefer apartments with easy metro access to DAFZA.

Always call a tool to get fresh data — do NOT invent listings.

After receiving tool results, write a clean Telegram reply in PLAIN TEXT.

STRICT FORMATTING (no markdown — Telegram will show raw asterisks if you use them):
- No asterisks, no underscores, no [text](url), no backticks, no #headings.
- Use UPPERCASE for section headers (sparingly).
- Use the visual divider line "─────────────────────────────" between sections.
- URLs go on their own line (Telegram auto-previews them).
- Use light emoji as visual anchors: 🚗 for cars, 🏠 for apartments, ☀️ for sunroof, 📍 for location, 💰 for price, 🕒 for time. Don't overdo it.
- Indent sub-info with 3 spaces.
- Numbers go through toLocaleString feel: write 11,000 not 11000.

LISTING-REPLY TEMPLATE (cars):
🚗  N MATCHES FOUND
─────────────────────────────

🏆  TOP PICK
       <Year> <Brand> — AED 11,000
       ☀️  Sunroof  ·  250k km  ·  Automatic
       📍  Sobha Hartland, Dubai
       🔗  Dubizzle
       https://dubai.dubizzle.com/...

ALSO CONSIDER
   2.  <Year> <Brand> — AED 13,000
       245k km  ·  Al Quoz, Dubai
       https://...
   3.  <Year> <Brand> — AED 10,900
       180k km  ·  Al Khabaisi, Deira
       https://...

LISTING-REPLY TEMPLATE (apartments):
🏠  N APARTMENTS WITHIN YOUR FILTER
─────────────────────────────

🏆  TOP PICK
       Spacious Furnished 1BHK Suite — AED 4,750/mo
       📍  Tier 1 (DAFZA-adjacent) · Al Qusais
       📐  480 sqft  ·  1 bath  ·  Furnished
       🔗  Bayut
       https://www.bayut.com/property/details-11633806.html

ALSO CONSIDER
   2.  AED 5,167/mo  ·  Tier 2 Deira  ·  Bayut
       https://...

GENERAL CONTENT RULES:
- Lead with the count line.
- Top pick first, then 2-4 alternates.
- Be honest if nothing matches — say so in one line, don't pad.
- Under 350 words total.
- Omit the "ALSO CONSIDER" section if there's only 1 result.`;

// ─── OpenRouter LLM call ──────────────────────────────────────────────────────
async function callLLM(messages, useTools = true) {
  const body = {
    model: MODEL,
    messages,
    ...(useTools ? { tools: TOOL_DEFS, tool_choice: 'auto' } : {}),
    temperature: 0.3,
  };
  const r = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${OPENROUTER_API_KEY}`,
      'Content-Type': 'application/json',
      'X-Title': 'Dubai Hunt TG Bot',
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`OpenRouter ${r.status}: ${t.slice(0, 300)}`);
  }
  const j = await r.json();
  return j.choices?.[0]?.message;
}

async function answerQuestion(userText) {
  const messages = [
    { role: 'system', content: SYSTEM_PROMPT },
    { role: 'user',   content: userText },
  ];
  for (let round = 0; round < 3; round++) {
    const msg = await callLLM(messages);
    messages.push(msg);
    const calls = msg.tool_calls || [];
    if (!calls.length) return (msg.content || '').trim() || '(no reply generated)';
    for (const call of calls) {
      const fn = TOOLS[call.function.name];
      let result;
      try {
        const args = JSON.parse(call.function.arguments || '{}');
        console.log(`  tool: ${call.function.name}(${JSON.stringify(args)})`);
        result = fn ? await fn(args) : { error: `unknown tool ${call.function.name}` };
      } catch (e) {
        result = { error: e.message };
      }
      messages.push({
        role: 'tool',
        tool_call_id: call.id,
        name: call.function.name,
        content: JSON.stringify(result),
      });
    }
  }
  const final = await callLLM(messages, false);
  return (final.content || '(no reply generated)').trim();
}

// ─── Telegram transport (long-polling getUpdates) ─────────────────────────────
async function tgApi(method, body) {
  const r = await fetch(`${TG_API}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`Telegram ${method} ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

// Strip residual markdown formatting that LLMs sneak in despite instructions.
// Telegram renders `*foo*` as literal asterisks (since we don't use parse_mode),
// so we MUST remove them or replies look broken.
function stripMarkdown(s) {
  if (!s) return s;
  return s
    // **bold** or *bold*
    .replace(/\*\*([^\n]+?)\*\*/g, '$1')
    .replace(/\*([^*\n]+?)\*/g, '$1')
    // __bold__ — Telegram MarkdownV2 syntax leak
    .replace(/__([^\n]+?)__/g, '$1')
    // _italic_ (only around words, not inside identifiers like tier_1)
    .replace(/(^|[\s(])\b_([^_\n]+?)_\b(?=[\s)\.,!?;:]|$)/g, '$1$2')
    // [label](url) → "label url" (keeps URL auto-preview)
    .replace(/\[([^\]\n]+?)\]\((https?:\/\/[^)\s]+?)\)/g, '$1 $2')
    // inline `code`
    .replace(/`([^`\n]+?)`/g, '$1')
    // hash-headings
    .replace(/^[ \t]*#{1,6}[ \t]+/gm, '')
    // ">" blockquotes
    .replace(/^[ \t]*>[ \t]?/gm, '')
    // collapse 3+ blank lines
    .replace(/\n{3,}/g, '\n\n');
}

// Escape `&<>` for safe injection into HTML-formatted messages.
function escapeHTML(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

async function sendMessage(chatId, text, opts = {}) {
  // Two modes:
  //   opts.html === true  → parse_mode='HTML', we control the markup (built-ins)
  //   default             → plain text, strip any markdown the LLM leaked
  const useHtml = opts.html === true;
  const payload = {
    chat_id: chatId,
    text: (useHtml ? text : stripMarkdown(text)).slice(0, 4096),
    disable_web_page_preview: opts.disable_web_page_preview ?? false,
  };
  if (useHtml) payload.parse_mode = 'HTML';
  return tgApi('sendMessage', payload).catch(async err => {
    // HTML parse errors → retry as plain
    if (useHtml) {
      console.warn('HTML send failed, retrying plain:', err.message);
      return tgApi('sendMessage', {
        chat_id: chatId, text: stripMarkdown(text).slice(0, 4096),
        disable_web_page_preview: payload.disable_web_page_preview,
      });
    }
    throw err;
  });
}

async function sendTyping(chatId) {
  try {
    await tgApi('sendChatAction', { chat_id: chatId, action: 'typing' });
  } catch {}
}

function buildHelp() {
  // HTML — sendMessage will set parse_mode=HTML when called with {html:true}.
  // <pre> renders in Telegram's monospace font for crisp alignment.
  return (
`<b>Dubai Hunt</b> — your personal listings concierge.

Ask in plain English. Examples:
  • sunroof cars under 15k
  • cheapest Hyundai Elantra
  • 1bhk apartments in Deira under 5k
  • tier 1 apartments only

<b>Commands</b>
<pre>/stats              inventory totals
/refresh cars       re-scrape cars
/refresh apartments re-scrape apartments
/refresh all        both (10–15 min)
/help               this message</pre>`
  );
}

// Friendly relative-time for ISO timestamps in /stats.
function humanTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  const yesterday = new Date(now.getTime() - 86400_000).toDateString() === d.toDateString();
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  if (sameDay) return `today at ${hh}:${mm}`;
  if (yesterday) return `yesterday at ${hh}:${mm}`;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${d.getDate()} ${months[d.getMonth()]} ${hh}:${mm}`;
}

const TIER_LABELS = {
  1: 'Tier 1  (DAFZA-adjacent, 5–10 min)',
  2: 'Tier 2  (10–15 min)',
  3: 'Tier 3  (15–20 min)',
  4: 'Tier 4  (20–30 min)',
};

function formatStats(s) {
  // HTML output. <pre> renders in Telegram's monospace font with PERFECT
  // column alignment (regular-font proportional spacing breaks our padding).
  const fmtN = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US'));
  const pad  = (str, w, right = false) =>
    right ? String(str).padStart(w, ' ') : String(str).padEnd(w, ' ');

  const cars = s.cars, apts = s.apartments;
  const carsLast = humanTime(cars.last_seen);
  const aptsLast = humanTime(apts.last_seen);

  // Tier table — sort tier number ASC.
  const byTier = apts.by_tier || {};
  const tiers = Object.entries(byTier)
    .map(([k, v]) => [parseInt(String(k).replace(/[^\d]/g, '') || '0'), v])
    .sort((a, b) => a[0] - b[0]);

  // Build a fixed-width tier block.
  const tierLines = tiers.map(([t, n]) => {
    const label = ({
      1: 'Tier 1  (5–10 min)',
      2: 'Tier 2  (10–15 min)',
      3: 'Tier 3  (15–20 min)',
      4: 'Tier 4  (20–30 min)',
    })[t] || `Tier ${t}`;
    return `  ${pad(label, 24)}  ${pad(fmtN(n), 5, true)}`;
  }).join('\n');

  // Construct the HTML body. Everything inside <pre> is monospace.
  // We escape only the dynamic 'last refresh' strings since they're user-data-ish.
  const body =
`<b>📊 Dubai Hunt — Inventory</b>

<pre>CARS                          ${pad(fmtN(cars.total), 4, true)}
  with sunroof                ${pad(fmtN(cars.sunroof), 4, true)}
  priced ≤ AED 20,000         ${pad(fmtN(cars.under_20k), 4, true)}
  last refresh   ${pad(escapeHTML(carsLast), 17, true)}

APARTMENTS                    ${pad(fmtN(apts.total), 4, true)}
  cheapest        ${pad('AED ' + fmtN(apts.cheapest_monthly) + '/mo', 16, true)}
  last refresh   ${pad(escapeHTML(aptsLast), 17, true)}

  Commute to DAFZA:
${tierLines}</pre>`;
  return body;
}

// ─── refresh: spawn the Python scrapers in the background ─────────────────────
const REFRESH_COOLDOWN_MS = 5 * 60 * 1000;       // 5 min
const lastRefresh = { cars: 0, apartments: 0 };  // epoch ms
const inFlight    = { cars: false, apartments: false };

const SCRAPER = {
  cars: {
    cwd:  path.join(ROOT, 'Car Search - Dubai UAE'),
    file: 'scrape_dubai_cars.py',
    label: 'cars',
  },
  apartments: {
    cwd:  path.join(ROOT, 'Apartment Search - Dubai'),
    file: 'scrape_apartments.py',
    label: 'apartments',
  },
};

async function spawnScrape(chatId, kind) {
  const cfg = SCRAPER[kind];
  if (!cfg) return;
  if (inFlight[kind]) {
    await sendMessage(chatId, `Already refreshing ${cfg.label} — please wait for the current run to finish.`);
    return;
  }
  const elapsed = Date.now() - lastRefresh[kind];
  if (elapsed < REFRESH_COOLDOWN_MS) {
    const wait = Math.ceil((REFRESH_COOLDOWN_MS - elapsed) / 1000);
    await sendMessage(chatId, `Cooldown: try again in ${wait}s. (Last ${cfg.label} refresh ran ${Math.floor(elapsed/1000)}s ago.)`);
    return;
  }
  inFlight[kind] = true;
  lastRefresh[kind] = Date.now();

  await sendMessage(chatId, `Refreshing ${cfg.label} now… this can take 3–8 minutes. I'll ping you when done.`);

  const t0 = Date.now();
  const args = ['-X', 'utf8', cfg.file];
  const child = spawn('python', args, {
    cwd: cfg.cwd,
    detached: false,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  let stderrTail = '';
  child.stderr?.on('data', d => { stderrTail = (stderrTail + d.toString()).slice(-500); });
  child.on('error', async (e) => {
    inFlight[kind] = false;
    console.error(`scrape ${kind} spawn err:`, e);
    await sendMessage(chatId, `⚠️ Could not start ${cfg.label} scrape: ${e.message}`).catch(() => {});
  });
  child.on('exit', async (code) => {
    inFlight[kind] = false;
    const dur = Math.round((Date.now() - t0) / 1000);
    const stats = await tool_get_stats().catch(() => null);
    let msg;
    if (code === 0 && stats) {
      msg = kind === 'cars'
        ? `Cars refresh done in ${dur}s.\n\n` +
          `Total: ${stats.cars.total}\nSunroof: ${stats.cars.sunroof}\n≤ 20K AED: ${stats.cars.under_20k}\n\nAsk me anything.`
        : `Apartments refresh done in ${dur}s.\n\n` +
          `Total: ${stats.apartments.total}\nCheapest: ${stats.apartments.cheapest_monthly || '?'} AED/mo\nBy tier: ${JSON.stringify(stats.apartments.by_tier)}\n\nAsk me anything.`;
    } else {
      msg = `⚠️ ${cfg.label} refresh failed (exit ${code}) after ${dur}s.\nLast stderr:\n${stderrTail.slice(-300) || '(no output)'}`;
    }
    await sendMessage(chatId, msg).catch(() => {});
  });
}

async function handleUpdate(update) {
  const msg = update.message || update.edited_message;
  if (!msg || !msg.text) return;

  const userId = msg.from?.id;
  const chatId = msg.chat?.id;
  const text   = msg.text.trim();
  const userName = msg.from?.username || msg.from?.first_name || '(unknown)';

  // Allowlist
  if (ALLOWED_USER_ID && userId !== ALLOWED_USER_ID) {
    console.log(`× blocked user ${userId} (${userName}): ${text.slice(0, 60)}`);
    // Silent ignore — don't reveal the bot exists
    return;
  }

  console.log(`\n← from ${userName} (${userId}): ${text}`);

  try {
    if (/^\/?help$/i.test(text) || text === '/start') {
      await sendMessage(chatId, buildHelp(), { html: true });
      return;
    }
    if (/^\/?stats$/i.test(text)) {
      const s = await tool_get_stats();
      await sendMessage(chatId, formatStats(s), { html: true });
      return;
    }
    // /refresh cars | apartments | all   (also accept plain "refresh ...")
    const refreshMatch = text.match(/^\/?refresh\s+(cars?|apartments?|apts?|all|both)\s*$/i);
    if (refreshMatch) {
      const target = refreshMatch[1].toLowerCase();
      const kinds = (target === 'all' || target === 'both')
        ? ['cars', 'apartments']
        : (target.startsWith('car') ? ['cars'] : ['apartments']);
      for (const k of kinds) {
        spawnScrape(chatId, k).catch(e => console.error('spawnScrape err:', e));
      }
      return;
    }
    await sendTyping(chatId);
    const reply = await answerQuestion(text);
    await sendMessage(chatId, reply);
    console.log(`→ replied (${reply.length} chars)`);
  } catch (e) {
    console.error('error:', e);
    await sendMessage(chatId, `⚠️ Something broke: ${e.message}\nTry /help or /stats.`).catch(() => {});
  }
}

async function main() {
  console.log('Connecting to Telegram…');
  const me = await tgApi('getMe', {}).catch(e => { console.error('getMe failed:', e.message); process.exit(1); });
  if (!me.ok) { console.error('Bad token. Get a new one from @BotFather.'); process.exit(1); }
  console.log(`✓  Logged in as @${me.result.username}  (${me.result.first_name})`);
  console.log(`   Allowlist user ID: ${ALLOWED_USER_ID || '(open — anyone can chat)'}`);
  console.log(`   Model:             ${MODEL}`);
  console.log(`   Cars JSON:         ${CARS_JSON}`);
  console.log(`   Apts JSON:         ${APT_JSON}`);
  console.log('\nLong-polling for messages…\n');

  // Drop any backlog so we don't reply to old messages.
  let offset = 0;
  try {
    const drain = await tgApi('getUpdates', { offset: -1, timeout: 0 });
    if (drain.result?.length) offset = drain.result[drain.result.length - 1].update_id + 1;
  } catch {}

  while (true) {
    try {
      const j = await tgApi('getUpdates', { offset, timeout: 50, allowed_updates: ['message'] });
      for (const update of (j.result || [])) {
        offset = update.update_id + 1;
        handleUpdate(update).catch(e => console.error('handleUpdate err:', e));
      }
    } catch (e) {
      console.error('poll err:', e.message);
      await new Promise(r => setTimeout(r, 3000));
    }
  }
}

main();
