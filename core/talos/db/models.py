"""Modelo de dados (SPEC §5). Datas sempre em UTC, com fuso."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from talos.clock import utcnow


def _json(default: Any = None) -> Any:
    factory = (lambda: {}) if default is None else (lambda: default.copy())
    return Field(default_factory=factory, sa_column=Column(JSON, nullable=False))


class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("channel", "external_chat_id"),)
    id: int | None = Field(default=None, primary_key=True)
    channel: str = Field(index=True)  # telegram | app
    external_chat_id: str
    main_session_id: str | None = None
    session_started_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: int | None = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    role: str  # user | assistant | system
    content: str
    created_at: datetime = Field(default_factory=utcnow, index=True)
    meta_json: dict = _json()


TASK_STATUSES = (
    "planning", "running", "waiting_approval", "waiting_external",
    "scheduled", "done", "failed", "cancelled",
)


class Task(SQLModel, table=True):
    __tablename__ = "tasks"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    goal: str = ""
    status: str = Field(default="planning", index=True)
    priority: int = 0
    session_id: str | None = None
    parent_task_id: int | None = Field(default=None, foreign_key="tasks.id")
    origin_conversation_id: int | None = Field(default=None, foreign_key="conversations.id")
    model_profile: str = "task"  # task | planner
    plan_json: dict = _json()
    authorized_data_json: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    summary: str = ""
    due_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TaskEvent(SQLModel, table=True):
    __tablename__ = "task_events"
    id: int | None = Field(default=None, primary_key=True)
    task_id: int | None = Field(default=None, foreign_key="tasks.id", index=True)
    type: str = Field(index=True)
    payload_json: dict = _json()
    created_at: datetime = Field(default_factory=utcnow, index=True)


ACTION_KINDS = (
    "email.send", "email.reply", "calendar.invite", "browser.submit",
    "purchase", "booking", "share_data", "delete", "email.organize",
)
ACTION_STATUSES = (
    "pending", "approved", "executing", "rejected", "superseded", "expired", "executed", "failed",
)


class PendingAction(SQLModel, table=True):
    __tablename__ = "pending_actions"
    id: int | None = Field(default=None, primary_key=True)
    task_id: int | None = Field(default=None, foreign_key="tasks.id", index=True)
    kind: str
    payload_json: dict = _json()
    preview_text: str = ""
    risk: str = "medio"  # baixo | medio | alto
    reason: str = ""
    status: str = Field(default="pending", index=True)
    idempotency_key: str = Field(unique=True)
    expires_at: datetime | None = None
    reminded_at: datetime | None = None
    decided_at: datetime | None = None
    decided_via: str | None = None
    decision_note: str = ""
    executed_at: datetime | None = None
    result_json: dict = _json()
    superseded_by: int | None = None
    card_refs_json: dict = _json()  # ex.: {"telegram": {"chat_id": .., "message_id": ..}}
    created_at: datetime = Field(default_factory=utcnow)


class Watch(SQLModel, table=True):
    __tablename__ = "watches"
    id: int | None = Field(default=None, primary_key=True)
    task_id: int | None = Field(default=None, foreign_key="tasks.id", index=True)
    kind: str  # email_thread | webpage
    target: str  # threadId ou URL
    last_marker: str | None = None  # último messageId visto / hash da página
    followup_policy_json: dict = _json()  # {"business_days": 3, "max": 2}
    followups_sent: int = 0
    next_check_at: datetime | None = Field(default=None, index=True)
    status: str = Field(default="active", index=True)  # active | done | cancelled
    created_at: datetime = Field(default_factory=utcnow)


JOB_STATUSES = ("queued", "running", "done", "failed", "waiting")


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    task_id: int | None = Field(default=None, foreign_key="tasks.id", index=True)
    payload_json: dict = _json()
    status: str = Field(default="queued", index=True)
    priority: int = 0
    run_after: datetime = Field(default_factory=utcnow, index=True)
    attempts: int = 0
    max_attempts: int = 3
    locked_by: str | None = None
    locked_until: datetime | None = None
    last_error: str | None = None
    dedupe_key: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Schedule(SQLModel, table=True):
    __tablename__ = "schedules"
    id: int | None = Field(default=None, primary_key=True)
    task_id: int | None = Field(default=None, foreign_key="tasks.id")
    kind: str = "prompt"  # briefing | reflection | goal_checkin | prompt
    rrule: str  # RFC 5545, interpretado em Europe/Lisbon
    prompt: str = ""
    next_run_at: datetime | None = Field(default=None, index=True)
    enabled: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Contact(SQLModel, table=True):
    __tablename__ = "contacts"
    id: int | None = Field(default=None, primary_key=True)
    name: str
    org: str = ""
    email: str = Field(default="", index=True)
    phone: str = ""
    website: str = ""
    source_url: str  # obrigatória
    verified_at: datetime | None = None
    notes: str = ""


class MemoryFact(SQLModel, table=True):
    __tablename__ = "memory_facts"
    __table_args__ = (UniqueConstraint("scope", "key"),)
    id: int | None = Field(default=None, primary_key=True)
    scope: str = "geral"
    key: str
    value: str
    source: str = "dito"  # dito | confirmado
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Goal(SQLModel, table=True):
    __tablename__ = "goals"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    why: str = ""
    milestones_json: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    cadence: str = ""
    status: str = "proposed"  # proposed | active | done | dropped
    next_checkin_at: datetime | None = None


class UsageLog(SQLModel, table=True):
    __tablename__ = "usage_log"
    id: int | None = Field(default=None, primary_key=True)
    job_id: int | None = Field(default=None, index=True)
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    turns: int = 0
    duration_ms: int = 0
    notional_cost_usd: float = 0.0
    is_error: bool = False
    rate_limited: bool = False
    created_at: datetime = Field(default_factory=utcnow, index=True)


class VaultItem(SQLModel, table=True):
    __tablename__ = "vault_items"
    key: str = Field(primary_key=True)
    ciphertext: bytes
    kind: str  # dado_pessoal | segredo
    updated_at: datetime = Field(default_factory=utcnow)


class SystemState(SQLModel, table=True):
    """Estado global persistente (pausa, rate limit, último tick do monitor, historyId…)."""

    __tablename__ = "system_state"
    key: str = Field(primary_key=True)
    value_json: dict = _json()
    updated_at: datetime = Field(default_factory=utcnow)


class InboundLog(SQLModel, table=True):
    """Mensagens de chats fora da allowlist: ignoradas e registradas (SPEC §11)."""

    __tablename__ = "inbound_rejected"
    id: int | None = Field(default=None, primary_key=True)
    channel: str
    external_chat_id: str
    preview: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class PushSubscription(SQLModel, table=True):
    """Aparelho inscrito nas notificações Web Push do app (um por navegador/PWA instalado)."""

    __tablename__ = "push_subscriptions"
    id: int | None = Field(default=None, primary_key=True)
    endpoint: str = Field(unique=True)  # URL do serviço de push (FCM no Android)
    p256dh: str  # chave pública do navegador: o conteúdo vai cifrado ponta a ponta
    auth: str
    user_agent: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    last_ok_at: datetime | None = None
    failures: int = 0  # falhas seguidas (zera a cada entrega)
