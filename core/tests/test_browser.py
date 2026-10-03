"""Navegador real (Fase 4, SPEC §7.2.B, §7.4, W5): CDPBrowser contra um Chromium headless de verdade e o
formulário local de teste (infra/testpages), passando pelo mesmo portão (Sentinela + aprovações) que o
runtime real. Os testes `slow` falam com o @playwright/mcp 0.0.83 REAL via npx (ADR-007):
    .venv/bin/pytest -q -m slow

Pulados sozinhos se não houver Chromium do Playwright (PLAYWRIGHT_BROWSERS_PATH, /opt/pw-browsers…)
ou npx. Nunca rodam `playwright install`: o Chromium é aberto direto, com --remote-debugging-port.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import http.server
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import select

pytest.importorskip("playwright")
from playwright.async_api import Page, async_playwright  # noqa: E402

from talos.connectors.browser import (  # noqa: E402
    BrowserUnavailable,
    CDPBrowser,
    FakeBrowser,
    FieldNotFound,
    SensitiveField,
)
from talos.db.models import PendingAction  # noqa: E402
from tests.test_browser_snapshots import SNAP_FORM  # noqa: E402

PW = "mcp__playwright__"
TESTPAGES = Path(__file__).resolve().parents[2] / "infra" / "testpages"
NIF = "123456789"  # dados.nif do harness `h`


# ======================================================================== infraestrutura de teste
def find_chromium() -> str | None:
    if (p := os.environ.get("TALOS_TEST_CHROMIUM")) and os.access(p, os.X_OK):
        return p
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), "/opt/pw-browsers", "/opt/talos/pw-browsers",
             str(Path.home() / ".cache" / "ms-playwright")]
    for root in filter(None, roots):
        for pattern in ("chromium-*/chrome-linux*/chrome", "chromium_headless_shell-*/chrome-linux*/headless_shell"):
            for exe in sorted(Path(root).glob(pattern), reverse=True):
                if os.access(exe, os.X_OK):
                    return str(exe)
    return None


CHROMIUM = find_chromium()
NPX = shutil.which("npx")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Chromium:
    """Chromium headless com CDP só em 127.0.0.1, como o talos-browser (sem Xvfb)."""

    def __init__(self, exe: str, profile: Path, port: int | None = None) -> None:
        self.exe, self.profile, self.port = exe, profile, port or _free_port()
        self.proc: subprocess.Popen[bytes] | None = None

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [self.exe, "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
             "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"Chromium saiu com código {self.proc.returncode}")
            try:
                opener.open(self.endpoint + "/json/version", timeout=1).read()
                return
            except OSError:
                time.sleep(0.1)
        self.stop()
        raise RuntimeError("Chromium não abriu o CDP em 20 s")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(5)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_a: Any) -> None:
        pass


@pytest.fixture(scope="module")
def site() -> Any:
    """infra/testpages servido em 127.0.0.1:<porta livre> (o testpage.sh usa a 9000)."""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0),
                                          functools.partial(_QuietHandler, directory=str(TESTPAGES)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture(scope="module")
def chromium(tmp_path_factory: pytest.TempPathFactory) -> Any:
    if CHROMIUM is None:
        pytest.skip("Chromium do Playwright não encontrado (PLAYWRIGHT_BROWSERS_PATH)")
    c = Chromium(CHROMIUM, tmp_path_factory.mktemp("perfil"))
    try:
        c.start()
    except (RuntimeError, OSError) as e:
        pytest.skip(f"Chromium não arrancou: {e}")
    yield c
    c.stop()


@pytest.fixture
async def driver(chromium: Chromium, site: str) -> AsyncIterator[Page]:
    """Ligação CDP independente no papel do Playwright MCP: uma única aba, no formulário de teste."""
    async with async_playwright() as pw:
        b = await pw.chromium.connect_over_cdp(chromium.endpoint)
        ctx = b.contexts[0]
        pages = list(ctx.pages)
        page = pages[0] if pages else await ctx.new_page()
        for extra in pages[1:]:
            await extra.close()
        await page.goto(f"{site}/formulario.html")
        yield page
        await b.close()


def _settings(tmp_settings: Any, endpoint: str) -> Any:
    return tmp_settings.model_copy(update={"browser_cdp_endpoint": endpoint})


@pytest.fixture
async def cdp(tmp_settings: Any, chromium: Chromium) -> AsyncIterator[CDPBrowser]:
    b = CDPBrowser(_settings(tmp_settings, chromium.endpoint), action_timeout=5)
    yield b
    await b.close()


def _task(h: Any) -> Any:
    t = h.app.tasks.create("Pedido de ligação de gás", "Preencher o formulário da Empresa Teste")
    h.app.tasks.update(t.id, status="running")
    h.app.queue.enqueue("agent.task_run", {"event": None}, task_id=t.id)
    return t


async def _lucas(h: Any, decisions: list[str], on_pending: Any = None, timeout: float = 60) -> list[int]:
    """O Lucas no Telegram: decide cada proposta nova, por ordem ('a' aprovar, 'r' recusar)."""
    seen: list[int] = []
    deadline = time.monotonic() + timeout
    while len(seen) < len(decisions):
        if time.monotonic() > deadline:
            raise AssertionError(f"esperava {len(decisions)} propostas, vi {len(seen)}")
        await asyncio.sleep(0.03)
        for a in h.app.approvals.list_pending():
            if a.id in seen:
                continue
            if on_pending:
                await on_pending(a)
            await h.tap(f"ap:{a.id}:{decisions[len(seen)]}")
            seen.append(a.id)
    return seen


def _actions(h: Any) -> list[PendingAction]:
    with h.app.db.session() as s:
        return list(s.exec(select(PendingAction).order_by(PendingAction.id)))


VAULT_FILL_NIF = {"selector": "NIF", "key": "dados.nif", "field_description": "NIF no pedido de ligação (Empresa Teste)"}


# ======================================================================== CDPBrowser
async def test_fill_by_label_placeholder_and_css(cdp: CDPBrowser, driver: Page) -> None:
    assert await cdp.fill("NIF", NIF) == "rótulo 'NIF'"
    assert await cdp.fill("Nome completo", "Lucas Teste Silva") == "placeholder 'Nome completo'"
    assert await cdp.fill("#morada", "Rua das Flores 12, 1200-195 Lisboa") == "seletor '#morada'"
    assert await cdp.fill("input[name=email]", "lucas@exemplo.pt") == "seletor 'input[name=email]'"
    assert await driver.input_value("#nif") == NIF
    assert await driver.input_value("#nome") == "Lucas Teste Silva"
    assert await driver.input_value("#morada") == "Rua das Flores 12, 1200-195 Lisboa"
    assert await driver.input_value("#email") == "lucas@exemplo.pt"
    assert await driver.locator("#sucesso").is_hidden()  # preencher nunca submete


REFUSALS = [
    ("e13", FieldNotFound, "ref do snapshot"),
    ("f4e13", FieldNotFound, "ref do snapshot"),
    ("Palavra-passe", SensitiveField, "takeover"),  # type=password
    ("Número do cartão", SensitiveField, "takeover"),  # autocomplete=cc-number
    ("Campo que não existe", FieldNotFound, "não encontrado"),
    ("input", FieldNotFound, "corresponde a 6 campos"),  # ambíguo: nunca "o primeiro"
    ("", FieldNotFound, "indique o campo"),
]


async def test_fill_refuses_without_leaking_the_value(cdp: CDPBrowser, driver: Page) -> None:
    for target, exc, msg in REFUSALS:
        with pytest.raises(exc) as ei:
            await cdp.fill(target, NIF)
        assert msg in str(ei.value), target
        assert NIF not in str(ei.value)
        # o traceback não leva a exceção original (que poderia citar o valor)
        assert ei.value.__cause__ is None and (ei.value.__context__ is None or ei.value.__suppress_context__)
    for sel in ("#nif", "#senha", "#cartao", "#nome"):
        assert await driver.input_value(sel) == ""


async def test_screenshot_and_current_url(cdp: CDPBrowser, driver: Page, tmp_settings: Any) -> None:
    path = Path(await cdp.screenshot())
    assert path.parent == tmp_settings.data_dir / "screens"
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and path.stat().st_size > 1000
    assert await cdp.current_url() == driver.url


async def test_picks_the_tab_the_mcp_is_working_on(cdp: CDPBrowser, driver: Page, site: str) -> None:
    other = await driver.context.new_page()
    await other.goto(f"{site}/armadilhas.html")
    try:
        cdp.url_hint = lambda: driver.url  # a última "Page URL" que o MCP reportou
        assert await cdp.current_url() == driver.url
        await cdp.fill("NIF", NIF)
        assert await driver.input_value("#nif") == NIF
        cdp.url_hint = lambda: other.url
        assert await cdp.current_url() == other.url
        # sem pista (headless: todas as abas "visíveis"): ganha a navegação mais recente
        cdp.url_hint = None
        await driver.reload()
        assert await cdp.current_url() == driver.url
        await other.reload()
        assert await cdp.current_url() == other.url
    finally:
        await other.close()
    assert await cdp.current_url() == driver.url


async def test_unavailable_then_reconnects_after_chromium_restart(tmp_settings: Any, tmp_path: Path) -> None:
    if CHROMIUM is None:
        pytest.skip("Chromium do Playwright não encontrado")
    c = Chromium(CHROMIUM, tmp_path / "perfil")
    b = CDPBrowser(_settings(tmp_settings, c.endpoint), connect_timeout=3, action_timeout=3)
    try:
        with pytest.raises(BrowserUnavailable, match="navegador indisponível"):
            await b.current_url()  # Chromium ainda desligado
        c.start()
        assert await b.current_url() == "about:blank"  # ligação preguiçosa, refeita
        c.stop()  # talos-browser reiniciado (Restart=always)
        for _ in range(100):
            if b._browser is None or not b._browser.is_connected():
                break
            await asyncio.sleep(0.05)
        with pytest.raises(BrowserUnavailable):
            await b.current_url()
        c.start()
        assert await b.current_url() == "about:blank"
    finally:
        await b.close()
        c.stop()


# ======================================================================== ponta a ponta pelo portão
async def test_vault_fill_approved_fills_the_real_field(h: Any, cdp: CDPBrowser, driver: Page) -> None:
    h.app.browser = cdp
    h.rt.pause_seconds = 20
    out: dict[str, str] = {}

    async def agent_script(agent: Any) -> str:
        out["r"] = await agent.call("mcp__talos__vault_fill", VAULT_FILL_NIF)
        return "—"

    h.rt.on(lambda r: r.task_id is not None, agent_script)
    t = _task(h)

    async def before_approval(a: PendingAction) -> None:
        assert await driver.input_value("#nif") == ""  # nada antes do sim do Lucas
        assert a.kind == "share_data" and a.payload_json["_data_keys"] == ["dados.nif"]

    await asyncio.gather(h.drain(), _lucas(h, ["a"], before_approval))
    assert await driver.input_value("#nif") == NIF
    assert out["r"] == "Preenchidos: rótulo 'NIF' ← dados.nif"
    (a,) = _actions(h)
    assert a.status == "executed"
    assert "NIF" in h.tg.cards()[-1]["text"]
    assert "dados.nif" in h.app.tasks.authorized_keys(t.id)
    assert NIF not in str(a.payload_json)  # o valor nunca entra na proposta, só a chave


@pytest.mark.parametrize("decision,expected", [("r", "não aprovou"), (None, "Pausado aguardando aprovação")])
async def test_vault_fill_without_approval_fills_nothing(h: Any, cdp: CDPBrowser, driver: Page,
                                                         decision: str | None, expected: str) -> None:
    h.app.browser = cdp
    h.rt.pause_seconds = 20 if decision else 0.3
    out: dict[str, str] = {}

    async def agent_script(agent: Any) -> str:
        out["r"] = await agent.call("mcp__talos__vault_fill", VAULT_FILL_NIF)
        return "—"

    h.rt.on(lambda r: r.task_id is not None and not r.resume_session_id, agent_script)
    h.rt.reply("—", when=lambda r: r.resume_session_id is not None)
    _task(h)
    if decision:
        await asyncio.gather(h.drain(), _lucas(h, [decision]))
    else:
        await h.drain()
    assert expected in out["r"]
    assert await driver.input_value("#nif") == ""


async def test_form_until_submit_card_with_screenshot_then_submit(h: Any, cdp: CDPBrowser, driver: Page,
                                                                  tmp_settings: Any) -> None:
    """Critério da Fase 4: preencher até antes de submeter → cartão com screenshot → submeter só depois do sim.
    O MCP aqui é simulado com o snapshot REAL capturado (refs e10/e13/e29); o teste `slow` usa o MCP de verdade."""
    h.app.browser = cdp
    h.rt.pause_seconds = 20
    clicks: list[str] = []

    async def navigate(_args: dict[str, Any]) -> str:
        return SNAP_FORM

    async def type_text(args: dict[str, Any]) -> str:
        await driver.fill({"e19": "#email"}[args["target"]], args["text"])
        return "ok"

    async def click(args: dict[str, Any]) -> str:
        clicks.append(args["target"])
        await driver.get_by_role("button", name="Submeter pedido").click()
        return "ok"

    h.rt.external_tools.update({PW + "browser_navigate": navigate, PW + "browser_type": type_text,
                                PW + "browser_click": click})
    res: dict[str, str] = {}

    async def agent_script(agent: Any) -> str:
        await agent.call(PW + "browser_navigate", {"url": driver.url})
        # campo não sensível e valor fora do cofre: passa direto (o nome completo, que está no cofre, pediria
        # aprovação pelo egress)
        res["email"] = await agent.call(PW + "browser_type", {"element": "Email", "target": "e19",
                                                              "text": "lucas@exemplo.pt"})
        res["nif"] = await agent.call("mcp__talos__vault_fill", VAULT_FILL_NIF)
        # descrição enganosa: a Sentinela avalia o texto real do e29 ("Submeter pedido")
        res["submit"] = await agent.call(PW + "browser_click", {"element": "Ver detalhes", "target": "e29"})
        return "Pedido submetido."

    h.rt.on(lambda r: r.task_id is not None, agent_script)
    _task(h)
    state: dict[str, Any] = {}

    async def check(a: PendingAction) -> None:
        if a.payload_json.get("tool") == PW + "browser_click":
            state["hidden_before"] = await driver.locator("#sucesso").is_hidden()
            state["nif_before"] = await driver.input_value("#nif")

    await asyncio.gather(h.drain(), _lucas(h, ["a", "a"], check))

    assert res["email"] == "ok" and res["submit"] == "ok" and clicks == ["e29"]
    assert state == {"hidden_before": True, "nif_before": NIF}  # tudo preenchido, nada submetido
    assert await driver.locator("#sucesso").is_visible()
    sub = await driver.evaluate("window.submissoes")
    assert sub == [{"nome": "", "nif": NIF, "morada": "", "email": "lucas@exemplo.pt", "senha": "", "cartao": ""}]

    fill_action, click_action = _actions(h)
    assert fill_action.kind == "share_data" and click_action.kind == "browser.submit"
    assert 'elemento real: button "Submeter pedido"' in click_action.preview_text
    shot = Path(click_action.payload_json["screenshot"])
    assert shot.parent == tmp_settings.data_dir / "screens" and shot.read_bytes()[:4] == b"\x89PNG"
    photos = [m for m in h.tg.sent if m["type"] == "photo"]
    # o cartão do clique final leva o screenshot (o do vault_fill também leva o seu)
    assert [p["path"] for p in photos][-1] == str(shot) and len(photos) == 2
    assert [p["caption"] for p in photos] == [f"Proposta #{fill_action.id}", f"Proposta #{click_action.id}"]


async def test_password_and_card_are_takeover_never_typed(h: Any, cdp: CDPBrowser, driver: Page) -> None:
    h.app.browser = cdp
    h.rt.pause_seconds = 20
    typed: list[Any] = []

    async def navigate(_args: dict[str, Any]) -> str:
        return SNAP_FORM

    async def type_text(args: dict[str, Any]) -> str:
        typed.append(args)
        return "ok"

    h.rt.external_tools.update({PW + "browser_navigate": navigate, PW + "browser_type": type_text,
                                PW + "browser_fill_form": type_text})
    res: dict[str, str] = {}

    async def agent_script(agent: Any) -> str:
        await agent.call(PW + "browser_navigate", {"url": driver.url})
        res["senha"] = await agent.call(PW + "browser_type", {"element": "campo de texto", "target": "e24",
                                                              "text": "hunter2"})
        res["cartao"] = await agent.call(PW + "browser_fill_form", {"fields": [
            {"name": "Campo 6", "type": "textbox", "target": "e27", "value": "4111111111111111"}]})
        # mesmo aprovado, o vault_fill recusa campos de senha (defesa em profundidade)
        res["vault"] = await agent.call("mcp__talos__vault_fill", {**VAULT_FILL_NIF, "selector": "Palavra-passe"})
        return "—"

    h.rt.on(lambda r: r.task_id is not None, agent_script)
    _task(h)
    await asyncio.gather(h.drain(), _lucas(h, ["a"]))
    assert typed == []
    assert res["senha"].startswith("TAKEOVER") and res["cartao"].startswith("TAKEOVER")
    assert "takeover" in res["vault"] and NIF not in res["vault"]
    assert await driver.input_value("#senha") == "" and await driver.input_value("#cartao") == ""
    assert any("assuma a Tela" in t for t in h.tg.texts())


async def test_fake_browser_flow(h: Any, tmp_settings: Any) -> None:
    """Sem Chromium: o mesmo fluxo com o FakeBrowser (screenshot no cartão + vault_fill aprovado)."""
    fake = FakeBrowser(tmp_settings.data_dir / "screens")
    h.app.browser = fake
    h.rt.pause_seconds = 20

    async def navigate(_args: dict[str, Any]) -> str:
        return SNAP_FORM

    async def click(_args: dict[str, Any]) -> str:
        return "ok"

    h.rt.external_tools.update({PW + "browser_navigate": navigate, PW + "browser_click": click})
    res: dict[str, str] = {}

    async def agent_script(agent: Any) -> str:
        await agent.call(PW + "browser_navigate", {"url": fake.url})
        res["ref"] = await agent.call("mcp__talos__vault_fill", {**VAULT_FILL_NIF, "selector": "e13"})
        res["nif"] = await agent.call("mcp__talos__vault_fill", VAULT_FILL_NIF)
        res["submit"] = await agent.call(PW + "browser_click", {"element": "Submeter pedido", "target": "e29"})
        return "—"

    h.rt.on(lambda r: r.task_id is not None, agent_script)
    _task(h)
    await asyncio.gather(h.drain(), _lucas(h, ["a", "a", "a"]))
    assert "ref do snapshot" in res["ref"]
    assert fake.filled == {"NIF": NIF}
    assert res["submit"] == "ok"
    assert _actions(h)[-1].payload_json["screenshot"] == fake.screenshots[-1]


# ======================================================================== Playwright MCP 0.0.83 real (slow)
@contextlib.asynccontextmanager
async def mcp_session(endpoint: str, settings: Any) -> AsyncIterator[Any]:
    """O MCP como o ClaudeRuntime o arranca (`_playwright_server`), com cwd = workspace (como o CLI)."""
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    from talos.runtime.claude import PLAYWRIGHT_MCP

    out = settings.data_dir / "screens"
    params = StdioServerParameters(
        command=NPX, args=["-y", PLAYWRIGHT_MCP, "--cdp-endpoint", endpoint, "--output-dir", str(out),
                           "--image-responses", "omit"],
        cwd=str(settings.workspace_dir), env=dict(os.environ))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await asyncio.wait_for(s.initialize(), 180)
        yield s


def _text(res: Any) -> str:
    return "\n".join(getattr(c, "text", "") for c in res.content)


@pytest.mark.slow
@pytest.mark.skipif(NPX is None, reason="npx não encontrado")
async def test_real_mcp_tools_match_sentinel_rules(chromium: Chromium, tmp_settings: Any) -> None:
    from talos.sentinel.policy import READ_ONLY_BROWSER, Sentinel, ToolCall

    async with mcp_session(chromium.endpoint, tmp_settings) as s:
        tools = {t.name: t.input_schema for t in (await s.list_tools()).tools}
    props = {name: set(schema.get("properties", {})) for name, schema in tools.items()}
    expected = {
        "browser_click": {"element", "target"}, "browser_type": {"element", "target", "text", "submit"},
        "browser_fill_form": {"fields"}, "browser_select_option": {"element", "target", "values"},
        "browser_press_key": {"key"}, "browser_navigate": {"url"}, "browser_tabs": {"action", "url"},
        "browser_evaluate": {"function"}, "browser_run_code_unsafe": {"code"}, "browser_file_upload": {"paths"},
        "browser_drag": {"startElement", "startTarget", "endElement", "endTarget"},
        "browser_drop": {"element", "target", "paths"}, "browser_snapshot": set(),
        "browser_take_screenshot": set(), "browser_handle_dialog": {"accept"}, "browser_hover": {"element", "target"},
    }
    for name, want in expected.items():
        assert want <= props[name], (name, props.get(name))
    assert tools["browser_click"]["required"] == ["target"]  # `target` (ref ou seletor), não `ref`
    field = tools["browser_fill_form"]["properties"]["fields"]["items"]
    assert {"name", "type", "target", "value"} <= set(field["required"])
    assert {n.removeprefix(PW) for n in READ_ONLY_BROWSER} <= set(tools)
    # todas as ferramentas reais caem numa regra explícita (nenhuma no `default`)
    sentinel = Sentinel(workspace_dir=tmp_settings.workspace_dir)
    for name in tools:
        d = await sentinel.evaluate(ToolCall(PW + name, {}), ["mcp__playwright__*"])
        assert d.rule_id is not None, name


@pytest.mark.slow
@pytest.mark.skipif(NPX is None, reason="npx não encontrado")
async def test_real_mcp_snapshot_format_is_indexed(chromium: Chromium, driver: Page, site: str,
                                                   tmp_settings: Any) -> None:
    from talos.sentinel.policy import SnapshotIndex

    async with mcp_session(chromium.endpoint, tmp_settings) as s:
        nav = _text(await s.call_tool("browser_navigate", {"url": f"{site}/armadilhas.html"}))
        snap = _text(await s.call_tool("browser_snapshot", {}))
    # as ações devolvem o snapshot num ficheiro; o browser_snapshot explícito, inline
    m = re.search(r"- \[Snapshot\]\(([^)]+\.yml)\)", nav)
    assert m and "```yaml" in snap and f"- Page URL: {site}/armadilhas.html" in nav
    idx = SnapshotIndex(base_dir=tmp_settings.workspace_dir, allowed_dirs=[tmp_settings.data_dir / "screens"])
    idx.ingest(nav)  # lido do .yml (link relativo ao cwd do MCP)
    refs = set(re.findall(r"\[ref=((?:f\d+)?e\d+)\]", snap))
    assert refs and refs <= set(idx._refs)
    texts = set(idx._refs.values())
    assert "generic: Finalizar compra" in texts and "generic: Aceitar os termos" in texts
    assert 'textbox "Pesquisar: produtos, serviços"' in texts and 'button "Pagar 10 €"' in texts
    assert idx.page_url == f"{site}/armadilhas.html"


@pytest.mark.slow
@pytest.mark.skipif(NPX is None, reason="npx não encontrado")
async def test_real_mcp_form_flow_through_the_gate(h: Any, chromium: Chromium, driver: Page, site: str,
                                                   tmp_settings: Any) -> None:
    """Critério da Fase 4 de ponta a ponta, sem o Claude: script → Sentinela → MCP 0.0.83 real → Chromium."""
    from talos.sentinel.policy import SnapshotIndex

    screens = tmp_settings.data_dir / "screens"
    h.sentinel.snapshots = SnapshotIndex(base_dir=tmp_settings.workspace_dir, allowed_dirs=[screens])  # = main.py
    browser = CDPBrowser(_settings(tmp_settings, chromium.endpoint), url_hint=lambda: h.sentinel.snapshots.page_url)
    h.app.browser = browser
    h.rt.pause_seconds = 60
    res: dict[str, Any] = {}
    try:
        async with mcp_session(chromium.endpoint, tmp_settings) as s:
            async def call(tool: str, args: dict[str, Any]) -> str:
                return _text(await s.call_tool(tool, args))

            for tool in ("browser_navigate", "browser_snapshot", "browser_type", "browser_click",
                         "browser_press_key", "browser_fill_form"):
                h.rt.external_tools[PW + tool] = functools.partial(call, tool)

            async def agent_script(agent: Any) -> str:
                await agent.call(PW + "browser_navigate", {"url": f"{site}/formulario.html"})
                res["known_after_nav"] = 'button "Submeter pedido"' in h.sentinel.snapshots._refs.values()
                snap = await agent.call(PW + "browser_snapshot", {})

                def ref(label: str) -> str:
                    return re.search(rf"{re.escape(label)} \[ref=((?:f\d+)?e\d+)\]", snap).group(1)

                res["email"] = await agent.call(PW + "browser_type", {
                    "element": "Email", "target": ref('textbox "Email"'), "text": "lucas@exemplo.pt"})
                res["senha"] = await agent.call(PW + "browser_type", {
                    "element": "campo de texto", "target": ref('textbox "Palavra-passe"'), "text": "hunter2"})
                res["cartao"] = await agent.call(PW + "browser_fill_form", {"fields": [
                    {"name": "Campo 6", "type": "textbox", "target": ref('textbox "Número do cartão"'),
                     "value": "4111111111111111"}]})
                res["nif"] = await agent.call("mcp__talos__vault_fill", VAULT_FILL_NIF)
                res["snap_after_fill"] = await agent.call(PW + "browser_snapshot", {})
                res["enter"] = await agent.call(PW + "browser_press_key", {"key": "NumpadEnter"})
                res["submit"] = await agent.call(PW + "browser_click", {
                    "element": "Ver detalhes", "target": ref('button "Submeter pedido"')})
                return "—"

            # a recusa do Enter retoma a sessão da tarefa (SPEC §7.2.A); essa retomada só responde
            h.rt.on(lambda r: r.task_id is not None and not r.resume_session_id, agent_script)
            h.rt.reply("—", when=lambda r: r.resume_session_id is not None)
            _task(h)

            async def check(a: PendingAction) -> None:
                if a.payload_json.get("tool") == PW + "browser_click":
                    res["hidden_before"] = await driver.locator("#sucesso").is_hidden()

            await asyncio.gather(h.drain(), _lucas(h, ["a", "r", "a"], check, timeout=120))
    finally:
        await browser.close()

    assert res["known_after_nav"]  # a Sentinela leu o snapshot que a ação gravou em data_dir/screens
    assert h.sentinel.snapshots.page_url == f"{site}/formulario.html"
    assert "Error" not in res["email"]
    assert res["senha"].startswith("TAKEOVER") and res["cartao"].startswith("TAKEOVER")
    assert res["nif"] == "Campo rótulo 'NIF' preenchido com dados.nif."
    # limitação conhecida (SPEC §7.4, SECURITY.md): depois do vault_fill, o snapshot mostra o valor ao modelo
    assert re.search(r'textbox "NIF" \[active\] \[ref=(f\d+)?e\d+\]:\n(\s+- .*\n)*?\s+- text: "123456789"',
                     res["snap_after_fill"])
    assert "não aprovou" in res["enter"]  # NumpadEnter submeteria; o Lucas recusou
    assert res["hidden_before"] is True
    assert "Error" not in res["submit"]
    await driver.locator("#sucesso").wait_for(state="visible", timeout=5000)
    sub = await driver.evaluate("window.submissoes")
    assert sub == [{"nome": "", "nif": NIF, "morada": "", "email": "lucas@exemplo.pt", "senha": "", "cartao": ""}]
    fill_action, enter_action, click_action = _actions(h)
    assert (fill_action.kind, enter_action.status, click_action.kind) == ("share_data", "rejected", "browser.submit")
    assert 'elemento real: button "Submeter pedido"' in click_action.preview_text
    assert Path(click_action.payload_json["screenshot"]).read_bytes()[:4] == b"\x89PNG"
