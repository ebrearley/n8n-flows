const PRIVATE_FIELDS = new Set([
  'email_body',
  'body_preview',
  'raw',
  'raw_content',
  'userPrompt',
  'systemPrompt',
  'output',
  'classifier_output',
  'classification_raw_response',
]);

function compactEmail(item) {
  const compact = {};
  for (const [key, value] of Object.entries(item || {})) {
    if (!PRIVATE_FIELDS.has(key)) compact[key] = value;
  }
  compact.resetLoop = false;
  return compact;
}

const inputs = $input.all().map((item) => item.json ?? {});
const first = inputs[0] ?? {};
const telemetry = first.telemetry && typeof first.telemetry === 'object'
  ? first.telemetry
  : {};
const batch = inputs.map(compactEmail);

return [{
  json: {
    sourceFlow: 'bulk',
    runMode: 'apply_label_batch',
    telemetry,
    run_id: first.run_id || telemetry.run_id || '',
    run_key: first.run_key || telemetry.run_key || '',
    workflow_id: first.workflow_id || telemetry.workflow_id || '',
    workflow_name: first.workflow_name || telemetry.workflow_name || '',
    execution_id: first.execution_id || telemetry.execution_id || '',
    label_batch_items: batch,
    total_emails: batch.length,
    stopped_reason: batch.length ? 'batch_processed' : 'empty_batch',
  },
}];
