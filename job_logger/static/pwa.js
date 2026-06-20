"use strict";

const closeAppButtons = document.querySelectorAll("[data-close-app-button]");
const CLOSE_FALLBACK_DELAY_MS = 250;

function leaveAppSurface() {
  window.location.replace("about:blank");
}

function closeCurrentAppWindow() {
  try {
    window.close();
  } catch {
    // Some browsers throw when closing a window they did not create. The timer
    // below still lets the user leave the app surface without logging out.
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
    // Installed mobile web apps usually honor a direct close request. Regular
    // browser tabs may ignore it, so the fallback intentionally avoids logout or
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
