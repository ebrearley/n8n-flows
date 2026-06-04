# Email Organiser Workflow Design

Date: 2026-06-05
Workflow: `Email Organiser` (`fm6pLPnZWsGfK1oH`)

## Current Revision

`Email Organiser` is an inactive 15-node n8n workflow with two entry points:

- a manual bulk pass that fetches up to 50 unclassified IMAP emails at a time, loops over them one by one, and repeats until no unclassified emails remain;
- an `Email Trigger (IMAP)` path that classifies one newly received email.

Both paths use a visible n8n AI Agent node, `Classify with Ollama`, backed by an `Ollama Chat Model` node configured for `gemma4-26b:4090` at `http://192.168.1.100:11434`.

## Proton IMAP Label Model

The mail provider is Proton Mail. Through IMAP it exposes top-level mailboxes named `Folders` and `Labels`. Proton Mail UI labels live under the `Labels` mailbox, so workflow label targets must be `Labels/<label>`.

Examples:

- `Labels/Invoice`
- `Labels/Hustle`
- `Labels/Classified`

`Labels/Classified` is the state marker used to avoid reprocessing already classified emails.

The workflow must not create labels, create folders, move source messages, delete messages, or expunge. It only applies labels by copying the source message to existing `Labels/*` mailboxes.

## Data Flow

Manual bulk pass:

1. `Manual Trigger` starts the pass from n8n.
2. `Configure Proton IMAP batch` sets host `192.168.3.200`, port `1143`, STARTTLS, `sourceMailbox=INBOX`, `labelPrefix=Labels`, `stateLabel=Classified`, and `batchLimit=50`.
3. `Get next 50 unclassified emails` runs `email_classifier.py` in `fetch_batch` mode.
4. The script connects through IMAP using n8n process environment variables `IMAP_USER` and `IMAP_PASSWORD`.
5. The script scans `INBOX`, skips messages already present in `Labels/Classified` by `Message-ID`, and returns up to 50 email items.
6. `Expand fetched emails` turns the script JSON into one n8n item per email.
7. `Loop Over Emails` processes one email at a time.
8. `Build classification prompt` creates the editable system prompt and per-email user prompt.
9. `Classify with Ollama` classifies the email with the local Ollama model and structured JSON parser.
10. `Prepare Proton label targets` validates labels, drops unknown/low-confidence labels, maps accepted labels to `Labels/<label>`, and always adds `Labels/Classified`.
11. `From bulk loop?` routes bulk items to `Apply Proton labels`.
12. `Apply Proton labels` runs `email_classifier.py` in `apply_labels` mode and loops back to `Loop Over Emails`.
13. When the 50-item batch is done, the loop's done output runs `Get next 50 unclassified emails` again. If that fetch returns no emails, the workflow ends.

Live trigger:

1. `Email Trigger (IMAP)` emits one new email item using the n8n IMAP credential.
2. `Normalize trigger email` maps the trigger payload to the same email item shape as the bulk path.
3. The item flows through `Build classification prompt`, `Classify with Ollama`, and `Prepare Proton label targets`.
4. `From bulk loop?` routes trigger items to `Apply Proton labels (trigger)`, which applies labels and exits without entering the bulk loop.

## Runtime Requirements

The live trigger uses the IMAP credential configured in n8n.

The Execute Command nodes cannot read n8n credential secrets directly. The n8n runtime therefore also needs:

```bash
IMAP_USER=...
IMAP_PASSWORD=...
EMAIL_CLASSIFIER_SCRIPT=/home/node/.n8n/email-classifer/email_classifier.py
```

Production execution should be queued with concurrency `1` before activation so the local Ollama GPU only handles one classifier workflow at a time.

## Safety

All destination labels must already exist under Proton's `Labels` mailbox, including `Labels/Classified`.

`uncertain` is a classifier fallback, not a Proton label target. If no confident label is accepted, the workflow applies only `Labels/Classified` so the message is not retried forever.

The workflow is currently inactive and must not be executed or activated until the required labels and runtime environment are ready.

## Testing

Local deterministic tests cover:

- Proton `Labels/` mailbox target construction;
- ignoring `uncertain` as a real label;
- STARTTLS runtime configuration;
- applying labels without delete or expunge;
- using classification supplied by the n8n AI node instead of calling Ollama inside Python.
