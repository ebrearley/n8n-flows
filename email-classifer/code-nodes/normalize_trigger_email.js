function parseSender(value) {
  if (Array.isArray(value)) return parseSender(value[0]);
  if (value && typeof value === 'object') {
    if (Array.isArray(value.value)) return parseSender(value.value[0]);
    if (Array.isArray(value.addresses)) return parseSender(value.addresses[0]);

    const email = value.email || value.address || value.mail || '';
    const name = value.name || value.displayName || '';
    const header = String(value.value || value.text || (name || email ? `${name} <${email}>` : ''));
    return { header, name, email };
  }

  const header = String(value || '');
  const match = header.match(/^(.*?)\s*<([^>]+)>$/);
  if (match) {
    return { header, name: match[1].replace(/^"|"$/g, '').trim(), email: match[2].trim() };
  }
  return { header, name: '', email: header.includes('@') ? header.trim() : '' };
}

const sender = parseSender($json.from ?? $json.sender ?? $json.sender_email ?? $json.senderEmail);
const recipient = parseSender(
  $json.to
    ?? $json.recipient
    ?? $json.recipients
    ?? $json.recipient_email
    ?? $json.recipientEmail
    ?? $json.to_email
    ?? $json.toEmail
    ?? $json.deliveredTo
    ?? $json['delivered-to'],
);
const subject = String($json.subject ?? $json.email_subject ?? $json.emailSubject ?? '');
const body = String($json.text ?? $json.textPlain ?? $json.body ?? $json.email_body ?? $json.emailBody ?? '');

return [{
  json: {
    ...$json,
    sourceFlow: 'trigger',
    runMode: 'apply_labels',
    uid: String($json.uid ?? $json.imapUid ?? $json.messageUid ?? ''),
    message_id: String($json.messageId ?? $json.message_id ?? $json['message-id'] ?? ''),
    from: sender.header,
    sender_name: sender.name,
    sender_email: sender.email,
    to: recipient.header,
    recipient: recipient.email || recipient.header,
    recipient_name: recipient.name,
    recipient_email: recipient.email,
    subject,
    email_subject: subject,
    body_preview: body.slice(0, 4000),
    email_body: body.slice(0, 4000),
    sourceMailbox: 'INBOX',
    labelPrefix: 'Labels',
    stateLabel: 'Classified',
    dryRun: false,
    imapHost: '192.168.3.200',
    imapPort: 1143,
    imapSsl: false,
    imapStartTls: true,
  },
}];
