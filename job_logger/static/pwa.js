"use strict";

const closeAppButtons = document.querySelectorAll("[data-close-app-button]");

closeAppButtons.forEach((closeAppButton) => {
  closeAppButton.addEventListener("click", () => {
    // Installed mobile web apps can usually honor window.close(); regular
    // browser tabs may ignore it, so this control intentionally avoids logout
    // or navigation side effects when the browser refuses to close.
    window.close();
  });
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js", {scope: "/"}).catch(() => {
      // Registration failure should not block authenticated job entry.
    });
  });
}
