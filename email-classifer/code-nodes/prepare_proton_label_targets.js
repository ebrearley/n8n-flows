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
    },
    category: acceptedCategory,
    labels: accepted,
    labelMailboxes,
    stateMailbox,
    targetMailboxes,
  },
}];
