"""Configuração do Talos (pydantic-settings) + verificação de variáveis proibidas.

Em AUTH_MODE=subscription, ANTHROPIC_API_KEY e ANTHROPIC_AUTH_TOKEN não podem existir no
ambiente: se existirem, o Claude Code passa a cobrar por token. O startup e o `talos doctor`
abortam nesse caso (SPEC §2.2).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

FORBIDDEN_IN_SUBSCRIPTION = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
NOTIFY_CHANNELS = ("telegram", "app")


class ForbiddenEnvError(RuntimeError):
    pass


def check_auth_env(environ: Mapping[str, str], auth_mode: str) -> list[str]:
    """Devolve a lista de problemas de autenticação (vazia = ok)."""
    problems: list[str] = []
    if auth_mode == "subscription":
        for name in FORBIDDEN_IN_SUBSCRIPTION:
            if environ.get(name):
                problems.append(f"{name} está definida; em AUTH_MODE=subscription ela é proibida")
        if not environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            problems.append("CLAUDE_CODE_OAUTH_TOKEN ausente (rode `claude setup-token`)")
    elif auth_mode == "api_key":
        if not environ.get("ANTHROPIC_API_KEY"):
            problems.append("AUTH_MODE=api_key exige ANTHROPIC_API_KEY")
    else:
        problems.append(f"AUTH_MODE desconhecido: {auth_mode!r}")
    return problems


def enforce_auth_env(environ: Mapping[str, str] | None = None, auth_mode: str | None = None) -> None:
    environ = os.environ if environ is None else environ
    auth_mode = auth_mode or environ.get("AUTH_MODE", "subscription")
    forbidden = [
        p for p in check_auth_env(environ, auth_mode) if "proibida" in p or "desconhecido" in p
    ]
    if forbidden:
        raise ForbiddenEnvError("; ".join(forbidden))


class Settings(BaseSettings):
    # env_ignore_empty: `DAILY_RUN_SOFT_LIMIT=` (vazio no secrets.env) usa o padrão em vez de falhar
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False, env_ignore_empty=True)

    auth_mode: Literal["subscription", "api_key"] = "subscription"
    claude_plan: Literal["pro", "max5", "max20"] = "pro"

    agent_name: str = "Talos"
    timezone: str = "Europe/Lisbon"
    quiet_hours: str = "22:30-08:00"
    max_concurrent_agents: int = Field(default=1, ge=1, le=2)
    daily_run_soft_limit: int | None = None  # vazio = padrão do plano (pro 30, max5 60, max20 150)

    telegram_bot_token: str = ""
    telegram_allowed_chat_id: str = ""
    # onde chegam os avisos (notificações e cartões): telegram, app (Web Push do PWA) ou os dois
    notify_channels: str = "telegram,app"

    gmail_address: str = ""
    agent_inbox_tag: str = "talos"
    google_oauth_client_file: Path = Path("/etc/talos/google_client.json")

    vault_key_file: Path = Path("/etc/talos/vault.key")
    data_dir: Path = Path("/var/lib/talos")
    workspace_dir: Path = Path("/srv/talos/workspace")

    # Sistema 1 (Jev, TypeSafe): julgamentos rápidos que poupam a assinatura do Claude
    system1: Literal["jev", "off"] = "jev"
    typesafe_api_key: str = ""
    typesafe_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"

    browser_cdp_endpoint: str = "http://127.0.0.1:9222"
    mascot_model: str = "/assets/talos.glb"
    sentinel_classifier: bool = True

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    app_pin: str = ""
    allowed_tailscale_logins: str = ""  # vírgula; vazio = só PIN/local

    # Prazos (encurtáveis em teste)
    approval_ttl_hours: int = 48
    approval_reminder_hours: int = 24
    followup_business_days: int = 3
    max_followups: int = 2
    monitor_interval_seconds: int = 180
    briefing_time: str = "08:30"
    reflection_time: str = "23:00"
    organize_time: str = "09:00"  # segundas-feiras

    @field_validator("sentinel_classifier", mode="before")
    @classmethod
    def _on_off(cls, v: object) -> object:
        if isinstance(v, str) and v.lower() in {"on", "off"}:
            return v.lower() == "on"
        return v

    @field_validator("notify_channels")
    @classmethod
    def _channels(cls, v: str) -> str:
        names = [x.strip().lower() for x in v.split(",") if x.strip()]
        unknown = sorted(set(names) - set(NOTIFY_CHANNELS))
        if unknown or not names:
            raise ValueError(f"NOTIFY_CHANNELS aceita {', '.join(NOTIFY_CHANNELS)} (recebido: {v!r})")
        return ",".join(dict.fromkeys(names))

    # ---- derivados ----
    @property
    def notify_channel_set(self) -> frozenset[str]:
        return frozenset(self.notify_channels.split(","))

    @property
    def run_limit(self) -> int:
        if self.daily_run_soft_limit:
            return self.daily_run_soft_limit
        return {"pro": 30, "max5": 60, "max20": 150}[self.claude_plan]

    @property
    def planner_model(self) -> str:
        """No plano Pro o Opus no Claude Code é escasso: o planejamento usa Sonnet."""
        return "sonnet" if self.claude_plan == "pro" else "opus"

    @property
    def system1_enabled(self) -> bool:
        return self.system1 == "jev" and bool(self.typesafe_api_key)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "talos.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def agent_inbox_address(self) -> str:
        if not self.gmail_address or "@" not in self.gmail_address:
            return ""
        local, domain = self.gmail_address.split("@", 1)
        return f"{local}+{self.agent_inbox_tag}@{domain}"

    @property
    def quiet_window(self) -> tuple[time, time]:
        start, end = self.quiet_hours.split("-")
        return _parse_hhmm(start), _parse_hhmm(end)

    def secret_values(self) -> list[str]:
        """Valores que nunca podem aparecer em logs."""
        vals = [self.telegram_bot_token, self.typesafe_api_key, os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")]
        return [v for v in vals if v and len(v) >= 8]


def _parse_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(int(h), int(m))


@lru_cache
def get_settings() -> Settings:
    return Settings()
