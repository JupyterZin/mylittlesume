"""Orquestrador: conversa principal + fila de jobs (SPEC §3.1, §3.2)."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlmodel import col, func, select

from talos.clock import local_date, local_to_utc, to_local, utcnow
from talos.db.models import Conversation, Job, Message, PendingAction, Task, UsageLog
from talos.executor import ExecutorPaused
from talos.logging import get_logger
from talos.runtime.base import RunRequest, RunResult
from talos.tasks import OPEN_STATUSES

if TYPE_CHECKING:
    from talos.runtime.base import AgentRuntime
    from talos.services import Services

log = get_logger("talos.orchestrator")

AGENT_KINDS = ("agent.main_turn", "agent.task_run", "agent.triage", "agent.schedule", "agent.inbox",
               "agent.briefing", "agent.reflection")
OTHER_KINDS = ("executor.run", "notify.send", "approval.card")
BACKGROUND_AGENT_KINDS = ("agent.task_run", "agent.triage", "agent.schedule", "agent.inbox", "agent.reflection")


class Orchestrator:
    def __init__(self, app: Services, runtime: AgentRuntime) -> None:
        self.app = app
        self.runtime = runtime
        self.s = app.settings
        self._running: dict[int, asyncio.Task[Any]] = {}
        self._sem = asyncio.Semaphore(self.s.max_concurrent_agents)
        self._handlers = {
            "agent.main_turn": self._main_turn,
            "agent.task_run": self._task_run,
            "agent.schedule": self._schedule_run,
            "executor.run": self._executor_run,
            "notify.send": self._notify_send,
            "approval.card": self._approval_card,
        }

    def register(self, kind: str, handler: Any) -> None:
        self._handlers[kind] = handler

    # ======================= conversa =======================
    def conversation(self, channel: str, chat_id: str) -> Conversation:
        with self.app.db.session() as s:
            conv = s.exec(select(Conversation).where(Conversation.channel == channel,
                                                     Conversation.external_chat_id == chat_id)).first()
            if conv is None:
                conv = Conversation(channel=channel, external_chat_id=chat_id)
                s.add(conv)
                s.commit()
                s.refresh(conv)
            return conv

    def store_message(self, conv_id: int, role: str, content: str, meta: dict[str, Any] | None = None) -> Message:
        with self.app.db.session() as s:
            m = Message(conversation_id=conv_id, role=role, content=content, meta_json=meta or {})
            s.add(m)
            s.commit()
            s.refresh(m)
            return m

    async def handle_user_message(self, channel: str, chat_id: str, text: str) -> Job:
        conv = self.conversation(channel, chat_id)
        msg = self.store_message(conv.id, "user", text)
        self.app.bus.emit("message", {"role": "user", "content": text, "channel": channel}, persist=False)
        return self.app.queue.enqueue("agent.main_turn", {"message_id": msg.id, "conversation_id": conv.id},
                                      priority=5)

    def _rotation_context(self, conv: Conversation) -> str:
        """Bloco determinístico para a sessão nova do dia (ADR-010)."""
        tz = self.s.timezone
        lines = ["[contexto: nova sessão do dia]"]
        tasks = self.app.tasks.list(OPEN_STATUSES, limit=15)
        if tasks:
            lines.append("Tarefas abertas:")
            lines += [f"- #{t.id} {t.title} ({t.status})" for t in tasks]
        pend = self.app.approvals.list_pending()
        if pend:
            lines.append("Aprovações pendentes: " + ", ".join(f"#{a.id} {a.kind}" for a in pend))
        with self.app.db.session() as s:
            last = list(s.exec(select(Message).where(Message.conversation_id == conv.id)
                               .order_by(col(Message.id).desc()).limit(12)))
        if last:
            lines.append("Últimas mensagens:")
            for m in reversed(last):
                when = to_local(m.created_at, tz).strftime("%d/%m %H:%M")
                lines.append(f"- [{when}] {m.role}: {m.content[:300]}")
        return "\n".join(lines)

    # ======================= workers =======================
    async def run_forever(self, stop: asyncio.Event, poll: float = 1.0) -> None:
        self.app.queue.requeue_all_running()
        await self.app.executor.recover_executing()
        loops = [asyncio.create_task(self._loop(AGENT_KINDS, stop, poll), name=f"agent-worker-{i}")
                 for i in range(self.s.max_concurrent_agents)]
        loops.append(asyncio.create_task(self._loop(OTHER_KINDS, stop, poll), name="other-worker"))
        await stop.wait()
        for t in loops:
            t.cancel()
        await asyncio.gather(*loops, return_exceptions=True)

    async def _loop(self, kinds: tuple[str, ...], stop: asyncio.Event, poll: float) -> None:
        while not stop.is_set():
            try:
                worked = await self.process_one(kinds)
            except Exception as e:
                log.error("worker_error", error=str(e))
                worked = False
            if not worked:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), poll)

    async def process_one(self, kinds: tuple[str, ...] | None = None) -> bool:
        if self.app.control.is_paused():
            return False
        kinds = kinds or tuple(self._handlers)
        if self.app.control.takeover_active():  # o Lucas está a usar a Tela: só jobs não-agente
            kinds = tuple(k for k in kinds if not k.startswith("agent."))
            if not kinds:
                return False
        job = self.app.queue.claim(kinds)
        if job is None:
            return False
        handler = self._handlers.get(job.kind)
        if handler is None:
            self.app.queue.fail(job.id, f"sem handler para {job.kind}")
            return True
        task = asyncio.create_task(self._guarded(handler, job))
        self._running[job.id] = task
        try:
            await task
        except asyncio.CancelledError:
            self.app.queue.defer(job.id, utcnow(), "cancelado (pausa)")
            if asyncio.current_task() and asyncio.current_task().cancelling():  # type: ignore[union-attr]
                raise
        finally:
            self._running.pop(job.id, None)
        return True

    async def _guarded(self, handler: Any, job: Job) -> None:
        try:
            await handler(job)
        except asyncio.CancelledError:
            raise
        except ExecutorPaused:
            self.app.queue.defer(job.id, utcnow() + timedelta(minutes=1), "pausado")
        except Exception as e:
            log.error("job_failed", job_id=job.id, kind=job.kind, error=str(e))
            state = self.app.queue.fail(job.id, f"{type(e).__name__}: {e}", retry_in=timedelta(minutes=2))
            if state == "failed":
                self.app.bus.emit("job_failed", {"job_id": job.id, "kind": job.kind, "error": str(e)[:300]},
                                  task_id=job.task_id)
                await self.app.notifier.notify(f"❌ Falhou: {job.kind} (job #{job.id}): {e}", urgent=False,
                                               task_id=job.task_id, mascot="error")
        else:
            current = self.app.queue.get(job.id)
            if current and current.status == "running":
                self.app.queue.complete(job.id)

    async def drain(self, max_jobs: int = 100) -> int:
        """Processa tudo o que estiver pronto (testes e CLI)."""
        n = 0
        while n < max_jobs and await self.process_one():
            n += 1
        return n

    async def pause(self, by: str) -> bool:
        changed = self.app.control.pause(by)
        for t in list(self._running.values()):
            t.cancel()
        self.app.bus.emit("paused", {"by": by})
        return changed

    async def resume(self, by: str) -> bool:
        changed = self.app.control.resume(by)
        self.app.bus.emit("resumed", {"by": by})
        return changed

    async def takeover_start(self, by: str) -> bool:
        """'Assumir controle' da Tela: para o agente e guarda as tarefas que esperavam por isso."""
        if self.app.control.takeover_active():
            return False
        waiting = [t.id for t in self.app.tasks.list(("waiting_external", "running"), limit=20)]
        self.app.control.set_takeover(True, by, waiting)
        for t in list(self._running.values()):
            t.cancel()
        self.app.bus.emit("takeover_started", {"by": by})
        return True

    async def takeover_end(self, by: str) -> bool:
        """'Devolver ao Talos': retoma as tarefas que estavam à espera do Lucas na Tela."""
        st = self.app.control.takeover_state()
        if not st.get("active"):
            return False
        self.app.control.set_takeover(False, by)
        for tid in st.get("task_ids", []):
            t = self.app.tasks.get(tid)
            if t and t.status in ("waiting_external", "running"):
                self.app.tasks.update(tid, status="running")
                self.app.queue.enqueue("agent.task_run", {
                    "event": "O Lucas devolveu o controle da Tela. Veja o estado atual da página "
                             "(browser_snapshot) e continue de onde parou."}, task_id=tid)
        self.app.bus.emit("takeover_ended", {"by": by})
        return True

    def cancel_if_paused(self) -> None:
        """Chamado pelo tique: pausa pedida pelo CLI noutro processo."""
        if self.app.control.is_paused():
            for t in list(self._running.values()):
                t.cancel()

    # ======================= execução de agentes =======================
    async def _run_agent(self, job: Job, req: RunRequest) -> RunResult | None:
        background = job.kind in BACKGROUND_AGENT_KINDS
        if background and (until := self._over_daily_limit()):
            self.app.queue.defer(job.id, until, "teto diário de execuções")
            return None
        if until := self.app.control.rate_limited_until():
            from datetime import datetime

            dt = datetime.fromisoformat(until)
            if dt > utcnow():
                self.app.queue.defer(job.id, dt, "rate_limited")
                return None
        req.job_id = job.id
        async with self._sem:
            res = await self.runtime.run(req)
        self._log_usage(job, res)
        if res.rate_limited:
            resume_at = res.resets_at or utcnow() + timedelta(minutes=30)
            self.app.queue.defer(job.id, resume_at, "rate_limited")
            first = not self.app.db.get_state("rate_limit").get("notified")
            self.app.control.set_rate_limited(resume_at.isoformat(), notified=True)
            if first:
                when = to_local(resume_at, self.s.timezone).strftime("%H:%M")
                await self.app.notifier.notify(f"⏸️ Atingi o limite da assinatura. Retomo sozinho por volta das "
                                               f"{when}.", urgent=True)
            return None
        if self.app.db.get_state("rate_limit").get("until"):
            self.app.control.set_rate_limited(None, notified=False)
        return res

    def _log_usage(self, job: Job, res: RunResult) -> None:
        with self.app.db.session() as s:
            s.add(UsageLog(job_id=job.id, model=res.model, input_tokens=res.input_tokens,
                           output_tokens=res.output_tokens, turns=res.num_turns, duration_ms=res.duration_ms,
                           notional_cost_usd=res.cost_usd, is_error=res.is_error, rate_limited=res.rate_limited))
            s.commit()

    def runs_today(self) -> int:
        tz = self.s.timezone
        start = local_to_utc(to_local(utcnow(), tz).replace(hour=0, minute=0, second=0, microsecond=0))
        with self.app.db.session() as s:
            return int(s.exec(select(func.count(UsageLog.id)).where(col(UsageLog.created_at) >= start)).one())

    def _over_daily_limit(self):  # type: ignore[no-untyped-def]
        n, limit = self.runs_today(), self.s.daily_run_soft_limit
        state = self.app.db.get_state("daily_limit")
        today = local_date(utcnow(), self.s.timezone).isoformat()
        if n >= int(limit * 0.8) and state.get("warned") != today:
            self.app.db.set_state("daily_limit", {"warned": today})
            asyncio.ensure_future(self.app.notifier.notify(
                f"ℹ️ Já usei {n} de {limit} execuções hoje (80%). Tarefas de fundo param no teto; "
                "as suas mensagens continuam a ser respondidas."))
        if n >= limit:
            tz = self.s.timezone
            tomorrow = to_local(utcnow(), tz).replace(hour=0, minute=5, second=0, microsecond=0) + timedelta(days=1)
            return local_to_utc(tomorrow)
        return None

    # ======================= handlers =======================
    async def _main_turn(self, job: Job) -> None:
        p = job.payload_json
        with self.app.db.session() as s:
            conv = s.get(Conversation, p["conversation_id"])
            msg = s.get(Message, p["message_id"])
        tz = self.s.timezone
        today = local_date(utcnow(), tz)
        rotate = conv.main_session_id is None or conv.session_started_at is None or \
            local_date(conv.session_started_at, tz) != today
        prefix = ""
        if rotate and conv.main_session_id is not None:
            prefix = self._rotation_context(conv) + "\n\n"
        prompt = f"{prefix}[{conv.channel} · {to_local(msg.created_at, tz):%d/%m %H:%M}] Lucas: {msg.content}"
        req = RunRequest(prompt=prompt, profile="main", resume_session_id=None if rotate else conv.main_session_id,
                         conversation_id=conv.id, user_request=msg.content)
        self.app.bus.emit("thinking", {"conversation_id": conv.id}, persist=False)
        res = await self._run_agent(job, req)
        if res is None:
            return
        with self.app.db.session() as s:
            c = s.get(Conversation, conv.id)
            if res.session_id:
                if rotate:
                    c.session_started_at = utcnow()
                c.main_session_id = res.session_id
            s.add(c)
            s.commit()
        text = res.text or ("Tive um problema a processar isso: " + res.error if res.is_error else "")
        if text:
            self.store_message(conv.id, "assistant", text, {"job_id": job.id})
            await self.app.notifier.reply(conv.channel, conv.external_chat_id, text)
        self.app.bus.emit("idle", {}, persist=False)

    async def _task_run(self, job: Job) -> None:
        task = self.app.tasks.get(job.task_id)
        event = job.payload_json.get("event")
        if task is None or task.status == "cancelled":
            return
        if task.status in ("done", "failed") and not event:
            return
        if task.session_id is None or not event:
            steps = "\n".join(f"- {x}" for x in (task.plan_json or {}).get("steps", []))
            prompt = (f"Tarefa #{task.id}: {task.title}\nObjetivo: {task.goal}\n"
                      + (f"Plano:\n{steps}\n" if steps else "")
                      + "Faça sozinho o que é seguro (N0/N1); para o que é sensível use propose_action. "
                        "Ao terminar chame task_update(status='done', summary=...). Se depender de terceiros, "
                        "crie uma vigilância e diga quando espera novidades.")
            if event:
                prompt += f"\n\n[evento do sistema] {event}"
        else:
            prompt = f"[evento do sistema] {event}"
        if task.status not in ("running",):
            self.app.tasks.update(task.id, status="running")
        user_req = task.goal
        req = RunRequest(prompt=prompt, profile=task.model_profile or "task", resume_session_id=task.session_id,
                         task_id=task.id, conversation_id=task.origin_conversation_id, user_request=user_req)
        self.app.bus.emit("working", {"task_id": task.id}, task_id=task.id, persist=False)
        res = await self._run_agent(job, req)
        if res is None:
            return
        if res.session_id and res.session_id != task.session_id:
            self.app.tasks.update(task.id, session_id=res.session_id)
        if res.is_error and not res.text:
            self.app.tasks.update(task.id, status="failed", summary=res.error[:500])
            await self.app.notifier.notify(f"❌ Tarefa #{task.id} falhou: {res.error[:300]}", task_id=task.id,
                                           mascot="error")
            return
        t = self.app.tasks.settle_after_run(task.id)
        text = (res.text or "").strip()
        plan = task.plan_json or {}
        if plan.get("max_lines"):
            text = "\n".join(text.splitlines()[: int(plan["max_lines"])])
        if text and text not in ("—", "-") and "notified" not in res.notes and plan.get("notify", True):
            header = f"Tarefa #{task.id} · {t.title}\n" if plan.get("header", True) else ""
            await self.app.notifier.notify(header + text, task_id=task.id)
        if t.status == "done":
            self.app.bus.emit("task_done", {"title": t.title}, task_id=task.id)
        self.app.bus.emit("idle", {}, persist=False)

    async def _schedule_run(self, job: Job) -> None:
        p = job.payload_json
        t = self.app.tasks.create(p.get("title", "Recorrência"), p["prompt"], model_profile="task")
        self.app.tasks.update(t.id, status="running")
        self.app.queue.enqueue("agent.task_run", {"event": None}, task_id=t.id)

    async def _executor_run(self, job: Job) -> None:
        await self.app.executor.run(int(job.payload_json["action_id"]))

    async def _notify_send(self, job: Job) -> None:
        p = job.payload_json
        await self.app.notifier._deliver(p["text"], task_id=p.get("task_id"), silent=False, mascot=p.get("mascot"))

    async def _approval_card(self, job: Job) -> None:
        a = self.app.approvals.get(int(job.payload_json["action_id"]))
        if a is None or a.status != "pending":
            return
        title = ""
        if a.task_id and (t := self.app.tasks.get(a.task_id)):
            title = t.title
        await self.app.notifier.send_card(a, task_title=title)

    # ======================= consultas para comandos =======================
    def open_tasks(self) -> list[Task]:
        return self.app.tasks.list(OPEN_STATUSES)

    def pending_actions(self) -> list[PendingAction]:
        return self.app.approvals.list_pending()
