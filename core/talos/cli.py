"""CLI: talos doctor | vault | google-auth | pause | resume | run."""

from __future__ import annotations

import asyncio
import getpass
import json
import sys

import typer

from talos.config import get_settings

app = typer.Typer(help="Talos — agente pessoal do Lucas", no_args_is_help=True, add_completion=False)
vault_app = typer.Typer(help="Cofre: dados pessoais e segredos (valores nunca aparecem no terminal)")
app.add_typer(vault_app, name="vault")
secrets_app = typer.Typer(help="Variáveis do /etc/talos/secrets.env (tokens); valores nunca aparecem no terminal")
app.add_typer(secrets_app, name="secrets")

SECRETS_FILE = "/etc/talos/secrets.env"
SECRET_KEYS = {"CLAUDE_CODE_OAUTH_TOKEN", "TYPESAFE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID",
               "GMAIL_ADDRESS", "ALLOWED_TAILSCALE_LOGINS", "APP_PIN", "CLAUDE_PLAN", "SYSTEM1"}
NOT_SECRET = {"TELEGRAM_ALLOWED_CHAT_ID", "GMAIL_ADDRESS", "ALLOWED_TAILSCALE_LOGINS", "CLAUDE_PLAN", "SYSTEM1"}


def _db():  # type: ignore[no-untyped-def]
    from talos.db.engine import Database

    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(s.db_url)
    db.migrate()
    return db


def _vault():  # type: ignore[no-untyped-def]
    from talos.vault.store import Vault, load_or_create_key

    return Vault(_db(), load_or_create_key(get_settings().vault_key_file))


@app.command()
def doctor(offline: bool = typer.Option(False, help="Não contacta serviços externos (nem o Claude)."),
           as_json: bool = typer.Option(False, "--json")) -> None:
    """Verifica a saúde do Talos (SPEC §12.4)."""
    from talos.doctor import Doctor, all_green, render

    s = get_settings()
    db = None
    try:
        db = _db()
    except Exception as e:
        typer.echo(f"❌ banco de dados: {e}")
    checks = asyncio.run(Doctor(s, db, live=not offline).run())
    if as_json:
        typer.echo(json.dumps([c.__dict__ for c in checks], ensure_ascii=False, indent=1))
    else:
        typer.echo(render(checks))
    raise typer.Exit(0 if all_green(checks) else 1)


@vault_app.command("init")
def vault_init() -> None:
    """Cria a chave do cofre (0600), se ainda não existir."""
    from talos.vault.store import load_or_create_key

    p = get_settings().vault_key_file
    existed = p.exists()
    load_or_create_key(p, create=True)
    typer.echo(f"{'Já existia' if existed else 'Criada'}: {p}")


@vault_app.command("set")
def vault_set(key: str) -> None:
    """Grava um valor sem eco no terminal. Ex.: talos vault set dados.nif"""
    value = getpass.getpass(f"Valor para {key} (não aparece enquanto digita): ")
    confirm = getpass.getpass("Repita: ")
    if value != confirm:
        typer.echo("Os valores não coincidem. Nada foi gravado.")
        raise typer.Exit(1)
    _vault().set(key, value)
    typer.echo(f"✅ {key} gravado.")


@vault_app.command("list")
def vault_list() -> None:
    """Lista só as chaves."""
    for k in _vault().list_keys():
        typer.echo(f"{k['key']}  ({k['kind']})")


@vault_app.command("delete")
def vault_delete(key: str) -> None:
    if not typer.confirm(f"Apagar {key} do cofre?"):
        raise typer.Exit(1)
    typer.echo("Apagado." if _vault().delete(key) else "Não existia.")


def write_env_value(path: str, key: str, value: str) -> None:
    """Atualiza (ou acrescenta) KEY=valor mantendo dono e permissões do ficheiro."""
    import os
    import tempfile
    from pathlib import Path

    if "\n" in value or "\r" in value:
        raise ValueError("o valor não pode ter quebras de linha")
    p = Path(path)
    lines = p.read_text().splitlines() if p.exists() else []
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == key and not line.lstrip().startswith("#"):
            if not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"{key}={value}")
    st = p.stat() if p.exists() else None
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".secrets.")
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(tmp, 0o600)
    if st is not None and os.geteuid() == 0:
        os.chown(tmp, st.st_uid, st.st_gid)
    os.replace(tmp, p)


TOKEN_PREFIX = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat", "TYPESAFE_API_KEY": "apikey_"}


def clean_token(raw: str) -> str:
    """Tokens nunca têm espaços: remove os que o terminal do celular mete ao copiar linhas quebradas."""
    return "".join(raw.split())


def token_problem(key: str, value: str) -> str | None:
    prefix = TOKEN_PREFIX.get(key)
    if prefix and not value.startswith(prefix):
        return f"{key} devia começar por {prefix}…; confira se copiou o token inteiro"
    if key == "CLAUDE_CODE_OAUTH_TOKEN" and len(value) < 60:
        return "o token parece curto demais; confira se copiou o token inteiro"
    if key == "TELEGRAM_BOT_TOKEN" and ":" not in value:
        return "o token do Telegram tem o formato 123456:ABC…"
    return None


@secrets_app.command("set")
def secrets_set(key: str, file: str = typer.Option(SECRETS_FILE, help="Ficheiro de segredos")) -> None:
    """Grava uma variável no secrets.env sem eco. Ex.: talos secrets set CLAUDE_CODE_OAUTH_TOKEN"""
    key = key.strip().upper()
    if key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        typer.echo(f"{key} é proibida em AUTH_MODE=subscription (faria o uso ser cobrado por token).")
        raise typer.Exit(1)
    if key not in SECRET_KEYS:
        typer.echo(f"Chave desconhecida. Use uma de: {', '.join(sorted(SECRET_KEYS))}")
        raise typer.Exit(1)
    if key in NOT_SECRET:
        value = input(f"Valor para {key}: ").strip()
    else:
        value = clean_token(getpass.getpass(f"Cole o valor de {key} (não aparece enquanto cola) e Enter: "))
        if clean_token(getpass.getpass("Cole de novo para confirmar: ")) != value:
            typer.echo("Os valores não coincidem. Nada foi gravado.")
            raise typer.Exit(1)
    if not value:
        typer.echo("Valor vazio. Nada foi gravado.")
        raise typer.Exit(1)
    if problem := token_problem(key, value):
        typer.echo(f"⚠️ {problem}. Nada foi gravado.")
        raise typer.Exit(1)
    write_env_value(file, key, value)
    shown = value if key in NOT_SECRET else f"{len(value)} caracteres"
    typer.echo(f"✅ {key} gravado ({shown}). Reinicie o core para aplicar: systemctl restart talos-core")


@app.command("google-auth")
def google_auth() -> None:
    """Liga a conta Google (Gmail, Calendar, Drive) sem navegador no servidor."""
    from talos.connectors.google_auth import finish_flow, start_flow

    s = get_settings()
    if not s.google_oauth_client_file.exists():
        typer.echo(f"Falta o ficheiro do cliente OAuth em {s.google_oauth_client_file}.")
        raise typer.Exit(1)
    flow, url = start_flow(s.google_oauth_client_file)
    typer.echo("1. Abra este link no celular ou no computador e aceite:\n")
    typer.echo(url + "\n")
    typer.echo("2. No fim, o navegador vai mostrar um erro (localhost). Está certo.")
    typer.echo("3. Copie o endereço COMPLETO da barra do navegador e cole aqui.\n")
    pasted = input("URL: ").strip()
    finish_flow(flow, pasted, _vault())
    typer.echo("✅ Google ligado. Rode `talos doctor` para confirmar.")


@app.command()
def pause(reason: str = typer.Option("", help="Motivo (opcional)")) -> None:
    """Botão de pânico: para workers e executor; congela propostas."""
    from talos.control import Control

    changed = Control(_db()).pause("cli", reason)
    typer.echo("⏸️ Pausado." if changed else "Já estava pausado.")


@app.command()
def resume() -> None:
    from talos.control import Control

    changed = Control(_db()).resume("cli")
    typer.echo("▶️ Retomado." if changed else "Não estava pausado.")


@app.command()
def run() -> None:
    """Arranca o talos-core (normalmente via systemd)."""
    from talos.main import run as main_run

    main_run()


@app.command()
def migrate() -> None:
    _db()
    typer.echo("Migrações aplicadas.")


if __name__ == "__main__":
    sys.exit(app())
