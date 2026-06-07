# Workflow Telemetry And Status App Design

Date: 2026-06-07

## Scope

Build a generic workflow telemetry system with `Email Organiser` as the first instrumented workflow, plus a read-only Next.js dashboard deployed as a separate Coolify application.

This work has four coordinated parts:

- a separate Postgres database and user on the existing Coolify Postgres engine;
- n8n workflow instrumentation for durable state, audit history, AI usage, and structured logs;
- Grafana Alloy/Loki investigation and updates so n8n logs appear in Grafana;
- a new private GitHub repository and Coolify app named `n8n-workflow-status`.

The dashboard is private-network only and does not implement app-level authentication.

## Architecture

The existing `n8n-flows` repo remains the source for workflow definitions and n8n instrumentation code.

A separate repo, `n8n-workflow-status`, will contain the dashboard application. It will live locally at:

```text
~/source/n8n-workflow-status
```

The GitHub repo will be private:

```text
ebrearley/n8n-workflow-status
```

The app will be deployed into the existing Coolify project/environment:

```text
https://coolify.home.brearley.net/project/tk7pb9r1a5cqvhth6kiot9e4/environment/auw9n2ov1ix59da3h3dcbvgt
```

The public hostname inside the private network will be:

```text
n8n-workflow-status.home.brearley.net
```

Data stores and observability systems have separate jobs:

- Postgres stores durable workflow state, detailed audit history, raw email content, prompts, AI responses, errors, timings, labels, and token usage.
- Loki stores short-lived structured runtime logs, including n8n and workflow-level events.
- Prometheus/Grafana continue to provide service and infrastructure visibility. No Pushgateway will be added for v1.
- The status app reads Postgres through server-side routes and uses the n8n API for workflow metadata enrichment.

## Postgres

Use the existing Coolify Postgres engine that is already configured alongside n8n, but create a separate database and user rather than writing into n8n's internal tables.

Recommended names:

```text
database: workflow_status
user: workflow_status_app
```

The new app receives its connection string through environment variables. The n8n workflow uses an n8n Postgres credential so workflow Code nodes do not receive database credentials directly. No database credentials are stored in git.

Expected app environment variable:

```bash
DATABASE_URL=postgres://workflow_status_app:<password>@<host>:5432/workflow_status
```

The n8n credential is named `Workflow Status Postgres`.

## Runtime Refinement

The stock n8n container does not include the `pg` Node package, so workflow telemetry writes will use first-party n8n Postgres nodes rather than direct database clients inside Code nodes.

The n8n service still needs database connection details, but they will be configured as an n8n Postgres credential named `Workflow Status Postgres`. Code nodes will prepare telemetry payloads and query parameters; Postgres nodes will execute the writes. This keeps the deployment on the stock n8n image.

## Database Model

The schema is generic for multiple workflows, with `Email Organiser` as the first source of telemetry.

Core tables:

- `workflows`
  Stores workflow identity and n8n metadata: n8n workflow ID, name, active flag, first seen time, last seen time, and the latest n8n API metadata JSON retrieved by the status app.

- `workflow_runs`
  Stores one row per run/execution/backfill/trigger event. Fields include workflow ID, n8n execution ID, trigger mode, status, started time, stopped time, duration, error summary, total emails, total tokens, and total estimated tokens.

- `workflow_steps`
  Stores logical step records. Fields include run ID, step name, step type, status, started time, stopped time, duration, input JSON, output JSON, error JSON, and sort order.

- `email_items`
  Stores emails encountered by workflows. Fields include account ID, source mailbox, UIDVALIDITY when available, UID, Message-ID, headers JSON, full raw content, body text, sender, recipient, subject, classified status, and timestamps.

- `classification_attempts`
  Stores AI call details. Fields include run ID, step ID, email item ID, model, prompt, raw response, parsed JSON, label JSON, reported prompt tokens, reported completion tokens, estimated prompt tokens, estimated completion tokens, token estimate flag, latency, status, and error JSON.

- `label_actions`
  Stores every attempted label application. Fields include run ID, step ID, email item ID, target mailbox, action status, IMAP UID, recipient/to fields for debugging, and error JSON.

- `workflow_events`
  Stores generic timeline events for UI and diagnostics. Fields include workflow ID, run ID, step ID, event type, severity, message, payload JSON, and timestamp.

Retention:

- compact current-state records can remain indefinitely;
- detailed DB records are retained for 30 days;
- Loki logs are retained for 7 days.

Cleanup runs through an explicit scheduled n8n workflow so pruning behavior is visible in n8n.

## Email Organiser Instrumentation

The workflow behavior remains:

- fetch emails from IMAP;
- classify using the local Ollama-backed n8n AI node;
- apply Proton labels by copying messages to `Labels/<label>`;
- apply `Labels/Classified` to every processed email;
- continue on `uncertain` by applying only `Labels/Classified`.

Instrumentation adds durable telemetry around that behavior.

Run-level instrumentation:

- insert or update `workflows`;
- create a `workflow_runs` row at start;
- update `workflow_runs` on finish or error;
- store run mode such as `manual_backfill`, `imap_trigger`, or later `scheduled`.

Email fetch instrumentation:

- upsert `email_items` for every fetched email;
- store full raw content, headers, body, sender, recipient, subject, account ID, mailbox, UID, and Message-ID;
- skip emails when DB state says they are already processed;
- if DB state is missing, fall back to checking Proton's `Labels/Classified` mailbox for migration safety.

Step instrumentation:

- record logical steps for configure, fetch batch, normalize trigger, build prompt, classify, parse classification, prepare labels, apply labels, and finish batch;
- store input/output/error JSON for each step where feasible;
- record timestamps and durations.

AI telemetry:

- store model name, prompt, raw response, parsed labels, duration, and token usage;
- use reported token counts when n8n/Ollama provides them;
- estimate token counts when reported counts are unavailable and mark them as estimated.

Label telemetry:

- store every attempted `Labels/<label>` and `Labels/Classified` copy;
- record successful copies, missing-label skips, IMAP errors, recipient/to fields, and source mailbox.

Failure policy during setup:

- DB connection and schema errors should stop the workflow so failures are visible;
- after the system is stable, degraded logs-only operation can be designed separately.

## Structured Logs

Workflow Code nodes should emit structured JSON logs for major events. Postgres remains the primary detailed record, but Loki should have enough detail for short-term operational debugging.

Common log fields:

```json
{
  "service": "n8n",
  "workflow_id": "fm6pLPnZWsGfK1oH",
  "workflow_name": "Email Organiser",
  "run_id": "...",
  "execution_id": "...",
  "step": "classify",
  "status": "success",
  "account_id": "imap-1",
  "mailbox": "INBOX",
  "message_id": "<...>",
  "subject": "...",
  "error": null
}
```

Because full detail is explicitly allowed for this private system, logs may include email content, prompts, and model responses. Retention is limited to 7 days in Loki.

## Alloy, Loki, And Prometheus

Grafana Alloy configuration lives on the Coolify host:

```text
ssh ubuntu@192.168.3.200:/var/app-data/o11y/grafana-alloy/config
```

The observability work starts with investigation, then config changes.

Investigation:

- inspect Docker discovery;
- inspect log scrape targets;
- inspect relabeling rules;
- inspect Loki write endpoint;
- inspect Prometheus scrape/export settings;
- confirm whether `n8n-ew4sow0ws8kggowogk4owk4c` is discovered;
- confirm whether Coolify one-click service containers are filtered out;
- confirm whether logs reach Loki under labels that Grafana queries do not currently show.

Expected n8n log labels after update:

```text
service="n8n"
container="n8n-ew4sow0ws8kggowogk4owk4c"
coolify_service="n8n"
```

Structured workflow logs can add workflow labels through parsed payload fields where Alloy/Loki configuration supports it without high-cardinality label explosions. Full content should stay in log bodies, not labels.

Prometheus v1 behavior:

- do not add Pushgateway;
- keep existing service/container metrics;
- leave n8n-specific Prometheus metrics unchanged unless the current n8n deployment already exposes them.

Validation:

- query n8n container logs in Grafana/Loki;
- query structured workflow logs;
- verify other service logs still appear;
- document working LogQL examples.

## Status App

The `n8n-workflow-status` app is read-only for v1.

Tech stack:

- Next.js App Router;
- TypeScript;
- Tailwind CSS;
- shadcn/ui;
- server-side Postgres access;
- n8n API enrichment from server routes;
- short polling every 2-5 seconds.

No browser-side code receives database credentials or n8n API keys.

Required environment variables:

```bash
DATABASE_URL=postgres://workflow_status_app:<password>@<host>:5432/workflow_status
N8N_BASE_URL=https://n8n.home.ericbrearley.com
N8N_API_KEY=<secret>
POLL_INTERVAL_MS=3000
```

The n8n API key belongs in the Coolify environment variables for the `n8n-workflow-status` app. It must not be committed, and it must not use a `NEXT_PUBLIC_` prefix.

Main UI:

- left sidebar with known workflows from Postgres, enriched with n8n API metadata when available;
- global overview with running workflows, recent failures, total tokens, token totals by model, run counts, and average duration;
- focused workflow page with current/latest run, run history, duration, step timeline, selected step detail, input/output/error JSON, email details, AI details, and label actions.

Focused workflow details:

- run status and duration;
- run history table;
- step timeline with status and timing;
- selected step panel showing inputs, outputs, and errors;
- email panel showing sender, recipient, subject, raw content, headers, and body;
- AI panel showing model, prompt, raw response, parsed labels, token usage, and whether tokens were estimated;
- label action panel showing attempted mailboxes, successes, missing labels, and failures.

Polling:

- sidebar and focused run refresh every configured interval;
- v1 does not use WebSockets or Server-Sent Events.

Authentication:

- no app-level authentication;
- the app assumes access is limited by the private network, Pangolin reverse proxy, and firewall.

## n8n API Enrichment

Postgres telemetry is the primary workflow list. The n8n API enriches workflow names, active status, and links back to n8n.

If the n8n API is unavailable, the app still works from Postgres data and marks enrichment as unavailable.

## Rollout

Implementation should proceed in phases:

1. Create the separate Postgres database/user/schema.
2. Add migration files and schema tests.
3. Add Postgres writer code to `n8n-flows`.
4. Instrument run start, fetch, and finish first.
5. Verify DB writes with a deliberately capped run.
6. Add classification, label, and error telemetry.
7. Investigate and fix Alloy scraping for n8n logs.
8. Scaffold `n8n-workflow-status`.
9. Deploy the status app to Coolify.
10. Wire dashboard routes and UI to Postgres and n8n API.
11. Switch Email Organiser skipping to DB-primary with `Labels/Classified` fallback.

## Safety

- Do not store secrets in git.
- Do not modify n8n internal DB tables.
- Do not drop or recreate user data tables without explicit approval.
- Use a separate database/user for workflow telemetry.
- Full raw email content, prompts, and model outputs are intentionally stored.
- Detailed DB retention is 30 days.
- Loki retention is 7 days.
- Keep the app read-only for v1.
- Avoid Pushgateway for v1.
- During setup, workflow instrumentation failures should stop the workflow so missing telemetry does not go unnoticed.

## Implementation Defaults

Use plain SQL migrations stored in the `n8n-workflow-status` repository under `db/migrations/`, executed by a small Node.js migration script that uses the same `DATABASE_URL` as the app.

Use a scheduled n8n workflow for the 30-day Postgres retention cleanup.

Estimate tokens with a simple `Math.ceil(characterCount / 4)` heuristic when usage is not reported by n8n/Ollama. Store estimated values separately from reported values and mark `estimated_tokens=true`.

Use shadcn/ui `Sidebar`, `Card`, `Table`, `Tabs`, `Badge`, `ScrollArea`, `Sheet`, `Separator`, and `Button` components for the first dashboard layout.

Add LogQL examples to the repository documentation after the Alloy configuration is inspected and the actual Loki label set is verified.
