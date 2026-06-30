# Web Changelog

Short release notes shown on the authenticated `/changelog` page.

## v1.2.0 - Ticket note mode, ticket history, alerts, and time totals

- Work entries can now be Time entries or customer-visible Ticket notes.
- Ticket note mode uses a required note title and note description instead of time and Remote/On-Site fields.
- Append to resolution is available for both entry types, and submitted Ticket notes can be updated or deleted from Review.
- Ticket notes now open from the selected ticket in a closeable newest-first overlay.
- A Past time entries button now opens ticket time entries with resource, start/stop time, hours, and summary-of-work details.
- Job date controls now show Today, Yesterday, or Tomorrow inside the date selector when applicable.
- Work in Progress and Review now have cleaner time controls, larger Remote/On-Site pills, and rounded total time shown.
- Full-browser Review now keeps Entry type beside Job date so start and end times share a row.
- Admins now see a top-bar alert when app health needs attention.

## v1.1.6 - Review, Home, and header polish

- Review summaries now start with Remote. or On-Site. before the work notes.
- The Home start button now says Start Work.
- Work in Progress and Review job dates now show Today or the weekday beside the date.
- Service-call date selectors now show Today, Yesterday, or Tomorrow with the weekday.
- Dev builds now show DEV inside the yellow version badge instead of a separate pill.
- Review is now titled Work Review and no longer shows the Autotask time-entry ID.
- Review detail spacing and the mobile DEV version badge now fit better.

## v1.1.5 - AI cleanup, speech-to-text, and sign-in updates

- AI Cleanup can now switch to Revert cleanup and restore the pre-cleanup notes after reloads.
- Revert cleanup drafts now expire automatically instead of being kept forever.
- Submitted Review entries can keep cleaned draft notes until Submit changes is clicked.
- Speech-to-text can now use a trusted remote faster-whisper server.
- Sign-in now temporarily blocks repeated failed attempts before checking another password.

## v1.1.4 - Login protection, Work in Progress controls, and deployment safety

- Sign-in protection now handles repeated failed login attempts more defensively.
- The login page now keeps password sign-in first and puts Device sign-in under it.
- Work in Progress rounded start and rounded stop are now editable like Review time fields.
- Remote and On-Site switches are a little larger.
- Tickets with no description now show a clear left-aligned message.
- Cloudflare Tunnel deployments can now choose the local web listener port.

## v1.1.3 - Review visibility and Work in Progress refinements

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

## v1.1.2 - User management, ticket status, and Device sign-in updates

- User management rows are more compact and easier to scan.
- Passkey setup and login buttons now use the clearer Device sign-in name.
- Submitted time entries now keep the Autotask ticket status matched to the selected Job Logger status on submit and Edit Entry.
- If Delete From Autotask fails, Review can now offer a local-only purge option for the Job Logger entry.

## v1.1.1 - Review action cleanup and Autotask role fixes

- Review detail now uses compact action rows like Work in Progress.
- Record and AI Cleanup now share a row on review detail with shorter labels and icons.
- Active jobs can now be ended from Review detail.
- Full browser Work in Progress and Review buttons now use cleaner paired rows.
- Autotask submission now handles tickets that provide an assigned resource but omit the assigned role.
- Autotask submission now handles tickets where the submitting user is assigned as a secondary resource.
- Autotask submission can now use a configured default service-desk role for a user when a ticket does not provide usable role data.


## v1.1.0 - Direct submission and passkeys

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

## v1.0.2 - Autotask workflow and desktop layout updates

- The work-entry page now uses `/home`; old `/mobile` links still redirect.
- Edit Entry can update submitted time entries that were already marked Complete.
- Starting work on a New ticket now moves it to In progress.
- Work in Progress now shows an editable ticket status field.
- Open-ticket choices now show Remote or On-Site with matching colors.
- The Config password card now shows password requirements without a separate current-settings card.
- The full browser Home and Work in Progress layouts are wider and easier to scan.

## v1.0.1 - Mobile shell navigation and close behavior

- Mobile users now have version, Home, Review, Config, and close icons in the top bar.
- The mobile close button exits the app screen without logging out.
- The changelog page now shows short release notes for each version.
- The mobile home page now starts directly with the work-entry card.

## v1.0.0 - Initial release

- Initial release.
