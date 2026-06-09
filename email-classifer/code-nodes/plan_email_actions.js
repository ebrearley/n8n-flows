const item = $input.first()?.json ?? {};
const HOURS_24_MS = 24 * 60 * 60 * 1000;
const ALLOWED_LABELS = new Set([
  'Invoice',
  'Purchase',
  'Bill',
  'Payment',
  'Marketing',
  'Cold email',
  'Important',
  'Awaiting reply',
  'Travel',
  'Ticket',
  'Infrastructure',
  'Hustle',
  'Schedule',
  'Spam like',
]);
const EMAIL_MONTHS = {
  Jan: 1,
  Feb: 2,
  Mar: 3,
  Apr: 4,
  May: 5,
  Jun: 6,
  Jul: 7,
  Aug: 8,
  Sep: 9,
  Oct: 10,
  Nov: 11,
  Dec: 12,
};

function stringValue(value, fallback = '') {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value);
}

function actionMode(value) {
  const mode = stringValue(value, 'live').toLowerCase();
  return ['live', 'dry_run', 'disabled'].includes(mode) ? mode : 'live';
}

function clampConfidence(value) {
  const confidence = Number(value ?? 0);
  if (!Number.isFinite(confidence)) return 0;
  return Math.max(0, Math.min(1, confidence));
}

function labelsOf(source) {
  if (!Array.isArray(source.labels)) return new Set();
  return new Set(
    source.labels
      .filter((label) => ALLOWED_LABELS.has(label?.label) && clampConfidence(label?.confidence) >= 0.75)
      .map((label) => label.label),
  );
}

function hintsOf(source) {
  const hints = source.actionHints || source.action_hints || source.classification?.action_hints || {};
  return hints && typeof hints === 'object' ? hints : {};
}

function hasUncertainLabel(labels) {
  return Array.isArray(labels) && labels.some((label) => label?.label === 'uncertain');
}

function parseDate(value) {
  if (value === undefined || value === null) return null;
  if (typeof value === 'string' && value.trim() === '') return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function isLeapYear(year) {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}

function daysInMonth(year, month) {
  if (month === 2) return isLeapYear(year) ? 29 : 28;
  if ([4, 6, 9, 11].includes(month)) return 30;
  return 31;
}

function isValidIsoDateTimeWithTimezone(value) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?(Z|[+-](\d{2}):(\d{2}))$/);
  if (!match) return false;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = match[6] === undefined ? 0 : Number(match[6]);
  const offsetHour = match[8] === undefined ? 0 : Number(match[8]);
  const offsetMinute = match[9] === undefined ? 0 : Number(match[9]);

  if (month < 1 || month > 12) return false;
  if (day < 1 || day > daysInMonth(year, month)) return false;
  if (hour > 23 || minute > 59 || second > 59) return false;
  if (offsetHour > 23 || offsetMinute > 59) return false;

  return true;
}

function parseEventTime(value) {
  if (!isValidIsoDateTimeWithTimezone(value)) return null;
  return parseDate(value);
}

function parseEmailDate(value) {
  if (value === undefined || value === null) return null;
  if (typeof value !== 'string') return parseDate(value);

  const text = value.trim();
  if (text === '') return null;
  if (isValidIsoDateTimeWithTimezone(text)) return parseDate(text);
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return null;

  const match = text.match(/^(?:[A-Za-z]{3},\s*)?(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?\s+([+-])(\d{2})(\d{2})$/);
  if (!match) return null;

  const day = Number(match[1]);
  const month = EMAIL_MONTHS[match[2]];
  const year = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = match[6] === undefined ? 0 : Number(match[6]);
  const offsetHour = Number(match[8]);
  const offsetMinute = Number(match[9]);

  if (!month) return null;
  if (day < 1 || day > daysInMonth(year, month)) return null;
  if (hour > 23 || minute > 59 || second > 59) return null;
  if (offsetHour > 23 || offsetMinute > 59) return null;

  return parseDate(text);
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
const classificationLabels = Array.isArray(item.classification?.labels) ? item.classification.labels : [];
const hasUncertainClassification = hasUncertainLabel(item.labels) || hasUncertainLabel(classificationLabels);
const now = parseDate(item.actionNow || item.workflowNow || item.now) || new Date();
const archiveMailbox = stringValue(item.actionArchiveMailbox, 'Archive');
const spamMailbox = stringValue(item.actionSpamMailbox, 'Spam');
const trashMailbox = stringValue(item.actionTrashMailbox, 'Trash');

let emailAction = noAction('no_rule_matched', mode);

if (mode === 'disabled') {
  emailAction = noAction('actions_disabled', mode);
} else if (hasUncertainClassification) {
  emailAction = noAction('uncertain_classification', mode);
} else if (labelNames.size === 0) {
  emailAction = noAction('no_accepted_labels', mode);
} else if (labelNames.has('Spam like')) {
  emailAction = approved('move_to_spam', spamMailbox, 'spam_like', mode);
} else if (actionHints.two_factor_code === true) {
  const emailDate = parseEmailDate(item.date || item.email_date || item.receivedAt);
  if (emailDate && now.getTime() - emailDate.getTime() > HOURS_24_MS) {
    emailAction = approved('move_to_trash', trashMailbox, 'expired_two_factor_code', mode);
  } else {
    emailAction = noAction(emailDate ? 'two_factor_code_still_recent' : 'invalid_email_date', mode);
  }
} else if (labelNames.has('Schedule') && actionHints.event_notice === true) {
  const eventTime = parseEventTime(actionHints.event_time);
  if (eventTime && eventTime.getTime() < now.getTime()) {
    emailAction = approved('archive', archiveMailbox, 'past_event', mode);
  } else {
    emailAction = noAction(eventTime ? 'event_not_past' : 'invalid_event_time', mode);
  }
} else if (
  labelNames.has('Infrastructure')
  && actionHints.backup_job === true
  && actionHints.backup_status === 'success'
  && actionHints.has_errors === false
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
