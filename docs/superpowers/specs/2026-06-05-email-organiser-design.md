# Email Organiser Workflow Design

Date: 2026-06-05
Workflow: `Email Organiser` (`fm6pLPnZWsGfK1oH`)

## Current Revision

`Email Organiser` is an active, published n8n workflow with two entry points:

- a manual bulk pass that fetches up to 50 unclassified IMAP emails at a time, loops over them one by one, and repeats until no unclassified emails remain;
- an `Email Trigger (IMAP)` path that classifies one newly received email.

Both paths use a visible n8n AI Agent node, `Classify with Ollama`, backed by an `Ollama Chat Model` node configured for `gemma4-26b:4090` at `http://192.168.1.100:11434`.

## Proton IMAP Label Model

The mail provider is Proton Mail. Through IMAP it exposes top-level mailboxes named `Folders` and `Labels`. Proton Mail UI labels live under the `Labels` mailbox, so workflow label targets must be `Labels/<label>`.

Examples:

- `Labels/Invoice`
- `Labels/Hustle`
- `Labels/Schedule`
- `Labels/Spam like`
- `Labels/Classified`

`Labels/Classified` is the state marker used to avoid reprocessing already classified emails.

The workflow must not create labels, create folders, move source messages, delete messages, or expunge. It only applies labels by copying the source message to existing `Labels/*` mailboxes.

## Data Flow

Manual bulk pass:

1. `Manual Trigger` starts the pass from n8n.
2. `Configure Proton IMAP batch` sets `imapPairsJson`, `batchLimit=50`, `maxBatches=0`, `rawFetchByteLimit=65536`, `fetchWatchdogMs=120000`, `uidSearchWindow=500`, and fallback IMAP defaults.
3. `Get next 50 unclassified emails` runs JavaScript in an n8n Code node.
4. The Code node iterates credential pairs, reading each pair's `userVar` and `passwordVar` from n8n variables first, then environment variables.
5. The Code node scans each pair's `sourceMailboxes` by bounded UID ranges, skips messages already present in that account's `Labels/Classified` using per-candidate `Message-ID` checks, fetches only selected headers and bounded body previews, and returns up to 50 email items. A fetch watchdog stops the node with stage counters if the first batch cannot be prepared in time.
6. `Stop if no fetched emails` returns no items when the fetch result is empty, including when `maxBatches` has been reached.
7. `Expand fetched emails` turns the script JSON into one n8n item per email.
8. `Loop Over Emails` processes one email at a time.
9. `Build classification prompt` creates the editable system prompt and per-email user prompt.
10. `Classify with Ollama` classifies the email with the local Ollama model and returns raw JSON text. During setup this node has retry disabled so model errors stop the workflow.
11. `Prepare Proton label targets` parses raw or fenced JSON, validates labels, drops unknown/low-confidence labels, maps accepted labels to `Labels/<label>`, and always adds `Labels/Classified`.
12. `From bulk loop?` routes bulk items to `Apply Proton labels`.
13. `Apply Proton labels` uses the email item's `credentialPair` to reconnect to the original account, `UID COPY` the message into each `Labels/<label>` mailbox, and loop back to `Loop Over Emails`.
14. When the 50-item batch is done, the loop's done output runs `Get next 50 unclassified emails` again. With `maxBatches=0`, this repeats until no unclassified emails remain; set `maxBatches` to a positive number only for deliberately capped test runs.

Live trigger:

1. `Email Trigger (IMAP)` emits one new email item using the n8n IMAP credential.
2. `Normalize trigger email` maps the trigger payload to the same email item shape as the bulk path.
3. The item flows through `Build classification prompt`, `Classify with Ollama`, and `Prepare Proton label targets`.
4. `From bulk loop?` routes trigger items to `Apply Proton labels (trigger)`, which applies labels and exits without entering the bulk loop.

## Runtime Requirements

The live trigger uses the IMAP credential configured in n8n.

The Code nodes cannot read n8n credential secrets directly. `imapPairsJson` names the variables for each account, for example:

```bash
IMAP_1_USER=...
IMAP_1_PASSWORD=...
IMAP_1_HOST=...
IMAP_1_PORT=...
IMAP_2_USER=...
IMAP_2_PASSWORD=...
IMAP_2_HOST=...
IMAP_2_PORT=...
```

If those values are supplied through Coolify environment variables rather than n8n variables, n8n also needs `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`.

Production execution should be queued with concurrency `1` before activation so the local Ollama GPU only handles one classifier workflow at a time.

## Safety

All destination labels must already exist under Proton's `Labels` mailbox, including `Labels/Classified`.

`uncertain` is a classifier fallback, not a Proton label target. If no confident label is accepted, the workflow applies only `Labels/Classified` so the message is not retried forever.

The workflow is active and should only remain active once the required labels and runtime environment are ready.

While the workflow is being set up, model retries are disabled so errors stop the execution and remain visible in n8n.

## Testing

Local deterministic tests cover:

- Proton `Labels/` mailbox target construction;
- ignoring `uncertain` as a real label;
- STARTTLS runtime configuration;
- applying labels without delete or expunge;
- using classification supplied by the n8n AI node instead of calling Ollama inside Python.
