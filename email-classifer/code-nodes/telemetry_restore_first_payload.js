function parsePayload(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(String(value));
  } catch {
    return null;
  }
}

const first = $input.all()[0]?.json ?? {};
const payload = parsePayload(first.payload_json ?? first.payloadJson ?? first.payload);

return [{
  json: payload && typeof payload === 'object' ? payload : first,
}];
