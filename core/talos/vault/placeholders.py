"""Placeholders `{{dados.*}}` (SPEC §7.4): o agente escreve, o executor resolve no envio."""

from __future__ import annotations

import re
from collections.abc import Mapping

PLACEHOLDER_RE = re.compile(r"\{\{\s*(dados\.[a-z0-9_]+)\s*\}\}")
ANY_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)\s*\}\}")

LABELS = {
    "dados.morada": "morada",
    "dados.nif": "NIF",
    "dados.telefone": "telefone",
    "dados.nome_completo": "nome completo",
    "dados.email": "email",
    "dados.iban": "IBAN",
    "dados.cui": "CUI",
    "dados.cpe": "CPE",
}


class PlaceholderError(ValueError):
    pass


def find_keys(text: str) -> list[str]:
    """Chaves `dados.*` usadas no texto, sem repetição, na ordem em que aparecem."""
    seen: list[str] = []
    for m in PLACEHOLDER_RE.finditer(text or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def find_forbidden(text: str) -> list[str]:
    """Placeholders que não são `dados.*` (ex.: segredos) — nunca podem ser resolvidos."""
    return [m.group(1) for m in ANY_PLACEHOLDER_RE.finditer(text or "") if not m.group(1).startswith("dados.")]


def resolve(text: str, values: Mapping[str, str]) -> str:
    if forbidden := find_forbidden(text):
        raise PlaceholderError(f"placeholders proibidos: {', '.join(forbidden)}")

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in values or not values[key]:
            raise PlaceholderError(f"{key} não existe no cofre")
        return values[key]

    return PLACEHOLDER_RE.sub(sub, text or "")


def label(key: str) -> str:
    return LABELS.get(key, key.removeprefix("dados.").replace("_", " "))
