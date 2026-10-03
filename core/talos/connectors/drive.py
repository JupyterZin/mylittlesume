"""Conector Google Drive (só leitura)."""

from __future__ import annotations

from typing import Any, Protocol

from talos.connectors.google_lock import serialized

EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


class DriveAPI(Protocol):
    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]: ...
    def read(self, file_id: str, max_chars: int = 20000) -> dict[str, Any]: ...


@serialized
class GoogleDrive:
    def __init__(self, creds: Any) -> None:
        from googleapiclient.discovery import build

        self.svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        q = query.replace("\\", "\\\\").replace("'", "\\'")
        res = self.svc.files().list(q=f"fullText contains '{q}' and trashed = false", pageSize=max_results,
                                    fields="files(id,name,mimeType,modifiedTime,webViewLink)").execute()
        return res.get("files", [])

    def read(self, file_id: str, max_chars: int = 20000) -> dict[str, Any]:
        meta = self.svc.files().get(fileId=file_id, fields="id,name,mimeType").execute()
        mime = meta["mimeType"]
        if mime in EXPORTS:
            data = self.svc.files().export(fileId=file_id, mimeType=EXPORTS[mime]).execute()
        elif mime.startswith("text/") or mime in ("application/json",):
            data = self.svc.files().get_media(fileId=file_id).execute()
        else:
            return {**meta, "text": f"(formato {mime} não suportado para leitura direta)"}
        text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
        return {**meta, "text": text[:max_chars], "truncated": len(text) > max_chars}
