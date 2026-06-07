function actionStatus(value) {
  if (value === 'skipped_missing_mailbox') return 'skipped_missing_mailbox';
  if (value === 'label_applied' || value === 'would_apply_label') return 'success';
  return 'error';
}

function payloadJson(value) {
  return JSON.stringify(value ?? {});
}

const item = $input.first()?.json ?? {};
const destinationActions = item.destination_actions && typeof item.destination_actions === 'object'
  ? item.destination_actions
  : {};
const targets = Object.entries(destinationActions);

if (targets.length === 0) {
  return [{
    json: {
      ...item,
      label_action_params: [
        item.telemetry?.run_key,
        item.credentialPairId || item.account_id || 'imap-1',
        item.sourceMailbox || 'INBOX',
        String(item.uidvalidity || ''),
        String(item.uid || ''),
        '',
        'error',
        String(item.uid || ''),
        item.recipient_email || item.recipient || '',
        item.recipient_name || '',
        payloadJson({ error: 'No destination actions were recorded' }),
        payloadJson(item),
      ],
    },
  }];
}

return targets.map(([mailbox, action]) => {
  const status = actionStatus(action);
  const errorJson = status === 'skipped_missing_mailbox'
    ? {
        missingMailboxes: item.missingMailboxes || [mailbox],
        recipient_email: item.recipient_email || item.recipient || '',
      }
    : null;

  return {
    json: {
      ...item,
      label_action_params: [
        item.telemetry?.run_key,
        item.credentialPairId || item.account_id || 'imap-1',
        item.sourceMailbox || 'INBOX',
        String(item.uidvalidity || ''),
        String(item.uid || ''),
        mailbox,
        status,
        String(item.uid || ''),
        item.recipient_email || item.recipient || '',
        item.recipient_name || '',
        errorJson === null ? null : payloadJson(errorJson),
        payloadJson(item),
      ],
    },
  };
});
