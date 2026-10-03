"""Cliente HTTP mínimo da API System One da TypeSafe (ADR-017).

Contrato copiado do SDK oficial `typesafe-sdk` 0.7.2: POST {base}/v1/systemone com
`Authorization: Bearer <chave>` e corpo `{"state", "model", "questions"}`; resposta
`{"model", "usage": {"input_tokens","output_tokens"}, "answers": {nome: {...}}}`.
Tudo o que sai passa antes pela redação (valores do cofre e padrões de dados pessoais).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from talos.logging import REDACTOR, get_logger
from talos.sentinel.egress import mask_personal

log = get_logger("talos.system1")

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"
PATH = "/v1/systemone"


class System1Error(RuntimeError):
    pass


@dataclass(frozen=True)
class Answer:
    type: str
    choice: str | None = None
    noul: float | None = None
    score: float | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_wire(cls, raw: dict[str, Any]) -> Answer:
        return cls(type=raw.get("type", ""), choice=raw.get("choice"), noul=raw.get("noul"),
                   score=raw.get("score"), confidence=raw.get("confidence"),
                   probabilities={str(k): float(v) for k, v in (raw.get("probabilities") or {}).items()})


def choice(instructions: Any, criteria: dict[str, Any]) -> dict[str, Any]:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def noul(instructions: Any, true: Any = None, false: Any = None) -> dict[str, Any]:
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if true is not None or false is not None:
        q["criteria"] = {k: v for k, v in (("true", true), ("false", false)) if v is not None}
    return q


def score(instructions: Any, levels: list[Any]) -> dict[str, Any]:
    return {"type": "score", "instructions": instructions, "criteria": levels}


def sanitize(obj: Any) -> Any:
    """Nada de valores do cofre nem números pessoais a sair para um terceiro."""
    if isinstance(obj, str):
        return mask_personal(REDACTOR.redact_text(obj))
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [sanitize(v) for v in obj]
    return obj


class JevClient:
    def __init__(self, api_key: str, *, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 timeout: float = 10.0, transport: httpx.AsyncBaseTransport | None = None,
                 on_usage: Callable[[int, int], None] | None = None, retries: int = 2) -> None:
        if not api_key:
            raise System1Error("TYPESAFE_API_KEY vazio")
        self.model = model
        self.on_usage = on_usage
        self.retries = retries
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout, transport=transport, headers={
            "Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": "talos/0.1 (+typesafe-http)"})
        REDACTOR.register("TYPESAFE_API_KEY", api_key)

    async def ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> dict[str, Answer]:
        if not questions:
            raise System1Error("pelo menos uma pergunta")
        body = {"state": sanitize(state), "model": self.model, "questions": sanitize(questions)}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = await self._http.post(PATH, content=json.dumps(body, ensure_ascii=False))
            except httpx.HTTPError as e:
                last = e
            else:
                if r.status_code == 200:
                    data = r.json()
                    usage = data.get("usage") or {}
                    if self.on_usage:
                        self.on_usage(int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))
                    return {k: Answer.from_wire(v) for k, v in (data.get("answers") or {}).items()
                            if isinstance(v, dict) and v.get("type") in ("choice", "noul", "score")}
                if r.status_code in (429, 500, 502, 503, 504):
                    last = System1Error(f"HTTP {r.status_code}")
                else:
                    raise System1Error(f"HTTP {r.status_code}: {r.text[:200]}")
            if attempt < self.retries:
                await asyncio.sleep(0.5 * (2**attempt))
        raise System1Error(f"Jev indisponível: {last}")

    async def models(self) -> list[str]:
        r = await self._http.get("/v1/models")
        if r.status_code != 200:
            raise System1Error(f"HTTP {r.status_code}")
        return [m.get("name", "") for m in r.json().get("models", [])]

    async def aclose(self) -> None:
        await self._http.aclose()
