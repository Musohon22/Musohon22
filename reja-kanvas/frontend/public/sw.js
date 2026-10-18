// App-shell cache so the app opens offline. API calls are never cached here:
// plan data offline comes from the app's own local store and outbox.
const CACHE = "reja-shell-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  const isAsset = url.pathname.startsWith("/_next/static/") || /\.(svg|png|woff2|webmanifest)$/.test(url.pathname);
  if (isAsset) {
    // immutable build assets: cache first
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      })),
    );
  } else if (req.mode === "navigate") {
    // pages: network first, fall back to the last copy
    event.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req).then((hit) => hit || caches.match("/canvas"))),
    );
  }
});
