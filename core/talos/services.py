"""Contêiner de serviços: monta o Talos (real ou com fakes) num único objeto."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from talos.approvals import Approvals
from talos.channels.base import ChatChannel
from talos.channels.notifier import Notifier
from talos.config import Settings
from talos.connectors.calendar import CalendarAPI
from talos.connectors.drive import DriveAPI
from talos.connectors.gmail import GmailAPI
from talos.control import Control
from talos.db.engine import Database
from talos.events import EventBus
from talos.executor import Executor
from talos.memory.facts import ContactService, MemoryService
from talos.scheduler.jobs import JobQueue
from talos.system1.judgments import System1
from talos.tasks import TaskService
from talos.vault.store import Vault


@dataclass
class Services:
    settings: Settings
    db: Database
    bus: EventBus
    queue: JobQueue
    control: Control
    vault: Vault
    tasks: TaskService
    memory: MemoryService
    contacts: ContactService
    approvals: Approvals
    executor: Executor
    notifier: Notifier
    channels: dict[str, ChatChannel]
    gmail: GmailAPI | None = None
    calendar: CalendarAPI | None = None
    drive: DriveAPI | None = None
    browser: Any = None
    runtime: Any = None
    system1: System1 = field(default_factory=lambda: System1(None))
    extra: dict[str, Any] = field(default_factory=dict)


def build_services(settings: Settings, db: Database, vault_key: bytes, *,
                   channels: dict[str, ChatChannel] | None = None, gmail: GmailAPI | None = None,
                   calendar: CalendarAPI | None = None, drive: DriveAPI | None = None,
                   browser: Any = None, system1: System1 | None = None) -> Services:
    bus = EventBus(db)
    queue = JobQueue(db)
    control = Control(db)
    vault = Vault(db, vault_key)
    vault.register_redactions()
    tasks = TaskService(db, bus)
    memory = MemoryService(db)
    contacts = ContactService(db)
    channels = channels or {}
    notifier = Notifier(settings, db, queue, bus, channels, vault)
    approvals = Approvals(settings=settings, db=db, bus=bus, queue=queue, tasks=tasks, contacts=contacts,
                          vault=vault, control=control, gmail=gmail, notifier=notifier)
    executor = Executor(settings=settings, db=db, bus=bus, queue=queue, vault=vault, approvals=approvals,
                        tasks=tasks, control=control, notifier=notifier, gmail=gmail, calendar=calendar)
    services = Services(settings=settings, db=db, bus=bus, queue=queue, control=control, vault=vault, tasks=tasks,
                    memory=memory, contacts=contacts, approvals=approvals, executor=executor, notifier=notifier,
                    channels=channels, gmail=gmail, calendar=calendar, drive=drive, browser=browser,
                    system1=system1 or System1(None))
    executor._app = services
    return services
