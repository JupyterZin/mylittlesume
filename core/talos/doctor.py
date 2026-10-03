"""`talos doctor` (SPEC §12.4): verificações de saúde, com sondas injetáveis para teste."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import stat
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from talos.clock import as_utc, utcnow
from talos.config import Settings, check_auth_env
from talos.control import Control
from talos.db.engine import Database

OK, WARN, FAIL = "ok", "aviso", "falha"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


Probe = Callable[[], Awaitable[Check]]


class Doctor:
    def __init__(self, settings: Settings, db: Database | None = None, *, live: bool = True,
                 environ: dict[str, str] | None = None) -> None:
        self.s = settings
        self.db = db
        self.live = live
        self.environ = dict(os.environ) if environ is None else environ

    async def run(self, extra: list[Probe] | None = None) -> list[Check]:
        probes: list[Probe] = [
            self.auth_env, self.secrets_perms, self.vault_key, self.disk, self.database,
            self.monitor_tick, self.backups, self.pause_state,
        ]
        if self.live:
            probes += [self.claude_cli, self.telegram, self.google, self.browser, self.novnc, self.system1]
        probes += extra or []
        results = []
        for p in probes:
            try:
                results.append(await p())
            except Exception as e:  # uma sonda partida nunca derruba o doctor
                results.append(Check(getattr(p, "__name__", "sonda"), FAIL, f"erro inesperado: {e}"))
        return results

    # ---------- sondas ----------
    async def auth_env(self) -> Check:
        problems = check_auth_env(self.environ, self.s.auth_mode)
        mode = f"modo de autenticação ativo: {self.s.auth_mode} · plano: {self.s.claude_plan}"
        if problems:
            return Check("autenticação Claude", FAIL, mode + " · " + "; ".join(problems))
        return Check("autenticação Claude", OK, mode)

    async def secrets_perms(self) -> Check:
        p = Path("/etc/talos/secrets.env")
        if not p.exists():
            return Check("arquivo de segredos", WARN, f"{p} não existe (ok em desenvolvimento)")
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o077:
            return Check("arquivo de segredos", FAIL, f"{p} com permissão {oct(mode)}; use 0600")
        return Check("arquivo de segredos", OK, f"{p} {oct(mode)}")

    async def vault_key(self) -> Check:
        p = self.s.vault_key_file
        if not p.exists():
            return Check("chave do cofre", FAIL, f"{p} não existe (rode `talos vault init`)")
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o077:
            return Check("chave do cofre", FAIL, f"{p} com permissão {oct(mode)}; use 0600")
        return Check("chave do cofre", OK, str(p))

    async def disk(self) -> Check:
        target = self.s.data_dir if self.s.data_dir.exists() else Path("/")
        u = shutil.disk_usage(target)
        free_gb = u.free / 2**30
        status = OK if free_gb >= 2 and u.free / u.total >= 0.1 else (WARN if free_gb >= 0.5 else FAIL)
        return Check("espaço em disco", status, f"{free_gb:.1f} GB livres em {target}")

    async def database(self) -> Check:
        if not self.db:
            return Check("banco de dados", WARN, "não inicializado")
        with self.db.engine.connect() as c:
            c.exec_driver_sql("SELECT 1")
        return Check("banco de dados", OK, str(self.s.db_path))

    async def monitor_tick(self) -> Check:
        if not self.db:
            return Check("monitor", WARN, "sem banco")
        last = self.db.get_state("monitor").get("last_tick")
        if not last:
            return Check("monitor", WARN, "ainda não rodou")
        age = utcnow() - as_utc(datetime.fromisoformat(last))
        status = OK if age < timedelta(minutes=10) else FAIL
        return Check("monitor", status, f"último tick há {int(age.total_seconds() // 60)} min")

    async def backups(self) -> Check:
        d = self.s.data_dir / "backups"
        files = sorted(d.glob("*"), key=lambda p: p.stat().st_mtime) if d.exists() else []
        if not files:
            return Check("backups", WARN, f"nenhum backup em {d}")
        age_h = (utcnow().timestamp() - files[-1].stat().st_mtime) / 3600
        return Check("backups", OK if age_h < 26 else FAIL, f"último há {age_h:.0f} h ({files[-1].name})")

    async def pause_state(self) -> Check:
        if not self.db:
            return Check("pausa", WARN, "sem banco")
        return Check("pausa", WARN if Control(self.db).is_paused() else OK,
                     "Talos PAUSADO (/retomar para voltar)" if Control(self.db).is_paused() else "ativo")

    async def claude_cli(self) -> Check:
        from talos.runtime.claude import probe_cli

        try:
            text, info = await asyncio.wait_for(probe_cli(self.s), timeout=120)
        except Exception as e:
            return Check("Claude Code", FAIL, f"não respondeu: {e}")
        source = info.get("apiKeySource", "?")
        version = info.get("claude_code_version", "?")
        bad_source = self.s.auth_mode == "subscription" and "ANTHROPIC" in str(source).upper()
        status = OK if text.strip().upper().startswith("OK") and not bad_source else FAIL
        return Check("Claude Code", status, f"v{version} · resposta {text.strip()[:20]!r} · credencial: {source}")

    async def telegram(self) -> Check:
        if not self.s.telegram_bot_token:
            return Check("Telegram", FAIL, "TELEGRAM_BOT_TOKEN vazio")
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"https://api.telegram.org/bot{self.s.telegram_bot_token}/getMe")
        if r.status_code == 200 and r.json().get("ok"):
            return Check("Telegram", OK, "@" + r.json()["result"].get("username", "?"))
        return Check("Telegram", FAIL, f"getMe → HTTP {r.status_code}")

    async def google(self) -> Check:
        from talos.connectors.google_auth import GoogleAuthError, load_credentials
        from talos.vault.store import Vault, load_or_create_key

        if not self.db:
            return Check("Google", WARN, "sem banco")
        try:
            vault = Vault(self.db, load_or_create_key(self.s.vault_key_file))
            creds = await asyncio.to_thread(load_credentials, vault)
        except GoogleAuthError as e:
            return Check("Google", FAIL, str(e))
        from talos.clock import to_local

        expiry = to_local(creds.expiry, self.s.timezone).strftime("%H:%M") if creds.expiry else "?"
        return Check("Google", OK, f"token de acesso válido até {expiry} (renova-se sozinho)")

    async def system1(self) -> Check:
        if self.s.system1 == "off":
            return Check("Sistema 1 (Jev)", WARN, "desligado (SYSTEM1=off): triagem e roteamento usam o Haiku")
        if not self.s.typesafe_api_key:
            return Check("Sistema 1 (Jev)", WARN, "TYPESAFE_API_KEY vazio: triagem e roteamento usam o Haiku")
        from talos.system1.client import JevClient

        client = JevClient(self.s.typesafe_api_key, base_url=self.s.typesafe_base_url, retries=0)
        try:
            models = await client.models()
        except Exception as e:
            return Check("Sistema 1 (Jev)", FAIL, f"{self.s.typesafe_base_url}: {e}")
        finally:
            await client.aclose()
        ok = self.s.jev_model in models or self.s.jev_model.endswith("latest")
        return Check("Sistema 1 (Jev)", OK if ok else WARN, f"modelos: {', '.join(models[:4])}")

    async def browser(self) -> Check:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(self.s.browser_cdp_endpoint.rstrip("/") + "/json/version")
            return Check("navegador (CDP)", OK, r.json().get("Browser", "?"))
        except Exception as e:
            return Check("navegador (CDP)", FAIL, f"{self.s.browser_cdp_endpoint}: {e}")

    async def novnc(self) -> Check:
        try:
            with socket.create_connection(("127.0.0.1", 6080), timeout=3):
                return Check("Tela (noVNC)", OK, "127.0.0.1:6080")
        except OSError as e:
            return Check("Tela (noVNC)", FAIL, str(e))


def render(checks: list[Check]) -> str:
    icon = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
    return "\n".join(f"{icon[c.status]} {c.name}: {c.detail}" for c in checks)


def all_green(checks: list[Check]) -> bool:
    return all(c.status != FAIL for c in checks)
