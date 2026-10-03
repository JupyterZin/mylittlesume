"""API HTTP + WebSocket para o PWA (SPEC §10). Exposta só via `tailscale serve`."""

from __future__ import annotations

import asyncio
import hmac
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlmodel import col, select

from talos import __version__
from talos.db.models import Message, PendingAction, TaskEvent

if TYPE_CHECKING:
    from talos.channels.gateway import Gateway
    from talos.services import Services


class Decide(BaseModel):
    decision: str
    note: str = ""


class Say(BaseModel):
    text: str


def build_api(app: Services, gateway: Gateway) -> FastAPI:
    api = FastAPI(title="Talos", version=__version__, docs_url=None, redoc_url=None)
    s = app.settings
    allowed_logins = {x.strip().lower() for x in s.allowed_tailscale_logins.split(",") if x.strip()}

    def auth(tailscale_user_login: str | None = Header(default=None),
             x_talos_pin: str | None = Header(default=None)) -> str:
        if allowed_logins and (tailscale_user_login or "").lower() not in allowed_logins:
            raise HTTPException(403, "identidade Tailscale fora da allowlist")
        if s.app_pin and not hmac.compare_digest(x_talos_pin or "", s.app_pin):
            raise HTTPException(401, "PIN inválido")
        return tailscale_user_login or "local"

    @api.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "paused": app.control.is_paused(),
                "jobs": app.queue.counts(), "monitor": app.db.get_state("monitor").get("last_tick"),
                "auth_mode": s.auth_mode}

    @api.get("/api/tasks")
    def tasks(_: str = Depends(auth)) -> list[dict[str, Any]]:
        return [t.model_dump(mode="json") for t in app.tasks.list(limit=100)]

    @api.get("/api/tasks/{task_id}/events")
    def task_events(task_id: int, _: str = Depends(auth)) -> list[dict[str, Any]]:
        with app.db.session() as ss:
            rows = ss.exec(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(col(TaskEvent.id)))
            return [r.model_dump(mode="json") for r in rows]

    @api.get("/api/approvals")
    def approvals(_: str = Depends(auth)) -> list[dict[str, Any]]:
        from talos.channels.cards import render

        values = app.vault.personal_values()
        with app.db.session() as ss:
            rows = list(ss.exec(select(PendingAction).order_by(col(PendingAction.id).desc()).limit(50)))
        return [{**r.model_dump(mode="json", exclude={"payload_json"}), "card": render(r, values, limit=100_000)}
                for r in rows]

    @api.post("/api/approvals/{action_id}/decide")
    async def decide(action_id: int, body: Decide, who: str = Depends(auth)) -> dict[str, Any]:
        if body.decision == "edit":
            res = await app.approvals.decide(action_id, "edit", via="app", note=body.note)
        else:
            res = await app.approvals.decide(action_id, body.decision, via="app", note=body.note)
        if res.ok and res.action and body.decision in ("approve", "reject"):
            await app.notifier.close_cards(res.action, f"{res.message} (pelo app)")
        return {"ok": res.ok, "message": res.message}

    @api.get("/api/messages")
    def messages(_: str = Depends(auth)) -> list[dict[str, Any]]:
        with app.db.session() as ss:
            rows = list(ss.exec(select(Message).order_by(col(Message.id).desc()).limit(100)))
        return [r.model_dump(mode="json") for r in reversed(rows)]

    @api.post("/api/messages")
    async def say(body: Say, _: str = Depends(auth)) -> dict[str, Any]:
        answer = await gateway.on_text("app", "app", body.text)
        return {"ok": True, "answer": answer}

    @api.post("/api/pause")
    async def pause(who: str = Depends(auth)) -> dict[str, Any]:
        return {"changed": await gateway.orch.pause(by=f"app:{who}")}

    @api.post("/api/resume")
    async def resume(who: str = Depends(auth)) -> dict[str, Any]:
        return {"changed": await gateway.orch.resume(by=f"app:{who}")}

    @api.websocket("/ws")
    async def ws(sock: WebSocket) -> None:
        login = (sock.headers.get("tailscale-user-login") or "").lower()
        if allowed_logins and login not in allowed_logins:
            await sock.close(code=4403)
            return
        await sock.accept()
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        unsubscribe = app.bus.subscribe(lambda ev: q.put_nowait(ev) if not q.full() else None)
        try:
            while True:
                ev = await q.get()
                await sock.send_json(ev)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            unsubscribe()

    return api
