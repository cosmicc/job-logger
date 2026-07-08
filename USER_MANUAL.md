# Job Logger User Manual

This manual explains the Job Logger screens and workflows available to a normal
managed web user. It covers signing in, resetting your password, recording work,
submitting Autotask time entries or ticket notes, reviewing completed work,
changing your own settings, and understanding common messages.

## What Job Logger Does

Job Logger helps you record work while it is happening and send the finished
record to Autotask. A work record can become either:

- A **Time entry** with date, start time, end time, work type, ticket status,
  and summary notes.
- A **Ticket note** with a note title, note description, ticket status, and
  customer-visible note content.

The app is designed for phone use first, but the same Work, Review, and Config
pages also work from a full browser.

## Signing In

Open the Job Logger URL provided by your organization. Sign in with your
username and password.

If your account is new or your administrator reset your password, Job Logger
will ask you to choose a new password before you can use the rest of the app.

Your password must have:

- At least 8 characters.
- Lowercase and uppercase letters.
- At least one number.
- At least one symbol.

If your account is disabled, the sign-in page will tell you after you enter the
correct password. Contact your app administrator if that happens.

If there are too many failed sign-in attempts, Job Logger may temporarily block
more attempts from that location. Wait for the lockout time to pass or contact
your app administrator.

If your organization enables password reset, the sign-in page shows **Forgot
password?**. Enter your account email address and complete the verification
prompt. Job Logger always shows the same confirmation message, even when no
enabled account matches that email address. If your email matches exactly one
enabled account, you will receive a reset link that works once and expires after
24 hours. After you set the new password, sign in again with that password.

## Device Sign-In

Device sign-in is an optional passkey-style login. It can use a phone, browser,
biometric unlock, PIN, pattern, security key, or another supported device
unlock method.

To set it up:

1. Sign in with your normal username and password.
2. If Job Logger asks you to change a temporary password, change it first.
3. Open **Config**.
4. In **Device sign-in**, select **Set up device sign-in**.
5. Follow the browser or device prompt.

On phones, Job Logger may also show a one-time Work page prompt to set up
device sign-in when your account does not have one yet.

After setup, the login page still shows username/password first. Use the
**Device sign-in** button when you want to sign in with the saved device
credential. Password sign-in remains available as a fallback.

You can delete a saved device sign-in from **Config**. Deleting it removes that
credential from Job Logger, but it does not change your password.

## Navigation

The signed-in header includes these main areas:

- **Work** opens the active Work in Progress page.
- **Review** opens completed or submitted work records.
- **Config** opens your personal settings.
- **Help** opens support help and version information.
- **Log out** ends your signed-in session.

On a phone, Work and Review sit on the left side of the top bar. Help, Config,
any optional admin shortcut, and Log out sit on the right side. On a full
browser, these controls use icon-and-text buttons.

If a red app-health icon appears in the header, Job Logger has detected that
something needs attention. You can usually keep working unless the page shows a
specific error. Contact your app administrator if the icon stays on or work
submission fails.

## Work Page

The Work page is where you start and finish work. It may show scheduled service
calls for your Autotask resource, and it also lets you start a blank work
record.

Select **Start Work** to create a Work in Progress card. Job Logger supports up
to two active work records at the same time.

Each Work in Progress card belongs to your user account. Other users do not use
your active cards.

## Work In Progress Fields

A Work in Progress card contains the information that will eventually be sent
to Autotask.

**Entry type**

Choose whether the record is a **Time entry** or a **Ticket note**.

**Work type**

For time entries, choose **Remote** or **On-Site**. Ticket notes keep this card
visible but disabled because ticket notes do not use work type.

**Ticket status**

Choose the status Job Logger should send to Autotask when the record is
submitted. Supported statuses are **In progress**, **Waiting customer**,
**Waiting parts**, **Follow up**, and **Complete**.

**Job date** or **Note Date**

Time entries use **Job date**. Ticket notes use **Note Date**. Date pickers use
Job Logger's own **Today**, **Cancel**, and **Set** controls.

**Start time**, **End time**, and **Work Duration**

Time entries use rounded start and end times in 15-minute increments. You can
adjust the visible times with the time controls. **Work Duration** shows the
rounded duration that will be used for the time entry. Ticket notes hide these
time fields because ticket notes do not use start and end time.

**Client name**

Search for and select the Autotask company. Typed client names must be selected
from the search results before they can be saved as the verified client.

You can change the selected client before choosing a ticket. After a ticket is
selected, the client becomes read-only for that work record.

**Ticket number** and **Ticket name**

After selecting a verified client, load that client's open tickets and select
the correct ticket. Job Logger saves the selected ticket number, title, and
description. The ticket identity becomes read-only after selection.

**Ticket notes** and **Past time entries**

When available, these buttons open read-only Autotask context for the selected
ticket. **Ticket notes** shows ticket-note history. **Past time entries** shows
prior time entries for the ticket. Some Autotask-generated system notes are
filtered out so this list focuses on useful ticket history.

**Summary notes**

For time entries, write the work summary that should go to Autotask. Job Logger
adds the selected work type prefix, such as `Remote.` or `On-Site.`, to the
summary that will be submitted.

For ticket notes, write the note description. Ticket notes do not use the
Remote or On-Site prefix.

**Note title**

Ticket notes require a note title. Time entries do not use a note title.

**Append to resolution**

This option is available for time entries and ticket notes. When it is on, Job
Logger tells Autotask to append the submitted content to the ticket resolution
where the Autotask workflow supports that behavior.

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
- **End Note** stops a ticket note and sends it to Review.

With **Submit from Work in Progress** turned on:

- **Submit to Autotask** stops a time entry and submits it directly to Autotask.
- **Submit note** stops a ticket note and submits it directly to Autotask.

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

The Review page lists your completed, failed, and submitted records.

Use Review to:

- Check completed records before sending them to Autotask.
- Fix missing or incorrect fields.
- Retry a failed Autotask submission.
- Update a record that was already submitted.
- Delete a submitted Autotask record when that action is available.

Review shows the selected client and ticket identity as read-only once they
have been chosen. If an active record was opened in Review before any client was
selected, Review may let you choose the first verified client and then select a
ticket.

## Review Fields

Before successful Autotask submission, Review can edit the same work fields
used on Work in Progress:

- Entry type.
- Work type for time entries.
- Ticket status.
- Job date or Note Date.
- Start time and end time for time entries.
- Summary notes for time entries.
- Note title and note description for ticket notes.
- Append to resolution.

Time entries require ticket number, summary notes, ticket status, job date,
start time, and end time.

Ticket notes require ticket number, ticket status, note title, and note
description. Ticket notes are customer-visible.

## Review Actions

**Accept and Submit**

Submits an unsubmitted Review record to Autotask.

**Retry**

Retries a record that failed submission. Check the visible error first and fix
any missing or invalid fields.

**Submit changes**

Updates an Autotask record that was already submitted. Time entries can update
date, start time, end time, summary notes, work type, append-to-resolution, and
ticket status. Ticket notes can update note title, note description,
append-to-resolution, and ticket status.

**Delete From Autotask**

Deletes the submitted Autotask record when that action is available and moves
the local record back to Review. If Autotask cannot complete the delete, Job
Logger may show a local-only cleanup option with a warning.

**Delete time entry** or **Delete note**

Removes a local unsubmitted record from Review. Use this only when the local
record should not be submitted.

## Config Page

Config stores your personal settings. Most options save immediately when you
change them.

### Appearance

Choose **Dark** or **Light** theme. The choice applies to your signed-in pages.
Dark is the default.

### Password

Enter a new password twice and select **Change password**. Password changes do
not save automatically because they require explicit confirmation.

When Job Logger says you are using a temporary password, Config shows only the
password-change step until the new password is saved.

### Device Sign-In

Set up or delete device sign-in credentials for your account.

### Workflow

**Submit from Work in Progress** controls what happens when you finish a Work
in Progress card.

- Off: finishing work sends the record to Review first.
- On: finishing work submits the record directly to Autotask from Work in
  Progress when all required fields are complete.

Use the default off setting when you want to review and edit every completed
record before Autotask submission. Turn it on when you trust the Work in
Progress fields and want fewer steps.

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

If AI Help is enabled, you can ask one Job Logger support question at a time in
the **Ask AI for help** card and read the answer on the Help page.

## Common Messages And What To Do

**Account disabled**

Your account cannot sign in. Contact your app administrator.

**Too many failed attempts**

Sign-in is temporarily blocked for that location. Wait and try again later, or
contact your app administrator.

**If an enabled Job Logger account exists for that email address, a password reset email has been sent**

Check your email for the reset link. If no message arrives, confirm you entered
the email address connected to your account and contact your app administrator.

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
results so Job Logger can save the verified company ID.

**No open tickets**

The selected client did not return usable open tickets. Confirm the client is
correct, then check Autotask or contact your app administrator.

**Missing required fields**

Complete the required client, ticket, status, date/time, title, or notes fields
shown on the page, then submit again.

**Autotask submission failed**

Read the safe error shown on the record, correct any fields that need changes,
and retry from Review. Contact your app administrator if the same error keeps
appearing.

**Service Temporarily Unavailable**

Job Logger cannot reach required storage right now. Wait for the page to retry
or sign in again later. Contact your app administrator if it does not recover.

## Glossary

**Autotask**

The external system where Job Logger sends time entries and ticket notes.

**Device sign-in**

A passkey-style sign-in method that uses a device or browser unlock method.

**Entry type**

Whether the record is a Time entry or a Ticket note.

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

An active Job Logger record that has been started but not yet finished.
