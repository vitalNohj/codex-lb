from __future__ import annotations

from app.db.models import DashboardSettings
from app.modules.claude_sidecar.quota import SidecarAuthQuota, parse_auth_files
from app.modules.cliproxy_accounts.summaries import build_cliproxy_provider_summaries


def _entry(**overrides) -> dict:
    entry = {
        "name": "credential.json",
        "auth_index": "1",
        "email": "person@example.com",
        "provider": "xai",
        "type": "xai",
        "status": "active",
        "disabled": False,
        "unavailable": False,
        "success": 1,
        "failed": 0,
    }
    entry.update(overrides)
    return entry


def _auth(**overrides) -> SidecarAuthQuota:
    values = {
        "name": "credential.json",
        "auth_index": "1",
        "email": "person@example.com",
        "provider": "xai",
        "status": "active",
        "status_message": None,
        "disabled": False,
        "unavailable": False,
        "quota_exceeded": False,
        "next_recover_at": None,
        "model_states": (),
        "success": 1,
        "failed": 0,
        "last_refresh": None,
    }
    values.update(overrides)
    return SidecarAuthQuota(**values)


def test_parse_auth_files_keeps_xai_and_surfaces_prefix_without_tokens():
    accounts = parse_auth_files(
        [
            _entry(
                prefix="acct2",
                access_token="cliproxy-test-access-token",
                refresh_token="cliproxy-test-refresh-token",
                id_token="cliproxy-test-id-token",
            ),
            _entry(name="claude.json", provider="claude", type="claude", email="claude@example.com", auth_index="2"),
        ],
        provider="xai",
    )

    assert len(accounts) == 1
    only = accounts[0]
    assert only.provider == "xai"
    assert only.email == "person@example.com"
    assert only.prefix == "acct2"
    rendered = repr(only)
    assert "cliproxy-test-access-token" not in rendered
    assert "cliproxy-test-refresh-token" not in rendered
    assert "cliproxy-test-id-token" not in rendered


def test_parse_auth_files_without_provider_keeps_every_entry():
    accounts = parse_auth_files(
        [
            _entry(),
            _entry(name="claude.json", provider="claude", type="claude", email="claude@example.com"),
            _entry(name="bare.json", provider=None, type=None, account_type="anthropic", email="anth@example.com"),
        ],
        provider=None,
    )

    assert {account.email for account in accounts} == {
        "person@example.com",
        "claude@example.com",
        "anth@example.com",
    }
    by_email = {account.email: account for account in accounts}
    assert by_email["anth@example.com"].provider == "claude"
    assert by_email["person@example.com"].prefix is None


def test_provider_summaries_skip_claude_and_group_xai():
    settings = DashboardSettings(id=1, claude_sidecar_base_url="http://127.0.0.1:8317")
    summaries = build_cliproxy_provider_summaries(
        settings,
        [
            _auth(provider="claude", email="claude@example.com", name="claude.json"),
            _auth(provider="xai", email="xai@example.com", name="xai.json", auth_index="9"),
            _auth(
                provider="xai",
                email="xai-b@example.com",
                name="xai-b.json",
                auth_index="8",
                disabled=True,
            ),
        ],
    )

    by_id = {summary.account_id: summary for summary in summaries}
    assert set(by_id) == {"cliproxy-xai"}
    xai = by_id["cliproxy-xai"]
    assert xai.synthetic is True
    assert xai.read_only is True
    assert xai.provider == "xai"
    assert xai.display_name == "CLIProxyAPI xAI"
    assert xai.status == "active"
    assert [row.email for row in xai.sidecar_auths] == ["xai@example.com", "xai-b@example.com"]
    assert xai.sidecar_auths[1].paused is True
