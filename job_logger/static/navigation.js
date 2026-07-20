(function () {
  "use strict";

  const REFRESH_AFTER_NAVIGATION_KEY = "jobLoggerRefreshAfterNavigation";

  function isAppleMobileDevice(userAgent, platform, maxTouchPoints) {
    const safeUserAgent = String(userAgent || "");
    const safePlatform = String(platform || "");
    return /iPad|iPhone|iPod/i.test(safeUserAgent)
      || (safePlatform === "MacIntel" && Number(maxTouchPoints || 0) > 1);
  }

  function buildNavigationUrl(navigationApp, address, deviceInfo) {
    const safeAddress = String(address || "").trim();
    if (!safeAddress || navigationApp === "none") {
      return "";
    }

    const encodedAddress = encodeURIComponent(safeAddress);
    if (navigationApp === "waze") {
      return `https://waze.com/ul?q=${encodedAddress}&navigate=yes`;
    }
    if (navigationApp === "google_maps") {
      return `https://www.google.com/maps/dir/?api=1&destination=${encodedAddress}`;
    }
    if (navigationApp === "apple_maps") {
      return `https://maps.apple.com/?daddr=${encodedAddress}&dirflg=d`;
    }
    if (navigationApp !== "device_default") {
      return "";
    }

    const resolvedDeviceInfo = deviceInfo || {
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      maxTouchPoints: navigator.maxTouchPoints,
    };
    if (isAppleMobileDevice(
      resolvedDeviceInfo.userAgent,
      resolvedDeviceInfo.platform,
      resolvedDeviceInfo.maxTouchPoints,
    )) {
      return `https://maps.apple.com/?daddr=${encodedAddress}&dirflg=d`;
    }
    if (/Android/i.test(String(resolvedDeviceInfo.userAgent || ""))) {
      return `geo:0,0?q=${encodedAddress}`;
    }
    return `https://www.google.com/maps/dir/?api=1&destination=${encodedAddress}`;
  }

  function launch(navigationApp, address, options) {
    const navigationUrl = buildNavigationUrl(navigationApp, address);
    if (!navigationUrl) {
      return false;
    }
    if (options && options.refreshOnReturn) {
      try {
        sessionStorage.setItem(REFRESH_AFTER_NAVIGATION_KEY, "true");
      } catch (_error) {
        // Browser privacy modes may disable session storage. Navigation itself
        // remains useful, so failure to set the refresh hint is non-fatal.
      }
    }
    window.location.href = navigationUrl;
    return true;
  }

  function buttonsForNavigationUrl(navigationUrl) {
    return Array.from(document.querySelectorAll("[data-ticket-navigation-button]"))
      .filter((button) => button.dataset.navigationUrl === navigationUrl);
  }

  function applyDestination(navigationUrl, payload) {
    const navigationApp = String(payload?.navigation_app || "none");
    const navigationAddress = String(payload?.navigation_address || "").trim();
    const available = Boolean(payload?.available !== false && navigationApp !== "none" && navigationAddress);
    buttonsForNavigationUrl(navigationUrl).forEach((button) => {
      button.dataset.navigationApp = available ? navigationApp : "";
      button.dataset.navigationAddress = available ? navigationAddress : "";
      button.classList.toggle("is-hidden", !available);
      button.disabled = !available;
    });
  }

  async function refreshDestination(navigationUrl) {
    if (!navigationUrl) {
      return;
    }
    try {
      const response = await fetch(navigationUrl, {headers: {Accept: "application/json"}});
      const payload = await response.json();
      applyDestination(navigationUrl, response.ok ? payload : {available: false});
    } catch (_error) {
      applyDestination(navigationUrl, {available: false});
    }
  }

  function initializeTicketButtons() {
    const navigationUrls = new Set();
    document.querySelectorAll("[data-ticket-navigation-button]").forEach((button) => {
      const navigationUrl = button.dataset.navigationUrl || "";
      navigationUrls.add(navigationUrl);
      button.addEventListener("click", () => {
        launch(button.dataset.navigationApp, button.dataset.navigationAddress);
      });
    });
    navigationUrls.forEach(refreshDestination);
  }

  function initializeStaticButtons() {
    document.querySelectorAll("[data-static-navigation-button]").forEach((button) => {
      button.addEventListener("click", () => {
        launch(button.dataset.navigationApp, button.dataset.navigationAddress);
      });
    });
  }

  function refreshPageAfterReturningFromAutomaticNavigation() {
    try {
      if (sessionStorage.getItem(REFRESH_AFTER_NAVIGATION_KEY) !== "true") {
        return;
      }
      sessionStorage.removeItem(REFRESH_AFTER_NAVIGATION_KEY);
      window.location.reload();
    } catch (_error) {
      // The active page remains usable when storage is unavailable.
    }
  }

  window.JobLoggerNavigation = {
    applyDestination,
    buildNavigationUrl,
    isAppleMobileDevice,
    launch,
    refreshDestination,
  };

  initializeStaticButtons();
  initializeTicketButtons();
  window.addEventListener("pageshow", refreshPageAfterReturningFromAutomaticNavigation);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      refreshPageAfterReturningFromAutomaticNavigation();
    }
  });
}());
