# Email Classifier

Workflow-as-code for the n8n `Email Organiser` flow.

The directory name intentionally matches the requested spelling: `email-classifer`.

## Files

- `workflow.json`: importable n8n workflow JSON for the bulk and trigger workflow.
- `workflow-imap-trigger.json`: equivalent export retained for compatibility.
- `email_classifier.py`: IMAP helper used by Execute Command nodes.
- `tests/`: unit tests for classifier helper behavior.

## Runtime Shape

The workflow has two entry points.

Bulk pass:

```text
Manual Trigger
  -> Configure Proton IMAP batch
  -> Get next 50 unclassified emails
  -> Expand fetched emails
  -> Loop Over Emails
  -> Build classification prompt
  -> Classify with Ollama
  -> Prepare Proton label targets
  -> Apply Proton labels
  -> Loop Over Emails / next 50
```

Live trigger:

```text
Email Trigger (IMAP)
  -> Normalize trigger email
  -> Build classification prompt
  -> Classify with Ollama
  -> Prepare Proton label targets
  -> Apply Proton labels (trigger)
```

Classification happens in the visible n8n AI Agent node `Classify with Ollama`, backed by the `Ollama Chat Model` node using `gemma4-26b:4090` at `http://192.168.1.100:11434`.

The Python helper no longer calls Ollama. It only fetches candidate IMAP emails for the bulk loop or applies labels already selected by the AI node.

## Proton Labels

Proton exposes UI labels through IMAP as mailboxes nested under the top-level `Labels` mailbox. The workflow therefore applies labels as:

- `Labels/Invoice`
- `Labels/Purchase`
- `Labels/Classified`

`Classified` is the state marker and is applied as `Labels/Classified`.

The workflow does not create labels, create folders, move source messages, delete source messages, or expunge. It applies labels by copying the message to existing `Labels/*` mailboxes and keeps the original message in `INBOX`.

`uncertain` is a classifier fallback only. It is not applied as a Proton label.

## Required n8n Runtime

The live `Email Trigger (IMAP)` node uses the credential assigned in n8n.

The bulk fetch and label-application Execute Command nodes cannot read n8n credential secrets directly, so the n8n runtime also needs:

```bash
IMAP_USER=your-user
IMAP_PASSWORD=your-password
EMAIL_CLASSIFIER_SCRIPT=/home/node/.n8n/email-classifer/email_classifier.py
```

The workflow node config sets:

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

Import the workflow JSON into n8n:

```bash
n8n import:workflow --input=email-classifer/workflow.json
```

Copy `email_classifier.py` to the path configured by `EMAIL_CLASSIFIER_SCRIPT` on the n8n host.

Assign the IMAP credential to `Email Trigger (IMAP)` and configure the Ollama account/endpoint on `Ollama Chat Model` if n8n asks for it.

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

## Local Tests

```bash
python3 -m unittest discover -s email-classifer/tests
```
