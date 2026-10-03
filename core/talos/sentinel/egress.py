"""Verificação de egress: dados pessoais a sair por URL, formulário ou pesquisa (SPEC §7.3, §7.5.3).

Detecta (1) valores literais do cofre (`dados.*`), também URL-encoded, e (2) padrões de dados
pessoais: NIF (com dígito de controlo), IBAN (mod 97), cartão (Luhn), telefone e código postal PT
(indicador de morada).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, quote_plus, unquote_plus

NIF_RE = re.compile(r"(?<!\d)([1235689]\d{8}|45\d{7})(?!\d)")
IBAN_RE = re.compile(r"\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30})\b")
CARD_RE = re.compile(r"(?<!\d)(\d(?:[ -]?\d){12,18})(?!\d)")
PHONE_RE = re.compile(r"(?<![\d+])((?:\+|00)351[ .-]?)?(9[1236]\d(?:[ .-]?\d){6}|2\d(?:[ .-]?\d){7})(?!\d)")
INTL_PHONE_RE = re.compile(r"(?<![\w+])\+(?!351)\d{1,3}[ .-]?\d(?:[ .-]?\d){6,12}(?!\d)")
POSTAL_RE = re.compile(r"(?<!\d)\d{4}-\d{3}(?!\d)")


@dataclass(frozen=True)
class EgressHit:
    kind: str  # vault | nif | iban | cartao | telefone | morada
    key: str | None  # chave do cofre, quando for valor do cofre
    sample: str  # mascarado

    def describe(self) -> str:
        return f"{self.kind}{f' ({self.key})' if self.key else ''}"


def _mask(s: str) -> str:
    s = s.strip()
    return s[:2] + "…" + s[-2:] if len(s) > 6 else "…"


def nif_valid(n: str) -> bool:
    if len(n) != 9 or not n.isdigit():
        return False
    total = sum(int(d) * (9 - i) for i, d in enumerate(n[:8]))
    check = 11 - total % 11
    check = 0 if check >= 10 else check
    return check == int(n[8])


def iban_valid(s: str) -> bool:
    s = s.replace(" ", "").upper()
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def luhn_valid(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def strings_in(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, Mapping):
        for v in obj.values():
            yield from strings_in(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from strings_in(v)
    elif obj is not None and not isinstance(obj, bool | int | float):
        yield json.dumps(obj, default=str)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def scan_text(text: str, vault_values: Mapping[str, str]) -> list[EgressHit]:
    hits: list[EgressHit] = []
    variants = {text, unquote_plus(text)}
    lowered = {_norm(v) for v in variants}
    for key, value in vault_values.items():
        if not value or len(value) < 3:
            continue
        parts = [value] + [p for p in re.split(r"[,;\n]", value) if len(p.strip()) >= 8]
        forms = {f for p in parts for f in (_norm(p), _norm(quote_plus(p.strip())), _norm(quote(p.strip())))}
        compact = re.sub(r"[\s.-]", "", value)
        if any(f in t for f in forms for t in lowered) or (
            len(compact) >= 6 and any(compact.lower() in re.sub(r"[\s.-]", "", t) for t in lowered)
        ):
            hits.append(EgressHit("vault", key, _mask(value)))
    for t in variants:
        for m in NIF_RE.finditer(t):
            if nif_valid(m.group(1)):
                hits.append(EgressHit("nif", None, _mask(m.group(1))))
        for m in IBAN_RE.finditer(t.upper()):
            if iban_valid(m.group(1)):
                hits.append(EgressHit("iban", None, _mask(m.group(1))))
        for m in CARD_RE.finditer(t):
            if luhn_valid(m.group(1)):
                hits.append(EgressHit("cartao", None, _mask(m.group(1))))
        for m in PHONE_RE.finditer(t):
            hits.append(EgressHit("telefone", None, _mask(m.group(0))))
        for m in INTL_PHONE_RE.finditer(t):
            hits.append(EgressHit("telefone", None, _mask(m.group(0))))
        for m in POSTAL_RE.finditer(t):
            hits.append(EgressHit("morada", None, _mask(m.group(0))))
    # sem repetidos
    uniq: dict[tuple[str, str | None, str], EgressHit] = {}
    for h in hits:
        uniq[(h.kind, h.key, h.sample)] = h
    return list(uniq.values())


def scan(tool_input: Any, vault_values: Mapping[str, str]) -> list[EgressHit]:
    hits: list[EgressHit] = []
    for s in strings_in(tool_input):
        hits.extend(scan_text(s, vault_values))
    uniq = {(h.kind, h.key, h.sample): h for h in hits}
    return list(uniq.values())


def unauthorized(hits: list[EgressHit], authorized_keys: Iterable[str]) -> list[EgressHit]:
    """Um hit de valor do cofre é autorizado se a chave foi aprovada nesta tarefa.

    Padrões genéricos (NIF, IBAN…) que coincidem com um valor do cofre autorizado também são
    aceites; os restantes pedem aprovação.
    """
    allowed = set(authorized_keys)
    vault_hits = [h for h in hits if h.kind == "vault"]
    authorized_vault_samples = {h.sample for h in vault_hits if h.key in allowed}
    out = []
    for h in hits:
        if h.kind == "vault" and h.key in allowed:
            continue
        if h.kind != "vault" and authorized_vault_samples and _covered_by_authorized(h, vault_hits, allowed):
            continue
        out.append(h)
    return out


_PATTERN_FOR_KEY = {
    "dados.nif": "nif", "dados.iban": "iban", "dados.telefone": "telefone", "dados.morada": "morada",
}


def _covered_by_authorized(hit: EgressHit, vault_hits: list[EgressHit], allowed: set[str]) -> bool:
    return any(
        vh.key in allowed and _PATTERN_FOR_KEY.get(vh.key or "") == hit.kind for vh in vault_hits
    )
