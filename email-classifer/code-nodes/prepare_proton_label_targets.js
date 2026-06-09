const source = $('Build classification prompt').item.json;
const allowed = ["Invoice","Purchase","Bill","Payment","Marketing","Cold email","Important","Awaiting reply","Travel","Ticket","Infrastructure","Hustle","Schedule","Spam like","Account notification","Statement","Account (security)","Newsletter","Personal"];

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
    if (Array.isArray(value.labels)) return value;
    if ('output' in value) return parseAiOutput(value.output);
  }
  if (typeof value === 'string') {
    return JSON.parse(extractJsonText(value));
  }
  return value;
}

let parsed;
try {
  parsed = parseAiOutput($json.output ?? $json);
} catch (error) {
  parsed = { labels: [{ label: 'uncertain', confidence: 0 }], reason: 'format violation or instruction conflict' };
}

const accepted = [];
const parsedLabels = Array.isArray(parsed?.labels) ? parsed.labels : [];
for (const item of parsedLabels) {
  const label = item?.label;
  const confidence = clampConfidence(item?.confidence);
  if (!allowed.includes(label) || confidence < 0.75) continue;
  if (!accepted.some((existing) => existing.label === label)) {
    accepted.push({ label, confidence });
  }
}

const fallbackConfidence = parsedLabels.length > 0
  ? clampConfidence(parsedLabels[0]?.confidence)
  : 0;
const reason = String(parsed?.reason ?? (accepted.length ? 'Classifier returned matching labels' : 'No label reached confidence threshold')).slice(0, 240);
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
      reason,
    },
    labels: accepted,
    labelMailboxes,
    stateMailbox,
    targetMailboxes,
  },
}];
