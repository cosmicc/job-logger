# Web Changelog

Short release notes shown on the authenticated `/changelog` page.

## 1.2.4 - 07.08.2026 - Review activity cleanup and password reset

- Review activity now skips automatic summary-note saves so the timeline only shows meaningful job actions.
- When enabled by the app administrator, the login page can send a secure password reset email without revealing whether an email address is on an account.
- The password reset page now shows verification status and waits for human verification to finish before sending a reset request.
- Human verification on the password reset page now loads more reliably instead of leaving a blank verification box.

## 1.2.3 - 07.05.2026 - Help navigation, AI Help, AI Cleanup, and changelog display

- The header now uses Help instead of the version number; phones show a Help icon and full browsers show the same icon with Help.
- Help now sits beside Log out in the header, while the main route buttons stay grouped together.
- On phones, Work and Review now stay on the left, while Help, Config, any optional admin shortcut, and Log out sit on the right.
- Phone header icons are larger inside the same compact navigation buttons.
- Phone header icons are now even larger and use the same size inside every nav button.
- The Help page now opens the version changelog in an overlay with an X close button.
- On phones, the current version and version changelog button now share one row.
- The Help page now starts with Ask AI for help, then shows Operational Status, with Current version as the last card.
- The Help page cards now have a little more space between them.
- Ask AI for help now uses a one-line question field that submits when Enter is pressed.
- The Help page can answer one Job Logger support question at a time when the app administrator configures Gemini AI Help instructions.
- Gemini AI Cleanup now uses the same Gemini endpoint setup as Ask AI for help.
- Ask AI for help now keeps broad/simple answers concise and avoids showing unfinished trailing fragments.
- Ask AI for help now explains what users can ask, clears the old question when users start another one, and shows a general app operational-status card.
- The degraded app-health alert now opens Operational Status on the Help page and uses yellow or red to show severity; Operational Status shows green when the app is healthy.
- New managed users and users whose password was reset now have to change that temporary password before using the app; phones still show the device sign-in setup prompt after the password is changed.
- Help now labels released version dates as Released: MM.DD.YYYY and shows previous changelog entries as full-width cards without timeline dots.

## 1.2.2 - 07.03.2026 - App icon, user manual, ticket history, and Config workflow

- Updated the app icon, browser favicon, and desktop header logo to the new Job Logger artwork.
- The installed app icon now uses the original dark-background icon artwork, fills the icon frame, and avoids the over-zoomed maskable icon crop.
- Ticket history now hides Autotask notes titled Some actions did not occur.
- Added a full user manual covering sign-in, Work in Progress, Review, Config, Device sign-in, the changelog, and common messages.
- The Config page documentation now explains that Submit from Work in Progress submits finished entries directly to Autotask instead of stopping in Review first.

## 1.2.1 - 07.03.2026 - Work in Progress, Review, and outage-page polish

- Full-browser Review now pairs Entry type with Work type, puts Job date before Ticket status, and keeps two-card rows evenly split.
- Full-browser Review now keeps Client name and Ticket number together above Ticket description, then shows Ticket name in its own centered card with ticket-history buttons at the bottom.
- Full-browser Work in Progress now pairs Entry type with Work type, puts Job date before Ticket status, and centers duration under the time row.
- Full-browser Work in Progress now puts Ticket number beside Client name, centers Ticket name in the full-width ticket-history card, and uses the ticket name as the active job heading.
- Work in Progress and Review now center ticket status dropdown text, center job dates in their date boxes, and label the rounded total as Work Duration.
- The Config page now shows Appearance, Password, Device sign-in, then Workflow.
- Ticket description stays full width on Work in Progress so longer ticket details stay readable.
- Mobile Work in Progress and Review now show Entry type, Work type, Ticket status, Job date, Start time, End time, and duration in the same order.
- On phones, Work in Progress now centers the selected Client name and Ticket name cards.
- On phones, Review now centers the selected Client name card.
- On phones, Ticket notes and Past time entries sit under Ticket name on Work in Progress, while Review puts Client name above Ticket number and moves those buttons into Ticket name above Ticket description.
- On phones, Past time entries now open in the same full-screen overlay as Ticket notes.
- Work in Progress now keeps Past time entries visible beside Ticket notes on every active job when past entries are available.
- Work in Progress now lets you change the selected client before choosing a ticket and loads the new client's tickets.
- Ticket note mode now keeps Work type visible but greyed out instead of removing it.
- The temporary outage page now uses a tighter card without the extra app header.

## 1.2.0 - 07.02.2026 - Ticket note mode, ticket history, Work in Progress layout, navigation, and web-edge polish

- Date choosers now use Today, Cancel, and Set controls inside the app.
- Start and end time fields now open a 15-minute time dropdown.
- Switching a Time entry to a Ticket note now removes the Remote. or On-Site. prefix from the note description.
- Switching back to Time entry restores the Remote. or On-Site. prefix that matches the selected work type.
- Ticket note mode now shows Note Date and hides start/end time fields until switching back to Time entry.
- Ticket history now filters system-generated notes, including Workflow Rule title variants, and shows No Notes or No past entries when the selected ticket has no usable history.
- Past time entry cards now show compact hours beside the resource name, such as 1.5hrs.
- Full-browser navigation is now centered and uses the app's home-screen icon in the header.
- The login page no longer shows a top app mark above the sign-in form.
- The full-browser header now uses the same installed-app icon asset.
- If storage is temporarily unavailable, the browser now shows a Job Logger-styled Service Temporarily Unavailable page that retries sign-in automatically.
- The changelog now shows version numbers without brackets and release dates for released versions.
- The work-entry navigation button now says Work, uses a work-entry icon, and the mobile top-bar buttons use the same blue style as the full web nav.
- Work in Progress and Review detail now show the ticket title with the state pill beside it, center key field labels, and use matching action button sizes.
- Work in Progress active cards show the Work in Progress label again, and full-browser summary notes line up with the job date cards.
- The full-browser Work page Job date card stays full-width, while the date selector inside it is compact.
- The full-browser Work page note-title and summary boxes now start flush with the Job date or Note Date card.
- Note title fields are centered, Work in Progress status messages sit under the action buttons, and Ticket note or On-Site switch selections are orange.
- Empty No Notes and No past entries buttons now stay fully disabled with no hover or click behavior.
- The app-health degraded icon now appears for every signed-in user without opening another page.
- Web service and missing-page errors now match Job Logger's look and offer Back to Login or Back to Work.
- Work entries can now be Time entries or customer-visible Ticket notes.
- Ticket note mode uses a required note title and note description instead of time and Remote/On-Site fields.
- Append to resolution is available for both entry types, and submitted Ticket notes can be updated or deleted from Review.
- Ticket notes now open from the selected ticket in a closeable newest-first overlay.
- A Past time entries button now opens ticket time entries with clear technician names, large time details, and summary-of-work details.
- Work entry save, recording, and AI Cleanup messages now share one status line.
- Job date controls now center the date with Today, Yesterday, or Tomorrow inside the selector when applicable.
- Ticket note fields are tighter, with Append to resolution below the note description.
- Full-browser navigation now uses raised blue icon buttons with visible labels.
- Buttons now have clear hover and pressed states, including red destructive actions staying red on hover.
- Work in Progress and Review now have clean time controls, larger Remote/On-Site pills, and rounded total time shown.

## 1.1.6 - 06.29.2026 - Review, Home, and header polish

- Review summaries now start with Remote. or On-Site. before the work notes.
- The Home start button now says Start Work.
- Work in Progress and Review job dates now show Today or the weekday beside the date.
- Service-call date selectors now show Today, Yesterday, or Tomorrow with the weekday.
- Dev builds now show DEV inside the yellow version badge instead of a separate pill.
- Review is now titled Work Review and no longer shows the Autotask time-entry ID.
- Review detail spacing and the mobile DEV version badge now fit better.

## 1.1.5 - 06.26.2026 - AI cleanup, speech-to-text, and sign-in updates

- AI Cleanup can now switch to Revert cleanup and restore the pre-cleanup notes after reloads.
- Revert cleanup drafts now expire automatically instead of being kept forever.
- Submitted Review entries can keep cleaned draft notes until Submit changes is clicked.
- Speech-to-text can now use a trusted remote faster-whisper server.
- Sign-in now temporarily blocks repeated failed attempts before checking another password.

## 1.1.4 - 06.24.2026 - Login protection, Work in Progress controls, and deployment safety

- Sign-in protection now handles repeated failed login attempts more defensively.
- The login page now keeps password sign-in first and puts Device sign-in under it.
- Work in Progress rounded start and rounded stop are now editable like Review time fields.
- Remote and On-Site switches are a little larger.
- Tickets with no description now show a clear left-aligned message.
- Cloudflare Tunnel deployments can now choose the local web listener port.

## 1.1.3 - 06.23.2026 - Review visibility and Work in Progress refinements

- Review rows now show whether each job is Remote or On-Site.
- Review detail can now switch Remote or On-Site and updates the Summary notes prefix.
- Work in Progress active job cards are easier to tell apart.
- Dev builds can now show a yellow DEV badge in the top bar.
- Status pills now use a cleaner outlined all-caps style.
- Full browser Work in Progress actions now keep finish and delete buttons directly under Record and AI Cleanup.
- Work in Progress now has an editable Job date calendar.
- Review detail can choose a client when an active entry was opened before a client was selected.
- Client selection now requires choosing an Autotask search result on Work in Progress and Review.
- Review client search no longer shows a Summary notes warning while typing.
- Choosing an open ticket now locks that job's client name everywhere.
- Mobile Review status messages now stay below the action buttons.
- Service-call starts now hide tickets already marked Complete in Job Logger.
- Submitted Review entries now use a clearer Submit changes button.
- User management rows now fit better on full browser screens.

## 1.1.2 - 06.22.2026 - User management, ticket status, and Device sign-in updates

- User management rows are more compact and easier to scan.
- Passkey setup and login buttons now use the clearer Device sign-in name.
- Submitted time entries now keep the Autotask ticket status matched to the selected Job Logger status on submit and Edit Entry.
- If Delete From Autotask fails, Review can now offer a local-only purge option for the Job Logger entry.

## 1.1.1 - 06.21.2026 - Review action cleanup and Autotask role fixes

- Review detail now uses compact action rows like Work in Progress.
- Record and AI Cleanup now share a row on review detail with shorter labels and icons.
- Active jobs can now be ended from Review detail.
- Full browser Work in Progress and Review buttons now use cleaner paired rows.
- Autotask submission now handles tickets that provide an assigned resource but omit the assigned role.
- Autotask submission now handles tickets where the submitting user is assigned as a secondary resource.
- Autotask submission can now use a configured default service-desk role for a user when a ticket does not provide usable role data.


## 1.1.0 - 06.21.2026 - Direct submission and passkeys

- Added a Config option to submit time entries directly from Work in Progress.
- Review is still available afterward for submitted-entry edits and Autotask deletion.
- Added passkey sign-in for managed users, with password login still available.
- App sessions can now require users to sign in again after the configured timeout.
- Disabled users are signed out and see an account-disabled message when they try to log in.
- The Home passkey setup card now appears only once after login, while Config always keeps passkey setup available.
- Ticket source can now mark alert-created tickets as Remote when ticket text does not say Remote or On-Site.
- Review detail now shows the active Work in Progress rounded stop time before the job is ended.
- Review open-ticket choices now match Work in Progress ticket card details and colors.
- Time entry submission can now use the submitting user's default service-desk role when the selected ticket has no assigned role.
- The mobile top bar now uses a logout icon instead of the app-close X.
- Mobile Work in Progress actions now use compact button rows with shorter labels and icons.
- Rounded start and stop `-15` and `+15` buttons no longer show the full-page status overlay.
- Mobile Summary notes boxes now start taller while still allowing manual resize.

## 1.0.2 - 06.20.2026 - Autotask workflow and desktop layout updates

- The work-entry page now uses `/home`; old `/mobile` links still redirect.
- Edit Entry can update submitted time entries that were already marked Complete.
- Starting work on a New ticket now moves it to In progress.
- Work in Progress now shows an editable ticket status field.
- Open-ticket choices now show Remote or On-Site with matching colors.
- The Config password card now shows password requirements without a separate current-settings card.
- The full browser Home and Work in Progress layouts are wider and easier to scan.

## 1.0.1 - 06.20.2026 - Mobile shell navigation and close behavior

- Mobile users now have version, Home, Review, Config, and close icons in the top bar.
- The mobile close button exits the app screen without logging out.
- The changelog page now shows short release notes for each version.
- The mobile home page now starts directly with the work-entry card.

## 1.0.0 - 06.16.2026 - Initial release

- Initial release.
