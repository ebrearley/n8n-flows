import json
import importlib.util
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

    def run_step_telemetry_helper(self, filename, input_items):
        script = f"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {{}}).constructor;
const inputJson = JSON.parse(fs.readFileSync(0, 'utf8'));
const code = fs.readFileSync('code-nodes/{filename}', 'utf8');
const inputItems = inputJson.map((json) => ({{ json }}));
const $input = {{
  all: () => inputItems,
  first: () => inputItems[0],
}};

(async () => {{
  const result = await new AsyncFunction('$input', '$json', code)(
    $input,
    inputItems[0]?.json ?? {{}},
  );
  console.log(JSON.stringify(result));
}})().catch((error) => {{
  console.error(error);
  process.exit(1);
}});
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            input=json.dumps(input_items),
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def run_workflow_code_node(self, node_name, input_items, lookups=None):
        script = """
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const inputJson = JSON.parse(fs.readFileSync(0, 'utf8'));
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === inputJson.node_name).parameters.jsCode;
const inputItems = inputJson.input_items;
const lookups = inputJson.lookups || {};
const $input = {
  all: () => inputItems,
  first: () => inputItems[0],
};
const $ = (name) => {
  const items = lookups[name] || [];
  return {
    all: () => items,
    item: { json: items[0]?.json || {} },
  };
};

(async () => {
  const result = await new AsyncFunction('$input', '$json', '$', code)(
    $input,
    inputItems[0]?.json ?? {},
    $,
  );
  console.log(JSON.stringify(result));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            input=json.dumps(
                {
                    "node_name": node_name,
                    "input_items": input_items,
                    "lookups": lookups or {},
                },
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def load_step_telemetry_generator(self):
        path = ROOT / "tools" / "add_step_telemetry.py"
        spec = importlib.util.spec_from_file_location("add_step_telemetry", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

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

    def test_backfill_form_trigger_starts_same_bulk_path(self):
        workflow = self.load_workflow()
        nodes = self.nodes_by_name()

        self.assertIn("Backfill Form Trigger", nodes)
        form_trigger = nodes["Backfill Form Trigger"]
        self.assertEqual(form_trigger["type"], "n8n-nodes-base.formTrigger")
        self.assertEqual(form_trigger["parameters"]["path"], "email-organiser-backfill")
        self.assertEqual(
            workflow["connections"]["Backfill Form Trigger"]["main"][0][0]["node"],
            "Telemetry start run",
        )
        self.assertEqual(
            workflow["connections"]["Manual Trigger"]["main"][0][0]["node"],
            "Telemetry start run",
        )
        self.assertEqual(
            workflow["connections"]["Telemetry restore step start: Configure batch"]["main"][0][0]["node"],
            "Configure Proton IMAP batch",
        )

    def test_configure_node_defines_credential_pair_list(self):
        assignments = self.configure_assignments()
        self.assertIn("imapPairsJson", assignments)
        self.assertEqual(assignments["maxBatches"]["value"], 0)
        self.assertEqual(assignments["rawFetchByteLimit"]["value"], 65536)
        self.assertEqual(assignments["fetchWatchdogMs"]["value"], 120000)
        self.assertEqual(assignments["uidSearchWindow"]["value"], 500)

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
        self.assertIn("$input.first()?.json", code)
        self.assertLess(code.index("$input.first()?.json"), code.index("$('Configure Proton IMAP batch')"))
        self.assertIn("telemetryFromConfig", code)
        self.assertIn("run_id: config.telemetry?.run_id", code)

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

    def test_trigger_items_include_first_imap_credential_pair_metadata(self):
        code = self.nodes_by_name()["Normalize trigger email"]["parameters"]["jsCode"]

        self.assertIn("credentialPair", code)
        self.assertIn("IMAP_1_USER", code)
        self.assertIn("IMAP_1_PASSWORD", code)
        self.assertIn("IMAP_1_HOST", code)
        self.assertIn("IMAP_1_PORT", code)

    def test_trigger_normalizer_uses_imap_metadata_uid_message_id_and_html_body(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Normalize trigger email').parameters.jsCode;
const json = {
  attributes: { uid: 42 },
  metadata: { 'message-id': '<trigger-message@example.test>' },
  from: '"Example" <sender@example.test>',
  to: '<recipient@example.test>',
  subject: 'Calendar invitation',
  textPlain: '',
  textHtml: '<p>Meet at 4pm in Brunswick.</p>',
};

(async () => {
  const result = await new AsyncFunction('$json', code)(json);
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

        self.assertEqual(result["uid"], "42")
        self.assertEqual(result["message_id"], "<trigger-message@example.test>")
        self.assertIn("Meet at 4pm", result["email_body"])

    def test_fetch_checks_classified_state_with_headers_before_fetching_body(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("fetchHeaders", code)
        self.assertIn("BODY.PEEK[HEADER.FIELDS", code)
        self.assertLess(code.index("fetchHeaders(uid"), code.index("fetchRaw(uid"))

    def test_fetch_limits_imap_header_and_body_payloads(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("SOURCE_HEADER_FIELDS", code)
        self.assertIn("MESSAGE_ID_HEADER_FIELDS", code)
        self.assertIn("BODY.PEEK[]<0.", code)
        self.assertIn("rawFetchByteLimit", code)

    def test_fetch_has_watchdog_with_stage_progress(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("fetchWatchdogMs", code)
        self.assertIn("Fetch watchdog exceeded", code)
        self.assertIn("progress.stage", code)
        self.assertIn("JSON.stringify(progress)", code)

    def test_fetch_scans_source_by_bounded_uid_ranges_before_fetching_candidates(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("uidNext", code)
        self.assertIn("searchUidRange", code)
        self.assertIn("uidSearchWindow", code)
        self.assertIn("searchMessageId(stateMailbox", code)
        self.assertIn("fetchHeadersForUids", code)
        self.assertNotIn("searchAll(sourceMailbox", code)
        self.assertNotIn("fetchMessageIds(stateMailbox", code)

    def test_fetch_supports_optional_batch_limit_without_capping_manual_backfill(self):
        assignments = self.configure_assignments()
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertEqual(assignments["maxBatches"]["value"], 0)
        self.assertIn("maxBatches", code)
        self.assertIn("max_batches_reached", code)
        self.assertIn("runIndex >= defaults.maxBatches", code)

    def test_bulk_fetch_has_visible_stop_guard_for_empty_batches(self):
        nodes = self.nodes_by_name()
        self.assertIn("Stop if no fetched emails", nodes)
        self.assertIn("Fetched emails?", nodes)

        guard_code = nodes["Stop if no fetched emails"]["parameters"]["jsCode"]
        self.assertIn("total_emails", guard_code)
        self.assertIn("has_fetched_emails", guard_code)
        self.assertNotIn("return []", guard_code)

        workflow = self.load_workflow()
        self.assertEqual(
            workflow["connections"]["Get next 50 unclassified emails"]["main"][0][0]["node"],
            "Telemetry finish step: Fetch next unclassified emails",
        )
        self.assertEqual(
            workflow["connections"]["Telemetry restore step finish: Fetch next unclassified emails"]["main"][0][0]["node"],
            "Stop if no fetched emails",
        )
        self.assertEqual(
            workflow["connections"]["Stop if no fetched emails"]["main"][0][0]["node"],
            "Fetched emails?",
        )
        self.assertEqual(
            workflow["connections"]["Fetched emails?"]["main"][0][0]["node"],
            "Telemetry start step: Expand fetched emails",
        )
        self.assertEqual(
            workflow["connections"]["Telemetry restore step start: Expand fetched emails"]["main"][0][0]["node"],
            "Expand fetched emails",
        )
        self.assertEqual(
            workflow["connections"]["Fetched emails?"]["main"][1][0]["node"],
            "Telemetry start step: Finish run",
        )
        self.assertEqual(
            workflow["connections"]["Telemetry restore step start: Finish run"]["main"][0][0]["node"],
            "Telemetry finish run",
        )

    def test_loop_done_path_collapses_to_one_control_item_before_next_fetch(self):
        workflow = self.load_workflow()
        nodes = self.nodes_by_name()

        self.assertIn("Prepare next fetch control item", nodes)
        self.assertEqual(
            workflow["connections"]["Loop Over Emails"]["main"][0][0]["node"],
            "Prepare next fetch control item",
        )
        self.assertEqual(
            workflow["connections"]["Prepare next fetch control item"]["main"][0][0]["node"],
            "Telemetry start step: Fetch next unclassified emails",
        )

        code = nodes["Prepare next fetch control item"]["parameters"]["jsCode"]
        self.assertIn("$input.first()?.json", code)
        self.assertIn("return [{", code)
        self.assertIn("telemetry: telemetrySource", code)
        self.assertNotIn("email_body", code)
        self.assertNotIn("body_preview", code)

        result = self.run_workflow_code_node(
            "Prepare next fetch control item",
            [
                {
                    "json": {
                        "email_subject": "private subject",
                        "email_body": "private body",
                        "batchLimit": 50,
                        "telemetry": {"run_id": "run-from-email"},
                    },
                },
                {
                    "json": {
                        "email_subject": "another private subject",
                        "email_body": "another private body",
                    },
                },
            ],
            {
                "Configure Proton IMAP batch": [
                    {
                        "json": {
                            "batchLimit": 50,
                            "maxBatches": 3,
                            "imapPairsJson": "[]",
                            "telemetry": {"run_id": "run-from-config"},
                        },
                    },
                ],
            },
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["json"]["telemetry"]["run_id"], "run-from-config")
        self.assertEqual(result[0]["json"]["batchLimit"], 50)
        self.assertEqual(result[0]["json"]["maxBatches"], 3)
        self.assertNotIn("email_subject", result[0]["json"])
        self.assertNotIn("email_body", result[0]["json"])

    def test_loop_over_emails_resets_only_for_fresh_fetch_batches(self):
        nodes = self.nodes_by_name()
        workflow = self.load_workflow()

        loop = nodes["Loop Over Emails"]
        self.assertEqual(loop["parameters"]["options"]["reset"], "={{ $json.resetLoop === true }}")

        expand_code = nodes["Expand fetched emails"]["parameters"]["jsCode"]
        self.assertIn("resetLoop: true", expand_code)
        self.assertEqual(
            workflow["connections"]["Telemetry restore email item payload"]["main"][0][0]["node"],
            "Loop Over Emails",
        )

        apply_code = nodes["Apply Proton labels"]["parameters"]["jsCode"]
        self.assertIn("resetLoop: false", apply_code)
        result = self.run_workflow_code_node(
            "Apply Proton labels",
            [
                {
                    "json": {
                        "dryRun": True,
                        "resetLoop": True,
                        "targetMailboxes": ["Labels/Classified"],
                        "credentialPair": {"id": "imap-1"},
                    },
                },
            ],
        )
        self.assertEqual(result[0]["json"]["resetLoop"], False)

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

    def test_telemetry_uses_postgres_nodes_not_execute_command(self):
        workflow = self.load_workflow()
        telemetry_nodes = [
            node for node in workflow["nodes"] if node["name"].startswith("Telemetry ")
        ]

        self.assertGreaterEqual(len(telemetry_nodes), 8)
        self.assertTrue(
            any(node["type"] == "n8n-nodes-base.postgres" for node in telemetry_nodes),
        )
        self.assertFalse(
            any(node["type"] == "n8n-nodes-base.executeCommand" for node in telemetry_nodes),
        )

    def test_step_telemetry_code_sanitizes_payloads(self):
        start_code = (ROOT / "code-nodes" / "telemetry_start_step.js").read_text(encoding="utf-8")
        finish_code = (ROOT / "code-nodes" / "telemetry_finish_step.js").read_text(encoding="utf-8")

        for code in (start_code, finish_code):
            self.assertIn("sanitizeForStepTelemetry", code)
            self.assertIn("body_preview", code)
            self.assertIn("slice(0, 500)", code)
            self.assertIn("password", code)
            self.assertIn("N8N_API_KEY", code)
            self.assertNotIn("email_body: item.email_body", code)

        input_items = [
            {
                "uid": "1",
                "telemetry": {"run_id": "11111111-1111-1111-1111-111111111111"},
                "telemetry_step_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "telemetry_step_name": "Stage one",
                "telemetry_step_type": "n8n-stage",
                "telemetry_step_sort_order": 10,
                "email_body": "first body",
            },
            {
                "uid": "2",
                "telemetry": {"run_id": "22222222-2222-2222-2222-222222222222"},
                "telemetry_step_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                "telemetry_step_name": "Stage two",
                "telemetry_step_type": "n8n-stage",
                "telemetry_step_sort_order": 20,
                "email_body": "second body",
            },
        ]

        start_result = self.run_step_telemetry_helper("telemetry_start_step.js", input_items)
        finish_result = self.run_step_telemetry_helper("telemetry_finish_step.js", input_items)

        for result, params_name in (
            (start_result, "telemetry_step_params"),
            (finish_result, "telemetry_step_finish_params"),
        ):
            self.assertEqual(len(result), 2)
            for index, output_item in enumerate(result):
                self.assertEqual(output_item["pairedItem"], index)
                self.assertEqual(output_item["json"]["uid"], input_items[index]["uid"])
                self.assertEqual(output_item["json"]["telemetry_step_source_index"], index)
                self.assertEqual(output_item["json"][params_name][-1], index)

        full_body = "x" * 700
        malicious_items = [
            {
                "uid": "9",
                "telemetry": {"run_id": "99999999-9999-9999-9999-999999999999"},
                "telemetry_step_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "telemetry_step_name": "Sensitive stage",
                "telemetry_step_type": "n8n-stage",
                "telemetry_step_sort_order": 90,
                "email_body": full_body,
                "raw_content": "raw-secret-value",
                "IMAP_1_PASSWORD": "imap-secret-value",
                "api_key": "api-secret-value",
                "destination_actions": {
                    "Inbox": {
                        "api_key": "nested-api-secret",
                        "raw_content": "nested-raw-secret-value",
                    },
                },
            }
        ]
        sensitive_values = (
            full_body,
            "raw_content",
            "raw-secret-value",
            "imap-secret-value",
            "api-secret-value",
            "nested-api-secret",
            "nested-raw-secret-value",
        )

        for filename, params_name, json_param_index in (
            ("telemetry_start_step.js", "telemetry_step_params", 5),
            ("telemetry_finish_step.js", "telemetry_step_finish_params", 3),
        ):
            result = self.run_step_telemetry_helper(filename, malicious_items)
            params = result[0]["json"][params_name]
            params_text = json.dumps(params)
            sanitized_json = json.loads(params[json_param_index])

            self.assertEqual(params[-1], 0)
            self.assertEqual(sanitized_json["body_preview"], "x" * 500)
            for value in sensitive_values:
                self.assertNotIn(value, params_text)

        for code in (start_code, finish_code):
            self.assertNotIn("payloadJson(item)", code)

    def test_step_telemetry_nodes_are_generated_and_use_query_replacement(self):
        workflow = self.load_workflow()
        trigger_export = json.loads(
            (ROOT / "workflow-imap-trigger.json").read_text(encoding="utf-8"),
        )
        nodes = self.nodes_by_name()
        trigger_nodes = {node["name"]: node for node in trigger_export["nodes"]}
        expected_stages = {
            "Start run": {
                "node": "Telemetry restore start payload",
                "sort": 10,
            },
            "Configure batch": {
                "node": "Configure Proton IMAP batch",
                "sort": 20,
            },
            "Fetch next unclassified emails": {
                "node": "Get next 50 unclassified emails",
                "sort": 30,
            },
            "Expand fetched emails": {
                "node": "Expand fetched emails",
                "sort": 40,
            },
            "Build classification prompt": {
                "node": "Build classification prompt",
                "sort": 50,
            },
            "Classify with Ollama": {
                "node": "Classify with Ollama",
                "sort": 60,
            },
            "Prepare Proton label targets": {
                "node": "Prepare Proton label targets",
                "sort": 70,
            },
            "Apply Proton labels": {
                "node": "Apply Proton labels",
                "sort": 80,
            },
            "Apply Proton labels (trigger)": {
                "node": "Apply Proton labels (trigger)",
                "sort": 85,
            },
            "Finish run": {
                "node": "Telemetry finish run",
                "sort": 100,
            },
        }

        for stage, config in expected_stages.items():
            target_node = config["node"]
            start_name = f"Telemetry start step: {stage}"
            record_name = f"Telemetry record step: {stage}"
            restore_start_name = f"Telemetry restore step start: {stage}"
            finish_name = f"Telemetry finish step: {stage}"
            update_name = f"Telemetry update step: {stage}"
            restore_finish_name = f"Telemetry restore step finish: {stage}"

            for name in (
                start_name,
                record_name,
                restore_start_name,
                finish_name,
                update_name,
                restore_finish_name,
            ):
                self.assertIn(name, nodes)
                self.assertIn(name, trigger_nodes)

            self.assertEqual(nodes[start_name]["type"], "n8n-nodes-base.code")
            self.assertEqual(nodes[finish_name]["type"], "n8n-nodes-base.code")
            self.assertEqual(nodes[record_name]["type"], "n8n-nodes-base.postgres")
            self.assertEqual(nodes[update_name]["type"], "n8n-nodes-base.postgres")
            start_code = nodes[start_name]["parameters"]["jsCode"]
            self.assertIn(
                f"const TELEMETRY_STEP_NAME = {json.dumps(stage)};",
                start_code,
            )
            self.assertIn(
                f"const TELEMETRY_STEP_SORT_ORDER = {config['sort']};",
                start_code,
            )
            self.assertEqual(
                workflow["connections"][start_name]["main"][0][0]["node"],
                record_name,
            )
            self.assertEqual(
                workflow["connections"][record_name]["main"][0][0]["node"],
                restore_start_name,
            )
            self.assertEqual(
                workflow["connections"][restore_start_name]["main"][0][0]["node"],
                target_node,
            )
            self.assertEqual(
                workflow["connections"][target_node]["main"][0][0]["node"],
                finish_name,
            )
            self.assertEqual(
                workflow["connections"][finish_name]["main"][0][0]["node"],
                update_name,
            )
            self.assertEqual(
                workflow["connections"][update_name]["main"][0][0]["node"],
                restore_finish_name,
            )

            restore_start_code = nodes[restore_start_name]["parameters"]["jsCode"]
            restore_finish_code = nodes[restore_finish_name]["parameters"]["jsCode"]
            self.assertIn(f"$('{start_name}').all()", restore_start_code)
            self.assertIn("source_index", restore_start_code)
            self.assertIn("telemetry_step_source_index", restore_start_code)
            self.assertIn("telemetry_step_id", restore_start_code)
            self.assertIn(f"$('{finish_name}').all()", restore_finish_code)
            self.assertIn("source_index", restore_finish_code)
            self.assertIn("telemetry_step_source_index", restore_finish_code)

        step_telemetry_names = {
            name
            for name in nodes
            if name.startswith("Telemetry start step: ")
            or name.startswith("Telemetry record step: ")
            or name.startswith("Telemetry restore step start: ")
            or name.startswith("Telemetry finish step: ")
            or name.startswith("Telemetry update step: ")
            or name.startswith("Telemetry restore step finish: ")
        }
        trigger_step_telemetry_names = {
            name
            for name in trigger_nodes
            if name.startswith("Telemetry start step: ")
            or name.startswith("Telemetry record step: ")
            or name.startswith("Telemetry restore step start: ")
            or name.startswith("Telemetry finish step: ")
            or name.startswith("Telemetry update step: ")
            or name.startswith("Telemetry restore step finish: ")
        }
        self.assertEqual(trigger_step_telemetry_names, step_telemetry_names)

        postgres_step_nodes = [
            node for node in workflow["nodes"]
            if node["name"].startswith("Telemetry record step: ")
            or node["name"].startswith("Telemetry update step: ")
        ]
        self.assertEqual(len(postgres_step_nodes), len(expected_stages) * 2)
        for node in postgres_step_nodes:
            query = node["parameters"]["query"]
            options = node["parameters"].get("options", {})
            self.assertEqual(node["type"], "n8n-nodes-base.postgres")
            self.assertIn("queryReplacement", options)
            self.assertNotIn("queryParameters", json.dumps(node))
            self.assertNotIn("payload_json", query)
            self.assertFalse(node.get("continueOnFail", False))
            self.assertEqual(
                node["credentials"]["postgres"]["id"],
                "wspg_a409ed51b8f18c5e",
            )
            self.assertEqual(
                node["credentials"]["postgres"]["name"],
                "Workflow Status Postgres",
            )

            if node["name"].startswith("Telemetry record step: "):
                self.assertEqual(
                    options["queryReplacement"],
                    "={{ $json.telemetry_step_params }}",
                )
                self.assertIn("RETURNING id AS step_id, $7::int AS source_index", query)
            else:
                self.assertEqual(
                    options["queryReplacement"],
                    "={{ $json.telemetry_step_finish_params }}",
                )
                self.assertIn("WHEN EXISTS (SELECT 1 FROM updated)", query)
                self.assertIn("THEN $6::int", query)
                self.assertIn("1 / (SELECT count(*)::int FROM updated)", query)

        self.assertEqual(
            workflow["connections"]["From bulk loop?"]["main"][1][0]["node"],
            "Telemetry start step: Apply Proton labels (trigger)",
        )
        self.assertEqual(
            workflow["connections"]["Telemetry restore step start: Apply Proton labels (trigger)"]["main"][0][0]["node"],
            "Apply Proton labels (trigger)",
        )
        self.assertEqual(
            workflow["connections"]["Apply Proton labels (trigger)"]["main"][0][0]["node"],
            "Telemetry finish step: Apply Proton labels (trigger)",
        )
        self.assertEqual(
            workflow["connections"]["Telemetry restore step finish: Apply Proton labels (trigger)"]["main"][0][0]["node"],
            "Telemetry build label actions (trigger)",
        )

    def test_generated_step_start_overrides_previous_stage_metadata(self):
        result = self.run_workflow_code_node(
            "Telemetry start step: Build classification prompt",
            [
                {
                    "json": {
                        "telemetry": {"run_id": "11111111-1111-1111-1111-111111111111"},
                        "telemetry_step_name": "Fetch next unclassified emails",
                        "telemetry_step_type": "previous-stage",
                        "telemetry_step_sort_order": 30,
                        "uid": "42",
                    },
                },
            ],
        )
        output = result[0]["json"]

        self.assertEqual(output["telemetry_step_name"], "Build classification prompt")
        self.assertEqual(output["telemetry_step_type"], "n8n-stage")
        self.assertEqual(output["telemetry_step_sort_order"], 50)
        self.assertEqual(output["telemetry_step_params"][1], "Build classification prompt")
        self.assertEqual(output["telemetry_step_params"][2], "n8n-stage")
        self.assertEqual(output["telemetry_step_params"][3], 50)

    def test_generated_finish_step_recovers_step_id_for_replaced_and_fanned_out_items(self):
        step_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        result = self.run_workflow_code_node(
            "Telemetry finish step: Expand fetched emails",
            [
                {"json": {"uid": "1"}, "pairedItem": {"item": 0}},
                {"json": {"uid": "2"}, "pairedItem": {"item": 0}},
            ],
            lookups={
                "Telemetry restore step start: Expand fetched emails": [
                    {
                        "json": {
                            "telemetry_step_id": step_id,
                            "telemetry_step_source_index": 0,
                        },
                    },
                ],
            },
        )

        self.assertEqual(result[0]["json"]["telemetry_step_id"], step_id)
        self.assertEqual(result[1]["json"]["telemetry_step_id"], step_id)
        self.assertEqual(result[0]["json"]["telemetry_step_finish_params"][0], step_id)
        self.assertEqual(result[1]["json"]["telemetry_step_finish_params"][0], step_id)
        self.assertEqual(result[0]["json"]["telemetry_step_finish_params"][-1], 0)
        self.assertEqual(result[1]["json"]["telemetry_step_finish_params"][-1], 1)

    def test_step_telemetry_generator_rejects_multi_output_stage_targets(self):
        generator = self.load_step_telemetry_generator()
        workflow = {
            "nodes": [{"name": "Multi output target", "position": [0, 0]}],
            "connections": {
                "Multi output target": {
                    "main": [
                        [{"node": "First output", "type": "main", "index": 0}],
                        [{"node": "Second output", "type": "main", "index": 0}],
                    ],
                },
            },
        }

        with self.assertRaisesRegex(ValueError, "non-empty non-zero main output"):
            generator.validate_stage_target_outputs(
                workflow,
                {"stage": "Unsupported", "node": "Multi output target"},
            )

    def test_telemetry_postgres_nodes_stop_on_error_during_setup(self):
        for node in self.load_workflow()["nodes"]:
            if node["name"].startswith("Telemetry ") and node["type"] == "n8n-nodes-base.postgres":
                self.assertFalse(node.get("continueOnFail", False))
                self.assertEqual(
                    node["credentials"]["postgres"]["name"],
                    "Workflow Status Postgres",
                )

    def test_telemetry_records_ai_model_tokens_and_label_actions(self):
        workflow = self.load_workflow()
        text = json.dumps(workflow)

        self.assertIn("classification_attempts", text)
        self.assertIn("label_actions", text)
        self.assertIn("estimated_prompt_tokens", text)
        self.assertIn("odytrice/gemma4-26b:4090", text)

    def test_telemetry_inserts_classification_and_label_actions_by_ids(self):
        nodes = self.nodes_by_name()
        classification_code = nodes["Telemetry build classification attempt"]["parameters"]["jsCode"]
        label_code = nodes["Telemetry build label actions"]["parameters"]["jsCode"]

        self.assertIn("source.telemetry?.run_id", classification_code)
        self.assertIn("source.email_item_id", classification_code)
        self.assertNotIn("source.telemetry?.run_key,\n      source.credentialPairId", classification_code)
        self.assertIn("item.telemetry?.run_id", label_code)
        self.assertIn("item.email_item_id", label_code)

        classification_query = nodes["Telemetry record classification attempt"]["parameters"]["query"]
        label_query = nodes["Telemetry record label action"]["parameters"]["query"]
        finish_code = nodes["Telemetry finish run"]["parameters"]["jsCode"]
        finish_query = nodes["Telemetry update finished run"]["parameters"]["query"]

        self.assertIn("NULLIF($1, '')::uuid", classification_query)
        self.assertIn("NULLIF($2, '')::uuid", classification_query)
        self.assertNotIn("metadata->>'run_key'", classification_query)
        self.assertNotIn("WHERE account_id = $2", classification_query)
        self.assertIn("NULLIF($1, '')::uuid", label_query)
        self.assertIn("NULLIF($2, '')::uuid", label_query)
        self.assertNotIn("metadata->>'run_key'", label_query)
        self.assertIn("telemetry.run_id", finish_code)
        self.assertIn("WHERE id = NULLIF($1, '')::uuid", finish_query)
        self.assertNotIn("metadata->>'run_key'", finish_query)

    def test_telemetry_preserves_payload_after_postgres_writes(self):
        workflow = self.load_workflow()
        nodes = self.nodes_by_name()
        text = json.dumps(workflow)

        self.assertIn("payload_json", text)
        self.assertIn("telemetry_payload_json", text)
        self.assertIn("jsonb_set", text)
        self.assertIn("Telemetry restore start payload", nodes)
        self.assertIn("Telemetry restore email item payload", nodes)
        self.assertIn("Telemetry restore classification payload", nodes)
        self.assertIn("Telemetry restore label action payload", nodes)

    def test_telemetry_is_wired_into_bulk_and_trigger_paths(self):
        workflow = self.load_workflow()
        connections = workflow["connections"]

        self.assertEqual(
            connections["Manual Trigger"]["main"][0][0]["node"],
            "Telemetry start run",
        )
        self.assertEqual(
            connections["Telemetry upsert workflow and run"]["main"][0][0]["node"],
            "Telemetry start step: Start run",
        )
        self.assertEqual(
            connections["Telemetry restore step start: Start run"]["main"][0][0]["node"],
            "Telemetry restore start payload",
        )
        self.assertEqual(
            connections["Telemetry restore step finish: Start run"]["main"][0][0]["node"],
            "Telemetry start step: Configure batch",
        )
        self.assertEqual(
            connections["Telemetry restore step start: Configure batch"]["main"][0][0]["node"],
            "Configure Proton IMAP batch",
        )
        self.assertEqual(
            connections["Telemetry restore step finish: Configure batch"]["main"][0][0]["node"],
            "Telemetry start step: Fetch next unclassified emails",
        )
        self.assertEqual(
            connections["Telemetry restore step start: Fetch next unclassified emails"]["main"][0][0]["node"],
            "Get next 50 unclassified emails",
        )
        self.assertEqual(
            connections["Normalize trigger email"]["main"][0][0]["node"],
            "Telemetry start run (trigger)",
        )
        self.assertEqual(
            connections["Telemetry restore email item payload (trigger)"]["main"][0][0]["node"],
            "Telemetry start step: Build classification prompt",
        )
        self.assertEqual(
            connections["Telemetry restore step start: Build classification prompt"]["main"][0][0]["node"],
            "Build classification prompt",
        )
        self.assertEqual(
            connections["Classify with Ollama"]["main"][0][0]["node"],
            "Telemetry finish step: Classify with Ollama",
        )
        self.assertEqual(
            connections["Telemetry restore step finish: Classify with Ollama"]["main"][0][0]["node"],
            "Telemetry build classification attempt",
        )
        self.assertEqual(
            connections["Telemetry restore classification payload"]["main"][0][0]["node"],
            "Telemetry start step: Prepare Proton label targets",
        )
        self.assertEqual(
            connections["Telemetry restore step start: Prepare Proton label targets"]["main"][0][0]["node"],
            "Prepare Proton label targets",
        )
        self.assertEqual(
            connections["Telemetry restore label action payload"]["main"][0][0]["node"],
            "Loop Over Emails",
        )
        self.assertEqual(
            connections["Telemetry restore label action payload (trigger)"]["main"][0][0]["node"],
            "Telemetry finish run (trigger)",
        )

    def test_fetch_carries_telemetry_and_batch_config_across_loop(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("telemetry: defaults.telemetry", code)
        self.assertIn("imapPairsJson: inputConfig.imapPairsJson", code)
        self.assertIn("fetchWatchdogMs: defaults.fetchWatchdogMs", code)

    def test_telemetry_email_builder_preserves_multiple_expanded_items(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const code = fs.readFileSync('code-nodes/telemetry_build_email_items.js', 'utf8');
const items = ['1', '2', '3'].map((uid) => ({
  json: {
    uid,
    message_id: `<${uid}@example.test>`,
    credentialPairId: 'imap-1',
    sourceMailbox: 'INBOX',
    sender_email: 'sender@example.test',
    recipient_email: 'recipient@example.test',
    email_subject: `Subject ${uid}`,
    email_body: `Body ${uid}`,
    telemetry: { run_key: 'run-1' },
  },
}));
const $input = {
  all: () => items,
  first: () => items[0],
};

(async () => {
  const result = await new AsyncFunction('$input', code)($input);
  console.log(JSON.stringify(result.map((item) => item.json.uid)));
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

        self.assertEqual(json.loads(completed.stdout), ["1", "2", "3"])

    def test_compatibility_export_has_same_telemetry_nodes(self):
        workflow = self.load_workflow()
        trigger_export = json.loads(
            (ROOT / "workflow-imap-trigger.json").read_text(encoding="utf-8"),
        )
        workflow_telemetry = {
            node["name"] for node in workflow["nodes"] if node["name"].startswith("Telemetry ")
        }
        trigger_telemetry = {
            node["name"]
            for node in trigger_export["nodes"]
            if node["name"].startswith("Telemetry ")
        }

        self.assertEqual(trigger_telemetry, workflow_telemetry)
        self.assertEqual(
            trigger_export["connections"]["Classify with Ollama"]["main"][0][0]["node"],
            "Telemetry finish step: Classify with Ollama",
        )
        self.assertEqual(
            trigger_export["connections"]["Telemetry restore step finish: Classify with Ollama"]["main"][0][0]["node"],
            "Telemetry build classification attempt",
        )

    def test_system_prompt_includes_schedule_and_spam_like_labels(self):
        assignments = self.build_prompt_assignments()
        value = assignments["systemPrompt"]["value"]

        self.assertIn("`Schedule`", value)
        self.assertIn("calendar invitation", value)
        self.assertIn("time and place to be", value)
        self.assertIn("`Spam like`", value)
        self.assertIn("spam or junk mail", value)

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

        self.assertIn("suggested_labels", result)
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
        self.assertIn("unknown_labels", result)
        self.assertEqual(result["unknown_labels"], [{"label": "Security alert", "confidence": 0.94}])
        self.assertEqual(result["targetMailboxes"], ["Labels/Spam like", "Labels/Classified"])
        self.assertNotIn("Labels/Security alert", result["targetMailboxes"])

    def test_prepare_targets_caps_and_dedupes_unknown_labels(self):
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
      { label: 'security alert', confidence: 0.93 },
      { label: 'Subscription', confidence: 0.92 },
      { label: 'Newsletter', confidence: 0.91 },
      { label: 'Delivery', confidence: 0.90 },
      { label: 'Warranty', confidence: 0.89 },
      { label: 'Account', confidence: 0.88 }
    ],
    suggested_labels: [],
    reason: 'Unsupported category overflow',
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
            result["unknown_labels"],
            [
                {"label": "Security alert", "confidence": 0.94},
                {"label": "Subscription", "confidence": 0.92},
                {"label": "Newsletter", "confidence": 0.91},
                {"label": "Delivery", "confidence": 0.9},
                {"label": "Warranty", "confidence": 0.89},
            ],
        )
        self.assertEqual(result["targetMailboxes"], ["Labels/Classified"])

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
        result = json.loads(completed.stdout.strip().splitlines()[-1])

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

    def test_prepare_targets_accepts_schedule_and_spam_like_labels(self):
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
      { label: 'Schedule', confidence: 0.91 },
      { label: 'Spam like', confidence: 0.88 },
    ],
    reason: 'Calendar event notification that also resembles junk mail',
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
                {"label": "Schedule", "confidence": 0.91},
                {"label": "Spam like", "confidence": 0.88},
            ],
        )
        self.assertEqual(
            result["targetMailboxes"],
            ["Labels/Schedule", "Labels/Spam like", "Labels/Classified"],
        )

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
