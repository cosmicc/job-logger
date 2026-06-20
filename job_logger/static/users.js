(function () {
  "use strict";

  const AUTOTASK_RESOURCE_SEARCH_DELAY_MS = 450;

  function usernamePart(value) {
    return String(value || "").replace(/[^A-Za-z0-9]/g, "");
  }

  function suggestedUsername(fullName) {
    const nameParts = String(fullName || "")
      .trim()
      .split(/\s+/)
      .map(usernamePart)
      .filter(Boolean);
    if (nameParts.length < 2) {
      return "";
    }

    const firstName = nameParts[0];
    const lastName = nameParts[nameParts.length - 1];
    return `${firstName.charAt(0)}${lastName}`.toLowerCase();
  }

  function setResourceStatus(form, message, isError) {
    const statusElement = form.querySelector("[data-resource-status]");
    if (!statusElement) {
      return;
    }

    statusElement.textContent = message;
    statusElement.classList.toggle("error-text", Boolean(isError));
  }

  function clearResourceResults(form) {
    const resultsElement = form.querySelector("[data-resource-results]");
    if (resultsElement) {
      resultsElement.replaceChildren();
    }
  }

  function resourceOptionLabel(resource) {
    const resourceName = resource.resource_name || `Resource ${resource.resource_id}`;
    return `${resourceName} (ID ${resource.resource_id})`;
  }

  function renderResourceResults(form, resources) {
    const resultsElement = form.querySelector("[data-resource-results]");
    const resourceIdInput = form.querySelector("[data-resource-id-input]");
    if (!resultsElement || !resourceIdInput) {
      return;
    }

    resultsElement.replaceChildren();
    if (!Array.isArray(resources) || resources.length === 0) {
      setResourceStatus(form, "No matching Autotask resources found.", true);
      return;
    }

    resources.forEach((resource) => {
      const optionButton = document.createElement("button");
      optionButton.type = "button";
      optionButton.className = "resource-option-button";

      const labelElement = document.createElement("span");
      labelElement.className = "resource-option-label";
      labelElement.textContent = resourceOptionLabel(resource);
      optionButton.appendChild(labelElement);

      if (resource.email) {
        const emailElement = document.createElement("span");
        emailElement.className = "resource-option-meta";
        emailElement.textContent = resource.email;
        optionButton.appendChild(emailElement);
      }

      optionButton.addEventListener("click", () => {
        resourceIdInput.value = String(resource.resource_id || "");
        setResourceStatus(form, `Selected ${resourceOptionLabel(resource)}.`, false);
      });

      resultsElement.appendChild(optionButton);
    });

    setResourceStatus(form, "Select the Autotask resource for this web user.", false);
  }

  async function searchAutotaskResources(form) {
    const resourceUrl = form.dataset.autotaskResourceUrl;
    const fullNameInput = form.querySelector("[data-user-full-name]");
    const searchButton = form.querySelector("[data-resource-search-button]");
    const queryText = fullNameInput ? fullNameInput.value.trim() : "";
    if (!resourceUrl || queryText.length < 2) {
      clearResourceResults(form);
      setResourceStatus(form, "Enter a full name to search Autotask resources.", false);
      return;
    }

    const lookupUrl = new URL(resourceUrl, window.location.origin);
    lookupUrl.searchParams.set("query", queryText);
    if (searchButton) {
      searchButton.disabled = true;
    }
    setResourceStatus(form, "Searching Autotask resources...", false);

    try {
      const response = await fetch(lookupUrl.toString(), {
        headers: {"Accept": "application/json"},
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Autotask resource lookup failed.");
      }

      renderResourceResults(form, payload.resources || []);
    } catch (error) {
      clearResourceResults(form);
      setResourceStatus(form, error.message || "Autotask resource lookup failed.", true);
    } finally {
      if (searchButton) {
        searchButton.disabled = false;
      }
    }
  }

  function initializeUserCreateForm(form) {
    const fullNameInput = form.querySelector("[data-user-full-name]");
    const usernameInput = form.querySelector("[data-username-input]");
    const searchButton = form.querySelector("[data-resource-search-button]");
    let lastGeneratedUsername = usernameInput ? usernameInput.value : "";
    let usernameWasEdited = false;
    let resourceSearchTimer = null;

    function updateGeneratedUsername() {
      if (!fullNameInput || !usernameInput) {
        return;
      }

      const nextSuggestion = suggestedUsername(fullNameInput.value);
      if (!usernameWasEdited || usernameInput.value === lastGeneratedUsername) {
        usernameInput.value = nextSuggestion;
        lastGeneratedUsername = nextSuggestion;
      }
    }

    function scheduleResourceSearch() {
      window.clearTimeout(resourceSearchTimer);
      resourceSearchTimer = window.setTimeout(() => {
        searchAutotaskResources(form);
      }, AUTOTASK_RESOURCE_SEARCH_DELAY_MS);
    }

    if (fullNameInput) {
      fullNameInput.addEventListener("input", () => {
        updateGeneratedUsername();
        scheduleResourceSearch();
      });
    }

    if (usernameInput) {
      usernameInput.addEventListener("input", () => {
        usernameWasEdited = usernameInput.value.trim() !== "" && usernameInput.value !== lastGeneratedUsername;
      });
    }

    if (searchButton) {
      searchButton.addEventListener("click", () => {
        window.clearTimeout(resourceSearchTimer);
        searchAutotaskResources(form);
      });
    }

    updateGeneratedUsername();
  }

  document.querySelectorAll("[data-user-create-form]").forEach(initializeUserCreateForm);
}());
