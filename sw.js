// sw.js
const CACHE_NAME = "tiles-cache-v1";
const FALLBACK_TILE = "/tiles/placeholder.png";

self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.add(FALLBACK_TILE).catch(() => {
                console.warn("Fallback tile non disponibile");
            });
        })
    );
    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(key => key !== CACHE_NAME)
                    .map(key => caches.delete(key))
            )
        )
    );
    self.clients.claim();
});

// Fetch 
self.addEventListener("fetch", event => {
    const url = event.request.url;

    // filter
    if (url.startsWith("https://www.alessandromusetta.com/geo/tiles/mahagi/")) {
        event.respondWith(
            caches.open(CACHE_NAME).then(cache =>
                cache.match(event.request).then(response => {
                    if (response) return response;

                    return fetch(event.request)
                        .then(networkResponse => {
                            cache.put(event.request, networkResponse.clone());
                            return networkResponse;
                        })
                        .catch(() => {
                            // if offline return fallback
                            return cache.match(FALLBACK_TILE) || new Response(null, { status: 404 });
                        });
                })
            )
        );
    }
});
