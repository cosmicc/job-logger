(function () {
  "use strict";

  let verificationToken = "";

  function elements() {
    return {
      form: document.querySelector('form[action="/forgot-password"]'),
      widget: document.querySelector("[data-turnstile-widget]"),
      status: document.querySelector("[data-turnstile-status]"),
      submit: document.querySelector("[data-password-reset-submit]"),
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

  function initialize() {
    setSubmitEnabled(false);
    setStatus("Human verification is loading...", false);
    setupFormGuard();
    exposeTurnstileCallbacks();
    window.setTimeout(function () {
      if (submittedToken()) {
        return;
      }
      if (turnstileAvailable() || widgetHasRenderedMarkup()) {
        setStatus("Complete human verification before sending the reset link.", false);
        return;
      }
      setStatus("Human verification could not load. Reload this page or check browser content blockers.", true);
    }, 8000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }

  exposeTurnstileCallbacks();
})();
