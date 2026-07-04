(function () {
  "use strict";

  function csrfToken() {
    const csrfMeta = document.querySelector("meta[name='csrf-token']");
    return csrfMeta ? csrfMeta.getAttribute("content") || "" : "";
  }

  function setStatus(statusElement, message, isError) {
    if (!statusElement) {
      return;
    }
    statusElement.textContent = message;
    statusElement.classList.toggle("error-text", Boolean(isError));
  }

  function setLoading(button, isLoading) {
    if (!button) {
      return;
    }
    button.disabled = Boolean(isLoading);
    button.classList.toggle("is-loading", Boolean(isLoading));
  }

  function showAnswer(answerPanel, answerTextElement, answer) {
    if (!answerPanel || !answerTextElement) {
      return;
    }
    answerTextElement.textContent = answer;
    answerPanel.classList.toggle("is-hidden", !answer);
  }

  function initializeChangelogOverlay() {
    const overlay = document.querySelector("[data-help-changelog-overlay]");
    const openButtons = document.querySelectorAll("[data-help-changelog-open]");
    if (!overlay || openButtons.length === 0) {
      return;
    }

    const closeButton = overlay.querySelector("[data-help-changelog-close]");
    let returnFocusElement = null;

    function openOverlay(triggerElement) {
      returnFocusElement = triggerElement || null;
      overlay.classList.remove("is-hidden");
      overlay.setAttribute("aria-hidden", "false");
      document.body.classList.add("help-changelog-overlay-open");
      if (closeButton) {
        closeButton.focus();
      }
    }

    function closeOverlay() {
      overlay.classList.add("is-hidden");
      overlay.setAttribute("aria-hidden", "true");
      document.body.classList.remove("help-changelog-overlay-open");
      if (returnFocusElement && typeof returnFocusElement.focus === "function") {
        returnFocusElement.focus();
      }
      returnFocusElement = null;
    }

    openButtons.forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        openOverlay(button);
      });
    });

    if (closeButton) {
      closeButton.addEventListener("click", closeOverlay);
    }

    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) {
        closeOverlay();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !overlay.classList.contains("is-hidden")) {
        closeOverlay();
      }
    });
  }

  function initializeHelpForm(form) {
    const questionInput = form.querySelector("[data-help-question-input]");
    const submitButton = form.querySelector("[data-help-submit-button]");
    const statusElement = form.querySelector("[data-help-status]");
    const answerPanel = document.querySelector("[data-help-answer-panel]");
    const answerTextElement = document.querySelector("[data-help-answer-text]");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!questionInput || questionInput.disabled) {
        return;
      }

      const question = questionInput.value.trim();
      if (!question) {
        setStatus(statusElement, "Enter a help question first.", true);
        return;
      }

      showAnswer(answerPanel, answerTextElement, "");
      setStatus(statusElement, "Asking Help...", false);
      setLoading(submitButton, true);

      try {
        const response = await fetch("/help/ask", {
          method: "POST",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken(),
          },
          body: JSON.stringify({ question }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Help request failed.");
        }
        showAnswer(answerPanel, answerTextElement, payload.answer || "");
        setStatus(statusElement, "Answer ready.", false);
      } catch (error) {
        setStatus(statusElement, error.message || "Help request failed.", true);
      } finally {
        setLoading(submitButton, false);
      }
    });
  }

  initializeChangelogOverlay();
  document.querySelectorAll("[data-help-question-form]").forEach(initializeHelpForm);
}());
