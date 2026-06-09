# Email Label Taxonomy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the approved `Account notification`, `Statement`, `Account (security)`, `Newsletter`, and `Personal` labels to the Email Organiser workflow-as-code and legacy helper behavior.

**Architecture:** Keep the taxonomy source aligned across the Python helper, reusable JavaScript Code node source, README, and both importable workflow exports. Tests drive the change first, then implementation updates label lists, prompt text, and workflow inline node code using structured JSON edits. No live n8n import, execution, activation, mailbox mutation, or Proton label creation is part of this plan.

**Tech Stack:** Python `unittest`, n8n workflow JSON, n8n JavaScript Code nodes, Node.js syntax checks.

---

## File Structure

- `email-classifer/tests/test_workflow_json.py`
  Adds workflow JSON regression tests for the approved labels in prompts and target mailbox mapping.
- `email-classifer/tests/test_email_classifier.py`
  Adds legacy helper regression tests for default labels and `Account (security)` destination behavior.
- `email-classifer/code-nodes/prepare_proton_label_targets.js`
  Extends the enforced allowed label list used by the n8n Code node.
- `email-classifer/email_classifier.py`
  Extends `DEFAULT_SYSTEM_PROMPT` and `DEFAULT_LABELS` for the legacy helper.
- `email-classifer/workflow.json`
  Updates inline prompt text and `Prepare Proton label targets` JavaScript.
- `email-classifer/workflow-imap-trigger.json`
  Keeps the compatibility export in sync with `workflow.json`.
- `email-classifer/README.md`
  Updates the documented default labels.

## Approved Labels

Use these exact spellings:

```text
Account notification
Statement
Account (security)
Newsletter
Personal
```

Do not add `Account/Security`; the slash would become an IMAP path separator. Do not add separate `Security alert`, `Security`, `Notification`, `Account Update`, `Financial`, or `Onboarding` labels.

### Task 1: Add Failing Taxonomy Tests

**Files:**
- Modify: `email-classifer/tests/test_workflow_json.py`
- Modify: `email-classifer/tests/test_email_classifier.py`

- [ ] **Step 1: Add workflow JSON tests**

In `email-classifer/tests/test_workflow_json.py`, add this helper and tests inside `WorkflowJsonTests` after `build_prompt_assignments`:

```python
    def load_workflow_file(self, filename):
        return json.loads((ROOT / filename).read_text(encoding="utf-8"))

    def build_prompt_value_from_workflow(self, workflow):
        node = next(
            node for node in workflow["nodes"]
            if node["name"] == "Build classification prompt"
        )
        assignments = {
            assignment["name"]: assignment
            for assignment in node["parameters"]["assignments"]["assignments"]
        }
        return assignments["systemPrompt"]["value"]
```

Then add these tests near the existing prompt and prepare-target tests:

```python
    def test_system_prompt_includes_approved_label_taxonomy(self):
        expected_labels = [
            "Account notification",
            "Statement",
            "Account (security)",
            "Newsletter",
            "Personal",
        ]
        expected_phrases = [
            "routine account",
            "service statements",
            "MFA",
            "digest-style",
            "Direct personal correspondence",
        ]

        for filename in ("workflow.json", "workflow-imap-trigger.json"):
            with self.subTest(filename=filename):
                value = self.build_prompt_value_from_workflow(
                    self.load_workflow_file(filename),
                )
                for label in expected_labels:
                    self.assertIn(f"`{label}`", value)
                for phrase in expected_phrases:
                    self.assertIn(phrase, value)
                self.assertNotIn("`Account/Security`", value)

    def test_prepare_targets_accepts_approved_label_taxonomy(self):
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
      { label: 'Account notification', confidence: 0.91 },
      { label: 'Statement', confidence: 0.90 },
      { label: 'Account (security)', confidence: 0.89 },
      { label: 'Newsletter', confidence: 0.88 },
      { label: 'Personal', confidence: 0.87 },
    ],
    reason: 'Multiple approved taxonomy labels are present',
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
            result["labels"],
            [
                {"label": "Account notification", "confidence": 0.91},
                {"label": "Statement", "confidence": 0.90},
                {"label": "Account (security)", "confidence": 0.89},
                {"label": "Newsletter", "confidence": 0.88},
                {"label": "Personal", "confidence": 0.87},
            ],
        )
        self.assertEqual(
            result["targetMailboxes"],
            [
                "Labels/Account notification",
                "Labels/Statement",
                "Labels/Account (security)",
                "Labels/Newsletter",
                "Labels/Personal",
                "Labels/Classified",
            ],
        )
        self.assertNotIn("Labels/Account/Security", result["targetMailboxes"])
```

- [ ] **Step 2: Add Python helper tests**

In `email-classifer/tests/test_email_classifier.py`, add these tests after `test_parses_categories_from_environment_value`:

```python
    def test_default_labels_include_approved_label_taxonomy(self):
        for label in (
            "Account notification",
            "Statement",
            "Account (security)",
            "Newsletter",
            "Personal",
        ):
            self.assertIn(label, classifier.DEFAULT_LABELS)
            self.assertIn(f"`{label}`", classifier.DEFAULT_SYSTEM_PROMPT)

        self.assertNotIn("Account/Security", classifier.DEFAULT_LABELS)
        self.assertNotIn("`Account/Security`", classifier.DEFAULT_SYSTEM_PROMPT)

    def test_normalizes_new_labels_and_preserves_account_security_mailbox(self):
        result = classifier.normalize_classification(
            json.dumps({
                "labels": [
                    {"label": "Account notification", "confidence": 0.91},
                    {"label": "Statement", "confidence": 0.90},
                    {"label": "Account (security)", "confidence": 0.89},
                    {"label": "Newsletter", "confidence": 0.88},
                    {"label": "Personal", "confidence": 0.87},
                ],
                "reason": "Approved taxonomy labels",
            }),
            classifier.DEFAULT_LABELS,
        )

        self.assertEqual(
            result["folders"],
            [
                "Account notification",
                "Statement",
                "Account (security)",
                "Newsletter",
                "Personal",
            ],
        )

        destinations = classifier.classification_destinations(
            result,
            state_label="Classified",
            prefix="Labels",
        )
        self.assertEqual(
            destinations,
            [
                "Labels/Account notification",
                "Labels/Statement",
                "Labels/Account (security)",
                "Labels/Newsletter",
                "Labels/Personal",
                "Labels/Classified",
            ],
        )
        self.assertNotIn("Labels/Account/Security", destinations)
```

- [ ] **Step 3: Run the targeted tests and verify RED**

Run:

```bash
python3 -m unittest \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_system_prompt_includes_approved_label_taxonomy \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_prepare_targets_accepts_approved_label_taxonomy \
  email-classifer.tests.test_email_classifier.EmailClassifierTests.test_default_labels_include_approved_label_taxonomy \
  email-classifer.tests.test_email_classifier.EmailClassifierTests.test_normalizes_new_labels_and_preserves_account_security_mailbox
```

Expected: FAIL. The prompt tests should fail because the new labels are not in the prompts yet. The prepare-target and helper normalization tests should fail because the new labels are not in the allowed lists yet.

### Task 2: Implement Approved Labels And Sync Workflow Exports

**Files:**
- Modify: `email-classifer/code-nodes/prepare_proton_label_targets.js`
- Modify: `email-classifer/email_classifier.py`
- Modify: `email-classifer/workflow.json`
- Modify: `email-classifer/workflow-imap-trigger.json`
- Modify: `email-classifer/README.md`

- [ ] **Step 1: Update the JavaScript allowed list**

In `email-classifer/code-nodes/prepare_proton_label_targets.js`, replace the `allowed` declaration with:

```javascript
const allowed = ["Invoice","Purchase","Bill","Payment","Marketing","Cold email","Important","Awaiting reply","Travel","Ticket","Infrastructure","Hustle","Schedule","Spam like","Account notification","Statement","Account (security)","Newsletter","Personal"];
```

- [ ] **Step 2: Update Python `DEFAULT_LABELS`**

In `email-classifer/email_classifier.py`, append the approved labels before `uncertain`:

```python
DEFAULT_LABELS = [
    "Invoice",
    "Purchase",
    "Bill",
    "Payment",
    "Marketing",
    "Cold email",
    "Important",
    "Awaiting reply",
    "Travel",
    "Ticket",
    "Infrastructure",
    "Hustle",
    "Schedule",
    "Spam like",
    "Account notification",
    "Statement",
    "Account (security)",
    "Newsletter",
    "Personal",
    "uncertain",
]
```

- [ ] **Step 3: Update Python `DEFAULT_SYSTEM_PROMPT` allowed labels**

In `email-classifer/email_classifier.py`, add these entries under `## Allowed labels`, after `Spam like`:

```text
- `Account notification` — routine account, service, policy, profile, membership, subscription, or platform notices that do not primarily concern security or billing
- `Statement` — periodic account, bank, provider, or service statements summarizing balances, activity, usage, holdings, or charges
- `Account (security)` — account access and security messages, including logins, MFA, password changes, identity checks, recovery codes, suspicious activity, sign-in warnings, or verification requests
- `Newsletter` — recurring editorial, community, creator, publication, product-update, or digest-style emails from known or subscribed sources
- `Personal` — Direct personal correspondence from friends, family, acquaintances, or personal contacts about non-business, non-automated matters
```

Add a short boundary section before `## Schema`:

```text
## Label boundaries
- `Account notification`: use for routine account, service, policy, profile, membership, subscription, or platform notices. Do not use for security, billing, infrastructure, or transaction mail.
- `Statement`: use for periodic account, bank, provider, or service statements. Do not use for invoices, bills, receipts, purchases, or payment events.
- `Account (security)`: use for login, MFA, password, recovery, identity verification, suspicious activity, sign-in warning, and account access security messages. Do not use `Account/Security`.
- `Newsletter`: use for recurring editorial, community, creator, publication, product-update, or digest-style mail where the main intent is information rather than direct selling.
- `Personal`: use for direct personal correspondence from real personal contacts. It can overlap with `Schedule` and `Awaiting reply` when those also apply.
```

Add five few-shot examples before the closing triple quote, after the existing `Spam like` example:

```text

Email: "Your account profile was updated successfully."
```json
{"labels": [{"label": "Account notification", "confidence": 0.90}], "reason": "Routine account status notice"}
```

Email: "Your April bank statement is now available."
```json
{"labels": [{"label": "Statement", "confidence": 0.94}], "reason": "Periodic account statement notice"}
```

Email: "New sign-in to your account from Chrome on Linux. If this was not you, reset your password."
```json
{"labels": [{"label": "Account (security)", "confidence": 0.95}], "reason": "Account access security alert"}
```

Email: "Weekly digest: five new essays and community updates."
```json
{"labels": [{"label": "Newsletter", "confidence": 0.90}], "reason": "Recurring digest-style newsletter"}
```

Email: "Hey, dinner at my place this Friday?"
```json
{"labels": [{"label": "Personal", "confidence": 0.88}, {"label": "Schedule", "confidence": 0.78}, {"label": "Awaiting reply", "confidence": 0.76}], "reason": "Personal invitation that needs a response and includes timing"}
```
```

- [ ] **Step 4: Update the README default labels**

In `email-classifer/README.md`, add these bullets after `Spam like` in the `Default labels` list:

```markdown
- `Account notification`
- `Statement`
- `Account (security)`
- `Newsletter`
- `Personal`
```

- [ ] **Step 5: Sync source changes into workflow exports with structured JSON**

Run this command from the repository root:

```bash
python3 - <<'PY'
import importlib.util
import json
from pathlib import Path

root = Path("email-classifer")
spec = importlib.util.spec_from_file_location("email_classifier", root / "email_classifier.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

prepare_code = (root / "code-nodes" / "prepare_proton_label_targets.js").read_text(encoding="utf-8")

for workflow_path in (root / "workflow.json", root / "workflow-imap-trigger.json"):
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    for node in workflow["nodes"]:
        if node["name"] == "Build classification prompt":
            for assignment in node["parameters"]["assignments"]["assignments"]:
                if assignment["name"] == "systemPrompt":
                    assignment["value"] = module.DEFAULT_SYSTEM_PROMPT
        if node["name"] == "Prepare Proton label targets":
            node["parameters"]["jsCode"] = prepare_code
    workflow_path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
PY
```

- [ ] **Step 6: Run targeted tests and verify GREEN**

Run:

```bash
python3 -m unittest \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_system_prompt_includes_approved_label_taxonomy \
  email-classifer.tests.test_workflow_json.WorkflowJsonTests.test_prepare_targets_accepts_approved_label_taxonomy \
  email-classifer.tests.test_email_classifier.EmailClassifierTests.test_default_labels_include_approved_label_taxonomy \
  email-classifer.tests.test_email_classifier.EmailClassifierTests.test_normalizes_new_labels_and_preserves_account_security_mailbox
```

Expected: PASS.

### Task 3: Verify Full Local Behavior

**Files:**
- No new files.
- Verify all files changed by Tasks 1 and 2.

- [ ] **Step 1: Compile reusable Code nodes**

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

Expected: `compiled code nodes`.

- [ ] **Step 2: Compile inline workflow Code nodes**

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

Expected: `compiled workflow code nodes`.

- [ ] **Step 3: Run the full unit test suite**

Run:

```bash
python3 -m unittest discover -s email-classifer/tests
```

Expected: all tests pass.

- [ ] **Step 4: Check whitespace and final diff**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` has no output. `git status --short` shows only intended modifications:

```text
 M email-classifer/README.md
 M email-classifer/code-nodes/prepare_proton_label_targets.js
 M email-classifer/email_classifier.py
 M email-classifer/tests/test_email_classifier.py
 M email-classifer/tests/test_workflow_json.py
 M email-classifer/workflow-imap-trigger.json
 M email-classifer/workflow.json
```

- [ ] **Step 5: Commit implementation**

Run:

```bash
git add email-classifer/README.md \
  email-classifer/code-nodes/prepare_proton_label_targets.js \
  email-classifer/email_classifier.py \
  email-classifer/tests/test_email_classifier.py \
  email-classifer/tests/test_workflow_json.py \
  email-classifer/workflow-imap-trigger.json \
  email-classifer/workflow.json
git commit -m "feat(email-classifer): add account and personal labels"
```

Expected: commit succeeds.

## Self-Review

Spec coverage:

- The plan adds all five approved labels with exact spelling.
- The plan avoids `Account/Security` and maps `Account (security)` to one Proton label mailbox segment.
- The plan updates workflow exports, reusable Code node source, the legacy helper, README, and tests.
- The plan does not perform any live n8n import, workflow execution, activation, or mailbox mutation.

Placeholder scan:

- No unresolved markers or incomplete implementation steps remain.

Type consistency:

- The same exact label strings are used in tests, JavaScript, Python, prompt text, README, and expected mailbox paths.
