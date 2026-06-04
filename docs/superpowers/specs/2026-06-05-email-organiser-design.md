# Email Organiser Workflow Design

Date: 2026-06-05
Workflow: `Email Organiser` (`fm6pLPnZWsGfK1oH`)

## Objective

Create a manually executed n8n workflow that reads the latest 50 messages from an IMAP mailbox and organises them into folders. The workflow should also discover available IMAP folders where possible, create missing destination folders when needed, and avoid destructive changes during the first test run.

## Recommended Approach

Use the existing Manual Trigger node followed by an Execute Command node that runs a Python script using the standard library `imaplib` and `email` modules.

This is the most direct fit because n8n exposes an IMAP trigger node, but not a general IMAP action node for "fetch latest N emails and move them to folders" through the node search available via MCP. A script keeps the IMAP-specific behavior explicit and testable without needing another service API.

## Data Flow

1. Manual Trigger starts the workflow from the n8n UI or MCP execution.
2. Execute Command connects to `192.168.3.200:1143` with `IMAP_USER` and `IMAP_PASSWORD`.
3. Script lists available mailboxes with IMAP `LIST`.
4. Script selects `INBOX` and fetches the latest 50 message UIDs.
5. For each message, script fetches headers and a small body preview.
6. A deterministic classifier assigns a destination folder.
7. Script creates the destination folder if it does not exist.
8. Script moves the message with `UID MOVE`; if unsupported, it falls back to `UID COPY`, `+FLAGS.SILENT (\Deleted)`, and `EXPUNGE`.
9. Script prints a JSON summary for n8n execution output.

## Initial Classification Rules

Start conservative and transparent:

- `Finance`: invoices, receipts, statements, payments, subscriptions, taxes.
- `Travel`: flights, hotels, bookings, itineraries, tickets.
- `Work`: meetings, projects, tickets, pull requests, deployments.
- `Shopping`: orders, shipping, delivery, returns.
- `Newsletters`: unsubscribe headers, newsletter language, marketing campaigns.
- `Notifications`: alerts, verification codes, automated status messages.
- `Needs Review`: anything uncertain.

The first implementation should prefer `Needs Review` over over-classifying.

## Safety

Default the script to dry-run mode until a successful preview is reviewed. In dry-run mode it should list proposed moves but not create folders or move messages.

Never store IMAP credentials in workflow code or repository files. Read them from the n8n process environment.

Log only message metadata needed for review: UID, date, sender, subject, destination, and action. Do not print full email bodies by default.

## Error Handling

The script should fail fast if required environment variables are missing.

Connection, authentication, folder creation, fetch, and move failures should be captured per message in the JSON summary. A single bad message should not prevent the workflow from reporting results for the rest of the batch unless the mailbox connection itself fails.

## Testing Plan

1. Run the workflow in dry-run mode.
2. Verify folder discovery works against `192.168.3.200:1143`.
3. Review the proposed classifications for the latest 50 messages.
4. Adjust folder rules.
5. Disable dry-run and execute on a small batch first.
6. Expand back to 50 after confirming moves are correct.

## Implementation Notes

The workflow can be updated through n8n MCP with `update_workflow`, adding an `n8n-nodes-base.executeCommand` node after the existing Manual Trigger and connecting the Manual Trigger to it.

If n8n's Execute Command node is disabled in this instance, fallback options are:

- use an HTTP Request node against a small internal IMAP organizer service;
- install/use a community IMAP action node;
- use n8n's IMAP trigger node for new mail only, accepting that it does not satisfy the "manual latest 50" requirement.

