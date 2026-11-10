const CACHE_NAME = "patchy-shell-v2";
const SHELL_ASSETS = [
  "./",
  "index.html",
  "404.html",
  "favicon.svg",
  "apple-touch-icon.png",
  "manifest.webmanifest",
  "assets/style.css",
  "assets/boot.js",
  "assets/app.js",
  "assets/data.js",
  "assets/glass.js",
  "assets/backdrop.js",
  "assets/world.js",
  "assets/hero.js",
  "assets/perf.js",
  "assets/i18n.js",
  "assets/vendor/glassy-liquid.min.js",
  "assets/fonts/inter-400.woff2",
  "assets/fonts/inter-600.woff2",
  "assets/fonts/inter-display-700.woff2"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);

  if (url.pathname.endsWith("/data/catalog.json")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response && response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const networkFetch = fetch(request)
          .then((response) => {
            if (response && response.status === 200) {
              const clone = response.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
            }
            return response;
          })
          .catch(() => cached);
        return cached || networkFetch;
      })
    );
  }
});
