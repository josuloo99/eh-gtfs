'use strict';
/* App-shell cache. The shell loads offline; live data (/api/*) and map tiles always go to the network. */
const CACHE = 'eh-shell-v6';
const SHELL = [
  '/', '/index.html', '/style.css', '/app.js', '/i18n.js', '/manifest.webmanifest',
  '/icon.svg', '/icon-192.png', '/icon-512.png',
  '/vendor/leaflet/leaflet.css', '/vendor/leaflet/leaflet.js',
  '/vendor/maplibre/maplibre-gl.css', '/vendor/maplibre/maplibre-gl.js', '/vendor/maplibre/leaflet-maplibre-gl.js',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  // Network first so a new deploy shows up at once; the cache answers only when offline.
  e.respondWith(
    fetch(req).then(res => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then(async c => {
          // files are requested as /app.js?v=<hash>: keep only the newest version of each
          if (url.search) for (const k of await c.keys()) { const ku = new URL(k.url); if (ku.pathname === url.pathname && ku.search !== url.search) await c.delete(k); }
          await c.put(req, copy);
        });
      }
      return res;
    }).catch(() => caches.match(req, { ignoreSearch: true }).then(hit => hit || caches.match('/')))
  );
});
