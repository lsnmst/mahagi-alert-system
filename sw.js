// sw.js
const TILE_CACHE = "tiles-cache-v1";
const API_CACHE = "api-cache-v1";

const FALLBACK_TILE = "/tiles/placeholder.png";

// INSTALL
self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(TILE_CACHE).then(cache => {
            return cache.add(FALLBACK_TILE).catch(() => {
                console.warn("⚠️ Fallback tile non trovata");
            });
        })
    );
    self.skipWaiting();
});

// ACTIVATE
self.addEventListener("activate", event => {
    const keepCaches = [TILE_CACHE, API_CACHE];

    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys
                    .filter(key => !keepCaches.includes(key))
                    .map(key => caches.delete(key))
            )
        )
    );

    self.clients.claim();
});

// FETCH
self.addEventListener("fetch", event => {
    const url = event.request.url;

    // =========================
    // TILE CACHE
    // =========================
    if (url.startsWith("https://www.alessandromusetta.com/geo/tiles/mahagi/")) {

        event.respondWith(
            caches.open(TILE_CACHE).then(async cache => {

                const cached = await cache.match(event.request);
                if (cached) return cached;

                try {
                    const networkResponse = await fetch(event.request);
                    cache.put(event.request, networkResponse.clone());
                    return networkResponse;

                } catch (e) {

                    const fallback = await cache.match(FALLBACK_TILE);
                    return fallback || new Response("Offline", { status: 503 });

                }
            })
        );

        return;
    }

    // =========================
    // API CACHE (SUPABASE)
    // =========================
    if (
        url.includes("/rest/v1/alerts") ||
        url.includes("/rest/v1/community_notes")
    ) {

        event.respondWith(
            caches.open(API_CACHE).then(async cache => {

                const cached = await cache.match(event.request);

                try {
                    const networkResponse = await fetch(event.request);
                    cache.put(event.request, networkResponse.clone());
                    return networkResponse;

                } catch (e) {

                    // offline fallback
                    if (cached) return cached;

                    return new Response(JSON.stringify([]), {
                        headers: { "Content-Type": "application/json" },
                        status: 200
                    });
                }
            })
        );

        return;
    }

});
