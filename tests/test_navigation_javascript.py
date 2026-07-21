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
    navigation_script_path = repository_root / "ticket_pilot" / "static" / "navigation.js"
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
            const ticketNavigationButtons = [];
            const browserWindow = {{
              addEventListener(name, handler) {{ windowHandlers[name] = handler; }},
              location: {{href: "", reload() {{}}}},
              TicketPilotNavigation: null,
            }};
            const browserDocument = {{
              addEventListener(name, handler) {{ documentHandlers[name] = handler; }},
              querySelectorAll(selector) {{
                return selector === "[data-ticket-navigation-button]" ? ticketNavigationButtons : [];
              }},
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
            const api = browserWindow.TicketPilotNavigation;
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

            assert.strictEqual(api.isMobileDevice({{
              userAgent: "Mozilla/5.0 (iPod touch)",
              platform: "iPod",
              maxTouchPoints: 5,
            }}), true);
            assert.strictEqual(api.isMobileDevice({{
              userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel Tablet)",
              platform: "Linux armv8l",
              maxTouchPoints: 10,
            }}), true);
            assert.strictEqual(api.isMobileDevice({{
              userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15)",
              platform: "MacIntel",
              maxTouchPoints: 5,
              userAgentDataMobile: false,
            }}), true);
            assert.strictEqual(api.isMobileDevice({{
              userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
              platform: "Win32",
              maxTouchPoints: 10,
              userAgentDataMobile: false,
              primaryPointerCoarse: true,
            }}), true);
            assert.strictEqual(api.isMobileDevice({{
              userAgent: "Mozilla/5.0 (X11; Linux x86_64)",
              platform: "Linux x86_64",
              maxTouchPoints: 0,
              userAgentDataMobile: false,
            }}), false);
            assert.strictEqual(api.isNavigationAllowed(false, {{
              userAgent: "Desktop",
              platform: "Linux",
              maxTouchPoints: 0,
            }}), false);
            assert.strictEqual(api.isNavigationAllowed(true, {{
              userAgent: "Desktop",
              platform: "Linux",
              maxTouchPoints: 0,
            }}), true);
            assert.strictEqual(api.isNavigationAllowed(false, {{
              userAgent: "Mozilla/5.0 (iPad)",
              platform: "iPad",
              maxTouchPoints: 5,
            }}), true);

            let destinationHidden = true;
            const mobileNavigationRow = {{
              classList: {{
                toggle(className, force) {{
                  if (className === "is-destination-hidden") destinationHidden = force;
                }},
              }},
            }};
            const ticketNavigationButton = {{
              classList: {{toggle() {{}}}},
              closest(selector) {{
                return selector === "[data-mobile-entry-navigation-row]" ? mobileNavigationRow : null;
              }},
              dataset: {{navigationUrl: "/review/job-1/navigation", navigationAllowFullWeb: "true"}},
              disabled: true,
            }};
            ticketNavigationButtons.push(ticketNavigationButton);
            api.applyDestination("/review/job-1/navigation", {{
              available: true,
              navigation_app: "google_maps",
              navigation_address: address,
            }});
            assert.strictEqual(destinationHidden, false);
            assert.strictEqual(ticketNavigationButton.disabled, false);
            api.applyDestination("/review/job-1/navigation", {{available: false}});
            assert.strictEqual(destinationHidden, true);
            assert.strictEqual(ticketNavigationButton.disabled, true);

            assert.strictEqual(api.launch("google_maps", address), false);
            assert.strictEqual(browserWindow.location.href, "");
            assert.strictEqual(api.launch("google_maps", address, {{allowFullWeb: true}}), true);
            assert.ok(browserWindow.location.href.startsWith("https://www.google.com/maps/dir/"));
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
