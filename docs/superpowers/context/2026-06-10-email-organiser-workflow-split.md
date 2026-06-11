# Email Organiser Production And Telemetry Workflow Split

Date: 2026-06-10

## Live Workflows

`Email Organiser` (`fm6pLPnZWsGfK1oH`) is the production workflow. It is backed by `email-classifer/workflow.json` and `email-classifer/workflow-imap-trigger.json`, has no telemetry/Postgres nodes, and is intended to stay active for normal mail processing.

Verified live metadata after import/restart:

- active: `true`
- node count: `22`
- telemetry-like node count: `0`

`Email Organiser (with telemetry)` (`bXNCHRxwqXoOeePH`) is the iteration/status workflow. It is backed by `email-classifer/workflow-with-telemetry.json`, writes to the `workflow_status` database, and is the workflow to run when feeding `n8n-workflow-status`.

Verified live metadata after import/restart:

- active: `false`
- node count: `92`
- telemetry-like node count: `73`
- telemetry start nodes write workflow ID `bXNCHRxwqXoOeePH`
- telemetry start nodes write workflow name `Email Organiser (with telemetry)`

## Operational Rule

Do not import one workflow export over the other live workflow ID. Production should remain telemetry-free. The telemetry workflow should be activated or executed only when deliberately validating or iterating with dashboard visibility.

No workflow execution output or private email content was read while making this split.
