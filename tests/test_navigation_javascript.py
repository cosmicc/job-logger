"""Regression tests for browser navigation URL selection."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def test_navigation_script_builds_provider_and_device_specific_urls(tmp_path: Path) -> None:
    """Navigation URLs should honor explicit providers and device-default behavior."""

    node_path = shutil.which("node")
    if node_path is None:
        pytest.skip("Node.js is required to execute navigation.js.")

    repository_root = Path(__file__).resolve().parents[1]
    navigation_script_path = repository_root / "job_logger" / "static" / "navigation.js"
    harness_path = tmp_path / "navigation_script_test.js"
    harness_path.write_text(
        textwrap.dedent(
            f"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const script = fs.readFileSync({str(navigation_script_path)!r}, "utf8");
            const windowHandlers = {{}};
            const documentHandlers = {{}};
            const browserWindow = {{
              addEventListener(name, handler) {{ windowHandlers[name] = handler; }},
              location: {{href: "", reload() {{}}}},
              JobLoggerNavigation: null,
            }};
            const browserDocument = {{
              addEventListener(name, handler) {{ documentHandlers[name] = handler; }},
              querySelectorAll() {{ return []; }},
              visibilityState: "visible",
            }};
            const context = {{
              console,
              document: browserDocument,
              navigator: {{userAgent: "Desktop", platform: "Linux", maxTouchPoints: 0}},
              sessionStorage: {{getItem() {{ return null; }}, removeItem() {{}}, setItem() {{}}}},
              window: browserWindow,
            }};
            vm.runInNewContext(script, context, {{filename: "navigation.js"}});
            const api = browserWindow.JobLoggerNavigation;
            const address = "123 Main Street, Detroit, MI 48201";

            assert.strictEqual(
              api.buildNavigationUrl("waze", address),
              "https://waze.com/ul?q=123%20Main%20Street%2C%20Detroit%2C%20MI%2048201&navigate=yes",
            );
            assert.strictEqual(
              api.buildNavigationUrl("google_maps", address),
              "https://www.google.com/maps/dir/?api=1&destination=123%20Main%20Street%2C%20Detroit%2C%20MI%2048201",
            );
            assert.strictEqual(
              api.buildNavigationUrl("apple_maps", address),
              "https://maps.apple.com/?daddr=123%20Main%20Street%2C%20Detroit%2C%20MI%2048201&dirflg=d",
            );
            assert.strictEqual(
              api.buildNavigationUrl("device_default", address, {{userAgent: "Android 15", platform: "Linux", maxTouchPoints: 5}}),
              "geo:0,0?q=123%20Main%20Street%2C%20Detroit%2C%20MI%2048201",
            );
            assert.ok(api.buildNavigationUrl(
              "device_default",
              address,
              {{userAgent: "Mobile", platform: "MacIntel", maxTouchPoints: 5}},
            ).startsWith("https://maps.apple.com/"));
            assert.ok(api.buildNavigationUrl(
              "device_default",
              address,
              {{userAgent: "Desktop", platform: "Linux", maxTouchPoints: 0}},
            ).startsWith("https://www.google.com/maps/dir/"));
            assert.strictEqual(api.buildNavigationUrl("none", address), "");
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
