# Codex Context: n8n-flows

This repository contains workflow-as-code and local test coverage for n8n flows, primarily the Proton IMAP email classification workflow named `Email Organiser`.

Read this file before changing workflows. It captures decisions and operational context from the setup session so a fresh agent can iterate without re-discovering everything.

## Non-Negotiables

- Do not print, quote, commit, or summarize private email bodies, raw email content, prompt text containing full email bodies, API keys, IMAP passwords, database passwords, or n8n API keys.
- Be especially careful with `n8n execute`: even without `--rawOutput`, it can print stored execution data containing private mailbox content. Prefer validating through sanitized `workflow_status` Postgres telemetry.
- Do not create Proton labels/folders from the workflow. The workflow only applies labels by copying messages into existing `Labels/<label>` IMAP mailboxes.
- Do not move, delete, expunge, or otherwise mutate source messages beyond copying to existing label mailboxes.
- Keep setup/debug runs fail-closed unless the user explicitly asks for production-style tolerant behavior. The user wants errors to stop the workflow while this is being built.
- `uncertain` is not a Proton label. If classification is uncertain, apply only `Labels/Classified` and continue to the next email.
- Existing local changes may be present. Never revert changes you did not make.
- Use `apply_patch` for manual file edits.
- Use `rg` or `rg --files` for local search.
- Use the `ctx7` CLI for current docs about n8n, Coolify, Next.js, shadcn/ui, Tailwind, or other libraries/tools.

## Repository Map

- Local repo: `/home/eric/source/n8n-flows`
- GitHub repo: `https://github.com/ebrearley/n8n-flows`
- Main workflow directory: `email-classifer`
- The directory name `email-classifer` is intentionally misspelled and should not be renamed unless the user asks.

Important files:

- `email-classifer/workflow.json`: importable workflow export.
- `email-classifer/workflow-imap-trigger.json`: compatibility export kept in sync with `workflow.json`.
- `email-classifer/code-nodes/*.js`: JavaScript used by n8n Code nodes.
- `email-classifer/email_classifier.py`: legacy Python helper retained for tested behavior references.
- `email-classifer/tests/test_workflow_json.py`: workflow JSON and Code-node behavior tests.
- `email-classifer/tests/test_email_classifier.py`: legacy helper behavior tests.
- `docs/superpowers/context/`: durable handoff and investigation notes.
- `docs/superpowers/specs/`: design notes.
- `docs/superpowers/plans/`: implementation plans and verification records.

## Current Branch And Divergence

As of 2026-06-08, the main checkout had uncommitted workflow and docs changes and was ahead of `origin/main`:

```text
main...origin/main [ahead 3]
```

The local main workflow export had the smaller non-step-telemetry graph, about 17 nodes.

A local worktree and branch also exist:

```text
/home/eric/source/n8n-flows/.worktrees/workflow-telemetry-status
feature/workflow-telemetry-status
origin/feature/workflow-telemetry-status
```

That branch contains generated step telemetry around the email organiser workflow and has a 103-node export. Relevant commits include:

- `8a51cda feat: add step telemetry helpers`
- `ddf8fe1 fix: preserve payload through step telemetry`
- `d29a03c fix: keep step telemetry params sanitized`
- `7eff3a6 fix: strip nested raw step payloads`
- `f17ca04 feat: generate email organiser step telemetry`
- `c3c71d3 fix: align step telemetry with design review`
- `bc83388 fix: harden generated step telemetry`

The last live n8n validation used the telemetry workflow shape, not the smaller local main export. If you are about to import a workflow, first confirm which state the user wants:

- local main without step telemetry;
- the `feature/workflow-telemetry-status` branch;
- a fresh export from live n8n.

Do not silently overwrite live n8n with the smaller local main export if the status dashboard still expects `workflow_steps` rows.

## Live n8n Context

- n8n public URL: `https://n8n.home.ericbrearley.com`
- n8n Coolify service URL: `https://coolify.home.ericbrearley.com/project/tk7pb9r1a5cqvhth6kiot9e4/environment/auw9n2ov1ix59da3h3dcbvgt/service/ew4sow0ws8kggowogk4owk4c`
- Coolify host: `ubuntu@192.168.3.200`
- n8n container: `n8n-ew4sow0ws8kggowogk4owk4c`
- n8n Postgres container: `postgresql-ew4sow0ws8kggowogk4owk4c`
- Observed n8n version: `2.23.4`
- Workflow ID: `fm6pLPnZWsGfK1oH`
- Workflow name: `Email Organiser`
- Project ID for import: `VYxWLhVfItgsWnnA`

Live credential references that may need to be injected into workflow JSON before import:

- IMAP trigger credential: type `imap`, id `8dnbMcRYZzmpdI9B`, name `eric@brearley.net`
- Ollama credential: type `ollamaApi`, id `aR1KuRnGv6tTTkQ8`, name `Ollama account`
- Workflow status Postgres credential: type `postgres`, id `wspg_a409ed51b8f18c5e`, name `Workflow Status Postgres`

These IDs are not secrets. Do not document or print credential values.

Latest verified live state from the step-telemetry work:

- workflow imported and published;
- workflow then left inactive;
- full workflow export contained 103 nodes;
- `Configure Proton IMAP batch` had `batchLimit=50`;
- `Configure Proton IMAP batch` had `maxBatches=0`;
- one capped validation run used `batchLimit=1` and `maxBatches=1`;
- capped validation processed one email and recorded sanitized telemetry rows;
- no private email content should be quoted from that run.

## n8n MCP Context

Codex n8n MCP config used during setup:

```toml
[mcp_servers.n8n-mcp]
url = "https://n8n.home.ericbrearley.com/mcp-server/http"
bearer_token_env_var = "N8N_MCP_ACCESS_TOKEN"
```

The intended MCP configuration has no `enabled_tools` allow-list. An empty or absent allow-list is intended to expose all tools advertised by the n8n MCP server. The token must be available in Codex's process environment, not merely in an interactive shell after Codex has already started.

## Email Organiser Goals

The workflow classifies Proton Mail messages using a local Ollama model and applies Proton labels through IMAP.

Bulk/backfill behavior:

- manually start a backfill pass;
- fetch up to 50 unclassified emails;
- process emails one by one;
- apply any confident labels;
- always apply `Labels/Classified` after classification, including uncertain classification;
- fetch the next batch of 50;
- continue until no unclassified emails remain.

Live trigger behavior:

- after backfill is complete, classify new messages from `Email Trigger (IMAP)`;
- process the single trigger email through the same prompt, model, target preparation, and label-application path;
- use n8n queue/concurrency so only one workflow execution runs at a time because local Ollama GPU compute is the bottleneck.

The user later asked to remove the editor-only `Manual Trigger` and leave the backfill trigger. As of this document, the local main workflow still contains both `Manual Trigger` and `Backfill Form Trigger`. Treat trigger cleanup as open work unless you confirm it has already been done in the current checkout or live n8n.

Manual versus backfill trigger:

- `Manual Trigger` is the n8n editor manual execute trigger.
- `Backfill Form Trigger` is a form/webhook-style trigger with path `email-organiser-backfill`.
- The backfill trigger routes into the same bulk path as the manual trigger.

## Proton IMAP Context

The mail provider is Proton Mail via Proton Bridge. Proton exposes two top-level IMAP mailboxes named `Folders` and `Labels`; UI labels live under `Labels`.

IMAP endpoint:

- host: `192.168.3.200`
- port: `1143`
- transport: STARTTLS
- TLS certificate validation: allow unauthorized certificate during local bridge setup
- source mailbox: `INBOX`
- label root: `Labels`
- state label: `Classified`
- state mailbox: `Labels/Classified`

Applying a Proton label means copying the message into the label mailbox:

```text
UID COPY <uid> "Labels/<label>"
UID COPY <uid> "Labels/Classified"
```

The workflow must not create missing mailboxes. If a target mailbox is missing, skip applying labels for that email and make the missing mailbox visible in telemetry/output so the user can create it in Proton.

The user has multiple separate personal IMAP accounts. They are not personal/work categories. The workflow supports a list of credential pairs in `imapPairsJson`, currently using placeholders for two accounts:

```json
[
  {
    "id": "imap-1",
    "hostVar": "IMAP_1_HOST",
    "portVar": "IMAP_1_PORT",
    "userVar": "IMAP_1_USER",
    "passwordVar": "IMAP_1_PASSWORD"
  },
  {
    "id": "imap-2",
    "hostVar": "IMAP_2_HOST",
    "portVar": "IMAP_2_PORT",
    "userVar": "IMAP_2_USER",
    "passwordVar": "IMAP_2_PASSWORD"
  }
]
```

The Code nodes read n8n variables first, then runtime environment variables. Environment access from Code nodes requires this n8n setting:

```text
N8N_BLOCK_ENV_ACCESS_IN_NODE=false
```

The user previously configured placeholder Coolify env vars and then provided real values separately. Do not print those values.

## Classification Model And Prompt

Ollama endpoint:

- LAN host: `192.168.1.100`
- base URL: `http://192.168.1.100:11434`
- local model requested by the user: `gemma4-26b:4090`
- workflow model value observed in JSON: `odytrice/gemma4-26b:4090`
- temperature: `0`

Classification is done by the visible n8n AI Agent node:

- node: `Classify with Ollama`
- model node: `Ollama Chat Model`
- prompt text: `={{ $json.userPrompt }}`
- system message: `={{ $json.systemPrompt }}`
- structured output parser was removed/disabled after empty parser responses caused failures; JSON parsing is handled downstream in Code.

The editable user prompt shape is:

```text
From: {{ $json.sender_email }}
Name: {{ $json.sender_name }}
Subject: {{ $json.email_subject }}
Email Content:

{{ $json.email_body }}
```

Inside n8n Set nodes, this needs to be represented as an n8n expression that builds `userPrompt`. Do not paste raw `{{ }}` templating into a plain string if tests expect an evaluable expression.

Allowed labels:

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
- `Schedule`
- `Spam like`

`Schedule` is for calendar invitations, calendar notifications, and anything with a time and place to be, such as a wedding, meeting with friends, or work meeting.

`Spam like` is for emails that look like spam or junk mail.

Expected classifier output shape:

```json
{
  "labels": [
    { "label": "Invoice", "confidence": 0.9 }
  ],
  "reason": "One sentence justification"
}
```

Fallback shape:

```json
{
  "labels": [
    { "label": "uncertain", "confidence": 0.5 }
  ],
  "reason": "What is ambiguous or missing"
}
```

Downstream behavior:

- parse raw JSON or fenced JSON;
- validate labels against the fixed list;
- drop unknown or low-confidence labels;
- do not fail merely because the label is `uncertain`;
- if no confident label remains, target only `Labels/Classified`;
- if a confident label mailbox is missing, skip label application and expose the missing target plus recipient/account context.

## Known Email Trigger Issue

The `Email Trigger (IMAP)` node had a live startup/fetch error:

```text
Search option argument must be a Date object or a parseable date string
```

Investigation on n8n `2.23.4` found that the installed EmailReadImap v2 code sets `activatedAt = DateTime.now()` and, when `staticData.lastMessageUid` is unset, `node.typeVersion > 2`, and `options.trackLastMessageId !== false`, it appends a `SINCE` search criterion formatted with `activatedAt.toFormat('dd-LLL-yyyy')`. The underlying `imap` package then rejected the search criterion.

Current local trigger parameters observed on 2026-06-08:

```json
{
  "mailbox": "INBOX",
  "postProcessAction": "nothing",
  "format": "simple",
  "downloadAttachments": false,
  "options": {
    "trackLastMessageId": true,
    "allowUnauthorizedCerts": true
  }
}
```

Proposed but not yet applied in the local main checkout:

- set `Email Trigger (IMAP)` `options.trackLastMessageId=false` to avoid the first-activation `SINCE` path;
- add a trigger-side guard to skip messages already present in `Labels/Classified`, because disabling trigger UID tracking may emit old unread messages;
- remove `Manual Trigger` and keep `Backfill Form Trigger` if the user still wants that simplification.

Use ctx7 for current n8n docs before changing this node because n8n node behavior may have changed.

## Step Telemetry And Status Dashboard

Related repo:

- local: `/home/eric/source/n8n-workflow-status`
- GitHub: `https://github.com/ebrearley/n8n-workflow-status`
- app URL: `https://n8n-workflow-status.home.brearley.net`
- Coolify app UUID: `hpuhcco92fb6xgqjnwd8mcvt`
- latest deployed commit observed: `74a92738993c95fd55871faf2b8c715d51d5a80f`

The status app is private behind Pangolin/firewall and intentionally has no built-in auth.

The telemetry database is separate from n8n's main database but lives in the same Postgres engine:

- database: `workflow_status`
- app role: `workflow_status_app`
- migration marker table: `schema_migrations`

The step telemetry branch in this repo writes:

- workflow runs;
- email items;
- AI classification attempts;
- label actions;
- workflow steps with sanitized input/output/error JSON.

Step telemetry stages:

- `Start run` sort `10`
- `Configure batch` sort `20`
- `Fetch next unclassified emails` sort `30`
- `Expand fetched emails` sort `40`
- `Build classification prompt` sort `50`
- `Classify with Ollama` sort `60`
- `Prepare Proton label targets` sort `70`
- `Apply Proton labels` sort `80`
- `Apply Proton labels (trigger)` sort `85`
- `Finish run` sort `100`

Generated step telemetry nodes follow this naming pattern:

- `Telemetry start step: <stage>`
- `Telemetry record step: <stage>`
- `Telemetry restore step start: <stage>`
- `Telemetry finish step: <stage>`
- `Telemetry update step: <stage>`
- `Telemetry restore step finish: <stage>`

Important implementation constraints from prior review:

- n8n Postgres nodes on n8n `2.23.x` must use `options.queryReplacement`, not `queryParameters`.
- Step telemetry Postgres nodes should fail closed while debugging.
- Step update SQL intentionally fails if no row is updated.
- Restore nodes must restore original n8n items by source index; do not use SQL-returned payload JSON as the workflow payload.
- Generated start nodes must overwrite stale `telemetry_step_name`, `telemetry_step_type`, and `telemetry_step_sort_order` fields.
- Generated finish nodes recover `telemetry_step_id` from matching restore-start nodes for stages that replace or fan out items.
- The generator rejects multi-output stage targets.
- Sanitization must avoid full `email_body`, full raw content, full prompts, credentials, and secret-looking fields.
- Body previews in step telemetry are capped to 500 characters.

The dashboard derives `currentStep` from `workflow_steps` and shows current/final/failed step input, output, and error JSON. It also shows global token totals and per-run model/token usage.

## Importing Live Workflow Safely

Before importing, make a copy of the intended workflow JSON and inject live IDs/credential refs. Do not edit secrets into the committed file.

Known successful import pattern:

1. Set the workflow JSON `id` to `fm6pLPnZWsGfK1oH`.
2. Set `active` to `false` in the import JSON.
3. Inject credential references:
   - `Email Trigger (IMAP)` gets IMAP credential id `8dnbMcRYZzmpdI9B`, name `eric@brearley.net`.
   - `Ollama Chat Model` gets Ollama credential id `aR1KuRnGv6tTTkQ8`, name `Ollama account`.
   - all Postgres telemetry nodes get credential id `wspg_a409ed51b8f18c5e`, name `Workflow Status Postgres`.
4. Copy the import JSON into the n8n container.
5. Import and publish:

```bash
docker exec n8n-ew4sow0ws8kggowogk4owk4c n8n import:workflow --input=/tmp/email-organiser-import.json --projectId=VYxWLhVfItgsWnnA
docker exec n8n-ew4sow0ws8kggowogk4owk4c n8n publish:workflow --id=fm6pLPnZWsGfK1oH
docker exec n8n-ew4sow0ws8kggowogk4owk4c n8n update:workflow --id=fm6pLPnZWsGfK1oH --active=false
```

6. Restart n8n because the CLI warns that imports may not affect a running instance until restart:

```bash
docker restart n8n-ew4sow0ws8kggowogk4owk4c
```

7. Wait for healthy:

```bash
docker inspect --format "{{.State.Health.Status}}" n8n-ew4sow0ws8kggowogk4owk4c
```

The `update:workflow` command is deprecated in n8n but worked during setup. If current docs show a replacement such as `unpublish:workflow`, prefer current official behavior after checking ctx7.

## Live Validation Without Leaking Email Content

For a capped setup run, import a temporary copy with:

- `batchLimit=1`
- `maxBatches=1`
- workflow inactive after import

Then execute once:

```bash
docker exec -e N8N_RUNNERS_BROKER_PORT=5681 -e N8N_RUNNERS_TASK_REQUEST_TIMEOUT=240 n8n-ew4sow0ws8kggowogk4owk4c n8n execute --id=fm6pLPnZWsGfK1oH
```

Do not paste the CLI output back to the user. It can include private email data. Instead query `workflow_status` for sanitized verification.

Query the telemetry DB from the Coolify host:

```bash
ssh ubuntu@192.168.3.200 'docker exec postgresql-ew4sow0ws8kggowogk4owk4c sh -lc '\''psql -U "$POSTGRES_USER" -d workflow_status -c "select id, workflow_name, status, total_emails, total_estimated_tokens from workflow_runs order by started_at desc limit 5;"'\'''
```

Observed safe validation summary from the capped run:

- execution id: `54`
- run id: `3276939b-659e-494e-8a8d-0af412ff6106`
- status: `success`
- total emails: `1`
- total estimated tokens: `1593`
- step rows: `10`
- running steps after completion: `0`
- error steps: `0`

Do not add email subject/body details to docs or responses.

## Local Development Commands

From `/home/eric/source/n8n-flows`:

```bash
python3 -m unittest discover -s email-classifer/tests
git diff --check
```

When working on the step-telemetry branch/worktree:

```bash
cd /home/eric/source/n8n-flows/.worktrees/workflow-telemetry-status
python3 email-classifer/tools/sync_code_nodes.py
python3 email-classifer/tools/add_step_telemetry.py
python3 -m unittest discover -s email-classifer/tests
git diff --check
```

Compile Code-node source files with Node when editing JavaScript:

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

## Adding Or Iterating A Flow

Use this checklist for new workflows in this repo:

1. Create a dedicated directory under the repo root.
2. Keep an importable `workflow.json`.
3. Put reusable n8n Code-node source in `code-nodes/`.
4. Add tests that assert node types, critical node parameters, credential placeholders, and safety behavior.
5. Avoid unsupported/custom n8n node types unless the live n8n instance actually has them installed.
6. Avoid `n8n-nodes-base.executeCommand`; it was not installed in the live n8n and caused `Unrecognized node type` errors.
7. Prefer first-party n8n nodes plus JavaScript Code nodes for logic that must run inside n8n.
8. Keep live credentials out of committed workflow files; inject credential IDs/names into temporary import JSON when needed.
9. If the flow writes telemetry, use the existing `workflow_status` database and status app shape where practical.
10. Add a context doc under `docs/superpowers/context/` with live IDs, deployment notes, and safety constraints.

## Closely Related n8n-workflow-status Repo

`n8n-workflow-status` is the operational dashboard for this repo's n8n flows. A fresh agent working on either repo should read both root `AGENTS.md` files.

Status app highlights:

- local path: `/home/eric/source/n8n-workflow-status`
- URL: `https://n8n-workflow-status.home.brearley.net`
- stack: Next.js App Router, React, Tailwind CSS 4, shadcn/ui, PostgreSQL
- no built-in auth, private access via Pangolin/firewall
- reads `workflow_status` Postgres
- enriches workflow metadata through n8n API using server-side `N8N_API_KEY`
- shows workflow list, global token totals, run history, current step, step input/output/error JSON, email rows, AI attempts, label actions, and errors

Current deployed commit observed:

```text
74a92738993c95fd55871faf2b8c715d51d5a80f fix: select current step by start time
```

Status app verification commands are in `/home/eric/source/n8n-workflow-status/AGENTS.md` and `docs/deploy/coolify.md`.
