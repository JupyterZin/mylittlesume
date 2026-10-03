import io
import json

import pytest

from talos.logging import REDACTOR, configure_logging, get_logger
from talos.vault.placeholders import PlaceholderError, find_forbidden, find_keys, resolve
from talos.vault.store import VaultError


def test_vault_roundtrip_and_kinds(vault):
    assert vault.get("dados.nif") == "123456789"
    keys = {k["key"]: k["kind"] for k in vault.list_keys()}
    assert keys["dados.nif"] == "dado_pessoal"
    vault.set("google.token", "ya29.secret-token-value")
    assert {k["key"]: k["kind"] for k in vault.list_keys()}["google.token"] == "segredo"
    with pytest.raises(VaultError):
        vault.set("Bad Key", "x")


def test_ciphertext_not_plain(vault, db):
    from talos.db.models import VaultItem

    with db.session() as s:
        item = s.get(VaultItem, "dados.nif")
    assert b"123456789" not in item.ciphertext


def test_placeholders():
    text = "Morada: {{dados.morada}}, NIF {{ dados.nif }}, de novo {{dados.nif}}"
    assert find_keys(text) == ["dados.morada", "dados.nif"]
    out = resolve(text, {"dados.morada": "Rua X", "dados.nif": "123"})
    assert out == "Morada: Rua X, NIF 123, de novo 123"
    with pytest.raises(PlaceholderError):
        resolve("{{dados.iban}}", {})
    assert find_forbidden("{{google.token}}") == ["google.token"]
    with pytest.raises(PlaceholderError):
        resolve("{{google.token}}", {"google.token": "x"})


def test_vault_values_never_in_logs(vault, capsys):
    configure_logging(json=True)
    log = get_logger("t")
    log.info("enviando", body="NIF 123456789 morada Rua das Flores 12, 1200-195 Lisboa", nested={"x": ["912345678"]})
    out = capsys.readouterr().out
    assert "123456789" not in out and "Rua das Flores" not in out and "912345678" not in out
    rec = json.loads(out.strip().splitlines()[-1])
    assert "[REDACTED:dados.nif]" in rec["body"]


def test_stdlib_logging_redacted(vault, capsys):
    import logging

    configure_logging(json=True)
    logging.getLogger("lib").warning("valor %s", "123456789")
    assert "123456789" not in capsys.readouterr().out
    assert REDACTOR.redact_text("x 123456789") == "x [REDACTED:dados.nif]"
    _ = io  # noqa
