"use strict";

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js", {scope: "/"}).catch(() => {
      // Registration failure should not block authenticated job entry.
    });
  });
}
