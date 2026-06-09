# Email Organiser Backfill Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce backfill runtime by keeping each execution to one fetched batch, removing expensive non-essential per-email step telemetry in the bulk path, and applying Proton labels once per batch instead of opening an IMAP session per email.

**Architecture:** The backfill path will fetch one batch of up to 50 emails, classify each email through the existing loop, collect prepared label targets from the loop done output, apply all labels in one batch-level IMAP Code node, record per-email label actions, then finish the run. The trigger path keeps single-email label behavior. LLM tiering and additional GPU models are out of scope.

**Tech Stack:** n8n workflow JSON, n8n Code nodes in JavaScript, generated workflow exports, Python `unittest`, Proton Bridge IMAP, sanitized `workflow_status` telemetry.

---

### Task 1: Short Backfill Executions And Lighter Bulk Step Telemetry

**Files:**
- Modify: `email-classifer/tests/test_workflow_json.py`
- Modify: `email-classifer/workflow.json`
- Modify: `email-classifer/workflow-imap-trigger.json`
- Create: `email-classifer/code-nodes/prepare_label_batch.js`
- Modify: `email-classifer/tools/sync_code_nodes.py`

- [ ] **Step 1: Write failing workflow wiring tests**

Add tests asserting:

```python
def test_backfill_defaults_to_one_batch_per_execution(self):
    assignments = self.configure_assignments()
    self.assertEqual(assignments["maxBatches"]["value"], 1)

def test_bulk_loop_collects_prepared_labels_before_batch_apply(self):
    workflow = self.load_workflow()
    nodes = self.nodes_by_name()
    self.assertIn("Prepare label batch", nodes)
    self.assertEqual(
        workflow["connections"]["Loop Over Emails"]["main"][0][0]["node"],
        "Prepare label batch",
    )
    self.assertEqual(
        workflow["connections"]["Prepare label batch"]["main"][0][0]["node"],
        "Telemetry start step: Apply Proton labels",
    )
    self.assertEqual(
        workflow["connections"]["From bulk loop?"]["main"][0][0]["node"],
        "Loop Over Emails",
    )
    self.assertEqual(
        workflow["connections"]["Telemetry restore label action payload"]["main"][0][0]["node"],
        "Telemetry start step: Finish run",
    )

def test_bulk_path_bypasses_prompt_and_prepare_step_telemetry(self):
    workflow = self.load_workflow()
    self.assertEqual(
        workflow["connections"]["Loop Over Emails"]["main"][1][0]["node"],
        "Build classification prompt",
    )
    self.assertEqual(
        workflow["connections"]["Build classification prompt"]["main"][0][0]["node"],
        "Telemetry start step: Classify with Ollama",
    )
    self.assertEqual(
        workflow["connections"]["Telemetry restore classification payload"]["main"][0][0]["node"],
        "Prepare Proton label targets",
    )
    self.assertEqual(
        workflow["connections"]["Prepare Proton label targets"]["main"][0][0]["node"],
        "Inspect Proton label targets",
    )
```

- [ ] **Step 2: Run tests and verify they fail**

Run: `python3 -m unittest email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_backfill_defaults_to_one_batch_per_execution email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_bulk_loop_collects_prepared_labels_before_batch_apply email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_bulk_path_bypasses_prompt_and_prepare_step_telemetry`

Expected: failures showing `maxBatches` is still `0`, `Prepare label batch` is missing, and the bulk path still uses step telemetry wrappers.

- [ ] **Step 3: Add `Prepare label batch` tests**

Add a test that runs the new Code node with two prepared email items containing private body/prompt fields and asserts:

```python
result = self.run_workflow_code_node("Prepare label batch", input_items)
self.assertEqual(len(result), 1)
batch = result[0]["json"]["label_batch_items"]
self.assertEqual([item["uid"] for item in batch], ["101", "102"])
self.assertNotIn("email_body", batch[0])
self.assertNotIn("body_preview", batch[0])
self.assertNotIn("userPrompt", batch[0])
self.assertEqual(result[0]["json"]["total_emails"], 2)
self.assertEqual(result[0]["json"]["stopped_reason"], "batch_processed")
```

- [ ] **Step 4: Run test and verify it fails**

Run: `python3 -m unittest email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_prepare_label_batch_collapses_items_without_private_content`

Expected: failure because the node does not exist.

- [ ] **Step 5: Implement the node and wiring**

Create `email-classifer/code-nodes/prepare_label_batch.js` with logic that maps `$input.all()` into one item:

```javascript
const PRIVATE_FIELDS = new Set([
  'email_body', 'body_preview', 'raw', 'raw_content', 'userPrompt',
  'systemPrompt', 'output', 'classifier_output', 'classification_raw_response',
]);

function compactEmail(item) {
  const compact = {};
  for (const [key, value] of Object.entries(item || {})) {
    if (!PRIVATE_FIELDS.has(key)) compact[key] = value;
  }
  compact.resetLoop = false;
  return compact;
}

const inputs = $input.all().map((item) => item.json ?? {});
const first = inputs[0] ?? {};
const batch = inputs.map(compactEmail);

return [{
  json: {
    sourceFlow: 'bulk',
    runMode: 'apply_label_batch',
    telemetry: first.telemetry || {},
    run_id: first.run_id || first.telemetry?.run_id || '',
    run_key: first.run_key || first.telemetry?.run_key || '',
    workflow_id: first.workflow_id || first.telemetry?.workflow_id || '',
    workflow_name: first.workflow_name || first.telemetry?.workflow_name || '',
    execution_id: first.execution_id || first.telemetry?.execution_id || '',
    label_batch_items: batch,
    total_emails: batch.length,
    stopped_reason: batch.length ? 'batch_processed' : 'empty_batch',
  },
}];
```

Update `sync_code_nodes.py` to map `"Prepare label batch"` to this file. Add the node to both workflow exports and update connections:

- `Configure Proton IMAP batch.maxBatches = 1`
- `Loop Over Emails` done output -> `Prepare label batch`
- `Prepare label batch` -> `Telemetry start step: Apply Proton labels`
- `Loop Over Emails` item output -> `Build classification prompt`
- `Build classification prompt` -> `Telemetry start step: Classify with Ollama`
- `Telemetry restore classification payload` -> `Prepare Proton label targets`
- `Prepare Proton label targets` -> `Inspect Proton label targets`
- `From bulk loop?` true output -> `Loop Over Emails`
- `Telemetry restore label action payload` -> `Telemetry start step: Finish run`

- [ ] **Step 6: Run tests and commit**

Run:

```bash
python3 -m unittest discover -s email-classifer/tests
git diff --check
git add email-classifer tests docs
git commit -m "perf(email-classifer): process backfill in short executions"
```

Expected: all tests pass, whitespace check clean.

### Task 2: Batch IMAP Label Application

**Files:**
- Modify: `email-classifer/tests/test_workflow_json.py`
- Modify: `email-classifer/code-nodes/apply_proton_labels.js`
- Modify: `email-classifer/code-nodes/telemetry_build_label_actions.js`
- Modify: `email-classifer/workflow.json`
- Modify: `email-classifer/workflow-imap-trigger.json`

- [ ] **Step 1: Write failing dry-run batch label test**

Add a test that invokes `Apply Proton labels` in dry-run mode with one batch item containing two `label_batch_items`. Assert the node returns one batch result item with two `label_batch_results`, each preserving `email_item_id`, `uid`, and `destination_actions`, and no `email_body`.

- [ ] **Step 2: Run test and verify it fails**

Run: `python3 -m unittest email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_apply_proton_labels_processes_label_batch_items`

Expected: failure because the current node only reads `$input.first().json` as one email item.

- [ ] **Step 3: Write failing label-action expansion test**

Add a test that invokes `Telemetry build label actions` with a batch result containing two emails and asserts it returns one `label_action_params` row per email/mailbox target.

- [ ] **Step 4: Run test and verify it fails**

Run: `python3 -m unittest email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_telemetry_label_actions_expand_batch_results`

Expected: failure because the current helper only uses the first input item and does not inspect `label_batch_results`.

- [ ] **Step 5: Implement batch-aware label application**

Update `apply_proton_labels.js` so:

- input source is `item.label_batch_items` when present, otherwise all input items;
- dry-run returns one batch summary item with `label_batch_results`;
- real mode groups emails by credential pair and source mailbox;
- each group opens one IMAP connection and logs in once;
- mailbox existence checks are cached per target mailbox;
- valid items are copied in UID groups with `UID COPY uid1,uid2 "Labels/X"`;
- each result records `destination_actions` exactly as current telemetry expects;
- the trigger path still works with a single item.

- [ ] **Step 6: Implement batch-aware label telemetry**

Update `telemetry_build_label_actions.js` so it expands `label_batch_results` when present, otherwise preserves current single-item behavior.

- [ ] **Step 7: Sync workflow code nodes, run tests, and commit**

Run:

```bash
python3 email-classifer/tools/sync_code_nodes.py
python3 -m unittest discover -s email-classifer/tests
git diff --check
git add email-classifer
git commit -m "perf(email-classifer): batch proton label application"
```

Expected: all tests pass, whitespace check clean.

### Task 3: Validate Locally And Prepare Live Update

**Files:**
- Modify only if needed: `docs/superpowers/context/2026-06-05-n8n-email-organiser-context.md`

- [ ] **Step 1: Compile Code nodes**

Run the repo’s Code-node compile checks:

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

Expected: `compiled code nodes`.

- [ ] **Step 2: Compile inline workflow Code nodes**

Run the repo’s inline workflow compile check for both exports.

Expected: `compiled workflow code nodes`.

- [ ] **Step 3: Check live execution before import**

Use sanitized `workflow_status` telemetry to see whether execution `60` is still running. Do not start a second backfill execution while execution `60` is still running.

- [ ] **Step 4: Update live draft only after local validation**

Use MCP/public API/import tooling following `AGENTS.md`. Keep workflow inactive after import/publish. Do not print raw execution data.

- [ ] **Step 5: Validate with one batch when no other backfill is running**

Run a single one-batch execution, monitor sanitized telemetry, and verify:

- one fetch step succeeds with `50` or fewer emails;
- `Classify with Ollama` classifications match the fetched email count;
- `Apply Proton labels` has one batch-level step row, not one per email;
- `label_actions` still contains one row per email/target mailbox;
- workflow run finishes instead of fetching another batch in the same execution.
