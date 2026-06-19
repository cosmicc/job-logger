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

Starting a new job also requires the server-side Autotask connectivity gate to
pass. This is enforced in `job_logger/routes/mobile.py` before `start_job()` is
called. Start Work uses a short server-side health cache so repeated taps do not
run the full live Autotask workflow probe every time.

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
- Query today's service calls for the configured resource.
- Resolve service-call ticket/resource relationships before starting a job from
  a service call.
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

Start Work uses `test_cached_autotask_connectivity_for_start()` instead of the
debug function. A successful result is cached for five minutes, and a failed
result is cached for thirty seconds. Keep the debug page on
`test_autotask_connectivity()` so operator-triggered diagnostics always run a
fresh live check.

## Company Search And Ticket Lookup

The browser calls `/autotask/companies` while the user types a client name.

Important rules:

- Require authentication.
- Return only safe company options: ID and display name.
- Do not expose raw Autotask API responses to the browser.
- Manual client names remain allowed.
- Selected Autotask company IDs are preferred for exact ticket lookup.
- On the active mobile card, a selected Autotask company is locked and should
  be shown as read-only so the visible client name cannot drift away from the
  company ID used for ticket lookup.
- On review, stored client name, company ID, ticket number, ticket title, and
  ticket description are read-only identity/context fields. Save/accept
  handlers must overlay those values from the database before validation so
  crafted form posts cannot change which Autotask ticket receives time or what
  ticket context is displayed.

Ticket lookup uses `/review/{job_id}/tickets`.

Ticket lookup should prefer the stored Autotask company ID. If no company ID is
stored, it can fall back to client-name matching.

Ticket options returned to the browser include safe ticket number, title,
bounded description, status label, and company name. Review ticket selection uses
`POST /review/{job_id}/ticket`; the route uses the server-verified open-ticket
list that was just loaded when the short-lived selection cache is available,
falls back to re-querying Autotask when that cache is expired or absent,
verifies the submitted ticket number is valid for the job's stored
client/company, then persists the ticket number, title, and bounded description
as local job metadata. The review detail heading and ticket-description card can
then show the chosen ticket context without repeatedly querying Autotask.

On mobile, ticket numbers are populated from the open-ticket picker instead of
manual entry. The ticket choice posts to `POST /jobs/{job_id}/ticket`; that
route uses the same server-side selection cache or a fresh Autotask lookup,
verifies the selected ticket is valid for that job, and persists the ticket
number, title, and bounded description returned by the provider. The mobile **Find tickets** button first
saves the active job's current client fields through
`POST /jobs/{job_id}/ticket-number` with a JSON response, then loads open
tickets from the server-verified lookup endpoint. After mobile or review
selection succeeds, the UI hides the open-ticket list and updates visible ticket
number/title/description fields from the verified JSON response rather than
trusting the clicked browser option.

## Service Call Lookup

The mobile start panels can list today's Autotask service calls for
`AUTOTASK_RESOURCE_ID`. This is a read-only convenience path for starting a job
from scheduled dispatch data, not a separate trust boundary.

Service-call lookup must stay inside `job_logger/services/autotask.py` because
it needs several related Autotask entities:

- `ServiceCalls` for today's scheduled call details.
- `ServiceCallTickets` to identify tickets associated with each service call.
- `ServiceCallTicketResources` to verify the configured resource is assigned
  to that specific service-call ticket row.
- `Tickets` for ticket number, title, and bounded description.
- `Companies` for the client name stored with the new active job.

The browser must submit only `service_call_ticket_id` plus CSRF to
`POST /jobs/start/service-call`. The route re-reads the provider's
server-verified list for the current local day and configured resource before
creating a job. Never accept ticket number, ticket title, ticket description,
client name, company ID, or work-location values from hidden fields for this
path.

Remote/On-Site detection is intentionally simple and auditable: scan the
service-call details for `remote`, `onsite`, `on-site`, or `on site`. If neither
word is present, display `Not specified` and let the started job use the normal
Remote default. If both words are present, the first match in the details text
wins.

The Autotask API user's security level must be able to read `ServiceCalls`,
`ServiceCallTickets`, and `ServiceCallTicketResources` in addition to the
existing Companies/Tickets permissions. Service-call lookup failures should be
shown as safe, bounded UI errors without blocking the blank Start Work path.

## Caching Rules

Caching is in-process and non-secret only.

Current cache policy:

- Company search results: two hours.
- Selected company metadata by ID: two hours.
- Ticket status picklist labels: 15 minutes.
- Recently displayed open-ticket selection lists: two minutes.
- Today's displayed service-call start list: two minutes.
- Start Work Autotask connectivity success: five minutes.
- Start Work Autotask connectivity failure: thirty seconds.
- Other short-lived Autotask lookup data: 15 minutes unless documented
  otherwise.

Company cache must be treated carefully:

- Positive company results may be cached because company names rarely change.
- Empty company search results must not become authoritative negative cache
  entries.
- If a company is not in cache, the app must still be willing to query Autotask.

The cache is process-local. Multiple app containers do not share it.

The open-ticket selection cache stores only positive, non-secret ticket options
that the server already returned to the authenticated browser. It exists to keep
the click-to-save path fast; it is not a durable authorization source.

## Pagination Rules

Autotask query endpoints are paginated.

Live broad Companies and Tickets queries must:

- Request `MaxRecords=500`.
- Follow `pageDetails.nextPageUrl` when provided.
- Use POST with the original query body for `nextPageUrl` values that came from
  a POST query; Autotask returns HTTP 405 if those follow-up calls use GET.
- Bound pagination to avoid runaway loops.
- Fail safely if the result set exceeds the supported pagination bound instead
  of silently showing partial results.

Interactive open-ticket picker queries are intentionally narrower than broad
diagnostic or discovery queries. When a job already has a selected Autotask
company ID, use that exact company, request only the fields needed by the
picker, filter out completed tickets in the Autotask query, and request only the
first small picker page. The server still caches that returned list briefly and
validates a clicked ticket against it before persisting the ticket number.

## Submission Rules

Time entry submission happens only after review acceptance or retry.

Required local fields before submission:

- Ticket number.
- Ticket status.
- Start date/time.
- End date/time.
- Summary notes.
- Work location mode, which defaults to Remote.

Required live Autotask values include:

- Resource ID.
- Role ID.
- Time entry type.
- Tenant-specific ticket status picklist IDs.
- Impersonation resource ID when configured.

Ticket `TimeEntries` creation must not include `billingCodeID`. Autotask labels
that as Allocation Code, and tenants can reject it unless the API resource has
permission to change allocation codes. Let Autotask use the ticket/resource
defaults instead.

Ticket `TimeEntries.summaryNotes` must be built from the stored work-location
mode plus the reviewed summary text. The local `summary_notes` field stays
unprefixed for mobile and review editing; the final payload starts with
`Remote` or `On-Site`.

`AUTOTASK_IMPERSONATION_RESOURCE_ID` should be blank by default. When blank, the
provider omits `ImpersonationResourceId` and Autotask evaluates the API user's
own permissions. When set, Companies/Tickets query permissions must work for the
impersonated resource context too.

Submission must remain idempotent. A retry must not create duplicate time
entries for the same accepted job.

After a provider reports successful submission, the local job is locked to
preserve the exact values already sent to Autotask. Do not allow later review
save, ticket selection, accept/resend, retry, reject, or force-purge actions for
that job. Use the service-level successful-submission lock before validating
mutable review fields or making another Autotask write.

Live Autotask write failures should use `_raise_for_safe_response()` so bounded
body-level messages from `Tickets` or `TimeEntries` errors are shown without
falling back to generic HTTP client exception text.

## Diagnostics And Scripts

The debug page is for runtime visibility. It should show the source-controlled
application version, sanitized config, connectivity test results, and submission
attempts.

The script `scripts/discover_autotask_ids.py` is for read-only tenant metadata
discovery using `.env` configuration. Keep it read-only and never print
credentials.

Discovery success does not prove the full app workflow can run. The script also
prints non-fatal workflow preflight checks for Companies and Tickets query
access because role, billing code, and status metadata calls can succeed while
the API user still lacks endpoint access needed by the mobile/review workflow.
Autotask may return those permission failures as HTTP 500 responses with a
body-level permission message.

## Tests To Consider

Autotask changes usually need tests in:

- `tests/test_autotask_cache.py`.
- `tests/test_debug.py`.
- `tests/test_workflow.py`.

Use fakes/mocks for Autotask behavior. Do not make live Autotask calls in tests.
