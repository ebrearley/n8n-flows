# Email Classifier

Workflow-as-code for the n8n `Email Organiser` flow.

The directory name intentionally matches the requested spelling: `email-classifer`.

## Files

- `workflow.json`: importable n8n workflow JSON.
- `email_classifier.py`: Execute Command script used by the workflow.
- `tests/`: unit tests for classifier helper behavior.

## Runtime Shape

The n8n workflow is:

```text
Manual Trigger -> Configure classification prompt -> Execute Command -> email_classifier.py
```

The prompt node keeps `systemPrompt` and `userPromptTemplate` editable in n8n. The Execute Command node passes those values into the script, which connects to IMAP, fetches the latest messages, asks local Ollama to classify each email, creates missing folders if live moves are enabled, and moves messages. It defaults to dry-run mode.

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
EMAIL_CLASSIFIER_SCRIPT=/home/node/.n8n/email-classifer/email_classifier.py
```

Optional:

```bash
EMAIL_CLASSIFIER_FOLDER_PREFIX=AI
EMAIL_CLASSIFIER_LABELS=1: To respond,2: FYI,3: Comment,4: Notification,5: Meeting Update,6: Awaiting reply,7: Collab Request,8: Marketing,9: Cold Email,uncertain
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

## Safety

Do not execute the workflow against the mailbox until the destination labels/folders have been set up. Keep `EMAIL_CLASSIFIER_DRY_RUN=true` until the proposed moves look correct in n8n execution output. In dry-run mode the script lists folders and proposed moves without creating folders or moving messages.

Default labels:

- `1: To respond`
- `2: FYI`
- `3: Comment`
- `4: Notification`
- `5: Meeting Update`
- `6: Awaiting reply`
- `7: Collab Request`
- `8: Marketing`
- `9: Cold Email`
- `uncertain`

## Local Tests

```bash
python3 -m unittest discover -s email-classifer/tests
```
