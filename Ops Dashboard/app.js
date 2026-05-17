/* Ops Dashboard — Chart.js wiring
   Loads /admin/health + /admin/scrape_runs from FastAPI (port 8090).
   Auto-refreshes every 60 s and on tab focus.
*/
(function () {
  'use strict';

  // ── helpers ───────────────────────────────────────────────────────────────
  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // API base detection:
  //  • If served from the FastAPI itself (same origin) → use relative URLs.
  //    This is the VM deployment scenario (port 80 serves API + static).
  //  • If served from file:// or a different port (laptop dev) → hit localhost:8090.
  const API_BASE = (() => {
    if (location.protocol === 'file:') return 'http://127.0.0.1:8090';
    // Served from FastAPI directly (any non-8765 port that isn't a separate static server)
    if (location.port === '' || location.port === '80' || location.port === '443' || location.port === '8090') {
      return '';  // same-origin, relative
    }
    // Anything else (e.g. python http.server on 8765) → assume API is on :8090
    return `${location.protocol}//${location.hostname}:8090`;
  })();

  const fmtN = (n) => (n == null ? '—' : Number(n).toLocaleString('en-US'));

  function humanTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    const now = new Date();
    const sameDay  = d.toDateString() === now.toDateString();
    const yesterday = new Date(now.getTime() - 86400000).toDateString() === d.toDateString();
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    if (sameDay)   return `today, ${hh}:${mm}`;
    if (yesterday) return `yesterday, ${hh}:${mm}`;
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${d.getDate()} ${months[d.getMonth()]}, ${hh}:${mm}`;
  }

  function setStatus(ok, text) {
    const dot = $('#status-dot'); if (!dot) return;
    dot.className = ok ? 'dot-ok' : 'dot-fail';
    $('#status-text').textContent = text;
  }

  // ── colors (match dashboard's css vars) ───────────────────────────────────
  const COL = {
    cool:        'oklch(0.80 0.13 220)',
    coolBg:      'oklch(0.80 0.13 220 / 0.18)',
    sun:         'oklch(0.84 0.155 80)',
    sunBg:       'oklch(0.84 0.155 80 / 0.20)',
    excellent:   'oklch(0.82 0.16 150)',
    good:        'oklch(0.80 0.13 220)',
    fair:        'oklch(0.80 0.13 80)',
    poor:        'oklch(0.68 0.12 25)',
    ink2:        'oklch(0.72 0.008 250)',
    ink3:        'oklch(0.55 0.010 250)',
    ink4:        'oklch(0.40 0.012 250)',
    hairline2:   'oklch(1 0 0 / 0.10)',
  };
  const PALETTE = [COL.cool, COL.sun, COL.excellent, COL.fair, COL.poor,
                   'oklch(0.78 0.12 290)', 'oklch(0.74 0.10 30)', 'oklch(0.70 0.10 180)',
                   'oklch(0.65 0.10 320)', 'oklch(0.60 0.08 90)', COL.ink3, COL.ink4];

  // Chart.js defaults
  Chart.defaults.font.family = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
  Chart.defaults.color = COL.ink3;
  Chart.defaults.borderColor = COL.hairline2;
  Chart.defaults.plugins.legend.labels.color = COL.ink2;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.legend.labels.font = { size: 11 };

  const charts = {};   // id -> Chart instance
  function mkChart(canvasId, config) {
    const el = $('#' + canvasId);
    if (!el) return null;
    if (charts[canvasId]) charts[canvasId].destroy();
    config.options = Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 220 },
    }, config.options || {});
    charts[canvasId] = new Chart(el, config);
    return charts[canvasId];
  }

  // ── fetch helpers ─────────────────────────────────────────────────────────
  async function getJSON(path) {
    const r = await fetch(API_BASE + path, { cache: 'no-store', signal: AbortSignal.timeout(10000) });
    if (!r.ok) throw new Error(`API ${r.status} ${path}`);
    return r.json();
  }

  // ── renderers ─────────────────────────────────────────────────────────────
  function renderOverview(h) {
    const cs = h.cars.summary, as = h.apartments.summary;
    $('#kpi-cars-total').textContent     = fmtN(cs.total);
    $('#kpi-cars-active').textContent    = fmtN(cs.active);
    $('#kpi-cars-inactive').textContent  = fmtN(cs.inactive);
    $('#kpi-cars-sunroof').textContent   = fmtN(cs.sunroof);
    $('#kpi-cars-under-20k').textContent = fmtN(cs.under_20k);
    $('#kpi-apt-total').textContent      = fmtN(as.total);
    $('#kpi-apt-within-budget').textContent = fmtN(as.within_budget);
    $('#kpi-apt-cheapest').textContent    = fmtN(as.cheapest);
    $('#kpi-last-refresh').textContent    = new Date().toLocaleTimeString();
    $('#kpi-cars-last').textContent       = humanTime(cs.last_seen);
    $('#kpi-apt-last').textContent        = humanTime(as.last_seen);

    mkChart('chart-cars-source', {
      type: 'doughnut',
      data: {
        labels: h.cars.by_source.map(r => r.source),
        datasets: [{
          data:            h.cars.by_source.map(r => r.count),
          backgroundColor: h.cars.by_source.map((_, i) => PALETTE[i % PALETTE.length]),
          borderWidth: 0,
        }],
      },
      options: { plugins: { legend: { position: 'right' } }, cutout: '60%' },
    });

    mkChart('chart-apt-tier', {
      type: 'bar',
      data: {
        labels: h.apartments.by_tier.map(r => `Tier ${r.tier}`),
        datasets: [{
          label: 'Listings',
          data: h.apartments.by_tier.map(r => r.count),
          backgroundColor: h.apartments.by_tier.map(r => ({1:COL.excellent,2:COL.good,3:COL.fair,4:COL.poor})[r.tier] || COL.ink3),
          borderWidth: 0, borderRadius: 4,
        }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });

    mkChart('chart-cars-price', {
      type: 'bar',
      data: {
        labels: h.cars.price_hist.map(r => r.bucket),
        datasets: [{
          label: 'Cars',
          data: h.cars.price_hist.map(r => r.count),
          backgroundColor: COL.cool, borderWidth: 0, borderRadius: 4,
        }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });

    mkChart('chart-apt-price', {
      type: 'bar',
      data: {
        labels: h.apartments.price_hist.map(r => r.bucket),
        datasets: [{
          label: 'Apartments',
          data: h.apartments.price_hist.map(r => r.count),
          backgroundColor: COL.sun, borderWidth: 0, borderRadius: 4,
        }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });
  }

  function renderCars(h) {
    mkChart('chart-cars-brand', {
      type: 'bar',
      data: {
        labels: h.cars.by_brand.map(r => r.brand),
        datasets: [{
          label: 'Listings', data: h.cars.by_brand.map(r => r.count),
          backgroundColor: COL.cool, borderWidth: 0, borderRadius: 3,
        }],
      },
      options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true } } },
    });

    mkChart('chart-cars-sun', {
      type: 'doughnut',
      data: {
        labels: h.cars.sunroof_split.map(r => r.label),
        datasets: [{ data: h.cars.sunroof_split.map(r => r.count),
                      backgroundColor: [COL.sun, COL.hairline2], borderWidth: 0 }],
      },
      options: { plugins: { legend: { position: 'right' } }, cutout: '65%' },
    });

    mkChart('chart-cars-year', {
      type: 'bar',
      data: {
        labels: h.cars.year_dist.map(r => r.year),
        datasets: [{
          label: 'Cars', data: h.cars.year_dist.map(r => r.count),
          backgroundColor: COL.cool, borderWidth: 0,
        }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 } } } },
    });

    mkChart('chart-cars-km', {
      type: 'bar',
      data: {
        labels: h.cars.km_hist.map(r => r.bucket),
        datasets: [{
          label: 'Cars', data: h.cars.km_hist.map(r => r.count),
          backgroundColor: COL.fair, borderWidth: 0, borderRadius: 4,
        }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });

    const tbody = $('#table-brands tbody');
    tbody.innerHTML = h.cars.by_brand
      .map(r => `<tr><td>${r.brand}</td><td class="num-cell num">${fmtN(r.count)}</td></tr>`)
      .join('');
  }

  function renderApartments(h) {
    mkChart('chart-apt-area', {
      type: 'bar',
      data: {
        labels: h.apartments.by_area.map(r => r.area),
        datasets: [{
          label: 'Listings', data: h.apartments.by_area.map(r => r.count),
          backgroundColor: COL.cool, borderWidth: 0, borderRadius: 3,
        }],
      },
      options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true } } },
    });

    mkChart('chart-apt-source', {
      type: 'doughnut',
      data: {
        labels: h.apartments.by_source.map(r => r.source),
        datasets: [{
          data: h.apartments.by_source.map(r => r.count),
          backgroundColor: h.apartments.by_source.map((_, i) => PALETTE[i % PALETTE.length]),
          borderWidth: 0,
        }],
      },
      options: { plugins: { legend: { position: 'right' } }, cutout: '60%' },
    });

    mkChart('chart-apt-size', {
      type: 'bar',
      data: {
        labels: h.apartments.size_hist.map(r => r.bucket),
        datasets: [{
          label: 'Apartments', data: h.apartments.size_hist.map(r => r.count),
          backgroundColor: COL.sun, borderWidth: 0, borderRadius: 4,
        }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });

    // tier-vs-price scatter-ish (we don't have per-listing prices in the bundle, derive avg per-tier client-side from /apartments)
    fetchTierAveragesAndDraw();

    const tbody = $('#table-areas tbody');
    tbody.innerHTML = h.apartments.by_area
      .map(r => `<tr><td>${r.area}</td><td class="num-cell num">${fmtN(r.count)}</td></tr>`)
      .join('');
  }

  async function fetchTierAveragesAndDraw() {
    try {
      const r = await getJSON('/apartments?limit=500');
      const buckets = {};
      for (const a of r.results || []) {
        const t = a.commute_tier || 0;
        if (!buckets[t]) buckets[t] = { sum: 0, n: 0 };
        buckets[t].sum += (a.monthly_aed || 0);
        buckets[t].n++;
      }
      const tiers = Object.keys(buckets).map(t => parseInt(t)).sort();
      const data  = tiers.map(t => Math.round(buckets[t].sum / Math.max(1, buckets[t].n)));
      mkChart('chart-apt-tier-price', {
        type: 'bar',
        data: {
          labels: tiers.map(t => `Tier ${t}`),
          datasets: [{
            label: 'Avg monthly AED',
            data,
            backgroundColor: tiers.map(t => ({1:COL.excellent,2:COL.good,3:COL.fair,4:COL.poor})[t] || COL.ink3),
            borderWidth: 0, borderRadius: 4,
          }],
        },
        options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
      });
    } catch (e) { console.warn('tier-price fetch failed', e); }
  }

  function renderPipeline(h, runs) {
    const cs = h.cars.summary, as = h.apartments.summary;
    $('#pipe-cars-last').textContent  = humanTime(cs.last_seen);
    $('#pipe-apt-last').textContent   = humanTime(as.last_seen);
    $('#pipe-cars-new24h').textContent = fmtN(h.pipeline.cars_new_last_24h);
    $('#pipe-apt-new24h').textContent  = fmtN(h.pipeline.apartments_new_last_24h);
    $('#pipe-api-health').textContent  = 'ONLINE';
    $('#pipe-db-status').textContent   = `${fmtN(cs.total)} + ${fmtN(as.total)} rows`;

    mkChart('chart-cars-freshness', {
      type: 'bar',
      data: {
        labels: h.cars.freshness.map(r => r.bucket),
        datasets: [{
          label: 'Cars',
          data: h.cars.freshness.map(r => r.count),
          backgroundColor: [COL.excellent, COL.good, COL.fair, COL.poor, COL.ink4],
          borderWidth: 0, borderRadius: 4,
        }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });

    mkChart('chart-cars-source-bar', {
      type: 'bar',
      data: {
        labels: h.cars.by_source.map(r => r.source),
        datasets: [{
          label: 'Active listings',
          data: h.cars.by_source.map(r => r.count),
          backgroundColor: h.cars.by_source.map((_, i) => PALETTE[i % PALETTE.length]),
          borderWidth: 0, borderRadius: 4,
        }],
      },
      options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } },
    });

    const tbody = $('#table-runs tbody');
    if (!runs.runs.length) {
      tbody.innerHTML = `<tr><td colspan="6" style="color:var(--ink-3); padding:14px 10px">No scrape_runs logged yet — once your next scheduled run fires, history will appear here.</td></tr>`;
      $('#runs-hint').textContent = '';
    } else {
      const fmtDuration = (s) => {
        if (s == null) return '—';
        if (s < 60) return `${s}s`;
        const m = Math.floor(s / 60), sec = s % 60;
        return `${m}m ${sec.toString().padStart(2, '0')}s`;
      };
      tbody.innerHTML = runs.runs.map(r => {
        const status = r.finished_at
          ? `<span style="color:var(--tier-excellent)">✓ finished</span>`
          : `<span style="color:var(--tier-good)">⟳ running…</span>`;
        return `<tr>
          <td>${humanTime(r.started_at)}</td>
          <td>${r.kind}</td>
          <td>${status}</td>
          <td class="num-cell num">${fmtDuration(r.duration_s)}</td>
          <td class="num-cell num">${fmtN(r.rows_seen)}</td>
          <td style="color:var(--ink-3); font-size:11.5px">${(r.notes || '').slice(0, 90)}</td>
        </tr>`;
      }).join('');
      $('#runs-hint').textContent = '';
    }
  }

  // ── tabs ─────────────────────────────────────────────────────────────────
  function switchTab(name) {
    $$('.tab').forEach(t => t.classList.toggle('is-active', t.dataset.tab === name));
    $$('.panel').forEach(p => p.hidden = p.dataset.panel !== name);
  }
  $$('.tab').forEach(t => t.addEventListener('click', () => switchTab(t.dataset.tab)));

  // ── refresh loop ─────────────────────────────────────────────────────────
  let refreshTimer = null;
  let lastData = null;
  async function refresh() {
    setStatus(true, 'loading…');
    try {
      const [h, runs] = await Promise.all([
        getJSON('/admin/health'),
        getJSON('/admin/scrape_runs?limit=20').catch(() => ({ runs: [] })),
      ]);
      lastData = { h, runs };
      renderOverview(h);
      renderCars(h);
      renderApartments(h);
      renderPipeline(h, runs);
      $('#last-refresh').textContent = 'refreshed ' + new Date().toLocaleTimeString();
      setStatus(true, 'API online');
    } catch (e) {
      console.error(e);
      setStatus(false, 'API offline');
      $('#last-refresh').textContent = 'last attempt ' + new Date().toLocaleTimeString();
    }
  }
  function scheduleAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = setInterval(refresh, 60000);   // every 60 s
  }

  $('#refresh-btn').addEventListener('click', refresh);
  document.addEventListener('keydown', e => {
    const inField = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT';
    if (inField) return;
    if (e.key === 'r' || e.key === 'R') { e.preventDefault(); refresh(); }
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && lastData) refresh();
  });

  refresh();
  scheduleAutoRefresh();
})();
