function payloadJson(value) {
  return JSON.stringify(value ?? {});
}

function headerJson(email) {
  return {
    date: email.date || '',
    message_id: email.message_id || '',
    from: email.from || email.sender_email || '',
    to: email.to || email.recipient_email || email.recipient || '',
    subject: email.email_subject || email.subject || '',
  };
}

const inputs = $input.all().map((item) => item.json ?? {});
const parent = inputs[0] ?? {};
const parentTelemetry = parent.telemetry || {};
const emails = inputs.length === 1 && Array.isArray(parent.emails)
  ? parent.emails.map((email) => ({
      ...email,
      telemetry: email.telemetry || parentTelemetry,
    }))
  : inputs;

return emails.map((email) => {
  const item = {
    ...email,
    telemetry: email.telemetry || parentTelemetry,
  };

  return {
    json: {
      ...item,
      telemetry_payload_json: payloadJson(item),
      email_telemetry_params: [
        item.credentialPairId || item.account_id || 'imap-1',
        item.sourceMailbox || 'INBOX',
        String(item.uidvalidity || ''),
        String(item.uid || ''),
        item.message_id || '',
        payloadJson(item.headers || headerJson(item)),
        item.raw || item.raw_content || '',
        item.email_body || item.body_preview || '',
        item.sender_email || '',
        item.sender_name || '',
        item.recipient_email || item.recipient || '',
        item.recipient_name || '',
        item.email_subject || item.subject || '',
        payloadJson(item),
      ],
    },
  };
});
