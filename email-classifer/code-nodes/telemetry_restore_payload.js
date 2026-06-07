function parsePayload(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;
  try {
    return JSON.parse(String(value));
  } catch {
    return null;
  }
}

return $input.all().map((item) => {
  const json = item.json ?? {};
  const payload = parsePayload(json.payload_json ?? json.payloadJson ?? json.payload);

  return {
    json: payload && typeof payload === 'object' ? payload : json,
  };
});
