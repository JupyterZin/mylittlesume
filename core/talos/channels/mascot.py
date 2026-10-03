"""Estados do mascote (SPEC §9.3), derivados de forma determinística dos eventos do bus.

O app só desenha: quem decide o estado é este mapeador, no servidor, a partir dos mesmos
eventos que alimentam a trilha de auditoria. Há dois tipos de estado:

- **contínuos** (loop): idle, typing, thinking, working, long_task, waiting_approval,
  quiet_hours, paused — o "estado de base", recalculado a cada evento;
- **reações** (uma vez): greeting, approved, rejected, reply, milestone, error, blocked —
  o app toca a animação uma vez e volta ao estado de base que vem no mesmo payload (`base`).

`typing` (o Lucas a escrever) é local do app; o servidor nunca o emite, mas faz parte do
vocabulário partilhado.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from talos.clock import local_date, utcnow

STATES = (
    "idle", "greeting", "typing", "thinking", "working", "long_task", "waiting_approval", "approved",
    "rejected", "reply", "milestone", "error", "blocked", "quiet_hours", "paused",
)
LOOP_STATES = frozenset({"idle", "typing", "thinking", "working", "long_task", "waiting_approval",
                         "quiet_hours", "paused"})
ONCE_STATES = frozenset(STATES) - LOOP_STATES

# dicas que o notifier já manda em `message.payload.mascot`
MESSAGE_HINTS = {"approved": "approved", "error": "error", "blocked": "blocked", "reply": "reply"}

LONG_TASK_AFTER = timedelta(seconds=90)   # trabalho contínuo há mais do que isto → Running
STALE_AFTER = timedelta(minutes=10)       # sem sinal de vida → deixa de estar "a trabalhar"
DEDUPE_WINDOW = timedelta(seconds=10)     # a mesma reação duas vezes seguidas conta uma

# frase curta (pt-BR) para a linha de estado, pela ferramenta em uso
TOOL_PHRASES: tuple[tuple[str, str], ...] = (
    ("mcp__playwright__browser_", "Navegando"),
    ("WebSearch", "Pesquisando na web"),
    ("WebFetch", "Lendo uma página"),
    ("mcp__talos__gmail_create_draft", "Escrevendo um rascunho"),
    ("mcp__talos__gmail_update_draft", "Ajustando o rascunho"),
    ("mcp__talos__gmail_", "Lendo emails"),
    ("mcp__talos__calendar_", "Olhando a agenda"),
    ("mcp__talos__drive_", "Procurando no Drive"),
    ("mcp__talos__contacts_", "Verificando contatos"),
    ("mcp__talos__memory_", "Consultando a memória"),
    ("mcp__talos__propose_action", "Preparando uma proposta"),
    ("mcp__talos__watch_", "Combinando um acompanhamento"),
    ("mcp__talos__schedule_", "Agendando"),
    ("mcp__talos__vault_fill", "Preenchendo um formulário"),
    ("mcp__talos__task_", "Organizando a tarefa"),
    ("mcp__talos__notify_user", "Escrevendo para você"),
)


def tool_phrase(tool: str | None) -> str:
    for prefix, phrase in TOOL_PHRASES:
        if tool and tool.startswith(prefix):
            return phrase
    return "Trabalhando"


@dataclass
class MascotContext:
    """Tudo o que o mapeador consulta fora dos eventos (injetável nos testes)."""

    paused: Callable[[], bool]
    pending: Callable[[], int]
    quiet: Callable[[datetime], bool]
    takeover: Callable[[], bool] = lambda: False
    task_title: Callable[[int], str | None] = lambda _id: None
    quiet_until: Callable[[], str] = lambda: ""
    clock: Callable[[], datetime] = utcnow
    tz: str = "Europe/Lisbon"


class MascotMapper:
    def __init__(self, ctx: MascotContext) -> None:
        self.ctx = ctx
        self._activity: str | None = None  # thinking | working
        self._since: datetime | None = None
        self._last_seen: datetime | None = None
        self._task_id: int | None = None
        self._tool: str | None = None
        self._urgent = False
        self._last_once: tuple[str, str | None, datetime] | None = None
        self._milestone_day: date | None = None
        self._last: dict[str, Any] | None = None

    # ------------------------------------------------------------------ API
    def snapshot(self) -> dict[str, Any]:
        """Estado contínuo atual (para `/api/state` e para quem acaba de ligar o WebSocket)."""
        now = self.ctx.clock()
        base = self._base(now)
        return self._payload(base, now, once=False, base=base)

    def feed(self, event: dict[str, Any]) -> dict[str, Any] | None:
        """Processa um evento do bus. Devolve o novo estado se mudou (ou uma reação), senão None."""
        now = self.ctx.clock()
        if self._last is None:  # referência: o que um cliente recém-ligado já recebeu
            before = self._base(now)
            self._last = self._payload(before, now, once=False, base=before)
        once = self._apply(event, now)
        base = self._base(now)
        if once is not None:
            state, gesture, extra = once
            if self._last_once and self._last_once[:2] == (state, gesture) and \
                    now - self._last_once[2] < DEDUPE_WINDOW:
                once = None
            else:
                self._last_once = (state, gesture, now)
                out = self._payload(state, now, once=True, base=base, gesture=gesture, extra=extra,
                                    task_id=event.get("task_id"))
                self._last = self._payload(base, now, once=False, base=base)
                return out
        out = self._payload(base, now, once=False, base=base)
        key = ("state", "status", "task_id")
        if self._last is not None and all(self._last.get(k) == out.get(k) for k in key):
            return None
        self._last = out
        return out

    # ------------------------------------------------------------- internos
    def _apply(self, ev: dict[str, Any], now: datetime) -> tuple[str, str | None, dict[str, Any]] | None:
        """Atualiza a atividade; devolve (reação, gesto, extra) se o evento pede uma."""
        t = ev.get("type", "")
        p = ev.get("payload") or {}
        tid = ev.get("task_id")

        if t == "thinking":
            if self._activity != "working":
                self._start("thinking", now, tid)
            return None
        if t == "run_started":
            self._start("working" if tid is not None else (self._activity or "thinking"), now, tid)
            return None
        if t in ("working", "tool_call"):
            self._start("working", now, tid if tid is not None else self._task_id)
            if t == "tool_call":
                self._tool = p.get("tool")
            if p.get("urgent"):
                self._urgent = True
            return None
        if t == "idle":
            self._stop()
            return None
        if t in ("paused", "takeover_started"):
            self._stop()
            return None

        if t == "greeting":
            return "greeting", None, {}
        if t == "approval_decided":
            decision = p.get("decision")
            if decision == "approved":
                return "approved", "Yes", {}
            if decision in ("rejected", "expired"):
                return "rejected", None, {"decision": decision}
            return None
        if t == "action_executed":
            return "approved", None, {}
        if t in ("action_failed", "job_failed"):
            if t == "job_failed":
                self._stop()
            return "error", None, {}
        if t == "sentinel_decision":
            if p.get("decision") in ("deny", "takeover"):
                return "blocked", None, {"tool": p.get("tool")}
            self._touch(now)
            return None
        if t in ("takeover_requested", "suspicious_content"):
            return "blocked", None, {}
        if t == "task_status":
            if p.get("to") == "cancelled":
                return "rejected", None, {}
            if p.get("to") == "failed":
                return "error", None, {}
            return None
        if t in ("task_done", "goal_done", "milestone"):
            today = local_date(now, self.ctx.tz)
            if t == "task_done" and self._milestone_day == today:
                return "approved", None, {}  # Dance no máximo 1× por dia; depois, polegar para cima
            self._milestone_day = today
            return "milestone", None, {"title": p.get("title", "")}
        if t == "message":
            hint = MESSAGE_HINTS.get(str(p.get("mascot") or ""))
            return (hint, None, {}) if hint else None

        # qualquer outro sinal de uma execução em curso conta como "ainda vivo"
        if self._activity and t in ("draft_created", "note", "triage", "approval_created", "reply_received"):
            self._touch(now)
        return None

    def _start(self, activity: str, now: datetime, task_id: int | None) -> None:
        if self._activity != activity or self._since is None or self._is_stale(now):
            self._since = now
            self._urgent = False
            self._tool = None
        self._activity = activity
        self._task_id = task_id
        self._last_seen = now

    def _touch(self, now: datetime) -> None:
        self._last_seen = now

    def _stop(self) -> None:
        self._activity, self._since, self._last_seen = None, None, None
        self._task_id, self._tool, self._urgent = None, None, False

    def _is_stale(self, now: datetime) -> bool:
        return self._last_seen is not None and now - self._last_seen > STALE_AFTER

    def _base(self, now: datetime) -> str:
        if self.ctx.paused():
            return "paused"
        activity = None if self._is_stale(now) else self._activity
        if activity == "working":
            long = self._urgent or (self._since is not None and now - self._since >= LONG_TASK_AFTER)
            return "long_task" if long else "working"
        if activity == "thinking":
            return "thinking"
        if self.ctx.pending() > 0:
            return "waiting_approval"
        if self.ctx.quiet(now):
            return "quiet_hours"
        return "idle"

    def _payload(self, state: str, now: datetime, *, once: bool, base: str, gesture: str | None = None,
                 extra: dict[str, Any] | None = None, task_id: int | None = None) -> dict[str, Any]:
        tid = task_id if once else (self._task_id if state in ("working", "long_task", "thinking") else None)
        return {
            "state": state,
            "once": once,
            "base": base,
            "gesture": gesture,
            "status": self._status(state, gesture, extra or {}, tid),
            "task_id": tid,
            "at": now.isoformat(),
        }

    def _status(self, state: str, gesture: str | None, extra: dict[str, Any], task_id: int | None) -> str:
        title = self._title(task_id)
        if state in ("working", "long_task"):
            phrase = tool_phrase(self._tool)
            return f"{phrase} · {title}" if title else f"{phrase}…"
        if state == "thinking":
            return f"Pensando · {title}" if title else "Pensando…"
        if state == "waiting_approval":
            n = self.ctx.pending()
            return "Esperando a sua aprovação" if n == 1 else f"Esperando a sua aprovação ({n})"
        if state == "quiet_hours":
            until = self.ctx.quiet_until()
            return f"Horas de silêncio até {until}" if until else "Horas de silêncio"
        if state == "paused":
            return "Pausado. Nada roda até você retomar."
        if state == "idle":
            return "Você está no controle da Tela." if self.ctx.takeover() else "Pronto quando você quiser."
        if state == "greeting":
            return "Olá, Lucas!"
        if state == "approved":
            if gesture == "Yes":
                return "Aprovado. Executando…"
            return f"Feito · {title}" if title else "Feito."
        if state == "rejected":
            return "Expirou sem resposta. Não fiz nada." if extra.get("decision") == "expired" \
                else "Combinado, não vou fazer isso."
        if state == "reply":
            return "Chegou uma resposta."
        if state == "milestone":
            name = extra.get("title") or title
            return f"Concluído · {name}" if name else "Concluído!"
        if state == "error":
            return "Algo deu errado. Veja os detalhes na conversa."
        if state == "blocked":
            return "Bloqueei uma ação por segurança."
        return ""

    def _title(self, task_id: int | None) -> str:
        if task_id is None:
            return ""
        try:
            return (self.ctx.task_title(task_id) or "").strip()
        except Exception:
            return ""

