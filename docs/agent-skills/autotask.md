# TicketPilot Agent Skill: Autotask Integration

TicketPilot's formal long name is **Ticket Pilot for Autotask** because the
production workflow requires the Autotask service and API.

Read this file before changing Autotask configuration, company lookup, ticket
or project-task lookup, connectivity checks, ticket/task status handling,
submission payloads, or Autotask diagnostics.

## Production Requirement

Autotask is mandatory for production.

Production startup requires:

- `APP_ENV=production`.
- `AUTOTASK_PROVIDER=autotask`.
- Valid application authentication settings.

The initial `/work` page and blank Start Work route must not run an Autotask
contactability probe. The mobile screen should render from local state first,
then service-call cards can load through `/work/service-calls` after the page
has loaded. Autotask is queried only when a workflow actually needs provider
  data, such as service-call loading, company search, work-target lookup,
service-call start verification, or Autotask submission/update/delete actions.

Mock mode remains available for tests and isolated development only.

Autotask resource IDs are database-managed per web user, not environment
configuration. A managed web user must have an Autotask resource ID before they
can start work. Routes pass that resource ID into service-call lookup and time
entry submission. Static role and billing-code IDs must not be environment
configuration. The live provider gets `TimeEntries.roleID` from the selected
ticket's `assignedResourceroleID` at submit time when available. If the ticket
omits that role, the provider first checks `TicketSecondaryResources` for a row
matching the selected ticket and the submitting managed user's resource ID, then
uses `Tickets.assignedResourceID` to resolve that ticket-assigned resource's
default or single active `ResourceServiceDeskRoles.roleID`, then uses the
submitting managed user's configured default service-desk role ID when present,
then falls back to the submitting managed user's default or single active
service-desk role. The final `TimeEntries.resourceID` must still be the
owning/submitting managed user's resource ID. The provider omits
`TimeEntries.billingCodeID` so Autotask
inherits the selected ticket's Work Type on create. API credentials, ticket
status IDs, time-entry type, and optional Autotask provider settings remain
environment-backed. New Autotask record submissions and submitted-entry
**Submit changes** resubmissions must patch `Tickets.status` to the selected
local ticket status and require the mapped tenant status ID. Do not add a global
Autotask impersonation resource setting; user-scoped workflows use the owning
managed web user's resource ID in payloads and filters but do not send
Autotask's optional `ImpersonationResourceId` header.
The config super admin may use `/users` to query Autotask Resources by name
while creating a managed web user, and may query active
`ResourceServiceDeskRoles` by selected Resource ID for a per-user default role
dropdown. The provider may also query matching `Roles` records so the dropdown
shows human-readable role names while the form still submits and stores the
numeric `roleID`. These lookups must still go through the server-side provider
and return only safe metadata. When the selected resource includes an email
address, the user manager stores it with the managed web-user row for future
user-scoped features.

## Provider Location

All Autotask behavior belongs in `ticket_pilot/services/autotask.py`.

Do not put direct Autotask HTTP calls in routes, templates, or browser
JavaScript. Routes should call the provider/service interface and return safe
data to the browser.

All live Autotask REST calls must pass through
`LiveAutotaskProvider._api_request()`. That wrapper enforces
`AUTOTASK_MAX_CONCURRENT_REQUESTS`, which defaults to `2` and is validated from
`1` through `3` to stay below Autotask's three-thread threshold. The limiter is
process-local and, when PostgreSQL is available, also uses advisory locks so app
processes sharing the same database coordinate the cap. Separate deployments
that use different databases but share one Autotask tenant or API user must use
lower per-instance caps because they cannot coordinate through the database.

Current provider responsibilities:

- Validate live Autotask configuration.
- Build non-secret request headers.
- Test connectivity.
- Search companies for client autocomplete.
- Search Resources for super-admin managed-user setup.
- Query one selected company by ID.
- Query open tickets for a company.
- Query time-eligible projects and non-complete tasks assigned to the managed
  user's Autotask resource as either primary or secondary resource.
- Query active tenant `Tasks.status` picklist metadata.
- Resolve transient ticket and service-call navigation destinations from
  `CompanyLocations` and company main-address fields.
- Query selected-day service calls for the logged-in managed web user's
  resource.
- Resolve service-call ticket/resource relationships before starting a job from
  a service call.
- Resolve service-call task/resource relationships without collapsing them
  into ticket associations.
- Query bounded read-only `TicketNotes` rows for a selected ticket number.
- Query bounded read-only `TaskNotes` rows for a selected project task.
- Query bounded read-only `TimeEntries` rows for a selected ticket number.
- Query bounded read-only `TimeEntries` rows for a selected project task.
- Query ticket status picklist metadata.
- Query a ticket ID from a ticket number.
- Keep service-call and open-ticket selection read-only against Autotask while
  the workflow stores a local editable default status of `In progress`.
- Update selected ticket status during time-entry and ticket-note submission
  using the local app ticket status and tenant status IDs.
- Update ticket status during submitted-record edits using the local app ticket
  status and tenant status IDs.
- Create `TimeEntries`.
- Patch existing submitted `TimeEntries`.
- Delete existing submitted `TimeEntries` when the local job must return to
  review.
- Create customer-visible `TicketNotes`.
- Patch existing submitted `TicketNotes`.
- Create and patch task-owned `TaskNotes`; never use `ProjectNotes`.
- Create task `TimeEntries` with `taskID` and time-entry type `6`.
- Patch only `Tasks.status` for project-task work and never patch the parent
  `Projects.status`.
- Reject submitted `TicketNotes` deletion because the Autotask REST entity
  does not support that operation.
- Return sanitized submission results.

## Mandatory Connectivity Test

The Diagnostics page posts to `POST /diagnostics/autotask/test`.

The connectivity test must remain safe:

- Do not print secrets.
- Do not log request headers.
- Do not log raw Autotask credentials.
- Return actionable troubleshooting tips.
- Audit the test result without sensitive details.

The live check currently verifies:

- Required workflow configuration is present.
- Company query endpoint is reachable.
- CompanyLocations query endpoint is reachable.
- Ticket status metadata endpoint is reachable.
- Ticket query endpoint is reachable.

If this check fails, show a clear diagnostic result, but do not wire this check
into `/work` page rendering or blank Start Work. Keep the Diagnostics page on
`test_autotask_connectivity()` so operator-triggered diagnostics always run a
fresh live check.

## Company Search And Ticket Lookup

The browser calls `/autotask/companies` while the user types a client name.

Important rules:

- Require authentication.
- Return only safe company options: ID and display name.
- Do not expose raw Autotask API responses to the browser.
- Saving a client requires a selected Autotask company option. The submitted
  display name and company ID must verify against the provider by ID before
  either value is persisted.
- Typed-only client names, missing company IDs, and names that do not match the
  selected Autotask company ID must be rejected and not saved.
- On the active mobile card, a selected Autotask company stays editable until
  an open ticket is selected, so users can switch to another verified client
  and load that client's open tickets. Once a ticket is selected, the client
  identity is locked and should be shown as read-only so the visible client name
  cannot drift away from the identity used for the selected ticket.
- On review, stored client name, company ID, ticket number, ticket title, and
  ticket description are read-only identity/context fields. Save/accept
  handlers must overlay those values from the database before validation so
  crafted form posts cannot change which Autotask ticket receives time or what
  ticket context is displayed. The only review exception is an active job with
  no client name, company ID, or ticket number yet; `POST /review/{job_id}/client`
  may save that first verified client/company selection and audit it before
  normal open-ticket lookup. Review client search input must not be included in
  generic review autosave.

Ticket lookup uses `/review/{job_id}/tickets`.

Ticket lookup requires the stored Autotask company ID and verified client name.

Ticket options returned to the browser include safe ticket number, title,
bounded description, status label, company name, local display dates derived
from `Tickets.createDate` as **Start** and `Tickets.dueDateTime` as **Due by**,
and display-only work-location detection. Review ticket selection uses
`POST /review/{job_id}/ticket`; the
route uses the server-verified open-ticket list that was just loaded when the
short-lived selection cache is available, falls back to re-querying Autotask
when that cache is expired or absent, verifies the submitted ticket number is
valid for the job's stored client/company, then persists the ticket number,
title, and bounded description as local job metadata and defaults the local
editable ticket status to In progress. It must not patch Autotask ticket status
or perform any other remote write. The review detail heading and
ticket-description card can then show the chosen ticket context without
repeatedly querying Autotask.

On mobile, ticket numbers are populated from the open-ticket picker instead of
manual entry. The ticket choice posts to `POST /jobs/{job_id}/ticket`; that
route uses the same server-side selection cache or a fresh Autotask lookup,
verifies the selected ticket is valid for that job, and persists the ticket
number, title, and bounded description returned by the provider, then defaults
the local editable ticket status to In progress. This selection path must not
patch Autotask ticket status or perform any other remote write. While no ticket
options are loaded, the mobile open-ticket panel itself is clickable and
keyboard-activatable; that action first saves the active job's current client
selection through `POST /jobs/{job_id}/ticket-number` with a JSON response, shows
the spinner loading state, then loads open tickets from the server-verified
lookup endpoint. A saved active-job client may be replaced through the same
company search before ticket selection, and changing the client must clear any
stale ticket options before loading that new client's tickets. The review
open-ticket panel uses the same click-to-load pattern. When Review is opened
for an active job that has no client yet, the review page exposes the same
authenticated Autotask company search and saves the first selected
client/company through `POST /review/{job_id}/client` before ticket lookup.
Open-ticket options should include a display-only Remote, On-Site, or Not
specified label inferred from safe ticket title/description text, falling
back to remote-only ticket source labels when text has no result, and expose the
matching `.ticket-location-*` CSS class for the browser. They should also
include a safe `has_customer_notes` boolean from one batched, bounded
`TicketNotes` query across the returned ticket IDs. Apply the same system-note
filter used by the overlay before setting that boolean. A note-availability
lookup failure must default the indicator off without blocking the primary
open-ticket lookup. After mobile or review
selection succeeds, the UI hides the open-ticket list and updates visible ticket
number/title/description fields from the verified JSON response rather than
trusting the clicked browser option. The mobile UI must also make the current
client input read-only immediately after a successful ticket selection, and the
service layer must reject crafted client/company changes after the ticket
exists.

## Project Task Lookup

The same selected-company work picker also returns a separate **Project tasks**
group. The browser must not submit task titles, project names, task statuses, or
assignment claims as authority.

The live provider must:

- Query `Projects` for the verified company.
- Exclude projects whose current metadata labels identify them as Complete,
  Inactive, Template, or Baseline.
- Query `Tasks` for the remaining projects.
- Include only non-complete tasks where the managed user's Autotask resource ID
  is `Tasks.assignedResourceID` or appears in `TaskSecondaryResources`.
- Return bounded task number, title, description, project number/name,
  task-status label, schedule context, location detection, and a safe
  TaskNotes-availability flag.
- Cache the returned selection list briefly and verify a clicked task ID
  against that server-side list or a fresh query before storing it.

Autotask does not expose a task-level allow-time-entry field. Actual permission
to enter task time comes from the resource's Autotask Projects security level,
including its **Can enter time on** setting. The picker narrows choices to
assigned tasks on project types where Autotask permits time entry; the provider
must still surface a safe Autotask rejection if tenant security denies the
submission.

After selection, store `work_target_type=project_task`, task ID/number/title,
parent project ID/number/name, and the selected task status. Clear ticket-only
identity fields. Keep client, task, and parent-project identity read-only from
then on.

Task status is independent from project status. Fetch active options from
`Tasks.status` entity metadata, validate the submitted numeric ID server-side,
and show the field in the same workflow position as ticket status under the
label **Task status**. Do not map task statuses through
`AUTOTASK_STATUS_*_ID`, and never use `Projects.status` as the work status.
Autotask documents task Complete as status ID `5`; use that value only for the
special completion ordering rule.

The tenant mappings `AUTOTASK_STATUS_NEW_ID` and
`AUTOTASK_STATUS_CUSTOMER_NOTE_ADDED_ID` are read-only observed statuses.
Neither belongs in TicketPilot's editable status enum or dropdown. Selection
routes must compare the server-verified numeric ticket status ID, not the
display label, and may return only the safe
`open_customer_note_overlay` presentation flag. For **Customer Note Added**,
Work and Review reuse the existing Ticket notes overlay, refresh its
authenticated data, and select the newest note.

Ticket notes use `GET /review/{job_id}/ticket-notes`. This route must require
an authenticated session, enforce normal review visibility and ownership rules,
use the stored ticket number from the database, and call the server-side
provider. The browser must not call Autotask directly. The response should
contain only bounded safe fields needed by the overlay, such as note ID, title,
description, safe author display text, created/updated display times, type, and
publish metadata. Filter out Autotask system notes whose note type is
`Workflow Rule` or `Service Desk Notification`, whose title is
`Service Desk Notification`, whose title starts with `Workflow Rule`, or whose
title starts with `Some actions did not occur` before sorting or deciding
whether the ticket has notes. Return the remaining notes
ordered by created date/time with newest first. Keep the Work in Progress and
Review **Ticket notes** button hidden until a ticket exists and the
authenticated lookup has completed. If the lookup returns zero displayable
notes, show a disabled
same-place **No Notes** button instead of opening the overlay. The overlay list
cards should render only note titles; note body text and author metadata belong
in the selected note detail. When displayable notes exist, show the shared
**Note** indicator in the active highlight's complementary counterpart color
beside the selected Ticket name and inside the counterpart-highlighted
**Ticket notes** button.

Past time entries use `GET /review/{job_id}/ticket-time-entries`. This route
must require an authenticated session, enforce normal review visibility and
ownership rules, use the stored ticket number from the database, and call the
server-side provider. The provider should query the selected ticket ID, then
bounded `TimeEntries` rows for that ticket, and resolve `resourceID` values
through safe `Resources` display names. The response should contain only the
fields needed by the overlay: time-entry ID, safe resource display name,
formatted local start/stop/hours text, and bounded summary notes. Keep the Work
in Progress and Review **Past time entries** button hidden until a ticket
exists and the authenticated lookup has completed. If the lookup returns zero
rows, show a disabled same-place **No past entries** button instead of opening
the overlay. The overlay list cards should show resource and time range only;
summary notes belong in the selected detail pane.

For project-task targets, reuse those authenticated overlay routes and safe
view models but dispatch reads to `TaskNotes` by stored task ID and
`TimeEntries` by `taskID`. User-facing labels must say **Project task notes**,
not Ticket notes or Project notes. The note indicator uses the same bounded,
optional lookup and counterpart color. A task-note lookup failure must not
block task selection or time entry. The parent project must not be queried for
notes.

## Service Call Lookup

The mobile start panels can list selected-day Autotask service calls for the
logged-in managed web user's Autotask resource ID. This is a read-only
convenience path for starting a job from scheduled dispatch data, not a
separate trust boundary. The browser may ask for another local date through
`/work/service-calls?date=YYYY-MM-DD`; the resource ID still comes only from
the authenticated managed web user.

Service-call lookup must stay inside `ticket_pilot/services/autotask.py` because
it needs several related Autotask entities:

- `ServiceCalls` for scheduled call details in the selected local date bounds.
- `ServiceCallTickets` to identify tickets associated with each service call.
- `ServiceCallTicketResources` to verify the user's resource is assigned to
  that specific service-call ticket row.
- `ServiceCallTasks` to identify project tasks associated with each service
  call.
- `ServiceCallTaskResources` to verify the user's resource is assigned to that
  specific service-call task row.
- `Tickets` for ticket number, title, bounded description, status, and source.
- `Tasks` and `Projects` for task, parent-project, company, status, schedule,
  role, and navigation context.
- `Companies` for the client name stored with the new active job.
- `CompanyLocations` for service-call, ticket, and primary company navigation
  destinations.

Ticket and service-call navigation addresses remain transient provider data.
Browser code must not request or launch them on a full web browser unless the
managed user has enabled both a navigation app and the default-off **Allow
navigation on full web version** preference. Phones, tablets, iPads, and iPods
remain eligible whenever navigation itself is enabled.

The browser must submit only the target type, the selected service-call
association ID, `service_call_date`, and CSRF to
`POST /jobs/start/service-call`. Continue accepting the legacy
`service_call_ticket_id` field for ticket associations. The route re-reads the
provider's server-verified list for the selected local date and current managed
web user's resource, matches both the target type and association ID, and only
then creates a job.
If one service call has ticket and task associations, return one clearly
labeled card for each association rather than merging or preferring one.
Filter out ticket associations that already have a local TicketPilot job for
that user with ticket status Complete or Follow up. Filter out task
associations when that user already has a local job for the same task with task
status Complete.
Apply the same local Complete/Follow up filter to `/work/service-calls`
responses for tickets and the task Complete filter for project tasks; this is
local workflow state and should not be pushed into the provider query. Never
accept target number, title, description, client name, company ID, project
identity, status, or work-location values from hidden fields for this path.
Starting from a service call stores verified local job metadata and defaults
ticket status to In progress or preserves the task's current status, but it
must not patch Autotask status or perform another remote write before
submission.

When the verified service-call ticket status ID matches
`AUTOTASK_STATUS_CUSTOMER_NOTE_ADDED_ID`, the JSON start response may request
the same one-time Ticket notes overlay. Carry only the newly created local job
ID through same-tab session storage when navigation or redirect separates the
start response from the refreshed Work page. Consume that value once, match it
against a rendered active job, and still load notes only through the
authenticated server route.

Navigation address priority is service-call `companylocationID`, ticket
`companylocationID`, primary active CompanyLocation, then the Companies main
address. Regular selected tickets start at ticket `companylocationID`, then use
the same company fallbacks. Validate every CompanyLocation belongs to the
expected company. Return a bounded single-line address only; do not return raw
location rows and do not store customer addresses on Job or audit rows.

The `/work/service-calls` response includes a preformatted local scheduled date
and may include a local start/end time range for display, such as
`06/20/2026 · 4:00pm-5:00pm`. Treat that context as
read-only card context; it must not be submitted back by the browser or used as
the authorization source for starting a job. Service-call choices should also
receive the same safe `has_customer_notes` boolean from one batched, bounded
TicketNotes availability lookup and show the shared counterpart-colored
**Note** indicator when true. A failed optional note lookup must not hide
otherwise valid service calls.

## Resource Lookup

The `/users/autotask-resources` endpoint is for config super admins only. It
lets the user manager search Autotask Resources while creating or editing
managed web users and returns safe fields such as resource ID, first name, last
name, display name, and email when available.

Resource lookup must stay inside `ticket_pilot/services/autotask.py`. Browser
JavaScript may call TicketPilot's authenticated endpoint, but it must never call
Autotask directly or receive Autotask credentials. Autotask formats resource
names as `Last, First`; the provider should accept either `First Last` or
`Last, First`, query `Resources/query` with bounded first-name and last-name
filters, deduplicate IDs, and cache only positive non-secret results briefly.
When the browser submits the selected resource email back with the add/edit
form, the server must treat it as optional metadata, validate it as a bounded
email address, and never trust it as an authorization source.

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
`ServiceCallTickets`, `ServiceCallTicketResources`, and `CompanyLocations` in
addition to the existing Companies/Tickets permissions. Service-call lookup failures should be
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

Caching reduces repeated reads, but it is not the thread-threshold control.
Keep the shared request limiter in place for every live request, including
cache misses, diagnostics, ticket history lookups, submissions, updates, and
deletes.

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

Autotask submission happens after review acceptance or retry by default. A
managed web user can opt in to **Submit from Work in Progress** on `/config`;
when enabled, ending an active job submits the selected Time entry, Ticket
note, or Project task note through the same service immediately after local
end-work validation succeeds.

Required local fields before time-entry submission:

- Verified ticket number or project-task and parent-project IDs.
- Ticket status or task status.
- One local job date.
- Start time.
- End time.
- Summary notes.
- Work location mode, which defaults to Remote.
- Append to resolution.

Time entries must also meet the selected work-location minimum before any
Autotask create or update leaves the app: Remote requires at least 15 rounded
minutes, and On-Site requires at least 1 rounded hour. Keep this validation in
the workflow service so direct Work in Progress submission, Review
accept/retry, and submitted-entry **Submit changes** share the same rule.

Required local fields before ticket-note submission:

- Ticket number.
- Ticket status.
- Note title.
- Note description.

Project-task-note submission requires the verified task and parent project,
tenant-validated task status, note title, and note description. It must not
require time fields, work location, or append-to-resolution.

Direct Work in Progress submission must not bypass these requirements. If a
required local field is missing, the end-work transaction should roll back and
leave the job active. If the Autotask provider returns a safe failure, the job
should use the existing failed-submission review state so the user can retry
from Review.

Required live Autotask values include:

- The owning managed web user's Autotask resource ID.
- A usable role ID from the selected ticket's assigned role or, when that is
  missing, the submitting user's ticket-specific secondary resource role, the
  ticket-assigned resource's service-desk role, or the submitting resource's
  service-desk role.
- Time entry type.
- Tenant-specific ticket status picklist IDs for each selectable local status.
- Tenant-specific `New` and `Customer Note Added` status IDs used only to
  recognize server-verified ticket state.
- Current `Tasks.status` picklist metadata for project-task status validation.
- One unambiguous role assignment for the submitting resource on a project
  task, either the task's primary assigned role or the matching
  `TaskSecondaryResources.roleID`.

Ticket `TimeEntries` creation must query the selected `Tickets` row by
`ticketNumber` and use `assignedResourceroleID` for `TimeEntries.roleID` when
the ticket provides one. If the ticket omits that role, query
`TicketSecondaryResources` for the selected `ticketID` and submitting managed
user's resource ID before generic resource-role fallbacks. If no matching
ticket-specific secondary role exists, query `ResourceServiceDeskRoles` for
`Tickets.assignedResourceID` first. If that does not produce a role, use the
submitting managed user's configured default service-desk role ID when one was
selected on `/users`, then query `ResourceServiceDeskRoles` for the submitting
managed user's resource ID. A generic resource-role lookup may use the default
active role, or a single active role when Autotask does not mark a default. If
multiple active roles exist without a default and no configured per-user role is
available, fail clearly instead of choosing one arbitrarily. Autotask may still
reject a fallback role when tenant permissions or ticket rules require a
different role.

Ticket `TimeEntries` creation must not include `billingCodeID`. Autotask labels
that as Allocation Code / Work Type. On create, omitting it lets Autotask
inherit the selected ticket's `billingCodeID`; passing the field can require
extra Allocation Code edit permission even when the value matches the ticket.

Ticket `TimeEntries.summaryNotes` must be built from the stored work-location
mode plus the reviewed summary text. The local `summary_notes` field stays
unprefixed for mobile and persistence. Review detail displays the full
Autotask-bound summary, including `Remote. ` or `On-Site. `, so the operator can
correct the prefix before submission or submitted-entry update. Save, accept,
retry, and submitted-entry update handlers must parse that visible prefix back
into `work_location` before building the final payload, while still accepting
older `Remote`, `Remote:`, `Remote -`, and matching On-Site prefixes.

Ticket `TicketNotes` creation must query the selected `Tickets` row by
`ticketNumber` to get `ticketID`, then create the note through the child
`/Tickets/{ticketID}/Notes` endpoint. Submitted-note updates must patch that
same child endpoint with the stored TicketNotes ID in the request body. Keep
bounded reads on `/TicketNotes/query`. The mutation payload must use the local
note title as `title`, the unprefixed note description as `description`, the
configured customer-visible publish value, and the default ticket-note type
value; the child endpoint supplies the parent ticket identity.
TicketPilot ticket notes must never be internal. Ticket-note submission and
submitted-note updates do not require or send append-to-resolution, start time,
end time, hours worked, work location, role ID, billing code, or time-entry
type. Autotask documents `appendToResolution` for `TimeEntries`, but not for
`TicketNotes`, so the ticket-note payload must omit it.

Project-task `TimeEntries` creation must send `taskID`, omit `ticketID`, and
use `timeEntryType=6` (`ProjectTask`). The resource ID is still the owning
managed user's Autotask resource ID. The role ID must be that user's primary
task role when the user is the primary resource, or the one unambiguous
matching `TaskSecondaryResources.roleID` when the user is secondary. Fail
clearly if neither source supplies a valid task role.

Project-task note mode creates or patches `TaskNotes` through
`/Tasks/{taskID}/Notes`; it must never create `ProjectNotes`. Use the local note
title and description, the configured TaskNotes publish/type values, and omit
time-entry-only and ticket-only fields. The Autotask TaskNotes description is
limited to 3,200 characters.

For any non-complete task status, apply `Tasks.status` before creating the
external record. For Complete status ID `5`, create or patch the `TimeEntries`
or `TaskNotes` row first and patch `Tasks.status` last. Before either create or
submitted-entry update, globally block Complete while any other Active, Ready
for Review, or Submission Failed local job for the same task ID exists,
regardless of owner or record type. Task status mutations use the
`/Projects/{projectID}/Tasks` child endpoint and must never update
`Projects.status`.

Time entries must include the local append-to-resolution checkbox value in the
Autotask payload. The local setting defaults on for newly created jobs and for
restored legacy rows that did not have the column.

User-scoped live calls must use the owning managed web user's Autotask resource
ID for local `resourceID` payloads and resource filters. They must not send the
optional Autotask `ImpersonationResourceId` header. Super-admin Resource lookup
and debug connectivity checks do not have an owning managed user and must not
use a global impersonation fallback.

Submission must remain idempotent. A retry must not create duplicate Autotask
records for the same accepted job.

Both Review acceptance and direct Work in Progress submission must call
`submit_job_to_autotask()` so idempotency keys, submission attempts, safe error
handling, required target-status updates, role lookup, and summary construction
remain centralized.

After a provider reports successful submission, target identity and destructive
workflow actions remain protected. Do not allow later review save, ticket
or project-task selection, accept/resend, retry, local delete actions, or entry-type conversion
for that job. Supported submitted-job mutations are limited to audited external
record actions: time-entry **Submit changes** validates one job date,
start/end times, summary notes, work location, append-to-resolution, and ticket
status, then patches the existing Autotask `TimeEntries` row by its stored
external ID. Ticket-note **Submit changes** validates note title, note
description and ticket status, then patches the existing
Autotask `TicketNotes` row by its stored external ID. Project-task Time entries
and notes use the same editable field categories while patching the existing
`TimeEntries` or `TaskNotes` row and reasserting the validated Task status.
Ticket paths reassert the selected local ticket status on `Tickets.status`;
task paths reassert only `Tasks.status`. A previously submitted Complete target
may be moved to In progress before patching the external record, then moved to
the selected final status after the record patch when needed. **Delete From
Autotask** deletes `TimeEntries/{id}` and returns the
local job to review only after Autotask confirms the delete. Autotask does not
support deleting `TicketNotes` through this REST entity, so submitted ticket
notes must not expose or call that action. If a time-entry delete fails, the
selected review detail may offer
a session-scoped, local-only purge fallback that removes the TicketPilot row
while warning that the Autotask record may still exist. If either action fails,
keep local state aligned with the last known successful Autotask state and
store only safe error details.

Live Autotask write failures should use `_raise_for_safe_response()` so bounded
body-level messages from `Tickets`, `TimeEntries`, or `TicketNotes` errors are
shown without falling back to generic HTTP client exception text.

## Diagnostics And Scripts

The Diagnostics page is a Diagnostics-authorized runtime visibility surface for the
config super admin and managed web users marked Admin. It should show the
source-controlled application version, sanitized config, connectivity test
results, and submission attempts under the **Diagnostics** page title. The
desktop header may label the route **Diag** to keep navigation compact. The
submission-attempt list should keep its full table width inside a horizontal
scroller on phone layouts so attempt metadata does not get squeezed into
unreadable columns.
Autotask provider failures also update cached app health. Any failed live
Autotask HTTP/status response, failed time-entry or ticket-note
submission/update/delete result, or failed manual connectivity test should keep
the authenticated top-bar degraded-health Help link, Diagnostics app-health banner,
and optional Pushover health notification state degraded until the same
semantic Autotask operation type succeeds again. A successful request for a
different operation must not clear another operation's active failure. This
applies to live Autotask requests triggered by ordinary managed users, managed
Admin users, and the config super admin. Do not run the connectivity test from
shared header rendering; the header reads cached state only.

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
