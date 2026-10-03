"""Contrato do runtime de agente + perfis de modelo (SPEC §13)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

BUILTIN_READ = ["Read", "Glob", "Grep"]
BUILTIN_WRITE = ["Write", "Edit"]
BUILTIN_WEB = ["WebSearch", "WebFetch"]
ALWAYS_DISALLOWED = ["Bash", "BashOutput", "KillShell", "KillBash", "NotebookEdit"]


@dataclass(frozen=True)
class Profile:
    name: str
    model: str  # alias: haiku | sonnet | opus
    max_turns: int
    builtin_tools: tuple[str, ...]
    talos_tools: bool = True
    browser: bool = False
    skills: bool = True


PROFILES: dict[str, Profile] = {
    "main": Profile("main", "sonnet", 30, tuple(BUILTIN_READ + BUILTIN_WRITE + BUILTIN_WEB + ["Skill", "Task"])),
    "task": Profile("task", "sonnet", 30, tuple(BUILTIN_READ + BUILTIN_WRITE + BUILTIN_WEB + ["Skill", "Task"]),
                    browser=True),
    "planner": Profile("planner", "opus", 40,
                       tuple(BUILTIN_READ + BUILTIN_WRITE + BUILTIN_WEB + ["Skill", "Task"]), browser=True),
    "triage": Profile("triage", "haiku", 3, (), talos_tools=False, skills=False),
    "classifier": Profile("classifier", "haiku", 1, (), talos_tools=False, skills=False),
}


def allowed_tools_for(profile: Profile) -> list[str]:
    allowed = list(profile.builtin_tools)
    if profile.talos_tools:
        allowed.append("mcp__talos__*")
    if profile.browser:
        allowed.append("mcp__playwright__*")
    return allowed


@dataclass
class RunRequest:
    prompt: str
    profile: str = "main"
    resume_session_id: str | None = None
    task_id: int | None = None
    conversation_id: int | None = None
    job_id: int | None = None
    user_request: str = ""  # pedido original do Lucas (para o classificador)
    system_append: str = ""
    model_override: str | None = None  # escolhido pelo Sistema 1 (ex.: haiku para conversa leve)


@dataclass
class RunResult:
    text: str = ""
    session_id: str | None = None
    is_error: bool = False
    error: str = ""
    rate_limited: bool = False
    resets_at: datetime | None = None
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    num_turns: int = 0
    duration_ms: int = 0
    cost_usd: float = 0.0
    tool_calls: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    auth_source: str | None = None


class AgentRuntime(Protocol):
    async def run(self, req: RunRequest) -> RunResult: ...

    async def ask_text(self, prompt: str, profile: str = "classifier") -> str:
        """Pergunta simples sem ferramentas (classificador, triagem)."""
        ...

    def extra_info(self) -> dict[str, Any]: ...


def resolve_profile(name: str, settings: Any) -> Profile:
    """Ajusta o perfil ao plano da assinatura (ex.: planner usa Sonnet no plano Pro)."""
    from dataclasses import replace

    p = PROFILES[name]
    if name == "planner":
        p = replace(p, model=settings.planner_model)
    return p
