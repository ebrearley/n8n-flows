# Email Classifier

Workflow-as-code for the n8n `Email Organiser` flow.

The directory name intentionally matches the requested spelling: `email-classifer`.

## Files

- `workflow.json`: importable n8n workflow JSON for the bulk and trigger workflow.
- `workflow-imap-trigger.json`: equivalent export retained for compatibility.
- `code-nodes/`: JavaScript used by the n8n Code nodes for IMAP fetch and label application.
- `email_classifier.py`: legacy Python helper retained for unit-tested behavior references.
- `tests/`: unit tests for classifier helper behavior.

## Runtime Shape

The workflow has two entry points.

Bulk pass:

```text
Manual Trigger
  -> Configure Proton IMAP batch
  -> Get next 50 unclassified emails
  -> Stop if no fetched emails
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

The current workflow uses n8n JavaScript Code nodes for IMAP fetch and label application. The Python helper is retained as legacy local test coverage only.

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

The bulk fetch and label-application Code nodes cannot read the `Email Trigger (IMAP)` credential secrets directly, so each IMAP account is configured as an entry in `imapPairsJson` on `Configure Proton IMAP batch`.

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
- `Schedule`
- `Spam like`

## Local Tests

```bash
python3 -m unittest discover -s email-classifer/tests
```
