// Meeting Master — Minimal Service Worker for PWA support
const CACHE_NAME = 'meeting-master-v1';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(clients.claim());
});

self.addEventListener('fetch', (event) => {
    // Network-first strategy — always try network, fall back to cache
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
