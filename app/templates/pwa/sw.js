// Sünger CRM service worker — sürüm {{ surum }}
// Sayfalar her zaman sunucudan gelir (müşteri verisi önbelleğe alınmaz).
// İnternet yoksa yalnızca "bağlantı yok" sayfası gösterilir.
const ONBELLEK = "sunger-crm-{{ surum }}";
const CEVRIMDISI = "{{ cevrimdisi }}";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(ONBELLEK).then((c) => c.addAll([CEVRIMDISI, "{{ simge }}"])));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((adlar) => Promise.all(adlar.filter((a) => a !== ONBELLEK).map((a) => caches.delete(a))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;   // sayfa dışı istekler tarayıcının kendi yoluyla
  e.respondWith(fetch(e.request).catch(() => caches.match(CEVRIMDISI)));
});
