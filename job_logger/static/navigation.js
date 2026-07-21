(function () {
  "use strict";

  const REFRESH_AFTER_NAVIGATION_KEY = "jobLoggerRefreshAfterNavigation";

  function isAppleMobileDevice(userAgent, platform, maxTouchPoints) {
    const safeUserAgent = String(userAgent || "");
    const safePlatform = String(platform || "");
    return /iPad|iPhone|iPod/i.test(safeUserAgent)
      || (safePlatform === "MacIntel" && Number(maxTouchPoints || 0) > 1);
  }

  function currentDeviceInfo() {
    return {
      userAgent: navigator.userAgent,
      platform: navigator.platform,
      maxTouchPoints: navigator.maxTouchPoints,
      userAgentDataMobile: navigator.userAgentData?.mobile,
      primaryPointerCoarse: (
        typeof window.matchMedia === "function"
        && window.matchMedia("(pointer: coarse)").matches
      ),
    };
  }

  function isMobileDevice(deviceInfo) {
    const resolvedDeviceInfo = deviceInfo || currentDeviceInfo();
    if (resolvedDeviceInfo.userAgentDataMobile === true) {
      return true;
    }

    const safeUserAgent = String(resolvedDeviceInfo.userAgent || "");
    if (
      /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile|Tablet|PlayBook|Kindle|Silk/i
        .test(safeUserAgent)
    ) {
      return true;
    }

    // Some Windows and ChromeOS tablets use a desktop-style user agent. A
    // touch-capable device whose primary pointer is coarse is treated as a
    // tablet without confusing ordinary mouse/trackpad desktop sessions.
    if (
      Number(resolvedDeviceInfo.maxTouchPoints || 0) > 0
      && resolvedDeviceInfo.primaryPointerCoarse === true
    ) {
      return true;
    }

    // iPadOS can report a desktop Mac platform. Multiple touch points
    // distinguish that browser shape without using viewport width.
    return isAppleMobileDevice(
      safeUserAgent,
      resolvedDeviceInfo.platform,
      resolvedDeviceInfo.maxTouchPoints,
    );
  }

  function booleanDataValue(rawValue) {
    return rawValue === true || String(rawValue || "").trim().toLowerCase() === "true";
  }

  function isNavigationAllowed(allowFullWeb, deviceInfo) {
    return isMobileDevice(deviceInfo) || booleanDataValue(allowFullWeb);
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

    const resolvedDeviceInfo = deviceInfo || currentDeviceInfo();
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
    const launchOptions = options || {};
    if (!isNavigationAllowed(launchOptions.allowFullWeb, launchOptions.deviceInfo)) {
      return false;
    }
    const navigationUrl = buildNavigationUrl(navigationApp, address);
    if (!navigationUrl) {
      return false;
    }
    if (launchOptions.refreshOnReturn) {
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
      const allowedOnDevice = isNavigationAllowed(button.dataset.navigationAllowFullWeb);
      const buttonAvailable = available && allowedOnDevice;
      button.dataset.navigationApp = buttonAvailable ? navigationApp : "";
      button.dataset.navigationAddress = buttonAvailable ? navigationAddress : "";
      button.classList.toggle("is-hidden", !buttonAvailable);
      button.disabled = !buttonAvailable;
      const mobileNavigationRow = button.closest("[data-mobile-entry-navigation-row]");
      if (mobileNavigationRow) {
        mobileNavigationRow.classList.toggle("is-destination-hidden", !buttonAvailable);
      }
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
      const allowedOnDevice = isNavigationAllowed(button.dataset.navigationAllowFullWeb);
      button.disabled = !allowedOnDevice;
      if (!allowedOnDevice) {
        button.classList.add("is-hidden");
        return;
      }
      navigationUrls.add(navigationUrl);
      button.addEventListener("click", () => {
        launch(button.dataset.navigationApp, button.dataset.navigationAddress, {
          allowFullWeb: button.dataset.navigationAllowFullWeb,
        });
      });
    });
    navigationUrls.forEach(refreshDestination);
  }

  function initializeStaticButtons() {
    let hasAvailableButton = false;
    document.querySelectorAll("[data-static-navigation-button]").forEach((button) => {
      const allowedOnDevice = isNavigationAllowed(button.dataset.navigationAllowFullWeb);
      button.disabled = !allowedOnDevice;
      button.classList.toggle("is-hidden", !allowedOnDevice);
      if (!allowedOnDevice) {
        return;
      }
      hasAvailableButton = true;
      button.addEventListener("click", () => {
        launch(button.dataset.navigationApp, button.dataset.navigationAddress, {
          allowFullWeb: button.dataset.navigationAllowFullWeb,
        });
      });
    });
    document.querySelectorAll("[data-quick-navigation-row]").forEach((row) => {
      row.classList.toggle("is-hidden", !hasAvailableButton);
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
    isMobileDevice,
    isNavigationAllowed,
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
