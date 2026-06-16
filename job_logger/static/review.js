const TIME_STEP_MINUTES = 15;

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

  const date = new Date(year, month - 1, day);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return {date, year, month, day};
}

function formatDateValue(date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function addDaysToDateString(dateValue, dayDelta) {
  const parsed = normalizeDateValue(dateValue);
  if (!parsed) {
    return dateValue;
  }

  const nextDate = parsed.date;
  nextDate.setDate(nextDate.getDate() + dayDelta);
  return formatDateValue(nextDate);
}

function padTwo(value) {
  return String(value).padStart(2, "0");
}

function adjustTimeField(timeFieldName, dateFieldName, deltaMinutes) {
  const timeInput = document.querySelector(`input[name="${timeFieldName}"]`);
  const dateInput = document.querySelector(`input[name="${dateFieldName}"]`);
  if (!timeInput || !dateInput) {
    return;
  }

  const timeParts = timeInput.value.split(":").map((part) => Number(part));
  if (timeParts.length !== 2 || !Number.isFinite(timeParts[0]) || !Number.isFinite(timeParts[1])) {
    return;
  }

  const hours = timeParts[0];
  const minutes = timeParts[1];
  const totalMinutes = hours * 60 + minutes + deltaMinutes;
  const dayDelta = Math.trunc(totalMinutes / (60 * 24));
  const normalizedTotalMinutes = ((totalMinutes % (60 * 24)) + (60 * 24)) % (60 * 24);
  const adjustedHours = Math.floor(normalizedTotalMinutes / 60);
  const adjustedMinutes = normalizedTotalMinutes % 60;

  timeInput.value = `${padTwo(adjustedHours)}:${padTwo(adjustedMinutes)}`;
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
  const lookupButton = ticketPicker.querySelector("[data-ticket-lookup-button]");
  const statusElement = ticketPicker.querySelector("[data-ticket-lookup-status]");
  const resultsElement = ticketPicker.querySelector("[data-ticket-lookup-results]");
  const ticketNumberInput = document.querySelector('input[name="ticket_number"]');
  if (!lookupUrl || !lookupButton || !statusElement || !resultsElement || !ticketNumberInput) {
    return;
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
        optionButton.addEventListener("click", () => {
          ticketNumberInput.value = ticketOption.ticket_number || "";
          ticketNumberInput.focus();
          statusElement.textContent = `Selected ${ticketNumberInput.value}.`;
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

function bindReviewCompanyClearing() {
  const clientInput = document.querySelector("[data-review-client-input]");
  const companyIdInput = document.querySelector("[data-review-company-id-input]");
  if (!clientInput || !companyIdInput) {
    return;
  }

  const initialClientName = clientInput.value;
  clientInput.addEventListener("input", () => {
    if (clientInput.value !== initialClientName) {
      companyIdInput.value = "";
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
bindReviewCompanyClearing();
