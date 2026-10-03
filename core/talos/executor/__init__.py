"""Executor determinístico (SPEC §3.1, §7.2): executa UMA vez o que o Lucas aprovou.

O LLM nunca recebe estas capacidades como ferramenta.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from talos.clock import add_business_days, utcnow
from talos.connectors.mime import build_message, deterministic_message_id, to_raw
from talos.db.models import PendingAction, Watch
from talos.logging import get_logger
from talos.vault.placeholders import resolve

if TYPE_CHECKING:
    from talos.approvals import Approvals
    from talos.channels.notifier import Notifier
    from talos.config import Settings
    from talos.connectors.calendar import CalendarAPI
    from talos.connectors.gmail import GmailAPI
    from talos.control import Control
    from talos.db.engine import Database
    from talos.events import EventBus
    from talos.scheduler.jobs import JobQueue
    from talos.tasks import TaskService
    from talos.vault.store import Vault

log = get_logger("talos.executor")


class ExecutorPaused(RuntimeError):
    pass


class Executor:
    def __init__(self, *, settings: Settings, db: Database, bus: EventBus, queue: JobQueue, vault: Vault,
                 approvals: Approvals, tasks: TaskService, control: Control, notifier: Notifier | None,
                 gmail: GmailAPI | None, calendar: CalendarAPI | None) -> None:
        self.s = settings
        self.db = db
        self.bus = bus
        self.queue = queue
        self.vault = vault
        self.approvals = approvals
        self.tasks = tasks
        self.control = control
        self.notifier = notifier
        self.gmail = gmail
        self.calendar = calendar
        self._app: Any = None  # Services, ligado em build_services (o organizador precisa do sistema completo)

    async def run(self, action_id: int) -> dict[str, Any]:
        if self.control.is_paused():
            raise ExecutorPaused("Talos pausado")
        if not self.approvals._transition(action_id, ("approved",), "executing"):
            a = self.approvals.get(action_id)
            log.info("executor_skip", action_id=action_id, status=a.status if a else None)
            return {"skipped": True, "status": a.status if a else None}
        action = self.approvals.get(action_id)
        try:
            if action.kind in ("email.send", "email.reply"):
                result = await self._send_email(action)
            elif action.kind == "calendar.invite":
                result = await self._calendar_invite(action)
            elif action.kind == "email.organize":
                from talos.monitor.organizer import execute_organize

                if self.gmail is None:
                    raise RuntimeError("Gmail não configurado")
                result = await execute_organize(self._app, action)
            else:
                raise NotImplementedError(f"execução de {action.kind} ainda não implementada (fase 4)")
        except Exception as e:
            self.approvals._transition(action_id, ("executing",), "failed", executed_at=utcnow(),
                                       result_json={"error": str(e)[:500]})
            self.bus.emit("action_failed", {"action_id": action_id, "error": str(e)[:300]}, task_id=action.task_id)
            log.error("executor_failed", action_id=action_id, error=str(e))
            if self.notifier:
                await self.notifier.notify(f"❌ A proposta #{action_id} falhou ao executar: {e}", urgent=True,
                                           task_id=action.task_id, mascot="error")
            self._resume(action, f"A execução da proposta #{action_id} FALHOU: {e}. Avalie e informe o Lucas.")
            return {"error": str(e)}

        self.approvals._transition(action_id, ("executing",), "executed", executed_at=utcnow(), result_json=result)
        self.bus.emit("action_executed", {"action_id": action_id, "kind": action.kind, **result},
                      task_id=action.task_id)
        if self.notifier:
            await self.notifier.notify(self._done_text(action, result), task_id=action.task_id, mascot="approved")
        self._resume(action, f"Proposta #{action_id} executada: {self._done_text(action, result)}")
        return result

    async def recover_executing(self) -> list[int]:
        """No arranque: ações presas em `executing` (crash a meio). Nunca reenvia às cegas."""
        from sqlmodel import select

        with self.db.session() as s:
            stuck = list(s.exec(select(PendingAction).where(PendingAction.status == "executing")))
        recovered = []
        for a in stuck:
            sent = None
            if a.kind in ("email.send", "email.reply") and self.gmail is not None:
                sent = await asyncio.to_thread(self.gmail.find_by_rfc822_id,
                                               deterministic_message_id(a.idempotency_key))
            if sent:
                self.approvals._transition(a.id, ("executing",), "executed", executed_at=utcnow(),
                                           result_json={"message_id": sent["id"], "thread_id": sent["threadId"],
                                                        "recovered": True})
            else:
                self.approvals._transition(a.id, ("executing",), "failed", executed_at=utcnow(),
                                           result_json={"error": "interrompido a meio; estado incerto"})
                if self.notifier:
                    await self.notifier.notify(
                        f"⚠️ A proposta #{a.id} foi interrompida a meio da execução e não encontrei "
                        "confirmação do envio. Não reenviei. Confira no Gmail e peça de novo se faltar.",
                        urgent=True, task_id=a.task_id)
            recovered.append(a.id)
        return recovered

    # ---------------- email ----------------
    async def _send_email(self, action: PendingAction) -> dict[str, Any]:
        if self.gmail is None:
            raise RuntimeError("Gmail não configurado")
        p = action.payload_json
        values = {k: self.vault.get(k) or "" for k in p.get("_data_keys", [])}
        subject = resolve(p["subject"], values)
        body = resolve(p["body"], values)
        msg_id = deterministic_message_id(action.idempotency_key)

        existing = await asyncio.to_thread(self.gmail.find_by_rfc822_id, msg_id)
        if existing:  # já saiu (retry após crash, toque duplo…): não envia de novo
            sent = existing
            already = True
        else:
            in_reply_to, references = p.get("in_reply_to"), p.get("references")
            if p.get("thread_id") and not in_reply_to:
                in_reply_to, references = await asyncio.to_thread(self._thread_refs, p["thread_id"])
            mime = build_message(sender=self.s.gmail_address, to=p["to"], cc=p.get("cc"), subject=subject,
                                 body=body, reply_to=self.s.agent_inbox_address or None, message_id=msg_id,
                                 in_reply_to=in_reply_to, references=references)
            raw = to_raw(mime)
            if p.get("draft_id"):
                await asyncio.to_thread(self.gmail.update_draft, p["draft_id"], raw, p.get("thread_id"))
                sent = await asyncio.to_thread(self.gmail.send_draft, p["draft_id"])
            else:
                sent = await asyncio.to_thread(self.gmail.send_message, raw, p.get("thread_id"))
            already = False

        watch_id = self._ensure_watch(action, sent["threadId"], sent["id"])
        return {"message_id": sent["id"], "thread_id": sent["threadId"], "rfc822_id": msg_id,
                "already_sent": already, "watch_id": watch_id, "to": p["to"], "subject": subject}

    def _thread_refs(self, thread_id: str) -> tuple[str | None, str | None]:
        th = self.gmail.get_thread(thread_id)  # type: ignore[union-attr]
        last = th["messages"][-1] if th["messages"] else {}
        return last.get("message_id") or None, last.get("references") or None

    def _ensure_watch(self, action: PendingAction, thread_id: str, last_msg: str) -> int | None:
        policy = action.payload_json.get("watch", {})
        if policy is False:
            return None
        from sqlmodel import select

        with self.db.session() as s:
            w = s.exec(select(Watch).where(Watch.kind == "email_thread", Watch.target == thread_id,
                                           Watch.status == "active")).first()
            bd = int(policy.get("business_days", self.s.followup_business_days)) if isinstance(policy, dict) \
                else self.s.followup_business_days
            nxt = add_business_days(utcnow(), bd, self.s.timezone)
            if w is None:
                w = Watch(task_id=action.task_id, kind="email_thread", target=thread_id, last_marker=last_msg,
                          followup_policy_json={"business_days": bd,
                                                "max": int(policy.get("max", self.s.max_followups))
                                                if isinstance(policy, dict) else self.s.max_followups},
                          next_check_at=nxt)
            else:
                w.last_marker, w.next_check_at = last_msg, nxt
            s.add(w)
            s.commit()
            s.refresh(w)
            return w.id

    # ---------------- calendário ----------------
    async def _calendar_invite(self, action: PendingAction) -> dict[str, Any]:
        if self.calendar is None:
            raise RuntimeError("Calendar não configurado")
        p = action.payload_json
        event = {
            "summary": p["summary"], "location": p.get("location", ""), "description": p.get("description", ""),
            "start": {"dateTime": p["start"], "timeZone": self.s.timezone},
            "end": {"dateTime": p["end"], "timeZone": self.s.timezone},
            "attendees": [{"email": a} for a in p.get("attendees", [])],
            "extendedProperties": {"private": {"talos_key": action.idempotency_key}},
        }
        ev = await asyncio.to_thread(self.calendar.create_event, event, send_updates="all")
        return {"event_id": ev.get("id"), "attendees": p.get("attendees", [])}

    # ---------------- comum ----------------
    def _resume(self, action: PendingAction, message: str) -> None:
        if action.task_id is None:
            return
        self.tasks.update(action.task_id, status="running")
        self.queue.enqueue("agent.task_run", {"event": message}, task_id=action.task_id)

    @staticmethod
    def _done_text(action: PendingAction, result: dict[str, Any]) -> str:
        if action.kind in ("email.send", "email.reply"):
            extra = " (já tinha saído antes; não reenviei)" if result.get("already_sent") else ""
            return f"✅ Email enviado para {', '.join(result.get('to', []))}: «{result.get('subject', '')}»{extra}"
        if action.kind == "calendar.invite":
            return f"✅ Convite enviado para {', '.join(result.get('attendees', []))}"
        if action.kind == "email.organize":
            return (f"✅ Caixa organizada: {result.get('labeled', 0)} rotulados, {result.get('archived', 0)} "
                    "arquivados. /desfazer_organizacao devolve os arquivados à caixa.")
        return f"✅ Proposta #{action.id} executada"
