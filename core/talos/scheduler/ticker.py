"""Tique periódico determinístico (ADR-011): expirações, lembretes, recorrências, pausa externa."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, select

from talos.clock import utcnow
from talos.db.models import Schedule
from talos.logging import get_logger
from talos.tools.definitions import next_occurrence

if TYPE_CHECKING:
    from talos.orchestrator.core import Orchestrator
    from talos.services import Services

log = get_logger("talos.ticker")


class Ticker:
    def __init__(self, app: Services, orch: Orchestrator) -> None:
        self.app = app
        self.orch = orch

    async def minute(self) -> None:
        self.orch.cancel_if_paused()
        if self.app.control.is_paused():
            return
        res = self.app.approvals.sweep()
        for aid in res["remind"]:
            self.app.queue.enqueue("approval.card", {"action_id": aid}, dedupe_key=f"card:{aid}")
        if res["expired"]:
            await self.app.notifier.notify(
                "⌛ Expiraram sem resposta: " + ", ".join(f"#{i}" for i in res["expired"]) + ". Nada foi executado.")
        self.due_schedules()

    def due_schedules(self) -> int:
        now = utcnow()
        n = 0
        with self.app.db.session() as s:
            due = list(s.exec(select(Schedule).where(Schedule.enabled == True,  # noqa: E712
                                                     col(Schedule.next_run_at) <= now)))
            for sc in due:
                kind = {"briefing": "agent.briefing", "reflection": "agent.reflection"}.get(sc.kind, "agent.schedule")
                self.app.queue.enqueue(kind, {"schedule_id": sc.id, "prompt": sc.prompt, "title": sc.kind},
                                       dedupe_key=f"sched:{sc.id}:{sc.next_run_at.isoformat()}")
                sc.next_run_at = next_occurrence(sc.rrule, self.app.settings.timezone, after=now)
                if sc.next_run_at is None:
                    sc.enabled = False
                s.add(sc)
                n += 1
            s.commit()
        return n
