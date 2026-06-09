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
    await this.command(`SELECT ${quoteString(mailbox)}`);
  }

  async mailboxExists(mailbox) {
    const response = await this.command(`LIST "" ${quoteString(mailbox)}`);
    return /\* LIST /i.test(response);
  }

  async searchMessageId(mailbox, messageId) {
    await this.select(mailbox);
    const response = await this.command(`UID SEARCH HEADER Message-ID ${quoteString(messageId)}`);
    return parseSearchResponse(response);
  }

  async copyUid(uid, destination) {
    await this.command(`UID COPY ${uid} ${quoteString(destination)}`, 120000);
  }

  async copyUids(uids, destination) {
    if (uids.length === 0) return;
    await this.command(`UID COPY ${uids.join(',')} ${quoteString(destination)}`, 120000);
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

function configValue(source, key, fallback) {
  const value = source[key];
  return value === undefined || value === null || value === '' ? fallback : value;
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

function normalizeCredentialPair(item) {
  const pair = item.credentialPair && typeof item.credentialPair === 'object'
    ? item.credentialPair
    : {};
  const id = String(configValue(pair, 'id', item.credentialPairId || 'imap-1'));
  const hostVar = String(configValue(pair, 'hostVar', configValue(item, 'hostVar', 'IMAP_HOST')));
  const portVar = String(configValue(pair, 'portVar', configValue(item, 'portVar', 'IMAP_PORT')));

  return {
    id,
    host: String(envValue(hostVar) || configValue(pair, 'host', configValue(item, 'imapHost', '192.168.3.200'))),
    port: numberValue(
      envValue(portVar) || configValue(pair, 'port', configValue(item, 'imapPort', 1143)),
      1143,
      `Credential pair ${id} port`,
    ),
    hostVar,
    portVar,
    ssl: boolValue(pair.ssl ?? pair.imapSsl, boolValue(item.imapSsl, false)),
    startTls: boolValue(pair.startTls ?? pair.imapStartTls, boolValue(item.imapStartTls, true)),
    allowUnauthorizedCerts: boolValue(
      pair.allowUnauthorizedCerts,
      boolValue(item.allowUnauthorizedCerts, true),
    ),
    userVar: String(configValue(pair, 'userVar', configValue(item, 'userVar', 'IMAP_USER'))),
    passwordVar: String(configValue(pair, 'passwordVar', configValue(item, 'passwordVar', 'IMAP_PASSWORD'))),
    labelPrefix: String(configValue(pair, 'labelPrefix', configValue(item, 'labelPrefix', 'Labels'))),
    stateLabel: String(configValue(pair, 'stateLabel', configValue(item, 'stateLabel', 'Classified'))),
  };
}

function loopbackPayload(item, fields) {
  return {
    ...item,
    ...fields,
    resetLoop: false,
  };
}

const PRIVATE_BATCH_RESULT_FIELDS = new Set([
  'email_body',
  'body_preview',
  'raw',
  'raw_content',
  'userPrompt',
  'systemPrompt',
  'output',
  'classifier_output',
  'classification_raw_response',
]);

function compactBatchResult(item) {
  const compact = {};
  for (const [key, value] of Object.entries(item || {})) {
    if (!PRIVATE_BATCH_RESULT_FIELDS.has(key)) compact[key] = value;
  }
  return compact;
}

function targetMailboxesFor(item, pair) {
  const targetMailboxes = Array.isArray(item.targetMailboxes)
    ? item.targetMailboxes
    : [
        ...(Array.isArray(item.labelMailboxes) ? item.labelMailboxes : []),
        `${pair.labelPrefix}/${pair.stateLabel}`,
      ];

  return [...new Set(targetMailboxes.filter(Boolean))];
}

function isBatchPayload(item) {
  return Array.isArray(item.label_batch_items);
}

function outputItems(root, results) {
  if (isBatchPayload(root)) {
    return [{
      json: {
        ...root,
        runMode: 'apply_label_batch',
        label_batch_results: results.map(compactBatchResult),
        total_emails: results.length,
        source_action: 'kept_in_source',
      },
    }];
  }

  return results.map((result) => ({ json: result }));
}

function groupKey(pair, sourceMailbox) {
  return JSON.stringify({
    id: pair.id,
    host: envValue(pair.hostVar) || pair.host,
    port: envValue(pair.portVar) || pair.port,
    ssl: pair.ssl,
    startTls: pair.startTls,
    allowUnauthorizedCerts: pair.allowUnauthorizedCerts,
    userVar: pair.userVar,
    passwordVar: pair.passwordVar,
    sourceMailbox,
  });
}

function clientConfig(pair) {
  return {
    host: envValue(pair.hostVar) || pair.host,
    port: numberValue(envValue(pair.portVar) || pair.port, pair.port, `Credential pair ${pair.id} port`),
    ssl: pair.ssl,
    startTls: pair.startTls,
    allowUnauthorizedCerts: pair.allowUnauthorizedCerts,
  };
}

const root = $input.first()?.json ?? {};
const inputItems = isBatchPayload(root)
  ? root.label_batch_items
  : $input.all().map((item) => item.json ?? {});
const emails = inputItems.map((item) => ({
  ...item,
  dryRun: item.dryRun ?? root.dryRun,
  telemetry: item.telemetry || root.telemetry || {},
}));

const dryRun = boolValue(root.dryRun, false) || emails.every((item) => boolValue(item.dryRun, false));
const results = emails.map((item) => loopbackPayload(item, {
  destination_actions: {},
  source_action: dryRun ? 'would_keep_in_source' : 'kept_in_source',
}));

if (dryRun) {
  for (let index = 0; index < emails.length; index += 1) {
    const item = emails[index];
    const pair = normalizeCredentialPair(item);
    const uniqueTargets = targetMailboxesFor(item, pair);
    results[index] = loopbackPayload(item, {
      destination_actions: Object.fromEntries(uniqueTargets.map((target) => [target, 'would_apply_label'])),
      source_action: 'would_keep_in_source',
    });
  }

  return outputItems(root, results);
}

const groups = new Map();
for (let index = 0; index < emails.length; index += 1) {
  const item = emails[index];
  const pair = normalizeCredentialPair(item);
  const sourceMailbox = String(configValue(item, 'sourceMailbox', 'INBOX'));
  const key = groupKey(pair, sourceMailbox);
  if (!groups.has(key)) {
    groups.set(key, { pair, sourceMailbox, entries: [] });
  }
  groups.get(key).entries.push({ index, item, pair });
}

for (const group of groups.values()) {
  const { pair, sourceMailbox, entries } = group;
  const username = envValue(pair.userVar);
  const password = envValue(pair.passwordVar);
  if (!username || !password) {
    throw new Error(`Credential pair ${pair.id} requires n8n variables ${pair.userVar} and ${pair.passwordVar}.`);
  }

  const client = new ImapClient(clientConfig(pair));
  const mailboxExists = new Map();
  const copiesByMailbox = new Map();

  try {
    await client.connect();
    await client.login(username, password);

    async function targetExists(mailbox) {
      if (!mailboxExists.has(mailbox)) {
        mailboxExists.set(mailbox, await client.mailboxExists(mailbox));
      }
      return mailboxExists.get(mailbox);
    }

    for (const { index, item } of entries) {
      const uniqueTargets = targetMailboxesFor(item, pair);
      const missingMailboxes = [];
      for (const mailbox of uniqueTargets) {
        if (!(await targetExists(mailbox))) missingMailboxes.push(mailbox);
      }

      if (missingMailboxes.length > 0) {
        results[index] = loopbackPayload(item, {
          label_application_skipped: true,
          missingMailboxes,
          destination_actions: Object.fromEntries(
            uniqueTargets.map((target) => [target, 'skipped_missing_mailbox']),
          ),
          source_action: 'kept_in_source',
        });
        continue;
      }

      let uid = String(item.uid || '');
      if (!uid && item.message_id) {
        const matches = await client.searchMessageId(sourceMailbox, item.message_id);
        uid = matches.at(-1) || '';
      }
      if (!uid) {
        throw new Error('Email item did not include an IMAP UID or searchable Message-ID.');
      }

      results[index] = loopbackPayload(item, {
        destination_actions: Object.fromEntries(uniqueTargets.map((target) => [target, 'label_pending'])),
        source_action: 'kept_in_source',
      });

      for (const mailbox of uniqueTargets) {
        if (!copiesByMailbox.has(mailbox)) copiesByMailbox.set(mailbox, []);
        copiesByMailbox.get(mailbox).push({ index, uid });
      }
    }

    await client.select(sourceMailbox);
    for (const [mailbox, copies] of copiesByMailbox.entries()) {
      const uids = copies.map((copy) => copy.uid);
      await client.copyUids(uids, mailbox);
      for (const { index } of copies) {
        results[index].destination_actions[mailbox] = 'label_applied';
      }
    }
  } finally {
    await client.logout().catch(() => {});
  }
}

return outputItems(root, results);
