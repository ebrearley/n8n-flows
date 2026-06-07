const net = require('net');
const tls = require('tls');

const SOURCE_HEADER_FIELDS = [
  'FROM',
  'TO',
  'SUBJECT',
  'DATE',
  'MESSAGE-ID',
  'DELIVERED-TO',
  'X-ORIGINAL-TO',
  'CONTENT-TYPE',
  'CONTENT-TRANSFER-ENCODING',
].join(' ');
const MESSAGE_ID_HEADER_FIELDS = 'MESSAGE-ID';

class ImapClient {
  constructor(config) {
    this.host = config.host;
    this.port = config.port;
    this.ssl = config.ssl;
    this.startTls = config.startTls;
    this.allowUnauthorizedCerts = config.allowUnauthorizedCerts;
    this.rawFetchByteLimit = config.rawFetchByteLimit;
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

  tlsOptions(options) {
    const tlsOptions = {
      ...options,
      rejectUnauthorized: !this.allowUnauthorizedCerts,
    };
    if (!net.isIP(this.host)) {
      tlsOptions.servername = this.host;
    }
    return tlsOptions;
  }

  async connect() {
    const socket = this.ssl
      ? tls.connect(this.tlsOptions({
          host: this.host,
          port: this.port,
        }))
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
      this.socket = tls.connect(this.tlsOptions({
        socket: this.socket,
      }));
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
    return await this.command(`SELECT ${quoteString(mailbox)}`);
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

  async uidNext(mailbox) {
    const response = await this.select(mailbox);
    const match = /\[UIDNEXT\s+(\d+)\]/i.exec(response);
    if (!match) throw new Error(`IMAP SELECT ${mailbox} did not return UIDNEXT`);
    return Number(match[1]);
  }

  async searchUidRange(mailbox, startUid, endUid) {
    await this.select(mailbox);
    const response = await this.command(`UID SEARCH UID ${startUid}:${endUid}`, 60000);
    return parseSearchResponse(response);
  }

  async searchMessageId(mailbox, messageId) {
    await this.select(mailbox);
    const response = await this.command(`UID SEARCH HEADER Message-ID ${quoteString(messageId)}`, 60000);
    return parseSearchResponse(response);
  }

  async fetchHeaders(uid, mailbox, fields = SOURCE_HEADER_FIELDS) {
    await this.select(mailbox);
    const response = await this.command(`UID FETCH ${uid} (BODY.PEEK[HEADER.FIELDS (${fields})])`, 60000);
    return firstLiteral(response);
  }

  async fetchHeadersForUids(uids, mailbox, fields = SOURCE_HEADER_FIELDS) {
    if (uids.length === 0) return [];
    await this.select(mailbox);
    const response = await this.command(`UID FETCH ${uids.join(',')} (BODY.PEEK[HEADER.FIELDS (${fields})])`, 120000);
    return fetchLiterals(response);
  }

  async fetchMessageIds(mailbox) {
    const uids = await this.searchAll(mailbox);
    const messageIds = new Set();
    for (const batch of chunked(uids, 100)) {
      const headersByUid = await this.fetchHeadersForUids(batch, mailbox, MESSAGE_ID_HEADER_FIELDS);
      for (const entry of headersByUid) {
        const headers = parseHeaders(entry.literal);
        const messageId = headers['message-id'] || '';
        if (messageId) messageIds.add(messageId);
      }
    }
    return messageIds;
  }

  async fetchRaw(uid, mailbox) {
    await this.select(mailbox);
    const response = await this.command(`UID FETCH ${uid} (BODY.PEEK[]<0.${this.rawFetchByteLimit}>)`, 60000);
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

function fetchLiterals(response) {
  const literals = [];
  const literalPattern = /\{(\d+)\}\r\n/g;
  let match;

  while ((match = literalPattern.exec(response))) {
    const literalStart = literalPattern.lastIndex;
    const length = Number(match[1]);
    const literal = response.slice(literalStart, literalStart + length);
    const lineStart = response.lastIndexOf('\r\n* ', match.index);
    const prefixStart = lineStart >= 0 ? lineStart + 2 : 0;
    const prefix = response.slice(prefixStart, match.index);
    const uid = /UID\s+(\d+)/i.exec(prefix)?.[1];
    if (uid) literals.push({ uid: String(uid), literal });
    literalPattern.lastIndex = literalStart + length;
  }

  return literals;
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

function recipientParts(header) {
  const decoded = decodeEncodedWords(header || '');
  const primary = decoded.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/)[0]?.trim() || decoded;
  const match = primary.match(/^(.*?)\s*<([^>]+)>$/);
  if (match) {
    const email = match[2].trim();
    return {
      to: decoded,
      recipient: email,
      recipient_name: match[1].replace(/^"|"$/g, '').trim(),
      recipient_email: email,
    };
  }
  const email = primary.includes('@') ? primary.trim() : '';
  return {
    to: decoded,
    recipient: email || decoded,
    recipient_name: '',
    recipient_email: email,
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
  const recipient = recipientParts(headers.to || headers['delivered-to'] || headers['x-original-to'] || '');
  const subject = decodeEncodedWords(headers.subject || '');
  const body = messageBody(raw, headers).replace(/\s+/g, ' ').trim().slice(0, 4000);

  return {
    uid: String(uid),
    message_id: headers['message-id'] || '',
    ...sender,
    ...recipient,
    subject,
    email_subject: subject,
    date: headers.date || '',
    body_preview: body,
    email_body: body,
    sourceFlow: 'bulk',
    runMode: 'apply_labels',
    credentialPairId: config.id,
    credentialPair: publicCredentialPair(config),
    sourceMailbox: config.sourceMailbox,
    telemetry: config.telemetry || {},
    batchLimit: config.batchLimit,
    maxBatches: config.maxBatches,
    rawFetchByteLimit: config.rawFetchByteLimit,
    fetchWatchdogMs: config.fetchWatchdogMs,
    uidSearchWindow: config.uidSearchWindow,
    imapPairsJson: config.imapPairsJson || '',
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

function numberValue(value, fallback, description) {
  const raw = value === undefined || value === null || value === '' ? fallback : value;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${description} must be a number`);
  }
  return parsed;
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

function listValue(value, fallback) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return fallback;
    if (trimmed.startsWith('[')) {
      const parsed = JSON.parse(trimmed);
      if (!Array.isArray(parsed)) throw new Error('Expected sourceMailboxes JSON to be an array');
      return parsed.map((item) => String(item).trim()).filter(Boolean);
    }
    return trimmed.split(',').map((item) => item.trim()).filter(Boolean);
  }
  return fallback;
}

function parseCredentialPairs(value) {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) throw new Error('imapPairsJson must contain a JSON array');
    return parsed;
  }
  return [];
}

function normalizeCredentialPair(rawPair, index, defaults) {
  const pair = rawPair && typeof rawPair === 'object' ? rawPair : {};
  const id = String(configValue(pair, 'id', `imap-${index + 1}`));
  const hostVar = String(configValue(pair, 'hostVar', defaults.hostVar));
  const portVar = String(configValue(pair, 'portVar', defaults.portVar));
  const host = String(envValue(hostVar) || configValue(pair, 'host', defaults.host));
  const port = numberValue(
    envValue(portVar) || configValue(pair, 'port', defaults.port),
    defaults.port,
    `Credential pair ${id} port`,
  );
  const sourceMailboxes = listValue(
    pair.sourceMailboxes ?? pair.sourceMailbox,
    [defaults.sourceMailbox],
  );

  if (sourceMailboxes.length === 0) {
    throw new Error(`Credential pair ${id} must include at least one source mailbox`);
  }

  return {
    id,
    host,
    port,
    hostVar,
    portVar,
    ssl: boolValue(pair.ssl ?? pair.imapSsl, defaults.ssl),
    startTls: boolValue(pair.startTls ?? pair.imapStartTls, defaults.startTls),
    allowUnauthorizedCerts: boolValue(
      pair.allowUnauthorizedCerts,
      defaults.allowUnauthorizedCerts,
    ),
    userVar: String(configValue(pair, 'userVar', defaults.userVar)),
    passwordVar: String(configValue(pair, 'passwordVar', defaults.passwordVar)),
    sourceMailboxes,
    labelPrefix: String(configValue(pair, 'labelPrefix', defaults.labelPrefix)),
    stateLabel: String(configValue(pair, 'stateLabel', defaults.stateLabel)),
    rawFetchByteLimit: numberValue(
      configValue(pair, 'rawFetchByteLimit', defaults.rawFetchByteLimit),
      defaults.rawFetchByteLimit,
      `Credential pair ${id} raw fetch byte limit`,
    ),
    dryRun: defaults.dryRun,
  };
}

function credentialPairsFromConfig(inputConfig, defaults) {
  const configuredPairs = parseCredentialPairs(
    inputConfig.imapPairs ?? inputConfig.imapPairsJson ?? inputConfig.credentialPairs ?? inputConfig.credentialPairsJson,
  );

  const pairs = configuredPairs.length > 0
    ? configuredPairs
    : [{
        id: 'imap-1',
        host: defaults.host,
        port: defaults.port,
        hostVar: defaults.hostVar,
        portVar: defaults.portVar,
        ssl: defaults.ssl,
        startTls: defaults.startTls,
        allowUnauthorizedCerts: defaults.allowUnauthorizedCerts,
        userVar: defaults.userVar,
        passwordVar: defaults.passwordVar,
        sourceMailboxes: [defaults.sourceMailbox],
        labelPrefix: defaults.labelPrefix,
        stateLabel: defaults.stateLabel,
        rawFetchByteLimit: defaults.rawFetchByteLimit,
      }];

  return pairs.map((pair, index) => normalizeCredentialPair(pair, index, defaults));
}

function chunked(values, size) {
  const chunks = [];
  for (let index = 0; index < values.length; index += size) {
    chunks.push(values.slice(index, index + size));
  }
  return chunks;
}

function assertFetchWithinWatchdog(startedAt, fetchWatchdogMs, progress) {
  if (fetchWatchdogMs <= 0) return;
  const elapsedMs = Date.now() - startedAt;
  if (elapsedMs > fetchWatchdogMs) {
    throw new Error(`Fetch watchdog exceeded after ${elapsedMs}ms: ${JSON.stringify(progress)}`);
  }
}

function withProgressError(error, progress) {
  if (error && typeof error.message === 'string' && !error.message.includes('fetch progress')) {
    error.message = `${error.message}; fetch progress ${JSON.stringify(progress)}`;
  }
  return error;
}

function publicCredentialPair(pair) {
  return {
    id: pair.id,
    host: pair.host,
    port: pair.port,
    hostVar: pair.hostVar,
    portVar: pair.portVar,
    ssl: pair.ssl,
    startTls: pair.startTls,
    allowUnauthorizedCerts: pair.allowUnauthorizedCerts,
    userVar: pair.userVar,
    passwordVar: pair.passwordVar,
    sourceMailboxes: pair.sourceMailboxes,
    labelPrefix: pair.labelPrefix,
    stateLabel: pair.stateLabel,
    rawFetchByteLimit: pair.rawFetchByteLimit,
  };
}

let inputConfig = {};
try {
  inputConfig = $('Configure Proton IMAP batch').first().json;
} catch {
  inputConfig = $input.first()?.json ?? {};
}

const runIndex = typeof $runIndex === 'number' ? $runIndex : 0;
const defaults = {
  host: String(configValue(inputConfig, 'imapHost', '192.168.3.200')),
  port: numberValue(configValue(inputConfig, 'imapPort', 1143), 1143, 'Default IMAP port'),
  hostVar: String(configValue(inputConfig, 'imapHostVar', 'IMAP_HOST')),
  portVar: String(configValue(inputConfig, 'imapPortVar', 'IMAP_PORT')),
  ssl: boolValue(inputConfig.imapSsl, false),
  startTls: boolValue(inputConfig.imapStartTls, true),
  allowUnauthorizedCerts: boolValue(inputConfig.allowUnauthorizedCerts, true),
  sourceMailbox: String(configValue(inputConfig, 'sourceMailbox', 'INBOX')),
  labelPrefix: String(configValue(inputConfig, 'labelPrefix', 'Labels')),
  stateLabel: String(configValue(inputConfig, 'stateLabel', 'Classified')),
  userVar: String(configValue(inputConfig, 'userVar', 'IMAP_USER')),
  passwordVar: String(configValue(inputConfig, 'passwordVar', 'IMAP_PASSWORD')),
  batchLimit: Number(configValue(inputConfig, 'batchLimit', 50)),
  maxBatches: numberValue(configValue(inputConfig, 'maxBatches', 0), 0, 'Max batches'),
  rawFetchByteLimit: numberValue(configValue(inputConfig, 'rawFetchByteLimit', 65536), 65536, 'Raw fetch byte limit'),
  fetchWatchdogMs: numberValue(configValue(inputConfig, 'fetchWatchdogMs', 120000), 120000, 'Fetch watchdog milliseconds'),
  uidSearchWindow: numberValue(configValue(inputConfig, 'uidSearchWindow', 500), 500, 'UID search window'),
  dryRun: boolValue(inputConfig.dryRun, false),
  telemetry: inputConfig.telemetry || {},
};

if (defaults.dryRun && runIndex > 0) {
  return [{
    json: {
      emails: [],
      total_emails: 0,
      stopped_reason: 'dry_run_single_batch',
      telemetry: defaults.telemetry,
    },
  }];
}

if (defaults.maxBatches > 0 && runIndex >= defaults.maxBatches) {
  return [{
    json: {
      emails: [],
      warnings: [],
      total_emails: 0,
      stopped_reason: 'max_batches_reached',
      max_batches: defaults.maxBatches,
      telemetry: defaults.telemetry,
    },
  }];
}

const credentialPairs = credentialPairsFromConfig(inputConfig, defaults);
const emails = [];
const warnings = [];

for (const pair of credentialPairs) {
  if (emails.length >= defaults.batchLimit) break;
  const fetchStartedAt = Date.now();
  const progress = {
    stage: 'credential_pair_start',
    pair: pair.id,
    stateMailbox: `${pair.labelPrefix}/${pair.stateLabel}`,
    sourceMailbox: '',
    classifiedUidCount: 0,
    sourceUidCount: 0,
    rangeStart: 0,
    rangeEnd: 0,
    candidateChecks: 0,
    bodyFetches: 0,
    emails: emails.length,
  };
  function markProgress(stage, updates = {}) {
    progress.stage = stage;
    Object.assign(progress, updates, { emails: emails.length });
    assertFetchWithinWatchdog(fetchStartedAt, defaults.fetchWatchdogMs, progress);
  }

  const username = envValue(pair.userVar);
  const password = envValue(pair.passwordVar);
  if (!username || !password) {
    throw new Error(`Credential pair ${pair.id} requires n8n variables ${pair.userVar} and ${pair.passwordVar}.`);
  }

  const stateMailbox = `${pair.labelPrefix}/${pair.stateLabel}`;
  const client = new ImapClient(pair);

  try {
    markProgress('connect');
    await client.connect();
    markProgress('login');
    await client.login(username, password);

    markProgress('check_state_mailbox');
    const stateMailboxExists = await client.mailboxExists(stateMailbox);
    if (!stateMailboxExists && !pair.dryRun) {
      throw new Error(`Required Proton label mailbox does not exist for credential pair ${pair.id}: ${stateMailbox}`);
    }
    if (!stateMailboxExists) {
      warnings.push(`State mailbox not found during dry-run for credential pair ${pair.id}: ${stateMailbox}`);
    }

    for (const sourceMailbox of pair.sourceMailboxes) {
      if (emails.length >= defaults.batchLimit) break;

      const mailboxConfig = {
        ...pair,
        sourceMailbox,
        dryRun: defaults.dryRun,
        telemetry: defaults.telemetry,
        batchLimit: defaults.batchLimit,
        maxBatches: defaults.maxBatches,
        rawFetchByteLimit: defaults.rawFetchByteLimit,
        fetchWatchdogMs: defaults.fetchWatchdogMs,
        uidSearchWindow: defaults.uidSearchWindow,
        imapPairsJson: inputConfig.imapPairsJson || '',
      };
      markProgress('read_source_uidnext', { sourceMailbox });
      const uidNext = await client.uidNext(sourceMailbox);
      markProgress('source_uidnext_loaded', { sourceMailbox, rangeEnd: uidNext - 1 });

      for (
        let rangeEnd = uidNext - 1;
        rangeEnd >= 1 && emails.length < defaults.batchLimit;
        rangeEnd -= defaults.uidSearchWindow
      ) {
        const rangeStart = Math.max(1, rangeEnd - defaults.uidSearchWindow + 1);
        markProgress('search_source_uid_range', { sourceMailbox, rangeStart, rangeEnd });
        const rangeUids = (await client.searchUidRange(sourceMailbox, rangeStart, rangeEnd)).reverse();
        markProgress('source_uid_range_loaded', {
          sourceMailbox,
          rangeStart,
          rangeEnd,
          sourceUidCount: progress.sourceUidCount + rangeUids.length,
        });
        if (rangeUids.length === 0) continue;

        for (const uidBatch of chunked(rangeUids, 100)) {
          markProgress('fetch_candidate_headers', {
            sourceMailbox,
            rangeStart,
            rangeEnd,
            candidateChecks: progress.candidateChecks + uidBatch.length,
          });
          const batchHeaders = await client.fetchHeadersForUids(uidBatch, sourceMailbox);
          const headersByUid = new Map(batchHeaders.map((entry) => [String(entry.uid), entry.literal]));

          for (const uid of uidBatch) {
            markProgress('check_candidate_state', {
              sourceMailbox,
              rangeStart,
              rangeEnd,
              candidateChecks: progress.candidateChecks + 1,
            });
            const rawHeaders = headersByUid.get(String(uid)) || await client.fetchHeaders(uid, sourceMailbox);
            const headers = parseHeaders(rawHeaders);
            const messageId = headers['message-id'] || '';
            if (stateMailboxExists && messageId) {
              const matches = await client.searchMessageId(stateMailbox, messageId);
              if (matches.length > 0) continue;
            }

            markProgress('fetch_candidate_body', {
              sourceMailbox,
              rangeStart,
              rangeEnd,
              bodyFetches: progress.bodyFetches + 1,
            });
            const raw = await client.fetchRaw(uid, sourceMailbox);
            const summary = summaryFromRaw(uid, raw, mailboxConfig);
            emails.push(summary);
            markProgress('candidate_ready', { sourceMailbox, rangeStart, rangeEnd });
            if (emails.length >= defaults.batchLimit) break;
          }

          if (emails.length >= defaults.batchLimit) break;
        }
      }
    }
  } catch (error) {
    throw withProgressError(error, progress);
  } finally {
    await client.logout().catch(() => {});
  }
}

return [{
  json: {
    emails,
    warnings,
    total_emails: emails.length,
    stopped_reason: emails.length ? 'batch_ready' : 'inbox_fully_classified',
    telemetry: defaults.telemetry,
  },
}];
