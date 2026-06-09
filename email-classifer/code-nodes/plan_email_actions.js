const item = $input.first()?.json ?? {};
const HOURS_24_MS = 24 * 60 * 60 * 1000;

function stringValue(value, fallback = '') {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value);
}

function actionMode(value) {
  const mode = stringValue(value, 'live').toLowerCase();
  return ['live', 'dry_run', 'disabled'].includes(mode) ? mode : 'live';
}

function labelsOf(source) {
  if (!Array.isArray(source.labels)) return new Set();
  return new Set(source.labels.map((label) => label?.label).filter(Boolean));
}

function hintsOf(source) {
  const hints = source.actionHints || source.action_hints || source.classification?.action_hints || {};
  return hints && typeof hints === 'object' ? hints : {};
}

function parseDate(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function noAction(reason, mode) {
  return {
    action: 'none',
    destinationMailbox: '',
    reason,
    approved: false,
    mode,
  };
}

function approved(action, destinationMailbox, reason, mode) {
  return {
    action,
    destinationMailbox,
    reason,
    approved: true,
    mode,
  };
}

const mode = actionMode(item.emailActionsMode ?? item.email_actions_mode);
const labelNames = labelsOf(item);
const actionHints = hintsOf(item);
const now = parseDate(item.actionNow || item.workflowNow || item.now) || new Date();
const archiveMailbox = stringValue(item.actionArchiveMailbox, 'Archive');
const spamMailbox = stringValue(item.actionSpamMailbox, 'Spam');
const trashMailbox = stringValue(item.actionTrashMailbox, 'Trash');

let emailAction = noAction('no_rule_matched', mode);

if (mode === 'disabled') {
  emailAction = noAction('actions_disabled', mode);
} else if (labelNames.has('Spam like')) {
  emailAction = approved('move_to_spam', spamMailbox, 'spam_like', mode);
} else if (actionHints.two_factor_code === true) {
  const emailDate = parseDate(item.date || item.email_date || item.receivedAt);
  if (emailDate && now.getTime() - emailDate.getTime() > HOURS_24_MS) {
    emailAction = approved('move_to_trash', trashMailbox, 'expired_two_factor_code', mode);
  } else {
    emailAction = noAction(emailDate ? 'two_factor_code_still_recent' : 'invalid_email_date', mode);
  }
} else if (labelNames.has('Schedule') && actionHints.event_notice === true) {
  const eventTime = parseDate(actionHints.event_time);
  if (eventTime && eventTime.getTime() < now.getTime()) {
    emailAction = approved('archive', archiveMailbox, 'past_event', mode);
  } else {
    emailAction = noAction(eventTime ? 'event_not_past' : 'invalid_event_time', mode);
  }
} else if (
  labelNames.has('Infrastructure')
  && actionHints.backup_job === true
  && actionHints.backup_status === 'success'
  && actionHints.has_errors !== true
) {
  emailAction = approved('archive', archiveMailbox, 'successful_backup', mode);
}

return [{
  json: {
    ...item,
    emailAction,
    email_action_status: emailAction.approved ? 'planned' : 'skipped_no_action',
    email_action_destination: emailAction.destinationMailbox,
  },
}];
