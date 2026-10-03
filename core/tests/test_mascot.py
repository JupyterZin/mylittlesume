"""Mapeador determinístico eventos do bus → estados do mascote (SPEC §9.3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from talos.channels.mascot import LOOP_STATES, ONCE_STATES, STATES, MascotContext, MascotMapper, tool_phrase

NOON = datetime(2026, 10, 7, 11, 0, tzinfo=UTC)  # meio-dia em Lisboa


class World:
    def __init__(self) -> None:
        self.now = NOON
        self.paused = False
        self.pending = 0
        self.quiet = False
        self.takeover = False
        self.titles = {7: "Ligar o gás em casa"}

    def mapper(self) -> MascotMapper:
        return MascotMapper(MascotContext(
            paused=lambda: self.paused, pending=lambda: self.pending, quiet=lambda _now: self.quiet,
            takeover=lambda: self.takeover, task_title=self.titles.get, quiet_until=lambda: "08:00",
            clock=lambda: self.now, tz="Europe/Lisbon",
        ))

    def tick(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def ev(type_: str, task_id: int | None = None, **payload: Any) -> dict[str, Any]:
    return {"type": type_, "task_id": task_id, "payload": payload}


@pytest.fixture
def w() -> World:
    return World()


def test_vocabulary_is_the_spec_table() -> None:
    assert len(STATES) == 15
    assert LOOP_STATES | ONCE_STATES == set(STATES)
    assert not LOOP_STATES & ONCE_STATES


def test_idle_snapshot(w: World) -> None:
    snap = w.mapper().snapshot()
    assert snap["state"] == "idle" and snap["once"] is False and snap["base"] == "idle"
    assert snap["status"] == "Pronto quando você quiser."


def test_thinking_then_idle(w: World) -> None:
    m = w.mapper()
    out = m.feed(ev("thinking"))
    assert out["state"] == "thinking" and out["status"] == "Pensando…"
    assert m.feed(ev("run_started", profile="main")) is None  # nada mudou
    assert m.feed(ev("idle"))["state"] == "idle"


def test_working_status_uses_tool_and_task_title(w: World) -> None:
    m = w.mapper()
    out = m.feed(ev("working", 7))
    assert out["state"] == "working" and out["task_id"] == 7
    out = m.feed(ev("tool_call", 7, tool="mcp__playwright__browser_navigate"))
    assert out["status"] == "Navegando · Ligar o gás em casa"
    assert m.feed(ev("tool_call", 7, tool="mcp__playwright__browser_click")) is None


def test_long_task_after_sustained_work(w: World) -> None:
    m = w.mapper()
    m.feed(ev("working", 7))
    w.tick(60)
    assert m.feed(ev("tool_call", 7, tool="WebSearch"))["state"] == "working"
    w.tick(40)
    assert m.feed(ev("tool_call", 7, tool="WebFetch"))["state"] == "long_task"


def test_urgent_work_is_long_task_immediately(w: World) -> None:
    assert w.mapper().feed(ev("working", 7, urgent=True))["state"] == "long_task"


def test_waiting_approval_when_idle_with_pending(w: World) -> None:
    m = w.mapper()
    m.feed(ev("working", 7))
    w.pending = 2
    assert m.feed(ev("approval_created", 7, action_id=1, kind="email.send")) is None  # ainda a trabalhar
    out = m.feed(ev("idle"))
    assert out["state"] == "waiting_approval" and out["status"] == "Esperando a sua aprovação (2)"


def test_quiet_hours_and_priority(w: World) -> None:
    m = w.mapper()
    w.quiet = True
    assert m.snapshot()["state"] == "quiet_hours"
    assert m.snapshot()["status"] == "Horas de silêncio até 08:00"
    w.pending = 1
    assert m.snapshot()["state"] == "waiting_approval"  # app aberto à noite: a aprovação vence


def test_paused_wins_over_everything(w: World) -> None:
    m = w.mapper()
    m.feed(ev("working", 7))
    w.paused, w.pending, w.quiet = True, 3, True
    out = m.feed(ev("paused", by="app"))
    assert out["state"] == "paused" and out["status"].startswith("Pausado")
    w.paused = False
    assert m.feed(ev("resumed", by="app"))["state"] == "waiting_approval"


def test_approval_yes_then_thumbs_up_and_dedupe(w: World) -> None:
    m = w.mapper()
    w.pending = 1
    m.feed(ev("approval_created", 7, action_id=1))
    w.pending = 0
    out = m.feed(ev("approval_decided", 7, action_id=1, decision="approved", via="app"))
    assert out["state"] == "approved" and out["once"] and out["gesture"] == "Yes" and out["base"] == "idle"
    w.tick(2)
    out = m.feed(ev("action_executed", 7, action_id=1, kind="email.send"))
    assert out["state"] == "approved" and out["gesture"] is None
    assert out["status"] == "Feito · Ligar o gás em casa"
    w.tick(1)
    # o notifier manda logo a seguir uma mensagem com a dica "approved": não repete o gesto
    assert m.feed(ev("message", 7, role="assistant", content="Enviado", mascot="approved")) is None
    w.tick(30)
    assert m.feed(ev("message", 7, role="assistant", content="x", mascot="approved"))["state"] == "approved"


@pytest.mark.parametrize("decision", ["rejected", "expired"])
def test_rejected(w: World, decision: str) -> None:
    out = w.mapper().feed(ev("approval_decided", 7, action_id=1, decision=decision))
    assert out["state"] == "rejected" and out["once"]


def test_edit_is_not_a_rejection(w: World) -> None:
    m = w.mapper()
    w.pending = 1
    m.feed(ev("approval_created", 7))
    w.pending = 0
    assert m.feed(ev("approval_decided", 7, action_id=1, decision="edit"))["state"] == "idle"


def test_cancelled_and_failed_tasks(w: World) -> None:
    m = w.mapper()
    assert m.feed(ev("task_status", 7, to="cancelled", **{"from": "running"}))["state"] == "rejected"
    assert m.feed(ev("task_status", 7, to="failed", **{"from": "running"}))["state"] == "error"
    assert m.feed(ev("task_status", 7, to="waiting_external", **{"from": "running"})) is None


def test_milestone_once_per_local_day(w: World) -> None:
    m = w.mapper()
    out = m.feed(ev("task_done", 7, title="Ligar o gás em casa"))
    assert out["state"] == "milestone" and out["status"] == "Concluído · Ligar o gás em casa"
    w.tick(3600)
    assert m.feed(ev("task_done", 8, title="Outra"))["state"] == "approved"
    w.tick(24 * 3600)
    assert m.feed(ev("task_done", 9, title="Amanhã"))["state"] == "milestone"


def test_errors_stop_activity(w: World) -> None:
    m = w.mapper()
    m.feed(ev("working", 7))
    out = m.feed(ev("job_failed", 7, job_id=3, kind="agent.task_run", error="boom"))
    assert out["state"] == "error" and out["base"] == "idle"
    assert m.snapshot()["state"] == "idle"
    w.tick(20)
    assert m.feed(ev("action_failed", 7, action_id=2, error="x"))["state"] == "error"


def test_blocked_by_sentinel_only_on_deny_or_takeover(w: World) -> None:
    m = w.mapper()
    assert m.feed(ev("sentinel_decision", 7, tool="Bash", decision="allow")) is None
    out = m.feed(ev("sentinel_decision", 7, tool="Bash", decision="deny", reason="proibido"))
    assert out["state"] == "blocked"
    w.tick(30)
    assert m.feed(ev("takeover_requested", 7, tool="browser_type"))["state"] == "blocked"
    w.tick(30)
    assert m.feed(ev("suspicious_content", 7, origin="email:1"))["state"] == "blocked"


def test_reply_and_greeting(w: World) -> None:
    m = w.mapper()
    assert m.feed(ev("greeting"))["state"] == "greeting"
    assert m.feed(ev("reply_received", 7, message_id="m1")) is None  # a reação vem com o resumo
    assert m.feed(ev("message", 7, role="assistant", content="Respondeu", mascot="reply"))["state"] == "reply"


def test_stale_activity_falls_back_to_idle(w: World) -> None:
    m = w.mapper()
    m.feed(ev("working", 7))
    w.tick(11 * 60)
    assert m.snapshot()["state"] == "idle"


def test_takeover_status(w: World) -> None:
    m = w.mapper()
    assert m.feed(ev("idle")) is None
    w.takeover = True
    out = m.feed(ev("takeover_started", by="app"))
    assert out["state"] == "idle" and out["status"] == "Você está no controle da Tela."


def test_every_server_state_is_reachable(w: World) -> None:
    m = w.mapper()
    seen = {m.snapshot()["state"]}
    script: list[tuple[dict[str, Any], dict[str, Any]]] = [
        (ev("greeting"), {}), (ev("thinking"), {}), (ev("working", 7), {}),
        (ev("tool_call", 7, tool="WebSearch"), {"tick": 120}), (ev("idle"), {"pending": 1}),
        (ev("approval_decided", 7, decision="approved"), {"pending": 0}),
        (ev("approval_decided", 7, decision="rejected"), {}), (ev("message", mascot="reply"), {}),
        (ev("task_done", 7, title="x"), {}), (ev("job_failed", 7), {}),
        (ev("sentinel_decision", 7, decision="deny"), {"quiet": True}), (ev("idle"), {"paused": True}),
        (ev("paused"), {}),
    ]
    for event, change in script:
        w.tick(change.get("tick", 15))
        w.pending = change.get("pending", w.pending)
        w.quiet = change.get("quiet", w.quiet)
        w.paused = change.get("paused", w.paused)
        out = m.feed(event)
        if out:
            seen.add(out["state"])
            seen.add(out["base"])
    assert seen | {"typing"} == set(STATES)  # typing é local do app


def test_tool_phrases() -> None:
    assert tool_phrase("mcp__talos__gmail_create_draft") == "Escrevendo um rascunho"
    assert tool_phrase("mcp__talos__gmail_search") == "Lendo emails"
    assert tool_phrase(None) == "Trabalhando"
