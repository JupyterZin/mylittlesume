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
