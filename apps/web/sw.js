// Service worker for the farmer app (FR-32): keeps the app and the photo-check libraries available with no network.
// Model weights are cached by transformers.js itself. API calls are never cached.
const CACHE = "ghante72-v2";
const SHELL = ["/farmer", "/static/farmer.css", "/static/farmer.js", "/static/edge-worker.js", "/static/label_embeddings.json"];
const LIBRARY_HOSTS = ["cdn.jsdelivr.net"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url)))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("ghante72-") && k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (LIBRARY_HOSTS.includes(url.hostname)) {
    // versioned library files never change: cache first
    event.respondWith(caches.open(CACHE).then(async (cache) => {
      const hit = await cache.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok || res.type === "opaque") cache.put(req, res.clone());
      return res;
    }));
    return;
  }
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/internal/")) return;
  const shell = url.pathname === "/farmer" || url.pathname.startsWith("/static/");
  if (!shell) return;
  // our own files: the network copy when there is one (so a new build shows up), the cached copy when there is not
  event.respondWith(caches.open(CACHE).then(async (cache) => {
    try {
      const res = await fetch(req);
      if (res.ok) cache.put(url.pathname === "/farmer" ? "/farmer" : req, res.clone());
      return res;
    } catch (err) {
      const hit = await cache.match(url.pathname === "/farmer" ? "/farmer" : req);
      if (hit) return hit;
      throw err;
    }
  }));
});
