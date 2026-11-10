const CACHE='visimed-territory-01b7770e272136ae';
const FILES=["/territorio/index.html", "/territorio/inter.woff2", "/territorio/navigation.css", "/territorio/product-theme.css", "/territorio/assets/index-D1juPHt1.js", "/territorio/assets/index-D8mHLodT.css", "/territorio/assets/web-DH0FuRwi.js"];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(FILES)).then(()=>self.skipWaiting()))});
self.addEventListener('activate',e=>e.waitUntil((async()=>{for(const k of await caches.keys()){if(k.startsWith('visimed-territory-')&&k!==CACHE)await caches.delete(k)}await self.clients.claim()})()));
self.addEventListener('fetch',e=>{const u=new URL(e.request.url);if(e.request.method!=='GET'||u.origin!==self.location.origin||!u.pathname.startsWith('/territorio/'))return;
if(e.request.mode==='navigate')e.respondWith(fetch(e.request).then(r=>r.ok?r:caches.match('/territorio/index.html')).catch(()=>caches.match('/territorio/index.html')));
else if(FILES.includes(u.pathname))e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request)));
});