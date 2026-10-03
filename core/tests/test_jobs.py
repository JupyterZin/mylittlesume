from datetime import timedelta

from talos.clock import utcnow
from talos.db.engine import Database
from talos.db.models import Task
from talos.scheduler.jobs import JobQueue


def _task(db: Database) -> int:
    with db.session() as s:
        t = Task(title="t")
        s.add(t)
        s.commit()
        s.refresh(t)
        return t.id


def test_claim_order_and_complete(db):
    q = JobQueue(db)
    a = q.enqueue("x", {"n": 1})
    b = q.enqueue("x", {"n": 2}, priority=5)
    assert q.claim().id == b.id
    assert q.claim().id == a.id
    assert q.claim() is None
    q.complete(a.id)
    assert q.get(a.id).status == "done"


def test_run_after_and_kind_filter(db):
    q = JobQueue(db)
    q.enqueue("later", run_after=utcnow() + timedelta(hours=1))
    j = q.enqueue("now")
    assert q.claim(kinds=("later",)) is None
    assert q.claim().id == j.id


def test_task_lock(db):
    q = JobQueue(db)
    tid = _task(db)
    j1 = q.enqueue("agent.task_run", task_id=tid)
    j2 = q.enqueue("agent.task_run", task_id=tid)
    assert q.claim().id == j1.id
    assert q.claim() is None  # mesma tarefa já está rodando
    q.complete(j1.id)
    assert q.claim().id == j2.id


def test_retry_then_fail(db):
    q = JobQueue(db)
    j = q.enqueue("x", max_attempts=2)
    q.claim()
    assert q.fail(j.id, "boom", retry_in=timedelta(0)) == "queued"
    q.claim()
    assert q.fail(j.id, "boom", retry_in=timedelta(0)) == "failed"


def test_defer_refunds_attempt(db):
    q = JobQueue(db)
    j = q.enqueue("x")
    q.claim()
    q.defer(j.id, utcnow() - timedelta(seconds=1), "rate_limited")
    job = q.get(j.id)
    assert job.status == "queued" and job.attempts == 0 and job.last_error == "rate_limited"


def test_survives_restart(tmp_settings, db):
    q = JobQueue(db)
    j = q.enqueue("x")
    q.claim()  # processo "morre" com o job em running
    db2 = Database(tmp_settings.db_url)  # novo processo, mesmo arquivo
    q2 = JobQueue(db2)
    assert q2.requeue_all_running() == 1
    assert q2.claim().id == j.id


def test_dedupe(db):
    q = JobQueue(db)
    a = q.enqueue("x", dedupe_key="k")
    b = q.enqueue("x", dedupe_key="k")
    assert a.id == b.id
