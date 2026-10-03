"""Fase 2: caso âncora (SPEC §1.4) com FakeRuntime roteirizado + FakeGmail."""

import json

import pytest
from sqlmodel import select

from talos.connectors.mime import deterministic_message_id
from talos.db.models import PendingAction, TaskEvent, Watch

EMPRESA = "lucas.teste+empresa-teste@gmail.com"
BODY = ("Bom dia,\nVenho por este meio solicitar a ligação de gás natural na morada {{dados.morada}}, "
        "NIF {{dados.nif}}.\nCom os melhores cumprimentos,\n{{dados.nome_completo}}")


def script_anchor(h, *, to=EMPRESA, body=BODY):
    async def main_turn(agent):
        r = await agent.call("mcp__talos__task_create", {
            "title": "Ligar o gás em casa", "goal": "Pedir à Empresa Teste a ligação do gás na morada do Lucas.",
            "plan": ["achar contato oficial", "rascunho PT-PT", "propor envio", "vigiar resposta"]})
        assert "criada" in r
        return "Combinado. Plano: 1) contato oficial 2) rascunho 3) você aprova 4) vigio a resposta."

    async def task_first(agent):
        await agent.call("mcp__talos__contacts_save", {"name": "Apoio ao cliente", "org": "Empresa Teste",
                                                       "email": EMPRESA,
                                                       "source_url": "https://empresa-teste.example/contactos"})
        keys = await agent.call("mcp__talos__vault_list_keys", {})
        assert "dados.nif" in keys and "123456789" not in keys
        d = await agent.call("mcp__talos__gmail_create_draft", {"to": [to], "subject": "Pedido de ligação de gás natural",
                                                                "body": body})
        draft_id = d.split("draft_id=")[1].split()[0]
        r = await agent.call("mcp__talos__propose_action", {
            "kind": "email.send", "reason": "email de apoio indicado na página oficial de contactos",
            "payload": {"draft_id": draft_id, "to": [to], "subject": "Pedido de ligação de gás natural",
                        "body": body}})
        assert "Proposta #" in r
        return "—"

    async def task_resumed(agent):
        return "—"

    h.rt.on(lambda r: r.profile == "main", main_turn)
    h.rt.on(lambda r: r.task_id is not None and not r.resume_session_id, task_first)
    h.rt.on(lambda r: r.task_id is not None and bool(r.resume_session_id), task_resumed)


def pending(h):
    with h.app.db.session() as s:
        return list(s.exec(select(PendingAction)))


async def test_anchor_until_sent(h, capsys):
    script_anchor(h)
    await h.say("Fala com a Empresa Teste para ligar o gás aqui em casa.")
    await h.drain()
    assert any("Plano" in t for t in h.tg.texts())

    [action] = pending(h)
    assert action.status == "pending" and action.kind == "email.send"
    card = h.tg.cards()[-1]
    # o cartão mostra os valores REAIS para o Lucas conferir
    assert "Rua das Flores 12" in card["text"] and "123456789" in card["text"]
    assert "Dados pessoais incluídos: morada, NIF, nome completo" in card["text"]
    assert "fonte: https://empresa-teste.example/contactos, verificada" in card["text"]
    assert "Risco: médio" in card["text"]
    assert card["buttons"][0][0][0] == "Aprovar e enviar"
    assert h.gmail.sent == []  # nada sai antes da aprovação
    # o rascunho no Gmail continua com placeholders
    draft = next(iter(h.gmail.drafts.values()))["msg"].get_body().get_content()
    assert "{{dados.nif}}" in draft and "123456789" not in draft

    assert "Aprovado" in await h.tap(f"ap:{action.id}:a")
    assert "já não está ativa" in await h.tap(f"ap:{action.id}:a")  # toque duplo
    await h.drain()
    assert "já não está ativa" in await h.tap(f"ap:{action.id}:a")
    await h.drain()

    sent = h.gmail.sent_to(EMPRESA)
    assert len(sent) == 1, "toque duplo não pode enviar duas vezes"
    msg = sent[0]
    assert "Rua das Flores 12, 1200-195 Lisboa" in msg["body"] and "NIF 123456789" in msg["body"]
    assert "{{" not in msg["body"]
    assert msg["message_id"] == deterministic_message_id(pending(h)[0].idempotency_key)
    assert msg["reply_to"] == "lucas.teste+talos@gmail.com"

    a = pending(h)[0]
    assert a.status == "executed" and a.result_json["thread_id"] == msg["threadId"]
    with h.app.db.session() as s:
        w = s.exec(select(Watch)).one()
        assert w.target == msg["threadId"] and w.followup_policy_json["max"] == 2
        types = [e.type for e in s.exec(select(TaskEvent))]
    assert {"approval_created", "approval_decided", "action_executed", "sentinel_decision"} <= set(types)
    assert any("Email enviado" in t for t in h.tg.texts())
    # a sessão da tarefa foi retomada com o resultado
    assert any("executada" in (r.prompt or "") for r in h.rt.requests if r.task_id)
    # dados do cofre nunca nos logs
    out = capsys.readouterr().out
    assert "123456789" not in out and "Rua das Flores" not in out


async def test_reject_sends_nothing(h):
    script_anchor(h)
    await h.say("Fala com a Empresa Teste para ligar o gás.")
    await h.drain()
    [action] = pending(h)
    assert "Recusado" in await h.tap(f"ap:{action.id}:r")
    await h.drain()
    assert h.gmail.sent == []
    assert pending(h)[0].status == "rejected"
    assert any("RECUSOU" in r.prompt for r in h.rt.requests if r.task_id)


async def test_edit_supersedes(h):
    script_anchor(h)
    edits = []

    async def task_on_edit(agent):
        edits.append(agent.req.prompt)
        await agent.call("mcp__talos__propose_action", {
            "kind": "email.send", "reason": "versão editada",
            "payload": {"to": [EMPRESA], "subject": "Pedido de ligação de gás (urgente)", "body": BODY}})
        return "—"

    h.rt.scripts.insert(0, (lambda r: r.task_id is not None and "ALTERAÇÕES" in r.prompt, task_on_edit))
    await h.say("Fala com a Empresa Teste para ligar o gás.")
    await h.drain()
    [old] = pending(h)
    assert "O que quer mudar" in await h.tap(f"ap:{old.id}:e")
    assert "refazer" in await h.say("põe 'urgente' no assunto")
    await h.drain()
    old2, new = pending(h)
    assert old2.status == "superseded" and old2.superseded_by == new.id
    assert new.status == "pending" and "urgente" in new.payload_json["subject"]
    assert "põe 'urgente' no assunto" in edits[0]
    assert "já não está ativa" in await h.tap(f"ap:{old.id}:a")  # cartão antigo
    assert h.gmail.sent == []


async def test_edit_by_replying_to_card(h):
    script_anchor(h)
    await h.say("Fala com a Empresa Teste para ligar o gás.")
    await h.drain()
    [action] = pending(h)
    card_msg_id = action.card_refs_json["telegram"][0]["message_id"]
    assert "refazer" in await h.say("muda o assunto", reply_to=card_msg_id)
    assert pending(h)[0].status == "superseded"


async def test_expiry_and_reminder(h):
    from datetime import timedelta

    from talos.clock import utcnow

    script_anchor(h)
    await h.say("Fala com a Empresa Teste para ligar o gás.")
    await h.drain()
    [a] = pending(h)
    with h.app.db.session() as s:
        row = s.get(PendingAction, a.id)
        row.created_at = utcnow() - timedelta(hours=25)
        s.add(row)
        s.commit()
    assert h.app.approvals.sweep()["remind"] == [a.id]
    assert h.app.approvals.sweep()["remind"] == []  # lembrete só uma vez
    with h.app.db.session() as s:
        row = s.get(PendingAction, a.id)
        row.expires_at = utcnow() - timedelta(minutes=1)
        s.add(row)
        s.commit()
    assert h.app.approvals.sweep()["expired"] == [a.id]
    assert "já não está ativa" in await h.tap(f"ap:{a.id}:a")
    await h.drain()
    assert h.gmail.sent == []


async def test_approve_while_paused_is_refused(h):
    script_anchor(h)
    await h.say("Fala com a Empresa Teste para ligar o gás.")
    await h.drain()
    [a] = pending(h)
    await h.orch.pause("teste")
    assert "pausado" in (await h.tap(f"ap:{a.id}:a")).lower()
    assert pending(h)[0].status == "pending"


async def test_crash_recovery_never_resends(h):
    script_anchor(h)
    await h.say("Fala com a Empresa Teste para ligar o gás.")
    await h.drain()
    [a] = pending(h)
    await h.tap(f"ap:{a.id}:a")
    await h.drain()
    assert len(h.gmail.sent) == 1
    # simula crash: estado preso em executing depois do envio
    h.app.approvals._transition(a.id, ("executed",), "executing")
    assert await h.app.executor.recover_executing() == [a.id]
    assert pending(h)[0].status == "executed" and pending(h)[0].result_json["recovered"]
    assert len(h.gmail.sent) == 1


async def test_proposal_validation(h):
    from talos.approvals import ProposalError

    with pytest.raises(ProposalError):
        h.app.approvals.create(task_id=None, kind="email.send", payload={"to": [], "subject": "x", "body": "y"})
    with pytest.raises(ProposalError):  # segredo como placeholder
        h.app.approvals.create(task_id=None, kind="email.send",
                               payload={"to": ["a@b.pt"], "subject": "x", "body": "{{google.token}}"})
    with pytest.raises(ProposalError):  # chave inexistente
        h.app.approvals.create(task_id=None, kind="email.send",
                               payload={"to": ["a@b.pt"], "subject": "x", "body": "{{dados.iban}}"})
    a = h.app.approvals.create(task_id=None, kind="email.send",
                               payload={"to": ["a@b.pt"], "subject": "x", "body": "o meu NIF é 123456789"})
    assert a.risk == "alto" and a.payload_json["_raw_personal"]
    assert json.dumps(a.payload_json["_recipients"]).count("novo") == 1
