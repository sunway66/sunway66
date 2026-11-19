/* 顺为数据 PWA Service Worker
 * 策略：
 *  - 页面导航：网络优先，离线回退 index.html
 *  - data.json：网络优先，离线回退最近一次缓存
 *  - 同源静态资源：stale-while-revalidate
 *  - Chart.js CDN：cache-first
 */

const CACHE_VERSION = "shunwei-data-v11";
const CACHE_NAME = `${CACHE_VERSION}-shell`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

const SCOPE = self.registration.scope;
const absolute = (path) => new URL(path, SCOPE).href;

const APP_SHELL = [
  "./",
  "./index.html",
  "./styles.css",
  "./app.js",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png",
  "./icons/favicon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        Promise.allSettled(APP_SHELL.map((path) => cache.add(absolute(path)))),
      )
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME && key !== RUNTIME_CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  if (request.mode === "navigate") {
    event.respondWith(networkFirst(request, absolute("./index.html"), true));
    return;
  }

  if (url.origin === self.location.origin && url.pathname.endsWith("/data.json")) {
    event.respondWith(networkFirst(request, absolute("./data.json"), false));
    return;
  }

  if (url.origin === self.location.origin) {
    const path = url.pathname;
    if (
      path.endsWith("/app.js") ||
      path.endsWith("/styles.css") ||
      path.endsWith("/index.html")
    ) {
      event.respondWith(networkFirstAsset(request));
      return;
    }
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  if (url.hostname.includes("jsdelivr.net") || url.hostname.includes("unpkg.com")) {
    event.respondWith(cacheFirst(request));
  }
});

async function networkFirst(request, fallbackUrl, navigation) {
  const cache = await caches.open(RUNTIME_CACHE);
  try {
    const response = await fetch(request, { cache: "no-store" });
    if (response && response.ok) {
      if (navigation) {
        const shell = await caches.open(CACHE_NAME);
        await shell.put(fallbackUrl, response.clone());
      } else {
        // data.json 每次请求带不同的时间戳，统一按无查询串的地址缓存，避免缓存膨胀。
        await cache.put(fallbackUrl, response.clone());
      }
    }
    return response;
  } catch (error) {
    const cached =
      (await cache.match(request, { ignoreSearch: true })) ||
      (await caches.match(request, { ignoreSearch: true }));
    if (cached) return cached;
    if (navigation) {
      const shell = await caches.open(CACHE_NAME);
      const fallback = await shell.match(fallbackUrl);
      if (fallback) return fallback;
    }
    return new Response(
      JSON.stringify({ error: "offline", message: "当前离线且没有缓存数据" }),
      {
        status: 503,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      },
    );
  }
}

async function networkFirstAsset(request) {
  const shell = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request, { cache: "no-store" });
    if (response && response.ok) {
      await shell.put(request, response.clone());
    }
    return response;
  } catch (error) {
    const cached =
      (await shell.match(request)) ||
      (await caches.match(request, { ignoreSearch: true }));
    if (cached) return cached;
    return new Response("", { status: 503, statusText: "Offline" });
  }
}

async function staleWhileRevalidate(request) {  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) {
        cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  if (cached) {
    network.catch(() => {});
    return cached;
  }

  const response = await network;
  if (response) return response;
  return new Response("", { status: 503, statusText: "Offline" });
}

async function cacheFirst(request) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;

  try {
    const response = await fetch(request);
    if (response && (response.ok || response.type === "opaque")) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (error) {
    return new Response("", { status: 503, statusText: "Offline" });
  }
}
