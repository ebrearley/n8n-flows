# Email Label Taxonomy Design

## Goal

Add five approved labels to the Email Organiser classifier taxonomy:

- `Account notification`
- `Statement`
- `Account (security)`
- `Newsletter`
- `Personal`

These labels should become normal allowed labels after implementation, which means the classifier may return them in `labels` and the workflow may apply the matching Proton mailboxes under `Labels/`.

## Background

The current workflow has 14 allowed labels:

- `Invoice`
- `Purchase`
- `Bill`
- `Payment`
- `Marketing`
- `Cold email`
- `Important`
- `Awaiting reply`
- `Travel`
- `Ticket`
- `Infrastructure`
- `Hustle`
- `Schedule`
- `Spam like`

Saved telemetry-backed candidates on the step-telemetry branch recorded:

- `Account notification`
- `Statement`
- `Account/Security`

A sanitized aggregate telemetry query over classifier output also showed these non-allowed label themes:

- `Account Notification`: 14 occurrences
- `Statement`: 13 occurrences
- `Account/Security`: 5 occurrences
- `Notification`: 3 occurrences
- `Financial`: 2 occurrences
- `Account Update`: 1 occurrence
- `Newsletter`: 1 occurrence
- `Onboarding`: 1 occurrence
- `Personal`: 1 occurrence
- `Security`: 1 occurrence

No email bodies, subjects, prompts, raw model responses, credentials, or private mailbox content were used in this design.

## Approved Labels

### Account notification

Routine account, service, policy, profile, membership, subscription, or platform notices that do not primarily concern security or billing.

Use this for:

- account updates;
- profile or membership notices;
- service policy changes;
- terms, privacy, plan, or product administrative notices;
- non-security account status updates.

Do not use this when:

- the message is primarily about login, MFA, password, recovery, identity verification, or suspicious activity; use `Account (security)`;
- the message is primarily a statement, invoice, bill, receipt, or payment event; use the financial label that fits;
- the message is a technical service alert about infrastructure, monitoring, domains, deployments, or devices; use `Infrastructure`.

### Statement

Periodic account, bank, provider, or service statements summarizing balances, activity, usage, holdings, or charges, where the email is not clearly an invoice, bill, receipt, or payment event.

Use this for:

- bank, credit card, investment, insurance, superannuation, or service statements;
- monthly or periodic account summaries;
- usage or activity summaries from a provider;
- notices that a statement is ready.

Do not use this when:

- the email requests or requires payment for a recurring obligation; use `Bill`;
- the email confirms a payment, payout, transfer, failed payment, or payslip; use `Payment`;
- the email is a receipt, invoice, or document showing a specific purchase amount due or paid; use `Invoice`;
- the email is an order, shipment, delivery, or purchase lifecycle notice; use `Purchase`.

### Account (security)

Account access and security messages, including logins, MFA, password changes, identity checks, recovery codes, suspicious activity, sign-in warnings, or verification requests.

Use this for:

- sign-in, login, or new-device alerts;
- MFA, passkey, recovery, or verification code messages;
- password reset or password changed messages;
- suspicious activity, account lock, fraud, or identity verification notices;
- security policy notices about account access.

Do not use this when:

- the message is only a routine account notice with no access or security implication; use `Account notification`;
- the message is a technical alert from a monitored service, device, deployment, domain, or production system; use `Infrastructure`;
- the message uses security-sounding language but is clearly junk or phishing-like; use `Spam like`, and also `Account (security)` only if the account-security intent is still useful after classification.

### Newsletter

Recurring editorial, community, creator, publication, product-update, or digest-style emails from known or subscribed sources, especially when the main intent is information rather than direct selling.

Use this for:

- publication, blog, community, or creator newsletters;
- recurring digests and roundup emails;
- product update digests that are informational rather than transactional;
- subscribed content where the main purpose is to read or scan information.

Do not use this when:

- the main intent is a sale, offer, discount, launch, or promotion; use `Marketing`;
- the message is unsolicited direct outreach seeking attention, sales, recruiting, partnerships, backlinks, or meetings; use `Cold email`;
- the message is a personal message from a real contact; use `Personal`.

### Personal

Direct personal correspondence from friends, family, acquaintances, or personal contacts about non-business, non-automated matters.

Use this for:

- one-to-one personal messages;
- family, friend, acquaintance, social, or household correspondence;
- non-commercial personal updates;
- personal invitations or coordination that are not primarily professional work.

Do not use this when:

- the message is professional work, client, quote, booking, project, or collaboration correspondence; use `Hustle`;
- the message is a calendar invite, appointment, booking, or event with a time and place to be; also use `Schedule`;
- the sender expects a response, approval, confirmation, or follow-up; also use `Awaiting reply`;
- the message is automated account, service, marketing, newsletter, or transaction mail.

## Taxonomy Decisions

`Account (security)` replaces the observed `Account/Security` candidate because parentheses match the user's approved label name and avoid an IMAP mailbox path separator in the label name.

`Security alert` and `Security` are not added separately. Their useful meaning is covered by `Account (security)`.

`Notification` and `Account Update` are not added separately. Their useful meaning is covered by `Account notification`.

`Financial` is not added separately. It is too broad and overlaps with `Invoice`, `Bill`, `Payment`, `Statement`, and `Purchase`.

`Onboarding` is not added now because it appeared once and lacks a clear boundary from `Account notification`, `Hustle`, and `Personal`.

## Implementation Requirements

Implementation should update both the reusable Code node source and the importable workflow exports:

- `email-classifer/code-nodes/prepare_proton_label_targets.js`
- `email-classifer/workflow.json`
- `email-classifer/workflow-imap-trigger.json`
- `email-classifer/email_classifier.py`
- `email-classifer/README.md`
- `email-classifer/tests/test_workflow_json.py`
- `email-classifer/tests/test_email_classifier.py`

The workflow must continue to:

- apply only exact allowed label names from the classifier `labels` array;
- drop unknown labels from `labels`;
- keep `uncertain` as a fallback sentinel, not a Proton label;
- always apply `Labels/Classified`;
- never create Proton labels or folders;
- skip label application and surface missing mailbox information when a required `Labels/<label>` mailbox does not exist.

If implementation happens against the step-telemetry workflow, the same allowed label list and prompt changes must also preserve telemetry sanitization and `suggested_labels` handling.

## Testing Requirements

Tests should prove:

- the new labels are included in the allowed list enforced by `Prepare Proton label targets`;
- both workflow exports contain the new labels in the classifier prompt;
- classifier examples or parsing tests accept the new labels with confidence at or above `0.75`;
- unknown labels remain dropped;
- `uncertain` still targets only `Labels/Classified`;
- `Account (security)` maps to `Labels/Account (security)`, not a path containing `Account/Security`;
- prompt descriptions include the boundary distinctions above.

## Deployment Note

Before importing any workflow to live n8n, confirm whether the target should be the smaller local main workflow, the step-telemetry branch, or a fresh export from live n8n. The live status dashboard may expect `workflow_steps` rows, so do not overwrite the live 103-node step-telemetry workflow with the smaller local main export without explicit confirmation.
