"""Web Push do app: mensagens (redigidas e resumidas), notifier (horas de silêncio, canais, respostas),
envio real cifrado (VAPID + aes128gcm) com o HTTP falso, limpeza de inscrições mortas, doctor e migração."""

from __future__ import annotations

import base64
import json
import os
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import http_ece
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02
from pydantic import ValidationError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from talos.channels.push import (
    BODY_MAX,
    MAX_FAILURES,
    VAPID_KEY,
    FakePushSender,
    PushError,
    PushMessage,
    WebPushSender,
    card_message,
    notice_message,
    ping_message,
    validate_subscription,
)
from talos.config import Settings
from talos.db.engine import Database
from talos.db.models import Job, PushSubscription
from talos.doctor import OK, WARN, Doctor
from talos.vault.store import Vault
from tests.conftest import Harness

MORADA = "Rua das Flores 12, 1200-195 Lisboa"
NIF = "123456789"
FCM = "https://fcm.googleapis.com/fcm/send/"
QUIET = datetime(2026, 10, 7, 22, 30, tzinfo=UTC)  # 23:30 em Lisboa (horário de verão)


def browser_keys() -> tuple[ec.EllipticCurvePrivateKey, str, bytes, str]:
    """O que o Chrome gera ao inscrever-se: par P-256 + segredo de 16 bytes."""
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    return priv, b64(pub), auth, b64(auth)


def subscribe(sender: Any, endpoint: str = FCM + "abc") -> tuple[ec.EllipticCurvePrivateKey, bytes]:
    priv, p256dh, auth, auth_b64 = browser_keys()
    sender.subscribe(endpoint, p256dh, auth_b64, user_agent="Mozilla/5.0 (Linux; Android 15) Chrome/141")
    return priv, auth


@pytest.fixture
def fake(h: Harness) -> FakePushSender:
    f = FakePushSender()
    h.app.notifier.push = f
    return f


def _proposal(h: Harness) -> Any:
    t = h.app.tasks.create("Ligar o gás em casa", "pedir ligação do gás")
    h.app.contacts.save(name="Apoio", email="apoio@empresa-exemplo.pt",
                        source_url="https://empresa-exemplo.pt/contactos")
    return h.app.approvals.create(task_id=t.id, kind="email.send", payload={
        "to": ["apoio@empresa-exemplo.pt"], "subject": "Pedido de ligação",
        "body": "Bom dia, morada {{dados.morada}}, NIF {{dados.nif}}.",
    }, reason="email oficial de apoio")


def _no_secrets(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False)
    for v in (MORADA, NIF, "Lucas Teste Silva"):
        assert v not in text


# ------------------------------------------------------------------ mensagens
def test_payload_is_redacted_then_clipped(h: Harness) -> None:
    body = f"📬 Resposta de apoio@x.pt:\n\n\nconfirmaram a morada {MORADA} e o NIF {NIF}. " + "bla " * 100
    p = PushMessage(title="Talos", body=body, url="https://evil.example/x").payload()
    _no_secrets(p)
    assert "[REDACTED:dados.morada]" in p["body"] and "[REDACTED:dados.nif]" in p["body"]
    assert len(p["body"]) <= BODY_MAX and p["body"].endswith("…")
    assert "\n\n" not in p["body"]  # linhas em branco colapsadas
    assert p["url"] == "/"  # só caminhos do próprio app
    assert PushMessage(title="t", body="b", url="//evil.example").payload()["url"] == "/"
    assert PushMessage(title="t", body="b", url="/aprovacoes/3").payload()["url"] == "/aprovacoes/3"
    # um valor do cofre cortado ao meio não pode escapar à redação: redige-se antes de cortar
    tail = PushMessage(title="t", body="x" * (BODY_MAX - 10) + MORADA).payload()["body"]
    assert "Rua das" not in tail


def test_card_message_is_a_summary(h: Harness) -> None:
    a = _proposal(h)
    m = card_message(a, "Ligar o gás em casa")
    p = m.payload()
    assert p["title"] == "Aprovação necessária · Ligar o gás em casa"
    assert p["body"] == f"Proposta #{a.id} · enviar email para apoio@empresa-exemplo.pt — toque para ver"
    assert p["url"] == f"/aprovacoes/{a.id}" and p["tag"] == f"ap-{a.id}" and p["kind"] == "card"
    assert m.urgency == "high" and m.topic == f"ap-{a.id}"
    assert "Bom dia" not in json.dumps(p) and "{{" not in json.dumps(p)  # nada do corpo do email
    _no_secrets(p)


def test_card_message_for_browser_submit_names_the_site(h: Harness) -> None:
    a = h.app.approvals.create(task_id=None, kind="browser.submit", payload={
        "summary": "Submeter o formulário de pedido", "_host": "empresa-exemplo.pt",
        "input": {"element": "Enviar"}}, reason="formulário oficial")
    assert card_message(a).payload()["body"] == (f"Proposta #{a.id} · submeter formulário em empresa-exemplo.pt"
                                                 " — toque para ver")


def test_notice_message_urgency_and_tags() -> None:
    assert notice_message("x").urgency == "normal"
    assert notice_message("x", urgent=True).urgency == "high"
    assert notice_message("x", task_id=7).tag == "task-7"
    assert notice_message("x", silent=True).payload()["silent"] is True
    assert "silent" not in notice_message("x").payload()
    assert ping_message().payload()["body"] == "Notificações do Talos ligadas ✓"


def test_validate_subscription() -> None:
    _, p256dh, _, auth = browser_keys()
    validate_subscription(FCM + "abc", p256dh, auth)
    validate_subscription("https://updates.push.services.mozilla.com/wpush/v2/x", p256dh, auth)
    for bad in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://evil.example/fcm.googleapis.com",
                "https://fcm.googleapis.com.evil.example/x", "https://storage.googleapis.com/b/x",
                "javascript:alert(1)", ""):
        with pytest.raises(PushError):
            validate_subscription(bad, p256dh, auth)
    with pytest.raises(PushError):
        validate_subscription(FCM + "abc", p256dh[:-4], auth)
    with pytest.raises(PushError):
        validate_subscription(FCM + "abc", p256dh, "a/b+c")


# ------------------------------------------------------------------ notifier
async def test_notify_pushes_notice(h: Harness, fake: FakePushSender) -> None:
    assert await h.app.notifier.notify(f"📬 Resposta de apoio: confirmam a morada {MORADA}", task_id=None) == "sent"
    (p,) = fake.sent
    assert p["kind"] == "notice" and p["title"] == "Talos" and p["url"] == "/" and p["_urgency"] == "normal"
    assert "📬 Resposta de apoio" in p["body"]
    _no_secrets(p)
    assert h.tg.texts()[-1].startswith("📬 Resposta de apoio")  # o Telegram continua igual (com o valor real)
    await h.app.notifier.notify("🖐️ Preciso que você assuma a Tela", urgent=True, task_id=3)
    assert fake.sent[-1]["_urgency"] == "high" and fake.sent[-1]["tag"] == "task-3"


async def test_card_pushes_summary_with_link(h: Harness, fake: FakePushSender) -> None:
    a = _proposal(h)
    assert await h.app.notifier.send_card(a, task_title="Ligar o gás em casa") == "sent"
    (p,) = fake.by_kind("card")
    assert p["url"] == f"/aprovacoes/{a.id}" and p["tag"] == f"ap-{a.id}" and p["_urgency"] == "high"
    assert p["body"].startswith(f"Proposta #{a.id} · enviar email para apoio@empresa-exemplo.pt")
    _no_secrets(p)
    assert MORADA in h.tg.cards()[-1]["text"]  # no Telegram o cartão completo, como antes


async def test_quiet_hours_defer_push_like_telegram(h: Harness, fake: FakePushSender,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("talos.channels.notifier.utcnow", lambda: QUIET)
    assert await h.app.notifier.notify("Resumo do dia") == "deferred"
    a = _proposal(h)
    assert await h.app.notifier.send_card(a, task_title="Ligar o gás") == "deferred"
    assert fake.sent == [] and h.tg.sent == []
    # urgente passa já, com urgência alta; silenciosa passa já, sem som
    await h.app.notifier.notify("❌ A proposta falhou", urgent=True)
    await h.app.notifier.notify("🤖 Resposta automática", silent=True)
    assert [(m["_urgency"], m.get("silent", False)) for m in fake.sent] == [("high", False), ("normal", True)]
    # fim da janela: os jobs adiados entregam no Telegram e no app
    monkeypatch.setattr("talos.channels.notifier.utcnow", lambda: datetime(2026, 10, 8, 7, 0, tzinfo=UTC))
    with h.app.db.session() as s:
        jobs = {j.kind: j for j in s.exec(select(Job))}
    await h.orch._notify_send(jobs["notify.send"])
    await h.orch._approval_card(jobs["approval.card"])
    assert [m["kind"] for m in fake.sent[2:]] == ["notice", "card"]
    assert fake.sent[2]["body"] == "Resumo do dia" and fake.sent[3]["tag"] == f"ap-{a.id}"


async def test_notify_channels(h: Harness, fake: FakePushSender) -> None:
    h.app.settings.notify_channels = "app"
    await h.app.notifier.notify("só no app")
    await h.app.notifier.send_card(_proposal(h))
    assert h.tg.sent == [] and [m["kind"] for m in fake.sent] == ["notice", "card"]
    h.app.settings.notify_channels = "telegram"
    await h.app.notifier.notify("só no Telegram")
    assert len(fake.sent) == 2 and h.tg.texts() == ["só no Telegram"]


async def test_reply_pushes_only_when_app_is_not_on_screen(h: Harness, fake: FakePushSender) -> None:
    n = h.app.notifier
    now = [0.0]
    n.presence._clock = lambda: now[0]
    await n.reply("telegram", "1001", "resposta no Telegram")
    assert fake.sent == []  # o Telegram já avisa
    n.presence.update("cliente", True)
    await n.reply("app", "app", "com o app aberto")
    assert fake.sent == []
    n.presence.update("cliente", False)  # foi para segundo plano
    await n.reply("app", "app", "pronto: encontrei o horário")
    assert [(m["kind"], m["body"]) for m in fake.sent] == [("reply", "pronto: encontrei o horário")]
    n.presence.update("cliente", True)
    now[0] += 120  # sem sinal de vida há 2 min (Android congelou o app): conta como fechado
    await n.reply("app", "app", "outra")
    assert len(fake.sent) == 2
    n.presence.drop("cliente")
    h.app.settings.notify_channels = "telegram"
    await n.reply("app", "app", "sem push")
    assert len(fake.sent) == 2


async def test_push_failure_never_breaks_notify(h: Harness) -> None:
    class Boom(FakePushSender):
        async def send(self, msg: PushMessage) -> Any:
            raise RuntimeError("FCM fora do ar")

    h.app.notifier.push = Boom()
    assert await h.app.notifier.notify("ainda chego") == "sent"
    assert h.tg.texts() == ["ainda chego"]


async def test_push_still_sent_when_telegram_fails(h: Harness, fake: FakePushSender) -> None:
    async def down(*a: Any, **k: Any) -> str:
        raise ConnectionError("Telegram fora do ar")

    h.tg.send_text = down  # type: ignore[method-assign]
    with pytest.raises(ConnectionError):
        await h.app.notifier.notify("aviso")
    assert [m["body"] for m in fake.sent] == ["aviso"]


# ------------------------------------------------------------------ envio real (HTTP falso)
class FakeHTTP:
    def __init__(self, statuses: list[int] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.statuses = statuses or []
        self.threads: set[str] = set()

    def __call__(self, url: str, data: bytes | None = None, headers: dict[str, str] | None = None,
                 timeout: Any = None) -> Any:
        self.threads.add(threading.current_thread().name)
        self.calls.append({"url": url, "data": data, "headers": dict(headers or {}), "timeout": timeout})
        status = self.statuses.pop(0) if self.statuses else 201
        return SimpleNamespace(status_code=status, reason="x", text="", headers={})


async def test_real_send_is_encrypted_signed_and_off_the_loop(h: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    sender = h.app.notifier.push
    assert isinstance(sender, WebPushSender)
    priv, auth = subscribe(sender)
    http = FakeHTTP()
    monkeypatch.setattr("requests.post", http)
    a = _proposal(h)
    await h.app.notifier.send_card(a, task_title="Ligar o gás em casa")
    (call,) = http.calls
    assert call["url"] == FCM + "abc"
    hd = {k.lower(): v for k, v in call["headers"].items()}
    assert hd["urgency"] == "high" and hd["topic"] == f"ap-{a.id}" and hd["ttl"] == str(12 * 3600)
    assert hd["content-encoding"] == "aes128gcm" and call["timeout"] == 10
    assert Vapid02.verify(hd["authorization"])  # assinatura VAPID válida
    jwt = hd["authorization"].split("t=", 1)[1].split(",", 1)[0]
    claims = json.loads(base64.urlsafe_b64decode(jwt.split(".")[1] + "=="))
    assert claims["sub"] == "mailto:lucas.teste@gmail.com" and claims["aud"] == "https://fcm.googleapis.com"
    assert hd["authorization"].endswith("k=" + sender.public_key())  # a mesma chave que o app usou
    assert threading.main_thread().name not in http.threads  # o POST correu numa thread
    payload = json.loads(http_ece.decrypt(call["data"], private_key=priv, auth_secret=auth, version="aes128gcm"))
    assert payload["url"] == f"/aprovacoes/{a.id}" and payload["kind"] == "card"
    _no_secrets(payload)
    with h.app.db.session() as s:
        row = s.exec(select(PushSubscription)).one()
        assert row.last_ok_at is not None and row.failures == 0


async def test_gone_subscription_is_removed_and_failures_counted(h: Harness,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    sender = h.app.notifier.push
    subscribe(sender, FCM + "morta")
    subscribe(sender, FCM + "doente")
    http = FakeHTTP([410, 500])
    monkeypatch.setattr("requests.post", http)
    res = await sender.send(notice_message("olá"))
    assert (res.sent, res.failed, res.removed) == (0, 1, 1)
    with h.app.db.session() as s:
        rows = list(s.exec(select(PushSubscription)))
    assert [(r.endpoint, r.failures) for r in rows] == [(FCM + "doente", 1)]
    http.statuses = [500] * MAX_FAILURES
    for _ in range(MAX_FAILURES - 1):
        await sender.send(notice_message("olá"))
    assert sender.count() == 0  # falhou vezes demais seguidas: desiste
    subscribe(sender, FCM + "nova")
    http.statuses = [404]
    assert (await sender.send(notice_message("olá"))).removed == 1 and sender.count() == 0


async def test_vapid_key_lives_in_vault_and_survives_restart(h: Harness, tmp_settings: Settings,
                                                            db: Database) -> None:
    assert h.app.vault.get(VAPID_KEY) is None  # só no primeiro uso
    key = h.app.notifier.push.public_key()
    raw = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
    assert len(raw) == 65 and raw[0] == 4
    assert {"key": VAPID_KEY, "kind": "segredo"} in h.app.vault.list_keys()
    again = WebPushSender(tmp_settings, db, Vault(db, h.key))  # outro processo, mesmo cofre
    assert again.public_key() == key
    assert again.subject == "mailto:lucas.teste@gmail.com"
    tmp_settings.gmail_address = ""
    assert again.subject == "mailto:talos@localhost"


def test_subscribe_upsert_replace_and_cap(h: Harness) -> None:
    sender = h.app.notifier.push
    _, p256dh, _, auth = browser_keys()
    assert sender.subscribe(FCM + "a", p256dh, auth) is True
    assert sender.subscribe(FCM + "a", p256dh, auth) is False
    assert sender.subscribe(FCM + "b", p256dh, auth, replaces=FCM + "a") is True
    assert sender.count() == 1
    for i in range(12):
        sender.subscribe(FCM + f"x{i}", p256dh, auth)
    assert sender.count() == 10
    assert sender.unsubscribe(FCM + "x11") is True and sender.unsubscribe(FCM + "x11") is False


# ------------------------------------------------------------------ configuração, doctor, migração
def test_notify_channels_setting() -> None:
    assert Settings().notify_channel_set == {"telegram", "app"}
    assert Settings(notify_channels=" App ").notify_channel_set == {"app"}
    assert Settings(notify_channels="telegram, app,app").notify_channels == "telegram,app"
    for bad in ("sms", "telegram,email", ","):
        with pytest.raises(ValidationError):
            Settings(notify_channels=bad)


async def test_doctor_counts_subscriptions(tmp_settings: Settings, db: Database) -> None:
    env = {"CLAUDE_CODE_OAUTH_TOKEN": "t"}

    async def check() -> Any:
        checks = await Doctor(tmp_settings, db, live=False, environ=env).run()
        return {c.name: c for c in checks}["notificações do app"]

    assert (await check()).status == WARN
    with db.session() as s:
        s.add(PushSubscription(endpoint=FCM + "a", p256dh="k", auth="a", last_ok_at=datetime.now(UTC)))
        s.commit()
    c = await check()
    assert c.status == OK and "1 aparelho" in c.detail
    tmp_settings.notify_channels = "telegram"
    assert "desligadas" in (await check()).detail


def _alembic(db: Database, *args: str) -> None:
    from alembic import command
    from alembic.config import Config

    from talos.db.engine import MIGRATIONS_DIR

    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    with db.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        getattr(command, args[0])(cfg, args[1])


def test_migration_0002_on_fresh_db_and_from_0001(tmp_path: Any) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlmodel import SQLModel

    fresh = Database(f"sqlite:///{tmp_path / 'novo.db'}")
    fresh.migrate()
    with fresh.engine.connect() as c:
        assert compare_metadata(MigrationContext.configure(c), SQLModel.metadata) == []  # modelo = migrações
        assert "push_subscriptions" in sa_inspect(c).get_table_names()

    old = Database(f"sqlite:///{tmp_path / 'antigo.db'}")
    _alembic(old, "upgrade", "0001")
    with old.engine.connect() as c:
        assert "push_subscriptions" not in sa_inspect(c).get_table_names()
    old.set_state("pause", {"paused": True})  # dados de antes ficam
    old.migrate()
    with old.engine.connect() as c:
        assert "push_subscriptions" in sa_inspect(c).get_table_names()
        assert c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "0002"
    assert old.get_state("pause") == {"paused": True}
    with old.session() as s:
        s.add(PushSubscription(endpoint=FCM + "a", p256dh="k", auth="a"))
        s.commit()
        with pytest.raises(IntegrityError):  # endpoint único
            s.add(PushSubscription(endpoint=FCM + "a", p256dh="k", auth="a"))
            s.commit()
    _alembic(old, "downgrade", "0001")
    with old.engine.connect() as c:
        assert "push_subscriptions" not in sa_inspect(c).get_table_names()
