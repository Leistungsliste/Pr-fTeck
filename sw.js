const CACHE_NAME = "prueftechniker-feed-hub-v3";

const URLS_TO_CACHE = [
  "./",
  "./index.html",
  "./manifest.json",
  "./prueftechniker-weekly.xml",
  "./weekly-data.json"
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(URLS_TO_CACHE))
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);

  // Immer frisch für Weekly-Daten
  if (
    url.pathname.endsWith("/prueftechniker-weekly.xml") ||
    url.pathname.endsWith("/weekly-data.json") ||
    url.pathname.endsWith("/index.html") ||
    url.pathname === "/" ||
    url.pathname.endsWith("/Pr-tleck/")
  ) {
    event.respondWith(
      fetch(request, { cache: "no-store" })
        .then(response => {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, responseClone));
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(cached => {
      return (
        cached ||
        fetch(request).then(response => {
          const responseClone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, responseClone));
          return response;
        })
      );
    })
  );
});
