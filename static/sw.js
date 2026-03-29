/**
 * Offline shell — логика как в habirov: главная по pathname '/', не только navigate.
 * На iOS запрос документа иногда не помечается как navigate → иначе уходит в network-first и белый экран офлайн.
 */
const CACHE_NAME = "zp-widget-cache-v5";
const APP_SHELL_URL = "/";

const urlsToPrecache = [
  "/",
  "/index.html",
  "/static/site.webmanifest",
  "/static/icon.svg",
  "/sw.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    for (const url of urlsToPrecache) {
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

function isSameOriginPage(url) {
  return url.origin === self.location.origin && (url.pathname === "/" || url.pathname === "");
}

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const req = event.request;
  const url = new URL(req.url);

  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(req).catch(
        () =>
          new Response('{"error":"offline"}', {
            status: 503,
            headers: { "Content-Type": "application/json" },
          })
      )
    );
    return;
  }

  // Главная: cache-first + фоновое обновление (как habirov pwa/templates/pwa/sw.js)
  if (isSameOriginPage(url)) {
    event.respondWith(
      caches.open(CACHE_NAME).then((cache) =>
        cache.match(req, { ignoreSearch: true }).then((cached) => {
          const tryNetwork = fetch(req)
            .then((response) => {
              if (response && response.status === 200 && response.type !== "error") {
                cache.put(req, response.clone());
                cache.put(APP_SHELL_URL, response.clone());
              }
              return response;
            })
            .catch(() => null);

          if (cached) {
            tryNetwork.catch(() => {});
            return cached;
          }

          return tryNetwork.then(async (response) => {
            if (response && response.status === 200) return response;
            const m =
              (await cache.match(APP_SHELL_URL, { ignoreSearch: true })) ||
              (await cache.match("/index.html", { ignoreSearch: true }));
            if (m) return m;
            return new Response(
              "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>ZP-Widget</title><style>html,body{margin:0;height:100%;background:#0f0f12;color:#e8e8ec;font-family:system-ui,-apple-system,sans-serif}main{height:100%;display:grid;place-items:center;padding:24px;text-align:center}small{color:#888}</style></head><body><main><div><h1 style='margin:0 0 10px 0;font-size:20px'>ZP-Widget</h1><small>Нет кэша. Откройте сайт онлайн хотя бы раз.</small></div></main></body></html>",
              { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } }
            );
          });
        })
      )
    );
    return;
  }

  if (url.origin === self.location.origin && url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(req, { ignoreSearch: true }).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          return response;
        });
      })
    );
    return;
  }

  event.respondWith(
    fetch(req).catch(() =>
      caches.match(req, { ignoreSearch: true }).then(
        (r) =>
          r ||
          caches.match(APP_SHELL_URL, { ignoreSearch: true }) ||
          caches.match("/index.html", { ignoreSearch: true })
      )
    )
  );
});
