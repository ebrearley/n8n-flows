import json
import sys
import unittest
from pathlib import Path


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
            ["Invoice", "Ticket"],
            dry_run=True,
        )

        self.assertEqual(result, {
            "destination_actions": {
                "Invoice": "would_apply_label",
                "Ticket": "would_apply_label",
            },
            "source_action": "would_remove_from_source",
        })

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


if __name__ == "__main__":
    unittest.main()
