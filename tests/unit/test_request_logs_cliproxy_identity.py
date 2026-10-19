from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import pytest

from app.db.models import DashboardSettings
from app.modules.claude_sidecar.quota import SidecarAuthQuota, SidecarQuotaSnapshot, snapshot_to_json
from app.modules.cliproxy_accounts.api_keys import ApiKeyRouteRow
from app.modules.request_logs.cliproxy_identity import (
    CliproxyIdentityResolver,
    api_key_display_name,
    api_key_identity_labels,
    snapshot_identity_labels,
)


def _auth(name: str, auth_index: str | None, email: str | None, provider: str = "claude") -> SidecarAuthQuota:
    return SidecarAuthQuota(
        name=name,
        auth_index=auth_index,
        email=email,
        status="active",
        status_message=None,
        disabled=False,
        unavailable=False,
        quota_exceeded=False,
        next_recover_at=None,
        model_states=(),
        success=0,
        failed=0,
        last_refresh=None,
        provider=provider,
    )


def _snapshot(*accounts: SidecarAuthQuota) -> SidecarQuotaSnapshot:
    return SidecarQuotaSnapshot(
        checked_at=datetime(2026, 10, 19, tzinfo=timezone.utc),
        status="healthy",
        message=None,
        accounts=accounts,
    )


def _row(
    kind: str,
    index: int,
    name: str,
    auth_index: str | None,
    route_identity: str | None = None,
) -> ApiKeyRouteRow:
    return ApiKeyRouteRow(
        kind=kind,
        index=index,
        name=name,
        prefix=None,
        disabled=False,
        models=(),
        auth_index=auth_index,
        weight=None,
        priority=None,
        route_identity=route_identity or auth_index or f"local-{kind}-{index}",
    )


def _settings(snapshot: SidecarQuotaSnapshot | None, *, management: bool = True) -> DashboardSettings:
    settings = DashboardSettings()
    settings.claude_sidecar_quota_state_json = snapshot_to_json(snapshot) if snapshot is not None else None
    settings.claude_sidecar_base_url = "http://cliproxy.test" if management else ""
    settings.claude_sidecar_management_key_encrypted = b"key" if management else None
    return settings


class _Loader:
    def __init__(self, rows: Iterable[ApiKeyRouteRow] = (), *, error: Exception | None = None) -> None:
        self.rows = list(rows)
        self.error = error
        self.calls = 0

    async def __call__(self, settings: DashboardSettings) -> list[ApiKeyRouteRow]:
        del settings
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.rows


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_snapshot_labels_prefer_email_then_auth_file_name() -> None:
    labels = snapshot_identity_labels(
        _snapshot(
            _auth("claude-a.json", "ca51a540a688", "alice@example.com"),
            _auth("grok-b.json", "c954787e3fa69", None, provider="xai"),
            _auth("no-index.json", None, "orphan@example.com"),
        )
    )

    assert labels == {"ca51a540a688": "alice@example.com", "c954787e3fa69": "grok-b.json"}


def test_snapshot_labels_handle_missing_snapshot() -> None:
    assert snapshot_identity_labels(None) == {}


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_row("openai-compatibility", 0, "OpenRouter", "a1"), "OpenRouter"),
        (_row("openai-compatibility", 2, "openai-compatibility:2", "a2"), "OpenAI-compatible API key 3"),
        (_row("claude", 0, "team#2", "a3"), "team#2"),
        (_row("claude", 1, "claude:1", "a4"), "Claude API key 2"),
        (_row("gemini", 0, "gemini:0", "a5"), "Gemini API key 1"),
    ],
)
def test_api_key_display_name(row: ApiKeyRouteRow, expected: str) -> None:
    assert api_key_display_name(row) == expected


def test_api_key_labels_cover_reported_and_local_identity() -> None:
    labels = api_key_identity_labels(
        [
            _row("claude", 0, "team#1", "reported-idx"),
            _row("openai-compatibility", 0, "OpenRouter", None, route_identity="local-digest"),
        ]
    )

    assert labels == {"reported-idx": "team#1", "local-digest": "OpenRouter"}


@pytest.mark.asyncio
async def test_resolver_uses_snapshot_email_without_reading_api_keys() -> None:
    loader = _Loader()
    resolver = CliproxyIdentityResolver(load_api_key_rows=loader)
    settings = _settings(_snapshot(_auth("claude-a.json", "ca51a540a688", "alice@example.com")))

    labels = await resolver.labels_for(settings, ["ca51a540a688", "ca51a540a688", None])

    assert labels == {"ca51a540a688": "alice@example.com"}
    assert loader.calls == 0


@pytest.mark.asyncio
async def test_resolver_names_api_key_accounts_and_skips_unknown_indexes() -> None:
    loader = _Loader([_row("claude", 0, "claude:0", "key-idx")])
    resolver = CliproxyIdentityResolver(load_api_key_rows=loader)
    settings = _settings(_snapshot(_auth("claude-a.json", "oauth-idx", "alice@example.com")))

    labels = await resolver.labels_for(settings, ["oauth-idx", "key-idx", "gone-idx"])

    assert labels == {"oauth-idx": "alice@example.com", "key-idx": "Claude API key 1"}
    assert loader.calls == 1


@pytest.mark.asyncio
async def test_resolver_caches_api_key_labels_and_failures_until_ttl() -> None:
    clock = _Clock()
    loader = _Loader(error=RuntimeError("cliproxy down"))
    resolver = CliproxyIdentityResolver(load_api_key_rows=loader, ttl_seconds=60.0, clock=clock)
    settings = _settings(None)

    assert await resolver.labels_for(settings, ["key-idx"]) == {}
    assert await resolver.labels_for(settings, ["key-idx"]) == {}
    assert loader.calls == 1

    clock.now += 61.0
    loader.error = None
    loader.rows = [_row("openai-compatibility", 0, "OpenRouter", "key-idx")]
    assert await resolver.labels_for(settings, ["key-idx"]) == {"key-idx": "OpenRouter"}
    assert loader.calls == 2


@pytest.mark.asyncio
async def test_resolver_skips_api_key_read_without_management_access() -> None:
    loader = _Loader([_row("claude", 0, "claude:0", "key-idx")])
    resolver = CliproxyIdentityResolver(load_api_key_rows=loader)

    labels = await resolver.labels_for(_settings(None, management=False), ["key-idx"])

    assert labels == {}
    assert loader.calls == 0


@pytest.mark.asyncio
async def test_resolver_returns_nothing_for_legacy_rows_without_auth_index() -> None:
    loader = _Loader()
    resolver = CliproxyIdentityResolver(load_api_key_rows=loader)

    assert await resolver.labels_for(_settings(None), [None, "", "  "]) == {}
    assert loader.calls == 0
