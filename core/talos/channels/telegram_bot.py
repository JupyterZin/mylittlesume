"""Telegram por long polling (SPEC §11, ADR-012). Toda a lógica vive no Gateway."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from talos.channels.base import Buttons
from talos.logging import get_logger

if TYPE_CHECKING:
    from talos.channels.gateway import Gateway

log = get_logger("talos.telegram")

COMMANDS = ["start", "tarefas", "aprovacoes", "agenda", "pausar", "retomar", "uso", "tela", "cancelar"]


class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str) -> None:
        from telegram.ext import Application

        self.app = Application.builder().token(token).build()
        self.gateway: Gateway | None = None

    # ---------- ChatChannel ----------
    async def send_text(self, chat_id: str, text: str, *, silent: bool = False, reply_to: str | None = None) -> str:
        m = await self.app.bot.send_message(int(chat_id), text[:4096], disable_notification=silent)
        return str(m.message_id)

    async def send_card(self, chat_id: str, text: str, buttons: Buttons, *, silent: bool = False) -> str:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        kb = InlineKeyboardMarkup([[InlineKeyboardButton(lbl, callback_data=data) for lbl, data in row]
                                   for row in buttons])
        m = await self.app.bot.send_message(int(chat_id), text[:4096], reply_markup=kb,
                                            disable_notification=silent)
        return str(m.message_id)

    async def edit_message(self, chat_id: str, message_id: str, text: str) -> None:
        await self.app.bot.edit_message_text(text[:4096], chat_id=int(chat_id), message_id=int(message_id))

    async def send_photo(self, chat_id: str, path: str, caption: str = "", *, silent: bool = False) -> str:
        with Path(path).open("rb") as f:
            m = await self.app.bot.send_photo(int(chat_id), photo=f, caption=caption[:1024],
                                              disable_notification=silent)
        return str(m.message_id)

    # ---------- ciclo de vida ----------
    async def start(self, gateway: Gateway) -> None:
        from telegram import Update
        from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

        self.gateway = gateway
        self.app.add_handler(CommandHandler(COMMANDS, self._on_command))
        self.app.add_handler(CallbackQueryHandler(self._on_callback))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self.app.add_handler(MessageHandler(filters.VOICE, self._on_voice))
        await self.app.initialize()
        await self.app.updater.start_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)
        await self.app.start()
        log.info("telegram_started")

    async def stop(self) -> None:
        try:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
        except Exception as e:
            log.warning("telegram_stop_error", error=str(e))

    # ---------- handlers ----------
    async def _on_text(self, update: Any, _ctx: Any) -> None:
        m = update.effective_message
        reply_to = str(m.reply_to_message.message_id) if m.reply_to_message else None
        answer = await self.gateway.on_text("telegram", str(update.effective_chat.id), m.text or "",
                                            reply_to=reply_to)
        if answer:
            await m.reply_text(answer)

    async def _on_command(self, update: Any, ctx: Any) -> None:
        m = update.effective_message
        cmd = (m.text or "/").split()[0][1:].split("@")[0]
        answer = await self.gateway.on_command("telegram", str(update.effective_chat.id), cmd, list(ctx.args or []))
        if answer:
            await m.reply_text(answer)

    async def _on_callback(self, update: Any, _ctx: Any) -> None:
        q = update.callback_query
        answer = await self.gateway.on_callback("telegram", str(update.effective_chat.id), q.data or "")
        await q.answer(answer[:190])
        if answer and not answer.startswith(("Aprovado", "Recusado")):
            await q.message.reply_text(answer)

    async def _on_voice(self, update: Any, _ctx: Any) -> None:
        if not self.gateway.allowed("telegram", str(update.effective_chat.id)):
            self.gateway.reject("telegram", str(update.effective_chat.id), "voz")
            return
        await update.effective_message.reply_text("Notas de voz ainda não estão ativas; escreva por favor.")
