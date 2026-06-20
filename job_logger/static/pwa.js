"use strict";

const closeAppButtons = document.querySelectorAll("[data-close-app-button]");
const CLOSE_FALLBACK_DELAY_MS = 250;

function isStandaloneDisplayMode() {
  const isStandaloneMedia = typeof window.matchMedia === "function"
    && window.matchMedia("(display-mode: standalone)").matches;
  const isAppleStandalone = typeof navigator !== "undefined" && navigator.standalone === true;
  return isStandaloneMedia || isAppleStandalone;
}

function leaveAppSurface() {
  window.location.replace("about:blank");
}

function closeCurrentAppWindow() {
  if (!isStandaloneDisplayMode()) {
    leaveAppSurface();
    return;
  }

  const selfTargetedWindow = window.open("", "_self");
  if (selfTargetedWindow && typeof selfTargetedWindow.close === "function") {
    selfTargetedWindow.close();
  } else {
    window.close();
  }
  window.setTimeout(() => {
    if (document.visibilityState === "hidden") {
      return;
    }

    // If the platform refuses to close the window, leave the authenticated app
    // surface without posting logout or visiting another app route.
    leaveAppSurface();
  }, CLOSE_FALLBACK_DELAY_MS);
}

closeAppButtons.forEach((closeAppButton) => {
  closeAppButton.addEventListener("click", (event) => {
    event.preventDefault();
    // Installed mobile web apps often require the current window to be
    // self-targeted before a close request is honored. Regular browser tabs may
    // still ignore the request, so this control intentionally avoids logout or
    // app-route navigation side effects when the platform refuses to close.
    closeCurrentAppWindow();
  });
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js", {scope: "/"}).catch(() => {
      // Registration failure should not block authenticated job entry.
    });
  });
}
