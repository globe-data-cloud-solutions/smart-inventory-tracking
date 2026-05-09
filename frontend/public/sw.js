const CACHE = "smart-v1";
const SHELL  = ["/", "/dashboard/inventory", "/dashboard/products", "/dashboard/reports"];
const LOCALES = ["/api/locales/en", "/api/locales/am", "/api/locales/or"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll([...SHELL, ...LOCALES]).catch(() => {}))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const { request } = e;
  const url = new URL(request.url);

  // Cache-first for shell + locales
  if (request.method === "GET" && (SHELL.includes(url.pathname) || url.pathname.startsWith("/api/locales/"))) {
    e.respondWith(
      caches.match(request).then((cached) =>
        cached ??
        fetch(request).then((resp) => {
          const clone = resp.clone();
          caches.open(CACHE).then((c) => c.put(request, clone));
          return resp;
        })
      )
    );
    return;
  }

  // Network-first for API calls — queue on failure
  if (request.method !== "GET" && url.pathname.startsWith("/api/v1/")) {
    e.respondWith(
      fetch(request.clone()).catch(() => {
        // Offline mutations are queued in IndexedDB by the calling code (offlineQueue.ts)
        return new Response(JSON.stringify({ success: false, error: { code: "OFFLINE" } }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        });
      })
    );
  }
});
