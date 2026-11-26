'use strict';
/* Mugitu – front-end. Talks to the local server's /api/* endpoints. */

// ───────────────────────────────────────────────────────────── icons (inline SVG, Material-style)
const P = d => `<path d="${d}"/>`;
const STROKE = d => `<path d="${d}" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>`;
const ICONS = {
  bus: P('M4 16c0 .88.39 1.67 1 2.22V20c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h8v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1.78c.61-.55 1-1.34 1-2.22V6c0-3.5-3.58-4-8-4s-8 .5-8 4v10zm3.5 1c-.83 0-1.5-.67-1.5-1.5S6.67 14 7.5 14s1.5.67 1.5 1.5S8.33 17 7.5 17zm9 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm1.5-6H6V6h12v5z'),
  train: P('M12 2c-4 0-8 .5-8 4v9.5C4 17.43 5.57 19 7.5 19L6 20.5v.5h2.23l2-2H14l2 2h2v-.5L16.5 19c1.93 0 3.5-1.57 3.5-3.5V6c0-3.5-3.58-4-8-4zM7.5 17c-.83 0-1.5-.67-1.5-1.5S6.67 14 7.5 14s1.5.67 1.5 1.5S8.33 17 7.5 17zm3.5-7H6V6h5v4zm2 0V6h5v4h-5zm3.5 7c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5z'),
  metro: P('M12 2c-4.42 0-8 .5-8 4v9.5C4 17.43 5.57 19 7.5 19L6 20.5v.5h12v-.5L16.5 19c1.93 0 3.5-1.57 3.5-3.5V6c0-3.5-3.58-4-8-4zM7.5 17c-.83 0-1.5-.67-1.5-1.5S6.67 14 7.5 14s1.5.67 1.5 1.5S8.33 17 7.5 17zm3.5-6H6V6h5v5zm5.5 6c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zM18 11h-5V6h5v5z'),
  tram: P('M19 16.94V8.5c0-2.79-2.61-3.4-6.01-3.49l.76-1.51H17V2H7v1.5h4.75l-.76 1.52C7.86 5.11 5 5.73 5 8.5v8.44c0 1.45 1.19 2.66 2.59 2.97L6 21.5v.5h2.23l2-2H14l2 2h2v-.5L16.5 20h-.08c1.69 0 2.58-1.37 2.58-3.06zm-7 1.56c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm5-4.5H7V9h10v5z'),
  funicular: '<path fill-rule="evenodd" d="M2.5 6.2l19-3.4.35 2L13 6.9V9h4.5a2.5 2.5 0 0 1 2.5 2.5v7a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 18.5v-7A2.5 2.5 0 0 1 6.5 9H11V7.3L2.15 8.2zM7 12v4h10v-4z"/>',
  ferry: P('M20 21c-1.39 0-2.78-.47-4-1.32-2.44 1.71-5.56 1.71-8 0C6.78 20.53 5.39 21 4 21H2v2h2c1.38 0 2.74-.35 4-.99 2.52 1.29 5.48 1.29 8 0 1.26.65 2.62.99 4 .99h2v-2h-2zM3.95 19H4c1.6 0 3.02-.88 4-2 .98 1.12 2.4 2 4 2s3.02-.88 4-2c.98 1.12 2.4 2 4 2h.05l1.89-6.68c.08-.26.06-.54-.06-.78s-.34-.42-.6-.5L20 10.62V6c0-1.1-.9-2-2-2h-3V1H9v3H6c-1.1 0-2 .9-2 2v4.62l-1.29.42c-.26.08-.48.26-.6.5s-.15.52-.06.78L3.95 19zM6 6h12v3.97L12 8 6 9.97V6z'),
  target: P('M12 8c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm8.94 3c-.46-4.17-3.77-7.48-7.94-7.94V1h-2v2.06C6.83 3.52 3.52 6.83 3.06 11H1v2h2.06c.46 4.17 3.77 7.48 7.94 7.94V23h2v-2.06c4.17-.46 7.48-3.77 7.94-7.94H23v-2h-2.06zM12 19c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z'),
  star: P('M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z'),
  starO: P('M22 9.24l-7.19-.62L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21 12 17.27 18.18 21l-1.63-7.03L22 9.24zM12 15.4l-3.76 2.27 1-4.28-3.32-2.88 4.38-.38L12 6.1l1.71 4.04 4.38.38-3.32 2.88 1 4.28L12 15.4z'),
  warn: P('M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z'),
  back: P('M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z'),
  refresh: P('M17.65 6.35C16.2 4.9 14.21 4 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08c-.82 2.33-3.04 4-5.65 4-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z'),
  chev: P('M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z'),
  close: P('M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z'),
  route: STROKE('M4 19c4 0 3-7 8-7s4-7 8-7'),
  pin: P('M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z'),
  tune: P('M3 17v2h6v-2H3zM3 5v2h10V5H3zm10 16v-2h8v-2h-8v-2h-2v6h2zM7 9v2H3v2h4v2h2V9H7zm14 4v-2H11v2h10zm-6-4h2V7h4V5h-4V3h-2v6z'),
  info: P('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z'),
  calendar: P('M19 4h-1V2h-2v2H8V2H6v2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2zm0 16H5V10h14v10zm0-12H5V6h14v2zM7 12h5v5H7z'),
  globe: P('M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zm6.93 6h-2.95a15.65 15.65 0 0 0-1.38-3.56A8.03 8.03 0 0 1 18.92 8zM12 4.04c.83 1.2 1.48 2.53 1.91 3.96h-3.82c.43-1.43 1.08-2.76 1.91-3.96zM4.26 14C4.1 13.36 4 12.69 4 12s.1-1.36.26-2h3.38c-.08.66-.14 1.32-.14 2 0 .68.06 1.34.14 2H4.26zm.82 2h2.95c.32 1.25.78 2.45 1.38 3.56A7.987 7.987 0 0 1 5.08 16zm2.95-8H5.08a7.987 7.987 0 0 1 4.33-3.56A15.65 15.65 0 0 0 8.03 8zM12 19.96c-.83-1.2-1.48-2.53-1.91-3.96h3.82c-.43 1.43-1.08 2.76-1.91 3.96zM14.34 14H9.66c-.09-.66-.16-1.32-.16-2 0-.68.07-1.35.16-2h4.68c.09.65.16 1.32.16 2 0 .68-.07 1.34-.16 2zm.25 5.56c.6-1.11 1.06-2.31 1.38-3.56h2.95a8.03 8.03 0 0 1-4.33 3.56zM16.36 14c.08-.66.14-1.32.14-2 0-.68-.06-1.34-.14-2h3.38c.16.64.26 1.31.26 2s-.1 1.36-.26 2h-3.38z'),
  sun: P('M6.76 4.84l-1.8-1.79-1.41 1.41 1.79 1.79 1.42-1.41zM4 10.5H1v2h3v-2zm9-9.95h-2V3.5h2V.55zm7.45 3.91l-1.41-1.41-1.79 1.79 1.41 1.41 1.79-1.79zm-3.21 13.7l1.79 1.8 1.41-1.41-1.8-1.79-1.4 1.4zM20 10.5v2h3v-2h-3zm-8-5c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm-1 16.95h2V19.5h-2v2.95zm-7.45-3.91l1.41 1.41 1.79-1.8-1.41-1.41-1.79 1.8z'),
  moon: P('M12 3c-4.97 0-9 4.03-9 9s4.03 9 9 9 9-4.03 9-9c0-.46-.04-.92-.1-1.36-.98 1.37-2.58 2.26-4.4 2.26-2.98 0-5.4-2.42-5.4-5.4 0-1.81.89-3.42 2.26-4.4-.44-.06-.9-.1-1.36-.1z'),
  search: P('M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z'),
  link: P('M19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z'),
  car: P('M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 4a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm0 12.2c-2.1 0-3.9-1.1-5-2.7.03-1.65 3.3-2.55 5-2.55s4.97.9 5 2.55c-1.1 1.6-2.9 2.7-5 2.7z'),
  share: P('M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92s2.92-1.31 2.92-2.92-1.31-2.92-2.92-2.92z'),
  person: P('M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z'),
};
const ic = (name, cls = '') => `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">${ICONS[name] || ''}</svg>`;

// ───────────────────────────────────────────────────────────── state & helpers
const MODES = ['bus', 'train', 'metro', 'tram', 'funicular', 'ferry'];
const CHIP_MODES = MODES.filter(m => m !== 'ferry');
/** Read a design token from :root (the canvas map layers cannot resolve var()). */
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const MODE_COLOR = Object.fromEntries(MODES.map(m => [m, cssv('--mode-' + m)]));
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const EH_BOUNDS = [[41.95, -3.45], [43.6, -0.7]];   // Euskal Herria: Euskadi, Nafarroa and Ipar Euskal Herria
/** The three administrative areas are listed side by side, with the same weight. 'eh' = networks covering several. */
const REGIONS = ['eus', 'nav', 'ipar', 'eh'];
const regionName = r => t('region_' + (r || 'eus'));
/** [region, agencies[]] for every area that has operators, in a fixed order. */
const byRegion = list => REGIONS.map(r => [r, list.filter(a => (a.region || 'eus') === r)]).filter(([, l]) => l.length);
const POLL_VEHICLES_MS = 15000;
const POLL_VIEW_MS = 20000;
// Zoom thresholds, the same for every mode. Stops: shown from this zoom, whatever they serve (bus, train, metro...).
// Live vehicles: drawn one by one from VEHICLE_MIN_ZOOM; zoomed further out they are grouped into count bubbles,
// so the opening view of the whole territory is never empty.
const STOP_MIN_ZOOM = 13;
const VEHICLE_MIN_ZOOM = 10;
const CLUSTER_PX = 76;        // size of the grid cell of a vehicle bubble, in screen pixels

/** Languages in the order shown in the selectors: Euskara, Español, Français, English. */
const LANGS = [['eu', 'Euskara'], ['es', 'Español'], ['fr', 'Français'], ['en', 'English']];
/** Everybody starts in Basque, whatever the language of their browser. Only a language the user picks is remembered
 *  (under its own key: the old 'lang' key also held languages that were merely detected, so it is ignored and removed). */
const DEFAULT_LANG = 'eu';
const LANG_KEY = 'langChoice';
/** localStorage that never throws: site data can be blocked, and a stored value can be corrupt. */
const ls = {
  get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* not persisted */ } },
  del: k => { try { localStorage.removeItem(k); } catch (e) { /* nothing to remove */ } },
  json: (k, dflt) => { try { const v = localStorage.getItem(k); return v == null ? dflt : JSON.parse(v); } catch (e) { return dflt; } },
};
ls.del('lang');

const S = {
  lang: ls.get(LANG_KEY) || DEFAULT_LANG,
  tab: 'stops',
  view: { name: 'home' },
  hist: [],
  agencies: {},          // id -> summary
  vehicles: [],
  feeds: {},
  skew: 0,               // server time - client time (s)
  filters: { modes: new Set(MODES), agencies: null, gps: true, est: true, sched: true, showStops: true, line: null },
  focus: null,           // {agency, route_id?, trip_id?} while a trip / route view is open
  selVeh: null,          // selected vehicle id
  favs: ls.json('favs', []),
  nearby: null,
  me: null,
  alerts: [],
  linesAgency: ls.get('linesAgency') || '',
  routesCache: {},
  mapStyle: ls.get('mapStyle') === 'detailed' ? 'detailed' : 'simple',
};
if (!I18N[S.lang]) S.lang = DEFAULT_LANG;
try {
  const f = ls.json('filters2', null);
  if (f) {
    S.filters.modes = new Set(f.modes); S.filters.agencies = f.agencies ? new Set(f.agencies) : null;
    S.filters.gps = f.gps !== false; S.filters.est = f.est !== false; S.filters.sched = f.sched !== false; S.filters.showStops = f.showStops !== false; S.filters.line = f.line || null;
  }
} catch (e) { /* ignore */ }
function saveFilters() {
  const f = S.filters;
  ls.set('filters2', JSON.stringify({ modes: [...f.modes], agencies: f.agencies ? [...f.agencies] : null, gps: f.gps, est: f.est, sched: f.sched, showStops: f.showStops, line: f.line }));
  updateAlertBadge();
}

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const t = k => (I18N[S.lang] && I18N[S.lang][k]) || I18N.en[k] || k;
const fold = s => String(s == null ? '' : s).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nowTs = () => Date.now() / 1000 + S.skew;
const pad = n => String(n).padStart(2, '0');
const clock = ts => { const d = new Date(ts * 1000); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
const clockS = ts => { const d = new Date(ts * 1000); return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); };
const saveFavs = () => ls.set('favs', JSON.stringify(S.favs));
const isFav = (a, id) => S.favs.some(f => f.agency === a && f.station_id === id);
const agName = id => (S.agencies[id] && S.agencies[id].name) || id;
const modeLabel = m => t('mode_' + m);
const modeSvg = (m, cls = '') => `<span class="mi ${cls}" style="color:${MODE_COLOR[m] || MODE_COLOR.bus}">${ic(m in ICONS ? m : 'bus')}</span>`;
const modeIcons = modes => (modes || '').split(',').filter(Boolean).map(m => modeSvg(m)).join('');
const stationModes = s => (s.modes || 'bus').split(',').filter(Boolean);

async function api(path, params) {
  const usp = new URLSearchParams();
  for (const [k, val] of Object.entries(params || {})) Array.isArray(val) ? val.forEach(x => usp.append(k, x)) : usp.set(k, val);
  const qs = params ? '?' + usp.toString() : '';
  const r = await fetch('/api/' + path + qs, { signal: AbortSignal.timeout(25000), cache: 'no-store' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}

/** "Updated 30 s ago" in the current language (word order differs, e.g. Basque). */
function updatedAgo(ts) {
  const sec = Math.max(0, Math.round(nowTs() - ts));
  const long = sec >= 90;
  const n = long ? Math.round(sec / 60) : sec;
  return t('upd_ago').replace('{n}', n).replace('{u}', t(long ? 'unit_min' : 'unit_s'));
}

function fmtDelay(sec) {
  if (sec == null) return '';
  const m = Math.round(sec / 60);
  if (Math.abs(sec) < 60) return t('on_time');
  return (m > 0 ? '+' : '−') + Math.abs(m) + ' ' + t('min') + ' ' + (m > 0 ? t('late') : t('early'));
}
/** Passengers on board, as reported by Lurraldebus. */
const occChip = n => n == null ? '' : `<span class="occ" title="${esc(t('occupancy_hint'))}">${ic('person', 'xs')}<span class="num">${esc(n)}</span><span class="sr-only"> ${esc(t('occupancy'))}</span></span>`;
const FLAGS = ['drop_off_only', 'pick_up_only'];
const flagTags = fl => (fl || []).filter(f => FLAGS.includes(f)).map(f => `<span class="tag flag">${t('flag_' + f)}</span>`).join('');

function lum(hex) {
  const n = parseInt(hex, 16); const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); };
  return .2126 * f((n >> 16) & 255) + .7152 * f((n >> 8) & 255) + .0722 * f(n & 255);
}
const isHex = c => /^[0-9a-fA-F]{6}$/.test(c || '');
function contrast(a, b) { const x = lum(a), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); }

/** Resolve badge colours for a line {color,text_color,mode}. */
function colors(o) {
  let bg = isHex(o.color) ? o.color : null;
  if (!bg || lum(bg) > .8) bg = MODE_COLOR[o.mode] ? MODE_COLOR[o.mode].slice(1) : '2d6cdf';
  const fg = isHex(o.text_color) && contrast(bg, o.text_color) >= 3.5 ? o.text_color : (lum(bg) > .45 ? '111111' : 'ffffff');
  return { bg: '#' + bg, fg: '#' + fg };
}
function badge(o) {
  const c = colors(o);
  const l = o.line || '';
  const inner = l.length > 9 ? ic(o.mode in ICONS ? o.mode : 'bus') : esc(l);
  return `<span class="lb" style="background:${c.bg};color:${c.fg}">${inner}</span>`;
}

// ───────────────────────────────────────────────────────────── i18n
function applyI18n() {
  document.documentElement.lang = S.lang;
  $$('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  $$('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); el.setAttribute('aria-label', el.placeholder); });
  $$('[data-i18n-aria]').forEach(el => el.setAttribute('aria-label', t(el.dataset.i18nAria)));
  $$('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); el.setAttribute('aria-label', el.title); });
}

// ───────────────────────────────────────────────────────────── map
const map = L.map('map', { zoomControl: false, attributionControl: false, renderer: L.canvas({ tolerance: 12 }), tap: true, maxZoom: 19, zoomAnimation: !reduceMotion.matches }).fitBounds(EH_BOUNDS, { animate: false });
L.control.zoom({ position: 'bottomright' }).addTo(map);   // hidden on phones: pinch instead
L.control.attribution({ prefix: false }).addTo(map);
let baseLayers = [], glLayer = null, basemapReq = 0;
const OSM_CREDIT = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, <a href="https://opendata.euskadi.eus/">Open Data Euskadi</a>, <a href="https://transport.data.gouv.fr/">transport.data.gouv.fr</a>';
const OFM_CREDIT = '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">© OpenMapTiles</a> Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>, <a href="https://opendata.euskadi.eus/">Open Data Euskadi</a>, <a href="https://transport.data.gouv.fr/">transport.data.gouv.fr</a>';

// "Simple" is OpenFreeMap's vector basemap: Positron (light theme) or Fiord (dark theme), with place names in Basque.
// "Detailed" is the standard OpenStreetMap raster style. Vector tiles are drawn by MapLibre GL inside the Leaflet map.
const OFM_STYLES = 'https://tiles.openfreemap.org/styles/';
const ofmCache = {};          // 'positron' | 'fiord' -> Promise of the style (fetched once, already in Basque)
/** The tiles carry every OSM language as name:xx. The styles label with name_en (English); use name:eu instead, and the
 *  local name (the style's own fallback) where a place has no Basque name. */
function basqueLabels(style) {
  const swap = x => Array.isArray(x) ? (x.length === 2 && x[0] === 'get' && x[1] === 'name_en' ? ['get', 'name:eu'] : x.map(swap)) : x;
  for (const l of style.layers) if (l.layout && l.layout['text-field'] !== undefined) l.layout['text-field'] = swap(l.layout['text-field']);
  return style;
}
function ofmStyle(name) {
  return ofmCache[name] || (ofmCache[name] = fetch(OFM_STYLES + name).then(r => {
    if (!r.ok) throw new Error('OpenFreeMap style: HTTP ' + r.status);
    return r.json();
  }).then(basqueLabels).catch(e => { delete ofmCache[name]; throw e; }));
}
const webglOk = () => { try { return !!(window.maplibregl && document.createElement('canvas').getContext('webgl2')); } catch (e) { return false; } };
function dropBasemap() {
  baseLayers.forEach(l => map.removeLayer(l)); baseLayers = [];
  if (glLayer) { map.removeLayer(glLayer); glLayer = null; }
}
function rasterBasemap() {
  baseLayers = [L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: OSM_CREDIT })];
  baseLayers.forEach((l, n) => { l.addTo(map); l.setZIndex(n); });
}
async function applyBasemap() {
  const my = ++basemapReq, el = $('#map');
  const detailed = S.mapStyle === 'detailed';
  el.classList.toggle('osm', detailed);
  if (detailed) { dropBasemap(); rasterBasemap(); el.style.background = ''; return; }
  // the simple style needs WebGL and OpenFreeMap; without them the map falls back to the OpenStreetMap raster tiles
  const fallback = () => { if (my === basemapReq && !glLayer) { dropBasemap(); rasterBasemap(); el.classList.add('osm'); el.style.background = ''; } };
  if (!webglOk()) { fallback(); return; }
  try {
    const style = await ofmStyle(document.documentElement.dataset.theme === 'dark' ? 'fiord' : 'positron');
    if (my !== basemapReq) return;                           // the theme or the style changed meanwhile
    const bg = (style.layers.find(l => l.type === 'background') || {}).paint;
    el.style.background = bg && typeof bg['background-color'] === 'string' ? bg['background-color'] : '';   // no flash while tiles load
    const copy = structuredClone(style);                    // MapLibre may modify what it is given
    if (glLayer) glLayer.getMaplibreMap().setStyle(copy);    // theme switch: same map, same tiles, new colours
    else {
      dropBasemap();
      glLayer = L.maplibreGL({ style: copy, attributionControl: { customAttribution: OFM_CREDIT } }).addTo(map);
    }
  } catch (e) { console.warn(e); fallback(); }
}
const vehLayer = L.layerGroup().addTo(map);
const cluLayer = L.layerGroup().addTo(map);
const stnLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
const meLayer = L.layerGroup().addTo(map);
const selLayer = L.layerGroup().addTo(map);
const selVehLayer = L.layerGroup().addTo(map);
const markers = new Map();   // vehicle id -> {m, v, key}
map.on('zoomstart', () => $('#map').classList.add('noanim'));
map.on('zoomend', () => setTimeout(() => $('#map').classList.remove('noanim'), 50));
function zoomClass() { const z = map.getZoom(), m = $('#map'); m.classList.toggle('compact', z <= 12); m.classList.toggle('dense', z <= 11); }
map.on('zoomend', zoomClass); zoomClass();

function toast(msg, ms = 2500) {
  const el = $('#map-toast'); el.textContent = msg; el.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => el.hidden = true, ms);
}
const isMobile = () => window.innerWidth <= 800;

// ── bottom sheet (phones). States: closed (handle only), half, full. Moves with transform, never height.
const sheetEl = $('#sheet'), tabsEl = $('#tabs');
let sheetOff = 0;
function sheetOffsets() {
  const h = sheetEl.offsetHeight;
  return { closed: Math.max(0, h - 32), half: Math.max(0, h - Math.round(window.innerHeight * .42)), full: 0 };
}
function setSheet(state) {
  sheetEl.dataset.state = state;
  if (!isMobile()) { sheetEl.style.removeProperty('--off'); sheetEl.style.removeProperty('--pad'); $('#panel-body').inert = false; return; }
  sheetOff = sheetOffsets()[state];
  sheetEl.style.setProperty('--off', sheetOff + 'px');
  sheetEl.style.setProperty('--pad', sheetOff + 'px');
  $('#panel-body').inert = state === 'closed';
}
/** Pixels at the bottom of the screen covered by the tab bar and the visible part of the sheet. */
function coverBottom() { return isMobile() ? tabsEl.offsetHeight + sheetEl.offsetHeight - sheetOff : 0; }
function coverTop() { return isMobile() ? 120 : 0; }
function expandSheet() { if (isMobile() && sheetEl.dataset.state === 'closed') setSheet('half'); }
(function sheetDrag() {
  const handle = $('#sheet-handle');
  let y0 = null, off0 = 0, moved = false, lastY = 0, lastT = 0, vel = 0;
  const cycle = () => setSheet({ closed: 'half', half: 'full', full: 'half' }[sheetEl.dataset.state]);
  handle.addEventListener('pointerdown', e => {
    if (!isMobile()) return;
    handle.setPointerCapture(e.pointerId);
    y0 = e.clientY; off0 = sheetOff; moved = false; vel = 0; lastY = e.clientY; lastT = e.timeStamp;
    sheetEl.classList.add('dragging');
  });
  handle.addEventListener('pointermove', e => {
    if (y0 === null) return;
    const dy = e.clientY - y0;
    if (Math.abs(dy) > 4) moved = true;
    sheetOff = Math.min(sheetOffsets().closed, Math.max(0, off0 + dy));
    sheetEl.style.setProperty('--off', sheetOff + 'px');
    vel = (e.clientY - lastY) / Math.max(1, e.timeStamp - lastT); lastY = e.clientY; lastT = e.timeStamp;
  });
  const end = () => {
    if (y0 === null) return;
    y0 = null; sheetEl.classList.remove('dragging');
    if (!moved) { cycle(); return; }
    const o = sheetOffsets(), target = sheetOff + vel * 180;   // a flick carries the sheet to the next stop
    setSheet(Object.keys(o).reduce((a, b) => Math.abs(o[a] - target) <= Math.abs(o[b] - target) ? a : b));
  };
  handle.addEventListener('pointerup', end);
  handle.addEventListener('pointercancel', end);
  handle.addEventListener('click', e => { if (e.detail === 0) cycle(); });   // keyboard
  window.addEventListener('resize', () => setSheet(sheetEl.dataset.state));
})();

/** Pan so that a point is visible next to the side panel / above the bottom sheet. */
function showPoint(lat, lon, zoom) {
  const pad = isMobile() ? { paddingTopLeft: [0, coverTop()], paddingBottomRight: [0, coverBottom()] } : {};
  if (zoom && map.getZoom() < zoom) flyTo([lat, lon], zoom);
  else map.panInside([lat, lon], Object.assign({ padding: [60, 60], animate: !reduceMotion.matches }, pad));
}
/** Fly so that `ll` sits in the middle of the part of the map the sheet and search bar leave visible. */
function flyTo(ll, zoom, dur = .5) {
  const z = zoom || map.getZoom();
  const d = isMobile() ? (coverBottom() - coverTop()) / 2 : 0;
  const c = map.unproject(map.project(ll, z).add([0, d]), z);
  reduceMotion.matches ? map.setView(c, z, { animate: false }) : map.flyTo(c, z, { duration: dur });
}
function fitTo(bounds) {
  const o = isMobile() ? { paddingTopLeft: [20, coverTop()], paddingBottomRight: [20, coverBottom() + 20] } : { padding: [30, 30] };
  map.fitBounds(bounds, Object.assign(o, { animate: !reduceMotion.matches }));
}

// ───────────────────────────────────────────────────────────── vehicles
function hasScope() { const a = S.filters.agencies; return !!S.filters.line || (a && a.size > 0 && a.size <= 3); }
/** Too far out to draw each vehicle: they are grouped into bubbles (unless a line / trip / few operators are picked). */
function vehiclesClustered() { return map.getZoom() < VEHICLE_MIN_ZOOM && !hasScope() && !S.focus; }
function vehicleVisible(v) {
  const f = S.filters;
  if (!f.modes.has(v.mode)) return false;
  if (f.agencies && !f.agencies.has(v.agency)) return false;
  if (f.line && !(v.agency === f.line.agency && v.route_id === f.line.route_id)) return false;
  if (!v.est && !v.sched && !f.gps) return false;
  if (v.est && !f.est) return false;
  if (v.sched && !f.sched) return false;
  const fo = S.focus;
  if (fo && S.selVeh !== v.id) {
    if (fo.trip_id) return v.agency === fo.agency && v.trip_id === fo.trip_id;
    if (fo.route_id) return v.agency === fo.agency && v.route_id === fo.route_id;
  }
  return true;
}
function vehicleIcon(v) {
  const c = colors(v);
  let txt = v.mode === 'metro' && (v.line || '').length > 5 ? 'M' : (v.line || '');
  if (txt.length > 7) txt = txt.slice(0, 6) + '…';
  const late = v.delay != null && v.delay >= 300;
  // the marker is a pill: as wide as its text needs, never narrower than a circle
  const w = Math.max(30, Math.round(txt.length * 7.6 + 16));
  let arrow = '';
  if (v.bearing != null) {   // the arrow orbits the pill: distance from the centre to its edge along the heading, plus a gap
    const th = v.bearing * Math.PI / 180, rx = w / 2, ry = 15;
    const edge = 1 / Math.sqrt(Math.pow(Math.sin(th) / rx, 2) + Math.pow(Math.cos(th) / ry, 2));
    arrow = `<span class="arrow" style="transform:rotate(${Math.round(v.bearing)}deg) translateY(-${Math.round(edge + 9)}px);--ac:${c.bg}"></span>`;
  }
  const html = `<div class="v ${v.sched ? 'sched' : v.est ? 'est' : 'gps'}${late ? ' late' : ''}${v.mode === 'train' || v.mode === 'metro' || v.mode === 'tram' ? ' sq' : ''}" style="background:${c.bg};color:${c.fg};min-width:${w}px;--ac:${c.bg}">${arrow}<span class="vt">${esc(txt)}</span></div>`;
  return L.divIcon({ className: 'veh', html, iconSize: [0, 0] });
}
function vehKey(v) { return [v.line, v.color, v.mode, v.est, v.sched, v.delay != null && v.delay >= 300, v.bearing != null ? Math.round(v.bearing / 5) : '-'].join('|'); }

/** Group vehicles into screen-grid cells: [{n, lat, lon, modes, pts}]. */
function clusterVehicles(list) {
  const z = map.getZoom(), cells = new Map();
  for (const v of list) {
    const p = map.project([v.lat, v.lon], z);
    const k = Math.floor(p.x / CLUSTER_PX) + ':' + Math.floor(p.y / CLUSTER_PX);
    let c = cells.get(k);
    if (!c) cells.set(k, c = { n: 0, lat: 0, lon: 0, modes: {}, pts: [] });
    c.n++; c.lat += v.lat; c.lon += v.lon; c.modes[v.mode] = (c.modes[v.mode] || 0) + 1; c.pts.push([v.lat, v.lon]);
  }
  return [...cells.values()].map(c => Object.assign(c, { lat: c.lat / c.n, lon: c.lon / c.n }));
}
function clusterIcon(c) {
  const kinds = Object.keys(c.modes);
  const size = Math.round(Math.min(58, 30 + Math.sqrt(c.n) * 5));
  // one mode: that mode's colour with text that contrasts with it; mixed: the theme's ink colours (dark on light, light on dark)
  const mc = kinds.length === 1 ? MODE_COLOR[kinds[0]] : '';
  const style = mc ? `background:${mc};color:${isHex(mc.slice(1)) && lum(mc.slice(1)) > .45 ? '#111' : '#fff'}` : '';
  // every bubble counts all its vehicles (GPS, estimated and theoretical alike) and looks the same
  return L.divIcon({ className: 'vclu', iconSize: [size, size],
    html: `<div class="cl${mc ? '' : ' mix'}" style="width:${size}px;height:${size}px;${style}"><b class="num">${c.n}</b></div>` });
}
function drawClusters(list) {
  cluLayer.clearLayers();
  for (const c of clusterVehicles(list)) {
    const m = L.marker([c.lat, c.lon], { icon: clusterIcon(c), keyboard: false, riseOnHover: true });
    m.on('click', () => {   // zoom in until the vehicles of this bubble are drawn one by one
      const b = L.latLngBounds(c.pts);
      flyTo(b.getCenter(), Math.min(Math.max(map.getBoundsZoom(b.pad(.25)), map.getZoom() + 1), VEHICLE_MIN_ZOOM + 2));
    });
    m.addTo(cluLayer);
  }
}

function drawVehicles() {
  const vis = S.vehicles.filter(vehicleVisible);
  const clustered = vehiclesClustered();
  const shown = clustered ? vis.filter(v => v.id === S.selVeh) : vis;   // the selected one is always drawn alone
  if (clustered) drawClusters(vis.filter(v => v.id !== S.selVeh)); else cluLayer.clearLayers();
  const seen = new Set();
  for (const v of shown) {
    seen.add(v.id);
    let e = markers.get(v.id);
    if (!e) {
      const m = L.marker([v.lat, v.lon], { icon: vehicleIcon(v), riseOnHover: true, keyboard: false });
      m.on('click', () => openVehicle(v.id));
      m.addTo(vehLayer);
      e = { m, v, key: vehKey(v) };
      markers.set(v.id, e);
    } else {
      e.v = v;
      e.m.setLatLng([v.lat, v.lon]);
      const k = vehKey(v);
      if (k !== e.key) { e.m.setIcon(vehicleIcon(v)); e.key = k; }
    }
    e.m.setZIndexOffset(v.id === S.selVeh ? 2000 : v.sched ? -1000 : v.est ? 0 : 500);
  }
  for (const [id, e] of markers) if (!seen.has(id)) { vehLayer.removeLayer(e.m); markers.delete(id); }
  selVehLayer.clearLayers();
  const sel = S.selVeh && markers.get(S.selVeh);
  if (sel) L.circleMarker(sel.m.getLatLng(), { radius: 22, color: cssv('--map-sel'), weight: 3, fillColor: cssv('--map-sel'), fillOpacity: .15, interactive: false }).addTo(selVehLayer);
  const el = $('#veh-count'); if (el) el.textContent = vis.length;
}

// ───────────────────────────────────────────────────────────── vehicle in the sidebar
function findVehicle(view) {
  if (view.vid) return S.vehicles.find(v => v.id === view.vid);
  return S.vehicles.find(v => v.agency === view.agency && v.trip_id === view.trip);
}
function vehCardInner(v) {
  const stat = v.status === 1 ? t('at_stop') : v.status === 0 ? t('incoming') : t('next_stop');
  const late = v.delay != null && v.delay >= 300;
  return `<div class="row"><span class="mi" style="color:${colors(v).bg}">${ic(v.mode in ICONS ? v.mode : 'bus', 'lg')}</span>
      <div class="grow"><b>${t('vehicle')}${v.label ? ' ' + esc(v.label) : ''}</b> <span class="muted small">${esc(v.agency_name)}</span></div>
      ${v.delay != null ? `<span class="tag ${late ? 'late' : v.delay < 60 ? 'live' : ''}"><b>${esc(fmtDelay(v.delay))}</b></span>` : ''}</div>
    ${v.stop ? `<div class="kv"><span class="muted">${stat}</span><b>${esc(v.stop)}</b></div>` : ''}
    ${v.speed != null ? `<div class="kv"><span class="muted">${t('speed')}</span><b>${v.speed} km/h</b></div>` : ''}
    ${v.occupancy != null ? `<div class="kv"><span class="muted">${t('occupancy')}</span><b>${occChip(v.occupancy)}</b></div>` : ''}
    ${v.ts ? `<div class="muted small" style="margin-top:4px">${updatedAgo(v.ts)}</div>` : ''}
    <div class="muted small" style="margin-top:4px">${v.sched ? t('position_sched') : v.est ? t('position_est') : t('position_gps')}</div>`;
}
function vehCard(view) {
  const v = findVehicle(view);
  return `<div class="card" id="veh-card"${v ? '' : ' hidden'}>${v ? vehCardInner(v) : ''}</div>`;
}
function refreshVehCard() {
  const el = $('#veh-card'); if (!el) return;
  const v = findVehicle(S.view);
  el.hidden = !v; if (v) el.innerHTML = vehCardInner(v);
}
function openVehicle(id) {
  const e = markers.get(id); if (!e) return;
  const v = e.v;
  S.selVeh = id;
  showPoint(v.lat, v.lon);
  if (v.trip_id) go({ name: 'trip', agency: v.agency, trip: v.trip_id, date: v.date || '', vid: id, data: null }, S.tab === 'lines' ? 'lines' : 'stops');
  else go({ name: 'vehicle', vid: id }, S.tab === 'lines' ? 'lines' : 'stops');
}
function renderVehicle(body) {
  const v = findVehicle(S.view);
  if (!v) { body.innerHTML = `<div class="row" style="margin-bottom:8px"><button type="button" class="btn small" data-act="back">${ic('back')}${t('back')}</button></div><div class="empty">${t('no_results')}</div>`; return; }
  body.innerHTML = `<div class="row" style="margin-bottom:8px"><button type="button" class="btn small" data-act="back">${ic('back')}${t('back')}</button></div>
    <div class="row" style="margin-bottom:8px">${badge(v)}<div class="grow"><div class="title">${esc(v.headsign || v.line)}</div><div class="muted small">${esc(v.agency_name)}</div></div></div>
    ${vehCard(S.view)}${vehActions(v)}`;
}
function vehActions(v) {
  return `<div class="row wrap" style="margin:8px 0">
    ${v.route_id ? `<button type="button" class="btn small" data-act="route" data-agency="${esc(v.agency)}" data-route="${esc(v.route_id)}">${ic('route')}${t('route_on_map')}</button>` : ''}
    ${v.route_id ? `<button type="button" class="btn small" data-act="only-line" data-agency="${esc(v.agency)}" data-route="${esc(v.route_id)}" data-line="${esc(v.line)}">${t('only_line')}</button>` : ''}</div>`;
}

let vehBusy = false;
/** Map area to cover with live bus data: only sent while buses are actually shown (keeps Lurraldebus requests down). */
function vehicleView() {
  if (!S.filters.modes.has('bus') || vehiclesClustered()) return undefined;
  const b = map.getBounds();
  const r = x => x.toFixed(3);
  return { s: r(b.getSouth()), w: r(b.getWest()), n: r(b.getNorth()), e: r(b.getEast()) };
}
let lastPoll = 0, moveTimer;
map.on('moveend', () => {   // a new area should not wait for the 15 s poll to start being tracked
  clearTimeout(moveTimer);
  moveTimer = setTimeout(() => { if (Date.now() - lastPoll > 5000) pollVehicles(); }, 1200);
});
async function pollVehicles() {
  if (vehBusy || document.hidden) return;
  vehBusy = true; lastPoll = Date.now();
  try {
    const d = await api('vehicles', vehicleView());
    S.skew = d.time - Date.now() / 1000;
    S.vehicles = d.vehicles; S.feeds = d.feeds;
    drawVehicles();
    refreshVehCard();
    if (S.view.name === 'vehicle') renderVehicle($('#panel-body'));
    if (S.tab === 'live') renderLive(true);
  } catch (e) { console.warn(e); } finally { vehBusy = false; }
}

// ───────────────────────────────────────────────────────────── quick filter overlay (modes + active filters)
const allModes = () => CHIP_MODES.every(m => S.filters.modes.has(m));
/** With every mode showing nothing looks selected; tapping a mode then shows only that mode. */
function modeChip(m) {
  const on = !allModes() && S.filters.modes.has(m);
  return `<button type="button" class="chip mode${on ? ' on' : ''}" data-act="mode" data-mode="${m}" aria-pressed="${on}"><span class="mi" style="color:${MODE_COLOR[m]}">${ic(m)}</span>${modeLabel(m)}</button>`;
}
function toggleMode(m) {
  const f = S.filters;
  if (allModes()) f.modes = new Set([m]);
  else if (f.modes.has(m)) { f.modes.delete(m); if (!CHIP_MODES.some(x => f.modes.has(x))) f.modes = new Set(MODES); }
  else { f.modes.add(m); if (allModes()) f.modes = new Set(MODES); }
}
function renderMapFilter() {
  const f = S.filters;
  let h = `<div class="chips" role="group" aria-label="${t('filter_modes')}">${CHIP_MODES.map(modeChip).join('')}</div>`;
  const act = [];
  if (f.line) act.push(`<button type="button" class="chip on" data-act="clear-line" aria-label="${t('clear_filter')}"><b>${esc(f.line.line)}</b> ${esc(agName(f.line.agency))}${ic('close', 'xs')}</button>`);
  if (f.agencies && f.agencies.size && f.agencies.size <= 3) f.agencies.forEach(a => act.push(`<button type="button" class="chip on" data-act="clear-agency" data-id="${esc(a)}" aria-label="${t('clear_filter')}">${esc(agName(a))}${ic('close', 'xs')}</button>`));
  if (act.length) h += `<div class="chips">${act.join('')}</div>`;
  $('#mapfilter').innerHTML = h;
}
map.on('zoomend', () => { drawVehicles(); renderMapFilter(); });
L.DomEvent.disableClickPropagation($('#mapfilter'));
function filtersChanged() { saveFilters(); drawVehicles(); renderMapFilter(); loadStations(); if (S.view.name === 'alerts') drawAlerts(); if (S.tab === 'live') renderLive(); }

// ───────────────────────────────────────────────────────────── stations layer
let stnReq = 0;
async function loadStations() {
  stnLayer.clearLayers();
  if (!S.filters.showStops) return;
  const z = map.getZoom(); if (z < STOP_MIN_ZOOM) return;
  const b = map.getBounds(); const id = ++stnReq;
  try {
    const d = await api('stations', { s: b.getSouth(), w: b.getWest(), n: b.getNorth(), e: b.getEast() });
    if (id !== stnReq) return;
    stnLayer.clearLayers();
    const f = S.filters;
    for (const s of d.stations) {
      const ms = stationModes(s);
      if (!ms.some(m => f.modes.has(m))) continue;
      if (f.agencies && !f.agencies.has(s.agency)) continue;
      const railMode = ms.find(x => x !== 'bus');
      const mk = L.circleMarker([s.lat, s.lon], {
        radius: (z >= 16 ? 7 : z >= 14 ? 6 : 5) + (railMode ? 1.5 : 0), bubblingMouseEvents: false, weight: 1.5, color: cssv('--map-ring'),
        fillColor: MODE_COLOR[railMode || ms[0]] || '#2d6cdf', fillOpacity: 1,
      });
      mk.bindTooltip(esc(s.name), { direction: 'top', offset: [0, -4] });
      mk.on('click', () => openStation(s.agency, s.station_id));
      mk.addTo(stnLayer);
    }
  } catch (e) { console.warn(e); }
}
let stnTimer;
map.on('moveend', () => { clearTimeout(stnTimer); stnTimer = setTimeout(loadStations, 250); });

// ───────────────────────────────────────────────────────────── date picker (theoretical timetables)
const ymdToDate = ymd => new Date(+ymd.slice(0, 4), +ymd.slice(4, 6) - 1, +ymd.slice(6, 8), 12);
const dateToYmd = d => d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate());
const ymdAdd = (ymd, n) => { const d = ymdToDate(ymd); d.setDate(d.getDate() + n); return dateToYmd(d); };
const ymdIso = ymd => ymd.slice(0, 4) + '-' + ymd.slice(4, 6) + '-' + ymd.slice(6, 8);
const ymdLong = ymd => ymdToDate(ymd).toLocaleDateString(S.lang, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
const ymdShort = ymd => ymdToDate(ymd).toLocaleDateString(S.lang, { day: 'numeric', month: 'short', year: 'numeric' });
const pickErr = e => t(e === 'bad_date' ? 'date_out_of_range' : e);
const ymdMedium = ymd => ymdToDate(ymd).toLocaleDateString(S.lang, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
/** "Today", "Tomorrow", "In 3 days", "2 days ago" in the current language. */
function ymdRelative(ymd, today) {
  const diff = Math.round((ymdToDate(ymd) - ymdToDate(today)) / 86400000);
  let txt;
  try { txt = new Intl.RelativeTimeFormat(S.lang, { numeric: 'auto' }).format(diff, 'day'); } catch (e) { txt = ymdLong(ymd); }
  return txt.charAt(0).toUpperCase() + txt.slice(1);
}
/** Date selector at the top of the station and line views. The row never changes size: [<] [date] [>],
 *  with the relative day and the "Today" shortcut on a line below (hidden, not removed, while on today). */
function dateBar(v) {
  const r = v.range;
  if (!r) return '';
  const cur = v.date || r.today;
  const atMin = cur <= r.min, atMax = cur >= r.max, isToday = cur === r.today;
  return `<div class="datebar${isToday ? '' : ' other'}">
    <div class="datepill">
      <button type="button" class="dstep" data-act="date-step" data-step="-1" ${atMin ? 'disabled' : ''} title="${t('prev_day')}" aria-label="${t('prev_day')}">${ic('back')}</button>
      <button type="button" class="dpick" data-act="date-pick" title="${t('date_label')}" aria-label="${t('date_label')}: ${esc(ymdLong(cur))}">${ic('calendar')}<span>${esc(ymdMedium(cur))}</span></button>
      <input type="date" class="date-hidden" data-act="date-set" value="${ymdIso(cur)}" min="${ymdIso(r.min)}" max="${ymdIso(r.max)}" tabindex="-1" aria-hidden="true">
      <button type="button" class="dstep" data-act="date-step" data-step="1" ${atMax ? 'disabled' : ''} title="${t('next_day')}" aria-label="${t('next_day')}">${ic('chev')}</button>
    </div>
    <div class="dateinfo"><span class="rel">${esc(ymdRelative(cur, r.today))}</span>
      <button type="button" class="linkbtn" data-act="date-today" ${isToday ? 'hidden' : ''}>${t('today')}</button></div></div>`;
}
/** Apply a new date to the open station / line view. In the station view today means live data (date = null);
 *  the line view always shows the timetable of its date. */
function applyDate(date) {
  const v = S.view, r = v.range;
  if (date && r && (date < r.min || date > r.max)) { toast(t('date_out_of_range')); return renderDateUi(); }
  if (v.name === 'station') {
    if (date && r && date === r.today) date = null;
    if ((date || null) === (v.date || null)) return renderDateUi();
    v.date = date; v.share = null; v.lineSel = null; v.scroll = null; v.scrolled = false; v.data = null; render();
  } else { v.date = date; drawRouteTT(); }
}
function renderDateUi() { if (S.view.name === 'station' && S.view.data) drawStationHeader($('#panel-body')); else if (S.view.name === 'route') drawRouteTT(); }

// ───────────────────────────────────────────────────────────── navigation
function resetOverlays() { clearRouteLayer(); selLayer.clearLayers(); S.selVeh = null; setFocus(null); }
function setTab(tab) {
  S.tab = tab; S.hist = []; S.view = { name: tab === 'stops' ? 'home' : tab === 'lines' ? 'lines' : tab };
  resetOverlays();
  render();
}
/** Push the current view on the history stack and switch to `view` (inside `tab`). */
function go(view, tab) {
  S.hist.push({ view: S.view, tab: S.tab });
  history.pushState(null, '', location.href);   // so the phone's Back button steps back inside the app
  S.view = view; S.tab = tab || S.tab;
  expandSheet(); render();
}
function back() {
  const h = S.hist.pop();
  if (!h) { setTab(S.tab === 'lines' ? 'lines' : 'stops'); return; }
  S.view = h.view; S.tab = h.tab;
  resetOverlays();
  if (S.view.name === 'station' || S.view.name === 'trip') S.view.data = null;
  if (S.view.vid) S.selVeh = S.view.vid;
  render();
}
window.addEventListener('popstate', () => { if (S.hist.length) back(); else setHash(); });
const DETAIL_VIEWS = ['station', 'trip', 'vehicle', 'route'];
/** Leave a station / trip / vehicle / line view and show the whole network again. */
function closeDetail() {
  const n = S.hist.length;
  if (S.view.name === 'route' && S.filters.line) { S.filters.line = null; filtersChanged(); }   // that filter came with opening the line
  S.hist = [];
  S.view = { name: S.tab === 'lines' ? 'lines' : 'home' };
  resetOverlays();
  render();
  if (n) history.go(-n);   // drop the browser entries those views pushed
}
function setFocus(f) { S.focus = f; drawVehicles(); }
function clearRouteLayer() { routeLayer.clearLayers(); }

function render() {
  $$('#tabs button').forEach(b => { const on = b.dataset.tab === S.tab; b.classList.toggle('active', on); on ? b.setAttribute('aria-current', 'true') : b.removeAttribute('aria-current'); });
  const body = $('#panel-body');
  const v = S.view.name;
  if (v === 'home') renderHome(body);
  else if (v === 'station') renderStation(body);
  else if (v === 'trip') renderTrip(body);
  else if (v === 'vehicle') renderVehicle(body);
  else if (v === 'live') renderLive();
  else if (v === 'lines') renderLines(body);
  else if (v === 'route') renderRoute(body);
  else if (v === 'alerts') renderAlerts(body);
  else if (v === 'info') renderInfo(body);
  updateTitle();
  setHash();
}
/** The document title says where the user is: the stop, line or trip being viewed, else the section. */
function updateTitle() {
  const v = S.view, d = v.data;
  let part = '';
  if (v.name === 'station' && d && d.station) part = d.station.name;
  else if (v.name === 'trip' && d) part = [d.line, d.headsign].filter(Boolean).join(' → ');
  else if (v.name === 'route' && d) part = [d.line, d.long].filter(Boolean).join(' ');
  else if (S.tab !== 'stops') part = t('tab_' + S.tab);
  document.title = part ? part + ' · Mugitu' : t('app_title');
}
function setHash() {
  const v = S.view;
  let h = '';
  if (v.name === 'station') h = '#s=' + encodeURIComponent(v.agency + '|' + v.id + (v.date ? '|' + v.date : ''));
  else if (v.name === 'route') h = '#r=' + encodeURIComponent(v.agency + '|' + v.route);
  else if (v.name === 'trip') h = '#t=' + encodeURIComponent(v.agency + '|' + v.trip + (v.sched && v.date ? '|' + v.date : ''));
  history.replaceState(null, '', h || location.pathname);
}
const backBtn = () => `<button type="button" class="btn small" data-act="back">${ic('back')}${t('back')}</button>`;
const refreshRow = txt => `<div class="row muted small" style="margin-top:8px"><span>${txt}</span><div class="grow"></div><button type="button" class="btn small" data-act="reload">${ic('refresh')}${t('refresh')}</button></div>`;

// ───────────────────────────────────────────────────────────── home (favourites / nearby)
function stationRow(s, meta = '') {
  return `<div class="list-item" data-act="station" data-agency="${esc(s.agency)}" data-id="${esc(s.station_id)}" data-lat="${s.lat}" data-lon="${s.lon}">
    <span class="mode-ic">${modeIcons(s.modes)}</span>
    <div class="grow"><div class="ellipsis"><b>${esc(s.name)}</b></div><div class="muted small ellipsis">${esc(s.agency_name || agName(s.agency))}</div></div>
    ${meta ? `<span class="muted small num">${meta}</span>` : ''}<span class="muted">${ic('chev')}</span></div>`;
}
function renderHome(body) {
  let h = '';
  const imp = Object.values(S.agencies).filter(a => !a.ready).length;
  if (imp) h += `<div class="notice small">${t('importing')} (${imp})</div>`;
  h += `<button type="button" class="btn primary block" data-act="locate">${ic('target')}${t('nearby')}</button>`;
  if (S.nearby) {
    h += `<h2>${t('nearby_title')}</h2>`;
    h += S.nearby.length ? S.nearby.map(s => stationRow(s, `${s.dist} ${t('m')}`)).join('') : `<div class="empty">${t('no_nearby')}</div>`;
  }
  h += `<h2>${t('favorites')}</h2>`;
  if (!S.favs.length) h += `<div class="empty">${t('no_favorites')}</div>`;
  else h += S.favs.map((f, i) => `<div class="fav" data-act="station" data-agency="${esc(f.agency)}" data-id="${esc(f.station_id)}">
      <div class="row"><span class="mode-ic">${modeIcons(f.modes)}</span><div class="grow ellipsis"><b>${esc(f.name)}</b> <span class="muted small">${esc(agName(f.agency))}</span></div>
      <button type="button" class="star" data-act="unfav" data-i="${i}" title="${t('remove_fav')}" aria-label="${t('remove_fav')}">${ic('star')}</button></div>
      <div class="fav-next muted small" id="fav-${i}">…</div></div>`).join('');
  body.innerHTML = h;
  loadFavNext();
}
async function loadFavNext() {
  await Promise.all(S.favs.map(async (f, i) => {
    try {
      const d = await api('departures', { agency: f.agency, station: f.station_id, limit: 3 });
      const el = $('#fav-' + i); if (!el || S.view.name !== 'home') return;
      el.innerHTML = d.items && d.items.length ? d.items.map(it => {
        const min = Math.round((it.expected - nowTs()) / 60);
        return `<div class="row" style="margin-top:4px">${badge(it)}<span class="grow ellipsis">${esc(it.headsign)}</span><b class="num" style="color:${it.rt ? 'var(--good)' : 'var(--text)'}">${min < 1 ? t('now') : min < 60 ? min + ' ' + t('min') : clock(it.expected)}</b></div>`;
      }).join('') : t('no_deps');
    } catch (e) { /* ignore */ }
  }));
}

// ───────────────────────────────────────────────────────────── station view
function openStation(agency, id, date) {
  const cur = S.view;
  if (cur.name === 'station' && cur.agency === agency && cur.id === id && !date) return;
  resetOverlays();
  const view = { name: 'station', agency, id, data: null, date: date || null };
  if (cur.name === 'station') { S.view = view; S.tab = S.tab === 'lines' ? 'lines' : 'stops'; expandSheet(); render(); }
  else go(view, S.tab === 'lines' ? 'lines' : 'stops');
}
let depReq = 0;
async function renderStation(body) {
  const v = S.view;
  const my = ++depReq;
  if (!v.data) body.innerHTML = `<div class="empty">${t('loading')}</div>`;
  try {
    // live: with a line picked the server returns only that line; otherwise it also sends the lines of the stop for the chips
    const params = { agency: v.agency, station: v.id, kind: 'dep', limit: 20 };
    if (v.date) params.date = v.date;
    else if (v.lineSel && v.lineSel.size) params.line = [...v.lineSel];
    else params.lines = '1';
    const d = await api('departures', params);
    if (my !== depReq || S.view !== v) return;
    if (d.error === 'date_out_of_range' && v.date) { v.range = d.range; v.date = null; v.data = null; toast(t('date_out_of_range')); return renderStation(body); }
    if (d.error) { body.innerHTML = `<div class="empty">${esc(d.error)}</div>`; return; }
    v.data = d; v.range = d.range; S.skew = d.time - Date.now() / 1000; updateTitle();
    if (d.lines) v.chipItems = d.lines;     // the lines calling here today, for the filter chips
    drawStationHeader(body);
    if (v.scroll != null) { body.scrollTop = v.scroll; v.scroll = null; v.scrolled = true; }
    else if (v.date && !v.scrolled) { v.scrolled = true; scrollToUpcoming(body); }
    const st = d.station;
    selLayer.clearLayers();
    L.circleMarker([st.lat, st.lon], { radius: 13, color: cssv('--map-sel'), weight: 3, fillOpacity: .1, interactive: false }).addTo(selLayer);
    if (v.fresh !== true) { v.fresh = true; flyTo([st.lat, st.lon], Math.max(map.getZoom(), 15), .6); }
  } catch (e) {
    if (!v.data) body.innerHTML = `<div class="empty">${t('error')}</div>`;
  }
}
function drawStationHeader(body) {
  const v0 = S.view, d = v0.data; const st = d.station;
  const fav = isFav(st.agency, st.station_id);
  let h = `<div class="row" style="margin-bottom:8px">${backBtn()}<div class="grow"></div>
    <button type="button" class="btn small" data-act="focus-stn">${ic('target')}${t('on_map')}</button>
    <button type="button" class="btn small icon-only" data-act="share-start" aria-pressed="${!!v0.share}" title="${t('share')}" aria-label="${t('share')}">${ic('share')}</button>
    <button type="button" class="star" data-act="fav" title="${fav ? t('remove_fav') : t('add_fav')}" aria-label="${fav ? t('remove_fav') : t('add_fav')}">${ic(fav ? 'star' : 'starO')}</button></div>
    <div class="row" style="margin-bottom:8px"><span class="mode-ic lg">${modeIcons(st.modes)}</span>
      <div class="grow"><div class="title">${esc(st.name)}</div><div class="muted small">${esc(st.agency_name)}</div></div></div>`;
  h += dateBar(S.view);
  if (d.date) {
    h += schedList(d);
    if (v0.share) h += shareBar();
    const keep = body.scrollTop;
    body.innerHTML = h; body.scrollTop = keep; paintShare();
    return;
  }
  h += lineChips(v0.chipItems, v0.lineSel);
  h += `<div id="dep-list">${depList(d)}</div>`;
  if ((d.alerts || []).length) h += `<details class="alerts-fold"><summary>${ic('warn')}${t('tab_alerts')} (${d.alerts.length})</summary>${d.alerts.map(a => alertCard(a, true)).join('')}</details>`;
  h += refreshRow(`${t('updated_lbl')} ${clockS(d.time)}`);
  if (v0.share) h += shareBar();
  const keep = body.scrollTop;
  body.innerHTML = h; body.scrollTop = keep; paintShare();
}
/** Full-day theoretical timetable of a station: line filter + calls grouped by hour. */
const lineKey = it => it.agency + '|' + it.route_id;
/** One chip per line calling at the open stop (none when only one line does). Like the transport-mode chips:
 *  nothing picked = every line is shown; picking one shows only it, picking more adds them, un-picking the last
 *  one shows everything again. */
function lineChips(items, sel) {
  const lines = new Map();
  (items || []).forEach(it => { if (!lines.has(lineKey(it))) lines.set(lineKey(it), it); });
  if (lines.size < 2) return '';
  const on = k => !!sel && sel.has(k);
  const sorted = [...lines.entries()].sort((a, b) => a[1].line.localeCompare(b[1].line, undefined, { numeric: true }));
  return `<div class="chips linechips${sel && sel.size ? ' sel' : ''}" role="group" aria-label="${t('filter_line')}">` +
    sorted.map(([k, it]) => `<button type="button" class="lchip${on(k) ? ' on' : ''}" data-act="line-filter" data-key="${esc(k)}" aria-pressed="${on(k)}">${badge(it)}</button>`).join('') + '</div>';
}
function toggleLine(v, key) {
  const keys = [...new Set((v.date ? v.data.items : (v.chipItems || v.data.items)).map(lineKey))];
  const sel = v.lineSel || (v.lineSel = new Set());
  if (!sel.size) sel.add(key);
  else if (sel.has(key)) sel.delete(key);
  else { sel.add(key); if (sel.size >= keys.length) sel.clear(); }
}
function schedList(d) {
  const v = S.view;
  const items = v.lineSel && v.lineSel.size ? d.items.filter(it => v.lineSel.has(lineKey(it))) : d.items;
  let h = lineChips(d.items, v.lineSel);
  if (!items.length) return h + `<div class="empty">${t('no_service_date')}</div>`;
  h += `<div class="small muted" style="margin:8px 0 2px">${t('services_n').replace('{n}', items.length)}</div>`;
  const now = nowTs(); let hour = null, marked = false;
  for (const [i, it] of items.entries()) {
    const hh = clock(it.sched).slice(0, 2);
    if (hh !== hour) { hour = hh; h += `<h3 class="region hourh">${hh}:00</h3>`; }
    const up = !marked && it.sched >= now && d.date === dateToYmd(new Date());
    if (up) marked = true;
    h += `<div class="dep" ${up ? 'id="upcoming" ' : ''}${v.share ? `data-act="share-pick" data-i="${i}"` : 'data-act="trip"'} data-sched="1" data-agency="${esc(it.agency)}" data-trip="${esc(it.trip_id)}" data-date="${esc(it.date)}">
      ${badge(it)}<div class="grow"><div class="dest ellipsis">${esc(it.headsign || it.line)}</div></div>
      <div class="when"><div class="big">${clock(it.sched)}</div></div></div>`;
  }
  return h;
}
function scrollToUpcoming(body) {
  const el = $('#upcoming'); if (!el) return;
  body.scrollTop = el.getBoundingClientRect().top - body.getBoundingClientRect().top + body.scrollTop - 8;
}
function depList(d) {
  if (!d.items.length) return `<div class="empty">${t('no_deps')}</div>`;
  const now = nowTs();
  const sharing = S.view.name === 'station' && S.view.share;
  return d.items.map((it, i) => {
    const mins = Math.round((it.expected - now) / 60);
    const big = mins < 1 ? t('now') : mins < 60 ? mins + ' ' + t('min') : clock(it.expected);
    const late = it.delay >= 300;
    let tag;
    const dl = Math.abs(it.delay) >= 60 ? `<span class="tag"><span class="${late ? 'late' : ''}">${esc(fmtDelay(it.delay))}</span></span>` : '';
    if (it.cancelled) tag = `<span class="tag late">${t(it.skipped ? 'not_served' : 'cancelled')}</span>`;
    else if (it.rt === 'rt') tag = `<span class="tag live">${t('live')}</span>${dl}`;
    else if (it.rt === 'est') tag = `<span class="tag est">${t('estimated')}</span>${dl}`;
    else tag = `<span class="tag">${t('scheduled')}</span>`;
    tag += flagTags(it.flags);
    if (it.occupancy != null) tag += occChip(it.occupancy);
    const second = mins < 60 && mins >= 1 ? `<div class="muted small">${clock(it.expected)}</div>` : (Math.abs(it.delay) >= 60 ? `<div class="muted small">${t('sched_short')} ${clock(it.sched)}</div>` : '');
    return `<div class="dep${it.cancelled ? ' cancelled' : ''}" ${sharing ? `data-act="share-pick" data-i="${i}"` : 'data-act="trip"'} data-agency="${esc(it.agency || S.view.agency)}" data-trip="${esc(it.trip_id)}" data-date="${esc(it.date)}">
      ${badge(it)}<div class="grow"><div class="dest ellipsis">${esc(it.headsign || it.line)}</div><div class="tags">${tag}</div></div>
      <div class="when"><div class="big${mins < 3 && !it.cancelled ? ' soon' : ''}">${big}</div>${second}</div></div>`;
  }).join('');
}

// ───────────────────────────────────────────────────────────── alerts
function alertText(o) {
  if (!o) return '';
  return o[S.lang] || o['eu'] || o['es'] || o['es-ES'] || o['fr'] || o['en'] || Object.values(o).find(Boolean) || '';
}
function alertVisible(a) {
  const f = S.filters;
  if (f.agencies && !f.agencies.has(a.agency)) return false;
  if (a.modes && a.modes.length && !a.modes.some(m => f.modes.has(m))) return false;
  if (f.line) {
    if (a.agency !== f.line.agency) return false;
    if (a.route_ids && a.route_ids.length && !a.route_ids.includes(f.line.route_id)) return false;
  }
  return true;
}
function alertCard(a, compact) {
  const url = alertText(a.url), head = alertText(a.header), desc = alertText(a.description);
  return `<div class="alert-card small">
    <div class="alert-top">${ic('warn')}<b>${esc(a.agency_name)}</b>${(a.lines || []).length ? `<span class="muted">${esc(a.lines.slice(0, 6).join(', '))}${a.lines.length > 6 ? '…' : ''}</span>` : ''}</div>
    ${head ? `<div>${esc(head)}</div>` : ''}
    ${desc ? `<div class="muted" style="margin-top:3px">${esc(desc).slice(0, compact ? 240 : 600)}</div>` : ''}
    ${a.end ? `<div class="muted">${t('until')} ${new Date(a.end * 1000).toLocaleString()}</div>` : ''}
    ${url ? `<div><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${t('more')}${ic('link', 'xs')}</a></div>` : ''}</div>`;
}
function updateAlertBadge() {
  const c = $('#alert-count'); if (!c) return;
  const n = S.alerts.filter(alertVisible).length;
  c.hidden = !n; c.textContent = n;
}
async function loadAlerts() {
  try { S.alerts = (await api('alerts')).alerts; } catch (e) { return; }
  updateAlertBadge();
  if (S.view.name === 'alerts') drawAlerts();
}
function renderAlerts(body) {
  body.innerHTML = `<input type="search" id="alerts-q" autocomplete="off" placeholder="${t('alerts_filter')}" style="margin-bottom:8px"><div id="alerts-list"></div>`;
  $('#alerts-q').oninput = drawAlerts; drawAlerts();
}
function drawAlerts() {
  const el = $('#alerts-list'); if (!el) return;
  const q = fold($('#alerts-q').value);
  const vis = S.alerts.filter(alertVisible);
  const rows = vis.filter(a => !q || fold(alertText(a.header) + ' ' + alertText(a.description) + ' ' + a.agency_name + ' ' + (a.lines || []).join(' ')).includes(q));
  const hidden = S.alerts.length - vis.length;
  el.innerHTML = (hidden > 0 ? `<div class="small muted" style="margin-bottom:8px">${t('alerts_hidden').replace('{n}', hidden)}</div>` : '') +
    (rows.length ? rows.slice(0, 200).map(a => alertCard(a, false)).join('') : `<div class="empty">${t('no_alerts')}</div>`);
}

// ───────────────────────────────────────────────────────────── trip view
function openTrip(agency, trip, date, sched) {
  go({ name: 'trip', agency, trip, date, sched: !!sched, data: null }, S.tab === 'lines' ? 'lines' : 'stops');
}
let tripReq = 0;
async function renderTrip(body) {
  const v = S.view; const my = ++tripReq;
  if (!v.data) body.innerHTML = `<div class="empty">${t('loading')}</div>`;
  try {
    const d = await api('trip', { agency: v.agency, trip: v.trip, date: v.date || '', sched: v.sched ? '1' : '' });
    if (my !== tripReq || S.view !== v) return;
    if (d.error) { body.innerHTML = `<div class="row" style="margin-bottom:8px">${backBtn()}</div><div class="empty">${esc(t(d.error) === d.error ? d.error : pickErr(d.error))}</div>`; return; }
    v.data = d; updateTitle();
    const sched = !!d.sched_only;
    const veh = sched ? null : findVehicle(v);
    if (veh && S.selVeh !== veh.id) S.selVeh = veh.id;
    const now = nowTs();
    const c = colors(d);
    const idx = sched ? -2 : d.stops.findIndex(s => s.expected >= now - 30);
    let h = `<div class="row" style="margin-bottom:8px">${backBtn()}<div class="grow"></div>
      <button type="button" class="btn small" data-act="route" data-agency="${esc(d.agency)}" data-route="${esc(d.route_id)}">${ic('route')}${t('route_on_map')}</button>
      <button type="button" class="btn small icon-only" data-act="share-start" aria-pressed="${!!v.share}" title="${t('share')}" aria-label="${t('share')}">${ic('share')}</button></div>
      <div class="row" style="margin-bottom:6px">${badge(d)}<div class="grow"><div class="title">${esc(d.headsign)}</div><div class="muted small">${esc(agName(d.agency))}${sched ? ' · ' + esc(ymdLong(d.date)) : ''}</div></div></div>
      ${sched ? '' : vehCard(v)}`;
    if (sched) h += d.runs ? '' : `<div class="notice warn small">${t('trip_not_running')}</div>`;
    else if (d.cancelled) h += `<div class="notice bad small">${ic('close', 'xs')}${t('cancelled')}</div>`;
    else if (!d.has_rt) h += `<div class="notice small">${t('rt_none')}</div>`;
    h += `<ul class="tl" style="--c:${c.bg}">` + d.stops.map((s, i) => {
      const dl = s.expected - s.sched;
      const cls = (sched ? '' : (i < idx || idx < 0 ? 'past' : '') + (i === idx ? ' here' : '')) + (s.skipped ? ' skipped' : '');
      return `<li class="${cls}" ${v.share ? `data-act="share-pick" data-i="${i}"` : 'data-act="station"'} data-agency="${esc(d.agency)}" data-id="${esc(s.station_id)}" data-lat="${s.lat}" data-lon="${s.lon}">
        <div class="grow nm">${esc(s.name)}</div>
        <div class="tm"><b>${clock(s.expected)}</b>${Math.abs(dl) >= 60 ? `<div class="small ${dl >= 300 ? 'late' : 'muted'}">${t('sched_short')} ${clock(s.sched)}</div>` : ''}</div></li>`;
    }).join('') + '</ul>';
    if (!sched) h += refreshRow(`${t('updated_lbl')} ${clockS(now)}`);
    if (v.share) h += shareBar();
    const keep = body.scrollTop;
    body.innerHTML = h; body.scrollTop = keep; paintShare();
    // a live vehicle keeps the user's own zoom and position; only a scheduled trip is framed
    drawTripOnMap(d, idx, !v.fitted && !veh && !v.vid); v.fitted = true;
    setFocus({ agency: d.agency, trip_id: sched ? '' : d.trip_id });   // a timetable for another date shows no live vehicles
  } catch (e) { if (!v.data) body.innerHTML = `<div class="empty">${t('error')}</div>`; }
}
function drawTripOnMap(d, idx, fit) {
  clearRouteLayer(); selLayer.clearLayers();
  const c = colors(d).bg;
  const pts = d.shape && d.shape.length ? d.shape : d.stops.filter(s => s.lat).map(s => [s.lat, s.lon]);
  const pl = L.polyline(pts, { color: c, weight: 5, opacity: .8, bubblingMouseEvents: false }).addTo(routeLayer);
  d.stops.forEach((s, i) => {
    if (!s.lat) return;
    L.circleMarker([s.lat, s.lon], { radius: i === idx ? 8 : 5, weight: 2, color: cssv('--map-ring'), fillColor: i === idx ? cssv('--ink') : c, fillOpacity: 1, bubblingMouseEvents: false })
      .bindTooltip(`${esc(s.name)} <b>${clock(s.expected)}</b>`).on('click', () => openStation(d.agency, s.station_id)).addTo(routeLayer);
  });
  if (fit) fitTo(pl.getBounds());
}

// ───────────────────────────────────────────────────────────── live map tab (filters)
function renderLive(soft) {
  const body = $('#panel-body');
  if (soft && $('#live-root')) { updateLiveCounts(); return; }
  const f = S.filters;
  body.innerHTML = `<div id="live-root"><div class="card"><b id="veh-count" class="num">0</b> ${t('vehicles_shown')}</div>
    <h2>${t('filter_modes')}</h2><div class="chips">${CHIP_MODES.map(modeChip).join('')}</div>
    <h2>${t('map_style')}</h2>
    <div class="seg" role="group" aria-label="${t('map_style')}">${['simple', 'detailed'].map(k => `<button type="button" class="${S.mapStyle === k ? 'on' : ''}" data-act="mapstyle" data-style="${k}" aria-pressed="${S.mapStyle === k}">${t('style_' + k)}</button>`).join('')}</div>
    ${f.line ? `<h2>${t('filter_line')}</h2><div class="chips"><button type="button" class="chip on" data-act="clear-line"><b>${esc(f.line.line)}</b> ${esc(agName(f.line.agency))}${ic('close', 'xs')}</button></div>` : ''}
    <h2>${t('veh_kinds')}</h2>
    <div class="checks kinds">${['gps', 'est', 'sched'].map(k => `<label><input type="checkbox" data-act="opt" data-opt="${k}" ${f[k] ? 'checked' : ''}>
      <span class="veh kind-ic" aria-hidden="true"><span class="v ${k}"><span class="vt">12</span></span></span>
      <span class="grow"><b>${t('kind_' + k)}</b><span class="muted small">${t('kind_' + k + '_d')}</span></span>
      <span class="small muted num" id="kc-${k}"></span></label>`).join('')}</div>
    <h2>${t('filter_agencies')}</h2>
    <div class="row wrap" style="margin-bottom:8px"><button type="button" class="btn small" data-act="ag-all">${t('all')}</button><button type="button" class="btn small" data-act="ag-none">${t('none')}</button></div>
    <div class="checks" id="ag-checks"></div>
    <div class="checks" style="margin-top:24px">
      <label><input type="checkbox" data-act="opt" data-opt="showStops" ${f.showStops ? 'checked' : ''}><span class="grow">${t('show_stops')}</span></label></div></div>`;
  updateLiveCounts();
}
function updateLiveCounts() {
  const el = $('#ag-checks'); if (!el) return;
  const live = {}, theo = {}, kinds = { gps: 0, est: 0, sched: 0 };
  S.vehicles.forEach(v => {
    const k = v.sched ? 'sched' : v.est ? 'est' : 'gps'; kinds[k]++;
    const c = v.sched ? theo : live; c[v.agency] = (c[v.agency] || 0) + 1;
  });
  for (const k in kinds) { const e = $('#kc-' + k); if (e) e.textContent = kinds[k]; }
  // every operator, in one list: those with live vehicles first, then those drawn from the timetable, then the rest
  const list = Object.values(S.agencies).filter(a => a.ready);
  const rank = a => live[a.id] ? 0 : theo[a.id] ? 1 : 2;
  const tag = a => live[a.id] ? `<span class="small tag live">${live[a.id]} ${t('live_vehicles')}</span>`
    : theo[a.id] ? `<span class="small tag">${theo[a.id]} ${t('sched_vehicles')}</span>` : `<span class="small muted">${t('no_vehicles')}</span>`;
  el.innerHTML = list.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name)).map(a =>
    `<label><input type="checkbox" data-act="ag" data-id="${esc(a.id)}" ${!S.filters.agencies || S.filters.agencies.has(a.id) ? 'checked' : ''}>
    <span class="grow">${esc(a.name)}</span>${tag(a)}</label>`).join('');
  const vc = $('#veh-count'); if (vc) vc.textContent = S.vehicles.filter(vehicleVisible).length;
}

// ───────────────────────────────────────────────────────────── lines tab
async function renderLines(body) {
  const ags = Object.values(S.agencies).filter(a => a.ready).sort((a, b) => a.name.localeCompare(b.name));
  if (!S.linesAgency || !S.agencies[S.linesAgency]) S.linesAgency = (ags.find(a => a.id === 'euskotren') || ags[0] || {}).id || '';
  body.innerHTML = `<select class="field" id="lines-ag" aria-label="${t('pick_agency')}">${byRegion(ags).map(([r, l]) => `<optgroup label="${esc(regionName(r))}">${l.map(a => `<option value="${esc(a.id)}"${a.id === S.linesAgency ? ' selected' : ''}>${esc(a.name)}${a.rt.vehicles || a.rt.trips ? ' (' + t('live').toLowerCase() + ')' : ''}</option>`).join('')}</optgroup>`).join('')}</select>
    <input type="search" id="lines-q" placeholder="${t('filter_lines')}" autocomplete="off" style="margin:8px 0"><div id="lines-list"><div class="empty">${t('loading')}</div></div>`;
  $('#lines-ag').onchange = e => { S.linesAgency = e.target.value; ls.set('linesAgency', S.linesAgency); renderLines(body); };
  $('#lines-q').oninput = drawLinesList;
  if (!S.linesAgency) return;
  if (!S.routesCache[S.linesAgency]) {
    try { S.routesCache[S.linesAgency] = (await api('routes', { agency: S.linesAgency })).routes; } catch (e) { $('#lines-list').innerHTML = `<div class="empty">${t('error')}</div>`; return; }
  }
  drawLinesList();
}
function drawLinesList() {
  const el = $('#lines-list'); if (!el) return;
  const q = fold($('#lines-q').value);
  const rs = (S.routesCache[S.linesAgency] || []).filter(r => !q || fold(r.line + ' ' + r.long).includes(q)).slice(0, 300);
  el.innerHTML = rs.length ? rs.map(r => `<div class="list-item" data-act="route" data-agency="${esc(S.linesAgency)}" data-route="${esc(r.route_id)}">${badge(r)}<div class="grow ellipsis">${esc(r.long || '')}</div><span class="muted">${ic('chev')}</span></div>`).join('') : `<div class="empty">${t('no_results')}</div>`;
}
function openRoute(agency, route) {
  go({ name: 'route', agency, route, data: null }, 'lines');
}
async function renderRoute(body) {
  const v = S.view;
  body.innerHTML = `<div class="empty">${t('loading')}</div>`;
  try {
    const d = await api('route', { agency: v.agency, route: v.route });
    if (S.view !== v) return;
    v.data = d; v.range = d.range; updateTitle();
    const c = colors(d);
    const isOnly = S.filters.line && S.filters.line.agency === v.agency && S.filters.line.route_id === v.route;
    let h = `<div class="row" style="margin-bottom:8px">${backBtn()}<div class="grow"></div>
      <button type="button" class="btn small${isOnly ? ' primary' : ''}" data-act="${isOnly ? 'clear-line' : 'only-line'}" data-agency="${esc(v.agency)}" data-route="${esc(v.route)}" data-line="${esc(d.line)}">${isOnly ? t('clear_filter') : t('only_line')}</button>
      <button type="button" class="btn small icon-only" data-act="share-line" title="${t('share')}" aria-label="${t('share')}">${ic('share')}</button></div>
      <div class="row" style="margin-bottom:8px">${badge(d)}<div class="grow"><div class="title">${esc(d.long || d.line)}</div><div class="muted small">${esc(agName(v.agency))}</div></div></div>`;
    const live = S.vehicles.filter(x => x.agency === v.agency && x.route_id === v.route).length;
    h += `<div class="notice ${live ? 'ok' : ''} small">${live ? `${live} ${t('live_vehicles')}` : t('no_rt')}</div><div id="route-tt"></div>`;
    for (const sh of d.shapes) {
      h += `<h2>${t('departs_from')} ${esc(sh.headsign || '')}</h2><ul class="tl" style="--c:${c.bg}">` +
        sh.stops.map(s => `<li data-act="station" data-agency="${esc(v.agency)}" data-id="${esc(s.station_id)}" data-lat="${s.lat}" data-lon="${s.lon}"><span class="nm">${esc(s.name)}</span></li>`).join('') + '</ul>';
    }
    body.innerHTML = h;
    clearRouteLayer(); selLayer.clearLayers();
    let bounds = L.latLngBounds([]);
    d.shapes.forEach((sh, i) => {
      const pts = sh.pts && sh.pts.length ? sh.pts : sh.stops.filter(s => s.lat).map(s => [s.lat, s.lon]);
      if (!pts.length) return;
      const pl = L.polyline(pts, { color: c.bg, weight: 5, opacity: i ? .55 : .85, dashArray: i ? '8 8' : null, bubblingMouseEvents: false }).addTo(routeLayer);
      bounds.extend(pl.getBounds());
      sh.stops.forEach(s => s.lat && L.circleMarker([s.lat, s.lon], { radius: 5, weight: 2, color: cssv('--map-ring'), fillColor: c.bg, fillOpacity: 1, bubblingMouseEvents: false })
        .bindTooltip(esc(s.name)).on('click', () => openStation(v.agency, s.station_id)).addTo(routeLayer));
    });
    if (bounds.isValid()) fitTo(bounds);
    setFocus({ agency: v.agency, route_id: v.route });
    drawRouteTT();
  } catch (e) { body.innerHTML = `<div class="empty">${t('error')}</div>`; }
}

/** Timetable of the open line for the chosen date (date bar + departure times by hour, per direction). */
let ttReq = 0;
async function drawRouteTT() {
  const v = S.view, el = $('#route-tt'); if (!el || v.name !== 'route' || !v.range) return;
  if (!v.date) v.date = v.range.today;
  const my = ++ttReq;
  el.innerHTML = dateBar(v) + `<div id="route-tt-body"><div class="empty">${t('loading')}</div></div>`;
  try {
    const d = await api('route_schedule', { agency: v.agency, route: v.route, date: v.date });
    if (my !== ttReq || S.view !== v) return;
    if (d.error) {
      v.range = d.range || v.range; toast(pickErr(d.error));
      if (v.date !== v.range.today) { v.date = v.range.today; return drawRouteTT(); }
      $('#route-tt-body').innerHTML = `<div class="empty">${t('no_service_date')}</div>`; return;
    }
    v.range = d.range; v.sched = d;
    const c = colors(v.data);
    let h = '';
    if (!d.directions.length) h += `<div class="empty">${t('no_service_date')}</div>`;
    for (const g of d.directions) {
      h += `<h2>${t('departs_from')} ${esc(g.headsign || '')} <span class="muted small">· ${t('services_n').replace('{n}', g.trips.length)}</span></h2>`;
      const byHour = new Map();
      g.trips.forEach(x => { const hh = clock(x.dep).slice(0, 2); if (!byHour.has(hh)) byHour.set(hh, []); byHour.get(hh).push(x); });
      for (const [hh, list] of byHour) {
        h += `<div class="hrow"><span class="hh num">${hh}</span><div class="chips">` + list.map(x =>
          `<button type="button" class="tchip" style="--c:${c.bg}" data-act="trip" data-sched="1" data-agency="${esc(v.agency)}" data-trip="${esc(x.trip_id)}" data-date="${esc(x.date)}" title="${esc((x.from || '') + (x.headsign ? ' → ' + x.headsign : ''))}"><b class="num">${clock(x.dep).slice(3)}</b>${x.headsign && x.headsign !== g.headsign ? `<span class="small">${esc(x.headsign)}</span>` : ''}</button>`).join('') + '</div></div>';
      }
    }
    $('#route-tt-body').innerHTML = h;
  } catch (e) { const b = $('#route-tt-body'); if (b) b.innerHTML = `<div class="empty">${t('error')}</div>`; }
}

// ───────────────────────────────────────────────────────────── sources
let deferredInstall = null;
const isStandalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
window.addEventListener('beforeinstallprompt', e => { e.preventDefault(); deferredInstall = e; if (S.view.name === 'info') render(); });
window.addEventListener('appinstalled', () => { deferredInstall = null; if (S.view.name === 'info') render(); });
function installBlock() {
  if (isStandalone()) return '';
  if (deferredInstall) return `<h2>${t('install_title')}</h2><p class="small muted" style="margin:0 0 8px">${t('install_text')}</p><button type="button" class="btn primary block" data-act="install">${t('install')}</button>`;
  if (isIOS) return `<h2>${t('install_title')}</h2><p class="small muted" style="margin:0">${t('install_text')} ${t('install_ios')}</p>`;
  return '';
}
async function renderInfo(body) {
  body.innerHTML = `<h2>${t('language')}</h2>
    <div class="seg" role="group" aria-label="${t('language')}">${LANGS.map(([c, n]) =>
      `<button type="button" class="${S.lang === c ? 'on' : ''}" lang="${c}" data-act="lang" data-lang="${c}" aria-pressed="${S.lang === c}">${n}</button>`).join('')}</div>
    ${installBlock()}
    <h2>${t('src_title')}</h2><p class="small muted" style="margin:0 0 8px">${t('src_intro')}</p><div id="info-t"><div class="empty">${t('loading')}</div></div>
    <p class="credit">${t('credit')}</p>`;
  try {
    const d = await api('agencies', { probe: 1 });
    S.agencies = Object.fromEntries(d.agencies.map(a => [a.id, a]));
    if (S.view.name !== 'info') return;
    const st = s => s ? `<span class="st ${s.status}">${t('st_' + s.status)}${s.n ? ' ' + s.n : ''}</span>` : '<span class="muted">—</span>';
    $('#info-t').innerHTML = `<table class="src"><tr><th>${t('src_operator')}</th><th>${t('src_veh')}</th><th>${t('src_trips')}</th><th>${t('src_alerts')}</th></tr>` +
      byRegion(d.agencies).map(([r, l]) => `<tr class="region-row"><th colspan="4">${esc(regionName(r))}</th></tr>` + l.map(a => `<tr><td>${esc(a.name)}<div class="muted small">${a.ready ? (a.modes || []).map(m => modeSvg(m, 'sm')).join('') + ' ' + esc((a.gtfs_updated || '').slice(0, 16)) : (a.importing ? t('importing') : esc(a.error || ''))}</div>${a.rt.arrivals ? `<div class="muted small">${t('src_arrivals')}: ${st(a.rt.arrivals)}</div>` : ''}</td>
      <td>${st(a.rt.vehicles)}</td><td>${st(a.rt.trips)}</td><td>${st(a.rt.alerts)}</td></tr>`).join('')).join('') + '</table>' +
      `<p class="small muted">${t('updated_lbl')} ${clockS(d.time)}</p>`;
  } catch (e) { const el = $('#info-t'); if (el) el.innerHTML = `<div class="empty">${t('error')}</div>`; }
}

// ───────────────────────────────────────────────────────────── search (stops, lines, operators in one box)
const qEl = $('#q'), sugEl = $('#suggest');
let sugData = [], sugSel = -1, sugTimer, sugReq = 0;
function renderSuggest(d) {
  sugData = [];
  let h = '';
  const sect = (title, items, fn) => { if (!items.length) return; h += `<li class="hd">${title}</li>`; items.forEach(x => { sugData.push(x); h += fn(x, sugData.length - 1); }); };
  sect(t('search_lines'), d.routes.slice(0, 6).map(r => Object.assign({ type: 'route' }, r)),
    (r, i) => `<li data-i="${i}">${badge(r)}<div class="grow ellipsis">${esc(r.long || r.line)} <span class="muted small">${esc(r.agency_name)}</span></div></li>`);
  sect(t('search_ops'), d.operators.slice(0, 4).map(o => Object.assign({ type: 'operator' }, o)),
    (o, i) => `<li data-i="${i}"><span class="mi">${ic('bus')}</span><div class="grow ellipsis"><b>${esc(o.name)}</b></div></li>`);
  sect(t('search_stops'), d.results.map(s => Object.assign({ type: 'station' }, s)),
    (s, i) => `<li data-i="${i}"><span class="mode-ic">${modeIcons(s.modes)}</span><div class="grow ellipsis"><b>${esc(s.name)}</b> <span class="muted small">${esc(s.agency_name)}</span></div></li>`);
  sugEl.innerHTML = h || `<li class="muted pad">${t('no_results')}</li>`;
  sugSel = -1; sugEl.hidden = false;
}
qEl.addEventListener('input', () => {
  clearTimeout(sugTimer);
  const q = qEl.value.trim();
  if (q.length < 1) { sugEl.hidden = true; return; }
  sugTimer = setTimeout(async () => {
    const id = ++sugReq;
    try { const d = await api('search', { q }); if (id === sugReq) renderSuggest(d); } catch (e) { /* ignore */ }
  }, 180);
});
qEl.addEventListener('keydown', e => {
  const lis = $$('li[data-i]', sugEl);
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault(); if (!lis.length) return;
    sugSel = (sugSel + (e.key === 'ArrowDown' ? 1 : -1) + lis.length) % lis.length;
    lis.forEach((l, i) => l.classList.toggle('sel', i === sugSel));
    lis[sugSel].scrollIntoView({ block: 'nearest' });
  } else if (e.key === 'Enter') {
    const s = sugData[sugSel >= 0 ? sugSel : 0]; if (s) pickSuggestion(s);
  } else if (e.key === 'Escape') { sugEl.hidden = true; qEl.blur(); }
});
sugEl.addEventListener('mousedown', e => { const li = e.target.closest('li[data-i]'); if (li) { e.preventDefault(); pickSuggestion(sugData[+li.dataset.i]); } });
qEl.addEventListener('blur', () => setTimeout(() => sugEl.hidden = true, 150));
qEl.addEventListener('focus', () => { if (sugData.length && qEl.value.trim()) sugEl.hidden = false; });
function pickSuggestion(s) {
  sugEl.hidden = true; qEl.value = ''; qEl.blur();
  if (s.type === 'station') openStation(s.agency, s.station_id);
  else if (s.type === 'route') {
    S.filters.line = { agency: s.agency, route_id: s.route_id, line: s.line };
    filtersChanged(); openRoute(s.agency, s.route_id);
  } else if (s.type === 'operator') {
    S.filters.agencies = new Set([s.agency]); S.filters.line = null;
    filtersChanged(); toast(s.name);
  }
}

// ───────────────────────────────────────────────────────────── language + theme
function setLang(code, remember) {
  S.lang = I18N[code] ? code : DEFAULT_LANG;
  if (remember) ls.set(LANG_KEY, S.lang);
  const nm = Object.fromEntries(LANGS)[S.lang];
  $('#btn-lang').setAttribute('aria-label', t('language') + ': ' + nm); $('#btn-lang').title = t('language');
  $$('#lang-menu [data-lang]').forEach(b => b.dataset.lang === S.lang ? b.setAttribute('aria-current', 'true') : b.removeAttribute('aria-current'));
  applyI18n(); updateThemeBtn(); renderMapFilter(); render();
}
function closeLangMenu() { $('#lang-menu').hidden = true; $('#btn-lang').setAttribute('aria-expanded', 'false'); }
$('#btn-lang').addEventListener('click', e => {
  e.stopPropagation();
  const m = $('#lang-menu'); m.hidden = !m.hidden;
  $('#btn-lang').setAttribute('aria-expanded', String(!m.hidden));
});
document.addEventListener('click', e => { if (!e.target.closest('.lang-wrap')) closeLangMenu(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#lang-menu').hidden) { closeLangMenu(); $('#btn-lang').focus(); } });

/** Colour scheme. With nothing stored the page follows the system; the toggle pins "light" or "dark" only when that
 *  differs from the system (toggling back to what the system says removes the pin, so the page follows it again).
 *  The choice is mirrored in <meta name="color-scheme"> ("light dark" = follow the system). */
const sysDark = matchMedia('(prefers-color-scheme: dark)');
const theme = () => document.documentElement.dataset.theme;
const pinnedTheme = () => { const v = ls.get('theme'); return v === 'light' || v === 'dark' ? v : null; };
function updateThemeBtn() {
  const dark = theme() === 'dark', b = $('#btn-theme');
  b.innerHTML = ic(dark ? 'sun' : 'moon');
  b.title = t(dark ? 'theme_to_light' : 'theme_to_dark'); b.setAttribute('aria-label', b.title);
}
function setTheme(th) {
  document.documentElement.dataset.theme = th;
  $$('meta[name=theme-color]').forEach(m => { m.removeAttribute('media'); m.content = cssv('--surface'); });
  updateThemeBtn(); applyBasemap(); loadStations(); drawVehicles();
}
function syncTheme() {       // from the stored choice (or the system) to the page; also after another tab changed it
  const pinned = pinnedTheme();
  $('meta[name=color-scheme]').content = pinned || 'light dark';
  const th = pinned || (sysDark.matches ? 'dark' : 'light');
  if (th !== theme()) setTheme(th);
}
$('#btn-theme').addEventListener('click', () => {
  const target = theme() === 'dark' ? 'light' : 'dark';
  if (target === (sysDark.matches ? 'dark' : 'light')) ls.del('theme'); else ls.set('theme', target);
  syncTheme();
});
sysDark.addEventListener('change', syncTheme);
addEventListener('storage', e => { if (e.key === 'theme' || e.key === null) syncTheme(); });

// ───────────────────────────────────────────────────────────── geolocation
function locate() {
  if (!navigator.geolocation) { toast(t('loc_denied')); return; }
  toast(t('locating'), 5000);
  navigator.geolocation.getCurrentPosition(async pos => {
    const { latitude: lat, longitude: lon } = pos.coords;
    S.me = [lat, lon];
    meLayer.clearLayers();
    L.marker(S.me, { icon: L.divIcon({ className: '', html: '<div class="me"></div>', iconSize: [0, 0] }), interactive: false }).addTo(meLayer);
    expandSheet(); flyTo(S.me, 16, .8);
    try { S.nearby = (await api('nearby', { lat, lon, radius: 600 })).results; } catch (e) { S.nearby = []; }
    setTab('stops'); expandSheet();
  }, () => toast(t('loc_denied')), { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 });
}

// ───────────────────────────────────────────────────────────── share (Web Share API → native Android/iOS share sheet)
/** Nearest coloured-square emoji for a line colour (#rrggbb), so a shared line keeps its identity in plain text. */
function colorEmoji(hex) {
  const n = parseInt(hex.slice(1), 16), r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, dl = mx - mn;
  const sat = dl === 0 ? 0 : dl / (1 - Math.abs(2 * l - 1));
  if (l < .13) return '⬛';
  if (l > .88) return '⬜';
  if (sat < .15) return l > .6 ? '⬜' : '⬛';
  let h = dl === 0 ? 0 : mx === r ? ((g - b) / dl) % 6 : mx === g ? (b - r) / dl + 2 : (r - g) / dl + 4;
  h = (h * 60 + 360) % 360;
  if (h < 15 || h >= 335) return '🟥';
  if (h < 40) return l < .38 ? '🟫' : '🟧';
  if (h < 70) return '🟨';
  if (h < 170) return '🟩';
  if (h < 260) return '🟦';
  return '🟪';
}
/** What a station share offers: the lines the list currently shows (live: filtered by the server; timetable: filtered here). */
function shareItems(v) {
  const d = v.data; if (!d) return [];
  return d.date && v.lineSel && v.lineSel.size ? d.items.filter(it => v.lineSel.has(lineKey(it))) : d.items;
}
const shareCount = v => v.name === 'trip' ? (v.data ? v.data.stops.length : 0) : shareItems(v).length;
function shareRange(v) {
  const n = shareCount(v), s = v.share;
  return [Math.max(0, s.a == null ? 0 : s.a), Math.min(n - 1, s.b == null ? n - 1 : s.b)];
}
const shareBar = () => `<div class="sharebar" id="sharebar"><span class="grow small" id="share-info"></span>
  <button type="button" class="btn small" data-act="share-cancel">${t('cancel')}</button>
  <button type="button" class="btn small primary icon-only" data-act="share-go" title="${t('share')}" aria-label="${t('share')}">${ic('share')}</button></div>`;
function toggleShare(on) {
  const v = S.view;
  if (on === undefined) on = !v.share;
  if (!on) v.share = null;
  else {
    if (v.name === 'trip' && v.data && !v.data.sched_only) {      // a live trip starts at the next stop
      const i = v.data.stops.findIndex(s => s.expected >= nowTs() - 30);
      v.share = { a: Math.max(i, 0), b: null, anchor: null };
    } else v.share = { a: null, b: null, anchor: null };
  }
  if (v.name === 'trip') render(); else drawStationHeader($('#panel-body'));
}
/** Two taps pick a contiguous range: first and last item (in either order). */
function pickShare(i) {
  const s = S.view.share; if (!s) return;
  if (s.anchor == null) { s.a = s.b = i; s.anchor = i; }
  else { s.a = Math.min(s.anchor, i); s.b = Math.max(s.anchor, i); s.anchor = null; }
  paintShare();
}
function paintShare() {
  const v = S.view, s = v.share; if (!s) return;
  const [a, b] = shareRange(v);
  $$('#panel-body [data-i]').forEach(el => { const i = +el.dataset.i, on = i >= a && i <= b; el.classList.toggle('sel', on); el.classList.toggle('out', !on); });
  const info = $('#share-info');
  if (info) info.textContent = s.anchor != null ? t(v.name === 'trip' ? 'share_pick_end_stop' : 'share_pick_end') : t(v.name === 'trip' ? 'share_stops_n' : 'share_deps_n').replace('{n}', Math.max(0, b - a + 1));
}
function tripShareText(d, a, b) {
  const stops = d.stops.slice(a, b + 1).filter(s => !s.skipped);
  const lines = [`${colorEmoji(colors(d).bg)} ${d.line || ''} → ${d.headsign || ''}`.trim(), agName(d.agency) + (d.sched_only && d.date ? ' · ' + ymdMedium(d.date) : '')];
  stops.forEach(s => lines.push(`📍 ${clock(s.expected)} ${s.name}`));
  return lines;
}
function stationShareText(v, a, b) {
  const st = v.data.station, d = v.data;
  const lines = [`🚏 ${st.name}`, st.agency_name + (d.date ? ' · ' + ymdMedium(d.date) : '')];
  shareItems(v).slice(a, b + 1).forEach(it => {
    const when = it.cancelled ? '❌' : clock(d.date ? it.sched : it.expected);
    lines.push(`${colorEmoji(colors(it).bg)} ${it.line} · ${it.headsign || ''} ${when}`.replace(/ {2,}/g, ' '));
  });
  return lines;
}
async function doShare() {
  const v = S.view; if (!v.share || !v.data) return;
  const [a, b] = shareRange(v);
  if (b < a) return;
  sendShare(v.name === 'trip' ? tripShareText(v.data, a, b) : stationShareText(v, a, b));
}
/** Hands the text lines (+ a link to the current view) to the native share sheet, or copies them. */
async function sendShare(lines) {
  const url = location.origin + location.pathname + location.hash;
  const text = lines.join('\n') + '\n🔗 ' + url;
  try {
    if (navigator.share) { await navigator.share({ title: lines[0], text }); return; }
  } catch (e) { if (e && e.name === 'AbortError') return; }
  try { await navigator.clipboard.writeText(text); toast(t('share_copied')); }
  catch (e) { toast(t('error')); }
}
/** Typical gap between services, in minutes: the middle half of the gaps of the busiest direction, rounded to 5. */
function headwayText(directions) {
  const g = directions.toSorted((x, y) => y.trips.length - x.trips.length)[0];
  if (!g || g.trips.length < 4) return '';
  const deps = g.trips.map(x => x.dep).sort((x, y) => x - y);
  const gaps = deps.slice(1).map((x, i) => (x - deps[i]) / 60).filter(m => m > 0).sort((x, y) => x - y);
  if (!gaps.length) return '';
  const q = p => gaps[Math.min(gaps.length - 1, Math.floor(p * (gaps.length - 1)))];
  const r = m => m < 10 ? Math.round(m) : Math.round(m / 5) * 5;
  const lo = r(q(.25)), hi = r(q(.75));
  if (!lo) return '';
  return (lo === hi ? t('share_every').replace('{n}', lo) : t('share_every').replace('{n}', lo + '–' + hi));
}
function lineShareText(v) {
  const d = v.data, sc = v.sched;
  const lines = [`${colorEmoji(colors(d).bg)} ${d.line || ''}${d.long && d.long !== d.line ? ' · ' + d.long : ''}`.trim(), agName(v.agency)];
  const sh = d.shapes || [];
  if (sh[0] && sh[0].stops.length > 1) {
    const f = sh[0].stops[0].name, l = sh[0].stops[sh[0].stops.length - 1].name;
    lines.push(`📍 ${f}`, `🏁 ${l}`);
  }
  const all = sc && !sc.error ? sc.directions.flatMap(g => g.trips.map(x => x.dep)) : [];
  if (all.length) {
    const hw = headwayText(sc.directions);
    const day = sc.date && sc.date !== (v.range && v.range.today) ? ' (' + ymdMedium(sc.date) + ')' : '';
    lines.push(`🕕 ${clock(Math.min(...all))} – ${clock(Math.max(...all))}${hw ? ' · ' + hw : ''}${day}`);
  }
  return lines;
}
function shareLine() {
  const v = S.view; if (v.name !== 'route' || !v.data) return;
  sendShare(lineShareText(v));
}
// ───────────────────────────────────────────────────────────── events
document.addEventListener('click', ev => {
  const el = ev.target.closest('[data-act]'); if (!el) return;
  const a = el.dataset.act, d = el.dataset;
  if (el.tagName === 'INPUT') return;
  ev.stopPropagation();
  switch (a) {
    case 'station':
      map.closePopup();
      if (d.lat && S.view.name === 'trip') showPoint(+d.lat, +d.lon);
      openStation(d.agency, d.id); break;
    case 'trip':
      if (S.view.name === 'station') S.view.scroll = $('#panel-body').scrollTop;
      openTrip(d.agency, d.trip, d.date, d.sched === '1'); break;
    case 'date-step': { const v = S.view; if (v.range) applyDate(ymdAdd(v.date || v.range.today, +d.step)); break; }
    case 'date-today': applyDate(S.view.range.today); break;
    case 'date-pick': { const i = $('input[data-act=date-set]'); if (i) { try { i.showPicker(); } catch (e) { i.focus(); i.click(); } } break; }
    case 'line-filter':
      toggleLine(S.view, d.key);
      if (S.view.share) S.view.share = { a: null, b: null, anchor: null };
      if (S.view.date) drawStationHeader($('#panel-body')); else render();      // live: the server filters, so ask again
      break;
    case 'route': openRoute(d.agency, d.route); break;
    case 'share-start': toggleShare(); break;
    case 'share-pick': pickShare(+d.i); break;
    case 'share-cancel': toggleShare(false); break;
    case 'share-go': doShare(); break;
    case 'share-line': shareLine(); break;
    case 'back': S.hist.length ? history.back() : back(); break;
    case 'reload': render(); break;
    case 'fav': {
      const st = S.view.data && S.view.data.station; if (!st) break;
      if (isFav(st.agency, st.station_id)) S.favs = S.favs.filter(f => !(f.agency === st.agency && f.station_id === st.station_id));
      else S.favs.push({ agency: st.agency, station_id: st.station_id, name: st.name, modes: st.modes });
      saveFavs(); drawStationHeader($('#panel-body')); break;
    }
    case 'unfav': S.favs.splice(+d.i, 1); saveFavs(); render(); break;
    case 'focus-stn': { const st = S.view.data && S.view.data.station; if (st) { if (isMobile()) setSheet('closed'); flyTo([st.lat, st.lon], 17); } break; }
    case 'locate': locate(); break;
    case 'only-line': S.filters.line = { agency: d.agency, route_id: d.route, line: d.line }; filtersChanged(); if (S.view.name === 'route') render(); break;
    case 'clear-line': S.filters.line = null; filtersChanged(); if (S.view.name === 'route') render(); break;
    case 'clear-agency': S.filters.agencies.delete(d.id); if (!S.filters.agencies.size) S.filters.agencies = null; filtersChanged(); break;
    case 'mode': toggleMode(d.mode); filtersChanged(); break;
    case 'lang': setLang(d.lang, true); closeLangMenu(); break;
    case 'mapstyle': S.mapStyle = d.style; ls.set('mapStyle', d.style); applyBasemap(); renderLive(); break;
    case 'install': if (deferredInstall) { deferredInstall.prompt(); deferredInstall.userChoice.finally(() => { deferredInstall = null; if (S.view.name === 'info') render(); }); } break;
    case 'ag-all': S.filters.agencies = null; filtersChanged(); break;
    case 'ag-none': S.filters.agencies = new Set(); filtersChanged(); break;
  }
});
document.addEventListener('change', ev => {
  const el = ev.target; const a = el.dataset && el.dataset.act;
  if (a === 'ag') {
    if (!S.filters.agencies) S.filters.agencies = new Set(Object.keys(S.agencies));
    el.checked ? S.filters.agencies.add(el.dataset.id) : S.filters.agencies.delete(el.dataset.id);
    saveFilters(); drawVehicles(); renderMapFilter(); loadStations();
  } else if (a === 'date-set') {
    if (el.value) applyDate(el.value.replace(/-/g, '')); else renderDateUi();
  } else if (a === 'opt') {
    S.filters[el.dataset.opt] = el.checked; saveFilters();
    if (el.dataset.opt === 'showStops') loadStations(); else drawVehicles();
  }
});
$$('#tabs button').forEach(b => b.addEventListener('click', () => { setTab(b.dataset.tab); if (b.dataset.tab === 'alerts') loadAlerts(); expandSheet(); }));
$('#btn-locate').addEventListener('click', locate);
// a tap on empty map closes whatever is open and shows every service again (markers and the line itself swallow their own taps)
map.on('click', () => {
  if (DETAIL_VIEWS.includes(S.view.name)) closeDetail();
  if (isMobile()) setSheet('closed');
});
// rows built as <div data-act> behave like buttons for keyboard and screen-reader users
new MutationObserver(() => $$('#panel-body [data-act]:not(button):not(input)').forEach(el => {
  if (el.hasAttribute('tabindex')) return;
  el.tabIndex = 0; if (!el.querySelector('button')) el.setAttribute('role', 'button');
})).observe($('#panel-body'), { childList: true, subtree: true });
document.addEventListener('keydown', e => {
  const el = e.target;
  if ((e.key === 'Enter' || e.key === ' ') && el.matches && el.matches('[data-act][tabindex]') && el.tagName !== 'BUTTON' && el.tagName !== 'INPUT') { e.preventDefault(); el.click(); }
});
window.addEventListener('offline', () => toast(t('offline'), 4000));
document.addEventListener('visibilitychange', () => { if (!document.hidden) { pollVehicles(); refreshView(); } });

function refreshView() {
  const n = S.view.name;
  if (document.hidden) return;
  if (n === 'station' && S.view.date) return;    // timetable of another date: nothing changes
  if (n === 'trip' && S.view.sched) return;
  if (S.view.share) return;                      // keep the user's selection while choosing what to share
  if (n === 'station' || n === 'trip') render();
  else if (n === 'home' && S.favs.length) loadFavNext();
}
setInterval(pollVehicles, POLL_VEHICLES_MS);
setInterval(refreshView, POLL_VIEW_MS);
setInterval(() => { // keep countdowns ticking between fetches
  if (S.view.name === 'station' && S.view.data && !S.view.date && !S.view.share && !document.hidden) { const l = $('#dep-list'); if (l) l.innerHTML = depList(S.view.data); }
}, 10000);
setInterval(loadAlerts, 120000);

// vertical mouse wheel scrolls the tab strip horizontally
$('#tabs').addEventListener('wheel', e => {
  if (e.deltaY && !e.deltaX) { e.preventDefault(); e.currentTarget.scrollLeft += e.deltaY; }
}, { passive: false });

// drag handle to resize the side panel (desktop): a window splitter, operated with the pointer or the arrow keys
(function () {
  const PANEL_MIN = 300, root = document.documentElement, handle = $('#resizer');
  const panelMax = () => Math.min(900, window.innerWidth - 200);
  const clampW = w => Math.min(Math.max(w, PANEL_MIN), panelMax());
  const setW = (w, save) => {
    w = Math.round(clampW(w));
    root.style.setProperty('--panel-w', w + 'px');
    handle.setAttribute('aria-valuenow', w); handle.setAttribute('aria-valuemax', panelMax());
    if (save) ls.set('panelW', w);
    map.invalidateSize();
  };
  handle.setAttribute('aria-valuemin', PANEL_MIN);
  const saved = +ls.get('panelW');
  if (saved >= PANEL_MIN) setW(saved); else { handle.setAttribute('aria-valuemax', panelMax()); handle.setAttribute('aria-valuenow', $('#panel').offsetWidth); }
  let drag = false;
  handle.addEventListener('pointerdown', e => {
    drag = true; handle.setPointerCapture(e.pointerId); document.body.classList.add('resizing'); e.preventDefault();
  });
  handle.addEventListener('pointermove', e => { if (drag) setW(e.clientX, true); });
  const stop = () => { if (!drag) return; drag = false; document.body.classList.remove('resizing'); map.invalidateSize(); };
  handle.addEventListener('pointerup', stop); handle.addEventListener('pointercancel', stop);
  handle.addEventListener('dblclick', () => {
    root.style.removeProperty('--panel-w'); ls.del('panelW'); map.invalidateSize();
    handle.setAttribute('aria-valuenow', $('#panel').offsetWidth);
  });
  handle.addEventListener('keydown', e => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    setW($('#panel').offsetWidth + (e.key === 'ArrowRight' ? 30 : -30), true);
  });
})();

// ───────────────────────────────────────────────────────────── boot
async function loadAgencies() {
  try {
    const d = await api('agencies');
    S.agencies = Object.fromEntries(d.agencies.map(a => [a.id, a]));
    if (S.view.name === 'home') renderHome($('#panel-body'));
    return d.agencies.some(a => !a.ready || a.importing);
  } catch (e) { return true; }
}
async function boot() {
  const h = decodeURIComponent((location.hash || '').slice(1));
  $('#btn-locate').innerHTML = ic('target');
  $('#search-ic').innerHTML = ic('search');
  $('#btn-lang').innerHTML = ic('globe');
  setLang(S.lang);
  $$('#tabs button').forEach(b => { $('.tab-ic', b).innerHTML = ic(b.dataset.ic); });
  setSheet('half');
  applyBasemap();
  applyI18n();
  renderMapFilter();
  render();
  const importing = await loadAgencies();
  renderMapFilter();
  pollVehicles(); loadAlerts(); loadStations();
  if (importing) { // first run: timetables are still being imported
    const iv = setInterval(async () => { const still = await loadAgencies(); if (!still) { clearInterval(iv); loadStations(); } }, 8000);
  }
  if (new URLSearchParams(location.search).get('near') === '1') { history.replaceState(null, '', location.pathname); locate(); }
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => { /* not on https/localhost: fine */ });
  if (h.startsWith('s=')) { const [a, id, dt] = h.slice(2).split('|'); if (a && id) openStation(a, id, /^\d{8}$/.test(dt || '') ? dt : null); }
  else if (h.startsWith('r=')) { const [a, id] = h.slice(2).split('|'); if (a && id) openRoute(a, id); }
  else if (h.startsWith('t=')) { const [a, id, dt] = h.slice(2).split('|'); if (a && id) openTrip(a, id, dt || '', !!dt); }
}
boot();
