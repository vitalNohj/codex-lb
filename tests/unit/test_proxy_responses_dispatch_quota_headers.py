"""Every sidecar Responses dispatcher reads quota headers through the privacy check."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import app.modules.proxy.api as proxy_api_module
from app.modules.proxy.sidecar_routing import SidecarRoutingDecision

pytestmark = pytest.mark.unit


class _HeadersRead(Exception):
    def __init__(self, headers: object) -> None:
        super().__init__("headers read")
        self.headers = headers


async def _resolved(value: Any) -> Any:
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dispatcher", "provider"),
    [
        ("_opencode_go_responses_dispatch_or_none", "opencode_go"),
        ("_omniroute_responses_dispatch_or_none", "omniroute"),
        ("_chat_provider_responses_dispatch_or_none", "claude"),
    ],
)
async def test_sidecar_responses_dispatch_uses_privacy_checked_quota_headers(
    monkeypatch: pytest.MonkeyPatch,
    dispatcher: str,
    provider: str,
) -> None:
    api_key = SimpleNamespace(enforced_model=None)
    seen: list[object] = []

    async def unchecked_headers() -> dict[str, str]:
        pytest.fail("a Responses dispatcher read pool quota headers without the API-key privacy check")

    async def checked_headers(_context: object, key: object) -> dict[str, str]:
        seen.append(key)
        return {"x-checked": "1"}

    def stop_after_headers(*args: object, **_kwargs: object) -> object:
        raise _HeadersRead(args[-1])

    async def stop_at_client(_provider: str) -> object:
        raise _HeadersRead(None)

    monkeypatch.setattr(proxy_api_module, "_rate_limit_headers_for_request", checked_headers)
    monkeypatch.setattr(proxy_api_module, "_enabled_sidecar_routing_entries", lambda: _resolved(()))
    monkeypatch.setattr(
        proxy_api_module,
        "resolve_sidecar_route",
        lambda model, _entries: SidecarRoutingDecision(provider=provider, wire_model=model),
    )
    monkeypatch.setattr(proxy_api_module, "validate_model_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(proxy_api_module, "load_opencode_go_sidecar_config", lambda: _resolved(object()))
    monkeypatch.setattr(proxy_api_module, "load_omniroute_sidecar_config", lambda: _resolved(object()))
    monkeypatch.setattr(proxy_api_module, "omniroute_enabled", lambda: True)
    monkeypatch.setattr(proxy_api_module, "_responses_chat_translation_or_error", stop_after_headers)
    monkeypatch.setattr(proxy_api_module, "_responses_chat_provider_client", stop_at_client)

    context = SimpleNamespace(service=SimpleNamespace(rate_limit_headers=unchecked_headers))
    payload = SimpleNamespace(model="some-model", service_tier=None)

    with pytest.raises(_HeadersRead):
        await getattr(proxy_api_module, dispatcher)(object(), payload, context, api_key)

    assert seen == [api_key]
