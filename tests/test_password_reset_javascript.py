"""Regression tests for browser-side password reset JavaScript."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_password_reset_turnstile_renders_explicit_widget(tmp_path: Path) -> None:
    """The reset script should render Turnstile explicitly without turnstile.ready()."""

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
            const eventHandlers = {{}};
            const renderCalls = [];
            const statusElement = {{
              textContent: "",
              classList: {{
                toggle() {{}},
              }},
            }};
            const submitButton = {{disabled: false}};
            const apiScriptElement = {{
              dataset: {{}},
              addEventListener(eventName, handler) {{
                eventHandlers[`api:${{eventName}}`] = handler;
              }},
            }};
            const widgetElement = {{
              dataset: {{
                sitekey: "site-key",
                theme: "dark",
              }},
              querySelector() {{
                return null;
              }},
            }};
            const formElement = {{
              dataset: {{}},
              addEventListener(eventName, handler) {{
                eventHandlers[`form:${{eventName}}`] = handler;
              }},
            }};
            const browserWindow = {{
              setTimeout(callback) {{
                if (typeof callback === "function") {{
                  callback();
                }}
                return 1;
              }},
              turnstile: {{
                render(containerSelector, options) {{
                  renderCalls.push({{containerSelector, options}});
                  return "widget-id";
                }},
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
                if (selector === "[data-turnstile-api-script]") {{
                  return apiScriptElement;
                }}
                if (selector === 'input[name="cf-turnstile-response"]') {{
                  return null;
                }}
                return null;
              }},
            }};

            vm.runInNewContext(passwordResetScript, {{
              document: browserDocument,
              setTimeout: browserWindow.setTimeout,
              window: browserWindow,
            }}, {{filename: "password-reset.js"}});

            assert.strictEqual(browserWindow.jobLoggerTurnstileReady, undefined);
            assert.strictEqual(typeof browserWindow.jobLoggerTurnstileSuccess, "function");
            assert.strictEqual(typeof browserWindow.jobLoggerTurnstileError, "function");
            assert.strictEqual(typeof browserWindow.jobLoggerTurnstileExpired, "function");
            assert.strictEqual(typeof browserWindow.jobLoggerTurnstileTimeout, "function");
            assert.strictEqual(typeof browserWindow.jobLoggerTurnstileUnsupported, "function");
            assert.strictEqual(formElement.dataset.turnstileGuardAttached, "true");
            assert.strictEqual(apiScriptElement.dataset.turnstileListenersAttached, "true");
            assert.strictEqual(renderCalls.length, 1);
            assert.strictEqual(renderCalls[0].containerSelector, "#password-reset-turnstile");
            assert.strictEqual(renderCalls[0].options.sitekey, "site-key");
            assert.strictEqual(renderCalls[0].options.theme, "dark");
            assert.strictEqual(renderCalls[0].options.action, "password_reset");
            assert.strictEqual(renderCalls[0].options.appearance, "always");
            assert.strictEqual(renderCalls[0].options.execution, "render");
            assert.strictEqual(renderCalls[0].options["response-field"], true);
            assert.strictEqual(renderCalls[0].options["response-field-name"], "cf-turnstile-response");
            assert.strictEqual(typeof renderCalls[0].options.callback, "function");
            assert.strictEqual(typeof renderCalls[0].options["error-callback"], "function");
            assert.strictEqual(submitButton.disabled, true);
            assert.strictEqual(statusElement.textContent, "Complete human verification before sending the reset link.");

            browserWindow.jobLoggerTurnstileSuccess("token-value");

            assert.strictEqual(submitButton.disabled, false);
            assert.strictEqual(statusElement.textContent, "Human verification complete.");

            browserWindow.jobLoggerTurnstileExpired();

            assert.strictEqual(submitButton.disabled, true);
            assert.strictEqual(statusElement.textContent, "Human verification expired. Complete it again before sending the reset link.");
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


def test_password_reset_turnstile_retries_api_script_load_failure(tmp_path: Path) -> None:
    """The reset script should retry the alternate Turnstile URL before failing."""

    node_path = shutil.which("node")
    if node_path is None:
        pytest.skip("Node.js is required to execute password-reset.js.")

    repository_root = Path(__file__).resolve().parents[1]
    password_reset_script_path = repository_root / "job_logger" / "static" / "password-reset.js"
    harness_path = tmp_path / "password_reset_turnstile_retry_test.js"
    harness_path.write_text(
        textwrap.dedent(
            f"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const passwordResetScript = fs.readFileSync({str(password_reset_script_path)!r}, "utf8");
            const eventHandlers = {{}};
            let appendedScript = null;
            const statusElement = {{
              textContent: "",
              classList: {{
                toggle() {{}},
              }},
            }};
            const submitButton = {{disabled: false}};
            const apiScriptElement = {{
              src: "https://challenges.cloudflare.com/turnstile/v0/api.js",
              dataset: {{
                turnstileFallbackSrc: "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit",
              }},
              addEventListener(eventName, handler) {{
                eventHandlers[`primary:${{eventName}}`] = handler;
              }},
            }};
            const widgetElement = {{
              dataset: {{
                sitekey: "site-key",
                theme: "dark",
              }},
              querySelector() {{
                return null;
              }},
            }};
            const formElement = {{
              dataset: {{}},
              addEventListener() {{}},
            }};
            const browserDocument = {{
              readyState: "complete",
              head: {{
                appendChild(scriptElement) {{
                  appendedScript = scriptElement;
                }},
              }},
              createElement(tagName) {{
                assert.strictEqual(tagName, "script");
                return {{
                  dataset: {{}},
                  addEventListener(eventName, handler) {{
                    eventHandlers[`fallback:${{eventName}}`] = handler;
                  }},
                }};
              }},
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
                if (selector === "[data-turnstile-api-script]") {{
                  return apiScriptElement;
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
              window: {{
                setTimeout() {{
                  return 1;
                }},
              }},
            }}, {{filename: "password-reset.js"}});

            eventHandlers["primary:error"]();

            assert.notStrictEqual(appendedScript, null);
            assert.strictEqual(appendedScript.src, "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit");
            assert.strictEqual(appendedScript.defer, true);
            assert.strictEqual(appendedScript.async, true);
            assert.strictEqual(appendedScript.dataset.turnstileApiScript, "true");
            assert.strictEqual(appendedScript.dataset.turnstileFallbackScript, "true");
            assert.strictEqual(appendedScript.dataset.turnstileListenersAttached, "true");
            assert.strictEqual(statusElement.textContent, "Human verification is retrying...");
            assert.strictEqual(submitButton.disabled, true);

            eventHandlers["fallback:error"]();

            assert.strictEqual(
              statusElement.textContent,
              "Human verification could not load. Reload this page or check browser content blockers.",
            );
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
