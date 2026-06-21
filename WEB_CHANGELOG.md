# Web Changelog

Short release notes shown on the authenticated `/changelog` page.

## v1.1.0 - Direct submission and passkeys

- Added a Config option to submit time entries directly from Work in Progress.
- Review is still available afterward for submitted-entry edits and Autotask deletion.
- Added passkey sign-in for managed users, with password login still available.
- App sessions can now require users to sign in again after the configured timeout.
- Diagnostics can now log out all managed web users without logging out the super admin.
- Disabled users are signed out and see an account-disabled message when they try to log in.
- The Home passkey setup card now appears only once after login, while Config always keeps passkey setup available.
- Ticket source can now mark alert-created tickets as Remote when ticket text does not say Remote or On-Site.
- Review detail now shows the active Work in Progress rounded stop time before the job is ended.
- Review open-ticket choices now match Work in Progress ticket card details and colors.
- Selecting service calls or open tickets now keeps Autotask read-only until submission and defaults the local status to In progress.
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
