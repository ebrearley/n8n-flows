function payloadJson(value) {
  return JSON.stringify(value ?? {});
}

function truncate(value) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, 500);
}

const SECRET_FIELDS = [
  'password',
  'N8N_API_KEY',
  'DATABASE_URL',
  'IMAP_PASSWORD',
  'IMAP_1_PASSWORD',
  'IMAP_2_PASSWORD',
  'IMAP_3_PASSWORD',
];

function isSecretField(key) {
  const normalized = String(key || '').toLowerCase();
  return normalized === 'password'
    || normalized === 'n8n_api_key'
    || normalized === 'database_url'
    || (normalized.startsWith('imap') && normalized.includes('password'));
}

function deleteSecretFields(payload) {
  for (const key of SECRET_FIELDS) {
    delete payload[key];
  }
  for (const key of Object.keys(payload)) {
    if (isSecretField(key)) delete payload[key];
  }
  return payload;
}

function safeObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value;
}

function sanitizeDebugValue(value) {
  if (Array.isArray(value)) {
    return value.slice(0, 20).map((entry) => sanitizeDebugValue(entry));
  }
  if (!value || typeof value !== 'object') return value ?? null;

  const result = {};
  for (const [key, entry] of Object.entries(value)) {
    if (isSecretField(key) || key === 'email_body') continue;
    result[key] = typeof entry === 'string' ? truncate(entry) : sanitizeDebugValue(entry);
  }
  return deleteSecretFields(result);
}

function sanitizeForStepTelemetry(item) {
  const telemetry = safeObject(item.telemetry);
  const classification = safeObject(item.classification);
  const destinationActions = safeObject(item.destination_actions);
  const payload = {
    workflow_id: telemetry.workflow_id || item.workflow_id || '',
    workflow_name: telemetry.workflow_name || item.workflow_name || '',
    execution_id: telemetry.execution_id || item.execution_id || '',
    run_id: telemetry.run_id || item.run_id || '',
    run_key: telemetry.run_key || item.run_key || '',
    sourceFlow: item.sourceFlow || '',
    account_id: item.credentialPairId || item.account_id || '',
    sourceMailbox: item.sourceMailbox || '',
    uidvalidity: String(item.uidvalidity || ''),
    uid: String(item.uid || ''),
    message_id: item.message_id || '',
    sender_email: item.sender_email || '',
    recipient_email: item.recipient_email || item.recipient || '',
    subject: item.email_subject || item.subject || '',
    body_preview: truncate(item.body_preview || item.email_body || ''),
    labels: sanitizeDebugValue(item.labels || classification.labels || item.classification_labels || []),
    target_mailboxes: sanitizeDebugValue(item.targetMailboxes || item.destination_mailboxes || []),
    model: item.model || item.ai_model || '',
    status: item.status || item.action_status || '',
    stopped_reason: item.stopped_reason || '',
    destination_actions: sanitizeDebugValue(destinationActions),
  };
  return deleteSecretFields(payload);
}

const item = $input.first()?.json ?? {};
const stepName = item.telemetry_step_name || $json.telemetry_step_name || 'unknown';
const stepType = item.telemetry_step_type || $json.telemetry_step_type || 'n8n-stage';
const sortOrder = Number(item.telemetry_step_sort_order ?? $json.telemetry_step_sort_order ?? 0);
const startedAt = new Date().toISOString();
const inputJson = sanitizeForStepTelemetry(item);

return [{
  json: {
    ...item,
    telemetry_step_started_at: startedAt,
    telemetry_step_params: [
      item.telemetry?.run_id || item.run_id || '',
      stepName,
      stepType,
      sortOrder,
      startedAt,
      payloadJson(inputJson),
      payloadJson(item),
    ],
  },
}];
