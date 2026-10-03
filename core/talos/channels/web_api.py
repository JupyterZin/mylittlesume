"""API HTTP + WebSocket para o PWA (SPEC §10). Exposta só via `tailscale serve`.

Tudo atrás de `auth` (identidade Tailscale + allowlist + PIN opcional), menos `/health` e os
ficheiros estáticos do app (o "esqueleto" não tem dados; sem PIN o app só mostra o pedido de PIN).

WebSocket `/ws` com eventos tipados:
- `message`            → mensagem da conversa (Lucas, Talos ou notificação);
- `approval_created`   → nova proposta pendente (`payload.action_id`);
- `approval_decided`   → proposta decidida (`payload.action_id`, `payload.decision`);
- `task_event`         → qualquer outro evento do bus (`kind` = tipo original);
- `mascot_state`       → estado do mascote calculado no servidor (`channels/mascot.py`).
Com PIN configurado, a primeira mensagem do cliente tem de ser `{"type": "auth", "pin": "…"}`.
O cliente manda `{"type": "presence", "visible": bool}` ao abrir, ao mudar de visibilidade e a cada
25 s: o notifier só manda push de respostas quando nenhum app está visível.

Web Push: `GET /api/push/key` (chave VAPID pública), `POST|DELETE /api/push/subscribe`, `POST /api/push/test`.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hmac
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, func, select

from talos import __version__
from talos.channels.cards import RISK, VERB, render
from talos.channels.mascot import MascotContext, MascotMapper
from talos.channels.push import PushError, PushSender, ping_message
from talos.clock import as_utc, in_quiet_hours, local_date, local_to_utc, to_local, utcnow
from talos.db.models import (
    Conversation,
    Goal,
    MemoryFact,
    Message,
    PendingAction,
    Schedule,
    Task,
    TaskEvent,
    UsageLog,
    VaultItem,
    Watch,
)
from talos.vault.placeholders import PlaceholderError, find_keys, label, resolve
from talos.vault.store import KEY_RE, PERSONAL_PREFIX, VaultError

if TYPE_CHECKING:
    from talos.channels.gateway import Gateway
    from talos.services import Services

REPO_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_TYPES = ("message", "approval_created", "approval_decided")
STATIC_RESERVED = ("api", "ws", "health", "tela")  # /tela é o noVNC (tailscale serve), nunca o app
IMMUTABLE_DIR = "static"  # build.assetsDir do Vite: ficheiros com hash, cache longa
RECIPIENT_NOTES = {
    "fornecido": "indicado por você",
    "contato_oficial": "fonte oficial verificada",
    "participante": "já participa da conversa",
    "novo": "destinatário novo",
}


class Decide(BaseModel):
    decision: str
    note: str = ""


class Say(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


class TakeoverIn(BaseModel):
    active: bool


class FactIn(BaseModel):
    value: str = Field(min_length=1, max_length=4000)
    key: str | None = Field(default=None, min_length=1, max_length=200)
    scope: str | None = Field(default=None, min_length=1, max_length=100)


class VaultValueIn(BaseModel):
    value: str = Field(min_length=1, max_length=4000)


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class PushSubscriptionIn(BaseModel):
    """`PushSubscription.toJSON()` do navegador (+ o endpoint antigo, se mudou)."""

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeysIn
    old_endpoint: str | None = Field(default=None, max_length=2048)


class PushEndpointIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


def default_static_dir() -> Path:
    return Path(os.environ.get("TALOS_APP_DIST") or REPO_ROOT / "app" / "dist")


HEARTBEAT_SECONDS = 20


def build_api(app: Services, gateway: Gateway, *, static_dir: Path | None | bool = True) -> FastAPI:
    """`static_dir=True` usa `app/dist` (ou `TALOS_APP_DIST`); `None`/`False` não serve o app."""
    api = FastAPI(title="Talos", version=__version__, docs_url=None, redoc_url=None)
    s = app.settings
    allowed_logins = {x.strip().lower() for x in s.allowed_tailscale_logins.split(",") if x.strip()}

    def pin_ok(pin: str | None) -> bool:
        return not s.app_pin or hmac.compare_digest((pin or "").encode(), s.app_pin.encode())

    def auth(tailscale_user_login: str | None = Header(default=None),
             x_talos_pin: str | None = Header(default=None)) -> str:
        if allowed_logins and (tailscale_user_login or "").lower() not in allowed_logins:
            raise HTTPException(403, "identidade Tailscale fora da allowlist")
        if not pin_ok(x_talos_pin):
            raise HTTPException(401, "PIN inválido")
        return tailscale_user_login or "local"

    # ------------------------------------------------------------ mascote + difusão
    def pending_count() -> int:
        with app.db.session() as ss:
            return int(ss.exec(select(func.count(col(PendingAction.id)))
                               .where(PendingAction.status == "pending")).one())

    def task_title(task_id: int) -> str | None:
        t = app.tasks.get(task_id)
        return t.title if t else None

    def quiet_now(now: datetime | None = None) -> bool:
        return in_quiet_hours(now or utcnow(), s.timezone, s.quiet_window)

    def quiet_until() -> str:
        end = s.quiet_window[1]
        return f"{end.hour:02d}:{end.minute:02d}"

    mapper = MascotMapper(MascotContext(
        paused=app.control.is_paused, pending=pending_count, quiet=quiet_now,
        takeover=app.control.takeover_active, task_title=task_title, quiet_until=quiet_until, tz=s.timezone,
    ))
    clients: dict[asyncio.Queue[dict[str, Any]], asyncio.AbstractEventLoop] = {}

    def on_bus(ev: dict[str, Any]) -> None:
        out = [typed_event(ev)]
        try:
            change = mapper.feed(ev)
        except Exception:
            change = None
        if change is not None:
            out.append({"type": "mascot_state", "payload": change})
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        for q, loop in list(clients.items()):
            for msg in out:
                if loop is current:
                    _offer(q, msg)
                else:  # evento emitido noutra thread: entrega pelo loop dono da fila
                    with contextlib.suppress(RuntimeError):
                        loop.call_soon_threadsafe(_offer, q, msg)

    app.bus.subscribe(on_bus)
    api.state.mascot = mapper

    # ------------------------------------------------------------ básicos
    @api.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "paused": app.control.is_paused(),
                "jobs": app.queue.counts(), "monitor": app.db.get_state("monitor").get("last_tick"),
                "auth_mode": s.auth_mode}

    @api.get("/api/state")
    def state(who: str = Depends(auth)) -> dict[str, Any]:
        pause = app.db.get_state("pause")
        tk = app.control.takeover_state()
        rl = app.control.rate_limited_until()
        if rl:
            try:
                if datetime.fromisoformat(rl) <= utcnow():
                    rl = None
            except ValueError:
                pass
        return {
            "agent_name": s.agent_name,
            "version": __version__,
            "user": who,
            "paused": bool(pause.get("paused")),
            "pause": {"since": pause.get("since"), "by": pause.get("by")} if pause.get("paused") else None,
            "takeover": {"active": bool(tk.get("active")), "since": tk.get("since"), "by": tk.get("by")},
            "rate_limited_until": rl,
            "pending_approvals": pending_count(),
            "mascot": mapper.snapshot(),
            "quiet_hours": {"window": s.quiet_hours, "active": quiet_now(), "until": quiet_until()},
            "timezone": s.timezone,
            "auth_mode": s.auth_mode,
            "mascot_model": s.mascot_model,
        }

    # ------------------------------------------------------------ tarefas
    @api.get("/api/tasks")
    def tasks(_: str = Depends(auth)) -> list[dict[str, Any]]:
        return [t.model_dump(mode="json") for t in app.tasks.list(limit=100)]

    @api.get("/api/tasks/{task_id}")
    def task_one(task_id: int, _: str = Depends(auth)) -> dict[str, Any]:
        t = app.tasks.get(task_id)
        if t is None:
            raise HTTPException(404, "tarefa não encontrada")
        return t.model_dump(mode="json")

    @api.get("/api/tasks/{task_id}/events")
    def task_events(task_id: int, _: str = Depends(auth)) -> list[dict[str, Any]]:
        with app.db.session() as ss:
            rows = ss.exec(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(col(TaskEvent.id)))
            return [r.model_dump(mode="json") for r in rows]

    # ------------------------------------------------------------ aprovações
    def serialize_action(a: PendingAction, values: dict[str, str], titles: dict[int, str]) -> dict[str, Any]:
        title = titles.get(a.task_id or 0, "")
        return {**a.model_dump(mode="json", exclude={"payload_json"}),
                "card": render(a, values, title, limit=100_000),
                "details": approval_details(a, values, title)}

    def titles_for(rows: list[PendingAction]) -> dict[int, str]:
        ids = {r.task_id for r in rows if r.task_id}
        if not ids:
            return {}
        with app.db.session() as ss:
            return {t.id: t.title for t in ss.exec(select(Task).where(col(Task.id).in_(ids)))}

    @api.get("/api/approvals")
    def approvals(status: str | None = None, _: str = Depends(auth)) -> list[dict[str, Any]]:
        values = app.vault.personal_values()
        with app.db.session() as ss:
            q = select(PendingAction).order_by(col(PendingAction.id).desc()).limit(50)
            if status:
                q = q.where(PendingAction.status == status)
            rows = list(ss.exec(q))
        titles = titles_for(rows)
        return [serialize_action(r, values, titles) for r in rows]

    @api.get("/api/approvals/{action_id}")
    def approval_one(action_id: int, _: str = Depends(auth)) -> dict[str, Any]:
        a = app.approvals.get(action_id)
        if a is None:
            raise HTTPException(404, "proposta não encontrada")
        return serialize_action(a, app.vault.personal_values(), titles_for([a]))

    @api.get("/api/approvals/{action_id}/screenshot")
    def approval_screenshot(action_id: int, _: str = Depends(auth)) -> Response:
        a = app.approvals.get(action_id)
        raw = (a.payload_json or {}).get("screenshot") if a else None
        data = _image_bytes(raw)
        if data is None:
            raise HTTPException(404, "sem captura de tela")
        return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @api.post("/api/approvals/{action_id}/decide")
    async def decide(action_id: int, body: Decide, who: str = Depends(auth)) -> dict[str, Any]:
        res = await app.approvals.decide(action_id, body.decision, via="app", note=body.note)
        if res.ok and res.action and body.decision in ("approve", "reject"):
            await app.notifier.close_cards(res.action, f"{res.message} (pelo app)")
        return {"ok": res.ok, "message": res.message}

    # ------------------------------------------------------------ conversa
    @api.get("/api/messages")
    def messages(limit: int = Query(default=100, ge=1, le=500), _: str = Depends(auth)) -> list[dict[str, Any]]:
        with app.db.session() as ss:
            rows = list(ss.exec(select(Message).order_by(col(Message.id).desc()).limit(limit)))
            channels = {c.id: c.channel for c in ss.exec(select(Conversation))}
        return [{**r.model_dump(mode="json"), "channel": channels.get(r.conversation_id, "")} for r in reversed(rows)]

    @api.post("/api/messages")
    async def say(body: Say, _: str = Depends(auth)) -> dict[str, Any]:
        answer = await gateway.on_text("app", "app", body.text)
        return {"ok": True, "answer": answer}

    # ------------------------------------------------------------ controle
    @api.post("/api/pause")
    async def pause(who: str = Depends(auth)) -> dict[str, Any]:
        return {"changed": await gateway.orch.pause(by=f"app:{who}")}

    @api.post("/api/resume")
    async def resume(who: str = Depends(auth)) -> dict[str, Any]:
        return {"changed": await gateway.orch.resume(by=f"app:{who}")}

    @api.post("/api/takeover")
    async def takeover(body: TakeoverIn, who: str = Depends(auth)) -> dict[str, Any]:
        if body.active:
            changed = await gateway.orch.takeover_start(by=f"app:{who}")
        else:
            changed = await gateway.orch.takeover_end(by=f"app:{who}")
        tk = app.control.takeover_state()
        return {"changed": changed, "takeover": {"active": bool(tk.get("active")), "since": tk.get("since"),
                                                 "by": tk.get("by")}}

    # ------------------------------------------------------------ agenda
    @api.get("/api/agenda")
    def agenda(_: str = Depends(auth)) -> dict[str, Any]:
        with app.db.session() as ss:
            watches = list(ss.exec(select(Watch).where(Watch.status == "active")
                                   .order_by(col(Watch.next_check_at))))
            schedules = list(ss.exec(select(Schedule).where(Schedule.enabled == True)  # noqa: E712
                                     .order_by(col(Schedule.next_run_at))))
            goals = list(ss.exec(select(Goal).where(col(Goal.status).in_(("proposed", "active")))
                                 .order_by(col(Goal.next_checkin_at))))
            ids = {w.task_id for w in watches if w.task_id} | {x.task_id for x in schedules if x.task_id}
            titles = {t.id: t.title for t in ss.exec(select(Task).where(col(Task.id).in_(ids)))} if ids else {}
        return {
            "watches": [{
                "id": w.id, "task_id": w.task_id, "task_title": titles.get(w.task_id or 0, ""), "kind": w.kind,
                "target": w.target if w.kind == "webpage" else "", "next_check_at": _iso(w.next_check_at),
                "followups_sent": w.followups_sent,
                "max_followups": int((w.followup_policy_json or {}).get("max", s.max_followups)),
                "created_at": _iso(w.created_at),
            } for w in watches],
            "schedules": [{
                "id": x.id, "task_id": x.task_id, "task_title": titles.get(x.task_id or 0, ""), "kind": x.kind,
                "rrule": x.rrule, "prompt": (x.prompt or "")[:280], "next_run_at": _iso(x.next_run_at),
            } for x in schedules],
            "goals": [{
                "id": g.id, "title": g.title, "why": g.why, "cadence": g.cadence, "status": g.status,
                "next_checkin_at": _iso(g.next_checkin_at), "milestones": g.milestones_json or [],
            } for g in goals],
        }

    # ------------------------------------------------------------ memória
    @api.get("/api/memory")
    def memory_list(q: str = "", _: str = Depends(auth)) -> list[dict[str, Any]]:
        return [f.model_dump(mode="json") for f in app.memory.search(q, limit=500)]

    @api.put("/api/memory/{fact_id}")
    def memory_put(fact_id: int, body: FactIn, _: str = Depends(auth)) -> dict[str, Any]:
        with app.db.session() as ss:
            f = ss.get(MemoryFact, fact_id)
            if f is None:
                raise HTTPException(404, "fato não encontrado")
            f.value = body.value.strip()
            if body.key:
                f.key = body.key.strip()
            if body.scope:
                f.scope = body.scope.strip()
            f.source, f.updated_at = "dito", utcnow()  # editado pelo próprio Lucas
            ss.add(f)
            try:
                ss.commit()
            except IntegrityError as e:
                raise HTTPException(409, "já existe um fato com essa chave neste âmbito") from e
            ss.refresh(f)
            return f.model_dump(mode="json")

    @api.delete("/api/memory/{fact_id}")
    def memory_delete(fact_id: int, _: str = Depends(auth)) -> dict[str, Any]:
        if not app.memory.delete(fact_id):
            raise HTTPException(404, "fato não encontrado")
        return {"ok": True}

    # ------------------------------------------------------------ cofre (só chaves; escrita cega)
    @api.get("/api/vault/keys")
    def vault_keys(_: str = Depends(auth)) -> list[dict[str, Any]]:
        with app.db.session() as ss:
            rows = list(ss.exec(select(VaultItem.key, VaultItem.kind, VaultItem.updated_at)
                                .order_by(col(VaultItem.key))))
        return [{"key": k, "kind": kind, "label": label(k), "updated_at": _iso(upd)} for k, kind, upd in rows]

    @api.put("/api/vault/{key}")
    def vault_put(key: str, body: VaultValueIn, who: str = Depends(auth)) -> dict[str, Any]:
        if not KEY_RE.match(key):
            raise HTTPException(400, "chave inválida (ex.: dados.morada)")
        with app.db.session() as ss:
            exists = ss.get(VaultItem, key) is not None
        if not exists and not key.startswith(PERSONAL_PREFIX):
            raise HTTPException(400, "pelo app só se criam dados pessoais (dados.*); segredos novos: `talos vault set`")
        try:
            app.vault.set(key, body.value)
        except VaultError as e:
            raise HTTPException(400, str(e)) from e
        app.bus.emit("vault_updated", {"key": key, "by": f"app:{who}", "created": not exists})
        with app.db.session() as ss:
            item = ss.get(VaultItem, key)
        return {"ok": True, "key": key, "kind": item.kind if item else "", "label": label(key),
                "updated_at": _iso(item.updated_at if item else None)}

    # ------------------------------------------------------------ uso, regras, ajustes
    @api.get("/api/usage")
    def usage(_: str = Depends(auth)) -> dict[str, Any]:
        now, tz = utcnow(), s.timezone
        today = local_date(now, tz)
        start_local = to_local(now, tz).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
        with app.db.session() as ss:
            rows = list(ss.exec(select(UsageLog).where(col(UsageLog.created_at) >= local_to_utc(start_local))))
        days: dict[str, dict[str, Any]] = {}
        for i in range(6, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            days[d] = {"date": d, "runs": 0, "turns": 0, "input_tokens": 0, "output_tokens": 0,
                       "cost_usd": 0.0, "errors": 0, "rate_limited": 0}
        models: dict[str, int] = {}
        for r in rows:
            d = local_date(r.created_at, tz).isoformat()
            if d not in days:
                continue
            agg = days[d]
            agg["runs"] += 1
            agg["turns"] += r.turns
            agg["input_tokens"] += r.input_tokens
            agg["output_tokens"] += r.output_tokens
            agg["cost_usd"] = round(agg["cost_usd"] + r.notional_cost_usd, 4)
            agg["errors"] += int(r.is_error)
            agg["rate_limited"] += int(r.rate_limited)
            if d == today.isoformat():
                models[r.model] = models.get(r.model, 0) + 1
        return {"auth_mode": s.auth_mode, "daily_limit": s.run_limit, "plan": s.claude_plan,
                "today": days[today.isoformat()], "days": list(days.values()), "models_today": models,
                "rate_limited_until": app.control.rate_limited_until()}

    @api.get("/api/sentinel/rules")
    def sentinel_rules(_: str = Depends(auth)) -> dict[str, Any]:
        from talos.sentinel.policy import RULES_PATH

        text = RULES_PATH.read_text(encoding="utf-8") if RULES_PATH.exists() else ""
        return {"yaml": text, "classifier": bool(s.sentinel_classifier), "path": "core/talos/sentinel/rules.yaml"}

    @api.get("/api/settings")
    def settings_view(_: str = Depends(auth)) -> dict[str, Any]:
        persona_file = Path(s.workspace_dir) / "CLAUDE.md"
        persona = persona_file.read_text(encoding="utf-8") if persona_file.is_file() else ""
        tg = app.channels.get("telegram")
        monitor = app.db.get_state("monitor").get("last_tick")
        connectors = [
            {"id": "gmail", "name": "Gmail", "ok": app.gmail is not None, "detail": s.gmail_address},
            {"id": "calendar", "name": "Google Agenda", "ok": app.calendar is not None, "detail": ""},
            {"id": "drive", "name": "Google Drive", "ok": app.drive is not None, "detail": ""},
            {"id": "telegram", "name": "Telegram", "ok": tg is not None and bool(s.telegram_allowed_chat_id),
             "detail": "" if s.telegram_allowed_chat_id else "chat_id não configurado"},
            {"id": "browser", "name": "Navegador", "ok": app.browser is not None, "detail": s.browser_cdp_endpoint},
            {"id": "monitor", "name": "Monitor do Gmail", "ok": bool(monitor), "detail": monitor or ""},
        ]
        if app.notifier.push is not None:
            n = app.notifier.push.count()
            connectors.append({"id": "push", "name": "Notificações do app", "ok": n > 0 and app.notifier.via("app"),
                               "detail": "desligadas em NOTIFY_CHANNELS" if not app.notifier.via("app")
                               else f"{n} aparelho{'s' if n != 1 else ''}"})
        return {
            "agent_name": s.agent_name, "version": __version__, "timezone": s.timezone, "auth_mode": s.auth_mode,
            "quiet_hours": {"window": s.quiet_hours, "active": quiet_now(), "until": quiet_until()},
            "classifier": bool(s.sentinel_classifier), "pin_required": bool(s.app_pin),
            "daily_run_soft_limit": s.run_limit, "connectors": connectors, "persona": persona,
            "approval_ttl_hours": s.approval_ttl_hours,
        }

    # ------------------------------------------------------------ notificações push (Web Push)
    def push_sender() -> PushSender:
        if app.notifier.push is None:
            raise HTTPException(503, "notificações push indisponíveis neste servidor")
        return app.notifier.push

    @api.get("/api/push/key")
    def push_key(_: str = Depends(auth)) -> dict[str, Any]:
        p = push_sender()
        try:
            key = p.public_key()
        except RuntimeError as e:
            raise HTTPException(500, str(e)) from e
        return {"public_key": key, "enabled": app.notifier.via("app"), "subscriptions": p.count()}

    @api.post("/api/push/subscribe")
    def push_subscribe(body: PushSubscriptionIn, user_agent: str | None = Header(default=None),
                       who: str = Depends(auth)) -> dict[str, Any]:
        p = push_sender()
        try:
            created = p.subscribe(body.endpoint, body.keys.p256dh, body.keys.auth, user_agent=user_agent or "",
                                  replaces=body.old_endpoint or "")
        except PushError as e:
            raise HTTPException(400, str(e)) from e
        if created:
            app.bus.emit("push_subscribed", {"by": f"app:{who}"})
        return {"ok": True, "created": created, "subscriptions": p.count()}

    @api.delete("/api/push/subscribe")
    def push_unsubscribe(body: PushEndpointIn, who: str = Depends(auth)) -> dict[str, Any]:
        p = push_sender()
        removed = p.unsubscribe(body.endpoint)
        if removed:
            app.bus.emit("push_unsubscribed", {"by": f"app:{who}"})
        return {"ok": True, "removed": removed, "subscriptions": p.count()}

    @api.post("/api/push/test")
    async def push_test(_: str = Depends(auth)) -> dict[str, Any]:
        p = push_sender()
        if p.count() == 0:
            raise HTTPException(409, "Nenhum aparelho inscrito. Ligue as notificações primeiro.")
        res = await p.send(ping_message())  # pedido explícito: ignora NOTIFY_CHANNELS e horas de silêncio
        return {"ok": res.sent > 0, **res.as_dict()}

    # ------------------------------------------------------------ tempo real
    @api.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        login = (sock.headers.get("tailscale-user-login") or "").lower()
        if allowed_logins and login not in allowed_logins:
            await sock.close(code=4403)
            return
        await sock.accept()
        if s.app_pin:
            try:
                first = await asyncio.wait_for(sock.receive_json(), timeout=10)
            except Exception:
                first = None
            if not (isinstance(first, dict) and first.get("type") == "auth" and pin_ok(str(first.get("pin") or ""))):
                with contextlib.suppress(Exception):
                    await sock.close(code=4401)
                return
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        clients[q] = asyncio.get_running_loop()
        presence = app.notifier.presence
        presence.update(q, True)  # acabou de abrir: está à frente do Lucas

        async def reader() -> None:
            while True:
                msg = await sock.receive()
                if msg.get("type") == "websocket.disconnect":
                    return
                data = _json_or_none(msg.get("text"))
                if isinstance(data, dict) and data.get("type") == "presence":
                    presence.update(q, bool(data.get("visible")))

        read_task = asyncio.create_task(reader())
        try:
            await sock.send_json({"type": "mascot_state", "payload": mapper.snapshot()})
            while True:
                get_task = asyncio.create_task(q.get())
                done, _ = await asyncio.wait({get_task, read_task}, timeout=HEARTBEAT_SECONDS,
                                             return_when=asyncio.FIRST_COMPLETED)
                if not done:  # sinal de vida: o app deteta ligações mortas (Android em segundo plano)
                    get_task.cancel()
                    await sock.send_json({"type": "heartbeat"})
                    continue
                if get_task not in done:
                    get_task.cancel()
                    break
                await sock.send_json(get_task.result())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            clients.pop(q, None)
            presence.drop(q)
            read_task.cancel()

    # ------------------------------------------------------------ app estático (SPA)
    dist = default_static_dir() if static_dir is True else (static_dir or None)
    if isinstance(dist, Path) and (dist / "index.html").is_file():
        mount_spa(api, dist.resolve())

    return api


def mount_spa(api: FastAPI, root: Path) -> None:
    """Serve `app/dist` com fallback para o index.html. Registrado por último: as rotas da API e o
    `/ws` têm prioridade; `/api/*`, `/tela/*` e ficheiros inexistentes com extensão dão 404."""
    index = root / "index.html"

    @api.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        first = path.split("/", 1)[0]
        if first in STATIC_RESERVED:
            raise HTTPException(404, "não encontrado")
        if path:
            f = (root / path).resolve()
            if f.is_file() and root in f.parents:
                immutable = first == IMMUTABLE_DIR
                return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"
                                                if immutable else "no-cache"})
            if "." in path.rsplit("/", 1)[-1]:
                raise HTTPException(404, "não encontrado")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def _json_or_none(text: str | None) -> Any:
    if not text or len(text) > 4096:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def _offer(q: asyncio.Queue[dict[str, Any]], msg: dict[str, Any]) -> None:
    if not q.full():
        q.put_nowait(msg)


def typed_event(ev: dict[str, Any]) -> dict[str, Any]:
    """Evento do bus → evento tipado do WebSocket (ver docstring do módulo)."""
    t = ev.get("type", "")
    if t in PROTOCOL_TYPES:
        return dict(ev)
    out = {"type": "task_event", "kind": t, "task_id": ev.get("task_id"), "payload": ev.get("payload") or {}}
    if "id" in ev:
        out["id"] = ev["id"]
    if "created_at" in ev:
        out["created_at"] = ev["created_at"]
    return out


def approval_details(a: PendingAction, values: dict[str, str], task_title: str = "") -> dict[str, Any]:
    """Cartão estruturado (SPEC Anexo A): o que sai, para quem, dados pessoais, risco e motivo."""
    p = a.payload_json or {}
    what, verb = VERB.get(a.kind, (a.kind, "Aprovar"))
    recips = [{"address": r.get("address", ""), "status": r.get("status", "novo"),
               "note": RECIPIENT_NOTES.get(r.get("status", "novo"), ""), "source_url": r.get("source_url") or ""}
              for r in p.get("_recipients") or []]
    if not recips and p.get("to"):
        to = p["to"] if isinstance(p["to"], list) else [p["to"]]
        recips = [{"address": str(x), "status": "", "note": "", "source_url": ""} for x in to]
    subject, body = str(p.get("subject") or ""), str(p.get("body") or "")
    keys = sorted(set(find_keys(subject) + find_keys(body) + list(p.get("_data_keys") or [])))
    return {
        "action": what,
        "verb": verb,
        "task_title": task_title,
        "to": recips,
        "subject": _fill(subject, values),
        "when": p.get("when") or "",
        "summary": _fill(str(p.get("summary") or ""), values),
        "body": _fill(body, values) if body else (a.preview_text or ""),
        "personal_data": [label(k) for k in keys],
        "raw_personal": list(p.get("_raw_personal") or []),
        "risk": RISK.get(a.risk, a.risk),
        "risk_level": a.risk,
        "risk_why": p.get("_risk_why") or "",
        "reason": a.reason,
        "screenshot": _image_bytes(p.get("screenshot")) is not None,
    }


def _fill(text: str, values: dict[str, str]) -> str:
    """No cartão o Lucas vê os valores reais (SPEC §7.4)."""
    if not text:
        return ""
    try:
        return resolve(text, values)
    except PlaceholderError:
        return text


def _image_bytes(raw: Any) -> bytes | None:
    if not raw:
        return None
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        data = raw.split(",", 1)[1] if raw.startswith("data:") else raw
        try:
            return base64.b64decode(data, validate=True)
        except (ValueError, TypeError):
            return None
    return None


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else as_utc(dt).isoformat()
