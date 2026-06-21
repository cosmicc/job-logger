"""Application version metadata for Job Logger.

This module is the runtime source for the version displayed in authenticated
pages and diagnostics. Keep this value aligned with ``pyproject.toml`` when the
user asks for a version advance.
"""

from __future__ import annotations

# APP_VERSION is intentionally source-controlled instead of environment-driven so
# deployments cannot silently report different application versions.
APP_VERSION = "1.0.2"
