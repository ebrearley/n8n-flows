# Email Organiser Workflow Design

Date: 2026-06-05
Workflow: `Email Organiser` (`fm6pLPnZWsGfK1oH`)

## Objective

Create a two-phase n8n email organiser. Phase one is a manually executed backfill workflow that starts when the user presses **Execute workflow**, reads messages from an IMAP mailbox in batches of 50, and organises them into labels/folders. Phase two, enabled only after the backfill, is an IMAP-triggered workflow that classifies one newly received email per trigger execution. Both phases should classify using local Ollama at `http://192.168.1.100:11434` with model `gemma4-26b:4090`, keep the classification prompts editable inside n8n, and add a `Classified` state label to each successfully classified email.

## Recommended Approach

Use the existing Manual Trigger node for backfill, followed by an Edit Fields node named `Configure classification prompt`, followed by an Execute Command node that runs a Python script using the standard library `imaplib`, `email`, and `urllib` modules.

After backfill, use a separate IMAP-triggered workflow with Email Trigger (IMAP), the same prompt node, and the same Execute Command script in `trigger_item` mode. n8n host concurrency must be limited to one production execution so new-email jobs queue behind any execution already using local Ollama.

This is the most direct fit because n8n exposes an IMAP trigger node, but not a general IMAP action node for "fetch latest N emails and move them to folders" through the node search available via MCP. A script keeps the IMAP-specific behavior explicit and testable without needing another service API.

Workflow-as-code lives in `email-classifer/`:

- `workflow.json`: importable n8n workflow JSON.
- `workflow-imap-trigger.json`: importable n8n workflow JSON scaffold for the post-backfill trigger phase.
- `email_classifier.py`: runtime classifier and IMAP mover.
- `tests/`: unit tests for helper behavior.

## Data Flow

Manual backfill:

1. Manual Trigger starts the workflow from the n8n UI or MCP execution.
2. `Configure classification prompt` stores editable `systemPrompt` and `userPromptTemplate` values in n8n.
3. Execute Command passes the prompt config to the script over stdin and connects to `192.168.3.200:1143` with `IMAP_USER` and `IMAP_PASSWORD`.
4. Script lists available mailboxes with IMAP `LIST`.
5. Script selects `INBOX` and fetches the latest batch of 50 message UIDs.
6. For each message in the batch, script fetches headers and a small body preview.
7. The script renders the user prompt template with `sender_email`, `sender_name`, `email_subject`, and `email_body`.
8. The script calls local Ollama `/api/chat` with `stream=false`, `format=json`, `temperature=0`, and `keep_alive=-1`.
9. Ollama returns strict JSON with `labels`, `confidence` per label, and `reason`.
10. The script validates every label against the allowed labels and falls back to `uncertain` for unknown, invalid, ambiguous, or low-confidence output.
11. Script appends `Classified` as a state label destination for the email.
12. Script creates every destination folder if it does not exist and live moves are enabled.
13. Script applies all confident labels plus `Classified`. For one destination it moves the message; for multiple destinations it copies to each destination and removes the source message.
14. Script repeats with the next batch of 50 until no messages remain, `EMAIL_CLASSIFIER_MAX_BATCHES` is reached, or only messages already attempted in the current run remain.
15. Script prints a JSON summary for n8n execution output.

IMAP-triggered phase:

1. Email Trigger (IMAP) emits one newly received email item.
2. `Configure classification prompt` preserves the trigger item fields and sets `runMode=trigger_item`.
3. Execute Command passes the trigger item and prompt config to the script over stdin.
4. Script builds an email summary from the trigger item, classifies that one email, applies all confident labels plus `Classified`, and exits.
5. n8n queue/concurrency settings ensure only one production execution runs at a time; new trigger executions wait in the queue while local Ollama is busy.

## Initial Classification Labels

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

The Ollama prompt must never invent labels. The implementation should preserve all confident labels, prefer `uncertain` when no label reaches the threshold, and enforce the confidence threshold after parsing.

State label:

- `Classified`

## Safety

Do not execute the workflow against the mailbox until the destination labels/folders have been set up in email, including `Classified`. Default the script to dry-run mode until a successful preview is reviewed. In dry-run mode it should list proposed moves but not create folders, move messages, or add `Classified`.

Dry-run defaults to one batch because it does not mutate mailbox state. Live mode defaults to unlimited batches (`EMAIL_CLASSIFIER_MAX_BATCHES=0`) and stops when no processable messages remain.

The IMAP-triggered workflow should remain inactive until the manual backfill completes. Before activating it, configure n8n production concurrency to one, for example `N8N_CONCURRENCY_PRODUCTION_LIMIT=1`, and use queue mode/worker concurrency `1` if this n8n deployment uses workers.

Never store IMAP credentials in workflow code or repository files. Read them from the n8n process environment.

Log only message metadata needed for review: UID, date, sender, subject, destination, and action. Do not print full email bodies by default.

## Error Handling

The script should fail fast if required environment variables are missing.

Connection, authentication, folder creation, fetch, and move failures should be captured per message in the JSON summary. A single bad message should not prevent the workflow from reporting results for the rest of the batch unless the mailbox connection itself fails.

## Testing Plan

1. Run unit tests for deterministic helper behavior without touching live IMAP.
2. Create the destination labels/folders in email, including `Classified`.
3. Run the workflow in dry-run mode from the n8n **Execute workflow** button.
4. Verify folder discovery works against `192.168.3.200:1143` during dry-run execution.
5. Review the proposed classifications and `Classified` state-label action for the first batch of 50 messages.
6. Adjust labels or prompt wording in the n8n `Configure classification prompt` node.
7. Disable dry-run and execute with a small `EMAIL_CLASSIFIER_MAX_BATCHES` first.
8. Set `EMAIL_CLASSIFIER_MAX_BATCHES=0` after confirming moves are correct so the workflow continues until the inbox is fully classified.
9. Import `workflow-imap-trigger.json`, assign the IMAP credential in n8n, and keep it inactive.
10. Configure n8n queue/concurrency so only one production execution runs at a time.
11. Activate the IMAP-triggered workflow after the manual backfill has completed.

## Implementation Notes

The workflow can be imported from `email-classifer/workflow.json` or updated through n8n MCP with `update_workflow`, adding the Edit Fields prompt node and Execute Command node after the existing Manual Trigger.

If n8n's Execute Command node is disabled in this instance, fallback options are:

- use an HTTP Request node against a small internal IMAP organizer service;
- install/use a community IMAP action node;
- use n8n's IMAP trigger node for new mail only, accepting that it does not satisfy the "manual latest 50" requirement.
