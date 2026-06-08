# Email Organiser Next Actions

## Status

Deferred until the classifier backfill is proven robust and accurate.

## Next Step

After the classifier reliably processes the inbox, applies existing Proton labels, continues through uncertain classifications, and records useful missing-label suggestions, extend the project to take controlled actions on email:

- move messages classified as `Spam like` into the spam folder;
- archive redundant notification emails that do not need attention;
- draft auto replies for emails that need a response.

These actions should be implemented only after a separate design and validation pass, with dry-run telemetry first and no destructive mailbox mutations until explicitly approved.
