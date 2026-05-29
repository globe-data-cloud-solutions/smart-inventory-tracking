// CACHE_VERSION must be bumped on every deployment to evict stale assets.
// CI: sed -i "s/CACHE_VERSION = \"smart-v[^\"]*\"/CACHE_VERSION = \"smart-v${BUILD_ID}\"/" public/sw.js
const CACHE_VERSION = "smart-v4";
const STATIC_CACHE  = `${CACHE_VERSION}-static`;   // immutable hashed assets
const DYNAMIC_CACHE = `${CACHE_VERSION}-dynamic`;  // pages + CSS (revalidate often)

const LOCALES = ["/api/locales/en", "/api/locales/am", "/api/locales/or"];

// ── Install: pre-cache language packs only (not shell pages — those are NetworkFirst) ──
self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(STATIC_CACHE)
      .then((c) => c.addAll(LOCALES).catch(() => {}))
  );
  self.skipWaiting();
});

// ── Activate: delete every cache that doesn't belong to this version ──────────
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => !k.startsWith(CACHE_VERSION))
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ── Fetch helpers ──────────────────────────────────────────────────────────────

async function networkFirst(request, cacheName) {
  try {
    const resp = await fetch(request);
    if (resp.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, resp.clone());
    }
    return resp;
  } catch {
    const cached = await caches.match(request);
    return cached ?? Response.error();
  }
}

async function cacheFirst(request, cacheName) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const resp = await fetch(request);
    if (resp.ok) {
      const cache = await caches.open(cacheName);
      cache.put(request, resp.clone());
    }
    return resp;
  } catch {
    return Response.error();
  }
}

// ── Fetch: strategy dispatch ───────────────────────────────────────────────────
self.addEventListener("fetch", (e) => {
  const { request } = e;
  const url = new URL(request.url);
  const path = url.pathname;

  // Non-GET: offline stub for API mutations; everything else passes through
  if (request.method !== "GET") {
    if (path.startsWith("/api/v1/")) {
      e.respondWith(
        fetch(request.clone()).catch(() =>
          new Response(
            JSON.stringify({ success: false, error: { code: "OFFLINE" } }),
            { status: 503, headers: { "Content-Type": "application/json" } }
          )
        )
      );
    }
    return;
  }

  // CSS — NetworkFirst: stale CSS breaks the UI after a new deploy.
  // Next.js content-hashes CSS filenames, so the network always wins when
  // the hash changes; the old file is still served from cache if offline.
  if (path.startsWith("/_next/static/css/")) {
    e.respondWith(networkFirst(request, DYNAMIC_CACHE));
    return;
  }

  // JS chunks and media — CacheFirst: content-hashed by Next.js, immutable.
  if (path.startsWith("/_next/static/")) {
    e.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }

  // Language packs — CacheFirst: stable JSON, loaded at app startup.
  if (path.startsWith("/api/locales/")) {
    e.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }

  // Pages (HTML) — NetworkFirst: ensures the browser always gets the latest
  // HTML with correct asset hashes after a deployment; falls back to cache
  // when offline so the app shell still loads.
  if (!path.startsWith("/api/")) {
    e.respondWith(networkFirst(request, DYNAMIC_CACHE));
    return;
  }

  // API GET calls — network only (no caching of data responses here).
});
