(function () {
  "use strict";

  const THEME_CLASS_NAMES = [
    "theme-dark",
    "theme-light",
    "theme-light-sage",
    "theme-light-sky",
    // Remove the former Slate class if an open Config tab spans the deployment.
    "theme-dark-slate",
    "theme-dark-midnight",
    "theme-dark-graphite",
    "theme-dark-forest",
    "theme-dark-plum",
  ];

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
    if (window.TicketPilotBranding) {
      window.TicketPilotBranding.applyTheme(theme);
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

  function initializeNavigationConfigForm(form) {
    const appInput = form.querySelector("[data-navigation-app-option]");
    const homeInput = form.querySelector("[data-navigation-home-address]");
    const officeInput = form.querySelector("[data-navigation-office-address]");
    const allowFullWebInput = form.querySelector("[data-full-web-navigation-option]");
    const allowFullWebSetting = form.querySelector("[data-full-web-navigation-setting]");
    const allowFullWebState = form.querySelector("[data-full-web-navigation-state]");
    if (!appInput || !homeInput || !officeInput || !allowFullWebInput) {
      return;
    }

    let lastSavedValues = {
      navigationApp: appInput.value,
      homeAddress: homeInput.value,
      officeAddress: officeInput.value,
      allowNavigationOnFullWeb: allowFullWebInput.checked,
    };
    let saveSequence = 0;

    function updateNavigationDependencies() {
      const navigationEnabled = appInput.value !== "none";
      homeInput.required = navigationEnabled;
      allowFullWebInput.disabled = !navigationEnabled;
      if (!navigationEnabled) {
        allowFullWebInput.checked = false;
      }
      if (allowFullWebSetting) {
        allowFullWebSetting.classList.toggle("is-disabled", !navigationEnabled);
      }
      if (allowFullWebState) {
        allowFullWebState.textContent = allowFullWebInput.checked ? "On" : "Off";
      }
    }

    async function saveNavigationConfig() {
      updateNavigationDependencies();
      if (!form.reportValidity()) {
        setStatus(form, "Enter a home address before enabling navigation.", true);
        return;
      }

      const requestSequence = ++saveSequence;
      setStatus(form, "Saving...", false);
      try {
        const formData = new FormData(form);
        // Disabled checkboxes are omitted from FormData. Send an explicit
        // false value when navigation is off so the server stores the same
        // state shown by the greyed-out control.
        formData.set(
          "allow_navigation_on_full_web",
          allowFullWebInput.checked ? "true" : "false",
        );
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
          throw new Error(payload.detail || "Navigation configuration update failed.");
        }
        if (requestSequence !== saveSequence) {
          return;
        }
        lastSavedValues = {
          navigationApp: appInput.value,
          homeAddress: homeInput.value,
          officeAddress: officeInput.value,
          allowNavigationOnFullWeb: allowFullWebInput.checked,
        };
        updateNavigationDependencies();
        setStatus(form, payload.message || "Configuration updated.", false);
      } catch (error) {
        if (requestSequence !== saveSequence) {
          return;
        }
        appInput.value = lastSavedValues.navigationApp;
        homeInput.value = lastSavedValues.homeAddress;
        officeInput.value = lastSavedValues.officeAddress;
        allowFullWebInput.checked = lastSavedValues.allowNavigationOnFullWeb;
        updateNavigationDependencies();
        setStatus(form, error.message || "Navigation configuration update failed.", true);
      }
    }

    form.addEventListener("submit", (event) => event.preventDefault());
    appInput.addEventListener("change", saveNavigationConfig);
    homeInput.addEventListener("change", saveNavigationConfig);
    officeInput.addEventListener("change", saveNavigationConfig);
    allowFullWebInput.addEventListener("change", saveNavigationConfig);
    updateNavigationDependencies();
  }

  document.querySelectorAll("[data-config-form]").forEach(initializeConfigForm);
  document.querySelectorAll("[data-navigation-config-form]").forEach(initializeNavigationConfigForm);
}());
