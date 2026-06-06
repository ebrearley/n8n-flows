const net = require('net');
const tls = require('tls');

class ImapClient {
  constructor(config) {
    this.host = config.host;
    this.port = config.port;
    this.ssl = config.ssl;
    this.startTls = config.startTls;
    this.allowUnauthorizedCerts = config.allowUnauthorizedCerts;
    this.socket = null;
    this.buffer = '';
    this.waiters = [];
    this.tagCounter = 0;
  }

  attachSocket(socket) {
    this.socket = socket;
    this.socket.setEncoding('binary');
    this.socket.on('data', (chunk) => {
      this.buffer += chunk;
      this.flushWaiters();
    });
    this.socket.on('error', (error) => {
      for (const waiter of this.waiters.splice(0)) waiter.reject(error);
    });
  }

  flushWaiters() {
    for (let index = 0; index < this.waiters.length; index += 1) {
      const waiter = this.waiters[index];
      let result;
      try {
        result = waiter.tryRead(this.buffer);
      } catch (error) {
        clearTimeout(waiter.timer);
        this.waiters.splice(index, 1);
        waiter.reject(error);
        index -= 1;
        continue;
      }
      if (!result) continue;
      clearTimeout(waiter.timer);
      this.buffer = this.buffer.slice(result.consumed);
      this.waiters.splice(index, 1);
      waiter.resolve(result.value);
      index -= 1;
    }
  }

  readWith(tryRead, timeoutMs = 30000) {
    return new Promise((resolve, reject) => {
      const waiter = {
        tryRead,
        resolve,
        reject,
        timer: setTimeout(() => {
          const idx = this.waiters.indexOf(waiter);
          if (idx >= 0) this.waiters.splice(idx, 1);
          reject(new Error('Timed out waiting for IMAP response'));
        }, timeoutMs),
      };
      this.waiters.push(waiter);
      this.flushWaiters();
    });
  }

  readLine() {
    return this.readWith((buffer) => {
      const end = buffer.indexOf('\r\n');
      if (end < 0) return null;
      return { value: buffer.slice(0, end), consumed: end + 2 };
    });
  }

  async connect() {
    const socket = this.ssl
      ? tls.connect({
          host: this.host,
          port: this.port,
          servername: this.host,
          rejectUnauthorized: !this.allowUnauthorizedCerts,
        })
      : net.connect({ host: this.host, port: this.port });

    this.attachSocket(socket);
    await new Promise((resolve, reject) => {
      socket.once('connect', resolve);
      socket.once('secureConnect', resolve);
      socket.once('error', reject);
    });
    await this.readLine();

    if (!this.ssl && this.startTls) {
      await this.command('STARTTLS');
      this.socket.removeAllListeners('data');
      this.socket = tls.connect({
        socket: this.socket,
        servername: this.host,
        rejectUnauthorized: !this.allowUnauthorizedCerts,
      });
      this.attachSocket(this.socket);
      await new Promise((resolve, reject) => {
        this.socket.once('secureConnect', resolve);
        this.socket.once('error', reject);
      });
    }
  }

  nextTag() {
    this.tagCounter += 1;
    return `A${String(this.tagCounter).padStart(4, '0')}`;
  }

  command(commandText, timeoutMs = 60000) {
    const tag = this.nextTag();
    this.socket.write(`${tag} ${commandText}\r\n`, 'binary');
    const pattern = new RegExp(`(^|\\r\\n)${tag} (OK|NO|BAD)[^\\r\\n]*(\\r\\n|$)`);
    return this.readWith((buffer) => {
      const match = pattern.exec(buffer);
      if (!match) return null;
      const end = match.index + match[0].length;
      const response = buffer.slice(0, end);
      if (match[2] !== 'OK') throw new Error(`IMAP ${commandText} failed: ${response}`);
      return { value: response, consumed: end };
    }, timeoutMs);
  }

  async login(username, password) {
    await this.command(`LOGIN ${quoteString(username)} ${quoteString(password)}`);
  }

  async select(mailbox) {
    await this.command(`SELECT ${quoteString(mailbox)}`);
  }

  async mailboxExists(mailbox) {
    const response = await this.command(`LIST "" ${quoteString(mailbox)}`);
    return /\* LIST /i.test(response);
  }

  async searchAll(mailbox) {
    await this.select(mailbox);
    const response = await this.command('UID SEARCH ALL');
    return parseSearchResponse(response);
  }

  async searchMessageId(mailbox, messageId) {
    await this.select(mailbox);
    const response = await this.command(`UID SEARCH HEADER Message-ID ${quoteString(messageId)}`);
    return parseSearchResponse(response);
  }

  async fetchRaw(uid, mailbox) {
    await this.select(mailbox);
    const response = await this.command(`UID FETCH ${uid} (BODY.PEEK[])`, 120000);
    return firstLiteral(response);
  }

  async logout() {
    try {
      await this.command('LOGOUT', 10000);
    } finally {
      this.socket?.end();
    }
  }
}

function quoteString(value) {
  return `"${String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

function parseSearchResponse(response) {
  const match = response.match(/\* SEARCH([^\r\n]*)/i);
  if (!match) return [];
  return match[1].trim().split(/\s+/).filter(Boolean);
}

function firstLiteral(response) {
  const match = response.match(/\{(\d+)\}\r\n/);
  if (!match) throw new Error('IMAP FETCH response did not include a message literal');
  const start = match.index + match[0].length;
  const length = Number(match[1]);
  return response.slice(start, start + length);
}

function parseHeaders(rawHeaders) {
  const headers = {};
  const unfolded = rawHeaders.replace(/\r?\n[ \t]+/g, ' ');
  for (const line of unfolded.split(/\r?\n/)) {
    const idx = line.indexOf(':');
    if (idx < 0) continue;
    const key = line.slice(0, idx).trim().toLowerCase();
    const value = line.slice(idx + 1).trim();
    if (!headers[key]) headers[key] = value;
  }
  return headers;
}

function decodeEncodedWords(value) {
  return String(value || '').replace(/=\?([^?]+)\?([bqBQ])\?([^?]*)\?=/g, (_match, charset, encoding, text) => {
    try {
      const normalized = encoding.toUpperCase() === 'B'
        ? Buffer.from(text.replace(/\s+/g, ''), 'base64')
        : Buffer.from(text.replace(/_/g, ' ').replace(/=([a-fA-F0-9]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16))), 'binary');
      return normalized.toString(/utf-?8/i.test(charset) ? 'utf8' : 'latin1');
    } catch {
      return text;
    }
  });
}

function senderParts(header) {
  const decoded = decodeEncodedWords(header || '');
  const match = decoded.match(/^(.*?)\s*<([^>]+)>$/);
  if (match) {
    return {
      from: decoded,
      sender_name: match[1].replace(/^"|"$/g, '').trim(),
      sender_email: match[2].trim(),
    };
  }
  return {
    from: decoded,
    sender_name: '',
    sender_email: decoded.includes('@') ? decoded.trim() : '',
  };
}

function decodeQuotedPrintable(value) {
  return String(value || '')
    .replace(/=\r?\n/g, '')
    .replace(/=([a-fA-F0-9]{2})/g, (_match, hex) => String.fromCharCode(parseInt(hex, 16)));
}

function decodeBody(body, headers) {
  const encoding = String(headers['content-transfer-encoding'] || '').toLowerCase();
  if (encoding === 'base64') {
    return Buffer.from(String(body || '').replace(/\s+/g, ''), 'base64').toString('utf8');
  }
  if (encoding === 'quoted-printable') {
    return Buffer.from(decodeQuotedPrintable(body), 'binary').toString('utf8');
  }
  return String(body || '');
}

function stripHtml(value) {
  return String(value || '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim();
}

function splitRawMessage(raw) {
  const delimiter = raw.includes('\r\n\r\n') ? '\r\n\r\n' : '\n\n';
  const idx = raw.indexOf(delimiter);
  if (idx < 0) return { headersRaw: raw, bodyRaw: '' };
  return {
    headersRaw: raw.slice(0, idx),
    bodyRaw: raw.slice(idx + delimiter.length),
  };
}

function messageBody(raw, headers) {
  const bodyRaw = splitRawMessage(raw).bodyRaw;
  const contentType = String(headers['content-type'] || '').toLowerCase();
  const boundary = /boundary="?([^";]+)"?/i.exec(headers['content-type'] || '')?.[1];

  if (boundary) {
    const parts = bodyRaw.split(`--${boundary}`);
    let htmlFallback = '';
    for (const part of parts) {
      const split = splitRawMessage(part.trim());
      const partHeaders = parseHeaders(split.headersRaw);
      const partType = String(partHeaders['content-type'] || '').toLowerCase();
      if (/attachment/i.test(partHeaders['content-disposition'] || '')) continue;
      const decoded = decodeBody(split.bodyRaw, partHeaders);
      if (partType.includes('text/plain') && decoded.trim()) return decoded.trim();
      if (partType.includes('text/html') && !htmlFallback) htmlFallback = stripHtml(decoded);
    }
    return htmlFallback;
  }

  const decoded = decodeBody(bodyRaw, headers);
  return contentType.includes('text/html') ? stripHtml(decoded) : decoded.trim();
}

function summaryFromRaw(uid, raw, config) {
  const split = splitRawMessage(raw);
  const headers = parseHeaders(split.headersRaw);
  const sender = senderParts(headers.from || '');
  const subject = decodeEncodedWords(headers.subject || '');
  const body = messageBody(raw, headers).replace(/\s+/g, ' ').trim().slice(0, 4000);

  return {
    uid: String(uid),
    message_id: headers['message-id'] || '',
    ...sender,
    subject,
    email_subject: subject,
    date: headers.date || '',
    body_preview: body,
    email_body: body,
    sourceFlow: 'bulk',
    runMode: 'apply_labels',
    sourceMailbox: config.sourceMailbox,
    labelPrefix: config.labelPrefix,
    stateLabel: config.stateLabel,
    dryRun: config.dryRun,
    imapHost: config.host,
    imapPort: config.port,
    imapSsl: config.ssl,
    imapStartTls: config.startTls,
  };
}

function configValue(source, key, fallback) {
  const value = source[key];
  return value === undefined || value === null || value === '' ? fallback : value;
}

function boolValue(value, fallback = false) {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'boolean') return value;
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
}

function envValue(name) {
  try {
    if (typeof $vars !== 'undefined' && $vars?.[name]) return $vars[name];
  } catch {}
  try {
    if (typeof vars !== 'undefined' && vars?.[name]) return vars[name];
  } catch {}
  try {
    if (typeof $env !== 'undefined' && $env?.[name]) return $env[name];
  } catch {}
  try {
    if (typeof env !== 'undefined' && env?.[name]) return env[name];
  } catch {}
  return '';
}

let inputConfig = {};
try {
  inputConfig = $('Configure Proton IMAP batch').first().json;
} catch {
  inputConfig = $input.first()?.json ?? {};
}

const runIndex = typeof $runIndex === 'number' ? $runIndex : 0;
const config = {
  host: String(configValue(inputConfig, 'imapHost', '192.168.3.200')),
  port: Number(configValue(inputConfig, 'imapPort', 1143)),
  ssl: boolValue(inputConfig.imapSsl, false),
  startTls: boolValue(inputConfig.imapStartTls, true),
  allowUnauthorizedCerts: boolValue(inputConfig.allowUnauthorizedCerts, true),
  sourceMailbox: String(configValue(inputConfig, 'sourceMailbox', 'INBOX')),
  labelPrefix: String(configValue(inputConfig, 'labelPrefix', 'Labels')),
  stateLabel: String(configValue(inputConfig, 'stateLabel', 'Classified')),
  batchLimit: Number(configValue(inputConfig, 'batchLimit', 50)),
  dryRun: boolValue(inputConfig.dryRun, false),
};

if (config.dryRun && runIndex > 0) {
  return [{ json: { emails: [], total_emails: 0, stopped_reason: 'dry_run_single_batch' } }];
}

const username = envValue('IMAP_USER');
const password = envValue('IMAP_PASSWORD');
if (!username || !password) {
  throw new Error('IMAP_USER and IMAP_PASSWORD must be set in the n8n runtime environment for manual batch processing.');
}

const stateMailbox = `${config.labelPrefix}/${config.stateLabel}`;
const client = new ImapClient(config);
const emails = [];
const warnings = [];

try {
  await client.connect();
  await client.login(username, password);

  const stateMailboxExists = await client.mailboxExists(stateMailbox);
  if (!stateMailboxExists && !config.dryRun) {
    throw new Error(`Required Proton label mailbox does not exist: ${stateMailbox}`);
  }
  if (!stateMailboxExists) warnings.push(`State mailbox not found during dry-run: ${stateMailbox}`);

  const uids = (await client.searchAll(config.sourceMailbox)).reverse();
  for (const uid of uids) {
    const raw = await client.fetchRaw(uid, config.sourceMailbox);
    const summary = summaryFromRaw(uid, raw, config);
    if (stateMailboxExists && summary.message_id) {
      const matches = await client.searchMessageId(stateMailbox, summary.message_id);
      if (matches.length > 0) continue;
    }
    emails.push(summary);
    if (emails.length >= config.batchLimit) break;
  }
} finally {
  await client.logout().catch(() => {});
}

return [{
  json: {
    emails,
    warnings,
    total_emails: emails.length,
    stopped_reason: emails.length ? 'batch_ready' : 'inbox_fully_classified',
  },
}];
