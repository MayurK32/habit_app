/*
 * Simple service worker for offline support.
 *
 * This service worker pre-caches the core assets of the habit tracker
 * (HTML, CSS, JS, manifest, and icons) during installation and
 * intercepts fetch requests to serve cached responses when available.
 * This ensures the app works offline and loads quickly on subsequent
 * visits.
 */

const CACHE_NAME = 'habit-tracker-cache-v1';

// List of assets to cache. We include the root path, CSS/JS,
// manifest and icons. When adding new static files, update this list.
const ASSETS_TO_CACHE = [
  '/',
  '/static/styles.css',
  '/static/scripts.js',
  '/manifest.json',
  '/static/icon-192.png',
  '/static/icon-512.png'
];

self.addEventListener('install', (event) => {
  // Perform install steps: pre-cache assets
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
});

self.addEventListener('activate', (event) => {
  // Remove old caches if necessary
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});

// Intercept fetch requests and respond with cache when available
self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request).then((response) => {
      // Cache hit - return response or fetch from network
      return response || fetch(event.request);
    })
  );
});