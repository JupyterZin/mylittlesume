"""Rotas de Web Push do app (`/api/push/*`), presença no WebSocket e conectores em /api/settings."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from talos.channels.web_api import build_api
from tests.conftest import Harness
from tests.test_push import FCM, browser_keys

UA = "Mozilla/5.0 (Linux; Android 15; Pixel 8) AppleWebKit/537.36 Chrome/141 Mobile Safari/537.36"


@pytest.fixture
def h2(h: Harness) -> Harness:
    h.app.settings.quiet_hours = "00:00-00:00"
    return h


@pytest.fixture
def client(h2: Harness) -> TestClient:
    with TestClient(build_api(h2.app, h2.gw, static_dir=None)) as c:
        yield c


def sub_json(endpoint: str = FCM + "abc") -> dict[str, Any]:
    _, p256dh, _, auth = browser_keys()
    return {"endpoint": endpoint, "expirationTime": None, "keys": {"p256dh": p256dh, "auth": auth}}


def _wait(cond: Callable[[], bool], timeout: float = 3) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_key_is_stable_and_public(client: TestClient, h2: Harness) -> None:
    r = client.get("/api/push/key")
    assert r.status_code == 200
    body = r.json()
    key = body["public_key"]
    assert body["enabled"] is True and body["subscriptions"] == 0
    assert len(base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))) == 65
    assert client.get("/api/push/key").json()["public_key"] == key
    # "reinício": API nova sobre o mesmo cofre → mesma chave (as inscrições continuam válidas)
    from talos.channels.push import WebPushSender
    from talos.vault.store import Vault

    h2.app.notifier.push = WebPushSender(h2.app.settings, h2.app.db, Vault(h2.app.db, h2.key))
    with TestClient(build_api(h2.app, h2.gw, static_dir=None)) as c2:
        assert c2.get("/api/push/key").json()["public_key"] == key
    raw = json.dumps(client.get("/api/push/key").json())
    assert h2.app.vault.get("webpush.vapid_private") not in raw  # a privada nunca sai


def test_subscribe_unsubscribe(client: TestClient, h2: Harness) -> None:
    sub = sub_json()
    r = client.post("/api/push/subscribe", json=sub, headers={"User-Agent": UA})
    assert r.status_code == 200 and r.json() == {"ok": True, "created": True, "subscriptions": 1}
    assert client.post("/api/push/subscribe", json=sub, headers={"User-Agent": UA}).json()["created"] is False
    from sqlmodel import select

    from talos.db.models import PushSubscription, TaskEvent

    with h2.app.db.session() as s:
        row = s.exec(select(PushSubscription)).one()
        assert row.user_agent == UA and row.p256dh == sub["keys"]["p256dh"]
        assert [e.type for e in s.exec(select(TaskEvent))].count("push_subscribed") == 1
    # endpoint rodou: o app manda o antigo e o servidor troca
    new = {**sub_json(FCM + "novo"), "old_endpoint": sub["endpoint"]}
    assert client.post("/api/push/subscribe", json=new).json()["subscriptions"] == 1
    r = client.request("DELETE", "/api/push/subscribe", json={"endpoint": FCM + "novo"})
    assert r.json() == {"ok": True, "removed": True, "subscriptions": 0}
    assert client.request("DELETE", "/api/push/subscribe", json={"endpoint": FCM + "novo"}).json()["removed"] is False


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(endpoint="https://evil.example/push"),
    lambda s: s.update(endpoint="http://fcm.googleapis.com/fcm/send/x"),
    lambda s: s["keys"].update(p256dh="AAAA"),
    lambda s: s["keys"].update(auth="não-é-base64"),
])
def test_subscribe_rejects_bad_subscriptions(client: TestClient, mutate: Callable[[dict], None]) -> None:
    sub = sub_json()
    mutate(sub)
    r = client.post("/api/push/subscribe", json=sub)
    assert r.status_code == 400 and r.json()["detail"]
    assert client.post("/api/push/subscribe", json={"endpoint": FCM + "x"}).status_code == 422


def test_push_routes_need_auth(h2: Harness) -> None:
    h2.app.settings.app_pin = "4321"
    with TestClient(build_api(h2.app, h2.gw, static_dir=None)) as c:
        assert c.get("/api/push/key").status_code == 401
        assert c.post("/api/push/subscribe", json=sub_json()).status_code == 401
        assert c.request("DELETE", "/api/push/subscribe", json={"endpoint": FCM}).status_code == 401
        assert c.post("/api/push/test").status_code == 401
        assert c.get("/api/push/key", headers={"X-Talos-Pin": "4321"}).status_code == 200


def test_send_test(client: TestClient, monkeypatch: pytest.MonkeyPatch, h2: Harness) -> None:
    assert client.post("/api/push/test").status_code == 409  # ninguém inscrito
    client.post("/api/push/subscribe", json=sub_json())
    calls: list[dict[str, Any]] = []

    def fake_webpush(info: dict, data: str, **kw: Any) -> Any:
        calls.append({"info": info, "data": json.loads(data), **kw})
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr("talos.channels.push.webpush", fake_webpush)
    h2.app.settings.notify_channels = "telegram"  # o teste é um pedido explícito: sai na mesma
    r = client.post("/api/push/test")
    assert r.json() == {"ok": True, "sent": 1, "failed": 0, "removed": 0}
    (c,) = calls
    assert c["data"]["body"] == "Notificações do Talos ligadas ✓" and c["data"]["kind"] == "test"
    assert c["vapid_claims"] == {"sub": "mailto:lucas.teste@gmail.com"} and c["headers"]["Urgency"] == "high"
    monkeypatch.setattr("talos.channels.push.webpush",
                        lambda *a, **k: (_ for _ in ()).throw(__import__("pywebpush").WebPushException(
                            "gone", response=SimpleNamespace(status_code=410, text="", headers={}))))
    assert client.post("/api/push/test").json() == {"ok": False, "sent": 0, "failed": 0, "removed": 1}
    assert client.get("/api/push/key").json()["subscriptions"] == 0


def test_settings_lists_push_connector(client: TestClient, h2: Harness) -> None:
    conn = {c["id"]: c for c in client.get("/api/settings").json()["connectors"]}
    assert conn["push"]["ok"] is False and conn["push"]["detail"] == "0 aparelhos"
    client.post("/api/push/subscribe", json=sub_json())
    conn = {c["id"]: c for c in client.get("/api/settings").json()["connectors"]}
    assert conn["push"]["ok"] is True and conn["push"]["detail"] == "1 aparelho"


def test_ws_presence_feeds_the_notifier(client: TestClient, h2: Harness) -> None:
    presence = h2.app.notifier.presence
    assert presence.any_visible() is False
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "mascot_state"
        assert _wait(presence.any_visible)  # abriu: visível
        ws.send_json({"type": "presence", "visible": False})
        assert _wait(lambda: not presence.any_visible())
        ws.send_text("isto não é json")  # ignorado sem fechar a ligação
        ws.send_json({"type": "presence", "visible": True})
        assert _wait(presence.any_visible)
    assert _wait(lambda: not presence.any_visible())  # fechou: esquecido
