"""Regression tests for browser-side mobile workflow JavaScript."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def run_mobile_javascript_harness(tmp_path: Path, javascript_assertions: str) -> None:
    """Execute production mobile.js inside a minimal browser-like Node context."""

    node_path = shutil.which("node")
    if node_path is None:
        pytest.skip("Node.js is required to execute mobile.js.")

    # repository_root is the project checkout that owns the source-controlled
    # mobile JavaScript file under test.
    repository_root = Path(__file__).resolve().parents[1]
    # mobile_script_path is read by the Node harness so the test executes the
    # production browser script instead of a copied or simplified version.
    mobile_script_path = repository_root / "job_logger" / "static" / "mobile.js"
    # harness_path keeps the temporary Node test outside source control while
    # still letting pytest report the exact browser-side assertion failure.
    harness_path = tmp_path / "mobile_script_test.js"
    # indented_assertions are inserted into the async Node harness after
    # production mobile.js has registered event handlers and global functions.
    indented_assertions = textwrap.indent(textwrap.dedent(javascript_assertions).strip(), "              ")
    harness_source = (
        textwrap.dedent(
            """
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            (async () => {
              const mobileScript = fs.readFileSync(MOBILE_SCRIPT_PATH, "utf8");
              const eventHandlers = {};
              const windowEventHandlers = {};
              const queuedTimers = [];
              const canceledTimerIds = new Set();
              const submittedSummaries = [];
              const aiCleanupRequests = [];
              const noopClassList = {
                add() {},
                remove() {},
                toggle() {},
              };

              const descriptionTextarea = {
                dataset: {jobId: "job-1"},
                value: "",
                addEventListener(eventName, handler) {
                  eventHandlers[eventName] = handler;
                },
              };
              const recordingStatusHistory = [];
              let recordingStatusText = "";
              const recordingStatusElement = {
                classList: noopClassList,
                get textContent() {
                  return recordingStatusText;
                },
                set textContent(nextText) {
                  recordingStatusText = nextText;
                  recordingStatusHistory.push(nextText);
                },
              };
              const aiCleanupStatusElement = {
                classList: noopClassList,
                textContent: "",
              };
              const aiCleanupButton = {
                classList: noopClassList,
                dataset: {
                  cleanupUrl: "/jobs/job-1/summary/cleanup",
                  jobId: "job-1",
                },
                disabled: false,
                eventHandlers: {},
                addEventListener(eventName, handler) {
                  this.eventHandlers[eventName] = handler;
                },
                setAttribute() {},
              };
              const csrfMetaElement = {
                getAttribute(attributeName) {
                  return attributeName === "content" ? "csrf-token" : "";
                },
              };
              let nextTimerId = 1;

              function fakeSetTimeout(callback) {
                const timerId = nextTimerId;
                nextTimerId += 1;
                queuedTimers.push({id: timerId, callback});
                return timerId;
              }

              function fakeClearTimeout(timerId) {
                canceledTimerIds.add(timerId);
              }

              function runQueuedTimers() {
                while (queuedTimers.length > 0) {
                  const queuedTimer = queuedTimers.shift();
                  if (!canceledTimerIds.has(queuedTimer.id)) {
                    queuedTimer.callback();
                  }
                }
              }

              const fakeDocument = {
                addEventListener() {},
                querySelector(selector) {
                  if (selector === 'meta[name="csrf-token"]') {
                    return csrfMetaElement;
                  }
                  if (selector === '.job-description[data-job-id="job-1"]') {
                    return descriptionTextarea;
                  }
                  if (selector === '.recording-status[data-job-id="job-1"]') {
                    return recordingStatusElement;
                  }
                  if (selector === '[data-ai-cleanup-status][data-job-id="job-1"]') {
                    return aiCleanupStatusElement;
                  }
                  return null;
                },
                querySelectorAll(selector) {
                  if (selector === ".job-description") {
                    return [descriptionTextarea];
                  }
                  if (selector === "[data-ai-cleanup-button]") {
                    return [aiCleanupButton];
                  }
                  return [];
                },
                getElementById() {
                  return null;
                },
              };

              const browserContext = {
                clearTimeout: fakeClearTimeout,
                console,
                document: fakeDocument,
                fetch: async (url, requestOptions) => {
                  const submittedPayload = JSON.parse(requestOptions.body);
                  if (url.endsWith("/summary/cleanup")) {
                    aiCleanupRequests.push(submittedPayload.summary_notes);
                    return {
                      ok: true,
                      json: async () => ({
                        description_text: "Cleaned active summary.",
                        summary_notes: "Cleaned active summary.",
                      }),
                    };
                  }

                  submittedSummaries.push(submittedPayload.summary_notes);
                  return {
                    ok: true,
                    json: async () => ({
                      description_text: String(submittedPayload.summary_notes || "").trim(),
                      summary_notes: String(submittedPayload.summary_notes || "").trim(),
                    }),
                  };
                },
                MediaRecorder: undefined,
                navigator: {},
                setTimeout: fakeSetTimeout,
                WebSocket: function WebSocket() {},
                window: {
                  addEventListener(eventName, handler) {
                    windowEventHandlers[eventName] = handler;
                  },
                  clearTimeout: fakeClearTimeout,
                  location: {
                    host: "example.test",
                    protocol: "https:",
                  },
                  setTimeout: fakeSetTimeout,
                },
              };

              vm.runInNewContext(mobileScript, browserContext, {filename: "mobile.js"});
            ASSERTIONS
            })().catch((error) => {
              console.error(error);
              process.exit(1);
            });
            """
        )
        .replace("MOBILE_SCRIPT_PATH", repr(str(mobile_script_path)))
        .replace("ASSERTIONS", indented_assertions)
    )
    harness_path.write_text(harness_source, encoding="utf-8")

    result = subprocess.run(
        [node_path, str(harness_path)],
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_mobile_summary_autosave_does_not_replace_typing_buffer(tmp_path: Path) -> None:
    """Manual mobile note autosave must not remove spaces from the active textarea."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        assert.strictEqual(typeof eventHandlers.input, "function");

        descriptionTextarea.value = "First word ";
        eventHandlers.input();
        runQueuedTimers();

        await Promise.resolve();
        await Promise.resolve();
        await new Promise((resolve) => setImmediate(resolve));

        assert.deepStrictEqual(submittedSummaries, ["First word "]);
        assert.strictEqual(descriptionTextarea.value, "First word ");
        """,
    )


def test_mobile_ai_cleanup_replaces_and_saves_summary(tmp_path: Path) -> None:
    """AI cleanup should replace the active textarea and persist the result."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        assert.strictEqual(typeof aiCleanupButton.eventHandlers.click, "function");

        descriptionTextarea.value = "fixd the vpn and did tests";
        aiCleanupButton.eventHandlers.click();

        await Promise.resolve();
        await Promise.resolve();
        await new Promise((resolve) => setImmediate(resolve));

        assert.deepStrictEqual(aiCleanupRequests, ["fixd the vpn and did tests"]);
        assert.deepStrictEqual(submittedSummaries, ["Cleaned active summary."]);
        assert.strictEqual(descriptionTextarea.value, "Cleaned active summary.");
        assert.strictEqual(aiCleanupStatusElement.textContent, "Summary cleaned up.");
        assert.strictEqual(aiCleanupButton.disabled, false);
        """,
    )


def test_mobile_audio_stream_pastes_only_final_transcript(tmp_path: Path) -> None:
    """Interim audio text must not overwrite manual notes before the final transcript."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        assert.strictEqual(typeof browserContext.handleAudioStreamMessage, "function");
        assert.strictEqual(typeof eventHandlers.input, "function");

        descriptionTextarea.value = "Manual text while recording";
        browserContext.handleAudioStreamMessage(
          "job-1",
          JSON.stringify({
            type: "partial",
            summary_notes: "Partial audio text",
            description_text: "Partial audio text",
          }),
          {},
        );

        assert.strictEqual(descriptionTextarea.value, "Manual text while recording");
        assert.strictEqual(recordingStatusElement.textContent, "Transcribing audio...");

        descriptionTextarea.value = "Manual text before final ";
        eventHandlers.input();
        browserContext.handleAudioStreamMessage(
          "job-1",
          JSON.stringify({
            type: "final",
            summary_notes: "Final audio transcript.",
            description_text: "Final audio transcript.",
          }),
          {},
        );
        runQueuedTimers();

        await Promise.resolve();
        await Promise.resolve();
        await new Promise((resolve) => setImmediate(resolve));

        assert.deepStrictEqual(submittedSummaries, []);
        assert.strictEqual(descriptionTextarea.value, "Final audio transcript.");
        """,
    )


def test_mobile_audio_stop_shows_upload_and_conversion_statuses(tmp_path: Path) -> None:
    """Stopping audio should not let final chunk acknowledgements say recording."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        let lastSocket = null;
        const stoppedTracks = [];

        class FakeWebSocket {
          static OPEN = 1;
          static CLOSED = 3;

          constructor() {
            this.readyState = FakeWebSocket.OPEN;
            this.bufferedAmount = 0;
            this.handlers = {};
            lastSocket = this;
          }

          addEventListener(eventName, handler) {
            this.handlers[eventName] = handler;
            if (eventName === "open") {
              Promise.resolve().then(() => handler({}));
            }
          }

          send(message) {
            if (typeof message !== "string") {
              this.handlers.message({
                data: JSON.stringify({type: "chunk_received"}),
              });
              return;
            }

            const payload = JSON.parse(message);
            if (payload.type === "start") {
              this.handlers.message({data: JSON.stringify({type: "ready"})});
              return;
            }

            if (payload.type === "finish") {
              this.handlers.message({
                data: JSON.stringify({type: "transcription_started", phase: "final"}),
              });
              this.handlers.message({
                data: JSON.stringify({
                  type: "final",
                  summary_notes: "Finished transcript.",
                  description_text: "Finished transcript.",
                }),
              });
            }
          }

          close() {
            this.readyState = FakeWebSocket.CLOSED;
          }
        }

        class FakeMediaRecorder {
          static isTypeSupported() {
            return true;
          }

          constructor() {
            this.mimeType = "audio/webm";
            this.state = "inactive";
            this.handlers = {};
          }

          addEventListener(eventName, handler) {
            this.handlers[eventName] = handler;
          }

          start() {
            this.state = "recording";
            this.handlers.start({});
          }

          stop() {
            this.state = "inactive";
            this.handlers.dataavailable({data: {size: 128}});
            this.handlers.stop({});
          }
        }

        browserContext.WebSocket = FakeWebSocket;
        browserContext.MediaRecorder = FakeMediaRecorder;
        browserContext.window.MediaRecorder = FakeMediaRecorder;
        browserContext.navigator.mediaDevices = {
          getUserMedia: async () => ({
            getTracks: () => [
              {
                stop() {
                  stoppedTracks.push("stopped");
                },
              },
            ],
          }),
        };

        await browserContext.startRecording("job-1");
        assert.strictEqual(lastSocket.readyState, FakeWebSocket.OPEN);

        await browserContext.stopRecording("job-1");
        await Promise.resolve();
        await Promise.resolve();
        await new Promise((resolve) => setImmediate(resolve));

        const sendingIndex = recordingStatusHistory.lastIndexOf("Sending data to server...");
        const convertingIndex = recordingStatusHistory.lastIndexOf("Converting audio to text...");
        const completeIndex = recordingStatusHistory.lastIndexOf("Conversion complete.");
        const recordingAfterStopIndex = recordingStatusHistory.findIndex(
          (message, index) => index > sendingIndex && message === "Recording audio...",
        );

        assert.notStrictEqual(sendingIndex, -1);
        assert.ok(convertingIndex > sendingIndex);
        assert.ok(completeIndex > convertingIndex);
        assert.strictEqual(recordingAfterStopIndex, -1);
        assert.strictEqual(recordingStatusElement.textContent, "Conversion complete.");
        assert.strictEqual(descriptionTextarea.value, "Finished transcript.");
        assert.ok(stoppedTracks.length >= 1);
        """,
    )
