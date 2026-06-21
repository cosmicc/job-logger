(function () {
  "use strict";

  const THEME_CLASS_NAMES = ["theme-dark", "theme-light"];

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

  function applyTheme(theme, themeColor) {
    const themeClassName = `theme-${theme}`;
    document.documentElement.classList.remove(...THEME_CLASS_NAMES);
    document.body.classList.remove(...THEME_CLASS_NAMES);
    document.documentElement.classList.add(themeClassName);
    document.body.classList.add(themeClassName);

    const themeColorMeta = document.querySelector("meta[name='theme-color']");
    if (themeColorMeta && themeColor) {
      themeColorMeta.setAttribute("content", themeColor);
    }
  }

  function checkedThemeInput(form) {
    return form.querySelector("input[name='theme']:checked");
  }

  function directSubmitInput(form) {
    return form.querySelector("[data-direct-submit-option]");
  }

  function setDirectSubmitState(form, enabled) {
    const settingInput = directSubmitInput(form);
    if (settingInput) {
      settingInput.checked = Boolean(enabled);
    }

    const stateElement = form.querySelector("[data-direct-submit-state]");
    if (stateElement) {
      stateElement.textContent = enabled ? "On" : "Off";
    }
  }

  async function saveConfig(form, options) {
    const themeInput = options.themeInput || null;
    const previousThemeInput = options.previousThemeInput || null;
    const submitPreferenceInput = options.submitPreferenceInput || null;
    const previousSubmitPreference = options.previousSubmitPreference;

    if (themeInput) {
      applyTheme(themeInput.value, themeInput.dataset.themeColor || "");
    }
    if (submitPreferenceInput) {
      setDirectSubmitState(form, submitPreferenceInput.checked);
    }
    setStatus(form, "Saving...", false);

    const formData = new FormData(form);
    if (themeInput) {
      formData.set("theme", themeInput.value);
    }
    if (submitPreferenceInput) {
      formData.set("submit_from_work_in_progress", submitPreferenceInput.checked ? "true" : "false");
    }

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

      if (payload.theme) {
        applyTheme(payload.theme, payload.theme_color || "");
      }
      if (submitPreferenceInput && Object.prototype.hasOwnProperty.call(payload, "submit_from_work_in_progress")) {
        setDirectSubmitState(form, Boolean(payload.submit_from_work_in_progress));
      }
      setStatus(form, payload.message || "Configuration updated.", false);
      return {
        themeInput,
        submitPreference: submitPreferenceInput ? submitPreferenceInput.checked : previousSubmitPreference,
      };
    } catch (error) {
      if (themeInput) {
        const fallbackInput = previousThemeInput || checkedThemeInput(form);
        if (fallbackInput) {
          fallbackInput.checked = true;
          applyTheme(
            fallbackInput.value,
            fallbackInput.dataset.themeColor || "",
          );
        }
      }
      if (submitPreferenceInput && previousSubmitPreference !== undefined) {
        setDirectSubmitState(form, previousSubmitPreference);
      }
      setStatus(form, error.message || "Configuration update failed.", true);
      return {
        themeInput: previousThemeInput || checkedThemeInput(form),
        submitPreference: submitPreferenceInput ? previousSubmitPreference : undefined,
      };
    }
  }

  function initializeConfigForm(form) {
    let currentThemeInput = checkedThemeInput(form);
    const submitPreferenceInput = directSubmitInput(form);
    let currentSubmitPreference = submitPreferenceInput ? submitPreferenceInput.checked : undefined;

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
        const result = await saveConfig(form, {
          themeInput,
          previousThemeInput,
        });
        currentThemeInput = result.themeInput;
      });
    });

    if (submitPreferenceInput) {
      submitPreferenceInput.addEventListener("change", async () => {
        const previousSubmitPreference = currentSubmitPreference;
        currentSubmitPreference = submitPreferenceInput.checked;
        const result = await saveConfig(form, {
          submitPreferenceInput,
          previousSubmitPreference,
        });
        if (result.submitPreference !== undefined) {
          currentSubmitPreference = result.submitPreference;
        }
      });
    }
  }

  document.querySelectorAll("[data-config-form]").forEach(initializeConfigForm);
}());
