(function () {
  "use strict";

  const AUTOTASK_RESOURCE_SEARCH_DELAY_MS = 450;
  const AUTOTASK_ROLE_LOAD_DELAY_MS = 350;

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
    if (!resultsElement) {
      return;
    }

    resultsElement.replaceChildren();
    resultsElement.hidden = true;
  }

  function resourceOptionLabel(resource) {
    const resourceName = resource.resource_name || `Resource ${resource.resource_id}`;
    return `${resourceName} (ID ${resource.resource_id})`;
  }

  function resourceOptionMeta(resource) {
    const nameParts = [resource.first_name, resource.last_name].filter(Boolean);
    if (resource.email && nameParts.length > 0) {
      return `${nameParts.join(" ")} | ${resource.email}`;
    }
    if (resource.email) {
      return resource.email;
    }
    return nameParts.join(" ");
  }

  function setResourceEmail(form, email) {
    const resourceEmailInput = form.querySelector("[data-resource-email-input]");
    if (!resourceEmailInput) {
      return;
    }

    resourceEmailInput.value = String(email || "").trim();
  }

  function setRoleStatus(form, message, isError) {
    const statusElement = form.querySelector("[data-role-status]");
    if (!statusElement) {
      return;
    }

    statusElement.textContent = message;
    statusElement.classList.toggle("error-text", Boolean(isError));
  }

  function roleOptionLabel(role) {
    if (role.label) {
      return String(role.label);
    }
    const label = `Role ${role.role_id}`;
    return role.is_default ? `${label} (Autotask default)` : label;
  }

  function resetRoleSelect(form, message) {
    const roleSelect = form.querySelector("[data-role-select]");
    if (!roleSelect) {
      return;
    }

    roleSelect.replaceChildren();
    const blankOption = document.createElement("option");
    blankOption.value = "";
    blankOption.textContent = "No default role selected";
    roleSelect.appendChild(blankOption);
    roleSelect.dataset.selectedRoleId = "";
    if (message) {
      setRoleStatus(form, message, false);
    }
  }

  function selectedRoleIdForLoad(roleSelect, roles) {
    const savedRoleId = String(roleSelect.dataset.selectedRoleId || "").trim();
    if (savedRoleId) {
      return savedRoleId;
    }

    const defaultRole = roles.find((role) => Boolean(role.is_default));
    if (defaultRole) {
      return String(defaultRole.role_id);
    }

    if (roles.length === 1) {
      return String(roles[0].role_id);
    }

    return "";
  }

  function renderRoleOptions(form, roles) {
    const roleSelect = form.querySelector("[data-role-select]");
    if (!roleSelect) {
      return;
    }

    const safeRoles = Array.isArray(roles) ? roles : [];
    roleSelect.replaceChildren();

    const blankOption = document.createElement("option");
    blankOption.value = "";
    blankOption.textContent = "No default role selected";
    roleSelect.appendChild(blankOption);

    if (safeRoles.length === 0) {
      roleSelect.dataset.selectedRoleId = "";
      setRoleStatus(form, "No active service desk roles were returned for this resource.", true);
      return;
    }

    const selectedRoleId = selectedRoleIdForLoad(roleSelect, safeRoles);
    let matchedSelectedRole = false;
    safeRoles.forEach((role) => {
      const optionElement = document.createElement("option");
      optionElement.value = String(role.role_id || "");
      optionElement.textContent = roleOptionLabel(role);
      if (optionElement.value && optionElement.value === selectedRoleId) {
        optionElement.selected = true;
        matchedSelectedRole = true;
      }
      roleSelect.appendChild(optionElement);
    });

    if (selectedRoleId && matchedSelectedRole) {
      roleSelect.dataset.selectedRoleId = selectedRoleId;
      setRoleStatus(form, "Selected role is active for this Autotask resource.", false);
      return;
    }

    roleSelect.dataset.selectedRoleId = "";
    if (selectedRoleId) {
      setRoleStatus(form, "The saved default role is not active for this Autotask resource.", true);
      return;
    }

    setRoleStatus(form, "Choose a default role, or leave blank to use Autotask ticket role fallbacks only.", false);
  }

  async function loadResourceRoles(form) {
    if (!form) {
      return;
    }

    const roleUrl = form.dataset.autotaskRoleUrl;
    const resourceIdInput = form.querySelector("[data-resource-id-input]");
    const roleSelect = form.querySelector("[data-role-select]");
    const resourceId = resourceIdInput ? resourceIdInput.value.trim() : "";
    if (!roleUrl || !roleSelect) {
      return;
    }
    if (!resourceId) {
      resetRoleSelect(form, "Select an Autotask resource to load active roles.");
      return;
    }

    const lookupUrl = new URL(roleUrl, window.location.origin);
    lookupUrl.searchParams.set("resource_id", resourceId);
    roleSelect.disabled = true;
    setRoleStatus(form, "Loading active service desk roles...", false);

    try {
      const response = await fetch(lookupUrl.toString(), {
        headers: {"Accept": "application/json"},
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Autotask service desk role lookup failed.");
      }

      renderRoleOptions(form, payload.roles || []);
    } catch (error) {
      resetRoleSelect(form);
      setRoleStatus(form, error.message || "Autotask service desk role lookup failed.", true);
    } finally {
      roleSelect.disabled = false;
    }
  }

  function renderResourceResults(form, resources) {
    const resultsElement = form.querySelector("[data-resource-results]");
    const resourceIdInput = form.querySelector("[data-resource-id-input]");
    if (!resultsElement || !resourceIdInput) {
      return;
    }

    resultsElement.replaceChildren();
    if (!Array.isArray(resources) || resources.length === 0) {
      resultsElement.hidden = true;
      setResourceStatus(form, "No matching Autotask resources found.", true);
      return;
    }

    resultsElement.hidden = false;
    resources.forEach((resource) => {
      const optionButton = document.createElement("button");
      optionButton.type = "button";
      optionButton.className = "resource-option-button";

      const labelElement = document.createElement("span");
      labelElement.className = "resource-option-label";
      labelElement.textContent = resourceOptionLabel(resource);
      optionButton.appendChild(labelElement);

      const metaText = resourceOptionMeta(resource);
      if (metaText) {
        const metaElement = document.createElement("span");
        metaElement.className = "resource-option-meta";
        metaElement.textContent = metaText;
        optionButton.appendChild(metaElement);
      }

      optionButton.addEventListener("click", () => {
        resourceIdInput.value = String(resource.resource_id || "");
        setResourceEmail(form, resource.email || "");
        resetRoleSelect(form);
        loadResourceRoles(form);
        clearResourceResults(form);
        const emailMessage = resource.email ? " Email saved with this user." : " No email returned.";
        setResourceStatus(form, `Selected ${resourceOptionLabel(resource)}.${emailMessage}`, false);
      });

      resultsElement.appendChild(optionButton);
    });

    if (resources.length === 1) {
      setResourceStatus(form, "One Autotask resource found.", false);
      return;
    }

    setResourceStatus(form, "Select the matching Autotask resource.", false);
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
    clearResourceResults(form);
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

  function initializeUsernameSuggestion(form) {
    if (!form.hasAttribute("data-username-autogenerate")) {
      return;
    }

    const fullNameInput = form.querySelector("[data-user-full-name]");
    const usernameInput = form.querySelector("[data-username-input]");
    let lastGeneratedUsername = usernameInput ? usernameInput.value : "";
    let usernameWasEdited = false;

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

    if (fullNameInput) {
      fullNameInput.addEventListener("input", updateGeneratedUsername);
    }

    if (usernameInput) {
      usernameInput.addEventListener("input", () => {
        usernameWasEdited = usernameInput.value.trim() !== "" && usernameInput.value !== lastGeneratedUsername;
      });
    }

    updateGeneratedUsername();
  }

  function initializeResourceLookup(form) {
    const fullNameInput = form.querySelector("[data-user-full-name]");
    const searchButton = form.querySelector("[data-resource-search-button]");
    const resourceIdInput = form.querySelector("[data-resource-id-input]");
    let resourceSearchTimer = null;
    let roleLoadTimer = null;

    function scheduleResourceSearch() {
      window.clearTimeout(resourceSearchTimer);
      resourceSearchTimer = window.setTimeout(() => {
        searchAutotaskResources(form);
      }, AUTOTASK_RESOURCE_SEARCH_DELAY_MS);
    }

    if (fullNameInput) {
      fullNameInput.addEventListener("input", scheduleResourceSearch);
    }

    if (searchButton) {
      searchButton.addEventListener("click", () => {
        window.clearTimeout(resourceSearchTimer);
        searchAutotaskResources(form);
      });
    }

    if (resourceIdInput) {
      resourceIdInput.addEventListener("input", () => {
        setResourceEmail(form, "");
        resetRoleSelect(form);
        window.clearTimeout(roleLoadTimer);
        roleLoadTimer = window.setTimeout(() => {
          loadResourceRoles(form);
        }, AUTOTASK_ROLE_LOAD_DELAY_MS);
      });
    }

    const roleSelect = form.querySelector("[data-role-select]");
    if (roleSelect) {
      roleSelect.addEventListener("change", () => {
        roleSelect.dataset.selectedRoleId = roleSelect.value;
      });
    }
  }

  function elementForUser(selector, userId) {
    return Array.from(document.querySelectorAll(selector)).find((element) => {
      return element.dataset.userId === userId;
    }) || null;
  }

  function editPanelForUser(userId) {
    return elementForUser("[data-user-edit-panel]", userId);
  }

  function editToggleForUser(userId) {
    return elementForUser("[data-user-edit-toggle]", userId);
  }

  function displayRowForUser(userId) {
    return elementForUser("[data-user-display-row]", userId);
  }

  function setUserEditMode(userId, isEditing) {
    const editPanel = editPanelForUser(userId);
    const editToggle = editToggleForUser(userId);
    const displayRow = displayRowForUser(userId);
    if (!editPanel || !editToggle) {
      return;
    }

    editPanel.hidden = !isEditing;
    editToggle.setAttribute("aria-expanded", String(isEditing));
    editToggle.classList.toggle("is-active", isEditing);
    if (displayRow) {
      displayRow.classList.toggle("is-editing", isEditing);
    }
  }

  function closeOtherEditPanels(activeUserId) {
    document.querySelectorAll("[data-user-edit-panel]").forEach((panel) => {
      const userId = panel.dataset.userId || "";
      if (userId && userId !== activeUserId) {
        setUserEditMode(userId, false);
      }
    });
  }

  function initializeEditControls() {
    document.querySelectorAll("[data-user-edit-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const userId = button.dataset.userId || "";
        const editPanel = editPanelForUser(userId);
        if (!userId || !editPanel) {
          return;
        }

        const shouldOpen = editPanel.hidden;
        if (shouldOpen) {
          closeOtherEditPanels(userId);
        }
        setUserEditMode(userId, shouldOpen);
        if (shouldOpen) {
          loadResourceRoles(editPanel.querySelector("form"));
          const firstInput = editPanel.querySelector("input:not([type='hidden'])");
          if (firstInput) {
            firstInput.focus();
          }
        }
      });
    });

    document.querySelectorAll("[data-user-edit-cancel]").forEach((button) => {
      button.addEventListener("click", () => {
        const userId = button.dataset.userId || "";
        const editPanel = editPanelForUser(userId);
        const editForm = editPanel ? editPanel.querySelector("form") : null;
        if (editForm) {
          editForm.reset();
          clearResourceResults(editForm);
          const roleSelect = editForm.querySelector("[data-role-select]");
          if (roleSelect) {
            roleSelect.dataset.selectedRoleId = roleSelect.dataset.initialRoleId || "";
          }
          loadResourceRoles(editForm);
        }
        setUserEditMode(userId, false);
      });
    });
  }

  function initializeConfirmations() {
    document.addEventListener("submit", (event) => {
      const formElement = event.target.closest("[data-confirm-message]");
      if (!formElement || event.defaultPrevented) {
        return;
      }

      const confirmationMessage = formElement.dataset.confirmMessage || "";
      if (confirmationMessage && !window.confirm(confirmationMessage)) {
        event.preventDefault();
      }
    });
  }

  function initializeForms() {
    document.querySelectorAll("[data-user-create-form], [data-user-edit-form]").forEach((form) => {
      initializeUsernameSuggestion(form);
      initializeResourceLookup(form);
    });
  }

  initializeForms();
  initializeEditControls();
  initializeConfirmations();
}());
