// JARVIS Service Worker — enables PWA install + offline caching
const CACHE_NAME = 'jarvis-v1';
const ASSETS = ['/', '/static/style.css', '/static/orb.js', '/static/icon-192.png', '/static/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))));
});

self.addEventListener('fetch', e => {
  // Network first, fall back to cache
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
