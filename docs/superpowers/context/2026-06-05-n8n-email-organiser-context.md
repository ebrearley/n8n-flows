# n8n Email Organiser Context

Date: 2026-06-05
Workspace: `/home/eric/source/n8n-flows`
Repository: `https://github.com/ebrearley/n8n-flows`

## Current Revision

For the newest cross-repo handoff, read `docs/superpowers/context/2026-06-10-email-organiser-workflow-split.md`, `docs/superpowers/context/2026-06-08-agent-handoff-context.md`, and root `AGENTS.md`.

`Email Organiser` (`fm6pLPnZWsGfK1oH`) is the n8n workflow for Proton IMAP email classification. It has a visible batch loop, visible Ollama AI classification node, raw JSON parsing in Proton label target preparation, an empty-batch stop guard, and JavaScript Code-node paths for IMAP fetch, label application, and post-label action planning/execution.

The latest verified live n8n workflow from the setup session was imported and published, then left inactive. `Configure Proton IMAP batch` sets `maxBatches=0` for full backfill, so a backfill/manual execution keeps fetching 50-email batches until no unclassified emails remain.

Important repository split as of 2026-06-10: `workflow.json` and `workflow-imap-trigger.json` back the telemetry-free production workflow `Email Organiser` (`fm6pLPnZWsGfK1oH`), while `workflow-with-telemetry.json` backs the iteration/status workflow `Email Organiser (with telemetry)` (`bXNCHRxwqXoOeePH`).

The bulk fetch path avoids full mailbox and classified-message preloads. It scans source mailboxes by bounded UID ranges (`uidSearchWindow=500`), verifies candidate `Message-ID`s against `Labels/Classified` as needed, requests only selected IMAP header fields, and caps each raw email preview at `rawFetchByteLimit=65536` bytes. `fetchWatchdogMs=120000` stops the first batch fetch with stage counters if it stalls.

## Proton IMAP Target

- Host: `192.168.3.200`
- Port: `1143`
- TLS: STARTTLS
- Source mailbox: `INBOX`
- Proton labels root: `Labels`
- State label mailbox: `Labels/Classified`

Proton Mail exposes UI labels as nested mailboxes under `Labels`. The workflow applies accepted labels as `Labels/<label>` and applies `Labels/Classified` to every classified email.

During label application, the workflow must not create labels, create folders, move messages, delete messages, or expunge.

## Email Action Phase

The email action phase was designed on 2026-06-09. It moves selected messages after labels are applied. Actions are live by default, with optional `dry_run` and `disabled` modes.

Verified action mailboxes from the live n8n runtime IMAP connection:

- `Archive` (`\Archive`)
- `Spam` (`\Junk`)
- `Trash` (`\Trash`)

The action executor must use `UID MOVE` and must not use `EXPUNGE`, folder creation, or delete fallbacks.

## Workflow Shape

Bulk/backfill path:

```text
Backfill Form Trigger
  -> Configure Proton IMAP batch
  -> Get next 50 unclassified emails
  -> Stop if no fetched emails
  -> Expand fetched emails
  -> Loop Over Emails
  -> Build classification prompt
  -> Classify with Ollama
  -> Prepare Proton label targets
  -> Plan email actions
  -> From bulk loop?
  -> Apply Proton labels
  -> Execute email action
  -> Loop Over Emails / next batch
```

Trigger path:

```text
Email Trigger (IMAP)
  -> Normalize trigger email
  -> Skip classified trigger email
  -> Build classification prompt
  -> Classify with Ollama
  -> Prepare Proton label targets
  -> Plan email actions
  -> From bulk loop?
  -> Apply Proton labels (trigger)
  -> Execute email action (trigger)
```

## Ollama

- Node: `Ollama Chat Model`
- Agent: `Classify with Ollama`
- Base URL: `http://192.168.1.100:11434`
- Model: `igorls/gemma4-e4b-classifier:latest`

The Python helper is retained only as legacy local test coverage. The current workflow performs IMAP fetch, label application, and post-label action planning/execution inside n8n JavaScript Code nodes, and n8n performs classification through the visible AI node.

During setup, `Classify with Ollama` has retry disabled so model errors stop the workflow and are visible in the execution.

`uncertain` classification should not stop the workflow. It should continue with only `Labels/Classified` as the target.

## Runtime Environment

The `Email Trigger (IMAP)` node uses the IMAP credential assigned in n8n.

The bulk fetch, label-application, and action Code nodes cannot read n8n credential secrets directly. They use `imapPairsJson` on `Configure Proton IMAP batch` to define one or more IMAP credential pairs. Each pair names the variables that hold its credentials. The default placeholders are:

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

The Code nodes read these names from n8n variables first, then from environment variables.

If using environment variables instead of n8n variables, n8n 2 blocks Code-node environment access by default. Enabling environment access requires setting `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, which lets Code nodes read runtime environment variables and needs explicit approval.

Coolify placeholder env vars have been created on the n8n service for `IMAP_1_USER`, `IMAP_1_PASSWORD`, `IMAP_1_HOST`, `IMAP_1_PORT`, `IMAP_2_USER`, `IMAP_2_PASSWORD`, `IMAP_2_HOST`, and `IMAP_2_PORT`. Replace the placeholder credential values in Coolify before executing the workflow.

## n8n MCP

Codex n8n MCP server config:

```toml
[mcp_servers.n8n-mcp]
url = "https://n8n.home.ericbrearley.com/mcp-server/http"
bearer_token_env_var = "N8N_MCP_ACCESS_TOKEN"
```

No `enabled_tools` allow-list is configured, so Codex should expose all tools advertised by the n8n MCP server.

## Open Checks

- Confirm the `Ollama Chat Model` credential/endpoint is valid in n8n if the UI asks for an `Ollama account`.
- Replace placeholder values for `IMAP_1_USER`, `IMAP_1_PASSWORD`, `IMAP_2_USER`, and `IMAP_2_PASSWORD`; update host/port variables if either endpoint differs; add more pairs and variables if needed.
- If using Coolify runtime env vars rather than n8n variables, explicitly approve `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`.
- Confirm all Proton labels exist under `Labels`, including `Labels/Classified`.
- Keep the production and telemetry workflow IDs separate when importing from code.
- Retest the `Email Trigger (IMAP)` startup issue after import. Current local main sets `trackLastMessageId=false` and routes trigger mail through `Skip classified trigger email`.
- Keep `maxBatches=0` for full manual backfill; set it to a positive number only for deliberately capped test runs.
- Keep `rawFetchByteLimit=65536` unless larger email body previews are needed for classification.
- Keep `fetchWatchdogMs=120000` while setup is being debugged so slow IMAP fetch stages fail visibly.
- Keep `uidSearchWindow=500` unless the IMAP source range scans need tuning.
- Configure production queue/concurrency to `1` before activating the workflow.
