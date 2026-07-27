"use strict";

const TicketPilotBranding = (() => {
  const LIGHT_THEME_PREFIX = "light";

  function logoVariant(theme) {
    if (typeof theme !== "string") {
      return "grey";
    }
    if (theme === LIGHT_THEME_PREFIX || theme.startsWith(`${LIGHT_THEME_PREFIX}-`)) {
      return "black";
    }
    if (theme === "dark" || theme.startsWith("dark-")) {
      return "white";
    }
    return "grey";
  }

  function applyTheme(theme) {
    const variant = logoVariant(theme);
    const datasetProperty = `logo${variant.charAt(0).toUpperCase()}${variant.slice(1)}`;

    document.querySelectorAll("[data-theme-logo]").forEach((logo) => {
      const source = logo.dataset[datasetProperty];
      if (source) {
        logo.setAttribute("src", source);
      }
    });
    document.querySelectorAll("[data-theme-favicon]").forEach((favicon) => {
      const source = favicon.dataset[datasetProperty];
      if (source) {
        favicon.setAttribute("href", source);
      }
    });
  }

  function currentTheme() {
    const themeClass = Array.from(document.documentElement.classList).find((className) => (
      className.startsWith("theme-")
    ));
    return themeClass ? themeClass.slice("theme-".length) : "";
  }

  return {applyTheme, currentTheme, logoVariant};
})();

window.TicketPilotBranding = TicketPilotBranding;
TicketPilotBranding.applyTheme(TicketPilotBranding.currentTheme());

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js", {scope: "/"}).catch(() => {
      // Registration failure should not block authenticated job entry.
    });
  });
}
