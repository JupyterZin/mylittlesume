"""Fase 1: núcleo conversacional com FakeTelegram + FakeRuntime."""

from datetime import timedelta

from sqlmodel import select

from talos.clock import utcnow
from talos.db.models import Conversation, InboundLog, Job, Message, UsageLog
from tests.conftest import CHAT, make_harness


async def test_hello_gets_answer(h):
    h.rt.reply("Olá, Lucas! Em que posso ajudar?")
    assert await h.say("olá") is None
    assert await h.drain() == 1
    assert h.tg.texts() == ["Olá, Lucas! Em que posso ajudar?"]
    req = h.rt.requests[0]
    assert req.profile == "main" and "Lucas: olá" in req.prompt
    with h.app.db.session() as s:
        roles = [m.role for m in s.exec(select(Message))]
        assert roles == ["user", "assistant"]
        assert len(list(s.exec(select(UsageLog)))) == 1


async def test_session_resumed_then_rotated_next_day(h):
    h.rt.reply("ok")
    await h.say("um")
    await h.drain()
    first = h.rt.requests[0]
    assert first.resume_session_id is None
    await h.say("dois")
    await h.drain()
    second = h.rt.requests[1]
    assert second.resume_session_id is not None
    # vira o dia
    with h.app.db.session() as s:
        c = s.exec(select(Conversation)).one()
        c.session_started_at = utcnow() - timedelta(days=1)
        s.add(c)
        s.commit()
    await h.say("três")
    await h.drain()
    third = h.rt.requests[2]
    assert third.resume_session_id is None
    assert "[contexto: nova sessão do dia]" in third.prompt and "dois" in third.prompt


async def test_other_chat_ignored_and_logged(h):
    assert await h.say("olá", chat="666") is None
    assert await h.gw.on_command("telegram", "666", "tarefas", []) is None
    with h.app.db.session() as s:
        assert len(list(s.exec(select(InboundLog)))) == 2
        assert list(s.exec(select(Job))) == []
    assert await h.drain() == 0


async def test_pause_blocks_and_resume_restores(h):
    h.rt.reply("feito")
    assert "Pausado" in await h.gw.on_command("telegram", CHAT, "pausar", [])
    await h.say("faz algo")
    assert await h.drain() == 0
    assert h.rt.requests == []
    assert "De volta" in await h.gw.on_command("telegram", CHAT, "retomar", [])
    assert await h.drain() == 1
    assert h.tg.texts()[-1] == "feito"


async def test_restart_keeps_history_and_jobs(h, tmp_settings):
    from talos.db.engine import Database

    h.rt.reply("ok")
    await h.say("primeira")
    await h.drain()
    await h.say("segunda (fica na fila)")
    db2 = Database(tmp_settings.db_url)
    h2 = make_harness(tmp_settings, db2, h.key)
    h2.rt.reply("voltei")
    with db2.session() as s:
        assert [m.content for m in s.exec(select(Message))][:2] == ["primeira", "ok"]
    assert await h2.drain() == 1
    assert h2.tg.texts() == ["voltei"]


async def test_rate_limit_defers_and_notifies_once(h):
    h.rt.reply("ok")
    h.rt.rate_limit_next = True
    await h.say("olá")
    assert await h.drain() == 1
    with h.app.db.session() as s:
        job = s.exec(select(Job)).one()
    assert job.status == "queued" and job.last_error == "rate_limited" and job.attempts == 0
    assert any("limite da assinatura" in t for t in h.tg.texts())
    assert h.app.control.rate_limited_until()


async def test_commands(h):
    assert "Nenhuma tarefa" in await h.gw.on_command("telegram", CHAT, "tarefas", [])
    assert "Modo: subscription" in await h.gw.on_command("telegram", CHAT, "uso", [])
    t = h.app.tasks.create("Teste", "x")
    assert "cancelada" in await h.gw.on_command("telegram", CHAT, "cancelar", [str(t.id)])
    assert h.app.tasks.get(t.id).status == "cancelled"
