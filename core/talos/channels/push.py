"""Notificações Web Push do app (PWA instalado no Android, Chrome → FCM).

- **VAPID**: o par de chaves é gerado no primeiro uso e a privada fica no cofre como segredo
  (`webpush.vapid_private`, 32 bytes em base64url); a pública (ponto P-256 não comprimido, base64url)
  é derivada dela e é o `applicationServerKey` que o app usa para se inscrever.
- **Conteúdo**: vai cifrado ponta a ponta para o navegador (aes128gcm), mas aparece no ecrã de bloqueio:
  título e corpo passam sempre pelo `REDACTOR` (nenhum valor do cofre) e o cartão de aprovação vai só
  como resumo ("Proposta #N · enviar email para X — toque para ver"). Não há botão "aprovar" na
  notificação: tocar abre o cartão completo no app.
- **Envio**: os POSTs ao serviço de push correm numa thread (`asyncio.to_thread`), em paralelo; o loop
  nunca bloqueia. 404/410 = inscrição morta → apagada; outras falhas contam e, seguidas demais, apagam.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlmodel import col, func, select

from talos.channels.cards import VERB
from talos.clock import utcnow
from talos.db.models import PendingAction, PushSubscription
from talos.logging import REDACTOR, get_logger

if TYPE_CHECKING:
    from talos.config import Settings
    from talos.db.engine import Database
    from talos.vault.store import Vault

log = get_logger("talos.push")

VAPID_KEY = "webpush.vapid_private"
TITLE_MAX = 60
BODY_MAX = 180
REQUEST_TIMEOUT = 10  # segundos por POST ao serviço de push
MAX_FAILURES = 25  # falhas seguidas (sem 404/410) antes de desistir da inscrição
MAX_SUBSCRIPTIONS = 10  # aparelhos; acima disto sai o mais antigo
# Só serviços de push conhecidos (o servidor faz POST para o endpoint: nada de URLs arbitrárias).
PUSH_HOST_SUFFIXES = ("googleapis.com", "push.services.mozilla.com", "notify.windows.com", "push.apple.com")

TTL_NOTICE = 6 * 3600
TTL_CARD = 12 * 3600
TTL_REPLY = 30 * 60
TTL_TEST = 5 * 60


class PushError(ValueError):
    """Inscrição inválida (mensagem em pt-BR, segura para mostrar no app)."""


# ------------------------------------------------------------------ mensagem
@dataclass
class PushMessage:
    title: str
    body: str
    url: str = "/"
    tag: str = ""
    kind: str = "notice"  # notice | card | reply | test
    urgency: str = "normal"  # RFC 8030: very-low | low | normal | high
    ttl: int = TTL_NOTICE
    silent: bool = False
    topic: str = ""  # RFC 8030: substitui no serviço de push uma mensagem ainda não entregue

    def payload(self) -> dict[str, Any]:
        """O que vai para o service worker: sempre redigido e cortado (redigir ANTES de cortar)."""
        out: dict[str, Any] = {
            "title": clip(REDACTOR.redact_text(squash(self.title)), TITLE_MAX) or "Talos",
            "body": clip(REDACTOR.redact_text(squash(self.body, keep_lines=True)), BODY_MAX),
            "url": safe_path(self.url),
            "tag": self.tag,
            "kind": self.kind,
            "ts": int(time.time() * 1000),
        }
        if self.silent:
            out["silent"] = True
        return out


def squash(text: str, *, keep_lines: bool = False) -> str:
    if not keep_lines:
        return " ".join((text or "").split())
    lines = [" ".join(ln.split()) for ln in (text or "").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def safe_path(url: str) -> str:
    """Só caminhos do próprio app ("/aprovacoes/3"); qualquer outra coisa vira "/"."""
    if not url or not url.startswith("/") or url.startswith("//") or "\\" in url:
        return "/"
    return url


def notice_message(text: str, *, agent_name: str = "Talos", task_id: int | None = None,
                   urgent: bool = False, silent: bool = False) -> PushMessage:
    tag = f"task-{task_id}" if task_id else f"n-{int(time.time() * 1000):x}"
    return PushMessage(title=agent_name, body=text, url="/", tag=tag, kind="notice",
                       urgency="high" if urgent else "normal", ttl=TTL_NOTICE, silent=silent)


def reply_message(text: str, *, agent_name: str = "Talos") -> PushMessage:
    return PushMessage(title=agent_name, body=text, url="/", tag="reply", kind="reply", ttl=TTL_REPLY)


def card_message(action: PendingAction, task_title: str = "") -> PushMessage:
    """Resumo do cartão: o que é e para quem. O corpo, os dados pessoais e o resto só no app."""
    p = action.payload_json or {}
    what = VERB.get(action.kind, (action.kind, ""))[0]
    if action.kind == "email.organize":
        what = "organizar a caixa de entrada"
    recips = [str(r.get("address", "")) for r in p.get("_recipients") or [] if r.get("address")]
    if not recips and p.get("to"):
        recips = [str(x) for x in (p["to"] if isinstance(p["to"], list) else [p["to"]])]
    target = ""
    if recips:
        target = f" para {recips[0]}" + (f" +{len(recips) - 1}" if len(recips) > 1 else "")
    elif isinstance(p.get("url"), str) and (host := urlparse(p["url"]).hostname):
        target = f" em {host}"
    title = "Aprovação necessária" + (f" · {task_title}" if task_title else "")
    body = f"Proposta #{action.id} · {what}{target} — toque para ver"
    tag = f"ap-{action.id}"
    return PushMessage(title=title, body=body, url=f"/aprovacoes/{action.id}", tag=tag, kind="card",
                       urgency="high", ttl=TTL_CARD, topic=tag)


def ping_message() -> PushMessage:
    return PushMessage(title="Talos", body="Notificações do Talos ligadas ✓", url="/ajustes", tag="test",
                       kind="test", urgency="high", ttl=TTL_TEST)


# ------------------------------------------------------------------ inscrições
B64URL = re.compile(r"^[A-Za-z0-9_-]+=*$")


def b64url_decode(s: str) -> bytes:
    if not s or not B64URL.match(s):
        raise ValueError("base64url inválido")
    return base64.urlsafe_b64decode(s.rstrip("=") + "=" * (-len(s.rstrip("=")) % 4))


def b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def validate_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    u = urlparse(endpoint or "")
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host:
        raise PushError("endpoint de push inválido (precisa ser https)")
    if not any(host == s or host.endswith("." + s) for s in PUSH_HOST_SUFFIXES):
        raise PushError(f"serviço de push não reconhecido: {host}")
    if len(endpoint) > 2048:
        raise PushError("endpoint de push longo demais")
    try:
        key, secret = b64url_decode(p256dh), b64url_decode(auth)
    except ValueError as e:
        raise PushError("chaves da inscrição ilegíveis") from e
    if len(key) != 65 or key[0] != 4 or len(secret) != 16:
        raise PushError("chaves da inscrição com tamanho errado")


@dataclass
class PushResult:
    sent: int = 0
    failed: int = 0
    removed: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"sent": self.sent, "failed": self.failed, "removed": self.removed}


class PushSender(Protocol):
    def public_key(self) -> str: ...

    def subscribe(self, endpoint: str, p256dh: str, auth: str, *, user_agent: str = "",
                  replaces: str = "") -> bool: ...

    def unsubscribe(self, endpoint: str) -> bool: ...

    def count(self) -> int: ...

    async def send(self, msg: PushMessage) -> PushResult: ...


class WebPushSender:
    def __init__(self, settings: Settings, db: Database, vault: Vault) -> None:
        self.s = settings
        self.db = db
        self.vault = vault
        self._vapid: Vapid | None = None
        self._lock = threading.Lock()

    # ---------- VAPID ----------
    @property
    def subject(self) -> str:
        addr = (self.s.gmail_address or "").strip()
        return f"mailto:{addr}" if "@" in addr else "mailto:talos@localhost"

    def vapid(self) -> Vapid:
        with self._lock:
            if self._vapid is None:
                raw = self.vault.get(VAPID_KEY)
                if not raw:
                    key = ec.generate_private_key(ec.SECP256R1())
                    raw = b64url_encode(key.private_numbers().private_value.to_bytes(32, "big"))
                    self.vault.set(VAPID_KEY, raw)
                    log.info("vapid_generated", key=VAPID_KEY)
                try:
                    self._vapid = Vapid.from_raw(raw.strip().encode())
                except Exception as e:
                    raise RuntimeError(f"chave VAPID inválida no cofre ({VAPID_KEY}); apague-a para gerar "
                                       "outra (os aparelhos vão precisar ligar as notificações de novo)") from e
            return self._vapid

    def public_key(self) -> str:
        pub = self.vapid().public_key.public_bytes(serialization.Encoding.X962,
                                                   serialization.PublicFormat.UncompressedPoint)
        return b64url_encode(pub)

    # ---------- inscrições ----------
    def subscribe(self, endpoint: str, p256dh: str, auth: str, *, user_agent: str = "",
                  replaces: str = "") -> bool:
        validate_subscription(endpoint, p256dh, auth)
        with self.db.session() as ss:
            if replaces and replaces != endpoint:
                old = ss.exec(select(PushSubscription).where(PushSubscription.endpoint == replaces)).first()
                if old:
                    ss.delete(old)
            row = ss.exec(select(PushSubscription).where(PushSubscription.endpoint == endpoint)).first()
            created = row is None
            if row is None:
                row = PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth)
            row.p256dh, row.auth, row.user_agent, row.failures = p256dh, auth, (user_agent or "")[:300], 0
            ss.add(row)
            ss.commit()
            rows = list(ss.exec(select(PushSubscription)))
            if len(rows) > MAX_SUBSCRIPTIONS:
                rows.sort(key=lambda r: r.last_ok_at or r.created_at)
                for extra in [r for r in rows if r.endpoint != endpoint][: len(rows) - MAX_SUBSCRIPTIONS]:
                    ss.delete(extra)
                ss.commit()
        log.info("push_subscribed", created=created, host=urlparse(endpoint).hostname)
        return created

    def unsubscribe(self, endpoint: str) -> bool:
        with self.db.session() as ss:
            row = ss.exec(select(PushSubscription).where(PushSubscription.endpoint == endpoint)).first()
            if row is None:
                return False
            ss.delete(row)
            ss.commit()
        log.info("push_unsubscribed", host=urlparse(endpoint).hostname)
        return True

    def count(self) -> int:
        with self.db.session() as ss:
            return int(ss.exec(select(func.count(col(PushSubscription.id)))).one())

    # ---------- envio ----------
    async def send(self, msg: PushMessage) -> PushResult:
        with self.db.session() as ss:
            subs = list(ss.exec(select(PushSubscription)))
        if not subs:
            return PushResult()
        vapid = self.vapid()
        data = json.dumps(msg.payload(), ensure_ascii=False)
        headers = {"Urgency": msg.urgency}
        if msg.topic:
            headers["Topic"] = msg.topic
        outcomes = await asyncio.gather(*(asyncio.to_thread(self._post, sub, data, headers, msg.ttl, vapid)
                                          for sub in subs))
        return self._book(subs, outcomes, msg.kind)

    def _post(self, sub: PushSubscription, data: str, headers: dict[str, str], ttl: int,
              vapid: Vapid) -> tuple[int, str]:
        """Corre numa thread. Devolve (status HTTP, erro); status 0 = sem resposta."""
        info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        try:
            resp = webpush(info, data=data, vapid_private_key=vapid, vapid_claims={"sub": self.subject},
                           ttl=ttl, timeout=REQUEST_TIMEOUT, headers=dict(headers))
            return int(getattr(resp, "status_code", 201) or 201), ""
        except WebPushException as e:
            return int(e.status_code or 0), str(e.message)[:200]
        except Exception as e:  # rede, chave do navegador ilegível…
            return 0, f"{type(e).__name__}: {e}"[:200]

    def _book(self, subs: list[PushSubscription], outcomes: list[tuple[int, str]], kind: str) -> PushResult:
        res = PushResult()
        now = utcnow()
        with self.db.session() as ss:
            for sub, (status, err) in zip(subs, outcomes, strict=True):
                row = ss.get(PushSubscription, sub.id)
                if row is None:
                    continue
                host = urlparse(row.endpoint).hostname
                if 200 <= status < 300:
                    res.sent += 1
                    row.last_ok_at, row.failures = now, 0
                    ss.add(row)
                elif status in (404, 410):
                    res.removed += 1
                    ss.delete(row)
                    log.info("push_subscription_gone", sub_id=row.id, host=host, status=status)
                else:
                    res.failed += 1
                    row.failures += 1
                    if row.failures >= MAX_FAILURES:
                        res.removed += 1
                        ss.delete(row)
                    else:
                        ss.add(row)
                    log.warning("push_failed", sub_id=row.id, host=host, status=status, error=err,
                                failures=row.failures)
            ss.commit()
        log.info("push_sent", kind=kind, **res.as_dict())
        return res


@dataclass
class FakePushSender:
    """Para testes: guarda o que seria enviado (já como payload redigido) e as inscrições em memória."""

    key: str = "BFakePublicKeyForTests"
    subs: dict[str, dict[str, str]] = field(default_factory=dict)
    sent: list[dict[str, Any]] = field(default_factory=list)

    def public_key(self) -> str:
        return self.key

    def subscribe(self, endpoint: str, p256dh: str, auth: str, *, user_agent: str = "",
                  replaces: str = "") -> bool:
        validate_subscription(endpoint, p256dh, auth)
        if replaces:
            self.subs.pop(replaces, None)
        created = endpoint not in self.subs
        self.subs[endpoint] = {"p256dh": p256dh, "auth": auth, "user_agent": user_agent}
        return created

    def unsubscribe(self, endpoint: str) -> bool:
        return self.subs.pop(endpoint, None) is not None

    def count(self) -> int:
        return len(self.subs)

    async def send(self, msg: PushMessage) -> PushResult:
        self.sent.append({**msg.payload(), "_urgency": msg.urgency, "_ttl": msg.ttl, "_topic": msg.topic})
        return PushResult(sent=len(self.subs))

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["kind"] == kind]


# ------------------------------------------------------------------ presença no app
class AppPresence:
    """Clientes do app ligados por WebSocket e se estão visíveis no ecrã.

    O app manda `{"type": "presence", "visible": …}` ao abrir, ao mudar de visibilidade e a cada
    25 s. Só conta como visível com um aviso recente: o Android congela o app em
    segundo plano sem fechar o socket.
    """

    FRESH_SECONDS = 70.0

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._clients: dict[Hashable, tuple[bool, float]] = {}
        self._lock = threading.Lock()

    def update(self, client: Hashable, visible: bool) -> None:
        with self._lock:
            self._clients[client] = (bool(visible), self._clock())

    def drop(self, client: Hashable) -> None:
        with self._lock:
            self._clients.pop(client, None)

    def any_visible(self) -> bool:
        now = self._clock()
        with self._lock:
            return any(v and now - t < self.FRESH_SECONDS for v, t in self._clients.values())
