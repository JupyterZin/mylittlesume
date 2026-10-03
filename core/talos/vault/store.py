"""Cofre cifrado (Fernet). As ferramentas do agente só veem as CHAVES (SPEC §7.4).

- `dados.*`  → dado pessoal: pode sair só depois de aprovação (resolvido pelo executor).
- resto      → segredo (tokens, senhas): nunca sai pelo agente.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlmodel import select

from talos.clock import utcnow
from talos.db.engine import Database
from talos.db.models import VaultItem
from talos.logging import REDACTOR

KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
PERSONAL_PREFIX = "dados."


class VaultError(RuntimeError):
    pass


def kind_for(key: str) -> str:
    return "dado_pessoal" if key.startswith(PERSONAL_PREFIX) else "segredo"


def load_or_create_key(path: Path, *, create: bool = False) -> bytes:
    if path.exists():
        return path.read_bytes().strip()
    if not create:
        raise VaultError(f"chave do cofre não encontrada em {path} (rode `talos vault init`)")
    path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


class Vault:
    def __init__(self, db: Database, key: bytes) -> None:
        self.db = db
        self._f = Fernet(key)

    # ---- escrita ----
    def set(self, key: str, value: str) -> None:
        if not KEY_RE.match(key):
            raise VaultError(f"chave inválida: {key!r} (use ex.: dados.morada)")
        if not value:
            raise VaultError("valor vazio")
        with self.db.session() as s:
            item = s.get(VaultItem, key) or VaultItem(key=key, ciphertext=b"", kind=kind_for(key))
            item.ciphertext = self._f.encrypt(value.encode())
            item.kind = kind_for(key)
            item.updated_at = utcnow()
            s.add(item)
            s.commit()
        REDACTOR.register(key, value)

    def delete(self, key: str) -> bool:
        with self.db.session() as s:
            item = s.get(VaultItem, key)
            if not item:
                return False
            s.delete(item)
            s.commit()
        REDACTOR.forget(key)
        return True

    # ---- leitura ----
    def list_keys(self) -> list[dict[str, str]]:
        with self.db.session() as s:
            rows = s.exec(select(VaultItem).order_by(VaultItem.key)).all()
        return [{"key": r.key, "kind": r.kind} for r in rows]

    def get(self, key: str) -> str | None:
        """Uso exclusivo do executor, do preview do cartão e do `vault_fill` aprovado."""
        with self.db.session() as s:
            item = s.get(VaultItem, key)
        if not item:
            return None
        try:
            return self._f.decrypt(item.ciphertext).decode()
        except InvalidToken as e:
            raise VaultError(f"não consegui decifrar {key} (chave do cofre errada?)") from e

    def personal_values(self) -> dict[str, str]:
        """Valores de `dados.*` (para egress e redação)."""
        out: dict[str, str] = {}
        for item in self.list_keys():
            if item["kind"] == "dado_pessoal":
                v = self.get(item["key"])
                if v:
                    out[item["key"]] = v
        return out

    def register_redactions(self) -> None:
        for item in self.list_keys():
            v = self.get(item["key"])
            REDACTOR.register(item["key"], v)
