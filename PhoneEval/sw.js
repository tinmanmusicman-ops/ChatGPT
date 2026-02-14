const CACHE_NAME = "phoneeval-share-v1";
const SHARED_DATA_PATH = "shared-data";

self.addEventListener("install", function () {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

function sharedDataUrl() {
  return new URL("./" + SHARED_DATA_PATH, self.registration.scope).toString();
}

async function writeSharedData(text) {
  const cache = await caches.open(CACHE_NAME);
  await cache.put(
    sharedDataUrl(),
    new Response(text, {
      headers: { "Content-Type": "text/plain; charset=utf-8" }
    })
  );
}

async function readSharedData() {
  const cache = await caches.open(CACHE_NAME);
  const hit = await cache.match(sharedDataUrl());
  if (hit) {
    return hit;
  }
  return new Response("", {
    status: 204,
    headers: { "Content-Type": "text/plain; charset=utf-8" }
  });
}

function buildSharedText(formData) {
  const title = String(formData.get("title") || "").trim();
  const text = String(formData.get("text") || "").trim();
  const url = String(formData.get("url") || "").trim();
  const lines = [];
  if (title) lines.push("Title: " + title);
  if (text) lines.push(text);
  if (url) lines.push("URL: " + url);
  return lines.join("\n\n").trim();
}

function isPathMatch(pathname, suffix) {
  return pathname === suffix || pathname.endsWith("/" + suffix) || pathname.endsWith("/" + suffix + "/");
}

self.addEventListener("fetch", function (event) {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method === "GET" && isPathMatch(url.pathname, SHARED_DATA_PATH)) {
    event.respondWith(readSharedData());
    return;
  }

  if (req.method === "POST" && isPathMatch(url.pathname, "share-target")) {
    event.respondWith((async function () {
      let merged = "";
      try {
        const formData = await req.formData();
        merged = buildSharedText(formData);
      } catch (err) {
        merged = "";
      }

      if (!merged) {
        merged = "No text was shared.";
      }

      await writeSharedData(merged);
      const target = new URL("./index.html?shared=1&auto=1", self.registration.scope);
      return Response.redirect(target.toString(), 303);
    })());
  }
});
