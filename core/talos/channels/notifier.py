"""Notificações ao Lucas: respeita horas de silêncio (SPEC §11), espelha tudo no app (WS).

Canais de aviso (`NOTIFY_CHANNELS`): Telegram e/ou Web Push do app. O push sai exatamente quando a
mensagem do Telegram sairia (adiada nas horas de silêncio, imediata se urgente/silenciosa), logo a
seguir a ela; uma falha no push nunca derruba a notificação. Respostas diretas (`reply`) só vão por
push quando a conversa é no app e o app não está visível no ecrã (no Telegram, o Telegram avisa).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any

from talos.channels.base import ChatChannel
from talos.channels.cards import buttons_for, render
from talos.channels.push import (
    AppPresence,
    PushMessage,
    PushSender,
    card_message,
    notice_message,
    reply_message,
)
from talos.clock import in_quiet_hours, quiet_hours_end, utcnow
from talos.config import Settings
from talos.db.engine import Database
from talos.db.models import Conversation, Message, PendingAction
from talos.events import EventBus
from talos.logging import get_logger
from talos.scheduler.jobs import JobQueue

if TYPE_CHECKING:
    from talos.vault.store import Vault

log = get_logger("talos.notifier")

PUSH_TIMEOUT = 20  # segundos; cada POST já tem o seu timeout, isto só limita o pior caso


class Notifier:
    def __init__(self, settings: Settings, db: Database, queue: JobQueue, bus: EventBus,
                 channels: dict[str, ChatChannel], vault: Vault | None = None,
                 push: PushSender | None = None) -> None:
        self.s = settings
        self.db = db
        self.queue = queue
        self.bus = bus
        self.channels = channels
        self.vault = vault
        self.push = push
        self.presence = AppPresence()  # alimentada pelo WebSocket do app (web_api)

    @property
    def owner_chat(self) -> str:
        return self.s.telegram_allowed_chat_id

    def quiet_now(self) -> bool:
        return in_quiet_hours(utcnow(), self.s.timezone, self.s.quiet_window)

    def via(self, channel: str) -> bool:
        """O canal de aviso está ligado em NOTIFY_CHANNELS?"""
        return channel in self.s.notify_channel_set

    async def _push(self, msg: PushMessage) -> None:
        if self.push is None or not self.via("app"):
            return
        try:
            await asyncio.wait_for(self.push.send(msg), timeout=PUSH_TIMEOUT)
        except Exception as e:  # o push nunca derruba a notificação
            log.warning("push_error", kind=msg.kind, error=str(e)[:200])

    async def _both(self, telegram: Coroutine[Any, Any, None], push: PushMessage) -> None:
        """Telegram e depois push, em sequência (sem push nem inscrições, nada cede o loop: quem chama
        conta com isso). Uma falha do Telegram não impede o push, mas continua a subir como antes."""
        error: Exception | None = None
        try:
            await telegram
        except Exception as e:
            error = e
        await self._push(push)
        if error is not None:
            raise error

    # ---------- texto ----------
    async def notify(self, text: str, *, urgent: bool = False, task_id: int | None = None,
                     silent: bool = False, mascot: str | None = None) -> str:
        """Devolve 'sent' ou 'deferred'."""
        if not urgent and self.quiet_now() and not silent:
            run_after = quiet_hours_end(utcnow(), self.s.timezone, self.s.quiet_window)
            self.queue.enqueue("notify.send", {"text": text, "task_id": task_id, "mascot": mascot},
                               run_after=run_after)
            self.bus.emit("notification_deferred", {"text": text[:200]}, task_id=task_id, persist=False)
            return "deferred"
        await self._deliver(text, task_id=task_id, silent=silent, mascot=mascot, urgent=urgent)
        return "sent"

    async def _deliver(self, text: str, *, task_id: int | None, silent: bool, mascot: str | None,
                       urgent: bool = False) -> None:
        tg = self.channels.get("telegram")

        async def telegram() -> None:
            if self.via("telegram") and tg and self.owner_chat:
                for chunk in split_text(text):
                    await tg.send_text(self.owner_chat, chunk, silent=silent)

        await self._both(telegram(), notice_message(text, agent_name=self.s.agent_name, task_id=task_id,
                                                    urgent=urgent, silent=silent))
        self._log_message("telegram", text, {"task_id": task_id, "kind": "notification"})
        self.bus.emit("message", {"role": "assistant", "content": text, "task_id": task_id,
                                  "mascot": mascot}, task_id=task_id, persist=False)

    async def reply(self, channel: str, chat_id: str, text: str) -> None:
        """Resposta direta numa conversa iniciada pelo Lucas (não espera horas de silêncio).

        Push só se a conversa for no app e ele não estiver com o app aberto à frente (pediu e saiu):
        no Telegram quem avisa é o Telegram; com o app visível, a resposta já aparece na conversa.
        """
        ch = self.channels.get(channel)
        if ch is not None:
            for chunk in split_text(text):
                await ch.send_text(chat_id, chunk)
        self.bus.emit("message", {"role": "assistant", "content": text, "channel": channel}, persist=False)
        if channel == "app" and not self.presence.any_visible():
            await self._push(reply_message(text, agent_name=self.s.agent_name))

    # ---------- cartões ----------
    async def send_card(self, action: PendingAction, *, task_title: str = "", urgent: bool = False) -> str:
        if not urgent and self.quiet_now():
            run_after = quiet_hours_end(utcnow(), self.s.timezone, self.s.quiet_window)
            self.queue.enqueue("approval.card", {"action_id": action.id}, run_after=run_after,
                               dedupe_key=f"card:{action.id}")
            return "deferred"
        values = self.vault.personal_values() if self.vault else {}
        text = render(action, values, task_title, app_url=self.app_url)
        tg = self.channels.get("telegram")

        async def telegram() -> None:
            if not (self.via("telegram") and tg and self.owner_chat):
                return
            mid = await tg.send_card(self.owner_chat, text, buttons_for(action))
            with self.db.session() as s:
                row = s.get(PendingAction, action.id)
                if row:
                    refs = dict(row.card_refs_json or {})
                    refs.setdefault("telegram", []).append({"chat_id": self.owner_chat, "message_id": mid})
                    row.card_refs_json = refs
                    s.add(row)
                    s.commit()

        # no push vai só o resumo (nunca o cartão com os valores): tocar abre o cartão completo no app
        await self._both(telegram(), card_message(action, task_title))
        self.bus.emit("approval_created", {"action_id": action.id, "kind": action.kind},
                      task_id=action.task_id, persist=False)
        return "sent"

    async def close_cards(self, action: PendingAction, status_text: str) -> None:
        """Atualiza os cartões antigos (ex.: 'Aprovado ✓', 'já não está ativo')."""
        tg = self.channels.get("telegram")
        for ref in (action.card_refs_json or {}).get("telegram", []):
            if tg:
                try:
                    await tg.edit_message(ref["chat_id"], ref["message_id"], status_text)
                except Exception as e:  # cartão apagado, mensagem antiga demais…
                    log.warning("card_edit_failed", action_id=action.id, error=str(e))

    @property
    def app_url(self) -> str:
        return self.db.get_state("app").get("url", "")

    def _log_message(self, channel: str, text: str, meta: dict[str, Any]) -> None:
        from sqlmodel import select

        with self.db.session() as s:
            conv = s.exec(select(Conversation).where(Conversation.channel == channel)).first()
            if conv:
                s.add(Message(conversation_id=conv.id, role="assistant", content=text, meta_json=meta))
                s.commit()


def split_text(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks, cur = [], ""
    for para in text.split("\n"):
        if len(cur) + len(para) + 1 > limit:
            if cur:
                chunks.append(cur)
            while len(para) > limit:
                chunks.append(para[:limit])
                para = para[limit:]
            cur = para
        else:
            cur = f"{cur}\n{para}" if cur else para
    if cur:
        chunks.append(cur)
    return chunks
