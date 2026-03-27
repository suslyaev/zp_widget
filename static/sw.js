const CACHE_NAME = "zp-widget-cache-v4";
const APP_SHELL_URL = "/";
const STATIC_ASSETS = [
  "/",
  "/index.html",
  "/static/site.webmanifest",
  "/static/icon.svg",
  "/sw.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // Safari-friendly install: avoid Promise.allSettled and tolerate single-asset failures.
    for (const url of STATIC_ASSETS) {
      try {
        const res = await fetch(url, { cache: "reload" });
        if (res && res.ok) await cache.put(url, res.clone());
      } catch (_) {}
    }
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

  // App shell for PWA open/reopen: serve cache first to avoid white-screen waits.
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      const cachedShell =
        (await cache.match(req, { ignoreSearch: true })) ||
        (await cache.match(APP_SHELL_URL, { ignoreSearch: true })) ||
        (await cache.match("/index.html", { ignoreSearch: true }));
      if (cachedShell) {
        // Refresh app shell in background when network is available.
        event.waitUntil((async () => {
          try {
            const fresh = await fetch(APP_SHELL_URL, { cache: "no-store" });
            if (fresh.ok) await cache.put(APP_SHELL_URL, fresh.clone());
          } catch (_) {}
        })());
        return cachedShell;
      }
      try {
        const fresh = await fetch(APP_SHELL_URL, { cache: "no-store" });
        if (fresh.ok) await cache.put(APP_SHELL_URL, fresh.clone());
        return fresh;
      } catch (_) {
        return new Response(
          "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>ZP-Widget</title><style>html,body{margin:0;height:100%;background:#0f0f12;color:#e8e8ec;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}main{height:100%;display:grid;place-items:center;padding:24px;text-align:center}small{color:#888}</style></head><body><main><div><h1 style='margin:0 0 10px 0;font-size:20px'>ZP-Widget</h1><small>Офлайн-режим недоступен до первой успешной загрузки приложения.</small></div></main></body></html>",
          { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } }
        );
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
    fetch(req).catch(() =>
      caches.match(req, { ignoreSearch: true }).then((r) =>
        r ||
        caches.match(APP_SHELL_URL, { ignoreSearch: true }) ||
        caches.match("/index.html", { ignoreSearch: true })
      )
    )
  );
});
