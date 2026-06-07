const workflowId = 'fm6pLPnZWsGfK1oH';
const workflowName = 'Email Organiser';
const startedAt = new Date().toISOString();
const executionId = String($execution?.id || $json.execution_id || startedAt);
const sourceFlow = $json.sourceFlow === 'trigger' ? 'trigger' : 'bulk';
const triggerMode = sourceFlow === 'trigger' ? 'imap_trigger' : 'manual_backfill';
const runKey = `${workflowId}:${executionId}:${triggerMode}`;

function payloadJson(value) {
  return JSON.stringify(value ?? {});
}

const next = {
  ...$json,
  sourceFlow,
  telemetry: {
    workflow_id: workflowId,
    workflow_name: workflowName,
    execution_id: executionId,
    trigger_mode: triggerMode,
    run_key: runKey,
    started_at: startedAt,
  },
};

console.log(JSON.stringify({
  service: 'n8n',
  workflow_id: workflowId,
  workflow_name: workflowName,
  execution_id: executionId,
  run_key: runKey,
  step: 'telemetry_start_run',
  status: 'running',
  trigger_mode: triggerMode,
}));

return [{
  json: {
    ...next,
    telemetry_payload_json: payloadJson(next),
  },
}];
