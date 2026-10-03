"""Gateway: normaliza mensagens, comandos e toques nos cartões de todos os canais (SPEC §3.1, §11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlmodel import col, select

from talos.channels.cards import parse_callback
from talos.clock import local_date, to_local, utcnow
from talos.db.models import InboundLog, PendingAction, Schedule, UsageLog, Watch
from talos.logging import get_logger

if TYPE_CHECKING:
    from talos.orchestrator.core import Orchestrator
    from talos.services import Services

log = get_logger("talos.gateway")

EDIT_STATE = "edit_pending"
HELP = ("Comandos: /tarefas · /aprovacoes · /agenda · /pausar · /retomar · /uso · /tela · /cancelar <id>")


class Gateway:
    def __init__(self, app: Services, orch: Orchestrator) -> None:
        self.app = app
        self.orch = orch
        self.s = app.settings

    # ---------- allowlist ----------
    def allowed(self, channel: str, chat_id: str) -> bool:
        if channel == "app":
            return True  # o app já é autenticado (Tailscale + allowlist + PIN) antes de chegar aqui
        return bool(self.s.telegram_allowed_chat_id) and str(chat_id) == str(self.s.telegram_allowed_chat_id)

    def reject(self, channel: str, chat_id: str, text: str) -> None:
        with self.app.db.session() as s:
            s.add(InboundLog(channel=channel, external_chat_id=str(chat_id), preview=(text or "")[:200]))
            s.commit()
        log.warning("inbound_rejected", channel=channel, chat_id=str(chat_id))

    # ---------- texto ----------
    async def on_text(self, channel: str, chat_id: str, text: str, *, reply_to: str | None = None) -> str | None:
        """Devolve uma resposta imediata (ou None se o agente vai responder)."""
        if not self.allowed(channel, chat_id):
            self.reject(channel, chat_id, text)
            return None
        action_id = self._edit_target(reply_to)
        if action_id is not None:
            res = await self.app.approvals.decide(action_id, "edit", via=channel, note=text)
            self.app.db.set_state(EDIT_STATE, {})
            return res.message
        await self.orch.handle_user_message(channel, str(chat_id), text)
        return None

    def _edit_target(self, reply_to: str | None) -> int | None:
        if reply_to:
            with self.app.db.session() as s:
                for a in s.exec(select(PendingAction).where(PendingAction.status == "pending")):
                    for ref in (a.card_refs_json or {}).get("telegram", []):
                        if str(ref.get("message_id")) == str(reply_to):
                            return a.id
        st = self.app.db.get_state(EDIT_STATE)
        if st.get("action_id"):
            from datetime import datetime

            if (utcnow() - datetime.fromisoformat(st["at"])).total_seconds() < 15 * 60:
                a = self.app.approvals.get(int(st["action_id"]))
                if a and a.status == "pending":
                    return a.id
            self.app.db.set_state(EDIT_STATE, {})
        return None

    # ---------- cartões ----------
    async def on_callback(self, channel: str, chat_id: str, data: str) -> str:
        if not self.allowed(channel, chat_id):
            self.reject(channel, chat_id, f"callback {data}")
            return "Não autorizado."
        parsed = parse_callback(data)
        if parsed is None:
            return "Botão inválido."
        action_id, decision = parsed
        if decision == "edit":
            a = self.app.approvals.get(action_id)
            if a is None or a.status != "pending":
                return "Esta proposta já não está ativa."
            self.app.db.set_state(EDIT_STATE, {"action_id": action_id, "at": utcnow().isoformat()})
            return "O que quer mudar? Escreva a seguir (ou responda ao cartão)."
        res = await self.app.approvals.decide(action_id, decision, via=channel)
        if res.ok and res.action and decision in ("approve", "reject"):
            await self.app.notifier.close_cards(res.action, f"{res.message}\n(proposta #{action_id})")
        return res.message

    # ---------- comandos ----------
    async def on_command(self, channel: str, chat_id: str, command: str, args: list[str]) -> str | None:
        if command == "start" and not self.s.telegram_allowed_chat_id and channel == "telegram":
            log.warning("start_without_allowlist", chat_id=chat_id)
            return (f"Olá! O seu chat_id é {chat_id}. Coloque-o em TELEGRAM_ALLOWED_CHAT_ID no "
                    "/etc/talos/secrets.env e reinicie o Talos.")
        if not self.allowed(channel, chat_id):
            self.reject(channel, chat_id, f"/{command}")
            return None
        fn = getattr(self, f"cmd_{command}", None)
        if fn is None:
            return HELP
        return await fn(channel, chat_id, args)

    async def cmd_start(self, channel: str, chat_id: str, args: list[str]) -> str:
        self.app.bus.emit("greeting", {}, persist=False)
        return f"Olá, Lucas. Sou o {self.s.agent_name}. Pode falar comigo à vontade.\n{HELP}"

    async def cmd_tarefas(self, channel: str, chat_id: str, args: list[str]) -> str:
        tasks = self.orch.open_tasks()
        if not tasks:
            return "Nenhuma tarefa aberta."
        names = {"planning": "planejando", "running": "em andamento", "waiting_approval": "aguardando você",
                 "waiting_external": "aguardando terceiros", "scheduled": "agendada"}
        return "\n".join(f"#{t.id} · {t.title} — {names.get(t.status, t.status)}" for t in tasks)

    async def cmd_aprovacoes(self, channel: str, chat_id: str, args: list[str]) -> str:
        pend = self.orch.pending_actions()
        if not pend:
            return "Nenhuma aprovação pendente."
        for a in pend:
            self.app.queue.enqueue("approval.card", {"action_id": a.id}, dedupe_key=f"card:{a.id}")
        return f"{len(pend)} aprovação(ões) pendente(s); reenviei os cartões."

    async def cmd_agenda(self, channel: str, chat_id: str, args: list[str]) -> str:
        tz = self.s.timezone
        with self.app.db.session() as s:
            watches = list(s.exec(select(Watch).where(Watch.status == "active").order_by(col(Watch.next_check_at))))
            schedules = list(s.exec(select(Schedule).where(Schedule.enabled == True)  # noqa: E712
                                    .order_by(col(Schedule.next_run_at))))
        lines = []
        for w in watches:
            when = to_local(w.next_check_at, tz).strftime("%d/%m %H:%M") if w.next_check_at else "?"
            lines.append(f"👀 vigilância #{w.id} (tarefa #{w.task_id}) · follow-up em {when}")
        for sc in schedules:
            when = to_local(sc.next_run_at, tz).strftime("%d/%m %H:%M") if sc.next_run_at else "?"
            lines.append(f"🔁 {sc.kind} #{sc.id} · próxima {when}")
        return "\n".join(lines) or "Agenda vazia."

    async def cmd_pausar(self, channel: str, chat_id: str, args: list[str]) -> str:
        changed = await self.orch.pause(by=channel)
        return "⏸️ Pausado. Nada roda nem é executado até /retomar." if changed else "Já estava pausado."

    async def cmd_retomar(self, channel: str, chat_id: str, args: list[str]) -> str:
        changed = await self.orch.resume(by=channel)
        return "▶️ De volta ao trabalho." if changed else "Não estava pausado."

    async def cmd_uso(self, channel: str, chat_id: str, args: list[str]) -> str:
        today = local_date(utcnow(), self.s.timezone)
        with self.app.db.session() as s:
            rows = list(s.exec(select(UsageLog).order_by(col(UsageLog.id).desc()).limit(500)))
        todays = [r for r in rows if local_date(r.created_at, self.s.timezone) == today]
        cost = sum(r.notional_cost_usd for r in todays)
        rl = self.app.control.rate_limited_until()
        return (f"Modo: {self.s.auth_mode} · hoje: {len(todays)}/{self.s.daily_run_soft_limit} execuções, "
                f"{sum(r.turns for r in todays)} turnos, custo equivalente ~US$ {cost:.2f} (informativo)"
                + (f"\nLimite da assinatura até {rl}" if rl else ""))

    async def cmd_tela(self, channel: str, chat_id: str, args: list[str]) -> str:
        url = self.app.db.get_state("app").get("url", "")
        return f"Tela do {self.s.agent_name}: {url}/tela" if url else "O app ainda não tem URL configurada."

    async def cmd_cancelar(self, channel: str, chat_id: str, args: list[str]) -> str:
        if not args or not args[0].lstrip("#").isdigit():
            return "Uso: /cancelar <id da tarefa>"
        tid = int(args[0].lstrip("#"))
        t = self.app.tasks.get(tid)
        if t is None:
            return f"Tarefa #{tid} não existe."
        self.app.tasks.update(tid, status="cancelled")
        with self.app.db.session() as s:
            for w in s.exec(select(Watch).where(Watch.task_id == tid, Watch.status == "active")):
                w.status = "cancelled"
                s.add(w)
            s.commit()
        for a in self.app.approvals.list_pending():
            if a.task_id == tid:
                self.app.approvals._transition(a.id, ("pending",), "rejected", decided_at=utcnow(),
                                               decided_via=channel, decision_note="tarefa cancelada")
        return f"Tarefa #{tid} cancelada (vigilâncias e propostas pendentes também)."
