const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
const recordButton = document.getElementById("record-description-button");
const stopRecordingButton = document.getElementById("stop-description-button");
const recordingStatus = document.getElementById("recording-status");
const descriptionPreview = document.getElementById("description-preview");
const activeTicketForm = document.getElementById("active-ticket-form");
const activeTicketInput = document.getElementById("active-ticket-number");

const DESCRIPTION_SAVE_DELAY_MS = 650;
let descriptionSaveTimer = null;
let lastSavedDescription = descriptionPreview ? descriptionPreview.value : "";

let activeRecorder = null;
let activeAudioChunks = [];
let activeAudioStream = null;
let activeRecordingJobId = "";
let isUploadingRecording = false;

function setRecordingStatus(message, isError = false) {
  if (!recordingStatus) {
    return;
  }

  recordingStatus.textContent = message;
  recordingStatus.classList.toggle("error-text", isError);
}

function setRecordingUi(isRecording = false, isPaused = false, isUploading = false) {
  if (!recordButton) {
    return;
  }

  if (isUploading) {
    recordButton.disabled = true;
    recordButton.classList.remove("is-recording");
    recordButton.textContent = "Processing recording...";
    if (stopRecordingButton) {
      stopRecordingButton.hidden = true;
      stopRecordingButton.disabled = true;
    }
    return;
  }

  recordButton.disabled = false;
  if (isRecording) {
    recordButton.classList.add("is-recording");
    recordButton.textContent = isPaused ? "Resume Notes" : "Pause Notes";
    if (stopRecordingButton) {
      stopRecordingButton.hidden = false;
      stopRecordingButton.disabled = false;
    }
    return;
  }

  recordButton.classList.remove("is-recording");
  recordButton.textContent = "Record Notes";
  if (stopRecordingButton) {
    stopRecordingButton.hidden = true;
    stopRecordingButton.disabled = false;
  }
}

function getJobIdForDescription() {
  if (recordButton) {
    return String(recordButton.dataset.jobId || "");
  }

  if (descriptionPreview && descriptionPreview.dataset.jobId) {
    return String(descriptionPreview.dataset.jobId);
  }

  return "";
}

function resetRecordingState() {
  isUploadingRecording = false;
  if (activeAudioStream) {
    stopActiveStream();
  }

  activeAudioStream = null;
  activeRecorder = null;
  activeAudioChunks = [];
  activeRecordingJobId = "";
  setRecordingUi(false);
}

async function saveDescriptionText(jobId, descriptionText) {
  const response = await fetch(`/jobs/${jobId}/description/text`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({ summary_notes: descriptionText }),
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Notes could not be saved.");
  }

  return payload.summary_notes || payload.description_text || "";
}

function queueDescriptionSave(immediate = false) {
  if (!descriptionPreview || !recordButton) {
    return;
  }

  const jobId = getJobIdForDescription();
  if (!jobId) {
    return;
  }

  const nextValue = descriptionPreview.value;
  if (nextValue === lastSavedDescription) {
    return;
  }

  if (descriptionSaveTimer) {
    clearTimeout(descriptionSaveTimer);
    descriptionSaveTimer = null;
  }

  if (immediate) {
    descriptionSaveTimer = setTimeout(async () => {
      try {
        if (!nextValue.trim()) {
          return;
        }

        setRecordingStatus("Saving notes...");
        const savedText = await saveDescriptionText(jobId, nextValue);
        lastSavedDescription = savedText || "";
        if (descriptionPreview) {
          descriptionPreview.value = lastSavedDescription;
        }
        setRecordingStatus("");
      } catch (error) {
        setRecordingStatus(error.message, true);
      }
    }, 0);
    return;
  }

  descriptionSaveTimer = setTimeout(() => queueDescriptionSave(true), DESCRIPTION_SAVE_DELAY_MS);
}

async function uploadRecording(jobId, audioBlob) {
  const formData = new FormData();
  formData.append("audio", audioBlob, "recording.webm");

  const response = await fetch(`/jobs/${jobId}/description/audio`, {
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

  if (descriptionPreview) {
    descriptionPreview.value = payload.summary_notes || payload.description_text || "";
    lastSavedDescription = descriptionPreview.value || "";
  }

  return payload;
}

function stopActiveStream() {
  if (!activeAudioStream) {
    return;
  }

  for (const track of activeAudioStream.getTracks()) {
    track.stop();
  }
  activeAudioStream = null;
}

async function startRecording() {
  if (!recordButton) {
    return;
  }

  const jobId = recordButton.dataset.jobId;
  if (!jobId) {
    setRecordingStatus("No active job is available.", true);
    return;
  }

  if (!navigator.mediaDevices || !window.MediaRecorder) {
    setRecordingStatus("This browser does not support secure audio recording.", true);
    return;
  }

  setRecordingStatus("Preparing recorder...");
  activeAudioChunks = [];
  activeAudioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  activeRecorder = new MediaRecorder(activeAudioStream);
  activeRecordingJobId = jobId;

  activeRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      activeAudioChunks.push(event.data);
    }
  });

  activeRecorder.addEventListener("pause", () => {
    setRecordingUi(true, true);
    setRecordingStatus("Recording paused.");
  });

  activeRecorder.addEventListener("resume", () => {
    setRecordingUi(true, false);
    setRecordingStatus("Recording notes...");
  });

  activeRecorder.addEventListener("stop", async () => {
    stopActiveStream();
    try {
      const audioBlob = new Blob(activeAudioChunks, { type: "audio/webm" });
      isUploadingRecording = true;
      setRecordingUi(false, false, true);
      setRecordingStatus("Uploading recording for transcription...");
      await uploadRecording(activeRecordingJobId, audioBlob);
      setRecordingStatus("Notes updated.");
    } catch (error) {
      setRecordingStatus(error.message, true);
    } finally {
      resetRecordingState();
    }
  });

  activeRecorder.start();
  setRecordingUi(true, false);
  setRecordingStatus("Recording notes...");
}

function pauseOrResumeRecording() {
  if (!activeRecorder) {
    return;
  }

  if (!activeRecorder.pause || !activeRecorder.resume) {
    setRecordingStatus("Pause/resume is not supported in this browser.");
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

function stopRecording() {
  if (!activeRecorder || isUploadingRecording || activeRecorder.state === "inactive") {
    return;
  }

  if (activeRecorder.state === "paused") {
    activeRecorder.resume();
  }

  activeRecorder.stop();
}

if (recordButton) {
  recordButton.addEventListener("click", async () => {
    if (isUploadingRecording) {
      return;
    }

    if (activeRecorder) {
      pauseOrResumeRecording();
      return;
    }

    try {
      await startRecording();
    } catch (error) {
      resetRecordingState();
      setRecordingStatus(error.message || "Recording could not start.", true);
    }
  });
}

if (stopRecordingButton) {
  stopRecordingButton.addEventListener("click", () => {
    if (isUploadingRecording) {
      return;
    }

    stopRecording();
  });
}

if (descriptionPreview) {
  descriptionPreview.addEventListener("input", () => {
    queueDescriptionSave(false);
  });

  descriptionPreview.addEventListener("blur", () => {
    queueDescriptionSave(true);
  });
}

if (activeTicketForm && activeTicketInput) {
  let initialTicketNumber = (activeTicketInput.value || "").trim();
  activeTicketInput.addEventListener("change", () => {
    const nextTicketNumber = (activeTicketInput.value || "").trim().toUpperCase();
    if (nextTicketNumber === initialTicketNumber) {
      return;
    }

    initialTicketNumber = nextTicketNumber;
    activeTicketInput.value = nextTicketNumber;
    activeTicketForm.submit();
  });
}
