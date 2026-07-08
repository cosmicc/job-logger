(function () {
  "use strict";

  let verificationToken = "";
  let turnstileWidgetId = null;
  let turnstileRenderAttempted = false;
  let turnstileApiLoadFailed = false;
  let turnstileFallbackLoadAttempted = false;
  let loadCheckCount = 0;
  const maxLoadChecks = 30;

  function elements() {
    return {
      form: document.querySelector('form[action="/forgot-password"]'),
      widget: document.querySelector("[data-turnstile-widget]"),
      status: document.querySelector("[data-turnstile-status]"),
      submit: document.querySelector("[data-password-reset-submit]"),
      apiScript: document.querySelector("[data-turnstile-api-script]"),
    };
  }

  function setStatus(message, isError) {
    const statusElement = elements().status;
    if (!statusElement) {
      return;
    }
    statusElement.textContent = message;
    statusElement.classList.toggle("turnstile-status-error", Boolean(isError));
  }

  function setSubmitEnabled(enabled) {
    const submitButton = elements().submit;
    if (!submitButton) {
      return;
    }
    submitButton.disabled = !enabled;
  }

  function turnstileAvailable() {
    return window.turnstile && typeof window.turnstile.render === "function";
  }

  function submittedToken() {
    const responseInput = document.querySelector('input[name="cf-turnstile-response"]');
    return verificationToken || (responseInput ? responseInput.value : "");
  }

  function widgetHasRenderedMarkup() {
    const widgetElement = elements().widget;
    return Boolean(widgetElement && widgetElement.querySelector('iframe, input[name="cf-turnstile-response"]'));
  }

  function renderTurnstileWidget() {
    const widgetElement = elements().widget;
    if (!widgetElement || turnstileWidgetId !== null || turnstileRenderAttempted || !turnstileAvailable()) {
      return;
    }

    turnstileRenderAttempted = true;
    try {
      turnstileWidgetId = window.turnstile.render("#password-reset-turnstile", {
        sitekey: widgetElement.dataset.sitekey || "",
        theme: widgetElement.dataset.theme || "auto",
        action: "password_reset",
        appearance: "always",
        execution: "render",
        "response-field": true,
        "response-field-name": "cf-turnstile-response",
        callback: handleTurnstileSuccess,
        "error-callback": handleTurnstileError,
        "expired-callback": handleTurnstileExpired,
        "timeout-callback": handleTurnstileTimeout,
        "unsupported-callback": handleTurnstileUnsupported,
      });
      setStatus("Complete human verification before sending the reset link.", false);
    } catch (_error) {
      turnstileWidgetId = null;
      verificationToken = "";
      setStatus("Human verification could not start. Reload this page and try again.", true);
      setSubmitEnabled(false);
    }
  }

  function handleTurnstileSuccess(token) {
    verificationToken = token || "";
    setStatus("Human verification complete.", false);
    setSubmitEnabled(Boolean(verificationToken));
  }

  function handleTurnstileError() {
    verificationToken = "";
    setStatus("Human verification could not complete. Reload this page and try again.", true);
    setSubmitEnabled(false);
  }

  function handleTurnstileExpired() {
    verificationToken = "";
    setStatus("Human verification expired. Complete it again before sending the reset link.", true);
    setSubmitEnabled(false);
  }

  function handleTurnstileTimeout() {
    verificationToken = "";
    setStatus("Human verification timed out. Complete it again before sending the reset link.", true);
    setSubmitEnabled(false);
  }

  function handleTurnstileUnsupported() {
    verificationToken = "";
    setStatus("This browser does not support human verification. Try another browser or device.", true);
    setSubmitEnabled(false);
  }

  function setupFormGuard() {
    const formElement = elements().form;
    if (!formElement || formElement.dataset.turnstileGuardAttached === "true") {
      return;
    }
    formElement.dataset.turnstileGuardAttached = "true";
    formElement.addEventListener("submit", function (event) {
      if (!elements().widget || submittedToken()) {
        return;
      }
      event.preventDefault();
      setStatus("Human verification is not complete yet. Wait for it to finish, then try again.", true);
      setSubmitEnabled(false);
    });
  }

  function exposeTurnstileCallbacks() {
    window.jobLoggerTurnstileSuccess = handleTurnstileSuccess;
    window.jobLoggerTurnstileError = handleTurnstileError;
    window.jobLoggerTurnstileExpired = handleTurnstileExpired;
    window.jobLoggerTurnstileTimeout = handleTurnstileTimeout;
    window.jobLoggerTurnstileUnsupported = handleTurnstileUnsupported;
  }

  function loadFallbackTurnstileScript() {
    const apiScript = elements().apiScript;
    const fallbackSource = apiScript ? apiScript.dataset.turnstileFallbackSrc : "";
    if (!fallbackSource || turnstileFallbackLoadAttempted || !document.createElement) {
      return false;
    }

    turnstileFallbackLoadAttempted = true;
    const fallbackScript = document.createElement("script");
    fallbackScript.src = fallbackSource;
    fallbackScript.defer = true;
    fallbackScript.async = true;
    fallbackScript.dataset.turnstileApiScript = "true";
    fallbackScript.dataset.turnstileFallbackScript = "true";
    setupTurnstileApiScriptListeners(fallbackScript);
    const scriptParent = document.head || document.body || document.documentElement;
    if (!scriptParent || !scriptParent.appendChild) {
      return false;
    }
    scriptParent.appendChild(fallbackScript);
    setStatus("Human verification is retrying...", false);
    return true;
  }

  function monitorTurnstileLoad() {
    if (submittedToken()) {
      return;
    }
    if (turnstileAvailable()) {
      renderTurnstileWidget();
      return;
    }
    if (turnstileApiLoadFailed) {
      setStatus("Human verification could not load. Reload this page or check browser content blockers.", true);
      setSubmitEnabled(false);
      return;
    }
    if (widgetHasRenderedMarkup()) {
      setStatus("Complete human verification before sending the reset link.", false);
      return;
    }
    loadCheckCount += 1;
    if (loadCheckCount >= maxLoadChecks) {
      setStatus("Human verification is still loading. Reload this page if the verification box stays blank.", true);
      return;
    }
    window.setTimeout(monitorTurnstileLoad, 1000);
  }

  function setupTurnstileApiScriptListeners(apiScript) {
    if (!apiScript || apiScript.dataset.turnstileListenersAttached === "true") {
      return;
    }
    apiScript.dataset.turnstileListenersAttached = "true";
    apiScript.addEventListener("load", function () {
      window.setTimeout(monitorTurnstileLoad, 0);
    });
    apiScript.addEventListener("error", function () {
      if (loadFallbackTurnstileScript()) {
        return;
      }
      turnstileApiLoadFailed = true;
      monitorTurnstileLoad();
    });
  }

  function setupTurnstileApiListeners() {
    setupTurnstileApiScriptListeners(elements().apiScript);
  }

  function initialize() {
    setSubmitEnabled(false);
    setStatus("Human verification is loading...", false);
    setupFormGuard();
    setupTurnstileApiListeners();
    exposeTurnstileCallbacks();
    monitorTurnstileLoad();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }

  exposeTurnstileCallbacks();
})();
