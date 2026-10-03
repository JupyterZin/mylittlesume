"""Organização semanal do Gmail (segunda-feira): plano → cartão → aprovação → rótulos/arquivo → desfazer."""

from datetime import UTC, datetime

from sqlmodel import select

from talos.db.models import PendingAction, Schedule
from talos.monitor.gmail_watch import seed_schedules
from talos.monitor.organizer import InboxOrganizer
from tests.conftest import CHAT
from tests.test_system1 import FakeJev, ch, no, with_jev

PROMO = {"List-Unsubscribe": "<mailto:sair@loja.example>"}


def fill_inbox(h):
    g = h.gmail
    ids = {
        "promo": g.deliver(sender="Loja <ofertas@loja.example>", subject="-50% só hoje", body="compre já",
                           labels=["CATEGORY_PROMOTIONS"])["id"],
        "news": g.deliver(sender="Jornal <news@jornal.example>", subject="Resumo da semana", body="notícias",
                          headers=PROMO)["id"],
        "mae": g.deliver(sender="Mãe <mae@familia.example>", subject="Jantar domingo?", body="Vens jantar?")["id"],
        "fatura": g.deliver(sender="EDP <faturas@edp.example>", subject="Fatura outubro", body="valor a pagar",
                            labels=["CATEGORY_UPDATES"])["id"],
    }
    star = g.deliver(sender="Chefe <chefe@empresa.example>", subject="Importante", body="x", labels=["STARRED"])
    ids["star"] = star["id"]
    return ids


def jev_for_inbox():
    def categoria(q, state):
        frm = state["de"]
        cat = ("promocoes" if "loja" in frm else "newsletters" if "jornal" in frm else
               "pessoal" if "familia" in frm else "financas")
        return ch(cat, 0.9)

    def precisa(q, state):
        return no(0.85 if "familia" in state["de"] else 0.05)

    def importancia(q, state):
        return {"type": "score", "score": 2.6 if "edp" in state["de"] or "familia" in state["de"] else 0.3,
                "confidence": 0.8, "legend": {}, "probabilities": {}}

    return FakeJev({"categoria": categoria, "precisa_resposta": precisa, "importancia": importancia})


def pending_org(h):
    with h.app.db.session() as s:
        return s.exec(select(PendingAction).where(PendingAction.kind == "email.organize",
                                                  PendingAction.status == "pending")).first()


async def test_organize_with_jev_card_approve_and_undo(h):
    ids = fill_inbox(h)
    with_jev(h, jev_for_inbox())
    action = await InboxOrganizer(h.app).propose()
    assert action is not None and action.risk == "baixo"
    p = action.payload_json
    assert p["scanned"] == 4  # a mensagem com estrela fica de fora
    assert set(p["archive"]) == {ids["promo"], ids["news"]}
    assert [x["de"] for x in p["needs_reply"]] == ["Mãe"]
    card = h.tg.cards()[-1]
    assert card["buttons"][0][0][0] == "Aprovar e organizar"
    assert "Parecem esperar resposta sua" in card["text"] and "Mãe" in card["text"]
    assert all("INBOX" in h.gmail.messages[i]["labelIds"] for i in ids.values())  # nada mudou ainda

    assert "Aprovado" in await h.tap(f"ap:{action.id}:a")
    await h.drain()
    msgs = h.gmail.messages
    assert "INBOX" not in msgs[ids["promo"]]["labelIds"] and "INBOX" not in msgs[ids["news"]]["labelIds"]
    assert "INBOX" in msgs[ids["mae"]]["labelIds"] and "INBOX" in msgs[ids["fatura"]]["labelIds"]
    assert h.gmail.labels["Talos/Finanças"] in msgs[ids["fatura"]]["labelIds"]
    assert len(h.gmail.messages) == 5  # nada apagado
    assert any("Caixa organizada" in t for t in h.tg.texts())

    res = await h.gw.on_command("telegram", CHAT, "desfazer_organizacao", [])
    assert "Voltaram 2 emails" in res
    assert "INBOX" in msgs[ids["promo"]]["labelIds"]
    assert "já foi desfeita" in await h.gw.on_command("telegram", CHAT, "desfazer_organizacao", [])


async def test_organize_without_jev_uses_gmail_signals_only(h):
    ids = fill_inbox(h)
    action = await InboxOrganizer(h.app).propose()
    p = action.payload_json
    assert set(p["archive"]) == {ids["promo"], ids["news"], ids["fatura"]}  # categorias do Gmail
    assert ids["mae"] not in p["archive"]
    assert "Sem Sistema 1" in p["summary"]


async def test_reject_changes_nothing_and_new_plan_supersedes(h):
    fill_inbox(h)
    org = InboxOrganizer(h.app)
    first = await org.propose()
    second = await org.propose()
    with h.app.db.session() as s:
        assert s.get(PendingAction, first.id).status == "superseded"
    assert pending_org(h).id == second.id
    await h.tap(f"ap:{second.id}:r")
    await h.drain()
    assert all("INBOX" in m["labelIds"] for m in h.gmail.messages.values())


async def test_monday_schedule_and_command(h):
    seed_schedules(h.app)
    with h.app.db.session() as s:
        sc = s.exec(select(Schedule).where(Schedule.kind == "gmail_organize")).one()
    assert "BYDAY=MO" in sc.rrule
    nxt = sc.next_run_at.astimezone(UTC)
    assert datetime(nxt.year, nxt.month, nxt.day).weekday() == 0  # segunda (09:00 Lisboa = 08:00 UTC)
    org = InboxOrganizer(h.app)
    h.orch.register("gmail.organize", org.handle_job)
    fill_inbox(h)
    assert "plano" in await h.gw.on_command("telegram", CHAT, "organizar", [])
    await h.drain()
    assert pending_org(h) is not None
