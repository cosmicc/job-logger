"""Regression tests for browser-side password reset JavaScript."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_password_reset_turnstile_renders_with_documented_selector(tmp_path: Path) -> None:
    """The reset script should use Cloudflare's explicit-render selector flow."""

    node_path = shutil.which("node")
    if node_path is None:
        pytest.skip("Node.js is required to execute password-reset.js.")

    repository_root = Path(__file__).resolve().parents[1]
    password_reset_script_path = repository_root / "job_logger" / "static" / "password-reset.js"
    harness_path = tmp_path / "password_reset_turnstile_test.js"
    harness_path.write_text(
        textwrap.dedent(
            f"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const passwordResetScript = fs.readFileSync({str(password_reset_script_path)!r}, "utf8");
            const readyCallbacks = [];
            const renderCalls = [];
            const eventHandlers = {{}};
            const statusElement = {{
              textContent: "",
              classList: {{
                toggle() {{}},
              }},
            }};
            const submitButton = {{disabled: false}};
            const widgetElement = {{
              dataset: {{
                sitekey: "site-key",
                theme: "dark",
              }},
            }};
            const formElement = {{
              dataset: {{}},
              addEventListener(eventName, handler) {{
                eventHandlers[eventName] = handler;
              }},
            }};
            const browserWindow = {{
              setTimeout() {{
                return 1;
              }},
              turnstile: {{
                ready(callback) {{
                  readyCallbacks.push(callback);
                }},
                render(containerSelector, options) {{
                  renderCalls.push({{containerSelector, options}});
                  return "widget-id";
                }},
                reset() {{}},
              }},
            }};
            const browserDocument = {{
              readyState: "complete",
              addEventListener() {{}},
              querySelector(selector) {{
                if (selector === 'form[action="/forgot-password"]') {{
                  return formElement;
                }}
                if (selector === "[data-turnstile-widget]") {{
                  return widgetElement;
                }}
                if (selector === "[data-turnstile-status]") {{
                  return statusElement;
                }}
                if (selector === "[data-password-reset-submit]") {{
                  return submitButton;
                }}
                if (selector === 'input[name="cf-turnstile-response"]') {{
                  return null;
                }}
                return null;
              }},
            }};

            vm.runInNewContext(passwordResetScript, {{
              document: browserDocument,
              setTimeout() {{
                return 1;
              }},
              window: browserWindow,
            }}, {{filename: "password-reset.js"}});

            assert.strictEqual(typeof browserWindow.jobLoggerTurnstileReady, "function");
            assert.strictEqual(readyCallbacks.length, 1);
            browserWindow.jobLoggerTurnstileReady();
            assert.strictEqual(readyCallbacks.length, 1);

            readyCallbacks[0]();

            assert.strictEqual(renderCalls.length, 1);
            assert.strictEqual(renderCalls[0].containerSelector, "#password-reset-turnstile");
            assert.strictEqual(renderCalls[0].options.sitekey, "site-key");
            assert.strictEqual(renderCalls[0].options.theme, "dark");
            assert.strictEqual(renderCalls[0].options.action, "password_reset");
            assert.strictEqual(renderCalls[0].options["response-field-name"], "cf-turnstile-response");
            assert.strictEqual(formElement.dataset.turnstileGuardAttached, "true");
            assert.strictEqual(submitButton.disabled, true);
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
