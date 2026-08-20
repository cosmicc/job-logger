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
    mobile_script_path = repository_root / "ticket_pilot" / "static" / "mobile.js"
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
              const mobileScript = `${fs.readFileSync(MOBILE_SCRIPT_PATH, "utf8")}
              ;this.__mobileTestApi = {
                consumeCustomerNoteOverlayJobId,
                consumeNaturalWorkFocus,
                focusNaturalTextEntry,
                jobDateDisplayTextForDateValue,
                jobDateLabelForDateValue,
                rememberCustomerNoteOverlayForJob,
                rememberNaturalWorkFocus,
                setDateWeekdayLabelText,
                updateActiveDurationDisplay,
                updateActiveTimeDisplays,
                updateActiveTicketDisplay,
                weekdayNameForDateValue,
              };`;
              const eventHandlers = {};
              const windowEventHandlers = {};
              const queuedTimers = [];
              const canceledTimerIds = new Set();
              const submittedSummaries = [];
              const aiCleanupRequests = [];
              let aiCleanupFailureMessage = "";

              function createTrackedClassList() {
                const classNames = new Set();
                return {
                  add(...names) {
                    for (const name of names) {
                      if (name) {
                        classNames.add(name);
                      }
                    }
                  },
                  remove(...names) {
                    for (const name of names) {
                      classNames.delete(name);
                    }
                  },
                  toggle(name, force) {
                    const shouldAdd = force === undefined ? !classNames.has(name) : Boolean(force);
                    if (shouldAdd) {
                      classNames.add(name);
                    } else {
                      classNames.delete(name);
                    }
                    return shouldAdd;
                  },
                  contains(name) {
                    return classNames.has(name);
                  },
                  toArray() {
                    return Array.from(classNames).sort();
                  },
                };
              }

              function collectTextFromChildren(children) {
                return children.map((child) => {
                  if (child && typeof child === "object" && "textContent" in child) {
                    return child.textContent;
                  }
                  return String(child);
                }).join("");
              }

              function createFakeElement(tagName = "span") {
                let elementText = "";
                return {
                  attributes: {},
                  children: [],
                  classList: createTrackedClassList(),
                  className: "",
                  dataset: {},
                  disabled: false,
                  eventHandlers: {},
                  tagName: tagName.toUpperCase(),
                  value: "",
                  addEventListener(eventName, handler) {
                    this.eventHandlers[eventName] = handler;
                  },
                  append(...nextChildren) {
                    this.children.push(...nextChildren);
                    elementText = collectTextFromChildren(this.children);
                  },
                  getAttribute(attributeName) {
                    return this.attributes[attributeName] || "";
                  },
                  querySelector() {
                    return null;
                  },
                  replaceChildren(...nextChildren) {
                    this.children = [...nextChildren];
                    elementText = collectTextFromChildren(this.children);
                  },
                  setAttribute(attributeName, value) {
                    this.attributes[attributeName] = String(value);
                  },
                  get textContent() {
                    return elementText;
                  },
                  set textContent(nextText) {
                    elementText = String(nextText || "");
                    this.children = [];
                  },
                };
              }

              const descriptionTextarea = createFakeElement("textarea");
              descriptionTextarea.dataset = {jobId: "job-1"};
              descriptionTextarea.addEventListener = (eventName, handler) => {
                eventHandlers[eventName] = handler;
              };
              const recordingStatusHistory = [];
              let recordingStatusText = "";
              const recordingStatusElement = createFakeElement("p");
              recordingStatusElement.replaceChildren = (...nextChildren) => {
                recordingStatusElement.children = [...nextChildren];
                recordingStatusText = collectTextFromChildren(recordingStatusElement.children);
                recordingStatusHistory.push(recordingStatusText);
              };
              Object.defineProperty(recordingStatusElement, "textContent", {
                get() {
                  return recordingStatusText;
                },
                set(nextText) {
                  recordingStatusText = String(nextText || "");
                  recordingStatusElement.children = [];
                  recordingStatusHistory.push(recordingStatusText);
                },
              });
              const recordButtonLabel = createFakeElement("span");
              recordButtonLabel.dataset = {};
              recordButtonLabel.textContent = "Record";
              const recordButton = createFakeElement("button");
              recordButton.dataset = {jobId: "job-1"};
              const aiCleanupButton = createFakeElement("button");
              aiCleanupButton.dataset = {
                cleanupUrl: "/jobs/job-1/summary/cleanup",
                jobId: "job-1",
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
                  if (selector === '.record-notes-button[data-job-id="job-1"]') {
                    return recordButton;
                  }
                  if (selector === '.record-notes-button[data-job-id="job-1"] [data-record-audio-label]') {
                    return recordButtonLabel;
                  }
                  return null;
                },
                querySelectorAll(selector) {
                  if (selector === ".record-notes-button") {
                    return [recordButton];
                  }
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
                createElement(tagName) {
                  return createFakeElement(tagName);
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
                    if (aiCleanupFailureMessage) {
                      return {
                        ok: false,
                        status: 400,
                        json: async () => ({detail: aiCleanupFailureMessage}),
                      };
                    }

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


def test_mobile_date_label_uses_near_current_relative_text(tmp_path: Path) -> None:
    """Work in Progress date labels should show only Today, Yesterday, or Tomorrow."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        const dateDisplay = createFakeElement("span");

        assert.strictEqual(browserContext.__mobileTestApi.weekdayNameForDateValue("2026-06-16"), "Tuesday");
        assert.strictEqual(browserContext.__mobileTestApi.weekdayNameForDateValue("2026-06-20"), "Saturday");
        assert.strictEqual(browserContext.__mobileTestApi.weekdayNameForDateValue("bad-date"), "");
        assert.strictEqual(browserContext.__mobileTestApi.jobDateLabelForDateValue("2026-06-20", "2026-06-20"), "Today");
        assert.strictEqual(browserContext.__mobileTestApi.jobDateLabelForDateValue("2026-06-20", "2026-06-21"), "Yesterday");
        assert.strictEqual(browserContext.__mobileTestApi.jobDateLabelForDateValue("2026-06-22", "2026-06-21"), "Tomorrow");
        assert.strictEqual(browserContext.__mobileTestApi.jobDateLabelForDateValue("2026-06-23", "2026-06-21"), "");
        assert.strictEqual(
          browserContext.__mobileTestApi.jobDateDisplayTextForDateValue("2026-06-20", "2026-06-20"),
          "06/20/2026  (Today)",
        );
        assert.strictEqual(
          browserContext.__mobileTestApi.jobDateDisplayTextForDateValue("2026-06-20", "2026-06-21"),
          "06/20/2026  (Yesterday)",
        );
        assert.strictEqual(
          browserContext.__mobileTestApi.jobDateDisplayTextForDateValue("2026-06-22", "2026-06-21"),
          "06/22/2026  (Tomorrow)",
        );
        assert.strictEqual(
          browserContext.__mobileTestApi.jobDateDisplayTextForDateValue("2026-06-23", "2026-06-21"),
          "06/23/2026",
        );
        assert.strictEqual(browserContext.__mobileTestApi.jobDateDisplayTextForDateValue("bad-date"), "");

        browserContext.__mobileTestApi.setDateWeekdayLabelText(dateDisplay, "2026-06-20");
        assert.match(dateDisplay.textContent, /^06\\/20\\/2026(  \\((Today|Yesterday|Tomorrow)\\))?$/);
        browserContext.__mobileTestApi.setDateWeekdayLabelText(dateDisplay, "bad-date");
        assert.strictEqual(dateDisplay.textContent, "");
        """,
    )


def test_mobile_duration_is_derived_from_the_visible_canonical_times(tmp_path: Path) -> None:
    """A completed time save must not leave a stale duration label behind."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        const startTimeInput = createFakeElement("input");
        startTimeInput.dataset = {activeTimeKind: "start"};
        startTimeInput.value = "8:00 am";
        const stopTimeInput = createFakeElement("input");
        stopTimeInput.dataset = {activeTimeKind: "stop"};
        stopTimeInput.value = "10:00 am";
        const durationDisplay = createFakeElement("strong");
        durationDisplay.textContent = "15 Minutes";
        const activeJobCard = createFakeElement("section");
        activeJobCard.querySelector = (selector) => {
          if (selector.includes('data-active-time-kind="start"')) return startTimeInput;
          if (selector.includes('data-active-time-kind="stop"')) return stopTimeInput;
          if (selector === "[data-duration-display]") return durationDisplay;
          return null;
        };
        activeJobCard.querySelectorAll = () => [];
        const activeTimeForm = createFakeElement("form");
        activeTimeForm.dataset = {activeTimeKind: "start", jobId: "duration-job"};
        fakeDocument.querySelector = (selector) => (
          selector === '[data-active-job-card="duration-job"]' ? activeJobCard : null
        );

        browserContext.__mobileTestApi.updateActiveTimeDisplays(activeTimeForm, {
          job_id: "duration-job",
          rounded_start_time: "9:00 am",
          rounded_start_utc: "2026-06-16T13:00:00Z",
          rounded_stop_time: "9:15 am",
          rounded_stop_utc: "2026-06-16T13:15:00Z",
          rounded_stop_overridden: true,
          minimum_duration_minutes: 60,
          duration_label: "9 Hours",
        });

        assert.strictEqual(startTimeInput.value, "9:00 am");
        assert.strictEqual(stopTimeInput.value, "10:00 am");
        assert.strictEqual(durationDisplay.textContent, "1 Hour");

        activeTimeForm.dataset.activeTimeKind = "stop";
        browserContext.__mobileTestApi.updateActiveTimeDisplays(activeTimeForm, {
          job_id: "duration-job",
          rounded_start_time: "7:00 am",
          rounded_start_utc: "2026-06-16T11:00:00Z",
          rounded_stop_time: "10:30 am",
          rounded_stop_utc: "2026-06-16T14:30:00Z",
          rounded_stop_overridden: true,
          minimum_duration_minutes: 60,
          duration_label: "9 Hours",
        });

        assert.strictEqual(startTimeInput.value, "9:00 am");
        assert.strictEqual(stopTimeInput.value, "10:30 am");
        assert.strictEqual(stopTimeInput.dataset.minimumDurationMinutes, "60");
        assert.strictEqual(durationDisplay.textContent, "1.5 Hours");
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
        assert.deepStrictEqual(recordingStatusHistory.slice(-3), [
          "Cleaning up summary...",
          "Saving cleaned summary...",
          "Summary cleaned up.",
        ]);
        assert.strictEqual(recordingStatusElement.textContent, "Summary cleaned up.");
        assert.strictEqual(aiCleanupButton.disabled, false);
        """,
    )


def test_mobile_ai_cleanup_failure_uses_recording_status_line(tmp_path: Path) -> None:
    """AI cleanup failures should show the provider reason in the shared status line."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        aiCleanupFailureMessage = "Gemini cleanup timed out. Try again.";
        descriptionTextarea.value = "cleanup should fail";
        aiCleanupButton.eventHandlers.click();

        await Promise.resolve();
        await Promise.resolve();
        await new Promise((resolve) => setImmediate(resolve));

        assert.deepStrictEqual(aiCleanupRequests, ["cleanup should fail"]);
        assert.deepStrictEqual(submittedSummaries, []);
        assert.strictEqual(descriptionTextarea.value, "cleanup should fail");
        assert.strictEqual(recordingStatusElement.textContent, "AI cleanup failed: Gemini cleanup timed out. Try again.");
        assert.strictEqual(aiCleanupButton.disabled, false);
        """,
    )


def test_mobile_ticket_selection_locks_client_input(tmp_path: Path) -> None:
    """Selecting an open ticket should immediately make the active client read-only."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        const ticketNumberCard = createFakeElement("div");
        const ticketNumberDisplay = createFakeElement("dd");
        const ticketTitleCard = createFakeElement("div");
        const ticketTitleDisplay = createFakeElement("dd");
        const ticketDescriptionCard = createFakeElement("div");
        const ticketDescriptionDisplay = createFakeElement("dd");
        const ticketStatusInput = createFakeElement("select");
        const mobileTicketNotesButton = createFakeElement("button");
        const desktopTicketNotesButton = createFakeElement("button");
        const mobileTimeEntriesButton = createFakeElement("button");
        const desktopTimeEntriesButton = createFakeElement("button");
        const refreshedNotesButtons = [];
        const openedNotesButtons = [];
        const refreshedTimeEntriesButtons = [];
        const activeClientInput = createFakeElement("input");
        activeClientInput.type = "text";
        activeClientInput.value = "North Bay";

        const activeTicketForm = createFakeElement("form");
        activeTicketForm.id = "active-ticket-form-job-2";
        activeTicketForm.dataset = {jobId: "job-2"};
        activeTicketForm.querySelector = (selector) => {
          if (selector === "[data-active-client-source]") {
            return null;
          }
          return null;
        };

        const activeJobCard = createFakeElement("article");
        activeJobCard.querySelector = (selector) => {
          const elementsBySelector = {
            "[data-active-ticket-number-card]": ticketNumberCard,
            "[data-active-ticket-number-display]": ticketNumberDisplay,
            "[data-active-ticket-title-card]": ticketTitleCard,
            "[data-active-ticket-title-display]": ticketTitleDisplay,
            "[data-active-ticket-description-card]": ticketDescriptionCard,
            "[data-active-ticket-description-display]": ticketDescriptionDisplay,
            "[data-active-ticket-status-input]": ticketStatusInput,
          };
          return elementsBySelector[selector] || null;
        };
        activeJobCard.querySelectorAll = (selector) => {
          if (selector === "[data-ticket-notes-button]") {
            return [mobileTicketNotesButton, desktopTicketNotesButton];
          }
          if (selector === "[data-ticket-time-entries-button]") {
            return [mobileTimeEntriesButton, desktopTimeEntriesButton];
          }
          return [];
        };

        browserContext.window.TicketPilotTicketNotes = {
          openNewestForButton(button) {
            openedNotesButtons.push(button);
          },
          refreshButton(button) {
            refreshedNotesButtons.push(button);
          },
          refreshTimeEntriesButton(button) {
            refreshedTimeEntriesButtons.push(button);
          },
        };

        fakeDocument.querySelector = (selector) => {
          if (selector === '[data-active-job-card="job-2"]') {
            return activeJobCard;
          }
          if (selector === '.active-ticket-form[data-job-id="job-2"]') {
            return activeTicketForm;
          }
          if (selector === '.active-client-name-source[form="active-ticket-form-job-2"]') {
            return activeClientInput;
          }
          return null;
        };

        browserContext.__mobileTestApi.updateActiveTicketDisplay("job-2", {
          ticket_number: "T20260616.0001",
          ticket_title: "VPN access cleanup",
          ticket_description: "Remote access ticket details.",
          ticket_status: "in_progress",
        });

        assert.strictEqual(ticketNumberDisplay.textContent, "T20260616.0001");
        assert.strictEqual(ticketTitleDisplay.textContent, "VPN access cleanup");
        assert.strictEqual(ticketDescriptionDisplay.textContent, "Remote access ticket details.");
        assert.strictEqual(ticketStatusInput.value, "in_progress");
        assert.strictEqual(mobileTicketNotesButton.dataset.ticketNotesTicketNumber, "T20260616.0001");
        assert.strictEqual(desktopTicketNotesButton.dataset.ticketNotesTicketNumber, "T20260616.0001");
        assert.strictEqual(mobileTimeEntriesButton.dataset.ticketTimeEntriesTicketNumber, "T20260616.0001");
        assert.strictEqual(desktopTimeEntriesButton.dataset.ticketTimeEntriesTicketNumber, "T20260616.0001");
        assert.deepStrictEqual(refreshedNotesButtons, [mobileTicketNotesButton]);
        assert.deepStrictEqual(refreshedTimeEntriesButtons, [mobileTimeEntriesButton]);
        assert.strictEqual(activeClientInput.readOnly, true);
        assert.strictEqual(activeClientInput.getAttribute("aria-readonly"), "true");
        assert.strictEqual(activeClientInput.classList.contains("is-locked-client-input"), true);

        ticketDescriptionCard.classList.add("is-hidden");
        browserContext.__mobileTestApi.updateActiveTicketDisplay("job-2", {
            ticket_number: "T20260616.0003",
            ticket_title: "Ticket without description",
            ticket_description: "",
            ticket_status: "in_progress",
            open_customer_note_overlay: true,
        });

        assert.strictEqual(ticketDescriptionDisplay.textContent, "No description exists for this ticket.");
        assert.strictEqual(ticketDescriptionCard.classList.contains("is-hidden"), false);
        assert.deepStrictEqual(openedNotesButtons, [mobileTicketNotesButton]);
        assert.deepStrictEqual(refreshedNotesButtons, [mobileTicketNotesButton]);
        """,
    )


def test_mobile_company_selection_stays_editable_until_ticket() -> None:
    """Selecting a company should clear stale tickets without locking the input."""

    repository_root = Path(__file__).resolve().parents[1]
    mobile_script = (repository_root / "ticket_pilot" / "static" / "mobile.js").read_text(encoding="utf-8")

    assert "function resetActiveTicketPickerForClientChange" in mobile_script
    assert "activeTicketLookupGenerations.set(" in mobile_script
    assert "activeTicketLookupLoaded.delete(ticketPicker);" in mobile_script
    assert 'resetActiveTicketPickerForClientChange(jobId, "Loading open tickets...");' in mobile_script
    assert "companyInput.readOnly = true;" not in mobile_script
    assert "lockActiveClientInputForSelectedTicket(jobId);" in mobile_script


def test_customer_note_overlay_job_marker_is_consumed_once(tmp_path: Path) -> None:
    """The service-call overlay marker should be same-tab and one-time."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        const storedValues = new Map();
        browserContext.window.sessionStorage = {
          getItem(key) {
            return storedValues.has(key) ? storedValues.get(key) : null;
          },
          removeItem(key) {
            storedValues.delete(key);
          },
          setItem(key, value) {
            storedValues.set(key, value);
          },
        };

        browserContext.__mobileTestApi.rememberCustomerNoteOverlayForJob("job-2");
        assert.strictEqual(
          browserContext.__mobileTestApi.consumeCustomerNoteOverlayJobId(),
          "job-2",
        );
        assert.strictEqual(
          browserContext.__mobileTestApi.consumeCustomerNoteOverlayJobId(),
          "",
        );
        """,
    )


def test_natural_work_focus_is_job_specific_and_places_cursor_at_end(tmp_path: Path) -> None:
    """Reload focus requests should be one-time, and typing should continue at the end."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        const storedValues = new Map();
        browserContext.window.sessionStorage = {
          getItem(key) {
            return storedValues.has(key) ? storedValues.get(key) : null;
          },
          removeItem(key) {
            storedValues.delete(key);
          },
          setItem(key, value) {
            storedValues.set(key, value);
          },
        };

        browserContext.__mobileTestApi.rememberNaturalWorkFocus("job-2", "summary");
        const storedFocus = browserContext.__mobileTestApi.consumeNaturalWorkFocus();
        assert.strictEqual(storedFocus.jobId, "job-2");
        assert.strictEqual(storedFocus.target, "summary");
        assert.strictEqual(browserContext.__mobileTestApi.consumeNaturalWorkFocus(), null);

        let focused = false;
        let selectedRange = null;
        const summaryControl = {
          disabled: false,
          readOnly: false,
          value: "Existing summary",
          focus() {
            focused = true;
          },
          setSelectionRange(start, end) {
            selectedRange = [start, end];
          },
        };
        assert.strictEqual(
          browserContext.__mobileTestApi.focusNaturalTextEntry(summaryControl),
          true,
        );
        assert.strictEqual(focused, true);
        assert.deepStrictEqual(selectedRange, [16, 16]);
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
        assert.strictEqual(recordingStatusElement.classList.contains("is-loading"), false);
        assert.strictEqual(recordingStatusElement.children.length, 0);

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
        assert.strictEqual(recordingStatusElement.classList.contains("is-loading"), false);
        """,
    )


def test_mobile_audio_stop_shows_upload_and_conversion_statuses(tmp_path: Path) -> None:
    """Stopping audio should not let final chunk acknowledgements say recording."""

    run_mobile_javascript_harness(
        tmp_path,
        """
        let lastSocket = null;
        const stoppedTracks = [];
        let finishTranscription = null;

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
              finishTranscription = () => {
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
              };
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

        assert.strictEqual(recordButton.disabled, true);
        assert.strictEqual(recordButton.classList.contains("is-loading"), true);
        assert.strictEqual(recordButton.attributes["aria-busy"], "true");
        assert.strictEqual(recordButtonLabel.textContent, "Record");
        assert.strictEqual(recordingStatusElement.textContent, "Converting audio to text...");
        assert.strictEqual(recordingStatusElement.classList.contains("is-loading"), false);
        assert.strictEqual(recordingStatusElement.children.length, 0);

        assert.strictEqual(typeof finishTranscription, "function");
        finishTranscription();
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
        assert.strictEqual(recordingStatusElement.classList.contains("is-loading"), false);
        assert.strictEqual(recordButton.disabled, false);
        assert.strictEqual(recordButton.classList.contains("is-loading"), false);
        assert.strictEqual(recordButton.attributes["aria-busy"], "false");
        assert.strictEqual(descriptionTextarea.value, "Finished transcript.");
        assert.ok(stoppedTracks.length >= 1);
        """,
    )
