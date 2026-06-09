# Email Organiser Embedding And Multi-IMAP Design

Date: 2026-06-09
Workflow: `Email Organiser`
Branch: `feature/email-organiser-embedding-multi-imap`

## Purpose

Adapt the Email Organiser workflow to make the classification pipeline explicit:

```text
mail -> clean/truncate -> embedding model -> classifier -> category
```

The workflow must keep its current safety boundaries: it may copy messages into existing Proton label mailboxes, but it must not create labels, move source messages, delete messages, expunge messages, or print private email content.

## Current State

The local workflow exports have two real start paths:

- `Backfill Form Trigger` starts a backfill run and connects to `Configure Proton IMAP batch`.
- `Email Trigger (IMAP)` handles new mail and connects through `Normalize trigger email` and `Skip classified trigger email`.

There is no `Manual Trigger` in the local compact workflow export. Tests already assert that `Manual Trigger` is absent from both workflow nodes and workflow connections. If the n8n editor still shows a manual trigger, treat that as live-draft drift and verify the live workflow before importing or updating it.

Backfill already supports multiple IMAP credential pairs through `imapPairsJson`. Each pair can include `sourceMailboxes`, and fetched email items carry `credentialPair`, `credentialPairId`, and `sourceMailbox` metadata so label application can use the correct account and mailbox.

The current classifier path is:

```text
Build classification prompt -> Classify with Ollama -> Prepare Proton label targets
```

Cleaning and truncation currently happen inside the fetch and trigger-normalization Code nodes. There is no dedicated embedding step and no canonical `category` schema.

## Design

### Start Paths

Keep only the two operational starts:

- Backfill runs start through `Backfill Form Trigger`.
- Live mail starts through `Email Trigger (IMAP)`.

Do not add a `Manual Trigger`. If a live workflow contains one, remove it only after verifying that the target live draft is the intended workflow version.

### Shared Mail Preparation

Add a dedicated Code node named `Clean and truncate email` on the shared path before any model work.

Both backfill and trigger items should enter this node with common fields:

- `sender_email`
- `sender_name`
- `recipient_email`
- `email_subject`
- `email_body`
- `body_preview`
- `message_id`
- `uid`
- `credentialPair`
- `credentialPairId`
- `sourceMailbox`
- `labelPrefix`
- `stateLabel`

The node should:

- normalize whitespace;
- strip residual HTML if present;
- preserve the original already-decoded body only in bounded form;
- write a canonical `cleanEmailText`;
- write `cleanEmailTextLength`;
- write `cleanEmailTruncated`;
- cap classifier-facing text with a configurable limit;
- avoid logging or returning unbounded raw body content.

The existing fetch and trigger nodes may keep their defensive body caps, but `Clean and truncate email` becomes the source of truth for model-facing text.

### Embedding Step

Add an Ollama embedding step after cleaning/truncation. The embedding output is enrichment, not the only source of classification truth.

The workflow should carry bounded embedding metadata forward, such as:

- whether embedding succeeded;
- embedding model name;
- vector dimensions if available;
- a short error message if the node fails and tolerant behavior is explicitly enabled in the future.

During setup/debugging, keep model failures fail-closed unless explicitly changed. Do not persist or print raw embedding vectors unless a later design needs vector storage.

### Classifier And Category Schema

Update the classifier prompt and parser so the canonical response shape is category-based:

```json
{
  "category": {
    "name": "Invoice",
    "confidence": 0.9
  },
  "reason": "One sentence justification"
}
```

The allowed category names remain the existing Proton label set:

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

The parser must also accept the existing `labels` array shape during transition so older model output does not break the workflow. When both `category` and `labels` are present, `category` is authoritative.

If the model returns an unknown category, low confidence, invalid JSON, or `uncertain`, the workflow should classify the email as uncertain and apply only `Labels/Classified`.

### Category To Proton Labels

Rename or adapt `Prepare Proton label targets` so it maps one accepted category to Proton mailboxes:

- accepted confident category -> `Labels/<category>` plus `Labels/Classified`;
- uncertain category -> `Labels/Classified` only;
- missing target mailbox -> skip all label copies for that item and expose the missing mailbox metadata in the item output.

The workflow must not create missing Proton label mailboxes.

### Backfill Across Multiple IMAP Configurations

Keep `imapPairsJson` as the backfill configuration source. Strengthen tests and implementation around these rules:

- each pair can provide one or more `sourceMailboxes`;
- each fetched email carries its originating pair and source mailbox;
- label application uses the per-email pair metadata, not a global default;
- the configured batch limit caps the total returned item count across all pairs and mailboxes for one batch fetch;
- empty mailboxes and already-classified messages do not stop scanning other configured mailboxes.

The IMAP trigger remains tied to the n8n trigger credential. The trigger normalizer should continue to attach the correct first-pair metadata for label application unless and until separate live IMAP triggers are added for more accounts.

## Testing

Add or update tests for:

- no `Manual Trigger` in both workflow exports;
- both start paths route into `Clean and truncate email`;
- model-facing prompt uses `cleanEmailText`, not raw `email_body`;
- workflow contains an Ollama embedding step between cleaning and classification;
- embedding metadata is bounded and raw vectors are not committed to telemetry fields;
- classifier parser accepts the new `category` shape;
- parser still tolerates the existing `labels` shape;
- unknown, low-confidence, invalid, or uncertain category targets only `Labels/Classified`;
- multi-IMAP backfill respects a batch limit across pairs and mailboxes;
- fetched items preserve `credentialPairId`, `credentialPair`, and `sourceMailbox`;
- `workflow.json` and `workflow-imap-trigger.json` stay synchronized.

Run at minimum:

```bash
python3 -m unittest discover -s email-classifer/tests
git diff --check
```

Also compile Code-node JavaScript after editing Code nodes or inline workflow Code nodes.

## Deployment Notes

Before updating live n8n, verify which workflow state is the intended target:

- local compact workflow;
- the step-telemetry branch;
- a fresh export from live n8n.

Do not silently overwrite the live 103-node telemetry draft with the compact local export if the status dashboard still expects `workflow_steps` rows.

If the live draft contains `Manual Trigger`, remove it only as part of the intended live workflow update and re-read the workflow afterward to confirm trigger count, node count, and active state.
