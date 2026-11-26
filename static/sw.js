'use strict';
/* App-shell cache. The shell loads offline; live data (/api/*) and map tiles always go to the network.
 *
 * Two strategies:
 *  - files requested with ?v=<hash> (the server adds it to every local asset, and the hash changes with the content)
 *    never go stale: cache first, which is instant and works offline;
 *  - everything else (the page itself, anything without a version): network first, so a new deploy shows up at once;
 *    the cache answers only when offline.
 */
const CACHE = 'eh-shell-v4';
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

/** Keep a copy of a good response; of a versioned file only the newest version is kept. */
async function remember(req, url, res) {
  const c = await caches.open(CACHE);
  if (url.search) for (const k of await c.keys()) { const ku = new URL(k.url); if (ku.pathname === url.pathname && ku.search !== url.search) await c.delete(k); }
  await c.put(req, res);
}

self.addEventListener('fetch', e => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  const versioned = url.searchParams.has('v');
  e.respondWith((async () => {
    if (versioned) {
      const hit = await caches.match(req);
      if (hit) return hit;
    }
    try {
      const res = await fetch(req);
      if (res.ok) e.waitUntil(remember(req, url, res.clone()));
      return res;
    } catch (err) {
      return (await caches.match(req, { ignoreSearch: true })) || (await caches.match('/')) || Response.error();
    }
  })());
});
