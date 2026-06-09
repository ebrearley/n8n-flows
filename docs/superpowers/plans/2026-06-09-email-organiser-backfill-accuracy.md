# Email Organiser Backfill Accuracy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate staged backfill runtime behavior, improve classifier prompt accuracy, and record telemetry-only missing label suggestions.

**Architecture:** Source changes happen in the telemetry worktree because it matches the live 103-node n8n draft. The classifier keeps allowed labels and suggested labels separate: allowed labels drive Proton `Labels/*` targets, while `suggested_labels` are sanitized and recorded for review. Live backfill uses capped MCP updates and sanitized Postgres telemetry before any uncapped run.

**Tech Stack:** n8n 2.23.4 workflow JSON, n8n MCP, n8n Code nodes in JavaScript, Python `unittest`, Node syntax checks, Postgres telemetry, Proton Bridge IMAP.

---

## Working Directory

Use the telemetry worktree for implementation:

```bash
cd /home/eric/source/n8n-flows/.worktrees/workflow-telemetry-status
```

Do not import or publish `/home/eric/source/n8n-flows/email-classifer/workflow.json` from `main`; that export has 17 nodes and does not match the live telemetry workflow.

## File Structure

- Modify: `email-classifer/tests/test_workflow_json.py`
  Adds regression tests for prompt schema, suggested labels, unknown labels, and telemetry persistence.
- Modify: `email-classifer/code-nodes/prepare_proton_label_targets.js`
  Parses and sanitizes `suggested_labels`, records unknown labels, and prevents suggested labels from becoming target mailboxes.
- Modify: `email-classifer/code-nodes/telemetry_build_classification_attempt.js`
  Keeps suggested labels in `parsed_json` and normalizes classifier status when no confident labels exist.
- Modify: `email-classifer/email_classifier.py`
  Updates the saved default system prompt so the prompt is in code as well as workflow JSON.
- Modify: `email-classifer/workflow.json`
  Generated/synced workflow export with 103 nodes.
- Modify: `email-classifer/workflow-imap-trigger.json`
  Compatibility export kept in sync with `workflow.json`.

## Task 1: Baseline And Documentation Checks

**Files:**
- Read: `/home/eric/source/n8n-flows/AGENTS.md`
- Read: `docs/superpowers/specs/2026-06-09-email-organiser-backfill-accuracy-design.md`
- Read: `email-classifer/workflow.json`

- [ ] **Step 1: Confirm clean telemetry worktree**

Run:

```bash
cd /home/eric/source/n8n-flows/.worktrees/workflow-telemetry-status
git status --short --branch
```

Expected:

```text
## feature/workflow-telemetry-status...origin/feature/workflow-telemetry-status
```

- [ ] **Step 2: Confirm local export is the telemetry graph**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path
workflow = json.loads(Path('email-classifer/workflow.json').read_text())
names = {node['name'] for node in workflow['nodes']}
required = [
    'Telemetry start step: Fetch next unclassified emails',
    'Telemetry finish step: Fetch next unclassified emails',
    'Telemetry build classification attempt',
    'Telemetry build label actions',
]
print(f"node_count={len(workflow['nodes'])}")
for name in required:
    print(f"{name}={'present' if name in names else 'missing'}")
PY
```

Expected:

```text
node_count=103
Telemetry start step: Fetch next unclassified emails=present
Telemetry finish step: Fetch next unclassified emails=present
Telemetry build classification attempt=present
Telemetry build label actions=present
```

- [ ] **Step 3: Keep n8n docs lookup result in mind**

Use the already fetched Context7 docs result for `/n8n-io/n8n-docs`:

- workflow updates require reading the workflow first;
- active state is managed separately from update requests;
- execution status can be monitored without `includeData`;
- MCP `execute_workflow` performs real workflow execution.

Do not fetch raw execution data unless a later debugging task explicitly needs sanitized node-level data.

## Task 2: Add Failing Tests For Suggested Labels

**Files:**
- Modify: `email-classifer/tests/test_workflow_json.py`

- [ ] **Step 1: Add tests near the existing prompt and prepare-target tests**

Insert these test methods after `test_system_prompt_includes_schedule_and_spam_like_labels`:

```python
    def test_system_prompt_documents_suggested_labels_as_telemetry_only(self):
        assignments = self.build_prompt_assignments()
        value = assignments["systemPrompt"]["value"]

        self.assertIn("suggested_labels", value)
        self.assertIn("telemetry-only", value)
        self.assertIn("do not create Proton labels", value)
        self.assertIn("do not put suggested labels in `labels`", value)
        self.assertIn("strict JSON", value)

    def test_prepare_targets_records_suggested_labels_without_targets(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Prepare Proton label targets').parameters.jsCode;
const source = {
  uid: '3542',
  sourceFlow: 'bulk',
  runMode: 'apply_labels',
  labelPrefix: 'Labels',
  stateLabel: 'Classified',
};
const aiOutput = {
  output: JSON.stringify({
    labels: [
      { label: 'Invoice', confidence: 0.91 }
    ],
    suggested_labels: [
      {
        label: 'Security alert',
        reason: 'Account access notifications do not fit the existing labels',
        criteria: 'Use for MFA, password, sign-in, and account access warnings'
      },
      {
        label: 'Invoice',
        reason: 'Duplicate of an allowed label',
        criteria: 'Should be ignored as a suggestion'
      }
    ],
    reason: 'Receipt with a useful missing category suggestion',
  }),
};
const dollar = (name) => {
  if (name !== 'Build classification prompt') throw new Error(`Unexpected node lookup: ${name}`);
  return { item: { json: source } };
};

(async () => {
  const result = await new AsyncFunction('$', '$json', code)(dollar, aiOutput);
  console.log(JSON.stringify(result[0].json));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(
            result["suggested_labels"],
            [
                {
                    "label": "Security alert",
                    "reason": "Account access notifications do not fit the existing labels",
                    "criteria": "Use for MFA, password, sign-in, and account access warnings",
                },
            ],
        )
        self.assertEqual(result["classification"]["suggested_labels"], result["suggested_labels"])
        self.assertEqual(result["labels"], [{"label": "Invoice", "confidence": 0.91}])
        self.assertEqual(result["targetMailboxes"], ["Labels/Invoice", "Labels/Classified"])
        self.assertNotIn("Labels/Security alert", result["targetMailboxes"])

    def test_prepare_targets_drops_unknown_labels_but_records_them(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Prepare Proton label targets').parameters.jsCode;
const source = {
  uid: '3542',
  sourceFlow: 'bulk',
  runMode: 'apply_labels',
  labelPrefix: 'Labels',
  stateLabel: 'Classified',
};
const aiOutput = {
  output: JSON.stringify({
    labels: [
      { label: 'Security alert', confidence: 0.94 },
      { label: 'Spam like', confidence: 0.86 }
    ],
    suggested_labels: [
      {
        label: 'Security alert',
        reason: 'Security notifications may deserve their own label',
        criteria: 'Use for account access warnings'
      }
    ],
    reason: 'Spam-like account warning with an unsupported category',
  }),
};
const dollar = (name) => {
  if (name !== 'Build classification prompt') throw new Error(`Unexpected node lookup: ${name}`);
  return { item: { json: source } };
};

(async () => {
  const result = await new AsyncFunction('$', '$json', code)(dollar, aiOutput);
  console.log(JSON.stringify(result[0].json));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(result["labels"], [{"label": "Spam like", "confidence": 0.86}])
        self.assertEqual(result["unknown_labels"], [{"label": "Security alert", "confidence": 0.94}])
        self.assertEqual(result["targetMailboxes"], ["Labels/Spam like", "Labels/Classified"])
        self.assertNotIn("Labels/Security alert", result["targetMailboxes"])
```

- [ ] **Step 2: Add telemetry attempt test after the prepare-target tests**

Insert this test method after `test_prepare_targets_drops_unknown_labels_but_records_them`:

```python
    def test_telemetry_classification_attempt_keeps_suggested_labels_in_parsed_json(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Telemetry build classification attempt').parameters.jsCode;
const source = {
  uid: '3542',
  sourceFlow: 'bulk',
  runMode: 'apply_labels',
  systemPrompt: 'system prompt',
  userPrompt: 'user prompt',
  telemetry: { run_id: '3276939b-659e-494e-8a8d-0af412ff6106' },
  email_item_id: '11111111-1111-4111-8111-111111111111',
};
const aiOutput = {
  output: JSON.stringify({
    labels: [{ label: 'uncertain', confidence: 0.4 }],
    suggested_labels: [
      {
        label: 'Security alert',
        reason: 'Security notification category is missing',
        criteria: 'Use for MFA and login warnings'
      }
    ],
    reason: 'Ambiguous account notification',
  }),
};
const dollar = (name) => {
  if (name !== 'Build classification prompt') throw new Error(`Unexpected node lookup: ${name}`);
  return { item: { json: source } };
};

(async () => {
  const result = await new AsyncFunction('$', '$json', code)(dollar, aiOutput);
  const params = result[0].json.classification_attempt_params;
  console.log(JSON.stringify({
    parsed_json: JSON.parse(params[5]),
    labels_json: JSON.parse(params[6]),
    status: params[9],
  }));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        self.assertEqual(
            result["parsed_json"]["suggested_labels"],
            [
                {
                    "label": "Security alert",
                    "reason": "Security notification category is missing",
                    "criteria": "Use for MFA and login warnings",
                },
            ],
        )
        self.assertEqual(result["labels_json"], [{"label": "uncertain", "confidence": 0.4}])
        self.assertEqual(result["status"], "uncertain")
```

- [ ] **Step 3: Run the targeted tests and verify they fail**

Run:

```bash
python3 -m unittest \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_system_prompt_documents_suggested_labels_as_telemetry_only \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_prepare_targets_records_suggested_labels_without_targets \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_prepare_targets_drops_unknown_labels_but_records_them \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_telemetry_classification_attempt_keeps_suggested_labels_in_parsed_json
```

Expected: FAIL. The prompt test should fail because `suggested_labels` is not in the prompt yet, and the prepare-target tests should fail because `suggested_labels` and `unknown_labels` are not emitted yet.

## Task 3: Implement Suggested Label Parsing

**Files:**
- Modify: `email-classifer/code-nodes/prepare_proton_label_targets.js`

- [ ] **Step 1: Replace prepare-target parsing code**

Update `email-classifer/code-nodes/prepare_proton_label_targets.js` so it contains these helper functions after `clampConfidence`:

```javascript
function cleanText(value, maxLength) {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLength);
}

function extractJsonText(value) {
  let text = String(value || '').trim();
  const fenced = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fenced) {
    text = fenced[1].trim();
  }

  if (!text.startsWith('{')) {
    const objectMatch = text.match(/\{[\s\S]*\}/);
    if (objectMatch) text = objectMatch[0];
  }

  return text;
}

function parseAiOutput(value) {
  if (value && typeof value === 'object') {
    if (Array.isArray(value.labels) || Array.isArray(value.suggested_labels)) return value;
    if ('output' in value) return parseAiOutput(value.output);
  }
  if (typeof value === 'string') {
    return JSON.parse(extractJsonText(value));
  }
  return value;
}

function suggestedLabelKey(value) {
  return cleanText(value, 64).toLowerCase();
}

function sanitizeSuggestedLabels(value) {
  if (!Array.isArray(value)) return [];

  const suggestions = [];
  for (const item of value) {
    const label = cleanText(item?.label, 64);
    const reason = cleanText(item?.reason, 240);
    const criteria = cleanText(item?.criteria, 320);
    const key = suggestedLabelKey(label);

    if (!label || key === 'uncertain') continue;
    if (allowed.some((allowedLabel) => suggestedLabelKey(allowedLabel) === key)) continue;
    if (suggestions.some((existing) => suggestedLabelKey(existing.label) === key)) continue;

    suggestions.push({ label, reason, criteria });
    if (suggestions.length >= 5) break;
  }

  return suggestions;
}
```

Then update the label loop and return object to this shape:

```javascript
const accepted = [];
const unknownLabels = [];
const parsedLabels = Array.isArray(parsed?.labels) ? parsed.labels : [];
for (const item of parsedLabels) {
  const label = cleanText(item?.label, 64);
  const confidence = clampConfidence(item?.confidence);
  if (label === 'uncertain') continue;
  if (!allowed.includes(label)) {
    if (label && !unknownLabels.some((existing) => existing.label === label)) {
      unknownLabels.push({ label, confidence });
    }
    continue;
  }
  if (confidence < 0.75) continue;
  if (!accepted.some((existing) => existing.label === label)) {
    accepted.push({ label, confidence });
  }
}

const fallbackConfidence = parsedLabels.length > 0
  ? clampConfidence(parsedLabels[0]?.confidence)
  : 0;
const suggestedLabels = sanitizeSuggestedLabels(parsed?.suggested_labels);
const reason = cleanText(
  parsed?.reason ?? (accepted.length ? 'Classifier returned matching labels' : 'No label reached confidence threshold'),
  240,
);
const labelPrefix = source.labelPrefix || 'Labels';
const stateLabel = source.stateLabel || 'Classified';
const labelMailboxes = accepted.map((item) => `${labelPrefix}/${item.label}`);
const stateMailbox = `${labelPrefix}/${stateLabel}`;
const targetMailboxes = [...labelMailboxes];
if (!targetMailboxes.includes(stateMailbox)) targetMailboxes.push(stateMailbox);

return [{
  json: {
    ...source,
    runMode: 'apply_labels',
    classification: {
      labels: accepted.length ? accepted : [{ label: 'uncertain', confidence: fallbackConfidence }],
      suggested_labels: suggestedLabels,
      unknown_labels: unknownLabels,
      reason,
    },
    labels: accepted,
    suggested_labels: suggestedLabels,
    unknown_labels: unknownLabels,
    labelMailboxes,
    stateMailbox,
    targetMailboxes,
  },
}];
```

- [ ] **Step 2: Run the prepare-target tests and verify they pass**

Run:

```bash
python3 -m unittest \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_prepare_targets_records_suggested_labels_without_targets \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_prepare_targets_drops_unknown_labels_but_records_them \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_uncertain_fenced_ai_output_applies_only_classified_and_continues
```

Expected: PASS.

## Task 4: Keep Suggested Labels In Classification Telemetry

**Files:**
- Modify: `email-classifer/code-nodes/telemetry_build_classification_attempt.js`

- [ ] **Step 1: Update object parsing and status**

In `parseAiOutput`, replace the object branch with:

```javascript
  if (value && typeof value === 'object') {
    if (Array.isArray(value.labels) || Array.isArray(value.suggested_labels)) return value;
    if ('output' in value) return parseAiOutput(value.output);
  }
```

Replace the `status` line with:

```javascript
const status = labels.length === 0 || labels.some((item) => item?.label === 'uncertain')
  ? 'uncertain'
  : 'success';
```

- [ ] **Step 2: Run the telemetry attempt test**

Run:

```bash
python3 -m unittest \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_telemetry_classification_attempt_keeps_suggested_labels_in_parsed_json
```

Expected: PASS.

## Task 5: Improve And Save The Prompt In Code

**Files:**
- Modify: `email-classifer/email_classifier.py`
- Modify: `email-classifer/workflow.json`
- Modify: `email-classifer/workflow-imap-trigger.json`

- [ ] **Step 1: Update `DEFAULT_SYSTEM_PROMPT`**

In `email-classifer/email_classifier.py`, replace the schema, fallback, rules, and examples section of `DEFAULT_SYSTEM_PROMPT` with text that contains this exact schema block and rules:

```text
## Schema
Output strict JSON only. Do not wrap it in Markdown.

{
  "labels": [
    { "label": string, "confidence": number }
  ],
  "suggested_labels": [
    {
      "label": string,
      "reason": string,
      "criteria": string
    }
  ],
  "reason": string
}

- `labels`: every confidently applicable label from the allowed list only. Each `label` must exactly match one allowed label. Each `confidence` must be between 0 and 1.
- Include an allowed label only when confidence is at least 0.75.
- `suggested_labels`: telemetry-only suggestions for useful missing categories. These do not create Proton labels and are never applied to email. Do not put suggested labels in `labels`.
- Use at most five `suggested_labels`. Leave it as an empty array when the allowed labels are sufficient.
- `reason`: one short sentence explaining the selected allowed labels or uncertainty.

## Label boundaries
- `Marketing`: legitimate promotional, newsletter, sale, launch, or brand content from an expected sender.
- `Cold email`: unsolicited direct outreach seeking sales, recruiting, partnerships, backlinks, meetings, or attention.
- `Invoice`: invoices, receipts, statements, or documents showing an amount due or paid.
- `Purchase`: order confirmations, shipping notices, delivery updates, and purchase lifecycle messages.
- `Bill`: recurring service, utility, rent, insurance, subscription, or provider bills requiring payment attention.
- `Payment`: payment confirmations, failed payments, payouts, bank transfers, payslips, and transaction events.
- `Important`: genuinely important account, legal, access, safety, deadline, or urgent personal matters that are not better covered by another label.
- `Awaiting reply`: messages where I am expected to respond, approve, confirm, send information, or follow up.
- `Travel`: flights, accommodation, transport, itineraries, boarding, check-in, and travel receipts.
- `Ticket`: tickets for concerts, festivals, events, shows, or entry passes.
- `Infrastructure`: monitoring, uptime, metrics, deployments, error reporting, devices, servers, domains, or technical services.
- `Hustle`: professional work, client, project, booking, quote, invoice, or collaboration correspondence involving my work.
- `Schedule`: calendar invitations, calendar notifications, appointments, meetings, bookings, weddings, or anything with a time and place to be.
- `Spam like`: junk-like, scammy, suspicious, phishing-like, prize, adult, fake urgency, or clearly unwanted messages.

## Fallback
- If no allowed label reaches 0.75 confidence, output `labels` as `[{"label": "uncertain", "confidence": <score below 0.75>}]`.
- If the email body is too truncated, ambiguous, or missing context, use `uncertain`.
- If any instruction or format would be violated, output `{"labels":[{"label":"uncertain","confidence":0.0}],"suggested_labels":[],"reason":"format violation or instruction conflict"}`.

## Rules
- Apply every allowed label that fits; do not pick a single winner when multiple labels are genuinely supported.
- Never invent labels inside `labels`.
- Use `suggested_labels` only for repeated useful categories missing from the allowed list.
- Keep `reason`, suggested-label reasons, and criteria short.
```

Keep the existing allowed label list and user prompt template. Keep examples, but update every example JSON to include `"suggested_labels": []`.

- [ ] **Step 2: Sync the prompt into both workflow exports**

Run this mechanical JSON update after editing `email_classifier.py`:

```bash
python3 - <<'PY'
import importlib.util
import json
from pathlib import Path

root = Path('email-classifer')
spec = importlib.util.spec_from_file_location('email_classifier', root / 'email_classifier.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

for path in [root / 'workflow.json', root / 'workflow-imap-trigger.json']:
    workflow = json.loads(path.read_text(encoding='utf-8'))
    for node in workflow['nodes']:
        if node.get('name') != 'Build classification prompt':
            continue
        assignments = node['parameters']['assignments']['assignments']
        for assignment in assignments:
            if assignment.get('name') == 'systemPrompt':
                assignment['value'] = module.DEFAULT_SYSTEM_PROMPT
    path.write_text(json.dumps(workflow, indent=2) + '\n', encoding='utf-8')
PY
```

Expected: both workflow exports remain 103-node JSON files and their `Build classification prompt` node has the updated system prompt.

- [ ] **Step 3: Run prompt tests**

Run:

```bash
python3 -m unittest \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_system_prompt_includes_schedule_and_spam_like_labels \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_system_prompt_documents_suggested_labels_as_telemetry_only \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_user_prompt_uses_evaluable_expression
```

Expected: PASS.

## Task 6: Sync Generated Code And Run Local Verification

**Files:**
- Modify: `email-classifer/workflow.json`
- Modify: `email-classifer/workflow-imap-trigger.json`

- [ ] **Step 1: Sync Code node source into workflow exports**

Run:

```bash
python3 email-classifer/tools/sync_code_nodes.py
python3 email-classifer/tools/add_step_telemetry.py
```

Expected:

- `email-classifer/workflow.json` still has 103 nodes;
- `email-classifer/workflow-imap-trigger.json` still has 103 nodes;
- no duplicate telemetry stages are added.

- [ ] **Step 2: Compile Code-node source files**

Run:

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

Expected:

```text
compiled code nodes
```

- [ ] **Step 3: Compile inline workflow Code nodes**

Run:

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

Expected:

```text
compiled workflow code nodes
```

- [ ] **Step 4: Run all local tests**

Run:

```bash
python3 -m unittest discover -s email-classifer/tests
git diff --check
```

Expected: tests pass and `git diff --check` prints no output.

- [ ] **Step 5: Commit local source changes**

Run:

```bash
git add email-classifer
git commit -m "feat(email-classifer): record suggested classifier labels"
```

Expected: one commit on `feature/workflow-telemetry-status`.

## Task 7: Update Live Draft Safely

**Files:**
- Read: `email-classifer/workflow.json`
- Live write target: n8n workflow `fm6pLPnZWsGfK1oH`

- [ ] **Step 1: Read live workflow summary before any write**

Run outside the sandbox if DNS fails inside the sandbox:

```bash
python3 - <<'PY'
import json
import os
import urllib.request

payload = {
    'jsonrpc': '2.0',
    'id': 1,
    'method': 'tools/call',
    'params': {
        'name': 'get_workflow_details',
        'arguments': {'workflowId': 'fm6pLPnZWsGfK1oH'},
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=30).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
content = message['result']['content'][0]['text']
result = json.loads(content)
workflow = result['workflow']
names = {node['name'] for node in workflow['nodes']}
print(f"id={workflow['id']}")
print(f"active={workflow['active']}")
print(f"node_count={len(workflow['nodes'])}")
print(f"active_version_id={workflow.get('activeVersionId')}")
for name in ['Build classification prompt', 'Prepare Proton label targets', 'Telemetry build classification attempt']:
    print(f"{name}={'present' if name in names else 'missing'}")
PY
```

Expected:

```text
id=fm6pLPnZWsGfK1oH
active=False
node_count=103
active_version_id=None
Build classification prompt=present
Prepare Proton label targets=present
Telemetry build classification attempt=present
```

- [ ] **Step 2: Apply targeted MCP updates from local workflow JSON**

Run:

```bash
python3 - <<'PY'
import json
import os
import urllib.request
from pathlib import Path

workflow_id = 'fm6pLPnZWsGfK1oH'
local = json.loads(Path('email-classifer/workflow.json').read_text())
nodes = {node['name']: node for node in local['nodes']}

operations = [
    {
        'type': 'setNodeParameter',
        'nodeName': 'Build classification prompt',
        'path': '/assignments/assignments',
        'value': nodes['Build classification prompt']['parameters']['assignments']['assignments'],
    },
    {
        'type': 'setNodeParameter',
        'nodeName': 'Prepare Proton label targets',
        'path': '/jsCode',
        'value': nodes['Prepare Proton label targets']['parameters']['jsCode'],
    },
    {
        'type': 'setNodeParameter',
        'nodeName': 'Telemetry build classification attempt',
        'path': '/jsCode',
        'value': nodes['Telemetry build classification attempt']['parameters']['jsCode'],
    },
]

payload = {
    'jsonrpc': '2.0',
    'id': 2,
    'method': 'tools/call',
    'params': {
        'name': 'update_workflow',
        'arguments': {
            'workflowId': workflow_id,
            'operations': operations,
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=60).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
content = message['result']['content'][0]['text']
result = json.loads(content)
print(json.dumps({
    'workflowId': result.get('workflowId'),
    'nodeCount': result.get('nodeCount'),
    'appliedOperations': result.get('appliedOperations'),
    'validationWarnings': result.get('validationWarnings', []),
}, indent=2))
PY
```

Expected:

```json
{
  "workflowId": "fm6pLPnZWsGfK1oH",
  "nodeCount": 103,
  "appliedOperations": 3,
  "validationWarnings": []
}
```

If the only warning is that `Email Trigger (IMAP)` is not connected to an input, treat it as expected for a trigger node and continue.

- [ ] **Step 3: Read live workflow summary again**

Run the Step 1 read command again.

Expected:

- `active=False`;
- `node_count=103`;
- the three updated nodes are present.

## Task 8: Stage 1 Backfill - One Batch

**Files:**
- Live write target: n8n workflow `fm6pLPnZWsGfK1oH`
- Telemetry read target: `workflow_status` Postgres database

- [ ] **Step 1: Set live `maxBatches` to 1**

Run:

```bash
python3 - <<'PY'
import json
import os
import urllib.request
from pathlib import Path

workflow_id = 'fm6pLPnZWsGfK1oH'
local = json.loads(Path('email-classifer/workflow.json').read_text())
node = next(node for node in local['nodes'] if node['name'] == 'Configure Proton IMAP batch')
assignments = node['parameters']['assignments']['assignments']
for assignment in assignments:
    if assignment.get('name') == 'maxBatches':
        assignment['value'] = 1
    if assignment.get('name') == 'batchLimit':
        assignment['value'] = 50

payload = {
    'jsonrpc': '2.0',
    'id': 3,
    'method': 'tools/call',
    'params': {
        'name': 'update_workflow',
        'arguments': {
            'workflowId': workflow_id,
            'operations': [{
                'type': 'setNodeParameter',
                'nodeName': 'Configure Proton IMAP batch',
                'path': '/assignments/assignments',
                'value': assignments,
            }],
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=60).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
result = json.loads(message['result']['content'][0]['text'])
print(json.dumps({'nodeCount': result.get('nodeCount'), 'appliedOperations': result.get('appliedOperations')}, indent=2))
PY
```

Expected:

```json
{
  "nodeCount": 103,
  "appliedOperations": 1
}
```

- [ ] **Step 2: Execute the workflow manually**

Run:

```bash
python3 - <<'PY'
import json
import os
import urllib.request

payload = {
    'jsonrpc': '2.0',
    'id': 4,
    'method': 'tools/call',
    'params': {
        'name': 'execute_workflow',
        'arguments': {
            'workflowId': 'fm6pLPnZWsGfK1oH',
            'executionMode': 'manual',
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=30).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
print(message['result']['content'][0]['text'])
PY
```

Expected: a JSON result with `"status":"started"` and a non-empty execution ID. Do not request execution data.

- [ ] **Step 3: Poll sanitized execution metadata**

Run this every 60 seconds until the execution is no longer `running`:

```bash
python3 - <<'PY'
import json
import os
import urllib.request

payload = {
    'jsonrpc': '2.0',
    'id': 5,
    'method': 'tools/call',
    'params': {
        'name': 'search_executions',
        'arguments': {
            'workflowId': 'fm6pLPnZWsGfK1oH',
            'limit': 5,
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=30).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
result = json.loads(message['result']['content'][0]['text'])
for execution in result.get('data', []):
    print(json.dumps({
        'id': execution.get('id'),
        'status': execution.get('status'),
        'mode': execution.get('mode'),
        'startedAt': execution.get('startedAt'),
        'stoppedAt': execution.get('stoppedAt'),
    }))
PY
```

Expected: latest execution moves from `running` to `success`. If it moves to `error`, stop and debug with sanitized telemetry before retrying.

- [ ] **Step 4: Query Stage 1 telemetry summary**

Run outside the sandbox:

```bash
ssh -F /dev/null -o BatchMode=yes ubuntu@192.168.3.200 'docker exec postgresql-ew4sow0ws8kggowogk4owk4c sh -lc '\''psql -X -q -A -F $'\''\t'\'' -U "$POSTGRES_USER" -d workflow_status -c "
with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''run'\'', r.id::text, r.status, coalesce(r.total_emails, 0)::text
from workflow_runs r
join latest_run lr on lr.id = r.id;

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''steps'\'', status, count(*)::text
from workflow_steps
where run_id = (select id from latest_run)
group by status
order by status;

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''fetch_steps'\'', count(*)::text
from workflow_steps
where run_id = (select id from latest_run)
  and step_name = '\''Fetch next unclassified emails'\'';

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''classifications'\'', status, count(*)::text
from classification_attempts
where run_id = (select id from latest_run)
group by status
order by status;

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''labels'\'', action_status, count(*)::text
from label_actions
where run_id = (select id from latest_run)
group by action_status
order by action_status;
"'\'''
```

Expected:

- latest run status is `success`;
- no `workflow_steps` row has `running` or `error`;
- `fetch_steps` is at least `1`;
- `label_actions` contains `success` rows for `Labels/Classified`;
- `classification_attempts` may contain `uncertain`, and the run still succeeds.

## Task 9: Stage 2 Backfill - Three Batches

**Files:**
- Live write target: n8n workflow `fm6pLPnZWsGfK1oH`
- Telemetry read target: `workflow_status` Postgres database

- [ ] **Step 1: Set live `maxBatches` to 3**

Run:

```bash
python3 - <<'PY'
import json
import os
import urllib.request
from pathlib import Path

workflow_id = 'fm6pLPnZWsGfK1oH'
local = json.loads(Path('email-classifer/workflow.json').read_text())
node = next(node for node in local['nodes'] if node['name'] == 'Configure Proton IMAP batch')
assignments = node['parameters']['assignments']['assignments']
for assignment in assignments:
    if assignment.get('name') == 'maxBatches':
        assignment['value'] = 3
    if assignment.get('name') == 'batchLimit':
        assignment['value'] = 50

payload = {
    'jsonrpc': '2.0',
    'id': 6,
    'method': 'tools/call',
    'params': {
        'name': 'update_workflow',
        'arguments': {
            'workflowId': workflow_id,
            'operations': [{
                'type': 'setNodeParameter',
                'nodeName': 'Configure Proton IMAP batch',
                'path': '/assignments/assignments',
                'value': assignments,
            }],
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=60).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
result = json.loads(message['result']['content'][0]['text'])
print(json.dumps({'nodeCount': result.get('nodeCount'), 'appliedOperations': result.get('appliedOperations')}, indent=2))
PY
```

Expected: update applies one operation and live node count remains 103.

- [ ] **Step 2: Execute workflow manually**

Run:

```bash
python3 - <<'PY'
import json
import os
import urllib.request

payload = {
    'jsonrpc': '2.0',
    'id': 7,
    'method': 'tools/call',
    'params': {
        'name': 'execute_workflow',
        'arguments': {
            'workflowId': 'fm6pLPnZWsGfK1oH',
            'executionMode': 'manual',
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=30).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
print(message['result']['content'][0]['text'])
PY
```

Expected: execution starts.

- [ ] **Step 3: Poll sanitized execution metadata**

Run this every 60 seconds until completion:

```bash
python3 - <<'PY'
import json
import os
import urllib.request

payload = {
    'jsonrpc': '2.0',
    'id': 8,
    'method': 'tools/call',
    'params': {
        'name': 'search_executions',
        'arguments': {
            'workflowId': 'fm6pLPnZWsGfK1oH',
            'limit': 5,
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=30).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
result = json.loads(message['result']['content'][0]['text'])
for execution in result.get('data', []):
    print(json.dumps({
        'id': execution.get('id'),
        'status': execution.get('status'),
        'mode': execution.get('mode'),
        'startedAt': execution.get('startedAt'),
        'stoppedAt': execution.get('stoppedAt'),
    }))
PY
```

Expected: latest execution reaches `success`.

- [ ] **Step 4: Verify three fetch cycles and batch progression**

Run outside the sandbox:

```bash
ssh -F /dev/null -o BatchMode=yes ubuntu@192.168.3.200 'docker exec postgresql-ew4sow0ws8kggowogk4owk4c sh -lc '\''psql -X -q -A -F $'\''\t'\'' -U "$POSTGRES_USER" -d workflow_status -c "
with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''fetch_step_count'\'', count(*)::text
from workflow_steps
where run_id = (select id from latest_run)
  and step_name = '\''Fetch next unclassified emails'\'';

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''fetch_step'\'',
       row_number() over (order by started_at)::text,
       status,
       coalesce(output_json->>'\''stopped_reason'\'', ''),
       coalesce(output_json->>'\''total_emails'\'', '')
from workflow_steps
where run_id = (select id from latest_run)
  and step_name = '\''Fetch next unclassified emails'\''
order by started_at;

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''email_count'\'', count(distinct email_item_id)::text
from label_actions
where run_id = (select id from latest_run);

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''classified_actions'\'', count(*)::text
from label_actions
where run_id = (select id from latest_run)
  and target_mailbox = '\''Labels/Classified'\''
  and action_status = '\''success'\'';
"'\'''
```

Expected:

- `fetch_step_count` is at least `3`;
- fetch rows are ordered and successful;
- distinct `email_item_id` count is greater than `50` when the inbox has enough unclassified mail;
- `classified_actions` equals the number of processed email items unless a real missing mailbox or IMAP error is recorded.

- [ ] **Step 5: Inspect aggregate suggested-label telemetry**

Run:

```bash
ssh -F /dev/null -o BatchMode=yes ubuntu@192.168.3.200 'docker exec postgresql-ew4sow0ws8kggowogk4owk4c sh -lc '\''psql -X -q -A -F $'\''\t'\'' -U "$POSTGRES_USER" -d workflow_status -c "
with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
),
suggestions as (
  select jsonb_array_elements(coalesce(parsed_json->'\''suggested_labels'\'', '\''[]'\''::jsonb)) as suggestion
  from classification_attempts
  where run_id = (select id from latest_run)
)
select coalesce(suggestion->>'\''label'\'', '\''<missing>'\'') as suggested_label,
       count(*)::text
from suggestions
group by suggested_label
order by count(*) desc, suggested_label
limit 20;
"'\'''
```

Expected: aggregate labels only. Do not print raw email body, subject, prompt, or raw model response.

## Task 10: Stage 3 Backfill - Full Inbox

**Files:**
- Live write target: n8n workflow `fm6pLPnZWsGfK1oH`
- Telemetry read target: `workflow_status` Postgres database

- [ ] **Step 1: Gate check before uncapped run**

Proceed only if Task 9 passed:

- at least three fetch cycles;
- no stuck `running` steps;
- no unexpected `error` steps;
- label actions show `Labels/Classified` success for processed emails;
- uncertain classifications did not stop the run.

- [ ] **Step 2: Set live `maxBatches` to 0**

Run:

```bash
python3 - <<'PY'
import json
import os
import urllib.request
from pathlib import Path

workflow_id = 'fm6pLPnZWsGfK1oH'
local = json.loads(Path('email-classifer/workflow.json').read_text())
node = next(node for node in local['nodes'] if node['name'] == 'Configure Proton IMAP batch')
assignments = node['parameters']['assignments']['assignments']
for assignment in assignments:
    if assignment.get('name') == 'maxBatches':
        assignment['value'] = 0
    if assignment.get('name') == 'batchLimit':
        assignment['value'] = 50

payload = {
    'jsonrpc': '2.0',
    'id': 9,
    'method': 'tools/call',
    'params': {
        'name': 'update_workflow',
        'arguments': {
            'workflowId': workflow_id,
            'operations': [{
                'type': 'setNodeParameter',
                'nodeName': 'Configure Proton IMAP batch',
                'path': '/assignments/assignments',
                'value': assignments,
            }],
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=60).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
result = json.loads(message['result']['content'][0]['text'])
print(json.dumps({'nodeCount': result.get('nodeCount'), 'appliedOperations': result.get('appliedOperations')}, indent=2))
PY
```

Expected: update applies one operation and live node count remains 103.

- [ ] **Step 3: Execute the full backfill**

Run:

```bash
python3 - <<'PY'
import json
import os
import urllib.request

payload = {
    'jsonrpc': '2.0',
    'id': 10,
    'method': 'tools/call',
    'params': {
        'name': 'execute_workflow',
        'arguments': {
            'workflowId': 'fm6pLPnZWsGfK1oH',
            'executionMode': 'manual',
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=30).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
print(message['result']['content'][0]['text'])
PY
```

Expected: execution starts.

- [ ] **Step 4: Monitor full backfill**

Every 2 minutes, run this execution metadata poll:

```bash
python3 - <<'PY'
import json
import os
import urllib.request

payload = {
    'jsonrpc': '2.0',
    'id': 11,
    'method': 'tools/call',
    'params': {
        'name': 'search_executions',
        'arguments': {
            'workflowId': 'fm6pLPnZWsGfK1oH',
            'limit': 5,
        },
    },
}
req = urllib.request.Request(
    'https://n8n.home.ericbrearley.com/mcp-server/http',
    data=json.dumps(payload).encode(),
    headers={
        'Authorization': f"Bearer {os.environ['N8N_MCP_ACCESS_TOKEN']}",
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
    },
)
raw = urllib.request.urlopen(req, timeout=30).read().decode()
message = json.loads([line[6:] for line in raw.splitlines() if line.startswith('data: ')][-1])
result = json.loads(message['result']['content'][0]['text'])
for execution in result.get('data', []):
    print(json.dumps({
        'id': execution.get('id'),
        'status': execution.get('status'),
        'mode': execution.get('mode'),
        'startedAt': execution.get('startedAt'),
        'stoppedAt': execution.get('stoppedAt'),
    }))
PY
```

Then run this telemetry summary:

```bash
ssh -F /dev/null -o BatchMode=yes ubuntu@192.168.3.200 'docker exec postgresql-ew4sow0ws8kggowogk4owk4c sh -lc '\''psql -X -q -A -F $'\''\t'\'' -U "$POSTGRES_USER" -d workflow_status -c "
with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''run'\'', status, coalesce(total_emails, 0)::text, coalesce(total_estimated_tokens, 0)::text
from workflow_runs
where id = (select id from latest_run);

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''step_status'\'', status, count(*)::text
from workflow_steps
where run_id = (select id from latest_run)
group by status
order by status;

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''fetch_count'\'', count(*)::text
from workflow_steps
where run_id = (select id from latest_run)
  and step_name = '\''Fetch next unclassified emails'\'';

with latest_run as (
  select id
  from workflow_runs
  where workflow_name = '\''Email Organiser'\''
  order by started_at desc
  limit 1
)
select '\''label_status'\'', action_status, count(*)::text
from label_actions
where run_id = (select id from latest_run)
group by action_status
order by action_status;
"'\'''
```

Expected while running: fetch count and label counts increase over time, with no long-lived stuck step. Expected final state: run reaches `success` and the final fetch step reports no remaining unclassified emails.

- [ ] **Step 5: Leave workflow inactive after validation**

Read live summary with Task 7 Step 1.

Expected:

```text
active=False
node_count=103
```

Do not publish or activate the workflow unless the user explicitly asks.

## Task 11: Accuracy Review And Next Step Note

**Files:**
- Modify: `email-classifer/README.md`

- [ ] **Step 1: Add aggregate accuracy notes**

Add a short section to `email-classifer/README.md`:

```markdown
## Backfill Accuracy Review

Backfill validation uses sanitized telemetry, not raw execution output. Review:

- run status and total processed email counts from `workflow_runs`;
- fetch cycle counts from `workflow_steps`;
- uncertain rates and suggested-label themes from `classification_attempts`;
- `Labels/Classified` and confident-label outcomes from `label_actions`.

Suggested labels are telemetry-only. They do not create Proton labels and are not applied to email until the allowed label list is deliberately updated.
```

- [ ] **Step 2: Add future action phase note**

Add this to `email-classifer/README.md`:

```markdown
## Future Action Phase

After the classifier is robust and accurate, design a separate safety-gated phase for mail actions such as moving spam-like messages to Spam, archiving redundant notifications, and drafting auto replies. That phase must be designed separately because it changes mailbox state beyond applying existing labels.
```

- [ ] **Step 3: Run docs and tests check**

Run:

```bash
python3 -m unittest discover -s email-classifer/tests
git diff --check
```

Expected: tests pass and `git diff --check` prints no output.

- [ ] **Step 4: Commit docs and validation notes**

Run:

```bash
git add email-classifer/README.md
git commit -m "docs(email-classifer): document backfill validation signals"
```

Expected: one docs commit on `feature/workflow-telemetry-status`.

## Plan Self-Review

- Spec coverage: The plan covers visibility checks, staged one-batch and three-batch ramps, uncapped backfill, prompt source persistence, telemetry-only suggested labels, prompt accuracy improvements, tests, and the future action-taking phase.
- Placeholder scan: No deferred-work markers or unspecified implementation steps remain.
- Type consistency: The plan uses `suggested_labels`, `unknown_labels`, `targetMailboxes`, `classification_attempt_params`, and `Labels/Classified` consistently across tests, Code nodes, workflow JSON, and telemetry SQL.
