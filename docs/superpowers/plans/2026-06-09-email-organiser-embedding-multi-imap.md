# Email Organiser Embedding Multi-IMAP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Email Organiser workflow follow `mail -> clean/truncate -> embedding model -> classifier -> category` while preserving safe Proton label application and existing multi-IMAP backfill support.

**Architecture:** Add two shared Code nodes before classification: `Clean and truncate email` prepares bounded model-facing text, and `Generate email embedding` calls Ollama `/api/embed` and forwards only embedding metadata. Update the classifier prompt and parser so `category` is canonical while legacy `labels` output remains accepted during transition. Keep backfill multi-IMAP behavior in the existing fetch node and add regression tests around it.

**Tech Stack:** n8n workflow JSON, n8n Code nodes in JavaScript, Ollama `/api/embed`, Python `unittest`, Node.js syntax checks.

---

## File Map

- Create: `email-classifer/code-nodes/clean_and_truncate_email.js`
  Shared preparation node. Produces `cleanEmailText`, `cleanEmailTextLength`, `cleanEmailTruncated`, and keeps body fields bounded.
- Create: `email-classifer/code-nodes/generate_email_embedding.js`
  Shared embedding node. Calls Ollama `/api/embed` with `cleanEmailText`, returns metadata only, and fails closed on embedding errors.
- Modify: `email-classifer/code-nodes/prepare_proton_label_targets.js`
  Parse the new `category` response shape and retain legacy `labels` parsing.
- Modify: `email-classifer/workflow.json`
  Add and wire the two new Code nodes, update the classification prompt to use `cleanEmailText`, add backfill embedding config defaults, and keep no `Manual Trigger`.
- Modify: `email-classifer/workflow-imap-trigger.json`
  Keep synchronized with `workflow.json`.
- Modify: `email-classifer/tests/test_workflow_json.py`
  Add tests for the new graph, node behavior, category parser, no raw vector forwarding, sync between exports, and multi-IMAP regression coverage.

## Task 1: RED Tests For Shared Preparation And Workflow Shape

**Files:**
- Modify: `email-classifer/tests/test_workflow_json.py`

- [ ] **Step 1: Add failing tests for synchronized exports, shared clean node, and clean-node behavior**

Add these helper methods near the top of `WorkflowJsonTests`, immediately after `load_workflow`:

```python
    def load_workflow_path(self, name):
        return json.loads((ROOT / name).read_text(encoding="utf-8"))

    def all_workflows(self):
        return {
            "workflow.json": self.load_workflow_path("workflow.json"),
            "workflow-imap-trigger.json": self.load_workflow_path("workflow-imap-trigger.json"),
        }

    def nodes_by_name_for(self, workflow):
        return {node["name"]: node for node in workflow["nodes"]}
```

Add these tests after `test_backfill_form_trigger_is_the_only_backfill_start`:

```python
    def test_workflow_exports_have_same_nodes_and_connections(self):
        workflows = self.all_workflows()
        primary = workflows["workflow.json"]
        compatibility = workflows["workflow-imap-trigger.json"]

        self.assertEqual(
            [node["name"] for node in compatibility["nodes"]],
            [node["name"] for node in primary["nodes"]],
        )
        self.assertEqual(compatibility["connections"], primary["connections"])

    def test_start_paths_route_through_clean_and_embedding_nodes(self):
        for workflow_name, workflow in self.all_workflows().items():
            nodes = self.nodes_by_name_for(workflow)

            self.assertNotIn("Manual Trigger", nodes, workflow_name)
            self.assertIn("Clean and truncate email", nodes, workflow_name)
            self.assertIn("Generate email embedding", nodes, workflow_name)
            self.assertEqual(
                nodes["Clean and truncate email"]["type"],
                "n8n-nodes-base.code",
                workflow_name,
            )
            self.assertEqual(
                nodes["Generate email embedding"]["type"],
                "n8n-nodes-base.code",
                workflow_name,
            )
            self.assertEqual(
                workflow["connections"]["Loop Over Emails"]["main"][1][0]["node"],
                "Clean and truncate email",
                workflow_name,
            )
            self.assertEqual(
                workflow["connections"]["Skip classified trigger email"]["main"][0][0]["node"],
                "Clean and truncate email",
                workflow_name,
            )
            self.assertEqual(
                workflow["connections"]["Clean and truncate email"]["main"][0][0]["node"],
                "Generate email embedding",
                workflow_name,
            )
            self.assertEqual(
                workflow["connections"]["Generate email embedding"]["main"][0][0]["node"],
                "Build classification prompt",
                workflow_name,
            )
```

Add this test near the existing prompt tests:

```python
    def test_clean_node_normalizes_html_and_truncates_model_text(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Clean and truncate email').parameters.jsCode;
const input = {
  all: () => [{
    json: {
      sender_email: 'sender@example.test',
      email_subject: 'Long body',
      email_body: '<p>Hello&nbsp; <strong>world</strong></p>' + ' x'.repeat(20),
      cleanEmailTextLimit: 18,
    },
  }],
};

(async () => {
  const result = await new AsyncFunction('$input', code)(input);
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

        self.assertEqual(result["cleanEmailText"], "Hello world x x x")
        self.assertGreater(result["cleanEmailTextLength"], len(result["cleanEmailText"]))
        self.assertTrue(result["cleanEmailTruncated"])
        self.assertEqual(result["email_body"], result["cleanEmailText"])
        self.assertLessEqual(len(result["body_preview"]), 500)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest email-classifer/tests/test_workflow_json.py
```

Expected: FAIL because `Clean and truncate email` and `Generate email embedding` do not exist yet.

## Task 2: GREEN Shared Clean/Truncate Node And Wiring

**Files:**
- Create: `email-classifer/code-nodes/clean_and_truncate_email.js`
- Modify: `email-classifer/workflow.json`
- Modify: `email-classifer/workflow-imap-trigger.json`
- Modify: `email-classifer/tests/test_workflow_json.py`

- [ ] **Step 1: Create `clean_and_truncate_email.js`**

Create `email-classifer/code-nodes/clean_and_truncate_email.js` with:

```javascript
const DEFAULT_CLEAN_TEXT_LIMIT = 4000;
const BODY_PREVIEW_LIMIT = 500;

function numberValue(value, fallback, description) {
  const raw = value === undefined || value === null || value === '' ? fallback : value;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 1) {
    throw new Error(`${description} must be a positive number`);
  }
  return parsed;
}

function decodeHtmlEntities(value) {
  return String(value || '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/g, "'");
}

function stripHtml(value) {
  return decodeHtmlEntities(value)
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ');
}

function normalizeWhitespace(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function sourceBody(item) {
  return item.email_body
    ?? item.emailBody
    ?? item.body
    ?? item.textPlain
    ?? item.text
    ?? item.body_preview
    ?? '';
}

const inputItems = $input.all();

return inputItems.map((item) => {
  const json = item.json ?? {};
  const cleanEmailTextLimit = numberValue(
    json.cleanEmailTextLimit ?? json.classifierTextLimit ?? json.emailTextLimit,
    DEFAULT_CLEAN_TEXT_LIMIT,
    'Clean email text limit',
  );
  const normalized = normalizeWhitespace(stripHtml(sourceBody(json)));
  const cleanEmailTruncated = normalized.length > cleanEmailTextLimit;
  const cleanEmailText = cleanEmailTruncated
    ? normalized.slice(0, cleanEmailTextLimit).trim()
    : normalized;

  return {
    json: {
      ...json,
      cleanEmailText,
      cleanEmailTextLength: normalized.length,
      cleanEmailTruncated,
      cleanEmailTextLimit,
      email_body: cleanEmailText,
      body_preview: cleanEmailText.slice(0, BODY_PREVIEW_LIMIT),
    },
  };
});
```

- [ ] **Step 2: Wire clean node and update prompt in both workflow exports**

Run this structured JSON rewrite from the repo root:

```bash
node <<'NODE'
const fs = require('fs');
const path = require('path');

const root = path.join(process.cwd(), 'email-classifer');
const cleanCode = fs.readFileSync(path.join(root, 'code-nodes', 'clean_and_truncate_email.js'), 'utf8');

function codeNode({ id, name, position, jsCode }) {
  return {
    id,
    name,
    type: 'n8n-nodes-base.code',
    typeVersion: 2,
    position,
    parameters: {
      language: 'javaScript',
      jsCode,
    },
  };
}

function upsertNode(workflow, node) {
  const index = workflow.nodes.findIndex((candidate) => candidate.name === node.name);
  if (index >= 0) workflow.nodes[index] = { ...workflow.nodes[index], ...node };
  else workflow.nodes.push(node);
}

function updateBuildPrompt(workflow) {
  const node = workflow.nodes.find((candidate) => candidate.name === 'Build classification prompt');
  const assignments = node.parameters.assignments.assignments;
  const userPrompt = assignments.find((assignment) => assignment.name === 'userPrompt');
  userPrompt.value = '={{ "From: " + ($json.sender_email || "") + "\\nName: " + ($json.sender_name || "") + "\\nSubject: " + ($json.email_subject || "") + "\\nEmail Content:\\n\\n" + ($json.cleanEmailText || "") + "\\n\\nEmbedding metadata:\\n" + JSON.stringify($json.emailEmbedding || {}) }}';
}

function updateWorkflow(filename) {
  const workflowPath = path.join(root, filename);
  const workflow = JSON.parse(fs.readFileSync(workflowPath, 'utf8'));
  upsertNode(workflow, codeNode({
    id: '7b22f4b8-e9da-4f12-8b75-9953adf0e9b1',
    name: 'Clean and truncate email',
    position: [320, 360],
    jsCode: cleanCode,
  }));
  workflow.connections['Loop Over Emails'].main[1][0].node = 'Clean and truncate email';
  workflow.connections['Skip classified trigger email'].main[0][0].node = 'Clean and truncate email';
  workflow.connections['Clean and truncate email'] = {
    main: [[{ node: 'Build classification prompt', type: 'main', index: 0 }]],
  };
  updateBuildPrompt(workflow);
  fs.writeFileSync(workflowPath, `${JSON.stringify(workflow, null, 2)}\n`);
}

updateWorkflow('workflow.json');
updateWorkflow('workflow-imap-trigger.json');
NODE
```

- [ ] **Step 3: Run the clean-node tests and verify GREEN for clean behavior**

Run:

```bash
python3 -m unittest email-classifer/tests/test_workflow_json.py
```

Expected: still FAIL only for missing `Generate email embedding`; `test_clean_node_normalizes_html_and_truncates_model_text` should PASS.

## Task 3: RED/GREEN Embedding Step

**Files:**
- Create: `email-classifer/code-nodes/generate_email_embedding.js`
- Modify: `email-classifer/workflow.json`
- Modify: `email-classifer/workflow-imap-trigger.json`
- Modify: `email-classifer/tests/test_workflow_json.py`

- [ ] **Step 1: Add failing tests for embedding metadata and prompt usage**

Add these tests near the clean-node test:

```python
    def test_generate_embedding_node_uses_ollama_embed_without_returning_vector(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Generate email embedding').parameters.jsCode;
globalThis.fetch = async (url, options) => {
  const payload = JSON.parse(options.body);
  if (!String(url).endsWith('/api/embed')) throw new Error(`Unexpected URL: ${url}`);
  if (payload.input !== 'A clean email') throw new Error(`Unexpected input: ${payload.input}`);
  return {
    ok: true,
    status: 200,
    text: async () => 'ok',
    json: async () => ({
      model: payload.model,
      embeddings: [[0.1, 0.2, 0.3]],
      prompt_eval_count: 7,
      total_duration: 12000000,
    }),
  };
};
const input = {
  all: () => [{
    json: {
      cleanEmailText: 'A clean email',
      embeddingModel: 'embeddinggemma',
      embeddingBaseUrl: 'http://ollama.test:11434',
    },
  }],
};

(async () => {
  const result = await new AsyncFunction('$input', code)(input);
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

        self.assertEqual(result["emailEmbedding"]["status"], "ok")
        self.assertEqual(result["emailEmbedding"]["model"], "embeddinggemma")
        self.assertEqual(result["emailEmbedding"]["dimensions"], 3)
        self.assertEqual(result["emailEmbedding"]["promptEvalCount"], 7)
        self.assertNotIn("embedding", result)
        self.assertNotIn("embeddings", result)
        self.assertNotIn("embeddingVector", result)

    def test_user_prompt_uses_clean_text_and_bounded_embedding_metadata(self):
        assignments = self.build_prompt_assignments()
        value = assignments["userPrompt"]["value"]

        self.assertIn("$json.cleanEmailText", value)
        self.assertIn("$json.emailEmbedding", value)
        self.assertNotIn("$json.email_body", value)
```

Update the existing `test_user_prompt_uses_evaluable_expression` to assert `cleanEmailText` instead of `email_body`:

```python
    def test_user_prompt_uses_evaluable_expression(self):
        assignments = self.build_prompt_assignments()
        value = assignments["userPrompt"]["value"]

        self.assertNotIn("userPromptTemplate", assignments)
        self.assertTrue(value.startswith("={{"))
        self.assertIn("$json.sender_email", value)
        self.assertIn("$json.cleanEmailText", value)
        self.assertNotIn("$json.email_body", value)
        self.assertNotIn("{{ $json.sender_email }}", value)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest email-classifer/tests/test_workflow_json.py
```

Expected: FAIL because `Generate email embedding` does not exist and the prompt still lacks embedding metadata if Task 2 did not insert it yet.

- [ ] **Step 3: Create `generate_email_embedding.js`**

Create `email-classifer/code-nodes/generate_email_embedding.js` with:

```javascript
const DEFAULT_OLLAMA_BASE_URL = 'http://192.168.1.100:11434';
const DEFAULT_EMBEDDING_MODEL = 'embeddinggemma';

function trimTrailingSlash(value) {
  return String(value || '').replace(/\/+$/, '');
}

function numberOrNull(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function embeddingVectorFromResponse(responseJson) {
  if (Array.isArray(responseJson?.embeddings?.[0])) return responseJson.embeddings[0];
  if (Array.isArray(responseJson?.embedding)) return responseJson.embedding;
  return [];
}

async function embedItem(json) {
  const cleanEmailText = String(json.cleanEmailText || '').trim();
  if (!cleanEmailText) {
    return {
      ...json,
      emailEmbedding: {
        status: 'skipped_empty_input',
        model: String(json.embeddingModel || DEFAULT_EMBEDDING_MODEL),
        dimensions: 0,
      },
    };
  }

  const model = String(json.embeddingModel || DEFAULT_EMBEDDING_MODEL);
  const baseUrl = trimTrailingSlash(json.embeddingBaseUrl || json.ollamaBaseUrl || DEFAULT_OLLAMA_BASE_URL);
  const response = await fetch(`${baseUrl}/api/embed`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      input: cleanEmailText,
      truncate: true,
    }),
  });

  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new Error(`Ollama embedding request failed with HTTP ${response.status}: ${body.slice(0, 240)}`);
  }

  const responseJson = await response.json();
  const vector = embeddingVectorFromResponse(responseJson);
  if (!Array.isArray(vector) || vector.length === 0) {
    throw new Error('Ollama embedding response did not include an embedding vector');
  }

  return {
    ...json,
    emailEmbedding: {
      status: 'ok',
      model: String(responseJson.model || model),
      dimensions: vector.length,
      promptEvalCount: numberOrNull(responseJson.prompt_eval_count),
      totalDuration: numberOrNull(responseJson.total_duration),
    },
  };
}

const results = [];
for (const item of $input.all()) {
  results.push({ json: await embedItem(item.json ?? {}) });
}

return results;
```

- [ ] **Step 4: Wire embedding node in both workflow exports**

Run this structured JSON rewrite from the repo root:

```bash
node <<'NODE'
const fs = require('fs');
const path = require('path');

const root = path.join(process.cwd(), 'email-classifer');
const embeddingCode = fs.readFileSync(path.join(root, 'code-nodes', 'generate_email_embedding.js'), 'utf8');

function codeNode({ id, name, position, jsCode }) {
  return {
    id,
    name,
    type: 'n8n-nodes-base.code',
    typeVersion: 2,
    position,
    parameters: {
      language: 'javaScript',
      jsCode,
    },
  };
}

function upsertNode(workflow, node) {
  const index = workflow.nodes.findIndex((candidate) => candidate.name === node.name);
  if (index >= 0) workflow.nodes[index] = { ...workflow.nodes[index], ...node };
  else workflow.nodes.push(node);
}

function upsertAssignment(assignments, assignment) {
  const index = assignments.findIndex((candidate) => candidate.name === assignment.name);
  if (index >= 0) assignments[index] = { ...assignments[index], ...assignment };
  else assignments.push(assignment);
}

function updateConfigureNode(workflow) {
  const node = workflow.nodes.find((candidate) => candidate.name === 'Configure Proton IMAP batch');
  const assignments = node.parameters.assignments.assignments;
  upsertAssignment(assignments, {
    id: 'embedding-base-url',
    name: 'embeddingBaseUrl',
    value: 'http://192.168.1.100:11434',
    type: 'string',
  });
  upsertAssignment(assignments, {
    id: 'embedding-model',
    name: 'embeddingModel',
    value: 'embeddinggemma',
    type: 'string',
  });
}

function updateWorkflow(filename) {
  const workflowPath = path.join(root, filename);
  const workflow = JSON.parse(fs.readFileSync(workflowPath, 'utf8'));
  upsertNode(workflow, codeNode({
    id: '90b2fced-9f64-4471-b596-2a8b8eddb99d',
    name: 'Generate email embedding',
    position: [455, 360],
    jsCode: embeddingCode,
  }));
  workflow.connections['Clean and truncate email'] = {
    main: [[{ node: 'Generate email embedding', type: 'main', index: 0 }]],
  };
  workflow.connections['Generate email embedding'] = {
    main: [[{ node: 'Build classification prompt', type: 'main', index: 0 }]],
  };
  updateConfigureNode(workflow);
  fs.writeFileSync(workflowPath, `${JSON.stringify(workflow, null, 2)}\n`);
}

updateWorkflow('workflow.json');
updateWorkflow('workflow-imap-trigger.json');
NODE
```

- [ ] **Step 5: Run embedding tests and verify GREEN**

Run:

```bash
python3 -m unittest email-classifer/tests/test_workflow_json.py
```

Expected: PASS for workflow-shape, clean-node, embedding-node, and prompt-use tests. Category parser tests may still fail until Task 4.

## Task 4: RED/GREEN Category Parser And Prompt

**Files:**
- Modify: `email-classifer/code-nodes/prepare_proton_label_targets.js`
- Modify: `email-classifer/workflow.json`
- Modify: `email-classifer/workflow-imap-trigger.json`
- Modify: `email-classifer/tests/test_workflow_json.py`

- [ ] **Step 1: Add failing category parser tests**

Add these tests near the existing prepare-target tests:

```python
    def test_prepare_targets_accepts_category_shape(self):
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
    category: { name: 'Schedule', confidence: 0.91 },
    reason: 'Calendar event notification with a time and place',
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

        self.assertEqual(result["category"], {"name": "Schedule", "confidence": 0.91})
        self.assertEqual(result["labels"], [{"label": "Schedule", "confidence": 0.91}])
        self.assertEqual(result["targetMailboxes"], ["Labels/Schedule", "Labels/Classified"])

    def test_category_shape_takes_precedence_over_legacy_labels(self):
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
    category: { name: 'Invoice', confidence: 0.93 },
    labels: [{ label: 'Spam like', confidence: 0.99 }],
    reason: 'Receipt for a paid order',
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

        self.assertEqual(result["category"], {"name": "Invoice", "confidence": 0.93})
        self.assertEqual(result["labels"], [{"label": "Invoice", "confidence": 0.93}])
        self.assertEqual(result["targetMailboxes"], ["Labels/Invoice", "Labels/Classified"])

    def test_unknown_low_confidence_or_uncertain_category_only_targets_classified(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Prepare Proton label targets').parameters.jsCode;
const cases = [
  { category: { name: 'Security alert', confidence: 0.9 }, reason: 'Unknown category' },
  { category: { name: 'Invoice', confidence: 0.5 }, reason: 'Too weak' },
  { category: { name: 'uncertain', confidence: 0.4 }, reason: 'Ambiguous' },
];
const dollar = () => ({
  item: {
    json: {
      uid: '3542',
      sourceFlow: 'bulk',
      runMode: 'apply_labels',
      labelPrefix: 'Labels',
      stateLabel: 'Classified',
    },
  },
});

(async () => {
  const results = [];
  for (const payload of cases) {
    const result = await new AsyncFunction('$', '$json', code)(dollar, { output: JSON.stringify(payload) });
    results.push(result[0].json);
  }
  console.log(JSON.stringify(results));
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
        results = json.loads(completed.stdout)

        for result in results:
            self.assertEqual(result["labels"], [])
            self.assertEqual(result["labelMailboxes"], [])
            self.assertEqual(result["targetMailboxes"], ["Labels/Classified"])
            self.assertEqual(result["category"]["name"], "uncertain")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m unittest email-classifer/tests/test_workflow_json.py
```

Expected: FAIL because `Prepare Proton label targets` does not yet parse `category`.

- [ ] **Step 3: Replace `prepare_proton_label_targets.js`**

Replace `email-classifer/code-nodes/prepare_proton_label_targets.js` with:

```javascript
const source = $('Build classification prompt').item.json;
const allowed = ["Invoice","Purchase","Bill","Payment","Marketing","Cold email","Important","Awaiting reply","Travel","Ticket","Infrastructure","Hustle","Schedule","Spam like"];
const MIN_CONFIDENCE = 0.75;

function clampConfidence(value) {
  const confidence = Number(value ?? 0);
  if (!Number.isFinite(confidence)) return 0;
  return Math.max(0, Math.min(1, confidence));
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
    if (value.category || Array.isArray(value.labels)) return value;
    if ('output' in value) return parseAiOutput(value.output);
  }
  if (typeof value === 'string') {
    return JSON.parse(extractJsonText(value));
  }
  return value;
}

function normalizeCategory(parsed) {
  if (parsed?.category && typeof parsed.category === 'object') {
    return {
      name: String(parsed.category.name ?? parsed.category.label ?? ''),
      confidence: clampConfidence(parsed.category.confidence),
    };
  }

  const labels = Array.isArray(parsed?.labels) ? parsed.labels : [];
  for (const item of labels) {
    const name = String(item?.label ?? item?.name ?? '');
    const confidence = clampConfidence(item?.confidence);
    if (allowed.includes(name) && confidence >= MIN_CONFIDENCE) {
      return { name, confidence };
    }
  }

  const fallbackConfidence = labels.length > 0
    ? clampConfidence(labels[0]?.confidence)
    : 0;
  return { name: 'uncertain', confidence: fallbackConfidence };
}

let parsed;
try {
  parsed = parseAiOutput($json.output ?? $json);
} catch (error) {
  parsed = {
    category: { name: 'uncertain', confidence: 0 },
    reason: 'format violation or instruction conflict',
  };
}

const parsedCategory = normalizeCategory(parsed);
const acceptedCategory = allowed.includes(parsedCategory.name) && parsedCategory.confidence >= MIN_CONFIDENCE
  ? parsedCategory
  : { name: 'uncertain', confidence: parsedCategory.confidence };

const accepted = acceptedCategory.name === 'uncertain'
  ? []
  : [{ label: acceptedCategory.name, confidence: acceptedCategory.confidence }];

const reason = String(
  parsed?.reason ?? (accepted.length ? 'Classifier returned a matching category' : 'No category reached confidence threshold'),
).slice(0, 240);
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
      category: acceptedCategory,
      labels: accepted.length ? accepted : [{ label: 'uncertain', confidence: acceptedCategory.confidence }],
      reason,
    },
    category: acceptedCategory,
    labels: accepted,
    labelMailboxes,
    stateMailbox,
    targetMailboxes,
  },
}];
```

- [ ] **Step 4: Update the system prompt in both workflow exports**

Run this structured JSON rewrite from the repo root:

```bash
node <<'NODE'
const fs = require('fs');
const path = require('path');

const root = path.join(process.cwd(), 'email-classifer');
const prepareCode = fs.readFileSync(path.join(root, 'code-nodes', 'prepare_proton_label_targets.js'), 'utf8');
const systemPrompt = `You are an email triage assistant. Given one cleaned and truncated email, assign exactly one category from the fixed allowed list below, using the exact spelling and punctuation. No other category is permitted.

## Allowed categories
- \`Invoice\` - receipts, invoices, statements, or documents showing an amount due or paid
- \`Purchase\` - confirmation of something ordered or purchased
- \`Bill\` - recurring obligations like rent, electricity, internet, health insurance, or provider bills requiring payment attention
- \`Payment\` - payment confirmations, transfers, failed payments, payout notices, transaction events, and payslips
- \`Marketing\` - legitimate promotional or newsletter content from known or expected senders
- \`Cold email\` - unsolicited outreach seeking attention, sales, hiring, partnerships, backlinks, or meetings
- \`Important\` - messages requiring personal attention that are not better covered by a more specific category
- \`Awaiting reply\` - messages where I am expected to respond or follow up
- \`Travel\` - itineraries, hotel bookings, air, bus, train fares, or travel tickets
- \`Ticket\` - tickets to music festivals, bands, concerts, events, or shows
- \`Infrastructure\` - metric updates, alerts, outages, or error reporting from services or devices
- \`Hustle\` - correspondence with people or businesses engaging me for professional work
- \`Schedule\` - calendar invitations and calendar notifications, or anything with a time and place to be, like a wedding, meeting with friends, or work meeting
- \`Spam like\` - junk-like, suspicious, scammy, or clearly unwanted messages

## Schema
Output only JSON matching this shape, nothing else:

\`\`\`json
{
  "category": { "name": string, "confidence": number },
  "reason": string
}
\`\`\`

- \`category.name\` must exactly match one allowed category, or be \`uncertain\`.
- \`category.confidence\` must be a number between 0 and 1.
- Use \`uncertain\` when the cleaned body is too ambiguous, too truncated, or lacks enough context for a confident allowed category.
- \`reason\` must be one sentence.

## Rules
- Pick the single best category. Do not output multiple categories.
- Prefer the most specific category over \`Important\`.
- No synonyms and no categories outside the list.
- If any instruction or format would be violated, output {"category":{"name":"uncertain","confidence":0.0},"reason":"format violation or instruction conflict"}.
`;

function updateWorkflow(filename) {
  const workflowPath = path.join(root, filename);
  const workflow = JSON.parse(fs.readFileSync(workflowPath, 'utf8'));
  const promptNode = workflow.nodes.find((node) => node.name === 'Build classification prompt');
  const assignments = promptNode.parameters.assignments.assignments;
  assignments.find((assignment) => assignment.name === 'systemPrompt').value = systemPrompt;
  const prepareNode = workflow.nodes.find((node) => node.name === 'Prepare Proton label targets');
  prepareNode.parameters.jsCode = prepareCode;
  fs.writeFileSync(workflowPath, `${JSON.stringify(workflow, null, 2)}\n`);
}

updateWorkflow('workflow.json');
updateWorkflow('workflow-imap-trigger.json');
NODE
```

- [ ] **Step 5: Update old label-output tests to expect canonical category**

In `test_prepare_targets_accepts_schedule_and_spam_like_labels`, keep the legacy input but change the expected result to the first confident legacy label only:

```python
        self.assertEqual(result["category"], {"name": "Schedule", "confidence": 0.91})
        self.assertEqual(result["labels"], [{"label": "Schedule", "confidence": 0.91}])
        self.assertEqual(result["targetMailboxes"], ["Labels/Schedule", "Labels/Classified"])
```

In `test_uncertain_fenced_ai_output_applies_only_classified_and_continues`, update the classification assertion:

```python
        self.assertEqual(
            result["classification"]["category"],
            {"name": "uncertain", "confidence": 0},
        )
```

- [ ] **Step 6: Run category tests and verify GREEN**

Run:

```bash
python3 -m unittest email-classifer/tests/test_workflow_json.py
```

Expected: PASS for all workflow JSON tests.

## Task 5: Multi-IMAP Backfill Regression Tests

**Files:**
- Modify: `email-classifer/tests/test_workflow_json.py`
- Modify only if tests reveal a real gap: `email-classifer/code-nodes/get_next_50_unclassified_emails.js`, `email-classifer/workflow.json`, `email-classifer/workflow-imap-trigger.json`

- [ ] **Step 1: Add regression tests for existing multi-IMAP behavior**

Add these tests after `test_fetch_code_tracks_credential_pairs_per_email`:

```python
    def test_configured_imap_pairs_can_include_multiple_source_mailboxes(self):
        assignments = self.configure_assignments()
        pairs = json.loads(assignments["imapPairsJson"]["value"])

        self.assertGreaterEqual(len(pairs), 2)
        for pair in pairs:
            self.assertIsInstance(pair["sourceMailboxes"], list)
            self.assertGreaterEqual(len(pair["sourceMailboxes"]), 1)
            self.assertIn("userVar", pair)
            self.assertIn("passwordVar", pair)

    def test_fetch_code_caps_batch_across_pairs_and_source_mailboxes(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("for (const pair of credentialPairs)", code)
        self.assertIn("for (const sourceMailbox of pair.sourceMailboxes)", code)
        self.assertIn("if (emails.length >= defaults.batchLimit) break;", code)
        self.assertLess(
            code.index("for (const pair of credentialPairs)"),
            code.index("for (const sourceMailbox of pair.sourceMailboxes)"),
        )
        self.assertGreaterEqual(
            code.count("if (emails.length >= defaults.batchLimit) break;"),
            4,
        )

    def test_fetch_summary_preserves_pair_and_mailbox_for_label_application(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("credentialPairId: config.id", code)
        self.assertIn("credentialPair: publicCredentialPair(config)", code)
        self.assertIn("sourceMailbox: config.sourceMailbox", code)
        self.assertIn("const mailboxConfig = { ...pair, sourceMailbox", code)
```

- [ ] **Step 2: Run tests**

Run:

```bash
python3 -m unittest email-classifer/tests/test_workflow_json.py
```

Expected: PASS. If any test fails, make the minimal production change to `get_next_50_unclassified_emails.js`, sync that Code node into both workflow exports, and rerun the test.

## Task 6: Full Verification And Commit

**Files:**
- Verify all changed files.

- [ ] **Step 1: Compile standalone Code-node source files**

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

Expected: `compiled code nodes`

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

Expected: `compiled workflow code nodes`

- [ ] **Step 3: Run full local tests**

Run:

```bash
python3 -m unittest discover -s email-classifer/tests
```

Expected: all tests pass.

- [ ] **Step 4: Check whitespace**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 5: Inspect diff**

Run:

```bash
git diff -- email-classifer/code-nodes email-classifer/tests email-classifer/workflow.json email-classifer/workflow-imap-trigger.json
```

Expected: diff contains only the clean/truncate node, embedding node, category parser/prompt, workflow wiring, and test updates.

- [ ] **Step 6: Commit implementation**

Run:

```bash
git add email-classifer/code-nodes email-classifer/tests/test_workflow_json.py email-classifer/workflow.json email-classifer/workflow-imap-trigger.json
git commit -m "feat: add email embedding category pipeline"
```

Expected: commit succeeds.
