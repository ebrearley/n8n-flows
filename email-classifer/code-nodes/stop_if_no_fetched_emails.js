const payload = $input.first()?.json ?? {};
const total = Number(payload.total_emails ?? (Array.isArray(payload.emails) ? payload.emails.length : 0));

if (!Number.isFinite(total) || total <= 0) {
  return [];
}

return [{ json: payload }];
