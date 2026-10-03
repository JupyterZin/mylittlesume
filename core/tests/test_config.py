import pytest

from talos.config import ForbiddenEnvError, Settings, check_auth_env, enforce_auth_env


def test_subscription_rejects_api_key():
    env = {"CLAUDE_CODE_OAUTH_TOKEN": "x", "ANTHROPIC_API_KEY": "sk-ant"}
    assert any("ANTHROPIC_API_KEY" in p for p in check_auth_env(env, "subscription"))
    with pytest.raises(ForbiddenEnvError):
        enforce_auth_env(env, "subscription")


def test_subscription_rejects_auth_token():
    with pytest.raises(ForbiddenEnvError):
        enforce_auth_env({"ANTHROPIC_AUTH_TOKEN": "t"}, "subscription")


def test_subscription_ok_and_missing_token_is_warning_only():
    assert check_auth_env({"CLAUDE_CODE_OAUTH_TOKEN": "x"}, "subscription") == []
    enforce_auth_env({}, "subscription")  # token ausente não aborta o processo, só o doctor
    assert check_auth_env({}, "subscription")


def test_api_key_mode_is_plan_b():
    assert check_auth_env({"ANTHROPIC_API_KEY": "k"}, "api_key") == []
    assert check_auth_env({}, "api_key")


def test_inbox_address_and_quiet_window():
    s = Settings(gmail_address="lucas@gmail.com", agent_inbox_tag="talos", quiet_hours="22:30-08:00")
    assert s.agent_inbox_address == "lucas+talos@gmail.com"
    start, end = s.quiet_window
    assert (start.hour, start.minute, end.hour) == (22, 30, 8)


def test_classifier_on_off():
    assert Settings(sentinel_classifier="off").sentinel_classifier is False
    assert Settings(sentinel_classifier="on").sentinel_classifier is True


def test_env_example_is_systemd_safe_and_loads(monkeypatch):
    """O systemd não aceita comentários inline; valores vazios usam o padrão."""
    from pathlib import Path

    env = Path(__file__).resolve().parents[2] / ".env.example"
    for line in env.read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            assert "#" not in value, f"comentário inline em {key}"
            monkeypatch.setenv(key, value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s = Settings()
    assert s.run_limit == 30 and s.claude_plan == "pro" and s.organize_time == "09:00"


def test_write_env_value_updates_in_place(tmp_path):
    import os
    import stat

    from talos.cli import write_env_value

    f = tmp_path / "secrets.env"
    f.write_text("# comentário\nCLAUDE_CODE_OAUTH_TOKEN=\nAGENT_NAME=Talos\n")
    os.chmod(f, 0o600)
    write_env_value(str(f), "CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-abc")
    write_env_value(str(f), "TYPESAFE_API_KEY", "apikey_x")
    text = f.read_text()
    assert "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-abc\n" in text and text.count("CLAUDE_CODE_OAUTH_TOKEN") == 1
    assert "TYPESAFE_API_KEY=apikey_x" in text and "# comentário" in text and "AGENT_NAME=Talos" in text
    assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_secrets_set_refuses_api_key(tmp_path):
    from typer.testing import CliRunner

    from talos.cli import app

    r = CliRunner().invoke(app, ["secrets", "set", "ANTHROPIC_API_KEY", "--file", str(tmp_path / "s.env")])
    assert r.exit_code == 1 and "proibida" in r.output


def test_token_cleanup_and_validation():
    from talos.cli import clean_token, token_problem

    broken = "sk-ant-oat01-AAAAbbbbCCCCddddEEEE ffffGGGGhhhhIIIIjjjjKKKKllllMMMMnnnnOOOOppppQQQQ\nrrrr"
    fixed = clean_token(broken)
    assert " " not in fixed and "\n" not in fixed and fixed.startswith("sk-ant-oat01-")
    assert token_problem("CLAUDE_CODE_OAUTH_TOKEN", fixed) is None
    assert token_problem("CLAUDE_CODE_OAUTH_TOKEN", "ckSrsEpfg") is not None  # só a cauda do token
    assert token_problem("TYPESAFE_API_KEY", "apikey_123") is None
    assert token_problem("TELEGRAM_BOT_TOKEN", "abc") is not None


def test_google_client_paste(tmp_path, monkeypatch):
    import json

    from typer.testing import CliRunner

    from talos.cli import app

    dest = tmp_path / "gc.json"
    good = json.dumps({"installed": {"client_id": "x.apps.googleusercontent.com", "client_secret": "s"}})
    r = CliRunner().invoke(app, ["secrets", "google-client", "--file", str(dest)], input=good + "\n")
    assert r.exit_code == 0 and json.loads(dest.read_text())["installed"]["client_id"].startswith("x.")
    r = CliRunner().invoke(app, ["secrets", "google-client", "--file", str(dest)],
                           input=json.dumps({"web": {}}) + "\n")
    assert r.exit_code == 1 and "Desktop" in r.output
