const DESCRIPTION_SAVE_DELAY_MS = 650;
const ACTIVE_FORM_SAVE_DELAY_MS = 650;
const ACTIVE_TIME_SAVE_DELAY_MS = 650;
const COMPANY_SEARCH_DELAY_MS = 400;
const MIN_COMPANY_SEARCH_CHARACTERS = 3;
const RECORDING_CHUNK_INTERVAL_MS = 2500;
const MAX_SOCKET_BUFFERED_BYTES = 2 * 1024 * 1024;
const ROUNDING_INTERVAL_MINUTES = 15;
const LIVE_ROUNDED_STOP_UPDATE_MS = 30000;
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
const RECORD_AUDIO_LABEL = "Record";
const STOP_RECORDING_LABEL = "Stop recording";
const RECORDING_STATUS_RECORDING = "Recording audio...";
const RECORDING_STATUS_SENDING = "Sending data to server...";
const RECORDING_STATUS_CONVERTING = "Converting audio to text...";
const RECORDING_STATUS_COMPLETE = "Conversion complete.";
const WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const activeRecordButtons = document.querySelectorAll(".record-notes-button");
const descriptionTextareas = document.querySelectorAll(".job-description");
const endJobForms = document.querySelectorAll(".end-job-form");
const activeTicketForms = document.querySelectorAll(".active-ticket-form");
const companyInputs = document.querySelectorAll("[data-company-input]");
const activeTicketPickers = document.querySelectorAll("[data-active-ticket-picker]");
const workLocationInputs = document.querySelectorAll("[data-work-location-input]");
const activeEntryTypeInputs = document.querySelectorAll("[data-entry-type-input]");
const activeNoteTitleInputs = document.querySelectorAll("[data-note-title-input]");
const activeAppendResolutionInputs = document.querySelectorAll("[data-append-resolution-input]");
const activeTicketStatusInputs = document.querySelectorAll("[data-active-ticket-status-input]");
const activeJobDateInputs = document.querySelectorAll("[data-active-job-date-input]");
const activeTimeForms = document.querySelectorAll("[data-active-time-form]");
const serviceCallPanels = document.querySelectorAll("[data-service-call-panel]");
const aiCleanupButtons = document.querySelectorAll("[data-ai-cleanup-button]");
const roundedStopDisplays = document.querySelectorAll("[data-rounded-stop-display]");
const mobilePageLoadingOverlay = document.querySelector("[data-mobile-page-loading]");
const mobilePageLoadingMessage = document.querySelector("[data-mobile-page-loading-message]");

const descriptionSaveTimers = new Map();
const activeFormSaveTimers = new WeakMap();
const lastSavedActiveFormSnapshots = new WeakMap();
const activeTimeSaveTimers = new WeakMap();
const lastSavedActiveTimeSnapshots = new WeakMap();
const companySearchTimers = new Map();
const lastSavedDescriptions = new Map();
const pendingDescriptionSaves = new Set();
const activeTicketLookupRequests = new WeakSet();
const activeTicketLookupLoaded = new WeakSet();

let activeRecorder = null;
let activeAudioStream = null;
let activeAudioSocket = null;
let activeAudioStreamFinalResolve = null;
let activeAudioStreamFinalReject = null;
let activeRecordingJobId = "";
let activeAudioCompletionInProgress = false;
let isUploadingRecording = false;
let hasRecordedAudio = false;
let activeAudioStreamReady = false;
let activeAudioStreamFailed = false;
let isStartingRecording = false;
let activeAudioStopRequested = false;

function toSafeMapString(value) {
  return String(value || "");
}

function formDataBooleanValue(formData, fieldName) {
  if (!formData) {
    return "false";
  }

  return formData
    .getAll(fieldName)
    .some((fieldValue) => String(fieldValue).trim().toLowerCase() === "true")
    ? "true"
    : "false";
}

function normalizedDateValue(dateValue) {
  const normalizedDate = toSafeMapString(dateValue).trim();
  const dateMatch = normalizedDate.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!dateMatch) {
    return null;
  }

  const year = Number(dateMatch[1]);
  const monthIndex = Number(dateMatch[2]) - 1;
  const day = Number(dateMatch[3]);
  const localDate = new Date(year, monthIndex, day);
  if (
    localDate.getFullYear() !== year
    || localDate.getMonth() !== monthIndex
    || localDate.getDate() !== day
  ) {
    return null;
  }

  return {normalizedDate, localDate};
}

function weekdayNameForDateValue(dateValue) {
  const dateInfo = normalizedDateValue(dateValue);
  if (!dateInfo) {
    return "";
  }

  return WEEKDAY_NAMES[dateInfo.localDate.getDay()] || "";
}

function currentDetroitDateValue() {
  const dateParts = new Intl.DateTimeFormat("en-US", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "America/Detroit",
    year: "numeric",
  }).formatToParts(new Date());
  const partValues = Object.fromEntries(dateParts.map((part) => [part.type, part.value]));
  if (!partValues.year || !partValues.month || !partValues.day) {
    return "";
  }

  return `${partValues.year}-${partValues.month}-${partValues.day}`;
}

function jobDateLabelForDateValue(dateValue, currentDateValue = currentDetroitDateValue()) {
  const dateInfo = normalizedDateValue(dateValue);
  if (!dateInfo) {
    return "";
  }

  if (dateInfo.normalizedDate === currentDateValue) {
    return "Today";
  }

  return WEEKDAY_NAMES[dateInfo.localDate.getDay()] || "";
}

function setDateWeekdayLabelText(labelElement, dateValue) {
  if (!labelElement) {
    return;
  }

  const dateLabel = jobDateLabelForDateValue(dateValue);
  labelElement.textContent = dateLabel ? `(${dateLabel})` : "";
}

function updateActiveJobDateWeekday(activeJobCard, dateValue) {
  if (!activeJobCard) {
    return;
  }

  setDateWeekdayLabelText(activeJobCard.querySelector("[data-date-weekday-label]"), dateValue);
}

function findDescriptionTextarea(jobId) {
  if (!jobId) {
    return null;
  }

  return document.querySelector(`.job-description[data-job-id="${toSafeMapString(jobId)}"]`);
}

function findRecordingStatusElement(jobId) {
  if (!jobId) {
    return null;
  }

  return document.querySelector(`.recording-status[data-job-id="${toSafeMapString(jobId)}"]`);
}

function findActiveSaveStatusElement(jobId) {
  if (!jobId) {
    return null;
  }

  return document.querySelector(`[data-active-save-status][data-job-id="${toSafeMapString(jobId)}"]`);
}

function findActiveTicketForm(jobId) {
  if (!jobId) {
    return null;
  }

  return document.querySelector(`.active-ticket-form[data-job-id="${toSafeMapString(jobId)}"]`);
}

function findActiveTicketPicker(jobId) {
  if (!jobId) {
    return null;
  }

  return document.querySelector(`[data-active-ticket-picker][data-ticket-form-job-id="${toSafeMapString(jobId)}"]`);
}

function resolveFormForControl(controlElement) {
  if (!controlElement) {
    return null;
  }

  const parentForm = controlElement.closest("form");
  if (parentForm) {
    return parentForm;
  }

  const formId = controlElement.getAttribute("form");
  if (!formId) {
    return null;
  }

  return document.getElementById(formId);
}

function readActiveJobClientFields(jobId) {
  const activeTicketForm = findActiveTicketForm(jobId);
  if (!activeTicketForm) {
    return {clientName: "", autotaskCompanyId: ""};
  }

  // The active job card has one authoritative client source. It may be a
  // visible autocomplete input while unlocked, or a hidden value after an
  // Autotask company has been selected and locked for the active job.
  const formClientInput = activeTicketForm.querySelector("[data-active-client-source]");
  const formId = toSafeMapString(activeTicketForm.id);
  const formLinkedClientInput = formId
    ? document.querySelector(`.active-client-name-source[form="${formId}"]`)
    : null;
  const clientNameSource = formClientInput || formLinkedClientInput;
  const autotaskCompanyIdSource = activeTicketForm.querySelector("[data-company-id-input]");
  return {
    clientName: clientNameSource ? clientNameSource.value : "",
    autotaskCompanyId: autotaskCompanyIdSource ? autotaskCompanyIdSource.value : "",
  };
}

function syncEndJobClientFields(endJobForm) {
  const jobId = toSafeMapString(endJobForm.dataset.jobId);
  const clientFields = readActiveJobClientFields(jobId);
  const activeTicketForm = findActiveTicketForm(jobId);
  const activeFormData = activeTicketForm ? new FormData(activeTicketForm) : null;
  const endClientNameField = endJobForm.querySelector(".end-client-name");
  const endAutotaskCompanyIdField = endJobForm.querySelector(".end-autotask-company-id");
  const endWorkLocationField = endJobForm.querySelector(".end-work-location");
  const endEntryTypeField = endJobForm.querySelector(".end-entry-type");
  const endNoteTitleField = endJobForm.querySelector(".end-note-title");
  const endAppendResolutionField = endJobForm.querySelector(".end-append-to-resolution");
  const endTicketStatusField = endJobForm.querySelector(".end-ticket-status");

  if (endClientNameField) {
    endClientNameField.value = clientFields.clientName;
  }

  if (endAutotaskCompanyIdField) {
    endAutotaskCompanyIdField.value = clientFields.autotaskCompanyId;
  }

  if (endWorkLocationField && activeFormData) {
    endWorkLocationField.value = toSafeMapString(activeFormData.get("work_location") || endWorkLocationField.value);
  }

  if (endEntryTypeField && activeFormData) {
    endEntryTypeField.value = toSafeMapString(activeFormData.get("entry_type") || "time_entry");
  }

  if (endNoteTitleField && activeFormData) {
    endNoteTitleField.value = toSafeMapString(activeFormData.get("note_title") || "");
  }

  if (endAppendResolutionField && activeFormData) {
    endAppendResolutionField.value = formDataBooleanValue(activeFormData, "append_to_resolution");
  }

  if (endTicketStatusField && activeFormData) {
    endTicketStatusField.value = toSafeMapString(activeFormData.get("ticket_status") || endTicketStatusField.value);
  }
}

function activeEntryTypeForCard(activeJobCard) {
  const checkedEntryTypeInput = activeJobCard
    ? activeJobCard.querySelector('[data-entry-type-input]:checked')
    : null;
  return checkedEntryTypeInput ? checkedEntryTypeInput.value : "time_entry";
}

function syncActiveEntryMode(activeJobCard) {
  if (!activeJobCard) {
    return;
  }

  const isTicketNote = activeEntryTypeForCard(activeJobCard) === "ticket_note";
  activeJobCard.classList.toggle("active-job-ticket-note", isTicketNote);
  for (const activeTimeForm of activeJobCard.querySelectorAll("[data-active-time-form]")) {
    activeTimeForm.classList.toggle("time-controls-disabled", isTicketNote);
    activeTimeForm.querySelectorAll("button, input").forEach((controlElement) => {
      if (controlElement.name === "csrf_token" || controlElement.dataset.activeTimeJobDate !== undefined) {
        return;
      }
      controlElement.disabled = isTicketNote;
    });
  }

  const durationRow = activeJobCard.querySelector("[data-duration-row]");
  if (durationRow) {
    durationRow.classList.toggle("is-hidden", isTicketNote);
  }

  const workLocationCard = activeJobCard.querySelector("[data-work-location-card]");
  if (workLocationCard) {
    workLocationCard.classList.toggle("is-hidden", isTicketNote);
    workLocationCard.querySelectorAll("[data-work-location-input]").forEach((inputElement) => {
      inputElement.disabled = isTicketNote;
    });
  }

  const noteTitleField = activeJobCard.querySelector("[data-note-title-field]");
  const noteTitleInput = activeJobCard.querySelector("[data-note-title-input]");
  if (noteTitleField) {
    noteTitleField.classList.toggle("is-hidden", !isTicketNote);
  }
  if (noteTitleInput) {
    noteTitleInput.disabled = !isTicketNote;
    noteTitleInput.required = isTicketNote;
  }

  const summaryLabel = activeJobCard.querySelector("[data-summary-label]");
  if (summaryLabel) {
    summaryLabel.textContent = isTicketNote ? "Note description" : "Summary notes";
  }

  const endJobForm = activeJobCard.querySelector(".end-job-form");
  if (endJobForm) {
    const isDirectSubmit = endJobForm.dataset.submitFromWorkInProgress === "true";
    const endLabel = endJobForm.querySelector("[data-end-entry-label]");
    endJobForm.dataset.loadingMessage = isTicketNote
      ? (isDirectSubmit ? "Submitting note to Autotask..." : "Ending note...")
      : (isDirectSubmit ? "Submitting to Autotask..." : "Ending work...");
    if (endLabel) {
      endLabel.textContent = isTicketNote
        ? (isDirectSubmit ? "Submit note" : "End Note")
        : (isDirectSubmit ? "Submit to Autotask" : "End Work");
    }
    syncEndJobClientFields(endJobForm);
  }

  const deleteForm = activeJobCard.querySelector(".delete-active-job-form");
  if (deleteForm) {
    deleteForm.dataset.loadingMessage = isTicketNote ? "Deleting note..." : "Deleting time entry...";
    deleteForm.dataset.confirmMessage = isTicketNote
      ? "Delete this note? This removes the in-progress note without sending it to review."
      : "Delete this time entry? This removes the in-progress entry without sending it to review.";
    const deleteLabel = deleteForm.querySelector("[data-delete-entry-label]");
    if (deleteLabel) {
      deleteLabel.textContent = isTicketNote ? "Delete Note" : "Delete";
    }
  }
}

function initializeActiveEntryModes() {
  document.querySelectorAll("[data-active-job-card]").forEach((activeJobCard) => {
    syncActiveEntryMode(activeJobCard);
  });
}

function parseLocalTimeDisplay(rawLocalTime) {
  const normalizedLocalTime = toSafeMapString(rawLocalTime).trim().toLowerCase();
  const timeMatch = normalizedLocalTime.match(/^(\d{1,2}):(\d{2})\s*(am|pm)$/);
  if (!timeMatch) {
    return null;
  }

  const displayHour = Number.parseInt(timeMatch[1], 10);
  const displayMinute = Number.parseInt(timeMatch[2], 10);
  const displayPeriod = timeMatch[3];
  if (displayHour < 1 || displayHour > 12 || displayMinute < 0 || displayMinute > 59) {
    return null;
  }

  const hour24 = displayPeriod === "am"
    ? (displayHour === 12 ? 0 : displayHour)
    : (displayHour === 12 ? 12 : displayHour + 12);
  return hour24 * 60 + displayMinute;
}

function formatLocalMinutes(totalLocalMinutes) {
  const minutesPerDay = 24 * 60;
  const normalizedMinutes = ((totalLocalMinutes % minutesPerDay) + minutesPerDay) % minutesPerDay;
  const hour24 = Math.floor(normalizedMinutes / 60);
  const displayMinute = normalizedMinutes % 60;
  const displayHour = hour24 % 12 || 12;
  const displayPeriod = hour24 < 12 ? "am" : "pm";
  return `${displayHour}:${String(displayMinute).padStart(2, "0")} ${displayPeriod}`;
}

function formatDurationMinutes(totalMinutes) {
  if (!Number.isFinite(totalMinutes) || totalMinutes <= 0) {
    return "";
  }

  if (totalMinutes < 60) {
    return `${totalMinutes} ${totalMinutes === 1 ? "Minute" : "Minutes"}`;
  }

  const wholeHours = Math.floor(totalMinutes / 60);
  const remainingMinutes = totalMinutes % 60;
  if (remainingMinutes === 0) {
    return `${wholeHours} ${wholeHours === 1 ? "Hour" : "Hours"}`;
  }

  return `${(totalMinutes / 60).toFixed(2).replace(/0+$/, "").replace(/\.$/, "")} Hours`;
}

function updateActiveDurationDisplay(activeJobCard) {
  if (!activeJobCard) {
    return;
  }

  const startTimeInput = activeJobCard.querySelector('[data-active-time-input][data-active-time-kind="start"]');
  const stopTimeInput = activeJobCard.querySelector('[data-active-time-input][data-active-time-kind="stop"]');
  const durationDisplay = activeJobCard.querySelector("[data-duration-display]");
  if (!startTimeInput || !stopTimeInput || !durationDisplay) {
    return;
  }

  const startMinutes = parseLocalTimeDisplay(startTimeInput.value);
  const stopMinutes = parseLocalTimeDisplay(stopTimeInput.value);
  if (startMinutes === null || stopMinutes === null || stopMinutes <= startMinutes) {
    durationDisplay.textContent = "";
    return;
  }

  durationDisplay.textContent = formatDurationMinutes(stopMinutes - startMinutes);
}

function initializeActiveDurationDisplays() {
  const activeJobCards = document.querySelectorAll("[data-active-job-card]");
  for (const activeJobCard of activeJobCards) {
    updateActiveDurationDisplay(activeJobCard);
  }
}

function formatRoundedStopDisplay(timestamp, displayElement) {
  const initialRoundedStopDate = parseRoundedStopDate(displayElement.dataset.initialRoundedStopUtc);
  const initialLocalMinutes = parseLocalTimeDisplay(displayElement.dataset.initialRoundedStopLocalTime);
  if (initialRoundedStopDate && initialLocalMinutes !== null) {
    const elapsedMinutes = Math.round((timestamp.getTime() - initialRoundedStopDate.getTime()) / (60 * 1000));
    return formatLocalMinutes(initialLocalMinutes + elapsedMinutes);
  }

  return displayElement.textContent.trim();
}

function parseRoundedStopDate(rawTimestamp) {
  const parsedDate = new Date(toSafeMapString(rawTimestamp));
  if (Number.isNaN(parsedDate.getTime())) {
    return null;
  }

  return parsedDate;
}

function ceilDateToQuarterHour(timestamp) {
  const intervalMilliseconds = ROUNDING_INTERVAL_MINUTES * 60 * 1000;
  const timestampMilliseconds = timestamp.getTime();
  return new Date(Math.ceil(timestampMilliseconds / intervalMilliseconds) * intervalMilliseconds);
}

function minimumRoundedStopForDisplay(displayElement) {
  const roundedStartDate = parseRoundedStopDate(displayElement.dataset.roundedStartUtc);
  if (!roundedStartDate) {
    return null;
  }

  return new Date(roundedStartDate.getTime() + ROUNDING_INTERVAL_MINUTES * 60 * 1000);
}

function resolveLiveRoundedStop(displayElement) {
  const roundedStopDate = ceilDateToQuarterHour(new Date());
  const minimumRoundedStop = minimumRoundedStopForDisplay(displayElement);
  if (minimumRoundedStop && roundedStopDate < minimumRoundedStop) {
    return minimumRoundedStop;
  }

  return roundedStopDate;
}

function updateLiveRoundedStopDisplay(displayElement) {
  if (displayElement.dataset.roundedStopOverridden === "true") {
    return;
  }
  if (document.activeElement === displayElement) {
    return;
  }

  const nextDisplayText = formatRoundedStopDisplay(resolveLiveRoundedStop(displayElement), displayElement);
  if ("value" in displayElement) {
    displayElement.value = nextDisplayText;
    updateActiveDurationDisplay(displayElement.closest("[data-active-job-card]"));
    return;
  }

  displayElement.textContent = nextDisplayText;
}

function initializeLiveRoundedStopDisplays() {
  if (!roundedStopDisplays.length) {
    return;
  }

  for (const roundedStopDisplay of roundedStopDisplays) {
    updateLiveRoundedStopDisplay(roundedStopDisplay);
  }

  window.setInterval(() => {
    for (const roundedStopDisplay of roundedStopDisplays) {
      updateLiveRoundedStopDisplay(roundedStopDisplay);
    }
  }, LIVE_ROUNDED_STOP_UPDATE_MS);
}

function findControlElements(jobId) {
  return {
    recordButton: document.querySelector(`.record-notes-button[data-job-id="${toSafeMapString(jobId)}"]`),
    recordButtonLabel: document.querySelector(`.record-notes-button[data-job-id="${toSafeMapString(jobId)}"] [data-record-audio-label]`),
    statusElement: findRecordingStatusElement(jobId),
  };
}

function getCompanyPickerElements(companyInput) {
  const parentForm = resolveFormForControl(companyInput);
  if (!parentForm) {
    return {companyIdInput: null, resultsElement: null, statusElement: null};
  }

  return {
    companyIdInput: parentForm.querySelector("[data-company-id-input]"),
    resultsElement: parentForm.querySelector("[data-company-results]"),
    statusElement: parentForm.querySelector("[data-company-status]"),
  };
}

function clearCompanyResults(companyInput) {
  const {resultsElement} = getCompanyPickerElements(companyInput);
  if (resultsElement) {
    resultsElement.replaceChildren();
  }
}

function setCompanyStatus(companyInput, message, isError = false) {
  const {statusElement} = getCompanyPickerElements(companyInput);
  if (!statusElement) {
    return;
  }

  statusElement.textContent = message;
  statusElement.classList.toggle("error-text", isError);
}

function submitFormWithCurrentFields(formElement) {
  if (!formElement) {
    return;
  }

  if (formElement.requestSubmit) {
    formElement.requestSubmit();
    return;
  }

  const shouldSubmit = formElement.dispatchEvent(new Event("submit", {cancelable: true}));
  if (shouldSubmit) {
    formElement.submit();
  }
}

function showMobilePageLoading(message) {
  if (!mobilePageLoadingOverlay) {
    return;
  }

  if (mobilePageLoadingMessage) {
    mobilePageLoadingMessage.textContent = message || "Loading...";
  }
  mobilePageLoadingOverlay.classList.remove("is-hidden");
}

function hideMobilePageLoading() {
  if (!mobilePageLoadingOverlay) {
    return;
  }

  mobilePageLoadingOverlay.classList.add("is-hidden");
}

function markSubmitFormPending(formElement) {
  const submitButton = formElement.querySelector('button[type="submit"]');
  if (submitButton) {
    submitButton.classList.add("is-loading");
    submitButton.setAttribute("aria-busy", "true");
    submitButton.setAttribute("aria-disabled", "true");
  }
  showMobilePageLoading(formElement.dataset.loadingMessage || "Loading...");
}

function handlePageLoadingSubmitButtonClick(event) {
  const submitButton = event.target.closest('button[type="submit"]');
  if (!submitButton) {
    return;
  }

  const formElement = submitButton.form;
  if (!formElement || !formElement.matches("[data-page-loading-form]")) {
    return;
  }

  if (typeof formElement.reportValidity === "function" && !formElement.reportValidity()) {
    event.preventDefault();
    return;
  }

  const confirmationMessage = formElement.dataset.confirmMessage || "";
  if (confirmationMessage && !window.confirm(confirmationMessage)) {
    event.preventDefault();
    return;
  }

  formElement.dataset.loadingConfirmed = "true";
  markSubmitFormPending(formElement);
}

function handlePageLoadingFormSubmit(event) {
  const formElement = event.target.closest("[data-page-loading-form]");
  if (!formElement || event.defaultPrevented) {
    return;
  }

  if (formElement.dataset.loadingConfirmed === "true") {
    delete formElement.dataset.loadingConfirmed;
    return;
  }

  const confirmationMessage = formElement.dataset.confirmMessage || "";
  if (confirmationMessage && !window.confirm(confirmationMessage)) {
    event.preventDefault();
    return;
  }

  markSubmitFormPending(formElement);
}

function setActiveSaveStatus(jobId, message, isError = false) {
  const statusElement = findActiveSaveStatusElement(jobId);
  if (!statusElement) {
    return;
  }

  statusElement.textContent = message;
  statusElement.classList.toggle("error-text", isError);
}

function setInlineLoadingStatus(statusElement, message, {isError = false} = {}) {
  if (!statusElement) {
    return;
  }

  statusElement.classList.toggle("error-text", isError);
  statusElement.classList.remove("is-loading");
  statusElement.textContent = message;
}

function setAiCleanupStatus(jobId, message, isError = false, isLoading = false) {
  setRecordingStatus(jobId, message, isError, isLoading);
}

function setAiCleanupButtonLoading(button, isLoading) {
  if (!button) {
    return;
  }

  button.disabled = isLoading;
  button.classList.toggle("is-loading", isLoading);
  button.setAttribute("aria-busy", isLoading ? "true" : "false");
}

function setAiCleanupButtonMode(button, mode) {
  if (!button) {
    return;
  }

  const normalizedMode = mode === "revert" ? "revert" : "cleanup";
  const labelElement = typeof button.querySelector === "function"
    ? button.querySelector("[data-ai-cleanup-label]") || button.querySelector("span")
    : null;
  button.dataset.cleanupMode = normalizedMode;
  if (labelElement) {
    labelElement.textContent = normalizedMode === "revert" ? "Revert cleanup" : "AI Cleanup";
  }
}

function populateActiveFormSummaryField(activeTicketForm) {
  if (!activeTicketForm) {
    return;
  }

  const summaryField = activeTicketForm.querySelector(".active-job-summary");
  if (!summaryField) {
    return;
  }

  const safeJobId = toSafeMapString(activeTicketForm.dataset.jobId);
  const descriptionElement = findDescriptionTextarea(safeJobId);
  if (descriptionElement) {
    summaryField.value = descriptionElement.value || "";
  }
  clearDescriptionTimer(safeJobId);
  pendingDescriptionSaves.delete(safeJobId);
}

function buildActiveJobFormSnapshot(activeTicketForm) {
  if (!activeTicketForm) {
    return "";
  }

  populateActiveFormSummaryField(activeTicketForm);
  return new URLSearchParams(new FormData(activeTicketForm)).toString();
}

async function saveActiveJobFormInBackground(activeTicketForm) {
  if (!activeTicketForm) {
    throw new Error("Active job form was not found.");
  }

  populateActiveFormSummaryField(activeTicketForm);
  const response = await fetch(activeTicketForm.action, {
    method: "POST",
    headers: {Accept: "application/json"},
    body: new FormData(activeTicketForm),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Active job changes could not be saved.");
  }

  return payload;
}

function clearActiveFormSaveTimer(activeTicketForm) {
  const timerId = activeFormSaveTimers.get(activeTicketForm);
  if (timerId) {
    clearTimeout(timerId);
    activeFormSaveTimers.delete(activeTicketForm);
  }
}

function persistActiveJobFormSnapshot(activeTicketForm, queuedSnapshot) {
  const jobId = toSafeMapString(activeTicketForm.dataset.jobId);
  setActiveSaveStatus(jobId, "Saving changes...");
  saveActiveJobFormInBackground(activeTicketForm)
    .then((payload) => {
      if (payload && payload.job_date) {
        updateActiveJobDateWeekday(
          document.querySelector(`[data-active-job-card="${jobId}"]`),
          payload.job_date,
        );
      }

      const endJobForm = document.querySelector(`.end-job-form[data-job-id="${jobId}"]`);
      if (endJobForm) {
        syncEndJobClientFields(endJobForm);
      }

      const latestSnapshot = buildActiveJobFormSnapshot(activeTicketForm);
      if (latestSnapshot === queuedSnapshot) {
        lastSavedActiveFormSnapshots.set(activeTicketForm, latestSnapshot);
        setActiveSaveStatus(jobId, "Changes saved.");
        return;
      }

      queueActiveJobFormSave(activeTicketForm, true);
    })
    .catch((error) => {
      setActiveSaveStatus(jobId, error.message || "Active job changes could not be saved.", true);
    });
}

function queueActiveJobFormSave(activeTicketForm, immediate = false) {
  if (!activeTicketForm) {
    return;
  }

  const nextSnapshot = buildActiveJobFormSnapshot(activeTicketForm);
  if (nextSnapshot === lastSavedActiveFormSnapshots.get(activeTicketForm)) {
    return;
  }

  clearActiveFormSaveTimer(activeTicketForm);
  activeFormSaveTimers.set(
    activeTicketForm,
    setTimeout(() => {
      activeFormSaveTimers.delete(activeTicketForm);
      persistActiveJobFormSnapshot(activeTicketForm, nextSnapshot);
    }, immediate ? 0 : ACTIVE_FORM_SAVE_DELAY_MS),
  );
}

function syncActiveTimeFormJobDate(activeTimeForm) {
  if (!activeTimeForm) {
    return;
  }

  const hiddenJobDateInput = activeTimeForm.querySelector("[data-active-time-job-date]");
  if (!hiddenJobDateInput) {
    return;
  }

  const activeJobCard = activeTimeForm.closest ? activeTimeForm.closest("[data-active-job-card]") : null;
  const visibleJobDateInput = activeJobCard ? activeJobCard.querySelector("[data-active-job-date-input]") : null;
  if (visibleJobDateInput && visibleJobDateInput.value) {
    hiddenJobDateInput.value = visibleJobDateInput.value;
  }
}

function buildActiveTimeFormSnapshot(activeTimeForm) {
  if (!activeTimeForm) {
    return "";
  }

  syncActiveTimeFormJobDate(activeTimeForm);
  return new URLSearchParams(new FormData(activeTimeForm)).toString();
}

async function saveActiveTimeFormInBackground(activeTimeForm) {
  if (!activeTimeForm) {
    throw new Error("Active time form was not found.");
  }

  syncActiveTimeFormJobDate(activeTimeForm);
  const response = await fetch(activeTimeForm.action, {
    method: "POST",
    headers: {Accept: "application/json"},
    body: new FormData(activeTimeForm),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Active time could not be saved.");
  }

  return payload;
}

function updateActiveTimeDisplays(activeTimeForm, payload) {
  const jobId = toSafeMapString(activeTimeForm.dataset.jobId || payload.job_id);
  const activeJobCard = document.querySelector(`[data-active-job-card="${jobId}"]`);
  if (!activeJobCard) {
    return null;
  }

  const startTimeInput = activeJobCard.querySelector('[data-active-time-input][data-active-time-kind="start"]');
  const stopTimeInput = activeJobCard.querySelector('[data-active-time-input][data-active-time-kind="stop"]');
  const visibleJobDateInput = activeJobCard.querySelector("[data-active-job-date-input]");
  const hiddenJobDateInputs = activeJobCard.querySelectorAll("[data-active-time-job-date]");
  const payloadJobDate = toSafeMapString(payload.job_date).trim();

  if (payloadJobDate && visibleJobDateInput) {
    visibleJobDateInput.value = payloadJobDate;
  }
  for (const hiddenJobDateInput of hiddenJobDateInputs) {
    if (payloadJobDate) {
      hiddenJobDateInput.value = payloadJobDate;
    }
  }
  if (payloadJobDate) {
    updateActiveJobDateWeekday(activeJobCard, payloadJobDate);
  }
  if (startTimeInput && payload.rounded_start_time) {
    startTimeInput.value = payload.rounded_start_time;
  }
  if (stopTimeInput && payload.rounded_stop_time) {
    stopTimeInput.value = payload.rounded_stop_time;
    stopTimeInput.dataset.roundedStopOverridden = payload.rounded_stop_overridden ? "true" : "false";
    stopTimeInput.dataset.roundedStartUtc = toSafeMapString(payload.rounded_start_utc);
    stopTimeInput.dataset.initialRoundedStopUtc = toSafeMapString(payload.rounded_stop_utc);
    stopTimeInput.dataset.initialRoundedStopLocalTime = toSafeMapString(payload.rounded_stop_time);
  }
  if (payload.duration_label) {
    const durationDisplay = activeJobCard.querySelector("[data-duration-display]");
    if (durationDisplay) {
      durationDisplay.textContent = toSafeMapString(payload.duration_label);
    }
  } else {
    updateActiveDurationDisplay(activeJobCard);
  }

  return activeJobCard;
}

function markActiveTimeFormsSaved(activeJobCard) {
  if (!activeJobCard) {
    return;
  }

  const savedActiveTimeForms = activeJobCard.querySelectorAll("[data-active-time-form]");
  for (const savedActiveTimeForm of savedActiveTimeForms) {
    lastSavedActiveTimeSnapshots.set(savedActiveTimeForm, buildActiveTimeFormSnapshot(savedActiveTimeForm));
  }
}

function clearActiveTimeSaveTimer(activeTimeForm) {
  const timerId = activeTimeSaveTimers.get(activeTimeForm);
  if (timerId) {
    clearTimeout(timerId);
    activeTimeSaveTimers.delete(activeTimeForm);
  }
}

function persistActiveTimeFormSnapshot(activeTimeForm, queuedSnapshot) {
  const jobId = toSafeMapString(activeTimeForm.dataset.jobId);
  setActiveSaveStatus(jobId, "Saving changes...");
  saveActiveTimeFormInBackground(activeTimeForm)
    .then((payload) => {
      const currentSnapshot = buildActiveTimeFormSnapshot(activeTimeForm);
      if (currentSnapshot !== queuedSnapshot) {
        queueActiveTimeFormSave(activeTimeForm, true);
        return;
      }

      const activeJobCard = updateActiveTimeDisplays(activeTimeForm, payload);
      markActiveTimeFormsSaved(activeJobCard);
      setActiveSaveStatus(jobId, "Changes saved.");
    })
    .catch((error) => {
      setActiveSaveStatus(jobId, error.message || "Active time could not be saved.", true);
    });
}

function queueActiveTimeFormSave(activeTimeForm, immediate = false) {
  if (!activeTimeForm) {
    return;
  }

  const nextSnapshot = buildActiveTimeFormSnapshot(activeTimeForm);
  if (nextSnapshot === lastSavedActiveTimeSnapshots.get(activeTimeForm)) {
    return;
  }

  clearActiveTimeSaveTimer(activeTimeForm);
  activeTimeSaveTimers.set(
    activeTimeForm,
    setTimeout(() => {
      activeTimeSaveTimers.delete(activeTimeForm);
      persistActiveTimeFormSnapshot(activeTimeForm, nextSnapshot);
    }, immediate ? 0 : ACTIVE_TIME_SAVE_DELAY_MS),
  );
}

function adjustActiveTimeInput(activeTimeForm, deltaMinutes) {
  const timeInput = activeTimeForm.querySelector("[data-active-time-input]");
  if (!timeInput) {
    return;
  }

  const currentTotalMinutes = parseLocalTimeDisplay(timeInput.value);
  if (currentTotalMinutes === null) {
    return;
  }

  timeInput.value = formatLocalMinutes(currentTotalMinutes + deltaMinutes);
  if (timeInput.dataset.activeTimeKind === "stop") {
    timeInput.dataset.roundedStopOverridden = "true";
  }
  updateActiveDurationDisplay(activeTimeForm.closest("[data-active-job-card]"));
}

function setRecordingStatus(jobId, message, isError = false, isLoading = false) {
  const statusElement = findRecordingStatusElement(jobId);
  setInlineLoadingStatus(statusElement, message, {isError, isLoading});
}

function setRecordingProgressStatus(activeJobId, activeMessage) {
  const safeActiveJobId = toSafeMapString(activeJobId);
  if (activeAudioStopRequested && activeRecordingJobId === safeActiveJobId) {
    const stoppedMessage = activeAudioCompletionInProgress
      ? RECORDING_STATUS_CONVERTING
      : RECORDING_STATUS_SENDING;
    setRecordingStatus(safeActiveJobId, stoppedMessage, false, true);
    return;
  }

  setRecordingStatus(safeActiveJobId, activeMessage, false, true);
}

function setRecordingUi({
  jobId,
  isRecording = false,
  isUploading = false,
}) {
  const controls = findControlElements(jobId);
  if (!controls.recordButton) {
    return;
  }

  controls.recordButton.disabled = isUploading;
  controls.recordButton.classList.toggle("is-loading", isUploading);
  controls.recordButton.setAttribute("aria-busy", isUploading ? "true" : "false");
  controls.recordButton.setAttribute("aria-pressed", isRecording ? "true" : "false");
  if (controls.recordButtonLabel) {
    controls.recordButtonLabel.textContent = isRecording ? STOP_RECORDING_LABEL : RECORD_AUDIO_LABEL;
    controls.recordButtonLabel.dataset.state = isRecording ? "stop" : "record";
    controls.recordButton.setAttribute("aria-label", isRecording ? STOP_RECORDING_LABEL : RECORD_AUDIO_LABEL);
  }

  if (isUploading) {
    controls.recordButton.classList.remove("is-recording");
    return;
  }

  if (isRecording) {
    controls.recordButton.classList.add("is-recording");
    return;
  }

  controls.recordButton.classList.remove("is-recording");
}

function setAllRecordingControlsIdle() {
  for (const button of activeRecordButtons) {
    const jobId = button.dataset.jobId || "";
    setRecordingUi({jobId, isRecording: false});
  }
}

function clearRecordingState() {
  isUploadingRecording = false;
  isStartingRecording = false;
  if (activeAudioStream) {
    stopActiveStream();
  }

  activeAudioStream = null;
  activeRecorder = null;
  if (activeAudioSocket && activeAudioSocket.readyState === WebSocket.OPEN) {
    activeAudioSocket.close(1000, "Recording finished.");
  }
  activeAudioSocket = null;
  activeAudioStreamFinalResolve = null;
  activeAudioStreamFinalReject = null;
  activeAudioStreamReady = false;
  activeAudioStreamFailed = false;
  hasRecordedAudio = false;
  activeAudioStopRequested = false;
  const jobId = activeRecordingJobId;
  activeRecordingJobId = "";
  activeAudioCompletionInProgress = false;
  if (jobId) {
    setRecordingUi({jobId, isRecording: false, isUploading: false});
  }
}

async function finalizeRecordingForActiveJob(activeJobId) {
  const safeJobId = toSafeMapString(activeJobId);
  if (!safeJobId || activeAudioCompletionInProgress) {
    return;
  }

  activeAudioCompletionInProgress = true;
  try {
    if (activeAudioStreamFailed) {
      setRecordingStatus(safeJobId, "Recording stream failed. Press Record and try again.", true);
      return;
    }

    if (!activeAudioSocket || activeAudioSocket.readyState !== WebSocket.OPEN) {
      throw new Error("Audio transcription stream is not available.");
    }

    setRecordingUi({jobId: safeJobId, isUploading: true});
    await finishAudioTranscriptionStream(safeJobId);
    setRecordingStatus(safeJobId, RECORDING_STATUS_COMPLETE);
  } catch (error) {
    setRecordingStatus(safeJobId, error.message || "Recording stream could not finish.", true);
  } finally {
    clearRecordingState();
  }
}

function stopActiveStream() {
  if (!activeAudioStream) {
    return;
  }

  for (const track of activeAudioStream.getTracks()) {
    track.stop();
  }
}

async function searchAutotaskCompanies(queryText) {
  const response = await fetch(`/autotask/companies?query=${encodeURIComponent(queryText)}`, {
    headers: {Accept: "application/json"},
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Autotask company search failed.");
  }

  return Array.isArray(payload.companies) ? payload.companies : [];
}

function renderCompanyResults(companyInput, companies) {
  const parentForm = resolveFormForControl(companyInput);
  const {companyIdInput, resultsElement} = getCompanyPickerElements(companyInput);
  if (!companyIdInput || !resultsElement) {
    return;
  }

  resultsElement.replaceChildren();
  for (const companyOption of companies) {
    const optionButton = document.createElement("button");
    optionButton.type = "button";
    optionButton.className = "company-option-button";
    optionButton.textContent = companyOption.company_name || "Unnamed company";
    optionButton.addEventListener("click", () => {
      companyInput.value = companyOption.company_name || "";
      companyIdInput.value = companyOption.company_id || "";
      resultsElement.replaceChildren();
      setCompanyStatus(companyInput, "");
      if (parentForm && parentForm.classList.contains("active-ticket-form")) {
        const jobId = toSafeMapString(parentForm.dataset.jobId);
        const endJobForm = document.querySelector(
          `.end-job-form[data-job-id="${jobId}"]`,
        );
        if (endJobForm) {
          syncEndJobClientFields(endJobForm);
        }
        const ticketPicker = findActiveTicketPicker(jobId);
        if (ticketPicker) {
          loadActiveTicketOptions(ticketPicker, {saveActiveFormFirst: true})
            .then(() => {
              companyInput.readOnly = true;
              setCompanyStatus(companyInput, "");
            })
            .catch((error) => {
              setCompanyStatus(companyInput, error.message || "Open tickets could not be loaded.", true);
            });
          return;
        }
        queueActiveJobFormSave(parentForm, true);
      }
    });
    resultsElement.append(optionButton);
  }
}

function queueCompanySearch(companyInput) {
  const queryText = toSafeMapString(companyInput.value).trim();
  const {companyIdInput} = getCompanyPickerElements(companyInput);
  if (companyIdInput) {
    companyIdInput.value = "";
  }

  clearTimeout(companySearchTimers.get(companyInput));
  clearCompanyResults(companyInput);

  if (queryText.length < MIN_COMPANY_SEARCH_CHARACTERS) {
    setCompanyStatus(companyInput, "");
    return;
  }

  companySearchTimers.set(
    companyInput,
    setTimeout(async () => {
      try {
        setCompanyStatus(companyInput, "Searching Autotask...");
        const companies = await searchAutotaskCompanies(queryText);
        if (companies.length === 0) {
          setCompanyStatus(companyInput, "No matching Autotask companies found.");
          return;
        }

        setCompanyStatus(companyInput, "");
        renderCompanyResults(companyInput, companies);
      } catch (error) {
        setCompanyStatus(companyInput, error.message || "Autotask company search failed.", true);
      }
    }, COMPANY_SEARCH_DELAY_MS),
  );
}

function clearDescriptionTimer(jobId) {
  const timerId = descriptionSaveTimers.get(jobId);
  if (timerId) {
    clearTimeout(timerId);
    descriptionSaveTimers.delete(jobId);
  }
}

async function saveDescriptionText(jobId, descriptionText) {
  // descriptionText is the exact textarea value at the time autosave was
  // queued. It may intentionally include a trailing space while the user is
  // between words on a mobile keyboard.
  const response = await fetch(`/jobs/${jobId}/description/text`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({summary_notes: descriptionText}),
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Notes could not be saved.");
  }

  // The server trims persisted summary notes for clean storage and Autotask
  // payloads. Do not write that normalized value back into the focused mobile
  // textarea during manual autosave, because trimming a just-typed trailing
  // space makes the phone keyboard appear unable to type normal sentences.
  return payload;
}

async function requestAiCleanup(cleanupUrl, summaryText) {
  const response = await fetch(cleanupUrl, {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({summary_notes: summaryText}),
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload.detail || `request failed with HTTP ${response.status || "error"}.`);
  }

  return payload;
}

async function requestAiCleanupRevert(revertUrl) {
  const response = await fetch(revertUrl, {
    method: "POST",
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({}),
  });

  let payload = {};
  try {
    payload = await response.json();
  } catch (error) {
    payload = {};
  }

  if (!response.ok) {
    throw new Error(payload.detail || `request failed with HTTP ${response.status || "error"}.`);
  }

  return payload;
}

async function revertMobileSummaryCleanup(button, jobId, descriptionElement) {
  const revertUrl = button.dataset.revertUrl || "";
  if (!revertUrl) {
    return;
  }

  if (activeRecorder || isUploadingRecording || activeAudioCompletionInProgress || isStartingRecording) {
    setAiCleanupStatus(jobId, "Finish audio recording before reverting cleanup.", true);
    return;
  }

  clearDescriptionTimer(jobId);
  pendingDescriptionSaves.delete(jobId);
  setAiCleanupButtonLoading(button, true);
  setAiCleanupStatus(jobId, "Reverting cleanup...", false, true);
  try {
    const payload = await requestAiCleanupRevert(revertUrl);
    const restoredSummaryText = payload.summary_notes || payload.description_text || "";
    if (!restoredSummaryText.trim()) {
      throw new Error("Revert cleanup returned no summary text.");
    }

    descriptionElement.value = restoredSummaryText;
    lastSavedDescriptions.set(jobId, restoredSummaryText);
    setAiCleanupButtonMode(button, "cleanup");
    setAiCleanupStatus(jobId, "Cleanup reverted.");
  } catch (error) {
    setAiCleanupStatus(jobId, `Revert cleanup failed: ${error.message || "Summary could not be restored."}`, true);
  } finally {
    setAiCleanupButtonLoading(button, false);
  }
}

async function cleanupMobileSummary(button) {
  const jobId = toSafeMapString(button.dataset.jobId);
  const cleanupUrl = button.dataset.cleanupUrl || "";
  const descriptionElement = findDescriptionTextarea(jobId);
  if (!jobId || !cleanupUrl || !descriptionElement) {
    return;
  }

  if (button.dataset.cleanupMode === "revert") {
    await revertMobileSummaryCleanup(button, jobId, descriptionElement);
    return;
  }

  const currentSummaryText = descriptionElement.value || "";
  if (!currentSummaryText.trim()) {
    setAiCleanupStatus(jobId, "Add summary notes before AI cleanup.", true);
    return;
  }

  if (activeRecorder || isUploadingRecording || activeAudioCompletionInProgress || isStartingRecording) {
    setAiCleanupStatus(jobId, "Finish audio recording before AI cleanup.", true);
    return;
  }

  clearDescriptionTimer(jobId);
  pendingDescriptionSaves.delete(jobId);
  setAiCleanupButtonLoading(button, true);
  setAiCleanupStatus(jobId, "Cleaning up summary...", false, true);
  try {
    const payload = await requestAiCleanup(cleanupUrl, currentSummaryText);
    const cleanedSummaryText = payload.summary_notes || payload.description_text || "";
    if (!cleanedSummaryText.trim()) {
      throw new Error("AI cleanup returned no summary text.");
    }

    descriptionElement.value = cleanedSummaryText;
    setAiCleanupStatus(jobId, "Saving cleaned summary...", false, true);
    await saveDescriptionText(jobId, cleanedSummaryText);
    lastSavedDescriptions.set(jobId, cleanedSummaryText);
    setAiCleanupButtonMode(button, "revert");
    setAiCleanupStatus(jobId, "Summary cleaned up.");
  } catch (error) {
    setAiCleanupStatus(jobId, `AI cleanup failed: ${error.message || "AI cleanup could not finish."}`, true);
  } finally {
    setAiCleanupButtonLoading(button, false);
  }
}

function queueDescriptionSave(jobId, immediate = false) {
  const descriptionElement = findDescriptionTextarea(jobId);
  if (!descriptionElement) {
    return;
  }

  const nextValue = descriptionElement.value;
  const safeJobId = toSafeMapString(jobId);
  if (nextValue === lastSavedDescriptions.get(safeJobId)) {
    return;
  }

  clearDescriptionTimer(safeJobId);
  descriptionSaveTimers.set(
    safeJobId,
    setTimeout(() => {
      descriptionSaveTimers.delete(safeJobId);
      saveDescriptionText(safeJobId, nextValue)
        .then(() => {
          setRecordingStatus(safeJobId, "", false);
          const latestDescriptionElement = findDescriptionTextarea(safeJobId);
          // Only mark this queued value as current if the user has not typed a
          // newer value while the network request was in flight.
          if (!latestDescriptionElement || latestDescriptionElement.value === nextValue) {
            lastSavedDescriptions.set(safeJobId, nextValue || "");
          }
          pendingDescriptionSaves.delete(safeJobId);
        })
        .catch((error) => {
          setRecordingStatus(safeJobId, error.message, true);
          pendingDescriptionSaves.delete(safeJobId);
        });
    }, immediate ? 0 : DESCRIPTION_SAVE_DELAY_MS),
  );

  if (immediate) {
    pendingDescriptionSaves.delete(safeJobId);
    pendingDescriptionSaves.add(safeJobId);
  }
}

function websocketUrlForAudioStream(activeJobId) {
  const websocketProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${websocketProtocol}//${window.location.host}/jobs/${encodeURIComponent(activeJobId)}/description/audio/stream`;
}

function preferredRecorderMimeType() {
  const candidateMimeTypes = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "video/webm;codecs=opus",
    "video/webm",
    "audio/ogg;codecs=opus",
  ];

  if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) {
    return "";
  }

  for (const candidateMimeType of candidateMimeTypes) {
    if (MediaRecorder.isTypeSupported(candidateMimeType)) {
      return candidateMimeType;
    }
  }

  return "";
}

function updateDescriptionFromTranscription(activeJobId, payload, shouldMarkSaved) {
  const nextDescriptionText = payload.summary_notes || payload.description_text || "";
  if (!nextDescriptionText) {
    return;
  }

  const safeActiveJobId = toSafeMapString(activeJobId);
  if (shouldMarkSaved) {
    // A final audio transcript is the authoritative replacement text for the
    // mobile summary box. Cancel any queued manual autosave so stale typed text
    // cannot fire after the transcript has been pasted into the field.
    clearDescriptionTimer(safeActiveJobId);
    pendingDescriptionSaves.delete(safeActiveJobId);
  }

  const descriptionElement = findDescriptionTextarea(activeJobId);
  if (descriptionElement) {
    descriptionElement.value = nextDescriptionText;
  }

  if (shouldMarkSaved) {
    lastSavedDescriptions.set(safeActiveJobId, nextDescriptionText);
  }
}

function rejectActiveAudioStream(errorMessage) {
  activeAudioStreamFailed = true;
  if (activeAudioStreamFinalReject) {
    activeAudioStreamFinalReject(new Error(errorMessage));
    activeAudioStreamFinalReject = null;
    activeAudioStreamFinalResolve = null;
  }
}

function handleAudioStreamMessage(activeJobId, rawMessage, readyHandlers) {
  let payload = null;
  try {
    payload = JSON.parse(rawMessage);
  } catch (error) {
    rejectActiveAudioStream("Audio stream returned an invalid server message.");
    if (readyHandlers && readyHandlers.reject) {
      readyHandlers.reject(new Error("Audio stream returned an invalid server message."));
    }
    return;
  }

  if (payload.type === "ready") {
    activeAudioStreamReady = true;
    setRecordingStatus(activeJobId, "Streaming audio to server...", false, true);
    if (readyHandlers && readyHandlers.resolve) {
      readyHandlers.resolve(payload);
    }
    return;
  }

  if (payload.type === "chunk_received") {
    setRecordingProgressStatus(activeJobId, RECORDING_STATUS_RECORDING);
    return;
  }

  if (payload.type === "transcription_started") {
    if (payload.phase === "final") {
      setRecordingStatus(activeJobId, RECORDING_STATUS_CONVERTING, false, true);
      return;
    }
    setRecordingStatus(activeJobId, "Converting streamed audio...", false, true);
    return;
  }

  if (payload.type === "partial_pending") {
    setRecordingStatus(activeJobId, payload.detail || "Collecting enough audio to transcribe...", false, true);
    return;
  }

  if (payload.type === "partial") {
    // Keep streaming transcription progress visible without changing the
    // summary textarea until the server returns the final transcript.
    setRecordingProgressStatus(activeJobId, "Transcribing audio...");
    return;
  }

  if (payload.type === "final") {
    updateDescriptionFromTranscription(activeJobId, payload, true);
    if (activeAudioStreamFinalResolve) {
      activeAudioStreamFinalResolve(payload);
      activeAudioStreamFinalResolve = null;
      activeAudioStreamFinalReject = null;
    }
    return;
  }

  if (payload.type === "error") {
    const errorMessage = payload.detail || "Recording could not be transcribed.";
    rejectActiveAudioStream(errorMessage);
    if (activeRecorder && activeRecordingJobId === activeJobId && activeRecorder.state !== "inactive") {
      activeRecorder.stop();
    }
    if (readyHandlers && readyHandlers.reject) {
      readyHandlers.reject(new Error(errorMessage));
    }
  }
}

async function openAudioTranscriptionStream(activeJobId, contentType) {
  return new Promise((resolve, reject) => {
    const audioSocket = new WebSocket(websocketUrlForAudioStream(activeJobId));
    let readySettled = false;
    const readyTimeout = window.setTimeout(() => {
      if (!readySettled) {
        readySettled = true;
        reject(new Error("Audio stream did not become ready."));
        audioSocket.close();
      }
    }, 10000);

    activeAudioSocket = audioSocket;
    activeAudioStreamReady = false;
    activeAudioStreamFailed = false;

    const readyHandlers = {
      resolve: (payload) => {
        if (readySettled) {
          return;
        }
        readySettled = true;
        window.clearTimeout(readyTimeout);
        resolve(payload);
      },
      reject: (error) => {
        if (readySettled) {
          return;
        }
        readySettled = true;
        window.clearTimeout(readyTimeout);
        reject(error);
      },
    };

    audioSocket.addEventListener("open", () => {
      audioSocket.send(JSON.stringify({
        type: "start",
        csrf_token: csrfToken,
        content_type: contentType || "audio/webm",
        filename: "recording.webm",
      }));
    });

    audioSocket.addEventListener("message", (event) => {
      handleAudioStreamMessage(activeJobId, event.data, readyHandlers);
    });

    audioSocket.addEventListener("error", () => {
      const error = new Error("Audio stream connection failed.");
      readyHandlers.reject(error);
      rejectActiveAudioStream(error.message);
    });

    audioSocket.addEventListener("close", () => {
      if (!readySettled) {
        readyHandlers.reject(new Error("Audio stream closed before it was ready."));
        return;
      }

      if (activeAudioStreamFinalReject && !activeAudioStreamFailed) {
        activeAudioStreamFinalReject(new Error("Audio stream closed before transcription finished."));
        activeAudioStreamFinalResolve = null;
        activeAudioStreamFinalReject = null;
      }

      if (activeRecorder && activeRecordingJobId === activeJobId && activeRecorder.state !== "inactive") {
        activeAudioStreamFailed = true;
        activeRecorder.stop();
      }
    });
  });
}

async function finishAudioTranscriptionStream(activeJobId) {
  if (!activeAudioSocket || activeAudioSocket.readyState !== WebSocket.OPEN || activeAudioStreamFailed) {
    throw new Error("Audio transcription stream is not available.");
  }

  return new Promise((resolve, reject) => {
    activeAudioStreamFinalResolve = resolve;
    activeAudioStreamFinalReject = reject;
    activeAudioSocket.send(JSON.stringify({type: "finish"}));
    setRecordingStatus(activeJobId, RECORDING_STATUS_CONVERTING, false, true);
  });
}

function streamAudioChunk(activeJobId, audioChunk) {
  if (!activeAudioSocket || activeAudioSocket.readyState !== WebSocket.OPEN || !activeAudioStreamReady) {
    throw new Error("Audio stream is not ready.");
  }

  if (activeAudioSocket.bufferedAmount > MAX_SOCKET_BUFFERED_BYTES) {
    throw new Error("Audio stream is backed up. Check the connection and try again.");
  }

  activeAudioSocket.send(audioChunk);
  hasRecordedAudio = true;
  setRecordingProgressStatus(activeJobId, RECORDING_STATUS_RECORDING);
}

function createTicketOptionSpan(className, textContent) {
  const spanElement = document.createElement("span");
  spanElement.className = className;
  spanElement.textContent = textContent;
  return spanElement;
}

function renderTicketOptionButton(optionButton, ticketOption) {
  const ticketNumber = ticketOption.ticket_number || "No ticket number";
  const ticketTitle = ticketOption.title || "Untitled ticket";
  const ticketStatus = ticketOption.status_label || "Unknown status";
  const companyName = ticketOption.company_name || "Unknown company";
  const locationLabel = ticketOption.work_location_label || "Not specified";
  const locationClass = ticketOption.work_location_class || "ticket-location-unknown";
  const cardHeader = document.createElement("span");
  cardHeader.className = "ticket-option-card-header";
  cardHeader.append(
    createTicketOptionSpan("ticket-option-number", ticketNumber),
    createTicketOptionSpan("ticket-location-badge", locationLabel),
  );
  optionButton.className = `ticket-option-button ${locationClass}`;
  optionButton.replaceChildren(
    cardHeader,
    createTicketOptionSpan("ticket-option-title", ticketTitle),
    createTicketOptionSpan("ticket-option-meta", `${ticketStatus} | ${companyName}`),
  );
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

function setActiveTicketPickerClickable(ticketPicker, isClickable) {
  if (!ticketPicker) {
    return;
  }

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

function clearServiceCallPanel(panel) {
  const resultsElement = panel.querySelector("[data-service-call-results]");
  const errorElement = panel.querySelector("[data-service-call-error]");
  const emptyElement = panel.querySelector("[data-service-call-empty]");
  if (resultsElement) {
    resultsElement.replaceChildren();
  }
  if (errorElement) {
    errorElement.textContent = "";
    errorElement.classList.add("is-hidden");
  }
  if (emptyElement) {
    emptyElement.classList.add("is-hidden");
  }
}

function setServiceCallPanelLoading(panel, isLoading) {
  const loadingElement = panel.querySelector("[data-service-call-loading]");
  if (loadingElement) {
    loadingElement.classList.toggle("is-hidden", !isLoading);
  }
  panel.querySelectorAll("[data-service-call-date-control]").forEach((controlElement) => {
    controlElement.disabled = isLoading;
  });
}

function setServiceCallPanelError(panel, message) {
  const errorElement = panel.querySelector("[data-service-call-error]");
  if (errorElement) {
    errorElement.textContent = message || "Service calls could not be loaded.";
    errorElement.classList.remove("is-hidden");
  }
}

function setServiceCallDateState(panel, payload) {
  const dateButton = panel.querySelector("[data-service-call-date-button]");
  const dateInput = panel.querySelector("[data-service-call-date-input]");
  const previousButton = panel.querySelector("[data-service-call-date-previous]");
  const nextButton = panel.querySelector("[data-service-call-date-next]");
  const emptyElement = panel.querySelector("[data-service-call-empty]");
  const selectedDate = toSafeMapString(payload.selected_date).trim();
  const dateLabel = toSafeMapString(payload.date_label).trim() || "Choose date";

  panel.dataset.serviceCallSelectedDate = selectedDate;
  if (dateButton) {
    dateButton.textContent = dateLabel;
  }
  if (dateInput) {
    dateInput.value = selectedDate;
  }
  if (previousButton) {
    previousButton.dataset.serviceCallTargetDate = toSafeMapString(payload.previous_date).trim();
  }
  if (nextButton) {
    nextButton.dataset.serviceCallTargetDate = toSafeMapString(payload.next_date).trim();
  }
  if (emptyElement) {
    emptyElement.textContent = payload.empty_message || "No service calls are scheduled for this date.";
  }
}

function openServiceCallCalendar(panel) {
  const dateInput = panel.querySelector("[data-service-call-date-input]");
  if (!dateInput || dateInput.disabled) {
    return;
  }

  if (typeof dateInput.showPicker === "function") {
    dateInput.showPicker();
    return;
  }

  dateInput.focus();
  dateInput.click();
}

function serviceCallPanelUrl(panel, selectedDate) {
  const serviceCallUrl = panel.dataset.serviceCallUrl || "";
  if (!serviceCallUrl) {
    return "";
  }

  const lookupUrl = new URL(serviceCallUrl, window.location.origin);
  const safeSelectedDate = toSafeMapString(selectedDate).trim();
  if (safeSelectedDate) {
    lookupUrl.searchParams.set("date", safeSelectedDate);
  }
  return lookupUrl.toString();
}

function createServiceCallStartForm(serviceCallOption, selectedDate) {
  const serviceCallForm = document.createElement("form");
  serviceCallForm.method = "post";
  serviceCallForm.action = "/jobs/start/service-call";
  serviceCallForm.className = "service-call-start-form";
  serviceCallForm.dataset.pageLoadingForm = "";
  serviceCallForm.dataset.loadingMessage = "Starting work and updating Autotask ticket status...";

  const csrfInput = document.createElement("input");
  csrfInput.type = "hidden";
  csrfInput.name = "csrf_token";
  csrfInput.value = csrfToken;

  const serviceCallTicketInput = document.createElement("input");
  serviceCallTicketInput.type = "hidden";
  serviceCallTicketInput.name = "service_call_ticket_id";
  serviceCallTicketInput.value = toSafeMapString(serviceCallOption.service_call_ticket_id);

  const serviceCallDateInput = document.createElement("input");
  serviceCallDateInput.type = "hidden";
  serviceCallDateInput.name = "service_call_date";
  serviceCallDateInput.value = toSafeMapString(selectedDate);

  const optionButton = document.createElement("button");
  optionButton.type = "submit";
  optionButton.className = `service-call-option-button ${serviceCallOption.work_location_class || "service-call-location-unknown"}`;

  const cardHeader = document.createElement("span");
  cardHeader.className = "service-call-card-header";

  const clientName = document.createElement("span");
  clientName.className = "service-call-client";
  clientName.textContent = serviceCallOption.client_name || "Unknown client";

  const workLocationBadge = document.createElement("span");
  workLocationBadge.className = "service-call-location-badge";
  workLocationBadge.textContent = serviceCallOption.work_location_label || "Unknown";

  const ticketTitle = document.createElement("span");
  ticketTitle.className = "service-call-ticket";
  ticketTitle.textContent = serviceCallOption.ticket_title || "Untitled ticket";

  const scheduledTimeRange = toSafeMapString(serviceCallOption.scheduled_time_range).trim();
  const timeRange = document.createElement("span");
  timeRange.className = "service-call-time-range";
  timeRange.textContent = scheduledTimeRange;

  cardHeader.append(clientName, workLocationBadge);
  optionButton.append(cardHeader);
  if (scheduledTimeRange) {
    optionButton.append(timeRange);
  }
  optionButton.append(ticketTitle);
  serviceCallForm.append(csrfInput, serviceCallTicketInput, serviceCallDateInput, optionButton);
  return serviceCallForm;
}

async function loadServiceCallPanel(panel, selectedDate = "") {
  const serviceCallUrl = serviceCallPanelUrl(panel, selectedDate);
  const resultsElement = panel.querySelector("[data-service-call-results]");
  const emptyElement = panel.querySelector("[data-service-call-empty]");
  if (!serviceCallUrl || !resultsElement) {
    return;
  }

  clearServiceCallPanel(panel);
  setServiceCallPanelLoading(panel, true);
  try {
    const response = await fetch(serviceCallUrl, {headers: {Accept: "application/json"}});
    const payload = await response.json();
    if (payload && payload.selected_date) {
      setServiceCallDateState(panel, payload);
    }
    if (!response.ok) {
      throw new Error(payload.detail || "Service calls could not be loaded.");
    }

    const serviceCallOptions = Array.isArray(payload.service_calls) ? payload.service_calls : [];
    if (serviceCallOptions.length === 0) {
      if (emptyElement) {
        emptyElement.classList.remove("is-hidden");
      }
      return;
    }

    for (const serviceCallOption of serviceCallOptions) {
      resultsElement.append(createServiceCallStartForm(serviceCallOption, payload.selected_date));
    }
  } catch (error) {
    setServiceCallPanelError(panel, error.message || "Service calls could not be loaded.");
  } finally {
    setServiceCallPanelLoading(panel, false);
  }
}

function initializeServiceCallDateControls(panel) {
  const previousButton = panel.querySelector("[data-service-call-date-previous]");
  const nextButton = panel.querySelector("[data-service-call-date-next]");
  const dateButton = panel.querySelector("[data-service-call-date-button]");
  const dateInput = panel.querySelector("[data-service-call-date-input]");

  if (previousButton) {
    previousButton.addEventListener("click", () => {
      const targetDate = previousButton.dataset.serviceCallTargetDate || "";
      if (targetDate) {
        loadServiceCallPanel(panel, targetDate);
      }
    });
  }

  if (nextButton) {
    nextButton.addEventListener("click", () => {
      const targetDate = nextButton.dataset.serviceCallTargetDate || "";
      if (targetDate) {
        loadServiceCallPanel(panel, targetDate);
      }
    });
  }

  if (dateButton) {
    dateButton.addEventListener("click", () => {
      openServiceCallCalendar(panel);
    });
  }

  if (dateInput) {
    dateInput.addEventListener("change", () => {
      if (dateInput.value) {
        loadServiceCallPanel(panel, dateInput.value);
      }
    });
  }
}

function updateActiveTicketDisplay(jobId, selectedTicket) {
  const activeJobCard = document.querySelector(`[data-active-job-card="${toSafeMapString(jobId)}"]`);
  if (!activeJobCard) {
    return;
  }

  const ticketNumber = toSafeMapString(selectedTicket.ticket_number).trim().toUpperCase();
  const ticketTitle = toSafeMapString(selectedTicket.ticket_title || selectedTicket.title).trim();
  const ticketDescription = toSafeMapString(selectedTicket.ticket_description || selectedTicket.description).trim();
  const ticketDescriptionDisplayText = ticketDescription || "No description exists for this ticket.";
  const ticketNumberCard = activeJobCard.querySelector("[data-active-ticket-number-card]");
  const ticketNumberDisplay = activeJobCard.querySelector("[data-active-ticket-number-display]");
  const ticketTitleCard = activeJobCard.querySelector("[data-active-ticket-title-card]");
  const ticketTitleDisplay = activeJobCard.querySelector("[data-active-ticket-title-display]");
  const ticketDescriptionCard = activeJobCard.querySelector("[data-active-ticket-description-card]");
  const ticketDescriptionDisplay = activeJobCard.querySelector("[data-active-ticket-description-display]");
  const ticketStatusInput = activeJobCard.querySelector("[data-active-ticket-status-input]");
  const ticketNotesButton = activeJobCard.querySelector("[data-ticket-notes-button]");

  if (ticketNumberCard && ticketNumber) {
    ticketNumberCard.classList.remove("is-hidden");
  }
  if (ticketNumberDisplay) {
    ticketNumberDisplay.textContent = ticketNumber;
  }

  if (ticketTitleCard && ticketTitle) {
    ticketTitleCard.classList.remove("is-hidden");
  }
  if (ticketTitleDisplay) {
    ticketTitleDisplay.textContent = ticketTitle;
  }

  if (ticketDescriptionCard) {
    ticketDescriptionCard.classList.toggle("is-hidden", !ticketNumber);
  }
  if (ticketDescriptionDisplay) {
    ticketDescriptionDisplay.textContent = ticketDescriptionDisplayText;
  }
  if (ticketStatusInput && selectedTicket.ticket_status) {
    ticketStatusInput.value = selectedTicket.ticket_status;
  }
  if (ticketNotesButton) {
    ticketNotesButton.dataset.ticketNotesTicketNumber = ticketNumber;
    if (window.JobLoggerTicketNotes) {
      window.JobLoggerTicketNotes.refreshButton(ticketNotesButton);
    }
  }
  if (ticketNumber) {
    lockActiveClientInputForSelectedTicket(jobId);
  }
}

function lockActiveClientInputForSelectedTicket(jobId) {
  const activeTicketForm = findActiveTicketForm(jobId);
  if (!activeTicketForm) {
    return;
  }

  const companyResults = activeTicketForm.querySelector("[data-company-results]");
  const companyStatus = activeTicketForm.querySelector("[data-company-status]");
  if (companyResults) {
    companyResults.replaceChildren();
  }
  if (companyStatus) {
    companyStatus.textContent = "";
    companyStatus.classList.remove("error-text");
  }

  const formClientInput = activeTicketForm.querySelector("[data-active-client-source]");
  const formId = toSafeMapString(activeTicketForm.id);
  const formLinkedClientInput = formId
    ? document.querySelector(`.active-client-name-source[form="${formId}"]`)
    : null;
  const clientInputs = new Set([formClientInput, formLinkedClientInput].filter(Boolean));
  for (const clientInput of clientInputs) {
    if (clientInput.tagName === "INPUT" && clientInput.type !== "hidden") {
      clientInput.readOnly = true;
      clientInput.setAttribute("aria-readonly", "true");
      clientInput.classList.add("is-locked-client-input");
    }
  }
}

async function loadActiveTicketOptions(ticketPicker, options = {}) {
  if (activeTicketLookupRequests.has(ticketPicker) || activeTicketLookupLoaded.has(ticketPicker)) {
    return;
  }

  const saveActiveFormFirst = Boolean(options.saveActiveFormFirst);
  const lookupUrl = ticketPicker.dataset.ticketLookupUrl || "";
  const ticketSelectUrl = ticketPicker.dataset.ticketSelectUrl || "";
  const jobId = toSafeMapString(ticketPicker.dataset.ticketFormJobId);
  const activeTicketForm = findActiveTicketForm(jobId);
  const statusElement = ticketPicker.querySelector("[data-active-ticket-lookup-status]");
  const resultsElement = ticketPicker.querySelector("[data-active-ticket-lookup-results]");
  if (!lookupUrl || !statusElement || !resultsElement) {
    return;
  }

  const clientFields = readActiveJobClientFields(jobId);
  if (!clientFields.clientName.trim()) {
    statusElement.classList.remove("error-text");
    setTicketLookupStatus(statusElement, "Choose a client, then click this box to load open tickets.");
    resultsElement.replaceChildren();
    setActiveTicketPickerClickable(ticketPicker, true);
    return;
  }

  activeTicketLookupRequests.add(ticketPicker);
  ticketPicker.classList.add("is-loading");
  ticketPicker.setAttribute("aria-busy", "true");
  setActiveTicketPickerClickable(ticketPicker, false);
  setTicketLookupStatus(
    statusElement,
    saveActiveFormFirst ? "Saving client before ticket lookup..." : "Loading open tickets...",
    {isLoading: true},
  );
  resultsElement.replaceChildren();

  try {
    if (saveActiveFormFirst) {
      await saveActiveJobFormInBackground(activeTicketForm);
      const endJobForm = document.querySelector(`.end-job-form[data-job-id="${jobId}"]`);
      if (endJobForm) {
        syncEndJobClientFields(endJobForm);
      }
    }

    setTicketLookupStatus(statusElement, "Loading open tickets...", {isLoading: true});
    const response = await fetch(lookupUrl, {headers: {Accept: "application/json"}});
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Autotask ticket lookup failed.");
    }

    const ticketOptions = Array.isArray(payload.tickets) ? payload.tickets : [];
    if (ticketOptions.length === 0) {
      setTicketLookupStatus(statusElement, "No open tickets found. Click this box to try again.");
      setActiveTicketPickerClickable(ticketPicker, true);
      return;
    }

    activeTicketLookupLoaded.add(ticketPicker);
    setTicketLookupStatus(statusElement, `${ticketOptions.length} open ticket(s) found.`);
    for (const ticketOption of ticketOptions) {
      const optionButton = document.createElement("button");
      optionButton.type = "button";
      renderTicketOptionButton(optionButton, ticketOption);
      optionButton.addEventListener("click", async () => {
        const activeTicketForm = findActiveTicketForm(jobId);
        const ticketInput = activeTicketForm ? activeTicketForm.querySelector(".active-ticket-number") : null;
        const ticketTitleInput = activeTicketForm ? activeTicketForm.querySelector(".active-ticket-title") : null;
        const ticketDescriptionInput = activeTicketForm ? activeTicketForm.querySelector(".active-ticket-description") : null;
        if (!ticketInput) {
          return;
        }

        optionButton.disabled = true;
        ticketPicker.classList.add("is-loading");
        ticketPicker.setAttribute("aria-busy", "true");
        showMobilePageLoading("Updating Autotask ticket status...");
        setTicketLookupStatus(statusElement, "Updating Autotask ticket status...", {isLoading: true});
        resultsElement.replaceChildren();
        try {
          if (ticketSelectUrl) {
            const selectedTicket = await persistActiveSelectedTicket(ticketSelectUrl, ticketOption);
            ticketInput.value = toSafeMapString(selectedTicket.ticket_number).trim().toUpperCase();
            if (ticketTitleInput) {
              ticketTitleInput.value = toSafeMapString(selectedTicket.ticket_title).trim();
            }
            if (ticketDescriptionInput) {
              ticketDescriptionInput.value = toSafeMapString(selectedTicket.ticket_description).trim();
            }
            updateActiveTicketDisplay(jobId, selectedTicket);
            ticketPicker.hidden = true;
            ticketPicker.classList.add("is-hidden");
            hideMobilePageLoading();
            return;
          }

          ticketInput.value = toSafeMapString(ticketOption.ticket_number).trim().toUpperCase();
          if (ticketTitleInput) {
            ticketTitleInput.value = toSafeMapString(ticketOption.title).trim();
          }
          if (ticketDescriptionInput) {
            ticketDescriptionInput.value = toSafeMapString(ticketOption.description).trim();
          }
          updateActiveTicketDisplay(jobId, ticketOption);
          submitFormWithCurrentFields(activeTicketForm);
        } catch (error) {
          activeTicketLookupLoaded.delete(ticketPicker);
          hideMobilePageLoading();
          ticketPicker.classList.remove("is-loading");
          ticketPicker.removeAttribute("aria-busy");
          ticketPicker.hidden = false;
          ticketPicker.classList.remove("is-hidden");
          optionButton.disabled = false;
          setTicketLookupStatus(statusElement, error.message || "Selected ticket could not be saved.", {isError: true});
          setActiveTicketPickerClickable(ticketPicker, true);
        }
      });
      resultsElement.append(optionButton);
    }
  } catch (error) {
    setTicketLookupStatus(statusElement, error.message || "Autotask ticket lookup failed.", {isError: true});
    setActiveTicketPickerClickable(ticketPicker, true);
  } finally {
    activeTicketLookupRequests.delete(ticketPicker);
    ticketPicker.classList.remove("is-loading");
    ticketPicker.removeAttribute("aria-busy");
  }
}

async function persistActiveSelectedTicket(ticketSelectUrl, ticketOption) {
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

async function startRecording(activeJobId) {
  if (!activeJobId) {
    setRecordingStatus("", "No active job is available.", true);
    return;
  }

  if (activeRecorder && activeRecordingJobId !== activeJobId) {
    setRecordingStatus(activeJobId, "Another job is currently recording. Finish that session first.", true);
    return;
  }

  if (activeRecorder) {
    await stopRecording(activeJobId);
    return;
  }

  if (!navigator.mediaDevices || !window.MediaRecorder) {
    setRecordingStatus(activeJobId, "This browser does not support secure audio recording.", true);
    return;
  }

  setRecordingStatus(activeJobId, "Preparing recorder...", false, true);
  hasRecordedAudio = false;
  isUploadingRecording = false;
  activeAudioCompletionInProgress = false;
  activeAudioStopRequested = false;
  activeAudioStream = await navigator.mediaDevices.getUserMedia({audio: true});
  const selectedMimeType = preferredRecorderMimeType();
  activeRecorder = selectedMimeType
    ? new MediaRecorder(activeAudioStream, {mimeType: selectedMimeType})
    : new MediaRecorder(activeAudioStream);
  activeRecordingJobId = activeJobId;
  setRecordingUi({jobId: activeJobId, isRecording: true});
  await openAudioTranscriptionStream(activeJobId, activeRecorder.mimeType || selectedMimeType || "audio/webm");

  activeRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      try {
        streamAudioChunk(activeJobId, event.data);
      } catch (error) {
        setRecordingStatus(activeJobId, error.message || "Audio chunk could not be streamed.", true);
        activeAudioStreamFailed = true;
        if (activeRecorder && activeRecorder.state !== "inactive") {
          activeRecorder.stop();
        }
      }
    }
  });

  activeRecorder.addEventListener("start", () => {
    setRecordingUi({jobId: activeJobId, isRecording: true});
  });

  activeRecorder.addEventListener("stop", async () => {
    const jobId = activeRecordingJobId;
    try {
      if (!jobId) {
        return;
      }

      stopActiveStream();
      if (activeAudioStreamFailed) {
        setRecordingStatus(jobId, "Recording stream failed. Press Record and try again.", true);
        clearRecordingState();
        return;
      }

      if (!hasRecordedAudio) {
        setRecordingStatus(jobId, "No audio was recorded. Press Record and try again.");
        clearRecordingState();
        return;
      }

      await finalizeRecordingForActiveJob(jobId);
    } catch (error) {
      setRecordingStatus(jobId, error.message, true);
      clearRecordingState();
    }
  });

  activeRecorder.start(RECORDING_CHUNK_INTERVAL_MS);
  setRecordingStatus(activeJobId, "Streaming audio to server...", false, true);
}

async function stopRecording(activeJobId) {
  if (!activeRecorder || isUploadingRecording) {
    return;
  }

  isUploadingRecording = true;

  if (activeRecordingJobId !== activeJobId) {
    setRecordingStatus(activeJobId, "That job is not currently recording.");
    isUploadingRecording = false;
    return;
  }

  if (activeRecorder.state === "inactive") {
    activeAudioStopRequested = true;
    setRecordingUi({jobId: activeJobId, isUploading: true});
    setRecordingStatus(activeJobId, RECORDING_STATUS_SENDING, false, true);
    if (!hasRecordedAudio) {
      setRecordingStatus(activeJobId, "No audio was recorded. Press Record and try again.");
      clearRecordingState();
      return;
    }

    await finalizeRecordingForActiveJob(activeJobId);
    return;
  }

  // Stopping capture finalizes the WebSocket stream. The button returns to its
  // idle appearance while the status line tracks server-side transcription.
  isUploadingRecording = true;
  activeAudioStopRequested = true;
  setRecordingUi({jobId: activeJobId, isUploading: true});
  setRecordingStatus(activeJobId, RECORDING_STATUS_SENDING, false, true);
  activeRecorder.stop();
}

for (const descriptionTextarea of descriptionTextareas) {
  const jobId = toSafeMapString(descriptionTextarea.dataset.jobId);
  lastSavedDescriptions.set(jobId, descriptionTextarea.value);

  descriptionTextarea.addEventListener("input", () => {
    queueDescriptionSave(jobId);
  });

  descriptionTextarea.addEventListener("blur", () => {
    queueDescriptionSave(jobId, true);
  });
}

for (const recordButton of activeRecordButtons) {
  const jobId = toSafeMapString(recordButton.dataset.jobId);
  recordButton.addEventListener("click", async () => {
    if (isUploadingRecording || isStartingRecording) {
      return;
    }

    if (activeRecorder) {
      if (activeRecordingJobId === jobId) {
        await stopRecording(jobId);
        return;
      }

      setRecordingStatus(jobId, "Stop the current recording before switching jobs.", true);
      return;
    }

    setRecordingUi({jobId, isRecording: true});
    setRecordingStatus(jobId, "Preparing recorder...", false, true);
    isStartingRecording = true;
    try {
      await startRecording(jobId);
    } catch (error) {
      setRecordingStatus(jobId, error.message || "Recording could not start.", true);
      clearRecordingState();
      isStartingRecording = false;
      return;
    }

    isStartingRecording = false;
    if (!activeRecorder || activeRecordingJobId !== jobId) {
      setRecordingUi({jobId, isRecording: false});
    }
  });
}

for (const workLocationInput of workLocationInputs) {
  workLocationInput.addEventListener("change", () => {
    if (!workLocationInput.checked) {
      return;
    }

    const activeTicketForm = document.getElementById(workLocationInput.getAttribute("form") || "");
    queueActiveJobFormSave(activeTicketForm, true);
  });
}

for (const entryTypeInput of activeEntryTypeInputs) {
  entryTypeInput.addEventListener("change", () => {
    if (!entryTypeInput.checked) {
      return;
    }

    const activeJobCard = entryTypeInput.closest("[data-active-job-card]");
    syncActiveEntryMode(activeJobCard);
    const activeTicketForm = document.getElementById(entryTypeInput.getAttribute("form") || "");
    queueActiveJobFormSave(activeTicketForm, true);
  });
}

for (const noteTitleInput of activeNoteTitleInputs) {
  noteTitleInput.addEventListener("input", () => {
    const activeTicketForm = document.getElementById(noteTitleInput.getAttribute("form") || "");
    queueActiveJobFormSave(activeTicketForm);
  });
  noteTitleInput.addEventListener("blur", () => {
    const activeTicketForm = document.getElementById(noteTitleInput.getAttribute("form") || "");
    queueActiveJobFormSave(activeTicketForm, true);
  });
}

for (const appendResolutionInput of activeAppendResolutionInputs) {
  appendResolutionInput.addEventListener("change", () => {
    const activeTicketForm = document.getElementById(appendResolutionInput.getAttribute("form") || "");
    queueActiveJobFormSave(activeTicketForm, true);
  });
}

for (const activeTimeForm of activeTimeForms) {
  lastSavedActiveTimeSnapshots.set(activeTimeForm, buildActiveTimeFormSnapshot(activeTimeForm));

  activeTimeForm.addEventListener("submit", (event) => {
    event.preventDefault();
    queueActiveTimeFormSave(activeTimeForm, true);
  });

  const timeInput = activeTimeForm.querySelector("[data-active-time-input]");
  if (timeInput) {
    timeInput.addEventListener("input", () => {
      if (timeInput.dataset.activeTimeKind === "stop") {
        timeInput.dataset.roundedStopOverridden = "true";
      }
      updateActiveDurationDisplay(activeTimeForm.closest("[data-active-job-card]"));
      queueActiveTimeFormSave(activeTimeForm);
    });
    timeInput.addEventListener("blur", () => {
      updateActiveDurationDisplay(activeTimeForm.closest("[data-active-job-card]"));
      queueActiveTimeFormSave(activeTimeForm, true);
    });
  }

  const timeStepButtons = activeTimeForm.querySelectorAll("[data-active-time-delta]");
  for (const timeStepButton of timeStepButtons) {
    timeStepButton.addEventListener("click", (event) => {
      event.preventDefault();
      const deltaMinutes = Number(timeStepButton.dataset.activeTimeDelta || 0);
      if (!Number.isFinite(deltaMinutes)) {
        return;
      }

      adjustActiveTimeInput(activeTimeForm, deltaMinutes);
      queueActiveTimeFormSave(activeTimeForm, true);
    });
  }
}

for (const activeTicketStatusInput of activeTicketStatusInputs) {
  activeTicketStatusInput.addEventListener("change", () => {
    const activeTicketForm = document.getElementById(activeTicketStatusInput.getAttribute("form") || "");
    queueActiveJobFormSave(activeTicketForm, true);
  });
}

for (const activeJobDateInput of activeJobDateInputs) {
  activeJobDateInput.addEventListener("change", () => {
    const activeJobCard = activeJobDateInput.closest ? activeJobDateInput.closest("[data-active-job-card]") : null;
    updateActiveJobDateWeekday(activeJobCard, activeJobDateInput.value);
    const activeTicketForm = document.getElementById(activeJobDateInput.getAttribute("form") || "");
    queueActiveJobFormSave(activeTicketForm, true);
  });
}

for (const aiCleanupButton of aiCleanupButtons) {
  aiCleanupButton.addEventListener("click", () => {
    cleanupMobileSummary(aiCleanupButton);
  });
}

for (const endJobForm of endJobForms) {
  const jobId = toSafeMapString(endJobForm.dataset.jobId);
  const summaryField = endJobForm.querySelector(".end-summary-notes");
  const descriptionElement = findDescriptionTextarea(jobId);
  endJobForm.addEventListener("submit", () => {
    syncEndJobClientFields(endJobForm);
    if (summaryField) {
      summaryField.value = descriptionElement ? descriptionElement.value : "";
    }
  });
}

for (const activeTicketForm of activeTicketForms) {
  const ticketInput = activeTicketForm.querySelector(".active-ticket-number");
  if (!ticketInput) {
    continue;
  }

  activeTicketForm.addEventListener("submit", (event) => {
    event.preventDefault();
    populateActiveFormSummaryField(activeTicketForm);
    queueActiveJobFormSave(activeTicketForm, true);
  });
}

for (const companyInput of companyInputs) {
  companyInput.addEventListener("input", () => {
    queueCompanySearch(companyInput);
  });
}

for (const ticketPicker of activeTicketPickers) {
  setActiveTicketPickerClickable(ticketPicker, true);

  ticketPicker.addEventListener("click", (event) => {
    if (event.target.closest("button, a, input, select, textarea")) {
      return;
    }

    loadActiveTicketOptions(ticketPicker, {saveActiveFormFirst: true});
  });

  ticketPicker.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }

    event.preventDefault();
    loadActiveTicketOptions(ticketPicker, {saveActiveFormFirst: true});
  });

}

document.addEventListener("click", handlePageLoadingSubmitButtonClick);
document.addEventListener("submit", handlePageLoadingFormSubmit);

function loadServiceCallPanelsAfterPageLoad() {
  for (const serviceCallPanel of serviceCallPanels) {
    loadServiceCallPanel(serviceCallPanel);
  }
}

for (const serviceCallPanel of serviceCallPanels) {
  initializeServiceCallDateControls(serviceCallPanel);
}

initializeLiveRoundedStopDisplays();
initializeActiveDurationDisplays();
initializeActiveEntryModes();

if (document.readyState === "complete") {
  window.setTimeout(loadServiceCallPanelsAfterPageLoad, 0);
} else {
  window.addEventListener("load", loadServiceCallPanelsAfterPageLoad, {once: true});
}

setAllRecordingControlsIdle();
