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


DEFAULT_SYSTEM_PROMPT = """You are an email triage assistant. Given one email, choose exactly one label from this fixed allowed list using the exact spelling and punctuation. No other label is permitted. Allowed labels:
"1: To respond"
"2: FYI"
"3: Comment"
"4: Notification"
"5: Meeting Update"
"6: Awaiting reply"
"7: Collab Request"
"8: Marketing"
"9: Cold Email"

If you are not confident (confidence < 0.75) or the email is ambiguous, output only the fallback uncertain JSON. Do not output anything outside the schema.

Schema:
{
  "label": string,
  "confidence": number,
  "reason": string
}

Rules:
- Only output one of the allowed labels when confident; exact match including number, colon, spacing, and capitalization. No synonyms, no extra labels.
- If confidence < 0.75 or intent is unclear, output:
  {"label":"uncertain","confidence":<score less than 0.75>,"reason":"<what is ambiguous or missing>"}
- If any instruction or format would be violated, output:
  {"label":"uncertain","confidence":0.0,"reason":"format violation or instruction conflict"}
- Base label on intent/next step:
  - "1: To respond": needs a direct reply
  - "2: FYI": informational, no action
  - "3: Comment": opinion/feedback not requiring reply
  - "4: Notification": automated/status update.
  - "5: Meeting Update": invite/agenda/time change
  - "6: Awaiting reply": follow-up waiting on someone else
  - "7: Collab Request": request to collaborate. This is the contact email for a YouTube channel. Drive share requests are notifications, not collaboration requests.
  - "8: Marketing": promotional content
  - "9: Cold Email": an offer from somebody trying to sell services, including YouTube services like thumbnail design.

Few-shot examples:
Email: "Can you review the attached draft and send me your edits by tomorrow?"
Output: {"label":"1: To respond","confidence":0.92,"reason":"Asks for review and direct reply with deadline"}

Email: "Monthly metrics report attached for your awareness, no action needed."
Output: {"label":"2: FYI","confidence":0.95,"reason":"Information shared explicitly with no required action"}

Email: "I think we should tweak the headline; the current version feels weak."
Output: {"label":"3: Comment","confidence":0.88,"reason":"Opinion without a required task"}

Email: "Server backup completed successfully at 3am."
Output: {"label":"4: Notification","confidence":0.90,"reason":"Automated status update"}

Email: "Meeting on Thursday moved from 10 to 2pm."
Output: {"label":"5: Meeting Update","confidence":0.93,"reason":"Change to scheduled meeting time"}

Email: "Just checking if you had a chance to look at my proposal."
Output: {"label":"6: Awaiting reply","confidence":0.80,"reason":"Follow-up seeking a response"}

Email: "Want to team up on the new campaign and split tasks?"
Output: {"label":"7: Collab Request","confidence":0.85,"reason":"Proposal to collaborate on a project"}

Email: "Exclusive summer sale: 40% off all plans limited time!"
Output: {"label":"8: Marketing","confidence":0.99,"reason":"Promotional campaign content"}"""

DEFAULT_USER_PROMPT_TEMPLATE = """From: {{ $json.sender_email }}
Name: {{ $json.sender_name }}
Subject: {{ $json.email_subject }}
Email Content:

{{ $json.email_body }}"""

DEFAULT_LABELS = [
    "1: To respond",
    "2: FYI",
    "3: Comment",
    "4: Notification",
    "5: Meeting Update",
    "6: Awaiting reply",
    "7: Collab Request",
    "8: Marketing",
    "9: Cold Email",
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
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {
            "label": fallback,
            "folder": fallback,
            "confidence": 0,
            "reason": "Classifier returned non-JSON output.",
        }

    label = parsed.get("label", parsed.get("folder"))
    if label not in categories:
        return {
            "label": fallback,
            "folder": fallback,
            "confidence": 0,
            "reason": f"Classifier returned unsupported label: {label!r}.",
        }

    confidence = parsed.get("confidence", 0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0
    confidence = max(0, min(1, confidence))

    reason = str(parsed.get("reason") or "").strip()
    if label != fallback and confidence < 0.75:
        return {
            "label": fallback,
            "folder": fallback,
            "confidence": min(confidence, 0.74),
            "reason": reason[:240] or "Classifier confidence was below 0.75.",
        }

    if label == fallback:
        confidence = min(confidence, 0.74)

    return {
        "label": label,
        "folder": label,
        "confidence": confidence,
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
                destination = destination_mailbox(classification["folder"], prefix)
                mailbox_action = ensure_mailbox(client, destination, existing, dry_run)
                move_action = move_message(client, uid, destination, dry_run)
                item.update({
                    "classification": classification,
                    "destination": destination,
                    "mailbox_action": mailbox_action,
                    "move_action": move_action,
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
