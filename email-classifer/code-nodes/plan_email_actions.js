const item = $input.first()?.json ?? {};

return [{
  json: {
    ...item,
    emailAction: {
      action: 'none',
      destinationMailbox: '',
      reason: 'planner_not_configured',
      approved: false,
      mode: item.emailActionsMode || 'live',
    },
    email_action_status: 'not_planned',
    email_action_destination: '',
  },
}];
