"""Limpeza dos testes: tira do contexto do Talos tudo o que foi feito antes de um corte (`talos limpar-testes`).

Nada é apagado às cegas:
- tarefas ficam `archived` (fora de task_list, /tarefas, briefing e app);
- vigilâncias são canceladas, para não haver follow-ups de testes;
- aprovações pendentes são recusadas;
- as conversas recomeçam sem trazer as mensagens antigas;
- fatos e contatos são apagados, depois de uma cópia do banco;
- os ficheiros de memória (workspace/memoria e a memória automática do CLI) vão para um arquivo fora do workspace.
"""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlmodel import col, select

from talos.clock import as_utc, utcnow
from talos.db.engine import Database
from talos.db.models import (
    Contact,
    Conversation,
    Job,
    MemoryFact,
    PendingAction,
    Task,
    TaskEvent,
    Watch,
)

CONTEXT_STATE = "context"  # system_state: {"floor": iso} → mensagens antes disto não voltam ao contexto


@dataclass
class CleanupPlan:
    cutoff: datetime
    tasks: list[Task] = field(default_factory=list)
    watches: list[Watch] = field(default_factory=list)
    approvals: list[PendingAction] = field(default_factory=list)
    conversations: list[Conversation] = field(default_factory=list)
    facts: list[MemoryFact] = field(default_factory=list)
    kept_facts: list[MemoryFact] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    kept_contacts: list[Contact] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.tasks or self.watches or self.approvals or self.conversations or self.facts
                    or self.contacts or self.files)


def context_floor(db: Database) -> datetime | None:
    raw = db.get_state(CONTEXT_STATE).get("floor")
    return as_utc(datetime.fromisoformat(raw)) if raw else None


def memory_dirs(workspace_dir: Path, home: Path) -> list[Path]:
    """Onde o agente guarda memória em ficheiros: workspace/memoria e a memória automática do Claude Code."""
    dirs = [workspace_dir / "memoria"]
    projects = home / ".claude" / "projects"
    if projects.is_dir():
        dirs += sorted(p / "memory" for p in projects.iterdir() if (p / "memory").is_dir())
    return dirs


def plan_cleanup(db: Database, cutoff: datetime, *, workspace_dir: Path, home: Path,
                 keep_facts: set[int] | None = None, keep_contacts: set[int] | None = None) -> CleanupPlan:
    cutoff = as_utc(cutoff)
    keep_facts, keep_contacts = keep_facts or set(), keep_contacts or set()
    p = CleanupPlan(cutoff=cutoff)
    with db.session() as s:
        p.tasks = list(s.exec(select(Task).where(col(Task.created_at) < cutoff, Task.status != "archived")
                              .order_by(col(Task.id))))
        p.watches = list(s.exec(select(Watch).where(Watch.status == "active", col(Watch.created_at) < cutoff)))
        p.approvals = list(s.exec(select(PendingAction).where(PendingAction.status == "pending",
                                                              col(PendingAction.created_at) < cutoff)))
        p.conversations = list(s.exec(select(Conversation).order_by(col(Conversation.id))))
        for f in s.exec(select(MemoryFact).where(col(MemoryFact.created_at) < cutoff).order_by(col(MemoryFact.id))):
            (p.kept_facts if f.id in keep_facts else p.facts).append(f)
        # contatos não têm data: todos entram, menos os que o Lucas mandar manter
        for c in s.exec(select(Contact).order_by(col(Contact.id))):
            (p.kept_contacts if c.id in keep_contacts else p.contacts).append(c)
    ts = cutoff.timestamp()
    for d in memory_dirs(workspace_dir, home):
        if d.is_dir():
            p.files += sorted(f for f in d.rglob("*") if f.is_file() and f.stat().st_mtime < ts)
    return p


def render_plan(p: CleanupPlan, tz_label: str = "") -> str:
    out = [f"Corte: tudo o que foi criado antes de {p.cutoff:%Y-%m-%d %H:%M} UTC{tz_label}.", ""]

    def section(title: str, rows: list[str]) -> None:
        out.append(f"{title} ({len(rows)})")
        out.extend(f"  {r}" for r in rows[:40])
        if len(rows) > 40:
            out.append(f"  … e mais {len(rows) - 40}")
        out.append("")

    section("Tarefas → arquivadas", [f"#{t.id} {t.title} [{t.status}]" for t in p.tasks])
    section("Vigilâncias de email → canceladas (sem follow-ups)", [f"#{w.id} tarefa #{w.task_id}" for w in p.watches])
    section("Aprovações pendentes → recusadas", [f"#{a.id} {a.kind}" for a in p.approvals])
    section("Conversas → recomeçam sem as mensagens antigas no contexto",
            [f"#{c.id} {c.channel}" for c in p.conversations])
    section("Fatos da memória → apagados", [f"#{f.id} {f.key}: {f.value[:60]}" for f in p.facts])
    if p.kept_facts:
        section("Fatos mantidos", [f"#{f.id} {f.key}" for f in p.kept_facts])
    section("Contatos → apagados", [f"#{c.id} {c.name} {('· ' + c.org) if c.org else ''}".rstrip() for c in p.contacts])
    if p.kept_contacts:
        section("Contatos mantidos", [f"#{c.id} {c.name}" for c in p.kept_contacts])
    section("Ficheiros de memória → arquivo (fora do alcance do agente)", [f.name for f in p.files])
    return "\n".join(out).rstrip()


def backup_db(db_path: Path, dest_dir: Path, stamp: str) -> Path:
    """Cópia consistente do SQLite (API de backup), mesmo com o serviço a correr."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"antes-limpeza-{stamp}.db"
    src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    dest.chmod(0o600)
    return dest


def apply_cleanup(db: Database, p: CleanupPlan, *, db_path: Path, data_dir: Path, workspace_dir: Path,
                  home: Path) -> dict[str, object]:
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    backup = backup_db(db_path, data_dir / "backups", stamp)
    now = utcnow()
    task_ids = {t.id for t in p.tasks}
    with db.session() as s:
        for t in s.exec(select(Task).where(col(Task.id).in_(task_ids))):
            old = t.status
            t.status, t.updated_at = "archived", now
            s.add(t)
            s.add(TaskEvent(task_id=t.id, type="archived", payload_json={"from": old, "motivo": "limpeza de testes"}))
        for w in s.exec(select(Watch).where(col(Watch.id).in_({w.id for w in p.watches}))):
            w.status = "cancelled"
            s.add(w)
        for a in s.exec(select(PendingAction).where(col(PendingAction.id).in_({a.id for a in p.approvals}),
                                                    PendingAction.status == "pending")):
            a.status, a.decided_at, a.decided_via, a.decision_note = "rejected", now, "cli", "limpeza de testes"
            s.add(a)
        for j in s.exec(select(Job).where(col(Job.task_id).in_(task_ids), col(Job.status).in_(("queued", "waiting")))):
            j.status, j.last_error, j.updated_at = "done", "tarefa arquivada (limpeza de testes)", now
            s.add(j)
        for c in s.exec(select(Conversation)):
            c.main_session_id, c.session_started_at = None, None
            s.add(c)
        for f in s.exec(select(MemoryFact).where(col(MemoryFact.id).in_({f.id for f in p.facts}))):
            s.delete(f)
        for c in s.exec(select(Contact).where(col(Contact.id).in_({c.id for c in p.contacts}))):
            s.delete(c)
        s.commit()
    floor = max(p.cutoff, context_floor(db) or p.cutoff)
    db.set_state(CONTEXT_STATE, {"floor": floor.isoformat(), "reason": "limpeza de testes"})

    archive = data_dir / "arquivo" / f"limpeza-{stamp}"
    roots = memory_dirs(workspace_dir, home)
    moved = 0
    for f in p.files:
        root = next((r for r in roots if f.is_relative_to(r)), None)
        if root is None or not f.exists():
            continue
        label = "memoria" if root == workspace_dir / "memoria" else f"auto-memory/{root.parent.name}"
        dest = archive / label / f.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(f), dest)
        moved += 1
    return {"backup": str(backup), "archive": str(archive) if moved else None, "files": moved,
            "tasks": len(p.tasks), "watches": len(p.watches), "approvals": len(p.approvals),
            "facts": len(p.facts), "contacts": len(p.contacts)}
