from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from talos.config import Settings
from talos.db.engine import Database
from talos.vault.store import Vault


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return Settings(
        data_dir=tmp_path / "data",
        workspace_dir=ws,
        vault_key_file=tmp_path / "vault.key",
        telegram_bot_token="123456:TEST-TOKEN-abcdef",
        telegram_allowed_chat_id="1001",
        gmail_address="lucas.teste@gmail.com",
        sentinel_classifier=False,
    )


@pytest.fixture
def db(tmp_settings: Settings) -> Database:
    tmp_settings.data_dir.mkdir(parents=True, exist_ok=True)
    d = Database(tmp_settings.db_url)
    d.migrate()
    return d


@pytest.fixture
def vault(db: Database) -> Vault:
    v = Vault(db, Fernet.generate_key())
    v.set("dados.morada", "Rua das Flores 12, 1200-195 Lisboa")
    v.set("dados.nif", "123456789")
    v.set("dados.telefone", "912345678")
    v.set("dados.nome_completo", "Lucas Teste Silva")
    return v


# ---------------------------------------------------------------- harness completo com fakes
from dataclasses import dataclass  # noqa: E402

from talos.channels.base import FakeChannel  # noqa: E402
from talos.channels.gateway import Gateway  # noqa: E402
from talos.connectors.fakes import FakeCalendar, FakeDrive, FakeGmail  # noqa: E402
from talos.orchestrator.core import Orchestrator  # noqa: E402
from talos.runtime.fake import FakeRuntime  # noqa: E402
from talos.sentinel.policy import Sentinel  # noqa: E402
from talos.services import Services, build_services  # noqa: E402

CHAT = "1001"


@dataclass
class Harness:
    app: Services
    rt: FakeRuntime
    orch: Orchestrator
    gw: Gateway
    tg: FakeChannel
    gmail: FakeGmail
    sentinel: Sentinel
    key: bytes = b""

    async def say(self, text: str, chat: str = CHAT, reply_to: str | None = None) -> str | None:
        return await self.gw.on_text("telegram", chat, text, reply_to=reply_to)

    async def tap(self, data: str, chat: str = CHAT) -> str:
        return await self.gw.on_callback("telegram", chat, data)

    async def drain(self) -> int:
        return await self.orch.drain()


def make_harness(settings: Settings, db: Database, key: bytes) -> Harness:
    tg = FakeChannel()
    gmail = FakeGmail(settings.gmail_address)
    app = build_services(settings, db, key, channels={"telegram": tg}, gmail=gmail, calendar=FakeCalendar(),
                         drive=FakeDrive())
    sentinel = Sentinel(workspace_dir=settings.workspace_dir, vault_values=app.vault.personal_values,
                        authorized_keys=app.tasks.authorized_keys,
                        on_decision=lambda c, d: app.bus.emit("sentinel_decision", d.as_event(c), task_id=c.task_id))
    app.approvals.on_grant = sentinel.grant_once
    rt = FakeRuntime(app, sentinel)
    app.runtime = rt
    orch = Orchestrator(app, rt)
    return Harness(app, rt, orch, Gateway(app, orch), tg, gmail, sentinel, key)


@pytest.fixture
def h(tmp_settings: Settings, db: Database, monkeypatch: pytest.MonkeyPatch) -> Harness:
    # meio-dia em Lisboa: fora das horas de silêncio, para os testes não dependerem da hora real
    from datetime import UTC, datetime

    fixed = datetime(2026, 10, 7, 11, 0, tzinfo=UTC)
    monkeypatch.setattr("talos.channels.notifier.utcnow", lambda: fixed)
    key = Fernet.generate_key()
    harness = make_harness(tmp_settings, db, key)
    v = harness.app.vault
    v.set("dados.morada", "Rua das Flores 12, 1200-195 Lisboa")
    v.set("dados.nif", "123456789")
    v.set("dados.nome_completo", "Lucas Teste Silva")
    return harness
