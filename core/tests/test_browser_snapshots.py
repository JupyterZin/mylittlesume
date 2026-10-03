"""SnapshotIndex e regras do navegador contra texto REAL do @playwright/mcp 0.0.83 (ADR-007).

Os textos abaixo foram capturados do MCP real (stdio, `--cdp-endpoint`, Chromium 141) a navegar em
infra/testpages/formulario.html e armadilhas.html. O teste `slow` em test_browser.py repete a captura
ao vivo; estes ficam na suíte rápida como regressão do formato.
"""

import re
from types import SimpleNamespace

import pytest

from talos.runtime.gate import ToolGate
from talos.sentinel.policy import Sentinel, SnapshotIndex, ToolCall

PW = "mcp__playwright__"
ALL = ["mcp__talos__*", "mcp__playwright__*"]

# browser_navigate: a ação NÃO traz o snapshot inline, só um link para o .yml no --output-dir
NAV_FORM_RESPONSE = """### Ran Playwright code
```js
await page.goto('http://127.0.0.1:9000/formulario.html');
```
### Page
- Page URL: http://127.0.0.1:9000/formulario.html
- Page Title: Empresa Teste · Pedido de ligação
### Snapshot
- [Snapshot](../mcpout/page-2026-10-03T14-53-18-985Z.yml)
### Events
- New console entries: ../mcpout/console-2026-10-03T14-53-18-850Z.log#L1"""

# conteúdo do .yml (igual ao do browser_snapshot explícito, sem o cabeçalho)
FORM_YAML = """- main [ref=e2]:
  - heading "Pedido de ligação de gás" [level=1] [ref=e3]
  - paragraph [ref=e4]: Empresa Teste, S.A. · formulário de demonstração (nada é enviado para fora desta página).
  - generic [ref=e5]:
    - group "Dados do titular" [ref=e6]:
      - generic [ref=e8]:
        - generic [ref=e9]: Nome
        - textbox "Nome" [ref=e10]:
          - /placeholder: Nome completo
      - generic [ref=e11]:
        - generic [ref=e12]: NIF
        - textbox "NIF" [ref=e13]:
          - /placeholder: Número de identificação fiscal
      - generic [ref=e14]:
        - generic [ref=e15]: Morada
        - textbox "Morada" [ref=e16]:
          - /placeholder: Rua, número, código postal e localidade
      - generic [ref=e17]:
        - generic [ref=e18]: Email
        - textbox "Email" [ref=e19]:
          - /placeholder: nome@exemplo.pt
    - group "Área de cliente e pagamento" [ref=e20]:
      - generic [ref=e22]:
        - generic [ref=e23]: Palavra-passe
        - textbox "Palavra-passe" [ref=e24]:
          - /placeholder: Palavra-passe da área de cliente
      - generic [ref=e25]:
        - generic [ref=e26]: Número do cartão
        - textbox "Número do cartão" [ref=e27]:
          - /placeholder: 0000 0000 0000 0000
        - generic [ref=e28]: Só para a caução; pode deixar em branco.
    - button "Submeter pedido" [ref=e29] [cursor=pointer]
"""

# browser_snapshot explícito: YAML inline
SNAP_FORM = f"""### Page
- Page URL: http://127.0.0.1:9000/formulario.html
- Page Title: Empresa Teste · Pedido de ligação
### Snapshot
```yaml
{FORM_YAML}```"""

# segunda página da mesma sessão do MCP: refs com prefixo de frame (f1e3), linha entre aspas, iframe
SNAP_TRAPS = """### Page
- Page URL: http://127.0.0.1:9000/armadilhas.html
- Page Title: Armadilhas · Sentinela
### Snapshot
```yaml
- generic [ref=f1e1]:
  - heading "Página com armadilhas" [level=1] [ref=f1e2]
  - generic [ref=f1e3] [cursor=pointer]: Finalizar compra
  - generic [ref=f1e4] [cursor=pointer]: Aceitar os termos
  - link "Pagar agora" [ref=f1e5] [cursor=pointer]:
    - /url: "#ver"
  - button "Confirmar contrato" [ref=f1e6]
  - button "Encomendar" [ref=f1e7]: 🛒
  - generic [ref=f1e8]:
    - textbox "Palavra-passe" [ref=f1e9]
    - textbox "Chave de acesso" [ref=f1e10]
    - 'textbox "Pesquisar: produtos, serviços" [ref=f1e11]'
  - iframe [ref=f1e12]:
    - generic [ref=f2e1]:
      - generic [ref=f2e2]:
        - text: Número do cartão
        - textbox "Número do cartão" [ref=f2e3]
      - button "Pagar 10 €" [ref=f2e4]
  - status
```"""

TABS_LIST = "### Result\n- 0: (current) [Empresa Teste · Pedido de ligação](http://127.0.0.1:9000/formulario.html)"


def _refs_in(text: str) -> set[str]:
    return set(re.findall(r"\[ref=((?:f\d+)?e\d+)\]", text))


@pytest.fixture
def sentinel(tmp_settings):
    s = Sentinel(workspace_dir=tmp_settings.workspace_dir)
    s.snapshots.ingest(SNAP_FORM)
    s.snapshots.ingest(SNAP_TRAPS)
    return s


def test_every_real_snapshot_line_is_indexed():
    for text in (SNAP_FORM, SNAP_TRAPS):
        idx = SnapshotIndex()
        idx.ingest(text)
        assert set(idx._refs) == _refs_in(text)


def test_real_element_texts():
    idx = SnapshotIndex()
    idx.ingest(SNAP_FORM)
    idx.ingest(SNAP_TRAPS)
    assert idx.lookup("e29") == 'button "Submeter pedido"'
    assert idx.lookup("e13") == 'textbox "NIF"'
    assert idx.lookup("e3") == 'heading "Pedido de ligação de gás"'
    assert idx.lookup("e4").startswith("paragraph: Empresa Teste, S.A.")
    assert idx.lookup("f1e3") == "generic: Finalizar compra"  # texto depois de ":" (antes perdia-se)
    assert idx.lookup("f1e4") == "generic: Aceitar os termos"
    assert idx.lookup("f1e7") == 'button "Encomendar": 🛒'
    assert idx.lookup("f1e11") == 'textbox "Pesquisar: produtos, serviços"'  # linha YAML entre aspas
    assert idx.lookup("f2e3") == 'textbox "Número do cartão"'  # dentro do iframe
    assert "Pagar 10 €" in idx.lookup("f1e12")  # elemento sem nome herda o texto dos filhos
    assert "placeholder" not in idx.lookup("e16")  # "código postal" no placeholder não conta
    assert idx.page_url == "http://127.0.0.1:9000/armadilhas.html"


DISGUISED = [
    # (ref real, descrição enganosa que o agente escreveu) → tem de pedir aprovação pelo texto real
    ("e29", "Ver detalhes"),
    ("f1e3", "Ver mais"),
    ("f1e4", "Fechar aviso"),
    ("f1e5", "Ver mais"),
    ("f1e6", "Ler contrato"),
    ("f1e7", "Ícone do carrinho"),
    ("f2e4", "Fechar"),
]


@pytest.mark.parametrize("ref,element", DISGUISED)
async def test_disguised_final_clicks_ask(sentinel, ref, element):
    d = await sentinel.evaluate(ToolCall(PW + "browser_click", {"element": element, "target": ref}), ALL)
    assert d.action == "ask" and d.rule_id == "browser-final-click", d


@pytest.mark.parametrize("tool,inp,expected", [
    (PW + "browser_type", {"element": "Nome", "target": "e10", "text": "Lucas"}, "allow"),
    (PW + "browser_type", {"element": "Morada", "target": "e16", "text": "Rua X"}, "allow"),
    (PW + "browser_type", {"element": "Pesquisa", "target": "f1e11", "text": "gás"}, "allow"),
    (PW + "browser_click", {"element": "Campo Nome", "target": "e10"}, "allow"),
    # senha e cartão pelo texto REAL do elemento, mesmo com descrição neutra
    (PW + "browser_type", {"element": "campo de texto", "target": "e24", "text": "x"}, "takeover"),
    (PW + "browser_type", {"element": "campo de texto", "target": "f1e9", "text": "x"}, "takeover"),
    (PW + "browser_type", {"element": "campo do iframe", "target": "f2e3", "text": "4111"}, "takeover"),
    (PW + "browser_fill_form", {"fields": [{"name": "Campo 6", "type": "textbox", "target": "e27", "value": "1"}]},
     "takeover"),
    # refs do snapshot de outra frame/página que a Sentinela nunca viu
    (PW + "browser_click", {"element": "Nome", "target": "f9e10"}, "ask"),
])
async def test_real_snapshot_decisions(sentinel, tool, inp, expected):
    d = await sentinel.evaluate(ToolCall(tool, inp), ALL)
    assert d.action == expected, d


async def test_action_snapshot_file_is_read_only_from_mcp_output_dir(tmp_path):
    ws, out = tmp_path / "workspace", tmp_path / "mcpout"  # o link é relativo ao cwd do MCP (= workspace)
    ws.mkdir()
    out.mkdir()
    (out / "page-2026-10-03T14-53-18-985Z.yml").write_text(FORM_YAML, encoding="utf-8")

    s = Sentinel(workspace_dir=ws, snapshot_dirs=[out])
    s.snapshots.ingest(NAV_FORM_RESPONSE)
    assert s.snapshots.lookup("e29") == 'button "Submeter pedido"'
    assert s.snapshots.page_url == "http://127.0.0.1:9000/formulario.html"
    d = await s.evaluate(ToolCall(PW + "browser_click", {"element": "Ver mais", "target": "e29"}), ALL)
    assert d.rule_id == "browser-final-click"

    # sem o diretório autorizado, o ficheiro não é lido: ref desconhecido → ask
    s2 = Sentinel(workspace_dir=ws)
    s2.snapshots.ingest(NAV_FORM_RESPONSE)
    assert s2.snapshots.lookup("e29") is None
    d = await s2.evaluate(ToolCall(PW + "browser_click", {"element": "Ver mais", "target": "e29"}), ALL)
    assert d.action == "ask" and d.rule_id == "browser-unknown-element"

    # links para fora do --output-dir são ignorados (o texto da página não escolhe que ficheiro ler)
    (tmp_path / "fora.yml").write_text('- button "Ver mais" [ref=e77]\n', encoding="utf-8")
    s.snapshots.ingest("- [Snapshot](../fora.yml)\n- [Snapshot](/etc/hostname.yml)")
    assert s.snapshots.lookup("e77") is None


def test_json_wrapped_response_from_post_tool_use_hook(tmp_settings):
    """O hook PostToolUse pode entregar a resposta do MCP como lista de blocos; o gate faz json.dumps."""
    s = Sentinel(workspace_dir=tmp_settings.workspace_dir)
    ToolGate.post(SimpleNamespace(sentinel=s), PW + "browser_snapshot", [{"type": "text", "text": SNAP_TRAPS}])
    assert s.snapshots.lookup("f1e3") == "generic: Finalizar compra"
    assert s.snapshots.lookup("f1e11") == 'textbox "Pesquisar: produtos, serviços"'
    assert set(s.snapshots._refs) == _refs_in(SNAP_TRAPS)
    assert s.snapshots.page_url == "http://127.0.0.1:9000/armadilhas.html"


def test_page_url_follows_mcp_reports():
    idx = SnapshotIndex()
    idx.ingest(NAV_FORM_RESPONSE)
    assert idx.page_url == "http://127.0.0.1:9000/formulario.html"
    idx.ingest(SNAP_TRAPS)
    assert idx.page_url == "http://127.0.0.1:9000/armadilhas.html"
    idx.ingest(TABS_LIST)  # lista de abas não tem "- Page URL:": não mexe
    assert idx.page_url == "http://127.0.0.1:9000/armadilhas.html"
    # texto da página dentro do YAML não consegue fingir o cabeçalho (está indentado / tem papel)
    idx.ingest('- generic [ref=e1]:\n  - text: "- Page URL: https://evil.example/"\n')
    assert idx.page_url == "http://127.0.0.1:9000/armadilhas.html"


@pytest.mark.parametrize("key,expected", [
    # confirmado no MCP real: estes submetem o formulário de teste
    ("Enter", "ask"), ("NumpadEnter", "ask"), ("Shift+Enter", "ask"), (" ", "ask"), ("Space", "ask"),
    ("Control+Enter", "ask"), ("Return", "ask"),
    ("ArrowDown", "allow"), ("Tab", "allow"), ("Escape", "allow"), ("PageDown", "allow"),
])
async def test_press_key_that_can_submit_asks(tmp_settings, key, expected):
    s = Sentinel(workspace_dir=tmp_settings.workspace_dir)
    assert (await s.evaluate(ToolCall(PW + "browser_press_key", {"key": key}), ALL)).action == expected


async def test_drop_and_page_tools(tmp_settings):
    s = Sentinel(workspace_dir=tmp_settings.workspace_dir)
    s.snapshots.ingest(SNAP_FORM)
    drop = ToolCall(PW + "browser_drop", {"element": "Área de anexos", "target": "e5", "paths": ["/tmp/x.pdf"]})
    assert (await s.evaluate(drop, ALL)).rule_id == "browser-upload"
    # ferramenta registada pela página via WebMCP (o MCP expõe-na como webmcp_<nome>)
    page_tool = ToolCall(PW + "webmcp_checkout", {"confirm": True})
    assert (await s.evaluate(page_tool, ALL)).action == "deny"


# depois do vault_fill (capturado no MCP real): o campo focado ganha [active] e o valor aparece como filho
AFTER_FILL = """    - group "Dados do titular" [ref=f1e6]:
      - generic [ref=f1e11]:
        - generic [ref=f1e12]: NIF
        - textbox "NIF" [active] [ref=f1e13]:
          - /placeholder: Número de identificação fiscal
          - text: "123456789"
      - generic [ref=f1e17]:
        - generic [ref=f1e18]: Email
        - textbox "Email" [ref=f1e19]:
          - /placeholder: nome@exemplo.pt
          - text: lucas@exemplo.pt
"""


async def test_after_fill_snapshot_attributes_and_values(tmp_settings):
    s = Sentinel(workspace_dir=tmp_settings.workspace_dir)
    s.snapshots.ingest(AFTER_FILL)
    assert s.snapshots.lookup("f1e13") == 'textbox "NIF"'  # [active] não atrapalha; o valor não entra no nome
    assert s.snapshots.lookup("f1e19") == 'textbox "Email"'
    d = await s.evaluate(ToolCall(PW + "browser_click", {"element": "Campo NIF", "target": "f1e13"}), ALL)
    assert d.action == "allow"
