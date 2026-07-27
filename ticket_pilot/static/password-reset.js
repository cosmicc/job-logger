(function () {
  "use strict";

  let verificationToken = "";
  let turnstileWidgetId = null;
  let turnstileRenderAttempted = false;
  let turnstileApiLoadFailed = false;
  let turnstileFallbackLoadAttempted = false;
  let turnstileLoadFailureLogged = false;
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

  function csrfToken() {
    const csrfMeta = document.querySelector("meta[name='csrf-token']");
    return csrfMeta ? csrfMeta.getAttribute("content") || "" : "";
  }

  function scriptSource(scriptElement) {
    if (!scriptElement) {
      return "";
    }
    if (scriptElement.src) {
      return scriptElement.src;
    }
    if (typeof scriptElement.getAttribute === "function") {
      return scriptElement.getAttribute("src") || "";
    }
    return "";
  }

  function turnstileState(extraDetails) {
    const widgetElement = elements().widget;
    const responseInput = document.querySelector('input[name="cf-turnstile-response"]');
    return Object.assign(
      {
        api_available: turnstileAvailable(),
        fallback_attempted: turnstileFallbackLoadAttempted,
        load_checks: loadCheckCount,
        rendered_markup: widgetHasRenderedMarkup(),
        response_input_present: Boolean(responseInput),
        response_input_has_value: Boolean(responseInput && responseInput.value),
        widget_present: Boolean(widgetElement),
        widget_id_present: turnstileWidgetId !== null,
      },
      extraDetails || {},
    );
  }

  function logTurnstileEvent(eventName, details) {
    if (!window.fetch) {
      return;
    }
    try {
      window.fetch("/forgot-password/turnstile-event", {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken(),
        },
        body: JSON.stringify({
          event: eventName,
          details: details || {},
        }),
      }).catch(function () {});
    } catch (_error) {
      // Logging must never interrupt the password-reset page.
    }
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
    logTurnstileEvent("turnstile.render_attempt", turnstileState({theme: widgetElement.dataset.theme || "auto"}));
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
      logTurnstileEvent("turnstile.rendered", turnstileState({widget_id_type: typeof turnstileWidgetId}));
      setStatus("Complete human verification before sending the reset link.", false);
    } catch (error) {
      turnstileWidgetId = null;
      verificationToken = "";
      logTurnstileEvent(
        "turnstile.render_exception",
        turnstileState({error_name: error && error.name ? error.name : "unknown"}),
      );
      setStatus("Human verification could not start. Reload this page and try again.", true);
      setSubmitEnabled(false);
    }
  }

  function handleTurnstileSuccess(token) {
    verificationToken = token || "";
    logTurnstileEvent("turnstile.callback_success", turnstileState({token_length: verificationToken.length}));
    setStatus("Human verification complete.", false);
    setSubmitEnabled(Boolean(verificationToken));
  }

  function handleTurnstileError() {
    verificationToken = "";
    logTurnstileEvent("turnstile.callback_error", turnstileState());
    setStatus("Human verification could not complete. Reload this page and try again.", true);
    setSubmitEnabled(false);
  }

  function handleTurnstileExpired() {
    verificationToken = "";
    logTurnstileEvent("turnstile.callback_expired", turnstileState());
    setStatus("Human verification expired. Complete it again before sending the reset link.", true);
    setSubmitEnabled(false);
  }

  function handleTurnstileTimeout() {
    verificationToken = "";
    logTurnstileEvent("turnstile.callback_timeout", turnstileState());
    setStatus("Human verification timed out. Complete it again before sending the reset link.", true);
    setSubmitEnabled(false);
  }

  function handleTurnstileUnsupported() {
    verificationToken = "";
    logTurnstileEvent("turnstile.callback_unsupported", turnstileState());
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
      logTurnstileEvent("turnstile.submit_blocked", turnstileState());
      setStatus("Human verification is not complete yet. Wait for it to finish, then try again.", true);
      setSubmitEnabled(false);
    });
  }

  function exposeTurnstileCallbacks() {
    window.ticketPilotTurnstileSuccess = handleTurnstileSuccess;
    window.ticketPilotTurnstileError = handleTurnstileError;
    window.ticketPilotTurnstileExpired = handleTurnstileExpired;
    window.ticketPilotTurnstileTimeout = handleTurnstileTimeout;
    window.ticketPilotTurnstileUnsupported = handleTurnstileUnsupported;
  }

  function loadFallbackTurnstileScript() {
    const apiScript = elements().apiScript;
    const fallbackSource = apiScript ? apiScript.dataset.turnstileFallbackSrc : "";
    if (!fallbackSource || turnstileFallbackLoadAttempted || !document.createElement) {
      logTurnstileEvent(
        "turnstile.fallback_script_unavailable",
        turnstileState({
          primary_src: scriptSource(apiScript),
          has_fallback_src: Boolean(fallbackSource),
        }),
      );
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
      logTurnstileEvent("turnstile.fallback_script_unavailable", turnstileState({reason: "missing_script_parent"}));
      return false;
    }
    scriptParent.appendChild(fallbackScript);
    logTurnstileEvent(
      "turnstile.fallback_script_appended",
      turnstileState({primary_src: scriptSource(apiScript), fallback_src: fallbackSource}),
    );
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
      if (!turnstileLoadFailureLogged) {
        turnstileLoadFailureLogged = true;
        logTurnstileEvent("turnstile.load_failed", turnstileState());
      }
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
      logTurnstileEvent("turnstile.load_timeout", turnstileState());
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
      logTurnstileEvent(
        "turnstile.api_script_load",
        turnstileState({
          script_src: scriptSource(apiScript),
          fallback_script: apiScript.dataset.turnstileFallbackScript === "true",
        }),
      );
      window.setTimeout(monitorTurnstileLoad, 0);
    });
    apiScript.addEventListener("error", function () {
      logTurnstileEvent(
        "turnstile.api_script_error",
        turnstileState({
          script_src: scriptSource(apiScript),
          fallback_script: apiScript.dataset.turnstileFallbackScript === "true",
        }),
      );
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
    logTurnstileEvent(
      "turnstile.initialize",
      turnstileState({
        document_ready_state: document.readyState,
        primary_script_src: scriptSource(elements().apiScript),
        has_fallback_src: Boolean(elements().apiScript && elements().apiScript.dataset.turnstileFallbackSrc),
      }),
    );
    monitorTurnstileLoad();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }

  exposeTurnstileCallbacks();
})();
