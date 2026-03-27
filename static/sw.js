const CACHE_NAME = "zp-widget-cache-v2";
const APP_SHELL_URL = "/";
const STATIC_ASSETS = [
  "/",
  "/static/site.webmanifest",
  "/static/icon.svg",
  "/static/sw.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // Cache assets individually so one failed request does not break offline shell.
    await Promise.allSettled(
      STATIC_ASSETS.map(async (url) => {
        const res = await fetch(url, { cache: "reload" });
        if (res.ok) await cache.put(url, res.clone());
      })
    );
  })());
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.map((k) => (k !== CACHE_NAME ? caches.delete(k) : Promise.resolve())));
  })());
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const req = event.request;
  const url = new URL(req.url);

  // Never serve API from stale cache by default.
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(fetch(req).catch(() => new Response('{"error":"offline"}', {
      status: 503,
      headers: { "Content-Type": "application/json" },
    })));
    return;
  }

  // App shell for PWA open/reopen offline.
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(CACHE_NAME);
        cache.put(APP_SHELL_URL, fresh.clone());
        return fresh;
      } catch (_) {
        return (await caches.match(APP_SHELL_URL)) || Response.error();
      }
    })());
    return;
  }

  // Cache-first for local static assets.
  if (url.origin === self.location.origin && url.pathname.startsWith("/static/")) {
    event.respondWith((async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(CACHE_NAME);
        cache.put(req, fresh.clone());
        return fresh;
      } catch (_) {
        return Response.error();
      }
    })());
    return;
  }

  // Default: network first with shell fallback.
  event.respondWith(
    fetch(req).catch(() => caches.match(req).then((r) => r || caches.match(APP_SHELL_URL)))
  );
});
