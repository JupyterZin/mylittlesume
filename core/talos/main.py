"""Entrypoint do talos-core: API + bot + workers + agendador num único processo asyncio."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from typing import Any

from talos.config import enforce_auth_env, get_settings
from talos.logging import configure_logging, get_logger

log = get_logger("talos.main")


def build_google(app_settings: Any, vault: Any) -> tuple[Any, Any, Any]:
    from talos.connectors.calendar import GoogleCalendar
    from talos.connectors.drive import GoogleDrive
    from talos.connectors.gmail import GoogleGmail
    from talos.connectors.google_auth import GoogleAuthError, load_credentials

    try:
        creds = load_credentials(vault)
    except GoogleAuthError as e:
        log.warning("google_unavailable", error=str(e))
        return None, None, None
    return GoogleGmail(creds), GoogleCalendar(creds), GoogleDrive(creds)


async def amain() -> None:
    import uvicorn
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from talos.channels.gateway import Gateway
    from talos.channels.telegram_bot import TelegramChannel
    from talos.channels.web_api import build_api
    from talos.db.engine import Database
    from talos.runtime.claude import ClaudeRuntime, sanitize_process_env
    from talos.scheduler.ticker import Ticker
    from talos.sentinel.classifier import HaikuClassifier
    from talos.sentinel.policy import Sentinel
    from talos.services import build_services
    from talos.vault.store import Vault, load_or_create_key

    settings = get_settings()
    configure_logging()
    enforce_auth_env(auth_mode=settings.auth_mode)  # aborta se houver ANTHROPIC_API_KEY em modo assinatura
    sanitize_process_env(settings.auth_mode)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    db = Database(settings.db_url)
    db.migrate()
    key = load_or_create_key(settings.vault_key_file)
    gmail, calendar, drive = build_google(settings, Vault(db, key))

    channels: dict[str, Any] = {}
    tg = TelegramChannel(settings.telegram_bot_token) if settings.telegram_bot_token else None
    if tg:
        channels["telegram"] = tg
    app = build_services(settings, db, key, channels=channels, gmail=gmail, calendar=calendar, drive=drive)

    runtime_holder: dict[str, Any] = {}

    async def ask_model(prompt: str) -> str:
        return await runtime_holder["rt"].ask_text(prompt, "classifier")

    sentinel = Sentinel(
        workspace_dir=settings.workspace_dir, vault_values=app.vault.personal_values,
        authorized_keys=app.tasks.authorized_keys, classifier=HaikuClassifier(ask_model),
        classifier_enabled=settings.sentinel_classifier,
        on_decision=lambda call, d: app.bus.emit("sentinel_decision", d.as_event(call), task_id=call.task_id),
    )
    app.approvals.on_grant = sentinel.grant_once
    runtime = ClaudeRuntime(app, sentinel)
    runtime_holder["rt"] = runtime
    app.runtime = runtime

    from talos.orchestrator.core import Orchestrator

    orch = Orchestrator(app, runtime)
    gateway = Gateway(app, orch)
    ticker = Ticker(app, orch)
    extra_jobs: list[Any] = []
    try:
        from talos.monitor.gmail_watch import install as install_monitor

        extra_jobs = install_monitor(app, orch)
    except ImportError:
        pass

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    sched = AsyncIOScheduler(timezone=settings.timezone)
    sched.add_job(ticker.minute, "interval", seconds=60, max_instances=1, coalesce=True)
    for fn, seconds in extra_jobs:
        sched.add_job(fn, "interval", seconds=seconds, max_instances=1, coalesce=True)
    sched.start()

    if tg:
        await tg.start(gateway)
    server = uvicorn.Server(uvicorn.Config(build_api(app, gateway), host=settings.api_host, port=settings.api_port,
                                           log_config=None, access_log=False))
    api_task = asyncio.create_task(server.serve())
    workers = asyncio.create_task(orch.run_forever(stop))
    log.info("talos_started", auth_mode=settings.auth_mode, paused=app.control.is_paused())

    await stop.wait()
    log.info("talos_stopping")
    server.should_exit = True
    sched.shutdown(wait=False)
    if tg:
        await tg.stop()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(asyncio.gather(workers, api_task, return_exceptions=True), timeout=20)


def run() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    run()
