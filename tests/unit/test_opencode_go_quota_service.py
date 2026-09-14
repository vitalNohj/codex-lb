"""Service tests: freshness, stale fallback, cache isolation and honest failure.

The client and settings row are both injected fakes, so these exercise the real
service logic with no network, no database and no credentials.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.clients.opencode_go import (
    OpenCodeGoConfig,
    OpenCodeGoError,
    OpenCodeGoUnavailableError,
)
from app.modules.opencode_go.service import (
    OpenCodeGoQuotaCache,
    OpenCodeGoQuotaService,
)

pytestmark = pytest.mark.unit

_KEY_A = "sk-oc-go-aaaa-111111111111"
_KEY_B = "sk-oc-go-bbbb-222222222222"


def _usage_body(rolling_percent: float = 10.0) -> dict:
    return {
        "usage": {
            "rolling": {"status": "ok", "percent": rolling_percent, "resetsAt": "2026-09-14T17:00:00Z"},
            "weekly": {"status": "ok", "percent": 25, "resetsAt": "2026-09-20T00:00:00Z"},
            "monthly": {"status": "ok", "percent": 50, "resetsAt": "2026-10-01T00:00:00Z"},
        }
    }


class _FakeSettings:
    """A settings row carrying the backend lane's real column names.

    Deliberately spelled ``opencode_go_sidecar_*``: these tests exercise the
    backend's actual ``opencode_go_sidecar_config_from_settings`` loader, so a
    wrong spelling here would fail loudly rather than silently reporting
    ``not_configured`` against a configured integration.
    """

    def __init__(self, *, enabled: bool = True, key: str | None = _KEY_A) -> None:
        self.opencode_go_sidecar_enabled = enabled
        # Decryption happens inside the backend loader; the fake encryptor below
        # is the identity, so no real credential is involved.
        self.opencode_go_sidecar_api_key_encrypted = key.encode() if key else None
        self.opencode_go_sidecar_base_url = "https://opencode.ai/zen/go/v1"
        self.opencode_go_sidecar_model_prefixes_json = "[]"
        self.opencode_go_sidecar_full_models_json = "[]"
        self.opencode_go_sidecar_connect_timeout_seconds = 5.0
        self.opencode_go_sidecar_request_timeout_seconds = 10.0
        self.opencode_go_sidecar_models_cache_ttl_seconds = 60.0


class _FakeSettingsRepository:
    def __init__(self, settings: _FakeSettings) -> None:
        self.settings = settings

    async def get_or_create(self) -> _FakeSettings:
        return self.settings


class _FakeClient:
    """Records calls and replays a scripted result per call."""

    def __init__(self, config: OpenCodeGoConfig, *, header_builder=None) -> None:
        self.config = config
        # Captured so a test can assert the service wires in the backend's
        # header builder rather than inventing its own.
        self.header_builder = header_builder
        _FakeClient.instances.append(self)

    instances: list["_FakeClient"] = []
    results: list = []
    calls: list[str | None] = []
    delay: float = 0.0

    @classmethod
    def reset(cls, results: list | None = None) -> None:
        cls.instances = []
        cls.results = list(results or [])
        cls.calls = []
        cls.delay = 0.0

    async def fetch_usage(self):
        _FakeClient.calls.append(self.config.api_key)
        if _FakeClient.delay:
            await asyncio.sleep(_FakeClient.delay)
        result = _FakeClient.results.pop(0) if _FakeClient.results else _usage_body()
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeClient.reset()
    yield
    _FakeClient.reset()


@pytest.fixture(autouse=True)
def _identity_encryptor(monkeypatch):
    """Patch the decryptor the *backend loader* uses, not a local one."""

    class _Encryptor:
        def decrypt(self, blob: bytes) -> str:
            return blob.decode()

    monkeypatch.setattr(
        "app.modules.proxy.opencode_go_sidecar_dispatch.TokenEncryptor",
        _Encryptor,
    )


def _service(settings: _FakeSettings, *, cache: OpenCodeGoQuotaCache | None = None) -> OpenCodeGoQuotaService:
    return OpenCodeGoQuotaService(
        _FakeSettingsRepository(settings),
        cache=cache if cache is not None else OpenCodeGoQuotaCache(),
        client_factory=_FakeClient,
    )


@pytest.mark.asyncio
async def test_healthy_read_returns_three_windows_with_unknown_scope():
    response = await _service(_FakeSettings()).get_quota()

    assert response.status == "ok"
    assert response.stale is False
    assert [window.key for window in response.windows] == ["five_hour", "weekly", "monthly"]
    assert response.windows[0].percent_used == 10.0
    assert response.windows[0].upstream_key == "rolling"
    # Upstream supplies no model dimension, so no per-model claim is made.
    assert response.scope == "unknown"
    assert response.model_breakdown_available is False
    assert response.models == []
    assert response.checked_at is not None


@pytest.mark.asyncio
async def test_disabled_integration_never_contacts_upstream():
    response = await _service(_FakeSettings(enabled=False)).get_quota()

    assert response.status == "disabled"
    assert response.windows == []
    assert _FakeClient.calls == []


@pytest.mark.asyncio
async def test_unconfigured_key_never_contacts_upstream():
    response = await _service(_FakeSettings(key=None)).get_quota()

    assert response.status == "not_configured"
    assert response.windows == []
    assert _FakeClient.calls == []


@pytest.mark.asyncio
async def test_config_is_read_through_the_backends_published_loader():
    """The credential comes from the backend's loader, not a second spelling.

    Guards the exact defect that would otherwise ship silently: reading
    un-prefixed ``opencode_go_*`` columns while the backend stores
    ``opencode_go_sidecar_*`` reports ``not_configured`` for a fully configured
    integration, contradicting the Settings screen the operator is looking at.
    """
    settings = _FakeSettings()
    assert not hasattr(settings, "opencode_go_api_key_encrypted")

    response = await _service(settings).get_quota()

    assert response.status == "ok"
    assert _FakeClient.calls == [_KEY_A]


@pytest.mark.asyncio
async def test_upstream_headers_come_from_the_backends_builder():
    """One header builder for chat and this poll, so identity cannot drift."""
    from app.core.clients.opencode_go_sidecar import OPENCODE_GO_USER_AGENT

    service = _service(_FakeSettings())
    await service.get_quota()

    client = _FakeClient.instances[-1]
    headers = client.header_builder(client.config)
    assert headers["User-Agent"] == OPENCODE_GO_USER_AGENT
    assert headers["Authorization"] == f"Bearer {_KEY_A}"
    assert "Mozilla" not in headers["User-Agent"]


@pytest.mark.asyncio
async def test_undecryptable_key_is_not_sent_upstream(monkeypatch):
    class _BrokenEncryptor:
        def decrypt(self, blob: bytes) -> str:
            raise ValueError("bad ciphertext")

    monkeypatch.setattr(
        "app.modules.proxy.opencode_go_sidecar_dispatch.TokenEncryptor",
        _BrokenEncryptor,
    )

    response = await _service(_FakeSettings()).get_quota()

    assert response.status == "not_configured"
    assert _FakeClient.calls == []


@pytest.mark.asyncio
async def test_fresh_result_is_served_from_cache_without_a_second_request():
    cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
    service = _service(_FakeSettings(), cache=cache)

    first = await service.get_quota()
    second = await service.get_quota()

    assert len(_FakeClient.calls) == 1
    assert second.status == "ok"
    assert second.checked_at == first.checked_at


@pytest.mark.asyncio
async def test_expired_ttl_triggers_a_refresh():
    cache = OpenCodeGoQuotaCache(ttl_seconds=0.0)
    service = _service(_FakeSettings(), cache=cache)

    await service.get_quota()
    await service.get_quota()

    assert len(_FakeClient.calls) == 2


@pytest.mark.asyncio
async def test_concurrent_requests_are_coalesced_into_one_upstream_call():
    cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
    service = _service(_FakeSettings(), cache=cache)
    _FakeClient.delay = 0.05

    responses = await asyncio.gather(*(service.get_quota() for _ in range(8)))

    assert len(_FakeClient.calls) == 1
    assert {response.status for response in responses} == {"ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (OpenCodeGoError(401, "bad key"), "unauthorized"),
        (OpenCodeGoError(403, "forbidden"), "unauthorized"),
        (OpenCodeGoError(429, "slow down"), "rate_limited"),
        (OpenCodeGoError(500, "boom"), "unavailable"),
        (OpenCodeGoUnavailableError("connection refused"), "unavailable"),
    ],
)
async def test_upstream_errors_map_to_honest_statuses_with_no_windows(error, expected):
    service = _service(_FakeSettings())
    _FakeClient.reset([error])

    response = await service.get_quota()

    assert response.status == expected
    # Empty windows mean unknown. Never zero usage, never full quota.
    assert response.windows == []
    assert response.stale is False


@pytest.mark.asyncio
async def test_usage_endpoint_429_is_not_a_model_quota_signal():
    """A throttled usage read must not render as an exhausted subscription."""
    service = _service(_FakeSettings())
    _FakeClient.reset([OpenCodeGoError(429, "slow down")])

    response = await service.get_quota()

    assert response.status == "rate_limited"
    # No windows at all, so nothing can render as an exhausted model quota.
    assert response.windows == []
    assert response.message is not None


@pytest.mark.asyncio
async def test_unparseable_body_is_unavailable_not_empty_usage():
    service = _service(_FakeSettings())
    _FakeClient.reset([{"type": "error", "error": {"message": "nope"}}])

    response = await service.get_quota()

    assert response.status == "unavailable"
    assert response.windows == []


@pytest.mark.asyncio
async def test_timeout_is_unavailable():
    service = _service(_FakeSettings())
    _FakeClient.reset([asyncio.TimeoutError()])

    response = await service.get_quota()

    assert response.status == "unavailable"


@pytest.mark.asyncio
async def test_failed_refresh_returns_last_good_marked_stale():
    cache = OpenCodeGoQuotaCache(ttl_seconds=0.0, failure_ttl_seconds=0.0)
    service = _service(_FakeSettings(), cache=cache)
    _FakeClient.reset([_usage_body(42.0), OpenCodeGoUnavailableError("connection refused")])

    fresh = await service.get_quota()
    degraded = await service.get_quota()

    assert fresh.status == "ok"
    assert degraded.status == "stale"
    assert degraded.stale is True
    assert degraded.stale_reason == "connection refused"
    # The values survive, and their original timestamp survives with them, so
    # the dashboard can show how old they are.
    assert degraded.windows[0].percent_used == 42.0
    assert degraded.checked_at == fresh.checked_at
    assert degraded.refreshed_at >= fresh.refreshed_at


@pytest.mark.asyncio
async def test_stale_never_silently_erases_the_last_good_value():
    cache = OpenCodeGoQuotaCache(ttl_seconds=0.0, failure_ttl_seconds=0.0)
    service = _service(_FakeSettings(), cache=cache)
    _FakeClient.reset(
        [
            _usage_body(42.0),
            OpenCodeGoUnavailableError("one"),
            OpenCodeGoUnavailableError("two"),
        ]
    )

    await service.get_quota()
    await service.get_quota()
    third = await service.get_quota()

    assert third.status == "stale"
    assert third.windows[0].percent_used == 42.0


@pytest.mark.asyncio
async def test_unauthorized_drops_cached_values_instead_of_showing_them_stale():
    """A rejected key may have no relationship to the cached subscription."""
    cache = OpenCodeGoQuotaCache(ttl_seconds=0.0, failure_ttl_seconds=0.0)
    service = _service(_FakeSettings(), cache=cache)
    _FakeClient.reset([_usage_body(42.0), OpenCodeGoError(401, "bad key")])

    await service.get_quota()
    response = await service.get_quota()

    assert response.status == "unauthorized"
    assert response.stale is False
    assert response.windows == []


@pytest.mark.asyncio
async def test_a_changed_key_never_sees_the_previous_subscriptions_quota():
    cache = OpenCodeGoQuotaCache(ttl_seconds=300.0)
    settings = _FakeSettings(key=_KEY_A)
    service = _service(settings, cache=cache)
    _FakeClient.reset([_usage_body(11.0), _usage_body(77.0)])

    first = await service.get_quota()
    assert first.windows[0].percent_used == 11.0

    # Operator swaps the subscription key. The TTL has not expired, so only
    # config-keyed isolation can prevent a cross-subscription read.
    settings.opencode_go_sidecar_api_key_encrypted = _KEY_B.encode()
    second = await service.get_quota()

    assert second.windows[0].percent_used == 77.0
    assert _FakeClient.calls == [_KEY_A, _KEY_B]


@pytest.mark.asyncio
async def test_a_changed_key_does_not_inherit_the_old_key_as_stale():
    cache = OpenCodeGoQuotaCache(ttl_seconds=0.0, failure_ttl_seconds=0.0)
    settings = _FakeSettings(key=_KEY_A)
    service = _service(settings, cache=cache)
    _FakeClient.reset([_usage_body(11.0), OpenCodeGoUnavailableError("down")])

    await service.get_quota()
    settings.opencode_go_sidecar_api_key_encrypted = _KEY_B.encode()
    response = await service.get_quota()

    # The new key has no last-good value of its own, so there is nothing
    # legitimate to show as stale.
    assert response.status == "unavailable"
    assert response.windows == []


@pytest.mark.asyncio
async def test_disabling_after_a_successful_read_stops_all_upstream_traffic():
    cache = OpenCodeGoQuotaCache(ttl_seconds=0.0)
    settings = _FakeSettings()
    service = _service(settings, cache=cache)

    await service.get_quota()
    settings.opencode_go_sidecar_enabled = False
    response = await service.get_quota()

    assert response.status == "disabled"
    assert response.windows == []
    assert len(_FakeClient.calls) == 1


@pytest.mark.asyncio
async def test_failure_ttl_prevents_repaying_the_timeout_on_every_load():
    cache = OpenCodeGoQuotaCache(ttl_seconds=0.0, failure_ttl_seconds=300.0)
    service = _service(_FakeSettings(), cache=cache)
    _FakeClient.reset([OpenCodeGoUnavailableError("down"), _usage_body()])

    first = await service.get_quota()
    second = await service.get_quota()

    assert first.status == "unavailable"
    assert second.status == "unavailable"
    assert len(_FakeClient.calls) == 1


@pytest.mark.asyncio
async def test_partial_window_payload_yields_a_partial_list():
    service = _service(_FakeSettings())
    _FakeClient.reset(
        [{"usage": {"rolling": {"status": "ok", "percent": 5, "resetsAt": "2026-09-14T17:00:00Z"}, "weekly": None}}]
    )

    response = await service.get_quota()

    assert response.status == "ok"
    assert [window.key for window in response.windows] == ["five_hour"]


@pytest.mark.asyncio
async def test_rate_limited_window_is_reported_as_exhausted():
    service = _service(_FakeSettings())
    _FakeClient.reset(
        [
            {
                "usage": {
                    "rolling": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-09-14T17:00:00Z"},
                    "weekly": {"status": "ok", "percent": 30, "resetsAt": "2026-09-20T00:00:00Z"},
                    "monthly": {"status": "ok", "percent": 40, "resetsAt": "2026-10-01T00:00:00Z"},
                }
            }
        ]
    )

    response = await service.get_quota()

    assert response.windows[0].status == "rate_limited"
    assert response.windows[0].limit_reached is True
    assert response.windows[1].limit_reached is False


@pytest.mark.asyncio
async def test_error_messages_never_carry_the_credential():
    service = _service(_FakeSettings())
    _FakeClient.reset([OpenCodeGoError(500, f"upstream echoed Bearer {_KEY_A}")])

    response = await service.get_quota()

    serialized = response.model_dump_json()
    assert _KEY_A not in serialized
