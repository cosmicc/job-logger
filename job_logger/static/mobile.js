const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || "";
const recordButton = document.getElementById("record-description-button");
const recordingStatus = document.getElementById("recording-status");
const descriptionPreview = document.getElementById("description-preview");

let activeRecorder = null;
let activeAudioChunks = [];
let activeAudioStream = null;

function setRecordingStatus(message, isError = false) {
  if (!recordingStatus) {
    return;
  }

  recordingStatus.textContent = message;
  recordingStatus.classList.toggle("error-text", isError);
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
    descriptionPreview.value = payload.description_text || "";
  }
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

  activeAudioChunks = [];
  activeAudioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  activeRecorder = new MediaRecorder(activeAudioStream);

  activeRecorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size > 0) {
      activeAudioChunks.push(event.data);
    }
  });

  activeRecorder.addEventListener("stop", async () => {
    recordButton.classList.remove("is-recording");
    recordButton.innerHTML = recordButton.dataset.originalHtml;
    stopActiveStream();
    try {
      const audioBlob = new Blob(activeAudioChunks, { type: "audio/webm" });
      setRecordingStatus("Uploading recording for transcription...");
      await uploadRecording(jobId, audioBlob);
      setRecordingStatus("Description updated.");
    } catch (error) {
      setRecordingStatus(error.message, true);
    } finally {
      activeRecorder = null;
      activeAudioChunks = [];
    }
  });

  recordButton.dataset.originalHtml = recordButton.innerHTML;
  recordButton.classList.add("is-recording");
  recordButton.textContent = "Stop Recording";
  activeRecorder.start();
  setRecordingStatus("Recording description...");
}

if (recordButton) {
  recordButton.addEventListener("click", async () => {
    if (activeRecorder && activeRecorder.state === "recording") {
      activeRecorder.stop();
      return;
    }

    try {
      await startRecording();
    } catch (error) {
      stopActiveStream();
      setRecordingStatus(error.message || "Recording could not start.", true);
    }
  });
}

