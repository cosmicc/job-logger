const DESCRIPTION_SAVE_DELAY_MS = 650;
const COMPANY_SEARCH_DELAY_MS = 400;
const MIN_COMPANY_SEARCH_CHARACTERS = 3;
const RECORDING_CHUNK_INTERVAL_MS = 2500;
const MAX_SOCKET_BUFFERED_BYTES = 2 * 1024 * 1024;
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

const activeRecordButtons = document.querySelectorAll(".record-notes-button");
const submitButtons = document.querySelectorAll(".submit-notes-button");
const descriptionTextareas = document.querySelectorAll(".job-description");
const endJobForms = document.querySelectorAll(".end-job-form");
const activeTicketForms = document.querySelectorAll(".active-ticket-form");
const companyInputs = document.querySelectorAll("[data-company-input]");
const activeTicketPickers = document.querySelectorAll("[data-active-ticket-picker]");
const roundedStartTimeForms = document.querySelectorAll("[data-rounded-start-time-form]");
const workLocationInputs = document.querySelectorAll("[data-work-location-input]");

const descriptionSaveTimers = new Map();
const companySearchTimers = new Map();
const lastSavedDescriptions = new Map();
const pendingDescriptionSaves = new Set();
const activeTicketLookupRequests = new WeakSet();

let activeRecorder = null;
let activeAudioStream = null;
let activeAudioSocket = null;
let activeAudioStreamFinalResolve = null;
let activeAudioStreamFinalReject = null;
let activeRecordingJobId = "";
let isUploadingRecording = false;
let hasRecordedAudio = false;
let activeAudioStreamReady = false;
let activeAudioStreamFailed = false;

function toSafeMapString(value) {
  return String(value || "");
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

function readActiveJobClientFields(jobId) {
  const activeTicketForm = findActiveTicketForm(jobId);
  if (!activeTicketForm) {
    return {clientName: "", autotaskCompanyId: ""};
  }

  // The active job card has one authoritative client source. It may be a
  // visible autocomplete input while unlocked, or a hidden value after an
  // Autotask company has been selected and locked for the active job.
  const clientNameSource = activeTicketForm.querySelector("[data-active-client-source]");
  const autotaskCompanyIdSource = activeTicketForm.querySelector("[data-company-id-input]");
  return {
    clientName: clientNameSource ? clientNameSource.value : "",
    autotaskCompanyId: autotaskCompanyIdSource ? autotaskCompanyIdSource.value : "",
  };
}

function syncEndJobClientFields(endJobForm) {
  const jobId = toSafeMapString(endJobForm.dataset.jobId);
  const clientFields = readActiveJobClientFields(jobId);
  const endClientNameField = endJobForm.querySelector(".end-client-name");
  const endAutotaskCompanyIdField = endJobForm.querySelector(".end-autotask-company-id");

  if (endClientNameField) {
    endClientNameField.value = clientFields.clientName;
  }

  if (endAutotaskCompanyIdField) {
    endAutotaskCompanyIdField.value = clientFields.autotaskCompanyId;
  }
}

function findControlElements(jobId) {
  return {
    recordButton: document.querySelector(`.record-notes-button[data-job-id="${toSafeMapString(jobId)}"]`),
    submitButton: document.querySelector(`.submit-notes-button[data-job-id="${toSafeMapString(jobId)}"]`),
    statusElement: findRecordingStatusElement(jobId),
  };
}

function getCompanyPickerElements(companyInput) {
  const parentForm = companyInput.closest("form");
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

function setRecordingStatus(jobId, message, isError = false) {
  const statusElement = findRecordingStatusElement(jobId);
  if (!statusElement) {
    return;
  }

  statusElement.textContent = message;
  statusElement.classList.toggle("error-text", isError);
}

function setRecordingUi({
  jobId,
  isRecording = false,
  isPaused = false,
  isUploading = false,
}) {
  const controls = findControlElements(jobId);
  if (!controls.recordButton || !controls.submitButton) {
    return;
  }

  controls.recordButton.disabled = isUploading;
  controls.submitButton.disabled = isUploading;

  if (isUploading) {
    controls.recordButton.classList.remove("is-recording");
    controls.recordButton.textContent = "Processing notes...";
    controls.submitButton.textContent = "Processing notes...";
    return;
  }

  if (isRecording) {
    controls.recordButton.classList.add("is-recording");
    controls.recordButton.textContent = isPaused ? "Resume Notes" : "Pause Notes";
    controls.submitButton.textContent = "Submit Notes";
    controls.submitButton.disabled = false;
    return;
  }

  controls.recordButton.classList.remove("is-recording");
  controls.recordButton.textContent = "Record Notes";
  controls.submitButton.textContent = "Submit Notes";
  controls.submitButton.disabled = true;
}

function setAllRecordingControlsIdle() {
  for (const button of activeRecordButtons) {
    const jobId = button.dataset.jobId || "";
    setRecordingUi({jobId, isRecording: false});
  }
}

function clearRecordingState() {
  isUploadingRecording = false;
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
  const jobId = activeRecordingJobId;
  activeRecordingJobId = "";
  if (jobId) {
    setRecordingUi({jobId, isRecording: false, isUploading: false});
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
  const parentForm = companyInput.closest("form");
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
      setCompanyStatus(companyInput, "Client selected.");
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
              setCompanyStatus(companyInput, "Client selected.");
            })
            .catch((error) => {
              setCompanyStatus(companyInput, error.message || "Open tickets could not be loaded.", true);
            });
          return;
        }
        submitFormWithCurrentFields(parentForm);
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

  if (payload.summary_notes) {
    const summaryElement = findDescriptionTextarea(jobId);
    if (summaryElement) {
      summaryElement.value = payload.summary_notes || "";
    }
    lastSavedDescriptions.set(jobId, payload.summary_notes || "");
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
          lastSavedDescriptions.set(safeJobId, nextValue || "");
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

  const descriptionElement = findDescriptionTextarea(activeJobId);
  if (descriptionElement) {
    descriptionElement.value = nextDescriptionText;
  }

  if (shouldMarkSaved) {
    lastSavedDescriptions.set(toSafeMapString(activeJobId), nextDescriptionText);
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
    setRecordingStatus(activeJobId, "Streaming audio to server...");
    if (readyHandlers && readyHandlers.resolve) {
      readyHandlers.resolve(payload);
    }
    return;
  }

  if (payload.type === "chunk_received") {
    setRecordingStatus(activeJobId, "Recording notes...");
    return;
  }

  if (payload.type === "transcription_started") {
    if (payload.phase === "final") {
      setRecordingStatus(activeJobId, "Finalizing transcription...");
      return;
    }
    setRecordingStatus(activeJobId, "Transcribing streamed audio...");
    return;
  }

  if (payload.type === "partial_pending") {
    setRecordingStatus(activeJobId, payload.detail || "Collecting enough audio to transcribe...");
    return;
  }

  if (payload.type === "partial") {
    updateDescriptionFromTranscription(activeJobId, payload, false);
    setRecordingStatus(activeJobId, "Streaming transcript preview...");
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
    setRecordingStatus(activeJobId, "Finalizing transcription...");
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
  setRecordingStatus(activeJobId, "Recording notes...");
}

function buildTicketOptionText(ticketOption) {
  const ticketNumber = ticketOption.ticket_number || "No ticket number";
  const ticketTitle = ticketOption.title || "Untitled ticket";
  const ticketStatus = ticketOption.status_label || "Unknown status";
  return `${ticketNumber} | ${ticketTitle} | ${ticketStatus}`;
}

async function loadActiveTicketOptions(ticketPicker, options = {}) {
  if (activeTicketLookupRequests.has(ticketPicker)) {
    return;
  }

  const saveActiveFormFirst = Boolean(options.saveActiveFormFirst);
  const lookupUrl = ticketPicker.dataset.ticketLookupUrl || "";
  const ticketSelectUrl = ticketPicker.dataset.ticketSelectUrl || "";
  const jobId = toSafeMapString(ticketPicker.dataset.ticketFormJobId);
  const activeTicketForm = findActiveTicketForm(jobId);
  const lookupButton = ticketPicker.querySelector("[data-active-ticket-lookup-button]");
  const statusElement = ticketPicker.querySelector("[data-active-ticket-lookup-status]");
  const resultsElement = ticketPicker.querySelector("[data-active-ticket-lookup-results]");
  if (!lookupUrl || !statusElement || !resultsElement) {
    return;
  }

  const clientFields = readActiveJobClientFields(jobId);
  if (!clientFields.clientName.trim()) {
    statusElement.classList.remove("error-text");
    statusElement.textContent = "Choose a client before finding open tickets.";
    resultsElement.replaceChildren();
    return;
  }

  activeTicketLookupRequests.add(ticketPicker);
  if (lookupButton) {
    lookupButton.disabled = true;
  }
  statusElement.classList.remove("error-text");
  statusElement.textContent = saveActiveFormFirst ? "Saving client before ticket lookup..." : "Searching Autotask tickets...";
  resultsElement.replaceChildren();

  try {
    if (saveActiveFormFirst) {
      await saveActiveJobFormInBackground(activeTicketForm);
      const endJobForm = document.querySelector(`.end-job-form[data-job-id="${jobId}"]`);
      if (endJobForm) {
        syncEndJobClientFields(endJobForm);
      }
    }

    statusElement.textContent = "Searching Autotask tickets...";
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
        const activeTicketForm = findActiveTicketForm(jobId);
        const ticketInput = activeTicketForm ? activeTicketForm.querySelector(".active-ticket-number") : null;
        const ticketTitleInput = activeTicketForm ? activeTicketForm.querySelector(".active-ticket-title") : null;
        if (!ticketInput) {
          return;
        }

        optionButton.disabled = true;
        statusElement.textContent = "Saving selected ticket...";
        try {
          if (ticketSelectUrl) {
            const selectedTicket = await persistActiveSelectedTicket(ticketSelectUrl, ticketOption);
            ticketInput.value = toSafeMapString(selectedTicket.ticket_number).trim().toUpperCase();
            if (ticketTitleInput) {
              ticketTitleInput.value = toSafeMapString(selectedTicket.ticket_title).trim();
            }
            window.location.reload();
            return;
          }

          ticketInput.value = toSafeMapString(ticketOption.ticket_number).trim().toUpperCase();
          if (ticketTitleInput) {
            ticketTitleInput.value = toSafeMapString(ticketOption.title).trim();
          }
          submitFormWithCurrentFields(activeTicketForm);
        } catch (error) {
          optionButton.disabled = false;
          statusElement.textContent = error.message || "Selected ticket could not be saved.";
          statusElement.classList.add("error-text");
        }
      });
      resultsElement.append(optionButton);
    }
  } catch (error) {
    statusElement.textContent = error.message || "Autotask ticket lookup failed.";
    statusElement.classList.add("error-text");
  } finally {
    activeTicketLookupRequests.delete(ticketPicker);
    if (lookupButton) {
      lookupButton.disabled = false;
    }
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
    if (activeRecorder.state === "recording") {
      activeRecorder.pause();
    } else if (activeRecorder.state === "paused") {
      activeRecorder.resume();
    }
    return;
  }

  if (!navigator.mediaDevices || !window.MediaRecorder) {
    setRecordingStatus(activeJobId, "This browser does not support secure audio recording.", true);
    return;
  }

  setRecordingStatus(activeJobId, "Preparing recorder...");
  hasRecordedAudio = false;
  activeAudioStream = await navigator.mediaDevices.getUserMedia({audio: true});
  const selectedMimeType = preferredRecorderMimeType();
  activeRecorder = selectedMimeType
    ? new MediaRecorder(activeAudioStream, {mimeType: selectedMimeType})
    : new MediaRecorder(activeAudioStream);
  activeRecordingJobId = activeJobId;
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

  activeRecorder.addEventListener("pause", () => {
    setRecordingStatus(activeJobId, "Recording paused.");
    setRecordingUi({jobId: activeJobId, isRecording: true, isPaused: true});
  });

  activeRecorder.addEventListener("resume", () => {
    setRecordingStatus(activeJobId, "Recording notes...");
    setRecordingUi({jobId: activeJobId, isRecording: true, isPaused: false});
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
        return;
      }

      if (!hasRecordedAudio) {
        setRecordingStatus(jobId, "No audio was recorded. Press Record and try again.");
        return;
      }

      isUploadingRecording = true;
      setRecordingUi({jobId, isUploading: true});
      await finishAudioTranscriptionStream(jobId);
      setRecordingStatus(jobId, "Notes updated.");
    } catch (error) {
      setRecordingStatus(jobId, error.message, true);
    } finally {
      clearRecordingState();
    }
  });

  activeRecorder.start(RECORDING_CHUNK_INTERVAL_MS);
  setRecordingUi({jobId: activeJobId, isRecording: true, isPaused: false});
  setRecordingStatus(activeJobId, "Recording notes...");
}

function togglePauseResume(activeJobId) {
  if (!activeRecorder || activeRecordingJobId !== activeJobId) {
    setRecordingStatus(activeJobId, "Start this job recording first.");
    return;
  }

  if (!activeRecorder.pause || !activeRecorder.resume) {
    setRecordingStatus(activeJobId, "Pause and resume are not supported in this browser.", true);
    return;
  }

  if (activeRecorder.state === "recording") {
    activeRecorder.pause();
    return;
  }

  if (activeRecorder.state === "paused") {
    activeRecorder.resume();
  }
}

function stopRecording(activeJobId) {
  if (!activeRecorder || isUploadingRecording) {
    return;
  }

  if (activeRecordingJobId !== activeJobId) {
    setRecordingStatus(activeJobId, "That job is not currently recording.");
    return;
  }

  if (activeRecorder.state === "paused") {
    activeRecorder.resume();
  }

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
    if (isUploadingRecording) {
      return;
    }

    if (activeRecorder) {
      if (activeRecordingJobId === jobId) {
        togglePauseResume(jobId);
        return;
      }

      setRecordingStatus(jobId, "Finish or submit the current recording before switching jobs.", true);
      return;
    }

    try {
      await startRecording(jobId);
    } catch (error) {
      setRecordingStatus(jobId, error.message || "Recording could not start.", true);
      clearRecordingState();
    }
  });
}

for (const submitButton of submitButtons) {
  const jobId = toSafeMapString(submitButton.dataset.jobId);
  submitButton.addEventListener("click", () => {
    if (isUploadingRecording) {
      return;
    }

    if (!activeRecorder || activeRecordingJobId !== jobId) {
      setRecordingStatus(jobId, "Press Record first, then press Submit when ready.");
      return;
    }

    stopRecording(jobId);
  });
}

for (const roundedStartTimeForm of roundedStartTimeForms) {
  const roundedStartTimeInput = roundedStartTimeForm.querySelector("[data-rounded-start-time-input]");
  if (!roundedStartTimeInput) {
    continue;
  }

  let lastSubmittedRoundedStartTime = roundedStartTimeInput.value;
  roundedStartTimeInput.addEventListener("change", () => {
    if (roundedStartTimeInput.value === lastSubmittedRoundedStartTime) {
      return;
    }

    lastSubmittedRoundedStartTime = roundedStartTimeInput.value;
    submitFormWithCurrentFields(roundedStartTimeForm);
  });
}

for (const workLocationInput of workLocationInputs) {
  workLocationInput.addEventListener("change", () => {
    if (!workLocationInput.checked) {
      return;
    }

    const activeTicketForm = document.getElementById(workLocationInput.getAttribute("form") || "");
    submitFormWithCurrentFields(activeTicketForm);
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

  activeTicketForm.addEventListener("submit", () => {
    populateActiveFormSummaryField(activeTicketForm);
  });
}

for (const companyInput of companyInputs) {
  companyInput.addEventListener("input", () => {
    queueCompanySearch(companyInput);
  });
}

for (const ticketPicker of activeTicketPickers) {
  const lookupButton = ticketPicker.querySelector("[data-active-ticket-lookup-button]");
  if (lookupButton) {
    lookupButton.addEventListener("click", () => {
      loadActiveTicketOptions(ticketPicker, {saveActiveFormFirst: true});
    });
  }

  if (ticketPicker.dataset.autoLoadTicketOptions === "true") {
    window.setTimeout(() => {
      loadActiveTicketOptions(ticketPicker);
    }, 50);
  }
}

setAllRecordingControlsIdle();
