import os

from talos.doctor import FAIL, OK, Doctor, all_green, render


async def test_doctor_offline(tmp_settings, db):
    tmp_settings.vault_key_file.write_bytes(b"k")
    os.chmod(tmp_settings.vault_key_file, 0o600)
    env = {"CLAUDE_CODE_OAUTH_TOKEN": "tok"}
    checks = await Doctor(tmp_settings, db, live=False, environ=env).run()
    by = {c.name: c for c in checks}
    assert by["autenticação Claude"].status == OK and "subscription" in by["autenticação Claude"].detail
    assert by["chave do cofre"].status == OK
    assert all_green(checks)
    assert "✅" in render(checks)


async def test_doctor_flags_api_key_and_loose_perms(tmp_settings, db):
    tmp_settings.vault_key_file.write_bytes(b"k")
    os.chmod(tmp_settings.vault_key_file, 0o644)
    checks = await Doctor(tmp_settings, db, live=False,
                          environ={"CLAUDE_CODE_OAUTH_TOKEN": "t", "ANTHROPIC_API_KEY": "sk"}).run()
    by = {c.name: c for c in checks}
    assert by["autenticação Claude"].status == FAIL
    assert by["chave do cofre"].status == FAIL
    assert not all_green(checks)


async def test_doctor_monitor_stale(tmp_settings, db):
    from datetime import timedelta

    from talos.clock import utcnow

    db.set_state("monitor", {"last_tick": (utcnow() - timedelta(minutes=30)).isoformat()})
    checks = await Doctor(tmp_settings, db, live=False, environ={"CLAUDE_CODE_OAUTH_TOKEN": "t"}).run()
    assert {c.name: c for c in checks}["monitor"].status == FAIL
