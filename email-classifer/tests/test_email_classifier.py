import json
import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import email_classifier as classifier  # noqa: E402


class EmailClassifierTests(unittest.TestCase):
    def test_sanitizes_mailbox_segments(self):
        self.assertEqual(classifier.sanitize_mailbox_segment("Needs Review"), "Needs Review")
        self.assertEqual(classifier.sanitize_mailbox_segment("Finance/Invoices"), "Finance_Invoices")
        self.assertEqual(classifier.sanitize_mailbox_segment("  bad\x00name  "), "bad_name")

    def test_builds_destination_with_optional_prefix(self):
        self.assertEqual(classifier.destination_mailbox("Finance", ""), "Finance")
        self.assertEqual(classifier.destination_mailbox("Finance", "AI"), "AI/Finance")
        self.assertEqual(classifier.destination_mailbox("Needs Review", "Mail/AI"), "Mail/AI/Needs Review")

    def test_normalizes_valid_ollama_json(self):
        result = classifier.normalize_classification(
            json.dumps({
                "labels": [
                    {"label": "Purchase", "confidence": 0.90},
                    {"label": "Invoice", "confidence": 0.82},
                ],
                "reason": "Order confirmation that also includes the invoice document",
            }),
            ["Purchase", "Invoice", "uncertain"],
        )

        self.assertEqual(result["labels"], [
            {"label": "Purchase", "confidence": 0.90},
            {"label": "Invoice", "confidence": 0.82},
        ])
        self.assertEqual(result["folders"], ["Purchase", "Invoice"])
        self.assertEqual(result["label"], "Purchase")
        self.assertEqual(result["folder"], "Purchase")
        self.assertEqual(result["reason"], "Order confirmation that also includes the invoice document")

    def test_rejects_unknown_or_invalid_ollama_output(self):
        for content in (
            "not json",
            json.dumps({"labels": [{"label": "Unknown", "confidence": 0.9}], "reason": "x"}),
            json.dumps({"confidence": 0.9}),
        ):
            result = classifier.normalize_classification(content, ["Purchase", "uncertain"])
            self.assertEqual(result["label"], "uncertain")
            self.assertEqual(result["folder"], "uncertain")
            self.assertEqual(result["labels"], [{"label": "uncertain", "confidence": 0}])

    def test_rejects_low_confidence_specific_labels(self):
        result = classifier.normalize_classification(
            json.dumps({"labels": [{"label": "Marketing", "confidence": 0.4}], "reason": "weak signal"}),
            ["Marketing", "uncertain"],
        )

        self.assertEqual(result["label"], "uncertain")
        self.assertLess(result["labels"][0]["confidence"], 0.75)

    def test_parses_categories_from_environment_value(self):
        categories = classifier.parse_categories("Invoice, Purchase")

        self.assertEqual(categories, ["Invoice", "Purchase", "uncertain"])

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

    def test_dry_run_application_reports_all_destinations(self):
        result = classifier.apply_message_to_destinations(
            None,
            b"123",
            ["Invoice", "Ticket", "Classified"],
            dry_run=True,
        )

        self.assertEqual(result, {
            "destination_actions": {
                "Invoice": "would_apply_label",
                "Ticket": "would_apply_label",
                "Classified": "would_apply_label",
            },
            "source_action": "would_keep_in_source",
        })

    def test_label_application_copies_without_deleting_source(self):
        class FakeClient:
            def __init__(self):
                self.commands = []
                self.expunge_called = False

            def uid(self, *args):
                self.commands.append(args)
                return "OK", [b"ok"]

            def expunge(self):
                self.expunge_called = True

        client = FakeClient()

        result = classifier.apply_message_to_destinations(
            client,
            b"123",
            ["Invoice", "Classified"],
            dry_run=False,
        )

        self.assertEqual(result, {
            "destination_actions": {
                "Invoice": "label_applied",
                "Classified": "label_applied",
            },
            "source_action": "kept_in_source",
        })
        self.assertEqual(client.commands, [
            ("COPY", "123", '"Invoice"'),
            ("COPY", "123", '"Classified"'),
        ])
        self.assertFalse(client.expunge_called)

    def test_missing_label_mailbox_fails_when_not_dry_run(self):
        with self.assertRaisesRegex(RuntimeError, "does not exist"):
            classifier.require_existing_mailbox("Invoice", {"Classified"}, dry_run=False)

        self.assertEqual(
            classifier.require_existing_mailbox("Invoice", {"Classified"}, dry_run=True),
            "missing",
        )

    def test_appends_classified_state_label_to_destinations(self):
        destinations = classifier.classification_destinations(
            {"folders": ["Invoice", "Ticket"]},
            state_label="Classified",
            prefix="Labels",
        )

        self.assertEqual(destinations, ["Labels/Invoice", "Labels/Ticket", "Labels/Classified"])

    def test_uncertain_classification_only_applies_classified_state_label(self):
        destinations = classifier.classification_destinations(
            {"folders": ["uncertain"], "folder": "uncertain"},
            state_label="Classified",
            prefix="Labels",
        )

        self.assertEqual(destinations, ["Labels/Classified"])

    def test_normalizes_classification_from_runtime_ai_output(self):
        result = classifier.classification_from_runtime(
            {
                "classification": {
                    "labels": [{"label": "Invoice", "confidence": 0.91}],
                    "reason": "Receipt for discretionary spending",
                }
            },
            ["Invoice", "uncertain"],
        )

        self.assertEqual(result["folders"], ["Invoice"])
        self.assertEqual(result["reason"], "Receipt for discretionary spending")

    def test_renders_custom_user_prompt_template(self):
        summary = {
            "sender_email": "billing@example.com",
            "sender_name": "Example Billing",
            "email_subject": "Invoice 123",
            "date": "Fri, 05 Jun 2026 10:00:00 +1000",
            "email_body": "Please pay this invoice.",
        }

        prompt = classifier.render_user_prompt_template(
            (
                "From: {{ $json.sender_email }}\n"
                "Name: {{ $json.sender_name }}\n"
                "Subject: {{ $json.email_subject }}\n"
                "Email Content:\n\n"
                "{{ $json.email_body }}"
            ),
            summary,
            ["1: To respond", "uncertain"],
        )

        self.assertIn("From: billing@example.com", prompt)
        self.assertIn("Name: Example Billing", prompt)
        self.assertIn("Subject: Invoice 123", prompt)
        self.assertIn("Please pay this invoice.", prompt)

    def test_n8n_prompt_config_overrides_environment_prompt(self):
        config = {
            "systemPrompt": "Custom system prompt",
            "userPromptTemplate": "Custom user prompt for {{subject}}",
        }

        settings = classifier.prompt_settings_from_config(config)

        self.assertEqual(settings["system_prompt"], "Custom system prompt")
        self.assertEqual(settings["user_prompt_template"], "Custom user prompt for {{subject}}")

    def test_runtime_config_overrides_imap_endpoint_without_workflow_credentials(self):
        fake_client = mock.MagicMock()
        with mock.patch.object(classifier.imaplib, "IMAP4", return_value=fake_client) as imap4, \
            mock.patch.dict(classifier.os.environ, {
                "IMAP_USER": "env-user",
                "IMAP_PASSWORD": "env-password",
            }, clear=False):
            classifier.connect_imap({
                "imapHost": "192.168.3.200",
                "imapPort": 1143,
                "imapSsl": False,
                "imapStartTls": False,
            })

        imap4.assert_called_once_with("192.168.3.200", 1143)
        fake_client.login.assert_called_once_with("env-user", "env-password")

    def test_builds_summary_from_imap_trigger_item(self):
        summary = classifier.summary_from_trigger_item({
            "uid": "42",
            "messageId": "<abc@example.com>",
            "from": "Sender Name <sender@example.com>",
            "subject": "Sponsor inquiry",
            "text": "Can you send your rates?",
            "date": "Fri, 05 Jun 2026 10:00:00 +1000",
        })

        self.assertEqual(summary["uid"], "42")
        self.assertEqual(summary["message_id"], "<abc@example.com>")
        self.assertEqual(summary["sender_email"], "sender@example.com")
        self.assertEqual(summary["sender_name"], "Sender Name")
        self.assertEqual(summary["email_subject"], "Sponsor inquiry")
        self.assertEqual(summary["email_body"], "Can you send your rates?")

    def test_trigger_mode_applies_ai_node_classification(self):
        class FakeClient:
            def logout(self):
                return None

        config = {
            "runMode": "trigger_item",
            "uid": "42",
            "from": "Sender <sender@example.com>",
            "subject": "Sponsor inquiry",
            "text": "Can you send your rates?",
            "date": "Fri, 05 Jun 2026 10:00:00 +1000",
            "labelPrefix": "Labels",
            "classification": {
                "labels": [{"label": "Hustle", "confidence": 0.9}],
                "reason": "test",
            },
        }

        def apply_message(_client, _uid, destinations, _dry_run):
            return {
                "destination_actions": {
                    destination: "applied"
                    for destination in destinations
                },
                "source_action": "kept_in_source",
            }

        with mock.patch.dict(classifier.os.environ, {
            "EMAIL_CLASSIFIER_DRY_RUN": "false",
        }, clear=False), \
            mock.patch.object(classifier, "load_runtime_config", return_value=config), \
            mock.patch.object(classifier, "connect_imap", return_value=FakeClient()), \
            mock.patch.object(classifier, "select_mailbox", return_value=None), \
            mock.patch.object(classifier, "list_mailboxes", return_value={"Labels/Hustle", "Labels/Classified"}), \
            mock.patch.object(classifier, "classify_with_ollama") as classify_with_ollama, \
            mock.patch.object(classifier, "require_existing_mailbox", return_value="exists"), \
            mock.patch.object(classifier, "apply_message_to_destinations", side_effect=apply_message):
            result = classifier.run()

        classify_with_ollama.assert_not_called()
        self.assertEqual(result["run_mode"], "trigger_item")
        self.assertEqual(result["total_processed"], 1)
        self.assertEqual(result["processed"][0]["uid"], "42")
        self.assertEqual(result["processed"][0]["destinations"], ["Labels/Hustle", "Labels/Classified"])


if __name__ == "__main__":
    unittest.main()
