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

The initial `/home` page and blank Start Work route must not run an Autotask
contactability probe. The mobile screen should render from local state first,
then service-call cards can load through `/home/service-calls` after the page
has loaded. Autotask is queried only when a workflow actually needs provider
data, such as service-call loading, company search, open-ticket lookup,
service-call start verification, or Autotask submission/update/delete actions.

Mock mode remains available for tests and isolated development only.

Autotask resource IDs are database-managed per web user, not environment
configuration. A managed web user must have an Autotask resource ID before they
can start work. Routes pass that resource ID into service-call lookup and time
entry submission. Static role and billing-code IDs must not be environment
configuration. The live provider gets `TimeEntries.roleID` from the selected
ticket's `assignedResourceroleID` at submit time and omits
`TimeEntries.billingCodeID` so Autotask inherits the selected ticket's Work Type
on create. API credentials, ticket status IDs, time-entry type, and optional
Autotask provider settings remain environment-backed. Do not add a global
Autotask impersonation resource setting; user-scoped workflows use the owning
managed web user's resource ID in payloads and filters but do not send
Autotask's optional `ImpersonationResourceId` header.
The config super admin may use `/users` to query Autotask Resources by name
while creating a managed web user, but that lookup must still go through the
server-side provider and return only safe resource metadata. When the selected
resource includes an email address, the user manager stores it with the managed
web-user row for future user-scoped features. The same page has a per-user
refresh action that re-runs Resource lookup, matches the returned resource ID
against the user's saved resource ID, and updates only safe local name/email
metadata.

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
- Search Resources for super-admin managed-user setup.
- Refresh safe stored Resource metadata for one managed user through the
  super-admin user manager.
- Query one selected company by ID.
- Query open tickets for a company.
- Query selected-day service calls for the logged-in managed web user's
  resource.
- Resolve service-call ticket/resource relationships before starting a job from
  a service call.
- Query ticket status picklist metadata.
- Query a ticket ID from a ticket number.
- Move a selected `New` ticket to `In progress` when work starts.
- Update selected ticket status around submission and submitted-entry edits
  when configured and required by the workflow.
- Create `TimeEntries`.
- Patch existing submitted `TimeEntries`.
- Delete existing submitted `TimeEntries` when the local job must return to
  review.
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

If this check fails, show a clear diagnostic result, but do not wire this check
into `/home` page rendering or blank Start Work. Keep the debug page on
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
bounded description, status label, company name, and display-only work-location
detection. Review ticket selection uses `POST /review/{job_id}/ticket`; the
route uses the server-verified open-ticket list that was just loaded when the
short-lived selection cache is available, falls back to re-querying Autotask
when that cache is expired or absent, verifies the submitted ticket number is
valid for the job's stored client/company, then persists the ticket number,
title, and bounded description as local job metadata. The review detail heading
and ticket-description card can then show the chosen ticket context without
repeatedly querying Autotask.

On mobile, ticket numbers are populated from the open-ticket picker instead of
manual entry. The ticket choice posts to `POST /jobs/{job_id}/ticket`; that
route uses the same server-side selection cache or a fresh Autotask lookup,
verifies the selected ticket is valid for that job, and persists the ticket
number, title, and bounded description returned by the provider. While no
ticket options are loaded, the mobile open-ticket panel itself is clickable and
keyboard-activatable; that action first saves the active job's current client
fields through `POST /jobs/{job_id}/ticket-number` with a JSON response, shows
the spinner loading state, then loads open tickets from the server-verified
lookup endpoint. The review open-ticket panel uses the same click-to-load
pattern. Open-ticket options should include a display-only Remote, On-Site, or
Not specified label inferred from safe ticket title/description text, falling
back to remote-only ticket source labels when text has no result, and expose the
matching `.ticket-location-*` CSS class for the browser. After mobile or review
selection succeeds, the UI hides the open-ticket list and updates visible ticket
number/title/description fields from the verified JSON response rather than
trusting the clicked browser option.

## Service Call Lookup

The mobile start panels can list selected-day Autotask service calls for the
logged-in managed web user's Autotask resource ID. This is a read-only
convenience path for starting a job from scheduled dispatch data, not a
separate trust boundary. The browser may ask for another local date through
`/home/service-calls?date=YYYY-MM-DD`; the resource ID still comes only from
the authenticated managed web user.

Service-call lookup must stay inside `job_logger/services/autotask.py` because
it needs several related Autotask entities:

- `ServiceCalls` for scheduled call details in the selected local date bounds.
- `ServiceCallTickets` to identify tickets associated with each service call.
- `ServiceCallTicketResources` to verify the user's resource is assigned to
  that specific service-call ticket row.
- `Tickets` for ticket number, title, bounded description, status, and source.
- `Companies` for the client name stored with the new active job.

The browser must submit only `service_call_ticket_id`, `service_call_date`, and
CSRF to `POST /jobs/start/service-call`. The route re-reads the provider's
server-verified list for the selected local date and current managed web user's
resource before creating a job. Never accept ticket number, ticket title, ticket
description, client name, company ID, or work-location values from hidden fields
for this path.

The `/home/service-calls` response may include a preformatted local
start/end time range for display, such as `4:00pm-5:00pm`. Treat that range as
read-only card context; it must not be submitted back by the browser or used as
the authorization source for starting a job.

## Resource Lookup

The `/users/autotask-resources` endpoint is for config super admins only. It
lets the user manager search Autotask Resources while creating or editing
managed web users and returns safe fields such as resource ID, first name, last
name, display name, and email when available.

Resource lookup must stay inside `job_logger/services/autotask.py`. Browser
JavaScript may call Job Logger's authenticated endpoint, but it must never call
Autotask directly or receive Autotask credentials. Autotask formats resource
names as `Last, First`; the provider should accept either `First Last` or
`Last, First`, query `Resources/query` with bounded first-name and last-name
filters, deduplicate IDs, and cache only positive non-secret results briefly.
When the browser submits the selected resource email back with the add/edit
form, the server must treat it as optional metadata, validate it as a bounded
email address, and never trust it as an authorization source.

Per-row refresh on `/users` is also super-admin-only and CSRF-protected. It
must search through the server-side provider, require the selected resource's ID
to equal the user's stored resource ID, and update only locally stored
non-secret metadata such as full name and email. Do not use returned email or
display names for authorization.

Remote/On-Site detection is intentionally simple and auditable: scan
service-call details or open-ticket title/description text for `remote`,
`onsite`, `on-site`, or `on site`. If both words are present, the first match in
the details text wins. If text detection has no result, fall back to
`Tickets.source`: `RMM Alert`, `Datto Alert`, `BCDR Alert`, and `Email Alert`
always mean Remote. Source fallback must support both direct source labels and
numeric picklist IDs resolved from `Tickets.source` field metadata. If neither
text nor source identifies a work mode, display `Not specified` and let the
started job use the normal Remote default.

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
- Displayed service-call start list for one selected local date: two minutes.
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

Time entry submission happens after review acceptance or retry by default. A
managed web user can opt in to **Submit from Work in Progress** on `/config`;
when enabled, ending an active job submits through the same service immediately
after local end-work validation succeeds.

Required local fields before submission:

- Ticket number.
- Ticket status.
- One local job date.
- Start time.
- End time.
- Summary notes.
- Work location mode, which defaults to Remote.

Direct Work in Progress submission must not bypass these requirements. If a
required local field is missing, the end-work transaction should roll back and
leave the job active. If the Autotask provider returns a safe failure, the job
should use the existing failed-submission review state so the user can retry
from Review.

Required live Autotask values include:

- The owning managed web user's Autotask resource ID.
- The selected ticket's assigned role ID.
- Time entry type.
- Tenant-specific ticket status picklist IDs.

Ticket `TimeEntries` creation must query the selected `Tickets` row by
`ticketNumber` and use `assignedResourceroleID` for `TimeEntries.roleID`.
Autotask requires ticket time-entry roles to match the ticket's assigned role
unless the tenant explicitly allows role edits on ticket time entries.

Ticket `TimeEntries` creation must not include `billingCodeID`. Autotask labels
that as Allocation Code / Work Type. On create, omitting it lets Autotask
inherit the selected ticket's `billingCodeID`; passing the field can require
extra Allocation Code edit permission even when the value matches the ticket.

Ticket `TimeEntries.summaryNotes` must be built from the stored work-location
mode plus the reviewed summary text. The local `summary_notes` field stays
unprefixed for mobile and persistence. Review detail displays the full
Autotask-bound summary, including `Remote` or `On-Site`, so the operator can
correct the prefix before submission or submitted-entry update. Save, accept,
retry, and edit-entry handlers must parse that visible prefix back into
`work_location` before building the final payload.

User-scoped live calls must use the owning managed web user's Autotask resource
ID for local `resourceID` payloads and resource filters. They must not send the
optional Autotask `ImpersonationResourceId` header. Super-admin Resource lookup
and debug connectivity checks do not have an owning managed user and must not
use a global impersonation fallback.

Submission must remain idempotent. A retry must not create duplicate time
entries for the same accepted job.

Both Review acceptance and direct Work in Progress submission must call
`submit_job_to_autotask()` so idempotency keys, submission attempts, safe error
handling, ticket status updates, role lookup, and summary construction remain
centralized.

After a provider reports successful submission, ticket identity and destructive
workflow actions remain protected. Do not allow later review save, ticket
selection, accept/resend, retry, or local **Delete time entry** actions for that
job. Supported submitted-job mutations are limited to audited external-entry
actions: **Edit Entry** validates one job date, start/end times, summary notes,
and ticket status, then patches the existing Autotask `TimeEntries` row by its
stored external ID. If the previously submitted ticket status is `Complete`,
**Edit Entry** must first move the ticket to `In progress`, then patch
`TimeEntries`, then move the ticket to the selected final status when needed.
If the previous status was not `Complete`, update `Tickets.status` only for an
intentional status change, and move a final `Complete` status after the
`TimeEntries` patch. Failure must leave local state aligned with the last known
successful Autotask state. **Delete From Autotask** deletes `TimeEntries/{id}` and
returns the local job to review only after Autotask confirms the delete. If
either action fails, keep local state aligned with the last known successful
Autotask state and store only safe error details.

Live Autotask write failures should use `_raise_for_safe_response()` so bounded
body-level messages from `Tickets` or `TimeEntries` errors are shown without
falling back to generic HTTP client exception text.

## Diagnostics And Scripts

The debug page is a super-admin-only runtime visibility surface. It should show
the source-controlled application version, sanitized config, connectivity test
results, and submission attempts.

The script `scripts/discover_autotask_ids.py` is for read-only tenant metadata
discovery using `.env` configuration. Keep it read-only and never print
credentials.

Discovery success does not prove the full app workflow can run. The script also
prints non-fatal workflow preflight checks for Companies and Tickets query
access because status metadata calls can succeed while the API user still lacks
endpoint access needed by the mobile/review workflow.
Autotask may return those permission failures as HTTP 500 responses with a
body-level permission message.

## Tests To Consider

Autotask changes usually need tests in:

- `tests/test_autotask_cache.py`.
- `tests/test_debug.py`.
- `tests/test_workflow.py`.

Use fakes/mocks for Autotask behavior. Do not make live Autotask calls in tests.
