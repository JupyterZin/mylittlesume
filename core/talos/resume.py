"""Retomar o trabalho depois de um evento (proposta decidida/executada, resposta recebida, follow-up).

Se o trabalho nasceu numa tarefa, retoma a sessão da tarefa. Se nasceu direto na conversa principal
(o agente fez tudo no chat, sem `task_create`), o evento volta à conversa principal, que tem o contexto.
Antes disto, eventos sem tarefa morriam em silêncio (encontrado no teste real do caso âncora).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, select

from talos.db.models import Conversation

if TYPE_CHECKING:
    from talos.db.engine import Database
    from talos.scheduler.jobs import JobQueue
    from talos.tasks import TaskService


def default_conversation(db: Database) -> int | None:
    with db.session() as s:
        conv = s.exec(select(Conversation).where(Conversation.channel == "telegram")).first() or \
            s.exec(select(Conversation).order_by(col(Conversation.id).desc())).first()
        return conv.id if conv else None


def resume_work(*, queue: JobQueue, tasks: TaskService, db: Database, task_id: int | None,
                conversation_id: int | None, event: str, dedupe_key: str | None = None) -> str | None:
    if task_id is not None:
        tasks.update(task_id, status="running")
        queue.enqueue("agent.task_run", {"event": event}, task_id=task_id, dedupe_key=dedupe_key)
        return "task"
    conv = conversation_id or default_conversation(db)
    if conv is None:
        return None
    queue.enqueue("agent.main_event", {"conversation_id": conv, "event": event}, priority=4, dedupe_key=dedupe_key)
    return "main"
