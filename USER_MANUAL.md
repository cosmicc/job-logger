# TicketPilot User Manual

TicketPilot's formal name is **Ticket Pilot for Autotask** because its work
workflow relies on the Autotask service. This manual explains the TicketPilot
screens and workflows available to a normal managed web user. It covers signing
in, resetting your password, recording work, submitting Autotask time entries
or ticket/project-task notes, reviewing completed work, changing your own
settings, and understanding common messages.

## What TicketPilot Does

TicketPilot helps you record work while it is happening and send the finished
record to Autotask. A work record can become either:

- A **Time entry** for a ticket or assigned project task, with date, start time,
  end time, work type, target status, and summary notes.
- A **Ticket note** with customer-visible note content, or a **Project task
  note** attached directly to the selected task.

The app is designed for phone use first, but the same Work, Review, and Config
pages also work from a full browser.

## Signing In

Open the TicketPilot URL provided by your organization. Sign in with your
username and password. The login page always uses a neutral black, white, and
grey appearance; your saved background and highlight choices apply only after
you sign in.

If you are signing in on a shared or public device, check **This is a public
device** before signing in. TicketPilot signs out public-device sessions after
15 minutes of inactivity and does not offer Device sign-in setup during that
session.

Your administrator may send a TicketPilot welcome email with the app link, your
username, mobile install steps, and support contact. The welcome email does not
include your temporary password.

If your account is new or your administrator reset your password, TicketPilot
will ask you to choose a new password before you can use the rest of the app.

Your password must have:

- At least 8 characters.
- Lowercase and uppercase letters.
- At least one number.
- At least one symbol.

If your account is disabled, the sign-in page will tell you after you enter the
correct password. It may also show the contact email your organization
configured for support.

If there are too many failed sign-in attempts, TicketPilot may temporarily block
more attempts from that location. Wait for the lockout time to pass or contact
your app administrator.

If your organization enables password reset, the sign-in page shows **Forgot
password?**. Enter your account email address and complete the verification
prompt if one appears. TicketPilot always shows the same confirmation message,
even when no enabled account matches that email address. If your email matches
exactly one enabled account, you will receive a reset link that works once and
expires after 24 hours. After you set the new password, sign in again with that
password. Three consecutive reset requests that do not match one enabled
account can temporarily block further requests from that location. Carefully
check the email address before submitting again, or contact your app
administrator if the location becomes blocked.

## Installing The App On A Phone

Open your organization's TicketPilot address in the phone browser, sign in,
then choose the browser action named **Install App** or **Add to Home Screen**.
The installed app uses the TicketPilot app icon and opens without the normal
browser toolbar. If a phone continues to show an older icon after an update,
remove the installed shortcut or app and install TicketPilot again.

## Device Sign-In

Device sign-in is an optional passkey-style login. It can use a phone, browser,
biometric unlock, PIN, pattern, security key, or another supported device
unlock method.

To set it up:

1. Sign in with your normal username and password.
2. If TicketPilot asks you to change a temporary password, change it first.
3. Open **Config**.
4. In **Device sign-in**, select **Set up device sign-in**.
5. Follow the browser or device prompt.

On phones, TicketPilot may also show a one-time Work page prompt to set up
device sign-in when your account does not have one yet.
Device sign-in setup is unavailable while you are signed in using the public
device option.

After setup, the login page still shows username/password first. Use the
**Device sign-in** button when you want to sign in with the saved device
credential. Password sign-in remains available as a fallback.

You can delete a saved device sign-in from **Config**. Deleting it removes that
credential from TicketPilot, but it does not change your password.

## Navigation

The signed-in header includes these main areas:

- **Work** opens the active Work in Progress page.
- **Review** opens completed or submitted work records.
- **Config** opens your personal settings.
- **Help** opens support help and version information.
- **Log out** ends your signed-in session.

On a phone, Work and Review sit on the left side of the top bar. Help, Config,
any optional admin shortcut, and Log out sit on the right side. On a full
browser, these controls use icon-and-text buttons. The top bar remains visible
while you scroll on either layout.

If a red app-health icon appears in the header, TicketPilot has detected that
something needs attention. You can usually keep working unless the page shows a
specific error. Contact your app administrator if the icon stays on or work
submission fails.

## Work Page

The Work page is where you start and finish work. It may show scheduled service
calls for tickets or project tasks assigned to your Autotask resource, and it
also lets you start a blank work record.

The Work page shows a compact Today and Week box with your total time-entry
hours directly below the navigation area. Ticket notes do not add to these
totals because they do not record start and end times.

The blank-work panel is titled **Start a time entry**. Select **Start Work** to
create a Work in Progress card. TicketPilot supports up to two active work
records at the same time. When two are active, the most recently started record
appears above the earlier record.

After **Start Work**, TicketPilot moves the cursor to the company search. After
you choose a ticket, project task, or service call, it moves the cursor to that
work record's summary field so you can continue typing.

Each Work in Progress card belongs to your user account. Other users do not use
your active cards.

Service-call cards are labeled **Ticket** or **Project task**. If one service
call has both types attached, TicketPilot shows one selectable card for each
association.

When navigation is enabled in Config, Work shows quick **Home** and **Office**
buttons. Office appears only when you or your administrator configured an
office destination. Starting a service call detected as On-Site opens your
chosen navigation app after TicketPilot confirms the work entry started. Remote
service calls start without opening navigation. These navigation actions are
available on phones and tablets by default. On a full web browser, they appear
only when **Allow navigation on full web version** is enabled in Config.

## Work In Progress Fields

A Work in Progress card contains the information that will eventually be sent
to Autotask.

**Entry type**

Choose whether the record is a **Time entry** or a note. Ticket work says
**Ticket note**. Project-task work says **Project task note**.

**Work type**

For time entries, choose **Remote** or **On-Site**. Ticket notes and Project
task notes keep this card visible but disabled because notes do not use work
type.

**Ticket status** or **Task status**

For a ticket, choose the status TicketPilot should send to Autotask when the
record is submitted. Supported statuses are **In progress**, **Waiting customer**,
**Waiting parts**, **Mfg Trouble Ticket**, **Follow up**, and **Complete**.
When Complete is selected, TicketPilot requires every other unsubmitted time
entry or ticket note for the same ticket to be sent first. This keeps the
Complete entry last even when another technician owns the earlier entry.

For a project task, the same card says **Task status** and shows the task
statuses configured in your Autotask tenant. This changes only the selected
task's status, never the whole project's status. If Complete is selected, every
other unsubmitted Time entry or Project task note for that task must be sent
first.

**Job date** or **Note Date**

Time entries use **Job date**. Ticket notes and Project task notes use **Note
Date**. Date pickers use TicketPilot's own **Today**, **Cancel**, and **Set**
controls.

**Start time**, **End time**, and **Work Duration**

Time entries use rounded start and end times in 15-minute increments. You can
adjust the visible times with the time controls. **Work Duration** shows the
rounded duration that will be used for the time entry. Note mode hides these
time fields because Ticket notes and Project task notes do not use start and
end time.
Remote time entries must be at least 15 minutes. On-Site time entries must be
at least 1 hour. On the active Work page, changing the work type updates only
the end time. TicketPilot uses the minimum duration unless the current rounded
15-minute block is later. Review and submitted-entry edits remain manual and
show a validation message when the selected duration is too short.

**Client name**

Search for and select the Autotask company. Typed client names must be selected
from the search results before they can be saved as the verified client.

You can change the selected client before choosing a ticket or project task.
After either target is selected, the client becomes read-only for that work
record.

**Ticket** or **Project task**

After selecting a verified client, load the grouped **Tickets** and **Project
tasks** choices. Ticket choices include **Start** and **Due by** dates when
Autotask provides them. Project-task choices show the task and its parent
project. Only non-complete tasks assigned to you as a primary or secondary
Autotask resource are shown. TicketPilot saves the selected target's verified
identity and makes it read-only. A **Note** badge means the ticket has
customer-note history or the task has TaskNotes available in TicketPilot.

**Ticket notes**, **Project task notes**, and **Past time entries**

When available, these buttons open read-only Autotask context for the selected
target. **Ticket notes** shows ticket-note history. **Project task notes** shows
notes attached directly to the selected task, not the whole project. **Past
time entries** shows prior time entries for the ticket or task. Some
Autotask-generated system notes are filtered out so the list stays useful.
When notes exist, the selected Ticket name repeats the counterpart-colored
**Note** badge and the **Ticket notes** button uses the same counterpart
highlight with that badge.

When you select a ticket whose current Autotask status is **Customer Note
Added**, TicketPilot automatically opens **Ticket notes** once and selects the
newest note. The same behavior applies when you start work from a service call
for that status. Use the X in the top-right corner to close the overlay. It
stays closed after you close it or reload the page; use **Ticket notes** to open
it again when needed.

When Autotask provides an address and navigation is enabled, **Navigate to Destination** opens
directions to the selected ticket's client. The button is available in Work in
Progress and Review, including after submission. It is available only for time
entries. Home, Office, and Navigate to Destination use a subtle blue shade so
they stand out from surrounding controls. On phones, Navigate to Destination
uses its own row immediately above the Entry type pill card and disappears when
Ticket note is selected.

**Summary notes**

For time entries, write the work summary that should go to Autotask. TicketPilot
adds the selected work type prefix, such as `Remote.` or `On-Site.`, to the
summary that will be submitted.

For Ticket notes or Project task notes, write the note description. Notes do
not use the Remote or On-Site prefix. Project task note descriptions can contain
up to 3,200 characters.

**Note title**

Ticket notes and Project task notes require a note title. Time entries do not
use a note title.

**Append to resolution**

This option is available for time entries. When it is on,
TicketPilot tells Autotask to append the submitted content to the ticket resolution
where the Autotask workflow supports that behavior.
Ticket notes and Project task notes do not show this option because Autotask
note records do not support the field.

## Recording Notes

Select **Record** to dictate notes. Select it again to stop recording.

After recording stops, the status line shows the upload and transcription
progress. When conversion finishes, the transcript is placed into the summary
or note-description field. Review the text before submitting because
speech-to-text can misunderstand words, names, numbers, and punctuation.

Recording is available during active work and on Review before the record has
been successfully submitted to Autotask.

## AI Cleanup

If AI Cleanup is enabled for your app, **AI Cleanup** can clean up the current
notes for readability. It does not submit anything to Autotask.

After a cleanup, the button can change to **Revert cleanup**. Use that if you
want to restore the notes from before the cleanup. Review the final text before
submitting.

## Finishing Work

The finish button depends on your Config workflow setting and the selected
entry type.

With the default setting:

- **End Work** stops a time entry and sends it to Review.
- **End Note** stops a Ticket note or Project task note and sends it to Review.

With **Submit from Work in Progress** turned on:

- **Submit to Autotask** stops a time entry and submits it directly to Autotask.
- **Submit note** stops a Ticket note or Project task note and submits it
  directly to Autotask.

**Submit from Work in Progress** is not a workflow availability setting. It
only controls whether finished Work in Progress records go straight to Autotask
or stop in Review first.

Direct submission still requires the same information as Review submission. If
required fields are missing, the record stays active so you can fix it. If
Autotask rejects the submission, the record moves to Review with a safe error
message so it can be corrected and retried.

## Deleting Active Work

Use **Delete** or **Delete Note** only when the active record should be removed
before it is submitted. Once work has been submitted to Autotask, use Review
actions instead.

## Review Page

The Review page starts with Today, Week, and Unsubmitted cards directly below
the navigation bar, then lists your completed, failed, and submitted records
newest first. Use **Hide submitted entries** to focus on work that still needs
attention. The Show menu offers 10, 20, 50, or 100 records per page, with 20
as the initial full-browser default and 10 as the initial mobile default. Your
choices are saved. First and Last buttons jump to the ends of the list. On a
phone, all three summary cards fit
on one row and abbreviate duration values, such as `15m`, `1h`, or `1.25h`. On
a full browser, the summary row aligns with the Review detail card.

Use Review to:

- Check completed records before sending them to Autotask.
- Fix missing or incorrect fields.
- Retry a failed Autotask submission.
- Update a record that was already submitted.
- Delete a submitted Autotask record when that action is available.

Review shows the selected client and ticket or project-task identity as
read-only once they
have been chosen. If an active record was opened in Review before any client was
selected, Review may let you choose the first verified client and then select a
ticket or assigned project task.

Review also shows your total time-entry hours worked today and this week, plus
the number of your time entries that have not been submitted to Autotask yet.
That count includes active entries, entries ready for review, and failed
submissions. Notes, rejected entries, and successfully submitted entries do not
count. Each review row shows day and week hour totals for that job's owner and
work date. Ticket notes and Project task notes do not add to these totals
because they do not record time.

## Review Fields

Before successful Autotask submission, Review can edit the same work fields
used on Work in Progress:

- Entry type.
- Work type for time entries.
- Ticket status or Task status.
- Job date or Note Date.
- Start time and end time for time entries.
- Summary notes for time entries.
- Note title and note description for Ticket notes or Project task notes.
- Append to resolution for time entries.

Time entries require verified ticket or project-task identity, summary notes,
target status, job date, start time, and end time.

Ticket notes require ticket number, ticket status, note title, and note
description. Ticket notes are customer-visible.
Project task notes require project-task identity, Task status, note title, and
note description, and are attached to the task rather than its parent project.

## Review Actions

**Accept and Submit**

Submits an unsubmitted Review record to Autotask.

**Retry**

Retries a record that failed submission. Check the visible error first and fix
any missing or invalid fields.

**Submit changes**

Updates an Autotask record that was already submitted. Time entries can update
date, start time, end time, summary notes, work type, append-to-resolution, and
the applicable Ticket or Task status. Ticket notes and Project task notes can
update note title, note description, and the applicable target status. A
project-task update changes only the task, not its parent project.

**Delete From Autotask**

Deletes a submitted Autotask time entry and moves the local record back to
Review. Autotask does not support deleting submitted ticket notes through this
API, so that action is not shown for Ticket notes or Project task notes. If
Autotask cannot complete a time-entry delete,
TicketPilot may show a local-only cleanup option with a warning.

**Delete time entry** or **Delete note**

Removes a local unsubmitted record from Review. Use this only when the local
record should not be submitted.

## Config Page

Config stores your personal settings. Most options save immediately when you
change them. The page identifies the active account as **User Settings for
Full Name (username)** above the settings cards.

### Appearance

Choose a background from the dropdown: **Default Light**, **Sage Light**,
**Sky Light**, **Default Dark**, **Midnight Black**, **Graphite Dark**,
**Forest Dark**, or **Plum Dark**. Every background option displays three round
palette samples. Then independently choose one of ten highlight colors from
its dropdown; every option includes a visible color sample. TicketPilot
automatically uses an adjusted shade for readable contrast on light and dark
backgrounds. The combination applies to your signed-in pages, including
navigation icons and ordinary buttons. Default Dark with Teal is selected
initially. Every highlight also has an automatic complementary counterpart
color. Remote, Time entry, navigation, and ordinary actions use the highlight;
On-Site, Ticket note, customer-note indicators, Record, and second-job
treatments use the counterpart. Genuine warnings and other status colors keep
their normal meaning.

On a full browser, Config uses a wide two-column card layout. On phones, the
same cards remain stacked in the documented order.

### Password

Enter a new password twice and select **Change password**. Password changes do
not save automatically because they require explicit confirmation.

When TicketPilot says you are using a temporary password, Config shows only the
password-change step until the new password is saved.

### Navigation

Choose **None**, **Device Default**, **Google Maps**, **Waze**, or **Apple
Maps**. Home address is required when navigation is enabled. Office address is
optional; leave it blank to use your organization's office address when one is
configured. These personal addresses save with your user settings.

**Allow navigation on full web version** is off by default. Leave it off to
hide navigation buttons and prevent automatic service-call directions in a
desktop browser. Turn it on to allow those actions on full web browsers as well
as mobile devices. The option is disabled while Navigation is set to None.

**Hide Home and Office navigation buttons** is also off by default. Turn it on
to remove only those two quick buttons from Work. Ticket and service-call
**Navigate to Destination** controls remain available. This option is disabled
while Navigation is set to None.

**Automatically open On-Site directions** is on by default. Turn it off when
you want an On-Site service call to start without opening a map. You can still
select **Navigate to Destination** afterward. This option is disabled while
Navigation is set to None.

Device Default asks Android to use its registered map handler, uses Apple Maps
on iPhone or iPad, and opens browser directions on an opted-in desktop.

### Workflow

**Submit from Work in Progress** controls what happens when you finish a Work
in Progress card.

- Off: finishing work sends the record to Review first.
- On: finishing work submits the record directly to Autotask from Work in
  Progress when all required fields are complete.

Use the default off setting when you want to review and edit every completed
record before Autotask submission. Turn it on when you trust the Work in
Progress fields and want fewer steps.

### Device Sign-In

The final Config card lets you set up or delete device sign-in credentials for
your account.

## Help And Changelog

Select **Help** in the header to open the Help page. On a phone, Help appears
as a question-mark icon. The Help page starts with **Ask AI for help**, then
shows **Operational Status**, and ends with the current app version card. The
version card shows a release date when that version has been released. The
**version changelog** button opens an overlay with short release notes for the
app version you are using and prior versions. Use the X in the top right to
close it.

If the Help page shows **DEV** beside the version, or the Help button is
yellow, you are using a development or testing instance rather than the
production instance.

If AI Help is enabled, you can ask one TicketPilot support question at a time in
the **Ask AI for help** card and read the answer on the Help page. When your
organization configures a support contact email, that contact line appears
under the AI answer.

## Common Messages And What To Do

**Account disabled**

Your account cannot sign in. Use the contact email shown in the message, or
contact your app administrator if no email is shown.

**Too many failed attempts**

Sign-in is temporarily blocked for that location. Wait and try again later, or
contact your app administrator.

**Too many password reset requests**

Password reset is temporarily blocked for that location. Wait and try again
later, or contact your app administrator to verify the account email address.

**If an enabled TicketPilot account exists for that email address, a password reset email has been sent**

Check your email for the reset link. If no message arrives, confirm you entered
the email address connected to your account and contact your app administrator.

**Human verification is not complete yet**

When the password reset page shows a verification prompt, wait for it to finish,
then try again. If the verification area stays blank, reload the page, check
browser content blockers, or try another browser or device.

**This password reset link is invalid or expired**

Request a new reset link from the sign-in page. Reset links can be used only
once and expire after 24 hours.

**This browser does not support secure audio recording**

Use a browser and device that support microphone recording over a secure
connection, or type the notes manually.

**Recording could not be transcribed**

Try recording again. If it keeps failing, type the notes manually and contact
your app administrator.

**Select a client from the search results**

Typed client text is not enough. Choose the Autotask company from the search
results so TicketPilot can save the verified company ID.

**No open tickets**

The selected client did not return usable open tickets or assigned project
tasks. Confirm the client is correct, then check your Autotask assignment and
project permissions or contact your app administrator.

**Missing required fields**

Complete the required client, ticket or project task, status, date/time, title,
or notes fields shown on the page, then submit again.

**Autotask submission failed**

Read the safe error shown on the record, correct any fields that need changes,
and retry from Review. Contact your app administrator if the same error keeps
appearing.

**Service Temporarily Unavailable**

TicketPilot cannot reach required storage right now. Wait for the page to retry
or sign in again later. Contact your app administrator if it does not recover.

## Glossary

**Autotask**

The external system where TicketPilot sends time entries, Ticket notes, and
Project task notes.

**Device sign-in**

A passkey-style sign-in method that uses a device or browser unlock method.

**Entry type**

Whether the record is a Time entry or a note for the selected target.

**Project task**

A task inside an Autotask project that is assigned to you as a primary or
secondary resource.

**Project task note**

A TaskNote attached directly to the selected Autotask project task, not to the
whole project.

**Review**

The page where completed records can be checked, edited, submitted, retried, or
updated.

**Submit from Work in Progress**

The Config option that submits finished Work in Progress records directly to
Autotask instead of sending them to Review first.

**Ticket note**

A customer-visible note added to an Autotask ticket.

**Time entry**

An Autotask work-time record with date, start time, end time, and work summary.

**Work in Progress**

An active TicketPilot record that has been started but not yet finished.
