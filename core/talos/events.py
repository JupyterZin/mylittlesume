"""Eventos de tarefa: trilha de auditoria (tabela `task_events`) + difusão em tempo real
(WebSocket do app, estados do mascote)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from talos.db.engine import Database
from talos.db.models import TaskEvent

Listener = Callable[[dict[str, Any]], Any]


class EventBus:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._listeners: list[Listener] = []

    def subscribe(self, fn: Listener) -> Callable[[], None]:
        self._listeners.append(fn)
        return lambda: self._listeners.remove(fn) if fn in self._listeners else None

    def emit(self, type_: str, payload: dict[str, Any] | None = None, *, task_id: int | None = None,
             persist: bool = True) -> dict[str, Any]:
        payload = payload or {}
        event = {"type": type_, "task_id": task_id, "payload": payload}
        if persist:
            with self.db.session() as s:
                row = TaskEvent(task_id=task_id, type=type_, payload_json=payload)
                s.add(row)
                s.commit()
                s.refresh(row)
                event["id"] = row.id
                event["created_at"] = row.created_at.isoformat()
        self.publish(event)
        return event

    def publish(self, event: dict[str, Any]) -> None:
        for fn in list(self._listeners):
            try:
                res = fn(event)
                if asyncio.iscoroutine(res):
                    asyncio.ensure_future(res)
            except Exception:
                pass
