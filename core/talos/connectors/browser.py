"""Navegador real (SPEC §3.1, §7.2.B, §7.4; ADR-007): o Chromium persistente do `talos-browser`.

O agente controla o navegador pelo Playwright MCP (`--cdp-endpoint`). O Talos abre uma SEGUNDA
ligação CDP (Python Playwright, `connect_over_cdp`) ao mesmo Chromium, no mesmo contexto
persistente (`browser.contexts[0]`, o perfil logado), para o que o modelo nunca deve fazer
diretamente:

- `fill(alvo, valor)`: o `vault_fill` aprovado escreve um valor do cofre num campo; o valor nunca
  passa pelo modelo nem aparece em logs, erros ou no retorno;
- `screenshot()`: PNG para o cartão de aprovação da pausa síncrona;
- `current_url()`: contexto do cartão.

**Alvos.** Os refs do snapshot do MCP (`e12`, `f4e12`) só existem dentro da ligação do MCP e NÃO
são resolúveis daqui. O alvo é o rótulo visível do campo ("NIF"), o placeholder, ou um seletor
CSS (`#nif`). Ordem: rótulo exato → placeholder exato → rótulo parcial → placeholder parcial →
CSS, em todos os frames da aba; o primeiro critério que encontrar exatamente 1 campo ganha; 2+
campos = ambíguo (erro, nunca "o primeiro"). Campos de senha, cartão e códigos únicos
(`type=password`, `autocomplete=cc-*|one-time-code|*-password`) são recusados: isso é takeover.

**Que aba?** O MCP trabalha na sua "aba atual", que não se consegue perguntar por CDP. Heurística,
por ordem de desempate:
1. URL igual à última "Page URL" que o MCP reportou (`url_hint`, ligado ao `SnapshotIndex`
   da Sentinela, que vê todas as respostas do MCP);
2. aba visível (`document.visibilityState`): no Chromium com janela (Xvfb) só a aba da frente é
   visível, e o MCP faz `bringToFront()` ao abrir/selecionar abas (em headless todas são "visíveis");
3. não `about:blank` (nada para preencher nem mostrar);
4. navegação mais recente vista por esta ligação (`framenavigated` da frame principal);
5. aba mais recente.
Páginas internas (`chrome://`, `devtools://`, extensões) nunca são escolhidas.

A ligação é preguiçosa (só no primeiro uso), refeita sozinha se o Chromium reiniciar
(`Restart=always`), e cada operação tem timeout. `browser.close()` numa ligação CDP só desliga
esta ligação: o Chromium, as abas e a sessão do MCP continuam.
"""

from __future__ import annotations

import asyncio
import itertools
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from talos.logging import get_logger

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Locator, Page, Playwright

    from talos.config import Settings

log = get_logger("talos.browser")
T = TypeVar("T")

MCP_REF_RE = re.compile(r"^(f\d+)?e\d+$")
INTERNAL_SCHEMES = ("chrome://", "devtools://", "chrome-extension://", "chrome-untrusted://", "chrome-search://")
SENSITIVE_AUTOCOMPLETE = re.compile(r"^(cc-.*|one-time-code|current-password|new-password)$")
FIELD_INFO_JS = """e => ({
  tag: e.tagName.toLowerCase(),
  type: (e.getAttribute('type') || '').toLowerCase(),
  autocomplete: (e.getAttribute('autocomplete') || '').toLowerCase(),
  editable: !e.disabled && !e.readOnly && (e.isContentEditable || ['input', 'textarea'].includes(e.tagName.toLowerCase())),
})"""
# PNG 1×1 transparente (FakeBrowser)
_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


class BrowserError(RuntimeError):
    """Falha do navegador. A mensagem já vem sem valores do cofre: pode ir para o agente."""


class BrowserUnavailable(BrowserError):
    pass


class FieldNotFound(BrowserError):
    pass


class SensitiveField(BrowserError):
    pass


def _scrub(text: str, secret: str | None) -> str:
    return text.replace(secret, "•••") if secret else text


class CDPBrowser:
    def __init__(self, settings: Settings, *, url_hint: Callable[[], str | None] | None = None,
                 connect_timeout: float = 10.0, action_timeout: float = 10.0) -> None:
        self.endpoint = settings.browser_cdp_endpoint
        self.screens_dir = Path(settings.data_dir) / "screens"
        self.url_hint = url_hint
        self.connect_timeout = connect_timeout
        self.action_timeout = action_timeout
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._tick = itertools.count(1)
        self._last_nav: dict[Page, int] = {}

    # ------------------------------------------------------------------ ligação
    async def _connect(self) -> BrowserContext:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._context(self._browser)
            await self._disconnect()
            from playwright.async_api import async_playwright

            try:
                if self._pw is None:
                    self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.connect_over_cdp(
                    self.endpoint, timeout=self.connect_timeout * 1000)
            except Exception as e:
                await self._disconnect(stop_driver=True)
                raise BrowserUnavailable(f"navegador indisponível em {self.endpoint} "
                                         f"({type(e).__name__}: {str(e).splitlines()[0][:200]})") from None
            ctx = self._context(self._browser)
            for page in ctx.pages:
                self._track(page)
            ctx.on("page", self._track)
            self._browser.on("disconnected", lambda _b: log.warning("browser_disconnected", endpoint=self.endpoint))
            log.info("browser_connected", endpoint=self.endpoint, version=self._browser.version, pages=len(ctx.pages))
            return ctx

    @staticmethod
    def _context(browser: Browser) -> BrowserContext:
        if not browser.contexts:
            raise BrowserUnavailable("o Chromium não tem contexto persistente (perfil) aberto")
        return browser.contexts[0]

    def _track(self, page: Page) -> None:
        self._last_nav[page] = next(self._tick)

        def on_nav(frame: Any) -> None:
            if frame == page.main_frame:
                self._last_nav[page] = next(self._tick)

        page.on("framenavigated", on_nav)
        page.on("close", lambda p: self._last_nav.pop(p, None))

    async def _disconnect(self, *, stop_driver: bool = False) -> None:
        b, self._browser = self._browser, None
        self._last_nav.clear()
        if b is not None:
            try:
                await asyncio.wait_for(b.close(), 5)  # CDP: só desliga; o Chromium continua
            except Exception:
                pass
        if stop_driver and self._pw is not None:
            pw, self._pw = self._pw, None
            try:
                await asyncio.wait_for(pw.stop(), 5)
            except Exception:
                pass

    async def close(self) -> None:
        async with self._lock:
            await self._disconnect(stop_driver=True)

    # ------------------------------------------------------------------ aba atual
    async def _current_page(self, ctx: BrowserContext) -> Page:
        pages = [p for p in ctx.pages if not p.is_closed() and not p.url.startswith(INTERNAL_SCHEMES)]
        if not pages:
            raise BrowserError("não há nenhuma aba aberta no navegador")
        if len(pages) == 1:
            return pages[0]
        hint = None
        if self.url_hint is not None:
            try:
                hint = self.url_hint()
            except Exception:
                hint = None
        visible = await asyncio.gather(*(self._is_visible(p) for p in pages))

        def score(i: int) -> tuple[bool, bool, bool, int, int]:
            p = pages[i]
            return (bool(hint) and p.url == hint, visible[i], p.url != "about:blank",
                    self._last_nav.get(p, 0), i)

        return pages[max(range(len(pages)), key=score)]

    @staticmethod
    async def _is_visible(page: Page) -> bool:
        try:
            return await asyncio.wait_for(page.evaluate("document.visibilityState"), 2) == "visible"
        except Exception:
            return False

    async def _with_page(self, op: Callable[[Page], Awaitable[T]]) -> T:
        """Executa `op` na aba atual; se a ligação caiu (Chromium reiniciado), religa e tenta 1 vez."""
        for attempt in (1, 2):
            ctx = await self._connect()
            page = await self._current_page(ctx)
            try:
                return await op(page)
            except BrowserError:
                raise
            except Exception as e:
                lost = self._browser is None or not self._browser.is_connected() or \
                    type(e).__name__ == "TargetClosedError"
                if attempt == 1 and lost:
                    log.warning("browser_retry", error=type(e).__name__)
                    async with self._lock:
                        await self._disconnect()
                    continue
                raise
        raise BrowserUnavailable("navegador indisponível")  # pragma: no cover

    # ------------------------------------------------------------------ API
    async def current_url(self) -> str:
        async def op(page: Page) -> str:
            return page.url

        return await self._with_page(op)

    async def screenshot(self) -> str:
        """PNG da área visível da aba atual, em data_dir/screens (para o cartão de aprovação)."""
        self.screens_dir.mkdir(parents=True, exist_ok=True)
        path = self.screens_dir / f"aprovacao-{datetime.now(UTC):%Y%m%dT%H%M%S%f}.png"

        async def op(page: Page) -> str:
            await page.screenshot(path=str(path), timeout=self.action_timeout * 1000)
            return str(path)

        try:
            return await self._with_page(op)
        except BrowserError:
            raise
        except Exception as e:
            raise BrowserError(f"screenshot falhou: {type(e).__name__}: {str(e).splitlines()[0][:200]}") from None

    async def fill(self, target: str, value: str) -> str:
        """Preenche o campo `target` (rótulo, placeholder ou CSS) com `value`.

        Devolve uma descrição do campo (sem o valor). Nunca registra nem devolve o valor; os erros
        saem sem ele e sem a exceção original encadeada (tracebacks também não o levam).
        """
        target = (target or "").strip()
        if not target:
            raise FieldNotFound("indique o campo: rótulo visível (ex.: 'NIF'), placeholder ou seletor CSS")
        if MCP_REF_RE.match(target):
            raise FieldNotFound(f"'{target}' é um ref do snapshot do Playwright MCP e não serve aqui; use o "
                                "rótulo visível do campo (ex.: 'NIF'), o placeholder ou um seletor CSS (ex.: #nif)")

        async def op(page: Page) -> str:
            loc, how = await self._locate(page, target)
            info = await loc.evaluate(FIELD_INFO_JS, timeout=self.action_timeout * 1000)
            tokens = info["autocomplete"].split()
            if info["type"] == "password" or any(SENSITIVE_AUTOCOMPLETE.match(t) for t in tokens):
                raise SensitiveField(f"'{target}' é um campo de senha, cartão ou código: só o Lucas preenche "
                                     "(takeover na Tela)")
            if not info["editable"]:
                raise BrowserError(f"'{target}' não é um campo editável ({info['tag']})")
            await loc.fill(value, timeout=self.action_timeout * 1000)
            return f"{how} '{target}'"

        try:
            desc = await self._with_page(op)
        except BrowserError as e:
            raise type(e)(_scrub(str(e), value)) from None
        except Exception as e:
            msg = _scrub(f"{type(e).__name__}: {str(e).splitlines()[0][:300]}", value)
            raise BrowserError(f"não consegui preencher '{target}': {msg}") from None
        log.info("browser_filled", field=target, how=desc.split(" ", 1)[0])
        return desc

    async def _locate(self, page: Page, target: str) -> tuple[Locator, str]:
        strategies: list[tuple[str, Callable[[Any], Locator]]] = [
            ("rótulo", lambda f: f.get_by_label(target, exact=True)),
            ("placeholder", lambda f: f.get_by_placeholder(target, exact=True)),
            ("rótulo", lambda f: f.get_by_label(target)),
            ("placeholder", lambda f: f.get_by_placeholder(target)),
            ("seletor", lambda f: f.locator(target)),
        ]
        for how, make in strategies:
            found: list[Locator] = []
            total = 0
            for frame in page.frames:
                try:
                    loc = make(frame)
                    n = await asyncio.wait_for(loc.count(), self.action_timeout)
                except Exception:  # CSS inválido, frame a ser destruído…
                    continue
                if n:
                    found.append(loc)
                    total += n
            if total == 1:
                return found[0], how
            if total > 1:
                raise FieldNotFound(f"'{target}' corresponde a {total} campos ({how}); seja mais específico "
                                    "(ex.: um seletor CSS como #nif)")
        raise FieldNotFound(f"campo '{target}' não encontrado na página {page.url}")


class FakeBrowser:
    """Navegador falso para testes (SPEC §15): mesma interface do CDPBrowser."""

    def __init__(self, screens_dir: Path | None = None, url: str = "http://127.0.0.1:9000/formulario.html") -> None:
        self.screens_dir = Path(screens_dir) if screens_dir else None
        self.url = url
        self.filled: dict[str, str] = {}
        self.screenshots: list[str] = []
        self.fail_with: BrowserError | None = None

    async def fill(self, target: str, value: str) -> str:
        if self.fail_with:
            raise self.fail_with
        if MCP_REF_RE.match(target or ""):
            raise FieldNotFound(f"'{target}' é um ref do snapshot do Playwright MCP e não serve aqui")
        self.filled[target] = value
        return f"rótulo '{target}'"

    async def screenshot(self) -> str:
        if self.screens_dir is None:
            raise BrowserError("FakeBrowser sem screens_dir")
        self.screens_dir.mkdir(parents=True, exist_ok=True)
        path = self.screens_dir / f"aprovacao-fake-{len(self.screenshots) + 1}.png"
        path.write_bytes(_PNG_1PX)
        self.screenshots.append(str(path))
        return str(path)

    async def current_url(self) -> str:
        return self.url

    async def close(self) -> None:
        return None
