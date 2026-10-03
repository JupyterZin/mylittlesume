"""Portão de ferramentas: liga a Sentinela às aprovações. Usado pelo runtime real (hooks +
can_use_tool) e pelo FakeRuntime, para que os testes passem pelo mesmo caminho."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from talos.logging import get_logger
from talos.sentinel.policy import Decision, Sentinel, ToolCall

if TYPE_CHECKING:
    from talos.runtime.base import Profile, RunRequest
    from talos.services import Services

log = get_logger("talos.gate")

SYNC_PAUSE_SECONDS = 15 * 60
PURCHASE_RE = re.compile(r"(pagar|comprar|encomendar|checkout|pay|buy|order|purchase)", re.I)
BOOKING_RE = re.compile(r"(reservar|book|reserva)", re.I)


class ToolGate:
    def __init__(self, app: Services, sentinel: Sentinel, req: RunRequest, profile: Profile,
                 allowed: list[str], *, pause_seconds: float = SYNC_PAUSE_SECONDS) -> None:
        self.app = app
        self.sentinel = sentinel
        self.req = req
        self.profile = profile
        self.allowed = allowed
        self.pause_seconds = pause_seconds
        self._cache: dict[str, Decision] = {}
        self.denials: list[str] = []
        self.paused_for_approval: int | None = None
        self.takeover_requested = False

    def _call(self, name: str, inp: dict[str, Any], tool_use_id: str | None) -> ToolCall:
        return ToolCall(name=name, input=inp or {}, task_id=self.req.task_id, profile=self.profile.name,
                        user_request=self.req.user_request, tool_use_id=tool_use_id,
                        page_summary=self._page_summary(name))

    def _page_summary(self, name: str) -> str:
        if not name.startswith("mcp__playwright__"):
            return ""
        return "\n".join(f"{ref}: {txt}" for ref, txt in list(self.sentinel.snapshots._refs.items())[-60:])

    async def pre(self, name: str, inp: dict[str, Any], tool_use_id: str | None = None) -> Decision:
        if tool_use_id and tool_use_id in self._cache:
            return self._cache[tool_use_id]
        d = await self.sentinel.evaluate(self._call(name, inp, tool_use_id), self.allowed)
        if tool_use_id:
            self._cache[tool_use_id] = d
        if d.action in ("deny", "takeover"):
            self.denials.append(f"{name}: {d.reason}")
        return d

    def post(self, name: str, response: Any) -> None:
        if name.startswith("mcp__playwright__"):
            text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, default=str)
            self.sentinel.snapshots.ingest(text.replace("\\n", "\n"))

    # ---------- ask: pausa síncrona ----------
    async def on_ask(self, name: str, inp: dict[str, Any], d: Decision) -> tuple[bool, str]:
        call = self._call(name, inp, None)
        kind = self._kind_for(name, inp, d)
        data_keys = sorted({h.key for h in d.egress_hits if h.key})
        if name == "mcp__talos__vault_fill" and str(inp.get("key", "")).startswith("dados."):
            data_keys = sorted(set(data_keys) | {inp["key"]})
        screenshot, page_url = None, ""
        if (name.startswith("mcp__playwright__") or name == "mcp__talos__vault_fill") and self.app.browser is not None:
            try:
                screenshot = await self.app.browser.screenshot()
                page_url = await self.app.browser.current_url()
            except Exception as e:
                log.warning("screenshot_failed", error=str(e))
        summary = self._summary(name, inp, d) + (f"\nPágina: {page_url}" if page_url else "")
        payload = {"summary": summary, "tool": name, "input": _redact_input(inp), "_fingerprint": call.fingerprint(),
                   "_data_keys": data_keys, "screenshot": screenshot, "_host": urlparse(page_url).hostname or ""}
        try:
            action = self.app.approvals.create(task_id=self.req.task_id, kind=kind, payload=payload,
                                               preview=summary, reason=d.reason)
        except Exception as e:
            return False, f"Bloqueado: não consegui criar a proposta de aprovação ({e})."
        title = ""
        if self.req.task_id and (t := self.app.tasks.get(self.req.task_id)):
            title = t.title
        await self.app.notifier.send_card(action, task_title=title)
        if screenshot:
            for ch in self.app.channels.values():
                try:
                    await ch.send_photo(self.app.notifier.owner_chat, screenshot, f"Proposta #{action.id}")
                except Exception:
                    pass
        status = await self.app.approvals.wait_for(action.id, self.pause_seconds)
        if status == "approved":
            self.app.approvals.mark_executed(action.id, {"sync": True})
            return True, ""
        if status == "timeout":
            self.paused_for_approval = action.id
            if self.req.task_id:
                self.app.tasks.update(self.req.task_id, status="waiting_approval")
            return False, (f"Pausado aguardando aprovação do Lucas (proposta #{action.id}). Não tente outra via: "
                           "termine esta execução; a sessão será retomada quando ele decidir.")
        return False, f"O Lucas não aprovou (proposta #{action.id}: {status}). Não faça esta ação."

    async def on_takeover(self, name: str, inp: dict[str, Any], d: Decision) -> str:
        self.takeover_requested = True
        self.app.bus.emit("takeover_requested", {"tool": name, "reason": d.reason}, task_id=self.req.task_id)
        await self.app.notifier.notify(
            f"🖐️ Preciso que você assuma a Tela: {d.reason}. Abra /tela, faça essa parte e toque em "
            "\"Devolver ao Talos\".", urgent=True, task_id=self.req.task_id, mascot="blocked")
        if self.req.task_id:
            self.app.tasks.update(self.req.task_id, status="waiting_external")
        return ("TAKEOVER: este passo (senha, código ou cartão) só o Lucas pode fazer. Já pedi para ele assumir a "
                "Tela. Não tente contornar; termine esta execução e espere ele devolver o controle.")

    @staticmethod
    def _kind_for(name: str, inp: dict[str, Any], d: Decision) -> str:
        if d.source == "egress" or name == "mcp__talos__vault_fill":
            return "share_data"
        text = json.dumps(inp, ensure_ascii=False)
        if PURCHASE_RE.search(text):
            return "purchase"
        if BOOKING_RE.search(text):
            return "booking"
        return "browser.submit"

    def _summary(self, name: str, inp: dict[str, Any], d: Decision) -> str:
        short = name.replace("mcp__playwright__browser_", "navegador: ").replace("mcp__talos__", "")
        target = inp.get("element") or inp.get("field_description") or inp.get("url") or ""
        real = ""
        t = inp.get("target")
        if isinstance(t, str) and (txt := self.sentinel.snapshots.lookup(t)):
            real = f" (elemento real: {txt})"
        return f"{short} → {target}{real}\nMotivo da pausa: {d.reason}"


def _redact_input(inp: dict[str, Any]) -> dict[str, Any]:
    out = dict(inp)
    for k in ("text", "value"):
        if k in out and isinstance(out[k], str) and len(out[k]) > 0:
            out[k] = out[k][:200]
    return out
