/* CYCLOPS service worker: offline field mode.
   Static shell: cache-first. GET /api/*: network-first, falling back to the last cached copy
   (latest risk map, routes, shelters, reach table). POSTs are never cached; reports are queued
   in the page (localStorage) and synced with idempotent client_report_id. */
const STATIC = "cyclops-static-v4";
const DATA = "cyclops-data-v4";
const SHELL = ["/", "/static/styles.css", "/static/app.js", "/static/cyclone-bg.js", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(STATIC).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => ![STATIC, DATA].includes(k)).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(DATA).then((c) => c.put(req, copy));
        return res;
      }).catch(() => caches.match(req).then((r) => r || new Response(JSON.stringify({ detail: "Offline and no cached copy" }), { status: 503, headers: { "Content-Type": "application/json" } })))
    );
    return;
  }
  e.respondWith(caches.match(req).then((r) => r || fetch(req).then((res) => {
    if (res.ok && (url.origin === location.origin || url.hostname.endsWith("cdnjs.cloudflare.com") || url.hostname.includes("fonts."))) {
      const copy = res.clone();
      caches.open(STATIC).then((c) => c.put(req, copy));
    }
    return res;
  })));
});
