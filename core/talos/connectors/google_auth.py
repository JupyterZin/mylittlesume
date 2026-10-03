"""OAuth Google para um servidor sem navegador (ADR-013).

Fluxo: `InstalledAppFlow` com redirect loopback; o Lucas abre a URL no celular/PC, o navegador
"falha" ao abrir localhost e ele cola de volta a URL completa. O token fica no cofre
(`google.token`, classe segredo) e nunca é exposto ao agente.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from talos.vault.store import Vault

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]
TOKEN_KEY = "google.token"
REDIRECT_URI = "http://localhost:8765/"


class GoogleAuthError(RuntimeError):
    """`invalid_grant` e afins: o Lucas precisa reautenticar (RUNBOOK)."""


def start_flow(client_file: Path) -> tuple[Any, str]:
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    url, _state = flow.authorization_url(access_type="offline", prompt="consent")
    return flow, url


def finish_flow(flow: Any, pasted: str, vault: Vault) -> None:
    pasted = pasted.strip()
    if pasted.startswith("http://"):
        pasted = pasted.replace("http://", "https://", 1)  # o oauthlib exige https; é só loopback
    if pasted.startswith("https://"):
        flow.fetch_token(authorization_response=pasted)
    else:
        flow.fetch_token(code=pasted)
    vault.set(TOKEN_KEY, flow.credentials.to_json())


def load_credentials(vault: Vault) -> Any:
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    raw = vault.get(TOKEN_KEY)
    if not raw:
        raise GoogleAuthError("sem token Google no cofre (rode `talos google-auth`)")
    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise GoogleAuthError(f"renovação do token Google falhou: {e}") from e
        vault.set(TOKEN_KEY, creds.to_json())
    return creds
