const source = $('Build classification prompt').item.json;
const allowed = ["Invoice","Purchase","Bill","Payment","Marketing","Cold email","Important","Awaiting reply","Travel","Ticket","Infrastructure","Hustle","Schedule","Spam like","Account notification","Statement","Account (security)","Newsletter","Personal"];
const MIN_CONFIDENCE = 0.75;

function clampConfidence(value) {
  const confidence = Number(value ?? 0);
  if (!Number.isFinite(confidence)) return 0;
  return Math.max(0, Math.min(1, confidence));
}

function extractJsonText(value) {
  let text = String(value || '').trim();
  const fenced = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fenced) {
    text = fenced[1].trim();
  }

  if (!text.startsWith('{')) {
    const objectMatch = text.match(/\{[\s\S]*\}/);
    if (objectMatch) text = objectMatch[0];
  }

  return text;
}

function parseAiOutput(value) {
  if (value && typeof value === 'object') {
    if (value.category || Array.isArray(value.labels)) return value;
    if ('output' in value) return parseAiOutput(value.output);
  }
  if (typeof value === 'string') {
    return JSON.parse(extractJsonText(value));
  }
  return value;
}

function normalizeCategory(parsed) {
  if (parsed?.category && typeof parsed.category === 'object') {
    return {
      name: String(parsed.category.name ?? parsed.category.label ?? ''),
      confidence: clampConfidence(parsed.category.confidence),
    };
  }

  const labels = Array.isArray(parsed?.labels) ? parsed.labels : [];
  for (const item of labels) {
    const name = String(item?.label ?? item?.name ?? '');
    const confidence = clampConfidence(item?.confidence);
    if (allowed.includes(name) && confidence >= MIN_CONFIDENCE) {
      return { name, confidence };
    }
  }

  const fallbackConfidence = labels.length > 0
    ? clampConfidence(labels[0]?.confidence)
    : 0;
  return { name: 'uncertain', confidence: fallbackConfidence };
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

function normalizeActionHints(value) {
  const source = value && typeof value === 'object' ? value : {};
  const backupStatus = ['success', 'failure', 'warning', 'unknown'].includes(source.backup_status)
    ? source.backup_status
    : 'unknown';
  const eventTime = typeof source.event_time === 'string'
    ? source.event_time.trim()
    : '';

  return {
    two_factor_code: source.two_factor_code === true,
    event_notice: source.event_notice === true,
    event_time: isValidIsoDateTimeWithTimezone(eventTime) ? eventTime : null,
    backup_job: source.backup_job === true,
    backup_status: backupStatus,
    has_errors: typeof source.has_errors === 'boolean' ? source.has_errors : null,
  };
}

let parsed;
try {
  parsed = parseAiOutput($json.output ?? $json);
} catch (error) {
  parsed = {
    category: { name: 'uncertain', confidence: 0 },
    reason: 'format violation or instruction conflict',
  };
}

const parsedCategory = normalizeCategory(parsed);
const acceptedCategory = allowed.includes(parsedCategory.name) && parsedCategory.confidence >= MIN_CONFIDENCE
  ? parsedCategory
  : { name: 'uncertain', confidence: parsedCategory.confidence };

const accepted = acceptedCategory.name === 'uncertain'
  ? []
  : [{ label: acceptedCategory.name, confidence: acceptedCategory.confidence }];

const reason = String(
  parsed?.reason ?? (accepted.length ? 'Classifier returned a matching category' : 'No category reached confidence threshold'),
).slice(0, 240);
const actionHints = normalizeActionHints(parsed?.action_hints ?? parsed?.actionHints);
const labelPrefix = source.labelPrefix || 'Labels';
const stateLabel = source.stateLabel || 'Classified';
const labelMailboxes = accepted.map((item) => `${labelPrefix}/${item.label}`);
const stateMailbox = `${labelPrefix}/${stateLabel}`;
const targetMailboxes = [...labelMailboxes];
if (!targetMailboxes.includes(stateMailbox)) targetMailboxes.push(stateMailbox);

return [{
  json: {
    ...source,
    runMode: 'apply_labels',
    classification: {
      category: acceptedCategory,
      labels: accepted.length ? accepted : [{ label: 'uncertain', confidence: acceptedCategory.confidence }],
      reason,
      action_hints: actionHints,
    },
    category: acceptedCategory,
    actionHints,
    labels: accepted,
    labelMailboxes,
    stateMailbox,
    targetMailboxes,
  },
}];
