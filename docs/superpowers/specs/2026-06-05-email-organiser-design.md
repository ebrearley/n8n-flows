# Email Organiser Workflow Design

Date: 2026-06-05
Workflow: `Email Organiser` (`fm6pLPnZWsGfK1oH`)

## Objective

Create a manually executed n8n workflow that reads the latest 50 messages from an IMAP mailbox and organises them into labels/folders. The workflow should classify each message using local Ollama at `http://192.168.1.100:11434` with model `gemma4-26b:4090`, keep the classification prompts editable inside n8n, discover available IMAP folders at runtime where possible, create missing destination folders when live moves are enabled, and avoid destructive changes during the first test run.

## Recommended Approach

Use the existing Manual Trigger node, followed by an Edit Fields node named `Configure classification prompt`, followed by an Execute Command node that runs a Python script using the standard library `imaplib`, `email`, and `urllib` modules.

This is the most direct fit because n8n exposes an IMAP trigger node, but not a general IMAP action node for "fetch latest N emails and move them to folders" through the node search available via MCP. A script keeps the IMAP-specific behavior explicit and testable without needing another service API.

Workflow-as-code lives in `email-classifer/`:

- `workflow.json`: importable n8n workflow JSON.
- `email_classifier.py`: runtime classifier and IMAP mover.
- `tests/`: unit tests for helper behavior.

## Data Flow

1. Manual Trigger starts the workflow from the n8n UI or MCP execution.
2. `Configure classification prompt` stores editable `systemPrompt` and `userPromptTemplate` values in n8n.
3. Execute Command passes the prompt config to the script over stdin and connects to `192.168.3.200:1143` with `IMAP_USER` and `IMAP_PASSWORD`.
4. Script lists available mailboxes with IMAP `LIST`.
5. Script selects `INBOX` and fetches the latest 50 message UIDs.
6. For each message, script fetches headers and a small body preview.
7. The script renders the user prompt template with `sender_email`, `sender_name`, `email_subject`, and `email_body`.
8. The script calls local Ollama `/api/chat` with `stream=false`, `format=json`, `temperature=0`, and `keep_alive=-1`.
9. Ollama returns strict JSON with `labels`, `confidence` per label, and `reason`.
10. The script validates every label against the allowed labels and falls back to `uncertain` for unknown, invalid, ambiguous, or low-confidence output.
11. Script creates every destination folder if it does not exist and live moves are enabled.
12. Script applies all confident labels. For one label it moves the message; for multiple labels it copies to each destination and removes the source message.
13. Script prints a JSON summary for n8n execution output.

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

## Safety

Do not execute the workflow against the mailbox until the destination labels/folders have been set up in email. Default the script to dry-run mode until a successful preview is reviewed. In dry-run mode it should list proposed moves but not create folders or move messages.

Never store IMAP credentials in workflow code or repository files. Read them from the n8n process environment.

Log only message metadata needed for review: UID, date, sender, subject, destination, and action. Do not print full email bodies by default.

## Error Handling

The script should fail fast if required environment variables are missing.

Connection, authentication, folder creation, fetch, and move failures should be captured per message in the JSON summary. A single bad message should not prevent the workflow from reporting results for the rest of the batch unless the mailbox connection itself fails.

## Testing Plan

1. Run unit tests for deterministic helper behavior without touching live IMAP.
2. Create the destination labels/folders in email.
3. Run the workflow in dry-run mode.
4. Verify folder discovery works against `192.168.3.200:1143` during dry-run execution.
5. Review the proposed classifications for the latest 50 messages.
6. Adjust labels or prompt wording in the n8n `Configure classification prompt` node.
7. Disable dry-run and execute on a small batch first.
8. Expand back to 50 after confirming moves are correct.

## Implementation Notes

The workflow can be imported from `email-classifer/workflow.json` or updated through n8n MCP with `update_workflow`, adding the Edit Fields prompt node and Execute Command node after the existing Manual Trigger.

If n8n's Execute Command node is disabled in this instance, fallback options are:

- use an HTTP Request node against a small internal IMAP organizer service;
- install/use a community IMAP action node;
- use n8n's IMAP trigger node for new mail only, accepting that it does not satisfy the "manual latest 50" requirement.
