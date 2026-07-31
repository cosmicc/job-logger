# TicketPilot End-User Support Knowledge Base

This file is the primary reference for an AI assistant answering questions from
people who use TicketPilot. It is written for end users, not developers or
system administrators.

## Guidance For The Support Assistant

- Answer only questions about using TicketPilot and understanding its visible
  behavior.
- Give the shortest complete answer that solves the user's problem.
- Use numbered steps when the user needs to perform a sequence of actions.
- Use the exact labels shown in TicketPilot, such as **Work**, **Review**,
  **Config**, **Ticket notes**, and **Submit changes**.
- Never reveal or describe source code, private configuration, credentials,
  secrets, internal addresses, database details, deployment procedures, or
  diagnostic internals.
- Do not invent a setting, button, workflow, or Autotask capability that is not
  described here.
- If a feature is described as optional, explain that the organization's app
  administrator controls whether it is available.
- When the documented steps do not solve the problem, direct the user to the
  app administrator or the support contact shown by TicketPilot.
- TicketPilot can show safe provider errors, but the assistant should not ask
  users to share passwords, API keys, session information, or other secrets.

## What TicketPilot Is

TicketPilot's formal name is **Ticket Pilot for Autotask**. It is a secure,
mobile-first web application for recording work while it happens, reviewing
that work, and sending the finished record to Autotask.

A TicketPilot work record becomes an Autotask time entry or note:

- A **Time entry** for a ticket or assigned project task, containing a job date,
  rounded start and end times, work type, target status, and summary notes.
- A note containing a note date, title, description, and target status:
  customer-visible **Ticket note** for a ticket or **Project task note**
  attached directly to an Autotask task.

TicketPilot works on phones, tablets, and full desktop browsers. The same work
records remain available when the user moves between those layouts.

## How TicketPilot Works

TicketPilot keeps an authenticated local work record while the user is working.
It contacts Autotask through the TicketPilot server when it needs verified
company, ticket, project-task, service-call, note, time-entry, or submission
information. The browser does not connect directly to Autotask.

This design lets TicketPilot:

- Preserve active and reviewed work until the user takes an explicit action.
- Verify companies, tickets, and project tasks before saving their identity.
- Apply the same ownership, required-field, duration, and status rules on Work
  and Review.
- Retry an Autotask submission without intentionally creating a duplicate.
- Keep a history of important work and submission actions.
- Show safe errors without displaying private Autotask connection details.

TicketPilot requires a working network connection. The installed phone version
is a convenient app-style launcher, not an offline copy of job or ticket data.

All user-facing dates and times use the application's local
America/Detroit time zone. Times appear in 12-hour am/pm format. Time-entry
start times, end times, and durations use 15-minute increments.

## Privacy And Safety In Normal Use

- Each managed user works under their own TicketPilot account and Autotask
  resource identity.
- Normal users see and change only their own work records.
- The selected Autotask company and ticket become read-only identity fields
  after ticket selection.
- Passwords are never shown after they are entered.
- Raw microphone recordings are not permanently retained by default. The
  resulting text is kept as the work summary or note description.
- AI Cleanup sends only the current work text and limited job context to the
  organization's configured cleanup provider.
- AI Help handles one support question at a time and does not save questions or
  answers in the TicketPilot database.
- Ticket and customer addresses are used only when directions are requested;
  they are not stored as part of the local job record.
- Important changes and submissions are recorded so work does not disappear
  silently.

## Signing In

Open the TicketPilot address provided by the organization. The public sign-in
page always uses a neutral black, white, and grey appearance. Personal
background and highlight choices apply after sign-in.

Enter the assigned username and password. A newly created or administratively
reset password is temporary. TicketPilot requires the user to choose a new
password before opening the rest of the app.

A managed-user password must contain:

- At least 8 characters.
- At least one lowercase letter.
- At least one uppercase letter.
- At least one number.
- At least one symbol.

If **This is a public device** is checked before password sign-in, TicketPilot:

- Ends the session after 15 minutes of inactivity.
- Does not offer Device sign-in setup during that session.
- Prevents new Device sign-in registration until the user signs in normally.

The public-device option does not remove any normal sign-in or security checks.

If an account is disabled, TicketPilot explains that only after the correct
password or Device sign-in has verified the account. Use the displayed support
contact when available, or contact the app administrator.

Several failed sign-in attempts can temporarily block additional attempts from
that location. Wait for the temporary lockout to end or contact the app
administrator.

## Forgot Password

The **Forgot password?** link appears only when the organization has enabled
self-service password reset.

To request a reset:

1. Select **Forgot password?** on the sign-in page.
2. Enter the email address associated with the TicketPilot account.
3. Complete the human-verification prompt when it appears.
4. Open the reset link received by email.
5. Enter a new password that meets the displayed requirements.
6. Sign in with the new password.

For privacy, TicketPilot shows the same confirmation whether or not an enabled
account matches the submitted email. A reset email is sent only when exactly
one enabled account matches. Reset links work once and expire after 24 hours.

Repeated reset requests for unknown, disabled, or duplicate account matches
can temporarily block additional requests from that location. Carefully check
the email address before trying again.

## Installing TicketPilot On A Phone

1. Open the organization's TicketPilot address in the phone browser.
2. Sign in.
3. Open the browser's sharing or page menu.
4. Choose **Install App** or **Add to Home Screen**.

The installed app uses the TicketPilot icon and opens without the normal
browser toolbar. If the phone keeps an old icon after an update, remove the
installed shortcut or app and install it again.

## Device Sign-In

Device sign-in is TicketPilot's name for a passkey-style sign-in. Depending on
the device, it may use a biometric unlock, PIN, pattern, security key, browser
profile, phone, or another passkey-capable device.

To set it up:

1. Sign in with the normal username and password.
2. Change a temporary password first when required.
3. Open **Config**.
4. Find the final **Device sign-in** card.
5. Select **Set up device sign-in**.
6. Follow the browser or device prompt.

TicketPilot may also show a one-time phone prompt on Work when the account has
no registered Device sign-in.

After setup, the sign-in page still shows normal username and password fields.
Select **Device sign-in** to use the saved credential. Password sign-in remains
available as a fallback.

A user can delete a registered Device sign-in from Config. Deleting it does not
change the account password. Setup is unavailable while the current session is
marked as a public-device session.

## Main Navigation

The authenticated header contains:

- **Work** for starting and managing active work.
- **Review** for completed, failed, and submitted records.
- **Config** for personal appearance, password, navigation, workflow, and
  Device sign-in settings.
- **Help** for AI support, operational status, version information, and the
  version changelog.
- **Log out** for ending the local session.

The header stays visible while the page scrolls. Phone navigation uses compact
icons. Full-browser navigation uses icons and text.

Some managed users may also see an administrative shortcut. Its presence does
not change the normal Work, Review, or Config workflow.

## Operational-Status Indicator

A yellow or red status icon in the authenticated header means TicketPilot has
detected an operational problem. Selecting it opens the **Operational Status**
section on Help.

Users can often continue recording local work when an external service is
temporarily unavailable. Submission or ticket lookup may still fail until the
service recovers. Contact the app administrator when the status remains
degraded or blocks work.

A yellow Help button or **DEV** beside the version means the user is on a
development or testing TicketPilot instance rather than production.

## Work Page Overview

Work is the main page for active jobs. It shows:

- A compact total of the user's time-entry hours for Today and Week.
- Existing Work in Progress cards.
- A blank **Start a time entry** panel when another active slot is available.
- Scheduled Autotask ticket or project-task service calls for the selected day
  when available.
- Optional Home and Office navigation buttons.

Ticket notes do not add to Today or Week hours because they do not contain work
time.

Each user can have up to two active Work in Progress records. When two records
are active, the newer record appears first and the cards use the selected
highlight color and its complementary counterpart color to remain visually
distinct.

## Starting Blank Work

Select **Start Work** in the **Start a time entry** panel. TicketPilot creates
a local Work in Progress record immediately. The user can then:

1. Select a verified client.
2. Load the grouped choices and select a ticket or assigned project task.
3. Confirm Time entry, Ticket note, or Project task note mode.
4. Complete the remaining work fields.
5. Record or type notes.
6. Finish the record or submit it directly, depending on Config.

Starting blank work does not require TicketPilot to test every Autotask
connection first. Provider data is loaded when the user searches for a client,
loads tickets, or submits.

## Starting From A Service Call

When an active slot is available, the service-call section loads scheduled
calls assigned to the signed-in user's Autotask resource.

Use the date arrows or the displayed date to choose a service-call day. The
date chooser includes **Today**, **Cancel**, and **Set**.

A service-call card can show:

- A **Ticket** or **Project task** target label.
- Client name.
- Scheduled local date and time.
- Target title.
- Remote or On-Site work type.
- A **Note** badge when displayable customer-note history exists.

Remote and On-Site cards use the user's selected highlight and complementary
counterpart colors. Selecting a service call creates a Work in Progress record
from server-verified Autotask information.

If one service call has both a ticket and a project task, TicketPilot shows a
separate selectable card for each association.

A ticket service call is hidden for the current user when that user already has
a local job for the same ticket with a Complete or Follow up ticket status. A
project-task service call is hidden when that user already has a local Complete
record for the same task.

When navigation is configured, starting an On-Site service call can open
directions after TicketPilot confirms the local job was created. The user can
turn off automatic opening while keeping manual destination navigation.
Remote service calls do not open directions automatically.

## Work In Progress Fields

### Entry Type

Choose **Time entry** or note mode before successful submission. Ticket targets
label note mode **Ticket note**. Project-task targets label it **Project task
note**.

- Time entry uses date, start time, end time, duration, work type, summary, and
  optional Append to resolution.
- Ticket note and Project task note use Note Date, Note title, Note description,
  and the selected target's status.

The selected Time entry choice uses the user's highlight color. The selected
Ticket note choice uses that highlight's automatic complementary counterpart.

### Work Type

Time entries use **Remote** or **On-Site**.

- Remote uses the user's highlight color.
- On-Site uses the matching complementary counterpart color.
- Ticket note and Project task note modes keep the Work type card visible but
  disabled because notes do not use work location.

Changing work type on an active time entry keeps the start time and
recalculates only the end time. Remote requires at least 15 minutes. On-Site
requires at least 1 hour. If the current rounded time is later than the minimum,
TicketPilot uses that later time.

### Ticket Status Or Task Status

TicketPilot can submit these user-selectable statuses:

- **In progress**
- **Waiting customer**
- **Waiting parts**
- **Mfg Trouble Ticket**
- **Follow up**
- **Complete**

Autotask may also return **New** or **Customer Note Added** on a ticket.
TicketPilot recognizes those states while selecting tickets, but users cannot
choose them in the local ticket-status menu.

For a project task, the same card says **Task status** and displays the active
task-status choices returned by that Autotask tenant. Task status is independent
from project status. TicketPilot changes only the selected task and never uses
or changes the whole project's status for this work record.

Before a Complete-status record can submit, TicketPilot checks for another
local entry for the same normalized ticket number that is Active, Ready for
Review, or Submission Failed. This check includes entries owned by other users
and includes both time entries and ticket notes. Every earlier entry must be
submitted first so the Complete record reaches Autotask last.

The same rule applies to a project task across every user and includes both
Time entries and Project task notes for that task. TicketPilot submits the
external TimeEntry or TaskNote before setting the task to Complete.

### Job Date Or Note Date

Time entries use **Job date**. Ticket notes use **Note Date**. TicketPilot's
calendar includes **Today**, **Cancel**, and **Set**.

Dates next to the current date may show **Today**, **Yesterday**, or
**Tomorrow** in the date control.

### Start Time, End Time, And Work Duration

Time entries use one local job date and rounded 15-minute start and end times.
Use the `-15` and `+15` controls or the time list to adjust them.

**Work Duration** shows the rounded duration represented by the visible times:

- Remote requires at least 15 minutes.
- On-Site requires at least 1 hour.
- The end must be after the start on the same date.

Note mode hides start, end, and duration because those values are not sent with
an Autotask TicketNote or TaskNote. Switching back to Time entry restores the
preserved time fields.

### Client Name

Begin typing the Autotask company name, then select the company from the
returned results. Typed text alone is not verified and cannot be saved as the
final client identity.

The selected client can be replaced before a ticket or project task is
selected. After target selection, the client becomes read-only for that record.

### Ticket Or Project Task Selection

After selecting a verified client, load the grouped **Tickets** and **Project
tasks** choices and select the correct work target.

Ticket choices can show:

- Ticket number and title.
- Current status and company.
- Start and Due by dates when Autotask provides them.
- Remote, On-Site, or Not specified detection.
- A **Note** badge when displayable customer-note history exists.

Remote cards use the user's highlight color. On-Site cards use the matching
counterpart color. Selecting a ticket saves its verified number, title,
description, company, and status context locally. It does not change the
Autotask ticket status during selection.

The selected ticket number, title, description, and client are read-only after
selection.

Project-task choices show task and parent-project context, current Task status,
schedule details when available, Remote/On-Site detection, and a Note badge when
TaskNotes exist. Only non-complete tasks assigned to the signed-in resource as a
primary or secondary resource are shown. Selecting a task stores verified task,
project, company, description, and status context without changing Autotask.
The task, parent project, and client then become read-only.

### Customer-Note Indicators

A **Note** badge means the ticket has at least one displayable customer-note
history item. TicketPilot filters several Autotask-generated system notes so
they do not trigger the indicator.

The same complementary counterpart color appears on:

- Open-ticket Note badges.
- Service-call Note badges.
- The selected Ticket name Note badge.
- The highlighted **Ticket notes** button.

The badge indicates available history only. It does not change the work type,
entry type, ticket status, or submission behavior.

### Ticket Notes, Project Task Notes, And Past Time Entries

When a selected target exists, TicketPilot checks for read-only history.

- **Ticket notes** opens displayable ticket-note history newest first.
- **Project task notes** opens TaskNotes attached directly to the selected task,
  not whole-project notes.
- **Past time entries** opens earlier Autotask time entries for the ticket or
  task.
- **No Notes** or **No past entries** appears disabled when no usable rows are
  returned.

Note selection cards show the title. Selecting one shows its safe
author, date, type, and note body when available. Long titles are contained
inside the card.

Past-time-entry cards show the resource name, local start and stop times, and
hours. Selecting one shows the time range and summary.

Use the X in the top-right corner to close either history overlay.

If the selected ticket's verified Autotask status is **Customer Note Added**,
TicketPilot automatically opens Ticket notes once and selects the newest note.
Closing the overlay or reloading keeps it closed. The **Ticket notes** button
can reopen it later.

### Ticket Or Task Description

The ticket or task description is read-only Autotask context. Long descriptions
use an internal scroll area instead of expanding the entire page. A clear
message appears when Autotask provides no description.

### Summary Notes And Note Description

For a Time entry, enter the work summary that should be sent to Autotask.
TicketPilot adds `Remote.` or `On-Site.` to the submitted summary according to
the selected work type.

For a Ticket note, enter the customer-visible note description. For a Project
task note, enter the TaskNote description, up to 3,200 characters. Notes do not
use a Remote or On-Site prefix.

### Note Title

Ticket notes and Project task notes require a non-empty note title. Time entries
do not use this field.

### Append To Resolution

Time entries show **Append to resolution**, enabled by default. It asks
Autotask to append the submitted time-entry content to the ticket resolution
where that tenant's workflow supports it.

Ticket note and Project task note modes completely hide this option because
Autotask note records do not support that field.

## Recording Notes

Select **Record** to begin dictation. The Record control uses the automatic
counterpart color so it stays distinct from the current highlight. Select
**Stop recording** to finish.

After recording stops, TicketPilot shows these phases:

1. **Sending data to server...**
2. **Converting audio to text...**
3. **Conversion complete.**

The final transcript replaces the editable summary or note description.
Review it carefully because names, numbers, product terms, and punctuation can
be misunderstood.

Recording is available on active Work and on unsubmitted Review records. It is
not available after successful Autotask submission.

If recording is unsupported or transcription fails, type the notes manually.

## AI Cleanup

When enabled by the organization, **AI Cleanup** improves the current summary
or note description for readability. It does not submit the record, change the
ticket, or bypass Review.

After successful cleanup, the control changes to **Revert cleanup** while the
original text is still available. Revert restores the pre-cleanup text.

Always review cleaned text before submission. A submitted Review record is not
updated in Autotask until the user explicitly selects **Submit changes**.

## Finishing Active Work

The Config setting **Submit from Work in Progress** controls the finish path.

When it is off:

- **End Work** finishes a Time entry and sends it to Review.
- **End Note** finishes a Ticket note and sends it to Review.

When it is on:

- **Submit to Autotask** finishes and directly submits a Time entry.
- **Submit note** finishes and directly submits a Ticket note.

Direct submission uses the same required-field, ownership, duration, ticket,
status, and Autotask rules as Review. A missing local field leaves the record
active so the user can correct it. A provider failure moves the record to
Review with a safe error so it can be fixed and retried.

## Deleting Active Work

Use **Delete** or **Delete Note** only when an active local record should be
discarded before submission. Deletion is explicit and cannot be used as a
normal submitted-entry correction method.

## Review Page

Review lists the user's active, completed, failed, and submitted records newest
first.

At the top:

- **Today** shows today's time-entry hours.
- **Week** shows the current week's time-entry hours.
- **Unsubmitted** counts Time entries in Active, Ready for Review, or Submission
  Failed states.

Ticket notes and Project task notes do not add hours or count toward
Unsubmitted. Rejected and successfully submitted records are also excluded
from that count.

Review controls include:

- **Hide submitted entries** to show only records still needing attention.
- A **Show** menu with 10, 20, 50, or 100 rows.
- **First**, **Previous**, **Next**, and **Last** pagination.

The initial full-browser row count is 20. The initial mobile row count is 10.
TicketPilot remembers the user's filter and row-count choices.

Review can be used to:

- Finish an active record opened from Review.
- Check and edit a completed record before submission.
- Correct missing or invalid fields.
- Submit or retry an Autotask record.
- Update supported fields on a submitted Autotask record.
- Delete a submitted Autotask time entry when supported.
- Remove an unsubmitted local record that should not be submitted.

Client and ticket or project-task identity stay read-only after selection. An
active record that has no client yet may select its first verified client from
Review.

## Review Fields

Before successful submission, Review supports the same applicable fields as
Work:

- Entry type.
- Work type for Time entries.
- Ticket status or Task status.
- Job date or Note Date.
- Start and end time for Time entries.
- Summary notes for Time entries.
- Note title and description for Ticket notes or Project task notes.
- Append to resolution for Time entries.

Time entries require verified ticket or project-task identity, target status,
job date, valid start and end time, and summary notes. Ticket notes require a
ticket number, status, title, and description. Project task notes require the
task and parent-project identity, Task status, title, and description.

Review displays the complete Time-entry summary that Autotask will receive,
including the `Remote.` or `On-Site.` prefix. Changing Work type updates that
prefix.

Most editable Review fields save automatically. Submission, retry, external
updates, and deletion remain explicit actions.

## Review Actions

### Accept And Submit

**Accept and Submit** creates the Autotask time entry, customer-visible Ticket
note, or task-owned Project task note after validation.

### Retry

**Retry** attempts a failed submission again. First correct the visible error
or missing field.

### Submit Changes

**Submit changes** updates a previously submitted Autotask record rather than
creating another one.

For a submitted Time entry, it can update:

- Job date.
- Start and end time.
- Work summary.
- Remote or On-Site work type.
- Append to resolution.
- Ticket status.

For a submitted Ticket note, it can update:

- Note title.
- Note description.
- Ticket status.

For a submitted Project task note, it can update the note title, note
description, and Task status. The selected Ticket or Task status is applied
again during Submit changes; task updates never change the parent project.

### Delete From Autotask

For a submitted Time entry, **Delete From Autotask** removes the external time
entry and returns the retained TicketPilot record to Review.

Autotask does not support deleting submitted TicketNotes or TaskNotes through
this TicketPilot workflow, so the button is not shown for submitted notes.

If Autotask cannot complete a Time-entry deletion, TicketPilot may offer a
clearly warned local-only cleanup. Use it only after understanding that the
Autotask record may still exist.

### Delete Time Entry Or Delete Note

These actions remove an unsubmitted local Review record that should not be sent
to Autotask. They are unavailable as normal cleanup for successfully submitted
records.

## Config Page

Most Config options save immediately. Password and Device sign-in actions
require explicit confirmation.

The page identifies the signed-in account as **User Settings for Full Name
(username)**.

### Appearance

Background choices are:

- **Default Light**
- **Sage Light**
- **Sky Light**
- **Default Dark**
- **Midnight Black**
- **Graphite Dark**
- **Forest Dark**
- **Plum Dark**

Highlight choices are:

- **Teal**
- **Sage**
- **Sky Blue**
- **Blue**
- **Indigo**
- **Amber**
- **Orange**
- **Mint**
- **Lavender**
- **Rose**

Background and highlight are independent. TicketPilot adjusts each highlight
for readable contrast on light and dark backgrounds.

Each highlight also has an automatic complementary counterpart color. The
highlight colors navigation, ordinary buttons, Remote choices, and Time entry
choices. Its counterpart colors On-Site choices, Ticket note choices,
customer-note indicators, the Record control, second-job shading, and related
outlines. This prevents Amber or Orange highlights from blending into controls
that previously used the same fixed amber.

Real warnings, errors, successful states, destructive controls, AI controls,
and disabled controls keep their established semantic colors.

The default appearance is Default Dark with Teal.

### Password

Enter the new password twice, then select **Change password**. Password changes
do not autosave. When a temporary password is required, Config shows only the
password-change workflow until the new password is saved.

### Navigation

Navigation provider choices are:

- **None**
- **Device Default**
- **Google Maps**
- **Waze**
- **Apple Maps**

Home address is required while navigation is enabled. Office address is
optional and can use the organization's default when left blank.

**Allow navigation on full web version** is off by default. When off,
navigation actions remain limited to phones and tablets. It is disabled while
Navigation is None.

**Hide Home and Office navigation buttons** hides only those two quick
destinations. It does not hide selected-ticket destination navigation. It is
disabled while Navigation is None.

**Automatically open On-Site directions** is on by default. Turn it off to
start an On-Site service call without opening maps automatically. The manual
**Navigate to Destination** button remains available. It is disabled while
Navigation is None.

Device Default uses the device's normal registered map behavior. On Apple
mobile devices it uses Apple Maps. On an opted-in desktop it opens browser
directions.

When Autotask supplies a usable address, **Navigate to Destination** can appear
for selected Time-entry tickets on Work or Review, including after submission.
It is hidden in Ticket note mode.

### Workflow

**Submit from Work in Progress** is off by default.

- Off sends finished work to Review first.
- On submits finished work directly when all required fields are valid.

This setting changes the finish destination. It does not enable or disable the
ability to create Time entries or Ticket notes.

### Device Sign-In

The final Config card is the persistent place to add or delete Device sign-in
credentials.

## Help And Version Changelog

The Help page contains:

1. **Ask AI for help**, when configured.
2. **Operational Status**.
3. The current TicketPilot version and release date, when released.
4. A **version changelog** button.

The version changelog opens in an overlay and contains short user-facing
release notes. Use the X in the top-right corner to close it.

AI Help answers one TicketPilot usage question at a time. It is not a source
code, deployment, credential, or private-configuration assistant. A configured
support contact appears below successful AI answers.

## Frequently Asked Questions

### What Is The Difference Between A Time Entry And A Note?

A Time entry records work time, date, Remote or On-Site type, target status,
and summary. A Ticket note adds a customer-visible title and description to a
ticket without work time. A Project task note adds a title and description
directly to the selected task without work time.

### Why Is Work Type Disabled?

Work type is disabled in Ticket note or Project task note mode because an
Autotask note does not use Remote or On-Site work location. Switch back to Time
entry to edit it.

### Why Did My End Time Change When I Selected On-Site?

An active On-Site Time entry requires at least one rounded hour. TicketPilot
keeps the start time and moves only the end time to the later of that minimum
or the current rounded 15-minute block.

### Why Can I Not Submit A Complete Entry?

Another local Time entry or note for the same ticket or project task is still
Active, Ready for Review, or Submission Failed. Submit every earlier entry
first so the Complete-status entry reaches Autotask last.

### Why Do I Not See An Assigned Project Task?

TicketPilot shows non-complete tasks under the selected company only when your
Autotask resource is assigned as a primary or secondary resource and the parent
project can accept time. Confirm the client, task assignment, project type, and
your Autotask Projects time-entry permission. Contact the app administrator if
the task remains missing.

### Does Task Status Change The Whole Project?

No. **Task status** changes only the selected Autotask task. TicketPilot never
sets the parent project's status when submitting project-task work.

### Where Is A Project Task Note Saved?

It is saved as an Autotask TaskNote attached directly to the selected project
task. TicketPilot does not create a whole-project note.

### Why Can I Not Type Any Client Name I Want?

TicketPilot requires a company selected from the Autotask search results. This
keeps the visible client and the Autotask company identity matched.

### Can I Change The Client After Selecting A Work Target?

No. The client becomes read-only after ticket or project-task selection so work
cannot be sent to a different company's target accidentally.

### Does Selecting A Ticket Change It In Autotask?

No. Selection stores verified local context. TicketPilot changes the Autotask
ticket status only during submission or an explicit submitted-record update.

### What Does The Note Badge Mean?

The ticket has displayable customer-note history. The badge is informational
and does not change the entry or ticket. Open **Ticket notes** to read the
available history.

### Why Did Ticket Notes Open Automatically?

The selected ticket was verified in the Autotask **Customer Note Added**
status. TicketPilot opens the newest existing note once. Close it with the X;
it stays closed until the Ticket notes button is selected.

### Why Does Ticket Notes Say No Notes?

Autotask returned no displayable notes, the visible notes were filtered
system-generated messages, or note history could not be read. The primary
ticket workflow can continue even when this optional context is unavailable.

### Why Is Append To Resolution Missing?

The record is in Ticket note or Project task note mode. Autotask supports
Append to resolution on Time entries but not on these note records.

### Why Is The Record Button A Different Color From My Highlight?

Every highlight has a complementary counterpart. Record and alternate workflow
choices use that counterpart so they stay visually distinct, including when
Amber or Orange is selected as the main highlight.

### Does AI Cleanup Submit My Work?

No. It only replaces the editable notes with cleaned text. Review the result
and finish or submit the record normally.

### Can I Undo AI Cleanup?

Use **Revert cleanup** while it is available. It restores the text saved
immediately before cleanup.

### Why Is My Recording Not Available After Submission?

Submitted work must be changed through the explicit supported Review actions.
New recording is limited to active or unsubmitted records.

### Where Did My Finished Work Go?

With the default workflow, it moved to Review. When **Submit from Work in
Progress** is enabled, it may already be submitted and still appears in Review
as a submitted record.

### Why Is A Record In Submission Failed?

Autotask rejected or could not complete the submission. Open it in Review,
read the safe error, correct the fields when possible, and select Retry. Contact
the app administrator if the same provider error continues.

### Can I Edit A Submitted Record?

Yes, within supported fields. Open it in Review, make the allowed changes, then
select **Submit changes**. Ticket and client identity cannot be changed.

### Can I Delete A Submitted Note?

No. Autotask does not provide the supported delete action used by TicketPilot
for submitted TicketNotes or TaskNotes. A submitted Time entry can show
**Delete From Autotask**.

### Why Do My Review Hours Ignore Ticket Notes?

Ticket notes and Project task notes do not have start and end times, so they do
not contribute to Today, Week, day, or week hour totals.

### Why Does Review Show A Different Default Number Of Rows?

The first full-browser visit defaults to 20 rows. Mobile defaults to 10. After
that, TicketPilot remembers the user's selected row count.

### Can I Hide Submitted Records?

Yes. Turn on **Hide submitted entries** in Review. TicketPilot remembers the
choice for the user.

### Why Did Directions Not Open For An On-Site Service Call?

Possible reasons include:

- **Automatically open On-Site directions** is off.
- Navigation is set to None.
- Autotask did not provide a usable destination.
- The browser blocked or could not launch the navigation app.
- A full browser has not enabled **Allow navigation on full web version**.

The local job may still have started successfully. Use
**Navigate to Destination** when it is available.

### Why Are Home And Office Missing?

Navigation may be set to None, **Hide Home and Office navigation buttons** may
be on, or no Office destination may be available. That setting does not hide
selected-ticket destination navigation.

### Why Is Device Sign-In Disabled On A Public Device?

Public-device sessions are intentionally short and do not allow registration
of a reusable Device sign-in credential. Sign out, then sign in normally on a
trusted device.

### Why Does TicketPilot Keep Asking Me To Change My Password?

The current password was created or reset as temporary. Enter a new password
twice in Config and select **Change password**.

### Why Did A Password Reset Email Not Arrive?

TicketPilot deliberately gives the same response for all submitted addresses.
Check the spelling, spam folder, and account email. The link is sent only when
exactly one enabled account matches. Contact the app administrator if needed.

### What Does Service Temporarily Unavailable Mean?

TicketPilot cannot reach required storage. Wait for the automatic retry or try
signing in later. Contact the app administrator if it does not recover.

### What Does The Yellow Or Red Header Status Mean?

TicketPilot detected an operational issue. Select the icon to open Operational
Status. Local work may continue, but provider lookups or submissions can fail
until the issue recovers.

### Is The Installed Phone App Available Offline?

No. The installed version provides app-style launch and navigation, but
TicketPilot still needs a network connection for authenticated work and
Autotask information.

## Common Messages And Recommended Actions

### Account Disabled

The account cannot sign in. Contact the address shown by TicketPilot or the app
administrator.

### Too Many Failed Attempts

Sign-in is temporarily blocked for that location. Wait and try later or contact
the app administrator.

### Too Many Password Reset Requests

Reset requests are temporarily blocked for that location. Wait and try later,
or ask the app administrator to verify the account email and send a reset.

### If An Enabled TicketPilot Account Exists For That Email Address, A Password Reset Email Has Been Sent

Check the inbox and spam folder. Verify the entered account email. TicketPilot
does not confirm whether an account matched.

### Human Verification Is Not Complete Yet

Wait for the verification control. If it remains blank, reload, check browser
content blockers, or use another browser or device.

### This Password Reset Link Is Invalid Or Expired

Request a new link. Reset links are single-use and expire after 24 hours.

### This Browser Does Not Support Secure Audio Recording

Use a modern browser over the organization's secure TicketPilot address, or
type notes manually.

### Recording Could Not Be Transcribed

Try again. If it continues, type the notes manually and contact the app
administrator.

### Select A Client From The Search Results

Choose the Autotask company from the returned list. Typed text alone is not a
verified company selection.

### No Open Tickets

Confirm the selected client. Then check the ticket or project-task assignment,
project type, and Autotask Projects permission. Contact the app administrator
if expected work is missing.

### Missing Required Fields

Complete the client, ticket or project task, target status, date/time, title, or
notes fields identified on the page and try again.

### All Other Time Entries For This Ticket Or Task Must Be Submitted First

Find every Active, Ready for Review, or Submission Failed record for the same
ticket or project task and submit it before the Complete-status record.

### Autotask Submission Failed

Open the record in Review, read the safe error, correct the available fields,
and Retry. Contact the app administrator when the same failure continues.

### Service Temporarily Unavailable

TicketPilot cannot reach required storage. Wait for the page to retry or sign
in later.

## Glossary

**AI Cleanup**

An optional action that improves the current work text without submitting it.

**Autotask**

The external service where TicketPilot reads verified customer, ticket, and
project-task context and sends Time entries, Ticket notes, or Project task
notes.

**Complementary counterpart**

The automatic contrasting color paired with the user's selected highlight. It
identifies alternate workflow choices such as On-Site and Ticket note without
changing semantic warning colors.

**Device sign-in**

A passkey-style sign-in using a supported device, browser, biometric, PIN,
pattern, or security key.

**Entry type**

Whether the local record will become an Autotask Time entry or a note on the
selected target.

**Project task**

A task inside an Autotask project that is assigned to the user as a primary or
secondary resource.

**Project task note**

An Autotask TaskNote attached directly to the selected project task, not to the
whole project.

**Review**

The page for checking, editing, submitting, retrying, updating, or explicitly
deleting supported records.

**Submit from Work in Progress**

The Config option that sends finished active work directly to Autotask instead
of stopping in Review first.

**Ticket note**

A customer-visible note added to an Autotask ticket without start and end
times.

**Time entry**

An Autotask work-time record containing a date, start time, end time, work type,
and summary.

**Work in Progress**

An active local TicketPilot record that has started but has not been finished.
