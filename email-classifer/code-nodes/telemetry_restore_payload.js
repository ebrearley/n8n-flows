function parsePayload(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(String(value));
  } catch {
    return null;
  }
}

return $input.all().map((item) => {
  const json = item.json ?? {};
  const payload = parsePayload(json.payload_json ?? json.payloadJson ?? json.payload);
  const restored = payload && typeof payload === 'object' ? payload : json;
  const telemetry = restored.telemetry && typeof restored.telemetry === 'object'
    ? restored.telemetry
    : {};

  return {
    json: {
      ...restored,
      run_id: restored.run_id || telemetry.run_id || '',
      run_key: restored.run_key || telemetry.run_key || '',
      workflow_id: restored.workflow_id || telemetry.workflow_id || '',
      execution_id: restored.execution_id || telemetry.execution_id || '',
    },
  };
});
