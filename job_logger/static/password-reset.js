(function () {
  "use strict";

  let widgetId = null;
  let widgetRendered = false;
  let widgetRenderScheduled = false;
  let verificationToken = "";
  const turnstileWidgetSelector = "#password-reset-turnstile";

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

  function renderTurnstileWidget() {
    const widgetElement = elements().widget;
    if (!widgetElement || widgetRendered) {
      return;
    }

    try {
      widgetId = window.turnstile.render(turnstileWidgetSelector, {
        sitekey: widgetElement.dataset.sitekey || "",
        theme: widgetElement.dataset.theme || "auto",
        action: "password_reset",
        appearance: "always",
        execution: "render",
        "response-field": true,
        "response-field-name": "cf-turnstile-response",
        callback(token) {
          verificationToken = token || "";
          setStatus("Human verification complete.", false);
          setSubmitEnabled(Boolean(verificationToken));
        },
        "error-callback"() {
          verificationToken = "";
          setStatus("Human verification could not complete. Reload this page and try again.", true);
          setSubmitEnabled(false);
        },
        "expired-callback"() {
          verificationToken = "";
          setStatus("Human verification expired. Complete it again before sending the reset link.", true);
          setSubmitEnabled(false);
        },
        "timeout-callback"() {
          verificationToken = "";
          setStatus("Human verification timed out. Complete it again before sending the reset link.", true);
          setSubmitEnabled(false);
        },
        "unsupported-callback"() {
          verificationToken = "";
          setStatus("This browser does not support human verification. Try another browser or device.", true);
          setSubmitEnabled(false);
        },
      });
      widgetRendered = true;
      setStatus("Human verification is running...", false);
    } catch (_error) {
      widgetId = null;
      widgetRendered = false;
      verificationToken = "";
      setStatus("Human verification could not load. Reload this page or check browser content blockers.", true);
      setSubmitEnabled(false);
    }
  }

  function renderTurnstile() {
    if (!elements().widget || widgetRendered) {
      return;
    }

    if (!turnstileAvailable()) {
      setStatus("Human verification is loading...", false);
      setSubmitEnabled(false);
      return;
    }

    if (typeof window.turnstile.ready === "function") {
      if (widgetRenderScheduled) {
        return;
      }
      widgetRenderScheduled = true;
      window.turnstile.ready(function () {
        widgetRenderScheduled = false;
        renderTurnstileWidget();
      });
      return;
    }

    renderTurnstileWidget();
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
      if (window.turnstile && widgetId !== null && typeof window.turnstile.reset === "function") {
        try {
          window.turnstile.reset(widgetId);
        } catch (_error) {
          setStatus("Human verification could not restart. Reload this page and try again.", true);
        }
      }
    });
  }

  function initialize() {
    setSubmitEnabled(false);
    setupFormGuard();
    renderTurnstile();
    window.setTimeout(function () {
      if (!submittedToken()) {
        if (widgetRendered) {
          setStatus(
            "Complete human verification before sending the reset link. Reload this page if the verification box stays blank.",
            true,
          );
        } else {
          setStatus("Human verification could not load. Reload this page or check browser content blockers.", true);
        }
      }
    }, 8000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }

  window.jobLoggerTurnstileReady = renderTurnstile;
})();
