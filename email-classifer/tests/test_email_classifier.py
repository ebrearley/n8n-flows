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
            "source_action": "would_remove_from_source",
        })

    def test_appends_classified_state_label_to_destinations(self):
        destinations = classifier.classification_destinations(
            {"folders": ["Invoice", "Ticket"]},
            state_label="Classified",
            prefix="AI",
        )

        self.assertEqual(destinations, ["AI/Invoice", "AI/Ticket", "Classified"])

    def test_filters_uids_already_attempted_in_current_run(self):
        uids = classifier.unattempted_uids([b"10", b"11", b"12"], {"11"})

        self.assertEqual(uids, [b"10", b"12"])

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

    def test_run_fetches_batches_until_no_messages_remain(self):
        class FakeClient:
            def logout(self):
                return None

        fetch_batches = [[b"1", b"2"], [b"2", b"3"], []]

        def fetch_latest_uids(_client, _mailbox, _limit):
            return fetch_batches.pop(0)

        def fetch_message_summary(_client, uid):
            uid_string = uid.decode("ascii")
            return {
                "from": "sender@example.com",
                "sender_email": "sender@example.com",
                "sender_name": "Sender",
                "subject": f"Message {uid_string}",
                "email_subject": f"Message {uid_string}",
                "date": "Fri, 05 Jun 2026 10:00:00 +1000",
                "email_body": "Body",
            }

        def apply_message(_client, _uid, destinations, _dry_run):
            return {
                "destination_actions": {
                    destination: "applied"
                    for destination in destinations
                },
                "source_action": "removed_from_source",
            }

        classification = {
            "labels": [{"label": "Invoice", "confidence": 0.9}],
            "label": "Invoice",
            "folders": ["Invoice"],
            "folder": "Invoice",
            "reason": "test",
        }

        with mock.patch.dict(classifier.os.environ, {
            "EMAIL_CLASSIFIER_DRY_RUN": "false",
            "EMAIL_CLASSIFIER_LIMIT": "2",
            "EMAIL_CLASSIFIER_MAX_BATCHES": "0",
        }, clear=False), \
            mock.patch.object(classifier, "load_runtime_config", return_value={}), \
            mock.patch.object(classifier, "connect_imap", return_value=FakeClient()), \
            mock.patch.object(classifier, "list_mailboxes", return_value={"Invoice", "Classified"}), \
            mock.patch.object(classifier, "fetch_latest_uids", side_effect=fetch_latest_uids) as fetch_uids, \
            mock.patch.object(classifier, "fetch_message_summary", side_effect=fetch_message_summary), \
            mock.patch.object(classifier, "classify_with_ollama", return_value=classification), \
            mock.patch.object(classifier, "ensure_mailbox", return_value="exists"), \
            mock.patch.object(classifier, "apply_message_to_destinations", side_effect=apply_message):
            result = classifier.run()

        self.assertEqual(fetch_uids.call_count, 3)
        self.assertEqual(result["total_batches"], 2)
        self.assertEqual(result["total_processed"], 3)
        self.assertEqual(result["stopped_reason"], "no_messages")
        for item in result["processed"]:
            self.assertIn("Classified", item["destinations"])

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

    def test_trigger_mode_classifies_one_trigger_item(self):
        class FakeClient:
            def logout(self):
                return None

        classification = {
            "labels": [{"label": "Hustle", "confidence": 0.9}],
            "label": "Hustle",
            "folders": ["Hustle"],
            "folder": "Hustle",
            "reason": "test",
        }

        config = {
            "runMode": "trigger_item",
            "uid": "42",
            "from": "Sender <sender@example.com>",
            "subject": "Sponsor inquiry",
            "text": "Can you send your rates?",
            "date": "Fri, 05 Jun 2026 10:00:00 +1000",
        }

        def apply_message(_client, _uid, destinations, _dry_run):
            return {
                "destination_actions": {
                    destination: "applied"
                    for destination in destinations
                },
                "source_action": "removed_from_source",
            }

        with mock.patch.dict(classifier.os.environ, {
            "EMAIL_CLASSIFIER_DRY_RUN": "false",
        }, clear=False), \
            mock.patch.object(classifier, "load_runtime_config", return_value=config), \
            mock.patch.object(classifier, "connect_imap", return_value=FakeClient()), \
            mock.patch.object(classifier, "list_mailboxes", return_value={"Hustle", "Classified"}), \
            mock.patch.object(classifier, "classify_with_ollama", return_value=classification), \
            mock.patch.object(classifier, "ensure_mailbox", return_value="exists"), \
            mock.patch.object(classifier, "apply_message_to_destinations", side_effect=apply_message):
            result = classifier.run()

        self.assertEqual(result["run_mode"], "trigger_item")
        self.assertEqual(result["total_processed"], 1)
        self.assertEqual(result["processed"][0]["uid"], "42")
        self.assertEqual(result["processed"][0]["destinations"], ["Hustle", "Classified"])


if __name__ == "__main__":
    unittest.main()
