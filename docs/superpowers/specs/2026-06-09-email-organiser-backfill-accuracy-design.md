# Email Organiser Backfill And Accuracy Design

Date: 2026-06-09
Workflow: `Email Organiser` (`fm6pLPnZWsGfK1oH`)

## Purpose

Validate the newly instrumented `Email Organiser` workflow against real backfill behavior, then improve its classification prompt and category-discovery loop without allowing the workflow to take destructive mail actions.

The current live draft is the step-telemetry workflow, not the smaller local main export. It has 103 nodes, two triggers, and telemetry around batch fetch, prompt construction, classification, label preparation, label application, and run completion.

## Visibility Gate

Before starting live backfill work, Codex must verify these access paths:

- n8n MCP is configured and reachable;
- `N8N_MCP_ACCESS_TOKEN` is available without printing it;
- `N8N_API_ACCESS_KEY` is available without printing it;
- the live workflow can be read by ID;
- the live workflow node count and key telemetry nodes match the expected 103-node draft;
- sanitized `workflow_status` Postgres telemetry can be queried.

Workflow execution output and raw n8n execution data must not be printed because they can contain private email content. Runtime monitoring should use sanitized telemetry summaries from `workflow_runs`, `workflow_steps`, `classification_attempts`, and `label_actions`.

## Staged Backfill Ramp

Backfill should start slowly and only ramp up after evidence that the workflow is progressing correctly.

Stage 1:

- run one capped batch with `batchLimit=50` and `maxBatches=1`;
- confirm the run finishes;
- confirm no workflow step remains `running`;
- confirm no workflow step has `error` status;
- confirm `Labels/Classified` label actions are recorded for processed emails;
- confirm confident labels are applied when their Proton label mailboxes exist;
- confirm uncertain classifications still proceed to `Labels/Classified`.

Stage 2:

- run a capped backfill with `batchLimit=50` and `maxBatches=3`;
- confirm at least three `Fetch next unclassified emails` cycles occur;
- confirm each batch produces a new set of unclassified messages rather than replaying the same static batch;
- confirm the loop returns from the completed email loop into the next fetch step;
- confirm all three batches finish with no stuck steps or unexpected workflow stop.

Stage 3:

- remove the `maxBatches` cap only after Stage 2 passes;
- run the full inbox backfill;
- continue monitoring batch progression until no unclassified emails remain or a real failure is found.

## Success Criteria

The workflow is robust enough for full backfill when:

- it can process at least three 50-email batches in sequence;
- the fetch-next-batch mechanism advances between batches;
- the execution does not hang after an individual email, after a batch, or after an uncertain classification;
- `Labels/Classified` is applied to every processed email, including uncertain cases;
- confident labels are applied only to existing Proton label mailboxes;
- missing label mailboxes are visible in telemetry and do not create Proton labels;
- prompt/model failures are visible in telemetry rather than silently swallowed.

## Prompt Source Of Truth

The editable classification prompt remains saved in workflow code:

- `Build classification prompt` creates `systemPrompt` and `userPrompt`;
- `Classify with Ollama` uses `={{ $json.userPrompt }}` and `={{ $json.systemPrompt }}`;
- tests assert the prompt fields exist and remain expression-compatible.

Prompt changes should be committed in workflow JSON and covered by tests. Private raw email bodies and prompt instances containing full email bodies must not be committed or printed.

## Suggested Labels

The model may suggest missing label categories, but suggestions are telemetry-only. The workflow must not create Proton labels, apply suggested labels, or add suggested labels to the allowed-label list automatically.

The classifier response shape should support:

```json
{
  "labels": [
    { "label": "Invoice", "confidence": 0.9 }
  ],
  "suggested_labels": [
    {
      "label": "Security alert",
      "reason": "Repeated login/security notifications do not fit the current label set",
      "criteria": "Use for account access alerts, MFA notices, password changes, and suspicious sign-in warnings"
    }
  ],
  "reason": "One sentence justification"
}
```

Parsing rules:

- `labels` may contain only the current allowed label names or `uncertain`;
- unknown labels in `labels` are dropped and surfaced through telemetry;
- `suggested_labels` entries are sanitized, bounded, and recorded;
- suggested labels never become `targetMailboxes`;
- if no confident allowed label remains, the workflow applies only `Labels/Classified`.

## Prompt Accuracy Improvements

The prompt should make label boundaries explicit and favor calibrated confidence over forced categorization.

Important distinctions:

- `Marketing` is for legitimate promotional/newsletter content from known or expected senders.
- `Cold email` is for unsolicited outreach from people or vendors seeking attention, sales, hiring, partnerships, backlinks, or meetings.
- `Invoice` is for invoices, receipts, statements, and documents showing an amount due or paid.
- `Bill` is for recurring service bills or utility/provider notices requiring payment attention.
- `Payment` is for payment confirmations, transfers, failed payments, payout notices, and transaction events.
- `Schedule` is for calendar invitations, calendar notifications, and events with a time and place to be.
- `Spam like` is for junk-like, suspicious, scammy, or clearly unwanted messages.
- `Important` should be reserved for messages that require personal attention and are not better covered by a more specific label.
- `Awaiting reply` should be used only when the user is expected to respond or follow up.

The prompt should require strict JSON, one-sentence reasoning, and confidence values that reflect uncertainty. It should tell the model to use `uncertain` when the body is too ambiguous, too truncated, or not enough context exists for a confident allowed label.

## Monitoring For Accuracy

Prompt changes should be driven by telemetry trends, not individual private email excerpts in chat.

Useful signals:

- invalid or fenced JSON frequency;
- unknown labels returned in `labels`;
- uncertain rate;
- repeated suggested-label themes;
- label distribution across batches;
- missing mailbox skips;
- label application successes and failures;
- classification latency and token estimates.

When reviewing examples, Codex should summarize aggregate patterns and avoid quoting private email content.

## Tests

Add or update tests to prove:

- the prompt mentions `suggested_labels` and keeps allowed labels distinct from suggestions;
- model responses with `suggested_labels` parse successfully;
- suggested labels are preserved in output telemetry fields;
- suggested labels do not become target mailboxes;
- unknown labels in `labels` are dropped without stopping the workflow;
- uncertain classifications target only `Labels/Classified`;
- the workflow JSON still has evaluable `systemPrompt` and `userPrompt` expressions.

## Future Phase

After the classifier is robust and accurate, design a separate action-taking phase. Candidate actions include:

- moving spam-like messages into the Spam folder;
- archiving redundant notification emails;
- drafting auto replies for messages that need a response.

That phase must have its own design and safety gates because it changes mail state beyond applying existing labels.
