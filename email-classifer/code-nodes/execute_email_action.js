const item = $input.first()?.json ?? {};
const action = item.emailAction && typeof item.emailAction === 'object'
  ? item.emailAction
  : {};

return [{
  json: {
    ...item,
    email_action_status: action.approved ? 'skipped_executor_pending' : 'skipped_no_action',
    email_action_destination: action.destinationMailbox || '',
  },
}];
