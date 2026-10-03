"""Fakes em memória (SPEC §15): a maior parte da suíte roda sem Google, Telegram nem assinatura."""

from __future__ import annotations

import itertools
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from talos.connectors.gmail import HistoryExpired
from talos.connectors.mime import addresses, build_message, from_raw


class FakeGmail:
    def __init__(self, address: str = "lucas.teste@gmail.com") -> None:
        self.address = address
        self._ids = itertools.count(1)
        self._hid = itertools.count(1000)
        self.history_id = "1000"
        self.messages: dict[str, dict[str, Any]] = {}
        self.drafts: dict[str, dict[str, Any]] = {}
        self.labels: dict[str, str] = {}
        self._history: list[tuple[int, dict[str, Any]]] = []
        self.expired_before: int = 0
        self.sent: list[dict[str, Any]] = []

    # ---------- utilitários de teste ----------
    def _new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids):04d}"

    def _store(self, msg: EmailMessage, thread_id: str | None, labels: list[str]) -> dict[str, Any]:
        mid = self._new_id("m")
        tid = thread_id or self._new_id("t")
        rec = {"id": mid, "threadId": tid, "labelIds": labels, "msg": msg}
        self.messages[mid] = rec
        hid = next(self._hid)
        self.history_id = str(hid)
        self._history.append((hid, {"id": mid, "threadId": tid, "labelIds": list(labels)}))
        return rec

    def deliver(self, *, sender: str, subject: str, body: str, to: str | None = None,
                thread_id: str | None = None, in_reply_to: str | None = None,
                headers: dict[str, str] | None = None, labels: list[str] | None = None) -> dict[str, Any]:
        msg = build_message(sender=sender, to=[to or self.address], subject=subject, body=body,
                            message_id=f"<{self._new_id('ext')}@externo.example>", in_reply_to=in_reply_to)
        for k, v in (headers or {}).items():
            msg[k] = v
        return self._store(msg, thread_id, ["INBOX", "UNREAD", *(labels or [])])

    def expire_history(self) -> None:
        self.expired_before = int(self.history_id) + 1

    # ---------- GmailAPI ----------
    def profile(self) -> dict[str, Any]:
        return {"emailAddress": self.address, "historyId": self.history_id}

    def _norm(self, rec: dict[str, Any]) -> dict[str, Any]:
        m: EmailMessage = rec["msg"]
        body = m.get_body(preferencelist=("plain",))
        return {
            "id": rec["id"], "threadId": rec["threadId"], "labelIds": list(rec["labelIds"]),
            "from": m.get("From", ""), "to": m.get("To", ""), "cc": m.get("Cc", ""),
            "reply_to": m.get("Reply-To", ""), "subject": m.get("Subject", ""), "date": m.get("Date", ""),
            "message_id": m.get("Message-ID", ""), "references": m.get("References", ""),
            "auto_submitted": m.get("Auto-Submitted", ""),
            "list_unsubscribe": m.get("List-Unsubscribe", ""),
            "snippet": (body.get_content() if body else "")[:120],
            "body": body.get_content() if body else "",
        }

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        out = []
        for rec in reversed(list(self.messages.values())):
            n = self._norm(rec)
            if query.startswith("rfc822msgid:"):
                if n["message_id"].strip("<>") != query.split(":", 1)[1].strip("<>"):
                    continue
            elif query.startswith("from:"):
                if query[5:].lower() not in n["from"].lower():
                    continue
            elif query and query.lower() not in (n["subject"] + " " + n["body"] + " " + n["from"]).lower():
                continue
            out.append(n)
            if len(out) >= max_results:
                break
        return out

    def get_message(self, msg_id: str) -> dict[str, Any]:
        return self._norm(self.messages[msg_id])

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        msgs = [self._norm(r) for r in self.messages.values() if r["threadId"] == thread_id]
        if not msgs:
            raise KeyError(thread_id)
        return {"id": thread_id, "messages": msgs}

    def create_draft(self, raw: str, thread_id: str | None = None) -> str:
        did = self._new_id("d")
        self.drafts[did] = {"msg": from_raw(raw), "threadId": thread_id}
        return did

    def update_draft(self, draft_id: str, raw: str, thread_id: str | None = None) -> None:
        if draft_id not in self.drafts:
            raise KeyError(draft_id)
        self.drafts[draft_id] = {"msg": from_raw(raw), "threadId": thread_id}

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        d = self.drafts[draft_id]
        return self._norm({"id": draft_id, "threadId": d["threadId"], "labelIds": ["DRAFT"], "msg": d["msg"]})

    def send_draft(self, draft_id: str) -> dict[str, Any]:
        d = self.drafts.pop(draft_id)
        rec = self._store(d["msg"], d["threadId"], ["SENT"])
        self.sent.append(rec)
        return {"id": rec["id"], "threadId": rec["threadId"]}

    def send_message(self, raw: str, thread_id: str | None = None) -> dict[str, Any]:
        rec = self._store(from_raw(raw), thread_id, ["SENT"])
        self.sent.append(rec)
        return {"id": rec["id"], "threadId": rec["threadId"]}

    def find_by_rfc822_id(self, message_id: str) -> dict[str, Any] | None:
        res = self.search(f"rfc822msgid:{message_id}", 1)
        return {"id": res[0]["id"], "threadId": res[0]["threadId"]} if res else None

    def history(self, start_history_id: str) -> tuple[list[dict[str, Any]], str]:
        start = int(start_history_id)
        if start < self.expired_before:
            raise HistoryExpired(f"startHistoryId {start} expirado")
        return [m for hid, m in self._history if hid > start], self.history_id

    def ensure_label(self, name: str) -> str:
        return self.labels.setdefault(name, f"Label_{len(self.labels) + 1}")

    def modify(self, msg_id: str, add: list[str] | None = None, remove: list[str] | None = None) -> None:
        rec = self.messages[msg_id]
        labels = [lab for lab in rec["labelIds"] if lab not in (remove or [])]
        rec["labelIds"] = labels + [lab for lab in (add or []) if lab not in labels]

    def list_messages(self, query: str, max_results: int = 300) -> list[dict[str, Any]]:
        want_inbox = "in:inbox" in query
        out = []
        for rec in self.messages.values():
            if want_inbox and "INBOX" not in rec["labelIds"]:
                continue
            if "-is:starred" in query and "STARRED" in rec["labelIds"]:
                continue
            out.append(self._norm(rec))
        return out[:max_results]

    def batch_modify(self, ids: list[str], add: list[str] | None = None, remove: list[str] | None = None) -> None:
        for mid in ids:
            self.modify(mid, add, remove)

    # conveniência para asserts
    def sent_to(self, address: str) -> list[dict[str, Any]]:
        return [self._norm(r) for r in self.sent if address.lower() in addresses(r["msg"].get("To"))]


class FakeCalendar:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.created: list[tuple[dict[str, Any], str]] = []

    def list_events(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        return [e for e in self.events
                if time_min.isoformat() <= e["start"] <= time_max.isoformat()]

    def create_event(self, event: dict[str, Any], *, send_updates: str = "none") -> dict[str, Any]:
        ev = {"id": f"ev{len(self.created) + 1}", **event}
        self.created.append((ev, send_updates))
        self.events.append({"id": ev["id"], "summary": event.get("summary", ""),
                            "start": event["start"].get("dateTime", event["start"].get("date")),
                            "end": event["end"].get("dateTime", event["end"].get("date")),
                            "attendees": [a["email"] for a in event.get("attendees", [])]})
        return ev


class FakeDrive:
    def __init__(self, files: dict[str, dict[str, Any]] | None = None) -> None:
        self.files = files or {}

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        return [{"id": fid, "name": f["name"], "mimeType": f.get("mimeType", "text/plain")}
                for fid, f in self.files.items() if query.lower() in (f["name"] + f.get("text", "")).lower()
                ][:max_results]

    def read(self, file_id: str, max_chars: int = 20000) -> dict[str, Any]:
        f = self.files[file_id]
        return {"id": file_id, "name": f["name"], "text": f.get("text", "")[:max_chars]}
