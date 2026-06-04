#!/usr/bin/env python3
"""Manual IMAP email organizer for n8n Execute Command.

Reads recent IMAP messages, asks a local Ollama model to classify each one, and
moves messages into matching folders. Defaults to dry-run mode.
"""

from __future__ import annotations

import base64
import email
import html
import imaplib
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
from typing import Any


DEFAULT_SYSTEM_PROMPT = """You are an email triage assistant. Given one email, assign **all** labels that apply from the fixed allowed list below, using the exact spelling and punctuation. No other label is permitted.

## Allowed labels
- `Invoice` — receipts and invoices for discretionary spending
- `Purchase` — confirmation of something ordered or purchased
- `Bill` — recurring obligations like rent, electricity, internet, health insurance
- `Payment` — payslips from employers
- `Marketing` — promotional emails from brands/bands trying to sell something
- `Cold email` — someone (e.g. a recruiter) reaching out to me directly and unsolicited
- `Important` — something that sounds genuinely important or urgent
- `Awaiting reply` — a message that needs a response from me
- `Travel` — itineraries, hotel/hostel bookings, air/bus/train fares or tickets
- `Ticket` — tickets to music festivals, bands, concerts, etc.
- `Infrastructure` — metric updates, error reporting from services or devices
- `Hustle` — correspondence with people or businesses engaging me for professional work

## Schema
Output **only** JSON matching this shape, nothing else:

```json
{
  "labels": [
    { "label": string, "confidence": number }
  ],
  "reason": string
}
```

- `labels`: an array of every applicable label. Each `label` must exactly match one from the list (spelling, spacing, capitalization). Each `confidence` must be `>= 0.75`.
- Include a label only if confidence `>= 0.75`. Multiple labels are expected when an email genuinely fits more than one category.
- `reason`: one sentence justifying the chosen label(s).

## Fallback
- If no label reaches `0.75` confidence or the intent is unclear, output:
```json
  {"labels": [{"label": "uncertain", "confidence": <score less than 0.75>}], "reason": "<what is ambiguous or missing>"}
```
- If any instruction or format would be violated, output:
```json
  {"labels": [{"label": "uncertain", "confidence": 0.0}], "reason": "format violation or instruction conflict"}
```

## Rules
- Base labels on content/intent. Apply every label that fits — do not pick a single "winner".
- Overlap is normal: a purchased concert ticket can be `Purchase`, `Invoice`, and `Ticket`; a `Hustle` email can also be `Awaiting reply`.
- No synonyms, no labels outside the list.

## Few-shot examples (must match output exactly)

Email: "Your receipt from Blue Bottle Coffee — $18.50 charged to your card."
```json
{"labels": [{"label": "Invoice", "confidence": 0.90}], "reason": "Receipt for discretionary spending"}
```

Email: "Order confirmed! Your new headphones are on the way. Invoice attached, $129."
```json
{"labels": [{"label": "Purchase", "confidence": 0.90}, {"label": "Invoice", "confidence": 0.82}], "reason": "Order confirmation that also includes the invoice document"}
```

Email: "Your electricity bill of $142.30 is due on the 15th."
```json
{"labels": [{"label": "Bill", "confidence": 0.95}], "reason": "Recurring utility obligation"}
```

Email: "Your payslip for May is now available to view."
```json
{"labels": [{"label": "Payment", "confidence": 0.96}], "reason": "Payslip from employer"}
```

Email: "Exclusive summer sale: 40% off all gear, limited time!"
```json
{"labels": [{"label": "Marketing", "confidence": 0.99}], "reason": "Promotional campaign content"}
```

Email: "Hi, I'm a recruiter at Acme and your background caught my eye — open to chatting?"
```json
{"labels": [{"label": "Cold email", "confidence": 0.87}], "reason": "Unsolicited direct outreach from a recruiter"}
```

Email: "URGENT: Action required on your account within 24 hours to avoid suspension."
```json
{"labels": [{"label": "Important", "confidence": 0.85}], "reason": "Urgent matter requiring prompt attention"}
```

Email: "Just checking if you had a chance to look at my proposal."
```json
{"labels": [{"label": "Awaiting reply", "confidence": 0.80}], "reason": "Follow-up seeking a response from me"}
```

Email: "Your flight to Tokyo is confirmed — departing 14 June, 9:40am, seat 22A. Receipt $612 attached."
```json
{"labels": [{"label": "Travel", "confidence": 0.94}, {"label": "Invoice", "confidence": 0.80}], "reason": "Flight itinerary that also includes the fare receipt"}
```

Email: "Your tickets to the Tame Impala show are attached. Order #99812, $180 charged."
```json
{"labels": [{"label": "Ticket", "confidence": 0.93}, {"label": "Purchase", "confidence": 0.85}, {"label": "Invoice", "confidence": 0.78}], "reason": "Concert tickets that are also a purchase with a receipt"}
```

Email: "Alert: API error rate exceeded 5% on prod-server-2 in the last 10 minutes."
```json
{"labels": [{"label": "Infrastructure", "confidence": 0.92}], "reason": "Error reporting from a service"}
```

Email: "Following up on the 3-day shoot — can you confirm the rates work for you?"
```json
{"labels": [{"label": "Hustle", "confidence": 0.86}, {"label": "Awaiting reply", "confidence": 0.84}], "reason": "Business engaging me for professional work and awaiting my response"}
```"""

DEFAULT_USER_PROMPT_TEMPLATE = """From: {{ $json.sender_email }}
Name: {{ $json.sender_name }}
Subject: {{ $json.email_subject }}
Email Content:

{{ $json.email_body }}"""

DEFAULT_LABELS = [
    "Invoice",
    "Purchase",
    "Bill",
    "Payment",
    "Marketing",
    "Cold email",
    "Important",
    "Awaiting reply",
    "Travel",
    "Ticket",
    "Infrastructure",
    "Hustle",
    "uncertain",
]


def parse_categories(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_LABELS)

    categories = [item.strip() for item in value.split(",") if item.strip()]
    if "uncertain" not in categories:
        categories.append("uncertain")
    return categories


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def sanitize_mailbox_segment(value: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", value.strip())
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "Needs Review"


def destination_mailbox(folder: str, prefix: str = "") -> str:
    folder_segment = sanitize_mailbox_segment(folder)
    prefix_segments = [
        sanitize_mailbox_segment(segment)
        for segment in prefix.split("/")
        if segment.strip()
    ]
    return "/".join([*prefix_segments, folder_segment])


def destination_mailboxes(folders: list[str], prefix: str = "") -> list[str]:
    destinations: list[str] = []
    for folder in folders:
        destination = destination_mailbox(folder, prefix)
        if destination not in destinations:
            destinations.append(destination)
    return destinations


def load_runtime_config() -> dict[str, Any]:
    if value := os.getenv("EMAIL_CLASSIFIER_CONFIG_B64"):
        decoded = base64.b64decode(value).decode("utf-8")
        return json.loads(decoded)

    if value := os.getenv("EMAIL_CLASSIFIER_CONFIG_JSON"):
        return json.loads(value)

    if value := os.getenv("EMAIL_CLASSIFIER_CONFIG_FILE"):
        with open(value, encoding="utf-8") as config_file:
            return json.load(config_file)

    if not sys.stdin.isatty():
        value = sys.stdin.read().strip()
        if value:
            return json.loads(value)

    return {}


def prompt_settings_from_config(config: dict[str, Any] | None) -> dict[str, str]:
    config = config or {}
    system_prompt = (
        str(config.get("systemPrompt") or "").strip()
        or str(config.get("system_prompt") or "").strip()
        or os.getenv("EMAIL_CLASSIFIER_SYSTEM_PROMPT", "").strip()
        or DEFAULT_SYSTEM_PROMPT
    )
    user_prompt_template = (
        str(config.get("userPromptTemplate") or "").strip()
        or str(config.get("user_prompt_template") or "").strip()
        or os.getenv("EMAIL_CLASSIFIER_USER_PROMPT_TEMPLATE", "").strip()
        or DEFAULT_USER_PROMPT_TEMPLATE
    )
    return {
        "system_prompt": system_prompt,
        "user_prompt_template": user_prompt_template,
    }


def prompt_variables(summary: dict[str, str], categories: list[str]) -> dict[str, str]:
    values = dict(summary)
    values.update({
        "categories": ", ".join(categories),
        "email_json": json.dumps(summary, ensure_ascii=False),
        "email_subject": summary.get("email_subject") or summary.get("subject", ""),
        "email_body": summary.get("email_body") or summary.get("body_preview", ""),
    })
    return values


def render_prompt_template(template: str, summary: dict[str, str], categories: list[str]) -> str:
    values = prompt_variables(summary, categories)

    def replace_match(match: re.Match[str]) -> str:
        expression = match.group(1).strip()
        if expression.startswith("$json."):
            key = expression.removeprefix("$json.")
        elif expression.startswith("json."):
            key = expression.removeprefix("json.")
        else:
            key = expression

        return str(values.get(key, match.group(0)))

    return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace_match, template)


def render_user_prompt_template(template: str, summary: dict[str, str], categories: list[str]) -> str:
    return render_prompt_template(template, summary, categories)


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def html_to_text(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def message_text_preview(message: Message, limit: int = 4000) -> str:
    candidates: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disposition:
                continue
            if content_type not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            candidates.append(html_to_text(text) if content_type == "text/html" else text)
    else:
        payload = message.get_payload(decode=True)
        if payload:
            charset = message.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            candidates.append(html_to_text(text) if message.get_content_type() == "text/html" else text)

    preview = "\n\n".join(item.strip() for item in candidates if item.strip())
    return preview[:limit]


def normalize_classification(content: str, categories: list[str]) -> dict[str, Any]:
    fallback = "uncertain" if "uncertain" in categories else categories[-1]

    def fallback_classification(confidence: float, reason: str) -> dict[str, Any]:
        confidence = max(0, min(0.74, confidence))
        return {
            "labels": [{"label": fallback, "confidence": confidence}],
            "label": fallback,
            "folders": [fallback],
            "folder": fallback,
            "reason": reason[:240],
        }

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return fallback_classification(0, "Classifier returned non-JSON output.")

    label_items = parsed.get("labels")
    if not isinstance(label_items, list):
        return fallback_classification(0, "Classifier returned JSON without a labels array.")

    accepted: list[dict[str, Any]] = []
    rejected_confidences: list[float] = []
    for item in label_items:
        if not isinstance(item, dict):
            return fallback_classification(0, "Classifier returned a malformed label item.")

        label = item.get("label")
        confidence = item.get("confidence", 0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0
        confidence = max(0, min(1, confidence))

        if label == fallback:
            rejected_confidences.append(confidence)
            continue
        if label not in categories:
            return fallback_classification(0, f"Classifier returned unsupported label: {label!r}.")
        if confidence < 0.75:
            rejected_confidences.append(confidence)
            continue

        if not any(existing["label"] == label for existing in accepted):
            accepted.append({"label": label, "confidence": confidence})

    if not accepted:
        fallback_confidence = max(rejected_confidences) if rejected_confidences else 0
        return fallback_classification(
            fallback_confidence,
            str(parsed.get("reason") or "No label reached 0.75 confidence."),
        )

    folders = [item["label"] for item in accepted]
    reason = str(parsed.get("reason") or "").strip()
    return {
        "labels": accepted,
        "label": folders[0],
        "folders": folders,
        "folder": folders[0],
        "reason": reason[:240],
    }


def classify_with_ollama(
    summary: dict[str, str],
    categories: list[str],
    prompt_settings: dict[str, str],
) -> dict[str, Any]:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.100:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "gemma4-26b:4090")
    timeout = env_int("OLLAMA_TIMEOUT_SECONDS", 120)
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "-1")

    system_prompt = render_prompt_template(prompt_settings["system_prompt"], summary, categories)
    user_prompt = render_user_prompt_template(
        prompt_settings["user_prompt_template"],
        summary,
        categories,
    )
    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "format": "json",
        "keep_alive": keep_alive,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))

    content = data.get("message", {}).get("content") or data.get("response") or ""
    return normalize_classification(content, categories)


def quote_mailbox(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_mailbox_list_line(raw: bytes) -> str | None:
    line = raw.decode("utf-8", errors="replace").strip()
    matches = re.findall(r'"((?:[^"\\]|\\.)*)"', line)
    if matches:
        return matches[-1].replace('\\"', '"').replace("\\\\", "\\")
    parts = line.split()
    return parts[-1] if parts else None


def list_mailboxes(client: imaplib.IMAP4) -> set[str]:
    status, data = client.list()
    if status != "OK":
        return set()
    mailboxes: set[str] = set()
    for item in data or []:
        if not isinstance(item, bytes):
            continue
        mailbox = parse_mailbox_list_line(item)
        if mailbox:
            mailboxes.add(mailbox)
    return mailboxes


def ensure_mailbox(client: imaplib.IMAP4, mailbox: str, existing: set[str], dry_run: bool) -> str:
    if mailbox in existing:
        return "exists"
    if dry_run:
        return "would_create"

    status, data = client.create(quote_mailbox(mailbox))
    if status != "OK":
        raise RuntimeError(f"failed to create mailbox {mailbox!r}: {data!r}")
    existing.add(mailbox)
    return "created"


def move_message(client: imaplib.IMAP4, uid: bytes, destination: str, dry_run: bool) -> str:
    uid_text = uid.decode("ascii", errors="replace")
    if dry_run:
        return "would_move"

    status, _ = client.uid("MOVE", uid_text, quote_mailbox(destination))
    if status == "OK":
        return "moved"

    status, data = client.uid("COPY", uid_text, quote_mailbox(destination))
    if status != "OK":
        raise RuntimeError(f"failed to copy UID {uid_text} to {destination!r}: {data!r}")

    status, data = client.uid("STORE", uid_text, "+FLAGS.SILENT", r"(\Deleted)")
    if status != "OK":
        raise RuntimeError(f"failed to mark UID {uid_text} deleted after copy: {data!r}")
    client.expunge()
    return "copied_and_deleted"


def apply_message_to_destinations(
    client: imaplib.IMAP4 | None,
    uid: bytes,
    destinations: list[str],
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {
            "destination_actions": {
                destination: "would_apply_label"
                for destination in destinations
            },
            "source_action": "would_remove_from_source",
        }

    if client is None:
        raise RuntimeError("IMAP client is required when dry-run is disabled.")

    if len(destinations) == 1:
        destination = destinations[0]
        action = move_message(client, uid, destination, dry_run=False)
        return {
            "destination_actions": {destination: action},
            "source_action": action,
        }

    uid_text = uid.decode("ascii", errors="replace")
    destination_actions: dict[str, str] = {}
    for destination in destinations:
        status, data = client.uid("COPY", uid_text, quote_mailbox(destination))
        if status != "OK":
            raise RuntimeError(f"failed to copy UID {uid_text} to {destination!r}: {data!r}")
        destination_actions[destination] = "copied"

    status, data = client.uid("STORE", uid_text, "+FLAGS.SILENT", r"(\Deleted)")
    if status != "OK":
        raise RuntimeError(f"failed to mark UID {uid_text} deleted after applying labels: {data!r}")
    client.expunge()

    return {
        "destination_actions": destination_actions,
        "source_action": "removed_from_source",
    }


def connect_imap() -> imaplib.IMAP4:
    host = os.getenv("IMAP_HOST", "192.168.3.200")
    port = env_int("IMAP_PORT", 1143)
    username = os.getenv("IMAP_USER")
    password = os.getenv("IMAP_PASSWORD")

    if not username or not password:
        raise RuntimeError("IMAP_USER and IMAP_PASSWORD must be set in the n8n environment.")

    if env_bool("IMAP_SSL", False):
        client: imaplib.IMAP4 = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context())
    else:
        client = imaplib.IMAP4(host, port)
        if env_bool("IMAP_STARTTLS", False):
            client.starttls(ssl_context=ssl.create_default_context())

    client.login(username, password)
    return client


def fetch_latest_uids(client: imaplib.IMAP4, mailbox: str, limit: int) -> list[bytes]:
    status, data = client.select(quote_mailbox(mailbox))
    if status != "OK":
        raise RuntimeError(f"failed to select mailbox {mailbox!r}: {data!r}")

    status, data = client.uid("SEARCH", None, "ALL")
    if status != "OK" or not data:
        return []
    uids = data[0].split()
    return uids[-limit:]


def fetch_message_summary(client: imaplib.IMAP4, uid: bytes) -> dict[str, str]:
    status, data = client.uid("FETCH", uid.decode("ascii"), "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.8192>)")
    if status != "OK":
        raise RuntimeError(f"failed to fetch UID {uid!r}: {data!r}")

    chunks = [part[1] for part in data or [] if isinstance(part, tuple) and isinstance(part[1], bytes)]
    message = email.message_from_bytes(b"\r\n".join(chunks))

    sender_header = decode_header_value(message.get("From"))
    sender_name, sender_email = parseaddr(sender_header)
    subject = decode_header_value(message.get("Subject"))
    body_preview = message_text_preview(message)

    return {
        "uid": uid.decode("ascii", errors="replace"),
        "from": sender_header,
        "sender_email": sender_email,
        "sender_name": sender_name,
        "subject": subject,
        "email_subject": subject,
        "date": decode_header_value(message.get("Date")),
        "list_id": decode_header_value(message.get("List-Id")),
        "list_unsubscribe": decode_header_value(message.get("List-Unsubscribe")),
        "body_preview": body_preview,
        "email_body": body_preview,
    }


def run() -> dict[str, Any]:
    dry_run = env_bool("EMAIL_CLASSIFIER_DRY_RUN", True)
    source_mailbox = os.getenv("EMAIL_CLASSIFIER_SOURCE_MAILBOX", "INBOX")
    limit = env_int("EMAIL_CLASSIFIER_LIMIT", 50)
    prefix = os.getenv("EMAIL_CLASSIFIER_FOLDER_PREFIX", "")
    categories = parse_categories(
        os.getenv("EMAIL_CLASSIFIER_LABELS")
        or os.getenv("EMAIL_CLASSIFIER_CATEGORIES")
    )
    runtime_config = load_runtime_config()
    prompt_settings = prompt_settings_from_config(runtime_config)

    result: dict[str, Any] = {
        "dry_run": dry_run,
        "source_mailbox": source_mailbox,
        "limit": limit,
        "categories": categories,
        "prompt_configured": bool(runtime_config),
        "processed": [],
        "errors": [],
    }

    client = connect_imap()
    try:
        existing = list_mailboxes(client)
        result["mailboxes"] = sorted(existing)
        uids = fetch_latest_uids(client, source_mailbox, limit)
        result["matched_count"] = len(uids)

        for uid in uids:
            uid_text = uid.decode("ascii", errors="replace")
            item: dict[str, Any] = {"uid": uid_text}
            try:
                summary = fetch_message_summary(client, uid)
                item.update({
                    "from": summary["from"],
                    "subject": summary["subject"],
                    "date": summary["date"],
                })
                classification = classify_with_ollama(summary, categories, prompt_settings)
                destinations = destination_mailboxes(
                    classification.get("folders", []) or [classification["folder"]],
                    prefix,
                )
                mailbox_actions = {
                    destination: ensure_mailbox(client, destination, existing, dry_run)
                    for destination in destinations
                }
                apply_actions = apply_message_to_destinations(client, uid, destinations, dry_run)
                item.update({
                    "classification": classification,
                    "destination": destinations[0],
                    "destinations": destinations,
                    "mailbox_actions": mailbox_actions,
                    "move_action": apply_actions["source_action"],
                    **apply_actions,
                })
            except (OSError, TimeoutError, urllib.error.URLError, RuntimeError, ValueError) as exc:
                item["error"] = str(exc)
                result["errors"].append({"uid": uid_text, "error": str(exc)})
            result["processed"].append(item)
    finally:
        try:
            client.logout()
        except Exception:
            pass

    return result


def main() -> int:
    try:
        print(json.dumps(run(), indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
