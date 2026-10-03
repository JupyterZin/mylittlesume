"""Conector Gmail (API oficial). O ENVIO só é chamado pelo executor, nunca exposto ao agente."""

from __future__ import annotations

from typing import Any, Protocol

from talos.connectors.mime import headers_map, text_from_payload


class HistoryExpired(Exception):
    """startHistoryId expirado (HTTP 404): fazer ressincronização completa."""


class GmailAPI(Protocol):
    def profile(self) -> dict[str, Any]: ...
    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]: ...
    def get_message(self, msg_id: str) -> dict[str, Any]: ...
    def get_thread(self, thread_id: str) -> dict[str, Any]: ...
    def create_draft(self, raw: str, thread_id: str | None = None) -> str: ...
    def update_draft(self, draft_id: str, raw: str, thread_id: str | None = None) -> None: ...
    def get_draft(self, draft_id: str) -> dict[str, Any]: ...
    def send_draft(self, draft_id: str) -> dict[str, Any]: ...
    def send_message(self, raw: str, thread_id: str | None = None) -> dict[str, Any]: ...
    def find_by_rfc822_id(self, message_id: str) -> dict[str, Any] | None: ...
    def history(self, start_history_id: str) -> tuple[list[dict[str, Any]], str]: ...
    def ensure_label(self, name: str) -> str: ...
    def modify(self, msg_id: str, add: list[str] | None = None, remove: list[str] | None = None) -> None: ...


def normalize_message(m: dict[str, Any]) -> dict[str, Any]:
    h = headers_map((m.get("payload") or {}).get("headers", []))
    return {
        "id": m["id"],
        "threadId": m.get("threadId"),
        "labelIds": m.get("labelIds", []),
        "from": h.get("from", ""),
        "to": h.get("to", ""),
        "cc": h.get("cc", ""),
        "reply_to": h.get("reply-to", ""),
        "subject": h.get("subject", ""),
        "date": h.get("date", ""),
        "message_id": h.get("message-id", ""),
        "references": h.get("references", ""),
        "auto_submitted": h.get("auto-submitted", ""),
        "snippet": m.get("snippet", ""),
        "body": text_from_payload(m.get("payload") or {}),
    }


class GoogleGmail:
    def __init__(self, creds: Any) -> None:
        from googleapiclient.discovery import build

        self.svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._labels: dict[str, str] = {}

    def profile(self) -> dict[str, Any]:
        return self.svc.users().getProfile(userId="me").execute()

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        res = self.svc.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        return [self.get_message(m["id"]) for m in res.get("messages", [])]

    def get_message(self, msg_id: str) -> dict[str, Any]:
        return normalize_message(self.svc.users().messages().get(userId="me", id=msg_id, format="full").execute())

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        t = self.svc.users().threads().get(userId="me", id=thread_id, format="full").execute()
        return {"id": t["id"], "messages": [normalize_message(m) for m in t.get("messages", [])]}

    def create_draft(self, raw: str, thread_id: str | None = None) -> str:
        msg: dict[str, Any] = {"raw": raw}
        if thread_id:
            msg["threadId"] = thread_id
        return self.svc.users().drafts().create(userId="me", body={"message": msg}).execute()["id"]

    def update_draft(self, draft_id: str, raw: str, thread_id: str | None = None) -> None:
        msg: dict[str, Any] = {"raw": raw}
        if thread_id:
            msg["threadId"] = thread_id
        self.svc.users().drafts().update(userId="me", id=draft_id, body={"message": msg}).execute()

    def get_draft(self, draft_id: str) -> dict[str, Any]:
        d = self.svc.users().drafts().get(userId="me", id=draft_id, format="full").execute()
        return normalize_message(d["message"])

    def send_draft(self, draft_id: str) -> dict[str, Any]:
        return self.svc.users().drafts().send(userId="me", body={"id": draft_id}).execute()

    def send_message(self, raw: str, thread_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        return self.svc.users().messages().send(userId="me", body=body).execute()

    def find_by_rfc822_id(self, message_id: str) -> dict[str, Any] | None:
        mid = message_id.strip("<>")
        # só mensagens ENVIADAS: um rascunho com o mesmo Message-ID não conta como envio
        res = self.svc.users().messages().list(userId="me", q=f"rfc822msgid:{mid} in:sent").execute()
        msgs = res.get("messages", [])
        return msgs[0] if msgs else None

    def history(self, start_history_id: str) -> tuple[list[dict[str, Any]], str]:
        from googleapiclient.errors import HttpError

        out: list[dict[str, Any]] = []
        req = self.svc.users().history().list(userId="me", startHistoryId=start_history_id,
                                               historyTypes=["messageAdded"], maxResults=500)
        last = start_history_id
        try:
            while req is not None:
                resp = req.execute()
                for h in resp.get("history", []):
                    for added in h.get("messagesAdded", []):
                        out.append(added["message"])
                last = resp.get("historyId", last)
                req = self.svc.users().history().list_next(req, resp)
        except HttpError as e:
            if getattr(e, "status_code", None) == 404 or e.resp.status == 404:
                raise HistoryExpired(str(e)) from e
            raise
        return out, str(last)

    def ensure_label(self, name: str) -> str:
        if not self._labels:
            for lab in self.svc.users().labels().list(userId="me").execute().get("labels", []):
                self._labels[lab["name"]] = lab["id"]
        if name not in self._labels:
            lab = self.svc.users().labels().create(userId="me", body={
                "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute()
            self._labels[name] = lab["id"]
        return self._labels[name]

    def modify(self, msg_id: str, add: list[str] | None = None, remove: list[str] | None = None) -> None:
        self.svc.users().messages().modify(userId="me", id=msg_id, body={
            "addLabelIds": add or [], "removeLabelIds": remove or []}).execute()
