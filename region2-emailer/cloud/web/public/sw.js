// Service worker for the Haulage Desk PWA.
//
// Strategy: NETWORK-FIRST for the app shell (a deploy must land on next open,
// never be pinned by a cache), falling back to the cached copy when offline so
// the app still opens on a train with no signal. The /api/* endpoints are
// never touched - live data must be live, and stale tracker state presented as
// current would be worse than an error.
const CACHE = 'r2-desk-v3';
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

// Phone alerts (push_notify.py on the home PC, 24/11): the home PC sends {title, body, url, tag} through the browser's
// push service, and it shows even with the desk closed. A payload that isn't JSON is shown as its text.
self.addEventListener('push', (e) => {
  let d = {};
  if (e.data) {
    try { d = e.data.json(); } catch (err) { d = { body: e.data.text() }; }
  }
  if (!d || typeof d !== 'object') d = { body: String(d || '') };
  const opts = {
    body: d.body || 'Something needs you - open the desk.',
    data: { url: d.url || '/' },
    icon: '/icon-192.png',
    badge: '/icon-192.png',
  };
  if (d.tag) opts.tag = String(d.tag);
  e.waitUntil(self.registration.showNotification(d.title || 'Haulage Desk', opts));
});

// The email of the alert last tapped, for a minute: a phone can resume a sleeping desk without handing it the message
// below, so the desk asks again when it comes to the front ('assist-pending'), and is told once.
let pendingAssist = { id: '', at: 0 };
self.addEventListener('message', (e) => {
  if (!e.data || e.data.type !== 'assist-pending' || !e.source) return;
  const fresh = pendingAssist.id && Date.now() - pendingAssist.at < 60000;
  if (fresh) e.source.postMessage({ type: 'assist-open', id: pendingAssist.id });
  pendingAssist = { id: '', at: 0 };
});

// A tap on an alert: the desk opened on that email (/?assist=ID - his 24/11 "you will tell me what it is ... one
// button that just says either dealt with or deal with it"). Open already in a tab or window: it is told which email
// (a message) and brought forward; else it is opened at the address. Only the desk's own pages.
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  let url = new URL('/', self.location.origin);
  try {
    const u = new URL((e.notification.data && e.notification.data.url) || '/', self.location.origin);
    if (u.origin === self.location.origin) url = u;
  } catch (err) { /* not an address: the desk's front page */ }
  const id = url.searchParams.get('assist') || '';
  pendingAssist = { id, at: Date.now() };
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((tabs) => {
      const open = tabs.find((c) => new URL(c.url).origin === self.location.origin && 'focus' in c);
      if (open) {
        if (id) open.postMessage({ type: 'assist-open', id });
        return open.focus();
      }
      return self.clients.openWindow ? self.clients.openWindow(url.href) : undefined;
    })
  );
});
