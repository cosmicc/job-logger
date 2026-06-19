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
              const queuedTimers = [];
              const canceledTimerIds = new Set();
              const submittedSummaries = [];
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
              const recordingStatusElement = {
                classList: noopClassList,
                textContent: "",
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
                  return null;
                },
                querySelectorAll(selector) {
                  if (selector === ".job-description") {
                    return [descriptionTextarea];
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
                fetch: async (_url, requestOptions) => {
                  const submittedPayload = JSON.parse(requestOptions.body);
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
