const TIME_STEP_MINUTES = 15;
const REVIEW_AUTOSAVE_DELAY_MS = 650;
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
const reviewAutosaveForm = document.querySelector("[data-review-autosave-form]");
const reviewAutosaveStatus = document.querySelector("[data-review-autosave-status]");

let reviewAutosaveTimer = null;
let lastReviewAutosaveSnapshot = "";

function padTwo(value) {
  return String(value).padStart(2, "0");
}

function parseTimeToMinutes(timeValue) {
  const normalizedTimeValue = String(timeValue || "").trim().toLowerCase().replace(/\s+/g, " ");
  const twelveHourMatch = normalizedTimeValue.match(/^(\d{1,2}):(\d{2})\s*([ap])\.?m\.?$/);
  if (twelveHourMatch) {
    const hour = Number(twelveHourMatch[1]);
    const minute = Number(twelveHourMatch[2]);
    const period = twelveHourMatch[3];
    if (hour < 1 || hour > 12 || minute < 0 || minute > 59) {
      return null;
    }

    const hour24 = period === "a"
      ? (hour === 12 ? 0 : hour)
      : (hour === 12 ? 12 : hour + 12);
    return hour24 * 60 + minute;
  }

  const twentyFourHourMatch = normalizedTimeValue.match(/^(\d{1,2}):(\d{2})$/);
  if (!twentyFourHourMatch) {
    return null;
  }

  const hour = Number(twentyFourHourMatch[1]);
  const minute = Number(twentyFourHourMatch[2]);
  if (hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return null;
  }

  return hour * 60 + minute;
}

function formatMinutesAsTwelveHourTime(totalMinutes) {
  const normalizedTotalMinutes = ((totalMinutes % (60 * 24)) + (60 * 24)) % (60 * 24);
  const hour24 = Math.floor(normalizedTotalMinutes / 60);
  const minute = normalizedTotalMinutes % 60;
  const hour12 = hour24 % 12 || 12;
  const period = hour24 < 12 ? "am" : "pm";
  return `${hour12}:${padTwo(minute)} ${period}`;
}

function adjustTimeField(timeFieldName, deltaMinutes) {
  const timeInput = document.querySelector(`input[name="${timeFieldName}"]`);
  if (!timeInput) {
    return;
  }

  const currentTotalMinutes = parseTimeToMinutes(timeInput.value);
  if (currentTotalMinutes === null) {
    return;
  }

  const totalMinutes = currentTotalMinutes + deltaMinutes;
  timeInput.value = formatMinutesAsTwelveHourTime(totalMinutes);
}

function setReviewAutosaveStatus(message, isError = false) {
  if (!reviewAutosaveStatus) {
    return;
  }

  reviewAutosaveStatus.textContent = message;
  reviewAutosaveStatus.classList.toggle("error-text", isError);
}

function buildReviewAutosaveSnapshot() {
  if (!reviewAutosaveForm) {
    return "";
  }

  return new URLSearchParams(new FormData(reviewAutosaveForm)).toString();
}

function clearReviewAutosaveTimer() {
  if (reviewAutosaveTimer) {
    clearTimeout(reviewAutosaveTimer);
    reviewAutosaveTimer = null;
  }
}

async function saveReviewFormInBackground() {
  if (!reviewAutosaveForm) {
    return {};
  }

  const saveUrl = reviewAutosaveForm.dataset.reviewSaveUrl || "";
  if (!saveUrl) {
    throw new Error("Review autosave endpoint is not configured.");
  }

  const response = await fetch(saveUrl, {
    method: "POST",
    headers: {Accept: "application/json"},
    body: new FormData(reviewAutosaveForm),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Review changes could not be saved.");
  }

  return payload;
}

function persistReviewAutosaveSnapshot(queuedSnapshot) {
  setReviewAutosaveStatus("Saving changes...");
  saveReviewFormInBackground()
    .then(() => {
      const latestSnapshot = buildReviewAutosaveSnapshot();
      if (latestSnapshot === queuedSnapshot) {
        lastReviewAutosaveSnapshot = latestSnapshot;
        setReviewAutosaveStatus("Changes saved.");
        return;
      }

      queueReviewAutosave(true);
    })
    .catch((error) => {
      setReviewAutosaveStatus(error.message || "Review changes could not be saved.", true);
    });
}

function queueReviewAutosave(immediate = false) {
  if (!reviewAutosaveForm) {
    return;
  }

  const nextSnapshot = buildReviewAutosaveSnapshot();
  if (nextSnapshot === lastReviewAutosaveSnapshot) {
    return;
  }

  clearReviewAutosaveTimer();
  reviewAutosaveTimer = setTimeout(() => {
    reviewAutosaveTimer = null;
    persistReviewAutosaveSnapshot(nextSnapshot);
  }, immediate ? 0 : REVIEW_AUTOSAVE_DELAY_MS);
}

function bindTimeStepButtons() {
  const timeStepButtons = document.querySelectorAll(".time-step-button");
  for (const button of timeStepButtons) {
    const timeFieldName = button.dataset.timeInput;
    const deltaMinutes = Number(button.dataset.deltaMinutes || 0);
    if (!timeFieldName || !Number.isFinite(deltaMinutes)) {
      continue;
    }

    button.addEventListener("click", (event) => {
      event.preventDefault();
      adjustTimeField(timeFieldName, deltaMinutes);
      queueReviewAutosave(true);
    });
  }
}

function bindReviewAutosave() {
  if (!reviewAutosaveForm) {
    return;
  }

  lastReviewAutosaveSnapshot = buildReviewAutosaveSnapshot();
  const autosaveControls = reviewAutosaveForm.querySelectorAll("input, select, textarea");
  for (const control of autosaveControls) {
    if (control.type === "hidden" || control.name === "csrf_token" || control.disabled) {
      continue;
    }

    if (control.tagName === "SELECT" || control.type === "date") {
      control.addEventListener("change", () => {
        queueReviewAutosave(true);
      });
      continue;
    }

    control.addEventListener("input", () => {
      queueReviewAutosave();
    });
    control.addEventListener("blur", () => {
      queueReviewAutosave(true);
    });
  }
}

function buildTicketOptionText(ticketOption) {
  const ticketNumber = ticketOption.ticket_number || "No ticket number";
  const ticketTitle = ticketOption.title || "Untitled ticket";
  const ticketStatus = ticketOption.status_label || "Unknown status";
  const companyName = ticketOption.company_name || "Unknown company";
  return `${ticketNumber} | ${ticketTitle} | ${ticketStatus} | ${companyName}`;
}

function setTicketLookupStatus(statusElement, message, {isError = false, isLoading = false} = {}) {
  if (!statusElement) {
    return;
  }

  statusElement.replaceChildren();
  statusElement.classList.toggle("error-text", isError);
  statusElement.classList.toggle("is-loading", isLoading);
  if (!isLoading) {
    statusElement.textContent = message;
    return;
  }

  const spinnerElement = document.createElement("span");
  spinnerElement.className = "loading-spinner";
  spinnerElement.setAttribute("aria-hidden", "true");
  const messageElement = document.createElement("span");
  messageElement.textContent = message;
  statusElement.append(spinnerElement, messageElement);
}

function bindTicketLookup() {
  const ticketPicker = document.querySelector("[data-ticket-picker]");
  if (!ticketPicker) {
    return;
  }

  const lookupUrl = ticketPicker.dataset.ticketLookupUrl;
  const ticketSelectUrl = ticketPicker.dataset.ticketSelectUrl;
  const ticketClientName = (ticketPicker.dataset.ticketClientName || "").trim();
  const statusElement = ticketPicker.querySelector("[data-ticket-lookup-status]");
  const resultsElement = ticketPicker.querySelector("[data-ticket-lookup-results]");
  const ticketNumberInput = document.querySelector("[data-review-ticket-number-input]");
  const ticketNumberDisplay = document.querySelector("[data-review-ticket-number-display]");
  const ticketTitleInput = document.querySelector("[data-review-ticket-title-input]");
  const ticketDescriptionInput = document.querySelector("[data-review-ticket-description-input]");
  const ticketDescriptionCard = document.querySelector("[data-review-ticket-description-card]");
  const ticketDescriptionDisplay = document.querySelector("[data-review-ticket-description-display]");
  const ticketHeading = document.querySelector("[data-selected-ticket-heading]");
  const selectedRowTicketDisplay = document.querySelector("[data-review-selected-row-ticket]");
  if (!lookupUrl || !ticketSelectUrl || !statusElement || !resultsElement || !ticketNumberInput) {
    return;
  }

  let hasLoadedTicketOptions = false;
  let isLookupInProgress = false;

  function setTicketPickerClickable(isClickable) {
    ticketPicker.classList.toggle("is-clickable", isClickable);
    if (isClickable) {
      ticketPicker.setAttribute("role", "button");
      ticketPicker.setAttribute("tabindex", "0");
      ticketPicker.setAttribute("aria-disabled", "false");
      return;
    }

    ticketPicker.removeAttribute("role");
    ticketPicker.removeAttribute("tabindex");
    ticketPicker.removeAttribute("aria-disabled");
  }

  async function persistSelectedTicket(ticketOption) {
    const response = await fetch(ticketSelectUrl, {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({ticket_number: ticketOption.ticket_number || ""}),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Selected ticket could not be saved.");
    }

    return payload;
  }

  function updateSelectedTicketDisplay(selectedTicket) {
    const selectedTicketNumber = selectedTicket.ticket_number || "";
    const selectedTicketTitle = selectedTicket.ticket_title || "";
    const selectedTicketDescription = selectedTicket.ticket_description || "";
    ticketNumberInput.value = selectedTicketNumber;
    if (ticketNumberDisplay) {
      ticketNumberDisplay.textContent = selectedTicketNumber || "Unassigned Ticket";
    }
    if (ticketTitleInput) {
      ticketTitleInput.value = selectedTicketTitle;
    }
    if (ticketDescriptionInput) {
      ticketDescriptionInput.value = selectedTicketDescription;
    }
    if (ticketDescriptionDisplay) {
      ticketDescriptionDisplay.textContent = selectedTicketDescription;
    }
    if (ticketDescriptionCard) {
      ticketDescriptionCard.classList.toggle("is-hidden", !selectedTicketDescription);
    }
    if (ticketHeading) {
      ticketHeading.textContent = selectedTicketTitle || selectedTicketNumber || "Unassigned Ticket";
    }
    if (selectedRowTicketDisplay) {
      selectedRowTicketDisplay.textContent = selectedTicketNumber || "No ticket";
    }
  }

  async function loadReviewTicketOptions() {
    if (isLookupInProgress || hasLoadedTicketOptions) {
      return;
    }

    if (!ticketClientName) {
      setTicketLookupStatus(statusElement, "Client name is required before open tickets can load.", {isError: true});
      return;
    }

    isLookupInProgress = true;
    ticketPicker.classList.add("is-loading");
    ticketPicker.setAttribute("aria-busy", "true");
    setTicketPickerClickable(false);
    setTicketLookupStatus(statusElement, "Loading open tickets...", {isLoading: true});
    resultsElement.replaceChildren();

    try {
      const response = await fetch(lookupUrl, {headers: {Accept: "application/json"}});
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Autotask ticket lookup failed.");
      }

      const ticketOptions = Array.isArray(payload.tickets) ? payload.tickets : [];
      if (ticketOptions.length === 0) {
        setTicketLookupStatus(statusElement, "No open tickets found. Click this box to try again.");
        setTicketPickerClickable(true);
        return;
      }

      hasLoadedTicketOptions = true;
      setTicketLookupStatus(statusElement, `${ticketOptions.length} open ticket(s) found.`);
      for (const ticketOption of ticketOptions) {
        const optionButton = document.createElement("button");
        optionButton.type = "button";
        optionButton.className = "ticket-option-button";
        optionButton.textContent = buildTicketOptionText(ticketOption);
        optionButton.addEventListener("click", async () => {
          optionButton.disabled = true;
          ticketPicker.classList.add("is-loading");
          ticketPicker.setAttribute("aria-busy", "true");
          setTicketLookupStatus(statusElement, "Saving selected ticket...", {isLoading: true});
          resultsElement.replaceChildren();
          try {
            const selectedTicket = await persistSelectedTicket(ticketOption);
            updateSelectedTicketDisplay(selectedTicket);
            ticketPicker.hidden = true;
          } catch (error) {
            ticketPicker.classList.remove("is-loading");
            ticketPicker.removeAttribute("aria-busy");
            ticketPicker.hidden = false;
            optionButton.disabled = false;
            hasLoadedTicketOptions = false;
            setTicketLookupStatus(statusElement, error.message || "Selected ticket could not be saved.", {isError: true});
            setTicketPickerClickable(true);
          }
        });
        resultsElement.append(optionButton);
      }
    } catch (error) {
      setTicketLookupStatus(statusElement, error.message || "Autotask ticket lookup failed.", {isError: true});
      setTicketPickerClickable(true);
    } finally {
      isLookupInProgress = false;
      ticketPicker.classList.remove("is-loading");
      ticketPicker.removeAttribute("aria-busy");
    }
  }

  setTicketPickerClickable(!hasLoadedTicketOptions);
  ticketPicker.addEventListener("click", (event) => {
    if (event.target.closest("button, a, input, select, textarea")) {
      return;
    }

    loadReviewTicketOptions();
  });
  ticketPicker.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }

    event.preventDefault();
    loadReviewTicketOptions();
  });
}

const reviewRows = document.querySelectorAll(".review-table-row[data-review-url]");
for (const reviewRow of reviewRows) {
  const reviewUrl = reviewRow.getAttribute("data-review-url");
  if (!reviewUrl) {
    continue;
  }

  reviewRow.addEventListener("click", () => {
    window.location.href = reviewUrl;
  });

  reviewRow.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      window.location.href = reviewUrl;
    }
  });
}

bindTimeStepButtons();
bindTicketLookup();
bindReviewAutosave();
