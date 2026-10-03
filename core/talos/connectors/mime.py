"""Construção e leitura de mensagens MIME para o Gmail."""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from email.utils import formatdate, getaddresses
from html import unescape
from typing import Any

MSGID_DOMAIN = "talos.local"


def deterministic_message_id(idempotency_key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", idempotency_key)
    return f"<talos-{safe}@{MSGID_DOMAIN}>"


def build_message(*, sender: str, to: list[str], subject: str, body: str, cc: list[str] | None = None,
                  reply_to: str | None = None, message_id: str | None = None,
                  in_reply_to: str | None = None, references: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    if sender:
        msg["From"] = sender
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    if reply_to:
        msg["Reply-To"] = reply_to
    if message_id:
        msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = f"{references} {in_reply_to}".strip() if references else in_reply_to
    msg.set_content(body)
    return msg


def to_raw(msg: EmailMessage) -> str:
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def from_raw(raw: str) -> EmailMessage:
    from email import message_from_bytes, policy

    return message_from_bytes(base64.urlsafe_b64decode(raw.encode()), policy=policy.default)  # type: ignore[return-value]


def addresses(header_value: str | None) -> list[str]:
    return [a.lower() for _, a in getaddresses([header_value or ""]) if a]


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode() + b"=" * (-len(data) % 4)).decode("utf-8", "replace")


def text_from_payload(payload: dict[str, Any]) -> str:
    """Extrai texto de um payload `format=full` da API do Gmail (prefere text/plain)."""
    plain, html = [], []

    def walk(p: dict[str, Any]) -> None:
        mime = p.get("mimeType", "")
        data = (p.get("body") or {}).get("data")
        if data and mime == "text/plain":
            plain.append(_b64(data))
        elif data and mime == "text/html":
            html.append(_b64(data))
        for sub in p.get("parts") or []:
            walk(sub)

    walk(payload)
    if plain:
        return "\n".join(plain)
    if html:
        return html_to_text("\n".join(html))
    return ""


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", html)
    return unescape(re.sub(r"<[^>]+>", "", html)).strip()


def headers_map(headers: list[dict[str, str]]) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in headers or []}
