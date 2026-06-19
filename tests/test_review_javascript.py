"""Regression tests for browser-side review workflow JavaScript."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


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
              const noopClassList = {{
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
                  disabled,
                  name,
                  tagName,
                  type,
                  value,
                  eventHandlers: {{}},
                  addEventListener(eventName, handler) {{
                    this.eventHandlers[eventName] = handler;
                  }},
                }};
              }}

              const csrfInput = makeControl({{type: "hidden", name: "csrf_token", value: "csrf-token"}});
              const ticketStatusSelect = makeControl({{tagName: "SELECT", name: "ticket_status", value: "complete"}});
              const jobDateInput = makeControl({{type: "date", name: "job_date", value: "2026-06-16"}});
              const startTimeInput = makeControl({{name: "start_time", value: "8:00 am"}});
              const endTimeInput = makeControl({{name: "end_time", value: "8:15 am"}});
              const summaryTextarea = makeControl({{tagName: "TEXTAREA", name: "summary_notes", value: "Initial review notes."}});
              const reviewControls = [
                csrfInput,
                ticketStatusSelect,
                jobDateInput,
                startTimeInput,
                endTimeInput,
                summaryTextarea,
              ];
              const reviewAutosaveForm = {{
                dataset: {{reviewSaveUrl: "/review/job-1/save"}},
                querySelectorAll(selector) {{
                  return selector === "input, select, textarea" ? reviewControls : [];
                }},
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
                  return null;
                }},
                querySelectorAll() {{
                  return [];
                }},
              }};

              const browserContext = {{
                clearTimeout: fakeClearTimeout,
                console,
                document: fakeDocument,
                fetch: async (url, requestOptions) => {{
                  submittedRequests.push({{
                    body: Object.fromEntries(requestOptions.body.entries()),
                    headers: requestOptions.headers,
                    method: requestOptions.method,
                    url,
                  }});
                  return {{
                    ok: true,
                    json: async () => ({{job_id: "job-1", summary_notes: summaryTextarea.value}}),
                  }};
                }},
                FormData: FakeFormData,
                setTimeout: fakeSetTimeout,
                URLSearchParams,
                window: {{location: {{href: ""}}}},
              }};

              vm.runInNewContext(reviewScript, browserContext, {{filename: "review.js"}});

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
