# Job Logger Agent Skill: Autotask Integration

Read this file before changing Autotask configuration, company lookup, ticket
lookup, connectivity checks, ticket status handling, submission payloads, or
Autotask diagnostics.

## Production Requirement

Autotask is mandatory for production.

Production startup requires:

- `APP_ENV=production`.
- `AUTOTASK_PROVIDER=autotask`.
- Valid application authentication settings.

Starting a new job also requires the server-side Autotask connectivity check to
pass. This is enforced in `job_logger/routes/mobile.py` before `start_job()` is
called.

Mock mode remains available for tests and isolated development only.

## Provider Location

All Autotask behavior belongs in `job_logger/services/autotask.py`.

Do not put direct Autotask HTTP calls in routes, templates, or browser
JavaScript. Routes should call the provider/service interface and return safe
data to the browser.

Current provider responsibilities:

- Validate live Autotask configuration.
- Build non-secret request headers.
- Test connectivity.
- Search companies for client autocomplete.
- Query one selected company by ID.
- Query open tickets for a company.
- Query ticket status picklist metadata.
- Query a ticket ID from a ticket number.
- Update selected ticket status when configured.
- Create `TimeEntries`.
- Return sanitized submission results.

## Mandatory Connectivity Test

The debug page posts to `POST /debug/autotask/test`.

The connectivity test must remain safe:

- Do not print secrets.
- Do not log request headers.
- Do not log raw Autotask credentials.
- Return actionable troubleshooting tips.
- Audit the test result without sensitive details.

The live check currently verifies:

- Required workflow configuration is present.
- Company query endpoint is reachable.
- Ticket status metadata endpoint is reachable.
- Ticket query endpoint is reachable.

If this check fails, new job starts are blocked with a clear message.

## Company Search And Ticket Lookup

The browser calls `/autotask/companies` while the user types a client name.

Important rules:

- Require authentication.
- Return only safe company options: ID and display name.
- Do not expose raw Autotask API responses to the browser.
- Manual client names remain allowed.
- Selected Autotask company IDs are preferred for exact ticket lookup.
- If a user edits the client name manually in review, stale company IDs should
  be cleared so future lookups do not silently use the wrong customer.

Ticket lookup uses `/review/{job_id}/tickets`.

Ticket lookup should prefer the stored Autotask company ID. If no company ID is
stored, it can fall back to client-name matching.

## Caching Rules

Caching is in-process and non-secret only.

Current cache policy:

- Company search results: two hours.
- Selected company metadata by ID: two hours.
- Ticket status picklist labels: 15 minutes.
- Other short-lived Autotask lookup data: 15 minutes unless documented
  otherwise.

Company cache must be treated carefully:

- Positive company results may be cached because company names rarely change.
- Empty company search results must not become authoritative negative cache
  entries.
- If a company is not in cache, the app must still be willing to query Autotask.

The cache is process-local. Multiple app containers do not share it.

## Pagination Rules

Autotask query endpoints are paginated.

Live Companies and Tickets queries must:

- Request `MaxRecords=500`.
- Follow `pageDetails.nextPageUrl` when provided.
- Bound pagination to avoid runaway loops.
- Fail safely if the result set exceeds the supported pagination bound instead
  of silently showing partial results.

## Submission Rules

Time entry submission happens only after review acceptance or retry.

Required local fields before submission:

- Ticket number.
- Ticket status.
- Start date/time.
- End date/time.
- Summary notes.

Required live Autotask values include:

- Resource ID.
- Role ID.
- Time entry type.
- Tenant-specific ticket status picklist IDs.
- Billing code ID when configured.
- Impersonation resource ID when configured.

Submission must remain idempotent. A retry must not create duplicate time
entries for the same accepted job.

## Diagnostics And Scripts

The debug page is for runtime visibility. It should show sanitized config,
connectivity test results, and submission attempts.

The script `scripts/discover_autotask_ids.py` is for read-only tenant metadata
discovery using `.env` configuration. Keep it read-only and never print
credentials.

## Tests To Consider

Autotask changes usually need tests in:

- `tests/test_autotask_cache.py`.
- `tests/test_debug.py`.
- `tests/test_workflow.py`.

Use fakes/mocks for Autotask behavior. Do not make live Autotask calls in tests.
