# Workflow Telemetry Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build durable n8n workflow telemetry, a read-only Next.js status dashboard, and private Coolify deployment for `n8n-workflow-status`.

**Architecture:** n8n writes workflow telemetry into a separate Postgres database using first-party Postgres nodes, because the stock n8n container does not include the `pg` package for Code nodes. The Next.js App Router dashboard reads the telemetry database through server-side code and enriches workflow metadata with the n8n API. Grafana Alloy normalizes Docker log labels so n8n logs are queryable in Loki as `service="n8n"`.

**Tech Stack:** n8n workflow JSON, n8n Code nodes, n8n Postgres nodes, PostgreSQL, Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui, Coolify CLI, Grafana Alloy, Loki.

---

## Runtime Findings

- The remote n8n container is `n8n-ew4sow0ws8kggowogk4owk4c`.
- The stock container does not have `pg` installed:

```bash
ssh ubuntu@192.168.3.200 "docker exec n8n-ew4sow0ws8kggowogk4owk4c node -e \"try { require('pg'); console.log('pg available'); } catch (error) { console.log('pg unavailable:', error.message); process.exit(2); }\""
```

Expected current output:

```text
pg unavailable: Cannot find module 'pg'
```

- Use n8n Postgres nodes for database writes. Do not build a custom n8n image for v1.
- n8n Postgres docs support `Execute Query`, query batching, transactions, and query parameters.
- Current Alloy `logs.alloy` discovers Docker logs but labels `service` as `<host>/<container>`. The n8n Docker labels include `coolify.serviceName=n8n` and `com.docker.compose.service=n8n`, so normalize Coolify containers to service names.

## File Structure

### Existing Repo: `/home/eric/source/n8n-flows`

- Modify: `docs/superpowers/specs/2026-06-07-workflow-telemetry-status-design.md`
  Record the runtime refinement from Code-node `pg` writes to n8n Postgres-node writes.
- Create: `email-classifer/code-nodes/telemetry_start_run.js`
  Build the start-run telemetry item and structured log.
- Create: `email-classifer/code-nodes/telemetry_build_email_items.js`
  Convert fetched email items into DB-ready records without changing classifier payloads.
- Create: `email-classifer/code-nodes/telemetry_build_classification_attempt.js`
  Build AI telemetry records from the classifier input/output.
- Create: `email-classifer/code-nodes/telemetry_build_label_actions.js`
  Build label-action telemetry records from IMAP label application results.
- Create: `email-classifer/code-nodes/telemetry_finish_run.js`
  Build run-finish telemetry and structured log records.
- Create: `email-classifer/tools/sync_code_nodes.py`
  Copy Code-node source files into `workflow.json` and `workflow-imap-trigger.json`.
- Modify: `email-classifer/workflow.json`
  Add telemetry Code nodes and Postgres nodes around the existing workflow.
- Modify: `email-classifer/workflow-imap-trigger.json`
  Keep the compatibility export in sync with `workflow.json`.
- Modify: `email-classifer/tests/test_workflow_json.py`
  Assert telemetry nodes exist, use supported node types, stop on errors, and keep `Classified` behavior.

### New Repo: `/home/eric/source/n8n-workflow-status`

- Create: `db/migrations/0001_init.sql`
  Create the telemetry schema.
- Create: `scripts/migrate.mjs`
  Apply SQL migrations using `DATABASE_URL`.
- Create: `scripts/validate-migrations.mjs`
  Validate migration ordering and required tables.
- Create: `src/lib/env.ts`
  Validate server-side environment variables.
- Create: `src/lib/db.ts`
  Provide a singleton Postgres pool.
- Create: `src/lib/repositories/dashboard.ts`
  Query global dashboard data and workflow summaries.
- Create: `src/lib/repositories/workflows.ts`
  Query focused workflow, run, step, email, classification, and label-action details.
- Create: `src/lib/n8n.ts`
  Fetch n8n workflow metadata using `N8N_BASE_URL` and `N8N_API_KEY`.
- Create: `src/app/api/overview/route.ts`
  Return global dashboard metrics.
- Create: `src/app/api/workflows/route.ts`
  Return workflow list.
- Create: `src/app/api/workflows/[workflowId]/route.ts`
  Return focused workflow detail.
- Create: `src/app/page.tsx`
  Render the dashboard shell.
- Create: `src/components/dashboard-shell.tsx`
  Manage polling and selected workflow state.
- Create: `src/components/workflow-sidebar.tsx`
  Render the workflow list.
- Create: `src/components/global-overview.tsx`
  Render run and token totals.
- Create: `src/components/workflow-detail.tsx`
  Render run history, timeline, inputs, outputs, errors, email data, AI data, and label actions.
- Create: `docs/deploy/coolify.md`
  Document private Coolify deployment and environment variables.
- Create: `docs/observability/loki-logql.md`
  Document verified Loki queries.

---

### Task 1: Record The Postgres-Node Refinement

**Files:**
- Modify: `docs/superpowers/specs/2026-06-07-workflow-telemetry-status-design.md`

- [ ] **Step 1: Add a runtime refinement note**

Add this section after `## Postgres`:

```markdown
## Runtime Refinement

The stock n8n container does not include the `pg` Node package, so workflow telemetry writes will use first-party n8n Postgres nodes rather than direct database clients inside Code nodes.

The n8n service still needs database connection details, but they will be configured as an n8n Postgres credential named `Workflow Status Postgres`. Code nodes will prepare telemetry payloads and query parameters; Postgres nodes will execute the writes. This keeps the deployment on the stock n8n image.
```

- [ ] **Step 2: Run the spec check**

Run:

```bash
python3 -c 'from pathlib import Path; text = Path("docs/superpowers/specs/2026-06-07-workflow-telemetry-status-design.md").read_text(); checks = ["TB" + "D", "TO" + "DO", "implement " + "later", "fill " + "in"]; hits = [word for word in checks if word in text]; raise SystemExit("scan hits: " + ", ".join(hits) if hits else 0)'
git diff --check -- docs/superpowers/specs/2026-06-07-workflow-telemetry-status-design.md
```

Expected: both commands exit `0`.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-07-workflow-telemetry-status-design.md
git commit -m "docs: record telemetry postgres node refinement"
```

### Task 2: Scaffold The Status App Repository

**Files:**
- Create repo: `/home/eric/source/n8n-workflow-status`

- [ ] **Step 1: Create the Next.js app**

Run:

```bash
cd /home/eric/source
npx create-next-app@latest n8n-workflow-status --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm --yes
cd /home/eric/source/n8n-workflow-status
```

Expected: `package.json`, `src/app/page.tsx`, `src/app/layout.tsx`, and Tailwind files exist.

- [ ] **Step 2: Install runtime and test dependencies**

Run:

```bash
npm install pg zod lucide-react
npm install -D @types/pg tsx vitest
```

Expected: `package-lock.json` records the dependencies.

- [ ] **Step 3: Initialize shadcn/ui**

Run:

```bash
npx shadcn@latest init -d
npx shadcn@latest add sidebar card table tabs badge scroll-area sheet separator button
```

Expected: `src/components/ui/` contains the installed shadcn components.

- [ ] **Step 4: Initialize Git and private GitHub repo**

Run:

```bash
git init
git add .
git commit -m "feat: scaffold workflow status app"
gh repo create ebrearley/n8n-workflow-status --private --source=. --remote=origin
git push -u origin main
```

Expected: GitHub has private repo `ebrearley/n8n-workflow-status`, and `git remote -v` points to it.

### Task 3: Add Database Migrations

**Files:**
- Create: `/home/eric/source/n8n-workflow-status/db/migrations/0001_init.sql`
- Create: `/home/eric/source/n8n-workflow-status/scripts/validate-migrations.mjs`
- Create: `/home/eric/source/n8n-workflow-status/scripts/migrate.mjs`
- Modify: `/home/eric/source/n8n-workflow-status/package.json`

- [ ] **Step 1: Create the initial schema**

Create `db/migrations/0001_init.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS workflows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  n8n_workflow_id text NOT NULL UNIQUE,
  name text NOT NULL,
  active boolean NOT NULL DEFAULT false,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workflow_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id uuid NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  n8n_execution_id text,
  trigger_mode text NOT NULL,
  status text NOT NULL CHECK (status IN ('running', 'success', 'error', 'cancelled')),
  started_at timestamptz NOT NULL DEFAULT now(),
  stopped_at timestamptz,
  duration_ms integer,
  error_summary text,
  total_emails integer NOT NULL DEFAULT 0,
  total_tokens integer NOT NULL DEFAULT 0,
  total_estimated_tokens integer NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS workflow_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
  name text NOT NULL,
  type text NOT NULL,
  status text NOT NULL CHECK (status IN ('running', 'success', 'error', 'skipped')),
  sort_order integer NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  stopped_at timestamptz,
  duration_ms integer,
  input_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  output_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  error_json jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id text NOT NULL,
  source_mailbox text NOT NULL,
  uidvalidity text NOT NULL DEFAULT '',
  uid text NOT NULL,
  message_id text NOT NULL DEFAULT '',
  headers_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  raw_content text NOT NULL DEFAULT '',
  body_text text NOT NULL DEFAULT '',
  sender_email text NOT NULL DEFAULT '',
  sender_name text NOT NULL DEFAULT '',
  recipient_email text NOT NULL DEFAULT '',
  recipient_name text NOT NULL DEFAULT '',
  subject text NOT NULL DEFAULT '',
  classified_status text NOT NULL DEFAULT 'unclassified',
  first_seen_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  classified_at timestamptz,
  UNIQUE (account_id, source_mailbox, uidvalidity, uid)
);

CREATE TABLE IF NOT EXISTS classification_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
  step_id uuid REFERENCES workflow_steps(id) ON DELETE SET NULL,
  email_item_id uuid REFERENCES email_items(id) ON DELETE SET NULL,
  model text NOT NULL,
  prompt text NOT NULL,
  raw_response text NOT NULL DEFAULT '',
  parsed_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  labels_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  reported_prompt_tokens integer,
  reported_completion_tokens integer,
  estimated_prompt_tokens integer NOT NULL DEFAULT 0,
  estimated_completion_tokens integer NOT NULL DEFAULT 0,
  estimated_tokens boolean NOT NULL DEFAULT true,
  latency_ms integer,
  status text NOT NULL CHECK (status IN ('success', 'error', 'uncertain')),
  error_json jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS label_actions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
  step_id uuid REFERENCES workflow_steps(id) ON DELETE SET NULL,
  email_item_id uuid REFERENCES email_items(id) ON DELETE SET NULL,
  target_mailbox text NOT NULL,
  action_status text NOT NULL CHECK (action_status IN ('success', 'skipped_missing_mailbox', 'error')),
  imap_uid text NOT NULL DEFAULT '',
  recipient_email text NOT NULL DEFAULT '',
  recipient_name text NOT NULL DEFAULT '',
  error_json jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS workflow_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id uuid REFERENCES workflows(id) ON DELETE CASCADE,
  run_id uuid REFERENCES workflow_runs(id) ON DELETE CASCADE,
  step_id uuid REFERENCES workflow_steps(id) ON DELETE SET NULL,
  event_type text NOT NULL,
  severity text NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
  message text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS workflow_runs_started_at_idx ON workflow_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS workflow_steps_run_sort_idx ON workflow_steps (run_id, sort_order);
CREATE INDEX IF NOT EXISTS email_items_status_idx ON email_items (classified_status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS classification_attempts_run_idx ON classification_attempts (run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS label_actions_run_idx ON label_actions (run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS workflow_events_run_idx ON workflow_events (run_id, created_at DESC);
```

- [ ] **Step 2: Add migration validation**

Create `scripts/validate-migrations.mjs`:

```js
import fs from 'node:fs';
import path from 'node:path';

const dir = path.join(process.cwd(), 'db', 'migrations');
const files = fs.readdirSync(dir).filter((file) => file.endsWith('.sql')).sort();

if (files.length === 0) throw new Error('No SQL migrations found');
if (files[0] !== '0001_init.sql') throw new Error(`First migration was ${files[0]}`);

const sql = fs.readFileSync(path.join(dir, '0001_init.sql'), 'utf8');
for (const table of [
  'workflows',
  'workflow_runs',
  'workflow_steps',
  'email_items',
  'classification_attempts',
  'label_actions',
  'workflow_events',
]) {
  if (!sql.includes(`CREATE TABLE IF NOT EXISTS ${table}`)) {
    throw new Error(`Missing table ${table}`);
  }
}

console.log(`Validated ${files.length} migration file(s)`);
```

- [ ] **Step 3: Add migration runner**

Create `scripts/migrate.mjs`:

```js
import fs from 'node:fs/promises';
import path from 'node:path';
import pg from 'pg';

const { Client } = pg;
const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) throw new Error('DATABASE_URL is required');

const client = new Client({ connectionString: databaseUrl });
await client.connect();

try {
  await client.query(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      filename text PRIMARY KEY,
      applied_at timestamptz NOT NULL DEFAULT now()
    )
  `);

  const dir = path.join(process.cwd(), 'db', 'migrations');
  const files = (await fs.readdir(dir)).filter((file) => file.endsWith('.sql')).sort();

  for (const file of files) {
    const seen = await client.query('SELECT 1 FROM schema_migrations WHERE filename = $1', [file]);
    if (seen.rowCount) continue;
    const sql = await fs.readFile(path.join(dir, file), 'utf8');
    await client.query('BEGIN');
    await client.query(sql);
    await client.query('INSERT INTO schema_migrations (filename) VALUES ($1)', [file]);
    await client.query('COMMIT');
    console.log(`Applied ${file}`);
  }
} catch (error) {
  await client.query('ROLLBACK').catch(() => {});
  throw error;
} finally {
  await client.end();
}
```

- [ ] **Step 4: Add package scripts**

Update `package.json` scripts:

```json
{
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "test": "vitest run",
    "db:validate": "node scripts/validate-migrations.mjs",
    "db:migrate": "node scripts/migrate.mjs"
  }
}
```

- [ ] **Step 5: Verify and commit**

Run:

```bash
npm run db:validate
npm run lint
git add db scripts package.json package-lock.json
git commit -m "feat: add workflow telemetry schema"
```

Expected: migration validation exits `0`, lint exits `0`, commit succeeds.

### Task 4: Build Server Data Access

**Files:**
- Create: `/home/eric/source/n8n-workflow-status/src/lib/env.ts`
- Create: `/home/eric/source/n8n-workflow-status/src/lib/db.ts`
- Create: `/home/eric/source/n8n-workflow-status/src/lib/repositories/dashboard.ts`
- Create: `/home/eric/source/n8n-workflow-status/src/lib/repositories/workflows.ts`
- Create: `/home/eric/source/n8n-workflow-status/src/lib/n8n.ts`
- Create: `/home/eric/source/n8n-workflow-status/src/lib/repositories/dashboard.test.ts`

- [ ] **Step 1: Add env validation**

Create `src/lib/env.ts`:

```ts
import { z } from 'zod';

const schema = z.object({
  DATABASE_URL: z.string().min(1),
  N8N_BASE_URL: z.string().url(),
  N8N_API_KEY: z.string().min(1),
  POLL_INTERVAL_MS: z.coerce.number().int().min(1000).default(3000),
});

export const env = schema.parse({
  DATABASE_URL: process.env.DATABASE_URL,
  N8N_BASE_URL: process.env.N8N_BASE_URL,
  N8N_API_KEY: process.env.N8N_API_KEY,
  POLL_INTERVAL_MS: process.env.POLL_INTERVAL_MS,
});
```

- [ ] **Step 2: Add Postgres pool**

Create `src/lib/db.ts`:

```ts
import pg from 'pg';
import { env } from './env';

const { Pool } = pg;

const globalForPg = globalThis as unknown as {
  workflowStatusPool?: pg.Pool;
};

export const pool =
  globalForPg.workflowStatusPool ??
  new Pool({
    connectionString: env.DATABASE_URL,
    max: 8,
    idleTimeoutMillis: 30_000,
  });

if (process.env.NODE_ENV !== 'production') {
  globalForPg.workflowStatusPool = pool;
}
```

- [ ] **Step 3: Add dashboard repository**

Create `src/lib/repositories/dashboard.ts` with these exports:

```ts
import { pool } from '@/lib/db';

export type Overview = {
  runningRuns: number;
  recentFailures: number;
  totalRuns: number;
  totalTokens: number;
  estimatedTokens: number;
  averageDurationMs: number | null;
  tokensByModel: Array<{ model: string; tokens: number; estimatedTokens: number }>;
};

export async function getOverview(): Promise<Overview> {
  const [summary, models] = await Promise.all([
    pool.query(`
      SELECT
        count(*) FILTER (WHERE status = 'running')::int AS running_runs,
        count(*) FILTER (WHERE status = 'error' AND started_at > now() - interval '24 hours')::int AS recent_failures,
        count(*)::int AS total_runs,
        coalesce(sum(total_tokens), 0)::int AS total_tokens,
        coalesce(sum(total_estimated_tokens), 0)::int AS estimated_tokens,
        avg(duration_ms)::int AS average_duration_ms
      FROM workflow_runs
    `),
    pool.query(`
      SELECT
        model,
        coalesce(sum(coalesce(reported_prompt_tokens, 0) + coalesce(reported_completion_tokens, 0)), 0)::int AS tokens,
        coalesce(sum(estimated_prompt_tokens + estimated_completion_tokens), 0)::int AS estimated_tokens
      FROM classification_attempts
      GROUP BY model
      ORDER BY estimated_tokens DESC, tokens DESC
    `),
  ]);

  const row = summary.rows[0] ?? {};
  return {
    runningRuns: row.running_runs ?? 0,
    recentFailures: row.recent_failures ?? 0,
    totalRuns: row.total_runs ?? 0,
    totalTokens: row.total_tokens ?? 0,
    estimatedTokens: row.estimated_tokens ?? 0,
    averageDurationMs: row.average_duration_ms ?? null,
    tokensByModel: models.rows.map((model) => ({
      model: model.model,
      tokens: model.tokens,
      estimatedTokens: model.estimated_tokens,
    })),
  };
}
```

- [ ] **Step 4: Add workflow repository**

Create `src/lib/repositories/workflows.ts`:

```ts
import { pool } from '@/lib/db';

export async function listWorkflows() {
  const result = await pool.query(`
    SELECT
      w.n8n_workflow_id,
      w.name,
      w.active,
      w.last_seen_at,
      r.status AS latest_status,
      r.started_at AS latest_started_at,
      r.duration_ms AS latest_duration_ms
    FROM workflows w
    LEFT JOIN LATERAL (
      SELECT *
      FROM workflow_runs r
      WHERE r.workflow_id = w.id
      ORDER BY r.started_at DESC
      LIMIT 1
    ) r ON true
    ORDER BY w.name ASC
  `);
  return result.rows;
}

export async function getWorkflowDetail(n8nWorkflowId: string) {
  const workflow = await pool.query(
    'SELECT * FROM workflows WHERE n8n_workflow_id = $1',
    [n8nWorkflowId],
  );

  if (!workflow.rowCount) {
    return { workflow: null, runs: [], steps: [], emails: [], classifications: [], labels: [] };
  }

  const workflowId = workflow.rows[0].id;
  const runs = await pool.query(
    `SELECT * FROM workflow_runs WHERE workflow_id = $1 ORDER BY started_at DESC LIMIT 25`,
    [workflowId],
  );
  const latestRunId = runs.rows[0]?.id;

  if (!latestRunId) {
    return { workflow: workflow.rows[0], runs: [], steps: [], emails: [], classifications: [], labels: [] };
  }

  const [steps, classifications, labels, emails] = await Promise.all([
    pool.query(
      `SELECT * FROM workflow_steps WHERE run_id = $1 ORDER BY sort_order ASC, started_at ASC`,
      [latestRunId],
    ),
    pool.query(
      `SELECT * FROM classification_attempts WHERE run_id = $1 ORDER BY created_at DESC LIMIT 100`,
      [latestRunId],
    ),
    pool.query(
      `SELECT * FROM label_actions WHERE run_id = $1 ORDER BY created_at DESC LIMIT 200`,
      [latestRunId],
    ),
    pool.query(
      `SELECT DISTINCT e.*
       FROM email_items e
       JOIN classification_attempts c ON c.email_item_id = e.id
       WHERE c.run_id = $1
       ORDER BY e.last_seen_at DESC
       LIMIT 100`,
      [latestRunId],
    ),
  ]);

  return {
    workflow: workflow.rows[0],
    runs: runs.rows,
    steps: steps.rows,
    emails: emails.rows,
    classifications: classifications.rows,
    labels: labels.rows,
  };
}
```

- [ ] **Step 5: Add n8n enrichment client**

Create `src/lib/n8n.ts`:

```ts
import { env } from '@/lib/env';

export async function fetchN8nWorkflow(workflowId: string) {
  const url = new URL(`/api/v1/workflows/${workflowId}`, env.N8N_BASE_URL);
  const response = await fetch(url, {
    headers: { 'X-N8N-API-KEY': env.N8N_API_KEY },
    cache: 'no-store',
  });

  if (!response.ok) {
    return { available: false as const, status: response.status };
  }

  return { available: true as const, workflow: await response.json() };
}
```

- [ ] **Step 6: Add repository test**

Create `src/lib/repositories/dashboard.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { formatDuration, tokenDisplay } from './format';

describe('dashboard formatting', () => {
  it('formats duration in seconds', () => {
    expect(formatDuration(2750)).toBe('2.8s');
  });

  it('marks estimated token counts', () => {
    expect(tokenDisplay({ tokens: 0, estimatedTokens: 1200 })).toBe('~1,200');
  });
});
```

Add `src/lib/repositories/format.ts`:

```ts
export function formatDuration(durationMs: number | null) {
  if (durationMs === null) return 'running';
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

export function tokenDisplay(value: { tokens: number; estimatedTokens: number }) {
  if (value.tokens > 0) return value.tokens.toLocaleString();
  return `~${value.estimatedTokens.toLocaleString()}`;
}
```

- [ ] **Step 7: Verify and commit**

Run:

```bash
npm run test
npm run lint
npm run build
git add src package.json package-lock.json
git commit -m "feat: add telemetry data access"
```

Expected: tests, lint, and build exit `0`.

### Task 5: Build Dashboard API Routes And UI

**Files:**
- Create: `/home/eric/source/n8n-workflow-status/src/app/api/overview/route.ts`
- Create: `/home/eric/source/n8n-workflow-status/src/app/api/workflows/route.ts`
- Create: `/home/eric/source/n8n-workflow-status/src/app/api/workflows/[workflowId]/route.ts`
- Modify: `/home/eric/source/n8n-workflow-status/src/app/page.tsx`
- Create: `/home/eric/source/n8n-workflow-status/src/components/dashboard-shell.tsx`
- Create: `/home/eric/source/n8n-workflow-status/src/components/workflow-sidebar.tsx`
- Create: `/home/eric/source/n8n-workflow-status/src/components/global-overview.tsx`
- Create: `/home/eric/source/n8n-workflow-status/src/components/workflow-detail.tsx`

- [ ] **Step 1: Add API routes**

Create `src/app/api/overview/route.ts`:

```ts
import { NextResponse } from 'next/server';
import { getOverview } from '@/lib/repositories/dashboard';

export async function GET() {
  return NextResponse.json(await getOverview());
}
```

Create `src/app/api/workflows/route.ts`:

```ts
import { NextResponse } from 'next/server';
import { listWorkflows } from '@/lib/repositories/workflows';

export async function GET() {
  return NextResponse.json(await listWorkflows());
}
```

Create `src/app/api/workflows/[workflowId]/route.ts`:

```ts
import { NextResponse } from 'next/server';
import { getWorkflowDetail } from '@/lib/repositories/workflows';

export async function GET(
  _request: Request,
  context: { params: Promise<{ workflowId: string }> },
) {
  const { workflowId } = await context.params;
  return NextResponse.json(await getWorkflowDetail(workflowId));
}
```

- [ ] **Step 2: Add polling dashboard shell**

Create `src/components/dashboard-shell.tsx`:

```tsx
'use client';

import { useEffect, useMemo, useState } from 'react';
import { GlobalOverview } from '@/components/global-overview';
import { WorkflowDetail } from '@/components/workflow-detail';
import { WorkflowSidebar } from '@/components/workflow-sidebar';

const pollMs = Number(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS ?? 3000);

export function DashboardShell() {
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [overview, setOverview] = useState<any>(null);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>('');
  const [detail, setDetail] = useState<any>(null);

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      const [overviewResponse, workflowsResponse] = await Promise.all([
        fetch('/api/overview'),
        fetch('/api/workflows'),
      ]);
      if (cancelled) return;
      const nextWorkflows = await workflowsResponse.json();
      setOverview(await overviewResponse.json());
      setWorkflows(nextWorkflows);
      setSelectedWorkflowId((current) => current || nextWorkflows[0]?.n8n_workflow_id || '');
    }
    refresh();
    const id = window.setInterval(refresh, pollMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    if (!selectedWorkflowId) return;
    let cancelled = false;
    async function refreshDetail() {
      const response = await fetch(`/api/workflows/${encodeURIComponent(selectedWorkflowId)}`);
      if (!cancelled) setDetail(await response.json());
    }
    refreshDetail();
    const id = window.setInterval(refreshDetail, pollMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [selectedWorkflowId]);

  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.n8n_workflow_id === selectedWorkflowId),
    [workflows, selectedWorkflowId],
  );

  return (
    <div className="grid min-h-screen grid-cols-[280px_1fr] bg-background text-foreground">
      <WorkflowSidebar
        workflows={workflows}
        selectedWorkflowId={selectedWorkflowId}
        onSelectWorkflow={setSelectedWorkflowId}
      />
      <main className="min-w-0 space-y-4 p-4">
        <GlobalOverview overview={overview} />
        <WorkflowDetail workflow={selectedWorkflow} detail={detail} />
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Add dense operational components**

Create `src/components/workflow-sidebar.tsx`:

```tsx
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';

export function WorkflowSidebar({
  workflows,
  selectedWorkflowId,
  onSelectWorkflow,
}: {
  workflows: any[];
  selectedWorkflowId: string;
  onSelectWorkflow: (workflowId: string) => void;
}) {
  return (
    <aside className="border-r bg-muted/30">
      <div className="border-b p-4">
        <h1 className="text-base font-semibold">Workflow Status</h1>
      </div>
      <ScrollArea className="h-[calc(100vh-57px)]">
        <div className="space-y-1 p-2">
          {workflows.map((workflow) => (
            <Button
              key={workflow.n8n_workflow_id}
              variant={workflow.n8n_workflow_id === selectedWorkflowId ? 'secondary' : 'ghost'}
              className="h-auto w-full justify-start px-3 py-2"
              onClick={() => onSelectWorkflow(workflow.n8n_workflow_id)}
            >
              <span className="min-w-0 flex-1 truncate text-left">{workflow.name}</span>
              <Badge variant={workflow.latest_status === 'error' ? 'destructive' : 'outline'}>
                {workflow.latest_status || 'new'}
              </Badge>
            </Button>
          ))}
        </div>
      </ScrollArea>
    </aside>
  );
}
```

Create `src/components/global-overview.tsx`:

```tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export function GlobalOverview({ overview }: { overview: any }) {
  const cards = [
    ['Running', overview?.runningRuns ?? 0],
    ['Failures 24h', overview?.recentFailures ?? 0],
    ['Runs', overview?.totalRuns ?? 0],
    ['Tokens', overview ? `${overview.totalTokens.toLocaleString()} / ~${overview.estimatedTokens.toLocaleString()}` : '0'],
  ];

  return (
    <section className="grid grid-cols-4 gap-3">
      {cards.map(([label, value]) => (
        <Card key={label}>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-medium text-muted-foreground">{label}</CardTitle>
          </CardHeader>
          <CardContent className="text-2xl font-semibold">{value}</CardContent>
        </Card>
      ))}
    </section>
  );
}
```

Create `src/components/workflow-detail.tsx`:

```tsx
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

export function WorkflowDetail({ workflow, detail }: { workflow: any; detail: any }) {
  if (!workflow) return <Card><CardContent className="p-4">No workflow data yet.</CardContent></Card>;

  const tabs = ['Runs', 'Steps', 'Email', 'AI', 'Labels', 'Errors'] as const;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{workflow.name}</CardTitle>
        <Badge variant={workflow.latest_status === 'error' ? 'destructive' : 'outline'}>
          {workflow.latest_status || 'new'}
        </Badge>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="Runs">
          <TabsList>
            {tabs.map((tab) => <TabsTrigger key={tab} value={tab}>{tab}</TabsTrigger>)}
          </TabsList>
          {tabs.map((tab) => (
            <TabsContent key={tab} value={tab}>
              <ScrollArea className="h-[520px] rounded border p-3">
                <pre className="whitespace-pre-wrap text-xs">
                  {JSON.stringify(selectTabData(tab, detail), null, 2)}
                </pre>
              </ScrollArea>
            </TabsContent>
          ))}
        </Tabs>
      </CardContent>
    </Card>
  );
}

function selectTabData(tab: string, detail: any) {
  if (tab === 'Runs') return detail?.runs ?? [];
  if (tab === 'Steps') return detail?.steps ?? [];
  if (tab === 'Email') return detail?.emails ?? [];
  if (tab === 'AI') return detail?.classifications ?? [];
  if (tab === 'Labels') return detail?.labels ?? [];
  return {
    steps: (detail?.steps ?? []).filter((step: any) => step.status === 'error'),
    labels: (detail?.labels ?? []).filter((label: any) => label.action_status === 'error'),
    classifications: (detail?.classifications ?? []).filter((attempt: any) => attempt.status === 'error'),
  };
}
```

- [ ] **Step 4: Add server page**

Update `src/app/page.tsx`:

```tsx
import { DashboardShell } from '@/components/dashboard-shell';

export default function Page() {
  return <DashboardShell />;
}
```

- [ ] **Step 5: Verify and commit**

Run:

```bash
npm run test
npm run lint
npm run build
git add src
git commit -m "feat: add workflow status dashboard"
```

Expected: tests, lint, and build exit `0`.

### Task 6: Create The Telemetry Database In Coolify Postgres

**Files:**
- Create: `/home/eric/source/n8n-workflow-status/docs/deploy/coolify.md`

- [ ] **Step 1: Locate the existing n8n Postgres container**

Run:

```bash
ssh ubuntu@192.168.3.200 "docker ps --format '{{.Names}} {{.Image}}' | grep ew4sow0ws8kggowogk4owk4c"
```

Expected output includes:

```text
n8n-ew4sow0ws8kggowogk4owk4c docker.n8n.io/n8nio/n8n
postgresql-ew4sow0ws8kggowogk4owk4c postgres:16-alpine
```

- [ ] **Step 2: Create a password locally**

Run:

```bash
openssl rand -base64 36
```

Save the generated value only in your password manager, then load it into the current shell:

```bash
read -r -s WORKFLOW_STATUS_DB_PASSWORD
export WORKFLOW_STATUS_DB_PASSWORD
```

- [ ] **Step 3: Expose the existing Postgres service on a private host port**

Run:

```bash
coolify --context home database update qkg0wksswswoss4ggowkg00g --is-public --public-port 15432
coolify --context home database restart qkg0wksswswoss4ggowkg00g
ssh ubuntu@192.168.3.200 "docker port postgresql-ew4sow0ws8kggowogk4owk4c"
```

Expected: Docker shows `5432/tcp` mapped to host port `15432`. The host remains private-network/firewall protected.

- [ ] **Step 4: Create the DB and user on the existing Postgres engine**

Run:

```bash
ssh ubuntu@192.168.3.200 "docker exec -i postgresql-ew4sow0ws8kggowogk4owk4c sh -lc 'psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"'" <<SQL
SELECT 'CREATE DATABASE workflow_status'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'workflow_status')\gexec
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'workflow_status_app') THEN
    CREATE USER workflow_status_app WITH PASSWORD '${WORKFLOW_STATUS_DB_PASSWORD}';
  ELSE
    ALTER USER workflow_status_app WITH PASSWORD '${WORKFLOW_STATUS_DB_PASSWORD}';
  END IF;
END
\$\$;
GRANT ALL PRIVILEGES ON DATABASE workflow_status TO workflow_status_app;
\c workflow_status
GRANT ALL ON SCHEMA public TO workflow_status_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO workflow_status_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO workflow_status_app;
SQL
```

Expected: database/user creation or update succeeds, and `GRANT` statements succeed.

- [ ] **Step 5: Run migrations**

From `/home/eric/source/n8n-workflow-status`, run:

```bash
export DATABASE_URL="postgres://workflow_status_app:${WORKFLOW_STATUS_DB_PASSWORD}@192.168.3.200:15432/workflow_status"
npm run db:migrate
```

Expected: `Applied 0001_init.sql`.

- [ ] **Step 6: Write deployment docs**

Create `docs/deploy/coolify.md`:

```markdown
# Coolify Deployment

Project UUID: `tk7pb9r1a5cqvhth6kiot9e4`
Environment UUID: `auw9n2ov1ix59da3h3dcbvgt`
Server UUID: `tcogoww`
GitHub App UUID: `x4wg4oc`
GitHub App numeric ID for repo listing: `1`
n8n Postgres database resource UUID: `qkg0wksswswoss4ggowkg00g`
n8n Postgres container: `postgresql-ew4sow0ws8kggowogk4owk4c`
n8n Postgres private host port: `192.168.3.200:15432`

Application hostname: `n8n-workflow-status.home.brearley.net`

Environment variables:

- `DATABASE_URL`
- `N8N_BASE_URL=https://n8n.home.ericbrearley.com`
- `N8N_API_KEY`
- `POLL_INTERVAL_MS=3000`
- `NEXT_PUBLIC_POLL_INTERVAL_MS=3000`

The n8n API key is stored in the Coolify application environment only. It is not committed and it does not use a `NEXT_PUBLIC_` prefix.
```

- [ ] **Step 7: Commit**

```bash
git add docs/deploy/coolify.md
git commit -m "docs: add coolify deployment notes"
```

### Task 7: Add Workflow Telemetry Nodes

**Files:**
- Create: `email-classifer/code-nodes/telemetry_start_run.js`
- Create: `email-classifer/code-nodes/telemetry_build_email_items.js`
- Create: `email-classifer/code-nodes/telemetry_build_classification_attempt.js`
- Create: `email-classifer/code-nodes/telemetry_build_label_actions.js`
- Create: `email-classifer/code-nodes/telemetry_finish_run.js`
- Create: `email-classifer/tools/sync_code_nodes.py`
- Modify: `email-classifer/workflow.json`
- Modify: `email-classifer/workflow-imap-trigger.json`
- Modify: `email-classifer/tests/test_workflow_json.py`

- [ ] **Step 1: Add telemetry start Code-node source**

Create `email-classifer/code-nodes/telemetry_start_run.js`:

```js
const workflowId = 'fm6pLPnZWsGfK1oH';
const workflowName = 'Email Organiser';
const startedAt = new Date().toISOString();
const executionId = String($execution?.id || $json.execution_id || startedAt);
const triggerMode = $json.sourceFlow === 'trigger' ? 'imap_trigger' : 'manual_backfill';
const runKey = `${workflowId}:${executionId}:${triggerMode}`;

console.log(JSON.stringify({
  service: 'n8n',
  workflow_id: workflowId,
  workflow_name: workflowName,
  execution_id: executionId,
  run_key: runKey,
  step: 'telemetry_start_run',
  status: 'running',
  trigger_mode: triggerMode,
}));

return [{
  json: {
    ...$json,
    telemetry: {
      workflow_id: workflowId,
      workflow_name: workflowName,
      execution_id: executionId,
      trigger_mode: triggerMode,
      run_key: runKey,
      started_at: startedAt,
    },
  },
}];
```

- [ ] **Step 2: Add DB-ready email telemetry source**

Create `email-classifer/code-nodes/telemetry_build_email_items.js`:

```js
const telemetry = $json.telemetry || {};
const emails = Array.isArray($json.emails) ? $json.emails : [$json];

return emails.map((email) => ({
  json: {
    ...email,
    telemetry,
    email_telemetry_params: [
      email.credentialPairId || email.account_id || 'imap-1',
      email.sourceMailbox || 'INBOX',
      String(email.uidvalidity || ''),
      String(email.uid || ''),
      email.message_id || '',
      email.headers || {},
      email.raw || email.raw_content || '',
      email.email_body || email.body_preview || '',
      email.sender_email || '',
      email.sender_name || '',
      email.recipient_email || email.recipient || '',
      email.recipient_name || '',
      email.email_subject || email.subject || '',
    ],
  },
}));
```

- [ ] **Step 3: Add classification telemetry source**

Create `email-classifer/code-nodes/telemetry_build_classification_attempt.js`:

```js
function estimateTokens(value) {
  return Math.ceil(String(value || '').length / 4);
}

const source = $('Build classification prompt').item.json;
const prompt = `${source.systemPrompt || ''}\n\n${source.userPrompt || ''}`;
const rawResponse = typeof $json.output === 'string' ? $json.output : JSON.stringify($json.output ?? $json);
const parsed = $json.classification || source.classification || {};
const labels = Array.isArray(parsed.labels) ? parsed.labels : [];
const status = labels.some((item) => item.label === 'uncertain') ? 'uncertain' : 'success';

console.log(JSON.stringify({
  service: 'n8n',
  workflow_id: source.telemetry?.workflow_id,
  workflow_name: source.telemetry?.workflow_name,
  execution_id: source.telemetry?.execution_id,
  run_key: source.telemetry?.run_key,
  step: 'classify',
  status,
  account_id: source.credentialPairId,
  mailbox: source.sourceMailbox,
  message_id: source.message_id,
  subject: source.email_subject,
  model: 'igorls/gemma4-e4b-classifier:latest',
}));

return [{
  json: {
    ...source,
    classifier_output: $json,
    classification_attempt_params: [
      source.telemetry?.run_key,
      source.credentialPairId || 'imap-1',
      source.sourceMailbox || 'INBOX',
      String(source.uidvalidity || ''),
      String(source.uid || ''),
      'igorls/gemma4-e4b-classifier:latest',
      prompt,
      rawResponse,
      parsed,
      labels,
      estimateTokens(prompt),
      estimateTokens(rawResponse),
      status,
    ],
  },
}];
```

- [ ] **Step 4: Add label action telemetry source**

Create `email-classifer/code-nodes/telemetry_build_label_actions.js`:

```js
const item = $json;
const targets = Array.isArray(item.labelResults) ? item.labelResults : [];

return targets.map((target) => ({
  json: {
    ...item,
    label_action_params: [
      item.telemetry?.run_key,
      item.credentialPairId || item.account_id || 'imap-1',
      item.sourceMailbox || 'INBOX',
      String(item.uidvalidity || ''),
      String(item.uid || ''),
      target.mailbox || target.targetMailbox || '',
      target.status || 'success',
      String(target.uid || item.uid || ''),
      item.recipient_email || item.recipient || '',
      item.recipient_name || '',
      target.error || null,
    ],
  },
}));
```

- [ ] **Step 5: Add finish telemetry source**

Create `email-classifer/code-nodes/telemetry_finish_run.js`:

```js
const telemetry = $json.telemetry || {};
const stoppedAt = new Date().toISOString();
const status = $json.error ? 'error' : 'success';

console.log(JSON.stringify({
  service: 'n8n',
  workflow_id: telemetry.workflow_id,
  workflow_name: telemetry.workflow_name,
  execution_id: telemetry.execution_id,
  run_key: telemetry.run_key,
  step: 'finish_run',
  status,
  total_emails: Number($json.total_emails || 0),
  error: $json.error || null,
}));

return [{
  json: {
    ...$json,
    finish_run_params: [
      telemetry.run_key,
      status,
      stoppedAt,
      Number($json.total_emails || 0),
      $json.error ? String($json.error.message || $json.error).slice(0, 500) : null,
    ],
  },
}];
```

- [ ] **Step 6: Add Code-node sync tool**

Create `email-classifer/tools/sync_code_nodes.py`:

```python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE_CODE = {
    "Telemetry start run": "telemetry_start_run.js",
    "Telemetry build email items": "telemetry_build_email_items.js",
    "Telemetry build classification attempt": "telemetry_build_classification_attempt.js",
    "Telemetry build label actions": "telemetry_build_label_actions.js",
    "Telemetry finish run": "telemetry_finish_run.js",
}

def sync(path: Path) -> None:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    for node in workflow["nodes"]:
        filename = NODE_CODE.get(node["name"])
        if filename:
            node["parameters"]["jsCode"] = (ROOT / "code-nodes" / filename).read_text(encoding="utf-8")
    path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    sync(ROOT / "workflow.json")
    sync(ROOT / "workflow-imap-trigger.json")
```

- [ ] **Step 7: Add Postgres nodes to workflow JSON**

Add these n8n nodes to `workflow.json` and `workflow-imap-trigger.json`:

```json
{
  "name": "Telemetry upsert workflow and run",
  "type": "n8n-nodes-base.postgres",
  "parameters": {
    "operation": "executeQuery",
    "query": "WITH workflow_row AS (INSERT INTO workflows (n8n_workflow_id, name, last_seen_at) VALUES ($1, $2, now()) ON CONFLICT (n8n_workflow_id) DO UPDATE SET name = excluded.name, last_seen_at = now() RETURNING id), run_row AS (INSERT INTO workflow_runs (workflow_id, n8n_execution_id, trigger_mode, status, started_at, metadata) SELECT id, $3, $4, 'running', $5::timestamptz, jsonb_build_object('run_key', $6) FROM workflow_row RETURNING id) SELECT id FROM run_row;",
    "options": {
      "queryBatching": "independently",
      "queryParameters": "={{ [$json.telemetry.workflow_id, $json.telemetry.workflow_name, $json.telemetry.execution_id, $json.telemetry.trigger_mode, $json.telemetry.started_at, $json.telemetry.run_key] }}"
    }
  },
  "credentials": {
    "postgres": {
      "name": "Workflow Status Postgres"
    }
  }
}
```

Add `Telemetry upsert email item` with this query:

```sql
INSERT INTO email_items (
  account_id, source_mailbox, uidvalidity, uid, message_id, headers_json, raw_content,
  body_text, sender_email, sender_name, recipient_email, recipient_name, subject, last_seen_at
) VALUES (
  $1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, $12, $13, now()
)
ON CONFLICT (account_id, source_mailbox, uidvalidity, uid)
DO UPDATE SET
  message_id = excluded.message_id,
  headers_json = excluded.headers_json,
  raw_content = excluded.raw_content,
  body_text = excluded.body_text,
  sender_email = excluded.sender_email,
  sender_name = excluded.sender_name,
  recipient_email = excluded.recipient_email,
  recipient_name = excluded.recipient_name,
  subject = excluded.subject,
  last_seen_at = now()
RETURNING id;
```

Set its query parameters to:

```text
={{ $json.email_telemetry_params }}
```

Add `Telemetry record classification attempt` with this query:

```sql
WITH run_row AS (
  SELECT id FROM workflow_runs WHERE metadata->>'run_key' = $1 ORDER BY started_at DESC LIMIT 1
),
email_row AS (
  SELECT id FROM email_items
  WHERE account_id = $2 AND source_mailbox = $3 AND uidvalidity = $4 AND uid = $5
  LIMIT 1
)
INSERT INTO classification_attempts (
  run_id, email_item_id, model, prompt, raw_response, parsed_json, labels_json,
  estimated_prompt_tokens, estimated_completion_tokens, estimated_tokens, status
)
SELECT
  run_row.id, email_row.id, $6, $7, $8, $9::jsonb, $10::jsonb, $11, $12, true, $13
FROM run_row, email_row
RETURNING id;
```

Set its query parameters to:

```text
={{ $json.classification_attempt_params }}
```

Add `Telemetry record label action` with this query:

```sql
WITH run_row AS (
  SELECT id FROM workflow_runs WHERE metadata->>'run_key' = $1 ORDER BY started_at DESC LIMIT 1
),
email_row AS (
  SELECT id FROM email_items
  WHERE account_id = $2 AND source_mailbox = $3 AND uidvalidity = $4 AND uid = $5
  LIMIT 1
)
INSERT INTO label_actions (
  run_id, email_item_id, target_mailbox, action_status, imap_uid,
  recipient_email, recipient_name, error_json
)
SELECT
  run_row.id, email_row.id, $6, $7, $8, $9, $10, $11::jsonb
FROM run_row, email_row
RETURNING id;
```

Set its query parameters to:

```text
={{ $json.label_action_params }}
```

Add `Telemetry finish run` with this query:

```sql
UPDATE workflow_runs
SET
  status = $2,
  stopped_at = $3::timestamptz,
  duration_ms = (extract(epoch from ($3::timestamptz - started_at)) * 1000)::int,
  total_emails = $4,
  error_summary = $5
WHERE metadata->>'run_key' = $1
RETURNING id;
```

Set its query parameters to:

```text
={{ $json.finish_run_params }}
```

Do not enable `continueOnFail` on telemetry Postgres nodes during setup.

- [ ] **Step 8: Add workflow tests**

Add tests in `email-classifer/tests/test_workflow_json.py`:

```python
def test_telemetry_uses_postgres_nodes_not_execute_command(self):
    workflow = self.load_workflow()
    telemetry_nodes = [node for node in workflow["nodes"] if node["name"].startswith("Telemetry ")]
    self.assertGreaterEqual(len(telemetry_nodes), 8)
    self.assertTrue(any(node["type"] == "n8n-nodes-base.postgres" for node in telemetry_nodes))
    self.assertFalse(any(node["type"] == "n8n-nodes-base.executeCommand" for node in telemetry_nodes))

def test_telemetry_postgres_nodes_stop_on_error_during_setup(self):
    for node in self.load_workflow()["nodes"]:
        if node["name"].startswith("Telemetry ") and node["type"] == "n8n-nodes-base.postgres":
            self.assertFalse(node.get("continueOnFail", False))
            self.assertEqual(node["credentials"]["postgres"]["name"], "Workflow Status Postgres")

def test_telemetry_records_ai_model_tokens_and_label_actions(self):
    workflow = self.load_workflow()
    text = json.dumps(workflow)
    self.assertIn("classification_attempts", text)
    self.assertIn("label_actions", text)
    self.assertIn("estimated_prompt_tokens", text)
    self.assertIn("igorls/gemma4-e4b-classifier:latest", text)
```

- [ ] **Step 9: Sync, verify, and commit**

Run:

```bash
python3 email-classifer/tools/sync_code_nodes.py
python3 -m unittest discover -s email-classifer/tests
git add email-classifer/code-nodes email-classifer/tools email-classifer/tests/test_workflow_json.py email-classifer/workflow.json email-classifer/workflow-imap-trigger.json
git commit -m "feat: add email organiser telemetry"
```

Expected: unittest exits `0`, commit succeeds.

### Task 8: Deploy Status App To Coolify

**Files:**
- Modify: `/home/eric/source/n8n-workflow-status/docs/deploy/coolify.md`

- [ ] **Step 1: Ensure Coolify GitHub App can see the new repo**

Run:

```bash
coolify --context home --format json github repos 1 | rg '"full_name":"ebrearley/n8n-workflow-status"'
```

Expected: one matching repository line after the GitHub App installation includes the repo.

- [ ] **Step 2: Create the Coolify app**

Run:

```bash
WORKFLOW_STATUS_APP_UUID="$(coolify --context home --format json app create github \
  --server-uuid tcogoww \
  --project-uuid tk7pb9r1a5cqvhth6kiot9e4 \
  --environment-uuid auw9n2ov1ix59da3h3dcbvgt \
  --github-app-uuid x4wg4oc \
  --git-repository ebrearley/n8n-workflow-status \
  --git-branch main \
  --build-pack nixpacks \
  --ports-exposes 3000 \
  --domains n8n-workflow-status.home.brearley.net \
  --name n8n-workflow-status | jq -r '.uuid')"
export WORKFLOW_STATUS_APP_UUID
printf '%s\n' "$WORKFLOW_STATUS_APP_UUID"
```

Expected: JSON output includes the new application UUID.

- [ ] **Step 3: Add app environment variables**

Run:

```bash
read -r -s N8N_API_KEY
export N8N_API_KEY
export DATABASE_URL="postgres://workflow_status_app:${WORKFLOW_STATUS_DB_PASSWORD}@192.168.3.200:15432/workflow_status"
coolify --context home app env create "$WORKFLOW_STATUS_APP_UUID" --key DATABASE_URL --value "$DATABASE_URL" --runtime --build-time --is-literal
coolify --context home app env create "$WORKFLOW_STATUS_APP_UUID" --key N8N_BASE_URL --value 'https://n8n.home.ericbrearley.com' --runtime --build-time
coolify --context home app env create "$WORKFLOW_STATUS_APP_UUID" --key N8N_API_KEY --value "$N8N_API_KEY" --runtime --build-time --is-literal
coolify --context home app env create "$WORKFLOW_STATUS_APP_UUID" --key POLL_INTERVAL_MS --value '3000' --runtime --build-time
coolify --context home app env create "$WORKFLOW_STATUS_APP_UUID" --key NEXT_PUBLIC_POLL_INTERVAL_MS --value '3000' --runtime --build-time
coolify --context home app env list "$WORKFLOW_STATUS_APP_UUID"
```

Expected: env list shows the keys. Secret values stay hidden unless `--show-sensitive` is used.

- [ ] **Step 4: Deploy**

Run:

```bash
coolify --context home deploy "$WORKFLOW_STATUS_APP_UUID"
```

Expected: deployment succeeds and `https://n8n-workflow-status.home.brearley.net` returns the dashboard shell.

- [ ] **Step 5: Commit deployment doc update**

```bash
git add docs/deploy/coolify.md
git commit -m "docs: record coolify app deployment"
git push origin main
```

### Task 9: Normalize Alloy Logs For n8n

**Files:**
- Remote modify: `ssh ubuntu@192.168.3.200:/var/app-data/o11y/grafana-alloy/config/logs.alloy`
- Create: `/home/eric/source/n8n-workflow-status/docs/observability/loki-logql.md`

- [ ] **Step 1: Back up Alloy logs config**

Run:

```bash
ssh ubuntu@192.168.3.200 "cp /var/app-data/o11y/grafana-alloy/config/logs.alloy /var/app-data/o11y/grafana-alloy/config/logs.alloy.$(date +%Y%m%d%H%M%S).bak"
```

Expected: backup file appears in the config directory.

- [ ] **Step 2: Update Docker relabel rules**

Edit `/var/app-data/o11y/grafana-alloy/config/logs.alloy` so `discovery.relabel "containers"` contains:

```alloy
  rule {
    source_labels = ["container"]
    regex         = "(.*)"
    replacement   = sys.env("HOST_NAME") + "/$1"
    target_label  = "host_container"
  }

  rule {
    source_labels = ["__meta_docker_container_label_coolify_serviceName"]
    regex         = "(.+)"
    target_label  = "service"
  }

  rule {
    source_labels = ["service", "host_container"]
    separator     = ";"
    regex         = ";(.+)"
    replacement   = "$1"
    target_label  = "service"
  }

  rule {
    source_labels = ["__meta_docker_container_label_coolify_serviceName"]
    regex         = "(.+)"
    target_label  = "coolify_service"
  }

  rule {
    source_labels = ["__meta_docker_container_label_com_docker_compose_service"]
    regex         = "(.+)"
    target_label  = "compose_service"
  }
```

Keep the existing `container` and `stream` rules.

- [ ] **Step 3: Restart Alloy**

Run:

```bash
ssh ubuntu@192.168.3.200 "docker restart grafana-alloy"
ssh ubuntu@192.168.3.200 "docker logs --tail=80 grafana-alloy"
```

Expected: Alloy starts without config parse errors.

- [ ] **Step 4: Validate Loki queries**

Run:

```bash
curl -G 'http://192.168.1.250:30105/loki/api/v1/query' --data-urlencode 'query={service="n8n"}'
curl -G 'http://192.168.1.250:30105/loki/api/v1/query' --data-urlencode 'query={coolify_service="n8n"}'
```

Expected: both queries return a Loki JSON response with `status":"success"`.

- [ ] **Step 5: Document verified LogQL**

Create `docs/observability/loki-logql.md`:

```markdown
# Loki Queries

n8n container logs:

```logql
{service="n8n"}
```

Workflow structured logs:

```logql
{service="n8n"} |= "\"workflow_name\":\"Email Organiser\""
```

Email Organiser errors:

```logql
{service="n8n"} |= "\"workflow_name\":\"Email Organiser\"" |= "\"status\":\"error\""
```
```

- [ ] **Step 6: Commit**

```bash
git add docs/observability/loki-logql.md
git commit -m "docs: add loki queries"
git push origin main
```

### Task 10: Import, Wire Credentials, And Validate Workflow

**Files:**
- Modify: `email-classifer/README.md`
- Modify: `docs/superpowers/context/2026-06-05-n8n-email-organiser-context.md`

- [ ] **Step 1: Import the workflow**

Use the n8n MCP workflow update tool or n8n UI import to update workflow `fm6pLPnZWsGfK1oH` from:

```text
/home/eric/source/n8n-flows/email-classifer/workflow.json
```

Expected: the n8n workflow contains the telemetry Code nodes and Postgres nodes.

- [ ] **Step 2: Create n8n Postgres credential**

In n8n, create a credential named:

```text
Workflow Status Postgres
```

Use the `workflow_status_app` database user and the `workflow_status` database created in Task 6.

- [ ] **Step 3: Assign the credential to telemetry Postgres nodes**

Assign `Workflow Status Postgres` to each node whose name starts with:

```text
Telemetry
```

Expected: no telemetry Postgres node has a missing credential marker in the n8n UI.

- [ ] **Step 4: Run a capped manual validation**

Set `maxBatches` on `Configure Proton IMAP batch` to `1`.

Run the manual workflow.

Expected:

- workflow stops on the first error during setup;
- if no error occurs, up to 50 emails are processed;
- `workflow_runs` has one new row;
- `email_items`, `classification_attempts`, and `label_actions` have rows for processed emails;
- `Labels/Classified` is still applied to processed emails;
- `uncertain` emails continue with only `Labels/Classified`.

- [ ] **Step 5: Check database rows**

Run:

```bash
psql "$DATABASE_URL" -c "select status, total_emails, total_tokens, total_estimated_tokens from workflow_runs order by started_at desc limit 5;"
psql "$DATABASE_URL" -c "select model, status, estimated_prompt_tokens, estimated_completion_tokens from classification_attempts order by created_at desc limit 5;"
psql "$DATABASE_URL" -c "select target_mailbox, action_status, recipient_email from label_actions order by created_at desc limit 10;"
```

Expected: rows match the capped run.

- [ ] **Step 6: Check dashboard**

Open:

```text
https://n8n-workflow-status.home.brearley.net
```

Expected: global token totals, workflow list, run history, step details, AI details, and label actions update within 3 seconds.

- [ ] **Step 7: Restore full backfill behavior**

Set `maxBatches` on `Configure Proton IMAP batch` back to:

```text
0
```

Publish the workflow.

- [ ] **Step 8: Update docs and commit**

Update `email-classifer/README.md` with:

```markdown
## Workflow Status Telemetry

The workflow writes telemetry to the separate `workflow_status` database through n8n Postgres nodes using the `Workflow Status Postgres` credential.

During setup, telemetry DB errors stop the workflow. After validation, manual backfill uses `maxBatches=0` to process the full inbox.
```

Run:

```bash
python3 -m unittest discover -s email-classifer/tests
git add email-classifer/README.md docs/superpowers/context/2026-06-05-n8n-email-organiser-context.md email-classifer/workflow.json email-classifer/workflow-imap-trigger.json
git commit -m "docs: record workflow telemetry validation"
git push origin main
```

### Task 11: Final Verification

**Files:**
- Existing repos: `/home/eric/source/n8n-flows`, `/home/eric/source/n8n-workflow-status`

- [ ] **Step 1: Verify n8n-flows**

Run:

```bash
cd /home/eric/source/n8n-flows
python3 -m unittest discover -s email-classifer/tests
git status --short
```

Expected: tests exit `0`; only intentional local changes remain.

- [ ] **Step 2: Verify status app**

Run:

```bash
cd /home/eric/source/n8n-workflow-status
npm run db:validate
npm run test
npm run lint
npm run build
git status --short
```

Expected: all commands exit `0`; git status is clean after commits.

- [ ] **Step 3: Verify Coolify app**

Run:

```bash
curl -I -s https://n8n-workflow-status.home.brearley.net/
coolify --context home app logs "$WORKFLOW_STATUS_APP_UUID"
```

Expected: HTTP response is `200` or `307` to HTTPS; app logs have no startup error.

- [ ] **Step 4: Verify Loki**

Run:

```bash
curl -G 'http://192.168.1.250:30105/loki/api/v1/query' --data-urlencode 'query={service="n8n"} |= "\"workflow_name\":\"Email Organiser\""'
```

Expected: Loki returns `status":"success"` and at least one workflow log line after the validation run.

- [ ] **Step 5: Verify n8n workflow state**

Use n8n UI or MCP to confirm:

```text
Workflow: Email Organiser
State: active/published
Configure Proton IMAP batch maxBatches: 0
Telemetry Postgres nodes: credential assigned
Classify with Ollama: setup failure mode still stops workflow on error
```

Expected: workflow is ready for manual backfill and live trigger telemetry.
