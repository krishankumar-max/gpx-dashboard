/* ================================================================
   Game Perfomix — Dashboard JS
   Pages: Home · Health Check · Performance · Publishers · Offers
          Administration · Management
   ================================================================ */
'use strict';

// ── Plotly base config ────────────────────────────────────────────
const PC = { responsive: true, displayModeBar: false };
const L = {
  paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
  font: { family: 'Inter, sans-serif', color: '#64748b', size: 12 },
  xaxis: { gridcolor: '#f1f5f9', zeroline: false, color: '#94a3b8', linecolor: '#e2e8f0', tickfont: { size: 11 } },
  yaxis: { gridcolor: '#f1f5f9', zeroline: false, color: '#94a3b8', linecolor: '#e2e8f0', tickfont: { size: 11 } },
  legend: { bgcolor: 'transparent', font: { color: '#64748b', size: 12 }, bordercolor: 'transparent' },
  hoverlabel: { bgcolor: '#0f172a', bordercolor: 'rgba(255,255,255,0.1)', font: { family: 'Inter, sans-serif', color: '#f1f5f9', size: 12 } },
  margin: { t: 20, r: 16, b: 48, l: 70 },
};
const C = {
  blue:'#3b82f6', red:'#ef4444', green:'#10b981', amber:'#f59e0b',
  purple:'#8b5cf6', sky:'#0ea5e9', teal:'#0d9488', pink:'#ec4899',
  palette:['#3b82f6','#8b5cf6','#0ea5e9','#10b981','#f59e0b','#ec4899','#f97316','#0d9488','#6366f1','#a855f7','#14b8a6','#84cc16'],
};

// ── Page / tab metadata ───────────────────────────────────────────
const PAGES = {
  overview       : 'Home',
  health         : 'Health Check',
  publishers     : 'Publishers',
  offers         : 'Offers',
  analytics      : 'Performance',
  administration : 'Administration',
};
const DEFAULT_TABS = {
  publishers     : 'summary',
  offers         : 'summary',
  analytics      : 'trend',
  administration : 'sync',
};
const tabState = {};   // { page: activeTab }
// Performance — Daily Trend tab state
let _perfChartType = 'line';
let _perfCompData  = null;

// ── App state ─────────────────────────────────────────────────────
const state = { from_date:'', to_date:'', partners:[], offers:[], page:'overview' };
const _loaded = new Set();
let tsPartner, tsOffer;

// ── Partner name mapping: publisher_id → partner_name ─────────────────────────
// Loaded once at init and refreshed after any publisher CRUD operation.
window._partnerMap = {};

// ── Offer ID mapping: offerName → offer_id ────────────────────────────────────
// Loaded once at init from /api/offers/map (built from raw parquet files).
window._offerMap = {};

function _partnerLabel(id) {
  if (id == null || id === '') return '—';
  const sid  = String(id);
  const name = window._partnerMap[sid];
  return name ? `${name} (${sid})` : `Unknown Publisher (${sid})`;
}
let _cascadeInProgress = false, _cascadeTimer = null, _reloadTimer = null;

// ── Formatters ────────────────────────────────────────────────────
const fmtN   = n => n==null||isNaN(n) ? '—' : Number(n).toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2});
const fmtI   = n => n==null||isNaN(n) ? '—' : Number(n).toLocaleString('en-IN');
const fmtCur = n => n==null||isNaN(n) ? '—' : '$'+fmtN(n);
const fmtPct = n => n==null||isNaN(n) ? '—' : fmtN(n)+'%';
const esc    = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fmtChange = (pct) => {
  if (pct == null) return '<span class="cmp-pct cmp-flat">—</span>';
  const cls = pct >= 0 ? 'cmp-up' : 'cmp-down';
  const arrow = pct >= 0 ? '▲' : '▼';
  return `<span class="cmp-pct ${cls}">${arrow} ${Math.abs(pct)}%</span>`;
};
const trendChip = (pct) => {
  if (pct == null) return '<span class="trend-flat">—</span>';
  if (pct >= 0) return `<span class="trend-up">▲ ${pct}%</span>`;
  return `<span class="trend-down">▼ ${Math.abs(pct)}%</span>`;
};
const recBadge = (action) => {
  const cls = { Scale:'rec-scale', Monitor:'rec-monitor', Optimize:'rec-optimize', Pause:'rec-pause' }[action] || '';
  return `<span class="rec-badge ${cls}">${action}</span>`;
};
const marginColor  = (mp) => mp >= 30 ? C.green : mp >= 15 ? C.amber : mp >= 0 ? C.red : '#7f1d1d';
// Derives status label from margin % — single source of truth used everywhere
const marginStatus = (mp) => mp > 30 ? 'Scale' : mp >= 15 ? 'Monitor' : mp >= 0 ? 'Optimize' : 'Pause';
const statusBadge  = (mp) => recBadge(marginStatus(mp));

// ── Helpers ───────────────────────────────────────────────────────
function qs(extra={}) {
  const p = new URLSearchParams();
  if (state.from_date) p.set('from_date', state.from_date);
  if (state.to_date)   p.set('to_date',   state.to_date);
  if (state.partners.length) p.set('partners', state.partners.join(','));
  if (state.offers.length)   p.set('offers',   state.offers.join(','));
  for (const [k,v] of Object.entries(extra)) p.set(k,v);
  return p.toString();
}

async function api(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

function loading(on) {
  document.getElementById('loading-bar').classList.toggle('active', on);
  document.getElementById('btn-refresh')?.classList.toggle('loading', on);
}

function noChart(id, msg='No data for the selected range') {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = `<div class="no-chart-msg"><i class="fas fa-chart-bar"></i><p>${msg}</p></div>`;
}

function showEmpty(emptyId, contentId, msg) {
  const e = document.getElementById(emptyId);
  const c = document.getElementById(contentId);
  if (e) e.style.display = '';
  if (c) c.classList.add('d-none');
  if (msg && e) {
    const sub = e.querySelector('.funnel-empty-sub');
    if (sub) sub.innerHTML = msg;
  }
}
function showContent(emptyId, contentId) {
  document.getElementById(emptyId).style.display = 'none';
  document.getElementById(contentId).classList.remove('d-none');
}

// ── Sub-tab routing ───────────────────────────────────────────────
function switchTab(page, tab) {
  tabState[page] = tab;
  document.querySelectorAll(`#page-${page} .tab-btn`).forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll(`#page-${page} .tab-content`).forEach(el =>
    el.classList.toggle('active', el.dataset.tab === tab));
  loadTabData(page, tab);
}

async function loadTabData(page, tab) {
  const key = `${page}:${tab}`;
  if (_loaded.has(key)) return;
  loading(true);
  try {
    switch(key) {
      case 'publishers:summary':         await loadPubSummary();         break;
      case 'offers:summary':             await loadOffersSummary();      break;
      case 'offers:funnel':              await loadFunnelData();         break;
      case 'analytics:weekly':           await loadAnalyticsWeekly();    break;
      case 'analytics:monthly':          await loadAnalyticsMonthly();   break;
      case 'analytics:trend':            await loadAnalyticsTrend();     break;
      case 'administration:sync':        await loadAdministration();     break;
      case 'administration:publishers':  await loadPubList();            break;
      case 'administration:games':       await loadGamesList();          break;
      case 'administration:clients':     await loadClientList();         break;
    }
    _loaded.add(key);
  } finally {
    loading(false);
  }
}

// ── Page routing ──────────────────────────────────────────────────
function navigateTo(page) {
  if (!PAGES[page]) return;
  state.page = page;
  document.querySelectorAll('.sb-item').forEach(el =>
    el.classList.toggle('active', el.dataset.page === page));
  document.querySelectorAll('.page').forEach(el =>
    el.classList.toggle('active', el.id === `page-${page}`));
  document.getElementById('tb-page-name').textContent = PAGES[page];
  history.replaceState(null,'','#'+page);

  if (!_loaded.has(page)) loadPageData(page);
}

async function loadPageData(page) {
  const tab = tabState[page] || DEFAULT_TABS[page];
  switch(page) {
    case 'overview':        await loadOverview(); break;
    case 'health':          await loadHealthCheck(); break;
    case 'publishers':      await loadTabData(page, tab || 'summary'); break;
    case 'offers':          await loadTabData(page, tab || 'summary'); break;
    case 'analytics':       await loadTabData(page, tab || 'trend'); break;
    case 'administration':  await loadTabData(page, tab || 'sync'); break;
  }
  _loaded.add(page);
}

// ── Tom Select ────────────────────────────────────────────────────
function makeTomSelect(id, onChange) {
  return new TomSelect('#'+id, {
    plugins: ['remove_button','checkbox_options'], maxOptions:1000,
    hidePlaceholder: false, onchange: onChange,
    render: { no_results: () => '<div style="padding:10px 12px;color:#94a3b8">No matches</div>' },
  });
}
function populateTS(ts, items, keep=[], labelFn=null) {
  ts.clearOptions(); ts.clear(true);
  items.forEach(v => ts.addOption({value:v, text: labelFn ? labelFn(v) : v}));
  ts.refreshOptions(false);
  const valid = keep.filter(v => items.includes(v));
  if (valid.length) ts.setValue(valid, true);
}

// ── Filter cascade ────────────────────────────────────────────────
function syncState() {
  state.from_date = document.getElementById('from-date').value;
  state.to_date   = document.getElementById('to-date').value;
  state.partners  = tsPartner ? [...tsPartner.getValue()] : [];
  state.offers    = tsOffer   ? [...tsOffer.getValue()]   : [];
}

async function cascadeFilters() {
  if (_cascadeInProgress) return;
  _cascadeInProgress = true;
  syncState();
  if (state.from_date && state.to_date && state.from_date > state.to_date) {
    _cascadeInProgress = false; return;
  }
  try {
    const data = await api('/api/filters?'+qs());
    populateTS(tsPartner, data.partners, state.partners.filter(p => data.partners.includes(p)), _partnerLabel);
    populateTS(tsOffer,   data.offers,   state.offers.filter(o => data.offers.includes(o)));
    state.partners = tsPartner ? [...tsPartner.getValue()] : [];
    state.offers   = tsOffer   ? [...tsOffer.getValue()]   : [];
    updateDateBadge();
  } catch(e) { console.warn('cascadeFilters:', e); }
  finally { _cascadeInProgress = false; }
  clearTimeout(_reloadTimer);
  _reloadTimer = setTimeout(_reloadCurrentPage, 280);
}

async function _reloadCurrentPage() {
  _loaded.clear();
  loading(true);
  try {
    if (state.page === 'publisher-detail') {
      await loadPublisherProfile();
    } else if (state.page === 'offer-detail') {
      await loadOfferProfile();
    } else if (state.page === 'pub-offer') {
      await loadPubOfferDetail();
    } else {
      await loadPageData(state.page);
    }
  }
  finally { loading(false); }
}

function onDateChange() {
  clearTimeout(_cascadeTimer);
  _cascadeTimer = setTimeout(cascadeFilters, 420);
}

function resetFilters() {
  _cascadeInProgress = true;
  try {
    const b = document.body;
    document.getElementById('from-date').value = b.dataset.defaultFrom;
    document.getElementById('to-date').value   = b.dataset.defaultTo;
    if (tsPartner) tsPartner.clear(true);
    if (tsOffer)   tsOffer.clear(true);
    state.partners=[]; state.offers=[];
    state.from_date = b.dataset.defaultFrom;
    state.to_date   = b.dataset.defaultTo;
  } finally { _cascadeInProgress = false; }
  cascadeFilters();
}

async function refreshAll() {
  _loaded.clear(); loading(true);
  try {
    await cascadeFilters();
    if (state.page === 'publisher-detail') {
      await loadPublisherProfile();
    } else if (state.page === 'offer-detail') {
      await loadOfferProfile();
    } else if (state.page === 'pub-offer') {
      await loadPubOfferDetail();
    } else {
      await loadPageData(state.page);
    }
  }
  finally { loading(false); }
}

function updateDateBadge() {
  const el = document.getElementById('tb-date-text');
  if (!el) return;
  const f = state.from_date||'—', t = state.to_date||'—';
  el.textContent = f===t ? f : `${f} → ${t}`;
}

// ── Status ────────────────────────────────────────────────────────
async function loadStatus() {
  try {
    const d = await api('/api/status');
    const badge = document.getElementById('tb-sync-badge');
    const dot   = document.getElementById('sb-dot');
    const txt   = document.getElementById('sb-status-text');
    const sub   = document.getElementById('sb-status-sub');
    if (d.has_data) {
      if (badge) { badge.className='tb-badge tb-badge-status online'; badge.innerHTML=`<i class="fas fa-circle" style="font-size:7px"></i> <span>${d.available_days} days synced</span>`; }
      if (dot) dot.className='sb-status-dot online';
      if (txt) txt.textContent='Data up to date';
      if (sub) sub.textContent=`${d.min_date} → ${d.max_date}`;
    } else {
      if (badge) badge.innerHTML='<i class="fas fa-exclamation-triangle" style="color:#f59e0b"></i> <span>No data</span>';
      document.getElementById('no-data-notice')?.classList.remove('d-none');
    }
  } catch { }
}

// ══════════════════════════════════════════════════════════════════
//  OVERVIEW PAGE
// ══════════════════════════════════════════════════════════════════

let _trendDays = 7;   // active day-range selection for the trend chart

async function loadOverview() {
  await Promise.all([
    loadOverviewKPIs(),
    loadOverviewComparisons(),
    loadOverviewTrend(_trendDays),
    loadOverviewLeaderboards(),
  ]);
}

// ── Health Check (Phase 6 — stub) ────────────────────────────────
// ══════════════════════════════════════════════════════════════════
//  OFFER PROFILE (360° offer page)
//  Entered from: Offers list → click an offer row
//  Also the root for Offer → Publisher drill-down
// ══════════════════════════════════════════════════════════════════

let _opOffer       = null;
let _opTrendData   = [];
let _opTrendMetric = 'revenue';
let _opPubData     = [];
let _opPubSort     = { col: 'profit', dir: -1 };
let _opPubPage     = 0;
const _OP_PAGE_SIZE = 50;

function openOfferProfile(offer) {
  _opOffer       = offer;
  state.page     = 'offer-detail';

  document.querySelectorAll('.sb-item').forEach(el =>
    el.classList.toggle('active', el.dataset.page === 'offers'));
  document.querySelectorAll('.page').forEach(el =>
    el.classList.toggle('active', el.id === 'page-offer-detail'));

  document.getElementById('tb-page-name').textContent = 'Offer Profile';
  document.getElementById('op-offer-crumb').textContent = _fmtOfferName(offer);
  history.replaceState(null, '', '#offer-detail');

  _opTrendMetric = 'revenue';
  document.querySelectorAll('#op-metric-btns .trend-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.m === 'revenue'));

  loading(true);
  loadOfferProfile().finally(() => loading(false));
}

async function loadOfferProfile() {
  if (!_opOffer) { navigateTo('offers'); return; }

  console.log('[OP] loadOfferProfile start, offer=', _opOffer);
  let data;
  try {
    data = await api('/api/offers/profile?' + qs({ offer: _opOffer }));
    console.log('[OP] API response: stats.revenue=', data?.stats?.revenue,
      'trend rows=', data?.trend?.length, 'publishers=', data?.publishers?.length);
  } catch(e) {
    console.error('[OP] API fetch failed:', e);
    return;
  }

  const { stats = {}, publishers = [], trend = [], ranking = {}, activity = {},
          funnel = [], funnel_summary = {},
          has_expected: opHasExpected = false } = data;

  document.getElementById('op-title').textContent = _fmtOfferName(_opOffer);
  document.getElementById('op-sub').textContent   = `${stats.active_publishers || 0} active publishers`;
  document.getElementById('op-status').innerHTML  = statusBadge(stats.margin_pct || 0);

  try { _opRenderKPIs(stats); } catch(e) { console.error('[OP] _opRenderKPIs:', e); }

  _opTrendData = trend;
  console.log('[OP] trend data set, rows=', trend.length, 'first=', trend[0]);
  try { renderOPTrend(); } catch(e) { console.error('[OP] renderOPTrend:', e); noChart('chart-op-trend', 'Chart error'); }

  try { _opRenderActionQueue(publishers); } catch(e) { console.error('[OP] _opRenderActionQueue:', e); }
  try { _opRenderPublishers(publishers); } catch(e) { console.error('[OP] _opRenderPublishers:', e); }
  try { _opRenderFunnel(funnel, funnel_summary, opHasExpected); } catch(e) { console.error('[OP] _opRenderFunnel:', e); }
  try { _opRenderConcentration(publishers, stats.revenue || 0); } catch(e) { console.error('[OP] _opRenderConcentration:', e); }
  try { _opRenderRankingActivity(ranking, activity); } catch(e) { console.error('[OP] _opRenderRankingActivity:', e); }
  console.log('[OP] loadOfferProfile done');
}

function _opRenderKPIs(s) {
  const mpClr = marginColor(s.margin_pct || 0);
  const pfClr = (s.profit || 0) >= 0 ? C.green : C.red;
  const cards = [
    { label: 'Revenue',    value: fmtCur(s.revenue),            icon: 'fa-dollar-sign', iconBg: '#eff6ff', iconClr: C.blue  },
    { label: 'Cost',       value: fmtCur(s.cost),               icon: 'fa-money-bill-wave',   iconBg: '#fef2f2', iconClr: C.red   },
    { label: 'Profit',     value: fmtCur(s.profit),             icon: 'fa-arrow-trend-up',    iconBg: '#ecfdf5', iconClr: pfClr   },
    { label: 'Margin %',   value: fmtPct(s.margin_pct),         icon: 'fa-percent',           iconBg: '#fffbeb', iconClr: '#d97706',
      valStyle: `color:${mpClr};font-weight:800` },
    { label: 'Conversions',   value: fmtI(s.installs || 0),        icon: 'fa-mobile-screen',     iconBg: '#f0fdf4', iconClr: C.green },
    { label: 'Publishers', value: fmtI(s.active_publishers || 0), icon: 'fa-network-wired',   iconBg: '#f0f9ff', iconClr: C.sky   },
  ];
  document.getElementById('op-kpis').innerHTML = cards.map(c => `
    <div class="kpi-card" style="--kpi-color:${c.iconClr};padding:16px">
      <div class="kpi-top">
        <div class="kpi-icon" style="background:${c.iconBg};color:${c.iconClr};width:30px;height:30px;font-size:12px">
          <i class="fas ${c.icon}"></i>
        </div>
      </div>
      <div class="kpi-label">${c.label}</div>
      <div class="kpi-value" style="font-size:19px;${c.valStyle || ''}">${c.value}</div>
    </div>`).join('');
}

function setOPMetric(btn, metric) {
  _opTrendMetric = metric;
  document.querySelectorAll('#op-metric-btns .trend-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.m === metric));
  renderOPTrend();
}

function renderOPTrend() {
  console.log('[OP] renderOPTrend: rows=', _opTrendData?.length, 'metric=', _opTrendMetric);
  if (!_opTrendData.length) { noChart('chart-op-trend', 'No trend data for selected range'); return; }
  const m   = _opTrendMetric;
  const cfg = {
    revenue:    { label: 'Revenue',  color: C.blue,  prefix: '$', suffix: '' },
    profit:     { label: 'Profit',   color: C.green, prefix: '$', suffix: '' },
    margin_pct: { label: 'Margin %', color: C.teal,  prefix: '',  suffix: '%' },
    installs:   { label: 'Conversions', color: C.sky,   prefix: '',  suffix: ''  },
  }[m] || { label: m, color: C.blue, prefix: '', suffix: '' };
  const vals  = _opTrendData.map(d => d[m] ?? 0);
  const dates = _opTrendData.map(d => d.date);
  const fill  = cfg.color.startsWith('#')
    ? cfg.color + '14'
    : cfg.color.replace(')', ',0.08)').replace('rgb', 'rgba');
  console.log('[OP] Plotly.react chart-op-trend, y sample=', vals.slice(0,3));
  Plotly.react('chart-op-trend', [{
    x: dates, y: vals, type: 'scatter', mode: 'lines+markers',
    name: cfg.label,
    line:   { color: cfg.color, width: 2.5 },
    marker: { color: cfg.color, size: 5 },
    fill: 'tozeroy', fillcolor: fill,
    hovertemplate: `%{x}<br>${cfg.label}: ${cfg.prefix}%{y:,.1f}${cfg.suffix}<extra></extra>`,
  }], {
    ...L,
    xaxis: { ...L.xaxis, tickformat: '%b %d', nticks: 10 },
    yaxis: { ...L.yaxis, tickprefix: cfg.prefix, ticksuffix: cfg.suffix, rangemode: 'tozero' },
    showlegend: false,
    margin: { l: 52, r: 12, t: 10, b: 40 },
  }, PC);
}

function _opRenderActionQueue(publishers) {
  const groups = [
    { key: 'Scale',    color: C.green, sort: (a, b) => b.margin_pct - a.margin_pct },
    { key: 'Monitor',  color: C.blue,  sort: (a, b) => b.margin_pct - a.margin_pct },
    { key: 'Optimize', color: C.amber, sort: (a, b) => a.margin_pct - b.margin_pct },
    { key: 'Pause',    color: C.red,   sort: (a, b) => a.margin_pct - b.margin_pct },
  ];
  const html = `<div class="pp-aq-grid">${
    groups.map(g => {
      const items = publishers
        .filter(r => marginStatus(r.margin_pct) === g.key)
        .sort(g.sort)
        .slice(0, 5);
      const rows = items.length
        ? items.map(r => `
          <div class="pp-aq-item" data-partner="${esc(r.partner)}" data-offer="${esc(_opOffer)}"
               onclick="openPubOfferDetail(this.dataset.partner, this.dataset.offer, 'offer')">
            <span class="pp-aq-name" title="${esc(_partnerLabel(r.partner))}">${esc(_partnerLabel(r.partner))}</span>
            <span class="pp-aq-pct" style="color:${g.color}">${fmtN(r.margin_pct)}%</span>
          </div>`).join('')
        : `<div class="pp-aq-none">None</div>`;
      return `<div class="pp-aq-col">
        <div class="pp-aq-hdr">
          <span style="font-size:12px;font-weight:700;color:${g.color}">${g.key}</span>
        </div>
        ${rows}
      </div>`;
    }).join('')
  }</div>`;
  document.getElementById('op-aq-body').innerHTML = html;
}

// ── Publisher Performance table ───────────────────────────────────

function _opRenderPublishers(publishers) {
  _opPubData = publishers;
  _opPubPage = 0;
  _opPubSort = { col: 'profit', dir: -1 };
  ['op-pub-search','op-pub-status','op-pub-active','op-margin-min','op-margin-max',
   'op-install-min','op-install-max'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  _opUpdateSortIcons();
  _opApplyAndRender();
}

function opSortBy(col) {
  if (_opPubSort.col === col) {
    _opPubSort.dir *= -1;
  } else {
    _opPubSort = { col, dir: col === 'partner' ? 1 : -1 };
  }
  _opPubPage = 0;
  _opUpdateSortIcons();
  _opApplyAndRender();
}

function _opUpdateSortIcons() {
  const cols = ['partner','revenue','profit','margin_pct','installs','last_activity'];
  cols.forEach(c => {
    const icon = document.getElementById(`opi-${c}`);
    const th   = document.getElementById(`opth-${c}`);
    if (!icon || !th) return;
    const active = _opPubSort.col === c;
    icon.className = `pp-sort-icon${active ? ' pp-sort-active' : ''}`;
    icon.textContent = active ? (_opPubSort.dir === -1 ? '↓' : '↑') : '⇅';
  });
}

function opPubFilter() { _opPubPage = 0; _opApplyAndRender(); }

function opPubReset() {
  ['op-pub-search','op-pub-status','op-pub-active','op-margin-min','op-margin-max',
   'op-install-min','op-install-max'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  _opPubPage = 0;
  _opApplyAndRender();
}

function _opApplyAndRender() {
  const search    = (document.getElementById('op-pub-search')?.value  || '').toLowerCase();
  const statusF   = document.getElementById('op-pub-status')?.value  || '';
  const activeF   = document.getElementById('op-pub-active')?.value  || '';
  const marginMin = parseFloat(document.getElementById('op-margin-min')?.value);
  const marginMax = parseFloat(document.getElementById('op-margin-max')?.value);
  const instMin   = parseFloat(document.getElementById('op-install-min')?.value);
  const instMax   = parseFloat(document.getElementById('op-install-max')?.value);

  let rows = _opPubData.filter(r => {
    const label = _partnerLabel(r.partner).toLowerCase();
    if (search   && !label.includes(search)) return false;
    if (statusF  && marginStatus(r.margin_pct) !== statusF) return false;
    if (activeF === 'active' && !r.is_active) return false;
    if (activeF === 'paused' && r.is_active)  return false;
    if (!isNaN(marginMin) && r.margin_pct < marginMin) return false;
    if (!isNaN(marginMax) && r.margin_pct > marginMax) return false;
    if (!isNaN(instMin) && (r.installs || 0) < instMin) return false;
    if (!isNaN(instMax) && (r.installs || 0) > instMax) return false;
    return true;
  });

  // Sort
  const { col, dir } = _opPubSort;
  rows.sort((a, b) => {
    const av = col === 'partner' ? _partnerLabel(a.partner) : (a[col] ?? '');
    const bv = col === 'partner' ? _partnerLabel(b.partner) : (b[col] ?? '');
    if (col === 'last_activity') {
      return dir * ((av || '').localeCompare(bv || ''));
    }
    return dir * (typeof av === 'string' ? av.localeCompare(bv) : (av - bv));
  });

  // Paginate
  const total    = rows.length;
  const pageSize = _OP_PAGE_SIZE;
  const pages    = Math.max(1, Math.ceil(total / pageSize));
  _opPubPage     = Math.min(_opPubPage, pages - 1);
  const slice    = rows.slice(_opPubPage * pageSize, (_opPubPage + 1) * pageSize);

  const badge = document.getElementById('op-pub-badge');
  if (badge) badge.textContent = total !== _opPubData.length
    ? `${total} / ${_opPubData.length}` : `${total}`;

  const tbody = document.getElementById('op-pub-body');
  if (tbody) {
    tbody.innerHTML = slice.length ? slice.map(r => {
      const mc = marginColor(r.margin_pct);
      return `<tr style="cursor:pointer" data-partner="${esc(r.partner)}" data-offer="${esc(_opOffer)}"
                  onclick="openPubOfferDetail(this.dataset.partner, this.dataset.offer, 'offer')">
        <td class="td-trunc" title="${esc(_partnerLabel(r.partner))}" style="font-weight:600;max-width:200px">${esc(_partnerLabel(r.partner))}</td>
        <td class="td-num rev">$${fmtN(r.revenue)}</td>
        <td class="td-num" style="color:${r.profit>=0?C.green:C.red};font-weight:600">$${fmtN(r.profit)}</td>
        <td class="td-num" style="font-weight:700;color:${mc}">${fmtN(r.margin_pct)}%</td>
        <td class="td-num">${fmtI(r.installs)}</td>
        <td class="td-center">${_ppTrendIcon(r.trend)}</td>
        <td class="td-num" style="font-size:12px;color:var(--txt-muted)">${_relDays(r.last_activity)}</td>
        <td class="td-center">${statusBadge(r.margin_pct)}</td>
      </tr>`;
    }).join('')
    : `<tr><td colspan="8" class="td-empty">No publishers match the current filters.</td></tr>`;
  }

  // Pagination
  const pag = document.getElementById('op-pagination');
  if (pag) {
    if (pages <= 1) { pag.innerHTML = ''; return; }
    const from = _opPubPage * pageSize + 1;
    const to   = Math.min((_opPubPage + 1) * pageSize, total);
    pag.innerHTML = `
      <span class="pp-pag-info">${from}–${to} of ${total}</span>
      <div class="pp-pag-btns">
        <button class="pp-pag-btn" onclick="_opGoPage(0)" ${_opPubPage===0?'disabled':''} title="First">«</button>
        <button class="pp-pag-btn" onclick="_opGoPage(${_opPubPage-1})" ${_opPubPage===0?'disabled':''}>‹ Prev</button>
        <span class="pp-pag-cur">Page ${_opPubPage+1} / ${pages}</span>
        <button class="pp-pag-btn" onclick="_opGoPage(${_opPubPage+1})" ${_opPubPage>=pages-1?'disabled':''}>Next ›</button>
        <button class="pp-pag-btn" onclick="_opGoPage(${pages-1})" ${_opPubPage>=pages-1?'disabled':''} title="Last">»</button>
      </div>`;
  }
}

function _opGoPage(p) { _opPubPage = p; _opApplyAndRender(); }

// ══════════════════════════════════════════════════════════════════
//  SHARED FUNNEL RENDERER
// ══════════════════════════════════════════════════════════════════

/**
 * Build funnel table HTML (notice + thead + tbody rows).
 * @param {Array}   steps           - funnel step objects from backend
 * @param {boolean} hasExpected     - true → show Expected % + Deviation columns
 * @param {object}  opts
 *   showMoveButtons {bool}  - include ↑↓ reorder buttons in Step cell
 *   showBar         {bool}  - append a visual bar column
 * @returns {{noticeHtml, theadHtml, tbodyHtml, colCount}}
 */
function _funnelHtml(steps, hasExpected, { showMoveButtons = false, showBar = false } = {}) {
  const blank = '<span class="td-first-step">—</span>';

  const noticeHtml = !hasExpected
    ? `<div class="funnel-notice"><i class="fas fa-circle-info"></i> Expected funnel not configured for this game. Showing actual funnel only.</div>`
    : '';

  // Scenario A: Step + Goal + Users + Actual% + Exp% + Deviation + TTC + ExpTime [+ Bar]
  // Scenario B: Step + Goal + Users + Actual% + TTC [+ Bar]
  const colCount = (hasExpected ? 8 : 5) + (showBar ? 1 : 0);

  let theadHtml = '<tr>';
  theadHtml += `<th class="th-center" style="width:${showMoveButtons ? 80 : 44}px">Step</th>`;
  theadHtml += '<th>Goal</th>';
  theadHtml += '<th class="th-num">Users</th>';
  theadHtml += '<th class="th-num">Actual %</th>';
  if (hasExpected) {
    theadHtml += '<th class="th-num">Expected %</th>';
    theadHtml += '<th class="th-num">Deviation</th>';
  }
  theadHtml += '<th class="th-num">Time To Complete</th>';
  if (hasExpected) theadHtml += '<th class="th-num">Expected Time</th>';
  if (showBar) theadHtml += '<th>Progress</th>';
  theadHtml += '</tr>';

  if (!steps.length) {
    const tbodyHtml = `<tr><td colspan="${colCount}" class="td-empty">No funnel data available.</td></tr>`;
    return { noticeHtml, theadHtml, tbodyHtml, colCount };
  }

  const topCnt = steps[0]?.count || 1;

  const tbodyHtml = steps.map((s, i) => {
    const isFirst = i === 0;
    const isLast  = i === steps.length - 1;

    // Step cell
    const stepCell = showMoveButtons
      ? `<div class="funnel-step-cell">
           <button class="funnel-move-btn" onclick="moveFunnelStep(${i},${i-1})" ${i > 0 ? '' : 'disabled'}>↑</button>
           <span class="funnel-step-num">${s.step}</span>
           <button class="funnel-move-btn" onclick="moveFunnelStep(${i},${i+1})" ${!isLast ? '' : 'disabled'}>↓</button>
         </div>`
      : `<span class="funnel-step-num">${s.step}</span>`;

    const goalBadge = isFirst ? '<span class="funnel-top-badge">Base</span>'
                    : isLast  ? '<span class="funnel-last-badge">Last</span>' : '';

    // Expected % cell
    const expCell = hasExpected
      ? (isFirst
          ? `<td class="td-num td-mono"><strong>100%</strong></td>`
          : `<td class="td-num td-mono">${fmtN(s.expected_pct ?? 0)}%</td>`)
      : '';

    // Deviation cell
    let devCell = '';
    if (hasExpected) {
      if (isFirst) {
        devCell = `<td class="td-num td-mono">${blank}</td>`;
      } else {
        const dev  = s.deviation_pct ?? 0;
        const clr  = dev >= 0 ? 'var(--green)' : 'var(--red)';
        const sign = dev > 0 ? '+' : '';
        devCell = `<td class="td-num td-mono" style="color:${clr};font-weight:600">${sign}${fmtN(dev)}%</td>`;
      }
    }

    // Expected Time cell
    const expTimeCell = hasExpected
      ? `<td class="td-num" style="font-size:12px;color:var(--txt-muted)">${isFirst ? '—' : (s.expected_time || '—')}</td>`
      : '';

    // Bar cell
    const barCell = showBar ? (() => {
      const pct      = Math.round(s.count / topCnt * 1000) / 10;
      const barClass = isFirst ? 'step-1' : pct < 20 ? 'vlow' : pct < 50 ? 'low' : '';
      return `<td><div class="funnel-bar-wrap"><div class="funnel-bar-track"><div class="funnel-bar-fill ${barClass}" style="width:${pct}%"></div></div><span class="funnel-bar-pct">${fmtN(pct)}%</span></div></td>`;
    })() : '';

    return `<tr>
      <td class="td-center">${stepCell}</td>
      <td style="font-weight:${isFirst ? 700 : 500}">${esc(s.goal)}${goalBadge}</td>
      <td class="td-num td-mono" style="font-weight:600">${fmtI(s.count)}</td>
      <td class="td-num td-mono" style="font-weight:600;color:${isFirst ? C.blue : '#334155'}">${fmtN(s.funnel_pct)}%</td>
      ${expCell}${devCell}
      <td class="td-num" style="font-size:12px;color:var(--txt-muted)">${s.time_to_complete || '—'}</td>
      ${expTimeCell}${barCell}
    </tr>`;
  }).join('');

  return { noticeHtml, theadHtml, tbodyHtml, colCount };
}

function _funnelKpiHtml(summary) {
  return [
    { label:'Total Users', value: fmtI(summary.total_users   || 0), icon:'fa-users',                     iconBg:'#eff6ff', iconClr:C.blue  },
    { label:'Final Conv.', value: fmtI(summary.final_count   || 0), icon:'fa-flag-checkered',             iconBg:'#ecfdf5', iconClr:C.green },
    { label:'Conv. Rate',  value: fmtN(summary.overall_rate  || 0) + '%', icon:'fa-chart-line',           iconBg:'#eff6ff', iconClr:C.blue  },
    { label:'Drop-off',    value: fmtI(summary.total_dropoff || 0), icon:'fa-person-walking-arrow-right', iconBg:'#fef2f2', iconClr:C.red   },
  ].map(c => `<div class="kpi-card" style="--kpi-color:${c.iconClr};padding:14px">
    <div class="kpi-top"><div class="kpi-icon" style="background:${c.iconBg};color:${c.iconClr};width:28px;height:28px;font-size:11px"><i class="fas ${c.icon}"></i></div></div>
    <div class="kpi-label">${c.label}</div><div class="kpi-value" style="font-size:18px">${c.value}</div>
  </div>`).join('');
}

// ── Offer Profile funnel ──────────────────────────────────────────

function _opRenderFunnel(steps, summary, hasExpected = false) {
  const sub = document.getElementById('op-funnel-subtitle');
  if (sub) sub.textContent = 'Offer-level · all publishers combined';

  const kpiEl = document.getElementById('op-funnel-kpis');
  if (kpiEl) kpiEl.innerHTML = _funnelKpiHtml(summary);

  const tbody   = document.getElementById('op-funnel-body');
  const theadEl = document.querySelector('#op-funnel-table thead');
  if (!tbody) return;

  const { noticeHtml, theadHtml, tbodyHtml } = _funnelHtml(steps, hasExpected);

  // Inject notice above the table
  const notice = document.getElementById('op-funnel-notice');
  if (notice) notice.innerHTML = noticeHtml;

  if (theadEl) theadEl.innerHTML = theadHtml;
  tbody.innerHTML = tbodyHtml;
}

function _opRenderConcentration(publishers, totalRev) {
  const body = document.getElementById('op-conc-body');
  if (!publishers.length || totalRev === 0) {
    body.innerHTML = '<p class="pp-action-empty">No publisher data.</p>';
    return;
  }
  const top  = publishers.slice(0, 5);
  const bars = top.map(r => {
    const pct       = totalRev > 0 ? Math.round(r.revenue / totalRev * 100) : 0;
    const fillColor = pct >= 50 ? 'var(--red)' : pct >= 30 ? 'var(--amber)' : 'var(--primary)';
    return `<div class="pp-conc-item">
      <div class="pp-conc-name" title="${esc(_partnerLabel(r.partner))}">${esc(_partnerLabel(r.partner))}</div>
      <div class="pp-conc-track"><div class="pp-conc-fill" style="width:${pct}%;background:${fillColor}"></div></div>
      <div class="pp-conc-pct">${pct}%</div>
    </div>`;
  }).join('');
  const topPct = totalRev > 0 ? Math.round(top[0].revenue / totalRev * 100) : 0;
  const warn   = topPct >= 50
    ? `<div class="pp-conc-warn"><i class="fas fa-triangle-exclamation"></i> ${esc(_partnerLabel(top[0].partner))} = ${topPct}% of offer revenue — high dependency risk</div>`
    : '';
  body.innerHTML = bars + warn;
}

function _opRenderRankingActivity(ranking, activity) {
  const rankBody = document.getElementById('op-rank-body');
  const actBody  = document.getElementById('op-act-body');

  const rankRows = [
    { label: 'Revenue Rank', rank: ranking.revenue_rank, total: ranking.total },
    { label: 'Profit Rank',  rank: ranking.profit_rank,  total: ranking.total },
    { label: 'Margin Rank',  rank: ranking.margin_rank,  total: ranking.total },
  ];
  rankBody.innerHTML = rankRows.map(r => `
    <div class="pp-rank-row">
      <span class="pp-rank-label">${r.label}</span>
      <div style="text-align:right">
        <div class="pp-rank-num">#${r.rank ?? '—'}</div>
        <div class="pp-rank-of">of ${r.total ?? '—'} offers</div>
      </div>
    </div>`).join('');

  actBody.innerHTML = [
    { label: 'First Seen',    val: activity.first_seen    || '—' },
    { label: 'Last Activity', val: activity.last_activity || '—' },
  ].map(r => `
    <div class="pp-act-row">
      <span class="pp-act-label">${r.label}</span>
      <span class="pp-act-val">${r.val}</span>
    </div>`).join('');
}

// ══════════════════════════════════════════════════════════════════
//  PUBLISHER + OFFER DETAIL (publisher-centric drill-down)
//  Entered from: Publisher Profile → click an offer row
//  Context: single publisher × single offer combination only
// ══════════════════════════════════════════════════════════════════

let _poPartner    = null;   // expose globally so HTML onclick can read it
let _poOffer      = null;
let _poTrendData  = [];
let _poTrendMetric = 'revenue';

// Expose to window so inline HTML onclick can access _poPartner
Object.defineProperty(window, '_poPartner', {
  get: () => _poPartner,
  set: (v) => { _poPartner = v; },
});

let _poContext = 'publisher';  // 'publisher' | 'offer'

function openPubOfferDetail(partner, offer, context = 'publisher') {
  _poPartner = partner;
  _poOffer   = offer;
  _poContext = context;
  state.page = 'pub-offer';

  // Sidebar: highlight the context root
  const sidebarPage = context === 'offer' ? 'offers' : 'publishers';
  document.querySelectorAll('.sb-item').forEach(el =>
    el.classList.toggle('active', el.dataset.page === sidebarPage));
  document.querySelectorAll('.page').forEach(el =>
    el.classList.toggle('active', el.id === 'page-pub-offer'));
  document.getElementById('tb-page-name').textContent =
    context === 'offer' ? 'Offer · Publisher Detail' : 'Publisher · Offer Detail';
  history.replaceState(null, '', '#pub-offer');

  // Build breadcrumb dynamically based on context
  const nav = document.getElementById('po-breadcrumb-nav');
  if (nav) {
    if (context === 'offer') {
      // Offers → Offer Name → Publisher Name
      nav.innerHTML = `
        <button class="po-crumb-btn" onclick="navigateTo('offers')">
          <i class="fas fa-arrow-left"></i> Offers
        </button>
        <i class="fas fa-chevron-right po-crumb-sep"></i>
        <button class="po-crumb-btn" onclick="if(window._poOffer)openOfferProfile(window._poOffer)"
          >${esc(offer)}</button>
        <i class="fas fa-chevron-right po-crumb-sep"></i>
        <span class="po-crumb-current">${esc(_partnerLabel(partner))}</span>`;
    } else {
      // Publishers → Publisher Name → Offer Name
      nav.innerHTML = `
        <button class="po-crumb-btn" onclick="navigateTo('publishers')">
          <i class="fas fa-arrow-left"></i> Publishers
        </button>
        <i class="fas fa-chevron-right po-crumb-sep"></i>
        <button class="po-crumb-btn" onclick="if(window._poPartner)openPublisherProfile(window._poPartner)"
          >${esc(_partnerLabel(partner))}</button>
        <i class="fas fa-chevron-right po-crumb-sep"></i>
        <span class="po-crumb-current">${esc(offer)}</span>`;
    }
  }

  // Reset trend
  _poTrendMetric = 'revenue';
  document.querySelectorAll('#po-metric-btns .trend-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.m === 'revenue'));

  loading(true);
  loadPubOfferDetail().finally(() => loading(false));
}

// Expose _poOffer to window for breadcrumb onclick
Object.defineProperty(window, '_poOffer', {
  get: () => _poOffer, set: (v) => { _poOffer = v; },
});

async function loadPubOfferDetail() {
  if (!_poPartner || !_poOffer) { navigateTo('publishers'); return; }

  const data = await api('/api/publishers/offer-detail?' + qs({ partner: _poPartner, offer: _poOffer }));
  const { stats = {}, trend = [], activity = {} } = data;

  // Title and subtitle flip based on context
  if (_poContext === 'offer') {
    document.getElementById('po-title').textContent = _partnerLabel(_poPartner);
    document.getElementById('po-sub').textContent   = _poOffer + ' · Publisher Detail';
  } else {
    document.getElementById('po-title').textContent = _poOffer;
    document.getElementById('po-sub').textContent   = _partnerLabel(_poPartner) + ' · Offer Detail';
  }
  document.getElementById('po-status').innerHTML = statusBadge(stats.margin_pct || 0);

  _poRenderKPIs(stats);
  _poTrendData = trend;
  renderPOTrend();
  _poRenderFunnel(data.funnel || [], data.funnel_summary || {}, data.has_expected || false);
  _poRenderStatus(stats);
  _poRenderActivity(activity, stats);
}

function _poRenderKPIs(s) {
  const mpClr = marginColor(s.margin_pct || 0);
  const pfClr = (s.profit || 0) >= 0 ? C.green : C.red;
  const cards = [
    { label: 'Revenue',  value: fmtCur(s.revenue),    icon: 'fa-dollar-sign', iconBg: '#eff6ff', iconClr: C.blue  },
    { label: 'Cost',     value: fmtCur(s.cost),       icon: 'fa-money-bill-wave',   iconBg: '#fef2f2', iconClr: C.red   },
    { label: 'Profit',   value: fmtCur(s.profit),     icon: 'fa-arrow-trend-up',    iconBg: '#ecfdf5', iconClr: pfClr   },
    { label: 'Margin %', value: fmtPct(s.margin_pct), icon: 'fa-percent',           iconBg: '#fffbeb', iconClr: '#d97706',
      valStyle: `color:${mpClr};font-weight:800` },
    { label: 'Conversions', value: fmtI(s.installs || 0), icon: 'fa-mobile-screen',    iconBg: '#f0fdf4', iconClr: C.green },
  ];
  document.getElementById('po-kpis').innerHTML = cards.map(c => `
    <div class="kpi-card" style="--kpi-color:${c.iconClr};padding:16px">
      <div class="kpi-top">
        <div class="kpi-icon" style="background:${c.iconBg};color:${c.iconClr};width:30px;height:30px;font-size:12px">
          <i class="fas ${c.icon}"></i>
        </div>
      </div>
      <div class="kpi-label">${c.label}</div>
      <div class="kpi-value" style="font-size:19px;${c.valStyle || ''}">${c.value}</div>
    </div>`).join('');
}

function setPOMetric(btn, metric) {
  _poTrendMetric = metric;
  document.querySelectorAll('#po-metric-btns .trend-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.m === metric));
  renderPOTrend();
}

function renderPOTrend() {
  if (!_poTrendData.length) { noChart('chart-po-trend', 'No trend data for selected range'); return; }
  const m   = _poTrendMetric;
  const cfg = {
    revenue:    { label: 'Revenue',  color: C.blue,  prefix: '$', suffix: '' },
    profit:     { label: 'Profit',   color: C.green, prefix: '$', suffix: '' },
    margin_pct: { label: 'Margin %', color: C.teal,  prefix: '',  suffix: '%' },
    installs:   { label: 'Conversions', color: C.sky,   prefix: '',  suffix: ''  },
  }[m] || { label: m, color: C.blue, prefix: '', suffix: '' };

  const fill = cfg.color.startsWith('#')
    ? cfg.color + '14'
    : cfg.color.replace(')', ',0.08)').replace('rgb', 'rgba');

  Plotly.react('chart-po-trend', [{
    x: _poTrendData.map(r => r.date),
    y: _poTrendData.map(r => r[m] ?? 0),
    type: 'scatter', mode: 'lines+markers', name: cfg.label,
    line: { color: cfg.color, width: 2.5 }, marker: { color: cfg.color, size: 5 },
    fill: 'tozeroy', fillcolor: fill,
    hovertemplate: `%{x}<br>${cfg.label}: ${cfg.prefix}%{y:,.1f}${cfg.suffix}<extra></extra>`,
  }], {
    ...PC,
    xaxis: { ...PC.xaxis, tickformat: '%b %d', nticks: 10 },
    yaxis: { ...PC.yaxis, tickprefix: cfg.prefix, ticksuffix: cfg.suffix, rangemode: 'tozero' },
    showlegend: false,
    margin: { l: 52, r: 12, t: 10, b: 40 },
  }, PC);
}

// Factual-only status card — no prescriptive business suggestions
function _poRenderStatus(s) {
  const mp     = s.margin_pct || 0;
  const status = marginStatus(mp);
  const cfg = {
    Scale:   { icon: 'fa-circle-check',  color: C.green,
      lines: [
        `Margin is ${fmtN(mp)}% — above the 30% scale threshold.`,
        `Revenue: ${fmtCur(s.revenue)} · Cost: ${fmtCur(s.cost)} · Profit: ${fmtCur(s.profit)}.`,
        'This publisher + offer combination is profitable.',
      ]},
    Monitor: { icon: 'fa-eye',           color: C.blue,
      lines: [
        `Margin is ${fmtN(mp)}% — within the monitor range (15–30%).`,
        `Revenue: ${fmtCur(s.revenue)} · Cost: ${fmtCur(s.cost)} · Profit: ${fmtCur(s.profit)}.`,
        'Performance is positive but below the scale threshold.',
      ]},
    Optimize:{ icon: 'fa-chart-bar',    color: C.amber,
      lines: [
        `Margin is ${fmtN(mp)}% — above breakeven but below 15%.`,
        `Revenue: ${fmtCur(s.revenue)} · Cost: ${fmtCur(s.cost)} · Profit: ${fmtCur(s.profit)}.`,
        'Revenue exceeds cost but margin is narrow.',
      ]},
    Pause:   { icon: 'fa-circle-xmark', color: C.red,
      lines: [
        `Margin is ${fmtN(mp)}% — cost exceeds revenue for this combination.`,
        `Revenue: ${fmtCur(s.revenue)} · Cost: ${fmtCur(s.cost)} · Loss: ${fmtCur(Math.abs(s.profit || 0))}.`,
        'This publisher + offer combination is currently unprofitable.',
      ]},
  }[status] || { icon: 'fa-circle-info', color: 'var(--txt-muted)',
    lines: [`Margin is ${fmtN(mp)}%.`] };

  document.getElementById('po-rec-body').innerHTML = `
    <div style="border-left:4px solid ${cfg.color};padding:14px 14px 14px 18px;
                border-radius:0 var(--r) var(--r) 0">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
        <i class="fas ${cfg.icon}" style="color:${cfg.color}"></i>
        <span style="font-weight:700;font-size:14px;color:var(--txt-head)">${status}</span>
        ${statusBadge(mp)}
      </div>
      <ul style="margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px">
        ${cfg.lines.map(l => `<li style="font-size:13px;color:var(--txt-muted)">${l}</li>`).join('')}
      </ul>
    </div>`;
}

function _poRenderFunnel(steps, summary, hasExpected = false) {
  const subtitle = document.getElementById('po-funnel-subtitle');
  if (subtitle && _poPartner && _poOffer) {
    subtitle.textContent = `${_partnerLabel(_poPartner)} · ${_poOffer} only`;
  }

  const kpisEl   = document.getElementById('po-funnel-kpis');
  const bodyEl   = document.getElementById('po-funnel-body');
  const theadEl  = document.querySelector('#po-funnel-table thead');
  const noticeEl = document.getElementById('po-funnel-notice');
  if (!bodyEl) return;

  if (!steps.length) {
    if (kpisEl) kpisEl.innerHTML = '';
    bodyEl.innerHTML = `<tr><td colspan="${hasExpected ? 8 : 5}" class="td-empty">
      <div class="empty-state"><i class="fas fa-inbox empty-icon"></i>
        <p>No funnel data for this publisher+offer in the selected range.</p>
      </div></td></tr>`;
    return;
  }

  if (kpisEl) kpisEl.innerHTML = _funnelKpiHtml(summary);

  const { noticeHtml, theadHtml, tbodyHtml } = _funnelHtml(steps, hasExpected);
  if (noticeEl) noticeEl.innerHTML = noticeHtml;
  if (theadEl)  theadEl.innerHTML  = theadHtml;
  bodyEl.innerHTML = tbodyHtml;
}

function _poRenderActivity(activity, stats) {
  const rows = [
    { label: 'First Seen',        val: activity.first_seen    || '—' },
    { label: 'Last Activity',     val: activity.last_activity || '—' },
    { label: 'Active Days',       val: fmtI(activity.active_days || 0) + ' days' },
    { label: 'Total Conversions',    val: fmtI(stats.installs    || 0) },
    { label: 'Total Conversions', val: fmtI(stats.conversions || 0) },
  ];
  document.getElementById('po-act-body').innerHTML = rows.map(r => `
    <div class="pp-act-row">
      <span class="pp-act-label">${r.label}</span>
      <span class="pp-act-val">${r.val}</span>
    </div>`).join('');
}

// ══════════════════════════════════════════════════════════════════
//  PUBLISHER PROFILE (360°)
// ══════════════════════════════════════════════════════════════════

let _ppPartner     = null;   // current publisher partner name
let _ppTrendData   = [];     // cached trend rows
let _ppTrendMetric = 'revenue';

// Offer Performance table state
let _ppOfferData   = [];                           // full unfiltered list from API
let _ppOfferSort   = { col: 'profit', dir: -1 };  // Profit DESC by default
let _ppOfferPage   = 0;
const _PP_PAGE_SIZE = 50;

// Navigate to the publisher profile page (bypasses normal navigateTo)
function openPublisherProfile(partner) {
  _ppPartner = partner;
  state.page = 'publisher-detail';

  // Keep 'publishers' sidebar item highlighted (context)
  document.querySelectorAll('.sb-item').forEach(el =>
    el.classList.toggle('active', el.dataset.page === 'publishers'));
  document.querySelectorAll('.page').forEach(el =>
    el.classList.toggle('active', el.id === 'page-publisher-detail'));
  document.getElementById('tb-page-name').textContent = 'Publisher Profile';
  history.replaceState(null, '', '#publisher-detail');

  // Reset trend metric and offer filter/sort state
  _ppTrendMetric = 'revenue';
  _ppOfferData   = [];
  _ppOfferPage   = 0;
  _ppOfferSort   = { col: 'profit', dir: -1 };
  document.querySelectorAll('#pp-metric-btns .trend-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.m === 'revenue'));

  loading(true);
  loadPublisherProfile().finally(() => loading(false));
}

async function loadPublisherProfile() {
  if (!_ppPartner) { navigateTo('publishers'); return; }

  console.log('[PP] loadPublisherProfile start, partner=', _ppPartner);
  let data;
  try {
    data = await api('/api/publishers/profile?' + qs({ partner: _ppPartner }));
    console.log('[PP] API response: stats.revenue=', data?.stats?.revenue,
      'trend rows=', data?.trend?.length, 'offers=', data?.offers?.length);
  } catch(e) {
    console.error('[PP] API fetch failed:', e);
    return;
  }

  const { stats = {}, offers = [], trend = [], ranking = {}, activity = {} } = data;

  // Header
  document.getElementById('pp-name').textContent = _partnerLabel(_ppPartner);
  document.getElementById('pp-sub').textContent  = `Publisher · ${_ppPartner}`;
  document.getElementById('pp-status').innerHTML  = statusBadge(stats.margin_pct || 0);

  try { _ppRenderKPIs(stats); } catch(e) { console.error('[PP] _ppRenderKPIs:', e); }
  try { _ppRenderActionQueue(offers); } catch(e) { console.error('[PP] _ppRenderActionQueue:', e); }

  _ppTrendData = trend;
  console.log('[PP] trend data set, rows=', trend.length, 'first=', trend[0]);
  try { renderPPTrend(); } catch(e) { console.error('[PP] renderPPTrend:', e); noChart('chart-pp-trend', 'Chart error'); }

  try { _ppRenderOffers(offers); } catch(e) { console.error('[PP] _ppRenderOffers:', e); }
  try { _ppRenderConcentration(offers, stats.revenue || 0); } catch(e) { console.error('[PP] _ppRenderConcentration:', e); }
  try { _ppRenderRankingActivity(ranking, activity); } catch(e) { console.error('[PP] _ppRenderRankingActivity:', e); }
  console.log('[PP] loadPublisherProfile done');
}

function setPPMetric(btn, metric) {
  _ppTrendMetric = metric;
  document.querySelectorAll('#pp-metric-btns .trend-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.m === metric));
  renderPPTrend();
}

function renderPPTrend() {
  const data = _ppTrendData;
  console.log('[PP] renderPPTrend: rows=', data?.length, 'metric=', _ppTrendMetric);
  if (!data || !data.length) { noChart('chart-pp-trend', 'No trend data for selected range'); return; }

  const m = _ppTrendMetric;
  const metricCfg = {
    revenue:    { label: 'Revenue',   color: C.blue,  prefix: '$', suffix: '' },
    profit:     { label: 'Profit',    color: C.green, prefix: '$', suffix: '' },
    margin_pct: { label: 'Margin %',  color: C.teal,  prefix: '',  suffix: '%' },
    installs:   { label: 'Conversions',  color: C.sky,   prefix: '',  suffix: ''  },
  };
  const cfg = metricCfg[m] || metricCfg.revenue;

  const fillcolor = cfg.color.startsWith('#')
    ? cfg.color + '14'
    : cfg.color.replace(')', ',0.08)').replace('rgb', 'rgba');

  const trace = {
    x: data.map(r => r.date),
    y: data.map(r => r[m] ?? 0),
    type: 'scatter', mode: 'lines+markers',
    name: cfg.label,
    line: { color: cfg.color, width: 2.5 },
    marker: { color: cfg.color, size: 5 },
    fill: 'tozeroy', fillcolor,
    hovertemplate: `%{x}<br>${cfg.label}: ${cfg.prefix}%{y:,.1f}${cfg.suffix}<extra></extra>`,
  };

  const layout = {
    ...L,
    xaxis: { ...L.xaxis, tickformat: '%b %d', nticks: 10 },
    yaxis: { ...L.yaxis,
      tickprefix: cfg.prefix,
      ticksuffix: cfg.suffix,
      rangemode: 'tozero',
    },
    showlegend: false,
    margin: { l: 52, r: 12, t: 10, b: 40 },
  };

  console.log('[PP] Plotly.react chart-pp-trend, y sample=', trace.y.slice(0,3));
  Plotly.react('chart-pp-trend', [trace], layout, PC);
}

// Relative date: "Today", "1d ago", "12d ago", "3mo ago"
function _relDays(dateStr) {
  if (!dateStr) return '—';
  const d    = new Date(dateStr + 'T00:00:00');
  const days = Math.floor((Date.now() - d.getTime()) / 86400000);
  if (days < 0)  return 'Today';
  if (days === 0) return 'Today';
  if (days === 1) return '1d ago';
  if (days < 31)  return `${days}d ago`;
  const m = Math.floor(days / 30);
  return `${m}mo ago`;
}

// Trend icon: ↑ / → / ↓
function _ppTrendIcon(trend) {
  if (trend === 'up')   return '<span class="pp-trend-up"   title="Growing">↑</span>';
  if (trend === 'down') return '<span class="pp-trend-down" title="Declining">↓</span>';
  return '<span class="pp-trend-stable" title="Stable">→</span>';
}

// Action Queue: top offers per status group
function _ppRenderActionQueue(offers) {
  const body = document.getElementById('pp-aq-body');
  if (!body) return;
  if (!offers.length) {
    body.innerHTML = '<p class="pp-aq-none" style="padding:12px 16px">No offers in range.</p>';
    return;
  }

  const groups = [
    { key: 'Scale',   color: C.green, sort: (a,b) => b.margin_pct - a.margin_pct },
    { key: 'Monitor', color: C.blue,  sort: (a,b) => b.margin_pct - a.margin_pct },
    { key: 'Optimize',color: C.amber, sort: (a,b) => a.margin_pct - b.margin_pct },
    { key: 'Pause',   color: C.red,   sort: (a,b) => a.margin_pct - b.margin_pct },
  ];

  body.innerHTML = `<div class="pp-aq-grid">` +
    groups.map(g => {
      const items = offers
        .filter(r => marginStatus(r.margin_pct) === g.key)
        .sort(g.sort)
        .slice(0, 5);
      const rows = items.length
        ? items.map(r => `
          <div class="pp-aq-item" data-offer="${esc(r.offerName)}" data-partner="${esc(_ppPartner)}"
               onclick="openPubOfferDetail(this.dataset.partner,this.dataset.offer)">
            <span class="pp-aq-name" title="${esc(r.offerName)}">${esc(_fmtOfferName(r.offerName))}</span>
            <span class="pp-aq-pct" style="color:${g.color}">${fmtN(r.margin_pct)}%</span>
          </div>`).join('')
        : `<div class="pp-aq-none">None</div>`;
      return `<div class="pp-aq-col">
        <div class="pp-aq-hdr">${recBadge(g.key)}</div>
        ${rows}
      </div>`;
    }).join('') + `</div>`;
}

function _ppRenderKPIs(s) {
  const mpClr  = marginColor(s.margin_pct || 0);
  const pfClr  = (s.profit || 0) >= 0 ? C.green : C.red;
  const cards  = [
    { label: 'Revenue',        value: fmtCur(s.revenue),           icon: 'fa-dollar-sign', iconBg: '#eff6ff', iconClr: C.blue  },
    { label: 'Profit',         value: fmtCur(s.profit),            icon: 'fa-arrow-trend-up',    iconBg: '#ecfdf5', iconClr: pfClr   },
    { label: 'Margin %',       value: fmtPct(s.margin_pct),        icon: 'fa-percent',           iconBg: '#fffbeb', iconClr: '#d97706', valStyle: `color:${mpClr};font-weight:800` },
    { label: 'Conversions',       value: fmtI(s.installs || 0),       icon: 'fa-mobile-screen',     iconBg: '#f0fdf4', iconClr: C.green },
    { label: 'Active Offers',  value: fmtI(s.active_offers || 0),  icon: 'fa-tag',               iconBg: '#f0f9ff', iconClr: C.sky   },
    { label: 'Revenue Share',  value: fmtN(s.revenue_share || 0) + '%', icon: 'fa-chart-pie',   iconBg: '#faf5ff', iconClr: '#7c3aed' },
  ];
  document.getElementById('pp-kpis').innerHTML = cards.map(c => `
    <div class="kpi-card" style="--kpi-color:${c.iconClr};padding:16px">
      <div class="kpi-top">
        <div class="kpi-icon" style="background:${c.iconBg};color:${c.iconClr};width:30px;height:30px;font-size:12px">
          <i class="fas ${c.icon}"></i>
        </div>
      </div>
      <div class="kpi-label">${c.label}</div>
      <div class="kpi-value" style="font-size:19px;${c.valStyle || ''}">${c.value}</div>
    </div>`).join('');
}

// Store data + trigger initial render (Profit DESC)
function _ppRenderOffers(offers) {
  _ppOfferData = offers;
  _ppOfferPage = 0;
  _ppOfferSort = { col: 'profit', dir: -1 };
  // Reset filter inputs if they exist
  ['pp-offer-search','pp-offer-status','pp-offer-active','pp-margin-min','pp-margin-max',
   'pp-install-min','pp-install-max'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  _ppApplyAndRender();
}

// Called by any filter control change
function ppOfferFilter() {
  _ppOfferPage = 0;
  _ppApplyAndRender();
}

// Toggle/set sort column
function ppSortBy(col) {
  _ppOfferSort = {
    col,
    dir: _ppOfferSort.col === col ? _ppOfferSort.dir * -1 : -1,
  };
  _ppApplyAndRender();
}

// Reset all filters to default
function ppOfferReset() {
  ['pp-offer-search','pp-offer-status','pp-offer-active','pp-margin-min','pp-margin-max',
   'pp-install-min','pp-install-max'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  _ppOfferPage = 0;
  _ppApplyAndRender();
}

// Page navigation
function ppOfferPage(delta) {
  _ppOfferPage += delta;
  _ppApplyAndRender();
  document.getElementById('pp-offers-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Core: filter → sort → paginate → render
function _ppApplyAndRender() {
  const q          = (document.getElementById('pp-offer-search')?.value || '').toLowerCase().trim();
  const statusF    = document.getElementById('pp-offer-status')?.value  || '';
  const activeF    = document.getElementById('pp-offer-active')?.value  || '';
  const marginMin  = document.getElementById('pp-margin-min')?.value  !== '' ? parseFloat(document.getElementById('pp-margin-min').value)  : null;
  const marginMax  = document.getElementById('pp-margin-max')?.value  !== '' ? parseFloat(document.getElementById('pp-margin-max').value)  : null;
  const installMin = document.getElementById('pp-install-min')?.value !== '' ? parseFloat(document.getElementById('pp-install-min').value) : null;
  const installMax = document.getElementById('pp-install-max')?.value !== '' ? parseFloat(document.getElementById('pp-install-max').value) : null;

  // Filter
  let filtered = _ppOfferData.filter(r => {
    if (q && !r.offerName.toLowerCase().includes(q))         return false;
    if (statusF && marginStatus(r.margin_pct) !== statusF)   return false;
    if (activeF === 'active'  &&  !r.is_active)              return false;
    if (activeF === 'paused'  &&   r.is_active)              return false;
    if (marginMin  !== null && r.margin_pct < marginMin)     return false;
    if (marginMax  !== null && r.margin_pct > marginMax)     return false;
    if (installMin !== null && r.installs   < installMin)    return false;
    if (installMax !== null && r.installs   > installMax)    return false;
    return true;
  });

  // Sort — last_activity sorts lexicographically (ISO dates)
  const { col, dir } = _ppOfferSort;
  filtered.sort((a, b) => {
    const av = a[col]; const bv = b[col];
    if (typeof av === 'string') return dir * (av || '').localeCompare(bv || '');
    return dir * ((av ?? 0) - (bv ?? 0));
  });

  // Update sort icon indicators
  ['offerName','revenue','profit','margin_pct','installs','last_activity'].forEach(c => {
    const icon = document.getElementById(`ppi-${c}`);
    if (!icon) return;
    if (c === col) {
      icon.textContent = dir === -1 ? '↓' : '↑';
      icon.className   = 'pp-sort-icon pp-sort-active';
    } else {
      icon.textContent = '⇅';
      icon.className   = 'pp-sort-icon';
    }
  });

  // Paginate
  const total = filtered.length;
  const pages = Math.max(1, Math.ceil(total / _PP_PAGE_SIZE));
  if (_ppOfferPage >= pages) _ppOfferPage = pages - 1;
  const start = _ppOfferPage * _PP_PAGE_SIZE;
  const page  = filtered.slice(start, start + _PP_PAGE_SIZE);

  // Badge: "filtered / total" when active filter, else just total
  const badge = document.getElementById('pp-offers-badge');
  if (badge) {
    badge.textContent = total < _ppOfferData.length
      ? `${total} / ${_ppOfferData.length}` : total;
  }

  // Render rows — 8 cols: Offer | Revenue | Profit | Margin% | Conversions | Trend | Last Active | Status
  const tbody = document.getElementById('pp-offers-body');
  if (!tbody) return;
  if (!page.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="td-empty">
      <div class="empty-state"><i class="fas fa-inbox empty-icon"></i>
        <p>${_ppOfferData.length ? 'No offers match the current filters.' : 'No offer data for selected range.'}</p>
      </div></td></tr>`;
  } else {
    tbody.innerHTML = page.map(r => {
      const mc = marginColor(r.margin_pct);
      return `<tr style="cursor:pointer" data-offer="${esc(r.offerName)}" data-partner="${esc(_ppPartner)}"
                  onclick="openPubOfferDetail(this.dataset.partner, this.dataset.offer)">
        <td class="td-trunc" title="${esc(r.offerName)}" style="font-weight:600;max-width:200px">${esc(_fmtOfferName(r.offerName))}</td>
        <td class="td-num rev">$${fmtN(r.revenue)}</td>
        <td class="td-num" style="color:${r.profit>=0?C.green:C.red};font-weight:600">$${fmtN(r.profit)}</td>
        <td class="td-num" style="font-weight:700;color:${mc}">${fmtN(r.margin_pct)}%</td>
        <td class="td-num">${fmtI(r.installs)}</td>
        <td class="td-center">${_ppTrendIcon(r.trend)}</td>
        <td class="td-num" style="font-size:12px;color:var(--txt-muted)">${_relDays(r.last_activity)}</td>
        <td class="td-center">${statusBadge(r.margin_pct)}</td>
      </tr>`;
    }).join('');
  }

  // Pagination controls
  const pagEl = document.getElementById('pp-pagination');
  if (!pagEl) return;
  if (total <= _PP_PAGE_SIZE) {
    pagEl.innerHTML = total
      ? `<span>Showing all ${total} offer${total !== 1 ? 's' : ''}</span>`
      : '';
    return;
  }
  const end = Math.min(start + _PP_PAGE_SIZE, total);
  pagEl.innerHTML = `
    <span class="pp-pag-info">Showing ${start + 1}–${end} of ${total} offers</span>
    <div class="pp-pag-btns">
      <button class="pp-pag-btn" onclick="ppOfferPage(-1)" ${_ppOfferPage === 0 ? 'disabled' : ''}>
        <i class="fas fa-chevron-left"></i> Prev
      </button>
      <span class="pp-pag-pages">${_ppOfferPage + 1} / ${pages}</span>
      <button class="pp-pag-btn" onclick="ppOfferPage(1)" ${_ppOfferPage >= pages - 1 ? 'disabled' : ''}>
        Next <i class="fas fa-chevron-right"></i>
      </button>
    </div>`;
}

function _ppRenderConcentration(offers, totalRev) {
  const body = document.getElementById('pp-conc-body');
  if (!offers.length || totalRev === 0) {
    body.innerHTML = '<p class="pp-action-empty">No offer data.</p>';
    return;
  }
  // Top 5 by revenue share
  const top = offers.slice(0, 5);
  const bars = top.map(r => {
    const pct = totalRev > 0 ? Math.round(r.revenue / totalRev * 100) : 0;
    // Colour: heavy concentration = warning
    const fillColor = pct >= 50 ? 'var(--red)' : pct >= 30 ? 'var(--amber)' : 'var(--primary)';
    return `<div class="pp-conc-item">
      <div class="pp-conc-name" title="${esc(r.offerName)}">${esc(_fmtOfferName(r.offerName))}</div>
      <div class="pp-conc-track"><div class="pp-conc-fill" style="width:${pct}%;background:${fillColor}"></div></div>
      <div class="pp-conc-pct">${pct}%</div>
    </div>`;
  }).join('');

  const topPct = totalRev > 0 ? Math.round(top[0].revenue / totalRev * 100) : 0;
  const warn   = topPct >= 50
    ? `<div class="pp-conc-warn"><i class="fas fa-triangle-exclamation"></i> ${esc(_fmtOfferName(top[0].offerName))} = ${topPct}% of revenue — high dependency risk</div>`
    : '';

  body.innerHTML = bars + warn;
}

function _ppRenderRankingActivity(ranking, activity) {
  const rankBody = document.getElementById('pp-rank-body');
  const actBody  = document.getElementById('pp-act-body');

  const rankRows = [
    { label: 'Revenue Rank', rank: ranking.revenue_rank },
    { label: 'Profit Rank',  rank: ranking.profit_rank  },
    { label: 'Margin Rank',  rank: ranking.margin_rank  },
  ];
  rankBody.innerHTML = rankRows.map(r => `
    <div class="pp-rank-row">
      <span class="pp-rank-label">${r.label}</span>
      <div style="text-align:right">
        <div class="pp-rank-num">#${r.rank ?? '—'}</div>
        <div class="pp-rank-of">of ${ranking.total ?? '?'} publishers</div>
      </div>
    </div>`).join('');

  actBody.innerHTML = [
    { label: 'First Seen',     val: activity.first_seen    || '—' },
    { label: 'Last Activity',  val: activity.last_activity || '—' },
    { label: 'Active Offers',  val: fmtI(document.getElementById('pp-offers-badge')?.textContent || 0) },
  ].map(r => `
    <div class="pp-act-row">
      <span class="pp-act-label">${r.label}</span>
      <span class="pp-act-val">${r.val}</span>
    </div>`).join('');
}

// Health Check — campaign filter state
// ══════════════════════════════════════════════════════════════════
//  HEALTH CHECK — Operations Control Center
// ══════════════════════════════════════════════════════════════════

// ── Criteria definitions for ⓘ info popups ────────────────────────────────────
const _HC_INFO = {
  priorities: {
    title: "Action Queue",
    rows: [
      { label: 'Critical', desc: 'Negative margin or < 5%' },
      { label: 'Warning',  desc: 'Margin 5–15%, or revenue drop > 40%' },
      { label: 'Oppty',    desc: 'Margin > 30%, ready to scale' },
    ],
  },
  risk: {
    title: 'Revenue At Risk',
    rows: [
      { label: 'Critical', desc: 'Negative profit or margin < 5%' },
      { label: 'Warning',  desc: 'Margin 5–15%, or revenue drop > 40%' },
      { label: 'Min rev',  desc: '$100 revenue required' },
    ],
  },
  scale: {
    title: 'Scale Opportunities',
    rows: [
      { label: 'Qualifies', desc: 'Margin > 30%, revenue ≥ $500' },
      { label: 'High',      desc: 'Margin > 50%, revenue ≥ $3,000' },
      { label: 'Excludes',  desc: 'Campaigns already in Revenue At Risk' },
    ],
  },
  pub_health: {
    title: 'Publisher Health',
    rows: [
      { label: 'Healthy',   desc: 'Margin ≥ 20%' },
      { label: 'Watchlist', desc: 'Margin 0–20%' },
      { label: 'At Risk',   desc: 'Negative margin' },
    ],
  },
  off_health: {
    title: 'Offer Health',
    rows: [
      { label: 'Healthy',   desc: 'Margin ≥ 20%' },
      { label: 'Watchlist', desc: 'Margin 0–20%' },
      { label: 'At Risk',   desc: 'Negative margin' },
    ],
  },
  funnel: {
    title: 'Funnel Issues',
    rows: [
      { label: 'Severe',   desc: 'Conv. rate dropped > 60%' },
      { label: 'Moderate', desc: 'Conv. rate dropped 40–60%' },
      { label: 'Minor',    desc: 'Conv. rate dropped 30–40%' },
    ],
  },
  anomaly: {
    title: 'Anomaly Detection',
    rows: [
      { label: 'Margin Collapse', desc: 'Margin < 5%' },
      { label: 'Revenue Drop',    desc: '> 40% drop day-over-day' },
      { label: 'Conversion Drop',    desc: '> 40% drop day-over-day' },
      { label: 'Revenue Spike',   desc: '> 50% increase day-over-day' },
    ],
  },
};

// ── ⓘ Info popup ──────────────────────────────────────────────────────────────
function showHcInfo(key, event) {
  event.stopPropagation();
  const existing = document.getElementById('hc-info-popup');
  if (existing) { existing.remove(); return; }

  const info = _HC_INFO[key];
  if (!info) return;

  const popup = document.createElement('div');
  popup.id        = 'hc-info-popup';
  popup.className = 'hc-info-popup';
  popup.innerHTML =
    `<div class="hc-info-title">${esc(info.title)}</div>` +
    info.rows.map(r =>
      `<div class="hc-info-row">
        <span class="hc-info-label">${esc(r.label)}</span>
        <span class="hc-info-desc">${esc(r.desc)}</span>
      </div>`
    ).join('');

  document.body.appendChild(popup);

  // Position below the icon, clamped to viewport
  const rect = event.currentTarget.getBoundingClientRect();
  const scrollY = window.scrollY || document.documentElement.scrollTop;
  const left = Math.min(rect.left, window.innerWidth - 300);
  popup.style.cssText = `position:absolute;top:${rect.bottom + scrollY + 6}px;left:${Math.max(8, left)}px;z-index:9999`;

  const dismiss = (e) => {
    if (!popup.contains(e.target)) { popup.remove(); document.removeEventListener('click', dismiss); }
  };
  const keyDismiss = (e) => {
    if (e.key === 'Escape') { popup.remove(); document.removeEventListener('keydown', keyDismiss); }
  };
  setTimeout(() => {
    document.addEventListener('click', dismiss);
    document.addEventListener('keydown', keyDismiss);
  }, 10);
}

// ── Inject (or update) a context subtitle inside a card header ────────────────
function _setHcCardSubtitle(cardId, text) {
  const card = document.getElementById(cardId);
  if (!card) return;
  let sub = card.querySelector('.hc-card-subtitle');
  if (!sub) {
    sub = document.createElement('div');
    sub.className = 'hc-card-subtitle';
    const header = card.querySelector('.card-header');
    if (header) header.appendChild(sub);
  }
  sub.textContent = text;
}

// ── Format raw offer/campaign names for display ───────────────────────────────
// Appends (offer_id) when known via _offerMap.  The raw offerName is always
// kept as the data-offer / onclick key so filtering still works correctly.
function _fmtOfferName(raw) {
  if (!raw) return raw;
  const clean = raw.replace(/_/g, ' ').replace(/\s{2,}/g, ' ').trim();
  const id    = window._offerMap?.[raw];
  return id ? `${clean} (${id})` : clean;
}

// ── Expand a hidden section (show-more pattern) ───────────────────────────────
function _hcExpandSection(btn, hiddenId, moreId) {
  const hidden = document.getElementById(hiddenId);
  if (hidden) hidden.style.display = '';
  const more = document.getElementById(moreId);
  if (more) more.remove();
}

// ── Stat summary bar helper ───────────────────────────────────────────────────
// stats = [{color, label, count}], impact = string or null
function _hcStatBar(stats, impact) {
  const chips = stats.map(s =>
    `<div class="hc-stat-chip">
      <span class="hc-stat-dot" style="background:${s.color}"></span>
      <span class="hc-stat-label">${s.label}</span>
      <span class="hc-stat-count" style="color:${s.color}">${s.count}</span>
    </div>`
  ).join('');
  const impactHtml = impact
    ? `<div class="hc-stat-impact"><i class="fas fa-circle-dot" style="font-size:9px;margin-right:4px;opacity:0.6"></i>${impact}</div>`
    : '';
  return `<div class="hc-stat-bar">${chips}${impactHtml}</div>`;
}

// ── Segmented health bar helper ───────────────────────────────────────────────
function _hcSegmentBar(healthy, watchlist, at_risk) {
  const total = healthy + watchlist + at_risk;
  if (!total) return '';
  const hp = (healthy   / total * 100).toFixed(1);
  const wp = (watchlist / total * 100).toFixed(1);
  const rp = (at_risk   / total * 100).toFixed(1);
  return `<div class="hc-segment-bar">
    <div class="hc-seg hc-seg-healthy"   style="width:${hp}%" title="${healthy} Healthy"></div>
    <div class="hc-seg hc-seg-watchlist" style="width:${wp}%" title="${watchlist} Watchlist"></div>
    <div class="hc-seg hc-seg-at-risk"   style="width:${rp}%" title="${at_risk} At Risk"></div>
  </div>`;
}

// ── Show-8-then-expand list renderer ─────────────────────────────────────────
// Returns { html, listId } — caller wraps in appropriate container
let _hcListSeq = 0;
function _hcList(rows, renderFn, containerId) {
  const id       = containerId || ('hcl' + (++_hcListSeq));
  const MAX      = 8;
  const visible  = rows.slice(0, MAX);
  const hidden   = rows.slice(MAX);
  const vHtml    = visible.map(renderFn).join('');
  const hHtml    = hidden.map(renderFn).join('');
  const moreBtn  = hidden.length
    ? `<div id="${id}-more">
        <button class="hc-show-more-btn" onclick="_hcExpandSection(this,'${id}-hidden','${id}-more')">
          <i class="fas fa-chevron-down" style="font-size:10px"></i> Show ${hidden.length} more
        </button>
      </div>`
    : '';
  return `<div id="${id}-visible" class="hc-detail-list">${vHtml}</div>`
       + (hHtml ? `<div id="${id}-hidden" class="hc-detail-list" style="display:none">${hHtml}</div>` : '')
       + moreBtn;
}

async function loadHealthCheck() {
  const [cmpRes, digestRes] = await Promise.allSettled([
    api('/api/overview/comparisons'),
    api('/api/health/digest?' + qs()),
  ]);

  // ── 1. Executive Summary (period comparison cards) ────────────────────────
  if (cmpRes.status === 'fulfilled') {
    const d  = cmpRes.value;
    const wl = d.week_labels || {};
    _renderHcPeriod('hc-today-body', d.today_vs_yesterday);
    _renderHcPeriod('hc-week-body',  d.week_vs_prev_week);
    _renderHcPeriod('hc-mtd-body',   d.mtd_vs_last_month);
    const lbl = document.getElementById('hc-week-label');
    if (lbl && wl.current) lbl.textContent = `${wl.current}  vs  ${wl.previous}`;
  } else {
    ['hc-today-body','hc-week-body','hc-mtd-body'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<p style="color:var(--txt-muted);font-size:12px;padding:8px 0">Unavailable</p>';
    });
  }

  // ── Remaining sections all come from /api/health/digest ──────────────────
  if (digestRes.status !== 'fulfilled') {
    ['hc-priorities-body','hc-risk-body','hc-scale-body',
     'hc-pub-health-body','hc-off-health-body','hc-funnel-body','hc-anomaly-body']
      .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '<p style="color:var(--txt-muted);padding:16px">Could not load data.</p>';
      });
  } else {
    const d = digestRes.value;
    _renderHcPriorities(d.priorities        || []);
    _renderHcRisk      (d.revenue_at_risk   || []);
    _renderHcScale     (d.scale_opportunities || []);
    _renderHcEntityHealth('hc-pub-health-body', d.publisher_health || [], 'publisher');
    _renderHcEntityHealth('hc-off-health-body', d.offer_health     || [], 'offer');
    _renderHcFunnel    (d.funnel_issues     || []);
    _renderHcAnomalies (d.anomaly_groups    || {});
  }

  const ts = document.getElementById('health-last-updated');
  if (ts) ts.textContent = 'Updated ' + new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
}

function refreshHealthCheck() {
  _loaded.delete('health');
  ['hc-today-body','hc-week-body','hc-mtd-body',
   'hc-priorities-body','hc-risk-body','hc-scale-body',
   'hc-pub-health-body','hc-off-health-body','hc-funnel-body','hc-anomaly-body']
    .forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="hc-loading" style="padding:20px"><i class="fas fa-circle-notch fa-spin"></i></div>';
    });
  loadHealthCheck();
}

// ── Period comparison card renderer ───────────────────────────────────────────
function _renderHcPeriod(bodyId, cmp) {
  if (!cmp) return;
  const el = document.getElementById(bodyId);
  if (!el) return;

  function _chip(pct) {
    if (pct == null) return '<span class="hc-metric-delta hc-delta-flat">—</span>';
    const cls   = pct > 0 ? 'hc-delta-up' : pct < 0 ? 'hc-delta-down' : 'hc-delta-flat';
    const arrow = pct > 0 ? '▲' : pct < 0 ? '▼' : '→';
    return `<span class="hc-metric-delta ${cls}">${arrow} ${Math.abs(pct)}%</span>`;
  }

  const marginVal = (cmp.revenue?.current > 0 && cmp.profit?.current != null)
    ? fmtN(Math.round(cmp.profit.current / cmp.revenue.current * 1000) / 10) + '%'
    : '—';

  const rows = [
    { label: 'Revenue',   val: fmtCur(cmp.revenue?.current),   delta: cmp.revenue?.pct_change   },
    { label: 'Profit',    val: fmtCur(cmp.profit?.current),    delta: cmp.profit?.pct_change    },
    { label: 'Margin %',  val: marginVal,                       delta: null                      },
    { label: 'Conversions',  val: fmtI(cmp.installs?.current),    delta: cmp.installs?.pct_change  },
  ];

  el.innerHTML = rows.map(r => `
    <div class="hc-metric-row">
      <span class="hc-metric-label">${r.label}</span>
      <div style="display:flex;align-items:center;gap:8px">
        <span class="hc-metric-value">${r.val}</span>
        ${_chip(r.delta)}
      </div>
    </div>`).join('');
}

// ── Today's Action Queue ──────────────────────────────────────────────────────
function _renderHcPriorities(items) {
  const body  = document.getElementById('hc-priorities-body');
  const badge = document.getElementById('hc-priorities-badge');
  if (!body) return;
  if (badge) badge.textContent = items.length;

  if (!items.length) {
    body.innerHTML = `<div class="hc-no-alerts" style="padding:28px 20px">
      <i class="fas fa-circle-check" style="font-size:20px;margin-bottom:8px;display:block"></i>
      No urgent priorities — all key metrics look healthy.
    </div>`;
    return;
  }

  // Severity groups — order and visual treatment
  const groupDefs = [
    { key: 'critical', label: 'Critical',    color: 'var(--red)',   desc: 'Negative margin or losing revenue — act now' },
    { key: 'warning',  label: 'Warning',     color: 'var(--amber)', desc: 'Low margin or declining revenue — monitor closely' },
    { key: 'success',  label: 'Opportunity', color: 'var(--green)', desc: 'Strong margin — consider increasing spend' },
  ];
  const buckets = { critical: [], warning: [], success: [] };
  items.forEach(item => (buckets[item.severity] || buckets.warning).push(item));

  const renderRow = (item) => {
    const nameRaw  = item.entity;
    const nameDisp = item.entity_type === 'publisher' ? _partnerLabel(nameRaw) : _fmtOfferName(nameRaw);
    const onClick  = item.entity_type === 'publisher'
      ? `openPublisherProfile('${esc(nameRaw)}')`
      : `openOfferProfile('${esc(nameRaw)}')`;
    const rev      = item.revenue != null ? `$${fmtN(item.revenue)}` : '—';
    const revColor = item.type === 'scale_opportunity' ? 'var(--green)'
                   : item.severity === 'critical'      ? 'var(--red)'
                   : 'var(--amber)';
    return `<div class="hc-aq-row" onclick="${onClick}">
      <div class="hc-aq-item">
        <div class="hc-aq-name" title="${esc(nameRaw)}">${esc(nameDisp)}</div>
      </div>
      <div class="hc-aq-reason">
        <span class="hc-aq-reason-text">${esc(item.detail)}</span>
      </div>
      <div class="hc-aq-impact">
        <span class="hc-aq-impact-rev" style="color:${revColor}">${rev}</span>
      </div>
    </div>`;
  };

  const colHeader = `<div class="hc-aq-col-header">
    <div>Offer / Publisher</div>
    <div>What's happening</div>
    <div style="text-align:right">Revenue</div>
  </div>`;

  const groupsHtml = groupDefs
    .filter(g => buckets[g.key].length > 0)
    .map(g => {
      const n = buckets[g.key].length;
      return `<div class="hc-aq-group">
        <div class="hc-aq-group-header" style="border-left-color:${g.color}">
          <span class="hc-aq-group-label" style="color:${g.color}">${g.label}</span>
          <span class="hc-aq-group-count">${n} item${n > 1 ? 's' : ''} — ${g.desc}</span>
        </div>
        <div class="hc-aq-group-rows">${buckets[g.key].map(renderRow).join('')}</div>
      </div>`;
    }).join('');

  body.innerHTML = colHeader + groupsHtml;
}

// ── Revenue At Risk ───────────────────────────────────────────────────────────
function _renderHcRisk(items) {
  const body  = document.getElementById('hc-risk-body');
  const badge = document.getElementById('hc-risk-badge');
  if (!body) return;
  if (badge) badge.textContent = items.length;

  if (!items.length) {
    body.innerHTML = `<div class="hc-no-alerts">
      <i class="fas fa-shield-check" style="color:var(--green);font-size:18px;margin-bottom:8px;display:block"></i>
      No revenue at risk — margins and revenue look stable.
    </div>`;
    return;
  }

  const critical   = items.filter(r => r.severity === 'critical').length;
  const warning    = items.length - critical;
  const totalRev   = items.reduce((s, r) => s + (r.revenue || 0), 0);
  _setHcCardSubtitle('hc-risk-card',
    `${critical} critical · ${warning} warning · $${fmtN(totalRev)} revenue exposed`);
  const statBar    = _hcStatBar(
    [
      { color: 'var(--red)',   label: 'Critical', count: critical },
      { color: 'var(--amber)', label: 'Warning',  count: warning  },
    ],
    `$${fmtN(totalRev)} exposed`
  );

  const renderRow = (r) => {
    const mc         = marginColor(r.margin_pct);
    const reasonText = r.reasons.join(' · ');
    return `<div class="hc-entity-row" onclick="openOfferProfile('${esc(r.offerName)}')" style="cursor:pointer">
      <div class="hc-entity-left">
        <div class="hc-entity-name" title="${esc(r.offerName)}">${esc(_fmtOfferName(r.offerName))}</div>
        <div class="hc-entity-reason">${esc(reasonText)}</div>
      </div>
      <div class="hc-entity-right">
        <div style="font-weight:700;color:${mc};font-size:13px">${fmtN(r.margin_pct)}%</div>
        <div style="font-size:12px;color:var(--txt-muted)">$${fmtN(r.revenue)}</div>
      </div>
    </div>`;
  };

  body.innerHTML = statBar + _hcList(items, renderRow);
}

// ── Scale Opportunities ───────────────────────────────────────────────────────
function _renderHcScale(items) {
  const body  = document.getElementById('hc-scale-body');
  const badge = document.getElementById('hc-scale-badge');
  if (!body) return;
  if (badge) badge.textContent = items.length;

  if (!items.length) {
    body.innerHTML = `<div class="hc-no-alerts">
      <i class="fas fa-chart-line" style="color:var(--txt-muted);font-size:18px;margin-bottom:8px;display:block"></i>
      No high-confidence scale opportunities right now.
    </div>`;
    return;
  }

  const high       = items.filter(r => r.confidence === 'high').length;
  const medium     = items.length - high;
  const totalRev   = items.reduce((s, r) => s + (r.revenue || 0), 0);
  const avgMargin  = items.length
    ? Math.round(items.reduce((s,r) => s+(r.margin_pct||0),0) / items.length)
    : 0;
  _setHcCardSubtitle('hc-scale-card',
    `${high} high-confidence · $${fmtN(totalRev)} revenue · avg ${avgMargin}% margin`);
  const statBar    = _hcStatBar(
    [
      { color: 'var(--green)', label: 'High conf.',   count: high   },
      { color: 'var(--amber)', label: 'Medium conf.', count: medium },
    ],
    `$${fmtN(totalRev)} upside`
  );

  const renderRow = (r) => {
    const confColor = r.confidence === 'high' ? C.green : C.amber;
    const confLabel = r.confidence === 'high' ? 'High' : 'Medium';
    return `<div class="hc-entity-row" onclick="openOfferProfile('${esc(r.offerName)}')" style="cursor:pointer">
      <div class="hc-entity-left">
        <div class="hc-entity-name" title="${esc(r.offerName)}">${esc(_fmtOfferName(r.offerName))}</div>
        <div style="font-size:12px;color:var(--txt-muted);margin-top:4px">
          ${fmtI(r.installs)} conversions · $${fmtN(r.profit)} profit
        </div>
      </div>
      <div class="hc-entity-right">
        <div style="font-weight:700;color:${C.green};font-size:13px">${fmtN(r.margin_pct)}%</div>
        <div style="font-size:11px;font-weight:600;color:${confColor}">${confLabel}</div>
      </div>
    </div>`;
  };

  body.innerHTML = statBar + _hcList(items, renderRow);
}

// ── Publisher / Offer Health compact ranking ──────────────────────────────────
function _renderHcEntityHealth(bodyId, items, type) {
  const body = document.getElementById(bodyId);
  if (!body) return;

  if (!items.length) {
    body.innerHTML = `<div class="hc-no-alerts" style="padding:20px">No data for selected range.</div>`;
    return;
  }

  const counts = { healthy: 0, watchlist: 0, at_risk: 0 };
  items.forEach(r => { const k = r.status; counts[k] = (counts[k] || 0) + 1; });

  // Segmented bar + stat chips
  const headerBlock = `
    <div class="hc-health-header">
      ${_hcSegmentBar(counts.healthy, counts.watchlist, counts.at_risk)}
      <div class="hc-health-counts">
        <span class="hc-stat-chip">
          <span class="hc-stat-dot" style="background:var(--green)"></span>
          <span class="hc-stat-label">Healthy</span>
          <span class="hc-stat-count" style="color:var(--green)">${counts.healthy}</span>
        </span>
        <span class="hc-stat-chip">
          <span class="hc-stat-dot" style="background:var(--amber)"></span>
          <span class="hc-stat-label">Watchlist</span>
          <span class="hc-stat-count" style="color:var(--amber)">${counts.watchlist}</span>
        </span>
        <span class="hc-stat-chip">
          <span class="hc-stat-dot" style="background:var(--red)"></span>
          <span class="hc-stat-label">At Risk</span>
          <span class="hc-stat-count" style="color:var(--red)">${counts.at_risk}</span>
        </span>
      </div>
    </div>`;

  const renderRow = (r) => {
    const mc      = marginColor(r.margin_pct);
    const nameRaw = type === 'publisher' ? r.partner : r.offerName;
    const name    = type === 'publisher' ? _partnerLabel(r.partner) : _fmtOfferName(r.offerName);
    const onClick = type === 'publisher'
      ? `openPublisherProfile('${esc(nameRaw)}')`
      : `openOfferProfile('${esc(nameRaw)}')`;
    const dotCls  = r.status === 'at_risk' ? 'at-risk' : r.status;
    return `<div class="hc-health-row status-${r.status}" onclick="${onClick}" style="cursor:pointer">
      <span class="hc-dot hc-dot-${dotCls}" style="flex-shrink:0"></span>
      <div class="hc-entity-name" style="flex:1;min-width:0" title="${esc(name)}">${esc(name)}</div>
      <div style="text-align:right;flex-shrink:0">
        <div style="font-weight:700;color:${mc};font-size:12px">${fmtN(r.margin_pct)}%</div>
        <div style="font-size:11px;color:var(--txt-muted)">$${fmtN(r.revenue)}</div>
      </div>
    </div>`;
  };

  body.innerHTML = headerBlock + `<div class="hc-health-list">${_hcList(items, renderRow)}</div>`;
}

// ── Funnel Issues ─────────────────────────────────────────────────────────────
function _renderHcFunnel(items) {
  const body  = document.getElementById('hc-funnel-body');
  const badge = document.getElementById('hc-funnel-badge');
  if (!body) return;
  if (badge) badge.textContent = items.length;

  if (!items.length) {
    body.innerHTML = `<div class="hc-no-alerts">
      <i class="fas fa-circle-check" style="color:var(--green);font-size:18px;margin-bottom:8px;display:block"></i>
      No funnel deterioration detected — conversion rates are stable.
    </div>`;
    return;
  }

  const severe   = items.filter(r => r.drop_pct > 60).length;
  const moderate = items.filter(r => r.drop_pct > 40 && r.drop_pct <= 60).length;
  const minor    = items.length - severe - moderate;
  _setHcCardSubtitle('hc-funnel-card',
    `${severe} severe · ${moderate} moderate · ${minor} minor conv. rate drops`);
  const statBar  = _hcStatBar(
    [
      { color: 'var(--red)',      label: 'Severe',   count: severe   },
      { color: 'var(--amber)',    label: 'Moderate', count: moderate },
      { color: 'var(--txt-label)',label: 'Minor',    count: minor    },
    ],
    null
  );

  const renderRow = (r) => {
    const sevColor = r.drop_pct > 60 ? 'var(--red)' : r.drop_pct > 40 ? 'var(--amber)' : 'var(--txt-muted)';
    return `<div class="hc-entity-row" onclick="openOfferProfile('${esc(r.offerName)}')" style="cursor:pointer">
      <div class="hc-entity-left">
        <div class="hc-entity-name" title="${esc(r.offerName)}">${esc(_fmtOfferName(r.offerName))}</div>
        <div style="font-size:12px;color:var(--txt-muted);margin-top:3px">
          Conv rate: <span style="color:var(--green)">${fmtN(r.prev_conv_rate)}%</span>
          → <span style="color:var(--red);font-weight:600">${fmtN(r.curr_conv_rate)}%</span>
          · ${fmtI(r.curr_conversions)} convs yesterday
        </div>
      </div>
      <div class="hc-entity-right">
        <div style="font-weight:700;color:${sevColor};font-size:13px">▼ ${fmtN(r.drop_pct)}%</div>
        <div style="font-size:11px;color:var(--txt-muted)">drop</div>
      </div>
    </div>`;
  };

  body.innerHTML = statBar + _hcList(items, renderRow);
}

// ── Anomaly Detection ─────────────────────────────────────────────────────────
function _renderHcAnomalies(groups) {
  const body  = document.getElementById('hc-anomaly-body');
  const badge = document.getElementById('hc-anomaly-total-badge');
  if (!body) return;

  const defs = [
    { key: 'margin_collapse', label: 'Margin Collapse',  icon: 'fa-arrow-down-to-line', color: 'var(--red)',    desc: 'Margin < 5%'           },
    { key: 'revenue_drop',    label: 'Revenue Drop',     icon: 'fa-chart-line-down',    color: 'var(--amber)',  desc: '> 40% drop yesterday'  },
    { key: 'install_drop',    label: 'Conversion Drop',     icon: 'fa-mobile-screen',      color: 'var(--amber)',  desc: '> 40% drop yesterday'  },
    { key: 'revenue_spike',   label: 'Revenue Spike',    icon: 'fa-chart-line',         color: 'var(--green)',  desc: '> 50% spike yesterday' },
  ];

  const total = defs.reduce((s, d) => s + (groups[d.key]?.count || 0), 0);
  if (badge) badge.textContent = total;

  if (!total) {
    body.innerHTML = `<div class="hc-no-alerts">
      <i class="fas fa-circle-check" style="color:var(--green);font-size:18px;margin-bottom:8px;display:block"></i>
      No anomalies detected — all day-over-day signals are within normal range.
    </div>`;
    return;
  }

  body.innerHTML = `<div class="hc-anomaly-grid">${defs.map(def => {
    const grp     = groups[def.key] || { count: 0, examples: [] };
    const isEmpty = grp.count === 0;
    const examples = grp.examples.map(ex => {
      const name   = ex.offerName;
      const detail = def.key === 'margin_collapse' ? `${ex.margin_pct}% margin`
                   : def.key === 'revenue_drop'    ? `↓${ex.drop_pct}% ($${fmtN(ex.base_revenue)})`
                   : def.key === 'install_drop'    ? `↓${ex.drop_pct}% (${fmtI(ex.base_installs)} base)`
                   : `↑${ex.spike_pct}% ($${fmtN(ex.revenue)})`;
      return `<div class="hc-anomaly-example" onclick="openOfferProfile('${esc(name)}')" style="cursor:pointer">
        <span class="td-trunc" style="max-width:140px" title="${esc(name)}">${esc(_fmtOfferName(name))}</span>
        <span style="color:${def.color};font-weight:600;flex-shrink:0">${detail}</span>
      </div>`;
    }).join('');

    return `<div class="hc-anomaly-tile${isEmpty ? ' hc-anomaly-tile-empty' : ''}">
      <div class="hc-anomaly-header">
        <i class="fas ${def.icon}" style="color:${isEmpty ? 'var(--txt-muted)' : def.color};font-size:16px"></i>
        <div>
          <div class="hc-anomaly-label">${def.label}</div>
          <div style="font-size:11px;color:var(--txt-muted)">${def.desc}</div>
        </div>
        <span class="hc-anomaly-count${isEmpty ? ' empty' : ''}">${grp.count}</span>
      </div>
      ${examples ? `<div class="hc-anomaly-examples">${examples}</div>` : ''}
    </div>`;
  }).join('')}</div>`;
}

// ── 7 KPI cards ───────────────────────────────────────────────────
async function loadOverviewKPIs() {
  try {
    const d = await api('/api/overview/kpis?'+qs());
    const mColor = d.profit >= 0 ? C.green : C.red;
    const mpColor = d.margin_pct >= 30 ? C.green : d.margin_pct >= 15 ? C.amber : C.red;
    const items = [
      { label:'Revenue',        value:fmtCur(d.revenue),         icon:'fa-dollar-sign', color:C.blue,   iconBg:'#eff6ff', iconClr:C.blue   },
      { label:'Cost',           value:fmtCur(d.cost),            icon:'fa-money-bill-wave',   color:C.red,    iconBg:'#fef2f2', iconClr:C.red    },
      { label:'Profit',         value:fmtCur(d.profit),          icon:'fa-arrow-trend-up',    color:mColor,   iconBg:'#ecfdf5', iconClr:mColor   },
      { label:'Margin %',       value:fmtPct(d.margin_pct),      icon:'fa-percent',           color:mpColor,  iconBg:'#fffbeb', iconClr:'#d97706'},
      { label:'Active Offers',  value:fmtI(d.active_offers),     icon:'fa-tag',               color:C.teal,   iconBg:'#f0fdfa', iconClr:C.teal   },
      { label:'Publishers',     value:fmtI(d.active_publishers), icon:'fa-handshake',         color:C.sky,    iconBg:'#f0f9ff', iconClr:C.sky    },
      { label:'Conversions',       value:fmtI(d.installs),          icon:'fa-mobile-screen',     color:C.purple, iconBg:'#f5f3ff', iconClr:C.purple },
    ];
    document.getElementById('ov-kpi-row').innerHTML = items.map(k => `
      <div class="kpi-card" style="--kpi-color:${k.color}">
        <div class="kpi-top"><div class="kpi-icon" style="background:${k.iconBg};color:${k.iconClr}"><i class="fas ${k.icon}"></i></div></div>
        <div class="kpi-label">${k.label}</div>
        <div class="kpi-value">${k.value}</div>
      </div>`).join('');
  } catch(e) { console.error('OV KPI:', e); }
}

// ── Period comparisons ────────────────────────────────────────────
async function loadOverviewComparisons() {
  try {
    const d = await api('/api/overview/comparisons?'+qs());

    // Update subtitle with actual week dates from backend
    const wl = d.week_labels;
    if (wl) {
      const sub = document.getElementById('ov-cmp-subtitle');
      if (sub) sub.textContent =
        `Today vs Yesterday  ·  Week (${wl.current}) vs Week (${wl.previous})  ·  MTD vs Last Month`;
    }

    const sections = [
      { key:'today_vs_yesterday', title:'Today vs Yesterday' },
      { key:'week_vs_prev_week',  title:`Week (${wl?.current||'Current'}) vs (${wl?.previous||'Prev'})` },
      { key:'mtd_vs_last_month',  title:'MTD vs Last Month' },
    ];
    document.getElementById('ov-comparisons').innerHTML = sections.map(s => {
      const cmp = d[s.key];
      const rows = [
        { label:'Revenue',     val:cmp.revenue },
        { label:'Cost',        val:cmp.cost },
        { label:'Profit',      val:cmp.profit },
        { label:'Conversions', val:cmp.conversions, fmt:'I' },
      ];
      return `<div class="comparison-card">
        <div class="comparison-card-title">${s.title}</div>
        ${rows.map(r => {
          const cur = r.fmt==='I' ? fmtI(r.val.current) : fmtCur(r.val.current);
          return `<div class="cmp-row">
            <span class="cmp-label">${r.label}</span>
            <span class="cmp-vals">
              <span class="cmp-current">${cur}</span>
              ${fmtChange(r.val.pct_change)}
            </span>
          </div>`;
        }).join('')}
      </div>`;
    }).join('');
  } catch(e) { console.error('OV compare:', e); }
}

// ── Performance trend chart ───────────────────────────────────────
// D7 / D14 / D30 / Custom all use the EXACT same function, layout,
// and trace config. Only the date range differs.
// Bar width is locked to 22 h (in ms) so bars look the same
// whether there are 7 or 30 data points.

const _TREND_BAR_WIDTH_MS = 22 * 60 * 60 * 1000;   // 22 hours → consistent bar width

const _TREND_LAYOUT = {
  ...L,
  barmode  : 'overlay',
  xaxis    : { ...L.xaxis, type: 'date', tickformat: '%b %d', tickangle: -30, automargin: true },
  yaxis    : {
    ...L.yaxis,
    tickprefix: '$', tickformat: ',.0s', rangemode: 'tozero',
    title: { text: 'Revenue', font: { size: 11, color: '#94a3b8' }, standoff: 8 },
  },
  yaxis2   : {
    ...L.yaxis,
    overlaying: 'y', side: 'right', ticksuffix: '%', showgrid: false, rangemode: 'normal',
    title: { text: 'Margin %', font: { size: 11, color: '#10b981' }, standoff: 8 },
    tickfont: { size: 11, color: '#10b981' },
  },
  yaxis3   : {
    overlaying: 'y', side: 'left', rangemode: 'tozero',
    showticklabels: false, showgrid: false, zeroline: false,
  },
  legend   : { ...L.legend, orientation: 'h', y: -0.25, x: 0 },
  hovermode: 'x unified',
  margin   : { t: 10, r: 85, b: 72, l: 85 },
};

function setTrendDays(btn, days) {
  document.querySelectorAll('.trend-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  _trendDays = days;
  loadOverviewTrend(days);
}

async function loadOverviewTrend(days) {
  const el = document.getElementById('chart-ov-trend');
  try {
    const data = await api('/api/overview/trend?' + qs({ days }));

    if (!data.length) {
      Plotly.purge(el);
      noChart('chart-ov-trend', 'No data for the selected range');
      return;
    }

    const dates    = data.map(r => r.date);
    const revenue  = data.map(r => r.revenue);
    const margin   = data.map(r => r.margin_pct);
    const installs = data.map(r => r.installs);

    const traces = [
      {                                        // ── Bars: Conversions (background, y3)
        x: dates, y: installs,
        type: 'bar', name: 'Conversions',
        yaxis: 'y3',
        width: _TREND_BAR_WIDTH_MS,           // ← locked width — same for all periods
        marker: {
          color: 'rgba(139,92,246,0.20)',
          line : { color: 'rgba(139,92,246,0.45)', width: 1 },
        },
        hovertemplate: '<b>%{x}</b><br>Conversions: %{y:,}<extra></extra>',
      },
      {                                        // ── Line: Revenue (left, y1)
        x: dates, y: revenue,
        mode: 'lines+markers', name: 'Revenue',
        yaxis: 'y',
        line  : { color: C.blue,  width: 2.5, shape: 'spline' },
        marker: { size: 5, color: C.blue },
        hovertemplate: '<b>%{x}</b><br>Revenue: $%{y:,.2f}<extra></extra>',
      },
      {                                        // ── Line: Margin % (right, y2)
        x: dates, y: margin,
        mode: 'lines+markers', name: 'Margin %',
        yaxis: 'y2',
        line  : { color: C.green, width: 2.5, shape: 'spline', dash: 'dash' },
        marker: { size: 5, color: C.green },
        hovertemplate: '<b>%{x}</b><br>Margin: %{y:.1f}%<extra></extra>',
      },
    ];

    // Purge before each render — prevents stale layout from a previous period
    Plotly.purge(el);
    Plotly.newPlot(el, traces, _TREND_LAYOUT, PC);
  } catch(e) {
    console.error('OV trend:', e);
    if (typeof Plotly !== 'undefined') Plotly.purge(el);
    noChart('chart-ov-trend');
  }
}

// ── Leaderboards ──────────────────────────────────────────────────
async function loadOverviewLeaderboards() {
  try {
    const d = await api('/api/overview/leaderboards?'+qs());

    const renderLB = (rows, nameKey, tbodyId) => {
      document.getElementById(tbodyId).innerHTML = rows.map((r, i) => {
        const mc          = marginColor(r.margin_pct);
        const displayName = nameKey === 'partner' ? _partnerLabel(r[nameKey]) : _fmtOfferName(r[nameKey]);
        return `<tr>
          <td><span class="lb-rank lb-rank-${i < 3 ? i+1 : 0}">${i+1}</span></td>
          <td class="td-trunc" title="${esc(displayName)}" style="max-width:180px">${esc(displayName)}</td>
          <td class="td-r" style="font-weight:600;color:${C.blue}">$${fmtN(r.revenue)}</td>
          <td class="td-r" style="color:${C.red}">$${fmtN(r.payout)}</td>
          <td class="td-r" style="font-weight:600;color:${r.profit>=0?C.green:C.red}">$${fmtN(r.profit)}</td>
          <td class="td-r" style="font-weight:700;color:${mc}">${fmtN(r.margin_pct)}%</td>
        </tr>`;
      }).join('') || `<tr><td colspan="6" style="text-align:center;padding:20px;color:#94a3b8">No data</td></tr>`;
    };

    renderLB(d.publishers, 'partner',   'lb-publishers');
    renderLB(d.offers,     'offerName', 'lb-offers');
  } catch(e) { console.error('leaderboards:', e); }
}

// ══════════════════════════════════════════════════════════════════
//  PUBLISHERS PAGE
// ══════════════════════════════════════════════════════════════════
async function loadPubSummary() {
  try {
    const [kpiData, sumData] = await Promise.all([
      api('/api/publishers/kpis?' + qs()),
      api('/api/publishers/summary?' + qs()),
    ]);
    const pubs = sumData.publishers || [];
    const k    = kpiData;

    // Cache for modal use
    window._pubKpiData = k;

    // ── Badge
    const badge = document.getElementById('pub-table-badge');
    if (badge) badge.textContent = fmtI(pubs.length) + ' publishers';

    // ── 4 KPI cards
    const profitClr = k.total_profit >= 0 ? C.green : C.red;
    const mpClr     = k.profit_pct >= 30 ? C.green : k.profit_pct >= 15 ? C.amber : C.red;
    const cardDefs = [
      {
        label: 'Total Publishers', value: fmtI(k.total_configured),
        sub: 'Configured publishers',
        icon: 'fa-handshake', color: C.sky, iconBg: '#f0f9ff', iconClr: C.sky,
        clickable: true, onclick: 'openPubListModal()',
      },
      {
        label: 'Revenue', value: fmtCur(k.total_revenue),
        sub: 'Selected date range',
        icon: 'fa-dollar-sign', color: C.blue, iconBg: '#eff6ff', iconClr: C.blue,
      },
      {
        label: 'Profit', value: fmtCur(k.total_profit),
        sub: fmtN(k.profit_pct) + '% of revenue',
        icon: 'fa-arrow-trend-up', color: profitClr, iconBg: '#ecfdf5', iconClr: profitClr,
      },
      {
        label: 'Publisher Status', value: fmtI(k.active_count) + ' Active',
        sub: fmtI(k.paused_count) + ' Paused',
        icon: 'fa-circle-dot', color: C.green, iconBg: '#ecfdf5', iconClr: C.green,
        clickable: true, onclick: 'openPubStatusModal()',
      },
    ];
    document.getElementById('pub-kpi-row').innerHTML = cardDefs.map(c => `
      <div class="kpi-card${c.clickable ? ' kpi-card-click' : ''}"
           style="--kpi-color:${c.color}"
           ${c.clickable ? `onclick="${c.onclick}"` : ''}>
        <div class="kpi-top">
          <div class="kpi-icon" style="background:${c.iconBg};color:${c.iconClr}">
            <i class="fas ${c.icon}"></i>
          </div>
        </div>
        <div class="kpi-label">${c.label}</div>
        <div class="kpi-value">${c.value}</div>
        <div class="kpi-sub">${c.sub || ''}</div>
        ${c.clickable ? '<div class="kpi-click-hint"><i class="fas fa-hand-pointer"></i> Click to view</div>' : ''}
      </div>`).join('');

    if (!pubs.length) {
      noChart('chart-pub-revenue', 'No publisher data');
      noChart('chart-pub-margin',  'No publisher data');
      document.getElementById('pub-table-body').innerHTML =
        `<tr><td colspan="7" class="td-empty"><div class="empty-state"><i class="fas fa-inbox empty-icon"></i><p>No publishers found</p></div></td></tr>`;
      return;
    }

    // Store for chart selectors
    window._pubAllData = pubs;

    // ── Charts (initial render using default selector values)
    try { renderPubRevenueChart(); } catch(ce) { console.error('pub revenue chart:', ce); noChart('chart-pub-revenue'); }
    try { renderPubMarginChart();  } catch(ce) { console.error('pub margin chart:',  ce); noChart('chart-pub-margin');  }

    // ── Table: Publisher | Revenue | Cost | Profit | Margin % | Conversions | Offers
    const tbody = document.getElementById('pub-table-body');
    tbody.innerHTML = pubs.map(r => {
      const mc = marginColor(r.margin_pct);
      return `<tr style="cursor:pointer" data-partner="${esc(r.partner)}"
                  onclick="openPublisherProfile(this.dataset.partner)">
        <td style="font-weight:600">${esc(_partnerLabel(r.partner))}</td>
        <td class="td-num rev">$${fmtN(r.revenue)}</td>
        <td class="td-num pay">$${fmtN(r.payout)}</td>
        <td class="td-num" style="color:${r.profit>=0?C.green:C.red};font-weight:600">$${fmtN(r.profit)}</td>
        <td class="td-num" style="font-weight:700;color:${mc}">${fmtN(r.margin_pct)}%</td>
        <td class="td-num">${fmtI(r.installs ?? 0)}</td>
        <td class="td-num">${fmtI(r.active_offers)}</td>
        <td class="td-center">${statusBadge(r.margin_pct)}</td>
      </tr>`;
    }).join('');
  } catch(e) { console.error('pub summary:', e); }
}

// ── Chart rendering functions (called by selectors and loadPubSummary)
function _pubTopN(selectId) {
  const sel = document.getElementById(selectId);
  const val = sel ? sel.value : '10';
  const pubs = window._pubAllData || [];
  return val === 'all' ? pubs : pubs.slice(0, parseInt(val, 10));
}

function renderPubRevenueChart() {
  const pubs = window._pubAllData || [];
  if (!pubs.length) return;
  const sel   = document.getElementById('pub-rev-topn');
  const n     = sel ? (sel.value === 'all' ? pubs.length : parseInt(sel.value, 10)) : 10;
  const top   = pubs.slice(0, n);
  const othersRev = pubs.slice(n).reduce((s, r) => s + r.revenue, 0);
  const labels = [...top.map(r => _partnerLabel(r.partner)), ...(othersRev > 0 ? ['Others'] : [])];
  const values = [...top.map(r => r.revenue),                ...(othersRev > 0 ? [Math.round(othersRev * 100) / 100] : [])];
  Plotly.react('chart-pub-revenue', [{
    labels, values, type: 'pie', hole: 0.5,
    marker: { colors: labels.map((_, i) => C.palette[i % C.palette.length]), line: { color: '#fff', width: 2 } },
    textinfo: 'percent', textfont: { size: 11, family: 'Inter, sans-serif' },
    hovertemplate: '<b>%{label}</b><br>Revenue: $%{value:,.2f}<br>%{percent}<extra></extra>',
  }], { ...L, margin: { t: 16, r: 20, b: 16, l: 20 },
        showlegend: true,
        legend: { orientation: 'v', x: 1.02, y: 0.5, font: { size: 11, color: '#64748b' } },
        height: 340 }, PC);
}

function renderPubMarginChart() {
  const pubs = window._pubAllData || [];
  if (!pubs.length) return;
  const sel = document.getElementById('pub-margin-topn');
  const n   = sel ? (sel.value === 'all' ? pubs.length : parseInt(sel.value, 10)) : 10;
  // Sort by margin_pct desc, take top N, then group rest as "Others (avg)"
  const sorted     = [...pubs].sort((a, b) => b.margin_pct - a.margin_pct);
  const top        = sorted.slice(0, n);
  const restPubs   = sorted.slice(n);
  const othersAvg  = restPubs.length
    ? restPubs.reduce((s, r) => s + r.margin_pct, 0) / restPubs.length
    : null;
  const labels = [...top.map(r => _partnerLabel(r.partner)), ...(othersAvg !== null ? ['Others (avg)'] : [])];
  const values = [...top.map(r => r.margin_pct),             ...(othersAvg !== null ? [Math.round(othersAvg * 100) / 100] : [])];
  Plotly.react('chart-pub-margin', [{
    labels, values, type: 'pie', hole: 0.5,
    marker: { colors: labels.map((_,i) => C.palette[i % C.palette.length]), line: { color: '#fff', width: 2 } },
    textinfo: 'percent', textfont: { size: 11, family: 'Inter, sans-serif' },
    hovertemplate: '<b>%{label}</b><br>Margin: %{value:.1f}%<extra></extra>',
  }], { ...L, margin: { t: 16, r: 20, b: 16, l: 20 },
        showlegend: true,
        legend: { orientation: 'v', x: 1.02, y: 0.5, font: { size: 11, color: '#64748b' } },
        height: 340 }, PC);
}

// ──────────────────────────────────────────────────────────────────
//  PUBLISHERS — modal helpers
// ──────────────────────────────────────────────────────────────────

// ── Total Publishers card → list all configured publishers
function openPubListModal() {
  const data = window._pubKpiData;
  if (!data) return;
  const list  = data.configured_list || [];
  const modal = document.getElementById('modal-pub-list');
  const title = document.getElementById('modal-pub-list-title');
  const body  = document.getElementById('modal-pub-list-body');
  if (!modal) return;
  if (title) title.textContent = 'All Publishers (' + list.length + ')';
  body.innerHTML = list.length
    ? '<div class="modal-pub-list">' + list.map(p => `
        <div class="modal-pub-item">
          <div>
            <div class="modal-pub-id">${esc(_partnerLabel(p.publisher_id))}</div>
          </div>
          <span class="status-chip chip-active">
            <i class="fas fa-circle" style="font-size:7px"></i> Configured
          </span>
        </div>`).join('') + '</div>'
    : '<p style="color:var(--txt-muted);text-align:center;padding:20px">No publishers configured</p>';
  modal.style.display = 'flex';
}
function closePubListModal() {
  const m = document.getElementById('modal-pub-list');
  if (m) m.style.display = 'none';
}

// ── Publisher Status card → active / paused split
function openPubStatusModal() {
  const data = window._pubKpiData;
  if (!data) return;
  const modal = document.getElementById('modal-pub-status');
  const body  = document.getElementById('modal-pub-status-body');
  if (!modal) return;
  const configured = data.configured_list || [];
  const activeSet  = new Set((data.active_list  || []).map(String));
  const pausedSet  = new Set((data.paused_list  || []).map(String));
  const activeItems = configured.filter(p => activeSet.has(String(p.publisher_id)));
  const pausedItems = configured.filter(p => pausedSet.has(String(p.publisher_id)));
  const renderItems = (items, chipCls, chipLabel) =>
    items.map(p => `
      <div class="modal-pub-item">
        <div>
          <div class="modal-pub-id">${esc(_partnerLabel(p.publisher_id))}</div>
        </div>
        <span class="status-chip ${chipCls}">${chipLabel}</span>
      </div>`).join('');
  body.innerHTML = `
    <div style="margin-bottom:20px">
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--green);margin-bottom:8px">
        Active (${activeItems.length})
      </div>
      <div class="modal-pub-list">
        ${activeItems.length
          ? renderItems(activeItems, 'chip-active', '<i class="fas fa-circle" style="font-size:7px"></i> Active')
          : '<p style="color:var(--txt-muted);font-size:13px">No active publishers in this date range</p>'}
      </div>
    </div>
    <div>
      <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--red);margin-bottom:8px">
        Paused (${pausedItems.length})
      </div>
      <div class="modal-pub-list">
        ${pausedItems.length
          ? renderItems(pausedItems, 'chip-paused', '<i class="fas fa-pause" style="font-size:7px"></i> Paused')
          : '<p style="color:var(--txt-muted);font-size:13px">No paused publishers</p>'}
      </div>
    </div>`;
  modal.style.display = 'flex';
}
function closePubStatusModal() {
  const m = document.getElementById('modal-pub-status');
  if (m) m.style.display = 'none';
}

// ══════════════════════════════════════════════════════════════════
//  SLIDE-OUT PANEL — shared component
// ══════════════════════════════════════════════════════════════════
let _spMode       = null;    // 'offer' | 'publisher'
let _spContext    = null;    // offer name OR partner name
let _spLoadedTabs = new Set();
let _spActiveTab  = null;

function openSlidePanel() {
  document.getElementById('slide-panel').classList.add('open');
  document.getElementById('slide-panel-overlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeSlidePanel() {
  document.getElementById('slide-panel').classList.remove('open');
  document.getElementById('slide-panel-overlay').classList.remove('open');
  document.body.style.overflow = '';
  _spMode       = null;
  _spContext    = null;
  _spLoadedTabs = new Set();
  _spActiveTab  = null;
}

function _spSetLoading() {
  document.getElementById('sp-body').innerHTML = `
    <div style="text-align:center;padding:64px;color:var(--txt-muted)">
      <i class="fas fa-circle-notch fa-spin" style="font-size:28px"></i>
      <p style="margin-top:14px;font-size:13px">Loading…</p>
    </div>`;
}

function _spSetError(msg) {
  document.getElementById('sp-body').innerHTML =
    `<p style="color:var(--red);text-align:center;padding:32px;font-size:13px">${esc(msg)}</p>`;
}

function _spBuildTabs(tabs, active) {
  const bar = document.getElementById('sp-tab-bar');
  bar.innerHTML = tabs.map(t =>
    `<button class="sp-tab${t.id === active ? ' active' : ''}" data-tab="${t.id}"
       onclick="switchPanelTab('${t.id}')">${t.label}</button>`
  ).join('');
}

function switchPanelTab(tab) {
  _spActiveTab = tab;
  document.querySelectorAll('#sp-tab-bar .sp-tab').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab));
  if (!_spLoadedTabs.has(tab)) {
    _spSetLoading();
    _spLoadTab(tab);
  }
}

async function _spLoadTab(tab) {
  if (!_spContext) return;
  try {
    if (_spMode === 'offer') {
      if (tab === 'publishers') await _spLoadOfferPublishers(_spContext);
      else if (tab === 'funnel') await _spLoadOfferFunnel(_spContext);
    } else if (_spMode === 'publisher') {
      if (tab === 'overview') await _spLoadPubOverview(_spContext);
      else if (tab === 'funnel') await _spLoadPubFunnel(_spContext);
    }
    _spLoadedTabs.add(tab);
  } catch(e) {
    _spSetError('Failed to load data. Please try again.');
    console.error('slide panel tab:', tab, e);
  }
}

// ── Entry point: open panel for an offer — REPLACED by openOfferProfile (full page) ──

// ── Tab: Publishers breakdown for this offer ──────────────────────
async function _spLoadOfferPublishers(offerName) {
  const params = new URLSearchParams();
  params.set('offers', offerName);
  if (state.from_date) params.set('from_date', state.from_date);
  if (state.to_date)   params.set('to_date',   state.to_date);
  if (state.partners.length) params.set('partners', state.partners.join(','));

  const data = await api('/api/offers/publishers?' + params.toString());
  const pubs  = data.publishers || [];

  if (!pubs.length) {
    document.getElementById('sp-body').innerHTML = `
      <div class="empty-state" style="padding:64px 0">
        <i class="fas fa-inbox empty-icon"></i>
        <p>No publisher data for this offer in the selected range.</p>
      </div>`;
    return;
  }

  const rows = pubs.map(r => {
    const mc = marginColor(r.margin_pct);
    // Offer context: show comparison table only — no drill-down from here
    return `<tr>
      <td style="font-weight:600">${esc(_partnerLabel(r.partner))}</td>
      <td class="td-num rev">$${fmtN(r.revenue)}</td>
      <td class="td-num pay">$${fmtN(r.payout)}</td>
      <td class="td-num" style="color:${r.profit>=0?C.green:C.red};font-weight:600">$${fmtN(r.profit)}</td>
      <td class="td-num" style="font-weight:700;color:${mc}">${fmtN(r.margin_pct)}%</td>
      <td class="td-num">${fmtI(r.conversions)}</td>
      <td class="td-center">${statusBadge(r.margin_pct)}</td>
    </tr>`;
  }).join('');

  document.getElementById('sp-body').innerHTML = `
    <div class="card" style="margin:0">
      <div class="card-header card-toolbar">
        <div class="toolbar-left">
          <h3 class="card-title">Publishers running this offer</h3>
          <span class="count-badge">${pubs.length}</span>
        </div>
        <span style="font-size:11px;color:var(--txt-muted)">Status = margin for this offer only</span>
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th>Publisher</th>
            <th class="th-num">Revenue</th>
            <th class="th-num">Cost</th>
            <th class="th-num">Profit</th>
            <th class="th-num">Margin %</th>
            <th class="th-num">Conv.</th>
            <th class="th-center">Status</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}

// ── Tab: Funnel for this offer ────────────────────────────────────
async function _spLoadOfferFunnel(offerName) {
  const params = new URLSearchParams();
  params.set('offers', offerName);
  if (state.from_date) params.set('from_date', state.from_date);
  if (state.to_date)   params.set('to_date',   state.to_date);
  if (state.partners.length) params.set('partners', state.partners.join(','));

  const data = await api('/api/funnel/data?' + params.toString());
  const hasExpected = data.has_expected || false;

  if (!data.steps?.length) {
    document.getElementById('sp-body').innerHTML = `
      <div class="empty-state" style="padding:64px 0">
        <i class="fas fa-inbox empty-icon"></i>
        <p>No funnel data for this offer in the selected range.</p>
      </div>`;
    return;
  }

  const kHtml = _funnelKpiHtml(data);
  const { noticeHtml, theadHtml, tbodyHtml } = _funnelHtml(data.steps, hasExpected);

  document.getElementById('sp-body').innerHTML = `
    <div class="kpi-grid kpi-grid-4" style="gap:10px">${kHtml}</div>
    ${noticeHtml}
    <div class="card" style="margin:0">
      <div class="table-wrap">
        <table class="data-table">
          <thead>${theadHtml}</thead>
          <tbody>${tbodyHtml}</tbody>
        </table>
      </div>
    </div>`;
}

// ── Entry point: open panel for a publisher ───────────────────────
async function openPublisherPanel(partnerName) {
  _spMode       = 'publisher';
  _spContext    = partnerName;
  _spLoadedTabs = new Set();
  _spActiveTab  = 'overview';

  document.getElementById('sp-title').textContent    = _partnerLabel(partnerName);
  document.getElementById('sp-subtitle').textContent = 'Publisher detail';

  _spBuildTabs([
    { id: 'overview', label: 'Overview' },
    { id: 'funnel',   label: 'Funnel'   },
  ], 'overview');

  _spSetLoading();
  openSlidePanel();
  await _spLoadTab('overview');
}

// ── Publisher tab: Overview (KPIs + offer breakdown) ─────────────
async function _spLoadPubOverview(partnerName) {
  const d       = await api('/api/publishers/detail?' + qs({ partner: partnerName }));
  const s       = d.stats  || {};
  const offers  = d.offers || [];
  const profClr = (s.profit || 0) >= 0 ? C.green : C.red;
  const mpClr   = marginColor(s.margin_pct || 0);

  // Update subtitle with publisher-level status badge
  const subEl = document.getElementById('sp-subtitle');
  if (subEl) subEl.innerHTML = `Publisher · ${statusBadge(s.margin_pct || 0)}`;

  const kpiHtml = [
    { label:'Revenue',      value:fmtCur(s.revenue),    icon:'fa-dollar-sign', color:C.blue,   iconBg:'#eff6ff', iconClr:C.blue   },
    { label:'Cost',         value:fmtCur(s.cost),       icon:'fa-money-bill-wave',   color:C.red,    iconBg:'#fef2f2', iconClr:C.red    },
    { label:'Profit',       value:fmtCur(s.profit),     icon:'fa-arrow-trend-up',    color:profClr,  iconBg:'#ecfdf5', iconClr:profClr  },
    { label:'Margin %',     value:fmtPct(s.margin_pct), icon:'fa-percent',           color:mpClr,    iconBg:'#fffbeb', iconClr:'#d97706'},
    { label:'Total Offers', value:fmtI(s.active_offers),icon:'fa-tag',               color:C.sky,    iconBg:'#f0f9ff', iconClr:C.sky    },
  ].map(c => `
    <div class="kpi-card" style="--kpi-color:${c.color};padding:14px">
      <div class="kpi-top"><div class="kpi-icon" style="background:${c.iconBg};color:${c.iconClr};width:28px;height:28px;font-size:11px"><i class="fas ${c.icon}"></i></div></div>
      <div class="kpi-label">${c.label}</div>
      <div class="kpi-value" style="font-size:18px">${c.value}</div>
    </div>`).join('');

  const tableRows = offers.map(r => {
    const omc = marginColor(r.margin_pct);
    return `<tr style="cursor:pointer" data-offer="${esc(r.offerName)}"
                onclick="openOfferProfile(this.dataset.offer)">
      <td class="td-trunc" title="${esc(r.offerName)}" style="font-weight:500;max-width:200px">${esc(_fmtOfferName(r.offerName))}</td>
      <td class="td-num rev">$${fmtN(r.revenue)}</td>
      <td class="td-num pay">$${fmtN(r.payout)}</td>
      <td class="td-num" style="color:${r.profit>=0?C.green:C.red};font-weight:600">$${fmtN(r.profit)}</td>
      <td class="td-num" style="font-weight:700;color:${omc}">${fmtN(r.margin_pct)}%</td>
      <td class="td-num">${fmtI(r.installs ?? 0)}</td>
      <td class="td-center">${statusBadge(r.margin_pct)}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="7" class="td-empty"><div class="empty-state"><i class="fas fa-inbox empty-icon"></i><p>No offers</p></div></td></tr>`;

  document.getElementById('sp-body').innerHTML = `
    <div class="kpi-grid kpi-grid-5" style="gap:10px">${kpiHtml}</div>
    <div class="card" style="margin:0">
      <div class="card-header card-toolbar">
        <div class="toolbar-left">
          <h3 class="card-title">Offer Breakdown</h3>
          <span class="count-badge">${offers.length} offers</span>
        </div>
        <span style="font-size:11px;color:var(--txt-muted)">Click offer to drill down</span>
      </div>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th>Offer</th>
            <th class="th-num">Revenue</th>
            <th class="th-num">Cost</th>
            <th class="th-num">Profit</th>
            <th class="th-num">Margin %</th>
            <th class="th-num">Conversions</th>
            <th class="th-center">Status</th>
          </tr></thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>
    </div>`;
}

// ── Publisher tab: Funnel (all this publisher's offers combined) ──
async function _spLoadPubFunnel(partnerName) {
  const params = new URLSearchParams();
  params.set('partners', partnerName);
  if (state.from_date) params.set('from_date', state.from_date);
  if (state.to_date)   params.set('to_date',   state.to_date);

  const data = await api('/api/funnel/data?' + params.toString());
  const hasExpected = data.has_expected || false;

  if (!data.steps?.length) {
    document.getElementById('sp-body').innerHTML = `
      <div class="empty-state" style="padding:64px 0">
        <i class="fas fa-inbox empty-icon"></i>
        <p>No funnel data for this publisher in the selected range.</p>
      </div>`;
    return;
  }

  const kHtml = _funnelKpiHtml(data);
  const { noticeHtml, theadHtml, tbodyHtml } = _funnelHtml(data.steps, hasExpected);

  document.getElementById('sp-body').innerHTML = `
    <div class="kpi-grid kpi-grid-4" style="gap:10px">${kHtml}</div>
    ${noticeHtml}
    <div class="card" style="margin:0">
      <div class="table-wrap">
        <table class="data-table">
          <thead>${theadHtml}</thead>
          <tbody>${tbodyHtml}</tbody>
        </table>
      </div>
    </div>`;
}

// ══════════════════════════════════════════════════════════════════
//  OFFERS PAGE
// ══════════════════════════════════════════════════════════════════
async function loadOffersSummary() {
  try {
    const d = await api('/api/offers/summary?' + qs());
    const offers = d.offers || [];
    const kpis   = d.kpis   || {};
    const ac     = kpis.action_counts || {};

    // Cache for chart selectors
    window._offersAllData = offers;

    const badge = document.getElementById('off-table-badge');
    if (badge) badge.textContent = fmtI(offers.length) + ' offers';

    // ── 4 KPI cards ──────────────────────────────────────────────────────
    const profClr = (kpis.total_profit || 0) >= 0 ? C.green : C.red;
    document.getElementById('off-kpi-row').innerHTML = [
      {
        label: 'Total Offers', value: fmtI(kpis.total_offers),
        sub: `Active: ${fmtI(kpis.active_offers)} · Paused: ${fmtI(kpis.paused_offers)}`,
        icon: 'fa-tag', color: C.sky, iconBg: '#f0f9ff', iconClr: C.sky,
      },
      {
        label: 'Total Conversions', value: fmtI(kpis.total_installs),
        sub: `${fmtN(kpis.avg_installs_per_day)} conversions/day avg`,
        icon: 'fa-mobile-screen', color: C.purple, iconBg: '#f5f3ff', iconClr: C.purple,
      },
      {
        label: 'Revenue', value: fmtCur(kpis.total_revenue),
        sub: `Profit: ${fmtCur(kpis.total_profit)}`,
        icon: 'fa-dollar-sign', color: C.blue, iconBg: '#eff6ff', iconClr: C.blue,
      },
      {
        label: 'Offer Status', value: null,   // custom body below
        icon: 'fa-chart-pie', color: C.green, iconBg: '#ecfdf5', iconClr: C.green,
        customBody: `
          <div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:8px">
            <span class="rec-badge rec-scale">Scale ${fmtI(ac.scale)}</span>
            <span class="rec-badge rec-monitor">Monitor ${fmtI(ac.monitor)}</span>
            <span class="rec-badge rec-optimize">Optimize ${fmtI(ac.optimize)}</span>
            <span class="rec-badge rec-pause">Pause ${fmtI(ac.pause)}</span>
          </div>`,
      },
    ].map(c => `
      <div class="kpi-card" style="--kpi-color:${c.color}">
        <div class="kpi-top">
          <div class="kpi-icon" style="background:${c.iconBg};color:${c.iconClr}"><i class="fas ${c.icon}"></i></div>
        </div>
        <div class="kpi-label">${c.label}</div>
        ${c.value !== null ? `<div class="kpi-value">${c.value}</div>` : ''}
        ${c.sub ? `<div class="kpi-sub">${c.sub}</div>` : ''}
        ${c.customBody || ''}
      </div>`).join('');

    // ── Charts ────────────────────────────────────────────────────────────
    try { renderOffersRevenueChart();      } catch(ce) { console.error('off revenue chart:',      ce); noChart('chart-off-revenue');      }
    try { renderOffersDistributionChart(); } catch(ce) { console.error('off distribution chart:', ce); noChart('chart-off-distribution'); }

    // ── Table (10 cols, click → offer funnel modal) ───────────────────────
    document.getElementById('off-table-body').innerHTML = offers.map(r => {
      const mc      = marginColor(r.margin_pct);
      const isActive = r.status === 'active';
      const chip    = isActive
        ? '<span class="status-chip chip-active">Active</span>'
        : '<span class="status-chip chip-paused">Paused</span>';
      return `<tr style="cursor:pointer" data-offer="${esc(r.offerName)}"
                  onclick="openOfferProfile(this.dataset.offer)">
        <td class="td-trunc" title="${esc(r.offerName)}" style="font-weight:500;max-width:200px">${esc(_fmtOfferName(r.offerName))}</td>
        <td class="td-num rev">$${fmtN(r.revenue)}</td>
        <td class="td-num pay">$${fmtN(r.payout)}</td>
        <td class="td-num" style="color:${r.profit>=0?C.green:C.red};font-weight:600">$${fmtN(r.profit)}</td>
        <td class="td-num" style="color:${mc};font-weight:700">${fmtN(r.margin_pct)}%</td>
        <td class="td-num">${fmtI(r.installs ?? 0)}</td>
        <td class="td-center">${isActive ? recBadge(r.action || 'Monitor') : '—'}</td>
        <td class="td-num">${fmtI(r.active_publishers)}</td>
        <td style="font-size:12px;color:#94a3b8">${esc(r.first_seen)}</td>
        <td>${chip}</td>
      </tr>`;
    }).join('') || `<tr><td colspan="10" class="td-empty"><div class="empty-state"><i class="fas fa-inbox empty-icon"></i><p>No offers found</p></div></td></tr>`;
  } catch(e) { console.error('offers summary:', e); }
}

// ── Offers chart render helpers (called by selectors + loadOffersSummary)
const _ACTION_COLORS = { Scale: '#10b981', Monitor: '#0ea5e9', Optimize: '#f59e0b', Pause: '#ef4444' };

function renderOffersRevenueChart() {
  const all = (window._offersAllData || []).filter(r => r.status === 'active');
  if (!all.length) { noChart('chart-off-revenue', 'No data'); return; }
  const sel = document.getElementById('off-rev-topn');
  const n   = sel ? (sel.value === 'all' ? all.length : parseInt(sel.value, 10)) : 10;
  const top = all.slice(0, n);
  // Sort ascending so highest bar is at top
  const sorted = [...top].sort((a, b) => a.revenue - b.revenue);
  Plotly.react('chart-off-revenue', [{
    x: sorted.map(r => r.revenue),
    y: sorted.map(r => r.offerName),
    type: 'bar', orientation: 'h',
    marker: { color: sorted.map(r => _ACTION_COLORS[r.action] || C.blue), opacity: 0.85 },
    text: sorted.map(r => '$' + fmtN(r.revenue)),
    textposition: 'outside', textfont: { size: 10, color: '#64748b' }, cliponaxis: false,
    customdata: sorted.map(r => [r.action || '—', r.margin_pct]),
    hovertemplate: '<b>%{y}</b><br>Revenue: $%{x:,.2f}<br>Action: %{customdata[0]}<br>Margin: %{customdata[1]:.1f}%<extra></extra>',
  }], {
    ...L,
    margin: { t: 10, r: 120, b: 40, l: 150 },
    xaxis: { ...L.xaxis, tickprefix: '$', tickformat: ',.0s' },
    yaxis: { ...L.yaxis, automargin: true },
    height: Math.max(260, sorted.length * 30 + 60),
  }, PC);
}

function renderOffersDistributionChart() {
  const all = (window._offersAllData || []).filter(r => r.status === 'active' && r.revenue > 0);
  if (!all.length) { noChart('chart-off-distribution', 'No data'); return; }
  const sel  = document.getElementById('off-dist-topn');
  const n    = sel ? (sel.value === 'all' ? all.length : parseInt(sel.value, 10)) : 10;
  const top  = all.slice(0, n);
  const rest = all.slice(n).reduce((s, r) => s + r.revenue, 0);
  const labels = [...top.map(r => _fmtOfferName(r.offerName)), ...(rest > 0 ? ['Others'] : [])];
  const values = [...top.map(r => r.revenue),    ...(rest > 0 ? [Math.round(rest * 100) / 100] : [])];
  Plotly.react('chart-off-distribution', [{
    labels, values, type: 'pie', hole: 0.5,
    marker: { colors: labels.map((_, i) => C.palette[i % C.palette.length]), line: { color: '#fff', width: 2 } },
    textinfo: 'percent',
    textfont: { size: 11, family: 'Inter, sans-serif' },
    hovertemplate: '<b>%{label}</b><br>$%{value:,.2f} (%{percent})<extra></extra>',
  }], {
    ...L,
    margin: { t: 16, r: 20, b: 16, l: 20 },
    showlegend: true,
    legend: { orientation: 'v', x: 1.02, y: 0.5, font: { size: 11, color: '#64748b' } },
    height: 340,
  }, PC);
}


// ── Offer Funnel (inside Offers tab) ─────────────────────────────
function _showFunnelEmpty(msg) {
  const empty   = document.getElementById('funnel-empty');
  const content = document.getElementById('funnel-content');
  if (empty)   empty.style.display = '';
  if (content) content.classList.add('d-none');
  if (msg) { const sub = empty?.querySelector('.funnel-empty-sub'); if(sub) sub.innerHTML=msg; }
}

async function loadFunnelData() {
  if (!state.offers.length) { _showFunnelEmpty('Please select an Offer to view the funnel.'); return; }
  loading(true);
  try {
    const data = await api('/api/funnel/data?' + qs());
    if (!data.steps?.length) { _showFunnelEmpty('No goal data found for the selected offer(s).'); return; }
    document.getElementById('funnel-empty').style.display = 'none';
    document.getElementById('funnel-content').classList.remove('d-none');
    const b = document.getElementById('funnel-steps-badge');
    if (b) b.textContent = data.steps.length + ' steps';
    renderFunnelKPIs(data);
    renderFunnelTable(data.steps, data.has_expected || false);
  } catch(e) { _showFunnelEmpty('Could not load funnel data.'); }
  finally { loading(false); }
}



function renderFunnelKPIs(data) {
  const oc=data.overall_rate>=50?C.green:data.overall_rate>=20?C.amber:C.red;
  const dc=data.total_dropoff_pct>=80?C.red:data.total_dropoff_pct>=50?C.amber:C.green;
  const items=[
    {label:'Total Users',value:fmtI(data.total_users),icon:'fa-users',color:C.blue,iconBg:'#eff6ff',iconClr:C.blue,sub:'Entries at step 1'},
    {label:'Final Conv.',value:fmtI(data.final_count),icon:'fa-flag-checkered',color:C.green,iconBg:'#ecfdf5',iconClr:C.green,sub:'Reached last step'},
    {label:'Conv. Rate', value:fmtN(data.overall_rate)+'%',icon:'fa-chart-line',color:oc,iconBg:'#eff6ff',iconClr:oc,sub:'Step 1 → final'},
    {label:'Drop-off',   value:fmtI(data.total_dropoff),icon:'fa-person-walking-arrow-right',color:dc,iconBg:'#fef2f2',iconClr:dc,sub:fmtN(data.total_dropoff_pct)+'% of top-step'},
  ];
  document.getElementById('funnel-kpi-row').innerHTML=items.map(k=>`
    <div class="kpi-card" style="--kpi-color:${k.color}">
      <div class="kpi-top"><div class="kpi-icon" style="background:${k.iconBg};color:${k.iconClr}"><i class="fas ${k.icon}"></i></div></div>
      <div class="kpi-label">${k.label}</div><div class="kpi-value">${k.value}</div>
      <div class="kpi-sub">${k.sub}</div>
    </div>`).join('');
}

let _funnelStepOrder = [];
let _funnelHasExpected = false;
function renderFunnelTable(steps, hasExpected = false) {
  _funnelHasExpected = hasExpected;
  _funnelStepOrder = steps.map(s => ({
    goal: s.goal, count: s.count, time_to_complete: s.time_to_complete || null,
    expected_pct: s.expected_pct ?? null, deviation_pct: s.deviation_pct ?? null,
    expected_time: s.expected_time ?? null,
    funnel_pct: s.funnel_pct ?? null,
  }));
  _drawFunnelTable();
}
function _drawFunnelTable() {
  const steps = _funnelStepOrder;
  const hasExpected = _funnelHasExpected;
  const tbody   = document.getElementById('funnel-table-body');
  const theadEl = document.querySelector('#funnel-main-table thead');
  const noticeEl = document.getElementById('funnel-main-notice');
  if (!tbody) return;

  const topCnt = steps[0]?.count || 1;
  const recalc = steps.map((s, i) => ({
    step: i + 1, goal: s.goal, count: s.count,
    funnel_pct:    s.funnel_pct ?? Math.round(s.count / topCnt * 1000) / 10,
    expected_pct:  s.expected_pct ?? null,
    deviation_pct: s.deviation_pct ?? null,
    expected_time: s.expected_time ?? null,
    time_to_complete: s.time_to_complete || null,
  }));

  const { noticeHtml, theadHtml, tbodyHtml } = _funnelHtml(recalc, hasExpected, { showMoveButtons: true, showBar: true });
  if (noticeEl) noticeEl.innerHTML = noticeHtml;
  if (theadEl)  theadEl.innerHTML  = theadHtml;
  tbody.innerHTML = tbodyHtml;
}
function moveFunnelStep(from, to) {
  if (to < 0 || to >= _funnelStepOrder.length) return;
  const arr = [..._funnelStepOrder];
  const [item] = arr.splice(from, 1);
  arr.splice(to, 0, item);
  _funnelStepOrder = arr;
  _drawFunnelTable();
}

// ══════════════════════════════════════════════════════════════════
//  ANALYTICS PAGE
// ══════════════════════════════════════════════════════════════════

// ── Helpers: contribution bars & winners/losers rows ─────────────

function _renderContribList(containerId, items, labelKey, totalRev, clickFn) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!items.length) { el.innerHTML = '<div class="an-empty">No data</div>'; return; }
  const maxRev = items[0]?.revenue ?? 1;
  el.innerHTML = items.slice(0, 8).map(r => {
    const name    = labelKey === 'partner' ? _partnerLabel(r[labelKey]) : _fmtOfferName(r[labelKey]);
    const pct     = totalRev > 0 ? ((r.revenue / totalRev) * 100).toFixed(1) : '0.0';
    const barW    = totalRev > 0 ? Math.round((r.revenue / totalRev) * 100) : 0;
    const margin  = r.revenue > 0 ? ((r.profit / r.revenue) * 100).toFixed(1) : '0.0';
    const mColor  = parseFloat(margin) >= 20 ? 'var(--green)' : parseFloat(margin) >= 0 ? 'var(--amber)' : 'var(--red)';
    return `<div class="an-contrib-row" onclick="${clickFn}('${esc(r[labelKey])}')" title="${esc(r[labelKey])}">
      <div class="an-contrib-meta">
        <span class="an-contrib-name">${esc(name)}</span>
        <span class="an-contrib-stats">$${fmtN(r.revenue)} · <span style="color:${mColor}">${margin}%</span></span>
      </div>
      <div class="an-contrib-bar-wrap">
        <div class="an-contrib-bar" style="width:${barW}%"></div>
        <span class="an-contrib-pct">${pct}%</span>
      </div>
    </div>`;
  }).join('');
}

function _renderWinLosRows(containerId, items, labelKey, isGainer, clickFn) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!items.length) {
    el.innerHTML = `<div class="an-empty">No ${isGainer ? 'gainers' : 'decliners'} this week</div>`;
    return;
  }
  el.innerHTML = items.map(r => {
    const name         = labelKey === 'partner' ? _partnerLabel(r[labelKey]) : _fmtOfferName(r[labelKey]);
    const dRev         = r.delta_rev   ?? 0;
    const dProfit      = r.delta_profit ?? 0;
    const prevMargin   = r.prev_margin  ?? 0;
    const currMargin   = r.curr_margin  ?? 0;
    const dMargin      = r.delta_margin ?? (currMargin - prevMargin);
    const revSign      = dRev    >= 0 ? '+' : '';
    const profSign     = dProfit >= 0 ? '+' : '';
    const marSign      = dMargin >= 0 ? '+' : '';
    const color        = dRev    >= 0 ? 'var(--green)' : 'var(--red)';
    const profColor    = dProfit >= 0 ? 'var(--green)' : 'var(--red)';
    const marColor     = dMargin >= 0 ? 'var(--green)' : 'var(--red)';
    const icon         = dRev    >= 0 ? 'fa-arrow-up' : 'fa-arrow-down';
    return `<div class="an-wl-row" onclick="${clickFn}('${esc(r[labelKey])}')" title="${esc(r[labelKey])}">
      <span class="an-wl-name">${esc(name)}</span>
      <div class="an-wl-metrics">
        <span class="an-wl-metric" title="Revenue change">
          <span class="an-wl-metric-label">Rev</span>
          <span style="color:${color}"><i class="fas ${icon}" style="font-size:9px"></i> ${revSign}$${fmtN(Math.abs(dRev))}</span>
        </span>
        <span class="an-wl-metric" title="Profit change">
          <span class="an-wl-metric-label">Profit</span>
          <span style="color:${profColor}">${profSign}$${fmtN(Math.abs(dProfit))}</span>
        </span>
        <span class="an-wl-metric" title="Margin change">
          <span class="an-wl-metric-label">Margin</span>
          <span style="color:${marColor}">${prevMargin}% → ${currMargin}% <small>(${marSign}${fmtN(Math.abs(dMargin))}pp)</small></span>
        </span>
      </div>
    </div>`;
  }).join('');
}

function _renderDriverRows(containerId, items, labelKey, isGainer, newSet, clickFn) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!items.length) {
    el.innerHTML = `<div class="an-empty">None this week</div>`;
    return;
  }
  el.innerHTML = items.map(r => {
    const raw   = r[labelKey];
    const name  = labelKey === 'partner' ? _partnerLabel(raw) : _fmtOfferName(raw);
    const delta = r.delta_rev;
    const sign  = delta >= 0 ? '+' : '';
    const color = delta >= 0 ? 'var(--green)' : 'var(--red)';
    const isNew = newSet && newSet.includes(raw);
    return `<div class="an-driver-row" onclick="${clickFn}('${esc(raw)}')" title="${esc(raw)}">
      <div class="an-driver-name-wrap">
        <span class="an-driver-name">${esc(name)}</span>
        ${isNew ? '<span class="an-driver-new-badge">NEW</span>' : ''}
      </div>
      <div class="an-driver-nums">
        <span class="an-driver-delta" style="color:${color}">${sign}$${fmtN(Math.abs(delta))}</span>
        <span class="an-driver-curr">$${fmtN(r.curr_rev)} this wk</span>
      </div>
    </div>`;
  }).join('');
}

function _renderConcentrationBars(containerId, items, labelKey, totalRev) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!items.length) { el.innerHTML = '<div class="an-empty">No data</div>'; return; }
  // Risk thresholds: >40% single entity = high risk, >20% = medium
  el.innerHTML = items.slice(0, 8).map((r, i) => {
    const name  = labelKey === 'partner' ? _partnerLabel(r[labelKey]) : _fmtOfferName(r[labelKey]);
    const pct   = totalRev > 0 ? (r.revenue / totalRev * 100) : 0;
    const pctS  = pct.toFixed(1);
    const barW  = Math.min(Math.round(pct), 100);
    const risk  = pct >= 40 ? 'var(--red)' : pct >= 20 ? 'var(--amber)' : 'var(--green)';
    return `<div class="an-conc-row">
      <div class="an-conc-header">
        <span class="an-conc-name">${esc(name)}</span>
        <span class="an-conc-pct" style="color:${risk}">${pctS}%</span>
      </div>
      <div class="an-conc-track">
        <div class="an-conc-fill" style="width:${barW}%;background:${risk}"></div>
      </div>
    </div>`;
  }).join('');
}

// ── Load: Trend tab (chart + drivers + concentration) ─────────────
async function loadAnalyticsTrend() {
  try {
    console.log('[AN] loadAnalyticsTrend: fetching trend, qs=', qs());
    _perfCompData = await api('/api/overview/trend?' + qs());
    console.log('[AN] trend API returned', _perfCompData?.length, 'rows, first=', _perfCompData?.[0]);
    renderAnalyticsTrend();
  } catch(e) { console.error('[AN] trend fetch error:', e); noChart('chart-an-trend'); }

  // Load drivers & concentration in parallel (non-blocking)
  try {
    const [driversData, lbData] = await Promise.all([
      api('/api/analytics/drivers?' + qs()),
      api('/api/overview/leaderboards?' + qs()),
    ]);
    _renderGrowthDrivers(driversData);
    _renderNewVsExisting(driversData);
    _renderConcentrationFromLeaderboards(lbData);
  } catch(e) { console.error('analytics drivers/concentration:', e); }
}

function _renderGrowthDrivers(d) {
  const period = d.period || {};
  const pEl = document.getElementById('an-drivers-period');
  if (pEl) pEl.textContent = `${period.current || 'This week'} vs ${period.previous || 'last week'} — what moved revenue and why`;

  _renderDriverRows('an-pub-gainers',   d.publishers?.gainers   || [], 'partner',   true,  d.publishers?.new, 'openPublisherProfile');
  _renderDriverRows('an-pub-decliners', d.publishers?.decliners || [], 'partner',   false, null,               'openPublisherProfile');
  _renderDriverRows('an-off-gainers',   d.offers?.gainers       || [], 'offerName', true,  d.offers?.new,      'openOfferProfile');
  _renderDriverRows('an-off-decliners', d.offers?.decliners     || [], 'offerName', false, null,               'openOfferProfile');
}

function _renderNewVsExisting(d) {
  const period = d.period || {};
  const pEl = document.getElementById('an-nve-period');
  if (pEl) pEl.textContent = `${period.current || 'This week'} — are we growing from new business or existing?`;

  function _renderNveBlock(containerId, nve) {
    const el = document.getElementById(containerId);
    if (!el || !nve) return;
    const total    = nve.total_rev || 0;
    const existRev = nve.exist_rev || 0;
    const newRev   = nve.new_rev   || 0;
    const existPct = nve.exist_pct || 0;
    const newPct   = nve.new_pct   || 0;
    if (total === 0) { el.innerHTML = '<div class="an-empty">No data this week</div>'; return; }

    const existW = Math.round(existPct);
    const newW   = Math.round(newPct);

    el.innerHTML = `
      <div class="an-nve-bar-row">
        ${existW > 0 ? `<div class="an-nve-bar-seg an-nve-exist" style="width:${existW}%" title="Existing: $${fmtN(existRev)} (${existPct}%)"></div>` : ''}
        ${newW   > 0 ? `<div class="an-nve-bar-seg an-nve-new"   style="width:${newW}%"   title="New: $${fmtN(newRev)} (${newPct}%)"></div>` : ''}
      </div>
      <div class="an-nve-legend">
        <div class="an-nve-legend-item">
          <span class="an-nve-dot an-nve-dot-exist"></span>
          <div>
            <div class="an-nve-legend-label">Existing</div>
            <div class="an-nve-legend-val">$${fmtN(existRev)} <span class="an-nve-legend-pct">${existPct}%</span></div>
          </div>
        </div>
        <div class="an-nve-legend-item">
          <span class="an-nve-dot an-nve-dot-new"></span>
          <div>
            <div class="an-nve-legend-label">New</div>
            <div class="an-nve-legend-val">$${fmtN(newRev)} <span class="an-nve-legend-pct">${newPct}%</span></div>
          </div>
        </div>
      </div>`;
  }

  _renderNveBlock('an-nve-publishers', d.publishers?.new_vs_existing);
  _renderNveBlock('an-nve-offers',     d.offers?.new_vs_existing);
}

function _renderConcentrationFromLeaderboards(lb) {
  const pubs   = lb.publishers || [];
  const offs   = lb.offers     || [];
  const pubRev = pubs.reduce((s, r) => s + r.revenue, 0);
  const offRev = offs.reduce((s, r) => s + r.revenue, 0);
  _renderConcentrationBars('an-conc-pubs',   pubs, 'partner',   pubRev);
  _renderConcentrationBars('an-conc-offers', offs, 'offerName', offRev);
}

function setPerfChartType(btn, type) {
  _perfChartType = type;
  document.querySelectorAll('#an-tab-trend .trend-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.ctype === type));
  renderAnalyticsTrend();
}

function renderAnalyticsTrend() {
  const data = _perfCompData;
  console.log('[AN] renderAnalyticsTrend: rows=', data?.length);
  if (!data || !data.length) { noChart('chart-an-trend', 'No data for selected range'); return; }

  const metricMap = {
    revenue:    { label: 'Revenue',  color: C.blue,   prefix: '$', suffix: '',  axis: 'y1' },
    cost:       { label: 'Cost',     color: C.red,    prefix: '$', suffix: '',  axis: 'y1' },
    profit:     { label: 'Profit',   color: C.green,  prefix: '$', suffix: '',  axis: 'y1' },
    margin_pct: { label: 'Margin %', color: C.teal,   prefix: '',  suffix: '%', axis: 'y2' },
    installs:   { label: 'Conversions', color: C.purple || '#a855f7', prefix: '', suffix: '', axis: 'y3' },
  };
  const checked = Array.from(
    document.querySelectorAll('#perf-metric-pills input[type="checkbox"]:checked')
  ).map(el => el.value);
  console.log('[AN] checked metrics=', checked, 'first data row keys=', data[0] ? Object.keys(data[0]) : 'none');
  if (!checked.length) { noChart('chart-an-trend', 'Select at least one metric'); return; }

  // Fix restore bug: clear innerHTML if no Plotly chart is attached
  const chartEl = document.getElementById('chart-an-trend');
  if (chartEl && !chartEl._fullData) chartEl.innerHTML = '';

  const dates = data.map(r => r.date);
  const ctype = _perfChartType;

  const hasCurrency  = checked.some(k => k !== 'margin_pct' && k !== 'installs');
  const hasPct       = checked.includes('margin_pct');
  const hasInstalls  = checked.includes('installs');

  const traces = checked.map(key => {
    const m   = metricMap[key] || { label: key, color: C.blue, prefix: '', suffix: '', axis: 'y1' };
    const yv  = data.map(r => r[key] ?? 0);
    const fmt = m.suffix === '%' ? '.2f' : ',.0f';
    const base = {
      x: dates, y: yv, name: m.label,
      marker: { color: m.color },
      hovertemplate: `<b>%{x}</b><br>${m.label}: ${m.prefix}%{y:${fmt}}${m.suffix}<extra></extra>`,
    };
    if (key === 'margin_pct') base.yaxis = 'y2';
    if (key === 'installs')   base.yaxis = 'y3';

    if (ctype === 'bar') return { ...base, type: 'bar', opacity: 0.82 };
    if (ctype === 'area') return {
      ...base, type: 'scatter', mode: 'lines+markers',
      line: { color: m.color, width: 2.5, shape: 'spline' },
      fill: 'tozeroy', fillcolor: m.color.replace(')', ',0.08)').replace('rgb', 'rgba'),
      marker: { size: 4, color: m.color },
    };
    return {
      ...base, type: 'scatter', mode: 'lines+markers',
      line: { color: m.color, width: 2.5, shape: 'spline' },
      marker: { size: 4, color: m.color },
    };
  });

  const rightMargin = (hasPct ? 60 : 0) + (hasInstalls ? 60 : 0) || 16;
  const layout = {
    ...L,
    barmode: 'group',
    xaxis: { ...L.xaxis, type: 'date', tickformat: '%b %d', tickangle: -30, automargin: true },
    yaxis: { ...L.yaxis,
      ...(hasCurrency ? { tickprefix: '$', tickformat: ',.0s' } : (hasPct ? { ticksuffix: '%' } : {})),
      rangemode: 'tozero',
    },
    ...(hasPct ? { yaxis2: {
      ...L.yaxis, overlaying: 'y', side: 'right', ticksuffix: '%',
      showgrid: false, rangemode: 'normal', tickfont: { size: 11, color: C.teal },
      anchor: 'x',
    }} : {}),
    ...(hasInstalls ? { yaxis3: {
      ...L.yaxis, overlaying: 'y', side: 'right',
      showgrid: false, rangemode: 'tozero', tickfont: { size: 11, color: '#a855f7' },
      anchor: 'free', position: hasPct ? 0.97 : 1.0,
      tickformat: ',.0f',
    }} : {}),
    legend: { ...L.legend, orientation: 'h', y: -0.22, x: 0 },
    hovermode: 'x unified',
    margin: { t: 10, r: rightMargin, b: 72, l: 85 },
  };

  Plotly.react('chart-an-trend', traces, layout, PC);
}

// ── Load: Weekly tab ─────────────────────────────────────────────
async function loadAnalyticsWeekly() {
  try {
    const [weekly, drivers, lb] = await Promise.all([
      api('/api/analytics/weekly?'+qs()),
      api('/api/analytics/drivers?'+qs()),
      api('/api/overview/leaderboards?'+qs()),
    ]);
    const weeks = weekly.weeks || [];
    if (!weeks.length) { noChart('chart-an-weekly-rev'); noChart('chart-an-weekly-wow'); }
    else {
      const labels = weeks.map(w=>w.week);
      try {
        Plotly.newPlot('chart-an-weekly-rev',[
          {x:labels,y:weeks.map(w=>w.revenue),mode:'lines+markers',name:'Revenue',line:{color:C.blue,width:2.5,shape:'spline'},marker:{size:5},fill:'tozeroy',fillcolor:'rgba(59,130,246,0.07)'},
          {x:labels,y:weeks.map(w=>w.profit), mode:'lines+markers',name:'Profit', line:{color:C.green,width:2,dash:'dash',shape:'spline'},marker:{size:4}},
          {x:labels,y:weeks.map(w=>w.cost),   mode:'lines',         name:'Cost',  line:{color:C.red,width:2,dash:'dot',shape:'spline'}},
        ],{...L,yaxis:{...L.yaxis,tickprefix:'$',tickformat:',.0f'},legend:{...L.legend,orientation:'h',y:-0.18,x:0},hovermode:'x unified',margin:{t:10,r:16,b:56,l:85}},PC);
      } catch(ce) { noChart('chart-an-weekly-rev'); }
      try {
        Plotly.newPlot('chart-an-weekly-wow',[{
          x:labels,y:weeks.map(w=>w.wow_revenue_pct??0),type:'bar',name:'WoW Revenue %',
          marker:{color:weeks.map(w=>(w.wow_revenue_pct??0)>=0?C.green:C.red),opacity:0.85},
          text:weeks.map(w=>w.wow_revenue_pct!=null?fmtN(w.wow_revenue_pct)+'%':'—'),
          textposition:'outside',textfont:{size:11,color:'#64748b'},cliponaxis:false,
        }],{...L,yaxis:{...L.yaxis,ticksuffix:'%'},bargap:0.3,margin:{t:30,r:20,b:56,l:70}},PC);
      } catch(ce) { noChart('chart-an-weekly-wow'); }

      // Simplified table: hide leading zero rows (before any activity started)
      let weeksActive = false;
      const weeksFiltered = weeks.filter(w => { if (w.revenue > 0 || w.cost > 0) weeksActive = true; return weeksActive; });
      const weeksToRender = weeksFiltered.length ? weeksFiltered : weeks.slice(-4);
      document.getElementById('an-weekly-body').innerHTML = weeksToRender.map(w=>`<tr>
        <td style="font-weight:600">${esc(w.week)}<br><span style="font-size:11px;color:#94a3b8;font-weight:400">${esc(w.period)}</span></td>
        <td class="td-num rev">$${fmtN(w.revenue)}</td>
        <td class="td-num" style="color:${w.profit>=0?C.green:C.red};font-weight:600">$${fmtN(w.profit)}</td>
        <td class="td-num">${fmtN(w.margin_pct)}%</td>
        <td class="td-num">${fmtI(w.conversions)}</td>
        <td class="td-num">${trendChip(w.wow_revenue_pct)}</td>
      </tr>`).join('');
    }

    // Winners & Losers (use drivers data, merged pub+offer)
    const wlPeriod = drivers.period || {};
    const wlPEl = document.getElementById('an-wl-period');
    if (wlPEl) wlPEl.textContent = `${wlPeriod.current || 'This week'} vs ${wlPeriod.previous || 'last week'}`;

    // Merge publishers + offers into a single ranked list
    const gainers   = [
      ...(drivers.publishers?.gainers   || []).map(r => ({...r, _type:'pub',   _key:'partner'})),
      ...(drivers.offers?.gainers       || []).map(r => ({...r, _type:'offer', _key:'offerName'})),
    ].sort((a,b) => b.delta_rev - a.delta_rev).slice(0, 6);
    const decliners = [
      ...(drivers.publishers?.decliners || []).map(r => ({...r, _type:'pub',   _key:'partner'})),
      ...(drivers.offers?.decliners     || []).map(r => ({...r, _type:'offer', _key:'offerName'})),
    ].sort((a,b) => a.delta_rev - b.delta_rev).slice(0, 6);

    function _wlRow(r) {
      const isPub      = r._type === 'pub';
      const name       = isPub ? _partnerLabel(r.partner) : _fmtOfferName(r.offerName);
      const raw        = isPub ? r.partner : r.offerName;
      const fn         = isPub ? 'openPublisherProfile' : 'openOfferProfile';
      const dRev       = r.delta_rev    ?? 0;
      const dProfit    = r.delta_profit ?? 0;
      const prevMargin = r.prev_margin  ?? 0;
      const currMargin = r.curr_margin  ?? 0;
      const dMargin    = r.delta_margin ?? (currMargin - prevMargin);
      const revSign    = dRev    >= 0 ? '+' : '';
      const profSign   = dProfit >= 0 ? '+' : '';
      const marSign    = dMargin >= 0 ? '+' : '';
      const revColor   = dRev    >= 0 ? 'var(--green)' : 'var(--red)';
      const profColor  = dProfit >= 0 ? 'var(--green)' : 'var(--red)';
      const marColor   = dMargin >= 0 ? 'var(--green)' : 'var(--red)';
      const icon       = dRev    >= 0 ? 'fa-arrow-up'  : 'fa-arrow-down';
      const badge      = isPub
        ? `<span class="an-wl-badge an-wl-badge-pub">Publisher</span>`
        : `<span class="an-wl-badge an-wl-badge-offer">Offer</span>`;
      return `<div class="an-wl-row" onclick="${fn}('${esc(raw)}')" title="${esc(raw)}">
        <div class="an-wl-top"><span class="an-wl-name">${esc(name)}</span>${badge}</div>
        <div class="an-wl-metrics">
          <span class="an-wl-metric">
            <span class="an-wl-metric-label">Rev</span>
            <span style="color:${revColor}"><i class="fas ${icon}" style="font-size:9px"></i> ${revSign}$${fmtN(Math.abs(dRev))}</span>
          </span>
          <span class="an-wl-metric">
            <span class="an-wl-metric-label">Profit</span>
            <span style="color:${profColor}">${profSign}$${fmtN(Math.abs(dProfit))}</span>
          </span>
          <span class="an-wl-metric">
            <span class="an-wl-metric-label">Margin</span>
            <span style="color:${marColor}">${prevMargin}% → ${currMargin}% <small>(${marSign}${fmtN(Math.abs(dMargin))}pp)</small></span>
          </span>
        </div>
      </div>`;
    }

    const gainEl = document.getElementById('an-wl-gainers');
    const decEl  = document.getElementById('an-wl-decliners');
    if (gainEl) gainEl.innerHTML = gainers.length  ? gainers.map(_wlRow).join('')   : '<div class="an-empty">No gainers this week</div>';
    if (decEl)  decEl.innerHTML  = decliners.length ? decliners.map(_wlRow).join('') : '<div class="an-empty">No decliners this week</div>';

    // Publisher & Offer Contribution
    const pubs   = lb.publishers || [];
    const offs   = lb.offers     || [];
    const pubRev = pubs.reduce((s, r) => s + r.revenue, 0);
    const offRev = offs.reduce((s, r) => s + r.revenue, 0);
    _renderContribList('an-contrib-pubs',   pubs, 'partner',   pubRev, 'openPublisherProfile');
    _renderContribList('an-contrib-offers', offs, 'offerName', offRev, 'openOfferProfile');

  } catch(e) { console.error('analytics weekly:', e); }
}

// ── Load: Monthly tab ─────────────────────────────────────────────
async function loadAnalyticsMonthly() {
  try {
    const d = await api('/api/analytics/monthly?'+qs());
    const months = d.months || [];
    if (!months.length) { noChart('chart-an-monthly-rev'); noChart('chart-an-monthly-mom'); return; }
    const labels = months.map(m=>m.month);
    try {
      Plotly.newPlot('chart-an-monthly-rev',[
        {x:labels,y:months.map(m=>m.revenue),mode:'lines+markers',name:'Revenue',line:{color:C.blue,width:2.5,shape:'spline'},fill:'tozeroy',fillcolor:'rgba(59,130,246,0.07)'},
        {x:labels,y:months.map(m=>m.profit), mode:'lines+markers',name:'Profit', line:{color:C.green,width:2,dash:'dash',shape:'spline'}},
        {x:labels,y:months.map(m=>m.cost),   mode:'lines',         name:'Cost',  line:{color:C.red,width:2,dash:'dot',shape:'spline'}},
      ],{...L,yaxis:{...L.yaxis,tickprefix:'$',tickformat:',.0f'},legend:{...L.legend,orientation:'h',y:-0.18,x:0},hovermode:'x unified',margin:{t:10,r:16,b:56,l:85}},PC);
    } catch(ce) { noChart('chart-an-monthly-rev'); }
    try {
      Plotly.newPlot('chart-an-monthly-mom',[{
        x:labels,y:months.map(m=>m.mom_revenue_pct??0),type:'bar',name:'MoM Revenue %',
        marker:{color:months.map(m=>(m.mom_revenue_pct??0)>=0?C.green:C.red),opacity:0.85},
        text:months.map(m=>m.mom_revenue_pct!=null?fmtN(m.mom_revenue_pct)+'%':'—'),
        textposition:'outside',textfont:{size:11,color:'#64748b'},cliponaxis:false,
      }],{...L,yaxis:{...L.yaxis,ticksuffix:'%'},bargap:0.3,margin:{t:30,r:20,b:56,l:70}},PC);
    } catch(ce) { noChart('chart-an-monthly-mom'); }

    // Simplified table: hide leading zero months (before any activity started)
    let monthsActive = false;
    const monthsFiltered = months.filter(m => { if (m.revenue > 0 || m.cost > 0) monthsActive = true; return monthsActive; });
    const monthsToRender = monthsFiltered.length ? monthsFiltered : months.slice(-3);
    document.getElementById('an-monthly-body').innerHTML = monthsToRender.map(m=>`<tr>
      <td style="font-weight:600">${esc(m.month)}</td>
      <td class="td-num rev">$${fmtN(m.revenue)}</td>
      <td class="td-num" style="color:${m.profit>=0?C.green:C.red};font-weight:600">$${fmtN(m.profit)}</td>
      <td class="td-num">${fmtN(m.margin_pct)}%</td>
      <td class="td-num">${fmtI(m.conversions)}</td>
      <td class="td-num">${trendChip(m.mom_revenue_pct)}</td>
    </tr>`).join('');
  } catch(e) { console.error('analytics monthly:', e); }
}

// ── Mobile sidebar ────────────────────────────────────────────────
// Desktop: click-toggle collapse/expand
function toggleSidebar() {
  if (window.innerWidth <= 768) {
    // Mobile: slide in/out
    document.getElementById('sidebar').classList.toggle('open');
    document.getElementById('sb-overlay').classList.toggle('open');
    return;
  }
  const sidebar  = document.getElementById('sidebar');
  const shell    = document.querySelector('.shell');
  const chev     = document.getElementById('sb-chevron');
  const tog      = document.getElementById('sb-toggle');
  const isCollapsed = sidebar.classList.toggle('collapsed');
  if (shell) shell.classList.toggle('sb-collapsed', isCollapsed);
  if (chev)  chev.className = isCollapsed ? 'fas fa-chevron-right' : 'fas fa-chevron-left';
  if (tog)   tog.style.left = isCollapsed ? '44px' : 'calc(var(--sb-w) - 12px)';
  localStorage.setItem('sb_collapsed', isCollapsed ? '1' : '0');
}

function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sb-overlay').classList.remove('open');
}

function toggleGroup(id) {
  const items = document.getElementById(id);
  const chev  = document.getElementById('gc-' + id);
  if (!items) return;
  const isOpen = !items.classList.contains('sb-group-collapsed');
  items.classList.toggle('sb-group-collapsed', isOpen);
  if (chev) chev.className = `fas fa-chevron-${isOpen ? 'right' : 'down'} sb-g-chev sb-label`;
  localStorage.setItem('sb_grp_' + id, isOpen ? '0' : '1');
}

function initSidebar() {
  // Restore group open/closed states
  ['g-overview', 'g-analyse', 'g-system'].forEach(id => {
    if (localStorage.getItem('sb_grp_' + id) === '0') {
      const items = document.getElementById(id);
      const chev  = document.getElementById('gc-' + id);
      if (items) items.classList.add('sb-group-collapsed');
      if (chev)  chev.className = 'fas fa-chevron-right sb-g-chev sb-label';
    }
  });
  // Restore sidebar collapsed state (desktop only)
  if (window.innerWidth > 768 && localStorage.getItem('sb_collapsed') === '1') {
    const sidebar = document.getElementById('sidebar');
    const shell   = document.querySelector('.shell');
    const chev    = document.getElementById('sb-chevron');
    const tog     = document.getElementById('sb-toggle');
    if (sidebar) sidebar.classList.add('collapsed');
    if (shell)   shell.classList.add('sb-collapsed');
    if (chev)    chev.className = 'fas fa-chevron-right';
    if (tog)     tog.style.left = '44px';
  }
}

// ── Init ──────────────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════
//  GLOBAL ALERT BELL + DRAWER
// ══════════════════════════════════════════════════════════════════

let _alertDrawerOpen = false;

function toggleAlertDrawer() {
  _alertDrawerOpen ? closeAlertDrawer() : openAlertDrawer();
}

function openAlertDrawer() {
  _alertDrawerOpen = true;
  document.getElementById('alert-drawer').classList.add('open');
  document.getElementById('alert-drawer-overlay').classList.add('open');
}

function closeAlertDrawer() {
  _alertDrawerOpen = false;
  document.getElementById('alert-drawer').classList.remove('open');
  document.getElementById('alert-drawer-overlay').classList.remove('open');
}

async function loadGlobalAlerts() {
  try {
    const data = await api('/api/overview/alerts');
    const alerts = data.alerts || [];
    const count = alerts.length;

    // Update bell badge
    const badge = document.getElementById('alert-bell-badge');
    if (badge) {
      badge.textContent = count > 99 ? '99+' : count;
      badge.style.display = count > 0 ? 'flex' : 'none';
    }

    // Update bell icon colour to red when criticals exist
    const bell = document.getElementById('btn-alert-bell');
    const hasCritical = alerts.some(a => a.severity === 'critical');
    if (bell) bell.style.color = hasCritical ? 'var(--red)' : '';

    // Populate drawer body (reuses hc-alert-* CSS)
    const body = document.getElementById('alert-drawer-body');
    if (!body) return;

    if (!count) {
      body.innerHTML = `<div class="hc-no-alerts">
        <i class="fas fa-circle-check" style="font-size:20px;margin-bottom:6px;display:block"></i>
        No active alerts
      </div>`;
      return;
    }

    const severityOrder = { critical: 0, warning: 1, info: 2 };
    const sorted = [...alerts].sort((a, b) =>
      (severityOrder[a.severity] ?? 9) - (severityOrder[b.severity] ?? 9));

    body.innerHTML = `<div class="hc-alert-list">${sorted.map(a => {
      const icon = a.severity === 'critical' ? 'fa-circle-xmark' : 'fa-triangle-exclamation';
      const offerLink = a.offer
        ? `<div class="hc-alert-sub" style="cursor:pointer;text-decoration:underline;text-underline-offset:2px"
                onclick="closeAlertDrawer();openOfferProfile('${esc(a.offer)}')">${esc(a.offer)}</div>`
        : '';
      return `<div class="hc-alert-item sev-${a.severity}">
        <i class="fas ${icon} hc-alert-icon"></i>
        <div>
          <div class="hc-alert-msg">${esc(a.message)}</div>
          ${offerLink}
        </div>
      </div>`;
    }).join('')}</div>`;
  } catch(e) {
    console.warn('global alerts:', e);
  }
}

async function init() {
  // Guard: Plotly must be loaded from CDN before any chart renders
  if (typeof Plotly === 'undefined') {
    console.error('FATAL: Plotly failed to load from CDN. Charts will not render. Check network connectivity or CDN availability.');
    // Banner in each chart container so it's visible in the UI
    document.querySelectorAll('.chart-container, [id^="chart-"]').forEach(el => {
      el.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#ef4444;font-size:13px;padding:16px;text-align:center"><i class="fas fa-exclamation-triangle" style="margin-right:6px"></i>Chart library failed to load. Please check your internet connection and refresh.</div>';
    });
  }

  const body = document.body;
  state.from_date = body.dataset.defaultFrom;
  state.to_date   = body.dataset.defaultTo;

  // ── Sidebar: restore collapsed state from localStorage ──────────────────
  initSidebar();

  tsPartner = makeTomSelect('filter-partner', () => { if (!_cascadeInProgress) cascadeFilters(); });
  tsOffer   = makeTomSelect('filter-offer',   () => { if (!_cascadeInProgress) cascadeFilters(); });

  document.getElementById('from-date').addEventListener('change', onDateChange);
  document.getElementById('to-date').addEventListener('change', onDateChange);

  const hash = location.hash.replace('#','');
  const initPage = PAGES[hash] ? hash : 'overview';
  document.querySelectorAll('.sb-item').forEach(el =>
    el.classList.toggle('active', el.dataset.page === initPage));
  document.querySelectorAll('.page').forEach(el =>
    el.classList.toggle('active', el.id === `page-${initPage}`));
  state.page = initPage;
  document.getElementById('tb-page-name').textContent = PAGES[initPage];
  updateDateBadge();

  await loadStatus();

  // Load partner name map + offer ID map before populating filter
  try {
    const mapData = await api('/api/publishers/map');
    window._partnerMap = mapData || {};
  } catch(e) { console.warn('partner map load:', e); }
  try {
    const offerMapData = await api('/api/offers/map');
    window._offerMap = offerMapData || {};
  } catch(e) { console.warn('offer map load:', e); }

  _cascadeInProgress = true;
  try {
    syncState();
    const data = await api('/api/filters?'+qs());
    populateTS(tsPartner, data.partners, state.partners, _partnerLabel);
    populateTS(tsOffer,   data.offers,   state.offers);
    updateDateBadge();
  } catch(e) { console.warn('init cascade:', e); }
  finally { _cascadeInProgress = false; }

  loading(true);
  try { await loadPageData(initPage); }
  finally { loading(false); }

  // Load global alerts after page renders (non-blocking)
  loadGlobalAlerts();
}

// ══════════════════════════════════════════════════════════════════
//  ADMINISTRATION PAGE
// ══════════════════════════════════════════════════════════════════

let _syncPollTimer = null;

async function loadAdministration() {
  // Default sync dates to MTD (only if not already set)
  const today = new Date();
  const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1);
  const fmt = d => d.toISOString().slice(0,10);
  const sfEl = document.getElementById('sync-from-date');
  const stEl = document.getElementById('sync-to-date');
  if (sfEl && !sfEl.value) sfEl.value = fmt(firstOfMonth);
  if (stEl && !stEl.value) stEl.value = fmt(today);

  // Load sync publisher preview
  try {
    const pubs = await api('/api/management/publishers');
    const list  = document.getElementById('sync-pub-list');
    const badge = document.getElementById('sync-pub-count');
    if (badge) badge.textContent = pubs.length + ' publishers';
    if (list) {
      if (!pubs.length) {
        list.innerHTML = '<span style="color:var(--amber);font-size:13px;font-weight:600"><i class="fas fa-warning" style="margin-right:4px"></i>No publishers configured — go to Administration → Publishers first</span>';
      } else {
        list.innerHTML = pubs.map(p =>
          `<span class="pub-chip">${esc(p.partner_name ? `${p.partner_name} (${p.publisher_id})` : p.publisher_id)}</span>`
        ).join('');
      }
    }
  } catch(e) { console.error('admin sync preview:', e); }

  // Resume polling if sync already running
  try {
    const status = await fetch('/api/sync/status').then(r => r.json());
    if (status.running || status.finished) {
      const card = document.getElementById('sync-progress-card');
      if (card) card.style.display = '';
      _renderSyncState(status);
      if (status.running) {
        clearTimeout(_syncPollTimer);
        _syncPoll();
      }
      const btn = document.getElementById('btn-start-sync');
      if (btn) {
        btn.disabled = status.running;
        if (status.running) btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Syncing…';
      }
    }
  } catch(e) { /* ignore */ }
}

async function startSync() {
  const from = document.getElementById('sync-from-date')?.value;
  const to   = document.getElementById('sync-to-date')?.value;
  if (!from || !to) { alert('Please set both From and To dates.'); return; }
  if (from > to)    { alert('From date must be ≤ To date.');       return; }

  const btn = document.getElementById('btn-start-sync');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Starting…'; }

  const r = await fetch('/api/sync/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ from_date: from, to_date: to }),
  });
  const data = await r.json();

  if (!r.ok) {
    const msg = data.error === 'no_publishers'
      ? '⚠ No publishers configured.\n\nGo to Administration → Publishers and add at least one Publisher ID before syncing.'
      : (data.message || data.error || 'Sync failed to start');
    alert(msg);
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-play"></i> Start Sync'; }
    return;
  }

  // Show progress card
  const card = document.getElementById('sync-progress-card');
  if (card) card.style.display = '';
  _syncPoll();
}

function _syncPoll() {
  clearTimeout(_syncPollTimer);
  fetch('/api/sync/status')
    .then(r => r.json())
    .then(s => {
      _renderSyncState(s);
      if (s.running) {
        _syncPollTimer = setTimeout(_syncPoll, 2000);
      } else {
        // Re-enable button
        const btn = document.getElementById('btn-start-sync');
        if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-play"></i> Start Sync'; }
      }
    })
    .catch(() => { _syncPollTimer = setTimeout(_syncPoll, 3000); });
}

function _renderSyncState(s) {
  const title = document.getElementById('sync-progress-title');
  const sub   = document.getElementById('sync-progress-sub');
  const fill  = document.getElementById('sync-progress-fill');
  const log   = document.getElementById('sync-log');

  const pct = s.total > 0 ? Math.round(s.progress / s.total * 100) : 0;
  if (fill) fill.style.width = pct + '%';

  const statusLabel = s.running ? 'Syncing…'
                    : s.error   ? 'Sync Failed'
                    : 'Sync Complete';
  if (title) {
    title.textContent = statusLabel;
    title.style.color = s.error ? 'var(--red)' : s.finished && !s.error ? 'var(--green)' : '';
  }

  const activeDates = s.active_dates || {};
  const activeKeys  = Object.keys(activeDates);
  let subText = s.total > 0 ? `${s.progress} / ${s.total} days complete` : '';
  if (activeKeys.length) {
    const pageInfos = activeKeys.map(d => {
      const ad = activeDates[d];
      const pg = ad.pages_total > 0
        ? `${d} · ${ad.pages_done}/${ad.pages_total} pages · ${fmtI(ad.rows)} rows`
        : `${d} · probing…`;
      return pg;
    });
    subText += (subText ? '   |   ' : '') + pageInfos.join('   |   ');
  }
  if (sub) sub.textContent = subText;

  // Log rendering
  if (log && s.log?.length) {
    log.innerHTML = s.log.map(line => {
      const cls = (line.startsWith('✓') || line.toLowerCase().includes('complete'))
                    ? 'log-ok'
                : (line.startsWith('✗') || line.toLowerCase().includes('error')
                    || line.toLowerCase().includes('failed'))
                    ? 'log-err'
                : 'log-info';
      return `<span class="${cls}">${esc(line)}</span>`;
    }).join('\n');
    log.scrollTop = log.scrollHeight;
  }

  // Show summary card when finished
  if (s.finished && s.summary && Object.keys(s.summary).length) {
    _renderSyncSummary(s.summary, !!s.error);
  }
}

function _renderSyncSummary(sm, isError) {
  const card   = document.getElementById('sync-summary-card');
  const kpis   = document.getElementById('sync-summary-kpis');
  const tbody  = document.getElementById('sync-summary-body');
  const stitle = document.getElementById('sync-summary-title');
  if (!card) return;

  card.style.display = '';
  if (stitle) {
    if (isError) {
      stitle.innerHTML = '<i class="fas fa-circle-xmark" style="margin-right:6px;color:var(--red)"></i><span style="color:var(--red)">Sync Failed — Partial Results</span>';
    } else {
      stitle.innerHTML = '<i class="fas fa-circle-check" style="margin-right:6px"></i>Sync Complete';
    }
  }

  // KPI cards
  const dur = sm.duration_str || (sm.duration_seconds ? `${sm.duration_seconds}s` : '—');
  const kpiItems = [
    { label:'Downloaded', value:fmtI(sm.rows_downloaded), icon:'fa-cloud-arrow-down', color:C.blue,   iconBg:'#eff6ff', iconClr:C.blue   },
    { label:'Inserted',   value:fmtI(sm.rows_inserted),   icon:'fa-plus-circle',      color:C.green,  iconBg:'#ecfdf5', iconClr:C.green  },
    { label:'Updated',    value:fmtI(sm.rows_updated),    icon:'fa-arrows-rotate',    color:C.amber,  iconBg:'#fffbeb', iconClr:'#d97706'},
    { label:'Skipped',    value:fmtI(sm.rows_skipped),    icon:'fa-ban',              color:C.purple, iconBg:'#f5f3ff', iconClr:C.purple },
  ];
  if (kpis) {
    kpis.innerHTML = kpiItems.map(k => `
      <div class="kpi-card" style="--kpi-color:${k.color}">
        <div class="kpi-top"><div class="kpi-icon" style="background:${k.iconBg};color:${k.iconClr}"><i class="fas ${k.icon}"></i></div></div>
        <div class="kpi-label">${k.label}</div>
        <div class="kpi-value" style="font-size:22px">${k.value}</div>
      </div>`).join('');
  }

  // Detail table
  if (tbody) {
    const rows = [
      ['Dates Processed', fmtI(sm.dates_processed)],
      ['Publishers',      fmtI(sm.publishers) || '—'],
      ['Rows Downloaded', fmtI(sm.rows_downloaded)],
      ['Rows Inserted',   fmtI(sm.rows_inserted)],
      ['Rows Updated',    fmtI(sm.rows_updated)],
      ['Rows Skipped (Duplicates)', fmtI(sm.rows_skipped)],
      ['Duration',        dur],
    ];
    tbody.innerHTML = rows.map(([label, val]) =>
      `<tr>
        <td style="font-weight:600;color:var(--txt-head);padding:8px 16px;width:240px">${label}</td>
        <td style="padding:8px 16px;color:var(--txt-body)">${val}</td>
      </tr>`
    ).join('');
  }
}

async function clearDatabase() {
  // Step 1: ask for typed confirmation
  const token = window.prompt(
    'This will permanently delete ALL synced data.\n\nType DELETE to confirm:'
  );
  if (token === null) return;                   // user clicked Cancel
  if (token !== 'DELETE') {
    alert('Incorrect confirmation — database was NOT cleared.\nYou must type exactly: DELETE');
    return;
  }

  const btn = document.getElementById('btn-clear-db');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Clearing…'; }

  try {
    const r    = await fetch('/api/sync/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: 'DELETE' }),
    });
    const data = await r.json();
    if (r.ok) {
      // Hide summary card (stale after clear)
      const sc = document.getElementById('sync-summary-card');
      if (sc) sc.style.display = 'none';
      const pc = document.getElementById('sync-progress-card');
      if (pc) pc.style.display = 'none';
      alert(`✓ Database cleared — ${data.files_deleted} file(s) deleted.`);
    } else {
      alert('Error: ' + (data.error || 'Failed to clear database'));
    }
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-trash"></i> Clear Database'; }
  }
}

// ══════════════════════════════════════════════════════════════════
//  MANAGEMENT PAGE — PUBLISHERS  (ID + Name only — sync source)
// ══════════════════════════════════════════════════════════════════

function _pubFormClear() {
  ['publisher_id','partner_name'].forEach(k => {
    const el = document.getElementById('pub-f-' + k);
    if (el) el.value = '';
  });
  const en = document.getElementById('pub-f-enabled');
  if (en) en.checked = true;
}

async function loadPubList() {
  try {
    const pubs  = await api('/api/management/publishers');
    const badge = document.getElementById('pub-table-count');
    if (badge) badge.textContent = pubs.length + ' publishers';
    api('/api/publishers/map').then(m => { window._partnerMap = m || {}; }).catch(()=>{});

    document.getElementById('pub-list-body').innerHTML = pubs.length ? pubs.map(p => {
      const enabled = p.enabled !== false;
      const statusBadge = enabled
        ? `<span class="pub-status-badge pub-status-active">Active</span>`
        : `<span class="pub-status-badge pub-status-paused">Paused</span>`;
      const toggleLabel = enabled ? 'Pause' : 'Activate';
      return `
      <tr class="${enabled ? '' : 'pub-row-paused'}">
        <td style="font-weight:600;font-size:13px">${esc(p.publisher_id)}</td>
        <td style="font-weight:500">${esc(p.partner_name || '—')}</td>
        <td class="td-center">${statusBadge}</td>
        <td class="td-center" style="white-space:nowrap">
          <button class="tbl-btn tbl-btn-edit"   onclick="editPub('${p.id}')">Edit</button>
          <button class="tbl-btn tbl-btn-toggle" onclick="togglePubEnabled('${p.id}', ${enabled})">${toggleLabel}</button>
          <button class="tbl-btn tbl-btn-del"    onclick="deletePub('${p.id}')">Del</button>
        </td>
      </tr>`;
    }).join('')
      : `<tr><td colspan="4" class="td-empty"><div class="empty-state"><i class="fas fa-handshake empty-icon"></i><p>No publishers yet — add one above</p></div></td></tr>`;
    _loaded.delete('administration:sync');
  } catch(e) { console.error('pub list:', e); }
}

async function savePub() {
  const editId       = document.getElementById('pub-edit-id')?.value;
  const publisher_id = document.getElementById('pub-f-publisher_id')?.value.trim();
  const partner_name = document.getElementById('pub-f-partner_name')?.value.trim();
  const enabled      = document.getElementById('pub-f-enabled')?.checked ?? true;
  if (!publisher_id) { alert('Publisher ID is required'); return; }
  if (!partner_name) { alert('Partner Name is required'); return; }

  const payload = { publisher_id, partner_name, enabled };
  const url     = editId ? `/api/management/publishers/${editId}` : '/api/management/publishers';
  const method  = editId ? 'PUT' : 'POST';
  const r = await fetch(url, { method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  if (!r.ok) { const d=await r.json(); alert(d.error||'Save failed'); return; }
  cancelPubEdit();
  _loaded.delete('administration:publishers');
  await loadPubList();
}

async function editPub(id) {
  const pubs = await api('/api/management/publishers');
  const p = pubs.find(x => x.id === id);
  if (!p) return;

  document.getElementById('pub-edit-id').value            = id;
  document.getElementById('pub-f-publisher_id').value     = p.publisher_id || '';
  document.getElementById('pub-f-partner_name').value     = p.partner_name || '';
  const en = document.getElementById('pub-f-enabled');
  if (en) en.checked = p.enabled !== false;

  document.getElementById('pub-form-title').innerHTML     = '<i class="fas fa-edit" style="color:var(--primary)"></i> Edit Publisher';
  document.getElementById('pub-save-label').textContent   = 'Save Changes';
  document.getElementById('pub-cancel-btn').style.display = 'inline-flex';
  document.getElementById('pub-form-card').scrollIntoView({ behavior:'smooth' });
}

// Quick toggle without opening the edit form.
// Sends a partial PUT — all other fields default to their stored values in the service.
async function togglePubEnabled(id, currentEnabled) {
  const r = await fetch(`/api/management/publishers/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled: !currentEnabled }),
  });
  if (!r.ok) { const d = await r.json(); alert(d.error || 'Toggle failed'); return; }
  _loaded.delete('administration:publishers');
  await loadPubList();
}

async function deletePub(id) {
  if (!confirm('Delete this publisher? This will NOT delete their game configurations.')) return;
  await fetch(`/api/management/publishers/${id}`, { method:'DELETE' });
  _loaded.delete('administration:publishers');
  await loadPubList();
}

function cancelPubEdit() {
  document.getElementById('pub-edit-id').value            = '';
  _pubFormClear();
  document.getElementById('pub-form-title').innerHTML     = '<i class="fas fa-plus-circle" style="color:var(--primary)"></i> Add Publisher';
  document.getElementById('pub-save-label').textContent   = 'Add Publisher';
  document.getElementById('pub-cancel-btn').style.display = 'none';
}

// ══════════════════════════════════════════════════════════════════
//  MANAGEMENT PAGE — GAME CONFIGURATIONS
// ══════════════════════════════════════════════════════════════════

// ── State ────────────────────────────────────────────────────────
let _gcGoals     = [];   // [{name:'', bid:null}]
let _gcPubKpi    = { retention: [], roas: [] };
let _gcClientKpi = { retention: [], roas: [] };
let _gcFunnel    = [];   // [{goal:'', pct:'', time_val:'', time_unit:'Days'}]
let _gcFilter    = 'all';
let _gcDiscovered = [];  // cached from /api/admin/games/discovered
let _gcConfigs    = [];  // cached from /api/admin/games

// ── Render helpers ───────────────────────────────────────────────

function _gcRenderGoalsList() {
  const el = document.getElementById('gc-goals-list');
  if (!el) return;
  el.innerHTML = _gcGoals.length ? _gcGoals.map((g, i) => `
    <div class="pub-goal-row">
      <input class="pub-goal-input" type="text" placeholder="e.g. Level 5"
        value="${esc(g.name)}"
        oninput="_gcGoalNameChange(${i}, this.value)">
      <button class="pub-row-del" title="Remove" onclick="_gcGoalRemove(${i})">
        <i class="fas fa-times"></i>
      </button>
    </div>`).join('')
    : '<div class="pub-empty-hint">No goals yet</div>';
  _gcRenderBidTable();
}

function _gcRenderBidTable() {
  const el = document.getElementById('gc-bid-list');
  if (!el) return;
  if (!_gcGoals.length) { el.innerHTML = '<div class="pub-bid-empty">Add goals to configure bids</div>'; return; }
  el.innerHTML = `
    <table class="pub-bid-table">
      <thead><tr><th>Goal</th><th>Bid ($)</th></tr></thead>
      <tbody>
        ${_gcGoals.map((g, i) => `
          <tr>
            <td class="pub-bid-goal">${esc(g.name || '(unnamed)')}</td>
            <td><input class="pub-bid-input" type="number" step="0.01" min="0"
              placeholder="0.00" value="${g.bid != null ? g.bid : ''}"
              oninput="_gcBidChange(${i}, this.value)"></td>
          </tr>`).join('')}
      </tbody>
    </table>`;
}

function _gcRenderKpi(side, type) {
  const state = side === 'pub' ? _gcPubKpi : _gcClientKpi;
  const rows  = state[type] || [];
  const elId  = `gc-${side}-kpi-${type}`;
  const el    = document.getElementById(elId);
  if (!el) return;
  el.innerHTML = rows.length ? rows.map((r, i) => `
    <div class="pub-kpi-row">
      <input class="pub-kpi-dn" type="number" min="1" placeholder="7"
        value="${r.dn != null ? r.dn : ''}"
        oninput="_gcKpiChange('${side}','${type}',${i},'dn',this.value)">
      <span class="pub-kpi-dlabel">D</span>
      <input class="pub-kpi-val" type="number" step="0.1" min="0" placeholder="0"
        value="${r.val != null ? r.val : ''}"
        oninput="_gcKpiChange('${side}','${type}',${i},'val',this.value)">
      <span class="pub-kpi-unit">%</span>
      <button class="pub-row-del" title="Remove" onclick="_gcKpiRemove('${side}','${type}',${i})">
        <i class="fas fa-times"></i>
      </button>
    </div>`).join('')
    : '<div class="pub-empty-hint">No targets yet</div>';
}

function _gcRenderAllKpi() {
  _gcRenderKpi('pub',    'retention');
  _gcRenderKpi('pub',    'roas');
  _gcRenderKpi('client', 'retention');
  _gcRenderKpi('client', 'roas');
}

function _gcRenderFunnel() {
  const el = document.getElementById('gc-funnel-list');
  if (!el) return;
  el.innerHTML = _gcFunnel.length ? _gcFunnel.map((r, i) => `
    <div class="pub-funnel-row">
      <input class="pub-funnel-goal" type="text" placeholder="e.g. Level 5"
        value="${esc(r.goal)}"
        oninput="_gcFunnelChange(${i},'goal',this.value)">
      <input class="pub-funnel-pct" type="number" step="0.1" min="0" max="100" placeholder="85"
        value="${r.pct !== '' ? r.pct : ''}"
        oninput="_gcFunnelChange(${i},'pct',this.value)">
      <div class="gc-funnel-time">
        <input class="gc-funnel-time-val" type="number" step="1" min="0" placeholder="1"
          value="${r.time_val !== '' ? r.time_val : ''}"
          oninput="_gcFunnelChange(${i},'time_val',this.value)">
        <select class="gc-funnel-time-unit" onchange="_gcFunnelChange(${i},'time_unit',this.value)">
          ${['Minutes','Hours','Days'].map(u => `<option value="${u}"${r.time_unit===u?' selected':''}>${u}</option>`).join('')}
        </select>
      </div>
      <button class="pub-row-del" title="Remove" onclick="_gcFunnelRemove(${i})">
        <i class="fas fa-times"></i>
      </button>
    </div>`).join('')
    : '<div class="pub-empty-hint">No funnel steps yet</div>';
}

// ── Mutators ─────────────────────────────────────────────────────

function _gcGoalAdd() {
  _gcGoals.push({ name: '', bid: null });
  _gcRenderGoalsList();
}
function _gcGoalRemove(i) { _gcGoals.splice(i, 1); _gcRenderGoalsList(); }
function _gcGoalNameChange(i, val) {
  _gcGoals[i].name = val;
  const cells = document.querySelectorAll('#gc-bid-list .pub-bid-goal');
  if (cells[i]) cells[i].textContent = val || '(unnamed)';
}
function _gcBidChange(i, val) { _gcGoals[i].bid = val === '' ? null : parseFloat(val); }

function _gcKpiAdd(side, type) {
  const s = side === 'pub' ? _gcPubKpi : _gcClientKpi;
  s[type].push({ dn: '', val: '' }); _gcRenderKpi(side, type);
}
function _gcKpiRemove(side, type, i) {
  const s = side === 'pub' ? _gcPubKpi : _gcClientKpi;
  s[type].splice(i, 1); _gcRenderKpi(side, type);
}
function _gcKpiChange(side, type, i, field, val) {
  const s = side === 'pub' ? _gcPubKpi : _gcClientKpi;
  s[type][i][field] = val;
}

function _gcFunnelAdd() {
  _gcFunnel.push({ goal: '', pct: '', time_val: '', time_unit: 'Days' });
  _gcRenderFunnel();
}
function _gcFunnelRemove(i) { _gcFunnel.splice(i, 1); _gcRenderFunnel(); }
function _gcFunnelChange(i, field, val) { _gcFunnel[i][field] = val; }

function _gcGameTypeChange(val) {
  // For CPI: auto-set a single goal '1' if no goals present yet
  if (val === 'CPI' && _gcGoals.length === 0) {
    _gcGoals = [{ name: '1', bid: null }];
    _gcRenderGoalsList();
  }
}

function _gcFormClear() {
  ['offer_name','offer_id','expected_margin'].forEach(k => {
    const el = document.getElementById('gc-f-' + k);
    if (el) el.value = '';
  });
  const gt = document.getElementById('gc-f-game_type');
  if (gt) gt.value = '';
  const picker = document.getElementById('gc-offer-picker');
  if (picker) picker.value = '';
  _gcGoals     = [];
  _gcPubKpi    = { retention: [], roas: [] };
  _gcClientKpi = { retention: [], roas: [] };
  _gcFunnel    = [];
  _gcRenderGoalsList();
  _gcRenderAllKpi();
  _gcRenderFunnel();
}

// ── Offer picker ─────────────────────────────────────────────────

function _gcPickOffer(val) {
  if (!val) return;
  const found = _gcDiscovered.find(d => d.offer_id === val);
  if (!found) return;
  document.getElementById('gc-f-offer_name').value = found.offer_name;
  document.getElementById('gc-f-offer_id').value   = found.offer_id;
  document.getElementById('gc-f-game_type').value  = found.game_type_guess;
  _gcGameTypeChange(found.game_type_guess);
}

// ── Filter ───────────────────────────────────────────────────────

function _gcSetFilter(f) {
  _gcFilter = f;
  // Update card active states
  document.querySelectorAll('.gc-stat-card').forEach(c => {
    c.classList.toggle('gc-stat-card--active', c.dataset.filter === f);
  });
  const lbl = document.getElementById('gc-filter-label');
  const btn = document.getElementById('gc-clear-filter-btn');
  if (lbl) lbl.textContent = f !== 'all' ? `Showing: ${f.replace('_',' ')}` : '';
  if (btn) btn.style.display = f !== 'all' ? '' : 'none';
  _gcRenderTable();
}

// ── Status cards ─────────────────────────────────────────────────

async function _gcLoadStatus() {
  try {
    const s = await api('/api/admin/games/status');
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('gcs-discovered',  s.discovered_count);
    set('gcs-configured',  s.configured_count);
    set('gcs-pending',     s.pending_count);
    set('gcs-mkpi',        s.missing_kpi);
    set('gcs-mfunnel',     s.missing_funnel);
    set('gcs-mmargin',     s.missing_margin);
    set('gcs-publishers',  s.publishers_count);

    // Alert banner
    const alertEl = document.getElementById('gc-alert');
    const alertTx = document.getElementById('gc-alert-text');
    if (alertEl && s.pending_count > 0) {
      alertTx.textContent = `${s.pending_count} discovered game${s.pending_count>1?'s are':' is'} not yet configured.`;
      alertEl.style.display = '';
    } else if (alertEl) {
      alertEl.style.display = 'none';
    }
  } catch(e) { console.warn('gc status:', e); }
}

// ── Table render ─────────────────────────────────────────────────

function _gcRenderTable() {
  const el = document.getElementById('gc-list-body');
  if (!el) return;

  // Build lookup: offer_id → discovered info
  const discMap = {};
  _gcDiscovered.forEach(d => { discMap[d.offer_id] = d; });

  // Apply filter
  let rows = [..._gcConfigs];
  if (_gcFilter === 'configured') {
    // only configured — already all in _gcConfigs
  } else if (_gcFilter === 'pending') {
    // show discovered but not configured
    rows = _gcDiscovered.filter(d => !d.configured);
  } else if (_gcFilter === 'missing_kpi') {
    rows = _gcConfigs.filter(c => {
      const pk = c.publisher_kpi || {}; const ck = c.client_kpi || {};
      return !(pk.retention?.length || pk.roas?.length || ck.retention?.length || ck.roas?.length);
    });
  } else if (_gcFilter === 'missing_funnel') {
    rows = _gcConfigs.filter(c => !(c.expected_funnel?.length));
  } else if (_gcFilter === 'missing_margin') {
    rows = _gcConfigs.filter(c => c.expected_margin == null);
  }

  const badge = document.getElementById('gc-table-count');
  if (badge) badge.textContent = _gcConfigs.length + ' configured';

  const typeBadge = t => t === 'CPI'
    ? '<span class="pub-type-badge chip-cpi">CPI</span>'
    : t === 'CPE' ? '<span class="pub-type-badge chip-cpe">CPE</span>'
    : '<span style="color:#64748b">—</span>';

  const _kpiLine = (kpi, type) => {
    const arr = kpi?.[type] || [];
    return arr.length ? arr.map(r => `D${r.dn}=${r.val}%`).join(' ') : '';
  };

  const _cfgSummary = c => {
    const lines = [];
    const goals = c.payable_goals || [];
    if (goals.length) lines.push(`<div class="pub-cfg-line"><span class="pub-cfg-label">Goals</span>${goals.map(g=>`<span class="pub-goal-tag">${esc(g.name||'?')}</span>`).join('')}</div>`);
    const pr = _kpiLine(c.publisher_kpi,'retention'), po = _kpiLine(c.publisher_kpi,'roas');
    if (pr||po) lines.push(`<div class="pub-cfg-line"><span class="pub-cfg-label">Pub KPI</span>${[pr&&`<span class="pub-kpi-chip pub-kpi-chip-ret">Ret ${pr}</span>`,po&&`<span class="pub-kpi-chip pub-kpi-chip-roas">ROAS ${po}</span>`].filter(Boolean).join('')}</div>`);
    const cr = _kpiLine(c.client_kpi,'retention'), co = _kpiLine(c.client_kpi,'roas');
    if (cr||co) lines.push(`<div class="pub-cfg-line"><span class="pub-cfg-label">Client KPI</span>${[cr&&`<span class="pub-kpi-chip pub-kpi-chip-ret">Ret ${cr}</span>`,co&&`<span class="pub-kpi-chip pub-kpi-chip-roas">ROAS ${co}</span>`].filter(Boolean).join('')}</div>`);
    if (c.expected_funnel?.length) lines.push(`<div class="pub-cfg-line"><span class="pub-cfg-label">Funnel</span><span class="pub-kpi-chip">${c.expected_funnel.length} step${c.expected_funnel.length>1?'s':''}</span></div>`);
    if (c.expected_margin != null) lines.push(`<div class="pub-cfg-line"><span class="pub-cfg-label">Margin</span><span class="pub-kpi-chip pub-kpi-chip-margin">${fmtN(c.expected_margin)}%</span></div>`);
    return lines.length ? `<div class="pub-cfg-summary">${lines.join('')}</div>` : '<span style="color:#64748b;font-size:11px">No configuration yet</span>';
  };

  if (_gcFilter === 'pending') {
    el.innerHTML = rows.length ? rows.map(d => `
      <tr>
        <td>
          <div style="font-weight:600;font-size:13px">${esc(d.offer_name)}</div>
          <div style="font-size:11px;color:#64748b">${esc(d.offer_id)}</div>
        </td>
        <td>${typeBadge(d.game_type_guess)}</td>
        <td><span class="gc-chip gc-chip-pending">Pending</span></td>
        <td class="td-center">
          <button class="tbl-btn tbl-btn-edit" onclick="_gcStartFromDiscovered('${esc(d.offer_id)}')">Configure</button>
        </td>
      </tr>`).join('')
      : '<tr><td colspan="4" class="td-empty">All discovered games are configured.</td></tr>';
    return;
  }

  el.innerHTML = rows.length ? rows.map(c => `
    <tr>
      <td>
        <div style="font-weight:600;font-size:13px">${esc(c.offer_name)}</div>
        <div style="font-size:11px;color:#64748b">${esc(c.offer_id)}</div>
      </td>
      <td>${typeBadge(c.game_type)}</td>
      <td>${_cfgSummary(c)}</td>
      <td class="td-center" style="white-space:nowrap">
        <button class="tbl-btn tbl-btn-edit" onclick="editGameConfig('${c.id}')">Edit</button>
        <button class="tbl-btn tbl-btn-del"  onclick="deleteGameConfig('${c.id}')">Del</button>
      </td>
    </tr>`).join('')
    : '<tr><td colspan="4" class="td-empty"><div class="empty-state"><i class="fas fa-gamepad empty-icon"></i><p>No game configurations yet</p></div></td></tr>';
}

// ── Populate offer picker ─────────────────────────────────────────

function _gcPopulatePicker() {
  const sel = document.getElementById('gc-offer-picker');
  if (!sel) return;
  // Only show unconfigured offers in the picker
  const unconfigured = _gcDiscovered.filter(d => !d.configured);
  sel.innerHTML = '<option value="">— pick a game to configure —</option>' +
    unconfigured.map(d => `<option value="${esc(d.offer_id)}">${esc(d.offer_name)} (${esc(d.offer_id)})</option>`).join('');
}

// ── Pre-fill form from a discovered-but-unconfigured offer ────────

function _gcStartFromDiscovered(offer_id) {
  _gcSetFilter('all');
  const d = _gcDiscovered.find(x => x.offer_id === offer_id);
  if (!d) return;
  _gcFormClear();
  document.getElementById('gc-f-offer_name').value = d.offer_name;
  document.getElementById('gc-f-offer_id').value   = d.offer_id;
  document.getElementById('gc-f-game_type').value  = d.game_type_guess;
  _gcGameTypeChange(d.game_type_guess);
  document.getElementById('gc-form-title').innerHTML   = '<i class="fas fa-gamepad" style="color:var(--primary)"></i> Configure Game';
  document.getElementById('gc-save-label').textContent = 'Save Configuration';
  document.getElementById('gc-cancel-btn').style.display = 'inline-flex';
  document.getElementById('gc-edit-id').value = '';
  document.getElementById('gc-form-card').scrollIntoView({ behavior:'smooth' });
}

// ── Main load ────────────────────────────────────────────────────

async function loadGamesList() {
  try {
    [_gcDiscovered, _gcConfigs] = await Promise.all([
      api('/api/admin/games/discovered'),
      api('/api/admin/games'),
    ]);
  } catch(e) { console.error('gc load:', e); _gcDiscovered = []; _gcConfigs = []; }

  _gcPopulatePicker();
  _gcRenderTable();
  await _gcLoadStatus();
  await loadUnconfiguredGames();

  // Init form dynamic lists if not mid-edit
  if (!document.getElementById('gc-edit-id')?.value) {
    _gcRenderGoalsList();
    _gcRenderAllKpi();
    _gcRenderFunnel();
  }
}

// ── Unconfigured Games ────────────────────────────────────────────

async function loadUnconfiguredGames() {
  const card = document.getElementById('uc-games-card');
  const body = document.getElementById('uc-games-body');
  const cnt  = document.getElementById('uc-games-count');
  if (!card || !body) return;

  let data;
  try {
    data = await api('/api/admin/games/unconfigured');
  } catch(e) {
    console.warn('uc-games load:', e);
    card.style.display = 'none';
    return;
  }

  const items = data.unconfigured || [];
  if (cnt) cnt.textContent = items.length;

  if (!items.length) {
    card.style.display = 'none';
    return;
  }

  card.style.display = '';
  body.innerHTML = items.map(g => `
    <tr>
      <td class="uc-offer-name">${esc(g.offer_name)}</td>
      <td class="uc-offer-id"><code>${esc(g.offer_id)}</code></td>
      <td class="uc-pubs"><span class="count-badge">${g.publisher_ids.length}</span></td>
      <td><span class="pub-type-badge ${g.game_type_guess === 'CPI' ? 'chip-cpi' : 'chip-cpe'}">${esc(g.game_type_guess)}</span></td>
      <td class="th-center">
        <button class="btn-xs btn-primary" onclick="_ucConfigure(${JSON.stringify(g).replace(/"/g, '&quot;')})">
          <i class="fas fa-gear"></i> Configure
        </button>
      </td>
    </tr>
  `).join('');
}

function _ucConfigure(game) {
  // Pre-fill the Game Configuration form with this offer's details, then scroll to it
  const offerNameEl = document.getElementById('gc-f-offer_name');
  const offerIdEl   = document.getElementById('gc-f-offer_id');
  const gameTypeEl  = document.getElementById('gc-f-game_type');
  if (offerNameEl) offerNameEl.value = game.offer_name;
  if (offerIdEl)   offerIdEl.value   = game.offer_id;
  if (gameTypeEl) {
    gameTypeEl.value = game.game_type_guess;
    _gcGameTypeChange(game.game_type_guess);
  }
  // Clear any active edit
  const editIdEl = document.getElementById('gc-edit-id');
  if (editIdEl) editIdEl.value = '';
  const banner = document.getElementById('gc-game-info-banner');
  if (banner) banner.style.display = 'none';

  // Scroll the form into view
  const form = document.getElementById('gc-form-card');
  if (form) form.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── CRUD ─────────────────────────────────────────────────────────

async function saveGameConfig() {
  const editId     = document.getElementById('gc-edit-id')?.value;
  const offer_name = document.getElementById('gc-f-offer_name')?.value.trim();
  const offer_id   = document.getElementById('gc-f-offer_id')?.value.trim();
  const game_type  = document.getElementById('gc-f-game_type')?.value;
  if (!offer_id)   { alert('Offer ID is required'); return; }
  if (!game_type)  { alert('Game Type is required'); return; }

  const _cleanKpi = rows => rows.filter(r => r.dn !== '').map(r => ({
    dn: parseInt(r.dn, 10), val: parseFloat(r.val) || 0,
  }));

  const payable_goals = _gcGoals
    .filter(g => g.name.trim())
    .map(g => ({ name: g.name.trim(), bid: g.bid != null ? g.bid : 0 }));

  const expected_funnel = _gcFunnel
    .filter(r => r.goal.trim())
    .map(r => ({
      goal:      r.goal.trim(),
      pct:       parseFloat(r.pct)  || 0,
      time_val:  parseFloat(r.time_val) || 0,
      time_unit: r.time_unit || 'Days',
    }));

  const em = document.getElementById('gc-f-expected_margin')?.value;
  const payload = {
    offer_id, offer_name, game_type, payable_goals,
    publisher_kpi:  { retention: _cleanKpi(_gcPubKpi.retention),    roas: _cleanKpi(_gcPubKpi.roas)    },
    client_kpi:     { retention: _cleanKpi(_gcClientKpi.retention),  roas: _cleanKpi(_gcClientKpi.roas)  },
    expected_funnel,
    expected_margin: em !== '' && em != null ? parseFloat(em) : null,
  };

  const url    = editId ? `/api/admin/games/${editId}` : '/api/admin/games';
  const method = editId ? 'PUT' : 'POST';
  const r = await fetch(url, { method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  if (!r.ok) { const d=await r.json(); alert(d.error||'Save failed'); return; }
  cancelGameEdit();
  _loaded.delete('administration:games');
  await loadGamesList();
}

async function editGameConfig(id) {
  const c = _gcConfigs.find(x => x.id === id);
  if (!c) return;

  document.getElementById('gc-edit-id').value        = id;
  document.getElementById('gc-f-offer_name').value   = c.offer_name || '';
  document.getElementById('gc-f-offer_id').value     = c.offer_id   || '';
  document.getElementById('gc-f-game_type').value    = c.game_type  || '';
  document.getElementById('gc-f-expected_margin').value = c.expected_margin != null ? c.expected_margin : '';

  // Show info banner
  const banner = document.getElementById('gc-game-info-banner');
  const bname  = document.getElementById('gc-banner-name');
  const bid    = document.getElementById('gc-banner-id');
  if (banner) banner.style.display = '';
  if (bname)  bname.textContent  = c.offer_name || '';
  if (bid)    bid.textContent    = `ID: ${c.offer_id}`;

  // Hide picker when editing existing
  const pf = document.getElementById('gc-picker-field');
  if (pf) pf.style.display = 'none';

  _gcGoals = Array.isArray(c.payable_goals)
    ? c.payable_goals.map(g => ({ name: g.name || '', bid: g.bid != null ? g.bid : null }))
    : [];

  const _loadKpi = src => ({
    retention: Array.isArray(src?.retention) ? src.retention.map(r => ({ dn: r.dn ?? '', val: r.val ?? '' })) : [],
    roas:      Array.isArray(src?.roas)      ? src.roas.map(r => ({ dn: r.dn ?? '', val: r.val ?? '' }))      : [],
  });
  _gcPubKpi    = _loadKpi(c.publisher_kpi);
  _gcClientKpi = _loadKpi(c.client_kpi);

  _gcFunnel = Array.isArray(c.expected_funnel)
    ? c.expected_funnel.map(r => ({
        goal:      r.goal ?? '',
        pct:       r.pct  ?? '',
        time_val:  r.time_val  ?? (r.days ?? ''),
        time_unit: r.time_unit ?? 'Days',
      }))
    : [];

  _gcRenderGoalsList();
  _gcRenderAllKpi();
  _gcRenderFunnel();

  document.getElementById('gc-form-title').innerHTML   = '<i class="fas fa-edit" style="color:var(--primary)"></i> Edit Game Configuration';
  document.getElementById('gc-save-label').textContent = 'Save Changes';
  document.getElementById('gc-cancel-btn').style.display = 'inline-flex';
  document.getElementById('gc-form-card').scrollIntoView({ behavior:'smooth' });
}

async function deleteGameConfig(id) {
  if (!confirm('Delete this game configuration?')) return;
  await fetch(`/api/admin/games/${id}`, { method:'DELETE' });
  _loaded.delete('administration:games');
  await loadGamesList();
}

function cancelGameEdit() {
  document.getElementById('gc-edit-id').value = '';
  _gcFormClear();
  // Hide banner, show picker
  const banner = document.getElementById('gc-game-info-banner');
  if (banner) banner.style.display = 'none';
  const pf = document.getElementById('gc-picker-field');
  if (pf) pf.style.display = '';
  document.getElementById('gc-form-title').innerHTML   = '<i class="fas fa-gamepad" style="color:var(--primary)"></i> Configure Game';
  document.getElementById('gc-save-label').textContent = 'Save Configuration';
  document.getElementById('gc-cancel-btn').style.display = 'none';
}

// ══════════════════════════════════════════════════════════════════
//  MANAGEMENT PAGE — CLIENTS
// ══════════════════════════════════════════════════════════════════

function _clientFormFields()  { return ['client_name','games','bid','kpi','notes']; }
function _clientFormVal(key)  { return document.getElementById('client-f-'+key)?.value.trim() || ''; }
function _clientFormSet(key, val) { const el = document.getElementById('client-f-'+key); if(el) el.value = val ?? ''; }

async function loadClientList() {
  try {
    const clients = await api('/api/management/clients');
    const badge   = document.getElementById('client-table-count');
    if (badge) badge.textContent = clients.length + ' clients';
    document.getElementById('client-list-body').innerHTML = clients.length ? clients.map(c => `
      <tr>
        <td style="font-weight:600">${esc(c.client_name)}</td>
        <td>${esc(c.games||'—')}</td>
        <td class="td-num">$${fmtN(c.bid)}</td>
        <td>${esc(c.kpi||'—')}</td>
        <td class="td-trunc" style="max-width:200px" title="${esc(c.notes||'')}">${esc(c.notes||'—')}</td>
        <td class="td-center">
          <button class="tbl-btn tbl-btn-edit" onclick="editClient('${c.id}')">Edit</button>
          <button class="tbl-btn tbl-btn-del"  onclick="deleteClient('${c.id}')">Delete</button>
        </td>
      </tr>`).join('')
      : `<tr><td colspan="6" class="td-empty"><div class="empty-state"><i class="fas fa-users empty-icon"></i><p>No clients yet — add one above</p></div></td></tr>`;
  } catch(e) { console.error('client list:', e); }
}

async function saveClient() {
  const editId = document.getElementById('client-edit-id')?.value;
  const payload = {};
  _clientFormFields().forEach(k => payload[k] = _clientFormVal(k));
  if (!payload.client_name) { alert('Client Name is required'); return; }

  const url    = editId ? `/api/management/clients/${editId}` : '/api/management/clients';
  const method = editId ? 'PUT' : 'POST';
  const r = await fetch(url, { method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  if (!r.ok) { const d=await r.json(); alert(d.error||'Save failed'); return; }
  cancelClientEdit();
  _loaded.delete('administration:clients');
  await loadClientList();
}

async function editClient(id) {
  const clients = await api('/api/management/clients');
  const c = clients.find(x => x.id === id);
  if (!c) return;
  document.getElementById('client-edit-id').value = id;
  _clientFormFields().forEach(k => _clientFormSet(k, c[k] ?? ''));
  document.getElementById('client-form-title').innerHTML = '<i class="fas fa-edit" style="color:var(--primary)"></i> Edit Client';
  document.getElementById('client-save-label').textContent   = 'Save Changes';
  document.getElementById('client-cancel-btn').style.display = 'inline-flex';
  document.getElementById('client-form-card').scrollIntoView({ behavior:'smooth' });
}

async function deleteClient(id) {
  if (!confirm('Delete this client?')) return;
  await fetch(`/api/management/clients/${id}`, { method:'DELETE' });
  _loaded.delete('administration:clients');
  await loadClientList();
}

function cancelClientEdit() {
  document.getElementById('client-edit-id').value = '';
  _clientFormFields().forEach(k => _clientFormSet(k,''));
  document.getElementById('client-form-title').innerHTML = '<i class="fas fa-plus-circle" style="color:var(--primary)"></i> Add Client';
  document.getElementById('client-save-label').textContent   = 'Add Client';
  document.getElementById('client-cancel-btn').style.display = 'none';
}

document.addEventListener('DOMContentLoaded', init);
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    if (document.getElementById('slide-panel')?.classList.contains('open')) closeSlidePanel();
  }
});
