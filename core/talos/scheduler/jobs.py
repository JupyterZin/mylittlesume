"""Fila de jobs durável sobre SQLite (SPEC §3.2).

Estados: queued → running → done | failed | waiting. Cada job tem `attempts`, `run_after` e
lease (`locked_by` + `locked_until`). Um job nunca roda em paralelo com outro da mesma tarefa
(lock por tarefa). Jobs `running` com lease vencido voltam para `queued` no arranque e a cada
varredura — é isso que faz a fila sobreviver a reinícios.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text
from sqlmodel import select
from sqlmodel.sql.sqltypes import UTCDateTime

from talos.clock import utcnow
from talos.db.engine import Database
from talos.db.models import Job

LEASE = timedelta(minutes=30)


class JobQueue:
    def __init__(self, db: Database, worker_id: str = "core") -> None:
        self.db = db
        self.worker_id = worker_id

    def enqueue(
        self,
        kind: str,
        payload: dict[str, Any] | None = None,
        *,
        task_id: int | None = None,
        run_after: datetime | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        dedupe_key: str | None = None,
    ) -> Job:
        with self.db.session() as s:
            if dedupe_key:
                existing = s.exec(
                    select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(("queued", "running")))
                ).first()
                if existing:
                    return existing
            job = Job(
                kind=kind,
                payload_json=payload or {},
                task_id=task_id,
                run_after=run_after or utcnow(),
                priority=priority,
                max_attempts=max_attempts,
                dedupe_key=dedupe_key,
            )
            s.add(job)
            s.commit()
            s.refresh(job)
            return job

    def claim(self, kinds: tuple[str, ...] | None = None, now: datetime | None = None) -> Job | None:
        """Reserva atomicamente o próximo job pronto (respeitando o lock por tarefa)."""
        now = now or utcnow()
        kind_filter = ""
        params: dict[str, Any] = {"now": now, "w": self.worker_id, "lu": now + LEASE}
        if kinds:
            names = []
            for i, k in enumerate(kinds):
                params[f"k{i}"] = k
                names.append(f":k{i}")
            kind_filter = f"AND j.kind IN ({', '.join(names)})"
        sql = text(
            f"""
            UPDATE jobs SET status='running', locked_by=:w, locked_until=:lu,
                   attempts=attempts+1, updated_at=:now
            WHERE id = (
              SELECT j.id FROM jobs j
              WHERE j.status='queued' AND j.run_after <= :now {kind_filter}
                AND (j.task_id IS NULL OR NOT EXISTS (
                      SELECT 1 FROM jobs r WHERE r.task_id = j.task_id AND r.status='running'))
              ORDER BY j.priority DESC, j.run_after, j.id
              LIMIT 1)
            AND status='queued'
            RETURNING id
            """
        ).bindparams(bindparam("now", type_=UTCDateTime()), bindparam("lu", type_=UTCDateTime()))
        with self.db.engine.begin() as conn:
            row = conn.execute(sql, params).first()
        if not row:
            return None
        return self.get(row[0])

    def get(self, job_id: int) -> Job | None:
        with self.db.session() as s:
            return s.get(Job, job_id)

    def _update(self, job_id: int, **fields: Any) -> None:
        with self.db.session() as s:
            job = s.get(Job, job_id)
            if job is None:
                return
            for k, v in fields.items():
                setattr(job, k, v)
            job.updated_at = utcnow()
            s.add(job)
            s.commit()

    def complete(self, job_id: int) -> None:
        self._update(job_id, status="done", locked_by=None, locked_until=None, last_error=None)

    def fail(self, job_id: int, error: str, *, retry_in: timedelta | None = None) -> str:
        """Regista a falha; volta para a fila se ainda houver tentativas. Devolve o novo estado."""
        job = self.get(job_id)
        if job is None:
            return "missing"
        if retry_in is not None and job.attempts < job.max_attempts:
            self._update(job_id, status="queued", run_after=utcnow() + retry_in, locked_by=None,
                         locked_until=None, last_error=error[:2000])
            return "queued"
        self._update(job_id, status="failed", locked_by=None, locked_until=None, last_error=error[:2000])
        return "failed"

    def defer(self, job_id: int, until: datetime, reason: str, *, refund_attempt: bool = True) -> None:
        """Devolve o job à fila sem gastar tentativa (ex.: limite da assinatura, pausa)."""
        job = self.get(job_id)
        if job is None:
            return
        self._update(job_id, status="queued", run_after=until, locked_by=None, locked_until=None,
                     last_error=reason, attempts=max(0, job.attempts - 1) if refund_attempt else job.attempts)

    def wait(self, job_id: int, reason: str = "") -> None:
        self._update(job_id, status="waiting", locked_by=None, locked_until=None, last_error=reason or None)

    def recover_stale(self, now: datetime | None = None) -> int:
        """Jobs `running` cujo lease venceu (processo morreu) voltam para `queued`."""
        now = now or utcnow()
        with self.db.engine.begin() as conn:
            res = conn.execute(
                text("UPDATE jobs SET status='queued', locked_by=NULL, locked_until=NULL, "
                     "last_error='recuperado após reinício' WHERE status='running' "
                     "AND (locked_until IS NULL OR locked_until < :now OR locked_by = :w)")
                .bindparams(bindparam("now", type_=UTCDateTime())),
                {"now": now, "w": self.worker_id},
            )
            return res.rowcount or 0

    def requeue_all_running(self) -> int:
        """No arranque: tudo o que estava `running` neste worker é órfão."""
        with self.db.engine.begin() as conn:
            res = conn.execute(
                text("UPDATE jobs SET status='queued', locked_by=NULL, locked_until=NULL, "
                     "last_error='recuperado após reinício' WHERE status='running'")
            )
            return res.rowcount or 0

    def counts(self) -> dict[str, int]:
        with self.db.engine.begin() as conn:
            rows = conn.execute(text("SELECT status, COUNT(*) FROM jobs GROUP BY status")).all()
        return {r[0]: r[1] for r in rows}
