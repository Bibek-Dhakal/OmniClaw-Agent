import hashlib
import hmac

from omniclaw.browser import RISKY_ACTION, matching_domain
from omniclaw.channels.whatsapp import extract_messages, valid_signature
from omniclaw.config import Settings
from omniclaw.connectors import composio_needs_approval, nango_needs_approval


def test_settings_parse_csv_lists():
    settings = Settings(
        _env_file=None,
        telegram_bot_token="",
        telegram_allowed_user_ids="1, 2",
        browser_allowed_domains="Instagram.com, tinder.com",
    )
    assert settings.telegram_allowed_ids == {"1", "2"}
    assert settings.browser_allowed_domain_list == ["instagram.com", "tinder.com"]
    assert settings.telegram_enabled is False


def test_engine_profile_selection():
    settings = Settings(_env_file=None, agent_engine="hermes", hermes_api_base="http://h/v1")
    profile = settings.engine_profile()
    assert profile.model == "openai/hermes"
    assert profile.api_base == "http://h/v1"


def test_matching_domain_allows_subdomains_only():
    allowed = ["instagram.com"]
    assert matching_domain("https://www.instagram.com/direct/inbox", allowed) == "instagram.com"
    assert matching_domain("https://instagram.com", allowed) == "instagram.com"
    assert matching_domain("https://evilinstagram.com", allowed) is None
    assert matching_domain("https://example.com", allowed) is None


def test_risky_selectors_need_approval():
    assert RISKY_ACTION.search('role=button[name="Send"]')
    assert not RISKY_ACTION.search("text=Inbox")


def test_composio_read_tools_skip_approval():
    assert not composio_needs_approval({"tool_slug": "GMAIL_FETCH_EMAILS"})
    assert composio_needs_approval({"tool_slug": "GMAIL_SEND_EMAIL"})


def test_nango_only_get_skips_approval():
    assert not nango_needs_approval({"method": "get"})
    assert nango_needs_approval({"method": "POST"})


def test_whatsapp_signature():
    body = b'{"a": 1}'
    header = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert valid_signature("secret", body, header)
    assert not valid_signature("other", body, header)


def test_whatsapp_extract_messages():
    payload = {"entry": [{"changes": [{"value": {"messages": [{"id": "1"}, {"id": "2"}]}}]}, {}]}
    assert [m["id"] for m in extract_messages(payload)] == ["1", "2"]
