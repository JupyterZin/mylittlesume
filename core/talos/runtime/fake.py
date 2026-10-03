"""FakeRuntime (SPEC §15): respostas roteirizadas que chamam as ferramentas PELO MESMO PORTÃO
(Sentinela + aprovações) que o runtime real. Não consome a assinatura."""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from talos.runtime.base import PROFILES, RunRequest, RunResult, allowed_tools_for
from talos.runtime.gate import ToolGate
from talos.tools.registry import REGISTRY, ToolContext, call_tool, specs_for

if TYPE_CHECKING:
    from talos.sentinel.policy import Sentinel
    from talos.services import Services


@dataclass
class FakeAgent:
    """O que o script recebe: pode chamar ferramentas como o modelo faria."""

    runtime: FakeRuntime
    req: RunRequest
    gate: ToolGate
    ctx: ToolContext
    calls: list[tuple[str, dict[str, Any], str]] = field(default_factory=list)

    async def call(self, name: str, args: dict[str, Any] | None = None) -> str:
        args = args or {}
        d = await self.gate.pre(name, args)
        if d.action == "takeover":
            msg = await self.gate.on_takeover(name, args, d)
            self.calls.append((name, args, "takeover"))
            return msg
        if d.action == "deny":
            self.calls.append((name, args, "deny"))
            return f"Sentinela negou: {d.reason}"
        if d.action == "ask":
            ok, msg = await self.gate.on_ask(name, args, d)
            if not ok:
                self.calls.append((name, args, "ask-denied"))
                return msg
        self.calls.append((name, args, "allow"))
        if name.startswith("mcp__talos__"):
            spec = REGISTRY[name.removeprefix("mcp__talos__")]
            res = await call_tool(spec, self.ctx, args)
            return "\n".join(c.get("text", "") for c in res["content"])
        ext = self.runtime.external_tools.get(name)
        if ext is None:
            return f"(ferramenta externa {name} simulada)"
        out = await ext(args)
        self.gate.post(name, out)
        return out


Script = Callable[[FakeAgent], Awaitable[str]]


class FakeRuntime:
    def __init__(self, app: Services, sentinel: Sentinel, *, pause_seconds: float = 0.2) -> None:
        self.app = app
        self.sentinel = sentinel
        self.pause_seconds = pause_seconds
        self.scripts: list[tuple[Callable[[RunRequest], bool], Script]] = []
        self.external_tools: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {}
        self.requests: list[RunRequest] = []
        self.agents: list[FakeAgent] = []
        self._ids = itertools.count(1)
        self.rate_limit_next = False

    def on(self, predicate: Callable[[RunRequest], bool], script: Script) -> None:
        self.scripts.append((predicate, script))

    def reply(self, text: str, when: Callable[[RunRequest], bool] = lambda r: True) -> None:
        async def s(_a: FakeAgent) -> str:
            return text

        self.on(when, s)

    async def run(self, req: RunRequest) -> RunResult:
        self.requests.append(req)
        if self.rate_limit_next:
            self.rate_limit_next = False
            return RunResult(is_error=True, rate_limited=True, error="rate_limit")
        profile = PROFILES[req.profile]
        allowed = allowed_tools_for(profile)
        gate = ToolGate(self.app, self.sentinel, req, profile, allowed, pause_seconds=self.pause_seconds)
        ctx = ToolContext(app=self.app, task_id=req.task_id, conversation_id=req.conversation_id,
                          profile=profile.name)
        _ = specs_for(profile.name)
        agent = FakeAgent(self, req, gate, ctx)
        self.agents.append(agent)
        script = next((s for p, s in self.scripts if p(req)), None)
        text = await script(agent) if script else "ok"
        notes = list(ctx.notes)
        if gate.paused_for_approval:
            notes.append(f"paused_for_approval:{gate.paused_for_approval}")
        return RunResult(text=text, session_id=req.resume_session_id or f"fake-{uuid.uuid4().hex[:8]}",
                         model=profile.model, num_turns=1 + len(agent.calls), input_tokens=100,
                         output_tokens=20, notes=notes, tool_calls=[c[0] for c in agent.calls])

    async def ask_text(self, prompt: str, profile: str = "classifier") -> str:
        for p, s in self.scripts:
            req = RunRequest(prompt=prompt, profile=profile)
            if p(req):
                return await s(FakeAgent(self, req, None, None))  # type: ignore[arg-type]
        return '{"verdict": "ok", "reason": "fake"}'

    def extra_info(self) -> dict[str, Any]:
        return {"kind": "fake"}
