function payloadJson(value) {
  return JSON.stringify(value ?? {});
}

function truncate(value) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, 500);
}

const SECRET_FIELDS = [
  'password',
  'api_key',
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
    || normalized === 'api_key'
    || normalized === 'n8n_api_key'
    || normalized.endsWith('_api_key')
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
    step_id: item.telemetry_step_id || item.step_id || '',
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
    destination_actions: sanitizeDebugValue(destinationActions),
    total_emails: item.total_emails || 0,
    status: item.status || item.action_status || '',
    stopped_reason: item.stopped_reason || '',
  };
  return deleteSecretFields(payload);
}

return $input.all().map((inputItem, index) => {
  const item = inputItem.json ?? {};
  const stoppedAt = new Date().toISOString();
  const status = item.error ? 'error' : 'success';
  const errorJson = item.error
    ? payloadJson({ message: truncate(item.error.message || item.error) })
    : null;
  const outputJson = sanitizeForStepTelemetry(item);

  return {
    json: {
      ...item,
      telemetry_step_stopped_at: stoppedAt,
      telemetry_step_source_index: index,
      telemetry_step_finish_params: [
        item.telemetry_step_id || item.step_id || '',
        status,
        stoppedAt,
        payloadJson(outputJson),
        errorJson,
        index,
      ],
    },
    pairedItem: index,
  };
});
