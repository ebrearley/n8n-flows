# Email Classifier

Workflow-as-code for the n8n `Email Organiser` flow.

The directory name intentionally matches the requested spelling: `email-classifer`.

## Files

- `workflow.json`: importable n8n workflow JSON for the bulk and trigger workflow.
- `workflow-imap-trigger.json`: equivalent export retained for compatibility.
- `workflow-with-telemetry.json`: importable telemetry/iteration workflow for `Email Organiser (with telemetry)`.
- `code-nodes/`: JavaScript used by the n8n Code nodes for IMAP fetch, label application, and post-label action planning/execution.
- `email_classifier.py`: legacy Python helper retained for unit-tested behavior references.
- `tests/`: unit tests for classifier helper behavior.

Read the root `AGENTS.md` and `docs/superpowers/context/2026-06-08-agent-handoff-context.md` before importing or executing against the live mailbox. They record live IDs, credential references, telemetry branch state, and privacy constraints from the setup session.

## Runtime Shape

The workflow has two entry points.

Bulk pass:

```text
Backfill Form Trigger
  -> Configure Proton IMAP batch
  -> Get next 50 unclassified emails
  -> Stop if no fetched emails
  -> Expand fetched emails
  -> Loop Over Emails
  -> Build classification prompt
  -> Classify with Ollama
  -> Prepare Proton label targets
  -> Plan email actions
  -> Apply Proton labels
  -> Execute email action
  -> Loop Over Emails / next 50
```

Live trigger:

```text
Email Trigger (IMAP)
  -> Normalize trigger email
  -> Skip classified trigger email
  -> Build classification prompt
  -> Classify with Ollama
  -> Prepare Proton label targets
  -> Plan email actions
  -> Apply Proton labels (trigger)
  -> Execute email action (trigger)
```

Classification happens in the visible n8n AI Agent node `Classify with Ollama`, backed by the `Ollama Chat Model` node using `igorls/gemma4-e4b-classifier:latest` at `http://192.168.1.100:11434`.

The current workflow uses n8n JavaScript Code nodes for IMAP fetch, label application, and post-label action planning/execution. The Python helper is retained as legacy local test coverage only.

The editor-only `Manual Trigger` has been removed from the current export. Use `Backfill Form Trigger` for explicit backfill starts.

The `Email Trigger (IMAP)` export has `trackLastMessageId=false` to avoid the n8n 2.23.x first-activation `SINCE` search issue seen during setup. Because that can cause old unread messages to be emitted, the trigger path runs `Skip classified trigger email` before the AI node and drops messages whose `Message-ID` already exists in `Labels/Classified`.

## Telemetry And Status Dashboard

This repository is closely related to `/home/eric/source/n8n-workflow-status`, a private Next.js dashboard at:

```text
https://n8n-workflow-status.home.brearley.net
```

The status app reads the separate `workflow_status` Postgres database and displays workflow runs, current step, step input/output/error JSON, AI model/token usage, label actions, and errors.

Current live/code split:

- `Email Organiser` (`fm6pLPnZWsGfK1oH`) is the production workflow. It is backed by `workflow.json` / `workflow-imap-trigger.json`, is telemetry-free, and is intended to run normally.
- `Email Organiser (with telemetry)` (`bXNCHRxwqXoOeePH`) is the iteration/status workflow. It is backed by `workflow-with-telemetry.json`, writes to `workflow_status`, and is the workflow to run when feeding the status dashboard.
- the telemetry workflow is normally kept inactive unless deliberately running a validation/backfill for dashboard visibility.

Do not import one export over the other workflow ID. The production workflow should stay telemetry-free; the telemetry workflow should keep its Postgres/step telemetry nodes.

## Proton Labels

Proton exposes UI labels through IMAP as mailboxes nested under the top-level `Labels` mailbox. The workflow therefore applies labels as:

- `Labels/Invoice`
- `Labels/Purchase`
- `Labels/Classified`

`Classified` is the state marker and is applied as `Labels/Classified`.

During label application, the workflow does not create labels, create folders, delete source messages, move source messages, or expunge. It applies labels by copying the message to existing `Labels/*` mailboxes, before any post-label action phase runs.

`uncertain` is a classifier fallback only. It is not applied as a Proton label.

## Proton Actions

The workflow can move messages after classification and label application. Actions are live by default through `emailActionsMode=live`.

Verified Proton Bridge IMAP action mailboxes:

- archive: `Archive`
- spam/junk: `Spam`
- trash/bin: `Trash`

The workflow plans actions in `Plan email actions`, then applies labels first, then runs `Execute email action` or `Execute email action (trigger)`.

The executor uses `UID MOVE` only. It does not create folders, hard delete, or expunge. If an action is ambiguous, the destination mailbox is missing, or required date evidence is invalid, it skips the move and leaves a visible action status.

## Required n8n Runtime

The live `Email Trigger (IMAP)` node uses the credential assigned in n8n.

The bulk fetch, label-application, and action Code nodes cannot read the `Email Trigger (IMAP)` credential secrets directly, so each IMAP account is configured as an entry in `imapPairsJson` on `Configure Proton IMAP batch`.

`Configure Proton IMAP batch` sets `maxBatches=0`, so the manual workflow keeps fetching 50-email batches until the inbox is classified. Set `maxBatches` to a positive number only when you want a deliberately capped test run.

The bulk fetch node reads only selected IMAP header fields and caps each raw message preview at `rawFetchByteLimit` bytes, defaulting to `65536`. It scans source mailboxes in bounded UID ranges using `uidSearchWindow=500`, and checks candidate Message-IDs against `Labels/Classified` only as needed. `fetchWatchdogMs` defaults to `120000` and stops the fetch with stage counters if the first batch cannot be prepared in time.

Each credential pair names the variables that hold its username and password:

```json
[
  {
    "id": "imap-1",
    "host": "192.168.3.200",
    "port": 1143,
    "hostVar": "IMAP_1_HOST",
    "portVar": "IMAP_1_PORT",
    "startTls": true,
    "userVar": "IMAP_1_USER",
    "passwordVar": "IMAP_1_PASSWORD",
    "sourceMailboxes": ["INBOX"],
    "labelPrefix": "Labels",
    "stateLabel": "Classified",
    "rawFetchByteLimit": 65536,
    "fetchWatchdogMs": 120000,
    "uidSearchWindow": 500
  }
]
```

The workflow reads those variable names from n8n variables first, then from runtime environment variables. The default workflow includes placeholders for `IMAP_1_HOST`, `IMAP_1_PORT`, `IMAP_1_USER`, `IMAP_1_PASSWORD`, `IMAP_2_HOST`, `IMAP_2_PORT`, `IMAP_2_USER`, and `IMAP_2_PASSWORD`.

For environment variables, n8n 2 blocks Code-node environment access by default. Enabling that path requires:

```bash
N8N_BLOCK_ENV_ACCESS_IN_NODE=false
```

The workflow node config sets these connection values:

```bash
IMAP_HOST=192.168.3.200
IMAP_PORT=1143
IMAP_SSL=false
IMAP_STARTTLS=true
EMAIL_CLASSIFIER_SOURCE_MAILBOX=INBOX
EMAIL_CLASSIFIER_LABEL_PREFIX=Labels
EMAIL_CLASSIFIER_STATE_LABEL=Classified
```

## Import

Import the production workflow JSON into n8n:

```bash
n8n import:workflow --input=email-classifer/workflow.json
```

Import the telemetry workflow JSON only when updating `Email Organiser (with telemetry)`:

```bash
n8n import:workflow --input=email-classifer/workflow-with-telemetry.json
```

Assign the IMAP credential to `Email Trigger (IMAP)` and configure the Ollama account/endpoint on `Ollama Chat Model` if n8n asks for it.

For the live n8n instance, use the safer import procedure in root `AGENTS.md`: inject the correct workflow ID and credential references into a temporary import JSON, import with `active=false`, publish, set production active and telemetry inactive unless intentionally testing, then restart n8n.

Avoid pasting `n8n execute` output into chat or docs. The CLI can print private email content even without `--rawOutput`; validate through sanitized `workflow_status` rows instead.

## Queueing

Run production with concurrency limited to one so local Ollama only handles one classification workflow at a time:

```bash
EXECUTIONS_MODE=queue
N8N_CONCURRENCY_PRODUCTION_LIMIT=1
```

If running n8n workers, run workers with concurrency `1`.

## Safety

Do not activate the workflow against the mailbox until the Proton labels already exist under `Labels`, including `Labels/Classified`.

Default labels:

- `Invoice`
- `Purchase`
- `Bill`
- `Payment`
- `Marketing`
- `Cold email`
- `Important`
- `Awaiting reply`
- `Travel`
- `Ticket`
- `Infrastructure`
- `Hustle`
- `Schedule`
- `Spam like`
- `Account notification`
- `Statement`
- `Account (security)`
- `Newsletter`
- `Personal`

## Local Tests

```bash
python3 -m unittest discover -s email-classifer/tests
```
