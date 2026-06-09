import importlib.util
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowJsonTests(unittest.TestCase):
    def load_workflow(self):
        return json.loads((ROOT / "workflow.json").read_text(encoding="utf-8"))

    def load_workflow_path(self, name):
        return json.loads((ROOT / name).read_text(encoding="utf-8"))

    def all_workflows(self):
        return {
            "workflow.json": self.load_workflow_path("workflow.json"),
            "workflow-imap-trigger.json": self.load_workflow_path("workflow-imap-trigger.json"),
        }

    def nodes_by_name_for(self, workflow):
        return {node["name"]: node for node in workflow["nodes"]}

    def connection_targets(self, workflow, node_name, output_index=0):
        return [
            connection["node"]
            for connection in workflow["connections"][node_name]["main"][output_index]
        ]

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

    def system_prompt_value(self):
        return self.build_prompt_assignments()["systemPrompt"]["value"]

    def system_prompt_json_snippets(self):
        snippets = []
        for match in re.finditer(r"```json\n([\s\S]*?)\n```", self.system_prompt_value()):
            snippets.append(json.loads(match.group(1)))
        return snippets

    def load_workflow_updater(self):
        updater_path = ROOT / "tools" / "apply_email_action_workflow_updates.py"
        spec = importlib.util.spec_from_file_location(
            "apply_email_action_workflow_updates", updater_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def run_plan_email_actions(self, item):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Plan email actions').parameters.jsCode;
const item = JSON.parse(process.argv[1]);
const input = { first: () => ({ json: item }) };

(async () => {
  const result = await new AsyncFunction('$input', code)(input);
  console.log(JSON.stringify(result[0].json));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
        completed = subprocess.run(
            ["node", "-e", script, json.dumps(item)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def run_prepare_then_plan_email_actions(self, classifier_output):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const prepareCode = workflow.nodes.find((node) => node.name === 'Prepare Proton label targets').parameters.jsCode;
const planCode = workflow.nodes.find((node) => node.name === 'Plan email actions').parameters.jsCode;
const classifierOutput = JSON.parse(process.argv[1]);
const source = {
  uid: 'synthetic-uid',
  sourceFlow: 'bulk',
  runMode: 'apply_labels',
  labelPrefix: 'Labels',
  stateLabel: 'Classified',
  emailActionsMode: 'live',
  actionNow: '2026-06-09T12:00:00+10:00',
  actionArchiveMailbox: 'Archive',
  actionSpamMailbox: 'Spam',
  actionTrashMailbox: 'Trash',
};
const aiOutput = { output: JSON.stringify(classifierOutput) };
const dollar = (name) => {
  if (name !== 'Build classification prompt') throw new Error(`Unexpected node lookup: ${name}`);
  return { item: { json: source } };
};

(async () => {
  const prepared = await new AsyncFunction('$', '$json', prepareCode)(dollar, aiOutput);
  const planned = await new AsyncFunction('$input', planCode)({ first: () => prepared[0] });
  console.log(JSON.stringify({ prepared: prepared[0].json, planned: planned[0].json }));
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
        completed = subprocess.run(
            ["node", "-e", script, json.dumps(classifier_output)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_imap_action_nodes_are_javascript_code_nodes(self):
        nodes = self.nodes_by_name()

        for name in (
            "Get next 50 unclassified emails",
            "Apply Proton labels",
            "Apply Proton labels (trigger)",
        ):
            self.assertEqual(nodes[name]["type"], "n8n-nodes-base.code")
            self.assertEqual(nodes[name]["parameters"]["language"], "javaScript")

    def test_email_action_nodes_are_javascript_code_nodes(self):
        nodes = self.nodes_by_name()

        for name in (
            "Plan email actions",
            "Execute email action",
            "Execute email action (trigger)",
        ):
            self.assertEqual(nodes[name]["type"], "n8n-nodes-base.code")
            self.assertEqual(nodes[name]["parameters"]["language"], "javaScript")

    def test_email_action_nodes_are_wired_after_label_target_preparation(self):
        workflow = self.load_workflow()

        self.assertEqual(
            workflow["connections"]["Prepare Proton label targets"]["main"][0][0]["node"],
            "Plan email actions",
        )
        self.assertEqual(
            workflow["connections"]["Plan email actions"]["main"][0][0]["node"],
            "Inspect Proton label targets",
        )
        self.assertEqual(
            workflow["connections"]["Apply Proton labels"]["main"][0][0]["node"],
            "Execute email action",
        )
        self.assertEqual(
            workflow["connections"]["Execute email action"]["main"][0][0]["node"],
            "Loop Over Emails",
        )
        self.assertEqual(
            workflow["connections"]["Apply Proton labels (trigger)"]["main"][0][0]["node"],
            "Execute email action (trigger)",
        )
        self.assertNotIn("Execute email action (trigger)", workflow["connections"])

    def test_configure_node_sets_live_email_action_defaults(self):
        assignments = self.configure_assignments()

        self.assertEqual(assignments["emailActionsMode"]["value"], "live")
        self.assertEqual(assignments["actionArchiveMailbox"]["value"], "Archive")
        self.assertEqual(assignments["actionSpamMailbox"]["value"], "Spam")
        self.assertEqual(assignments["actionTrashMailbox"]["value"], "Trash")

    def test_plan_email_actions_moves_spam_like_to_spam(self):
        result = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "labels": [{"label": "Spam like", "confidence": 0.9}],
            "actionHints": {},
        })

        self.assertEqual(result["emailAction"]["action"], "move_to_spam")
        self.assertEqual(result["emailAction"]["destinationMailbox"], "Spam")
        self.assertEqual(result["emailAction"]["reason"], "spam_like")
        self.assertIs(result["emailAction"]["approved"], True)

    def test_plan_email_actions_trashes_expired_two_factor_code(self):
        result = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "date": "Mon, 08 Jun 2026 10:00:00 +1000",
            "labels": [{"label": "Important", "confidence": 0.8}],
            "actionHints": {"two_factor_code": True},
        })

        self.assertEqual(result["emailAction"]["action"], "move_to_trash")
        self.assertEqual(result["emailAction"]["destinationMailbox"], "Trash")
        self.assertEqual(result["emailAction"]["reason"], "expired_two_factor_code")

    def test_plan_email_actions_keeps_recent_two_factor_code(self):
        result = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "date": "Tue, 09 Jun 2026 02:00:00 +1000",
            "labels": [{"label": "Important", "confidence": 0.8}],
            "actionHints": {"two_factor_code": True},
        })

        self.assertEqual(result["emailAction"]["action"], "none")
        self.assertIs(result["emailAction"]["approved"], False)

    def test_plan_email_actions_archives_past_event_only(self):
        past = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "labels": [{"label": "Schedule", "confidence": 0.91}],
            "actionHints": {
                "event_notice": True,
                "event_time": "2026-06-09T08:00:00+10:00"
            },
        })
        future = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "labels": [{"label": "Schedule", "confidence": 0.91}],
            "actionHints": {
                "event_notice": True,
                "event_time": "2026-06-09T18:00:00+10:00"
            },
        })

        self.assertEqual(past["emailAction"]["action"], "archive")
        self.assertEqual(past["emailAction"]["destinationMailbox"], "Archive")
        self.assertEqual(past["emailAction"]["reason"], "past_event")
        self.assertEqual(future["emailAction"]["action"], "none")

    def test_plan_email_actions_archives_successful_backup_only(self):
        success = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "labels": [{"label": "Infrastructure", "confidence": 0.91}],
            "actionHints": {
                "backup_job": True,
                "backup_status": "success",
                "has_errors": False
            },
        })
        warning = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "labels": [{"label": "Infrastructure", "confidence": 0.91}],
            "actionHints": {
                "backup_job": True,
                "backup_status": "warning",
                "has_errors": True
            },
        })

        self.assertEqual(success["emailAction"]["action"], "archive")
        self.assertEqual(success["emailAction"]["reason"], "successful_backup")
        self.assertEqual(warning["emailAction"]["action"], "none")

    def test_plan_email_actions_keeps_schedule_event_without_time(self):
        result = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "labels": [{"label": "Schedule", "confidence": 0.91}],
            "actionHints": {
                "event_notice": True,
            },
        })

        self.assertEqual(result["emailAction"]["action"], "none")
        self.assertEqual(result["emailAction"]["reason"], "invalid_event_time")
        self.assertIs(result["emailAction"]["approved"], False)

    def test_plan_email_actions_keeps_non_success_backup_statuses(self):
        for status in ("failure", "warning", "partial", "error", "unknown"):
            with self.subTest(status=status):
                result = self.run_plan_email_actions({
                    "emailActionsMode": "live",
                    "actionNow": "2026-06-09T12:00:00+10:00",
                    "labels": [{"label": "Infrastructure", "confidence": 0.91}],
                    "actionHints": {
                        "backup_job": True,
                        "backup_status": status,
                        "has_errors": False,
                    },
                })

                self.assertEqual(result["emailAction"]["action"], "none")
                self.assertIs(result["emailAction"]["approved"], False)

    def test_plan_email_actions_keeps_backup_with_missing_has_errors(self):
        result = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "labels": [{"label": "Infrastructure", "confidence": 0.91}],
            "actionHints": {
                "backup_job": True,
                "backup_status": "success",
            },
        })

        self.assertEqual(result["emailAction"]["action"], "none")
        self.assertIs(result["emailAction"]["approved"], False)

    def test_plan_email_actions_keeps_backup_with_malformed_has_errors(self):
        result = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "labels": [{"label": "Infrastructure", "confidence": 0.91}],
            "actionHints": {
                "backup_job": True,
                "backup_status": "success",
                "has_errors": "false",
            },
        })

        self.assertEqual(result["emailAction"]["action"], "none")
        self.assertIs(result["emailAction"]["approved"], False)

    def test_prepare_then_plan_keeps_schedule_events_without_valid_time(self):
        cases = {
            "omitted": {},
            "null": {"event_time": None},
            "natural_language": {
                "event_time": "Wedding at Brunswick Town Hall, ask Alex for the private address",
            },
            "impossible_calendar": {"event_time": "2026-02-31T12:00:00+10:00"},
        }

        for name, event_hint in cases.items():
            with self.subTest(name=name):
                result = self.run_prepare_then_plan_email_actions({
                    "labels": [{"label": "Schedule", "confidence": 0.91}],
                    "action_hints": {
                        "event_notice": True,
                        **event_hint,
                    },
                    "reason": "Synthetic schedule classification",
                })

                self.assertIsNone(result["prepared"]["actionHints"]["event_time"])
                self.assertEqual(result["planned"]["emailAction"]["action"], "none")
                self.assertIs(result["planned"]["emailAction"]["approved"], False)

    def test_prepare_then_plan_keeps_successful_backup_without_boolean_has_errors(self):
        cases = {
            "omitted": {},
            "string_false": {"has_errors": "false"},
        }

        for name, error_hint in cases.items():
            with self.subTest(name=name):
                result = self.run_prepare_then_plan_email_actions({
                    "labels": [{"label": "Infrastructure", "confidence": 0.91}],
                    "action_hints": {
                        "backup_job": True,
                        "backup_status": "success",
                        **error_hint,
                    },
                    "reason": "Synthetic backup classification",
                })

                self.assertIsNone(result["prepared"]["actionHints"]["has_errors"])
                self.assertEqual(result["planned"]["emailAction"]["action"], "none")
                self.assertIs(result["planned"]["emailAction"]["approved"], False)

    def test_plan_email_actions_uses_spam_precedence(self):
        result = self.run_plan_email_actions({
            "emailActionsMode": "live",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "date": "Mon, 08 Jun 2026 10:00:00 +1000",
            "labels": [
                {"label": "Spam like", "confidence": 0.9},
                {"label": "Schedule", "confidence": 0.9},
                {"label": "Infrastructure", "confidence": 0.9}
            ],
            "actionHints": {
                "two_factor_code": True,
                "event_notice": True,
                "event_time": "2026-06-09T08:00:00+10:00",
                "backup_job": True,
                "backup_status": "success",
                "has_errors": False
            },
        })

        self.assertEqual(result["emailAction"]["action"], "move_to_spam")
        self.assertEqual(result["emailAction"]["reason"], "spam_like")

    def test_plan_email_actions_supports_disabled_mode(self):
        result = self.run_plan_email_actions({
            "emailActionsMode": "disabled",
            "actionNow": "2026-06-09T12:00:00+10:00",
            "labels": [{"label": "Spam like", "confidence": 0.9}],
            "actionHints": {},
        })

        self.assertEqual(result["emailAction"]["action"], "none")
        self.assertEqual(result["emailAction"]["reason"], "actions_disabled")
        self.assertIs(result["emailAction"]["approved"], False)

    def test_workflow_does_not_use_execute_command_nodes(self):
        workflow = self.load_workflow()
        execute_nodes = [
            node["name"]
            for node in workflow["nodes"]
            if node["type"] == "n8n-nodes-base.executeCommand"
        ]

        self.assertEqual(execute_nodes, [])

    def test_backfill_form_trigger_is_the_only_backfill_start(self):
        workflow = self.load_workflow()
        nodes = self.nodes_by_name()

        self.assertNotIn("Manual Trigger", nodes)
        self.assertNotIn("Manual Trigger", workflow["connections"])
        self.assertIn("Backfill Form Trigger", nodes)
        form_trigger = nodes["Backfill Form Trigger"]
        self.assertEqual(form_trigger["type"], "n8n-nodes-base.formTrigger")
        self.assertEqual(form_trigger["parameters"]["path"], "email-organiser-backfill")
        self.assertEqual(
            workflow["connections"]["Backfill Form Trigger"]["main"][0][0]["node"],
            "Configure Proton IMAP batch",
        )

    def test_workflow_exports_have_same_nodes_and_connections(self):
        workflows = self.all_workflows()
        primary = workflows["workflow.json"]
        compatibility = workflows["workflow-imap-trigger.json"]

        self.assertEqual(compatibility["nodes"], primary["nodes"])
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
                self.connection_targets(workflow, "Loop Over Emails", 1),
                ["Clean and truncate email"],
                workflow_name,
            )
            self.assertEqual(
                self.connection_targets(workflow, "Skip classified trigger email"),
                ["Clean and truncate email"],
                workflow_name,
            )
            self.assertEqual(
                self.connection_targets(workflow, "Clean and truncate email"),
                ["Generate email embedding"],
                workflow_name,
            )
            self.assertEqual(
                self.connection_targets(workflow, "Generate email embedding"),
                ["Build classification prompt"],
                workflow_name,
            )

    def test_email_trigger_disables_last_message_tracking(self):
        node = self.nodes_by_name()["Email Trigger (IMAP)"]

        self.assertEqual(node["type"], "n8n-nodes-base.emailReadImap")
        self.assertIs(node["parameters"]["options"]["trackLastMessageId"], False)

    def test_trigger_path_skips_already_classified_messages_before_ai(self):
        workflow = self.load_workflow()
        nodes = self.nodes_by_name()

        self.assertIn("Skip classified trigger email", nodes)
        self.assertEqual(
            workflow["connections"]["Normalize trigger email"]["main"][0][0]["node"],
            "Skip classified trigger email",
        )
        self.assertEqual(
            workflow["connections"]["Skip classified trigger email"]["main"][0][0]["node"],
            "Clean and truncate email",
        )

        guard_code = nodes["Skip classified trigger email"]["parameters"]["jsCode"]
        self.assertIn("Labels", guard_code)
        self.assertIn("Classified", guard_code)
        self.assertIn("searchMessageId", guard_code)
        self.assertIn("trigger_already_classified", guard_code)
        self.assertIn("return []", guard_code)

    def test_configure_node_defines_credential_pair_list(self):
        assignments = self.configure_assignments()
        self.assertIn("imapPairsJson", assignments)
        self.assertEqual(assignments["maxBatches"]["value"], 0)
        self.assertEqual(assignments["rawFetchByteLimit"]["value"], 65536)
        self.assertEqual(assignments["fetchWatchdogMs"]["value"], 120000)
        self.assertEqual(assignments["uidSearchWindow"]["value"], 500)
        self.assertEqual(assignments["embeddingBaseUrl"]["value"], "http://192.168.1.100:11434")
        self.assertEqual(assignments["embeddingModel"]["value"], "embeddinggemma")

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

    def test_fetch_config_parser_accepts_multiple_source_mailboxes_without_default_extra_folders(self):
        assignments = self.configure_assignments()
        configured_pairs = json.loads(assignments["imapPairsJson"]["value"])
        for pair in configured_pairs:
            self.assertEqual(pair["sourceMailboxes"], ["INBOX"])

        script = r"""
const fs = require('fs');
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Get next 50 unclassified emails').parameters.jsCode;
const helperStart = code.indexOf('function configValue(');
const helperEnd = code.indexOf('function chunked(');
if (helperStart < 0 || helperEnd < helperStart) {
  throw new Error('Could not isolate IMAP config helpers');
}
const helpers = new Function(
  code.slice(helperStart, helperEnd) + '\nreturn { credentialPairsFromConfig };',
)();
const defaults = {
  host: '192.168.3.200',
  port: 1143,
  hostVar: 'IMAP_HOST',
  portVar: 'IMAP_PORT',
  ssl: false,
  startTls: true,
  allowUnauthorizedCerts: true,
  sourceMailbox: 'INBOX',
  labelPrefix: 'Labels',
  stateLabel: 'Classified',
  userVar: 'IMAP_USER',
  passwordVar: 'IMAP_PASSWORD',
  rawFetchByteLimit: 65536,
  dryRun: false,
};
const pairs = helpers.credentialPairsFromConfig({
  imapPairsJson: JSON.stringify([{
    id: 'imap-synthetic',
    hostVar: 'IMAP_SYNTHETIC_HOST',
    portVar: 'IMAP_SYNTHETIC_PORT',
    userVar: 'IMAP_SYNTHETIC_USER',
    passwordVar: 'IMAP_SYNTHETIC_PASSWORD',
    sourceMailboxes: ['INBOX', 'Folders/Receipts', 'Labels/Follow Up'],
  }]),
}, defaults);
console.log(JSON.stringify(pairs));
"""
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        pairs = json.loads(completed.stdout)

        self.assertEqual(len(pairs), 1)
        self.assertEqual(
            pairs[0]["sourceMailboxes"],
            ["INBOX", "Folders/Receipts", "Labels/Follow Up"],
        )
        self.assertEqual(pairs[0]["id"], "imap-synthetic")
        self.assertEqual(pairs[0]["userVar"], "IMAP_SYNTHETIC_USER")
        self.assertEqual(pairs[0]["passwordVar"], "IMAP_SYNTHETIC_PASSWORD")

    def test_fetch_code_caps_batch_at_each_nested_loop_boundary(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        pair_loop = code.index("for (const pair of credentialPairs)")
        pair_break = code.index("if (emails.length >= defaults.batchLimit) break;", pair_loop)
        source_loop = code.index("for (const sourceMailbox of pair.sourceMailboxes)", pair_break)
        source_break = code.index("if (emails.length >= defaults.batchLimit) break;", source_loop)
        range_loop = code.index("let rangeEnd = uidNext - 1;", source_break)
        range_limit = code.index(
            "rangeEnd >= 1 && emails.length < defaults.batchLimit",
            range_loop,
        )
        batch_loop = code.index("for (const uidBatch of chunked(rangeUids, 100))", range_limit)
        uid_loop = code.index("for (const uid of uidBatch)", batch_loop)
        push_summary = code.index("emails.push(summary);", uid_loop)
        uid_break = code.index("if (emails.length >= defaults.batchLimit) break;", push_summary)
        batch_break = code.index("if (emails.length >= defaults.batchLimit) break;", uid_break + 1)

        self.assertLess(pair_loop, pair_break)
        self.assertLess(pair_break, source_loop)
        self.assertLess(source_loop, source_break)
        self.assertLess(source_break, range_loop)
        self.assertLess(range_loop, range_limit)
        self.assertLess(range_limit, batch_loop)
        self.assertLess(batch_loop, uid_loop)
        self.assertLess(uid_loop, push_summary)
        self.assertLess(push_summary, uid_break)
        self.assertLess(uid_break, batch_break)

    def test_fetch_summary_preserves_pair_and_mailbox_for_label_application(self):
        code = self.nodes_by_name()["Get next 50 unclassified emails"]["parameters"]["jsCode"]

        self.assertIn("credentialPairId: config.id", code)
        self.assertIn("credentialPair: publicCredentialPair(config)", code)
        self.assertIn("sourceMailbox: config.sourceMailbox", code)
        self.assertIn("const mailboxConfig = { ...pair, sourceMailbox", code)

    def test_apply_code_uses_item_source_mailbox_for_lookup_and_copy(self):
        nodes = self.nodes_by_name()

        for name in ("Apply Proton labels", "Apply Proton labels (trigger)"):
            code = nodes[name]["parameters"]["jsCode"]
            source_decl = "const sourceMailbox = String(configValue(item, 'sourceMailbox', 'INBOX'));"
            search_call = "client.searchMessageId(sourceMailbox, item.message_id)"
            select_call = "await client.select(sourceMailbox);"
            copy_call = "await client.copyUid(uid, mailbox);"

            self.assertIn(source_decl, code, name)
            self.assertIn(search_call, code, name)
            self.assertIn(select_call, code, name)
            self.assertIn(copy_call, code, name)
            self.assertLess(code.index(source_decl), code.index(search_call), name)
            self.assertLess(code.index(search_call), code.index(select_call), name)
            self.assertLess(code.index(select_call), code.index(copy_call), name)

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

    def test_prepare_targets_accepts_approved_category_taxonomy(self):
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
const dollar = (name) => {
  if (name !== 'Build classification prompt') throw new Error(`Unexpected node lookup: ${name}`);
  return { item: { json: source } };
};
const categories = [
  ['Account notification', 0.91],
  ['Statement', 0.90],
  ['Account (security)', 0.89],
  ['Newsletter', 0.88],
  ['Personal', 0.87],
];

(async () => {
  const results = [];
  for (const [name, confidence] of categories) {
    const aiOutput = {
      output: JSON.stringify({
        category: { name, confidence },
        reason: `${name} is present`,
      }),
    };
    const result = await new AsyncFunction('$', '$json', code)(dollar, aiOutput);
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

        expected = [
            ("Account notification", 0.91),
            ("Statement", 0.90),
            ("Account (security)", 0.89),
            ("Newsletter", 0.88),
            ("Personal", 0.87),
        ]
        for result, (name, confidence) in zip(results, expected):
            self.assertEqual(result["category"], {"name": name, "confidence": confidence})
            self.assertEqual(result["labels"], [{"label": name, "confidence": confidence}])
            self.assertEqual(result["targetMailboxes"], [f"Labels/{name}", "Labels/Classified"])
            self.assertNotIn("Labels/Account/Security", result["targetMailboxes"])

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
        self.assertIn("$json.cleanEmailText", value)
        self.assertIn("$json.emailEmbedding", value)
        self.assertNotIn("$json.email_body", value)
        self.assertNotIn("{{ $json.sender_email }}", value)

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
        self.assertEqual(result["emailEmbedding"]["totalDuration"], 12000000)
        self.assertNotIn("embedding", result)
        self.assertNotIn("embeddings", result)
        self.assertNotIn("embeddingVector", result)

    def test_generate_embedding_http_error_redacts_response_body(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Generate email embedding').parameters.jsCode;
const privateLookingInput = 'PRIVATE_INPUT_SHOULD_NOT_LEAK sender@example.test subject body';
globalThis.fetch = async () => ({
  ok: false,
  status: 500,
  text: async () => `server echoed ${privateLookingInput}`,
  json: async () => {
    throw new Error('json should not be read for failed responses');
  },
});
const input = {
  all: () => [{
    json: {
      cleanEmailText: privateLookingInput,
      embeddingModel: 'embeddinggemma',
      embeddingBaseUrl: 'http://ollama.test:11434',
    },
  }],
};

(async () => {
  await new AsyncFunction('$input', code)(input);
  throw new Error('Expected embedding request to fail');
})().catch((error) => {
  console.log(JSON.stringify({ message: error.message }));
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

        self.assertIn("Ollama embedding request failed with HTTP 500", result["message"])
        self.assertNotIn("server echoed", result["message"])
        self.assertNotIn("PRIVATE_INPUT_SHOULD_NOT_LEAK", result["message"])
        self.assertNotIn("sender@example.test", result["message"])

    def test_generate_embedding_json_parse_error_redacts_parser_message(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Generate email embedding').parameters.jsCode;
const privateLookingInput = 'PRIVATE_JSON_PARSE_INPUT_SHOULD_NOT_LEAK sender@example.test subject body';
globalThis.fetch = async () => ({
  ok: true,
  status: 200,
  json: async () => {
    throw new Error(`Unexpected token near ${privateLookingInput}`);
  },
});
const input = {
  all: () => [{
    json: {
      cleanEmailText: privateLookingInput,
      embeddingModel: 'embeddinggemma',
      embeddingBaseUrl: 'http://ollama.test:11434',
    },
  }],
};

(async () => {
  await new AsyncFunction('$input', code)(input);
  throw new Error('Expected embedding JSON parsing to fail');
})().catch((error) => {
  console.log(JSON.stringify({ message: error.message }));
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

        self.assertIn("Ollama embedding response was not valid JSON", result["message"])
        self.assertIn("HTTP 200", result["message"])
        self.assertNotIn("Unexpected token", result["message"])
        self.assertNotIn("PRIVATE_JSON_PARSE_INPUT_SHOULD_NOT_LEAK", result["message"])
        self.assertNotIn("sender@example.test", result["message"])

    def test_user_prompt_uses_clean_text_and_bounded_embedding_metadata(self):
        assignments = self.build_prompt_assignments()
        value = assignments["userPrompt"]["value"]

        self.assertIn("$json.cleanEmailText", value)
        self.assertIn("$json.emailEmbedding", value)
        self.assertNotIn("$json.email_body", value)

    def test_clean_node_sanitizes_body_aliases_and_truncates_by_code_point(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Clean and truncate email').parameters.jsCode;
const bodyAliases = ['text', 'textPlain', 'body', 'emailBody', 'html', 'textHtml'];
const inputs = bodyAliases.map((alias) => ({
  json: {
    sender_email: 'sender@example.test',
    email_subject: `Alias body ${alias}`,
    cleanEmailTextLimit: 12,
    [alias]: '<p>Alias&nbsp;<strong>clean</strong> text with surplus</p>',
  },
}));
inputs.push({
  json: {
    sender_email: 'sender@example.test',
    email_subject: 'Emoji truncation',
    email_body: 'abc' + String.fromCodePoint(0x1f600) + 'def',
    cleanEmailTextLimit: 4,
  },
});
const input = { all: () => inputs };

(async () => {
  const result = await new AsyncFunction('$input', code)(input);
  console.log(JSON.stringify(result.map((item) => item.json)));
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
        body_aliases = ["text", "textPlain", "body", "emailBody", "html", "textHtml"]

        for result in results[:-1]:
            self.assertEqual(result["cleanEmailText"], "Alias clean")
            self.assertEqual(result["email_body"], result["cleanEmailText"])
            for alias in body_aliases:
                if alias in result:
                    self.assertEqual(result[alias], result["cleanEmailText"], alias)
                    self.assertLessEqual(len(result[alias]), result["cleanEmailTextLimit"])

        emoji_result = results[-1]
        self.assertEqual(emoji_result["cleanEmailText"], "abc" + chr(0x1F600))
        self.assertNotRegex(emoji_result["cleanEmailText"], r"[\ud800-\udfff]")

    def test_system_prompt_includes_schedule_and_spam_like_categories(self):
        assignments = self.build_prompt_assignments()
        value = assignments["systemPrompt"]["value"]

        self.assertIn("`Schedule`", value)
        self.assertIn("calendar invitation", value)
        self.assertIn("time and place to be", value)
        self.assertIn("`Spam like`", value)
        self.assertIn("category", value)
        self.assertIn("junk-like", value)

    def test_system_prompt_requests_sanitized_action_hints(self):
        assignments = self.build_prompt_assignments()
        value = assignments["systemPrompt"]["value"]
        schema_section = value.split("## Schema", 1)[1].split("## Rules", 1)[0]

        self.assertEqual(value.count("<!-- action-hints:start -->"), 1)
        self.assertEqual(value.count("<!-- action-hints:end -->"), 1)
        self.assertIn('"action_hints": {', schema_section)
        self.assertIn('"two_factor_code": false', schema_section)
        self.assertIn('"event_notice": false', schema_section)
        self.assertIn('"event_time": null', schema_section)
        self.assertIn('"backup_job": false', schema_section)
        self.assertIn('"backup_status": "unknown"', schema_section)
        self.assertIn('"has_errors": false', schema_section)
        self.assertIn("- `action_hints`:", schema_section)
        self.assertNotIn('"reason": string\n}', schema_section)
        self.assertNotIn("Also include an `action_hints` object", schema_section)
        self.assertNotIn("must match output exactly", value)

    def test_system_prompt_keeps_category_schema_with_action_hints(self):
        schema_section = self.system_prompt_value().split("## Schema", 1)[1].split("## Rules", 1)[0]

        self.assertIn('"category": { "name": string, "confidence": number }', schema_section)
        self.assertIn('"reason": string,', schema_section)
        self.assertIn('"action_hints": {', schema_section)
        self.assertIn('"two_factor_code": boolean', schema_section)
        self.assertNotIn('"labels": [', schema_section)

    def test_system_prompt_marks_uncertain_as_fallback_only(self):
        value = self.system_prompt_value()

        self.assertIn("`category.name` must exactly match one allowed category, or be `uncertain`.", value)
        self.assertIn('{"category":{"name":"uncertain","confidence":0.0}', value)

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

        self.assertEqual(result["category"], {"name": "Schedule", "confidence": 0.91})
        self.assertEqual(result["labels"], [{"label": "Schedule", "confidence": 0.91}])
        self.assertEqual(result["targetMailboxes"], ["Labels/Schedule", "Labels/Classified"])

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

    def test_prepare_targets_preserves_sanitized_action_hints(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Prepare Proton label targets').parameters.jsCode;
const source = {
  uid: '101',
  sourceFlow: 'bulk',
  runMode: 'apply_labels',
  labelPrefix: 'Labels',
  stateLabel: 'Classified',
};
const aiOutput = {
  output: JSON.stringify({
    labels: [{ label: 'Infrastructure', confidence: 0.91 }],
    action_hints: {
      two_factor_code: false,
      event_notice: true,
      event_time: '2026-06-09T08:00:00+10:00',
      backup_job: true,
      backup_status: 'success',
      has_errors: false,
      ignored_extra_field: 'not copied'
    },
    reason: 'Successful backup notification for an infrastructure system'
  })
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
            result["actionHints"],
            {
                "two_factor_code": False,
                "event_notice": True,
                "event_time": "2026-06-09T08:00:00+10:00",
                "backup_job": True,
                "backup_status": "success",
                "has_errors": False,
            },
        )
        self.assertNotIn("ignored_extra_field", result["actionHints"])
        self.assertEqual(result["classification"]["action_hints"], result["actionHints"])

    def test_prepare_targets_preserves_zulu_action_hint_event_time(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Prepare Proton label targets').parameters.jsCode;
const source = {
  uid: '104',
  sourceFlow: 'bulk',
  runMode: 'apply_labels',
  labelPrefix: 'Labels',
  stateLabel: 'Classified',
};
const aiOutput = {
  output: JSON.stringify({
    labels: [{ label: 'Schedule', confidence: 0.9 }],
    action_hints: {
      event_notice: true,
      event_time: '2026-06-09T08:00:00Z',
    },
    reason: 'Valid UTC event time should be preserved'
  })
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

        self.assertEqual(result["actionHints"]["event_time"], "2026-06-09T08:00:00Z")
        self.assertEqual(
            result["classification"]["action_hints"]["event_time"],
            "2026-06-09T08:00:00Z",
        )

    def test_prepare_targets_drops_invalid_action_hint_event_time(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Prepare Proton label targets').parameters.jsCode;
const source = {
  uid: '102',
  sourceFlow: 'bulk',
  runMode: 'apply_labels',
  labelPrefix: 'Labels',
  stateLabel: 'Classified',
};
const aiOutput = {
  output: JSON.stringify({
    labels: [{ label: 'Schedule', confidence: 0.9 }],
    action_hints: {
      event_notice: true,
      event_time: 'Wedding at Brunswick Town Hall, ask Alex for the private address',
    },
    reason: 'Invitation with a natural-language event description'
  })
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

        self.assertIsNone(result["actionHints"]["event_time"])
        self.assertIsNone(result["classification"]["action_hints"]["event_time"])

    def test_prepare_targets_drops_impossible_calendar_action_hint_event_time(self):
        script = r"""
const fs = require('fs');
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const workflow = JSON.parse(fs.readFileSync('workflow.json', 'utf8'));
const code = workflow.nodes.find((node) => node.name === 'Prepare Proton label targets').parameters.jsCode;
const source = {
  uid: '103',
  sourceFlow: 'bulk',
  runMode: 'apply_labels',
  labelPrefix: 'Labels',
  stateLabel: 'Classified',
};
const aiOutput = {
  output: JSON.stringify({
    labels: [{ label: 'Schedule', confidence: 0.9 }],
    action_hints: {
      event_notice: true,
      event_time: '2026-02-31T12:00:00+10:00',
    },
    reason: 'Impossible calendar date should not be preserved'
  })
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

        self.assertIsNone(result["actionHints"]["event_time"])
        self.assertIsNone(result["classification"]["action_hints"]["event_time"])

    def test_action_hint_prompt_updater_repairs_and_is_idempotent(self):
        updater = self.load_workflow_updater()
        workflow = self.load_workflow()

        assignments = {
            assignment["name"]: assignment
            for assignment in next(
                node
                for node in workflow["nodes"]
                if node["name"] == "Build classification prompt"
            )["parameters"]["assignments"]["assignments"]
        }
        assignments["systemPrompt"]["value"] = assignments["systemPrompt"]["value"].replace(
            updater.ACTION_HINTS_SECTION,
            '\n\n## Optional action hints\nAlso include an `action_hints` object without the canonical schema.\n',
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            workflow_path = Path(tmpdir) / "workflow.json"
            workflow_path.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")

            updater.update_workflow(workflow_path)
            first_update = workflow_path.read_text(encoding="utf-8")
            repaired = json.loads(first_update)
            repaired_assignments = {
                assignment["name"]: assignment
                for assignment in next(
                    node
                    for node in repaired["nodes"]
                    if node["name"] == "Build classification prompt"
                )["parameters"]["assignments"]["assignments"]
            }
            repaired_prompt = repaired_assignments["systemPrompt"]["value"]

            self.assertEqual(repaired_prompt.count(updater.ACTION_HINTS_START), 1)
            self.assertEqual(repaired_prompt.count(updater.ACTION_HINTS_END), 1)
            self.assertNotIn("without the canonical schema", repaired_prompt)

            updater.update_workflow(workflow_path)
            self.assertEqual(workflow_path.read_text(encoding="utf-8"), first_update)

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
        self.assertEqual(
            result["classification"]["category"],
            {"name": "uncertain", "confidence": 0},
        )
        self.assertEqual(result["labels"], [])
        self.assertEqual(result["labelMailboxes"], [])
        self.assertEqual(result["targetMailboxes"], ["Labels/Classified"])
        self.assertEqual(result["runMode"], "apply_labels")


if __name__ == "__main__":
    unittest.main()
