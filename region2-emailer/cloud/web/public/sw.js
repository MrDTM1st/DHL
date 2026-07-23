// Service worker for the Haulage Desk PWA.
//
// Strategy: NETWORK-FIRST for the app shell (a deploy must land on next open,
// never be pinned by a cache), falling back to the cached copy when offline so
// the app still opens on a train with no signal. The /api/* endpoints are
// never touched - live data must be live, and stale tracker state presented as
// current would be worse than an error.
const CACHE = 'r2-desk-v1';
const SHELL = ['/', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;
  if (url.origin !== self.location.origin) return;   // tiles/fonts/OSRM: browser default
  if (url.pathname.startsWith('/api/')) return;      // live data stays live
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request).then((m) => m || caches.match('/')))
  );
});
