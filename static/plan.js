'use strict';
/* Mugitu – directions screen (journey planner).
   Loaded before app.js: only function declarations run at load time. app.js calls planInit() at boot, once the map and
   the state exist, and routes the "plan-*" actions of its click handler to planAct(). Talks to /api/plan and /api/geocode. */

const PLAN_ICON_PATHS = {
  directions: 'M21.71 11.29l-9-9a.996.996 0 0 0-1.41 0l-9 9a.996.996 0 0 0 0 1.41l9 9c.39.39 1.02.39 1.41 0l9-9a.996.996 0 0 0 0-1.41zM14 14.5V12h-4v3H8v-4c0-.55.45-1 1-1h5V7.5l3.5 3.5-3.5 3.5z',
  walk: 'M13.5 5.5c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zM9.8 8.9L7 23h2.1l1.8-8 2.1 2v6h2v-7.5l-2.1-2 .6-3C14.8 12 16.8 13 19 13v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1L6 8.3V13h2V9.6l1.8-.7',
  swap: 'M16 17.01V10h-2v7.01h-3L15 21l4-3.99h-3zM9 3L5 6.99h3V14h2V6.99h3L9 3z',
  history: 'M13 3a9 9 0 0 0-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42A8.954 8.954 0 0 0 13 21a9 9 0 0 0 0-18zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z',
};
const PLAN_RECENT_KEY = 'planRecent';
const PLAN_ERRORS = { warming_up: 'plan_warming', no_route: 'plan_no_route', out_of_area: 'plan_out_of_area', same_place: 'plan_same',
  date_out_of_range: 'plan_date_out', bad_time: 'plan_bad', bad_endpoint: 'plan_bad' };
let pl = null, planEnds = null, planRoute = null, planReq = 0, sugTimer2 = 0, sugReq2 = 0, menuAt = 0, menuPop = null;

function planInit() {
  for (const k in PLAN_ICON_PATHS) ICONS[k] = P(PLAN_ICON_PATHS[k]);   // P() is defined by app.js, which loads after this file
  pl = S.plan = {
    from: null, to: null, when: { mode: 'now', date: '', time: '' }, maxWalk: +localStorage.getItem('planWalk') || 1000,
    res: null, err: null, errEnd: null, busy: false, selKey: null, field: null, sug: [], pick: null, open: {}, moreBusy: false,
  };
  planEnds = L.layerGroup().addTo(map);
  planRoute = L.layerGroup().addTo(map);
  const b = $('#btn-directions');
  b.innerHTML = ic('directions');
  b.addEventListener('click', () => openPlan());
  // a point of the map: right click, or a long press on a phone
  map.on('contextmenu', e => planMapMenu(e.latlng));
  map.getContainer().addEventListener('contextmenu', e => e.preventDefault());
  let timer = null, start = null;
  const cancel = () => { clearTimeout(timer); timer = null; };
  map.getContainer().addEventListener('pointerdown', e => {
    if (e.pointerType !== 'touch' || !e.isPrimary) return;
    start = [e.clientX, e.clientY];
    cancel();
    timer = setTimeout(() => { timer = null; planMapMenu(map.mouseEventToLatLng(e)); }, 600);
  }, { passive: true });
  map.getContainer().addEventListener('pointermove', e => { if (timer && Math.hypot(e.clientX - start[0], e.clientY - start[1]) > 10) cancel(); }, { passive: true });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach(n => map.getContainer().addEventListener(n, cancel, { passive: true }));
  map.on('movestart zoomstart', cancel);
  document.addEventListener('pointerdown', e => { if (pl.field && !e.target.closest('.pfields, #plan-sug')) planCloseSug(); });
  // live journeys are refreshed while the screen is open
  setInterval(() => { if (S.view.name === 'plan' && pl.when.mode === 'now' && pl.res && !pl.busy && !pl.field && !document.hidden) planSearch({ silent: true }); }, 60000);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && pl.pick) planPickEnd(); });
}

// ───────────────────────────────────────────────────────────── helpers
const epLabel = ep => ep ? (ep.kind === 'me' ? t('plan_my_loc') : ep.label) : '';
const epSpec = ep => ep.kind === 'station' ? 'st:' + ep.agency + '|' + ep.station_id : 'll:' + ep.lat.toFixed(5) + ',' + ep.lon.toFixed(5);
const fmtM = m => m < 950 ? Math.max(5, Math.round(m / 10) * 10) + ' m' : (m / 1000).toFixed(1).replace(/\.0$/, '') + ' km';
function fmtDur(secs) {
  const m = Math.max(1, Math.round(secs / 60));
  return m < 60 ? m + ' ' + t('min') : Math.floor(m / 60) + ' h' + (m % 60 ? ' ' + (m % 60) + ' ' + t('min') : '');
}
const jKey = j => JSON.stringify(j.sig);
/** "Tue, 24 Nov" when a moment is not today, otherwise nothing. */
function dayTag(ts) {
  const d = new Date(ts * 1000);
  return d.toDateString() === new Date().toDateString() ? '' : d.toLocaleDateString(S.lang, { weekday: 'short', day: 'numeric', month: 'short' });
}
const todayYmd = () => dateToYmd(new Date());
function nextFive() { const d = new Date(Date.now() + 5 * 60000); d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5, 0, 0); return d; }
function stationEp(st) {
  return { kind: 'station', lat: st.lat, lon: st.lon, label: st.name, sub: st.agency_name || '', agency: st.agency, station_id: st.station_id, modes: st.modes };
}
function planRecents() { try { return JSON.parse(localStorage.getItem(PLAN_RECENT_KEY) || '[]'); } catch (e) { return []; } }
function planRemember(ep) {
  if (!ep || ep.kind === 'me') return;
  const key = e => e.kind + ':' + e.lat.toFixed(4) + ',' + e.lon.toFixed(4);
  const list = [ep, ...planRecents().filter(x => key(x) !== key(ep))].slice(0, 6);
  localStorage.setItem(PLAN_RECENT_KEY, JSON.stringify(list));
}

// ───────────────────────────────────────────────────────────── entry points
/** Open the directions screen, optionally with a start and / or a destination. */
function openPlan(o = {}) {
  if (o.from) pl.from = o.from;
  if (o.to) pl.to = o.to;
  if (!pl.from && S.me && !o.to) pl.from = { kind: 'me', lat: S.me[0], lon: S.me[1], label: t('plan_my_loc') };
  if (S.view.name === 'plan') render(); else go({ name: 'plan' }, 'stops');
  if (isMobile()) setSheet(pl.from && pl.to ? 'half' : 'full');
  if (pl.from && pl.to) planSearch();
  else { const f = pl.from ? 'to' : 'from'; setTimeout(() => { const i = $('#pf-' + f); if (i) i.focus(); }, 60); }
}
function planLeave() { document.body.classList.remove('planning'); if (planEnds) { planEnds.clearLayers(); planRoute.clearLayers(); } planPickEnd(true); }

function planMapMenu(ll) {
  if (Date.now() - menuAt < 900 || pl.pick) return;
  menuAt = Date.now();
  const at = `data-lat="${ll.lat.toFixed(5)}" data-lon="${ll.lng.toFixed(5)}"`;
  menuPop = L.popup({ closeButton: false, closeOnClick: false, className: 'pmenu', minWidth: 190, autoPanPadding: [20, 140] }).setLatLng(ll).setContent(
    `<button type="button" class="pm-btn" data-act="plan-here" data-end="from" ${at}>${ic('directions')}${esc(t('plan_dir_from'))}</button>` +
    `<button type="button" class="pm-btn" data-act="plan-here" data-end="to" ${at}>${ic('pin')}${esc(t('plan_dir_to'))}</button>`).openOn(map);
}

/** The label of a point that was tapped on the map: the place it is near, or its coordinates. */
async function pinLabel(lat, lon) {
  try {
    const d = await api('geocode', { lat, lon, lang: S.lang });
    if (d.place) return t('plan_pinned') + ' (' + t('plan_near').replace('{x}', d.place.label) + ')';
  } catch (e) { /* ignore */ }
  return t('plan_pinned') + ' (' + lat.toFixed(4) + ', ' + lon.toFixed(4) + ')';
}
async function planSetPin(end, lat, lon) {
  const ep = { kind: 'll', lat, lon, label: t('plan_pinned') };
  planSetEnd(end, ep);
  const label = await pinLabel(lat, lon);
  if (pl[end] === ep) { ep.label = label; const i = $('#pf-' + end); if (i && pl.field !== end) i.value = label; if (pl.res) planSearch({ silent: true }); }
}

// ───────────────────────────────────────────────────────────── choosing a point on the map
function planPickStart(end) {
  planCloseSug();
  pl.pick = end;
  map.getContainer().classList.add('picking');
  document.body.classList.add('picking');
  let bar = $('#pickbar');
  if (!bar) { bar = document.createElement('div'); bar.id = 'pickbar'; bar.className = 'pickbar'; $('#mapwrap').appendChild(bar); L.DomEvent.disableClickPropagation(bar); }
  bar.innerHTML = `<span class="grow">${esc(t(end === 'from' ? 'plan_pick_from' : 'plan_pick_to'))}</span><button type="button" class="btn small" data-act="plan-pick-cancel">${esc(t('plan_cancel'))}</button>`;
  bar.hidden = false;
  if (isMobile()) setSheet('closed');
}
function planPickEnd(silent) {
  if (!pl || !pl.pick) return;
  pl.pick = null;
  map.getContainer().classList.remove('picking');
  document.body.classList.remove('picking');
  const bar = $('#pickbar'); if (bar) bar.hidden = true;
  if (!silent && isMobile() && S.view.name === 'plan') setSheet('half');
}
/** app.js calls this first on every map click: true when the click was a point being chosen. */
function planMapClick(e) {
  if (menuPop && menuPop.isOpen()) {               // the menu of a point: a tap elsewhere closes it (and does nothing else)
    const fresh = Date.now() - menuAt < 700;       // ... but not the tap that ends the long press that opened it
    if (!fresh) { map.closePopup(menuPop); menuPop = null; }
    return true;
  }
  menuPop = null;
  if (!pl || !pl.pick) return false;
  const end = pl.pick;
  planPickEnd();
  planSetPin(end, e.latlng.lat, e.latlng.lng);
  return true;
}
/** app.js calls this when a stop marker is tapped: while a point is being chosen the stop becomes that point. */
function planPickStation(s) {
  if (!pl || !pl.pick) return false;
  const end = pl.pick;
  planPickEnd();
  planSetEnd(end, stationEp(Object.assign({}, s, { agency_name: agName(s.agency) })));
  return true;
}

// ───────────────────────────────────────────────────────────── the two ends
function planSetEnd(end, ep) {
  pl[end] = ep;
  pl.field = null;
  planRemember(ep);
  if (S.view.name !== 'plan') { openPlan(); return; }
  const i = $('#pf-' + end); if (i) i.value = epLabel(ep);
  const c = $(`[data-act=plan-clear][data-end=${end}]`); if (c) c.hidden = false;
  planCloseSug();
  drawPlanEnds();
  if (pl.from && pl.to) { if (isMobile()) setSheet('half'); planSearch(); }
  else {
    const other = end === 'from' ? 'to' : 'from';
    if (other === 'from' && !pl.from) planLocate('from', true);      // a destination is enough: start from where I am
    else setTimeout(() => { const o = $('#pf-' + other); if (o) o.focus(); }, 30);
  }
}
function planLocate(end, quiet) {
  if (!navigator.geolocation) { if (!quiet) toast(t('loc_denied')); return; }
  if (!quiet) toast(t('locating'), 5000);
  navigator.geolocation.getCurrentPosition(pos => {
    const { latitude: lat, longitude: lon } = pos.coords;
    S.me = [lat, lon];
    meLayer.clearLayers();
    L.marker(S.me, { icon: L.divIcon({ className: '', html: '<div class="me"></div>', iconSize: [0, 0] }), interactive: false }).addTo(meLayer);
    if (end && (!quiet || !pl[end])) planSetEnd(end, { kind: 'me', lat, lon, label: t('plan_my_loc') });
  }, () => { if (!quiet) toast(t('loc_denied')); const i = $('#pf-' + end); if (i) i.focus(); }, { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 });
}
function planSwap() {
  [pl.from, pl.to] = [pl.to, pl.from];
  const f = $('#pf-from'), to = $('#pf-to');
  if (f) f.value = epLabel(pl.from); if (to) to.value = epLabel(pl.to);
  $$('[data-act=plan-clear]').forEach(b => b.hidden = !pl[b.dataset.end]);
  drawPlanEnds();
  if (pl.from && pl.to) planSearch();
}
function planClear(end) {
  pl[end] = null;
  const i = $('#pf-' + end); if (i) { i.value = ''; i.focus(); }
  const c = $(`[data-act=plan-clear][data-end=${end}]`); if (c) c.hidden = true;
  pl.res = null; pl.err = null; planReq++; pl.busy = false;
  planRoute.clearLayers(); drawPlanEnds(); drawPlanRes();
}

/** Start and destination on the map: a ring and a pin; pinned points can be dragged to fine-tune them. */
function drawPlanEnds() {
  planEnds.clearLayers();
  for (const end of ['from', 'to']) {
    const ep = pl[end];
    if (!ep) continue;
    const m = L.marker([ep.lat, ep.lon], {
      icon: L.divIcon({ className: 'pend', iconSize: [0, 0], html: `<div class="pe ${end}">${end === 'to' ? ic('pin') : ''}</div>` }),
      draggable: ep.kind === 'll', keyboard: false, zIndexOffset: 900, title: epLabel(ep),
    }).addTo(planEnds);
    if (ep.kind === 'll') m.on('dragend', () => { const ll = m.getLatLng(); planSetPin(end, ll.lat, ll.lng); });
  }
}

// ───────────────────────────────────────────────────────────── suggestions
function planCloseSug() {
  pl.field = null; clearTimeout(sugTimer2);
  const s = $('#plan-sug'); if (s) { s.hidden = true; s.innerHTML = ''; }
  const r = $('#plan-res'); if (r) r.hidden = false;
}
function planInput(end, el) {
  pl.field = end;
  const q = el.value.trim();
  clearTimeout(sugTimer2);
  if (!q || (pl[end] && q === epLabel(pl[end]))) { planShowSug(end, null); return; }     // nothing new typed: the shortcuts
  sugTimer2 = setTimeout(async () => {
    const id = ++sugReq2;
    try {
      const d = await api('geocode', { q, lang: S.lang });
      if (id !== sugReq2 || pl.field !== end) return;
      planShowSug(end, d.results.map(r => r.type === 'station'
        ? { kind: 'station', lat: r.lat, lon: r.lon, label: r.name, sub: r.agency_name, agency: r.agency, station_id: r.station_id, modes: r.modes }
        : { kind: 'place', lat: r.lat, lon: r.lon, label: r.name, sub: t(r.kind === 'city' || r.kind === 'town' || r.kind === 'village' ? 'plan_town' : 'plan_hood') }));
    } catch (e) { planShowSug(end, []); }
  }, 160);
}
function planShowSug(end, found) {
  const box = $('#plan-sug'); if (!box) return;
  pl.sug = [];
  const row = (ep, icon, cls = '') => {
    pl.sug.push(ep);
    return `<div class="list-item psug-row ${cls}" data-act="plan-pick-sug" data-i="${pl.sug.length - 1}"><span class="mode-ic">${icon}</span>
      <div class="grow"><div class="ellipsis"><b>${esc(epLabel(ep))}</b></div>${ep.sub ? `<div class="muted small ellipsis">${esc(ep.sub)}</div>` : ''}</div></div>`;
  };
  let h = '';
  if (found === null) {          // nothing typed yet: the shortcuts, then favourites and recent places
    h += `<div class="list-item psug-row" data-act="plan-locate" data-end="${end}"><span class="mode-ic">${ic('target')}</span><div class="grow"><b>${esc(t('plan_my_loc'))}</b></div></div>`;
    h += `<div class="list-item psug-row" data-act="plan-pick" data-end="${end}"><span class="mode-ic">${ic('pin')}</span><div class="grow"><b>${esc(t('plan_pick_map'))}</b></div></div>`;
    const favs = S.favs.map(f => stationEp({ lat: f.lat, lon: f.lon, name: f.name, agency: f.agency, station_id: f.station_id, modes: f.modes, agency_name: agName(f.agency) })).filter(e => e.lat != null);
    if (favs.length) h += `<h2 class="sugh">${esc(t('favorites'))}</h2>` + favs.map(e => row(e, ic('star'))).join('');
    const rec = planRecents();
    if (rec.length) h += `<h2 class="sugh">${esc(t('plan_recent'))}</h2>` + rec.map(e => row(e, e.kind === 'station' ? modeIcons(e.modes) || ic('bus') : ic('history'))).join('');
  } else if (!found.length) h = `<div class="empty">${esc(t('no_results'))}</div>`;
  else h = found.map(e => row(e, e.kind === 'station' ? modeIcons(e.modes) : ic('pin'))).join('');
  box.innerHTML = h; box.hidden = false;
  const r = $('#plan-res'); if (r) r.hidden = true;
}

// ───────────────────────────────────────────────────────────── the screen
function planWhenHtml() {
  const w = pl.when, lim = pl.res && pl.res.range;
  const min = ymdIso(lim ? lim.min > todayYmd() ? lim.min : todayYmd() : todayYmd()), max = ymdIso(lim ? lim.max : ymdAdd(todayYmd(), 60));
  return `<div class="seg pmode" role="group" aria-label="${esc(t('plan_title'))}">${['now', 'dep', 'arr'].map(m =>
      `<button type="button" class="${w.mode === m ? 'on' : ''}" data-act="plan-mode" data-mode="${m}" aria-pressed="${w.mode === m}">${esc(t('plan_' + m))}</button>`).join('')}</div>
    ${w.mode === 'now' ? '' : `<div class="pdt"><input type="date" id="pw-date" value="${ymdIso(w.date)}" min="${min}" max="${max}" aria-label="${esc(t('plan_date'))}">
      <input type="time" id="pw-time" value="${esc(w.time)}" aria-label="${esc(t('plan_time'))}"></div>`}
`;
}
function planField(end) {
  const ep = pl[end];
  return `<div class="pfield" data-end="${end}"><span class="pdot ${end}" aria-hidden="true"></span>
    <input id="pf-${end}" type="text" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false" inputmode="search"
      placeholder="${esc(t('plan_' + end + '_ph'))}" aria-label="${esc(t('plan_' + end))}" value="${esc(epLabel(ep))}">
    <button type="button" class="pclear" data-act="plan-clear" data-end="${end}" aria-label="${esc(t('plan_clear'))}" ${ep ? '' : 'hidden'}>${ic('close')}</button></div>`;
}
function renderPlan(body) {
  body.innerHTML = `<div class="row" style="margin-bottom:var(--sp-3)">${backBtn()}<div class="grow title">${esc(t('plan_title'))}</div></div>
    <div class="pfields">${planField('from')}${planField('to')}
      <button type="button" class="pswap" data-act="plan-swap" title="${esc(t('plan_swap'))}" aria-label="${esc(t('plan_swap'))}">${ic('swap')}</button></div>
    <div id="plan-sug" class="psug" hidden></div>
    <div id="plan-when" class="pwhen">${planWhenHtml()}</div>
    <div id="plan-res"></div>
    <details class="popts"><summary>${esc(t('plan_options'))}</summary>
      <div class="popt"><label for="pw-walk">${esc(t('plan_walk_limit'))}</label>
        <select id="pw-walk" class="field">${[500, 1000, 2000].map(m => `<option value="${m}"${pl.maxWalk === m ? ' selected' : ''}>${m < 1000 ? m + ' m' : m / 1000 + ' km'}</option>`).join('')}</select></div></details>`;
  document.body.classList.add('planning');
  $('#pw-walk').addEventListener('change', e => { pl.maxWalk = +e.target.value; localStorage.setItem('planWalk', pl.maxWalk); pl.res = null; planSearch(); });
  for (const end of ['from', 'to']) {
    const el = $('#pf-' + end);
    el.addEventListener('input', () => { if (!el.value.trim() && pl[end]) { pl[end] = null; $(`[data-act=plan-clear][data-end=${end}]`).hidden = true; drawPlanEnds(); } planInput(end, el); });
    el.addEventListener('focus', () => { pl.field = end; if (isMobile()) setSheet('full'); el.select(); planInput(end, el); });
    el.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' && pl.sug.length && pl.field === end) { ev.preventDefault(); const first = pl.sug.find((s, i) => $(`[data-act=plan-pick-sug][data-i="${i}"]`)); if (first) planSetEnd(end, first); }
      if (ev.key === 'Escape') { el.value = epLabel(pl[end]); planCloseSug(); el.blur(); }
    });
    el.addEventListener('blur', () => setTimeout(() => { if (pl.field !== end) el.value = epLabel(pl[end]); }, 200));
  }
  wirePlanWhen();
  drawPlanEnds();
  drawPlanRes();
  if (pl.res && pl.res.journeys.length) planDrawSelected(false);
}
function wirePlanWhen() {
  const d = $('#pw-date'), tm = $('#pw-time');
  const changed = () => { pl.when.date = d.value.replace(/-/g, '') || pl.when.date; pl.when.time = tm.value || pl.when.time; pl.res = null; planSearch(); };
  if (d) d.addEventListener('change', changed);
  if (tm) tm.addEventListener('change', changed);
}
function planSetMode(m) {
  const w = pl.when;
  w.mode = m;
  if (m !== 'now' && (!w.date || !w.time)) { const d = nextFive(); w.date = dateToYmd(d); w.time = pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  pl.res = null;
  $('#plan-when').innerHTML = planWhenHtml();
  wirePlanWhen();
  planSearch();
}

// ───────────────────────────────────────────────────────────── searching
async function planSearch(o = {}) {
  if (!pl.from || !pl.to) { pl.res = null; pl.err = null; drawPlanRes(); return; }
  const my = ++planReq, w = pl.when;
  const p = { from: epSpec(pl.from), to: epSpec(pl.to), from_name: epLabel(pl.from), to_name: epLabel(pl.to), max_walk: pl.maxWalk, lang: S.lang };
  if (o.more) {
    p.mode = o.more === 'later' ? 'dep' : 'arr';
    p.t = o.more === 'later' ? pl.res.later : pl.res.earlier;
    if (w.mode === 'now') p.live = 1;
    pl.moreBusy = true;
  } else {
    p.mode = w.mode;
    if (w.mode !== 'now') { p.date = w.date; p.time = w.time; }
    if (!o.silent) { pl.busy = true; pl.err = null; }
  }
  if (!o.silent) drawPlanRes();
  try {
    const d = await api('plan', p);
    if (my !== planReq) return;
    pl.busy = pl.moreBusy = false;
    if (d.error && d.error !== 'no_route') {
      pl.err = d.error; pl.errEnd = d.end || null;
      if (!o.more && !o.silent) pl.res = null;
      if (d.range) { pl.res = pl.res || null; pl.range = d.range; }
      if (d.error === 'warming_up') setTimeout(() => { if (S.view.name === 'plan' && pl.err === 'warming_up') planSearch(); }, 5000);
      else if (!o.silent) { planRoute.clearLayers(); fitTo(L.latLngBounds([[pl.from.lat, pl.from.lon], [pl.to.lat, pl.to.lon]])); }   // show both points
    } else if (o.more && pl.res) {
      const have = new Set(pl.res.journeys.map(jKey)), add = d.journeys.filter(j => !have.has(jKey(j)));
      pl.res.journeys = [...pl.res.journeys, ...add].sort((a, b) => a.leave - b.leave || a.arrive - b.arrive);
      if (o.more === 'later') { pl.res.later = d.later; pl.noLater = !add.length; } else { pl.res.earlier = d.earlier; pl.noEarlier = !add.length; }
    } else {
      pl.err = null; pl.noLater = pl.noEarlier = false;
      pl.res = d;
      const keep = pl.selKey && d.journeys.find(j => jKey(j) === pl.selKey);
      pl.selKey = jKey(keep || d.journeys.find(j => j.fastest) || d.journeys[0] || { sig: null });
      pl.open = o.silent ? pl.open : {};
    }
    drawPlanRes();
    if (!o.more) planDrawSelected(!o.silent);
  } catch (e) {
    if (my !== planReq) return;
    pl.busy = pl.moreBusy = false;
    if (!o.silent) { pl.err = 'bad'; drawPlanRes(); }
  }
}

// ───────────────────────────────────────────────────────────── results
function legChips(j) {
  return j.legs.map(l => l.type === 'walk'
    ? `<span class="lg walk">${ic('walk')}<span class="num">${Math.max(1, Math.round(l.secs / 60))}′</span></span>`
    : `<span class="lg">${badge(l)}</span>`).join(`<span class="lsep">${ic('chev')}</span>`);
}
function jCard(j) {
  const open = jKey(j) === pl.selKey;
  const tr = j.walk_only ? '' : j.transfers === 0 ? t('plan_direct') : j.transfers === 1 ? t('plan_transfer_1') : t('plan_transfer_n').replace('{n}', j.transfers);
  const wk = t('plan_on_foot').replace('{x}', j.walk_only ? fmtM(j.walk_m) : fmtDur(j.walk_s));
  const key = esc(jKey(j)), day = dayTag(j.leave);
  const next = new Date(j.arrive * 1000).toDateString() !== new Date(j.leave * 1000).toDateString() ? '<sup class="jplus">+1</sup>' : '';
  return `<div class="jcard${open ? ' open' : ''}">
    <button type="button" class="jhead" data-act="plan-sel" data-key="${key}" aria-expanded="${open}">
      <span class="jt"><b class="num">${clock(j.leave)}</b><span class="jto">${ic('chev')}</span><b class="num">${clock(j.arrive)}</b>${next}<span class="jdur num">${esc(fmtDur(j.dur))}</span></span>
      <span class="jlegs">${legChips(j)}</span>
      <span class="jmeta">${day ? `<span class="jday">${esc(day)}</span>` : ''}${tr ? `<span>${esc(tr)}</span>` : ''}<span>${esc(wk)}</span>${j.live ? `<span class="tag live">${esc(t('live'))}</span>` : ''}${j.fastest && !j.walk_only ? `<span class="jtag">${esc(t('plan_fastest'))}</span>` : ''}</span>
    </button>${open ? jDetail(j) : ''}</div>`;
}
function stepText(s) {
  let txt = t('s_' + s.k).replace('{n}', s.exit || '');
  if (s.street && s.k !== 'dest') txt += ' (' + s.street + ')';
  return txt;
}
function jDetail(j) {
  const L_ = j.legs, k0 = jKey(j);
  const link = p => p.station_id ? ` data-act="station" data-agency="${esc(p.agency)}" data-id="${esc(p.station_id)}" data-lat="${p.lat}" data-lon="${p.lon}"` : '';
  const name = p => `<span class="jname"${link(p)}>${esc(p.name || '')}</span>`;
  const lc = l => l.type === 'walk' ? 'var(--muted)' : colors(l).bg;
  const node = (times, p, cls, prev, next) => `<li class="jn ${cls}" style="--cp:${prev ? lc(prev) : 'transparent'};--cn:${next ? lc(next) : 'transparent'}">
    <div class="jtm num">${times}</div><span class="jrail"><span class="jdot"></span></span><div class="jb">${name(p)}</div></li>`;
  let h = '<ol class="jd">';
  h += node(`<b>${clock(L_[0].dep)}</b>`, L_[0].from, 'start', null, L_[0]);
  L_.forEach((l, k) => {
    const prev = L_[k - 1], next = L_[k + 1], id = k0 + '#' + k;
    if (l.type === 'walk') {
      const showSteps = pl.open['s' + id];
      h += `<li class="jl walk" style="--c:var(--muted)"><div class="jtm"></div><span class="jrail"></span><div class="jb">
        <div class="jwalk">${ic('walk')}<b>${esc(t('plan_walk'))}</b><span class="muted">${esc(fmtM(l.m))}, ${esc(fmtDur(l.secs))}</span></div>
        ${l.steps && l.steps.length > 1 ? `<button type="button" class="linkbtn" data-act="plan-toggle" data-id="s${esc(id)}">${esc(t(showSteps ? 'plan_hide_steps' : 'plan_show_steps'))}</button>` : ''}
        ${showSteps ? `<ol class="jsteps">${l.steps.map(s => `<li><span>${esc(stepText(s))}</span>${s.m ? `<span class="muted small num">${esc(fmtM(s.m))}</span>` : ''}</li>`).join('')}</ol>` : ''}</div></li>`;
      h += next ? node(`<b>${clock(next.dep)}</b>`, next.from, '', l, next) : node(`<b>${clock(l.arr)}</b>`, l.to, 'end', l, null);
    } else {
      const showStops = pl.open['t' + id], dly = l.dep - l.dep_s, n = l.n;
      const dtag = !l.rt ? '' : Math.abs(dly) < 60 ? `<span class="tag live">${esc(t('on_time'))}</span>` : `<span class="tag ${dly > 0 ? 'late' : 'live'}"><b>${esc(fmtDelay(dly))}</b></span>`;
      h += `<li class="jl ride" style="--c:${colors(l).bg}"><div class="jtm"></div><span class="jrail"></span><div class="jb">
        <div class="row jrh" data-act="trip" data-agency="${esc(l.agency)}" data-trip="${esc(l.trip_id)}" data-date="${esc(l.date)}" data-sched="${pl.res && pl.res.live ? '' : '1'}">${badge(l)}
          <div class="grow"><div class="dest ellipsis">${esc(t('plan_towards').replace('{x}', l.headsign || ''))}</div><div class="muted small ellipsis">${esc(l.agency_name)}</div></div><span class="muted">${ic('chev')}</span></div>
        <div class="jmeta"><span>${esc(t(n === 1 ? 'plan_stop_1' : 'plan_stop_n').replace('{n}', n))}</span><span>${esc(fmtDur(l.arr - l.dep))}</span>${dtag}</div>
        ${(l.alerts || []).length ? `<button type="button" class="warnlink" data-act="plan-toggle" data-id="a${esc(id)}" aria-expanded="${!!pl.open['a' + id]}">${ic('warn')}${esc(t('plan_line_alerts'))} (${l.alerts.length})</button>` : ''}
        ${pl.open['a' + id] ? l.alerts.map(a => alertCard(a, true)).join('') : ''}
        ${n > 1 ? `<button type="button" class="linkbtn" data-act="plan-toggle" data-id="t${esc(id)}">${esc(t(showStops ? 'plan_hide_stops' : 'plan_show_stops'))}</button>` : ''}
        ${showStops ? `<ul class="jstops">${l.stops.slice(1, -1).map(s => `<li><span class="num muted">${clock(s.arr)}</span><span>${esc(s.name)}</span></li>`).join('')}</ul>` : ''}</div></li>`;
      if (!next) h += node(`<b>${clock(l.arr)}</b>`, l.to, 'end', l, null);
      else if (next.type === 'walk') h += node(`<b>${clock(l.arr)}</b>`, l.to, '', l, next);
      else h += node(`<span class="muted small">${clock(l.arr)}</span><b>${clock(next.dep)}</b>`, l.to, 'xfer', l, next);
    }
  });
  return h + '</ol>';
}
function drawPlanRes() {
  const el = $('#plan-res'); if (!el) return;
  if (!pl.from || !pl.to) { el.innerHTML = ''; return; }
  if (pl.err) {
    const key = pl.err === 'no_stops_near' ? (pl.errEnd === 'from' ? 'plan_no_stops_from' : 'plan_no_stops_to') : PLAN_ERRORS[pl.err] || 'plan_bad';
    el.innerHTML = `<div class="notice ${pl.err === 'warming_up' ? '' : 'warn'}">${esc(t(key))}</div>`;
    return;
  }
  if (pl.busy && !pl.res) { el.innerHTML = `<div class="empty">${esc(t('plan_searching'))}</div>`; return; }
  const r = pl.res;
  if (!r) { el.innerHTML = ''; return; }
  let h = '';
  if (r.walking === 'estimate') h += `<div class="notice warn small">${esc(t('plan_estimated'))}</div>`;
  if (!r.journeys.length) { el.innerHTML = h + `<div class="notice warn">${esc(t('plan_no_route'))}</div>`; return; }
  const more = (dir, off) => `<button type="button" class="linkbtn more" data-act="plan-more" data-dir="${dir}" ${pl.moreBusy || off ? 'disabled' : ''}>${esc(t(dir === 'later' ? 'plan_later' : 'plan_earlier'))}</button>`;
  h += `<div class="jmore">${more('earlier', pl.noEarlier)}</div>` + r.journeys.map(jCard).join('') + `<div class="jmore">${more('later', pl.noLater)}</div>`;
  h += `<div class="psum muted small">${esc(t(r.live ? 'plan_live_note' : 'plan_sched_note'))}</div>`;
  if (r.mode === 'now') h += refreshRow(`${t('updated_lbl')} ${clockS(r.now)}`).replace('data-act="reload"', 'data-act="plan-refresh"');
  const keep = $('#panel-body').scrollTop;
  el.innerHTML = h;
  $('#panel-body').scrollTop = keep;
}

// ───────────────────────────────────────────────────────────── the chosen journey on the map
function planDrawSelected(fit) {
  planRoute.clearLayers();
  const j = pl.res && pl.res.journeys.find(x => jKey(x) === pl.selKey);
  if (!j) return;
  const bounds = [];
  const ring = cssv('--map-ring');
  for (const l of j.legs) {
    const pts = l.shape && l.shape.length > 1 ? l.shape : [[l.from.lat, l.from.lon], [l.to.lat, l.to.lon]];
    pts.forEach(p => bounds.push(p));
    if (l.type === 'walk') {
      L.polyline(pts, { color: ring, weight: 8, opacity: .85, bubblingMouseEvents: false, interactive: false }).addTo(planRoute);
      L.polyline(pts, { color: cssv('--ink'), weight: 4, opacity: .9, dashArray: '1 8', lineCap: 'round', interactive: false }).addTo(planRoute);
    } else {
      const c = colors(l).bg;
      L.polyline(pts, { color: ring, weight: 10, opacity: .9, interactive: false }).addTo(planRoute);
      L.polyline(pts, { color: c, weight: 6, opacity: .95, interactive: false }).addTo(planRoute);
      for (const p of [l.from, l.to]) L.circleMarker([p.lat, p.lon], { radius: 6, weight: 3, color: c, fillColor: ring, fillOpacity: 1, interactive: false }).addTo(planRoute);
    }
  }
  if (fit && bounds.length) fitTo(L.latLngBounds(bounds));
}

// ───────────────────────────────────────────────────────────── actions (called by app.js for data-act="plan-*")
function planAct(a, d, el) {
  switch (a) {
    case 'plan-swap': planSwap(); break;
    case 'plan-clear': planClear(d.end); break;
    case 'plan-mode': planSetMode(d.mode); break;
    case 'plan-sel': {
      pl.selKey = d.key; pl.open = {};
      drawPlanRes(); planDrawSelected(true);
      if (isMobile() && sheetEl.dataset.state === 'full') setSheet('half');
      break;
    }
    case 'plan-toggle': pl.open[d.id] = !pl.open[d.id]; drawPlanRes(); break;
    case 'plan-more': planSearch({ more: d.dir }); break;
    case 'plan-refresh': planSearch(); break;
    case 'plan-pick-sug': { const ep = pl.sug[+d.i]; if (ep && pl.field) planSetEnd(pl.field, ep); break; }
    case 'plan-locate': { const end = d.end; planCloseSug(); planLocate(end); break; }
    case 'plan-pick': planPickStart(d.end); break;
    case 'plan-pick-cancel': planPickEnd(); break;
    case 'plan-here': map.closePopup(); menuPop = null; planSetPin(d.end, +d.lat, +d.lon); break;
    case 'plan-to-stn': case 'plan-from-stn': {
      const st = S.view.data && S.view.data.station; if (!st) break;
      openPlan(a === 'plan-to-stn' ? { to: stationEp(st) } : { from: stationEp(st) });
      break;
    }
  }
}
