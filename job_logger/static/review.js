const TIME_STEP_MINUTES = 15;
const REVIEW_AUTOSAVE_DELAY_MS = 650;
const RECORDING_CHUNK_INTERVAL_MS = 2500;
const MAX_SOCKET_BUFFERED_BYTES = 2 * 1024 * 1024;
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
const RECORD_AUDIO_LABEL = "Record Audio";
const STOP_RECORDING_LABEL = "Stop recording";
const RECORDING_STATUS_RECORDING = "Recording audio...";
const RECORDING_STATUS_SENDING = "Sending data to server...";
const RECORDING_STATUS_CONVERTING = "Converting audio to text...";
const RECORDING_STATUS_COMPLETE = "Conversion complete.";
const reviewAutosaveForm = document.querySelector("[data-review-autosave-form]");
const reviewAutosaveStatus = document.querySelector("[data-review-autosave-status]");
const aiCleanupButtons = document.querySelectorAll("[data-ai-cleanup-button]");
const reviewRecordButtons = document.querySelectorAll("[data-review-record-button]");
const confirmationForms = document.querySelectorAll("[data-confirm-message]");

let reviewAutosaveTimer = null;
let lastReviewAutosaveSnapshot = "";
let reviewAudioRecorder = null;
let reviewAudioStream = null;
let reviewAudioSocket = null;
let reviewAudioStreamFinalResolve = null;
let reviewAudioStreamFinalReject = null;
let reviewRecordingJobId = "";
let reviewAudioCompletionInProgress = false;
let reviewUploadingRecording = false;
let reviewHasRecordedAudio = false;
let reviewAudioStreamReady = false;
let reviewAudioStreamFailed = false;
let reviewStartingRecording = false;
let reviewAudioStopRequested = false;

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

function setInlineLoadingStatus(statusElement, message, {isError = false} = {}) {
  if (!statusElement) {
    return;
  }

  statusElement.classList.toggle("error-text", isError);
  statusElement.classList.remove("is-loading");
  statusElement.textContent = message;
}

function setAiCleanupStatus(button, message, isError = false, isLoading = false) {
  const formElement = button ? button.closest("form") : null;
  const statusElement = formElement ? formElement.querySelector("[data-ai-cleanup-status]") : null;
  setInlineLoadingStatus(statusElement, message, {isError, isLoading});
}

function setAiCleanupButtonLoading(button, isLoading) {
  if (!button) {
    return;
  }

  button.disabled = isLoading;
  button.classList.toggle("is-loading", isLoading);
  button.setAttribute("aria-busy", isLoading ? "true" : "false");
}

function toSafeMapString(value) {
  return String(value || "");
}

function findReviewRecordingStatus(jobId) {
  if (!jobId) {
    return null;
  }

  return document.querySelector(`[data-review-recording-status][data-job-id="${toSafeMapString(jobId)}"]`);
}

function findReviewRecordingControls(jobId) {
  const safeJobId = toSafeMapString(jobId);
  return {
    recordButton: document.querySelector(`[data-review-record-button][data-job-id="${safeJobId}"]`),
    recordButtonLabel: document.querySelector(`[data-review-record-button][data-job-id="${safeJobId}"] [data-record-audio-label]`),
    statusElement: findReviewRecordingStatus(safeJobId),
  };
}

function findReviewSummaryTextarea() {
  return reviewAutosaveForm ? reviewAutosaveForm.querySelector('textarea[name="summary_notes"]') : null;
}

function setReviewRecordingStatus(jobId, message, isError = false) {
  const statusElement = findReviewRecordingStatus(jobId);
  setInlineLoadingStatus(statusElement, message, {isError});
}

function setReviewRecordingProgressStatus(activeJobId, activeMessage) {
  const safeActiveJobId = toSafeMapString(activeJobId);
  if (reviewAudioStopRequested && reviewRecordingJobId === safeActiveJobId) {
    setReviewRecordingStatus(
      safeActiveJobId,
      reviewAudioCompletionInProgress ? RECORDING_STATUS_CONVERTING : RECORDING_STATUS_SENDING,
    );
    return;
  }

  setReviewRecordingStatus(safeActiveJobId, activeMessage);
}

function setReviewRecordingUi({jobId, isRecording = false, isProcessing = false}) {
  const controls = findReviewRecordingControls(jobId);
  if (!controls.recordButton) {
    return;
  }

  controls.recordButton.disabled = isProcessing;
  controls.recordButton.classList.toggle("is-loading", isProcessing);
  controls.recordButton.setAttribute("aria-busy", isProcessing ? "true" : "false");
  controls.recordButton.setAttribute("aria-pressed", isRecording ? "true" : "false");
  if (controls.recordButtonLabel) {
    controls.recordButtonLabel.textContent = isRecording ? STOP_RECORDING_LABEL : RECORD_AUDIO_LABEL;
    controls.recordButtonLabel.dataset.state = isRecording ? "stop" : "record";
    controls.recordButton.setAttribute("aria-label", isRecording ? STOP_RECORDING_LABEL : RECORD_AUDIO_LABEL);
  }

  if (isProcessing) {
    controls.recordButton.classList.remove("is-recording");
    return;
  }

  controls.recordButton.classList.toggle("is-recording", isRecording);
}

function stopReviewAudioStreamTracks() {
  if (!reviewAudioStream) {
    return;
  }

  for (const track of reviewAudioStream.getTracks()) {
    track.stop();
  }
}

function clearReviewRecordingState() {
  reviewUploadingRecording = false;
  reviewStartingRecording = false;
  if (reviewAudioStream) {
    stopReviewAudioStreamTracks();
  }

  reviewAudioStream = null;
  reviewAudioRecorder = null;
  if (reviewAudioSocket && reviewAudioSocket.readyState === WebSocket.OPEN) {
    reviewAudioSocket.close(1000, "Recording finished.");
  }
  reviewAudioSocket = null;
  reviewAudioStreamFinalResolve = null;
  reviewAudioStreamFinalReject = null;
  reviewAudioStreamReady = false;
  reviewAudioStreamFailed = false;
  reviewHasRecordedAudio = false;
  reviewAudioStopRequested = false;
  const jobId = reviewRecordingJobId;
  reviewRecordingJobId = "";
  reviewAudioCompletionInProgress = false;
  if (jobId) {
    setReviewRecordingUi({jobId, isRecording: false, isProcessing: false});
  }
}

function reviewWebsocketUrlForAudioStream(activeJobId) {
  const websocketProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${websocketProtocol}//${window.location.host}/jobs/${encodeURIComponent(activeJobId)}/description/audio/stream`;
}

function preferredReviewRecorderMimeType() {
  if (!window.MediaRecorder || typeof MediaRecorder.isTypeSupported !== "function") {
    return "";
  }

  const supportedTypes = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "video/webm;codecs=opus",
    "audio/ogg;codecs=opus",
  ];
  return supportedTypes.find((mimeType) => MediaRecorder.isTypeSupported(mimeType)) || "";
}

function reviewSummaryPrefix() {
  const workLocationInput = reviewAutosaveForm ? reviewAutosaveForm.querySelector('input[name="work_location"]') : null;
  return workLocationInput && workLocationInput.value === "on_site" ? "On-Site" : "Remote";
}

function applyReviewSummaryPrefix(summaryText) {
  const safeSummaryText = String(summaryText || "").trim();
  if (!safeSummaryText || /^(Remote|On-Site)\b/i.test(safeSummaryText)) {
    return safeSummaryText;
  }

  return `${reviewSummaryPrefix()} ${safeSummaryText}`;
}

function updateReviewSummaryFromTranscription(activeJobId, payload) {
  const summaryTextarea = findReviewSummaryTextarea();
  if (!summaryTextarea) {
    return;
  }

  const transcriptionText = payload.summary_notes || payload.description_text || "";
  summaryTextarea.value = applyReviewSummaryPrefix(transcriptionText);
  clearReviewAutosaveTimer();
  queueReviewAutosave(true);
}

function rejectReviewAudioStream(errorMessage) {
  reviewAudioStreamFailed = true;
  if (reviewAudioStreamFinalReject) {
    reviewAudioStreamFinalReject(new Error(errorMessage));
    reviewAudioStreamFinalReject = null;
    reviewAudioStreamFinalResolve = null;
  }
}

function handleReviewAudioStreamMessage(activeJobId, rawMessage, readyHandlers) {
  let payload = null;
  try {
    payload = JSON.parse(rawMessage);
  } catch (error) {
    rejectReviewAudioStream("Audio stream returned an invalid server message.");
    if (readyHandlers && readyHandlers.reject) {
      readyHandlers.reject(new Error("Audio stream returned an invalid server message."));
    }
    return;
  }

  if (payload.type === "ready") {
    reviewAudioStreamReady = true;
    setReviewRecordingStatus(activeJobId, "Streaming audio to server...");
    if (readyHandlers && readyHandlers.resolve) {
      readyHandlers.resolve(payload);
    }
    return;
  }

  if (payload.type === "chunk_received") {
    setReviewRecordingProgressStatus(activeJobId, RECORDING_STATUS_RECORDING);
    return;
  }

  if (payload.type === "transcription_started") {
    setReviewRecordingStatus(
      activeJobId,
      payload.phase === "final" ? RECORDING_STATUS_CONVERTING : "Converting streamed audio...",
    );
    return;
  }

  if (payload.type === "partial_pending") {
    setReviewRecordingStatus(activeJobId, payload.detail || "Collecting enough audio to transcribe...");
    return;
  }

  if (payload.type === "partial") {
    setReviewRecordingProgressStatus(activeJobId, "Transcribing audio...");
    return;
  }

  if (payload.type === "final") {
    updateReviewSummaryFromTranscription(activeJobId, payload);
    if (reviewAudioStreamFinalResolve) {
      reviewAudioStreamFinalResolve(payload);
      reviewAudioStreamFinalResolve = null;
      reviewAudioStreamFinalReject = null;
    }
    return;
  }

  if (payload.type === "error") {
    const errorMessage = payload.detail || "Recording could not be transcribed.";
    rejectReviewAudioStream(errorMessage);
    if (reviewAudioRecorder && reviewRecordingJobId === activeJobId && reviewAudioRecorder.state !== "inactive") {
      reviewAudioRecorder.stop();
    }
    if (readyHandlers && readyHandlers.reject) {
      readyHandlers.reject(new Error(errorMessage));
    }
  }
}

async function openReviewAudioTranscriptionStream(activeJobId, contentType) {
  return new Promise((resolve, reject) => {
    const audioSocket = new WebSocket(reviewWebsocketUrlForAudioStream(activeJobId));
    let readySettled = false;
    const readyTimeout = window.setTimeout(() => {
      if (!readySettled) {
        readySettled = true;
        reject(new Error("Audio stream did not become ready."));
        audioSocket.close();
      }
    }, 10000);

    reviewAudioSocket = audioSocket;
    reviewAudioStreamReady = false;
    reviewAudioStreamFailed = false;

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
      handleReviewAudioStreamMessage(activeJobId, event.data, readyHandlers);
    });

    audioSocket.addEventListener("error", () => {
      const error = new Error("Audio stream connection failed.");
      readyHandlers.reject(error);
      rejectReviewAudioStream(error.message);
    });

    audioSocket.addEventListener("close", () => {
      if (!readySettled) {
        readyHandlers.reject(new Error("Audio stream closed before it was ready."));
        return;
      }

      if (reviewAudioStreamFinalReject && !reviewAudioStreamFailed) {
        reviewAudioStreamFinalReject(new Error("Audio stream closed before transcription finished."));
        reviewAudioStreamFinalResolve = null;
        reviewAudioStreamFinalReject = null;
      }

      if (reviewAudioRecorder && reviewRecordingJobId === activeJobId && reviewAudioRecorder.state !== "inactive") {
        reviewAudioStreamFailed = true;
        reviewAudioRecorder.stop();
      }
    });
  });
}

async function finishReviewAudioTranscriptionStream(activeJobId) {
  if (!reviewAudioSocket || reviewAudioSocket.readyState !== WebSocket.OPEN || reviewAudioStreamFailed) {
    throw new Error("Audio transcription stream is not available.");
  }

  return new Promise((resolve, reject) => {
    reviewAudioStreamFinalResolve = resolve;
    reviewAudioStreamFinalReject = reject;
    reviewAudioSocket.send(JSON.stringify({type: "finish"}));
    setReviewRecordingStatus(activeJobId, RECORDING_STATUS_CONVERTING);
  });
}

function streamReviewAudioChunk(activeJobId, audioChunk) {
  if (!reviewAudioSocket || reviewAudioSocket.readyState !== WebSocket.OPEN || !reviewAudioStreamReady) {
    throw new Error("Audio stream is not ready.");
  }

  if (reviewAudioSocket.bufferedAmount > MAX_SOCKET_BUFFERED_BYTES) {
    throw new Error("Audio stream is backed up. Check the connection and try again.");
  }

  reviewAudioSocket.send(audioChunk);
  reviewHasRecordedAudio = true;
  setReviewRecordingProgressStatus(activeJobId, RECORDING_STATUS_RECORDING);
}

async function finalizeReviewRecordingForJob(activeJobId) {
  const safeJobId = toSafeMapString(activeJobId);
  if (!safeJobId || reviewAudioCompletionInProgress) {
    return;
  }

  reviewAudioCompletionInProgress = true;
  try {
    if (reviewAudioStreamFailed) {
      setReviewRecordingStatus(safeJobId, "Recording stream failed. Press Record Audio and try again.", true);
      return;
    }

    if (!reviewAudioSocket || reviewAudioSocket.readyState !== WebSocket.OPEN) {
      throw new Error("Audio transcription stream is not available.");
    }

    setReviewRecordingUi({jobId: safeJobId, isProcessing: true});
    await finishReviewAudioTranscriptionStream(safeJobId);
    setReviewRecordingStatus(safeJobId, RECORDING_STATUS_COMPLETE);
  } catch (error) {
    setReviewRecordingStatus(safeJobId, error.message || "Recording stream could not finish.", true);
  } finally {
    clearReviewRecordingState();
  }
}

async function startReviewRecording(activeJobId) {
  if (!activeJobId) {
    setReviewRecordingStatus("", "No review job is available.", true);
    return;
  }

  if (reviewAudioRecorder && reviewRecordingJobId !== activeJobId) {
    setReviewRecordingStatus(activeJobId, "Another job is currently recording. Finish that session first.", true);
    return;
  }

  if (reviewAudioRecorder) {
    await stopReviewRecording(activeJobId);
    return;
  }

  if (!navigator.mediaDevices || !window.MediaRecorder) {
    setReviewRecordingStatus(activeJobId, "This browser does not support secure audio recording.", true);
    return;
  }

  setReviewRecordingStatus(activeJobId, "Preparing recorder...");
  reviewHasRecordedAudio = false;
  reviewUploadingRecording = false;
  reviewAudioCompletionInProgress = false;
  reviewAudioStopRequested = false;
  reviewAudioStream = await navigator.mediaDevices.getUserMedia({audio: true});
  const selectedMimeType = preferredReviewRecorderMimeType();
  reviewAudioRecorder = selectedMimeType
    ? new MediaRecorder(reviewAudioStream, {mimeType: selectedMimeType})
    : new MediaRecorder(reviewAudioStream);
  reviewRecordingJobId = activeJobId;
  setReviewRecordingUi({jobId: activeJobId, isRecording: true});
  await openReviewAudioTranscriptionStream(activeJobId, reviewAudioRecorder.mimeType || selectedMimeType || "audio/webm");

  reviewAudioRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      try {
        streamReviewAudioChunk(activeJobId, event.data);
      } catch (error) {
        setReviewRecordingStatus(activeJobId, error.message || "Audio chunk could not be streamed.", true);
        reviewAudioStreamFailed = true;
        if (reviewAudioRecorder && reviewAudioRecorder.state !== "inactive") {
          reviewAudioRecorder.stop();
        }
      }
    }
  });

  reviewAudioRecorder.addEventListener("start", () => {
    setReviewRecordingUi({jobId: activeJobId, isRecording: true});
  });

  reviewAudioRecorder.addEventListener("stop", async () => {
    const jobId = reviewRecordingJobId;
    try {
      if (!jobId) {
        return;
      }

      stopReviewAudioStreamTracks();
      if (reviewAudioStreamFailed) {
        setReviewRecordingStatus(jobId, "Recording stream failed. Press Record Audio and try again.", true);
        clearReviewRecordingState();
        return;
      }

      if (!reviewHasRecordedAudio) {
        setReviewRecordingStatus(jobId, "No audio was recorded. Press Record Audio and try again.");
        clearReviewRecordingState();
        return;
      }

      await finalizeReviewRecordingForJob(jobId);
    } catch (error) {
      setReviewRecordingStatus(jobId, error.message, true);
      clearReviewRecordingState();
    }
  });

  reviewAudioRecorder.start(RECORDING_CHUNK_INTERVAL_MS);
  setReviewRecordingStatus(activeJobId, "Streaming audio to server...");
}

async function stopReviewRecording(activeJobId) {
  if (!reviewAudioRecorder || reviewUploadingRecording) {
    return;
  }

  reviewUploadingRecording = true;

  if (reviewRecordingJobId !== activeJobId) {
    setReviewRecordingStatus(activeJobId, "That job is not currently recording.");
    reviewUploadingRecording = false;
    return;
  }

  if (reviewAudioRecorder.state === "inactive") {
    reviewAudioStopRequested = true;
    setReviewRecordingUi({jobId: activeJobId, isProcessing: true});
    setReviewRecordingStatus(activeJobId, RECORDING_STATUS_SENDING);
    if (!reviewHasRecordedAudio) {
      setReviewRecordingStatus(activeJobId, "No audio was recorded. Press Record Audio and try again.");
      clearReviewRecordingState();
      return;
    }

    await finalizeReviewRecordingForJob(activeJobId);
    return;
  }

  reviewAudioStopRequested = true;
  setReviewRecordingUi({jobId: activeJobId, isProcessing: true});
  setReviewRecordingStatus(activeJobId, RECORDING_STATUS_SENDING);
  reviewAudioRecorder.stop();
}

function isReviewRecordingBusy() {
  return Boolean(reviewAudioRecorder || reviewUploadingRecording || reviewAudioCompletionInProgress || reviewStartingRecording);
}

function handleConfirmedFormSubmit(event) {
  const formElement = event.target.closest("[data-confirm-message]");
  if (!formElement || event.defaultPrevented) {
    return;
  }

  const confirmationMessage = formElement.dataset.confirmMessage || "";
  if (confirmationMessage && !window.confirm(confirmationMessage)) {
    event.preventDefault();
  }
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

async function cleanupReviewSummary(button) {
  const cleanupUrl = button.dataset.cleanupUrl || "";
  const formElement = button.closest("form");
  const summaryTextarea = formElement ? formElement.querySelector('textarea[name="summary_notes"]') : null;
  if (!cleanupUrl || !summaryTextarea) {
    return;
  }

  const currentSummaryText = summaryTextarea.value || "";
  if (!currentSummaryText.trim()) {
    setAiCleanupStatus(button, "Add summary notes before AI cleanup.", true);
    return;
  }

  if (isReviewRecordingBusy()) {
    setAiCleanupStatus(button, "Finish audio recording before AI cleanup.", true);
    return;
  }

  clearReviewAutosaveTimer();
  setAiCleanupButtonLoading(button, true);
  setAiCleanupStatus(button, "Cleaning up summary...", false, true);
  try {
    const payload = await requestAiCleanup(cleanupUrl, currentSummaryText);
    const cleanedSummaryText = payload.summary_notes || payload.description_text || "";
    if (!cleanedSummaryText.trim()) {
      throw new Error("AI cleanup returned no summary text.");
    }

    summaryTextarea.value = cleanedSummaryText;
    setAiCleanupStatus(button, "Summary cleaned up.");
    if (formElement === reviewAutosaveForm) {
      queueReviewAutosave(true);
    }
  } catch (error) {
    setAiCleanupStatus(button, `AI cleanup failed: ${error.message || "AI cleanup could not finish."}`, true);
  } finally {
    setAiCleanupButtonLoading(button, false);
  }
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

for (const aiCleanupButton of aiCleanupButtons) {
  aiCleanupButton.addEventListener("click", () => {
    cleanupReviewSummary(aiCleanupButton);
  });
}

for (const reviewRecordButton of reviewRecordButtons) {
  const jobId = toSafeMapString(reviewRecordButton.dataset.jobId);
  reviewRecordButton.addEventListener("click", async () => {
    if (reviewUploadingRecording || reviewStartingRecording) {
      return;
    }

    if (reviewAudioRecorder) {
      if (reviewRecordingJobId === jobId) {
        await stopReviewRecording(jobId);
        return;
      }

      setReviewRecordingStatus(jobId, "Stop the current recording before switching jobs.", true);
      return;
    }

    setReviewRecordingUi({jobId, isRecording: true});
    setReviewRecordingStatus(jobId, "Preparing recorder...");
    reviewStartingRecording = true;
    try {
      await startReviewRecording(jobId);
    } catch (error) {
      setReviewRecordingStatus(jobId, error.message || "Recording could not start.", true);
      clearReviewRecordingState();
      reviewStartingRecording = false;
      return;
    }

    reviewStartingRecording = false;
    if (!reviewAudioRecorder || reviewRecordingJobId !== jobId) {
      setReviewRecordingUi({jobId, isRecording: false});
    }
  });
}

if (confirmationForms.length > 0) {
  document.addEventListener("submit", handleConfirmedFormSubmit);
}
