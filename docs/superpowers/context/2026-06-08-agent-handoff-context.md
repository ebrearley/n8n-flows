# Agent Handoff Context For n8n Flows

Date: 2026-06-08

Primary repo: `/home/eric/source/n8n-flows`

Related repo: `/home/eric/source/n8n-workflow-status`

This document is a detailed handoff from the long setup session for the n8n email organiser and workflow status dashboard. It is intentionally operational and specific so a fresh agent can continue iterating without asking the user to repeat context.

## User Intent

The user wants n8n workflows managed as code, with enough repository context that an agent can:

- iterate on the existing `Email Organiser` flow;
- add new n8n flows in the same style;
- import and publish flows to live n8n when requested;
- test behavior locally before importing;
- observe live execution through the companion status dashboard;
- avoid leaking private mailbox contents or secrets.

The current major workflow is an email classification and labelling flow for Proton Mail over IMAP.

## Source Control State

Repository:

```text
/home/eric/source/n8n-flows
https://github.com/ebrearley/n8n-flows
```

As of this handoff, the main checkout was dirty and ahead of origin. Treat existing local edits as user/agent work that must not be reverted casually.

Observed dirty files before this documentation update included:

```text
docs/superpowers/context/2026-06-05-n8n-email-organiser-context.md
docs/superpowers/specs/2026-06-05-email-organiser-design.md
email-classifer/README.md
email-classifer/code-nodes/get_next_50_unclassified_emails.js
email-classifer/code-nodes/normalize_trigger_email.js
email-classifer/code-nodes/prepare_proton_label_targets.js
email-classifer/email_classifier.py
email-classifer/tests/test_workflow_json.py
email-classifer/workflow-imap-trigger.json
email-classifer/workflow.json
```

The repo also has a local worktree:

```text
/home/eric/source/n8n-flows/.worktrees/workflow-telemetry-status
```

The associated branch is:

```text
feature/workflow-telemetry-status
origin/feature/workflow-telemetry-status
```

That branch includes the step telemetry generator and a 103-node workflow export. The local main checkout currently has the smaller workflow export without generated step telemetry nodes. Do not overwrite the live workflow with local main until you confirm which workflow state should be authoritative.

## Directory Layout

Main workflow directory:

```text
email-classifer/
```

The misspelling is intentional and should be preserved.

Key files in local main:

```text
email-classifer/workflow.json
email-classifer/workflow-imap-trigger.json
email-classifer/code-nodes/get_next_50_unclassified_emails.js
email-classifer/code-nodes/stop_if_no_fetched_emails.js
email-classifer/code-nodes/normalize_trigger_email.js
email-classifer/code-nodes/prepare_proton_label_targets.js
email-classifer/code-nodes/apply_proton_labels.js
email-classifer/email_classifier.py
email-classifer/tests/test_email_classifier.py
email-classifer/tests/test_workflow_json.py
```

Additional files on the step telemetry worktree/branch:

```text
email-classifer/tools/sync_code_nodes.py
email-classifer/tools/add_step_telemetry.py
email-classifer/code-nodes/telemetry_start_run.js
email-classifer/code-nodes/telemetry_finish_run.js
email-classifer/code-nodes/telemetry_build_email_items.js
email-classifer/code-nodes/telemetry_build_classification_attempt.js
email-classifer/code-nodes/telemetry_build_label_actions.js
email-classifer/code-nodes/telemetry_start_step.js
email-classifer/code-nodes/telemetry_finish_step.js
email-classifer/code-nodes/telemetry_restore_payload.js
email-classifer/code-nodes/telemetry_restore_first_payload.js
```

If future work needs telemetry support, prefer the telemetry worktree or merge/rebase that branch deliberately rather than copying fragments by hand.

## Live n8n System

n8n is deployed through Coolify.

Live identifiers:

```text
n8n URL: https://n8n.home.ericbrearley.com
Coolify service: ew4sow0ws8kggowogk4owk4c
Coolify project: tk7pb9r1a5cqvhth6kiot9e4
Coolify environment: auw9n2ov1ix59da3h3dcbvgt
n8n container: n8n-ew4sow0ws8kggowogk4owk4c
n8n Postgres container: postgresql-ew4sow0ws8kggowogk4owk4c
n8n workflow id: fm6pLPnZWsGfK1oH
n8n workflow name: Email Organiser
n8n project id for import: VYxWLhVfItgsWnnA
observed n8n version: 2.23.4
```

Useful SSH host:

```text
ubuntu@192.168.3.200
```

Live credential refs:

```text
IMAP trigger credential: type imap, id 8dnbMcRYZzmpdI9B, name eric@brearley.net
Ollama credential: type ollamaApi, id aR1KuRnGv6tTTkQ8, name Ollama account
Workflow status Postgres credential: type postgres, id wspg_a409ed51b8f18c5e, name Workflow Status Postgres
```

These are credential references, not secret values. Do not expose secret values.

Latest validated live state from the setup session:

- workflow was imported with step telemetry nodes;
- workflow was published;
- workflow was left inactive after validation;
- full live export had 103 nodes;
- backfill configuration was `batchLimit=50`, `maxBatches=0`;
- a capped validation import used `batchLimit=1`, `maxBatches=1`;
- the capped run completed successfully and wrote sanitized telemetry.

## n8n MCP

The n8n MCP server is configured for Codex as:

```toml
[mcp_servers.n8n-mcp]
url = "https://n8n.home.ericbrearley.com/mcp-server/http"
bearer_token_env_var = "N8N_MCP_ACCESS_TOKEN"
```

The user confirmed the intended tool setup is no allowed-tools restriction, so all tools should be available if the MCP server advertises them.

If Codex cannot see the token, restarting Codex is not enough unless `N8N_MCP_ACCESS_TOKEN` is available in the environment that launches Codex. The token may be visible in an interactive shell but absent from the Codex parent process.

## Email Organiser Workflow Behavior

The workflow is designed to handle two modes.

Backfill mode:

1. Start a bulk classification pass.
2. Fetch the next 50 emails not marked with the state label.
3. Process one email at a time.
4. Build a classification prompt.
5. Classify with local Ollama.
6. Parse and validate classifier JSON.
7. Apply all matching labels by IMAP copy into `Labels/<label>`.
8. Apply `Labels/Classified`.
9. Continue until the 50-item batch is exhausted.
10. Fetch the next 50.
11. Repeat until no unclassified email remains.

Trigger mode:

1. `Email Trigger (IMAP)` emits one new email.
2. Normalize it into the same item shape as the backfill path.
3. `Skip classified trigger email` checks whether the trigger email's `Message-ID` is already present in `Labels/Classified`.
4. If already classified, return no items so the message does not hit Ollama.
5. If not already classified, build prompt, classify, prepare label targets, apply labels.
6. Exit without entering the backfill loop.

The user eventually wants only one workflow execution running at a time because the local Ollama model is expensive. Production n8n should use queue mode and a concurrency limit of one.

## Backfill Trigger

The editor-only `Manual Trigger` has been removed from local main. `Backfill Form Trigger` is the explicit backfill start and uses this path:

```text
email-organiser-backfill
```

Keep the backfill path wired to `Configure Proton IMAP batch` and keep the bulk loop semantics unchanged.

## Proton IMAP Model

The mail service is Proton Mail via a Proton Bridge/IMAP endpoint.

Endpoint:

```text
host: 192.168.3.200
port: 1143
security: STARTTLS
allowUnauthorizedCerts: true
source mailbox: INBOX
label root: Labels
state label: Classified
state mailbox: Labels/Classified
```

Proton Mail exposes UI labels as IMAP mailboxes nested under `Labels`.

Examples:

```text
Labels/Invoice
Labels/Purchase
Labels/Schedule
Labels/Spam like
Labels/Classified
```

Applying a label is implemented as IMAP `UID COPY` to an existing label mailbox. The workflow must not create missing mailboxes. If a mailbox is missing, label application should be skipped for that email and the missing mailbox plus account/recipient context should be visible for debugging.

The workflow must not:

- create labels;
- create folders;
- move messages;
- delete messages;
- expunge messages;
- treat `Folders` as the label root.

## Multiple IMAP Accounts

The user has multiple separate personal IMAP accounts. They are not named personal/work. The workflow should support a list of IMAP credential pairs.

Current placeholders:

```text
IMAP_1_HOST
IMAP_1_PORT
IMAP_1_USER
IMAP_1_PASSWORD
IMAP_2_HOST
IMAP_2_PORT
IMAP_2_USER
IMAP_2_PASSWORD
```

The workflow reads n8n variables first, then environment variables. In n8n 2, Code-node environment access requires:

```text
N8N_BLOCK_ENV_ACCESS_IN_NODE=false
```

This was added to the n8n service after explicit user approval during setup.

The initial endpoint and port can be defined through environment variables. Default values in workflow config are still `192.168.3.200` and `1143`.

## Backfill Fetch Implementation

The backfill fetch Code node intentionally avoids expensive full-mailbox preloads.

Important settings:

```text
batchLimit: 50
maxBatches: 0
rawFetchByteLimit: 65536
fetchWatchdogMs: 120000
uidSearchWindow: 500
```

Semantics:

- `maxBatches=0` means unlimited/full backfill.
- A positive `maxBatches` is only for capped tests.
- The fetch node scans UID ranges in bounded windows.
- It fetches selected headers first.
- It fetches bounded raw previews for candidate messages.
- It checks `Labels/Classified` by candidate Message-ID as needed.
- It should skip already-classified messages.
- It includes stage counters if the fetch watchdog trips.

The user specifically asked whether this means only 50 emails are processed. It should not. The workflow should process batches of 50 repeatedly until the inbox is fully classified.

## Classification Prompt And Labels

Classification uses local Ollama:

```text
base URL: http://192.168.1.100:11434
model requested: gemma4-26b:4090
model observed in workflow JSON: odytrice/gemma4-26b:4090
temperature: 0
```

n8n nodes:

```text
Build classification prompt
Classify with Ollama
Ollama Chat Model
Prepare Proton label targets
```

The user wanted the prompt editable in n8n. The `Build classification prompt` node creates `systemPrompt` and `userPrompt`, and `Classify with Ollama` uses expressions:

```text
text: ={{ $json.userPrompt }}
systemMessage: ={{ $json.systemPrompt }}
```

The user prompt is conceptually:

```text
From: {{ $json.sender_email }}
Name: {{ $json.sender_name }}
Subject: {{ $json.email_subject }}
Email Content:

{{ $json.email_body }}
```

Allowed labels:

```text
Invoice
Purchase
Bill
Payment
Marketing
Cold email
Important
Awaiting reply
Travel
Ticket
Infrastructure
Hustle
Schedule
Spam like
```

Definitions added late in the session:

- `Schedule`: calendar invitations, calendar notifications, and things that have a time and place to be, like a wedding, meeting with friends, or work meeting.
- `Spam like`: emails that look like spam or junk mail.

The classifier should output only JSON:

```json
{
  "labels": [
    { "label": "Invoice", "confidence": 0.9 }
  ],
  "reason": "One sentence justification"
}
```

Uncertain fallback:

```json
{
  "labels": [
    { "label": "uncertain", "confidence": 0.5 }
  ],
  "reason": "What is ambiguous or missing"
}
```

`Prepare Proton label targets` should:

- parse plain JSON and fenced JSON;
- validate exact label names;
- keep only labels with `confidence >= 0.75`;
- ignore `uncertain` as an applied label;
- target only `Labels/Classified` if no confident labels remain;
- never stop the workflow merely because classification is uncertain.

The user added retry-on-fail directly to `Classify with Ollama` after empty structured parser responses. The current workflow has `hasOutputParser=false`; downstream Code parses the raw model output.

## Known Bugs And Fixes From The Session

### Unsupported Execute Command Node

The live n8n did not have `n8n-nodes-base.executeCommand` installed or available. Nodes using that type appeared as `?` in the UI and execution failed with:

```text
Unrecognized node type: n8n-nodes-base.executeCommand
```

Use `n8n-nodes-base.code` JavaScript nodes instead.

### TLS Server Name For IP Address

STARTTLS with an IP address originally triggered:

```text
Cannot assign to read only property 'name' of object 'Error: Setting the TLS ServerName to an IP address is not permitted by RFC 6066...'
```

The IMAP client Code nodes should not set TLS `servername` when `host` is an IP address.

### Invalid Prompt Syntax

`Build classification prompt` previously failed with invalid syntax because raw prompt templating was not a valid n8n expression. Tests should protect this by asserting the prompt fields are expression-compatible.

### Missing Label Behavior

If a label mailbox is missing, do not fail the workflow and do not create it. Skip label application and expose which mailbox and recipient/account need attention.

The user specifically asked to include `to` or `recipient` in missing-label details.

### Uncertain Emails Hanging

Uncertain classifier outputs previously looked like they hung. Desired behavior is to continue and apply only the state label:

```text
Labels/Classified
```

### Email Trigger Startup Error

The `Email Trigger (IMAP)` node logged:

```text
Search option argument must be a Date object or a parseable date string
```

Investigation on n8n `2.23.4` found the trigger can append a `SINCE` search condition on first activation if `trackLastMessageId` is enabled and static data has no last UID.

Local main now sets `Email Trigger (IMAP)` `options.trackLastMessageId=false`. Because that may cause old unread messages to be emitted, local main also routes trigger items through `Skip classified trigger email` before the AI node. The guard checks `Labels/Classified` by `Message-ID` and returns no items for already-classified messages.

Retest with current n8n docs and live n8n logs after importing this workflow shape.

## Telemetry Database

The user wanted persistent state/logging in a database rather than only n8n execution records. The setup created a separate database in the same Postgres engine used by n8n.

Database:

```text
workflow_status
```

Status app role:

```text
workflow_status_app
```

Tables from the initial migration include:

```text
workflows
workflow_runs
workflow_steps
email_items
classification_attempts
label_actions
workflow_errors
schema_migrations
```

The workflow telemetry writes are done with first-party n8n Postgres nodes using the `Workflow Status Postgres` credential. For n8n `2.23.x`, Postgres node parameters must use:

```text
options.queryReplacement
```

not:

```text
queryParameters
```

## Step Telemetry Branch

The step telemetry branch adds current-step visibility for the companion status dashboard.

Branch/worktree:

```text
feature/workflow-telemetry-status
/home/eric/source/n8n-flows/.worktrees/workflow-telemetry-status
```

Workflow stage instrumentation:

```text
Start run
Configure batch
Fetch next unclassified emails
Expand fetched emails
Build classification prompt
Classify with Ollama
Prepare Proton label targets
Apply Proton labels
Apply Proton labels (trigger)
Finish run
```

Generated nodes per stage:

```text
Telemetry start step: <stage>
Telemetry record step: <stage>
Telemetry restore step start: <stage>
Telemetry finish step: <stage>
Telemetry update step: <stage>
Telemetry restore step finish: <stage>
```

Important review outcomes:

- generated telemetry must preserve original payload flow;
- start nodes must overwrite stale telemetry stage metadata;
- finish nodes must recover the matching step id after fan-out/replacement;
- update SQL must fail if no row is updated;
- restored payload should come from original n8n items, not from SQL-returned `payload_json`;
- sanitization must not store full body, raw message, full prompt, or secrets;
- `body_preview` is capped;
- generator rejects multi-output stage targets.

The current `n8n-workflow-status` app reads this `workflow_steps` data and derives the current/final/error step from it.

## Companion Repo: n8n-workflow-status

Local path:

```text
/home/eric/source/n8n-workflow-status
```

GitHub:

```text
https://github.com/ebrearley/n8n-workflow-status
```

App URL:

```text
https://n8n-workflow-status.home.brearley.net
```

Coolify app UUID:

```text
hpuhcco92fb6xgqjnwd8mcvt
```

Latest deployed commit observed:

```text
74a92738993c95fd55871faf2b8c715d51d5a80f fix: select current step by start time
```

Stack:

```text
Next.js 16 App Router
React 19
Tailwind CSS 4
shadcn/ui
next-themes
PostgreSQL via pg
```

Access model:

- no built-in app auth;
- private access is handled by Pangolin reverse proxy plus firewall;
- unauthenticated public request should redirect to Pangolin;
- local Coolify Traefik request with Host header should return app responses.

Status app env:

```text
DATABASE_URL
N8N_BASE_URL=http://workflow-status-n8n:5678
N8N_API_KEY
POLL_INTERVAL_MS=3000
NEXT_PUBLIC_POLL_INTERVAL_MS=3000
```

Do not print the `N8N_API_KEY`.

The app shows:

- workflow list in side menu;
- global totals;
- global token total;
- focused workflow detail;
- run history and duration;
- current step;
- step input/output/error JSON;
- email item context;
- AI model and token usage;
- label actions;
- errors.

The status app uses shadcn default font variables and supports light/dark mode.

## Observability

The user has Grafana, Loki, Prometheus, and Grafana Alloy in Coolify.

Grafana Alloy service page:

```text
https://coolify.home.brearley.net/project/awy7zg616scotlha3xvb7p06/environment/s919ifv4r8d48963hf08pbac/service/whn1bhmqii3xq5u47qoz636m
```

Alloy config files:

```text
ssh ubuntu@192.168.3.200:/var/app-data/o11y/grafana-alloy/config
```

The user reported some logs show up in Grafana but n8n logs did not. This was not fully resolved in this repo. The status app has a Loki query doc:

```text
/home/eric/source/n8n-workflow-status/docs/observability/loki-logql.md
```

Useful LogQL selectors from that doc:

```logql
{service="n8n"}
{service="n8n"} |= "\"workflow_name\":\"Email Organiser\""
{service="n8n"} |= "\"workflow_name\":\"Email Organiser\"" |= "\"status\":\"error\""
{coolify_service="n8n"}
```

Do not add Pushgateway yet. The user explicitly said not to add it.

## Import And Publish Procedure

When asked to update live n8n, prepare a temporary import JSON rather than editing committed secrets.

For the current live `Email Organiser` workflow:

1. Start from the intended workflow export.
2. Set `id` to `fm6pLPnZWsGfK1oH`.
3. Set `active` to `false`.
4. Inject live credential references.
5. Copy the file into the n8n container.
6. Run import, publish, deactivate.
7. Restart n8n and wait for health.
8. Export/inspect the workflow to verify node count, key settings, credentials, and active state.

Commands that worked during setup:

```bash
docker exec n8n-ew4sow0ws8kggowogk4owk4c n8n import:workflow --input=/tmp/email-organiser-step-telemetry-import.json --projectId=VYxWLhVfItgsWnnA
docker exec n8n-ew4sow0ws8kggowogk4owk4c n8n publish:workflow --id=fm6pLPnZWsGfK1oH
docker exec n8n-ew4sow0ws8kggowogk4owk4c n8n update:workflow --id=fm6pLPnZWsGfK1oH --active=false
docker restart n8n-ew4sow0ws8kggowogk4owk4c
docker inspect --format "{{.State.Health.Status}}" n8n-ew4sow0ws8kggowogk4owk4c
```

`update:workflow` was deprecated but worked. Check current n8n docs through ctx7 before relying on it in future.

## Safe Live Validation

For a setup smoke test, import a capped temporary workflow:

```text
batchLimit=1
maxBatches=1
```

Execute:

```bash
docker exec -e N8N_RUNNERS_BROKER_PORT=5681 -e N8N_RUNNERS_TASK_REQUEST_TIMEOUT=240 n8n-ew4sow0ws8kggowogk4owk4c n8n execute --id=fm6pLPnZWsGfK1oH
```

Warning: this command can print private email data. Do not include the output in chat. Use sanitized database queries for verification.

Safe Postgres check pattern:

```bash
ssh ubuntu@192.168.3.200 'docker exec postgresql-ew4sow0ws8kggowogk4owk4c sh -lc '\''psql -U "$POSTGRES_USER" -d workflow_status -c "select id, workflow_name, status, total_emails, total_estimated_tokens from workflow_runs order by started_at desc limit 5;"'\'''
```

Known successful capped run summary:

```text
execution id: 54
run id: 3276939b-659e-494e-8a8d-0af412ff6106
status: success
total_emails: 1
total_estimated_tokens: 1593
step_count: 10
running_steps: 0
error_steps: 0
```

Do not add any email details from that run.

## Test And Verification Commands

From local main:

```bash
cd /home/eric/source/n8n-flows
python3 -m unittest discover -s email-classifer/tests
git diff --check
```

From the step telemetry worktree:

```bash
cd /home/eric/source/n8n-flows/.worktrees/workflow-telemetry-status
python3 email-classifer/tools/sync_code_nodes.py
python3 email-classifer/tools/add_step_telemetry.py
python3 -m unittest discover -s email-classifer/tests
git diff --check
```

Compile standalone Code-node sources:

```bash
python3 - <<'PY'
from pathlib import Path
from subprocess import run, PIPE
wrapper = "const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;\nnew AsyncFunction('$input', '$json', '$', %r);\n"
for code_path in Path('email-classifer/code-nodes').glob('*.js'):
    code = code_path.read_text()
    proc = run(['node', '-e', wrapper % code], text=True, stdout=PIPE, stderr=PIPE)
    if proc.returncode:
        print(code_path)
        print(proc.stderr)
        raise SystemExit(proc.returncode)
print('compiled code nodes')
PY
```

Compile inline workflow Code nodes:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from subprocess import run, PIPE
wrapper = "const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;\nnew AsyncFunction('$input', '$json', '$', %r);\n"
for wf_path in [Path('email-classifer/workflow.json'), Path('email-classifer/workflow-imap-trigger.json')]:
    wf = json.loads(wf_path.read_text())
    for node in wf['nodes']:
        if node.get('type') == 'n8n-nodes-base.code':
            code = node.get('parameters', {}).get('jsCode', '')
            proc = run(['node', '-e', wrapper % code], text=True, stdout=PIPE, stderr=PIPE)
            if proc.returncode:
                print(wf_path, node['name'])
                print(proc.stderr)
                raise SystemExit(proc.returncode)
print('compiled workflow code nodes')
PY
```

Status app verification:

```bash
cd /home/eric/source/n8n-workflow-status
npm test
npm run lint
npm run build
git diff --check
```

## Adding A New Flow

When adding a new flow in this repo:

1. Create a new directory with an importable `workflow.json`.
2. Keep Code-node JavaScript in `code-nodes/`.
3. Add tests that protect node types, credentials, critical parameters, expressions, and safety behavior.
4. Prefer first-party n8n nodes and JavaScript Code nodes.
5. Do not use `executeCommand` unless live n8n definitely supports it and the user approves.
6. Keep credentials out of committed workflow JSON.
7. Add a context doc with live workflow ID, credential reference IDs, runtime endpoints, and safety constraints.
8. If the flow needs observability, reuse the `workflow_status` database shape or extend it deliberately with a migration in the status app repo.
9. If the flow touches private content, document exactly what can and cannot be logged.

## Open Work

Open or likely follow-up tasks from the session:

- Import and retest the `Email Trigger (IMAP)` startup fix in live n8n.
- Decide whether to merge the step telemetry branch into main.
- Confirm live n8n still matches the telemetry workflow before importing any new local export.
- Investigate why n8n logs were not visible in Grafana/Loki while other services were.
- Continue improving the status app only if the user asks after seeing the dashboard.
