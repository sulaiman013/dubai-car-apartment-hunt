/* ============================================================
   Dubai Car Hunt v2 — app.js
   ============================================================ */
(function () {
  'use strict';

  const ALL = Array.isArray(window.CAR_DATA) ? window.CAR_DATA.slice() : [];
  const STATS = window.CAR_STATS || { total: ALL.length, sunroof_count: ALL.filter(c => c.has_sunroof).length };
  const PAGE = 60;

  const state = {
    q: '',
    brand: '',
    source: '',
    maxPrice: 30000,
    minScore: 0,
    chips: { sunroof: false, budget: false, lowkm: false, top20: false, owner: false },
    sort: 'sunroof',
    view: 'list',
    rendered: 0,
    filtered: [],
  };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const fmtAed = n => (n == null ? '—' : n.toLocaleString('en-US'));
  const fmtKmShort = c => {
    if (c.km == null) return '—';
    if (c.km >= 1000) return Math.round(c.km / 1000) + 'k km';
    return c.km + ' km';
  };
  const fmtKm = c => c.km_str || (c.km != null ? c.km.toLocaleString('en-US') + ' km' : '—');

  function tierClass(score) {
    if (score >= 80) return 'excellent';
    if (score >= 65) return 'good';
    if (score >= 50) return 'fair';
    return 'poor';
  }
  function tierLabel(rating, score) {
    if (rating) return rating;
    const t = tierClass(score);
    return ({ excellent: 'EXCELLENT', good: 'GOOD', fair: 'FAIR', poor: 'BELOW AVG' })[t];
  }
  function escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, ch => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]));
  }
  function locShort(loc) {
    if (!loc) return 'Location not listed';
    const parts = loc.split('>').map(s => s.trim()).filter(Boolean);
    if (parts[0] && parts[0].toUpperCase() === 'UAE') parts.shift();
    return parts.reverse().slice(0, 2).join(', ');
  }
  function relTime(iso) {
    if (!iso) return 'refreshed —';
    try {
      const d = new Date(iso);
      const diff = (Date.now() - d.getTime()) / 1000;
      if (diff < 60) return 'just now';
      if (diff < 3600) return 'refreshed ' + Math.floor(diff / 60) + 'm ago';
      if (diff < 86400) return 'refreshed ' + Math.floor(diff / 3600) + 'h ago';
      return 'refreshed ' + Math.floor(diff / 86400) + 'd ago';
    } catch (e) { return 'refreshed —'; }
  }

  // ---------- Stats ----------
  function paintStats() {
    $('#stat-total').textContent = (STATS.total ?? ALL.length).toString();
    $('#stat-sunroof').textContent = (STATS.sunroof_count ?? ALL.filter(c => c.has_sunroof).length).toString();
    $('#stat-budget').textContent = ALL.filter(c => c.price != null && c.price <= 20000).length.toString();
    $('#stat-updated').textContent = relTime(STATS.generated_at);
  }

  // ---------- Filter ----------
  function applyFilters() {
    const q = state.q.trim().toLowerCase();
    let list = ALL.filter(c => {
      if (state.brand && c.brand !== state.brand) return false;
      if (state.source && c.source !== state.source) return false;
      if (state.maxPrice < 30000 && c.price > state.maxPrice) return false;
      if (state.minScore > 0 && (c.score ?? 0) < state.minScore) return false;
      if (state.chips.sunroof && !c.has_sunroof) return false;
      if (state.chips.budget && c.price > 20000) return false;
      if (state.chips.lowkm && (c.km == null || c.km >= 150000)) return false;
      if (state.chips.owner && c.seller_type !== 'OW') return false;
      if (q) {
        const hay = [c.title, c.brand, c.location, c.description, c.color, c.trim, ...(c.features||[])].join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    list.sort((a, b) => {
      switch (state.sort) {
        case 'score': return (b.score ?? 0) - (a.score ?? 0);
        case 'price-asc': return (a.price ?? Infinity) - (b.price ?? Infinity);
        case 'price-desc': return (b.price ?? -Infinity) - (a.price ?? -Infinity);
        case 'year-desc': return (b.year ?? 0) - (a.year ?? 0);
        case 'km-asc': return (a.km ?? Infinity) - (b.km ?? Infinity);
        default:
          if (a.has_sunroof !== b.has_sunroof) return a.has_sunroof ? -1 : 1;
          return (b.score ?? 0) - (a.score ?? 0);
      }
    });

    if (state.chips.top20) list = list.slice(0, 20);

    state.filtered = list;
    state.rendered = 0;
    renderInitial();
    paintCounts();
  }

  function paintCounts() {
    const shown = state.filtered.length;
    const sun = state.filtered.filter(c => c.has_sunroof).length;
    $('#count-shown').textContent = shown.toLocaleString();
    $('#count-total').textContent = (STATS.total ?? ALL.length).toLocaleString();
    $('#count-sun').textContent = sun.toLocaleString();
    $('#empty').hidden = shown !== 0;
    $('#list').hidden = state.view !== 'list' || shown === 0;
    $('#grid').hidden = state.view !== 'grid' || shown === 0;
  }

  // ---------- Render: row ----------
  const sunSvg = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.4" fill="currentColor"/><g stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3v2"/><path d="M12 19v2"/><path d="M3 12h2"/><path d="M19 12h2"/><path d="M5.6 5.6l1.4 1.4"/><path d="M17 17l1.4 1.4"/><path d="M5.6 18.4l1.4-1.4"/><path d="M17 7l1.4-1.4"/></g></svg>';

  function thumbHTML(c) {
    if (!c.image) return '<div class="row__noimg">NO IMG</div>';
    return `<img loading="lazy" decoding="async" src="${escapeHtml(c.image)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'row__noimg',textContent:'NO IMG'}))" />`;
  }
  function cardImgHTML(c) {
    if (!c.image) return '<div class="card__noimg">No image<br>provided</div>';
    return `<img loading="lazy" decoding="async" src="${escapeHtml(c.image)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'card__noimg',innerHTML:'No image<br>provided'}))" />`;
  }

  function rowHTML(c) {
    const score = Math.round(c.score ?? 0);
    const tier = tierClass(score);
    const sunCls = c.has_sunroof ? ' row--sun' : '';
    const sellerTag = c.seller_type === 'OW'
      ? '<span class="tag tag--owner">OWNER</span>'
      : c.seller_type === 'DL'
        ? '<span class="tag tag--dealer">DEALER</span>'
        : '';

    return `
      <article class="row${sunCls}" tabindex="0" data-id="${escapeHtml(c.id)}">
        <div class="row__thumb">${thumbHTML(c)}</div>
        <div class="row__main">
          <h3 class="row__title">
            ${c.has_sunroof ? `<span class="row__sunTag">${sunSvg}Sunroof</span>` : ''}
            <span>${escapeHtml(c.title || c.brand || 'Untitled')}</span>
          </h3>
          <div class="row__meta">
            <span class="num">${c.year ?? '—'}</span>
            <span class="num">${escapeHtml(fmtKm(c))}</span>
            <span>${escapeHtml(c.transmission || '—')}</span>
            <span class="loc">${escapeHtml(locShort(c.location))}</span>
          </div>
        </div>
        <div class="row__price">
          <span class="ccy">AED</span>
          <span class="num">${fmtAed(c.price)}</span>
        </div>
        <div class="row__score row__score--${tier}">${score}<span class="lbl">/100</span></div>
        <div class="row__tags">
          ${sellerTag}
          <span class="tag tag--src">${escapeHtml(c.source || '—')}</span>
        </div>
        <button class="row__ext" data-ext aria-label="Open original" tabindex="-1">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>
        </button>
      </article>
    `;
  }

  function cardHTML(c) {
    const score = Math.round(c.score ?? 0);
    const tier = tierClass(score);
    const sunCls = c.has_sunroof ? ' card--sun' : '';

    return `
      <article class="card${sunCls}" tabindex="0" data-id="${escapeHtml(c.id)}">
        <div class="card__media">
          ${c.has_sunroof ? `<div class="card__sunBar"></div><span class="card__sunPill">${sunSvg}Sunroof</span>` : ''}
          <span class="card__src">${escapeHtml(c.source || '—')}</span>
          ${cardImgHTML(c)}
          <span class="card__score card__score--${tier}">${score}</span>
        </div>
        <div class="card__body">
          <div class="card__row1">
            <h3 class="card__title">${escapeHtml(c.title || c.brand || 'Untitled')}</h3>
            <div class="card__price"><span class="ccy">AED</span>${fmtAed(c.price)}</div>
          </div>
          <div class="card__meta">
            <span class="num">${c.year ?? '—'}</span>
            <span class="num">${escapeHtml(fmtKmShort(c))}</span>
            <span>${escapeHtml(c.transmission || '—')}</span>
            <span class="loc">${escapeHtml(locShort(c.location))}</span>
          </div>
        </div>
      </article>
    `;
  }

  function renderInitial() {
    $('#list').innerHTML = '';
    $('#grid').innerHTML = '';
    state.rendered = 0;
    renderMore();
  }
  function renderMore() {
    const next = state.filtered.slice(state.rendered, state.rendered + PAGE);
    if (!next.length) return;
    const container = state.view === 'list' ? $('#list') : $('#grid');
    const html = next.map(state.view === 'list' ? rowHTML : cardHTML).join('');
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const frag = document.createDocumentFragment();
    while (tmp.firstChild) frag.appendChild(tmp.firstChild);
    container.appendChild(frag);
    state.rendered += next.length;
  }

  function switchView(v) {
    if (state.view === v) return;
    state.view = v;
    $$('.seg__btn').forEach(b => {
      const active = b.dataset.view === v;
      b.classList.toggle('is-active', active);
      b.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    renderInitial();
    paintCounts();
  }

  // ---------- Modal ----------
  const SUBSCORE_LABELS = {
    price: 'Price',
    mileage: 'Mileage',
    age: 'Age',
    reliability: 'Reliability',
    kpy: 'Km/year',
    value: 'Value',
    transmission: 'Transmission',
    sunroof: 'Sunroof',
  };

  function openModal(c) {
    const modal = $('#modal');
    modal.classList.toggle('modal--sun', !!c.has_sunroof);
    modal.hidden = false;

    $('#m-media').innerHTML = c.image
      ? `<img src="${escapeHtml(c.image)}" alt="${escapeHtml(c.title || '')}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'card__noimg',innerHTML:'No image provided'}))" />`
      : `<div class="card__noimg">No image provided</div>`;

    $('#m-brand').textContent = c.brand || '';
    $('#m-title').textContent = c.title || c.brand || 'Listing';
    $('#m-loc').textContent = locShort(c.location);
    $('#m-price').textContent = fmtAed(c.price);

    const score = Math.round(c.score ?? 0);
    const tier = tierClass(score);
    $('#m-score').textContent = score;
    $('#m-score').style.color = `var(--tier-${tier})`;

    const ratingEl = $('#m-rating');
    ratingEl.textContent = tierLabel(c.rating, score);
    ratingEl.className = 'modal__ratingTag is-' + tier;

    const sellerLabel = c.seller_type === 'OW' ? 'Owner' : c.seller_type === 'DL' ? 'Dealer' : '—';
    const kv = $('#m-kv');
    kv.innerHTML = '';
    const rows = [
      ['Year', c.year ?? '—'],
      ['Mileage', fmtKm(c)],
      ['Transmission', c.transmission || '—'],
      ['Trim', c.trim || '—'],
      ['Color', c.color || '—'],
      ['Body', c.body_type || '—'],
      ['Fuel', c.fuel || '—'],
      ['Seller', sellerLabel],
      ['Source', c.source || '—'],
      ['Sunroof', c.has_sunroof ? 'Yes' : 'No', c.has_sunroof],
    ];
    rows.forEach(([k, v, sun]) => {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = v;
      if (sun) dd.classList.add('is-sun');
      kv.appendChild(dt); kv.appendChild(dd);
    });

    const subs = c.sub_scores || {};
    $('#m-bars').innerHTML = Object.keys(SUBSCORE_LABELS).map(k => {
      const v = Math.round(subs[k] ?? 0);
      const isSun = k === 'sunroof';
      return `
        <div class="bar ${isSun ? 'bar--sun' : ''}">
          <div class="bar__head"><span>${SUBSCORE_LABELS[k]}</span><span class="v">${v}</span></div>
          <div class="bar__track"><div class="bar__fill" style="width:${Math.max(0, Math.min(100, v))}%"></div></div>
        </div>
      `;
    }).join('');

    const feats = c.features || [];
    $('#m-feat').innerHTML = feats.length
      ? feats.map(f => `<span class="feat ${/sunroof/i.test(f) ? 'is-sun' : ''}">${escapeHtml(f)}</span>`).join('')
      : '<span class="feat">No features listed</span>';

    $('#m-desc').textContent = c.description || 'No description provided.';

    const link = $('#m-link');
    if (c.url) { link.href = c.url; link.style.display = ''; }
    else { link.removeAttribute('href'); link.style.display = 'none'; }

    document.body.style.overflow = 'hidden';
  }

  function closeModal() {
    $('#modal').hidden = true;
    document.body.style.overflow = '';
  }

  // ---------- Wiring ----------
  function syncRangeFill(input) {
    const min = +input.min, max = +input.max, val = +input.value;
    const pct = ((val - min) / (max - min)) * 100;
    input.style.setProperty('--pct', pct + '%');
  }

  function init() {
    paintStats();

    let qTimer;
    $('#q').addEventListener('input', e => {
      clearTimeout(qTimer);
      qTimer = setTimeout(() => { state.q = e.target.value; applyFilters(); }, 110);
    });

    $('#brand').addEventListener('change', e => { state.brand = e.target.value; applyFilters(); });
    $('#source').addEventListener('change', e => { state.source = e.target.value; applyFilters(); });

    const priceEl = $('#price');
    const priceVal = $('#price-val');
    const pricePill = $('#price-pill');
    syncRangeFill(priceEl);
    priceEl.addEventListener('input', e => {
      state.maxPrice = +e.target.value;
      const txt = state.maxPrice >= 30000 ? 'Any' : (state.maxPrice / 1000) + 'K';
      pricePill.textContent = txt;
      priceVal.textContent = state.maxPrice >= 30000 ? 'AED any' : 'AED ' + state.maxPrice.toLocaleString();
      syncRangeFill(priceEl);
      applyFilters();
    });

    const scoreEl = $('#score');
    const scoreVal = $('#score-val');
    const scorePill = $('#score-pill');
    syncRangeFill(scoreEl);
    scoreEl.addEventListener('input', e => {
      state.minScore = +e.target.value;
      scoreVal.textContent = state.minScore;
      scorePill.textContent = state.minScore + '+';
      syncRangeFill(scoreEl);
      applyFilters();
    });

    $('#sort').addEventListener('change', e => { state.sort = e.target.value; applyFilters(); });

    // View toggle
    $$('.seg__btn').forEach(btn => {
      btn.addEventListener('click', () => switchView(btn.dataset.view));
    });

    // Chips
    $$('.chip[data-chip]').forEach(btn => {
      btn.addEventListener('click', () => {
        const k = btn.dataset.chip;
        state.chips[k] = !state.chips[k];
        btn.classList.toggle('is-active', state.chips[k]);
        applyFilters();
      });
    });
    $('#chip-clear').addEventListener('click', clearAll);
    $('#empty-clear').addEventListener('click', clearAll);

    function clearAll() {
      state.q = ''; $('#q').value = '';
      state.brand = ''; $('#brand').value = '';
      state.source = ''; $('#source').value = '';
      state.maxPrice = 30000; priceEl.value = 30000;
      pricePill.textContent = 'Any'; priceVal.textContent = 'AED any'; syncRangeFill(priceEl);
      state.minScore = 0; scoreEl.value = 0;
      scorePill.textContent = '0+'; scoreVal.textContent = '0'; syncRangeFill(scoreEl);
      Object.keys(state.chips).forEach(k => state.chips[k] = false);
      $$('.chip[data-chip]').forEach(b => b.classList.remove('is-active'));
      state.sort = 'sunroof'; $('#sort').value = 'sunroof';
      applyFilters();
    }

    // Card click — both list rows and grid cards
    function bindOpen(container) {
      container.addEventListener('click', e => {
        // External link button on rows
        if (e.target.closest('[data-ext]')) {
          e.stopPropagation();
          const card = e.target.closest('[data-id]');
          if (card) {
            const c = ALL.find(x => x.id === card.dataset.id);
            if (c && c.url) window.open(c.url, '_blank', 'noopener');
          }
          return;
        }
        const card = e.target.closest('[data-id]');
        if (!card) return;
        const c = ALL.find(x => x.id === card.dataset.id);
        if (c) openModal(c);
      });
      container.addEventListener('keydown', e => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const card = e.target.closest('[data-id]');
        if (!card) return;
        e.preventDefault();
        const c = ALL.find(x => x.id === card.dataset.id);
        if (c) openModal(c);
      });
    }
    bindOpen($('#list'));
    bindOpen($('#grid'));

    $('#modal').addEventListener('click', e => { if (e.target.matches('[data-close]')) closeModal(); });

    // Keyboard shortcuts
    document.addEventListener('keydown', e => {
      const target = e.target;
      const inField = target && (target.tagName === 'INPUT' || target.tagName === 'SELECT' || target.tagName === 'TEXTAREA');
      if (e.key === 'Escape') {
        if (!$('#modal').hidden) closeModal();
        else if (document.activeElement === $('#q')) $('#q').blur();
        return;
      }
      if (inField) return;
      if (e.key === '/' || e.key === 's') {
        e.preventDefault();
        $('#q').focus();
        $('#q').select();
      } else if (e.key === 'g' || e.key === 'G') {
        switchView('grid');
      } else if (e.key === 'l' || e.key === 'L') {
        switchView('list');
      }
    });

    // Close popovers when clicking outside
    document.addEventListener('click', e => {
      $$('.popover[open]').forEach(p => {
        if (!p.contains(e.target)) p.removeAttribute('open');
      });
    });

    // Progressive load
    const sentinel = $('#sentinel');
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting && state.rendered < state.filtered.length) renderMore();
      }, { rootMargin: '800px' });
      io.observe(sentinel);
    } else {
      window.addEventListener('scroll', () => {
        if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 800
          && state.rendered < state.filtered.length) renderMore();
      });
    }

    applyFilters();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
