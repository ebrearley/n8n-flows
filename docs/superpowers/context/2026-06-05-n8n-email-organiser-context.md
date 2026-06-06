# n8n Email Organiser Context

Date: 2026-06-05
Workspace: `/home/eric/source/n8n-flows`
Repository: `https://github.com/ebrearley/n8n-flows`

## Current Revision

`Email Organiser` (`fm6pLPnZWsGfK1oH`) is an inactive n8n workflow. It now has a visible batch loop, visible Ollama AI classification node, structured JSON parser, Proton label target preparation, and separate JavaScript Code-node apply paths for bulk and trigger processing.

The saved n8n workflow is not active and is not published. Manual execution now reaches `Get next 50 unclassified emails` and is blocked on missing `IMAP_USER` / `IMAP_PASSWORD` access for the Code node.

## Proton IMAP Target

- Host: `192.168.3.200`
- Port: `1143`
- TLS: STARTTLS
- Source mailbox: `INBOX`
- Proton labels root: `Labels`
- State label mailbox: `Labels/Classified`

Proton Mail exposes UI labels as nested mailboxes under `Labels`. The workflow applies accepted labels as `Labels/<label>` and applies `Labels/Classified` to every classified email.

The workflow must not create labels, create folders, move messages, delete messages, or expunge.

## Workflow Shape

Bulk path:

```text
Manual Trigger
  -> Configure Proton IMAP batch
  -> Get next 50 unclassified emails
  -> Expand fetched emails
  -> Loop Over Emails
  -> Build classification prompt
  -> Classify with Ollama
  -> Prepare Proton label targets
  -> From bulk loop?
  -> Apply Proton labels
  -> Loop Over Emails / next batch
```

Trigger path:

```text
Email Trigger (IMAP)
  -> Normalize trigger email
  -> Build classification prompt
  -> Classify with Ollama
  -> Prepare Proton label targets
  -> From bulk loop?
  -> Apply Proton labels (trigger)
```

## Ollama

- Node: `Ollama Chat Model`
- Agent: `Classify with Ollama`
- Base URL: `http://192.168.1.100:11434`
- Model: `gemma4-26b:4090`

The Python helper is retained only as legacy local test coverage. The current workflow performs IMAP fetch and label application inside n8n JavaScript Code nodes, and n8n performs classification through the visible AI node.

## Runtime Environment

The `Email Trigger (IMAP)` node uses the IMAP credential assigned in n8n.

The bulk fetch and label-application Code nodes cannot read n8n credential secrets directly. They currently read the following keys from n8n variables first, then from environment variables:

```bash
IMAP_USER=...
IMAP_PASSWORD=...
```

If using environment variables instead of n8n variables, n8n 2 blocks Code-node environment access by default. Enabling environment access requires setting `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, which lets Code nodes read runtime environment variables and needs explicit approval.

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
- Provide `IMAP_USER` and `IMAP_PASSWORD` through n8n variables, or explicitly approve `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` and set them as Coolify runtime env vars.
- Confirm all Proton labels exist under `Labels`, including `Labels/Classified`.
- Configure production queue/concurrency to `1` before activating the workflow.
