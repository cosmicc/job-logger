const ticketNoteButtonCache = new WeakMap();
const ticketTimeEntryButtonCache = new WeakMap();
const ticketNoteRequestCache = new Map();
const ticketTimeEntryRequestCache = new Map();

function ticketNotesSafeString(value) {
  return String(value || "");
}

function ticketNotesCreateElement(tagName, className, textContent = "") {
  const element = document.createElement(tagName);
  if (className) {
    element.className = className;
  }
  if (textContent) {
    element.textContent = textContent;
  }
  return element;
}

function createCustomerNoteIndicator() {
  const indicator = ticketNotesCreateElement("span", "customer-note-indicator", "Note");
  indicator.dataset.customerNoteIndicator = "";
  indicator.setAttribute("aria-label", "Customer note attached");
  indicator.setAttribute("title", "Customer note attached");
  return indicator;
}

function setSelectedTicketNoteIndicators(button, hasCustomerNotes) {
  const selectedTicketRoot = button.closest(
    "[data-active-job-card], [data-review-ticket-title-card], .review-ticket-title-card",
  );
  if (!selectedTicketRoot) {
    return;
  }
  const indicators = selectedTicketRoot.querySelectorAll("[data-selected-ticket-note-indicator]");
  for (const indicator of indicators) {
    indicator.classList.toggle("is-hidden", !hasCustomerNotes);
  }
}

function setTicketNotesButtonIndicator(button, hasCustomerNotes) {
  let indicator = button.querySelector("[data-customer-note-indicator]");
  if (!indicator) {
    indicator = createCustomerNoteIndicator();
    button.append(indicator);
  }
  indicator.classList.toggle("is-hidden", !hasCustomerNotes);
  button.classList.toggle("has-customer-notes", hasCustomerNotes);
  setSelectedTicketNoteIndicators(button, hasCustomerNotes);
}

function ticketNotesResourceNameForDisplay(rawResourceName) {
  const resourceName = ticketNotesSafeString(rawResourceName).trim();
  if (!resourceName) {
    return "Unknown resource";
  }

  const commaIndex = resourceName.indexOf(",");
  if (commaIndex === -1) {
    return resourceName;
  }

  const lastName = resourceName.slice(0, commaIndex).trim();
  const firstName = resourceName.slice(commaIndex + 1).trim();
  if (!lastName || !firstName) {
    return resourceName;
  }

  return `${firstName} ${lastName}`;
}

function ticketTimeEntryListRangeForDisplay(rawDisplayRange) {
  const displayRange = ticketNotesSafeString(rawDisplayRange).trim();
  if (!displayRange) {
    return "No time range";
  }

  return displayRange.replace(/\s*\(\s*\d+(?:\.\d+)?\s+hours?\s*\)\s*$/i, "").trim() || "No time range";
}

function ticketTimeEntryHoursLabel(rawHoursWorked) {
  const parsedHours = Number(ticketNotesSafeString(rawHoursWorked).trim());
  if (!Number.isFinite(parsedHours) || parsedHours <= 0) {
    return "";
  }

  const compactHours = parsedHours.toFixed(2).replace(/\.?0+$/, "");
  return parsedHours === 1 ? `${compactHours}hr` : `${compactHours}hrs`;
}

function ticketNotesButtonHasTicket(button) {
  return Boolean(ticketNotesSafeString(button.dataset.ticketNotesTicketNumber).trim());
}

function ticketTimeEntriesButtonHasTicket(button) {
  return Boolean(ticketNotesSafeString(button.dataset.ticketTimeEntriesTicketNumber).trim());
}

function ticketContextRequestCacheKey(url, ticketNumber) {
  return `${ticketNotesSafeString(url).trim()}\n${ticketNotesSafeString(ticketNumber).trim()}`;
}

function ticketContextRetryDelay(milliseconds) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

async function fetchTicketContextJson(url, fallbackErrorMessage) {
  let lastErrorMessage = fallbackErrorMessage;
  for (let attemptIndex = 0; attemptIndex < 2; attemptIndex += 1) {
    const response = await fetch(url, {headers: {Accept: "application/json"}});
    const payload = await response.json();
    if (response.ok) {
      return payload;
    }

    lastErrorMessage = payload.detail || fallbackErrorMessage;
    if (attemptIndex === 0) {
      await ticketContextRetryDelay(200);
    }
  }

  throw new Error(lastErrorMessage);
}

function ticketContextDefaultLabel(button, fallbackLabel) {
  const labelElement = button.querySelector("[data-ticket-context-label]");
  if (!button.dataset.ticketContextDefaultLabel) {
    const initialLabel = labelElement
      ? ticketNotesSafeString(labelElement.textContent).trim()
      : ticketNotesSafeString(button.textContent).trim();
    button.dataset.ticketContextDefaultLabel = initialLabel || fallbackLabel;
  }
  return button.dataset.ticketContextDefaultLabel || fallbackLabel;
}

function setTicketContextButtonLabel(button, labelText, fallbackLabel) {
  const safeLabelText = ticketNotesSafeString(labelText).trim() || fallbackLabel;
  let labelElement = button.querySelector("[data-ticket-context-label]");
  if (!labelElement) {
    labelElement = document.createElement("span");
    labelElement.dataset.ticketContextLabel = "";
    button.append(labelElement);
  }
  labelElement.textContent = safeLabelText;
}

function ticketContextButtonIsUnavailable(button) {
  return !button || button.disabled || button.classList.contains("is-empty-context");
}

function ticketContextPeerButtons(button, selector, urlDatasetName, ticketDatasetName) {
  if (!button) {
    return [];
  }

  const urlValue = ticketNotesSafeString(button.dataset[urlDatasetName]).trim();
  const ticketValue = ticketNotesSafeString(button.dataset[ticketDatasetName]).trim();
  const root = button.closest("[data-active-job-card], [data-review-ticket-title-card], .review-ticket-title-card")
    || button.parentElement
    || document;
  const peers = Array.from(root.querySelectorAll(selector)).filter((peerButton) => (
    ticketNotesSafeString(peerButton.dataset[urlDatasetName]).trim() === urlValue
    && ticketNotesSafeString(peerButton.dataset[ticketDatasetName]).trim() === ticketValue
  ));
  return peers.length ? peers : [button];
}

function ticketNotesPeerButtons(button) {
  return ticketContextPeerButtons(button, "[data-ticket-notes-button]", "ticketNotesUrl", "ticketNotesTicketNumber");
}

function ticketTimeEntriesPeerButtons(button) {
  return ticketContextPeerButtons(
    button,
    "[data-ticket-time-entries-button]",
    "ticketTimeEntriesUrl",
    "ticketTimeEntriesTicketNumber",
  );
}

function uniqueTicketContextButtons(buttons, urlDatasetName, ticketDatasetName) {
  const uniqueButtons = [];
  const seenKeys = new Set();
  for (const button of buttons) {
    const urlValue = ticketNotesSafeString(button.dataset[urlDatasetName]).trim();
    const ticketValue = ticketNotesSafeString(button.dataset[ticketDatasetName]).trim();
    const cacheKey = ticketContextRequestCacheKey(urlValue, ticketValue);
    if (seenKeys.has(cacheKey)) {
      continue;
    }
    seenKeys.add(cacheKey);
    uniqueButtons.push(button);
  }
  return uniqueButtons;
}

function resetTicketContextButton(button, fallbackLabel, countDatasetName, ariaLabel) {
  ticketContextDefaultLabel(button, fallbackLabel);
  setTicketContextButtonLabel(button, button.dataset.ticketContextDefaultLabel, fallbackLabel);
  button.classList.add("is-hidden");
  button.classList.remove("is-empty-context");
  if (button.matches("[data-ticket-notes-button]")) {
    setTicketNotesButtonIndicator(button, false);
  }
  button.disabled = true;
  button.setAttribute("aria-hidden", "true");
  button.setAttribute("aria-label", ariaLabel);
  delete button.dataset[countDatasetName];
}

function setTicketNotesButtonReady(button, notes = []) {
  const noteCount = Array.isArray(notes) ? notes.length : 0;
  const hasNotes = noteCount > 0;
  ticketContextDefaultLabel(button, "Ticket notes");
  button.classList.remove("is-hidden");
  button.classList.toggle("is-empty-context", !hasNotes);
  setTicketNotesButtonIndicator(button, hasNotes);
  button.disabled = !hasNotes;
  button.setAttribute("aria-hidden", "false");
  button.setAttribute("aria-label", hasNotes ? "View ticket notes" : "No ticket notes");
  button.dataset.ticketNotesCount = String(noteCount);
  setTicketContextButtonLabel(
    button,
    hasNotes ? button.dataset.ticketContextDefaultLabel : "No Notes",
    "Ticket notes",
  );
}

function setTicketTimeEntriesButtonReady(button, timeEntries = []) {
  const entryCount = Array.isArray(timeEntries) ? timeEntries.length : 0;
  const hasTimeEntries = entryCount > 0;
  ticketContextDefaultLabel(button, "Past time entries");
  button.classList.remove("is-hidden");
  button.classList.toggle("is-empty-context", !hasTimeEntries);
  button.disabled = !hasTimeEntries;
  button.setAttribute("aria-hidden", "false");
  button.setAttribute("aria-label", hasTimeEntries ? "View past time entries" : "No past time entries");
  button.dataset.ticketTimeEntriesCount = String(entryCount);
  setTicketContextButtonLabel(
    button,
    hasTimeEntries ? button.dataset.ticketContextDefaultLabel : "No past entries",
    "Past time entries",
  );
}

async function fetchTicketNotesForButton(button) {
  const notesUrl = ticketNotesSafeString(button.dataset.ticketNotesUrl).trim();
  if (!notesUrl || !ticketNotesButtonHasTicket(button)) {
    return {ticket_number: "", ticket_title: "", notes: []};
  }

  const ticketNumber = ticketNotesSafeString(button.dataset.ticketNotesTicketNumber).trim();
  const cacheKey = ticketContextRequestCacheKey(notesUrl, ticketNumber);
  const cachedRequest = ticketNoteRequestCache.get(cacheKey);
  if (cachedRequest) {
    return cachedRequest;
  }

  const request = (async () => {
    try {
      const payload = await fetchTicketContextJson(notesUrl, "Ticket notes could not be loaded.");

      return {
        target_type: ticketNotesSafeString(payload.target_type).trim() || "ticket",
        target_number: ticketNotesSafeString(payload.target_number).trim(),
        target_title: ticketNotesSafeString(payload.target_title).trim(),
        ticket_number: ticketNotesSafeString(payload.ticket_number).trim(),
        ticket_title: ticketNotesSafeString(payload.ticket_title).trim(),
        notes: Array.isArray(payload.notes) ? payload.notes : [],
      };
    } finally {
      ticketNoteRequestCache.delete(cacheKey);
    }
  })();
  ticketNoteRequestCache.set(cacheKey, request);
  return request;
}

async function fetchTicketTimeEntriesForButton(button) {
  const timeEntriesUrl = ticketNotesSafeString(button.dataset.ticketTimeEntriesUrl).trim();
  if (!timeEntriesUrl || !ticketTimeEntriesButtonHasTicket(button)) {
    return {ticket_number: "", ticket_title: "", time_entries: []};
  }

  const ticketNumber = ticketNotesSafeString(button.dataset.ticketTimeEntriesTicketNumber).trim();
  const cacheKey = ticketContextRequestCacheKey(timeEntriesUrl, ticketNumber);
  const cachedRequest = ticketTimeEntryRequestCache.get(cacheKey);
  if (cachedRequest) {
    return cachedRequest;
  }

  const request = (async () => {
    try {
      const payload = await fetchTicketContextJson(timeEntriesUrl, "Ticket time entries could not be loaded.");

      return {
        target_type: ticketNotesSafeString(payload.target_type).trim() || "ticket",
        target_number: ticketNotesSafeString(payload.target_number).trim(),
        target_title: ticketNotesSafeString(payload.target_title).trim(),
        ticket_number: ticketNotesSafeString(payload.ticket_number).trim(),
        ticket_title: ticketNotesSafeString(payload.ticket_title).trim(),
        time_entries: Array.isArray(payload.time_entries) ? payload.time_entries : [],
      };
    } finally {
      ticketTimeEntryRequestCache.delete(cacheKey);
    }
  })();
  ticketTimeEntryRequestCache.set(cacheKey, request);
  return request;
}

async function refreshTicketNotesButton(button) {
  if (!button) {
    return;
  }

  const peerButtons = ticketNotesPeerButtons(button);
  for (const peerButton of peerButtons) {
    resetTicketContextButton(peerButton, "Ticket notes", "ticketNotesCount", "View ticket notes");
  }
  if (!ticketNotesButtonHasTicket(button)) {
    for (const peerButton of peerButtons) {
      ticketNoteButtonCache.delete(peerButton);
    }
    return;
  }

  try {
    const payload = await fetchTicketNotesForButton(button);
    const defaultLabel = payload.target_type === "project_task" ? "Project task notes" : "Ticket notes";
    const ariaLabel = payload.target_type === "project_task" ? "View project task notes" : "View ticket notes";
    for (const peerButton of peerButtons) {
      resetTicketContextButton(peerButton, defaultLabel, "ticketNotesCount", ariaLabel);
      ticketNoteButtonCache.set(peerButton, payload);
      setTicketNotesButtonReady(peerButton, payload.notes);
    }
  } catch (error) {
    for (const peerButton of peerButtons) {
      ticketNoteButtonCache.delete(peerButton);
      resetTicketContextButton(peerButton, "Ticket notes", "ticketNotesCount", "View ticket notes");
    }
  }
}

async function refreshTicketTimeEntriesButton(button) {
  if (!button) {
    return;
  }

  const peerButtons = ticketTimeEntriesPeerButtons(button);
  for (const peerButton of peerButtons) {
    resetTicketContextButton(peerButton, "Past time entries", "ticketTimeEntriesCount", "View past time entries");
  }
  if (!ticketTimeEntriesButtonHasTicket(button)) {
    for (const peerButton of peerButtons) {
      ticketTimeEntryButtonCache.delete(peerButton);
    }
    return;
  }

  try {
    const payload = await fetchTicketTimeEntriesForButton(button);
    for (const peerButton of peerButtons) {
      ticketTimeEntryButtonCache.set(peerButton, payload);
      setTicketTimeEntriesButtonReady(peerButton, payload.time_entries);
    }
  } catch (error) {
    for (const peerButton of peerButtons) {
      ticketTimeEntryButtonCache.delete(peerButton);
      resetTicketContextButton(peerButton, "Past time entries", "ticketTimeEntriesCount", "View past time entries");
    }
  }
}

function refreshTicketNotesWithin(rootElement) {
  const root = rootElement || document;
  const ticketNoteButtons = root.querySelectorAll("[data-ticket-notes-button]");
  for (const button of uniqueTicketContextButtons(ticketNoteButtons, "ticketNotesUrl", "ticketNotesTicketNumber")) {
    refreshTicketNotesButton(button);
  }
  const ticketTimeEntryButtons = root.querySelectorAll("[data-ticket-time-entries-button]");
  for (
    const button of uniqueTicketContextButtons(
      ticketTimeEntryButtons,
      "ticketTimeEntriesUrl",
      "ticketTimeEntriesTicketNumber",
    )
  ) {
    refreshTicketTimeEntriesButton(button);
  }
}

function ticketNotesOverlayElements() {
  const overlay = document.querySelector("[data-ticket-notes-overlay]");
  return {
    overlay,
    eyebrow: overlay ? overlay.querySelector("[data-ticket-notes-eyebrow]") : null,
    title: overlay ? overlay.querySelector("[data-ticket-notes-title]") : null,
    subtitle: overlay ? overlay.querySelector("[data-ticket-notes-subtitle]") : null,
    list: overlay ? overlay.querySelector("[data-ticket-notes-list]") : null,
    detail: overlay ? overlay.querySelector("[data-ticket-note-detail]") : null,
  };
}

function ticketNoteMetaText(note) {
  const metaParts = [];
  const createdBy = ticketNotesSafeString(note.created_by).trim();
  const createdAt = ticketNotesSafeString(note.created_at).trim();
  const updatedAt = ticketNotesSafeString(note.updated_at).trim();
  const noteType = ticketNotesSafeString(note.note_type).trim();
  if (createdBy) {
    metaParts.push(`From ${createdBy}`);
  }
  if (createdAt) {
    metaParts.push(`Created ${createdAt}`);
  }
  if (updatedAt && updatedAt !== createdAt) {
    metaParts.push(`Updated ${updatedAt}`);
  }
  if (noteType) {
    metaParts.push(noteType);
  }
  return metaParts.join(" | ");
}

function renderTicketNoteDetail(detailElement, note) {
  if (!detailElement) {
    return;
  }

  detailElement.replaceChildren();
  const title = ticketNotesCreateElement("h3", "", ticketNotesSafeString(note.title).trim() || "Ticket note");
  const metaText = ticketNoteMetaText(note);
  const bodyText = ticketNotesSafeString(note.description).trim() || "No note details are available.";
  const body = ticketNotesCreateElement("p", "ticket-note-body", bodyText);
  detailElement.append(title);
  if (metaText) {
    detailElement.append(ticketNotesCreateElement("p", "ticket-note-meta muted-text", metaText));
  }
  detailElement.append(body);
}

function renderTicketTimeEntryDetail(detailElement, timeEntry) {
  if (!detailElement) {
    return;
  }

  detailElement.replaceChildren();
  const resourceName = ticketNotesResourceNameForDisplay(timeEntry.resource_name);
  const displayRange = ticketNotesSafeString(timeEntry.display_range).trim();
  const summaryText = ticketNotesSafeString(timeEntry.summary_notes).trim() || "No summary of work is available.";
  const title = ticketNotesCreateElement("h3", "", resourceName);
  const body = ticketNotesCreateElement("p", "ticket-note-body", summaryText);
  detailElement.append(title);
  if (displayRange) {
    detailElement.append(ticketNotesCreateElement("p", "ticket-note-meta ticket-time-entry-detail-range muted-text", displayRange));
  }
  detailElement.append(body);
}

function renderTicketNotesList(listElement, detailElement, notes) {
  if (!listElement) {
    return;
  }

  listElement.replaceChildren();
  notes.forEach((note, index) => {
    const noteButton = document.createElement("button");
    noteButton.type = "button";
    noteButton.className = "ticket-note-list-button";
    noteButton.setAttribute("aria-pressed", index === 0 ? "true" : "false");

    const title = ticketNotesCreateElement("span", "ticket-note-list-title", ticketNotesSafeString(note.title).trim() || "Ticket note");
    noteButton.append(title);

    noteButton.addEventListener("click", () => {
      for (const siblingButton of listElement.querySelectorAll(".ticket-note-list-button")) {
        siblingButton.setAttribute("aria-pressed", "false");
      }
      noteButton.setAttribute("aria-pressed", "true");
      renderTicketNoteDetail(detailElement, note);
    });
    listElement.append(noteButton);
  });

  if (notes.length > 0) {
    renderTicketNoteDetail(detailElement, notes[0]);
  }
}

function renderTicketTimeEntriesList(listElement, detailElement, timeEntries) {
  if (!listElement) {
    return;
  }

  listElement.replaceChildren();
  timeEntries.forEach((timeEntry, index) => {
    const timeEntryButton = document.createElement("button");
    timeEntryButton.type = "button";
    timeEntryButton.className = "ticket-note-list-button";
    timeEntryButton.setAttribute("aria-pressed", index === 0 ? "true" : "false");

    const header = ticketNotesCreateElement("span", "ticket-time-entry-list-header");
    const resource = ticketNotesCreateElement(
      "span",
      "ticket-time-entry-list-resource",
      ticketNotesResourceNameForDisplay(timeEntry.resource_name),
    );
    const hours = ticketTimeEntryHoursLabel(timeEntry.hours_worked);
    if (hours) {
      header.append(resource, ticketNotesCreateElement("span", "ticket-time-entry-list-hours", hours));
    } else {
      header.append(resource);
    }

    const range = ticketNotesCreateElement(
      "span",
      "ticket-time-entry-list-range",
      ticketTimeEntryListRangeForDisplay(timeEntry.display_range),
    );
    timeEntryButton.append(header);
    timeEntryButton.append(range);

    timeEntryButton.addEventListener("click", () => {
      for (const siblingButton of listElement.querySelectorAll(".ticket-note-list-button")) {
        siblingButton.setAttribute("aria-pressed", "false");
      }
      timeEntryButton.setAttribute("aria-pressed", "true");
      renderTicketTimeEntryDetail(detailElement, timeEntry);
    });
    listElement.append(timeEntryButton);
  });

  if (timeEntries.length > 0) {
    renderTicketTimeEntryDetail(detailElement, timeEntries[0]);
  }
}

function openTicketNotesOverlay(button) {
  if (ticketContextButtonIsUnavailable(button)) {
    return;
  }

  const cachedPayload = ticketNoteButtonCache.get(button);
  if (!cachedPayload || !cachedPayload.notes.length) {
    return;
  }

  const {overlay, eyebrow, title, subtitle, list, detail} = ticketNotesOverlayElements();
  if (!overlay || !list || !detail) {
    return;
  }

  const ticketNumber = cachedPayload.target_number || cachedPayload.ticket_number || ticketNotesSafeString(button.dataset.ticketNotesTicketNumber).trim();
  const ticketTitle = cachedPayload.target_title || cachedPayload.ticket_title;
  const isProjectTask = cachedPayload.target_type === "project_task";
  if (eyebrow) {
    eyebrow.textContent = isProjectTask ? "Project task notes" : "Ticket notes";
  }
  if (title) {
    title.textContent = ticketTitle || ticketNumber || (isProjectTask ? "Project task notes" : "Ticket notes");
  }
  if (subtitle) {
    const noteCount = cachedPayload.notes.length;
    const noteUnit = noteCount === 1 ? "note" : "notes";
    subtitle.textContent = ticketNumber ? `${ticketNumber} | ${noteCount} ${noteUnit}` : `${noteCount} ${noteUnit}`;
  }

  renderTicketNotesList(list, detail, cachedPayload.notes);
  overlay.classList.remove("is-hidden");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("ticket-notes-overlay-open");
  const closeButton = overlay.querySelector("[data-ticket-notes-close]");
  if (closeButton) {
    closeButton.focus();
  }
}

async function openNewestTicketNoteForButton(button) {
  if (!button || !ticketNotesButtonHasTicket(button)) {
    return;
  }

  await refreshTicketNotesButton(button);
  openTicketNotesOverlay(button);
}

function openTicketTimeEntriesOverlay(button) {
  if (ticketContextButtonIsUnavailable(button)) {
    return;
  }

  const cachedPayload = ticketTimeEntryButtonCache.get(button);
  if (!cachedPayload || !cachedPayload.time_entries.length) {
    return;
  }

  const {overlay, eyebrow, title, subtitle, list, detail} = ticketNotesOverlayElements();
  if (!overlay || !list || !detail) {
    return;
  }

  const ticketNumber = cachedPayload.target_number || cachedPayload.ticket_number || ticketNotesSafeString(button.dataset.ticketTimeEntriesTicketNumber).trim();
  const ticketTitle = cachedPayload.target_title || cachedPayload.ticket_title;
  if (eyebrow) {
    eyebrow.textContent = "Past time entries";
  }
  if (title) {
    title.textContent = ticketTitle || ticketNumber || "Past time entries";
  }
  if (subtitle) {
    const entryCount = cachedPayload.time_entries.length;
    const entryUnit = entryCount === 1 ? "time entry" : "time entries";
    subtitle.textContent = ticketNumber ? `${ticketNumber} | ${entryCount} ${entryUnit}` : `${entryCount} ${entryUnit}`;
  }

  renderTicketTimeEntriesList(list, detail, cachedPayload.time_entries);
  overlay.classList.remove("is-hidden");
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("ticket-notes-overlay-open");
  const closeButton = overlay.querySelector("[data-ticket-notes-close]");
  if (closeButton) {
    closeButton.focus();
  }
}

function closeTicketNotesOverlay() {
  const {overlay} = ticketNotesOverlayElements();
  if (!overlay) {
    return;
  }

  overlay.classList.add("is-hidden");
  overlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("ticket-notes-overlay-open");
}

function initializeTicketNotesOverlay() {
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }

    const notesButton = event.target.closest("[data-ticket-notes-button]");
    if (notesButton) {
      if (ticketContextButtonIsUnavailable(notesButton)) {
        return;
      }
      openTicketNotesOverlay(notesButton);
      return;
    }

    const timeEntriesButton = event.target.closest("[data-ticket-time-entries-button]");
    if (timeEntriesButton) {
      if (ticketContextButtonIsUnavailable(timeEntriesButton)) {
        return;
      }
      openTicketTimeEntriesOverlay(timeEntriesButton);
      return;
    }

    const closeButton = event.target.closest("[data-ticket-notes-close]");
    if (closeButton) {
      closeTicketNotesOverlay();
      return;
    }

    const overlay = event.target.closest("[data-ticket-notes-overlay]");
    if (overlay && event.target === overlay) {
      closeTicketNotesOverlay();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeTicketNotesOverlay();
    }
  });

  refreshTicketNotesWithin(document);
}

window.TicketPilotTicketNotes = {
  createCustomerNoteIndicator,
  openNewestForButton: openNewestTicketNoteForButton,
  refreshButton: refreshTicketNotesButton,
  refreshTimeEntriesButton: refreshTicketTimeEntriesButton,
  refreshWithin: refreshTicketNotesWithin,
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeTicketNotesOverlay, {once: true});
} else {
  initializeTicketNotesOverlay();
}
