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
