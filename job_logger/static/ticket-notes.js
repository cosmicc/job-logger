const ticketNoteButtonCache = new WeakMap();
const ticketTimeEntryButtonCache = new WeakMap();

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

function resetTicketContextButton(button, fallbackLabel, countDatasetName, ariaLabel) {
  ticketContextDefaultLabel(button, fallbackLabel);
  setTicketContextButtonLabel(button, button.dataset.ticketContextDefaultLabel, fallbackLabel);
  button.classList.add("is-hidden");
  button.classList.remove("is-empty-context");
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

  const response = await fetch(notesUrl, {headers: {Accept: "application/json"}});
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Ticket notes could not be loaded.");
  }

  return {
    ticket_number: ticketNotesSafeString(payload.ticket_number).trim(),
    ticket_title: ticketNotesSafeString(payload.ticket_title).trim(),
    notes: Array.isArray(payload.notes) ? payload.notes : [],
  };
}

async function fetchTicketTimeEntriesForButton(button) {
  const timeEntriesUrl = ticketNotesSafeString(button.dataset.ticketTimeEntriesUrl).trim();
  if (!timeEntriesUrl || !ticketTimeEntriesButtonHasTicket(button)) {
    return {ticket_number: "", ticket_title: "", time_entries: []};
  }

  const response = await fetch(timeEntriesUrl, {headers: {Accept: "application/json"}});
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Ticket time entries could not be loaded.");
  }

  return {
    ticket_number: ticketNotesSafeString(payload.ticket_number).trim(),
    ticket_title: ticketNotesSafeString(payload.ticket_title).trim(),
    time_entries: Array.isArray(payload.time_entries) ? payload.time_entries : [],
  };
}

async function refreshTicketNotesButton(button) {
  if (!button) {
    return;
  }

  resetTicketContextButton(button, "Ticket notes", "ticketNotesCount", "View ticket notes");
  if (!ticketNotesButtonHasTicket(button)) {
    ticketNoteButtonCache.delete(button);
    return;
  }

  try {
    const payload = await fetchTicketNotesForButton(button);
    ticketNoteButtonCache.set(button, payload);
    setTicketNotesButtonReady(button, payload.notes);
  } catch (error) {
    ticketNoteButtonCache.delete(button);
    resetTicketContextButton(button, "Ticket notes", "ticketNotesCount", "View ticket notes");
  }
}

async function refreshTicketTimeEntriesButton(button) {
  if (!button) {
    return;
  }

  resetTicketContextButton(button, "Past time entries", "ticketTimeEntriesCount", "View past time entries");
  if (!ticketTimeEntriesButtonHasTicket(button)) {
    ticketTimeEntryButtonCache.delete(button);
    return;
  }

  try {
    const payload = await fetchTicketTimeEntriesForButton(button);
    ticketTimeEntryButtonCache.set(button, payload);
    setTicketTimeEntriesButtonReady(button, payload.time_entries);
  } catch (error) {
    ticketTimeEntryButtonCache.delete(button);
    resetTicketContextButton(button, "Past time entries", "ticketTimeEntriesCount", "View past time entries");
  }
}

function refreshTicketNotesWithin(rootElement) {
  const root = rootElement || document;
  const ticketNoteButtons = root.querySelectorAll("[data-ticket-notes-button]");
  for (const button of ticketNoteButtons) {
    refreshTicketNotesButton(button);
  }
  const ticketTimeEntryButtons = root.querySelectorAll("[data-ticket-time-entries-button]");
  for (const button of ticketTimeEntryButtons) {
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

  const ticketNumber = cachedPayload.ticket_number || ticketNotesSafeString(button.dataset.ticketNotesTicketNumber).trim();
  const ticketTitle = cachedPayload.ticket_title;
  if (eyebrow) {
    eyebrow.textContent = "Ticket notes";
  }
  if (title) {
    title.textContent = ticketTitle || ticketNumber || "Ticket notes";
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

  const ticketNumber = cachedPayload.ticket_number || ticketNotesSafeString(button.dataset.ticketTimeEntriesTicketNumber).trim();
  const ticketTitle = cachedPayload.ticket_title;
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

window.JobLoggerTicketNotes = {
  refreshButton: refreshTicketNotesButton,
  refreshTimeEntriesButton: refreshTicketTimeEntriesButton,
  refreshWithin: refreshTicketNotesWithin,
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeTicketNotesOverlay, {once: true});
} else {
  initializeTicketNotesOverlay();
}
