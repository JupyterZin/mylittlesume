"""Gestão de tarefas (SPEC §5 `tasks`)."""

from __future__ import annotations

from typing import Any

from sqlmodel import col, select

from talos.clock import utcnow
from talos.db.engine import Database
from talos.db.models import TASK_STATUSES, PendingAction, Task, Watch
from talos.events import EventBus

OPEN_STATUSES = ("planning", "running", "waiting_approval", "waiting_external", "scheduled")


class TaskService:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus

    def create(self, title: str, goal: str = "", *, origin_conversation_id: int | None = None,
               parent_task_id: int | None = None, plan: dict[str, Any] | None = None,
               model_profile: str = "task", priority: int = 0) -> Task:
        with self.db.session() as s:
            t = Task(title=title[:200], goal=goal, origin_conversation_id=origin_conversation_id,
                     parent_task_id=parent_task_id, plan_json=plan or {}, model_profile=model_profile,
                     priority=priority)
            s.add(t)
            s.commit()
            s.refresh(t)
        self.bus.emit("task_created", {"title": t.title}, task_id=t.id)
        return t

    def get(self, task_id: int) -> Task | None:
        with self.db.session() as s:
            return s.get(Task, task_id)

    def update(self, task_id: int, **fields: Any) -> Task:
        if "status" in fields and fields["status"] not in TASK_STATUSES:
            raise ValueError(f"estado inválido: {fields['status']}")
        with self.db.session() as s:
            t = s.get(Task, task_id)
            if t is None:
                raise KeyError(task_id)
            old = t.status
            for k, v in fields.items():
                setattr(t, k, v)
            t.updated_at = utcnow()
            s.add(t)
            s.commit()
            s.refresh(t)
        if "status" in fields and fields["status"] != old:
            self.bus.emit("task_status", {"from": old, "to": t.status}, task_id=task_id)
        return t

    def authorize_data(self, task_id: int, keys: list[str]) -> None:
        t = self.get(task_id)
        if t is None:
            return
        merged = sorted(set(t.authorized_data_json or []) | set(keys))
        self.update(task_id, authorized_data_json=merged)

    def authorized_keys(self, task_id: int | None) -> list[str]:
        if task_id is None:
            return []
        t = self.get(task_id)
        return list(t.authorized_data_json or []) if t else []

    def list(self, statuses: tuple[str, ...] | None = None, limit: int = 50) -> list[Task]:
        with self.db.session() as s:
            q = select(Task).order_by(col(Task.updated_at).desc()).limit(limit)
            if statuses:
                q = q.where(col(Task.status).in_(statuses))
            return list(s.exec(q))

    def settle_after_run(self, task_id: int) -> Task:
        """Depois de uma execução: se o agente não fechou a tarefa, deduz o estado de espera."""
        t = self.get(task_id)
        if t is None or t.status not in ("running", "planning"):
            return t  # type: ignore[return-value]
        with self.db.session() as s:
            pending = s.exec(select(PendingAction).where(PendingAction.task_id == task_id,
                                                         PendingAction.status == "pending")).first()
            watch = s.exec(select(Watch).where(Watch.task_id == task_id, Watch.status == "active")).first()
        if pending:
            return self.update(task_id, status="waiting_approval")
        if watch:
            return self.update(task_id, status="waiting_external")
        return self.update(task_id, status="done")
