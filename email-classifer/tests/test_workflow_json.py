import json
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


if __name__ == "__main__":
    unittest.main()
