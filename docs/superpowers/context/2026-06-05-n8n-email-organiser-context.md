# n8n Email Organiser Context

Date: 2026-06-05
Workspace: `/home/eric/source/n8n-flows`
Repository: `https://github.com/ebrearley/n8n-flows`

## Current Goal

Build out the n8n workflow named `Email Organiser` so it can be run manually, pull the most recent 50 emails from an IMAP server, classify them with local Ollama, and move them into folders.

## Codex MCP Configuration

The Codex n8n MCP server config was restored in `~/.codex/config.toml`:

```toml
[mcp_servers.n8n-mcp]
url = "https://n8n.home.ericbrearley.com/mcp-server/http"
bearer_token_env_var = "N8N_MCP_ACCESS_TOKEN"
```

No `enabled_tools` allow-list is configured, so Codex should expose all tools advertised by the n8n MCP server. The token value is intentionally not stored here.

## n8n Workflow

Workflow found via n8n MCP:

- Name: `Email Organiser`
- ID: `fm6pLPnZWsGfK1oH`
- Active: `false`
- Archived: `false`
- Available in MCP: `true`
- Can execute: `true`
- Current nodes: one manual trigger named `When clicking 'Execute workflow'`
- Current credentials visible through MCP: none

Workflow-as-code artifacts were added under `email-classifer/`:

- `workflow.json`: importable n8n workflow JSON for Manual Trigger -> Configure classification prompt -> Execute Command.
- `email_classifier.py`: stdlib Python script run by the Execute Command node.
- `tests/`: deterministic unit tests for local classifier helper behavior.
- `README.md`: runtime environment and import instructions.

## IMAP Target

User-provided IMAP endpoint:

- Host: `192.168.3.200`
- Port: `1143`

Credentials have not been provided in chat and should not be written into repo files. Proposed n8n environment variable names:

- `IMAP_USER`
- `IMAP_PASSWORD`

Live IMAP folder discovery is runtime/integration behavior. Unit tests should not depend on the current live folder list from `192.168.3.200:1143`.

Per user instruction, do not execute the workflow against the mailbox until the destination labels/folders have been set up in email.

## Ollama Target

User-provided Ollama endpoint and model:

- Base URL: `http://192.168.1.100:11434`
- Model: `gemma4-26b:4090`
- Keep loaded: `OLLAMA_KEEP_ALIVE=-1`

The classifier calls Ollama `/api/chat` with `stream=false`, `format=json`, `temperature=0`, and a conservative prompt that falls back to `uncertain`.

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

## Node Discovery Notes

n8n MCP node search found:

- `n8n-nodes-base.manualTrigger` for manual workflow execution.
- `n8n-nodes-base.emailReadImap`, but it is an IMAP trigger node for new mail, not a general manual action node for fetching the latest 50 messages.
- Gmail and Outlook nodes support label/folder operations, but the requested server is raw IMAP.

Because a generic IMAP action node was not found, the practical design is to use an Execute Command node with a short Python `imaplib` script. That script is now represented as workflow-as-code in this repo.

## Open Decisions

- Confirm whether to use `IMAP_USER` and `IMAP_PASSWORD` environment variables inside n8n.
- Confirm labels/folders have been created in email before any workflow execution.
- Confirm whether the first workflow execution should remain dry-run.
