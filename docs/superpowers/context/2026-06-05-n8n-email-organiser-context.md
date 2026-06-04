# n8n Email Organiser Context

Date: 2026-06-05
Workspace: `/home/eric/source/n8n-flows`
Repository: `https://github.com/ebrearley/n8n-flows`

## Current Revision

`Email Organiser` (`fm6pLPnZWsGfK1oH`) is an inactive 15-node n8n workflow. It now has a visible batch loop, visible Ollama AI classification node, structured JSON parser, Proton label target preparation, and separate apply nodes for bulk and trigger paths.

The saved n8n workflow is not active and was not executed.

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

The Python helper no longer calls Ollama in apply mode. n8n performs classification through the visible AI node.

## Runtime Environment

The `Email Trigger (IMAP)` node uses the IMAP credential assigned in n8n.

Execute Command nodes cannot access n8n credential secrets directly. For bulk fetch and label application, the n8n runtime also needs:

```bash
IMAP_USER=...
IMAP_PASSWORD=...
EMAIL_CLASSIFIER_SCRIPT=/home/node/.n8n/email-classifer/email_classifier.py
```

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
- Confirm `IMAP_USER`, `IMAP_PASSWORD`, and `EMAIL_CLASSIFIER_SCRIPT` are present in the n8n runtime.
- Confirm all Proton labels exist under `Labels`, including `Labels/Classified`.
- Configure production queue/concurrency to `1` before activating the workflow.
