const CACHE_PREFIX = 'night-pyodide-';
const CACHE_NAME = 'night-pyodide-v1';

function isPyodideAsset(request) {
  if (request.method !== 'GET') return false;
  const url = new URL(request.url);
  return url.origin === 'https://cdn.jsdelivr.net' && /^\/pyodide\/v[^/]+\/full\//.test(url.pathname);
}

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names
      .filter(name => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
      .map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  if (!isPyodideAsset(event.request)) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE_NAME);
    const cached = await cache.match(event.request);
    if (cached) return cached;

    const response = await fetch(event.request);
    if (response.ok) {
      event.waitUntil(cache.put(event.request, response.clone()));
    }
    return response;
  })());
});
