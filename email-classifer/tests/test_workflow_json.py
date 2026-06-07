import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowJsonTests(unittest.TestCase):
    def load_workflow(self):
        return json.loads((ROOT / "workflow.json").read_text(encoding="utf-8"))

    def nodes_by_name(self):
        workflow = self.load_workflow()
        return {node["name"]: node for node in workflow["nodes"]}

    def configure_assignments(self):
        node = self.nodes_by_name()["Configure Proton IMAP batch"]
        return {
            assignment["name"]: assignment
            for assignment in node["parameters"]["assignments"]["assignments"]
        }

    def build_prompt_assignments(self):
        node = self.nodes_by_name()["Build classification prompt"]
        return {
            assignment["name"]: assignment
            for assignment in node["parameters"]["assignments"]["assignments"]
        }

    def test_imap_action_nodes_are_javascript_code_nodes(self):
        nodes = self.nodes_by_name()

        for name in (
            "Get next 50 unclassified emails",
            "Apply Proton labels",
            "Apply Proton labels (trigger)",
        ):
            self.assertEqual(nodes[name]["type"], "n8n-nodes-base.code")
            self.assertEqual(nodes[name]["parameters"]["language"], "javaScript")

    def test_workflow_does_not_use_execute_command_nodes(self):
        workflow = self.load_workflow()
        execute_nodes = [
            node["name"]
            for node in workflow["nodes"]
            if node["type"] == "n8n-nodes-base.executeCommand"
        ]

        self.assertEqual(execute_nodes, [])

    def test_configure_node_defines_credential_pair_list(self):
        assignments = self.configure_assignments()
        self.assertIn("imapPairsJson", assignments)
        self.assertEqual(assignments["maxBatches"]["value"], 1)

        pairs = json.loads(assignments["imapPairsJson"]["value"])
        self.assertIsInstance(pairs, list)
        self.assertGreaterEqual(len(pairs), 1)

        first_pair = pairs[0]
        for key in (
            "id",
            "host",
            "port",
            "hostVar",
            "portVar",
            "startTls",
            "userVar",
            "passwordVar",
            "sourceMailboxes",
        ):
            self.assertIn(key, first_pair)
        self.assertIsInstance(first_pair["sourceMailboxes"], list)

    def test_fetch_code_tracks_credential_pairs_per_email(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("imapPairsJson", code)
        self.assertIn("sourceMailboxes", code)
        self.assertIn("credentialPairId", code)
        self.assertIn("hostVar", code)
        self.assertIn("portVar", code)

    def test_apply_code_uses_email_credential_pair(self):
        code = self.nodes_by_name()["Apply Proton labels"]["parameters"]["jsCode"]

        self.assertIn("item.credentialPair", code)
        self.assertIn("pair.userVar", code)
        self.assertIn("pair.passwordVar", code)
        self.assertIn("pair.hostVar", code)
        self.assertIn("pair.portVar", code)

    def test_apply_code_skips_all_labels_when_target_mailbox_is_missing(self):
        nodes = self.nodes_by_name()

        for name in ("Apply Proton labels", "Apply Proton labels (trigger)"):
            code = nodes[name]["parameters"]["jsCode"]
            self.assertIn("missingMailboxes", code)
            self.assertIn("label_application_skipped", code)
            self.assertIn("skipped_missing_mailbox", code)
            self.assertNotIn("Required Proton label mailbox does not exist", code)

    def test_email_items_include_recipient_fields_for_missing_label_debugging(self):
        nodes = self.nodes_by_name()
        fetch_code = nodes["Get next 50 unclassified emails"]["parameters"]["jsCode"]
        trigger_code = nodes["Normalize trigger email"]["parameters"]["jsCode"]
        apply_code = nodes["Apply Proton labels"]["parameters"]["jsCode"]

        self.assertIn("recipientParts", fetch_code)
        self.assertIn("headers.to", fetch_code)
        self.assertIn("recipient_email", fetch_code)
        self.assertIn("const recipient = parseSender", trigger_code)
        self.assertIn("recipient_email", trigger_code)
        self.assertIn("...item", apply_code)

    def test_fetch_checks_classified_state_with_headers_before_fetching_body(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("fetchHeaders", code)
        self.assertIn("BODY.PEEK[HEADER]", code)
        self.assertLess(code.index("fetchHeaders(uid"), code.index("fetchRaw(uid"))

    def test_fetch_has_setup_batch_limit_to_prevent_unbounded_manual_runs(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("maxBatches", code)
        self.assertIn("max_batches_reached", code)
        self.assertIn("runIndex >= defaults.maxBatches", code)

    def test_bulk_fetch_has_visible_stop_guard_for_empty_batches(self):
        nodes = self.nodes_by_name()
        self.assertIn("Stop if no fetched emails", nodes)

        guard_code = nodes["Stop if no fetched emails"]["parameters"]["jsCode"]
        self.assertIn("total_emails", guard_code)
        self.assertIn("return []", guard_code)

        workflow = self.load_workflow()
        self.assertEqual(
            workflow["connections"]["Get next 50 unclassified emails"]["main"][0][0]["node"],
            "Stop if no fetched emails",
        )
        self.assertEqual(
            workflow["connections"]["Stop if no fetched emails"]["main"][0][0]["node"],
            "Expand fetched emails",
        )

    def test_tls_servername_is_not_set_for_ip_hosts(self):
        nodes = self.nodes_by_name()

        for name in ("Get next 50 unclassified emails", "Apply Proton labels"):
            code = nodes[name]["parameters"]["jsCode"]
            self.assertIn("net.isIP(this.host)", code)
            self.assertNotIn("servername: this.host", code)

    def test_user_prompt_uses_evaluable_expression(self):
        assignments = self.build_prompt_assignments()
        value = assignments["userPrompt"]["value"]

        self.assertNotIn("userPromptTemplate", assignments)
        self.assertTrue(value.startswith("={{"))
        self.assertIn("$json.sender_email", value)
        self.assertIn("$json.email_body", value)
        self.assertNotIn("{{ $json.sender_email }}", value)

    def test_ollama_model_uses_installed_name(self):
        nodes = self.nodes_by_name()

        self.assertEqual(
            nodes["Ollama Chat Model"]["parameters"]["model"],
            "odytrice/gemma4-26b:4090",
        )

    def test_workflow_stops_on_model_errors_during_setup(self):
        node = self.nodes_by_name()["Classify with Ollama"]

        self.assertFalse(node.get("retryOnFail", False))
        self.assertNotIn("maxTries", node)
        self.assertNotIn("waitBetweenTries", node)

    def test_uncertain_fenced_ai_output_applies_only_classified_and_continues(self):
        workflow = self.load_workflow()
        nodes = self.nodes_by_name()
        classify_node = nodes["Classify with Ollama"]

        self.assertFalse(classify_node["parameters"].get("hasOutputParser", False))
        self.assertNotIn("Classification JSON Parser", workflow["connections"])

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
  output: '```json\n{\n  "labels": [\n    {\n      "label": "uncertain",\n      "confidence": 0.0\n    }\n  ],\n  "reason": "The email is an appointment confirmation, but it does not clearly fit into the specific categories provided."\n}\n```',
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
            result["classification"]["labels"],
            [{"label": "uncertain", "confidence": 0}],
        )
        self.assertEqual(result["labels"], [])
        self.assertEqual(result["labelMailboxes"], [])
        self.assertEqual(result["targetMailboxes"], ["Labels/Classified"])
        self.assertEqual(result["runMode"], "apply_labels")


if __name__ == "__main__":
    unittest.main()
