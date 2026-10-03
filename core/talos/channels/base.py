"""Interface comum dos canais de conversa (Telegram, app)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

Buttons = list[list[tuple[str, str]]]  # linhas de (rótulo, callback_data)


class ChatChannel(Protocol):
    name: str

    async def send_text(self, chat_id: str, text: str, *, silent: bool = False,
                        reply_to: str | None = None) -> str: ...

    async def send_card(self, chat_id: str, text: str, buttons: Buttons, *, silent: bool = False) -> str: ...

    async def edit_message(self, chat_id: str, message_id: str, text: str) -> None: ...

    async def send_photo(self, chat_id: str, path: str, caption: str = "", *, silent: bool = False) -> str: ...


@dataclass
class FakeChannel:
    """Canal falso para testes (FakeTelegram)."""

    name: str = "telegram"
    sent: list[dict[str, Any]] = field(default_factory=list)
    _n: int = 0

    def _id(self) -> str:
        self._n += 1
        return str(self._n)

    async def send_text(self, chat_id: str, text: str, *, silent: bool = False, reply_to: str | None = None) -> str:
        mid = self._id()
        self.sent.append({"type": "text", "chat_id": chat_id, "text": text, "silent": silent, "id": mid})
        return mid

    async def send_card(self, chat_id: str, text: str, buttons: Buttons, *, silent: bool = False) -> str:
        mid = self._id()
        self.sent.append({"type": "card", "chat_id": chat_id, "text": text, "buttons": buttons,
                          "silent": silent, "id": mid})
        return mid

    async def edit_message(self, chat_id: str, message_id: str, text: str) -> None:
        self.sent.append({"type": "edit", "chat_id": chat_id, "id": message_id, "text": text})

    async def send_photo(self, chat_id: str, path: str, caption: str = "", *, silent: bool = False) -> str:
        mid = self._id()
        self.sent.append({"type": "photo", "chat_id": chat_id, "path": path, "caption": caption, "id": mid})
        return mid

    # asserts
    def texts(self) -> list[str]:
        return [m["text"] for m in self.sent if m["type"] == "text"]

    def cards(self) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["type"] == "card"]
