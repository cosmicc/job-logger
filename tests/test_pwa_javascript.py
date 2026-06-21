"""Regression tests for browser-side progressive web app JavaScript."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_pwa_script_registers_worker_without_mobile_close_handler(tmp_path: Path) -> None:
    """The PWA script should not intercept mobile logout buttons."""

    repository_root = Path(__file__).resolve().parents[1]
    pwa_script_path = repository_root / "job_logger" / "static" / "pwa.js"
    pwa_script = pwa_script_path.read_text(encoding="utf-8")

    assert "data-close-app-button" not in pwa_script
    assert "window.close" not in pwa_script
    assert "about:blank" not in pwa_script

    node_path = shutil.which("node")
    if node_path is None:
        pytest.skip("Node.js is required to execute pwa.js.")

    harness_path = tmp_path / "pwa_worker_test.js"
    harness_path.write_text(
        textwrap.dedent(
            f"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const pwaScript = fs.readFileSync({str(pwa_script_path)!r}, "utf8");
            const registrations = [];
            let loadHandler = null;
            const browserWindow = {{
              addEventListener(eventName, handler) {{
                if (eventName === "load") {{
                  loadHandler = handler;
                }}
              }},
            }};
            const browserContext = {{
              console,
              navigator: {{
                serviceWorker: {{
                  register(path, options) {{
                    registrations.push({{path, options}});
                    return {{
                      catch() {{}},
                    }};
                  }},
                }},
              }},
              window: browserWindow,
            }};

            vm.runInNewContext(pwaScript, browserContext, {{filename: "pwa.js"}});

            assert.strictEqual(typeof loadHandler, "function");
            loadHandler();
            assert.strictEqual(JSON.stringify(registrations), JSON.stringify([
              {{
                path: "/service-worker.js",
                options: {{scope: "/"}},
              }},
            ]));
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
