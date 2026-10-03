"""Acesso ao SQLite (WAL) + migrações Alembic no arranque."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine, select

from talos.clock import utcnow
from talos.db.models import SystemState

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: Engine = create_engine(
            url, connect_args={"check_same_thread": False, "timeout": 30}
        )
        event.listen(self.engine, "connect", _sqlite_pragmas)

    # ---------- esquema ----------
    def migrate(self) -> None:
        from alembic import command
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
        cfg.set_main_option("sqlalchemy.url", self.url)
        cfg.attributes["connection"] = None
        with self.engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")

    def create_all(self) -> None:
        """Só para testes rápidos; produção usa migrate()."""
        SQLModel.metadata.create_all(self.engine)

    # ---------- sessões ----------
    @contextmanager
    def session(self) -> Iterator[Session]:
        with Session(self.engine, expire_on_commit=False) as s:
            yield s

    # ---------- estado global ----------
    def get_state(self, key: str, default: dict | None = None) -> dict:
        with self.session() as s:
            row = s.get(SystemState, key)
            return dict(row.value_json) if row else dict(default or {})

    def set_state(self, key: str, value: dict[str, Any]) -> None:
        with self.session() as s:
            row = s.get(SystemState, key)
            if row is None:
                row = SystemState(key=key, value_json=value)
            else:
                row.value_json = value
                row.updated_at = utcnow()
            s.add(row)
            s.commit()

    def all_state(self) -> dict[str, dict]:
        with self.session() as s:
            return {r.key: dict(r.value_json) for r in s.exec(select(SystemState))}


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()
