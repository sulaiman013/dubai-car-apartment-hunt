/* Apartment Hunt — frontend logic */
(function () {
  'use strict';

  const ALL = Array.isArray(window.APT_DATA) ? window.APT_DATA.slice() : [];
  const STATS = window.APT_STATS || {};
  const PAGE = 60;

  const state = {
    q: '',
    area: '',
    source: '',
    maxMonthly: 6000,
    maxTier: 4,
    chips: { tier1: false, under5k: false, parking: false, gym: false, largesize: false },
    sort: 'tier',
    view: 'list',
    rendered: 0,
    filtered: [],
  };

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const fmtAed = n => (n == null ? '—' : n.toLocaleString('en-US'));
  const escapeHtml = s => s == null ? '' : String(s).replace(/[&<>"']/g, ch => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]));

  function tierClass(tier) {
    return tier === 1 ? 'excellent' : tier === 2 ? 'good' : tier === 3 ? 'fair' : 'poor';
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
  function locShort(loc) {
    if (!loc) return 'Location not listed';
    const parts = loc.split(',').map(s => s.trim()).filter(Boolean);
    return parts.slice(0, 2).join(', ');
  }

  function paintStats() {
    $('#stat-total').textContent = (STATS.total ?? ALL.length).toString();
    $('#stat-tier1').textContent = ALL.filter(a => a.commute_tier === 1).length.toString();
    $('#stat-budget').textContent = ALL.filter(a => (a.monthly_aed || 0) <= 6000).length.toString();
    $('#stat-updated').textContent = relTime(STATS.generated_at);
  }

  function applyFilters() {
    const q = state.q.trim().toLowerCase();
    let list = ALL.filter(a => {
      if (state.area && a.area !== state.area) return false;
      if (state.source && a.source !== state.source) return false;
      if ((a.monthly_aed || 0) > state.maxMonthly) return false;
      if ((a.commute_tier || 5) > state.maxTier) return false;
      if (state.chips.tier1 && a.commute_tier !== 1) return false;
      if (state.chips.under5k && (a.monthly_aed || 0) > 5000) return false;
      if (state.chips.parking && !(a.amenities || []).some(x => /park/i.test(x))) return false;
      if (state.chips.gym && !(a.amenities || []).some(x => /gym|pool/i.test(x))) return false;
      if (state.chips.largesize && (a.size_sqft || 0) < 600) return false;
      if (q) {
        const hay = [a.title, a.area, a.full_location, a.broker, a.agent_name, (a.amenities||[]).join(' '), a.description].join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    list.sort((a, b) => {
      switch (state.sort) {
        case 'price-asc':  return (a.price_aed ?? Infinity) - (b.price_aed ?? Infinity);
        case 'price-desc': return (b.price_aed ?? -Infinity) - (a.price_aed ?? -Infinity);
        case 'size-desc':  return (b.size_sqft ?? 0) - (a.size_sqft ?? 0);
        case 'score':      return (b.score ?? 0) - (a.score ?? 0);
        default:           // tier asc, then price asc
          return (a.commute_tier - b.commute_tier) || (a.price_aed - b.price_aed);
      }
    });

    state.filtered = list;
    state.rendered = 0;
    renderInitial();
    paintCounts();
  }

  function paintCounts() {
    const shown = state.filtered.length;
    const tier1 = state.filtered.filter(a => a.commute_tier === 1).length;
    $('#count-shown').textContent = shown.toLocaleString();
    $('#count-total').textContent = (STATS.total ?? ALL.length).toLocaleString();
    $('#count-tier1').textContent = tier1.toLocaleString();
    $('#empty').hidden = shown !== 0;
    $('#list').hidden = state.view !== 'list' || shown === 0;
    $('#grid').hidden = state.view !== 'grid' || shown === 0;
  }

  function thumbHTML(a) {
    if (!a.image) return '<div class="row__noimg">NO IMG</div>';
    return `<img loading="lazy" decoding="async" src="${escapeHtml(a.image)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'row__noimg',textContent:'NO IMG'}))" />`;
  }
  function cardImgHTML(a) {
    if (!a.image) return '<div class="card__noimg">No image<br>provided</div>';
    return `<img loading="lazy" decoding="async" src="${escapeHtml(a.image)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'card__noimg',innerHTML:'No image<br>provided'}))" />`;
  }

  function rowHTML(a) {
    const tier = a.commute_tier || 4;
    const tierCls = `row--tier${tier}`;
    const tierName = a.tier_name || '?';
    const score = Math.round(a.score ?? 0);
    const scoreTier = tierClass(score >= 80 ? 1 : score >= 65 ? 2 : score >= 50 ? 3 : 4);

    return `
      <article class="row ${tierCls}" tabindex="0" data-id="${escapeHtml(a.ad_id)}">
        <div class="row__thumb">${thumbHTML(a)}</div>
        <div class="row__main">
          <h3 class="row__title">
            <span class="row__tierTag row__tierTag--${tier}">T${tier} · ${escapeHtml(tierName)}</span>
            <span>${escapeHtml(a.title || a.area || 'Untitled')}</span>
          </h3>
          <div class="row__meta">
            <span class="num">${a.bedrooms ?? '—'} BR</span>
            <span class="num">${a.size_sqft ? a.size_sqft + ' sqft' : '—'}</span>
            <span>${escapeHtml(a.area)}</span>
            <span class="loc">${escapeHtml(locShort(a.full_location))}</span>
          </div>
        </div>
        <div class="row__price">
          <span class="ccy">AED/mo</span>
          <span class="num">${fmtAed(a.monthly_aed)}</span>
          <span class="row__monthly">yearly ${fmtAed(a.price_aed)}</span>
        </div>
        <div class="row__score row__score--${scoreTier}">${score}<span class="lbl">/100</span></div>
        <div class="row__tags">
          <span class="tag tag--src">${escapeHtml(a.source || '—')}</span>
        </div>
        <button class="row__ext" data-ext aria-label="Open original" tabindex="-1">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>
        </button>
      </article>
    `;
  }

  function cardHTML(a) {
    const tier = a.commute_tier || 4;
    const score = Math.round(a.score ?? 0);
    const scoreTier = tierClass(score >= 80 ? 1 : score >= 65 ? 2 : score >= 50 ? 3 : 4);
    return `
      <article class="card card--tier${tier}" tabindex="0" data-id="${escapeHtml(a.ad_id)}">
        <div class="card__media">
          <div class="card__tierBar card__tierBar--${tier}"></div>
          <span class="card__tierPill card__tierPill--${tier}">T${tier}</span>
          <span class="card__src">${escapeHtml(a.source || '—')}</span>
          ${cardImgHTML(a)}
          <span class="card__score card__score--${scoreTier}">${score}</span>
        </div>
        <div class="card__body">
          <div class="card__row1">
            <h3 class="card__title">${escapeHtml(a.title || a.area || 'Untitled')}</h3>
            <div class="card__price"><span class="ccy">AED</span>${fmtAed(a.monthly_aed)}<span style="font-size:10px;color:var(--ink-3)">/mo</span></div>
          </div>
          <div class="card__meta">
            <span class="num">${a.size_sqft ? a.size_sqft + ' sqft' : '—'}</span>
            <span>${escapeHtml(a.area)}</span>
            <span class="loc">${escapeHtml(locShort(a.full_location))}</span>
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
    const tmp = document.createElement('div'); tmp.innerHTML = html;
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

  function populateAreas() {
    const sel = $('#area');
    const counts = {};
    ALL.forEach(a => counts[a.area] = (counts[a.area] || 0) + 1);
    Object.entries(counts).sort((a, b) => b[1] - a[1]).forEach(([n, c]) => {
      const opt = document.createElement('option');
      opt.value = n; opt.textContent = `${n} (${c})`;
      sel.appendChild(opt);
    });
  }

  const SUB_LABELS = {
    commute: 'Commute to DAFZA',
    budget: 'Budget headroom',
    size: 'Size',
    amenities: 'Amenities',
    bathrooms: 'Bathrooms',
    image: 'Image',
  };

  function openModal(a) {
    const modal = $('#modal');
    modal.hidden = false;

    $('#m-media').innerHTML = a.image
      ? `<img src="${escapeHtml(a.image)}" alt="${escapeHtml(a.title || '')}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'card__noimg',innerHTML:'No image provided'}))" />`
      : `<div class="card__noimg">No image provided</div>`;

    $('#m-area').textContent = `${a.area} · Tier ${a.commute_tier} · ${a.tier_name || ''}`;
    $('#m-title').textContent = a.title || a.area || 'Listing';
    $('#m-loc').textContent = a.full_location || '—';
    $('#m-monthly').textContent = fmtAed(a.monthly_aed);
    $('#m-yearly').textContent = 'AED ' + fmtAed(a.price_aed);

    const tier = a.commute_tier || 4;
    const tierEl = $('#m-tier');
    tierEl.textContent = `TIER ${tier} · ${(a.tier_name || '').toUpperCase()}`;
    tierEl.className = 'modal__ratingTag is-' + tierClass(tier);

    const kv = $('#m-kv'); kv.innerHTML = '';
    const rows = [
      ['Bedrooms', `${a.bedrooms ?? '—'}`],
      ['Bathrooms', a.bathrooms ?? '—'],
      ['Size', a.size_sqft ? `${a.size_sqft} sqft` : '—'],
      ['Furnished', a.furnished ? 'Yes' : 'No'],
      ['Source', a.source || '—'],
      ['Broker', a.broker || '—'],
      ['Agent', a.agent_name || '—'],
      ['Yearly', `AED ${fmtAed(a.price_aed)}`],
      ['Monthly', `AED ${fmtAed(a.monthly_aed)}`],
      ['Within 6K/mo', a.within_budget ? 'Yes' : 'No'],
    ];
    rows.forEach(([k, v]) => {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = v;
      if (k === 'Within 6K/mo' && a.within_budget) dd.classList.add('is-sun');
      kv.appendChild(dt); kv.appendChild(dd);
    });

    const subs = a.sub_scores || {};
    $('#m-bars').innerHTML = Object.keys(SUB_LABELS).map(k => {
      const v = Math.round(subs[k] ?? 0);
      const isCommute = k === 'commute';
      return `
        <div class="bar ${isCommute ? 'bar--sun' : ''}">
          <div class="bar__head"><span>${SUB_LABELS[k]}</span><span class="v">${v}</span></div>
          <div class="bar__track"><div class="bar__fill" style="width:${Math.max(0, Math.min(100, v))}%"></div></div>
        </div>
      `;
    }).join('');

    const feats = a.amenities || [];
    $('#m-feat').innerHTML = feats.length
      ? feats.map(f => `<span class="feat">${escapeHtml(f)}</span>`).join('')
      : '<span class="feat">No amenities listed</span>';

    $('#m-desc').textContent = a.description || 'No description provided.';
    const link = $('#m-link');
    if (a.url) { link.href = a.url; link.style.display = ''; } else { link.removeAttribute('href'); link.style.display = 'none'; }

    document.body.style.overflow = 'hidden';
  }
  function closeModal() {
    $('#modal').hidden = true;
    document.body.style.overflow = '';
  }

  function syncRangeFill(input) {
    const min = +input.min, max = +input.max, val = +input.value;
    input.style.setProperty('--pct', ((val - min) / (max - min)) * 100 + '%');
  }

  function init() {
    paintStats();

    let qTimer;
    $('#q').addEventListener('input', e => {
      clearTimeout(qTimer);
      qTimer = setTimeout(() => { state.q = e.target.value; applyFilters(); }, 110);
    });
    $('#area').addEventListener('change', e => { state.area = e.target.value; applyFilters(); });
    $('#source').addEventListener('change', e => { state.source = e.target.value; applyFilters(); });

    const priceEl = $('#price'); const pricePill = $('#price-pill'); const priceVal = $('#price-val');
    syncRangeFill(priceEl);
    priceEl.addEventListener('input', e => {
      state.maxMonthly = +e.target.value;
      pricePill.textContent = (state.maxMonthly / 1000).toFixed(state.maxMonthly % 1000 ? 1 : 0) + 'K';
      priceVal.textContent = 'AED ' + state.maxMonthly.toLocaleString();
      syncRangeFill(priceEl);
      applyFilters();
    });

    const tierEl = $('#tier'); const tierPill = $('#tier-pill'); const tierValEl = $('#tier-val');
    syncRangeFill(tierEl);
    tierEl.addEventListener('input', e => {
      state.maxTier = +e.target.value;
      const label = state.maxTier === 4 ? 'any' : `≤ T${state.maxTier}`;
      tierPill.textContent = label;
      tierValEl.textContent = state.maxTier === 4 ? 'any' : `tier ${state.maxTier}`;
      syncRangeFill(tierEl);
      applyFilters();
    });

    $('#sort').addEventListener('change', e => { state.sort = e.target.value; applyFilters(); });

    $$('.seg__btn').forEach(btn => btn.addEventListener('click', () => switchView(btn.dataset.view)));

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
      state.area = ''; $('#area').value = '';
      state.source = ''; $('#source').value = '';
      state.maxMonthly = 6000; priceEl.value = 6000;
      pricePill.textContent = '6K'; priceVal.textContent = 'AED 6,000'; syncRangeFill(priceEl);
      state.maxTier = 4; tierEl.value = 4;
      tierPill.textContent = 'any'; tierValEl.textContent = 'any'; syncRangeFill(tierEl);
      Object.keys(state.chips).forEach(k => state.chips[k] = false);
      $$('.chip[data-chip]').forEach(b => b.classList.remove('is-active'));
      state.sort = 'tier'; $('#sort').value = 'tier';
      applyFilters();
    }

    populateAreas();

    function bindOpen(container) {
      container.addEventListener('click', e => {
        if (e.target.closest('[data-ext]')) {
          e.stopPropagation();
          const card = e.target.closest('[data-id]');
          if (card) {
            const a = ALL.find(x => x.ad_id === card.dataset.id);
            if (a && a.url) window.open(a.url, '_blank', 'noopener');
          }
          return;
        }
        const card = e.target.closest('[data-id]');
        if (!card) return;
        const a = ALL.find(x => x.ad_id === card.dataset.id);
        if (a) openModal(a);
      });
      container.addEventListener('keydown', e => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const card = e.target.closest('[data-id]');
        if (!card) return;
        e.preventDefault();
        const a = ALL.find(x => x.ad_id === card.dataset.id);
        if (a) openModal(a);
      });
    }
    bindOpen($('#list'));
    bindOpen($('#grid'));

    $('#modal').addEventListener('click', e => { if (e.target.matches('[data-close]')) closeModal(); });

    document.addEventListener('keydown', e => {
      const inField = e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA');
      if (e.key === 'Escape') {
        if (!$('#modal').hidden) closeModal();
        else if (document.activeElement === $('#q')) $('#q').blur();
        return;
      }
      if (inField) return;
      if (e.key === '/' || e.key === 's') { e.preventDefault(); $('#q').focus(); $('#q').select(); }
      else if (e.key === 'g' || e.key === 'G') switchView('grid');
      else if (e.key === 'l' || e.key === 'L') switchView('list');
    });

    document.addEventListener('click', e => {
      $$('.popover[open]').forEach(p => { if (!p.contains(e.target)) p.removeAttribute('open'); });
    });

    const sentinel = $('#sentinel');
    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting && state.rendered < state.filtered.length) renderMore();
      }, { rootMargin: '800px' });
      io.observe(sentinel);
    }

    applyFilters();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
