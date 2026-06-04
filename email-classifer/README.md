# Email Classifier

Workflow-as-code for the n8n `Email Organiser` flow.

The directory name intentionally matches the requested spelling: `email-classifer`.

## Files

- `workflow.json`: importable n8n workflow JSON.
- `workflow-imap-trigger.json`: equivalent importable n8n workflow JSON for new incoming mail.
- `email_classifier.py`: Execute Command script used by the workflow.
- `tests/`: unit tests for classifier helper behavior.

## Runtime Shape

The n8n workflow is automated from the IMAP trigger:

```text
Email Trigger (IMAP) -> Configure classification prompt -> Execute Command -> email_classifier.py
```

The prompt node keeps `systemPrompt`, `userPromptTemplate`, and non-secret IMAP runtime settings editable in n8n. The workflow runs in `trigger_item` mode and classifies only the one email item emitted by the IMAP trigger.

The script connects back to IMAP to apply labels to that same message. It only copies the message into existing label mailboxes for every confident label returned by the model plus the `Classified` state label. It does not create labels, move messages, delete source messages, or expunge the mailbox.

## Required n8n Environment

Set these in the n8n runtime:

```bash
IMAP_HOST=192.168.3.200
IMAP_PORT=1143
IMAP_USER=your-user
IMAP_PASSWORD=your-password

OLLAMA_BASE_URL=http://192.168.1.100:11434
OLLAMA_MODEL=gemma4-26b:4090
OLLAMA_KEEP_ALIVE=-1

EMAIL_CLASSIFIER_DRY_RUN=true
EMAIL_CLASSIFIER_SOURCE_MAILBOX=INBOX
EMAIL_CLASSIFIER_STATE_LABEL=Classified
EMAIL_CLASSIFIER_SCRIPT=/home/node/.n8n/email-classifer/email_classifier.py
```

Optional:

```bash
EMAIL_CLASSIFIER_LABEL_PREFIX=AI
EMAIL_CLASSIFIER_LABELS=Invoice,Purchase,Bill,Payment,Marketing,Cold email,Important,Awaiting reply,Travel,Ticket,Infrastructure,Hustle,uncertain
EMAIL_CLASSIFIER_SYSTEM_PROMPT="..."
EMAIL_CLASSIFIER_USER_PROMPT_TEMPLATE="..."
IMAP_SSL=false
IMAP_STARTTLS=true
OLLAMA_TIMEOUT_SECONDS=120
```

## Import

Import the workflow JSON into n8n:

```bash
n8n import:workflow --input=email-classifer/workflow.json
```

Copy `email_classifier.py` to the path configured by `EMAIL_CLASSIFIER_SCRIPT` on the n8n host.

`workflow-imap-trigger.json` is retained as an equivalent trigger-only export:

```bash
n8n import:workflow --input=email-classifer/workflow-imap-trigger.json
```

Assign the IMAP credential to the `Email Trigger (IMAP)` node in n8n before activation.

## Queueing

The workflow should be run with production concurrency limited to one so local Ollama only handles one classification workflow at a time. This is n8n host configuration, not workflow JSON:

```bash
EXECUTIONS_MODE=queue
N8N_CONCURRENCY_PRODUCTION_LIMIT=1
```

If running n8n workers, run workers with concurrency `1`.

## Safety

Do not activate the workflow against the mailbox until the labels already exist in email, including `Classified`. In dry-run mode the script reports which labels it would apply without changing the message. In live mode it applies labels by copying the message to the existing label mailboxes and keeps the original message in the source mailbox.

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
- `uncertain`

State label:

- `Classified`

## Local Tests

```bash
python3 -m unittest discover -s email-classifer/tests
```
