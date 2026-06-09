const DEFAULT_CLEAN_TEXT_LIMIT = 4000;
const BODY_PREVIEW_LIMIT = 500;

function numberValue(value, fallback, description) {
  const raw = value === undefined || value === null || value === '' ? fallback : value;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed < 1) {
    throw new Error(`${description} must be a positive number`);
  }
  return parsed;
}

function decodeHtmlEntities(value) {
  return String(value || '')
    .replace(/&nbsp;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/g, "'");
}

function stripHtml(value) {
  return decodeHtmlEntities(value)
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ');
}

function normalizeWhitespace(value) {
  return String(value || '').replace(/\s+/g, ' ').trim();
}

function sourceBody(item) {
  return item.email_body
    ?? item.emailBody
    ?? item.body
    ?? item.textPlain
    ?? item.text
    ?? item.html
    ?? item.textHtml
    ?? item.body_preview
    ?? '';
}

function codePointLength(value) {
  return Array.from(String(value || '')).length;
}

function truncateCodePoints(value, limit) {
  return Array.from(String(value || '')).slice(0, limit).join('').trim();
}

const inputItems = $input.all();

return inputItems.map((item) => {
  const json = item.json ?? {};
  const cleanEmailTextLimit = numberValue(
    json.cleanEmailTextLimit ?? json.classifierTextLimit ?? json.emailTextLimit,
    DEFAULT_CLEAN_TEXT_LIMIT,
    'Clean email text limit',
  );
  const normalized = normalizeWhitespace(stripHtml(sourceBody(json)));
  const normalizedLength = codePointLength(normalized);
  const cleanEmailTruncated = normalizedLength > cleanEmailTextLimit;
  const cleanEmailText = cleanEmailTruncated
    ? truncateCodePoints(normalized, cleanEmailTextLimit)
    : normalized;
  const bodyPreview = truncateCodePoints(cleanEmailText, BODY_PREVIEW_LIMIT);

  return {
    json: {
      ...json,
      cleanEmailText,
      cleanEmailTextLength: normalizedLength,
      cleanEmailTruncated,
      cleanEmailTextLimit,
      email_body: cleanEmailText,
      emailBody: cleanEmailText,
      body: cleanEmailText,
      textPlain: cleanEmailText,
      text: cleanEmailText,
      html: cleanEmailText,
      textHtml: cleanEmailText,
      body_preview: bodyPreview,
    },
  };
});
