# Email Classifier

Workflow-as-code for the n8n `Email Organiser` flow.

The directory name intentionally matches the requested spelling: `email-classifer`.

## Files

- `workflow.json`: importable n8n workflow JSON.
- `workflow-imap-trigger.json`: later importable n8n workflow JSON for new incoming mail.
- `email_classifier.py`: Execute Command script used by the workflow.
- `tests/`: unit tests for classifier helper behavior.

## Runtime Shape

The n8n workflow is:

```text
Manual Trigger -> Configure classification prompt -> Execute Command -> email_classifier.py
```

The prompt node keeps `systemPrompt` and `userPromptTemplate` editable in n8n. Pressing n8n's **Execute workflow** button starts the Execute Command node, which passes those values into the script.

The script connects to IMAP, fetches a batch of 50 messages, classifies each email one-by-one with local Ollama, applies every confident label returned by the model, adds the `Classified` state label, then fetches the next batch of 50. In live mode it repeats until the source mailbox has no more processable messages. It defaults to dry-run mode.

After the manual backfill is complete, use the IMAP-triggered workflow:

```text
Email Trigger (IMAP) -> Configure classification prompt -> Execute Command -> email_classifier.py
```

That workflow runs in `trigger_item` mode and classifies only the one email item emitted by the IMAP trigger.

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
EMAIL_CLASSIFIER_LIMIT=50
EMAIL_CLASSIFIER_SOURCE_MAILBOX=INBOX
EMAIL_CLASSIFIER_STATE_LABEL=Classified
EMAIL_CLASSIFIER_SCRIPT=/home/node/.n8n/email-classifer/email_classifier.py
```

Optional:

```bash
EMAIL_CLASSIFIER_FOLDER_PREFIX=AI
EMAIL_CLASSIFIER_LABELS=Invoice,Purchase,Bill,Payment,Marketing,Cold email,Important,Awaiting reply,Travel,Ticket,Infrastructure,Hustle,uncertain
EMAIL_CLASSIFIER_RUN_MODE=manual_backfill
EMAIL_CLASSIFIER_MAX_BATCHES=0
EMAIL_CLASSIFIER_SYSTEM_PROMPT="..."
EMAIL_CLASSIFIER_USER_PROMPT_TEMPLATE="..."
IMAP_SSL=false
IMAP_STARTTLS=false
OLLAMA_TIMEOUT_SECONDS=120
```

## Import

Import the workflow JSON into n8n:

```bash
n8n import:workflow --input=email-classifer/workflow.json
```

Copy `email_classifier.py` to the path configured by `EMAIL_CLASSIFIER_SCRIPT` on the n8n host.

After the backfill is complete, import the trigger workflow and assign its IMAP credential in n8n:

```bash
n8n import:workflow --input=email-classifer/workflow-imap-trigger.json
```

Do not activate the IMAP-triggered workflow until the manual backfill has completed.

## Queueing

The trigger workflow should be run with production concurrency limited to one so local Ollama only handles one classification workflow at a time. This is n8n host configuration, not workflow JSON:

```bash
EXECUTIONS_MODE=queue
N8N_CONCURRENCY_PRODUCTION_LIMIT=1
```

If running n8n workers, run workers with concurrency `1`.

## Safety

Do not execute the workflow against the mailbox until the destination labels/folders have been set up, including `Classified`. Keep `EMAIL_CLASSIFIER_DRY_RUN=true` until the proposed moves look correct in n8n execution output. In dry-run mode the script lists folders and proposed moves without creating folders, moving messages, or adding the `Classified` state label. Dry-run defaults to one batch because it does not mutate mailbox state.

Set `EMAIL_CLASSIFIER_DRY_RUN=false` when ready to classify the full inbox. In live mode, `EMAIL_CLASSIFIER_MAX_BATCHES=0` means keep fetching batches until there are no more processable messages.

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
