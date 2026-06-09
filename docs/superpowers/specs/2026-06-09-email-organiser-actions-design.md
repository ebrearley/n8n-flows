# Email Organiser Actions Design

Date: 2026-06-09
Workflow: `Email Organiser` (`fm6pLPnZWsGfK1oH`)

## Purpose

Add a first-pass action layer after email classification so the workflow can move low-value or expired messages out of the inbox after they have been classified and labelled.

The first action set is:

- move two-factor/security-code emails older than 24 hours to trash;
- move spam-like emails to spam;
- archive event notifications and reminders for events that are already in the past;
- archive infrastructure backup notifications only when the backup completed without errors.

This changes the workflow safety model. The existing workflow only copies messages into Proton label mailboxes. This phase is allowed to mutate the source mailbox by moving messages, but must still avoid folder creation, permanent deletion, and expunge.

## IMAP Destination Discovery

The action destination mailboxes were verified through an IMAP `LIST "" "*"` probe from the live n8n runtime container. The probe printed mailbox names and flags only; it did not fetch messages or print credential values.

Both configured IMAP accounts expose the same action destinations:

- `Archive` with the `\Archive` flag;
- `Spam` with the `\Junk` flag;
- `Trash` with the `\Trash` flag.

The workflow should use these exact mailbox names for actions:

- archive -> `Archive`;
- spam/junk -> `Spam`;
- trash/bin -> `Trash`.

## Action Mode

Actions are live by default. When a planned action passes all guards, the executor moves the source message.

For controlled validation, the workflow should still support an explicit configuration value such as `emailActionsMode`:

- `live`: perform approved moves; this is the default;
- `dry_run`: compute and return action outcomes without moving messages;
- `disabled`: skip action planning and execution.

The default must be `live` because the user accepted recoverability through the Proton web client.

## Architecture

The workflow should keep classification and label application as the first state transition, then run source-mailbox actions.

Local workflow shape:

```text
Prepare Proton label targets
  -> Plan email actions
  -> Inspect Proton label targets
  -> From bulk loop?
  -> Apply Proton labels
  -> Execute email action
  -> Loop Over Emails

From bulk loop?
  -> Apply Proton labels (trigger)
  -> Execute email action (trigger)
```

`Plan email actions` is a Code node that reads the normalized email item, accepted classification labels, classifier metadata, date fields, source mailbox, and credential pair. It returns an `emailAction` object. It does not connect to IMAP and does not move messages.

`Execute email action` and `Execute email action (trigger)` are Code nodes that reuse the existing IMAP connection pattern. They check the destination mailbox exists, resolve the source UID if needed, and run a source move only when the action plan is approved.

Label application stays before action execution so `Labels/Classified` and any accepted category labels are applied before the message is archived, spammed, or trashed.

## Classifier Output

The classifier should continue returning the current `labels` and `reason` fields. It may also return an optional `action_hints` object for action planning:

```json
{
  "labels": [
    { "label": "Infrastructure", "confidence": 0.9 }
  ],
  "action_hints": {
    "two_factor_code": false,
    "event_notice": false,
    "event_time": null,
    "backup_job": true,
    "backup_status": "success",
    "has_errors": false
  },
  "reason": "One sentence justification"
}
```

Allowed action-hint fields:

- `two_factor_code`: boolean;
- `event_notice`: boolean;
- `event_time`: ISO 8601 date-time string with timezone, or `null`;
- `backup_job`: boolean;
- `backup_status`: `success`, `failure`, `warning`, or `unknown`;
- `has_errors`: boolean.

The planner must treat missing, malformed, or ambiguous hint values as no action.

## Planning Rules

The planner uses deterministic guards over model hints and accepted labels. Precedence is:

1. spam;
2. expired two-factor/security code;
3. past event notification/reminder;
4. successful backup notification;
5. no action.

Rules:

- Spam: if accepted labels include `Spam like`, plan `move_to_spam` with destination `Spam`.
- Expired 2FA: if `action_hints.two_factor_code` is true and the email `Date` header is more than 24 hours before workflow processing time, plan `move_to_trash` with destination `Trash`.
- Past event: if accepted labels include `Schedule`, `action_hints.event_notice` is true, and `action_hints.event_time` is parseable and earlier than workflow processing time, plan `archive` with destination `Archive`.
- Successful backup: if accepted labels include `Infrastructure`, `action_hints.backup_job` is true, `backup_status` is `success`, and `has_errors` is false, plan `archive` with destination `Archive`.

Fail-closed cases:

- no UID and no searchable Message-ID;
- destination mailbox missing;
- uncertain classification;
- low-confidence labels dropped by `Prepare Proton label targets`;
- unknown labels;
- invalid email date for the 2FA rule;
- missing or invalid event time for the past-event rule;
- backup status other than `success`;
- backup hints that mention errors, warnings, partial completion, or unknown status.

## IMAP Execution

The action executor should use `UID MOVE <uid> "<destination>"`.

It must not:

- create folders or labels;
- hard delete messages;
- call `EXPUNGE`;
- use `STORE +FLAGS (\Deleted)` as a fallback;
- move messages when the action plan is missing or rejected.

If `UID MOVE` fails, setup/debug behavior should fail closed and keep the failure visible. The implementation may return structured action status in dry-run mode, but live mode should not silently swallow move errors while the workflow is being built.

## Output And Telemetry Shape

Every processed item should keep label-application fields and add sanitized action fields:

```json
{
  "emailAction": {
    "action": "archive",
    "destinationMailbox": "Archive",
    "reason": "past_event",
    "approved": true
  },
  "email_action_status": "moved",
  "email_action_destination": "Archive"
}
```

No action output should include raw email body, full prompts, credentials, or secret-looking values. Short reasons such as `spam_like`, `expired_two_factor_code`, `past_event`, and `successful_backup` are enough.

The smaller local workflow does not have generated step telemetry. If this feature is ported to the live telemetry workflow, the telemetry nodes must sanitize these fields and avoid storing full action-evidence text.

## Live Workflow Safety

This worktree starts from the smaller 17-node local workflow export. The live n8n draft may still be the generated step-telemetry workflow, previously observed around 103 nodes.

Do not import the smaller export over live n8n unless the user explicitly accepts removing generated step telemetry. For a live deployment, first choose one target:

- port action nodes into the telemetry workflow branch/export;
- apply equivalent MCP updates to the live draft;
- or intentionally replace live with the smaller local export.

Before any live import or update, read the live workflow metadata and confirm node count, active state, and target node names.

## Testing

Add deterministic tests with synthetic email data only. Tests must not include private email bodies or credentials.

Required coverage:

- `Plan email actions` maps accepted `Spam like` to `move_to_spam` -> `Spam`;
- expired 2FA hint older than 24 hours maps to `move_to_trash` -> `Trash`;
- 2FA hint at or under 24 hours plans no action;
- past event notices archive only with parseable past `event_time`;
- future or missing event times plan no action;
- successful backup hints archive;
- failed, warning, partial, error, or unknown backup hints plan no action;
- precedence resolves multiple matches consistently;
- action executor uses `UID MOVE` and does not include `EXPUNGE`, folder creation, or `STORE +FLAGS`;
- dry-run mode reports `would_move` without moving;
- workflow JSON wires `Plan email actions` and action executors into both bulk and trigger paths;
- both `workflow.json` and `workflow-imap-trigger.json` stay in sync.
