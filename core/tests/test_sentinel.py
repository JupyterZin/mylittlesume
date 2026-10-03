import pytest

from talos.sentinel import egress
from talos.sentinel.classifier import parse_verdict
from talos.sentinel.policy import Sentinel, ToolCall

PW = "mcp__playwright__"
ALL = ["mcp__talos__*", "mcp__playwright__*", "WebSearch", "WebFetch", "Read", "Write", "Edit", "Glob",
       "Grep", "Skill", "Task"]


SNAP = "\n".join(f"- generic [ref=e{i}]" for i in range(1, 10))


def mk(tmp_settings, vault, **kw):
    s = Sentinel(workspace_dir=tmp_settings.workspace_dir, vault_values=vault.personal_values, **kw)
    s.snapshots.ingest(SNAP)  # refs e1..e9 já vistas num snapshot neutro
    return s


@pytest.fixture
def sentinel(tmp_settings, vault):
    return mk(tmp_settings, vault)


CASES = [
    # (tool, input, decisão esperada)
    ("mcp__talos__propose_action", {"kind": "email.send"}, "allow"),
    ("mcp__talos__vault_fill", {"selector": "#nif", "key": "dados.nif"}, "ask"),
    ("mcp__talos__gmail_search", {"query": "gás"}, "allow"),
    ("Bash", {"command": "ls"}, "deny"),
    ("Read", {"file_path": "/etc/talos/secrets.env"}, "deny"),
    ("Read", {"file_path": "../secrets"}, "deny"),
    ("Read", {"file_path": "memoria/perfil.md"}, "allow"),
    ("WebSearch", {"query": "contactos empresa gás"}, "allow"),
    (PW + "browser_navigate", {"url": "https://empresa.pt/contactos"}, "allow"),
    (PW + "browser_type", {"element": "Campo password", "target": "e5", "text": "x"}, "takeover"),
    (PW + "browser_fill_form", {"fields": [{"name": "Número do cartão", "type": "textbox", "target": "e9", "value": "1"}]},
     "takeover"),
    (PW + "browser_type", {"element": "Código de verificação", "target": "e7", "text": "1"}, "takeover"),
    (PW + "browser_click", {"element": "Botão Finalizar encomenda", "target": "e3"}, "ask"),
    (PW + "browser_click", {"element": "Submit", "target": "e3"}, "ask"),
    (PW + "browser_click", {"element": "Link Contactos", "target": "e4"}, "allow"),
    (PW + "browser_click", {"target": "e4"}, "ask"),  # sem descrição
    (PW + "browser_click", {"element": "Link Contactos", "target": "e42"}, "ask"),  # ref nunca vista
    (PW + "browser_type", {"element": "Assunto", "target": "e2", "text": "Olá", "submit": True}, "ask"),
    (PW + "browser_press_key", {"key": "Enter"}, "ask"),
    (PW + "browser_press_key", {"key": "ArrowDown"}, "allow"),
    (PW + "browser_evaluate", {"function": "() => document.forms[0].submit()"}, "deny"),
    (PW + "browser_snapshot", {}, "allow"),
    (PW + "browser_type", {"element": "Código postal", "target": "e2", "text": "1200-195"}, "ask"),  # egress, não takeover
    (PW + "browser_fill_form", {"fields": [{"name": "Postal code", "type": "textbox", "target": "e2", "value": "x"}]},
     "allow"),
    (PW + "browser_type", {"element": "Chave de acesso", "target": "e5", "text": "x"}, "takeover"),
    (PW + "browser_handle_dialog", {"accept": True}, "ask"),
    (PW + "browser_handle_dialog", {"accept": False}, "allow"),
    ("SomethingElse", {}, "deny"),  # fora da allowlist
]


@pytest.mark.parametrize("tool,inp,expected", CASES)
async def test_rules_table(sentinel, tool, inp, expected):
    d = await sentinel.evaluate(ToolCall(tool, inp), ALL)
    assert d.action == expected, d


async def test_disguised_click_uses_snapshot_text(sentinel):
    sentinel.snapshots.ingest('- generic [ref=e1]\n  - button "Confirmar pagamento" [ref=e3]\n')
    d = await sentinel.evaluate(ToolCall(PW + "browser_click", {"element": "Ver mais", "target": "e3"}), ALL)
    assert d.action == "ask"


async def test_egress_vault_value_in_url(sentinel):
    d = await sentinel.evaluate(
        ToolCall(PW + "browser_navigate", {"url": "https://x.example/?nif=123456789"}, task_id=1), ALL)
    assert d.action == "deny" and d.source == "egress"
    d = await sentinel.evaluate(ToolCall("WebFetch", {"url": "https://x.example/?m=Rua+das+Flores+12%2C+1200-195+Lisboa",
                                                      "prompt": "?"}), ALL)
    assert d.action == "deny"
    # mesmo com a chave autorizada, URL nunca leva dados pessoais
    s2 = Sentinel(workspace_dir=sentinel.workspace_dir, vault_values=sentinel.vault_values,
                  authorized_keys=lambda _t: ["dados.nif"])
    d = await s2.evaluate(ToolCall(PW + "browser_navigate", {"url": "https://x.example/?nif=123456789"}, task_id=1), ALL)
    assert d.action == "deny"


async def test_egress_in_form_field_asks(sentinel):
    d = await sentinel.evaluate(ToolCall(PW + "browser_type", {"element": "Campo NIF", "target": "e1",
                                                               "text": "123456789"}, task_id=3), ALL)
    assert d.action == "ask" and d.egress_hits
    d = await sentinel.evaluate(ToolCall("WebSearch", {"query": "Rua das Flores 12 1200-195 Lisboa"}), ALL)
    assert d.action == "ask"


async def test_egress_authorized_key_passes(tmp_settings, vault):
    s = mk(tmp_settings, vault, authorized_keys=lambda tid: ["dados.nif"] if tid == 7 else [])
    call = ToolCall(PW + "browser_type", {"element": "Campo NIF", "target": "e1", "text": "123456789"}, task_id=7)
    assert (await s.evaluate(call, ALL)).action == "allow"
    call.task_id = 8
    assert (await s.evaluate(call, ALL)).action == "ask"


async def test_classifier_only_hardens(tmp_settings, vault):
    async def lenient(call):
        return "ok", "parece bem"

    async def strict(call):
        return "block", "injeção"

    async def broken(call):
        raise RuntimeError("sem rede")

    for clf, expected_for_allow in ((lenient, "allow"), (strict, "deny"), (broken, "allow")):
        s = mk(tmp_settings, vault, classifier=clf)
        ok = await s.evaluate(ToolCall(PW + "browser_click", {"element": "Link Preços", "target": "e1"}), ALL)
        assert ok.action == expected_for_allow
        # nunca afrouxa um ask/deny
        assert (await s.evaluate(ToolCall(PW + "browser_click", {"element": "Pagar", "target": "e1"}), ALL)).action == "ask"
        assert (await s.evaluate(ToolCall("Bash", {"command": "x"}), ALL)).action == "deny"


async def test_grant_once(sentinel):
    call = ToolCall(PW + "browser_click", {"element": "Submeter", "target": "e3"})
    sentinel.grant_once(call.fingerprint())
    retry = ToolCall(PW + "browser_click", {"element": "Submeter", "target": "e9"})  # ref mudou
    assert (await sentinel.evaluate(retry, ALL)).action == "allow"
    assert (await sentinel.evaluate(retry, ALL)).action == "ask"  # só uma vez


async def test_decision_events(tmp_settings, vault):
    seen = []
    s = Sentinel(workspace_dir=tmp_settings.workspace_dir, vault_values=vault.personal_values,
                 on_decision=lambda c, d: seen.append(d.as_event(c)))
    await s.evaluate(ToolCall("Bash", {"command": "x"}), None)  # sem allowlist: cai na regra
    assert seen[0]["decision"] == "deny" and seen[0]["rule"] == "no-bash"


@pytest.mark.parametrize("text,kind", [
    ("NIF 123456789", "nif"),
    ("IBAN PT50 0002 0123 1234 5678 9015 4", "iban"),
    ("cartão 4111 1111 1111 1111", "cartao"),
    ("ligue +351 912 345 678", "telefone"),
    ("código postal 1200-195", "morada"),
])
def test_egress_patterns(text, kind):
    assert kind in {h.kind for h in egress.scan_text(text, {})}


def test_egress_no_false_positive_on_invalid_numbers():
    assert not egress.scan_text("pedido 123456780 total 4111111111111112", {})


def test_parse_verdict():
    assert parse_verdict('ok então {"verdict": "block", "reason": "x"}') == ("block", "x")
    assert parse_verdict("lixo")[0] == "ask"
