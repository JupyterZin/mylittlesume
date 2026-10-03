"""API do app (SPEC §10): rotas novas, compatibilidade, WebSocket tipado e o app estático."""

from __future__ import annotations

import base64
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from talos.channels.web_api import build_api, typed_event
from talos.clock import utcnow
from talos.db.models import Goal, MemoryFact, Schedule, UsageLog, Watch
from tests.conftest import Harness


@pytest.fixture
def h2(h: Harness) -> Harness:
    h.app.settings.quiet_hours = "00:00-00:00"  # nunca em silêncio: estados previsíveis
    return h


@pytest.fixture
def client(h2: Harness) -> TestClient:
    with TestClient(build_api(h2.app, h2.gw, static_dir=None)) as c:
        yield c


def _proposal(h: Harness, task_title: str = "Ligar o gás em casa", **extra) -> int:
    t = h.app.tasks.create(task_title, "pedir ligação do gás")
    h.app.contacts.save(name="Apoio", email="apoio@empresa-exemplo.pt",
                        source_url="https://empresa-exemplo.pt/contactos")
    a = h.app.approvals.create(task_id=t.id, kind="email.send", payload={
        "to": ["apoio@empresa-exemplo.pt"], "subject": "Pedido de ligação",
        "body": "Bom dia, morada {{dados.morada}}, NIF {{dados.nif}}.", **extra,
    }, reason="email oficial de apoio")
    return a.id


# ------------------------------------------------------------------ básicos e auth
def test_health_is_public(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_state(client: TestClient, h2: Harness) -> None:
    _proposal(h2)
    r = client.get("/api/state")
    assert r.status_code == 200
    st = r.json()
    assert st["agent_name"] == "Talos" and st["paused"] is False
    assert st["pending_approvals"] == 1
    assert st["takeover"]["active"] is False
    assert st["mascot"]["state"] == "waiting_approval"
    assert st["quiet_hours"]["active"] is False and st["timezone"] == "Europe/Lisbon"


def test_pin_and_tailscale_allowlist(h2: Harness) -> None:
    h2.app.settings.app_pin = "4321"
    h2.app.settings.allowed_tailscale_logins = "lucas@example.com"
    with TestClient(build_api(h2.app, h2.gw, static_dir=None)) as c:
        ok = {"Tailscale-User-Login": "Lucas@example.com", "X-Talos-Pin": "4321"}
        assert c.get("/api/state", headers=ok).status_code == 200
        assert c.get("/api/state", headers={**ok, "X-Talos-Pin": "1"}).status_code == 401
        assert c.get("/api/state", headers={**ok, "X-Talos-Pin": "ção".encode()}).status_code == 401
        assert c.get("/api/state", headers={**ok, "Tailscale-User-Login": "x@y.z"}).status_code == 403
        for path in ("/api/agenda", "/api/memory", "/api/vault/keys", "/api/usage", "/api/sentinel/rules",
                     "/api/settings", "/api/tasks", "/api/approvals", "/api/messages"):
            assert c.get(path, headers={"Tailscale-User-Login": "lucas@example.com"}).status_code == 401, path
        assert c.get("/health").status_code == 200


# ------------------------------------------------------------------ takeover e pausa
def test_takeover_roundtrip(client: TestClient, h2: Harness) -> None:
    r = client.post("/api/takeover", json={"active": True})
    assert r.json()["changed"] is True and r.json()["takeover"]["active"] is True
    assert h2.app.control.takeover_active()
    assert client.post("/api/takeover", json={"active": True}).json()["changed"] is False
    assert client.get("/api/state").json()["takeover"]["active"] is True
    r = client.post("/api/takeover", json={"active": False})
    assert r.json()["changed"] is True and not h2.app.control.takeover_active()
    assert client.post("/api/takeover", json={"active": False}).json()["changed"] is False


def test_pause_resume_and_mascot(client: TestClient) -> None:
    assert client.post("/api/pause").json()["changed"] is True
    st = client.get("/api/state").json()
    assert st["paused"] is True and st["pause"]["by"] == "app:local" and st["mascot"]["state"] == "paused"
    assert client.post("/api/resume").json()["changed"] is True
    assert client.get("/api/state").json()["mascot"]["state"] == "idle"


# ------------------------------------------------------------------ aprovações (compatível + detalhes)
def test_approvals_keep_card_and_add_details(client: TestClient, h2: Harness) -> None:
    aid = _proposal(h2)
    items = client.get("/api/approvals").json()
    a = next(x for x in items if x["id"] == aid)
    assert "Aprovação necessária" in a["card"] and a["status"] == "pending" and "payload_json" not in a
    d = a["details"]
    assert d["verb"] == "Aprovar e enviar" and d["action"] == "enviar email"
    assert d["task_title"] == "Ligar o gás em casa"
    assert d["to"][0]["address"] == "apoio@empresa-exemplo.pt" and d["to"][0]["status"] == "contato_oficial"
    assert "Rua das Flores 12" in d["body"] and "123456789" in d["body"]  # o Lucas vê os valores reais
    assert d["personal_data"] == ["morada", "NIF"]
    assert d["risk"] in ("médio", "alto") and d["reason"] == "email oficial de apoio"
    assert client.get(f"/api/approvals/{aid}").json()["id"] == aid
    assert [x["id"] for x in client.get("/api/approvals", params={"status": "pending"}).json()] == [aid]
    assert client.get("/api/approvals/9999").status_code == 404


def test_decide_from_app(client: TestClient, h2: Harness) -> None:
    aid = _proposal(h2)
    r = client.post(f"/api/approvals/{aid}/decide", json={"decision": "edit", "note": "mais curto"})
    assert r.json()["ok"] is True
    assert h2.app.approvals.get(aid).status == "superseded"
    r = client.post(f"/api/approvals/{aid}/decide", json={"decision": "approve"})
    assert r.json()["ok"] is False  # já não está ativa


def test_screenshot(client: TestClient, h2: Harness) -> None:
    png = b"\x89PNG\r\n\x1a\nfake"
    t = h2.app.tasks.create("Formulário", "")
    a = h2.app.approvals.create(task_id=t.id, kind="browser.submit", payload={
        "summary": "Submeter", "screenshot": base64.b64encode(png).decode()})
    assert client.get("/api/approvals").json()[0]["details"]["screenshot"] is True
    r = client.get(f"/api/approvals/{a.id}/screenshot")
    assert r.status_code == 200 and r.content == png and r.headers["content-type"] == "image/png"
    other = _proposal(h2)
    assert client.get(f"/api/approvals/{other}/screenshot").status_code == 404


# ------------------------------------------------------------------ agenda
def test_agenda(client: TestClient, h2: Harness) -> None:
    t = h2.app.tasks.create("Ligar o gás em casa", "")
    soon = utcnow() + timedelta(days=2)
    with h2.app.db.session() as s:
        s.add(Watch(task_id=t.id, kind="email_thread", target="thread-1", next_check_at=soon,
                    followup_policy_json={"max": 2}, followups_sent=1))
        s.add(Watch(task_id=t.id, kind="email_thread", target="thread-old", status="done"))
        s.add(Schedule(kind="briefing", rrule="FREQ=DAILY;BYHOUR=8;BYMINUTE=30", prompt="briefing", next_run_at=soon))
        s.add(Schedule(kind="prompt", rrule="FREQ=DAILY", enabled=False))
        s.add(Goal(title="Correr 10 km", why="saúde", cadence="semanal", status="active", next_checkin_at=soon))
        s.commit()
    ag = client.get("/api/agenda").json()
    assert len(ag["watches"]) == 1
    w = ag["watches"][0]
    assert w["task_title"] == "Ligar o gás em casa" and w["followups_sent"] == 1 and w["max_followups"] == 2
    assert w["target"] == ""  # threadId não interessa ao Lucas
    assert [x["kind"] for x in ag["schedules"]] == ["briefing"]
    assert ag["goals"][0]["title"] == "Correr 10 km"


# ------------------------------------------------------------------ memória
def test_memory_crud(client: TestClient, h2: Harness) -> None:
    f1 = h2.app.memory.note("cafe", "sem açúcar", scope="preferencias")
    h2.app.memory.note("cidade", "Lisboa")
    facts = client.get("/api/memory").json()
    assert {f["key"] for f in facts} == {"cafe", "cidade"}
    assert [f["key"] for f in client.get("/api/memory", params={"q": "açúcar"}).json()] == ["cafe"]
    r = client.put(f"/api/memory/{f1.id}", json={"value": "com canela"})
    assert r.status_code == 200 and r.json()["value"] == "com canela" and r.json()["source"] == "dito"
    with h2.app.db.session() as s:
        assert s.get(MemoryFact, f1.id).value == "com canela"
    assert client.put(f"/api/memory/{f1.id}", json={"value": "x", "key": "cidade", "scope": "geral"}).status_code == 409
    assert client.put("/api/memory/999", json={"value": "x"}).status_code == 404
    assert client.put(f"/api/memory/{f1.id}", json={"value": ""}).status_code == 422
    assert client.delete(f"/api/memory/{f1.id}").json() == {"ok": True}
    assert client.delete(f"/api/memory/{f1.id}").status_code == 404


# ------------------------------------------------------------------ cofre: só chaves, escrita cega
def test_vault_never_returns_values(client: TestClient, h2: Harness) -> None:
    h2.app.vault.set("google.token", "ya29.segredo-muito-secreto")
    r = client.get("/api/vault/keys")
    keys = {k["key"]: k for k in r.json()}
    assert {"dados.morada", "dados.nif", "google.token"} <= set(keys)
    assert keys["dados.nif"]["kind"] == "dado_pessoal" and keys["google.token"]["kind"] == "segredo"
    for secret in ("123456789", "Rua das Flores", "ya29.segredo"):
        assert secret not in r.text

    r = client.put("/api/vault/dados.iban", json={"value": "PT50000201231234567890154"})
    assert r.status_code == 200 and "PT50" not in r.text and r.json()["kind"] == "dado_pessoal"
    assert h2.app.vault.get("dados.iban") == "PT50000201231234567890154"
    r = client.put("/api/vault/dados.nif", json={"value": "987654321"})
    assert r.status_code == 200 and "987654321" not in r.text
    assert client.put("/api/vault/google.token", json={"value": "novo"}).status_code == 200  # editar existente
    assert client.put("/api/vault/servico.senha", json={"value": "x"}).status_code == 400  # segredo novo: CLI
    assert client.put("/api/vault/Chave Má", json={"value": "x"}).status_code == 400
    assert client.put("/api/vault/dados.x", json={"value": ""}).status_code == 422
    assert client.get("/api/vault/dados.nif").status_code in (404, 405)  # não existe leitura de valor


# ------------------------------------------------------------------ uso, regras, ajustes
def test_usage(client: TestClient, h2: Harness) -> None:
    with h2.app.db.session() as s:
        s.add(UsageLog(model="sonnet", turns=3, input_tokens=100, output_tokens=50, notional_cost_usd=0.12))
        s.add(UsageLog(model="haiku", turns=1, notional_cost_usd=0.01, is_error=True))
        s.add(UsageLog(model="sonnet", turns=9, created_at=utcnow() - timedelta(days=30)))
        s.commit()
    u = client.get("/api/usage").json()
    assert u["daily_limit"] == 30 and u["plan"] == "pro" and len(u["days"]) == 7  # padrão do plano Pro
    assert u["today"]["runs"] == 2 and u["today"]["turns"] == 4 and u["today"]["errors"] == 1
    assert u["today"]["cost_usd"] == pytest.approx(0.13)
    assert u["models_today"] == {"sonnet": 1, "haiku": 1}
    assert sum(d["runs"] for d in u["days"]) == 2


def test_sentinel_rules_and_settings(client: TestClient, h2: Harness) -> None:
    r = client.get("/api/sentinel/rules").json()
    assert "rules:" in r["yaml"] and r["classifier"] is False
    (h2.app.settings.workspace_dir / "CLAUDE.md").write_text("# Talos — agente pessoal do Lucas\n")
    st = client.get("/api/settings").json()
    assert st["persona"].startswith("# Talos")
    conn = {c["id"]: c for c in st["connectors"]}
    assert conn["gmail"]["ok"] is True and conn["telegram"]["ok"] is True and conn["browser"]["ok"] is False
    assert st["pin_required"] is False and st["quiet_hours"]["window"] == "00:00-00:00"


# ------------------------------------------------------------------ conversa (compatível)
async def test_messages_roundtrip(h2: Harness) -> None:
    with TestClient(build_api(h2.app, h2.gw, static_dir=None)) as c:
        r = c.post("/api/messages", json={"text": "olá"})
        assert r.json() == {"ok": True, "answer": None}
        assert c.post("/api/messages", json={"text": ""}).status_code == 422
        msgs = c.get("/api/messages").json()
        assert msgs[-1]["role"] == "user" and msgs[-1]["content"] == "olá" and msgs[-1]["channel"] == "app"
        assert len(c.get("/api/messages", params={"limit": 1}).json()) == 1


# ------------------------------------------------------------------ WebSocket tipado
def test_typed_event_mapping() -> None:
    assert typed_event({"type": "message", "task_id": None, "payload": {"role": "user"}})["type"] == "message"
    assert typed_event({"type": "approval_created", "task_id": 1, "payload": {}})["type"] == "approval_created"
    te = typed_event({"type": "tool_call", "task_id": 3, "payload": {"tool": "WebSearch"}, "id": 9,
                      "created_at": "2026-10-07T11:00:00+00:00"})
    assert te == {"type": "task_event", "kind": "tool_call", "task_id": 3, "payload": {"tool": "WebSearch"},
                  "id": 9, "created_at": "2026-10-07T11:00:00+00:00"}


def test_ws_streams_typed_events_and_mascot(client: TestClient, h2: Harness) -> None:
    t = h2.app.tasks.create("Ligar o gás em casa", "")
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "mascot_state" and first["payload"]["state"] == "idle"
        h2.app.bus.emit("working", {"task_id": t.id}, task_id=t.id, persist=False)
        assert ws.receive_json() == {"type": "task_event", "kind": "working", "task_id": t.id,
                                     "payload": {"task_id": t.id}}
        m = ws.receive_json()
        assert m["type"] == "mascot_state" and m["payload"]["state"] == "working"
        assert "Ligar o gás em casa" in m["payload"]["status"]
        h2.app.bus.emit("message", {"role": "assistant", "content": "Enviado", "mascot": "approved"},
                        persist=False)
        msg = ws.receive_json()
        assert msg["type"] == "message" and msg["payload"]["content"] == "Enviado"
        reaction = ws.receive_json()["payload"]
        assert reaction["state"] == "approved" and reaction["once"] is True and reaction["base"] == "working"
        _proposal(h2)
        types = [ws.receive_json()["type"] for _ in range(3)]
        assert "approval_created" in types and "task_event" in types


def test_ws_requires_pin_when_configured(h2: Harness) -> None:
    h2.app.settings.app_pin = "4321"
    with TestClient(build_api(h2.app, h2.gw, static_dir=None)) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "pin": "0000"})
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4401
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "pin": "4321"})
            assert ws.receive_json()["type"] == "mascot_state"


def test_ws_tailscale_allowlist(h2: Harness) -> None:
    h2.app.settings.allowed_tailscale_logins = "lucas@example.com"
    with TestClient(build_api(h2.app, h2.gw, static_dir=None)) as c:
        with pytest.raises(WebSocketDisconnect) as exc, c.websocket_connect("/ws") as ws:
            ws.receive_json()
        assert exc.value.code == 4403


# ------------------------------------------------------------------ app estático (SPA)
@pytest.fixture
def dist(tmp_path: Path) -> Path:
    d = tmp_path / "dist"
    (d / "static").mkdir(parents=True)
    (d / "assets").mkdir()
    (d / "index.html").write_text("<!doctype html><title>Talos</title>")
    (d / "static" / "index-abc123.js").write_text("console.log('talos')")
    (d / "assets" / "talos.glb").write_bytes(b"glTF")
    (d / "manifest.webmanifest").write_text("{}")
    return d


def test_spa_served_only_when_dist_exists(h2: Harness, dist: Path, tmp_path: Path) -> None:
    with TestClient(build_api(h2.app, h2.gw, static_dir=dist)) as c:
        r = c.get("/")
        assert r.status_code == 200 and "<title>Talos</title>" in r.text and r.headers["cache-control"] == "no-cache"
        assert "<title>Talos</title>" in c.get("/tarefas/3").text  # fallback SPA
        assert "<title>Talos</title>" in c.get("/aprovacoes/12").text
        r = c.get("/static/index-abc123.js")
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        assert c.get("/assets/talos.glb").content == b"glTF"
        assert c.get("/assets/nao-existe.glb").status_code == 404
        assert c.get("/static/velho.js").status_code == 404
        assert c.get("/api/nao-existe").status_code == 404
        assert c.get("/tela/vnc.html").status_code == 404  # é do noVNC, nunca do app
        assert c.get("/ws").status_code == 404
        assert c.get("/../../etc/passwd").status_code in (200, 404)  # nunca sai de dist
        assert "root:" not in c.get("/../../etc/passwd").text
        assert c.get("/api/state").status_code == 200  # a API mantém prioridade
        assert c.get("/health").json()["ok"] is True
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "mascot_state"
    with TestClient(build_api(h2.app, h2.gw, static_dir=tmp_path / "nada")) as c:
        assert c.get("/").status_code == 404
