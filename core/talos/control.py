"""Botão de pânico (SPEC §7.6): estado de pausa persistente, partilhado entre o processo
principal e o CLI (`talos pause`) através da tabela `system_state`."""

from __future__ import annotations

from talos.clock import utcnow
from talos.db.engine import Database

PAUSE_KEY = "pause"
RATE_KEY = "rate_limit"


class Control:
    def __init__(self, db: Database) -> None:
        self.db = db

    def is_paused(self) -> bool:
        return bool(self.db.get_state(PAUSE_KEY).get("paused"))

    def pause(self, by: str, reason: str = "") -> bool:
        """Devolve True se mudou de estado."""
        if self.is_paused():
            return False
        self.db.set_state(PAUSE_KEY, {"paused": True, "since": utcnow().isoformat(), "by": by, "reason": reason})
        return True

    def resume(self, by: str) -> bool:
        if not self.is_paused():
            return False
        self.db.set_state(PAUSE_KEY, {"paused": False, "since": utcnow().isoformat(), "by": by})
        return True

    # limite da assinatura
    def rate_limited_until(self) -> str | None:
        return self.db.get_state(RATE_KEY).get("until")

    def set_rate_limited(self, until_iso: str | None, notified: bool) -> None:
        self.db.set_state(RATE_KEY, {"until": until_iso, "notified": notified})
