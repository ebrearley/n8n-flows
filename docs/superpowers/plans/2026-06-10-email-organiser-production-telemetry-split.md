# Email Organiser Production Telemetry Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Back the production and telemetry Email Organiser workflows from code, with production telemetry-free and the duplicated telemetry workflow reserved for iteration and status-dashboard runs.

**Architecture:** Keep `email-classifer/workflow.json` and `workflow-imap-trigger.json` as the production `Email Organiser` source. Add `email-classifer/workflow-with-telemetry.json` as the code-backed source for `Email Organiser (with telemetry)`. Update live n8n by importing temporary workflow JSON with live IDs and credential references injected outside the committed files.

**Tech Stack:** n8n workflow JSON, Python unittest, n8n CLI/API, Markdown documentation.

---

### Task 1: Encode Workflow Split In Tests

**Files:**
- Modify: `email-classifer/tests/test_workflow_json.py`

- [ ] Add tests asserting production exports do not contain telemetry/Postgres nodes.
- [ ] Add tests asserting `workflow-with-telemetry.json` exists, is named `Email Organiser (with telemetry)`, and contains step/Postgres telemetry nodes.
- [ ] Run the targeted tests and verify the telemetry export test fails before adding the file.

### Task 2: Add Telemetry Workflow Export

**Files:**
- Create: `email-classifer/workflow-with-telemetry.json`

- [ ] Sanitize the live duplicate export by removing live-only top-level metadata, active state, and credential IDs.
- [ ] Preserve telemetry nodes, Postgres credential names, workflow settings, and the duplicated workflow name.
- [ ] Run workflow JSON tests and Code-node compile checks.

### Task 3: Update Documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `email-classifer/README.md`
- Modify: `/home/eric/source/n8n-workflow-status/AGENTS.md`
- Modify: `/home/eric/source/n8n-workflow-status/README.md`
- Modify: `/home/eric/source/n8n-workflow-status/docs/observability/loki-logql.md`

- [ ] Document `Email Organiser` as the telemetry-free production workflow.
- [ ] Document `Email Organiser (with telemetry)` as the workflow to run when feeding `n8n-workflow-status`.
- [ ] Replace stale warnings that say the status dashboard depends on the original workflow ID.

### Task 4: Update Live n8n From Code

**Files:**
- Temporary only: `/tmp/email-organiser-production-import.json`
- Temporary only: `/tmp/email-organiser-with-telemetry-import.json`

- [ ] Re-read both live workflow metadata before writing.
- [ ] Inject live workflow IDs and credential references into temporary import JSON.
- [ ] Import/publish `Email Organiser` from the production export and leave it active.
- [ ] Import/publish `Email Organiser (with telemetry)` from the telemetry export and leave it inactive.
- [ ] Restart n8n if using CLI import, then verify live metadata only: names, IDs, active states, node counts, trigger counts, and telemetry-node counts.

### Task 5: Final Verification

**Files:**
- Repository checks only.

- [ ] Run `python3 -m unittest discover -s email-classifer/tests`.
- [ ] Run Code-node compile checks for source and inline workflow Code nodes.
- [ ] Run `git diff --check` in `n8n-flows`.
- [ ] Run relevant documentation diff checks in `n8n-workflow-status`.
