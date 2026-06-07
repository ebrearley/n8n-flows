function payloadJson(value) {
  return JSON.stringify(value ?? {});
}

const telemetry = $json.telemetry || {};
const stoppedAt = new Date().toISOString();
const status = $json.error ? 'error' : 'success';
const errorSummary = $json.error
  ? String($json.error.message || $json.error).slice(0, 500)
  : null;
const item = {
  ...$json,
  telemetry_finished_at: stoppedAt,
  telemetry_status: status,
};

console.log(JSON.stringify({
  service: 'n8n',
  workflow_id: telemetry.workflow_id,
  workflow_name: telemetry.workflow_name,
  execution_id: telemetry.execution_id,
  run_key: telemetry.run_key,
  step: 'finish_run',
  status,
  stopped_reason: $json.stopped_reason || null,
  error: errorSummary,
}));

return [{
  json: {
    ...item,
    finish_run_params: [
      telemetry.run_id || $json.run_id || '',
      status,
      stoppedAt,
      errorSummary,
      payloadJson(item),
    ],
  },
}];
