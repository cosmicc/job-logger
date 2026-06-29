const ticketNoteButtonCache = new WeakMap();

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

function ticketNotesButtonHasTicket(button) {
  return Boolean(ticketNotesSafeString(button.dataset.ticketNotesTicketNumber).trim());
}

function setTicketNotesButtonVisible(button, isVisible, notes = []) {
  button.classList.toggle("is-hidden", !isVisible);
  button.disabled = !isVisible;
  button.setAttribute("aria-hidden", isVisible ? "false" : "true");
  if (isVisible) {
    const noteCount = Array.isArray(notes) ? notes.length : 0;
    button.dataset.ticketNotesCount = String(noteCount);
  } else {
    delete button.dataset.ticketNotesCount;
  }
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

async function refreshTicketNotesButton(button) {
  if (!button) {
    return;
  }

  setTicketNotesButtonVisible(button, false);
  if (!ticketNotesButtonHasTicket(button)) {
    ticketNoteButtonCache.delete(button);
    return;
  }

  try {
    const payload = await fetchTicketNotesForButton(button);
    ticketNoteButtonCache.set(button, payload);
    setTicketNotesButtonVisible(button, payload.notes.length > 0, payload.notes);
  } catch (error) {
    ticketNoteButtonCache.delete(button);
    setTicketNotesButtonVisible(button, false);
  }
}

function refreshTicketNotesWithin(rootElement) {
  const root = rootElement || document;
  const ticketNoteButtons = root.querySelectorAll("[data-ticket-notes-button]");
  for (const button of ticketNoteButtons) {
    refreshTicketNotesButton(button);
  }
}

function ticketNotesOverlayElements() {
  const overlay = document.querySelector("[data-ticket-notes-overlay]");
  return {
    overlay,
    title: overlay ? overlay.querySelector("[data-ticket-notes-title]") : null,
    subtitle: overlay ? overlay.querySelector("[data-ticket-notes-subtitle]") : null,
    list: overlay ? overlay.querySelector("[data-ticket-notes-list]") : null,
    detail: overlay ? overlay.querySelector("[data-ticket-note-detail]") : null,
  };
}

function ticketNoteMetaText(note) {
  const metaParts = [];
  const createdAt = ticketNotesSafeString(note.created_at).trim();
  const updatedAt = ticketNotesSafeString(note.updated_at).trim();
  const noteType = ticketNotesSafeString(note.note_type).trim();
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
    const preview = ticketNotesCreateElement("span", "ticket-note-list-preview", ticketNotesSafeString(note.preview).trim());
    const meta = ticketNotesCreateElement("span", "ticket-note-list-meta", ticketNoteMetaText(note));
    noteButton.append(title);
    if (preview.textContent) {
      noteButton.append(preview);
    }
    if (meta.textContent) {
      noteButton.append(meta);
    }

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

function openTicketNotesOverlay(button) {
  const cachedPayload = ticketNoteButtonCache.get(button);
  if (!cachedPayload || !cachedPayload.notes.length) {
    return;
  }

  const {overlay, title, subtitle, list, detail} = ticketNotesOverlayElements();
  if (!overlay || !list || !detail) {
    return;
  }

  const ticketNumber = cachedPayload.ticket_number || ticketNotesSafeString(button.dataset.ticketNotesTicketNumber).trim();
  const ticketTitle = cachedPayload.ticket_title;
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
      openTicketNotesOverlay(notesButton);
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
  refreshWithin: refreshTicketNotesWithin,
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initializeTicketNotesOverlay, {once: true});
} else {
  initializeTicketNotesOverlay();
}
