"use strict";

const SERVICE_WORKER_VERSION = "job-logger-pwa-1.1.0";

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") {
    return;
  }

  // Keep authenticated workflow data network-only. This service worker exists
  // for standalone PWA behavior, not for offline caching of job or Autotask data.
  event.respondWith(fetch(event.request));
});
