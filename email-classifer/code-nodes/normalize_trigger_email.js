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

function firstValue(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return '';
}

function stripHtml(value) {
  return String(value || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim();
}

const metadata = $json.metadata && typeof $json.metadata === 'object' ? $json.metadata : {};
const attributes = $json.attributes && typeof $json.attributes === 'object' ? $json.attributes : {};
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
    ?? $json['delivered-to']
    ?? metadata.deliveredTo
    ?? metadata['delivered-to']
    ?? metadata['x-original-to'],
);
const subject = String(firstValue($json.subject, $json.email_subject, $json.emailSubject));
const body = stripHtml(firstValue(
  $json.text,
  $json.textPlain,
  $json.body,
  $json.email_body,
  $json.emailBody,
  $json.textHtml,
  $json.html,
));
const credentialPair = {
  id: 'imap-1',
  host: '192.168.3.200',
  port: 1143,
  hostVar: 'IMAP_1_HOST',
  portVar: 'IMAP_1_PORT',
  ssl: false,
  startTls: true,
  allowUnauthorizedCerts: true,
  userVar: 'IMAP_1_USER',
  passwordVar: 'IMAP_1_PASSWORD',
  sourceMailboxes: ['INBOX'],
  labelPrefix: 'Labels',
  stateLabel: 'Classified',
};

return [{
  json: {
    ...$json,
    sourceFlow: 'trigger',
    runMode: 'apply_labels',
    uid: String(firstValue($json.uid, $json.imapUid, $json.messageUid, attributes.uid)),
    message_id: String(firstValue(
      $json.messageId,
      $json.message_id,
      $json['message-id'],
      metadata.messageId,
      metadata.message_id,
      metadata['message-id'],
      metadata['x-pm-external-id'],
    )),
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
    credentialPairId: credentialPair.id,
    credentialPair,
    dryRun: false,
    imapHost: '192.168.3.200',
    imapPort: 1143,
    imapSsl: false,
    imapStartTls: true,
  },
}];
