"""Registro das ferramentas do Talos (servidor MCP in-process `talos`, SPEC §6)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from talos.services import Services


@dataclass
class ToolContext:
    app: Services
    task_id: int | None = None
    conversation_id: int | None = None
    profile: str = "main"
    run_id: str = ""
    notes: list[str] = field(default_factory=list)  # efeitos colaterais visíveis no resumo


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Handler
    profiles: tuple[str, ...] = ("main", "task", "planner")


REGISTRY: dict[str, ToolSpec] = {}


def talos_tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None,
               profiles: tuple[str, ...] = ("main", "task", "planner")) -> Callable[[Handler], Handler]:
    schema = {"type": "object", "properties": properties, "required": required or [],
              "additionalProperties": False}

    def deco(fn: Handler) -> Handler:
        REGISTRY[name] = ToolSpec(name, description, schema, fn, profiles)
        return fn

    return deco


class ToolError(Exception):
    pass


def as_result(value: Any, is_error: bool = False) -> dict[str, Any]:
    if isinstance(value, dict) and "content" in value:
        return value
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str, indent=1)
    return {"content": [{"type": "text", "text": text}], "is_error": is_error}


async def call_tool(spec: ToolSpec, ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        return as_result(await spec.handler(ctx, args or {}))
    except ToolError as e:
        return as_result(f"Erro: {e}", is_error=True)
    except Exception as e:  # nunca derruba a sessão do agente
        return as_result(f"Erro inesperado em {spec.name}: {type(e).__name__}: {e}", is_error=True)


def specs_for(profile: str) -> list[ToolSpec]:
    from talos.tools import definitions  # noqa: F401  (regista as ferramentas)

    return [s for s in REGISTRY.values() if profile in s.profiles]
