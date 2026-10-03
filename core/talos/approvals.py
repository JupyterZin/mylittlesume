"""Máquina de estados das propostas (SPEC §7.2).

pending → approved → executing → executed | failed
        → rejected | superseded | expired
Todas as transições são `UPDATE … WHERE status=<esperado>` atômicos: toque duplo, cartões
antigos e corridas entre Telegram e app resolvem-se no banco.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import update
from sqlmodel import col, select

from talos.clock import utcnow
from talos.connectors.mime import addresses
from talos.db.engine import Database
from talos.db.models import ACTION_KINDS, Message, PendingAction, Task
from talos.events import EventBus
from talos.logging import get_logger
from talos.scheduler.jobs import JobQueue
from talos.sentinel import egress
from talos.vault.placeholders import find_forbidden, find_keys, label

if TYPE_CHECKING:
    from talos.channels.notifier import Notifier
    from talos.config import Settings
    from talos.connectors.gmail import GmailAPI
    from talos.control import Control
    from talos.memory.facts import ContactService
    from talos.tasks import TaskService
    from talos.vault.store import Vault

log = get_logger("talos.approvals")

EMAIL_KINDS = ("email.send", "email.reply")
SYNC_KINDS = ("browser.submit", "purchase", "booking", "share_data")


class ProposalError(ValueError):
    pass


@dataclass
class DecideResult:
    ok: bool
    message: str
    action: PendingAction | None = None


class Approvals:
    def __init__(self, *, settings: Settings, db: Database, bus: EventBus, queue: JobQueue,
                 tasks: TaskService, contacts: ContactService, vault: Vault, control: Control,
                 gmail: GmailAPI | None = None, notifier: Notifier | None = None) -> None:
        self.s = settings
        self.db = db
        self.bus = bus
        self.queue = queue
        self.tasks = tasks
        self.contacts = contacts
        self.vault = vault
        self.control = control
        self.gmail = gmail
        self.notifier = notifier
        self._waiters: dict[int, asyncio.Future[str]] = {}
        self.on_grant: Any = None  # callback(fingerprint) para concessões da Sentinela

    # ================= criação =================
    def create(self, *, task_id: int | None, kind: str, payload: dict[str, Any], preview: str = "",
               reason: str = "", ttl: timedelta | None = None) -> PendingAction:
        if kind not in ACTION_KINDS:
            raise ProposalError(f"tipo de ação desconhecido: {kind}")
        payload = dict(payload)
        risk, why = "baixo", []

        if kind in EMAIL_KINDS:
            payload, r, w = self._prepare_email(payload, task_id)
            risk, why = _max_risk(risk, r), why + w
        elif kind == "calendar.invite":
            statuses = [self._known_address(a, task_id, None) for a in payload.get("attendees", [])]
            payload["_recipients"] = [{"address": a, "status": st, "source_url": src}
                                      for a, (st, src) in zip(payload.get("attendees", []), statuses, strict=True)]
            if any(st == "novo" for st, _ in statuses):
                risk, why = "alto", why + ["convidado novo"]
            else:
                risk = "medio"
        elif kind == "email.organize":
            risk = "baixo"  # só rótulos e arquivo, reversível com /desfazer_organizacao
        else:
            risk = "medio" if kind in SYNC_KINDS else "alto"

        texts = " ".join(str(payload.get(k, "")) for k in ("subject", "body", "summary"))
        if forbidden := find_forbidden(texts):
            raise ProposalError(f"placeholders proibidos (segredos nunca saem): {', '.join(forbidden)}")
        keys = sorted(set(find_keys(texts)) | set(payload.get("_data_keys", [])))
        missing = [k for k in keys if self.vault.get(k) is None]
        if missing:
            raise ProposalError(f"chaves inexistentes no cofre: {', '.join(missing)} (use vault_list_keys)")
        payload["_data_keys"] = keys
        if keys:
            risk = _max_risk(risk, "medio")
        raw = [h for h in egress.scan_text(texts, self.vault.personal_values())]
        if raw:
            payload["_raw_personal"] = sorted({h.describe() for h in raw})
            risk, why = "alto", why + ["dados pessoais por extenso"]
        payload["_risk_why"] = ", ".join(dict.fromkeys(why))

        with self.db.session() as s:
            action = PendingAction(
                task_id=task_id, kind=kind, payload_json=payload, preview_text=preview[:8000],
                risk=risk, reason=reason[:500], idempotency_key=uuid.uuid4().hex,
                expires_at=utcnow() + (ttl or timedelta(hours=self.s.approval_ttl_hours)),
            )
            s.add(action)
            s.commit()
            s.refresh(action)
            # proposta nova substitui a que o Lucas pediu para editar
            if task_id is not None:
                for old in s.exec(select(PendingAction).where(
                        PendingAction.task_id == task_id, PendingAction.status == "superseded",
                        col(PendingAction.superseded_by).is_(None), PendingAction.id != action.id)):
                    old.superseded_by = action.id
                    s.add(old)
                s.commit()
        if task_id is not None:
            self.tasks.update(task_id, status="waiting_approval")
        self.bus.emit("approval_created", {"action_id": action.id, "kind": kind, "risk": risk}, task_id=task_id)
        return action

    def _prepare_email(self, p: dict[str, Any], task_id: int | None) -> tuple[dict[str, Any], str, list[str]]:
        to = _as_list(p.get("to"))
        cc = _as_list(p.get("cc"))
        if not to:
            raise ProposalError("email sem destinatário")
        if not p.get("subject") or not p.get("body"):
            raise ProposalError("email precisa de assunto e corpo")
        p["to"], p["cc"] = to, cc
        thread_participants: set[str] = set()
        if p.get("thread_id") and self.gmail:
            try:
                th = self.gmail.get_thread(p["thread_id"])
                for m in th["messages"]:
                    for h in ("from", "to", "cc", "reply_to"):
                        thread_participants.update(addresses(m.get(h)))
            except Exception as e:
                log.warning("thread_lookup_failed", error=str(e))
        recips, risk, why = [], "baixo", []
        for addr in to + cc:
            status, src = self._known_address(addr, task_id, thread_participants)
            recips.append({"address": addr, "status": status, "source_url": src})
            if status == "novo":
                risk, why = "alto", why + ["destinatário novo"]
            elif status == "contato_oficial" and not thread_participants:
                risk = _max_risk(risk, "medio")
                why.append("primeiro contato com este destinatário")
        p["_recipients"] = recips
        return p, risk, why

    def _known_address(self, addr: str, task_id: int | None, participants: set[str] | None) -> tuple[str, str]:
        a = addr.lower().strip()
        if participants and a in participants:
            return "participante", ""
        c = self.contacts.by_email(a)
        if c and c.source_url:
            return "contato_oficial", c.source_url
        if self._provided_by_lucas(a, task_id):
            return "fornecido", ""
        return "novo", ""

    def _provided_by_lucas(self, addr: str, task_id: int | None) -> bool:
        with self.db.session() as s:
            hit = s.exec(select(Message.id).where(Message.role == "user",
                                                  col(Message.content).ilike(f"%{addr}%"))).first()
            if hit:
                return True
            if task_id is not None:
                t = s.get(Task, task_id)
                if t and addr in (t.goal or "").lower():
                    return True
        return False

    # ================= decisões =================
    def _transition(self, action_id: int, frm: tuple[str, ...], to: str, **fields: Any) -> bool:
        with self.db.engine.begin() as conn:
            res = conn.execute(
                update(PendingAction).where(col(PendingAction.id) == action_id,
                                            col(PendingAction.status).in_(frm))
                .values(status=to, **fields)
            )
            return (res.rowcount or 0) == 1

    def get(self, action_id: int) -> PendingAction | None:
        with self.db.session() as s:
            return s.get(PendingAction, action_id)

    def list_pending(self) -> list[PendingAction]:
        with self.db.session() as s:
            return list(s.exec(select(PendingAction).where(PendingAction.status == "pending")
                               .order_by(PendingAction.id)))

    async def decide(self, action_id: int, decision: str, *, via: str, note: str = "") -> DecideResult:
        action = self.get(action_id)
        if action is None:
            return DecideResult(False, "Proposta não encontrada.")
        if action.status != "pending":
            return DecideResult(False, f"Esta proposta já não está ativa ({_status_pt(action.status)}).", action)
        if self.control.is_paused() and decision == "approve":
            return DecideResult(False, "O Talos está pausado. Use /retomar antes de aprovar.", action)

        now = utcnow()
        if decision == "approve":
            if not self._transition(action_id, ("pending",), "approved", decided_at=now, decided_via=via):
                return DecideResult(False, "Esta proposta já não está ativa.", self.get(action_id))
            action = self.get(action_id)
            if action.task_id and action.payload_json.get("_data_keys"):
                self.tasks.authorize_data(action.task_id, action.payload_json["_data_keys"])
            self.bus.emit("approval_decided", {"action_id": action_id, "decision": "approved", "via": via},
                          task_id=action.task_id)
            if action.kind in SYNC_KINDS and action_id in self._waiters:
                self._resolve_waiter(action_id, "approved")
            elif action.kind in SYNC_KINDS:
                # a pausa síncrona já expirou: concede a ação exata e retoma a sessão
                fp = action.payload_json.get("_fingerprint")
                if fp and self.on_grant:
                    self.on_grant(fp)
                self._transition(action_id, ("approved",), "executed", executed_at=now,
                                 result_json={"granted": True})
                self._resume(action, f"O Lucas APROVOU a proposta #{action_id}. Repita exatamente a ação "
                                     "que foi pausada; ela agora passa.")
            else:
                self.queue.enqueue("executor.run", {"action_id": action_id}, task_id=None,
                                   dedupe_key=f"exec:{action_id}", priority=10)
            return DecideResult(True, "Aprovado ✓ — executando.", action)

        if decision == "reject":
            if not self._transition(action_id, ("pending",), "rejected", decided_at=now, decided_via=via,
                                    decision_note=note[:1000]):
                return DecideResult(False, "Esta proposta já não está ativa.", self.get(action_id))
            action = self.get(action_id)
            self._resolve_waiter(action_id, "rejected")
            self.bus.emit("approval_decided", {"action_id": action_id, "decision": "rejected", "via": via},
                          task_id=action.task_id)
            self._resume(action, f"O Lucas RECUSOU a proposta #{action_id}."
                                 + (f" Motivo: {note}" if note else " Sem motivo indicado.")
                                 + " Não execute nada disto. Pergunte o que fazer se não estiver claro.")
            return DecideResult(True, "Recusado. Nada foi enviado.", action)

        if decision == "edit":
            if not note.strip():
                return DecideResult(True, "O que quer mudar? Responda a esta mensagem com o pedido.", action)
            if not self._transition(action_id, ("pending",), "superseded", decided_at=now, decided_via=via,
                                    decision_note=note[:2000]):
                return DecideResult(False, "Esta proposta já não está ativa.", self.get(action_id))
            action = self.get(action_id)
            self._resolve_waiter(action_id, "superseded")
            self.bus.emit("approval_decided", {"action_id": action_id, "decision": "edit", "via": via},
                          task_id=action.task_id)
            self._resume(action, f"O Lucas pediu ALTERAÇÕES na proposta #{action_id}: «{note}». "
                                 "Faça as alterações (atualize o rascunho) e crie uma proposta NOVA com propose_action.")
            return DecideResult(True, "Ok, vou refazer a proposta com essas mudanças.", action)

        if decision == "later":
            self.queue.enqueue("approval.card", {"action_id": action_id}, run_after=now + timedelta(hours=2),
                               dedupe_key=f"card:{action_id}")
            return DecideResult(True, "Ok, lembro de novo daqui a 2 horas.", action)

        return DecideResult(False, f"Decisão desconhecida: {decision}", action)

    def _resume(self, action: PendingAction, message: str) -> None:
        from talos.resume import resume_work

        resume_work(queue=self.queue, tasks=self.tasks, db=self.db, task_id=action.task_id,
                    conversation_id=(action.payload_json or {}).get("_conversation_id"), event=message)

    # ================= pausa síncrona (navegador) =================
    def expect(self, action_id: int) -> asyncio.Future[str]:
        """Regista quem espera pela decisão ANTES de o cartão sair: uma decisão rápida (enquanto o
        cartão ou o screenshot ainda estão a ser enviados) chega sempre a este waiter, em vez de cair no
        caminho "pausa já expirou" (que concederia a ação e retomaria a tarefa → ação em dobro)."""
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._waiters[action_id] = fut
        return fut

    async def wait_for(self, action_id: int, timeout: float, fut: asyncio.Future[str] | None = None) -> str:
        fut = fut or self.expect(action_id)
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout)
        except TimeoutError:
            return "timeout"
        finally:
            self._waiters.pop(action_id, None)

    def _resolve_waiter(self, action_id: int, status: str) -> None:
        fut = self._waiters.get(action_id)
        if fut and not fut.done():
            fut.set_result(status)

    def mark_executed(self, action_id: int, result: dict[str, Any]) -> None:
        self._transition(action_id, ("approved", "executing"), "executed", executed_at=utcnow(), result_json=result)

    # ================= varredura =================
    def sweep(self) -> dict[str, list[int]]:
        """Expira propostas vencidas e devolve as que precisam de lembrete (24 h)."""
        now = utcnow()
        expired, remind = [], []
        for a in self.list_pending():
            if a.expires_at and _aware(a.expires_at) <= now:
                if self._transition(a.id, ("pending",), "expired", decided_at=now, decided_via="sistema"):
                    expired.append(a.id)
                    self._resolve_waiter(a.id, "expired")
                    self.bus.emit("approval_decided", {"action_id": a.id, "decision": "expired"}, task_id=a.task_id)
                    if a.task_id:
                        self._resume(self.get(a.id), f"A proposta #{a.id} EXPIROU sem resposta do Lucas. "
                                                     "Não execute. Decida se vale propor de novo.")
            elif a.reminded_at is None and a.created_at and \
                    now - _aware(a.created_at) >= timedelta(hours=self.s.approval_reminder_hours):
                with self.db.session() as s:
                    row = s.get(PendingAction, a.id)
                    row.reminded_at = now
                    s.add(row)
                    s.commit()
                remind.append(a.id)
        return {"expired": expired, "remind": remind}


def _aware(dt: Any) -> Any:
    from talos.clock import as_utc

    return as_utc(dt)


def _as_list(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


_RISK_ORDER = {"baixo": 0, "medio": 1, "alto": 2}


def _max_risk(a: str, b: str) -> str:
    return a if _RISK_ORDER[a] >= _RISK_ORDER[b] else b


def _status_pt(status: str) -> str:
    return {"approved": "aprovada", "executing": "em execução", "executed": "executada", "rejected": "recusada",
            "superseded": "substituída", "expired": "expirada", "failed": "falhou"}.get(status, status)


def describe_keys(keys: list[str]) -> str:
    return ", ".join(label(k) for k in keys)
