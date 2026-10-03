"""Serializa o acesso às APIs Google.

O `googleapiclient` usa `httplib2.Http`, que NÃO é thread-safe. O Talos chama o Gmail/Calendar/Drive
via `asyncio.to_thread` a partir do monitor, das ferramentas e do executor ao mesmo tempo; sem isto a
ligação TLS partilhada corrompe-se (`SSL: WRONG_VERSION_NUMBER`, encontrado no servidor real).
O volume é baixo, por isso um lock global é a solução mais simples e segura.
"""

from __future__ import annotations

import functools
import threading
from typing import Any

GOOGLE_LOCK = threading.RLock()


def serialized[T](cls: type[T]) -> type[T]:
    """Envolve todos os métodos públicos da classe no lock global."""
    for name, fn in list(vars(cls).items()):
        if name.startswith("_") or not callable(fn):
            continue

        @functools.wraps(fn)
        def wrapper(*args: Any, __fn: Any = fn, **kwargs: Any) -> Any:
            with GOOGLE_LOCK:
                return __fn(*args, **kwargs)

        setattr(cls, name, wrapper)
    return cls
