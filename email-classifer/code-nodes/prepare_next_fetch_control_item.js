function safeObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function lookupConfig() {
  try {
    const lookup = $('Configure Proton IMAP batch');
    if (lookup && typeof lookup.first === 'function') {
      const first = lookup.first();
      if (first?.json) return first.json;
    }
    if (lookup && typeof lookup.all === 'function') {
      const all = lookup.all();
      if (all?.[0]?.json) return all[0].json;
    }
    if (lookup?.item?.json) return lookup.item.json;
  } catch {}
  return {};
}

function configuredValue(configured, current, key, fallback = undefined) {
  if (configured[key] !== undefined && configured[key] !== null && configured[key] !== '') {
    return configured[key];
  }
  if (current[key] !== undefined && current[key] !== null && current[key] !== '') {
    return current[key];
  }
  return fallback;
}

function copyField(target, configured, current, key, fallback = undefined) {
  const value = configuredValue(configured, current, key, fallback);
  if (value !== undefined && value !== null && value !== '') target[key] = value;
}

const current = $input.first()?.json ?? {};
const configured = lookupConfig();
const configuredTelemetry = safeObject(configured.telemetry);
const currentTelemetry = safeObject(current.telemetry);
const telemetrySource = Object.keys(configuredTelemetry).length > 0
  ? configuredTelemetry
  : currentTelemetry;

const control = {
  runMode: 'fetch_batch',
  sourceFlow: 'bulk',
  telemetry: telemetrySource,
  run_id: telemetrySource.run_id || configuredValue(configured, current, 'run_id', ''),
  run_key: telemetrySource.run_key || configuredValue(configured, current, 'run_key', ''),
  workflow_id: telemetrySource.workflow_id || configuredValue(configured, current, 'workflow_id', ''),
  workflow_name: telemetrySource.workflow_name || configuredValue(configured, current, 'workflow_name', ''),
  execution_id: telemetrySource.execution_id || configuredValue(configured, current, 'execution_id', ''),
};

for (const key of [
  'batchLimit',
  'maxBatches',
  'imapHost',
  'imapPort',
  'imapSsl',
  'imapStartTls',
  'sourceMailbox',
  'labelPrefix',
  'stateLabel',
  'dryRun',
  'rawFetchByteLimit',
  'fetchWatchdogMs',
  'uidSearchWindow',
  'imapPairsJson',
]) {
  copyField(control, configured, current, key);
}

return [{ json: control }];
