"""Regression tests for browser-side review workflow JavaScript."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_open_ticket_renderers_share_status_and_company_metadata() -> None:
    """Review and Work in Progress ticket cards should expose the same visible metadata."""

    repository_root = Path(__file__).resolve().parents[1]
    mobile_script = (repository_root / "job_logger" / "static" / "mobile.js").read_text(encoding="utf-8")
    review_script = (repository_root / "job_logger" / "static" / "review.js").read_text(encoding="utf-8")
    expected_company_line = 'const companyName = ticketOption.company_name || "Unknown company";'
    expected_meta_line = 'createTicketOptionSpan("ticket-option-meta", `${ticketStatus} | ${companyName}`),'

    assert expected_company_line in mobile_script
    assert expected_company_line in review_script
    assert expected_meta_line in mobile_script
    assert expected_meta_line in review_script


def test_ticket_notes_overlay_list_cards_show_titles_only() -> None:
    """Ticket note selection cards should leave metadata in detail."""

    repository_root = Path(__file__).resolve().parents[1]
    ticket_notes_script = (repository_root / "job_logger" / "static" / "ticket-notes.js").read_text(encoding="utf-8")

    assert "metaParts.push(`From ${createdBy}`);" in ticket_notes_script
    assert 'const title = ticketNotesCreateElement("span", "ticket-note-list-title"' in ticket_notes_script
    assert "noteButton.append(title);" in ticket_notes_script
    assert "noteButton.append(preview)" not in ticket_notes_script
    assert "noteButton.append(meta)" not in ticket_notes_script


def test_ticket_time_entries_overlay_list_cards_show_resource_and_range() -> None:
    """Time-entry selection cards should show resource/range while detail shows summary."""

    repository_root = Path(__file__).resolve().parents[1]
    ticket_notes_script = (repository_root / "job_logger" / "static" / "ticket-notes.js").read_text(encoding="utf-8")

    assert 'const resource = ticketNotesCreateElement(' in ticket_notes_script
    assert '"ticket-time-entry-list-resource"' in ticket_notes_script
    assert '"ticket-time-entry-list-range"' in ticket_notes_script
    assert "function ticketNotesResourceNameForDisplay(rawResourceName)" in ticket_notes_script
    assert 'ticketNotesResourceNameForDisplay(timeEntry.resource_name)' in ticket_notes_script
    assert '"ticket-note-meta ticket-time-entry-detail-range muted-text"' in ticket_notes_script
    assert "timeEntryButton.append(resource);" in ticket_notes_script
    assert "timeEntryButton.append(range);" in ticket_notes_script
    assert "renderTicketTimeEntryDetail(detailElement, timeEntry)" in ticket_notes_script
    assert "ticketNotesSafeString(timeEntry.summary_notes)" in ticket_notes_script


def test_workflow_status_messages_share_one_line() -> None:
    """Save, recording, and AI cleanup messages should overwrite one shared status line."""

    repository_root = Path(__file__).resolve().parents[1]
    mobile_template = (repository_root / "job_logger" / "templates" / "mobile.html").read_text(encoding="utf-8")
    review_template = (repository_root / "job_logger" / "templates" / "review.html").read_text(encoding="utf-8")

    assert 'class="recording-status workflow-status-line"' in mobile_template
    assert "data-active-save-status" in mobile_template
    assert 'class="recording-status workflow-status-line"' in review_template
    assert "data-review-autosave-status" in review_template
    assert "data-review-recording-status" in review_template
    assert "data-ai-cleanup-status" in review_template


def test_review_field_input_posts_autosave_request(tmp_path: Path) -> None:
    """Review edits must save through the background save endpoint without a button."""

    node_path = shutil.which("node")
    if node_path is None:
        pytest.skip("Node.js is required to execute review.js.")

    # repository_root is the project checkout containing the production review
    # browser script under test.
    repository_root = Path(__file__).resolve().parents[1]
    # review_script_path is read by the Node harness so the test exercises the
    # source-controlled script instead of a copied test double.
    review_script_path = repository_root / "job_logger" / "static" / "review.js"
    # harness_path keeps the temporary JavaScript runner out of source control.
    harness_path = tmp_path / "review_autosave_test.js"
    harness_path.write_text(
        textwrap.dedent(
            f"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            (async () => {{
              const reviewScript = fs.readFileSync({str(review_script_path)!r}, "utf8");
              const queuedTimers = [];
              const canceledTimerIds = new Set();
              const submittedRequests = [];
              const aiCleanupRequests = [];
              const noopClassList = {{
                remove() {{}},
                toggle() {{}},
              }};
              let nextTimerId = 1;

              function fakeSetTimeout(callback) {{
                const timerId = nextTimerId;
                nextTimerId += 1;
                queuedTimers.push({{id: timerId, callback}});
                return timerId;
              }}

              function fakeClearTimeout(timerId) {{
                canceledTimerIds.add(timerId);
              }}

              function runQueuedTimers() {{
                while (queuedTimers.length > 0) {{
                  const queuedTimer = queuedTimers.shift();
                  if (!canceledTimerIds.has(queuedTimer.id)) {{
                    queuedTimer.callback();
                  }}
                }}
              }}

              function makeControl({{tagName = "INPUT", type = "text", name, value = "", disabled = false}}) {{
                return {{
                  attributes: {{}},
                  disabled,
                  dataset: {{}},
                  name,
                  tagName,
                  type,
                  value,
                  eventHandlers: {{}},
                  addEventListener(eventName, handler) {{
                    this.eventHandlers[eventName] = handler;
                  }},
                  getAttribute(attributeName) {{
                    return this.attributes[attributeName] || "";
                  }},
                  setAttribute(attributeName, value) {{
                    this.attributes[attributeName] = String(value);
                  }},
                }};
              }}

              function makeElement(tagName = "DIV") {{
                return {{
                  attributes: {{}},
                  children: [],
                  classList: noopClassList,
                  className: "",
                  disabled: false,
                  eventHandlers: {{}},
                  tagName,
                  textContent: "",
                  value: "",
                  addEventListener(eventName, handler) {{
                    this.eventHandlers[eventName] = handler;
                  }},
                  append(...children) {{
                    this.children.push(...children);
                    this.textContent = this.children.map((child) => child.textContent || "").join("");
                  }},
                  getAttribute(attributeName) {{
                    return this.attributes[attributeName] || "";
                  }},
                  replaceChildren(...children) {{
                    this.children = [...children];
                    this.textContent = this.children.map((child) => child.textContent || "").join("");
                  }},
                  setAttribute(attributeName, value) {{
                    this.attributes[attributeName] = String(value);
                  }},
                }};
              }}

              const csrfInput = makeControl({{type: "hidden", name: "csrf_token", value: "csrf-token"}});
              const ticketStatusSelect = makeControl({{tagName: "SELECT", name: "ticket_status", value: "complete"}});
              const jobDateInput = makeControl({{type: "date", name: "job_date", value: "2026-06-16"}});
              const startTimeInput = makeControl({{name: "start_time", value: "8:00 am"}});
              const endTimeInput = makeControl({{name: "end_time", value: "8:15 am"}});
              const summaryTextarea = makeControl({{tagName: "TEXTAREA", name: "summary_notes", value: "Initial review notes."}});
              const companyIdInput = makeControl({{type: "hidden", name: "autotask_company_id", value: ""}});
              companyIdInput.dataset = {{reviewCompanyIdInput: ""}};
              const companyResults = makeElement("DIV");
              const companyStatus = makeElement("P");
              const reviewCompanyCard = {{
                querySelector(selector) {{
                  if (selector === "[data-company-results]") {{
                    return companyResults;
                  }}
                  if (selector === "[data-company-status]") {{
                    return companyStatus;
                  }}
                  return null;
                }},
              }};
              const reviewCompanyInput = makeControl({{name: "client_name", value: ""}});
              reviewCompanyInput.dataset = {{
                reviewCompanyInput: "",
                reviewClientNameInput: "",
                reviewClientSaveUrl: "/review/job-1/client",
              }};
              reviewCompanyInput.closest = (selector) => {{
                if (selector === "form") {{
                  return reviewAutosaveForm;
                }}
                if (selector === ".review-client-name-card") {{
                  return reviewCompanyCard;
                }}
                return null;
              }};
              const reviewControls = [
                csrfInput,
                ticketStatusSelect,
                jobDateInput,
                startTimeInput,
                endTimeInput,
                summaryTextarea,
                reviewCompanyInput,
                companyIdInput,
              ];
              const aiCleanupStatus = {{
                classList: noopClassList,
                textContent: "",
              }};
              const reviewDateWeekdayLabel = makeElement("SPAN");
              const reviewAutosaveForm = {{
                dataset: {{reviewSaveUrl: "/review/job-1/save"}},
                querySelector(selector) {{
                  if (selector === 'textarea[name="summary_notes"]') {{
                    return summaryTextarea;
                  }}
                  if (selector === "[data-review-company-id-input]") {{
                    return companyIdInput;
                  }}
                  return null;
                }},
                querySelectorAll(selector) {{
                  return selector === "input, select, textarea" ? reviewControls : [];
                }},
              }};
              const aiCleanupButton = {{
                classList: noopClassList,
                dataset: {{cleanupUrl: "/review/job-1/summary/cleanup"}},
                disabled: false,
                eventHandlers: {{}},
                addEventListener(eventName, handler) {{
                  this.eventHandlers[eventName] = handler;
                }},
                closest(selector) {{
                  return selector === "form" ? reviewAutosaveForm : null;
                }},
                setAttribute() {{}},
              }};
              const reviewAutosaveStatus = {{
                classList: noopClassList,
                textContent: "",
              }};

              class FakeFormData {{
                constructor(formElement) {{
                  this.entriesList = formElement.querySelectorAll("input, select, textarea")
                    .filter((control) => control.name && !control.disabled)
                    .map((control) => [control.name, control.value]);
                }}

                entries() {{
                  return this.entriesList[Symbol.iterator]();
                }}

                [Symbol.iterator]() {{
                  return this.entries();
                }}
              }}

              const fakeDocument = {{
                querySelector(selector) {{
                  if (selector === 'meta[name="csrf-token"]') {{
                    return {{getAttribute: () => "csrf-token"}};
                  }}
                  if (selector === "[data-review-autosave-form]") {{
                    return reviewAutosaveForm;
                  }}
                  if (selector === "[data-review-autosave-status]") {{
                    return reviewAutosaveStatus;
                  }}
                  if (selector === "[data-review-date-weekday-label]") {{
                    return reviewDateWeekdayLabel;
                  }}
                  if (selector === "[data-ai-cleanup-status]") {{
                    return aiCleanupStatus;
                  }}
                  return null;
                }},
                querySelectorAll() {{
                  if (arguments[0] === "[data-ai-cleanup-button]") {{
                    return [aiCleanupButton];
                  }}
                  if (arguments[0] === "[data-review-company-input]") {{
                    return [reviewCompanyInput];
                  }}
                  return [];
                }},
                createElement(tagName) {{
                  return makeElement(tagName.toUpperCase());
                }},
              }};

              const browserContext = {{
                clearTimeout: fakeClearTimeout,
                console,
                document: fakeDocument,
                fetch: async (url, requestOptions) => {{
                  if (url.startsWith("/autotask/companies?")) {{
                    return {{
                      ok: true,
                      json: async () => ({{
                        companies: [
                          {{company_id: 1001, company_name: "Acme Services"}},
                          {{company_id: 1002, company_name: "Acme Holdings"}},
                        ],
                      }}),
                    }};
                  }}

                  if (url.endsWith("/summary/cleanup")) {{
                    const submittedPayload = JSON.parse(requestOptions.body);
                    aiCleanupRequests.push(submittedPayload.summary_notes);
                    return {{
                      ok: true,
                      json: async () => ({{summary_notes: "Cleaned review notes."}}),
                    }};
                  }}

                  submittedRequests.push({{
                    body: Object.fromEntries(requestOptions.body.entries()),
                    headers: requestOptions.headers,
                    method: requestOptions.method,
                    url,
                  }});
                  return {{
                    ok: true,
                    json: async () => ({{
                      job_id: "job-1",
                      job_date: jobDateInput.value,
                      summary_notes: summaryTextarea.value,
                    }}),
                  }};
                }},
                FormData: FakeFormData,
                setTimeout: fakeSetTimeout,
                URLSearchParams,
                window: {{location: {{href: ""}}}},
              }};

              vm.runInNewContext(reviewScript, browserContext, {{filename: "review.js"}});

              summaryTextarea.value = "";
              reviewCompanyInput.value = "Acme";
              reviewCompanyInput.eventHandlers.input();
              runQueuedTimers();

              await Promise.resolve();
              await Promise.resolve();
              await new Promise((resolve) => setImmediate(resolve));

              assert.strictEqual(submittedRequests.length, 0);
              assert.strictEqual(reviewAutosaveStatus.textContent, "");
              assert.strictEqual(companyStatus.textContent, "");
              assert.strictEqual(companyResults.children.length, 2);
              assert.strictEqual(companyResults.children[0].textContent, "Acme Services");

              summaryTextarea.value = "Autosaved review notes.";
              summaryTextarea.eventHandlers.input();
              runQueuedTimers();

              await Promise.resolve();
              await Promise.resolve();
              await new Promise((resolve) => setImmediate(resolve));

              assert.strictEqual(submittedRequests.length, 1);
              assert.strictEqual(submittedRequests[0].url, "/review/job-1/save");
              assert.strictEqual(submittedRequests[0].method, "POST");
              assert.strictEqual(submittedRequests[0].headers.Accept, "application/json");
              assert.strictEqual(submittedRequests[0].body.csrf_token, "csrf-token");
              assert.strictEqual(submittedRequests[0].body.summary_notes, "Autosaved review notes.");
              assert.strictEqual(reviewAutosaveStatus.textContent, "Changes saved.");

              jobDateInput.value = "2026-06-20";
              jobDateInput.eventHandlers.change();
              assert.strictEqual(reviewDateWeekdayLabel.textContent, "");
              runQueuedTimers();

              await Promise.resolve();
              await Promise.resolve();
              await new Promise((resolve) => setImmediate(resolve));

              assert.strictEqual(submittedRequests.length, 2);
              assert.strictEqual(submittedRequests[1].body.job_date, "2026-06-20");
              assert.strictEqual(reviewDateWeekdayLabel.textContent, "");

              assert.strictEqual(typeof aiCleanupButton.eventHandlers.click, "function");
              summaryTextarea.value = "rough review wording";
              aiCleanupButton.eventHandlers.click();

              await Promise.resolve();
              await Promise.resolve();
              await new Promise((resolve) => setImmediate(resolve));
              runQueuedTimers();
              await Promise.resolve();
              await Promise.resolve();
              await new Promise((resolve) => setImmediate(resolve));

              assert.deepStrictEqual(aiCleanupRequests, ["rough review wording"]);
              assert.strictEqual(summaryTextarea.value, "Cleaned review notes.");
              assert.strictEqual(submittedRequests.length, 3);
              assert.strictEqual(submittedRequests[2].body.summary_notes, "Cleaned review notes.");
              assert.strictEqual(aiCleanupStatus.textContent, "Summary cleaned up.");
            }})().catch((error) => {{
              console.error(error);
              process.exit(1);
            }});
            """
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [node_path, str(harness_path)],
        cwd=repository_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
