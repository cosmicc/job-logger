const TIME_STEP_MINUTES = 15;
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

function normalizeDateValue(dateValue) {
  const parsedDate = dateValue.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!parsedDate) {
    return null;
  }

  const [, yearText, monthText, dayText] = parsedDate;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  if (!year || !month || !day) {
    return null;
  }

  const date = new Date(Date.UTC(year, month - 1, day));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatUtcDateValue(date) {
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${date.getUTCFullYear()}-${month}-${day}`;
}

function addDaysToDateString(dateValue, dayDelta) {
  const date = normalizeDateValue(dateValue);
  if (!date) {
    return dateValue;
  }

  date.setUTCDate(date.getUTCDate() + dayDelta);
  return formatUtcDateValue(date);
}

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

function adjustTimeField(timeFieldName, dateFieldName, deltaMinutes) {
  const timeInput = document.querySelector(`input[name="${timeFieldName}"]`);
  const dateInput = document.querySelector(`input[name="${dateFieldName}"]`);
  if (!timeInput || !dateInput) {
    return;
  }

  const currentTotalMinutes = parseTimeToMinutes(timeInput.value);
  if (currentTotalMinutes === null) {
    return;
  }

  const totalMinutes = currentTotalMinutes + deltaMinutes;
  // The date fields represent America/Detroit calendar dates. Rollover must
  // happen at local midnight, so the calculation stays in displayed wall-clock
  // minutes and then applies a pure calendar-day delta.
  const dayDelta = Math.floor(totalMinutes / (60 * 24));

  timeInput.value = formatMinutesAsTwelveHourTime(totalMinutes);
  if (dayDelta !== 0) {
    dateInput.value = addDaysToDateString(dateInput.value, dayDelta);
  }
}

function bindTimeStepButtons() {
  const timeStepButtons = document.querySelectorAll(".time-step-button");
  for (const button of timeStepButtons) {
    const timeFieldName = button.dataset.timeInput;
    const dateFieldName = button.dataset.dateInput;
    const deltaMinutes = Number(button.dataset.deltaMinutes || 0);
    if (!timeFieldName || !dateFieldName || !Number.isFinite(deltaMinutes)) {
      continue;
    }

    button.addEventListener("click", (event) => {
      event.preventDefault();
      adjustTimeField(timeFieldName, dateFieldName, deltaMinutes);
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

function bindTicketLookup() {
  const ticketPicker = document.querySelector("[data-ticket-picker]");
  if (!ticketPicker) {
    return;
  }

  const lookupUrl = ticketPicker.dataset.ticketLookupUrl;
  const ticketSelectUrl = ticketPicker.dataset.ticketSelectUrl;
  const lookupButton = ticketPicker.querySelector("[data-ticket-lookup-button]");
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
  if (!lookupUrl || !ticketSelectUrl || !lookupButton || !statusElement || !resultsElement || !ticketNumberInput) {
    return;
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

  lookupButton.addEventListener("click", async () => {
    lookupButton.disabled = true;
    statusElement.textContent = "Searching Autotask...";
    resultsElement.replaceChildren();

    try {
      const response = await fetch(lookupUrl, {headers: {Accept: "application/json"}});
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Autotask ticket lookup failed.");
      }

      const ticketOptions = Array.isArray(payload.tickets) ? payload.tickets : [];
      if (ticketOptions.length === 0) {
        statusElement.textContent = "No open tickets found.";
        return;
      }

      statusElement.textContent = `${ticketOptions.length} open ticket(s) found.`;
      for (const ticketOption of ticketOptions) {
        const optionButton = document.createElement("button");
        optionButton.type = "button";
        optionButton.className = "ticket-option-button";
        optionButton.textContent = buildTicketOptionText(ticketOption);
        optionButton.addEventListener("click", async () => {
          optionButton.disabled = true;
          statusElement.textContent = "Saving selected ticket...";
          ticketPicker.hidden = true;
          resultsElement.replaceChildren();
          try {
            const selectedTicket = await persistSelectedTicket(ticketOption);
            updateSelectedTicketDisplay(selectedTicket);
          } catch (error) {
            ticketPicker.hidden = false;
            optionButton.disabled = false;
            statusElement.textContent = error.message || "Selected ticket could not be saved.";
          }
        });
        resultsElement.append(optionButton);
      }
    } catch (error) {
      statusElement.textContent = error.message || "Autotask ticket lookup failed.";
    } finally {
      lookupButton.disabled = false;
    }
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
