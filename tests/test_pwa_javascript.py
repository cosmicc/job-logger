"""Regression tests for browser-side progressive web app JavaScript."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_mobile_close_button_self_targets_before_close(tmp_path: Path) -> None:
    """The mobile X should attempt an app-shell close without logging out."""

    node_path = shutil.which("node")
    if node_path is None:
        pytest.skip("Node.js is required to execute pwa.js.")

    repository_root = Path(__file__).resolve().parents[1]
    pwa_script_path = repository_root / "job_logger" / "static" / "pwa.js"
    harness_path = tmp_path / "pwa_close_test.js"
    harness_path.write_text(
        textwrap.dedent(
            f"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const pwaScript = fs.readFileSync({str(pwa_script_path)!r}, "utf8");
            const closeCalls = [];
            const queuedTimers = [];
            const locationReplacements = [];
            let clickHandler = null;
            let preventedDefault = false;
            const closeButton = {{
              addEventListener(eventName, handler) {{
                if (eventName === "click") {{
                  clickHandler = handler;
                }}
              }},
            }};
            const browserWindow = {{
              addEventListener() {{}},
              close() {{
                closeCalls.push(["close"]);
              }},
              location: {{
                replace(url) {{
                  locationReplacements.push(url);
                }},
              }},
              matchMedia(query) {{
                return {{matches: query === "(display-mode: standalone)"}};
              }},
              open(url, target) {{
                closeCalls.push(["open", url, target]);
                return browserWindow;
              }},
              setTimeout(callback, delay) {{
                queuedTimers.push({{callback, delay}});
              }},
            }};
            const browserContext = {{
              console,
              document: {{
                visibilityState: "visible",
                querySelectorAll(selector) {{
                  return selector === "[data-close-app-button]" ? [closeButton] : [];
                }},
              }},
              navigator: {{}},
              window: browserWindow,
            }};

            vm.runInNewContext(pwaScript, browserContext, {{filename: "pwa.js"}});

            assert.strictEqual(typeof clickHandler, "function");
            clickHandler({{
              preventDefault() {{
                preventedDefault = true;
              }},
            }});

            assert.strictEqual(preventedDefault, true);
            assert.deepStrictEqual(closeCalls, [
              ["open", "", "_self"],
              ["close"],
            ]);
            assert.strictEqual(queuedTimers.length, 1);
            assert.strictEqual(queuedTimers[0].delay, 250);
            queuedTimers[0].callback();
            assert.deepStrictEqual(locationReplacements, ["about:blank"]);
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
