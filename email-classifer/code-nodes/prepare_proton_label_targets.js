const source = $('Build classification prompt').item.json;
const allowed = ["Invoice","Purchase","Bill","Payment","Marketing","Cold email","Important","Awaiting reply","Travel","Ticket","Infrastructure","Hustle","Schedule","Spam like"];

function clampConfidence(value) {
  const confidence = Number(value ?? 0);
  if (!Number.isFinite(confidence)) return 0;
  return Math.max(0, Math.min(1, confidence));
}

function cleanText(value, maxLength) {
  return String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLength);
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
    if (Array.isArray(value.labels) || Array.isArray(value.suggested_labels)) return value;
    if ('output' in value) return parseAiOutput(value.output);
  }
  if (typeof value === 'string') {
    return JSON.parse(extractJsonText(value));
  }
  return value;
}

function suggestedLabelKey(value) {
  return cleanText(value, 64).toLowerCase();
}

function sanitizeSuggestedLabels(value) {
  if (!Array.isArray(value)) return [];

  const suggestions = [];
  for (const item of value) {
    const label = cleanText(item?.label, 64);
    const reason = cleanText(item?.reason, 240);
    const criteria = cleanText(item?.criteria, 320);
    const key = suggestedLabelKey(label);

    if (!label || key === 'uncertain') continue;
    if (allowed.some((allowedLabel) => suggestedLabelKey(allowedLabel) === key)) continue;
    if (suggestions.some((existing) => suggestedLabelKey(existing.label) === key)) continue;

    suggestions.push({ label, reason, criteria });
    if (suggestions.length >= 5) break;
  }

  return suggestions;
}

let parsed;
try {
  parsed = parseAiOutput($json.output ?? $json);
} catch (error) {
  parsed = { labels: [{ label: 'uncertain', confidence: 0 }], reason: 'format violation or instruction conflict' };
}

const accepted = [];
const unknownLabels = [];
const parsedLabels = Array.isArray(parsed?.labels) ? parsed.labels : [];
for (const item of parsedLabels) {
  const label = cleanText(item?.label, 64);
  const confidence = clampConfidence(item?.confidence);
  if (label === 'uncertain') continue;
  if (!allowed.includes(label)) {
    const key = suggestedLabelKey(label);
    const isDuplicate = unknownLabels.some((existing) => suggestedLabelKey(existing.label) === key);
    if (label && unknownLabels.length < 5 && !isDuplicate) {
      unknownLabels.push({ label, confidence });
    }
    continue;
  }
  if (confidence < 0.75) continue;
  if (!accepted.some((existing) => existing.label === label)) {
    accepted.push({ label, confidence });
  }
}

const fallbackConfidence = parsedLabels.length > 0
  ? clampConfidence(parsedLabels[0]?.confidence)
  : 0;
const suggestedLabels = sanitizeSuggestedLabels(parsed?.suggested_labels);
const reason = cleanText(
  parsed?.reason ?? (accepted.length ? 'Classifier returned matching labels' : 'No label reached confidence threshold'),
  240,
);
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
      labels: accepted.length ? accepted : [{ label: 'uncertain', confidence: fallbackConfidence }],
      suggested_labels: suggestedLabels,
      unknown_labels: unknownLabels,
      reason,
    },
    labels: accepted,
    suggested_labels: suggestedLabels,
    unknown_labels: unknownLabels,
    labelMailboxes,
    stateMailbox,
    targetMailboxes,
  },
}];
