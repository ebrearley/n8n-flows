function estimateTokens(value) {
  return Math.ceil(String(value || '').length / 4);
}

function extractJsonText(value) {
  let text = String(value || '').trim();
  const fenced = text.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fenced) text = fenced[1].trim();
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
  if (typeof value === 'string') return JSON.parse(extractJsonText(value));
  return value;
}

function payloadJson(value) {
  return JSON.stringify(value ?? {});
}

const source = $('Build classification prompt').item.json;
const prompt = `${source.systemPrompt || ''}\n\n${source.userPrompt || ''}`;
const rawResponse = typeof $json.output === 'string'
  ? $json.output
  : JSON.stringify($json.output ?? $json);

let parsed;
try {
  parsed = parseAiOutput($json.output ?? $json);
} catch (error) {
  parsed = {
    labels: [{ label: 'uncertain', confidence: 0 }],
    reason: 'format violation or instruction conflict',
  };
}

const labels = Array.isArray(parsed?.labels) ? parsed.labels : [];
const status = labels.some((item) => item?.label === 'uncertain') ? 'uncertain' : 'success';
const model = 'odytrice/gemma4-26b:4090';
const item = {
  ...source,
  output: $json.output ?? $json,
  classifier_output: $json,
  classification_raw_response: rawResponse,
};

console.log(JSON.stringify({
  service: 'n8n',
  workflow_id: source.telemetry?.workflow_id,
  workflow_name: source.telemetry?.workflow_name,
  execution_id: source.telemetry?.execution_id,
  run_key: source.telemetry?.run_key,
  step: 'classify',
  status,
  account_id: source.credentialPairId,
  mailbox: source.sourceMailbox,
  message_id: source.message_id,
  subject: source.email_subject,
  model,
}));

return [{
  json: {
    ...item,
    telemetry_payload_json: payloadJson(item),
    classification_attempt_params: [
      source.telemetry?.run_id || source.run_id || '',
      source.email_item_id || '',
      model,
      prompt,
      rawResponse,
      payloadJson(parsed || {}),
      payloadJson(labels),
      estimateTokens(prompt),
      estimateTokens(rawResponse),
      status,
      payloadJson(item),
    ],
  },
}];
