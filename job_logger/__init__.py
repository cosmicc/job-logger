"""Job Logger application package.

The package intentionally keeps integrations, routes, security helpers, and
database code separated so security-sensitive behavior can be audited without
reading one large application file.
"""

from job_logger.version import APP_VERSION

# __version__ gives scripts and diagnostics a standard package-level version
# attribute without making them import route or configuration modules.
__version__ = APP_VERSION
