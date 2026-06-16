const DESCRIPTION_SAVE_DELAY_MS = 650;
const COMPANY_SEARCH_DELAY_MS = 400;
const MIN_COMPANY_SEARCH_CHARACTERS = 3;
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";

const activeRecordButtons = document.querySelectorAll(".record-notes-button");
const submitButtons = document.querySelectorAll(".submit-notes-button");
const descriptionTextareas = document.querySelectorAll(".job-description");
const endJobForms = document.querySelectorAll(".end-job-form");
const activeTicketForms = document.querySelectorAll(".active-ticket-form");
const companyInputs = document.querySelectorAll("[data-company-input]");
const activeTicketPickers = document.querySelectorAll("[data-active-ticket-picker]");

const descriptionSaveTimers = new Map();
const companySearchTimers = new Map();
const lastSavedDescriptions = new Map();
const pendingDescriptionSaves = new Set();

let activeRecorder = null;
let activeAudioStream = null;
let activeAudioChunks = [];
let activeRecordingJobId = "";
let isUploadingRecording = false;
let hasRecordedAudio = false;

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
  activeAudioChunks = [];
  hasRecordedAudio = false;
  const jobId = activeRecordingJobId;
  activeRecordingJobId = "";
  if (jobId) {
    setRecordingUi({jobId, isRecording: false, isUploading: false});
  }
  setRecordingStatus(jobId, "");
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
      setCompanyStatus(companyInput, "Autotask company selected.");
      if (parentForm && parentForm.classList.contains("active-ticket-form")) {
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

async function uploadRecording(activeJobId, audioBlob) {
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.webm");

  const response = await fetch(`/jobs/${activeJobId}/description/audio`, {
    method: "POST",
    headers: {
      "X-CSRF-Token": csrfToken,
    },
    body: formData,
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Recording could not be transcribed.");
  }

  const descriptionElement = findDescriptionTextarea(activeJobId);
  if (descriptionElement) {
    descriptionElement.value = payload.summary_notes || payload.description_text || "";
    queueDescriptionSave(activeJobId, true);
  }

  return payload;
}

function buildTicketOptionText(ticketOption) {
  const ticketNumber = ticketOption.ticket_number || "No ticket number";
  const ticketTitle = ticketOption.title || "Untitled ticket";
  const ticketStatus = ticketOption.status_label || "Unknown status";
  return `${ticketNumber} | ${ticketTitle} | ${ticketStatus}`;
}

async function loadActiveTicketOptions(ticketPicker) {
  const lookupUrl = ticketPicker.dataset.ticketLookupUrl || "";
  const jobId = toSafeMapString(ticketPicker.dataset.ticketFormJobId);
  const lookupButton = ticketPicker.querySelector("[data-active-ticket-lookup-button]");
  const statusElement = ticketPicker.querySelector("[data-active-ticket-lookup-status]");
  const resultsElement = ticketPicker.querySelector("[data-active-ticket-lookup-results]");
  if (!lookupUrl || !lookupButton || !statusElement || !resultsElement) {
    return;
  }

  lookupButton.disabled = true;
  statusElement.classList.remove("error-text");
  statusElement.textContent = "Searching Autotask tickets...";
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
        const activeTicketForm = findActiveTicketForm(jobId);
        const ticketInput = activeTicketForm ? activeTicketForm.querySelector(".active-ticket-number") : null;
        if (!ticketInput) {
          return;
        }

        ticketInput.value = ticketOption.ticket_number || "";
        statusElement.textContent = `Selected ${ticketInput.value}.`;
        submitFormWithCurrentFields(activeTicketForm);
      });
      resultsElement.append(optionButton);
    }
  } catch (error) {
    statusElement.textContent = error.message || "Autotask ticket lookup failed.";
    statusElement.classList.add("error-text");
  } finally {
    lookupButton.disabled = false;
  }
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
  activeAudioChunks = [];
  hasRecordedAudio = false;
  activeAudioStream = await navigator.mediaDevices.getUserMedia({audio: true});
  activeRecorder = new MediaRecorder(activeAudioStream);
  activeRecordingJobId = activeJobId;

  activeRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      activeAudioChunks.push(event.data);
      hasRecordedAudio = true;
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
      if (!hasRecordedAudio || activeAudioChunks.length === 0) {
        setRecordingStatus(jobId, "No audio was recorded. Press Record and try again.");
        return;
      }

      const audioBlob = new Blob(activeAudioChunks, {type: "audio/webm"});
      isUploadingRecording = true;
      setRecordingUi({jobId, isUploading: true});
      setRecordingStatus(jobId, "Uploading recording for transcription...");
      await uploadRecording(jobId, audioBlob);
      setRecordingStatus(jobId, "Notes updated.");
    } catch (error) {
      setRecordingStatus(jobId, error.message, true);
    } finally {
      clearRecordingState();
    }
  });

  activeRecorder.start();
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

for (const endJobForm of endJobForms) {
  const jobId = toSafeMapString(endJobForm.dataset.jobId);
  const summaryField = endJobForm.querySelector(".end-summary-notes");
  const descriptionElement = findDescriptionTextarea(jobId);
  endJobForm.addEventListener("submit", () => {
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

  const summaryField = activeTicketForm.querySelector(".active-job-summary");
  let initialTicketNumber = toSafeMapString(ticketInput.value).trim().toUpperCase();

  activeTicketForm.addEventListener("submit", () => {
    if (summaryField) {
      const safeJobId = toSafeMapString(activeTicketForm.dataset.jobId);
      const descriptionElement = findDescriptionTextarea(safeJobId);
      if (descriptionElement) {
        summaryField.value = descriptionElement.value || "";
      }
      clearDescriptionTimer(safeJobId);
      pendingDescriptionSaves.delete(safeJobId);
    }
  });

  ticketInput.addEventListener("change", () => {
    const nextTicketNumber = toSafeMapString(ticketInput.value).trim().toUpperCase();
    if (nextTicketNumber === initialTicketNumber) {
      return;
    }

    initialTicketNumber = nextTicketNumber;
    ticketInput.value = nextTicketNumber;
    submitFormWithCurrentFields(activeTicketForm);
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
      loadActiveTicketOptions(ticketPicker);
    });
  }

  if (ticketPicker.dataset.autoLoadTicketOptions === "true") {
    loadActiveTicketOptions(ticketPicker);
  }
}

setAllRecordingControlsIdle();
