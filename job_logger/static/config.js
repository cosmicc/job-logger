(function () {
  "use strict";

  const THEME_CLASS_NAMES = ["theme-dark", "theme-light"];

  function titleCaseTheme(theme) {
    return `${String(theme || "").slice(0, 1).toUpperCase()}${String(theme || "").slice(1)}`;
  }

  function csrfToken() {
    const csrfMeta = document.querySelector("meta[name='csrf-token']");
    return csrfMeta ? csrfMeta.getAttribute("content") || "" : "";
  }

  function setStatus(form, message, isError) {
    const statusElement = form.querySelector("[data-config-status]");
    if (!statusElement) {
      return;
    }

    statusElement.textContent = message;
    statusElement.classList.toggle("error-text", Boolean(isError));
  }

  function updateThemeLabels(theme, label) {
    const displayLabel = label || titleCaseTheme(theme);
    const currentThemeElement = document.querySelector("[data-config-current-theme]");
    const themeSummaryElement = document.querySelector("[data-config-theme-summary]");
    if (currentThemeElement) {
      currentThemeElement.textContent = displayLabel;
    }
    if (themeSummaryElement) {
      themeSummaryElement.textContent = displayLabel;
    }
  }

  function applyTheme(theme, themeColor, label) {
    const themeClassName = `theme-${theme}`;
    document.documentElement.classList.remove(...THEME_CLASS_NAMES);
    document.body.classList.remove(...THEME_CLASS_NAMES);
    document.documentElement.classList.add(themeClassName);
    document.body.classList.add(themeClassName);

    const themeColorMeta = document.querySelector("meta[name='theme-color']");
    if (themeColorMeta && themeColor) {
      themeColorMeta.setAttribute("content", themeColor);
    }

    updateThemeLabels(theme, label);
  }

  function checkedThemeInput(form) {
    return form.querySelector("input[name='theme']:checked");
  }

  function checkThemeInput(form, theme) {
    const matchingInput = form.querySelector(`input[name='theme'][value="${CSS.escape(theme)}"]`);
    if (matchingInput) {
      matchingInput.checked = true;
    }
    return matchingInput;
  }

  async function saveTheme(form, themeInput, previousThemeInput) {
    const theme = themeInput.value;
    const themeLabel = themeInput.dataset.themeLabel || titleCaseTheme(theme);
    const themeColor = themeInput.dataset.themeColor || "";

    applyTheme(theme, themeColor, themeLabel);
    setStatus(form, "Saving...", false);

    const formData = new FormData(form);
    formData.set("theme", theme);
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "X-CSRF-Token": csrfToken(),
        },
        body: formData,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Configuration update failed.");
      }

      applyTheme(payload.theme || theme, payload.theme_color || themeColor, themeLabel);
      setStatus(form, payload.message || "Configuration updated.", false);
      return themeInput;
    } catch (error) {
      const fallbackInput = previousThemeInput || checkedThemeInput(form);
      if (fallbackInput) {
        fallbackInput.checked = true;
        applyTheme(
          fallbackInput.value,
          fallbackInput.dataset.themeColor || "",
          fallbackInput.dataset.themeLabel || titleCaseTheme(fallbackInput.value),
        );
      }
      setStatus(form, error.message || "Configuration update failed.", true);
      return fallbackInput;
    }
  }

  function initializeConfigForm(form) {
    let currentThemeInput = checkedThemeInput(form);

    form.addEventListener("submit", (event) => {
      event.preventDefault();
    });

    form.querySelectorAll("[data-theme-option]").forEach((themeInput) => {
      themeInput.addEventListener("change", async () => {
        if (!themeInput.checked) {
          return;
        }

        const previousThemeInput = currentThemeInput;
        currentThemeInput = themeInput;
        currentThemeInput = await saveTheme(form, themeInput, previousThemeInput);
      });
    });
  }

  document.querySelectorAll("[data-config-form]").forEach(initializeConfigForm);
}());
