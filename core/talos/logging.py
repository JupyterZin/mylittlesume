"""Logs JSON (journald) com redação de valores do cofre e de segredos (SPEC §7.4)."""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any

import structlog


class Redactor:
    """Guarda os valores sensíveis conhecidos e os substitui por [REDACTED:<nome>]."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[str, str] = {}

    def register(self, name: str, value: str | None) -> None:
        if not value or len(value) < 3:
            return
        with self._lock:
            self._values[value] = name

    def forget(self, name: str) -> None:
        with self._lock:
            for v in [v for v, n in self._values.items() if n == name]:
                del self._values[v]

    def redact_text(self, text: str) -> str:
        with self._lock:
            items = sorted(self._values.items(), key=lambda kv: -len(kv[0]))
        for value, name in items:
            if value in text:
                text = text.replace(value, f"[REDACTED:{name}]")
        return text

    def redact(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self.redact_text(obj)
        if isinstance(obj, dict):
            return {k: self.redact(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return type(obj)(self.redact(v) for v in obj)
        return obj

    def __call__(self, _logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        return self.redact(event_dict)


REDACTOR = Redactor()


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    renderer: Any = structlog.processors.JSONRenderer(ensure_ascii=False) if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            REDACTOR,  # sempre por último antes do renderer
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
    # bibliotecas que usam logging padrão também passam pela redação
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_StdlibRedactFilter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    for noisy in ("httpx", "telegram", "googleapiclient.discovery_cache", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class _StdlibRedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = REDACTOR.redact_text(str(record.msg))
        if record.args:
            record.args = tuple(REDACTOR.redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def get_logger(name: str = "talos") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
