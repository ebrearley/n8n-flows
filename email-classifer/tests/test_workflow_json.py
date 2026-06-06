import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowJsonTests(unittest.TestCase):
    def load_workflow(self):
        return json.loads((ROOT / "workflow.json").read_text(encoding="utf-8"))

    def test_imap_action_nodes_are_javascript_code_nodes(self):
        workflow = self.load_workflow()
        nodes = {node["name"]: node for node in workflow["nodes"]}

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


if __name__ == "__main__":
    unittest.main()
